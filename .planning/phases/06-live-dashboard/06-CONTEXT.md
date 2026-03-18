# Phase 6: Live Dashboard - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Real-time dashboard with WebSocket push updates, power gauge, 3-phase details, sparklines, and integrated v1.0 Config + Register pages. All live data updates without page refresh.

</domain>

<decisions>
## Implementation Decisions

### Real-time Updates
- WebSocket (or SSE) push from server to all connected browsers
- Data pushed after each poll cycle (~1 second)
- No manual refresh needed — widgets update automatically

### Dashboard Widgets (from Phase 5 + Requirements)
- Live Power Gauge — current total power vs 30kW capacity
- 3-Phase Detail — L1/L2/L3 voltage, current, power
- Mini-Sparkline — 60-min power history from TimeSeriesBuffer
- Health metrics (carried from v1.0 — uptime, poll rate, cache)
- Connection status dots (carried from v1.0)

### Config + Register Integration
- Config editor and Register Viewer from v1.0 remain as sidebar tabs
- Already ported to new layout in Phase 5
- Phase 6 wires them to WebSocket for live register updates (optional)

### Claude's Discretion (ALL UI design decisions)
User explicitly chose "Alle Claude's Discretion" — Claude has full creative freedom on:
- Power Gauge type (arc gauge, big number, tacho, donut, bar)
- Widget grid layout (arrangement, sizing, spacing)
- Sparkline styling (line color, fill, Y-axis, hover tooltips)
- 3-Phase detail presentation (table, cards, inline)
- Animation/transition effects on value updates
- Mobile widget stacking order
- Color coding for power levels (green→yellow→red thresholds)

Guidelines from prior phases:
- Must use Venus OS palette (#387DC5 blue, #141414 bg, #FAF9F5 text)
- Venus OS Widget-Style (abgerundete Panels, GX Touch Feel)
- Responsive (Desktop, Tablet, Mobile)
- Professional and "rund" (polished)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backend (already built in Phase 5)
- `src/venus_os_fronius_proxy/dashboard.py` — DashboardCollector with DECODE_MAP, snapshot generation
- `src/venus_os_fronius_proxy/timeseries.py` — TimeSeriesBuffer, Sample dataclass
- `src/venus_os_fronius_proxy/webapp.py` — existing REST endpoints, `/api/dashboard` returns decoded data

### Frontend (Phase 5 output)
- `src/venus_os_fronius_proxy/static/style.css` — Venus OS theme with CSS custom properties
- `src/venus_os_fronius_proxy/static/app.js` — polling functions, navigation, config form, register viewer
- `src/venus_os_fronius_proxy/static/index.html` — sidebar layout, page structure

### Architecture Research
- `.planning/research/ARCHITECTURE.md` — SSE vs WebSocket decision, DashboardCollector design
- `.planning/research/PITFALLS.md` — WebSocket memory leaks, heartbeat recommendation

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `DashboardCollector.last_snapshot` — pre-decoded JSON dict, ready to serialize and push
- `DashboardCollector.timeseries` — TimeSeriesBuffer with history, `get_history()` returns list of Samples
- `webapp.py:dashboard_handler` — already serves snapshot as JSON, pattern for WebSocket
- `app.js` polling functions — can be replaced with WebSocket event handlers
- CSS custom properties — all Venus OS colors available as `var(--ve-*)`

### Established Patterns
- `aiohttp.web.WebSocketResponse` — native WebSocket support, no extra deps
- `shared_ctx` dict — passes collector between proxy and webapp
- `setInterval` polling in app.js — to be replaced with WebSocket `onmessage`

### Integration Points
- `webapp.py` — add WebSocket route `/ws`
- `proxy.py:_poll_loop` — after `dashboard_collector.collect()`, broadcast to WebSocket clients
- `app.js` — replace `setInterval` polling with WebSocket connection + `onmessage` handler
- `style.css` — add widget-specific styles (gauge, sparkline, phase cards)
- `index.html` — add dashboard widget containers in `#page-dashboard`

</code_context>

<specifics>
## Specific Ideas

- Dashboard should feel like a real energy monitoring system — not a dev tool
- Power gauge should be the hero element — prominent, immediately shows "how much power right now"
- Sparkline should show trend at a glance — no need for complex chart interactions
- Value updates should have subtle animations (number ticking, sparkline growing)

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-live-dashboard*
*Context gathered: 2026-03-18*
