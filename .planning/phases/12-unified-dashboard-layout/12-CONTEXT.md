# Phase 12: Unified Dashboard Layout - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Merge Power Control inline into the Dashboard page (no separate page), reorganize the bottom grid into 2 clear rows, and remove the Power Control sidebar nav item. This is purely a layout restructuring — all widgets and functionality already exist from Phases 7-11.

</domain>

<decisions>
## Implementation Decisions

### Power Control Placement
- Power Control section moves inline into Dashboard, directly under the Power Gauge card
- Kompakte Inline-Section: slider + Apply button + Enable/Disable toggle on one line
- Override Log: collapsible/ausklappbar with "Override Log (N events)" toggle button, collapsed by default
- Power Control visibility (always visible vs only when active): Claude's Discretion

### Grid Layout
- Bottom grid reorganized into 2 explicit rows:
  - Row 1 (3 equal columns): Inverter Status, Connection, Service Health
  - Row 2 (2 half-width columns): Today's Performance, Venus OS Control
- This replaces the current auto-fit grid that wraps unpredictably

### L1/L2/L3 Phase Cards
- Claude's Discretion on placement (keep as own row or move next to gauge)

### Navigation Cleanup
- Remove "Power Control" from sidebar nav (4th nav item → 3 items: Dashboard, Config, Registers)
- Remove entire #page-power section from HTML
- All Power Control JS functions remain but now operate on elements inside #page-dashboard

### Claude's Discretion
- Power Control visibility behavior (always shown vs conditional)
- Phase Cards layout (own row vs beside gauge)
- Exact CSS grid template for the 2-row bottom section
- Responsive breakpoints for mobile (stack columns)
- Entrance animation adjustments for the new layout

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Current Layout
- `src/venus_os_fronius_proxy/static/index.html` — Full dashboard structure: #page-dashboard (lines 88-220), #page-power (lines 255-310), sidebar nav (lines 30-65)
- `src/venus_os_fronius_proxy/static/style.css` — .ve-dashboard-grid, .ve-dashboard-bottom, .ve-ctrl-* styles, .ve-gauge-card
- `src/venus_os_fronius_proxy/static/app.js` — showPage() navigation, power control IIFEs (slider, toggle, override log), confirmAction()

### Power Control Elements to Move
- `#ctrl-override-banner` — Venus OS override warning banner
- `#ctrl-slider-group` — Slider + value display + Apply button
- `#ctrl-toggle` — Enable/Disable button
- `#ctrl-override-log` — Override event log list
- All ctrl-* related JS bindings (slider input, apply click, toggle click, override log rendering)

### Research
- `.planning/research/ARCHITECTURE.md` — Layout merge approach, "all components must exist before merging"
- `.planning/research/PITFALLS.md` — "Merging Power Control into Dashboard has high risk of breaking JS event bindings"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- All Power Control HTML elements already exist in #page-power — need to move, not recreate
- All JS handler IIFEs bind by element ID — moving elements preserves bindings IF IDs don't change
- .ve-ctrl-* CSS classes already styled — reuse as-is or compact

### Established Patterns
- Page show/hide via data-page attributes and classList toggle
- Dashboard grid uses .ve-dashboard-grid (top) and .ve-dashboard-bottom (bottom)
- Phase 9 entrance animations use .ve-card--entering class

### Integration Points
- index.html: move ctrl-* elements from #page-power into #page-dashboard
- index.html: remove #page-power section entirely
- index.html: remove Power Control nav item from sidebar
- style.css: adjust grid templates for 2-row bottom layout
- app.js: remove or adapt showPage('power') references, ensure ctrl-* IIFEs still find elements

### Critical Risk
- JS IIFEs that bind slider/button handlers execute on DOMContentLoaded. If elements are in DOM (just moved), bindings should work. But #page-power removal means any JS checking `page === 'power'` needs updating.

</code_context>

<specifics>
## Specific Ideas

- User selected "Kompakte Inline-Section" at milestone start — power control should feel like part of the gauge area, not a separate panel
- Override Log as collapsible section with event count badge — keeps dashboard clean but info accessible
- Bottom grid: clear 2-row hierarchy separates system info (row 1) from analytics + Venus control (row 2)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-unified-dashboard-layout*
*Context gathered: 2026-03-18*
