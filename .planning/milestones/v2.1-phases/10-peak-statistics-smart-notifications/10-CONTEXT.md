# Phase 10: Peak Statistics & Smart Notifications - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add daily peak statistics tracking (peak power, operating hours, efficiency) to the backend and display in dashboard. Wire event-driven toast notifications for Venus OS override, inverter fault, temperature warning, and night mode transitions. Toast infrastructure from Phase 9 is ready — this phase adds the data and triggers.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation decisions for this phase are delegated to Claude. User trusts Claude to make good choices. Key areas:

**Peak Statistics:**
- Where to display stats (own card vs inline vs under daily energy)
- PeakStats dataclass design in backend (fields, reset logic)
- How to compute efficiency (current power vs peak, or vs rated capacity)
- Operating hours tracking (counting seconds when not SLEEPING)
- Integration into DashboardCollector snapshot pipeline

**Notification Events:**
- Which events trigger toasts (Override already exists in app.js line 1015)
- Fault detection: when operating_state changes to fault/error values
- Temperature warning threshold (suggest ~75C for cabinet as starting point for SE30K)
- Night mode transition toasts (SLEEPING ↔ Operating state changes)
- Backend: whether to add new WebSocket event types or use existing snapshot fields with client-side diffing
- Toast severity mapping (which events are info/warning/error)

**Display Design:**
- Stats card styling consistent with existing ve-card pattern
- Values update live via WebSocket (same pattern as other dashboard widgets)
- In-memory only, reset on proxy restart (consistent with daily_energy_wh pattern)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backend Data
- `src/venus_os_fronius_proxy/dashboard.py` — DashboardCollector with DECODE_MAP, TimeSeriesBuffer, snapshot() method, operating_state mapping, daily_energy_wh computation
- `src/venus_os_fronius_proxy/proxy.py` — Poll loop, night mode detection, connection manager, Venus OS override detection
- `src/venus_os_fronius_proxy/webapp.py` — WebSocket broadcast, REST endpoints

### Frontend
- `src/venus_os_fronius_proxy/static/app.js` — showToast() stacking system (Phase 9), WebSocket message handler, existing override_event toast at line 1015, dashboard update functions
- `src/venus_os_fronius_proxy/static/style.css` — ve-card pattern, animation variables from Phase 9
- `src/venus_os_fronius_proxy/static/index.html` — Dashboard HTML structure, toast-container

### Research
- `.planning/research/ARCHITECTURE.md` — Integration architecture for peak stats and notifications
- `.planning/research/FEATURES.md` — Feature landscape, notification event types
- `.planning/research/PITFALLS.md` — Toast notification fatigue, threshold tuning

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `DashboardCollector.snapshot()` — returns dict with all inverter data, extends naturally with peak stats fields
- `TimeSeriesBuffer` — ring buffer pattern for in-memory data (could be reused for tracking)
- `showToast(message, type)` — Phase 9 stacking toast system, supports info/success/warning/error
- `STATE_MAP` in dashboard.py — maps operating_state codes to strings (1=OPERATING, 2=SLEEPING, etc.)
- `daily_energy_wh` computation — pattern for in-memory daily tracking with baseline delta

### Established Patterns
- Backend data → snapshot dict → WebSocket broadcast → client-side JS update
- Override events already trigger toast via WebSocket message type
- In-memory tracking with reset on restart (daily_energy_wh, TimeSeriesBuffer)

### Integration Points
- `DashboardCollector._collect()` — where peak tracking would be updated per poll cycle
- `broadcast_to_clients()` in webapp.py — where snapshot is sent to all WS clients
- `updateDashboard()` in app.js — where new stats widget would be updated from WS data
- Existing override_event handler in app.js — pattern for other event-driven toasts

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. User wants maximum value with clean integration.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 10-peak-statistics-smart-notifications*
*Context gathered: 2026-03-18*
