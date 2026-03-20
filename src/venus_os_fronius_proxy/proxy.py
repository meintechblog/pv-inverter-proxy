"""Proxy orchestration: Modbus TCP server + staleness-aware slave context.

Provides the Modbus TCP server infrastructure that Venus OS reads from.
The register cache is populated by AggregationLayer (Phase 22+), not by
a built-in poll loop. When cache goes stale (30s without successful poll),
returns Modbus exception 0x04 to Venus OS.

The old _poll_loop and run_proxy functions have been replaced by DeviceRegistry
(per-device poll loops) + AggregationLayer (SunSpec aggregation) + run_modbus_server
(server-only setup without polling).
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

from venus_os_fronius_proxy.control import (
    ControlState,
    MODEL_123_START,
    WMAXLIMPCT_OFFSET,
    WMAXLIM_ENA_OFFSET,
    validate_wmaxlimpct,
)
from venus_os_fronius_proxy.sunspec_models import (
    build_initial_registers,
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
        plugin: object | None = None,
        control_state: ControlState | None = None,
        app_ctx: object | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._cache = cache
        self._plugin = plugin
        self._control = control_state
        self._app_ctx = app_ctx

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

        # Flag Venus OS detection on any Model 123 write (one-shot)
        if (
            self._app_ctx is not None
            and self._control is not None
            and self._control.is_model_123_address(abs_addr, len(values))
            and not self._app_ctx.venus_os_detected
        ):
            self._app_ctx.venus_os_detected = True
            self._app_ctx.venus_os_detected_ts = time.time()
            # Promote tracked client IP as Venus OS IP
            candidate_ip = self._app_ctx._last_modbus_client_ip
            if candidate_ip:
                self._app_ctx.venus_os_client_ip = candidate_ip
                logger.info("Venus OS detected: first Modbus write to Model 123 from %s", candidate_ip)
            else:
                logger.info("Venus OS detected: first Modbus write to Model 123")

        if (
            self._control is not None
            and self._control.is_model_123_address(abs_addr, len(values))
        ):
            if self._plugin is not None:
                await self._handle_control_write(abs_addr, values)
            else:
                # No plugin available -- accept write locally but log warning
                # Power limit forwarding deferred to Phase 23 (PowerLimitDistributor)
                control_log.warning(
                    "power_limit_forwarding_not_available_until_phase_23",
                    address=abs_addr,
                    values=values,
                )
                self._handle_local_control_write(abs_addr, values)
            return

        # Default: store in datablock via normal setValues
        self.setValues(fc_as_hex, address, values)

    def _handle_local_control_write(self, abs_addr: int, values: list[int]) -> None:
        """Accept Model 123 write locally without forwarding to a plugin.

        Updates ControlState and readback registers. Used when no single
        plugin is available for power limit forwarding (multi-device mode,
        Phase 23 will add PowerLimitDistributor).
        """
        offset = abs_addr - MODEL_123_START

        if offset == WMAXLIMPCT_OFFSET and len(values) >= 1:
            error = validate_wmaxlimpct(values[0])
            if error:
                control_log.info(
                    "power_limit_write",
                    wmaxlimpct=values[0], result="rejected", reason=error,
                )
                raise Exception(f"ILLEGAL_VALUE: {error}")

            floor = max(self._control.clamp_min_pct, 1)
            ceiling = self._control.clamp_max_pct
            clamped = max(floor, min(ceiling, values[0]))
            self._control.update_wmaxlimpct(clamped)
            self._control.update_wmaxlim_ena(1)
            self._control.set_from_venus_os()
            self._control.save_last_limit()
            if self._app_ctx and self._app_ctx.override_log is not None:
                self._app_ctx.override_log.append(
                    "venus_os", "set", self._control.wmaxlimpct_float,
                )
            self._update_model_123_readback()
            return

        if offset == WMAXLIM_ENA_OFFSET and len(values) >= 1:
            ena_value = values[0]
            if ena_value not in (0, 1):
                raise Exception(
                    f"ILLEGAL_VALUE: WMaxLim_Ena must be 0 or 1, got {ena_value}"
                )
            self._control.update_wmaxlim_ena(ena_value)
            self._control.set_from_venus_os()
            if self._app_ctx and self._app_ctx.override_log is not None:
                ena_action = "enable" if self._control.is_enabled else "disable"
                self._app_ctx.override_log.append(
                    "venus_os", ena_action, self._control.wmaxlimpct_float,
                )
            self._update_model_123_readback()
            return

        # Other Model 123 registers: store locally
        self.store["h"].setValues(abs_addr + 1, values)

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
            # Also enforce minimum 1% -- 0% shuts down SE30K (~10s restart)
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
            if self._app_ctx and self._app_ctx.override_log is not None:
                self._app_ctx.override_log.append(
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
            if self._app_ctx and self._app_ctx.override_log is not None:
                self._app_ctx.override_log.append(
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


async def run_modbus_server(
    host: str = "0.0.0.0",
    port: int = 502,
    app_ctx: object | None = None,
) -> tuple:
    """Set up the Modbus TCP server infrastructure (no polling).

    Creates datablock, RegisterCache, StalenessAwareSlaveContext, and
    ModbusTcpServer. Does NOT start poll loops -- that is handled by
    DeviceRegistry. Does NOT connect any plugin -- plugins are per-device.

    Returns:
        Tuple of (cache, control_state, server, server_task) so the caller
        can manage the server lifecycle and pass cache to AggregationLayer.
    """
    # Build initial register datablock with static SunSpec values
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)

    # Create register cache with staleness tracking
    cache = RegisterCache(datablock, staleness_timeout=STALENESS_TIMEOUT)

    # Create control state for Model 123 write path
    control_state = ControlState()

    # Create staleness-aware Modbus server context with unit ID 126
    # plugin=None -- power limit forwarding deferred to Phase 23
    slave_ctx = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=control_state,
        app_ctx=app_ctx, hr=datablock,
    )
    server_ctx = ModbusServerContext(
        devices={PROXY_UNIT_ID: slave_ctx},
        single=False,
    )

    # Create the Modbus TCP server
    server = ModbusTcpServer(
        context=server_ctx,
        address=(host, port),
    )

    # Patch server to track most recent Modbus TCP client IP
    _orig_callback_new_connection = server.callback_new_connection

    def _patched_callback_new_connection():
        handler = _orig_callback_new_connection()
        _orig_connection_made = handler.connection_made

        def _capture_ip_connection_made(transport):
            if app_ctx is not None:
                try:
                    peername = transport.get_extra_info("peername")
                    if peername:
                        # Store as candidate -- only promoted to venus_os_client_ip
                        # when Model 123 write is detected in async_setValues
                        app_ctx._last_modbus_client_ip = peername[0]
                except Exception:
                    pass
            return _orig_connection_made(transport)

        handler.connection_made = _capture_ip_connection_made
        return handler

    server.callback_new_connection = _patched_callback_new_connection
    logger.info(
        "Starting Modbus TCP server on %s:%d (unit ID %d)",
        host, port, PROXY_UNIT_ID,
    )

    # Populate app context
    if app_ctx is not None:
        app_ctx.cache = cache
        app_ctx.control_state = control_state

    # Start server as background task
    server_task = asyncio.create_task(_start_server(server), name="modbus-server")

    return cache, control_state, server, server_task
