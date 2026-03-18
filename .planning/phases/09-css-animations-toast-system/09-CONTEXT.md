# Phase 9: CSS Animations & Toast System - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add smooth, performant CSS animations throughout the dashboard and upgrade the toast notification system to support stacking, exit animations, and click-to-dismiss. No new data features or layout changes — purely visual polish and notification infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Animation Style
- Subtle Industrial feel — minimal, only where it adds value. Like a real SCADA/monitoring panel, not a consumer app.
- Animations should communicate state changes, not decorate.
- GPU-accelerated only: transform and opacity. No layout-triggering properties.

### Power Gauge Arc
- Reduce transition from 0.8s to 0.5s — more responsive to 1Hz updates
- Add deadband to avoid "always chasing" jitter on small fluctuations

### Value Flash Behavior
- Claude's Discretion on flash trigger logic (every change vs significant change vs status-only)
- Existing ve-flash keyframe (0.5s ease-out) is the starting point

### Toast System
- Claude's Discretion on all toast behavior details:
  - Stacking direction and max visible count
  - Auto-dismiss timing (consider tiered by severity)
  - Screen position (top-right recommended by research, user defers)
  - Exit animation style
  - Click-to-dismiss behavior
  - Duplicate toast suppression
- Must fix current issue: single toast with no stacking, overlaps on simultaneous events
- Toast types needed: info, success, warning, error

### Entrance Animations
- Claude's Discretion on:
  - Trigger conditions (initial load only vs reconnect)
  - Stagger order and timing
  - Animation style (fade-in, slide-up, scale, or combination)
- Must respect prefers-reduced-motion (currently not implemented at all)

### Claude's Discretion
- Value flash trigger logic (recommendation: significant changes only, not every 1Hz update)
- Toast stacking direction, position, timing, max visible
- Entrance animation triggers, stagger order, and easing curves
- All micro-interaction details (hover states, button feedback)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Animation Patterns
- `.planning/research/STACK.md` — CSS animation techniques, GPU-accelerated properties, prefers-reduced-motion patterns
- `.planning/research/PITFALLS.md` — Animation jank risks with 1Hz WebSocket updates, deadband recommendation

### Toast System
- `.planning/research/FEATURES.md` — Toast stacking requirements, priority levels, duplicate suppression
- `.planning/research/ARCHITECTURE.md` — Toast system integration points in existing app.js

### Existing Code
- `src/venus_os_fronius_proxy/static/style.css` — Current CSS with --ve-* custom properties, existing transitions, ve-flash keyframe, ve-toast-in keyframe
- `src/venus_os_fronius_proxy/static/app.js` lines 668-678 — Current showToast() implementation (single toast, 3s, no stacking)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `--ve-*` CSS custom properties: full color palette, font families already defined (style.css lines 5-23)
- `ve-flash` keyframe: 0.5s ease-out highlight animation (style.css line 445)
- `ve-toast-in` keyframe: translateY(-12px) entrance (style.css line 987)
- Multiple existing transitions: background 0.15s, stroke-dashoffset 0.8s, etc.

### Established Patterns
- All CSS classes use `ve-` prefix
- Transitions already on buttons (0.15s), sidebar links (0.15s), gauge stroke (0.8s)
- No prefers-reduced-motion support exists yet — needs adding

### Integration Points
- `showToast(message, type)` in app.js — called from power control, WebSocket events, fetch errors
- Gauge SVG stroke-dashoffset transition in style.css line 617
- Page show/hide via classList in app.js navigation functions

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches within the "Subtle Industrial" feel.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-css-animations-toast-system*
*Context gathered: 2026-03-18*
