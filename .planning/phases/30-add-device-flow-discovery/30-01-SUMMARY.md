---
phase: 30-add-device-flow-discovery
plan: 01
subsystem: api
tags: [shelly, mdns, zeroconf, aiohttp, discovery, probe]

requires:
  - phase: 28-plugin-core-profiles
    provides: "Shelly plugin architecture and profile system"
provides:
  - "POST /api/shelly/probe endpoint for single-device generation detection"
  - "POST /api/shelly/discover endpoint for LAN mDNS Shelly scanning"
  - "shelly_discovery.py module with discover_shelly_devices and probe_shelly_device"
  - "shelly_gen and rated_power persistence in inverters_add_handler"
affects: [30-add-device-flow-discovery]

tech-stack:
  added: []
  patterns: ["mDNS discovery pattern reused from mdns_discovery.py for Shelly devices"]

key-files:
  created:
    - src/pv_inverter_proxy/shelly_discovery.py
    - tests/test_shelly_discovery.py
  modified:
    - src/pv_inverter_proxy/webapp.py
    - src/pv_inverter_proxy/config.py

key-decisions:
  - "Reused mDNS discovery pattern from mdns_discovery.py for consistency"
  - "Gen2+ devices (gen>=2) all map to generation='gen2' with gen_display showing actual gen"

patterns-established:
  - "Shelly probe pattern: HTTP GET /shelly with generation detection via gen field presence"
  - "Shelly discovery dedup: skip_ips parameter filters already-configured devices"

requirements-completed: [UI-02, UI-06]

duration: 3min
completed: 2026-03-24
---

# Phase 30 Plan 01: Shelly Backend Discovery Summary

**mDNS discovery and HTTP probe endpoints for Shelly device detection with Gen1/Gen2/Gen3 support and dedup filtering**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T01:39:39Z
- **Completed:** 2026-03-24T01:42:17Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created shelly_discovery.py with mDNS scan (discover_shelly_devices) and HTTP probe (probe_shelly_device)
- Wired POST /api/shelly/probe and POST /api/shelly/discover endpoints in webapp.py
- 9 unit tests covering empty scan, device found, skip_ips dedup, error cleanup, Gen1/Gen2/Gen3 probe, unreachable
- Persists shelly_gen and rated_power when adding devices via inverters_add_handler

## Task Commits

Each task was committed atomically:

1. **Task 1: Create shelly_discovery.py and test scaffold** - `8318fff` (feat)
2. **Task 2: Wire probe and discover endpoints in webapp.py** - `03a6e2e` (feat)

## Files Created/Modified
- `src/pv_inverter_proxy/shelly_discovery.py` - mDNS discovery and HTTP probe for Shelly devices
- `tests/test_shelly_discovery.py` - 9 unit tests for discovery and probe functions
- `src/pv_inverter_proxy/webapp.py` - Two new handlers + routes + shelly_gen/rated_power in add handler
- `src/pv_inverter_proxy/config.py` - Added shelly_gen field to InverterEntry

## Decisions Made
- Reused the exact mDNS pattern from mdns_discovery.py (AsyncZeroconf + AsyncServiceBrowser + on_state_change callback)
- Gen2+ devices (gen field >= 2) all use generation="gen2" internally, with gen_display showing "Gen2" or "Gen3"
- probe_shelly_device uses 5-second timeout per research pitfall 2

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added shelly_gen field to InverterEntry**
- **Found during:** Task 2 (Wire endpoints)
- **Issue:** InverterEntry in this worktree lacked shelly_gen field (added in phase 29 on main, not present here)
- **Fix:** Added `shelly_gen: str = ""` to InverterEntry dataclass in config.py
- **Files modified:** src/pv_inverter_proxy/config.py
- **Verification:** inverters_add_handler can now pass shelly_gen to InverterEntry constructor
- **Committed in:** 03a6e2e (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Auto-fix necessary because worktree diverged from main. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend endpoints ready for frontend add-device flow (Plan 02)
- POST /api/shelly/probe accepts {host} and returns generation/model/mac
- POST /api/shelly/discover returns mDNS-discovered Shelly devices filtered against config

---
*Phase: 30-add-device-flow-discovery*
*Completed: 2026-03-24*
