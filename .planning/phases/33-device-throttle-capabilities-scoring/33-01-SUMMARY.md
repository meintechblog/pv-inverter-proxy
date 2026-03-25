---
phase: 33-device-throttle-capabilities-scoring
plan: 01
subsystem: plugin
tags: [dataclass, throttle, scoring, abc, tdd]

requires:
  - phase: 28-plugin-core-profiles
    provides: InverterPlugin ABC, ShellyPlugin with profile system
provides:
  - ThrottleCaps frozen dataclass with mode/response_time_s/cooldown_s/startup_delay_s
  - compute_throttle_score function (0-10 bounded)
  - Abstract throttle_capabilities property on InverterPlugin ABC
  - All 3 plugins implement throttle_capabilities with hardcoded values
affects: [34-binary-throttle-engine-with-hysteresis, 35-smart-auto-throttle-algorithm]

tech-stack:
  added: []
  patterns: [frozen dataclass for capability declaration, numeric scoring function for device comparison]

key-files:
  created:
    - tests/test_throttle_caps.py
  modified:
    - src/pv_inverter_proxy/plugin.py
    - src/pv_inverter_proxy/plugins/solaredge.py
    - src/pv_inverter_proxy/plugins/opendtu.py
    - src/pv_inverter_proxy/plugins/shelly.py
    - tests/test_plugin.py

key-decisions:
  - "Scoring formula: proportional base=7, binary base=3, none=0 with response/cooldown/startup penalties"
  - "ThrottleCaps is frozen (immutable) to prevent runtime mutation"

patterns-established:
  - "Plugin capability declaration: each plugin declares static capabilities via @property returning frozen dataclass"
  - "Throttle scoring: compute_throttle_score ranks devices for regulation priority"

requirements-completed: [THRT-01, THRT-02]

duration: 2min
completed: 2026-03-25
---

# Phase 33 Plan 01: Device Throttle Capabilities Scoring Summary

**ThrottleCaps frozen dataclass with scoring function on InverterPlugin ABC -- SolarEdge 9.7, OpenDTU 7.0, Shelly 2.9**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-25T15:50:28Z
- **Completed:** 2026-03-25T15:53:22Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- ThrottleCaps frozen dataclass with ThrottleMode type alias (proportional/binary/none)
- compute_throttle_score function producing bounded 0-10 scores with response/cooldown/startup factors
- Abstract throttle_capabilities property on InverterPlugin ABC
- All 3 plugins implement throttle_capabilities: SolarEdge (proportional/1s), OpenDTU (proportional/10s), Shelly (binary/0.5s/300s/30s)
- 7 dedicated tests for scoring logic, all existing tests pass (87 total)

## Task Commits

Each task was committed atomically:

1. **Task 1: ThrottleCaps dataclass, scoring function, and tests** - `dbe07d8` (test: RED), `e9cccf8` (feat: GREEN)
2. **Task 2: Implement throttle_capabilities on all three plugins** - `b52e94a` (feat)

## Files Created/Modified
- `src/pv_inverter_proxy/plugin.py` - Added ThrottleCaps, ThrottleMode, compute_throttle_score, abstract property
- `src/pv_inverter_proxy/plugins/solaredge.py` - throttle_capabilities returning proportional/1s/0s/0s
- `src/pv_inverter_proxy/plugins/opendtu.py` - throttle_capabilities returning proportional/10s/0s/0s
- `src/pv_inverter_proxy/plugins/shelly.py` - throttle_capabilities returning binary/0.5s/300s/30s
- `tests/test_throttle_caps.py` - 7 tests for ThrottleCaps and compute_throttle_score
- `tests/test_plugin.py` - DummyPlugin updated with throttle_capabilities property

## Decisions Made
- Scoring formula uses base scores (proportional=7, binary=3, none=0) with additive response bonus and subtractive penalties for cooldown and startup delay
- ThrottleCaps is frozen dataclass to ensure immutability of declared capabilities

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ThrottleCaps data model ready for Phase 34 (binary throttle engine) to consume
- compute_throttle_score ready for Phase 35 (auto-throttle algorithm) to use for device ranking
- No blockers

## Self-Check: PASSED

All 6 files found. All 3 commits verified. Key content (ThrottleCaps, compute_throttle_score, throttle_capabilities) confirmed in source.

---
*Phase: 33-device-throttle-capabilities-scoring*
*Completed: 2026-03-25*
