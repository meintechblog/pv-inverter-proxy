# Phase 35: Smart Auto-Throttle Algorithm - Research

**Researched:** 2026-03-25
**Domain:** Python asyncio, waterfall algorithm extension, live convergence measurement, scoring-based device ordering
**Confidence:** HIGH

## Summary

Phase 35 introduces an "Auto" mode to the `PowerLimitDistributor` that replaces manual `throttle_order` with dynamic ordering based on `throttle_score`. When auto-throttle is enabled, the distributor sorts devices by score descending (fastest first), creating a two-tier waterfall: proportional devices (SolarEdge=9.7, OpenDTU=7.0) are exhausted first for fine-grained regulation, then binary devices (Shelly=2.9) act as last-resort coarse controls.

The second major component is live response-time measurement: after sending a limit command, the distributor tracks how quickly each device's actual power converges to the target (Soll-Ist convergence). This measured response time feeds back into `compute_throttle_score()` to dynamically adjust device ranking based on real-world behavior rather than preset values.

The algorithm must converge to the target power within 3 poll cycles for proportional devices (~3s at 1s poll interval). This means the distributor sends the correct percentage on the first command; the 3-cycle constraint is about the physical device reaching the setpoint, not about iterative adjustments.

**Primary recommendation:** Add `auto_throttle: bool` to Config (persisted in YAML, editable via webapp API). When enabled, override `_waterfall()` to sort eligible devices by throttle_score descending instead of `throttle_order`. Add per-device convergence tracking in `DeviceLimitState` (target_power_w, target_set_ts, measured_response_time_s). After each poll, compare actual power to target power; when converged, compute elapsed time and update a running average. Feed `measured_response_time_s` into `compute_throttle_score()` when available, overriding the preset `response_time_s`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| THRT-07 | When auto_throttle is enabled, distributor ignores manual throttle_order and uses throttle_score ranking instead | Add `auto_throttle` bool to Config; in `_waterfall()`, sort eligible devices by `compute_throttle_score()` descending instead of `entry.throttle_order` ascending |
| THRT-08 | Waterfall first exhausts proportional devices (highest score first), then falls through to binary devices | Score-based ordering naturally achieves this: proportional base=7 > binary base=3. Proportional devices always score higher than binary, so they appear first in the waterfall |
| THRT-09 | Live response-time measurement updates throttle_score based on actual Soll-Ist convergence speed | Track per-device `target_power_w` and `target_set_ts` in DeviceLimitState; after poll shows convergence, compute elapsed time; feed into `compute_throttle_score()` via optional `measured_response_time_s` override |
</phase_requirements>

## Architecture Patterns

### Current Waterfall Flow (Phase 34 baseline)

```
distribute(limit_pct, enable)
  -> sync_devices()
  -> _waterfall(allowed_watts)
     -> eligible sorted by entry.throttle_order ASC  <-- MANUAL
     -> groupby throttle_order
     -> TO1 gets budget first, then TO2, etc.
  -> dispatch: proportional via write_power_limit(), binary via switch()
```

### Recommended Auto-Throttle Flow (Phase 35)

```
distribute(limit_pct, enable)
  -> sync_devices()
  -> _waterfall(allowed_watts)
     -> IF auto_throttle:
          eligible sorted by throttle_score DESC     <-- AUTOMATIC
          NO groupby (each device is its own priority tier)
        ELSE:
          existing throttle_order logic (unchanged)
  -> dispatch (unchanged from Phase 34)
  -> _record_target(device_id, target_watts)         <-- NEW: convergence tracking

on_poll(device_id, actual_power_w)                   <-- NEW: called from poll loop
  -> _check_convergence(device_id, actual_power_w)
  -> if converged: update measured_response_time_s
```

### Recommended Project Structure Changes

```
config.py              -- ADD: auto_throttle field to Config (not InverterEntry)
distributor.py         -- MODIFY: _waterfall() for score-based ordering
                          ADD: convergence tracking in DeviceLimitState
                          ADD: _record_target(), on_poll(), _check_convergence()
plugin.py              -- MODIFY: compute_throttle_score() to accept optional
                          measured_response_time_s override
webapp.py              -- MODIFY: config save/load for auto_throttle field
                          MODIFY: virtual snapshot to expose auto_throttle state
device_registry.py     -- MODIFY: poll loop calls distributor.on_poll() after collect
tests/test_distributor.py  -- EXTEND: auto-throttle ordering + convergence tests
```

### Pattern 1: Auto-Throttle Config Field

**What:** A single boolean `auto_throttle` on the `Config` dataclass (global, not per-device).
**Why on Config:** This is a system-wide mode, not a per-device setting. It replaces the manual ordering strategy entirely.

```python
# In config.py, on the Config dataclass:
auto_throttle: bool = False  # True = score-based ordering, False = manual throttle_order
```

This persists to `config.yaml` and is editable via the webapp config API (Phase 36 adds UI toggle, but Phase 35 must have the API ready).

### Pattern 2: Score-Based Waterfall Ordering

**What:** When `auto_throttle=True`, sort eligible devices by `compute_throttle_score()` descending. Each device is its own priority tier (no grouping).

```python
def _waterfall(self, allowed_watts: float) -> dict[str, float]:
    eligible = [
        ds for ds in self._device_states.values()
        if ds.entry.throttle_enabled and ds.is_online and ds.entry.rated_power > 0
        and not self._is_in_startup(ds)
    ]

    if self._config.auto_throttle:
        # Score-based: highest score first (fastest regulation first)
        eligible.sort(key=lambda ds: self._effective_score(ds), reverse=True)
        return self._waterfall_sequential(eligible, allowed_watts)
    else:
        # Manual: existing throttle_order groupby logic
        eligible.sort(key=lambda ds: ds.entry.throttle_order)
        return self._waterfall_grouped(eligible, allowed_watts)
```

**Why sequential (not grouped):** In auto mode, each device has a unique score. Grouping makes no sense -- devices are processed one-by-one in score order. The highest-scored device (SolarEdge, 9.7) gets budget first. If it can absorb all the throttling, lower-scored devices run at 100%. If not, the next device takes the remaining cut.

```python
def _waterfall_sequential(self, eligible: list[DeviceLimitState], allowed_watts: float) -> dict[str, float]:
    """Score-based waterfall: each device is its own tier."""
    result: dict[str, float] = {}
    remaining = allowed_watts

    for ds in eligible:
        if remaining >= ds.entry.rated_power:
            result[ds.device_id] = 100.0
            remaining -= ds.entry.rated_power
        else:
            pct = max(0.0, min(100.0, (remaining / ds.entry.rated_power) * 100.0))
            result[ds.device_id] = round(pct, 1)
            remaining = 0.0

        if remaining <= 0:
            break

    # Remaining eligible devices get 0%
    for ds in eligible:
        if ds.device_id not in result:
            result[ds.device_id] = 0.0

    return result
```

### Pattern 3: Convergence Tracking

**What:** After sending a limit command, track when the device actually reaches the target power. Measure elapsed time = `measured_response_time_s`.

```python
# New fields on DeviceLimitState:
target_power_w: float | None = None      # Expected power after limit command
target_set_ts: float | None = None       # When limit was sent
measured_response_time_s: float | None = None  # Running average of measured response
_convergence_samples: list[float] = field(default_factory=list)  # Last N measurements
```

**Convergence detection logic:**

```python
CONVERGENCE_TOLERANCE_PCT = 5.0  # Within 5% of target = converged
CONVERGENCE_MAX_SAMPLES = 10    # Rolling window for averaging

def on_poll(self, device_id: str, actual_power_w: float) -> None:
    """Called after each poll with the device's measured AC power."""
    ds = self._device_states.get(device_id)
    if ds is None or ds.target_power_w is None or ds.target_set_ts is None:
        return

    # Check convergence: actual within tolerance of target
    if ds.target_power_w == 0:
        converged = actual_power_w < 50  # Near-zero threshold
    else:
        error_pct = abs(actual_power_w - ds.target_power_w) / ds.target_power_w * 100
        converged = error_pct <= CONVERGENCE_TOLERANCE_PCT

    if converged:
        elapsed = time.monotonic() - ds.target_set_ts
        ds._convergence_samples.append(elapsed)
        if len(ds._convergence_samples) > CONVERGENCE_MAX_SAMPLES:
            ds._convergence_samples.pop(0)
        ds.measured_response_time_s = sum(ds._convergence_samples) / len(ds._convergence_samples)
        ds.target_power_w = None  # Reset tracking
        ds.target_set_ts = None
```

**When to set target:** In `_send_limit()` and `_send_binary_command()`, after successful send:

```python
# In _send_limit(), after successful write:
ds.target_power_w = (limit_pct / 100.0) * ds.entry.rated_power
ds.target_set_ts = time.monotonic()

# In _send_binary_command(), after successful switch:
ds.target_power_w = ds.entry.rated_power if turn_on else 0.0
ds.target_set_ts = time.monotonic()
```

### Pattern 4: Score Override with Measured Response Time

**What:** When `measured_response_time_s` is available, use it instead of the preset `caps.response_time_s` for scoring.

```python
def _effective_score(self, ds: DeviceLimitState) -> float:
    """Compute effective throttle score, using measured data when available."""
    if not hasattr(ds.plugin, 'throttle_capabilities'):
        return 0.0
    caps = ds.plugin.throttle_capabilities
    if ds.measured_response_time_s is not None:
        # Create modified caps with measured response time
        measured_caps = ThrottleCaps(
            mode=caps.mode,
            response_time_s=ds.measured_response_time_s,
            cooldown_s=caps.cooldown_s,
            startup_delay_s=caps.startup_delay_s,
        )
        return compute_throttle_score(measured_caps)
    return compute_throttle_score(caps)
```

This approach does NOT modify `compute_throttle_score()` itself -- it creates a new `ThrottleCaps` with the measured value. The scoring function stays pure. The `_effective_score()` method on the distributor handles the override.

### Pattern 5: Integration with Poll Loop

**What:** The poll loop in `device_registry.py` must call `distributor.on_poll()` after each successful poll to feed convergence data.

```python
# In device_registry.py, after successful poll and collector update:
if result.success:
    # ... existing code ...
    # Feed convergence tracking (Phase 35)
    distributor = getattr(app_ctx, 'device_registry', None)
    if distributor is not None:
        # Extract AC power from poll data
        ac_power_w = _extract_ac_power(result.inverter_registers)
        distributor.on_poll(entry.id, ac_power_w)
```

The `_extract_ac_power()` helper decodes `ac_power_w` from Model 103 registers (register offset 14 with scale factor at offset 15), the same decoding already done in `aggregation.py`.

### Anti-Patterns to Avoid

- **Iterative convergence in the distributor:** The distributor should NOT try to "converge" by adjusting limits over multiple cycles. The waterfall computes the correct percentage on the first pass. The 3-cycle convergence criterion is about the physical device reaching the setpoint, not about software iteration.
- **Per-device auto_throttle flag:** Auto-throttle is a global strategy. Having per-device overrides creates confusing interactions. A device can still be excluded via `throttle_enabled=False`.
- **Modifying compute_throttle_score() signature:** Keep it pure. The distributor wraps it with `_effective_score()` to inject measured data. This preserves backward compatibility and testability.
- **Persisting measured_response_time_s to config:** This is ephemeral runtime data. It resets on restart. The preset values in `ThrottleCaps` serve as the cold-start defaults.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Running average | Custom statistics class | Simple list + sum/len | Only need mean of 10 samples, stdlib suffices |
| AC power decoding | Duplicate SunSpec decoder | Extract helper from `aggregation.py` decode logic | Same register layout already decoded there |
| Config persistence | Custom YAML serialization | Existing `save_config()` in `config.py` | `auto_throttle` is just another dataclass field, `asdict()` handles it |

## Common Pitfalls

### Pitfall 1: Score Ties Between Proportional Devices
**What goes wrong:** If SolarEdge and OpenDTU have similar measured response times, their scores could be close. The sort order becomes unstable.
**Why it happens:** Measured response times naturally fluctuate. Two devices might swap positions each cycle.
**How to avoid:** Use a stable sort (`sorted()` in Python is stable). Add `device_id` as a tiebreaker so order is deterministic.
**Warning signs:** Devices alternating throttle position in logs.

### Pitfall 2: Convergence Never Detected for Binary Devices
**What goes wrong:** Binary devices (Shelly) turn OFF (0W target) but the poll might still show residual power during shutdown, or turn ON but take 30s startup to reach rated power.
**Why it happens:** Binary devices have inherently different convergence patterns than proportional.
**How to avoid:** For binary OFF: use a generous threshold (< 50W = converged). For binary ON: only start convergence measurement after `startup_until_ts` expires. During startup grace, do not attempt convergence checking.

### Pitfall 3: Stale Target After Rapid Limit Changes
**What goes wrong:** Venus OS sends new limits every second. Each `distribute()` call sets new targets, resetting `target_set_ts`. The device never has time to converge before the target changes again.
**Why it happens:** The distributor is called frequently; if the waterfall output changes each time, convergence tracking resets.
**How to avoid:** Only reset target tracking when the target actually changes significantly (> 2% difference). If the new target is within tolerance of the current target, keep the existing `target_set_ts`.

### Pitfall 4: Auto-Throttle Interferes with Manual Override
**What goes wrong:** User has carefully set `throttle_order` for a specific reason (e.g., they want Shelly to be first to throttle despite low score). Enabling auto_throttle silently overrides this.
**Why it happens:** Auto mode replaces the manual strategy entirely.
**How to avoid:** When `auto_throttle` is enabled, the manual `throttle_order` values are completely ignored. This is by design. The UI (Phase 36) should make this clear. No hybrid mode -- it is either manual or auto.

### Pitfall 5: Polling Integration Creates Circular Import
**What goes wrong:** `device_registry.py` imports from `distributor.py`, and vice versa.
**Why it happens:** The poll loop needs to call `distributor.on_poll()`, and the distributor references the registry for managed devices.
**How to avoid:** The distributor already receives the registry as a constructor argument (`registry: object`). For the reverse direction, `device_registry.py` can access the distributor through `app_ctx` rather than importing it directly. Or pass the distributor reference into the poll loop via `app_ctx`.

## Code Examples

### Modified _waterfall() with Auto Mode

```python
def _waterfall(self, allowed_watts: float) -> dict[str, float]:
    eligible = [
        ds for ds in self._device_states.values()
        if ds.entry.throttle_enabled and ds.is_online and ds.entry.rated_power > 0
        and not self._is_in_startup(ds)
    ]

    if not eligible:
        return {}

    if self._config.auto_throttle:
        # Auto mode: sort by effective score descending, each device is own tier
        eligible.sort(key=lambda ds: (self._effective_score(ds), ds.device_id), reverse=True)

        result: dict[str, float] = {}
        remaining = allowed_watts

        for ds in eligible:
            if remaining >= ds.entry.rated_power:
                result[ds.device_id] = 100.0
                remaining -= ds.entry.rated_power
            else:
                pct = max(0.0, min(100.0, (remaining / ds.entry.rated_power) * 100.0))
                result[ds.device_id] = round(pct, 1)
                remaining = 0.0

            if remaining <= 0:
                break

        for ds in eligible:
            if ds.device_id not in result:
                result[ds.device_id] = 0.0

        return result
    else:
        # Manual mode: existing grouped waterfall (unchanged)
        return self._waterfall_grouped(eligible, allowed_watts)
```

### Convergence Tracking Test

```python
@pytest.mark.asyncio
async def test_auto_throttle_score_ordering():
    """Auto mode sorts by score: SE (9.7) > OpenDTU (7.0) > Shelly (2.9)."""
    dist, plugins = _build_distributor_with_binary([
        ("shelly", 800, 3, True, 0.0, "binary"),      # score 2.9
        ("se30k", 30000, 2, True, 0.0, "proportional"), # score 9.7
        ("opendtu", 800, 1, True, 0.0, "proportional"), # score 7.0
    ])

    # Enable auto_throttle
    dist._config.auto_throttle = True

    # 50% of total (31600W) = 15800W allowed
    # Auto order: se30k (9.7) first -> 15800W < 30000W -> 52.7%, remaining=0
    # opendtu: 0%, shelly: 0%
    await dist.distribute(50.0, enable=True)

    # SE30K gets throttled (sole absorber of limit)
    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert 50.0 < se_args[1] < 55.0

    # OpenDTU and Shelly get 0%
    opendtu_args = plugins["opendtu"].write_power_limit.call_args[0]
    assert abs(opendtu_args[1] - 0.0) < 0.1


@pytest.mark.asyncio
async def test_convergence_measurement():
    """After limit send, on_poll detects convergence and records response time."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
    ])
    dist._config.auto_throttle = True

    await dist.distribute(50.0, enable=True)

    ds = dist._device_states["se30k"]
    assert ds.target_power_w is not None  # ~15000W
    assert ds.target_set_ts is not None

    # Simulate poll showing converged power
    dist.on_poll("se30k", ds.target_power_w)  # exact match

    assert ds.measured_response_time_s is not None
    assert ds.measured_response_time_s >= 0.0
```

### Config Addition Test

```python
def test_auto_throttle_config_default_false():
    """auto_throttle defaults to False."""
    config = Config()
    assert config.auto_throttle is False

def test_auto_throttle_config_round_trip():
    """auto_throttle persists through YAML save/load."""
    config = Config(auto_throttle=True)
    data = asdict(config)
    assert data["auto_throttle"] is True
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_distributor.py -x -k auto_throttle` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| THRT-07 | Auto mode ignores throttle_order, uses score ranking | unit | `python -m pytest tests/test_distributor.py -x -k auto_throttle_ordering` | Extend existing |
| THRT-08 | Proportional devices exhausted before binary in waterfall | unit | `python -m pytest tests/test_distributor.py -x -k auto_proportional_before_binary` | Extend existing |
| THRT-09 | Live convergence measurement updates effective score | unit | `python -m pytest tests/test_distributor.py -x -k convergence` | Extend existing |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_distributor.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] Extend `tests/test_distributor.py` -- add auto-throttle ordering tests (THRT-07, THRT-08)
- [ ] Extend `tests/test_distributor.py` -- add convergence tracking tests (THRT-09)
- [ ] Add `auto_throttle` field to Config in `config.py` (must exist before tests)

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/pv_inverter_proxy/distributor.py` -- current waterfall with binary dispatch (346 lines)
- Project codebase: `src/pv_inverter_proxy/plugin.py` -- ThrottleCaps, compute_throttle_score (51 lines)
- Project codebase: `src/pv_inverter_proxy/config.py` -- Config dataclass with YAML persistence
- Project codebase: `src/pv_inverter_proxy/aggregation.py` -- AC power decoding from Model 103 registers
- Project codebase: `src/pv_inverter_proxy/device_registry.py` -- poll loop at line 233+
- Project codebase: `tests/test_distributor.py` -- existing test patterns and helpers (613 lines)
- Phase 33 research: `.planning/phases/33-device-throttle-capabilities-scoring/33-RESEARCH.md`
- Phase 34 research: `.planning/phases/34-binary-throttle-engine-with-hysteresis/34-RESEARCH.md`

### Secondary (MEDIUM confidence)
- Python `time.monotonic()` -- clock source for convergence timing
- SunSpec Model 103 specification -- register layout for AC power (offset 14, SF at offset 15)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pure Python, no new dependencies, extends existing patterns
- Architecture: HIGH - clear extension points identified in distributor, config, and poll loop
- Pitfalls: HIGH - identified from actual code paths and timing concerns
- Convergence tracking: MEDIUM - the tolerance threshold (5%) and sample window (10) may need tuning in practice

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable -- no external dependencies)
