# Phase 34: Binary Throttle Engine with Hysteresis - Research

**Researched:** 2026-03-25
**Domain:** Python asyncio, relay control hysteresis, waterfall distribution extension, state machines
**Confidence:** HIGH

## Summary

Phase 34 extends the `PowerLimitDistributor` to handle binary (relay on/off) devices alongside the existing proportional (percentage-based) devices. The current distributor treats all devices as proportional -- it sends a percentage via `write_power_limit()`. For binary devices like Shelly, the distributor must instead call `switch(on/off)` and respect the device's `cooldown_s` (hysteresis timer to prevent relay flapping) and `startup_delay_s` (grace period after re-enable before expecting power output).

The key architectural challenge is that the waterfall algorithm currently outputs `{device_id: limit_pct}` -- a continuous value. Binary devices need a discrete decision: ON (100%) or OFF (0%). The distributor must detect binary devices via `throttle_capabilities.mode == "binary"`, convert the waterfall output to a binary decision (any limit > 0 = ON, limit == 0 = OFF), enforce cooldown between toggles, and track startup delay state. Re-enable order is reversed: slowest devices (lowest throttle_score) come back online first so fast proportional devices stay available for fine-tuning.

This phase touches only `distributor.py` (core logic), `plugin.py` (possible minor additions), and tests. No UI changes, no config changes, no new dependencies.

**Primary recommendation:** Extend `DeviceLimitState` with binary-specific tracking fields (relay_state, last_toggle_ts, startup_until_ts). Split the `_waterfall` output into two dispatch paths in `distribute()`: proportional devices use existing `write_power_limit()`, binary devices use `switch()` via the plugin. Add a `_enforce_cooldown()` guard and `_is_in_startup()` query. Implement reverse-order re-enable by sorting binary devices by throttle_score ascending when transitioning from OFF to ON.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| THRT-04 | PowerLimitDistributor recognizes binary-throttle devices and sends relay off when their turn comes in the waterfall | Detect via `plugin.throttle_capabilities.mode == "binary"`, convert waterfall 0% to `switch(False)`, waterfall >0% to `switch(True)` |
| THRT-05 | Hysteresis timer prevents relay toggling more than once per cooldown period (default 300s) | Track `last_toggle_ts` per device in `DeviceLimitState`; compare against `throttle_capabilities.cooldown_s` before sending switch command |
| THRT-06 | After relay on, distributor waits startup_delay_s before expecting power; re-enable in reverse order (slowest first) | Track `startup_until_ts`; sort binary devices by `throttle_score` ascending for re-enable; exclude startup devices from "available power" calculations |
</phase_requirements>

## Architecture Patterns

### Current Distributor Flow (before Phase 34)

```
distribute(limit_pct, enable)
  -> sync_devices()
  -> _waterfall(allowed_watts)  -> {device_id: target_pct}
  -> for each target: _send_limit(device_id, target_pct)
     -> plugin.write_power_limit(enable, limit_pct)
```

All devices are treated as proportional. `write_power_limit()` is a no-op on Shelly (returns `WriteResult(success=True)` without doing anything).

### Recommended Extended Flow (Phase 34)

```
distribute(limit_pct, enable)
  -> sync_devices()
  -> _waterfall(allowed_watts)  -> {device_id: target_pct}
  -> for each target:
     if device is binary:
       _send_binary_command(device_id, target_pct > 0)
         -> cooldown check
         -> plugin.switch(on/off)
         -> track relay_state, last_toggle_ts, startup_until_ts
     else:
       _send_limit(device_id, target_pct)  (existing path, unchanged)
```

### Recommended Project Structure Changes

```
distributor.py         -- MODIFY: extend DeviceLimitState, add binary dispatch
                          in distribute(), add _send_binary_command(),
                          add _enforce_cooldown(), add reverse-order re-enable
plugin.py              -- NO CHANGES (ThrottleCaps and switch() already exist)
plugins/shelly.py      -- NO CHANGES (switch() already implemented)
config.py              -- NO CHANGES
tests/test_distributor.py  -- EXTEND: add binary device tests
```

### Pattern 1: Extended DeviceLimitState

**What:** Add binary-specific tracking fields to the existing `DeviceLimitState` dataclass.

```python
@dataclass
class DeviceLimitState:
    """Per-device limit tracking within the distributor."""
    device_id: str
    entry: InverterEntry
    plugin: object
    conn_mgr: object
    current_limit_pct: float = 100.0
    last_write_ts: float | None = None
    pending_limit_pct: float | None = None
    is_online: bool = True
    # --- Binary throttle fields (Phase 34) ---
    relay_on: bool = True               # Current relay state (binary devices)
    last_toggle_ts: float | None = None # Monotonic timestamp of last relay toggle
    startup_until_ts: float = 0.0       # Monotonic time when startup grace ends
```

### Pattern 2: Binary Device Detection

**What:** Check `throttle_capabilities.mode` to determine dispatch path.
**Where:** In `distribute()`, after `_waterfall()` computes targets.

```python
def _is_binary_device(self, ds: DeviceLimitState) -> bool:
    """Check if device uses binary (relay on/off) throttling."""
    if hasattr(ds.plugin, 'throttle_capabilities'):
        return ds.plugin.throttle_capabilities.mode == "binary"
    return False
```

Use the same `hasattr` guard pattern established in Phase 33 for safety with plugins that may not yet have `throttle_capabilities`.

### Pattern 3: Binary Command with Cooldown Guard

**What:** Send relay switch command only if cooldown has elapsed since last toggle.

```python
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
            self._log.info(
                "binary_switch",
                device_id=device_id,
                relay_on=turn_on,
                startup_until=ds.startup_until_ts if turn_on else 0,
            )
        else:
            self._log.warning("binary_switch_failed", device_id=device_id, on=turn_on)
    except Exception as exc:
        self._log.error("binary_switch_error", device_id=device_id, error=str(exc))
```

### Pattern 4: Reverse-Order Re-Enable

**What:** When the waterfall says binary devices should come back (target > 0%), re-enable them in reverse throttle_score order (slowest first).
**Why:** Slow binary devices take longest to start up. Bringing them back first means by the time fast proportional devices need fine-tuning, all binary devices are already producing.

```python
def _sort_binary_reenable(self, device_ids: list[str]) -> list[str]:
    """Sort binary devices for re-enable: lowest throttle_score first."""
    def score_key(did: str) -> float:
        ds = self._device_states.get(did)
        if ds and hasattr(ds.plugin, 'throttle_capabilities'):
            return compute_throttle_score(ds.plugin.throttle_capabilities)
        return 0.0
    return sorted(device_ids, key=score_key)
```

In practice with Phase 34 there is only one binary device type (Shelly), so reverse ordering is more about establishing the pattern for Phase 35. If multiple Shelly devices exist with different scores, they would be re-enabled lowest-score-first.

### Pattern 5: Startup Grace Period

**What:** After relay turns ON, mark the device as "in startup" for `startup_delay_s` seconds. During startup, the distributor should not count this device's rated power as "available" in the waterfall (it is not producing yet).

```python
def _is_in_startup(self, ds: DeviceLimitState) -> bool:
    """Check if binary device is in startup grace period."""
    if not self._is_binary_device(ds):
        return False
    return time.monotonic() < ds.startup_until_ts
```

**Integration point:** In `_waterfall()`, devices in startup could be temporarily excluded from the "eligible" list so the remaining budget calculation is correct. Alternatively, they can remain eligible but with a "pending" status -- the simpler approach is to treat them as online but not count their power until startup ends.

### Anti-Patterns to Avoid

- **Modifying write_power_limit() to handle binary:** The ABC method is for proportional control. Binary devices already have `switch()`. Do not conflate the two APIs -- keep them separate dispatch paths in the distributor.
- **Storing cooldown in config.yaml:** Cooldown is an intrinsic device property from `ThrottleCaps`, not a user-tunable setting. The `throttle_dead_time_s` on InverterEntry is different (it is the per-write dead-time buffer for proportional devices).
- **Polling relay state from device:** The distributor tracks relay state locally (`ds.relay_on`). Do not add HTTP polls to Shelly to check relay state -- trust the last command sent. If a manual override happens externally, the next poll cycle will detect it via power data.
- **Re-implementing the waterfall for binary devices:** The existing `_waterfall()` already computes correct target percentages. Binary devices just need the output converted to boolean (>0 = ON, ==0 = OFF). Do not create a separate waterfall path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cooldown timer | Custom asyncio timer/task | Simple monotonic timestamp comparison | `time.monotonic()` is reliable, no async complexity needed |
| Relay state machine | Full FSM class | Fields on DeviceLimitState dataclass | Only 3 states needed (on/off/cooldown), dataclass fields suffice |
| Device capability detection | Type-checking with isinstance | `hasattr` + `throttle_capabilities.mode` check | Follows Phase 33 pattern, avoids circular imports |

## Common Pitfalls

### Pitfall 1: Relay Flapping on Rapid Limit Changes

**What goes wrong:** Venus OS sends limit updates every second. Without cooldown enforcement, a binary device could toggle on/off/on/off rapidly, damaging the relay and attached inverter.
**Why it happens:** The distributor is called on every Venus write. If the limit oscillates around the threshold, the binary decision flips each cycle.
**How to avoid:** The cooldown guard (`_send_binary_command`) MUST check `last_toggle_ts` against `cooldown_s` (300s for Shelly) before every toggle. This is the critical safety feature of Phase 34.
**Warning signs:** `binary_cooldown_active` log appearing constantly = working correctly. `binary_switch` appearing every few seconds = broken cooldown.

### Pitfall 2: Confusing throttle_dead_time_s with cooldown_s

**What goes wrong:** Using `entry.throttle_dead_time_s` (per-device config, default 0.0) instead of `caps.cooldown_s` (intrinsic device property, 300s for Shelly) for the binary cooldown.
**Why it happens:** Both are "wait before sending again" concepts but serve different purposes. `throttle_dead_time_s` is for proportional write buffering (avoid spamming Modbus). `cooldown_s` is for relay protection (physical switching limit).
**How to avoid:** Binary devices use `caps.cooldown_s` for toggle cooldown. `throttle_dead_time_s` is not relevant for binary dispatch.

### Pitfall 3: switch() Method Only on ShellyPlugin

**What goes wrong:** Calling `ds.plugin.switch(on)` on a SolarEdge or OpenDTU plugin which do not have a `switch()` method.
**Why it happens:** `switch()` is defined on ShellyPlugin but is NOT on the InverterPlugin ABC.
**How to avoid:** Only call `switch()` after confirming `_is_binary_device(ds)` returns True. Additionally, use `hasattr(ds.plugin, 'switch')` as a safety guard.
**Alternative:** Add `switch(on: bool) -> bool` as a method on `InverterPlugin` ABC with a default no-op implementation. This is cleaner but a larger change. Recommendation: use `hasattr` guard for Phase 34, consider ABC addition in Phase 35.

### Pitfall 4: Startup Grace Period Not Reflected in Waterfall

**What goes wrong:** After turning a binary device ON, the distributor immediately counts its rated power as "available" in the waterfall. But the device is not actually producing yet (30s startup delay). The waterfall then under-allocates to other devices.
**Why it happens:** `_waterfall()` uses `rated_power` of all eligible devices. If a binary device is "on" but still starting, its power is phantom.
**How to avoid:** During startup grace period, exclude the device from the waterfall's eligible list (or treat its rated_power as 0 temporarily). After `startup_until_ts` expires, it re-enters the waterfall normally.

### Pitfall 5: Disable (enable=False) Must Also Handle Binary Devices

**What goes wrong:** When Venus OS disables throttling (`enable=False`), the current code sends `write_power_limit(False, 100.0)` to all eligible devices. For binary devices this is a no-op.
**Why it happens:** `write_power_limit()` on Shelly returns success without doing anything.
**How to avoid:** In the `enable=False` path, detect binary devices and call `switch(True)` (turn relay ON = no throttling) instead of `write_power_limit`.

## Code Examples

### Binary Dispatch in distribute()

```python
async def distribute(self, limit_pct: float, enable: bool) -> None:
    self.sync_devices()
    self._global_limit_pct = limit_pct
    self._enabled = enable

    if not enable:
        for ds in self._device_states.values():
            if self._is_throttle_eligible(ds):
                if self._is_binary_device(ds):
                    await self._send_binary_command(ds.device_id, turn_on=True)
                else:
                    await self._send_limit(ds.device_id, 100.0, enable=False)
        return

    total_rated = sum(
        ds.entry.rated_power
        for ds in self._device_states.values()
        if ds.entry.enabled and ds.entry.rated_power > 0
        and not self._is_in_startup(ds)  # exclude startup devices
    )
    if total_rated <= 0:
        return

    allowed_watts = (limit_pct / 100.0) * total_rated
    targets = self._waterfall(allowed_watts)

    # Separate proportional and binary targets
    binary_on = []
    binary_off = []
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
```

### Test Pattern: Binary Cooldown

```python
@pytest.mark.asyncio
async def test_binary_cooldown_prevents_flapping():
    """Binary device cannot toggle within cooldown period."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    # First: throttle -> shelly OFF
    await dist.distribute(50.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1  # OFF

    # Second: release -> shelly should come back ON, but cooldown prevents it
    await dist.distribute(100.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1  # still 1, cooldown active
```

### Test Pattern: Startup Grace Period

```python
@pytest.mark.asyncio
async def test_startup_grace_excludes_from_waterfall():
    """Device in startup grace period not counted in available power."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),  # startup_delay_s=30
    ])

    # Turn shelly ON (triggers startup grace)
    # ... manipulate state to simulate recent toggle ...
    ds = dist._device_states["shelly"]
    ds.relay_on = True
    ds.startup_until_ts = time.monotonic() + 30.0  # 30s from now

    # Waterfall should NOT count shelly's 800W as available
    targets = dist._waterfall(15000)
    # Only se30k in waterfall -> 15000/30000 = 50%
    assert "shelly" not in targets or targets.get("shelly", 0) == 0
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_distributor.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| THRT-04 | Binary device gets switch(False) when waterfall assigns 0% | unit | `python -m pytest tests/test_distributor.py -x -k binary` | Extend existing |
| THRT-05 | Cooldown prevents toggle within cooldown_s period | unit | `python -m pytest tests/test_distributor.py -x -k cooldown` | Extend existing |
| THRT-06 | Startup delay grace period + reverse re-enable order | unit | `python -m pytest tests/test_distributor.py -x -k startup_or_reenable` | Extend existing |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_distributor.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] Extend `tests/test_distributor.py` -- add binary device helper (`_build_distributor_with_binary`) that creates mock plugins with `throttle_capabilities` and `switch()` method
- [ ] Add test cases for: binary dispatch, cooldown enforcement, startup grace, reverse re-enable, disable path with binary devices

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/pv_inverter_proxy/distributor.py` -- current waterfall algorithm (261 lines)
- Project codebase: `src/pv_inverter_proxy/plugin.py` -- ThrottleCaps, InverterPlugin ABC with `throttle_capabilities`
- Project codebase: `src/pv_inverter_proxy/plugins/shelly.py` -- `switch()` method (line 248), `throttle_capabilities` (line 266)
- Project codebase: `src/pv_inverter_proxy/config.py` -- InverterEntry with `throttle_dead_time_s` (distinct from cooldown)
- Project codebase: `tests/test_distributor.py` -- existing test patterns and helpers
- Phase 33 research: `.planning/phases/33-device-throttle-capabilities-scoring/33-RESEARCH.md`

### Secondary (MEDIUM confidence)
- Python stdlib `time.monotonic()` -- clock source for cooldown/startup timing (not affected by NTP adjustments)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pure Python, no new dependencies, extends existing patterns
- Architecture: HIGH - clear extension of existing distributor, all integration points understood
- Pitfalls: HIGH - identified from actual code paths (especially the cooldown vs dead-time confusion and switch() availability)
- Reverse re-enable: MEDIUM - straightforward sorting but only testable with multiple binary devices (currently only Shelly exists)

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable -- no external dependencies)
