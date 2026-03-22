---
phase: 25-publisher-infrastructure
plan: 02
subsystem: infra
tags: [mqtt, asyncio, mdns, zeroconf, lifecycle]

requires:
  - phase: 25-publisher-infrastructure plan 01
    provides: mqtt_publish_loop, MqttPublishConfig, AppContext mqtt_pub fields
provides:
  - Publisher lifecycle: conditional start on boot, shutdown on SIGTERM
  - Publisher hot-reload on config change via webapp
  - mDNS broker discovery module (mdns_discovery.py)
  - REST endpoint POST /api/mqtt/discover
affects: [26-telemetry-payloads, 27-webapp-mqtt-config]

tech-stack:
  added: [zeroconf AsyncZeroconf/AsyncServiceBrowser]
  patterns: [mqtt publisher lifecycle mirroring venus_task pattern, mDNS manual scan endpoint]

key-files:
  created:
    - src/venus_os_fronius_proxy/mdns_discovery.py
    - tests/test_mdns_discovery.py
  modified:
    - src/venus_os_fronius_proxy/__main__.py
    - src/venus_os_fronius_proxy/webapp.py

key-decisions:
  - "Publisher lifecycle mirrors venus_task pattern exactly: conditional start, cancel on shutdown, hot-reload on config save"
  - "mDNS discovery mocks zeroconf in tests for portability across environments without the dependency installed"

patterns-established:
  - "MQTT publisher lifecycle: Queue(maxsize=100) + create_task on boot, cancel before runner cleanup on shutdown"
  - "Config hot-reload pattern: capture old tuple, apply changes, compare, cancel/recreate task if changed"

requirements-completed: [CONN-03, CONN-04]

duration: 4min
completed: 2026-03-22
---

# Phase 25 Plan 02: Publisher Lifecycle & mDNS Discovery Summary

**MQTT publisher wired into app lifecycle (boot/shutdown/hot-reload) with mDNS broker discovery via POST /api/mqtt/discover**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-22T10:04:51Z
- **Completed:** 2026-03-22T10:08:45Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Publisher starts conditionally on boot when mqtt_publish.enabled is true, creates Queue(maxsize=100)
- Publisher shuts down cleanly on SIGTERM (cancelled before runner cleanup)
- Config save with changed mqtt_publish settings triggers cancel/recreate hot-reload
- mDNS discovery module scans for _mqtt._tcp.local. brokers using AsyncZeroconf
- POST /api/mqtt/discover endpoint returns broker list with host/port/name
- 5 unit tests covering empty scan, broker found, close-on-error, timeout, constant

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire publisher into __main__.py lifecycle + webapp.py hot-reload** - `55020f2` (feat)
2. **Task 2 RED: Failing tests for mDNS discovery** - `6d90c44` (test)
3. **Task 2 GREEN: mDNS discovery module + webapp endpoint** - `710ca90` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/__main__.py` - Conditional publisher start on boot, shutdown cancel before runner cleanup
- `src/venus_os_fronius_proxy/webapp.py` - mqtt_publish hot-reload in config_save_handler, mqtt_discover_handler endpoint, route registration
- `src/venus_os_fronius_proxy/mdns_discovery.py` - AsyncZeroconf scan for _mqtt._tcp.local. with timeout and cleanup
- `tests/test_mdns_discovery.py` - 5 tests with mocked zeroconf for environment portability

## Decisions Made
- Mirrored venus_task lifecycle pattern exactly for publisher (conditional start, cancel, hot-reload)
- Tests mock zeroconf at sys.modules level for environments where zeroconf is not installed
- mDNS handler uses 3.0s timeout per D-15 locked decision

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mocked zeroconf in tests for environment compatibility**
- **Found during:** Task 2 (TDD GREEN phase)
- **Issue:** Test environment has Python 3.9 without zeroconf installed, tests fail on import
- **Fix:** Added sys.modules mock for zeroconf at test file top when not installed
- **Files modified:** tests/test_mdns_discovery.py
- **Verification:** All 5 tests pass with PYTHONPATH set
- **Committed in:** 710ca90

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Environment portability fix, no scope change.

## Issues Encountered
- Test environment uses system Python 3.9 without project dependencies (aiomqtt, zeroconf) installed. Resolved by mocking zeroconf at module level in tests. Import-based verification of __main__.py skipped in favor of grep verification.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Publisher infrastructure complete: lifecycle, hot-reload, mDNS discovery
- Phase 26 (telemetry payloads) can wire data into mqtt_pub_queue
- Phase 27 (webapp config UI) can use POST /api/mqtt/discover for broker selection

---
*Phase: 25-publisher-infrastructure*
*Completed: 2026-03-22*
