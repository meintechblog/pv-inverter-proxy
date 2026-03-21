---
phase: 23-power-limit-distribution
plan: 01
subsystem: power-control
tags: [waterfall, throttling-order, dead-time, asyncio, distributor]

requires:
  - phase: 22-device-registry-aggregation
    provides: DeviceRegistry with ManagedDevice access and InverterPlugin interface
provides:
  - PowerLimitDistributor class with waterfall algorithm
  - DeviceLimitState per-device limit tracking
  - Config fields throttle_order, throttle_enabled, throttle_dead_time_s on InverterEntry
affects: [23-02-wiring, 24-config-ui]

tech-stack:
  added: []
  patterns: [waterfall-distribution, dead-time-buffering, latest-wins]

key-files:
  created:
    - src/venus_os_fronius_proxy/distributor.py
    - tests/test_distributor.py
  modified:
    - src/venus_os_fronius_proxy/config.py
    - tests/test_config.py

key-decisions:
  - "DeviceLimitState.last_write_ts defaults to None (not 0.0) to avoid false dead-time on first write"
  - "Waterfall walks TO ascending: TO 1 gets budget first, throttled first when budget < rated"
  - "Monitoring-only devices included in total_rated for pct-to-watt conversion but excluded from limit writes"

patterns-established:
  - "Waterfall distribution: sort by TO, groupby, allocate min(group_rated, remaining) per group"
  - "Dead-time buffering: latest-wins with flush_pending() for expired buffers"

requirements-completed: [PWR-01, PWR-02, PWR-03, PWR-04]

duration: 4min
completed: 2026-03-21
---

# Phase 23 Plan 01: PowerLimitDistributor Summary

**Waterfall power limit distributor with TO-based throttling order, dead-time buffering, monitoring-only exclusion, and offline failover**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T07:28:34Z
- **Completed:** 2026-03-21T07:32:25Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- PowerLimitDistributor class implementing waterfall algorithm by Throttling Order
- 9 unit tests covering all PWR-01 through PWR-04 requirement behaviors
- Config fields (throttle_order, throttle_enabled, throttle_dead_time_s) added to InverterEntry with correct defaults
- Dead-time buffering with latest-wins semantics and flush_pending() method

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests** - `da3fe42` (test)
2. **Task 1 GREEN: Implementation** - `382f1d7` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/distributor.py` - PowerLimitDistributor with waterfall, dead-time, offline handling
- `src/venus_os_fronius_proxy/config.py` - Added throttle_order, throttle_enabled, throttle_dead_time_s to InverterEntry
- `tests/test_distributor.py` - 9 tests for all PWR-* requirement behaviors
- `tests/test_config.py` - 3 new tests for throttle config field defaults and YAML loading

## Decisions Made
- DeviceLimitState.last_write_ts defaults to None instead of 0.0 to correctly handle the first write (no false dead-time trigger when time.monotonic() is near zero)
- Monitoring-only device power counts toward total_rated for percent-to-watt conversion (per user decision "Leistung zaehlt mit")
- Offline detection uses ConnectionManager.state pull model (checked at distribute time) rather than push callbacks

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed initial dead-time false trigger**
- **Found during:** Task 1 GREEN (tests failing)
- **Issue:** DeviceLimitState.last_write_ts=0.0 caused dead-time guard to trigger on first-ever write when time.monotonic() was near 0
- **Fix:** Changed last_write_ts default to None, added None check in _send_limit and flush_pending
- **Files modified:** src/venus_os_fronius_proxy/distributor.py
- **Verification:** test_dead_time_buffering and test_dead_time_flush both pass
- **Committed in:** 382f1d7

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Essential fix for correctness. No scope creep.

## Issues Encountered
- Pre-existing pymodbus import error in test_aggregation.py and test_connection.py (ModbusDeviceContext import) prevented full test suite run on dev machine. Not caused by this plan's changes. Distributor and config tests verified independently (39 tests pass).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PowerLimitDistributor ready for wiring into StalenessAwareSlaveContext (Plan 23-02)
- All PWR-* requirement behaviors tested and passing
- Config fields automatically picked up from YAML via existing field filtering

---
*Phase: 23-power-limit-distribution*
*Completed: 2026-03-21*
