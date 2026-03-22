---
phase: 27-webapp-config-status-ui
plan: 01
subsystem: webapp
tags: [mqtt, config, ui, dirty-tracking, mdns]
dependency_graph:
  requires: [phase-26-telemetry-publishing]
  provides: [mqtt-publish-config-panel, mqtt-discover-ui]
  affects: [webapp.py, app.js, style.css]
tech_stack:
  added: []
  patterns: [dirty-tracking, instant-save-toggle, mdns-discover-button, multi-broker-dropdown]
key_files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/webapp.py
    - src/venus_os_fronius_proxy/static/app.js
    - src/venus_os_fronius_proxy/static/style.css
decisions:
  - "Enable toggle uses instant-save pattern (no Save button) matching ESS toggle precedent"
  - "Discover button populates dropdown only when multiple brokers found, auto-selects first"
  - "client_id excluded from config API response as internal-only field"
metrics:
  duration: 86s
  completed: "2026-03-22T11:18:28Z"
  tasks: 2
  files: 3
---

# Phase 27 Plan 01: MQTT Publishing Config Panel Summary

MQTT Publishing config panel on Venus page with enable toggle (instant-save), host/port/prefix/interval fields with dirty tracking, and mDNS broker discovery with multi-broker dropdown.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Expose mqtt_publish in GET /api/config + CSS | 9863e86 | webapp.py, style.css |
| 2 | Build MQTT Publishing panel with dirty tracking + discover | ae021aa | app.js |

## Key Changes

### Backend (webapp.py)
- `config_get_handler` now returns `mqtt_publish` section with enabled, host, port, topic_prefix, interval_s fields
- client_id intentionally excluded from API response (internal only)

### Frontend (app.js)
- New Section 5 in `buildVenusPage`: MQTT Publishing config panel (`ve-mqtt-pub-panel`)
- Enable toggle: instant-save via POST /api/config, no Save/Cancel needed
- Host field with Discover button: calls POST /api/mqtt/discover
- Single broker result auto-populates host+port fields
- Multiple brokers show `<select>` dropdown for selection
- Port, Topic Prefix, Interval fields with ve-input dirty tracking
- Save/Cancel button pair: appears on dirty, hides on save/cancel
- Save handler POSTs mqtt_publish config, updates originals on success
- Cancel handler restores all fields to original values

### Styles (style.css)
- `.ve-mqtt-pub-discover-row` flex layout for host + discover button
- `.ve-mqtt-pub-discover-btn` blue button with hover/disabled states
- `.ve-mqtt-pub-broker-select` dropdown for multiple broker results
- All styles use `var(--ve-*)` tokens per design system

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Enable toggle instant-save**: Follows ESS toggle pattern - immediately POSTs on change, reverts on error
2. **Multi-broker dropdown**: Auto-selects first broker, change listener updates both host and port fields
3. **client_id excluded from API**: Internal implementation detail, not user-configurable

## Known Stubs

None - all data sources wired to live API endpoints.

## Self-Check: PASSED
