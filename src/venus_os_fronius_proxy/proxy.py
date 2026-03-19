"""Proxy orchestration: server + poller wiring, staleness-aware slave context.

Wires together the Modbus TCP server, background poller, register cache,
and inverter plugin into a running proxy. Venus OS reads from the register
cache (never passthrough to SE30K). When cache goes stale (30s without
successful poll), returns Modbus exception 0x04 to Venus OS.
"""
from __future__ import annotations

import asyncio
import logging
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusServerContext,
)
from pymodbus.server import ModbusTcpServer

import structlog

from venus_os_fronius_proxy.connection import (
    ConnectionManager,
    ConnectionState,
    build_night_mode_inverter_registers,
)
from venus_os_fronius_proxy.control import (
    ControlState,
    MODEL_123_START,
    WMAXLIMPCT_OFFSET,
    WMAXLIM_ENA_OFFSET,
    validate_wmaxlimpct,
)
from venus_os_fronius_proxy.plugin import InverterPlugin
from venus_os_fronius_proxy.sunspec_models import (
    build_initial_registers,
    apply_common_translation,
    DATABLOCK_START,
    PROXY_UNIT_ID,
)
from venus_os_fronius_proxy.register_cache import RegisterCache

logger = logging.getLogger(__name__)
control_log = structlog.get_logger(component="control")

# Polling interval in seconds (locked decision from CONTEXT.md)
POLL_INTERVAL = 1.0

# Cache staleness timeout (locked decision from CONTEXT.md)
STALENESS_TIMEOUT = 30.0

# Datablock addresses for cache updates (DATABLOCK_START-relative)
# Common Model: 67 registers starting at datablock address 40003 (40002 + 1 offset)
COMMON_CACHE_ADDR = 40003
# Inverter Model: 52 registers starting at datablock address 40070 (40069 + 1 offset)
INVERTER_CACHE_ADDR = 40070


class StalenessAwareSlaveContext(ModbusDeviceContext):
    """ModbusDeviceContext that returns Modbus exception 0x04 when cache is stale.

    Per locked decision: after 30s without a successful poll, start returning
    Modbus errors to Venus OS instead of serving stale data.

    Overrides getValues() to check RegisterCache.is_stale before reading.
    When stale, raises ModbusIOException with exception_code=0x04
    (SLAVE_DEVICE_FAILURE), which pymodbus translates into a proper
    Modbus exception response to the client.

    Overrides async_setValues() to intercept writes to Model 123 registers
    for power control forwarding to the inverter.
    """

    def __init__(
        self,
        cache: RegisterCache,
        plugin: InverterPlugin | None = None,
        control_state: ControlState | None = None,
        shared_ctx: dict | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._cache = cache
        self._plugin = plugin
        self._control = control_state
        self._shared_ctx = shared_ctx

    def getValues(self, fc_as_hex, address, count=1):
        """Override to intercept reads when cache is stale.

        When cache.is_stale is True, raise an exception that pymodbus
        will convert to Modbus exception code 0x04 (SLAVE_DEVICE_FAILURE).
        This tells Venus OS the device is unavailable rather than
        silently serving outdated data.
        """
        if self._cache.is_stale:
            # Raising any exception here causes pymodbus request handler to
            # return ExceptionResponse with SLAVE_FAILURE (0x04) to the client.
            # See pymodbus ServerRequestHandler.handle_request() except clause.
            raise Exception("Cache stale: no successful poll within timeout")
        return super().getValues(fc_as_hex, address, count)

    async def async_setValues(self, fc_as_hex, address, values):
        """Intercept writes to Model 123 registers for power control.

        pymodbus passes the protocol address directly (e.g. 40154 for
        register 40154). The +1 adjustment happens inside setValues(),
        not in the address passed to async_setValues.

        For Model 123 writes, validates and forwards to the inverter plugin.
        Other writes fall through to normal datablock storage.
        """
        # Address from pymodbus is the SunSpec address directly
        abs_addr = address

        if (
            self._control is not None
            and self._plugin is not None
            and self._control.is_model_123_address(abs_addr, len(values))
        ):
            await self._handle_control_write(abs_addr, values)
            return

        # Default: store in datablock via normal setValues
        self.setValues(fc_as_hex, address, values)

    async def _handle_control_write(self, abs_addr: int, values: list[int]) -> None:
        """Process a write to Model 123 control registers.

        Validates values, updates local state, and forwards to inverter
        via plugin.write_power_limit. Every control command is logged at
        INFO level with value and result (per locked CONTEXT.md decision).
        """
        offset = abs_addr - MODEL_123_START

        # Handle WMaxLimPct write (offset 5, register 40154)
        if offset == WMAXLIMPCT_OFFSET and len(values) >= 1:
            error = validate_wmaxlimpct(values[0])
            if error:
                control_log.info(
                    "power_limit_write",
                    wmaxlimpct=values[0], result="rejected", reason=error,
                )
                raise Exception(f"ILLEGAL_VALUE: {error}")

            old_raw = self._control.wmaxlimpct_raw
            # Apply power clamp (min/max bounds set via webapp)
            # Also enforce minimum 1% — 0% shuts down SE30K (~10s restart)
            floor = max(self._control.clamp_min_pct, 1)
            ceiling = self._control.clamp_max_pct
            clamped = max(floor, min(ceiling, values[0]))
            self._control.update_wmaxlimpct(clamped)
            # Implicitly enable when a limit value is written (Venus OS
            # writes WMaxLimPct without setting WMaxLim_Ena separately)
            self._control.update_wmaxlim_ena(1)

            if self._control.is_locked:
                control_log.info(
                    "power_limit_write",
                    wmaxlimpct=values[0], result="locked",
                    detail="Venus OS write accepted, not forwarded to inverter",
                )
                self._update_model_123_readback()
                return

            # Skip SE30K write if value unchanged (Venus OS refreshes every 5s)
            if clamped == old_raw and self._control.is_enabled:
                self._update_model_123_readback()
                return

            result = await self._plugin.write_power_limit(
                True, self._control.wmaxlimpct_float,
            )
            if not result.success:
                control_log.info(
                    "power_limit_write",
                    wmaxlimpct=values[0], enabled=True,
                    result="failed", error=result.error,
                )
                raise Exception(f"Write failed: {result.error}")
            control_log.info(
                "power_limit_write",
                wmaxlimpct=values[0],
                limit_pct=self._control.wmaxlimpct_float,
                enabled=True, result="ok",
            )

            # Venus OS source tracking + persist for restart recovery
            self._control.set_from_venus_os()
            self._control.save_last_limit()
            if self._shared_ctx and "override_log" in self._shared_ctx:
                self._shared_ctx["override_log"].append(
                    "venus_os", "set", self._control.wmaxlimpct_float,
                )

            # Update local readback registers
            self._update_model_123_readback()
            return

        # Handle WMaxLim_Ena write (offset 9, register 40158)
        if offset == WMAXLIM_ENA_OFFSET and len(values) >= 1:
            ena_value = values[0]
            if ena_value not in (0, 1):
                control_log.info(
                    "power_limit_write",
                    wmaxlim_ena=ena_value, result="rejected",
                    reason="must be 0 or 1",
                )
                raise Exception(
                    f"ILLEGAL_VALUE: WMaxLim_Ena must be 0 or 1, got {ena_value}"
                )

            self._control.update_wmaxlim_ena(ena_value)

            if self._control.is_locked:
                control_log.info(
                    "power_limit_write",
                    wmaxlim_ena=ena_value, result="locked",
                    detail="Venus OS write accepted, not forwarded to inverter",
                )
                self._update_model_123_readback()
                return

            result = await self._plugin.write_power_limit(
                self._control.is_enabled, self._control.wmaxlimpct_float,
            )
            if not result.success:
                control_log.info(
                    "power_limit_write",
                    wmaxlim_ena=ena_value, result="failed", error=result.error,
                )
                raise Exception(f"Write failed: {result.error}")
            control_log.info(
                "power_limit_write",
                wmaxlim_ena=ena_value,
                enabled=self._control.is_enabled,
                limit_pct=self._control.wmaxlimpct_float,
                result="ok",
            )

            # Venus OS source tracking (Phase 7)
            self._control.set_from_venus_os()
            ena_action = "enable" if self._control.is_enabled else "disable"
            if self._shared_ctx and "override_log" in self._shared_ctx:
                self._shared_ctx["override_log"].append(
                    "venus_os", ena_action, self._control.wmaxlimpct_float,
                )

            self._update_model_123_readback()
            return

        # Other Model 123 registers: store locally only (no SE30K forwarding)
        # Datablock address = SunSpec address + 1 (pymodbus internal offset)
        self.store["h"].setValues(abs_addr + 1, values)

    def _update_model_123_readback(self) -> None:
        """Write current ControlState as Model 123 readback to the datablock."""
        readback = self._control.get_model_123_readback()
        # Model 123 DID is at 40149, datablock address = 40149 + 1 offset = 40150
        self.store["h"].setValues(40150, readback)


async def _poll_loop(
    plugin: InverterPlugin,
    cache: RegisterCache,
    conn_mgr: ConnectionManager | None = None,
    control_state: ControlState | None = None,
    poll_interval: float = POLL_INTERVAL,
    poll_counter: dict | None = None,
    shared_ctx: dict | None = None,
) -> None:
    """Background polling loop with reconnection and night mode.

    State machine integration:
    - CONNECTED: normal polling at poll_interval
    - RECONNECTING: attempt reconnect with exponential backoff (5s-60s)
    - NIGHT_MODE: inject synthetic zero-power registers, continue reconnect attempts

    Args:
        conn_mgr: Optional ConnectionManager. If None, creates one internally.
        control_state: Optional ControlState for power limit restore after reconnect.
    """
    if conn_mgr is None:
        conn_mgr = ConnectionManager(poll_interval=poll_interval)

    if poll_counter is None:
        poll_counter = {"success": 0, "total": 0}

    last_energy_wh = 0  # Track last known energy for night mode preservation

    while True:
        try:
            result = await plugin.poll()
            poll_counter["total"] += 1
            if result.success:
                poll_counter["success"] += 1
                conn_mgr.on_poll_success()

                # Store raw SE30K poll data for webapp register viewer (source column)
                if shared_ctx is not None:
                    shared_ctx["last_se_poll"] = {
                        "common_registers": result.common_registers,
                        "inverter_registers": result.inverter_registers,
                    }

                # Preserve energy reading from inverter registers
                if len(result.inverter_registers) > 27:
                    last_energy_wh = (
                        (result.inverter_registers[26] << 16)
                        | result.inverter_registers[27]
                    )

                translated_common = apply_common_translation(result.common_registers)
                cache.update(COMMON_CACHE_ADDR, translated_common)
                cache.update(INVERTER_CACHE_ADDR, result.inverter_registers)

                if shared_ctx is not None and "dashboard_collector" in shared_ctx:
                    shared_ctx["dashboard_collector"].collect(
                        cache, shared_ctx.get("control_state"),
                        conn_mgr=conn_mgr, poll_counter=poll_counter,
                        override_log=shared_ctx.get("override_log"),
                        shared_ctx=shared_ctx,
                    )

                # Broadcast latest snapshot to all WebSocket clients
                if shared_ctx is not None and "webapp" in shared_ctx:
                    from venus_os_fronius_proxy.webapp import broadcast_to_clients
                    snapshot = shared_ctx["dashboard_collector"].last_snapshot
                    if snapshot is not None:
                        await broadcast_to_clients(shared_ctx["webapp"], snapshot)

                # Restore power limit after reconnection from night mode
                if conn_mgr.reconnected_from_night and control_state is not None and control_state.is_enabled:
                    try:
                        await plugin.write_power_limit(True, control_state.wmaxlimpct_float)
                        logger.info("Restored power limit after reconnect: %.1f%%", control_state.wmaxlimpct_float)
                    except Exception as e:
                        logger.error("Failed to restore power limit: %s", e)

                logger.debug("Poll successful, cache updated")
            else:
                new_state = conn_mgr.on_poll_failure()
                logger.warning("Poll failed: %s (state=%s)", result.error, new_state.value)

                if new_state == ConnectionState.NIGHT_MODE:
                    # Inject synthetic zero-power registers
                    night_regs = build_night_mode_inverter_registers(last_energy_wh)
                    cache.update(INVERTER_CACHE_ADDR, night_regs)
                    # Force cache to appear fresh so staleness doesn't override night mode
                    cache.last_successful_poll = time.monotonic()
                    cache._has_been_updated = True

                # Try to reconnect the plugin
                if new_state in (ConnectionState.RECONNECTING, ConnectionState.NIGHT_MODE):
                    try:
                        await plugin.close()
                    except Exception:
                        pass
                    try:
                        await plugin.connect()
                        logger.info("Reconnected to inverter")
                    except Exception as e:
                        logger.debug("Reconnect attempt failed: %s", e)

        except Exception as e:
            poll_counter["total"] += 1
            conn_mgr.on_poll_failure()
            logger.error("Unexpected poll error: %s", e)

        await asyncio.sleep(conn_mgr.sleep_duration)


async def _start_server(server: ModbusTcpServer) -> None:
    """Start the Modbus TCP server with fallback for API differences.

    Tries server.serve_forever() first (pymodbus 3.x standard).
    Falls back to StartAsyncTcpServer if serve_forever() is not available.
    """
    if hasattr(server, "serve_forever"):
        await server.serve_forever()
    else:
        from pymodbus.server import StartAsyncTcpServer
        logger.info("serve_forever() not found, using StartAsyncTcpServer fallback")
        await StartAsyncTcpServer(
            context=server.context,
            address=server.address,
        )


async def run_proxy(
    plugin: InverterPlugin,
    host: str = "0.0.0.0",
    port: int = 502,
    poll_interval: float = POLL_INTERVAL,
    shared_ctx: dict | None = None,
) -> None:
    """Start the Fronius proxy server and polling loop.

    1. Initializes the datablock with static SunSpec model chain
    2. Connects the inverter plugin
    3. Starts ModbusTcpServer on host:port with unit ID 126
    4. Starts background poller that updates the cache every poll_interval seconds
    5. Runs both concurrently until interrupted

    Args:
        plugin: InverterPlugin implementation (e.g., SolarEdgePlugin)
        host: Server bind address (default "0.0.0.0")
        port: Server bind port (default 502, standard Modbus TCP)
        poll_interval: Seconds between polls (default 1.0, use smaller values in tests)
    """
    # Build initial register datablock with static SunSpec values
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)

    # Create register cache with staleness tracking
    cache = RegisterCache(datablock, staleness_timeout=STALENESS_TIMEOUT)

    # Apply plugin-specific Model 120 to the datablock
    model_120_regs = plugin.get_model_120_registers()
    # Model 120 starts at datablock address 40122 (40121 + 1 offset)
    datablock.setValues(40122, model_120_regs)

    # Create control state for Model 123 write path
    control_state = ControlState()

    # Create staleness-aware Modbus server context with unit ID 126
    slave_ctx = StalenessAwareSlaveContext(
        cache=cache, plugin=plugin, control_state=control_state,
        shared_ctx=shared_ctx, hr=datablock,
    )
    server_ctx = ModbusServerContext(
        devices={PROXY_UNIT_ID: slave_ctx},
        single=False,
    )

    # Connect to the inverter
    await plugin.connect()
    logger.info("Inverter plugin connected")

    # Create and start the Modbus TCP server
    server = ModbusTcpServer(
        context=server_ctx,
        address=(host, port),
    )
    logger.info(
        "Starting Modbus TCP server on %s:%d (unit ID %d)",
        host, port, PROXY_UNIT_ID,
    )

    # Create connection manager for reconnection and night mode
    conn_mgr = ConnectionManager(poll_interval=poll_interval)

    # Poll counter for health heartbeat
    poll_counter = {"success": 0, "total": 0}

    # Populate shared context for external consumers (e.g. health heartbeat)
    if shared_ctx is not None:
        shared_ctx["cache"] = cache
        shared_ctx["conn_mgr"] = conn_mgr
        shared_ctx["control_state"] = control_state
        shared_ctx["poll_counter"] = poll_counter
        shared_ctx["last_se_poll"] = None

    try:
        await asyncio.gather(
            _start_server(server),
            _poll_loop(plugin, cache, conn_mgr, control_state, poll_interval=poll_interval, poll_counter=poll_counter, shared_ctx=shared_ctx),
        )
    finally:
        await plugin.close()
        logger.info("Proxy shutdown complete")
