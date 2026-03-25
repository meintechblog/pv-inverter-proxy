"""DeviceRegistry: per-device poll lifecycle management.

Manages N inverter devices with independent poll loops as asyncio tasks.
Supports runtime add/remove/enable/disable with clean lifecycle management.
Each device gets its own plugin, ConnectionManager, DashboardCollector,
and poll counter.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog

from pv_inverter_proxy.config import Config, InverterEntry, get_gateway_for_inverter
from pv_inverter_proxy.connection import ConnectionManager
from pv_inverter_proxy.context import AppContext, DeviceState
from pv_inverter_proxy.dashboard import DashboardCollector
from pv_inverter_proxy.plugins import plugin_factory

logger = structlog.get_logger()


def _extract_ac_power(inverter_registers: list[int]) -> float | None:
    """Extract AC power (W) from Model 103 inverter registers.

    Model 103 layout: DID(0) + Len(1) + 50 data fields.
    AC Power at data offset 12 (register index 14), scale factor at data offset 13 (register index 15).
    Values are unsigned 16-bit. Scale factor is signed 16-bit (two's complement).
    """
    if len(inverter_registers) < 16:
        return None
    raw_power = inverter_registers[14]
    raw_sf = inverter_registers[15]
    if raw_power == 0xFFFF or raw_sf == 0x8000:
        return None  # Not implemented / invalid
    # Convert unsigned to signed for scale factor
    sf = raw_sf if raw_sf < 0x8000 else raw_sf - 0x10000
    return float(raw_power) * (10.0 ** sf)


@dataclass
class ManagedDevice:
    """A device managed by the registry with its poll task."""

    entry: InverterEntry
    plugin: object  # InverterPlugin
    device_state: DeviceState
    poll_task: asyncio.Task | None = None


class DeviceRegistry:
    """Manages N inverter devices with independent poll loops.

    Each device gets its own asyncio poll task, plugin instance,
    ConnectionManager for backoff, and DashboardCollector.
    """

    def __init__(
        self,
        app_ctx: AppContext,
        config: Config,
        on_poll_success: Callable[[str], Awaitable[None]],
    ) -> None:
        self._app_ctx = app_ctx
        self._config = config
        self._on_poll_success = on_poll_success
        self._managed: dict[str, ManagedDevice] = {}
        self._distributor: object | None = None

    @property
    def distributor(self) -> object | None:
        """Public accessor for the PowerLimitDistributor instance."""
        return self._distributor

    async def start_device(self, device_id: str) -> None:
        """Start polling for a single device by its id.

        Finds the InverterEntry in config, creates plugin via plugin_factory,
        sets up DeviceState with ConnectionManager and DashboardCollector,
        and starts an asyncio poll task.

        Skips if entry is not enabled or device_id not found.
        """
        entry = self._find_entry(device_id)
        if entry is None:
            logger.warning("device_not_found", device_id=device_id)
            return
        if not entry.enabled:
            logger.info("device_disabled_skipped", device_id=device_id)
            return

        # Determine poll interval from gateway config or proxy config
        gateway_config = get_gateway_for_inverter(self._config, entry)
        poll_interval = (
            gateway_config.poll_interval
            if gateway_config
            else self._config.proxy.poll_interval
        )

        plugin = plugin_factory(entry, gateway_config)

        # Create per-device state
        conn_mgr = ConnectionManager(poll_interval=poll_interval)
        collector = DashboardCollector()
        poll_counter = {"success": 0, "total": 0}

        device_state = DeviceState(
            collector=collector,
            poll_counter=poll_counter,
            conn_mgr=conn_mgr,
            plugin=plugin,
        )

        managed = ManagedDevice(
            entry=entry,
            plugin=plugin,
            device_state=device_state,
        )

        # Register in managed dict and app context
        self._managed[device_id] = managed
        self._app_ctx.devices[device_id] = device_state

        # Start poll task
        task = asyncio.create_task(
            _device_poll_loop(
                device_id=device_id,
                plugin=plugin,
                device_state=device_state,
                poll_interval=poll_interval,
                on_success=self._on_poll_success,
                app_ctx=self._app_ctx,
            ),
            name=f"poll-{device_id}",
        )
        managed.poll_task = task

        logger.info("device_started", device_id=device_id, host=entry.host, type=entry.type)

    async def stop_device(self, device_id: str) -> None:
        """Stop polling for a device: cancel task, close plugin, remove state."""
        managed = self._managed.pop(device_id, None)
        if managed is None:
            return

        # Cancel poll task
        if managed.poll_task is not None and not managed.poll_task.done():
            managed.poll_task.cancel()
            try:
                await managed.poll_task
            except asyncio.CancelledError:
                pass

        # Close plugin
        try:
            await managed.plugin.close()
        except Exception:
            logger.debug("plugin_close_error", device_id=device_id, exc_info=True)

        # Remove from app context
        self._app_ctx.devices.pop(device_id, None)

        logger.info("device_stopped", device_id=device_id)

    async def start_all(self) -> None:
        """Start poll loops for all enabled inverters in config."""
        for entry in self._config.inverters:
            if entry.enabled:
                await self.start_device(entry.id)

    async def stop_all(self) -> None:
        """Stop all managed devices."""
        device_ids = list(self._managed.keys())
        for device_id in device_ids:
            await self.stop_device(device_id)

    async def enable_device(self, device_id: str) -> None:
        """Start a device (caller must set entry.enabled=True first)."""
        await self.start_device(device_id)

    async def disable_device(self, device_id: str) -> None:
        """Stop and clean up a device."""
        await self.stop_device(device_id)

    def get_active_device_ids(self) -> list[str]:
        """Return list of currently managed device ids."""
        return list(self._managed.keys())

    def get_active_count(self) -> int:
        """Return number of currently managed devices."""
        return len(self._managed)

    def _find_entry(self, device_id: str) -> InverterEntry | None:
        """Find InverterEntry by id in config."""
        for entry in self._config.inverters:
            if entry.id == device_id:
                return entry
        return None


async def _device_poll_loop(
    device_id: str,
    plugin: object,
    device_state: DeviceState,
    poll_interval: float,
    on_success: Callable[[str], Awaitable[None]],
    app_ctx: AppContext,
) -> None:
    """Per-device poll loop running as an asyncio task.

    Simplified version of proxy.py _poll_loop without night mode injection,
    common translation, or cache writes (those belong to AggregationLayer in Plan 02).

    Args:
        device_id: Unique identifier for the device.
        plugin: InverterPlugin instance.
        device_state: DeviceState with conn_mgr, poll_counter, etc.
        poll_interval: Base poll interval in seconds.
        on_success: Async callback invoked with device_id on successful poll.
        app_ctx: Application context for checking polling_paused.
    """
    log = logger.bind(device_id=device_id)
    conn_mgr = device_state.conn_mgr
    poll_counter = device_state.poll_counter

    # Initial connect
    if hasattr(plugin, "connect"):
        try:
            await plugin.connect()
            log.info("plugin_connected")
        except Exception as exc:
            log.warning("initial_connect_failed", error=str(exc))

    while True:
        # Skip polling when paused
        if app_ctx.polling_paused:
            await asyncio.sleep(poll_interval)
            continue

        try:
            # Reconnect if needed
            if hasattr(plugin, "_client") and not getattr(plugin._client, "connected", True):
                try:
                    await plugin.connect()
                    log.info("plugin_reconnected")
                except Exception:
                    log.debug("plugin_reconnect_failed", exc_info=True)

            result = await plugin.poll()
            poll_counter["total"] += 1

            if result.success:
                poll_counter["success"] += 1
                conn_mgr.on_poll_success()

                # Store raw poll data for register viewer
                device_state.last_poll_data = {
                    "common_registers": result.common_registers,
                    "inverter_registers": result.inverter_registers,
                }

                # Get nameplate registers from plugin for rated power
                nameplate_regs = None
                if hasattr(plugin, "get_model_120_registers"):
                    try:
                        nameplate_regs = plugin.get_model_120_registers()
                    except Exception:
                        log.debug("nameplate_register_error", exc_info=True)

                # Update DashboardCollector with decoded snapshot
                if device_state.collector is not None:
                    device_state.collector.collect_from_raw(
                        common_registers=result.common_registers,
                        inverter_registers=result.inverter_registers,
                        conn_mgr=conn_mgr,
                        poll_counter=poll_counter,
                        control_state=getattr(app_ctx, "control_state", None),
                        app_ctx=app_ctx,
                        nameplate_registers=nameplate_regs,
                    )

                distributor = getattr(app_ctx, 'distributor', None)
                if distributor is not None and hasattr(distributor, 'on_poll'):
                    ac_power_w = _extract_ac_power(result.inverter_registers)
                    if ac_power_w is not None:
                        distributor.on_poll(device_id, ac_power_w)

                await on_success(device_id)
                log.debug("poll_success")
            else:
                conn_mgr.on_poll_failure()
                log.warning("poll_failed", error=result.error, state=conn_mgr.state.value)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            poll_counter["total"] += 1
            conn_mgr.on_poll_failure()
            log.error("poll_error", error=str(exc), exc_info=True)

        await asyncio.sleep(conn_mgr.sleep_duration)
