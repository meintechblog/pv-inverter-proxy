# Phase 7: Power Control - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can view and test power limiting from the webapp with safety confirmations, and see who currently controls the inverter. Includes backend EDPC refresh loop to keep limits active.

</domain>

<decisions>
## Implementation Decisions

### Safety & Confirmation (Claude's Discretion with sensible defaults)
- **Confirmation dialog** before any power limit write — modal with value preview
- **Venus OS always wins** — if Venus OS writes a power limit, webapp shows "Venus OS has control" and disables manual slider
- **Webapp = test mode** — clearly labeled as "Manual Test" to distinguish from Venus OS production control
- **Auto-revert timeout** — webapp-initiated limits auto-revert after configurable timeout (default 5 min) as safety net
- **No accidental changes** — slider requires explicit "Apply" button click after dragging (not real-time)

### Power Control UI Components
- **Read-only display** — always visible: current power limit %, enabled/disabled, who set it (Venus OS / Webapp / None), timestamp
- **Slider** — 0-100% range, shows kW equivalent (e.g., "50% = 15.0 kW"), disabled when Venus OS has control
- **Enable/Disable toggle** — with confirmation dialog
- **Live feedback** — after applying, show SE30K acceptance confirmation (read-back from actual registers)
- **Status indicator** — color-coded: green = no limit, orange = limited, red = Venus OS override active

### EDPC Refresh Loop
- Backend periodically refreshes power limit to SE30K (prevents EDPC timeout revert)
- Refresh interval = CommandTimeout/2 (research found SE30K default = 60s, so refresh every 30s)
- Only when a limit is actively set (not when disabled)

### Override Detection
- Track `last_source` in ControlState: "venus_os" (from Modbus write path) vs "webapp" (from HTTP POST)
- Track `last_change_ts` for timestamp
- WebSocket pushes override events to all clients

### Override Log
- In-memory ring buffer (last 50 events)
- Each entry: timestamp, source (Venus OS / Webapp), action (set/enable/disable/revert), value
- Displayed as scrollable list in the Power Control panel
- Not persistent (resets on restart) — same as sparkline history

### Claude's Discretion (ALL UI details)
- Slider design (range input, custom styled, etc.)
- Confirmation dialog appearance and wording
- Override log layout (table, timeline, cards)
- Color coding thresholds
- Animation on value changes
- Mobile responsive behavior for control panel
- Toast/notification on override events
- Power Control placement in dashboard (new tab, inline section, or dedicated panel)

</decisions>

<canonical_refs>
## Canonical References

### Backend (already built)
- `src/venus_os_fronius_proxy/control.py` — ControlState, validate_wmaxlimpct, Model 123 constants
- `src/venus_os_fronius_proxy/proxy.py` — StalenessAwareSlaveContext.async_setValues (intercepts Venus OS writes)
- `src/venus_os_fronius_proxy/plugins/solaredge.py` — write_power_limit (0xF300/0xF322 EDPC)

### Frontend (Phase 5+6)
- `src/venus_os_fronius_proxy/static/app.js` — WebSocket handler, widget update pattern
- `src/venus_os_fronius_proxy/static/style.css` — Venus OS theme, ve-panel, ve-card classes
- `src/venus_os_fronius_proxy/webapp.py` — existing REST endpoints pattern, WebSocket broadcast

### Safety Research
- `.planning/research/PITFALLS.md` — Power control safety pitfalls, race conditions, EDPC timeout

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ControlState` in control.py — already tracks wmaxlimpct, wmaxlim_ena, is_enabled, wmaxlimpct_float
- `validate_wmaxlimpct()` — validation already exists (0-10000 range check)
- `plugin.write_power_limit(enable, limit_pct)` — full write path to SE30K already works
- `StalenessAwareSlaveContext.async_setValues` — already intercepts Model 123 writes from Venus OS
- `broadcast_to_clients()` in webapp.py — WebSocket push to all browsers

### Missing (Phase 7 must add)
- `ControlState.last_source` — who set the current limit (not tracked yet)
- `ControlState.last_change_ts` — when was it last changed
- REST endpoint for webapp power control writes (POST /api/power-limit)
- EDPC refresh loop (periodic re-write to keep SE30K limit active)
- Override event log (in-memory ring buffer)
- Frontend UI components (slider, toggle, log, status)

### Integration Points
- `webapp.py` — add POST /api/power-limit endpoint that calls plugin.write_power_limit
- `proxy.py:_handle_control_write` — update ControlState.last_source = "venus_os" on Model 123 writes
- `dashboard.py:DashboardCollector.collect()` — include control state in snapshot for WebSocket push
- `app.js` — add Power Control tab/section with slider, toggle, log

</code_context>

<specifics>
## Specific Ideas

- Power Control should feel like a "test bench" — professional, not dangerous
- Clearly distinguish "this is YOU testing" vs "Venus OS is controlling production"
- The 5-min auto-revert is a safety net — if you forget, inverter goes back to full power

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-power-control*
*Context gathered: 2026-03-18*
