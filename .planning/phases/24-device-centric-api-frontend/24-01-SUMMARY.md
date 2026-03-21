---
phase: 24-device-centric-api-frontend
plan: 01
subsystem: api
tags: [rest, websocket, aiohttp, device-centric, crud]

requires:
  - phase: 23-power-limit-distribution
    provides: PowerLimitDistributor with per-device limit tracking
  - phase: 22-device-registry
    provides: DeviceRegistry, DeviceState, multi-device poll loop
provides:
  - "GET /api/devices endpoint returning inverters + venus + virtual pseudo-devices"
  - "GET /api/devices/{id}/snapshot for per-device dashboard data"
  - "GET /api/devices/virtual/snapshot for aggregated power + contributions + throttle info"
  - "POST/PUT/DELETE /api/devices as CRUD aliases for inverter management"
  - "Device-tagged WebSocket broadcasts (device_snapshot, virtual_snapshot, device_list)"
  - "PowerLimitDistributor.get_device_limits() method"
  - "Name field support in inverter CRUD"
affects: [24-02-PLAN, frontend, dashboard]

tech-stack:
  added: []
  patterns: [device-centric API pattern with pseudo-devices, tagged WebSocket broadcasts]

key-files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/webapp.py
    - src/venus_os_fronius_proxy/distributor.py
    - src/venus_os_fronius_proxy/aggregation.py
    - src/venus_os_fronius_proxy/__main__.py
    - tests/test_webapp.py

key-decisions:
  - "Display name fallback chain: name -> manufacturer+model -> 'Inverter'"
  - "Venus and virtual appended as pseudo-devices in device list for unified frontend handling"
  - "broadcast_device_list fires after every _reconfigure_active call for real-time sidebar updates"
  - "AggregationLayer._broadcast_fn wired post-init in __main__.py to avoid import cycles"

patterns-established:
  - "Device-centric API: /api/devices/* replaces /api/inverters as primary frontend path"
  - "Tagged WS broadcasts: {type: 'device_snapshot', device_id, data} for per-device routing"
  - "Pseudo-devices: venus and virtual entries in device list with special type field"

requirements-completed: [API-01, API-02, API-03]

duration: 5min
completed: 2026-03-21
---

# Phase 24 Plan 01: Device-Centric API Summary

**REST endpoints for per-device snapshots, virtual aggregation with throttle info, CRUD aliases, and device-tagged WebSocket broadcasts wired into poll cycle**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-21T10:15:08Z
- **Completed:** 2026-03-21T10:20:16Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Device-centric REST API with GET /api/devices, /api/devices/{id}/snapshot, /api/devices/virtual/snapshot
- CRUD aliases (POST/PUT/DELETE /api/devices) delegating to existing inverter handlers with name field support
- Device-tagged WebSocket broadcasts wired into AggregationLayer poll cycle via _broadcast_fn callback
- PowerLimitDistributor.get_device_limits() for throttle info in virtual snapshot

## Task Commits

Each task was committed atomically:

1. **Task 1: Device-centric REST endpoints + CRUD aliases** - `1c61bef` (test) + `5695068` (feat, TDD)
2. **Task 2: Device-tagged WebSocket broadcasts** - `a116ba7` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/webapp.py` - Device list/snapshot/virtual handlers, broadcast functions, CRUD aliases, ws_handler updated
- `src/venus_os_fronius_proxy/distributor.py` - get_device_limits() method
- `src/venus_os_fronius_proxy/aggregation.py` - _broadcast_fn callback support
- `src/venus_os_fronius_proxy/__main__.py` - Broadcast wiring after webapp creation
- `tests/test_webapp.py` - Tests for device endpoints, CRUD aliases, get_device_limits

## Decisions Made
- Display name fallback chain: entry.name -> "{manufacturer} {model}".strip() -> "Inverter"
- Venus and virtual pseudo-devices appended to device list for unified frontend data model
- AggregationLayer._broadcast_fn set post-init in __main__.py to avoid circular imports between webapp and aggregation
- broadcast_device_list wired into _reconfigure_active for real-time CRUD update propagation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All device-centric API endpoints ready for Plan 02 (frontend)
- WebSocket broadcasts tagged with device_id for frontend routing
- Virtual snapshot includes throttle info for contribution display

---
*Phase: 24-device-centric-api-frontend*
*Completed: 2026-03-21*
