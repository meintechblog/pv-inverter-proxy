---
phase: 27-webapp-config-status-ui
plan: 02
subsystem: webapp
tags: [mqtt, status-dot, topic-preview, websocket, ui]
dependency_graph:
  requires:
    - phase: 27-01
      provides: MQTT Publishing config panel with dirty tracking
  provides:
    - mqtt_pub_connected in device_list WebSocket broadcast
    - MQTT publisher status dot (green/red) in panel header
    - MQTT topic preview card with per-device topic paths
  affects: [webapp.py, app.js, style.css]
tech_stack:
  added: []
  patterns: [ws-driven-status-dot, client-side-topic-generation, reactive-preview-on-input]
key_files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/webapp.py
    - src/venus_os_fronius_proxy/static/app.js
    - src/venus_os_fronius_proxy/static/style.css
key-decisions:
  - "Status dot color set via inline style for dynamic green/red, not CSS class toggling"
  - "Topic preview seeded from config.inverters on initial load, replaced by WS device_list data"
  - "Topic preview re-renders on prefix input change for instant feedback"
patterns-established:
  - "WebSocket-driven UI status indicators: broadcast extra fields in existing messages"
  - "Client-side topic generation from known prefix + device IDs"
requirements-completed: [UI-03, UI-04]
metrics:
  duration: 81s
  completed: "2026-03-22T11:21:55Z"
  tasks: 1
  files: 3
---

# Phase 27 Plan 02: MQTT Status Dot & Topic Preview Summary

**MQTT publisher connection status dot (green/red) in panel header and topic preview card showing per-device MQTT topic paths with reactive prefix updates**

## Performance

- **Duration:** 81s
- **Started:** 2026-03-22T11:20:34Z
- **Completed:** 2026-03-22T11:21:55Z
- **Tasks:** 1 (+ 1 human-verify checkpoint)
- **Files modified:** 3

## Accomplishments
- WebSocket device_list broadcast now includes mqtt_pub_connected boolean from AppContext
- Green/red status dot in MQTT Publishing panel header reflects real-time connection state
- Topic preview card lists all MQTT topics: per-device state, virtual PV state, and LWT availability
- Topic preview reactively updates when prefix input field changes or device list arrives via WS

## Task Commits

Each task was committed atomically:

1. **Task 1: Add mqtt_pub_connected to device_list broadcast and render status dot + topic preview** - `45d9bd8` (feat)

**Plan metadata:** [pending final commit]

## Files Created/Modified
- `src/venus_os_fronius_proxy/webapp.py` - Added mqtt_pub_connected to device_list broadcast payload
- `src/venus_os_fronius_proxy/static/app.js` - Status dot, topic preview card, updateMqttPubStatusDot(), renderMqttTopicPreview()
- `src/venus_os_fronius_proxy/static/style.css` - Topic preview styles and status dot transition

## Decisions Made
1. **Inline style for dot color**: Using `dot.style.background = var(--ve-green/red)` for dynamic state rather than class toggling -- simpler for two-state boolean
2. **Config.inverters seed**: On initial page build before WS data arrives, seed _lastDeviceList from config.inverters to show topic preview immediately
3. **LWT topic included**: Added `{prefix}/status` as availability (LWT) topic in preview for completeness

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all data sources wired to live WebSocket data and config API.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 27 complete: MQTT Publishing config panel + status dot + topic preview fully wired
- Human verification pending for visual/functional confirmation
