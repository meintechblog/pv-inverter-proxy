---
phase: 29-switch-control-config-wiring
plan: 01
subsystem: api
tags: [shelly, rest-api, aiohttp, relay-control, plugin]

# Dependency graph
requires:
  - phase: 28-plugin-core-profiles
    provides: ShellyPlugin with Gen1/Gen2 profiles and ShellyProfile.switch() abstract method
provides:
  - ShellyPlugin.switch() public method delegating to profile
  - POST /api/devices/{id}/shelly/switch endpoint
  - throttle_enabled=False default for Shelly devices
affects: [30-device-dashboard-frontend, 31-aggregation-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [shelly-switch-delegation, plugin-specific-route-pattern]

key-files:
  created: []
  modified:
    - src/pv_inverter_proxy/plugins/shelly.py
    - src/pv_inverter_proxy/webapp.py
    - tests/test_shelly_plugin.py
    - tests/test_webapp.py

key-decisions:
  - "ShellyPlugin.switch() wraps profile.switch() with session/host injection and error handling"
  - "Shelly devices default throttle_enabled=False since they only support on/off, not percentage limiting"
  - "Status MPPT/SLEEPING from Phase 28 register encoding is sufficient for CTRL-02 (no backend change needed)"

patterns-established:
  - "Plugin-specific route pattern: /api/devices/{id}/{plugin}/action with isinstance type check"

requirements-completed: [CTRL-01, CTRL-02, CTRL-03]

# Metrics
duration: 5min
completed: 2026-03-24
---

# Phase 29 Plan 01: Switch Control & Config Wiring Summary

**Shelly relay on/off control wired from webapp REST API through ShellyPlugin.switch() to profile-level HTTP commands, with throttle_enabled=False default for Shelly devices**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-24T00:44:31Z
- **Completed:** 2026-03-24T00:49:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- ShellyPlugin.switch(on) delegates to profile.switch() with error handling and disconnected-state guard
- POST /api/devices/{id}/shelly/switch endpoint with full input validation (404/400/200)
- Shelly devices added via API default to throttle_enabled=False (excluded from power-limit waterfall)
- 12 new tests (4 unit for switch delegation, 8 integration for route + throttle default), all passing

## Task Commits

Each task was committed atomically (TDD: RED then GREEN):

1. **Task 1: ShellyPlugin.switch() method** - `e8733d1` (test/RED), `12c3d7f` (feat/GREEN)
2. **Task 2: shelly_switch_handler route + throttle default** - `839f9ae` (test/RED), `c06aa3a` (feat/GREEN)

## Files Created/Modified
- `src/pv_inverter_proxy/plugins/shelly.py` - Added switch() method with profile delegation and error handling
- `src/pv_inverter_proxy/webapp.py` - Added ShellyPlugin import, shelly_switch_handler, route registration, throttle_enabled default
- `tests/test_shelly_plugin.py` - Added TestSwitchControl class with 4 tests
- `tests/test_webapp.py` - Added TestShellySwitchRoute (6 tests) and TestShellyThrottleDefault (2 tests)

## Decisions Made
- ShellyPlugin.switch() returns False (not raises) on error/disconnected -- matches existing poll() error pattern
- CTRL-02 (status visibility) requires no backend changes -- Phase 28 register encoding already sets MPPT/SLEEPING
- throttle_enabled defaults via expression `dev_type != "shelly"` -- extensible for future non-throttleable types

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test for non-Shelly device check**
- **Found during:** Task 2 (shelly_switch_handler tests)
- **Issue:** Test used "default" device from shared_ctx which has plugin=None, hitting 404 path instead of 400 type-check path
- **Fix:** Created explicit OpenDTU mock device for the non-Shelly type check test
- **Files modified:** tests/test_webapp.py
- **Verification:** Test passes, correctly exercises the isinstance check path
- **Committed in:** c06aa3a (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix in test)
**Impact on plan:** Minor test fixture correction. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Switch control API ready for frontend integration (Phase 30 dashboard)
- Device snapshot already shows MPPT/SLEEPING status for relay state visualization
- throttle_enabled=False ensures Shelly devices are excluded from power-limit waterfall

---
*Phase: 29-switch-control-config-wiring*
*Completed: 2026-03-24*
