---
phase: 13-mqtt-config-backend
plan: 02
subsystem: api
tags: [mqtt, config, auto-discovery, venus-os, webapp]

# Dependency graph
requires:
  - phase: 13-mqtt-config-backend (plan 01)
    provides: VenusConfig dataclass, parameterized venus_mqtt_loop, CONNACK validation
provides:
  - Portal ID auto-discovery via MQTT wildcard subscription
  - Zero hardcoded Venus OS references in entire codebase
  - Conditional venus_mqtt_loop start based on config
  - Dashboard venus_mqtt_connected boolean
affects: [14-mqtt-config-ui, 15-mqtt-config-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [mqtt-wildcard-discovery, config-driven-handler, conditional-background-task]

key-files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/venus_reader.py
    - src/venus_os_fronius_proxy/webapp.py
    - src/venus_os_fronius_proxy/__main__.py
    - src/venus_os_fronius_proxy/dashboard.py
    - tests/test_venus_reader.py
    - tests/test_webapp.py
    - tests/test_dashboard.py

key-decisions:
  - "Portal ID discovery retries every 30s in a while-True loop before entering main MQTT loop"
  - "venus_write_handler and venus_dbus_handler return 503 when Venus OS not configured"
  - "_mqtt_write_venus validates CONNACK to match venus_reader._mqtt_connect behavior"

patterns-established:
  - "Config-driven handlers: request.app['config'].venus for Venus OS settings"
  - "503 for unconfigured subsystems: graceful degradation when optional services not set up"

requirements-completed: [CFG-03, CFG-04]

# Metrics
duration: 5min
completed: 2026-03-19
---

# Phase 13 Plan 02: Webapp De-hardcode + Portal ID Auto-discovery Summary

**Portal ID auto-discovery via MQTT N/+/system/0/Serial wildcard, all five hardcoded Venus OS references eliminated, conditional MQTT start with dashboard connection state**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-19T17:48:54Z
- **Completed:** 2026-03-19T17:53:30Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Implemented `discover_portal_id()` that subscribes to `N/+/system/0/Serial` and extracts portal ID from MQTT topic
- Eliminated all five hardcoded Venus OS references (2 in venus_reader.py from plan 01, 3 in webapp.py)
- Wired config.venus through __main__.py with conditional start and venus_task stored in shared_ctx
- Added venus_mqtt_connected boolean to dashboard snapshot for UI consumption

## Task Commits

Each task was committed atomically:

1. **Task 1: Portal ID auto-discovery + webapp de-hardcode + tests (RED)** - `799c551` (test)
2. **Task 1: Portal ID auto-discovery + webapp de-hardcode + tests (GREEN)** - `260f39e` (feat)
3. **Task 2: Wire config through __main__.py + dashboard snapshot** - `da86df0` (feat)

_Note: Task 1 was TDD with RED/GREEN commits._

## Files Created/Modified
- `src/venus_os_fronius_proxy/venus_reader.py` - Added discover_portal_id() with retry loop in venus_mqtt_loop
- `src/venus_os_fronius_proxy/webapp.py` - De-hardcoded venus_write_handler, venus_dbus_handler, _mqtt_write_venus
- `src/venus_os_fronius_proxy/__main__.py` - Conditional venus_mqtt_loop start, venus_task in shared_ctx, venus_host in startup log
- `src/venus_os_fronius_proxy/dashboard.py` - Added venus_mqtt_connected to snapshot dict
- `tests/test_venus_reader.py` - Tests for discover_portal_id success/timeout/connection_error
- `tests/test_webapp.py` - Tests for 503 on unconfigured Venus, no hardcoded IPs assertion
- `tests/test_dashboard.py` - Tests for venus_mqtt_connected in snapshot (True, default False, None ctx)

## Decisions Made
- Portal ID discovery retries in a while-True loop (30s between attempts) before the main MQTT subscribe loop starts -- ensures eventual success without blocking startup
- 503 status for unconfigured Venus OS handlers (not 400) -- the service is unavailable, not a bad request
- CONNACK validation added to _mqtt_write_venus to match the fix already applied in venus_reader._mqtt_connect (consistency)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Several pre-existing test failures found in test_control.py, test_webapp.py, test_connection.py (wmaxlimpct_float property mismatch) -- these are unrelated to this plan and were not fixed per scope boundary rules.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- MQTT configuration is fully backend-ready: VenusConfig loads from YAML, all code paths use config, portal ID auto-discovers
- Phase 14 (MQTT Config UI) can now build a settings form that writes to config.yaml and triggers hot-reload
- shared_ctx["venus_task"] is stored for future hot-reload cancellation/restart

---
*Phase: 13-mqtt-config-backend*
*Completed: 2026-03-19*
