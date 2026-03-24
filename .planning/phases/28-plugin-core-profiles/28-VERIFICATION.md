---
phase: 28-plugin-core-profiles
verified: 2026-03-24T00:00:00Z
status: passed
score: 7/7 must-haves verified
re_verification: false
---

# Phase 28: Plugin Core & Profiles Verification Report

**Phase Goal:** A working ShellyPlugin can connect to any Shelly device, auto-detect its generation, poll energy data, and encode it as SunSpec registers
**Verified:** 2026-03-24
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ShellyPlugin implements InverterPlugin ABC and can be instantiated | VERIFIED | `class ShellyPlugin(InverterPlugin)` in `shelly.py:36`; all 7 ABC methods present; `TestABCCompliance` (3 tests) green |
| 2 | Auto-detection distinguishes Gen1 (no gen field) from Gen2+ (gen>=2) | VERIFIED | `shelly.py:65-86`: probes `/shelly`, reads `data.get("gen", 0)`, selects Gen2Profile if `>= 2` else Gen1Profile; `TestAutoDetection` (5 tests) green |
| 3 | Gen1Profile polls /status and extracts power/voltage/current/energy/temp/relay | VERIFIED | `shelly_profiles.py:56-72`: GET `/status`, extracts all fields with `.get()` defaults; `/ 60.0` Watt-minutes to Wh conversion at line 69 |
| 4 | Gen2Profile polls /rpc/Switch.GetStatus?id=0 and extracts all fields | VERIFIED | `shelly_profiles.py:96-116`: GET `/rpc/Switch.GetStatus?id=0`; reads `apower/voltage/current/freq/aenergy.total/output/temperature.tC` |
| 5 | Poll returns PollResult with SunSpec Model 103 registers identical to OpenDTU layout | VERIFIED | `_encode_model_103` returns 52-register list; register offsets match plan spec (current@2, voltage@10, power@14, freq@16, energy acc32@24-25, temp@33, status@38); `TestRegisterEncoding` (9 tests) green |
| 6 | Energy counter resets are detected and offset-tracked so total never decreases | VERIFIED | `_track_energy` at `shelly.py:116-127`: when `raw < last`, accumulates `_energy_offset_wh`; `TestEnergyTracking` (4 tests) including multi-reset scenario green |
| 7 | Missing fields (temp, voltage, current) produce 0.0 defaults, no crash | VERIFIED | All fields use `.get(key, 0.0)` pattern; Gen1 minimal response (no voltage/current/temp) handled; Gen2 missing temperature/energy handled; `TestMissingFields` (5 tests) green |

**Score: 7/7 truths verified**

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pv_inverter_proxy/plugins/shelly_profiles.py` | ShellyProfile ABC + Gen1Profile + Gen2Profile | VERIFIED | File exists, 131 lines. Exports `ShellyPollData`, `ShellyProfile`, `Gen1Profile`, `Gen2Profile`. All three classes fully implemented, not stubs. |
| `src/pv_inverter_proxy/plugins/shelly.py` | ShellyPlugin implementing InverterPlugin ABC | VERIFIED | File exists, 250 lines. `ShellyPlugin(InverterPlugin)` with all 7 ABC methods plus private helpers `_track_energy`, `_encode_model_103`, `_build_common_registers`. |
| `tests/test_shelly_plugin.py` | Unit tests for all PLUG-01 through PLUG-07 | VERIFIED | File exists, 563 lines. Contains `TestABCCompliance`, `TestProfiles`, `TestAutoDetection`, `TestPollSuccess`, `TestRegisterEncoding`, `TestEnergyTracking`, `TestMissingFields` plus 3 bonus test classes. 39 tests total, all passing. |
| `src/pv_inverter_proxy/config.py` | `shelly_gen` field on InverterEntry | VERIFIED | Line 45: `shelly_gen: str = ""` with comment |
| `src/pv_inverter_proxy/plugins/__init__.py` | `elif entry.type == "shelly"` branch in plugin_factory | VERIFIED | Lines 40-47: complete `elif` branch with lazy import and correct constructor call |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `shelly.py` | `shelly_profiles.py` | `from pv_inverter_proxy.plugins.shelly_profiles import` | WIRED | Lines 17-22 import `Gen1Profile`, `Gen2Profile`, `ShellyPollData`, `ShellyProfile`; all four are used in implementation |
| `plugins/__init__.py` | `shelly.py` | lazy import in `elif entry.type == "shelly"` branch | WIRED | Line 41: `from pv_inverter_proxy.plugins.shelly import ShellyPlugin`; line 42-47 instantiates and returns it |
| `shelly.py` | `plugin.py` | `class ShellyPlugin(InverterPlugin)` | WIRED | Line 36; all 7 abstract methods are concretely implemented — `connect`, `poll`, `close`, `write_power_limit`, `get_static_common_overrides`, `get_model_120_registers`, `reconfigure` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PLUG-01 | 28-01-PLAN.md | ShellyPlugin implements InverterPlugin ABC (all 7 methods) | SATISFIED | `issubclass(ShellyPlugin, InverterPlugin)` confirmed; `TestABCCompliance` 3/3 pass |
| PLUG-02 | 28-01-PLAN.md | Gen1/Gen2 profile system with correct API endpoints | SATISFIED | Gen1 uses `/status` + `/relay/0`, Gen2 uses `/rpc/Switch.*`; `TestProfiles` 4/4 pass |
| PLUG-03 | 28-01-PLAN.md | Auto-detection via GET /shelly (gen field presence) | SATISFIED | `connect()` probes `/shelly`, `gen >= 2` → Gen2Profile, no `gen` field → Gen1Profile; `TestAutoDetection` 5/5 pass |
| PLUG-04 | 28-01-PLAN.md | Poll returns power, voltage, current, frequency, energy, temperature | SATISFIED | All 6 values extracted by both profiles and encoded in PollResult; `TestPollSuccess` 3/3 pass |
| PLUG-05 | 28-01-PLAN.md | SunSpec Model 103 register encoding matching OpenDTU layout | SATISFIED | `_encode_model_103` with verified offsets; `TestRegisterEncoding` 9/9 pass |
| PLUG-06 | 28-01-PLAN.md | Energy counter offset tracking for Shelly device reboots | SATISFIED | `_track_energy` detects resets (`raw < last`), accumulates offset; `TestEnergyTracking` 4/4 pass |
| PLUG-07 | 28-01-PLAN.md | Missing fields (Gen1 less data, no temp on some models) produce 0.0 defaults | SATISFIED | All field access via `.get(key, 0.0)`; `TestMissingFields` 5/5 pass |

**No orphaned requirements:** REQUIREMENTS.md maps PLUG-01 through PLUG-07 to Phase 28, all 7 are claimed and verified. CTRL-*, UI-*, and AGG-* requirements are correctly deferred to Phases 29-32.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No stubs, placeholders, or hardcoded empty returns found in phase deliverables |

Scan notes:
- `write_power_limit()` returns `WriteResult(success=True)` with no HTTP call — this is documented and intentional behavior, not a stub. The method's docstring explicitly states "No-op: Shelly cannot do percentage-based power limiting."
- DC registers are all zero — also documented and intentional (Shelly only measures AC). Phase 32 (AGG-02) will handle DC averaging skip.

---

### Human Verification Required

None — all phase requirements are backend/unit-testable. Real device connectivity is out of scope for this phase.

---

### Full Test Run Results

```
uv run pytest tests/test_shelly_plugin.py -v
39 passed in 0.26s

uv run pytest tests/ -v
510 passed, 432 warnings in 39.54s  (no regressions)
```

Plugin factory smoke test:
```
uv run python -c "...plugin_factory(InverterEntry(type='shelly', host='192.168.1.100'))"
ShellyPlugin
```

---

### Gaps Summary

No gaps. All 7 must-have truths verified, all 5 artifacts exist and are substantive and wired, all 7 requirement IDs satisfied with passing test evidence.

---

_Verified: 2026-03-24_
_Verifier: Claude (gsd-verifier)_
