---
phase: 05-data-pipeline-theme-foundation
plan: 01
subsystem: api
tags: [modbus, sunspec, timeseries, dashboard, rest, static-files]

requires:
  - phase: 04-webapp-register-viewer
    provides: webapp with shared_ctx, register cache, proxy poll loop
provides:
  - DashboardCollector decoding all Model 103 registers with signed int16 scale factors
  - TimeSeriesBuffer ring buffer (60-min deque) per metric
  - GET /api/dashboard REST endpoint returning decoded snapshot JSON
  - GET /static/{filename} handler serving CSS/JS with correct Content-Type
  - Poll loop integration feeding DashboardCollector after each successful poll
affects: [05-02-frontend-theme, 06-websocket-push]

tech-stack:
  added: []
  patterns: [DashboardCollector callback in poll loop, DECODE_MAP register address table, int16 scale factor conversion, uint32 two-register energy decoding, importlib.resources static serving with CONTENT_TYPES dict]

key-files:
  created:
    - src/venus_os_fronius_proxy/timeseries.py
    - src/venus_os_fronius_proxy/dashboard.py
    - tests/test_timeseries.py
    - tests/test_dashboard.py
  modified:
    - src/venus_os_fronius_proxy/proxy.py
    - src/venus_os_fronius_proxy/__main__.py
    - src/venus_os_fronius_proxy/webapp.py

key-decisions:
  - "Store time series at 1/s poll rate (memory cheap at ~1.3MB for 6 buffers)"
  - "Track energy_at_start on first collect() for future daily energy delta"

patterns-established:
  - "DashboardCollector.collect() called via shared_ctx in poll loop -- no import in proxy.py"
  - "_read_int16 for SunSpec signed scale factors: raw - 65536 if raw > 32767"
  - "_read_uint32 for 2-register fields: (hi << 16) | lo"
  - "CONTENT_TYPES dict for static file serving with correct MIME types"

requirements-completed: [INFRA-02, INFRA-03, INFRA-04]

duration: 4min
completed: 2026-03-18
---

# Phase 5 Plan 01: Data Pipeline Backend Summary

**DashboardCollector decoding all Model 103 registers with int16 scale factors and uint32 energy, TimeSeriesBuffer ring buffers, REST endpoint, and static file handler**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T15:31:26Z
- **Completed:** 2026-03-18T15:35:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- DashboardCollector correctly decodes all 23 Model 103 fields with signed int16 scale factors and uint32 energy
- TimeSeriesBuffer stores 60-min history per metric using deque(maxlen) with automatic eviction
- Poll loop feeds DashboardCollector after each successful SE30K poll cycle
- GET /api/dashboard returns the latest decoded snapshot as JSON (503 if no data yet)
- GET /static/{filename} serves .css and .js with correct Content-Type headers

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TimeSeriesBuffer and DashboardCollector with tests (TDD)**
   - `6f32277` (test) - failing tests for TimeSeriesBuffer and DashboardCollector
   - `22b1bc4` (feat) - implement TimeSeriesBuffer and DashboardCollector
2. **Task 2: Wire DashboardCollector into proxy and webapp** - `bebd560` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/timeseries.py` - Sample dataclass and TimeSeriesBuffer ring buffer
- `src/venus_os_fronius_proxy/dashboard.py` - DashboardCollector with DECODE_MAP, int16/uint32 helpers, snapshot generation
- `src/venus_os_fronius_proxy/proxy.py` - Added 5 lines: dashboard_collector.collect() call after cache.update()
- `src/venus_os_fronius_proxy/__main__.py` - Added 2 lines: DashboardCollector() creation in shared_ctx
- `src/venus_os_fronius_proxy/webapp.py` - Added dashboard_handler, static_handler, CONTENT_TYPES, 2 routes
- `tests/test_timeseries.py` - 7 unit tests for TimeSeriesBuffer
- `tests/test_dashboard.py` - 10 unit tests for DashboardCollector

## Decisions Made
- Store time series at 1 sample/second (matches poll rate); memory is cheap at ~1.3MB for 6 buffers
- Track energy_at_start on first collect() for future daily energy delta computation
- DashboardCollector import placed inside run_with_shutdown() to avoid circular imports

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-existing test failure in tests/test_solaredge_plugin.py::TestPoll::test_poll_reads_registers (KeyError: 'slave') -- not caused by this plan, existed before. Out of scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Backend data pipeline complete, ready for Plan 02 (frontend theme/restructure)
- DashboardCollector.last_snapshot available for WebSocket broadcast in Phase 6
- TimeSeriesBuffer data available for sparkline rendering
- Static file handler ready to serve style.css and app.js once created

---
*Phase: 05-data-pipeline-theme-foundation*
*Completed: 2026-03-18*
