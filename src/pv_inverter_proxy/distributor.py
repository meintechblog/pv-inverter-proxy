"""PowerLimitDistributor: score-based waterfall distribution of power limits.

Distributes a global WMaxLimPct across N inverter plugins using throttle
score priority. Higher score = throttled first (fastest responders handle
throttling). Low-score devices are protected (get budget first).

Supports monitoring-only exclusion, per-device dead-time buffering,
offline failover, and disable handling.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

from pv_inverter_proxy.config import CONVERGENCE_PARAMS, Config, InverterEntry
from pv_inverter_proxy.connection import ConnectionState
from pv_inverter_proxy.plugin import ThrottleCaps, compute_throttle_score, get_throttle_caps


@dataclass
class DeviceLimitState:
    """Per-device limit tracking within the distributor."""

    device_id: str
    entry: InverterEntry
    plugin: object  # InverterPlugin (typed as object to avoid circular import)
    conn_mgr: object  # ConnectionManager
    current_limit_pct: float = 100.0
    last_write_ts: float | None = None
    pending_limit_pct: float | None = None
    is_online: bool = True
    relay_on: bool = True
    last_toggle_ts: float | None = None
    startup_until_ts: float = 0.0
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
        """Return convergence parameters."""
        return CONVERGENCE_PARAMS

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
        limit_pct = max(0.0, min(100.0, limit_pct))
        self._global_limit_pct = limit_pct
        self._enabled = enable

        if not enable:
            # Disable: force-send 100% to all devices (skip dead-time + cooldown)
            for ds in self._device_states.values():
                if self._is_throttle_eligible(ds):
                    if self._is_binary_device(ds):
                        await self._send_binary_command(ds.device_id, turn_on=True, force=True)
                    else:
                        await self._send_limit(ds.device_id, 100.0, enable=False, force=True)
            return

        # Calculate total rated power of devices that are part of the Fronius
        # Proxy aggregate (aggregate=True). Devices with aggregate=False are
        # outside the Fronius scope (e.g. a separate inverter on the same
        # network) — they do not count toward the limit denominator and are
        # not throttled by the Fronius limit. This matches the UI gauge,
        # which computes the dropdown percentage against the same set.
        # Exclude binary devices in startup grace period (not yet producing).
        total_rated = sum(
            ds.entry.rated_power
            for ds in self._device_states.values()
            if ds.entry.enabled and ds.entry.aggregate
            and ds.entry.rated_power > 0
            and not self._is_in_startup(ds)
        )
        if total_rated <= 0:
            return

        allowed_watts = (limit_pct / 100.0) * total_rated

        # Subtract non-throttle-eligible aggregate devices' rated power from
        # the waterfall budget. These devices are part of the aggregate but
        # produce at ~100% and can't be controlled, so their output must be
        # deducted from the fleet budget before distributing to controllable
        # devices.
        non_throttle_rated = sum(
            ds.entry.rated_power
            for ds in self._device_states.values()
            if ds.entry.enabled and ds.entry.aggregate
            and ds.entry.rated_power > 0
            and not ds.entry.throttle_enabled
            and not self._is_in_startup(ds)
        )
        waterfall_budget = max(0.0, allowed_watts - non_throttle_rated)
        targets = self._waterfall(waterfall_budget)

        # Reclaim slack from underproducing low-score devices and hand it
        # to high-score (fast-responding proportional) devices. Without this,
        # the waterfall reserves the *rated* power of small inverters even
        # if they are MPPT-limited far below their rated value, causing
        # the SolarEdge to underutilize the user's ceiling.
        reclaimed_slack = self._reclaim_slack_into_targets(targets)

        self._log.info(
            "distribute",
            limit_pct=limit_pct,
            total_rated=total_rated,
            allowed_watts=round(allowed_watts, 1),
            non_throttle_rated=non_throttle_rated,
            waterfall_budget=round(waterfall_budget, 1),
            reclaimed_slack_w=round(reclaimed_slack, 1),
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
        caps = get_throttle_caps(ds.plugin)
        if caps is None:
            return 0.0
        if ds.measured_response_time_s is not None:
            measured_caps = ThrottleCaps(
                mode=caps.mode,
                response_time_s=ds.measured_response_time_s,
                cooldown_s=caps.cooldown_s,
                startup_delay_s=caps.startup_delay_s,
            )
            return compute_throttle_score(measured_caps)
        return compute_throttle_score(caps)

    def _waterfall(self, allowed_watts: float) -> dict[str, float]:
        """Score-based waterfall: higher score = throttled first.

        Sorts by effective score ascending — low-score devices get budget
        first (protected), high-score devices get remaining (throttled first)
        because they respond fastest.

        Returns {device_id: limit_pct} for all throttle-eligible devices.
        """
        # Collect throttle-eligible: aggregate=True, throttle_enabled=True,
        # online, rated_power > 0. Non-aggregate devices are outside the
        # Fronius Proxy scope and must not be throttled by its limit.
        # Exclude binary devices in startup grace period.
        eligible = [
            ds for ds in self._device_states.values()
            if ds.entry.aggregate
            and ds.entry.throttle_enabled and ds.is_online and ds.entry.rated_power > 0
            and not self._is_in_startup(ds)
        ]

        if not eligible:
            return {}

        # Sort ascending: low score gets budget first, high score throttled first
        sorted_eligible = sorted(
            eligible,
            key=lambda ds: (self._effective_score(ds), ds.device_id),
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

        return result

    async def _send_limit(
        self, device_id: str, limit_pct: float, enable: bool = True,
        *, force: bool = False,
    ) -> None:
        """Send limit to one device, respecting dead-time buffering.

        Args:
            force: Skip dead-time buffering and pass force=True to plugin
                   (used when disabling all limiting).
        """
        ds = self._device_states.get(device_id)
        if ds is None:
            return

        now = time.monotonic()

        if force:
            # Skip dead-time, send immediately with force flag
            try:
                result = await ds.plugin.write_power_limit(enable, limit_pct, force=True)
                if result.success:
                    ds.current_limit_pct = limit_pct
                    ds.last_write_ts = now
                    ds.pending_limit_pct = None
                    self._record_target(ds, limit_pct)
                    self._log.debug("limit_sent_forced", device_id=device_id, limit_pct=round(limit_pct, 2))
            except Exception as exc:
                self._log.error("limit_write_error", device_id=device_id, error=str(exc))
            return

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
                    ds.pending_limit_pct = None
                    try:
                        await self._send_limit(ds.device_id, pending, enable=self._enabled)
                    except Exception:
                        ds.pending_limit_pct = pending  # restore on failure

    def get_device_limits(self) -> dict[str, float]:
        """Return current limit percentage for each managed device."""
        return {
            device_id: ds.current_limit_pct
            for device_id, ds in self._device_states.items()
        }

    def get_device_display_state(self, device_id: str) -> dict | None:
        """Return display-ready throttle state for a device (public API for webapp)."""
        ds = self._device_states.get(device_id)
        if ds is None:
            return None

        caps = get_throttle_caps(ds.plugin)
        throttle_mode = caps.mode if caps else "none"

        # Derive throttle_state
        if not ds.entry.throttle_enabled:
            state = "disabled"
        elif self._is_in_startup(ds):
            state = "startup"
        elif (throttle_mode == "binary" and ds.last_toggle_ts is not None
              and caps is not None
              and (time.monotonic() - ds.last_toggle_ts) < caps.cooldown_s):
            state = "cooldown"
        elif ds.current_limit_pct < 100.0 or not ds.relay_on:
            state = "throttled"
        else:
            state = "active"

        return {
            "throttle_state": state,
            "relay_on": ds.relay_on,
            "measured_response_time_s": ds.measured_response_time_s,
            "current_limit_pct": ds.current_limit_pct,
        }

    # Hysteresis bounds for slack reallocation
    _SLACK_MIN_PER_DEVICE_W = 50.0   # ignore <50W slack per device (noise)
    _SLACK_MIN_TOTAL_W = 100.0       # don't bother reallocating <100W total
    _SLACK_HEADROOM_FLOOR_W = 50.0   # device must have >=50W headroom to absorb

    def _read_actual_power_w(self, device_id: str) -> float | None:
        """Return current AC output of a device from its collector snapshot.

        Used by the slack reallocator to detect underproducing devices.
        Returns None if no snapshot is available yet (boot, transient).
        """
        managed = getattr(self._registry, "_managed", {})
        md = managed.get(device_id)
        if md is None:
            return None
        device_state = getattr(md, "device_state", None)
        collector = getattr(device_state, "collector", None) if device_state else None
        snap = getattr(collector, "last_snapshot", None) if collector else None
        if not snap:
            return None
        inv = snap.get("inverter") or {}
        p = inv.get("ac_power_w")
        if isinstance(p, (int, float)) and p >= 0:
            return float(p)
        return None

    def _reclaim_slack_into_targets(self, targets: dict[str, float]) -> float:
        """Reclaim slack from underproducing non-absorber devices.

        The absorber pool = high-score proportional devices (e.g. SolarEdge):
        fastest responders, capable of fractional throttling, can absorb
        extra budget. Slack source pool = everyone else (binary devices,
        low-score small inverters): when their actual AC output is below
        their waterfall target (MPPT-limited / partial shade), the
        difference becomes slack and is handed to the absorbers so the
        aggregate hits the user-chosen ceiling exactly.

        A device cannot absorb its own slack — feeding back its shortfall
        as extra budget is meaningless because the device is already
        producing less than its target.

        Mutates ``targets`` in place. Returns total slack watts reallocated.
        """
        if not targets:
            return 0.0

        # Determine absorber pool: devices the waterfall already throttled
        # below 100% — they have headroom and can swallow extra budget.
        # Devices sitting at 100% target are at the front of the waterfall
        # (= "protected" small inverters); their (rated - actual) shortfall
        # is the slack source. Binary devices are excluded as absorbers
        # because their on/off semantics don't accept fractional headroom.
        # Sort absorbers by score descending: fastest responder gets slack
        # first.
        absorbers = sorted(
            (
                self._device_states[device_id]
                for device_id, pct in targets.items()
                if pct < 100.0
                and device_id in self._device_states
                and not self._is_binary_device(self._device_states[device_id])
            ),
            key=lambda ds: (-self._effective_score(ds), ds.device_id),
        )
        if not absorbers:
            return 0.0
        absorber_ids = {ds.device_id for ds in absorbers}

        # Build a target-watts table and compute slack from non-absorbers.
        target_w_by_id: dict[str, float] = {}
        slack_w = 0.0
        for device_id, pct in targets.items():
            ds = self._device_states.get(device_id)
            if ds is None:
                continue
            target_w = (pct / 100.0) * ds.entry.rated_power
            target_w_by_id[device_id] = target_w
            if device_id in absorber_ids:
                continue
            actual_w = self._read_actual_power_w(device_id)
            if actual_w is None:
                continue
            shortfall = target_w - actual_w
            if shortfall > self._SLACK_MIN_PER_DEVICE_W:
                slack_w += shortfall

        if slack_w < self._SLACK_MIN_TOTAL_W:
            return 0.0

        reallocated = 0.0
        for ds in absorbers:
            if slack_w <= 0:
                break
            current_target_w = target_w_by_id.get(ds.device_id, 0.0)
            headroom = ds.entry.rated_power - current_target_w
            if headroom <= self._SLACK_HEADROOM_FLOOR_W:
                continue
            absorb = min(slack_w, headroom)
            new_target_w = current_target_w + absorb
            new_pct = min(100.0, (new_target_w / ds.entry.rated_power) * 100.0)
            targets[ds.device_id] = round(new_pct, 1)
            target_w_by_id[ds.device_id] = new_target_w
            slack_w -= absorb
            reallocated += absorb

        return reallocated

    async def redistribute(self) -> None:
        """Re-run distribution with last known global limit.

        Called on device online/offline change and periodically by the
        slack-tracking refresh loop so the SolarEdge picks up unused
        budget from MPPT-limited small inverters as conditions shift.
        """
        if self._enabled:
            await self.distribute(self._global_limit_pct, True)

    async def slack_refresh_loop(self, interval_s: float = 5.0) -> None:
        """Periodically redistribute so slack reallocation tracks the sun.

        Each tick re-runs distribute() with the same global limit. The
        slack reallocator picks up new actual-vs-target shortfalls and
        hands them to high-score absorbers. This keeps the aggregate
        output at the user-chosen ceiling even as small inverters'
        production rises and falls with cloud cover.
        """
        while True:
            try:
                await asyncio.sleep(interval_s)
                if self._enabled:
                    await self.redistribute()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log.warning("slack_refresh_error", error=str(exc))

    def _is_binary_device(self, ds: DeviceLimitState) -> bool:
        """Check if device uses binary (relay on/off) throttling."""
        caps = get_throttle_caps(ds.plugin)
        return caps is not None and caps.mode == "binary"

    def _is_in_startup(self, ds: DeviceLimitState) -> bool:
        """Check if binary device is in startup grace period."""
        if not self._is_binary_device(ds):
            return False
        return time.monotonic() < ds.startup_until_ts

    async def _send_binary_command(
        self, device_id: str, turn_on: bool, *, force: bool = False,
    ) -> None:
        """Send relay on/off to a binary device, respecting cooldown.

        Args:
            force: Skip cooldown check (used when disabling all limiting).
        """
        ds = self._device_states.get(device_id)
        if ds is None:
            return
        # No change needed
        if ds.relay_on == turn_on:
            return
        # Cooldown check (skipped when force=True, e.g. disable all)
        now = time.monotonic()
        caps = get_throttle_caps(ds.plugin)
        if caps is None:
            self._log.warning("binary_no_caps", device_id=device_id)
            return
        if not force and ds.last_toggle_ts is not None:
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
        """Sort binary devices for re-enable: lowest effective score first."""
        def score_key(did: str) -> float:
            ds = self._device_states.get(did)
            return self._effective_score(ds) if ds else 0.0
        return sorted(device_ids, key=score_key)

    def _is_throttle_eligible(self, ds: DeviceLimitState) -> bool:
        """Check if a device is eligible for throttle commands.

        Non-aggregate devices are outside the Fronius Proxy scope and are
        never throttled by the Fronius limit.
        """
        return (
            ds.entry.aggregate
            and ds.entry.throttle_enabled
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
