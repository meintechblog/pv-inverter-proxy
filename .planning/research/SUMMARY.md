# Research Summary: Venus OS Fronius Proxy v2.0 Dashboard & Power Control

**Domain:** Solar inverter monitoring dashboard with power control, Venus OS visual identity
**Researched:** 2026-03-18 (v2.0 milestone research, updating v1.0 research from 2026-03-17)
**Overall confidence:** HIGH

## Executive Summary

The v2.0 milestone adds a Venus OS styled dashboard, live sparkline charts, and power control sliders to the existing Modbus proxy webapp. The critical finding is that **zero new dependencies are needed** -- every capability required (WebSocket, SVG sparklines, ring buffers, styled sliders) is achievable with the existing aiohttp stack plus stdlib modules and vanilla JavaScript.

The Venus OS gui-v2 color palette has been extracted directly from the official Victron repository (`victronenergy/gui-v2/themes/color/`), providing HIGH confidence color tokens: Victron blue `#387DC5`, dark backgrounds `#141414`/`#272622`, warm gray text `#FAF9F5`/`#969591`, and accent colors for status indicators. This replaces the current generic dark theme with an authentic Victron look.

For real-time communication, WebSocket (built into aiohttp) is recommended over SSE. While the v1.0 architecture research recommended SSE for its simplicity, v2.0's power control slider requires bidirectional communication (slider values client-to-server, live feedback server-to-client). Using WebSocket for both directions in a single connection is cleaner than SSE + separate POST endpoints.

Sparkline charts are trivially implementable as inline SVG polylines (~15 lines of JavaScript), backed by `collections.deque` ring buffers on the server side. No charting library is needed or appropriate for the single-file HTML constraint.

## Key Findings

**Stack:** Zero new dependencies. aiohttp WebSocket (built-in) + inline SVG sparklines + Venus OS CSS custom properties + native HTML range/checkbox. All self-contained in single-file HTML.

**Architecture:** WebSocket endpoint added to existing aiohttp webapp. DashboardCollector decodes registers once per poll cycle. TimeSeriesBuffer stores 60-min history via `collections.deque`. Broadcast to all WebSocket clients after each poll.

**Critical pitfall:** Power control slider UX must have explicit "Apply" confirmation and revert timeouts. Accidental slider drags on a 30kW inverter have real consequences. Debouncing and safety constraints are mandatory.

## Implications for Roadmap

Based on research, suggested phase structure for v2.0:

1. **Phase 1: Venus OS Theme + Dashboard Data Layer** - CSS swap + backend data pipeline
   - Addresses: Venus OS color scheme (CSS only), parsed inverter API endpoint, TimeSeriesBuffer + DashboardCollector
   - Avoids: Building frontend before data pipeline is solid
   - Rationale: Theme is purely visual (zero risk), data layer is testable without frontend

2. **Phase 2: WebSocket + Live Dashboard UI** - Real-time push + frontend widgets
   - Addresses: WebSocket endpoint, live power display, per-phase breakdown, status indicator, sparklines
   - Avoids: Polling overhead of current approach
   - Rationale: WebSocket infrastructure enables all live features; build widgets on verified data pipeline

3. **Phase 3: Power Control UI** - Slider, toggle, override detection
   - Addresses: Power control slider + toggle, override detection, revert timeout display, feedback loop
   - Avoids: Shipping power control without safety constraints
   - Rationale: Most dangerous feature -- needs safety design, confirmation UX, and thorough testing

4. **Phase 4: Polish** - Detail panel, daily energy, edge cases
   - Addresses: Inverter detail panel (V/A/Hz/Temp), daily energy tracking, empty states, error handling
   - Rationale: Nice-to-have features that round out the dashboard

**Phase ordering rationale:**
- Theme first because it is zero-risk CSS changes with maximum visual impact
- Data pipeline before frontend because it is testable independently (curl, unit tests)
- WebSocket before power control because power control feedback depends on the WebSocket infrastructure
- Power control last among core features because it requires the most safety validation

**Research flags for phases:**
- Phase 1: Standard patterns, no additional research needed
- Phase 2: Standard patterns, aiohttp WebSocket docs sufficient
- Phase 3: Needs careful safety design for slider UX. Review SolarEdge EDPC timeout behavior.
- Phase 4: Standard patterns, unlikely to need research

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies. All capabilities verified against official docs. |
| Features | HIGH | Requirements clear from PROJECT.md. Venus OS colors from official repository. |
| Architecture | HIGH | Additive changes to existing v1.0 architecture. WebSocket pattern well-documented. |
| Pitfalls | MEDIUM | Power control safety is well-understood in principle but UX details need iteration. |

## SSE vs WebSocket Decision Update

The v1.0 architecture research recommended SSE. For v2.0, WebSocket is recommended instead because:
- Power control slider sends values client-to-server (bidirectional need)
- Single connection handles both directions (simpler than SSE + POST endpoints)
- aiohttp has equally first-class support for both
- No additional dependencies either way

The ARCHITECTURE.md SSE recommendation was correct for a monitoring-only dashboard. v2.0's power control changes the calculus.

## Gaps to Address

- Power control slider debounce strategy (200ms recommended, needs UX testing)
- SolarEdge EDPC revert behavior when proxy restarts mid-timeout
- Venus OS flow-style layout deferred to v2.x (complex, diminishing returns without full system data)

## Sources

- [aiohttp WebSocket docs (v3.13.3)](https://docs.aiohttp.org/en/stable/web_quickstart.html)
- [Venus OS gui-v2 theme colors](https://github.com/victronenergy/gui-v2/tree/main/themes/color)
- [Venus OS gui-v2 ColorDesign.json](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/ColorDesign.json)
- [Venus OS gui-v2 Dark.json](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/Dark.json)
- Existing codebase: `webapp.py`, `proxy.py`, `control.py`, `static/index.html`
