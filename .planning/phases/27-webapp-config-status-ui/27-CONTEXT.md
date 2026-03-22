# Phase 27: Webapp Config & Status UI - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Add MQTT Publishing config panel to the Venus OS device page. Enable/disable, broker host/port, topic prefix, publish interval. mDNS discover button. Connection status dot. Topic preview showing exact topics per device.

</domain>

<decisions>
## Implementation Decisions

### Location in UI
- **D-01:** MQTT Publishing settings go on the Venus OS device page (alongside existing ESS/MQTT config) — NOT a separate page
- **D-02:** New card/panel below existing Venus OS config panel

### Config Panel
- **D-03:** Fields: Enable toggle, Host input, Port input, Topic Prefix input, Interval input (number, seconds)
- **D-04:** Dirty tracking with Save/Cancel buttons (same pattern as existing inverter config and Venus config)
- **D-05:** Enable toggle is instant-save (same pattern as inverter enabled toggle)
- **D-06:** Save calls existing `POST /api/config` with `mqtt_publish: {...}` payload

### mDNS Discovery
- **D-07:** "Discover" button next to Host field
- **D-08:** On click: calls `POST /api/mqtt/discover`, shows spinner, populates host field with first result
- **D-09:** If multiple brokers found: show dropdown to select

### Connection Status
- **D-10:** Green/red dot showing mqtt_pub_connected state — in sidebar next to Venus device or in MQTT panel header
- **D-11:** Status comes via WebSocket snapshot (add mqtt_pub_connected to device_list or snapshot)

### Topic Preview
- **D-12:** Read-only section showing generated topics based on current config + device list
- **D-13:** Format: list of topics like `pvproxy/5303f554b55d/state`, `pvproxy/virtual/state`

### Backend
- **D-14:** Add `mqtt_pub_connected` to device list WebSocket message or new field in snapshot
- **D-15:** `POST /api/config` already handles `mqtt_publish` section via existing config_save_handler

### Claude's Discretion
- Exact layout within the Venus page
- Whether topic preview is collapsed by default
- Toast messages for save/discover actions
- Spinner style for mDNS scan

</decisions>

<canonical_refs>
## Canonical References

### UI patterns
- `src/venus_os_fronius_proxy/static/app.js` — buildVenusPage, wireESSToggles, dirty tracking pattern
- `src/venus_os_fronius_proxy/static/style.css` — ve-panel, ve-form-group, ve-btn patterns
- `CLAUDE.md` — Design system tokens, component patterns, naming conventions

### Backend
- `src/venus_os_fronius_proxy/webapp.py` — config_save_handler, mqtt discover endpoint, broadcast functions
- `src/venus_os_fronius_proxy/context.py` — AppContext.mqtt_pub_connected

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `buildVenusPage` in app.js — add MQTT panel here
- Venus config dirty tracking pattern (vHost, vPort, checkVenusDirty) — clone for MQTT
- `wireESSToggles` pattern — clone for MQTT enable toggle
- `POST /api/config` endpoint already handles mqtt_publish section

### Integration Points
- `app.js buildVenusPage()` — add new panel
- `app.js updateVenusESSOnPage()` — add mqtt status update
- `webapp.py` — add mqtt_pub_connected to device list or snapshot broadcast
- REST: `POST /api/mqtt/discover` already exists from Phase 25

</code_context>

<deferred>
## Deferred Ideas

None — this is the final phase of v5.0.

</deferred>

---

*Phase: 27-webapp-config-status-ui*
*Context gathered: 2026-03-22*
