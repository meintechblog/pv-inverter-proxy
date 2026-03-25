---
phase: 37-distributor-wiring-dc-average-fix
plan: 01
subsystem: aggregation, wiring
tags: [distributor, dc-voltage, aggregation, power-limiting, shelly]

requires:
  - phase: 35-smart-auto-throttle-algorithm
    provides: PowerLimitDistributor class
  - phase: 34-binary-throttle-engine-with-hysteresis
    provides: Binary throttle dispatch for relay devices
provides:
  - AppContext.distributor field wired at runtime
  - registry._distributor set from __main__.py
  - DC voltage averaging excludes zero-DC devices (Shelly)
affects: [auto-throttle, shelly-aggregation, device-registry]

tech-stack:
  added: []
  patterns:
    - "DC-aware averaging: filter by dc_power_w > 0 before averaging dc_voltage_v"

key-files:
  created: []
  modified:
    - src/pv_inverter_proxy/context.py
    - src/pv_inverter_proxy/__main__.py
    - src/pv_inverter_proxy/aggregation.py
    - tests/test_aggregation.py

key-decisions:
  - "DC voltage averaging filters by dc_power_w > 0 to exclude Shelly relay devices"
  - "All-zero-DC case returns 0.0 safely (no division by zero)"

patterns-established:
  - "DC-aware aggregation: any metric that only applies to true inverters (not relays) should filter by dc_power_w > 0"

requirements-completed: [AGG-02, THRT-08, THRT-09]

duration: 2min
completed: 2026-03-25
---

# Phase 37 Plan 01: Distributor Wiring + DC Average Fix Summary

**Wire PowerLimitDistributor into AppContext and DeviceRegistry, fix DC voltage averaging to exclude Shelly zero-DC devices**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-25T21:04:00Z
- **Completed:** 2026-03-25T21:06:21Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- AppContext.distributor field added and wired in __main__.py so poll loop can reach the distributor
- registry._distributor set in __main__.py so webapp can read device limit states
- DC voltage averaging now skips devices with dc_power_w == 0 (Shelly relay devices)
- 3 new tests prove DC exclusion behavior (mixed fleet, all-zero, two-real)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire distributor into AppContext and DeviceRegistry** - `a0886fa` (feat)
2. **Task 2 RED: Add failing DC voltage tests** - `af3a527` (test)
3. **Task 2 GREEN: Fix DC voltage averaging** - `8f06bbe` (feat)

## Files Created/Modified
- `src/pv_inverter_proxy/context.py` - Added distributor: object = None field to AppContext
- `src/pv_inverter_proxy/__main__.py` - Added app_ctx.distributor and registry._distributor wiring
- `src/pv_inverter_proxy/aggregation.py` - Removed dc_voltage_v from avg_keys, added dc_power_w > 0 filter
- `tests/test_aggregation.py` - Added 3 tests for DC voltage zero-DC exclusion

## Decisions Made
- DC voltage averaging filters by dc_power_w > 0 to exclude Shelly relay devices that report 0V DC
- All-zero-DC case returns 0.0 safely rather than raising ZeroDivisionError

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three audit gaps (THRT-08, THRT-09, AGG-02) are closed
- Auto-throttle algorithm is now reachable at runtime via app_ctx.distributor
- Mixed Shelly+inverter fleets will get correct DC voltage readings

## Self-Check: PASSED

All 5 files found. All 3 commits verified.

---
*Phase: 37-distributor-wiring-dc-average-fix*
*Completed: 2026-03-25*
