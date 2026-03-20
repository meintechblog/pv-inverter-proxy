---
phase: 21-data-model-opendtu-plugin
plan: 02
subsystem: plugins
tags: [opendtu, hoymiles, aiohttp, sunspec, rest-api, tdd]

# Dependency graph
requires:
  - phase: 21-data-model-opendtu-plugin (plan 01)
    provides: InverterPlugin ABC, typed config model, plugin_factory stub
provides:
  - OpenDTUPlugin implementing InverterPlugin ABC for Hoymiles micro-inverters
  - JSON-to-SunSpec register encoding for Model 103
  - Power limiting via POST /api/limit/config with dead-time guard
  - plugin_factory opendtu branch (no longer raises NotImplementedError)
affects: [22-device-registry, 23-power-distribution, 24-device-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: [REST-to-SunSpec register synthesis, dead-time guard for power limiting, DC channel summation]

key-files:
  created:
    - src/venus_os_fronius_proxy/plugins/opendtu.py
    - tests/test_opendtu_plugin.py
  modified:
    - src/venus_os_fronius_proxy/plugins/__init__.py

key-decisions:
  - "DC channel summation: sum power+current, power-weighted average for voltage"
  - "Fixed scale factors for SunSpec encoding: SF=0 power, SF=-1 voltage, SF=-2 current/freq"
  - "Dead-time guard at 30s (25s typical + 5s margin per CONTEXT.md)"
  - "Model 120 WRtg defaults to 400W, updatable from /api/limit/status"

patterns-established:
  - "REST-to-SunSpec: poll JSON API, extract physical values, encode to uint16 register arrays with fixed scale factors"
  - "Dead-time guard: track last write timestamp + pending flag, suppress re-sends within DEAD_TIME_S"

requirements-completed: [DTU-01, DTU-02, DTU-03, DTU-04, DTU-05]

# Metrics
duration: 4min
completed: 2026-03-20
---

# Phase 21 Plan 02: OpenDTU Plugin Summary

**OpenDTU plugin polling Hoymiles via REST API with SunSpec register synthesis, serial filtering, power limiting with Basic Auth, and 30s dead-time guard**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-20T19:13:29Z
- **Completed:** 2026-03-20T19:17:42Z
- **Tasks:** 1 (TDD: test + implement)
- **Files modified:** 3

## Accomplishments
- OpenDTUPlugin implementing all 7 InverterPlugin ABC methods
- JSON-to-SunSpec Model 103 register encoding with correct scale factors for dashboard compatibility
- Serial-based filtering for multi-inverter OpenDTU gateways
- Power limiting via POST /api/limit/config with Basic Auth and 30s dead-time guard
- 25 unit tests covering all DTU requirements (DTU-01 through DTU-05)
- plugin_factory updated to create OpenDTUPlugin for type="opendtu"

## Task Commits

Each task was committed atomically (TDD workflow):

1. **Task 1 RED: Failing tests for OpenDTU plugin** - `248fd11` (test)
2. **Task 1 GREEN: Implement OpenDTU plugin** - `fe3fdbc` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/plugins/opendtu.py` - OpenDTU plugin: poll, register encoding, power limiting, session management (340 lines)
- `tests/test_opendtu_plugin.py` - 25 tests covering ABC compliance, polling, register encoding, power limits, dead-time, session lifecycle (509 lines)
- `src/venus_os_fronius_proxy/plugins/__init__.py` - Updated plugin_factory with opendtu branch and optional gateway_config param

## Decisions Made
- DC channel summation: sum power and current across channels, use power-weighted average for voltage (handles HM-400 1ch, HM-600/800 2ch, HMS-2000 4ch)
- Fixed SunSpec scale factors: SF=0 for power (W), SF=-1 for voltage (0.1V), SF=-2 for current (0.01A) and frequency (0.01Hz)
- Dead-time guard conservative at 30s (25s typical Hoymiles latency + 5s margin)
- Model 120 WRtg defaults to 400W, can be updated from /api/limit/status on connect
- Energy total: sum YieldTotal across DC channels, convert kWh to Wh for SunSpec acc32

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 21 complete: both plans (data model + OpenDTU plugin) done
- Ready for Phase 22 (DeviceRegistry): plugin_factory can create both SolarEdge and OpenDTU plugins
- Ready for Phase 23 (Power Distribution): write_power_limit works for both plugin types
- Exponential backoff retry logic deferred to Phase 22 DeviceRegistry (per plan)

---
*Phase: 21-data-model-opendtu-plugin*
*Completed: 2026-03-20*
