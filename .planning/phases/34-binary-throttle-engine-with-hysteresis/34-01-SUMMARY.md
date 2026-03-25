---
phase: 34-binary-throttle-engine-with-hysteresis
plan: 01
subsystem: power-distribution
tags: [binary-throttle, relay-control, hysteresis, cooldown, waterfall]

# Dependency graph
requires:
  - phase: 33-device-throttle-capabilities-scoring
    provides: ThrottleCaps dataclass, compute_throttle_score(), hasattr guard pattern
provides:
  - Binary throttle dispatch in PowerLimitDistributor via switch() commands
  - Cooldown hysteresis preventing relay flapping (configurable per device)
  - Startup grace period excluding device from waterfall during power-up
  - Reverse throttle_score re-enable ordering for multiple binary devices
affects: [35-smart-auto-throttle-algorithm, 36-auto-throttle-ui-live-tuning]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Binary vs proportional dispatch split in distribute() method"
    - "Monotonic timestamp cooldown guard for relay protection"
    - "Startup grace exclusion from waterfall eligible list"

key-files:
  created: []
  modified:
    - src/pv_inverter_proxy/distributor.py
    - tests/test_distributor.py

key-decisions:
  - "Separate dispatch paths: switch() for binary, write_power_limit() for proportional -- no conflation"
  - "Cooldown uses ThrottleCaps.cooldown_s (intrinsic device property), not InverterEntry.throttle_dead_time_s (config)"
  - "Startup grace excludes device from both waterfall eligible list and total_rated calculation"

patterns-established:
  - "_is_binary_device() check via hasattr + throttle_capabilities.mode == binary"
  - "_send_binary_command() with cooldown guard and startup_until_ts tracking"
  - "_sort_binary_reenable() for reverse throttle_score ordering"

requirements-completed: [THRT-04, THRT-05, THRT-06]

# Metrics
duration: 6min
completed: 2026-03-25
---

# Phase 34 Plan 01: Binary Throttle Engine Summary

**Binary relay dispatch with 300s cooldown hysteresis, startup grace period, and reverse-order re-enable for Shelly devices in PowerLimitDistributor**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-25T16:41:22Z
- **Completed:** 2026-03-25T16:47:49Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Binary devices receive switch(on/off) commands instead of write_power_limit when waterfall assigns 0% or >0%
- Cooldown timer prevents relay toggle within cooldown_s (300s for Shelly) of last toggle
- Startup grace period (30s) excludes device from waterfall available power calculation
- Re-enable happens in reverse throttle_score order (lowest score first)
- enable=False turns binary relays ON (no throttling)
- All existing proportional device tests pass without modification (no regression)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests for binary throttle behavior** - `a4aa8c3` (test) - 8 test cases, RED phase
2. **Task 2: Implement binary throttle engine in distributor** - `2383ca9` (feat) - GREEN phase, all 17 tests pass

## Files Created/Modified
- `src/pv_inverter_proxy/distributor.py` - Extended with binary dispatch, cooldown guard, startup grace, reverse re-enable
- `tests/test_distributor.py` - Added 8 binary throttle test cases with _build_distributor_with_binary helper

## Decisions Made
- Separate dispatch paths for binary vs proportional -- switch() and write_power_limit() kept independent
- Used ThrottleCaps.cooldown_s for binary cooldown (not InverterEntry.throttle_dead_time_s which is for proportional buffering)
- Startup grace period excludes device from both waterfall and total_rated -- prevents phantom power allocation

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Binary throttle engine complete and tested
- Ready for Phase 35 (smart auto-throttle algorithm) which builds on binary+proportional dispatch
- Ready for Phase 36 (auto-throttle UI) which exposes binary device status

---
*Phase: 34-binary-throttle-engine-with-hysteresis*
*Completed: 2026-03-25*

## Self-Check: PASSED
