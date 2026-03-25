"""PowerLimitDistributor: waterfall distribution of Venus OS power limits.

Distributes a global WMaxLimPct from Venus OS across N inverter plugins
using Throttling Order (TO) priority. TO 1 is throttled first, then TO 2,
and so on. Same-TO devices split remaining budget equally.

Supports monitoring-only exclusion, per-device dead-time buffering,
offline failover, and disable handling.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import groupby

import structlog

from pv_inverter_proxy.config import AUTO_THROTTLE_PRESETS, Config, InverterEntry
from pv_inverter_proxy.connection import ConnectionState
from pv_inverter_proxy.plugin import ThrottleCaps, compute_throttle_score


# Convergence tracking constants
CONVERGENCE_TOLERANCE_PCT = 5.0
CONVERGENCE_MAX_SAMPLES = 10
CONVERGENCE_NEAR_ZERO_W = 50.0
TARGET_CHANGE_TOLERANCE_PCT = 2.0


@dataclass
class DeviceLimitState:
    """Per-device limit tracking within the distributor."""

    device_id: str
    entry: InverterEntry
    plugin: object  # InverterPlugin (typed as object to avoid circular import)
    conn_mgr: object  # ConnectionManager
    current_limit_pct: float = 100.0
    last_write_ts: float | None = None  # None = never written
    pending_limit_pct: float | None = None
    is_online: bool = True
    # Binary throttle fields (Phase 34)
    relay_on: bool = True                # Current relay state (binary devices)
    last_toggle_ts: float | None = None  # Monotonic timestamp of last relay toggle
    startup_until_ts: float = 0.0        # Monotonic time when startup grace ends
    # Convergence tracking fields (Phase 35)
    target_power_w: float | None = None
    target_set_ts: float | None = None
    measured_response_time_s: float | None = None
    _convergence_samples: list = field(default_factory=list)


class PowerLimitDistributor:
    """Distributes Venus OS power limit commands across N inverters.

    Uses a waterfall algorithm: devices sorted by Throttling Order (TO)
    ascending. TO 1 gets budget first -- if budget is less than TO 1's
    rated power, TO 1 is throttled. Higher TO groups get remaining budget.
    """

    def __init__(self, registry: object, config: Config) -> None:
        self._registry = registry
        self._config = config
        self._device_states: dict[str, DeviceLimitState] = {}
        self._global_limit_pct: float = 100.0
        self._enabled: bool = False
        self._log = structlog.get_logger(component="distributor")

    def _get_convergence_params(self) -> dict[str, float]:
        """Return convergence parameters from the configured preset."""
        preset_name = getattr(self._config, "auto_throttle_preset", "balanced")
        return AUTO_THROTTLE_PRESETS.get(preset_name, AUTO_THROTTLE_PRESETS["balanced"])

    def sync_devices(self) -> None:
        """Sync internal state with DeviceRegistry managed devices."""
        managed = getattr(self._registry, "_managed", {})

        # Remove devices no longer managed
        gone = set(self._device_states.keys()) - set(managed.keys())
        for device_id in gone:
            del self._device_states[device_id]

        # Add new devices
        for device_id, md in managed.items():
            if device_id not in self._device_states:
                self._device_states[device_id] = DeviceLimitState(
                    device_id=device_id,
                    entry=md.entry,
                    plugin=md.plugin,
                    conn_mgr=md.device_state.conn_mgr,
                )
            else:
                # Update references (entry/plugin may have changed)
                ds = self._device_states[device_id]
                ds.entry = md.entry
                ds.plugin = md.plugin
                ds.conn_mgr = md.device_state.conn_mgr

        # Update online status from ConnectionManager
        for ds in self._device_states.values():
            if ds.conn_mgr is not None:
                ds.is_online = ds.conn_mgr.state == ConnectionState.CONNECTED
            else:
                ds.is_online = True

    async def distribute(self, limit_pct: float, enable: bool) -> None:
        """Main entry: Venus OS limit -> per-device limits via waterfall.

        Args:
            limit_pct: Global power limit as percentage of total rated power.
            enable: True to enable limiting, False to disable (send 100%).
        """
        self.sync_devices()
        self._global_limit_pct = limit_pct
        self._enabled = enable

        if not enable:
            # Disable: send 100% to proportional, switch(True) to binary
            for ds in self._device_states.values():
                if self._is_throttle_eligible(ds):
                    if self._is_binary_device(ds):
                        await self._send_binary_command(ds.device_id, turn_on=True)
                    else:
                        await self._send_limit(ds.device_id, 100.0, enable=False)
            return

        # Calculate total rated power of ALL enabled devices with rated_power > 0
        # (including monitoring-only, per user decision "Leistung zaehlt mit")
        # Exclude binary devices in startup grace period (not yet producing)
        total_rated = sum(
            ds.entry.rated_power
            for ds in self._device_states.values()
            if ds.entry.enabled and ds.entry.rated_power > 0
            and not self._is_in_startup(ds)
        )
        if total_rated <= 0:
            return

        allowed_watts = (limit_pct / 100.0) * total_rated
        targets = self._waterfall(allowed_watts)

        self._log.info(
            "distribute",
            limit_pct=limit_pct,
            total_rated=total_rated,
            allowed_watts=round(allowed_watts, 1),
            targets={k: round(v, 2) for k, v in targets.items()},
        )

        binary_on: list[str] = []
        binary_off: list[str] = []
        for device_id, target_pct in targets.items():
            ds = self._device_states[device_id]
            if self._is_binary_device(ds):
                if target_pct > 0:
                    binary_on.append(device_id)
                else:
                    binary_off.append(device_id)
            else:
                await self._send_limit(device_id, target_pct, enable=True)

        # Binary OFF: send immediately (throttle)
        for device_id in binary_off:
            await self._send_binary_command(device_id, turn_on=False)

        # Binary ON: reverse order (slowest first for re-enable)
        for device_id in self._sort_binary_reenable(binary_on):
            await self._send_binary_command(device_id, turn_on=True)

    def _effective_score(self, ds: DeviceLimitState) -> float:
        """Compute effective throttle score, using measured response time if available."""
        if not hasattr(ds.plugin, 'throttle_capabilities'):
            return 0.0
        caps = ds.plugin.throttle_capabilities
        if getattr(ds, 'measured_response_time_s', None) is not None:
            measured_caps = ThrottleCaps(
                mode=caps.mode,
                response_time_s=ds.measured_response_time_s,
                cooldown_s=caps.cooldown_s,
                startup_delay_s=caps.startup_delay_s,
            )
            return compute_throttle_score(measured_caps)
        return compute_throttle_score(caps)

    def _waterfall(self, allowed_watts: float) -> dict[str, float]:
        """Pure function: waterfall distribution by Throttling Order or score.

        When auto_throttle is True, sorts by effective score descending (each
        device is its own tier). When False, uses manual throttle_order groups.

        Returns {device_id: limit_pct} for all throttle-eligible devices.
        """
        # Collect throttle-eligible: throttle_enabled=True, online, rated_power > 0
        # Exclude binary devices in startup grace period
        eligible_list = [
            ds for ds in self._device_states.values()
            if ds.entry.throttle_enabled and ds.is_online and ds.entry.rated_power > 0
            and not self._is_in_startup(ds)
        ]

        if not eligible_list:
            return {}

        if self._config.auto_throttle:
            return self._waterfall_auto(eligible_list, allowed_watts)
        else:
            return self._waterfall_manual(eligible_list, allowed_watts)

    def _waterfall_auto(self, eligible: list[DeviceLimitState], allowed_watts: float) -> dict[str, float]:
        """Score-based waterfall: each device is its own tier, sorted by score descending."""
        sorted_eligible = sorted(
            eligible,
            key=lambda ds: (self._effective_score(ds), ds.device_id),
            reverse=True,
        )

        result: dict[str, float] = {}
        remaining = allowed_watts

        for ds in sorted_eligible:
            if remaining <= 0:
                result[ds.device_id] = 0.0
                continue
            budget = min(remaining, ds.entry.rated_power)
            pct = max(0.0, min(100.0, (budget / ds.entry.rated_power) * 100.0))
            result[ds.device_id] = round(pct, 1)
            remaining -= budget

        return result

    def _waterfall_manual(self, eligible: list[DeviceLimitState], allowed_watts: float) -> dict[str, float]:
        """Manual waterfall: group by throttle_order, split within group."""
        eligible = sorted(eligible, key=lambda ds: ds.entry.throttle_order)

        result: dict[str, float] = {}
        remaining = allowed_watts

        # Group by throttle_order
        for to_num, group_iter in groupby(eligible, key=lambda ds: ds.entry.throttle_order):
            group = list(group_iter)
            group_rated = sum(ds.entry.rated_power for ds in group)

            if remaining >= group_rated:
                # This group runs at 100%
                for ds in group:
                    result[ds.device_id] = 100.0
                remaining -= group_rated
            else:
                # This group gets throttled -- split remaining equally by device count
                per_device_watts = remaining / len(group) if len(group) > 0 else 0.0
                for ds in group:
                    pct = max(0.0, min(100.0, (per_device_watts / ds.entry.rated_power) * 100.0))
                    result[ds.device_id] = round(pct, 1)
                remaining = 0.0

            if remaining <= 0:
                break

        # Any eligible device not yet assigned gets 0%
        for ds in eligible:
            if ds.device_id not in result:
                result[ds.device_id] = 0.0

        return result

    async def _send_limit(
        self, device_id: str, limit_pct: float, enable: bool = True
    ) -> None:
        """Send limit to one device, respecting dead-time buffering."""
        ds = self._device_states.get(device_id)
        if ds is None:
            return

        now = time.monotonic()

        # First write ever: no dead-time applies
        if ds.last_write_ts is None:
            elapsed = float("inf")
        else:
            elapsed = now - ds.last_write_ts

        if ds.entry.throttle_dead_time_s > 0 and elapsed < ds.entry.throttle_dead_time_s:
            # Buffer (latest wins)
            ds.pending_limit_pct = limit_pct
            self._log.debug(
                "limit_buffered",
                device_id=device_id,
                pending_pct=round(limit_pct, 2),
                dead_time_remaining=round(ds.entry.throttle_dead_time_s - elapsed, 2),
            )
            return

        # Actually send
        try:
            result = await ds.plugin.write_power_limit(enable, limit_pct)
            if result.success:
                ds.current_limit_pct = limit_pct
                ds.last_write_ts = now
                ds.pending_limit_pct = None
                self._record_target(ds, limit_pct)
                self._log.debug(
                    "limit_sent",
                    device_id=device_id,
                    limit_pct=round(limit_pct, 2),
                    enable=enable,
                )
            else:
                self._log.warning(
                    "limit_write_failed",
                    device_id=device_id,
                    error=result.error,
                )
        except Exception as exc:
            self._log.error(
                "limit_write_error",
                device_id=device_id,
                error=str(exc),
            )

    async def flush_pending(self) -> None:
        """Flush any buffered limits whose dead-time has expired."""
        now = time.monotonic()
        for ds in list(self._device_states.values()):
            if ds.pending_limit_pct is not None:
                if ds.last_write_ts is None:
                    elapsed = float("inf")
                else:
                    elapsed = now - ds.last_write_ts
                if elapsed >= ds.entry.throttle_dead_time_s:
                    pending = ds.pending_limit_pct
                    ds.pending_limit_pct = None  # clear before send to avoid recursion
                    await self._send_limit(ds.device_id, pending, enable=self._enabled)

    def get_device_limits(self) -> dict[str, float]:
        """Return current limit percentage for each managed device."""
        return {
            device_id: ds.current_limit_pct
            for device_id, ds in self._device_states.items()
        }

    async def redistribute(self) -> None:
        """Re-run distribution with last known global limit.

        Called on device online/offline change.
        """
        if self._enabled:
            await self.distribute(self._global_limit_pct, True)

    def _is_binary_device(self, ds: DeviceLimitState) -> bool:
        """Check if device uses binary (relay on/off) throttling."""
        if hasattr(ds.plugin, 'throttle_capabilities'):
            return ds.plugin.throttle_capabilities.mode == "binary"
        return False

    def _is_in_startup(self, ds: DeviceLimitState) -> bool:
        """Check if binary device is in startup grace period."""
        if not self._is_binary_device(ds):
            return False
        return time.monotonic() < ds.startup_until_ts

    async def _send_binary_command(self, device_id: str, turn_on: bool) -> None:
        """Send relay on/off to a binary device, respecting cooldown."""
        ds = self._device_states.get(device_id)
        if ds is None:
            return
        # No change needed
        if ds.relay_on == turn_on:
            return
        # Cooldown check
        now = time.monotonic()
        caps = ds.plugin.throttle_capabilities
        if ds.last_toggle_ts is not None:
            elapsed = now - ds.last_toggle_ts
            if elapsed < caps.cooldown_s:
                self._log.debug(
                    "binary_cooldown_active",
                    device_id=device_id,
                    want=turn_on,
                    cooldown_remaining=round(caps.cooldown_s - elapsed, 1),
                )
                return
        # Execute switch
        try:
            success = await ds.plugin.switch(turn_on)
            if success:
                ds.relay_on = turn_on
                ds.last_toggle_ts = now
                if turn_on:
                    ds.startup_until_ts = now + caps.startup_delay_s
                self._record_target(ds, 100.0 if turn_on else 0.0)
                self._log.info("binary_switch", device_id=device_id, relay_on=turn_on)
            else:
                self._log.warning("binary_switch_failed", device_id=device_id, on=turn_on)
        except Exception as exc:
            self._log.error("binary_switch_error", device_id=device_id, error=str(exc))

    def _sort_binary_reenable(self, device_ids: list[str]) -> list[str]:
        """Sort binary devices for re-enable: lowest throttle_score first."""
        def score_key(did: str) -> float:
            ds = self._device_states.get(did)
            if ds and hasattr(ds.plugin, 'throttle_capabilities'):
                return compute_throttle_score(ds.plugin.throttle_capabilities)
            return 0.0
        return sorted(device_ids, key=score_key)

    def _is_throttle_eligible(self, ds: DeviceLimitState) -> bool:
        """Check if a device is eligible for throttle commands."""
        return (
            ds.entry.throttle_enabled
            and ds.is_online
            and ds.entry.rated_power > 0
        )

    def _record_target(self, ds: DeviceLimitState, limit_pct: float) -> None:
        """Record target power for convergence tracking after a successful send.

        Only updates target_set_ts if the new target differs from current by
        more than target_change_tolerance_pct to avoid stale target resets.
        """
        params = self._get_convergence_params()
        target_change_tolerance = params["target_change_tolerance_pct"]
        new_target_w = (limit_pct / 100.0) * ds.entry.rated_power
        if ds.target_power_w is not None:
            if ds.target_power_w == 0 and new_target_w == 0:
                return  # No change
            if ds.target_power_w != 0:
                change_pct = abs(new_target_w - ds.target_power_w) / ds.target_power_w * 100.0
                if change_pct <= target_change_tolerance:
                    return  # Target unchanged within tolerance
        ds.target_power_w = new_target_w
        ds.target_set_ts = time.monotonic()

    def on_poll(self, device_id: str, actual_power_w: float) -> None:
        """Check convergence after receiving polled power data.

        If the actual power is within the preset's convergence_tolerance_pct of
        the target, records the response time and computes a rolling average.
        """
        ds = self._device_states.get(device_id)
        if ds is None:
            return
        if ds.target_power_w is None or ds.target_set_ts is None:
            return
        # Skip during startup grace period
        if self._is_in_startup(ds):
            return

        params = self._get_convergence_params()
        tolerance_pct = params["convergence_tolerance_pct"]
        max_samples = int(params["convergence_max_samples"])
        binary_off_w = params["binary_off_threshold_w"]

        # Check convergence
        converged = False
        if ds.target_power_w == 0:
            converged = actual_power_w < binary_off_w
        else:
            error_pct = abs(actual_power_w - ds.target_power_w) / ds.target_power_w * 100.0
            converged = error_pct <= tolerance_pct

        if converged:
            elapsed = time.monotonic() - ds.target_set_ts
            ds._convergence_samples.append(elapsed)
            # Trim to max samples
            if len(ds._convergence_samples) > max_samples:
                ds._convergence_samples = ds._convergence_samples[-max_samples:]
            ds.measured_response_time_s = sum(ds._convergence_samples) / len(ds._convergence_samples)
            # Reset target (convergence detected, wait for next limit command)
            ds.target_power_w = None
            ds.target_set_ts = None
