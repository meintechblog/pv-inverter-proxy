# Phase 9: CSS Animations & Toast System - Research

**Researched:** 2026-03-18
**Domain:** CSS animations, prefers-reduced-motion accessibility, vanilla JS toast notification system
**Confidence:** HIGH

## Summary

Phase 9 is a purely frontend phase -- no backend changes required. The existing codebase already has partial implementations of all features: a gauge arc transition (0.8s), a value flash animation (`ve-flash` keyframe + `flashValue()` function), a basic single-toast system (`showToast()`), and toast entrance animation (`ve-toast-in` keyframe). The work is about completing, upgrading, and adding accessibility compliance to these existing foundations.

The "Subtle Industrial" design constraint from CONTEXT.md means animations should communicate state changes (SCADA-style), not decorate. All animations use only GPU-accelerated properties (`transform`, `opacity`). The existing `--ve-*` CSS custom property system provides a clean extension point for animation timing variables. The zero-dependency constraint remains -- everything is vanilla CSS3 + vanilla JS.

**Primary recommendation:** Work in three passes: (1) add prefers-reduced-motion and animation CSS variables first (foundation), (2) upgrade the toast system to support stacking with a container element, (3) add entrance animations and polish gauge/flash behavior.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Subtle Industrial feel -- minimal animations, like SCADA/monitoring, not consumer app
- Animations communicate state changes, not decorate
- GPU-accelerated only: transform and opacity. No layout-triggering properties
- Power gauge arc: reduce transition from 0.8s to 0.5s for more responsive 1Hz updates
- Power gauge arc: add deadband to avoid jitter on small fluctuations
- Toast types needed: info, success, warning, error
- Must fix current issue: single toast with no stacking, overlaps on simultaneous events
- Must add prefers-reduced-motion support (currently missing entirely)

### Claude's Discretion
- Value flash trigger logic (recommendation: significant changes only, not every 1Hz update)
- Toast stacking direction, position, timing, max visible
- Toast duplicate suppression behavior
- Toast exit animation style
- Toast click-to-dismiss behavior
- Entrance animation triggers (initial load only vs reconnect)
- Entrance animation stagger order, timing, and style
- All micro-interaction details (hover states, button feedback)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ANIM-01 | Power Gauge hat smooth animierte Arc-Transition bei Wertaenderungen | Reduce to 0.5s transition, add deadband in `updateGauge()`, `will-change: stroke-dashoffset` on `#gauge-fill` |
| ANIM-02 | Dashboard-Widgets haben staggered Entrance-Animations beim Laden | `@keyframes ve-slide-up` with `animation-delay` via `nth-child` on `.ve-card` elements, trigger on page load |
| ANIM-03 | Wertaenderungen in Cards haben subtle Highlight/Flash-Animation | Existing `flashValue()` + `ve-value-flash` class already works; enhance with threshold-based triggering |
| ANIM-04 | Alle Animationen respektieren prefers-reduced-motion und nutzen nur GPU-accelerated Properties | Global `@media (prefers-reduced-motion: reduce)` rule zeroing durations; JS check via `matchMedia` for toast timers |
| NOTIF-01 | Toast-System mit Stacking (mehrere Toasts gleichzeitig sichtbar, nicht ueberlappend) | Replace body-appended toasts with `.ve-toast-container` fixed element, flex-column stacking, max 4 visible |
| NOTIF-05 | Toasts haben Exit-Animation und Click-to-Dismiss | `ve-toast--exiting` class with `ve-toast-out` keyframe, `animationend` listener for removal, click handler on each toast |
</phase_requirements>

## Standard Stack

### Core
| Technology | Version | Purpose | Why Standard |
|------------|---------|---------|--------------|
| CSS3 `@keyframes` | Modern browsers | Entrance animations, toast in/out | Native, zero-dependency, GPU-composited |
| CSS `transition` | Modern browsers | Gauge arc, value flash, hover states | Already used throughout codebase |
| CSS `prefers-reduced-motion` | Modern browsers | Accessibility compliance | W3C WCAG 2.1 technique C39 |
| Vanilla JS DOM API | ES6+ | Toast container management, class toggling | Existing pattern, zero dependencies |

### Supporting
| Technology | Version | Purpose | When to Use |
|------------|---------|---------|-------------|
| CSS Custom Properties (`--ve-*`) | Modern browsers | Parameterize animation timing/easing | All animation duration and easing values |
| `requestAnimationFrame` | Modern browsers | Batch sparkline rendering | Wrap `renderSparkline()` to prevent frame drops |
| `window.matchMedia` | Modern browsers | JS-side reduced motion detection | Guard JS-driven animations (toast auto-dismiss timing) |
| `animationend` event | Modern browsers | Clean up after exit animations | Toast removal after exit animation completes |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CSS `@keyframes` | GSAP / anime.js | Violates zero-dependency constraint; CSS sufficient for these effects |
| Vanilla toast system | Toastify / notyf | Violates zero-dependency constraint; existing `showToast()` just needs enhancement |
| `will-change` everywhere | No hints | Only use on `#gauge-fill` (constant animation); overuse wastes GPU memory |

**Installation:** No changes. Zero new dependencies.

## Architecture Patterns

### Recommended Changes Structure
```
src/venus_os_fronius_proxy/static/
  style.css     # ADD: animation variables, prefers-reduced-motion, toast container,
                #       entrance animations, toast exit animation, stacking layout
  app.js        # MODIFY: showToast() refactored for stacking, gauge deadband,
                #         flashValue() threshold, entrance animation trigger
  index.html    # ADD: toast container div (before closing </body>)
```

### Pattern 1: Animation CSS Custom Properties
**What:** Centralize all animation timing in `:root` variables alongside existing `--ve-*` palette.
**When to use:** Any animation duration or easing reference.
**Example:**
```css
:root {
    /* Add to existing :root block */
    --ve-duration-fast: 150ms;
    --ve-duration-normal: 300ms;
    --ve-duration-slow: 500ms;
    --ve-easing-default: cubic-bezier(0.4, 0, 0.2, 1);
    --ve-easing-out: cubic-bezier(0, 0, 0.2, 1);
}
```
**Source:** Matches existing `--ve-*` naming convention in style.css lines 4-24.

### Pattern 2: Toast Container with Flex Stacking
**What:** A fixed-position container that manages toast vertical layout via `flex-direction: column` and `gap`.
**When to use:** Replacing the current per-toast fixed positioning.
**Example:**
```css
.ve-toast-container {
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 2000;
    display: flex;
    flex-direction: column;
    gap: 8px;
    pointer-events: none;
    max-width: 380px;
}
.ve-toast {
    pointer-events: auto;
    /* Remove position: fixed from individual toasts */
}
```
**Source:** Standard toast stacking pattern used by all major toast libraries.

### Pattern 3: Prefers-Reduced-Motion Global Override
**What:** Single media query that disables all animations and transitions project-wide.
**When to use:** Must be the LAST CSS rule to override all animation durations.
**Example:**
```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}
```
**Source:** [W3C WCAG 2.1 Technique C39](https://www.w3.org/WAI/WCAG21/Techniques/css/C39), [web.dev prefers-reduced-motion guide](https://web.dev/articles/prefers-reduced-motion)

### Pattern 4: Gauge Deadband
**What:** Skip gauge DOM updates when power change is below threshold to prevent "always chasing" jitter.
**When to use:** In `updateGauge()` before setting `strokeDashoffset`.
**Example:**
```javascript
let lastGaugePower = 0;
const GAUGE_DEADBAND_W = 50;

function updateGauge(powerW) {
    if (Math.abs(powerW - lastGaugePower) < GAUGE_DEADBAND_W) return;
    lastGaugePower = powerW;
    // ... existing gauge update logic
}
```
**Source:** CONTEXT.md locked decision + PITFALLS.md Pitfall 8.

### Anti-Patterns to Avoid
- **Animating `width`, `height`, `top`, `left`, `margin`:** Triggers layout recalc on every frame. Use `transform` and `opacity` only.
- **`will-change` on all animated elements:** Creates excessive compositor layers. Only use on `#gauge-fill` (constantly animated element).
- **`display: none` with transitions:** CSS transitions cannot animate from `display: none`. The page switching pattern uses `display: none/block` and must remain as-is (entrance animations apply only to dashboard widgets on initial load, not page transitions).
- **Toast `alert()` or `confirm()`:** Blocks the main thread. Already avoided.
- **Per-element flash on every 1Hz update:** Existing `flashValue()` fires on every text change. With 15+ elements updating at 1Hz, this creates constant visual noise. Apply deadband or threshold-based triggering.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Animation timing functions | Custom JS easing math | CSS `cubic-bezier()` via `--ve-easing-*` variables | Browser-native, GPU-composited, handles interruption |
| Toast stacking layout | Manual `top` offset calculation per toast | Flex container with `gap` | Automatically adjusts when toasts are added/removed |
| Reduced motion detection | Custom user preference storage | `prefers-reduced-motion` media query + `matchMedia` | OS-level setting, works across all browsers |
| Exit animation cleanup | `setTimeout` matching animation duration | `animationend` event listener | Resilient to duration changes, no magic numbers |
| Frame timing | `setInterval` or `setTimeout` for animation frames | CSS transitions or `requestAnimationFrame` | Browser scheduler optimizes paint timing |

**Key insight:** Every animation in this phase can be achieved with CSS transitions/keyframes. JS is only needed for: (1) toast container management (DOM creation/removal), (2) deadband logic (conditional updates), (3) entrance animation triggering (adding/removing classes).

## Common Pitfalls

### Pitfall 1: Gauge Arc Never Settles at 1Hz Update Rate
**What goes wrong:** With 0.8s transition and 1s updates, the gauge is perpetually mid-transition. New values arrive before the previous transition completes, causing a "chasing" effect.
**Why it happens:** Transition duration (0.8s) is too close to update interval (1.0s), leaving only 200ms of settled time.
**How to avoid:** Reduce transition to 0.5s (locked decision) AND add 50W deadband to skip insignificant changes. This gives 500ms of settled display per update cycle when values are stable.
**Warning signs:** Gauge arc never stops moving even when power output is stable.

### Pitfall 2: Flash Animation Fatigue at 1Hz
**What goes wrong:** `flashValue()` fires on every text content change. With 15+ `.ve-live-value` elements updating every second, the entire dashboard constantly flashes blue, creating visual noise instead of highlighting important changes.
**Why it happens:** The current trigger is `textContent !== newValue`, which fires on every poll even for trivial changes (e.g., voltage goes from 230.1 to 230.2).
**How to avoid:** Apply flash only on significant changes. For voltage: > 2V change. For current: > 0.5A change. For power: > 100W change. For temperature: > 1C change. Track previous numeric values (not strings) and compare with thresholds.
**Warning signs:** Multiple elements flashing simultaneously on every WebSocket message.

### Pitfall 3: Toast z-index Conflict with Modal
**What goes wrong:** Toast has `z-index: 2000`, modal overlay has `z-index: 1000`. Toasts appear above the confirmation dialog, obscuring it.
**Why it happens:** Toast container is always on top regardless of modal state.
**How to avoid:** Either suppress toast creation while a modal is visible (`document.querySelector('.ve-modal-overlay')` check), or queue toasts and show after modal closes.
**Warning signs:** Error toast appearing on top of the power limit confirmation dialog.

### Pitfall 4: Toast Accumulation Without Max Limit
**What goes wrong:** Rapid-fire events (connection flapping, Venus OS control cycling) create dozens of toasts, filling the screen.
**Why it happens:** No rate limiting or max visible count.
**How to avoid:** Cap at 4 visible toasts. When a 5th arrives, dismiss the oldest non-error toast. Implement duplicate suppression: if same message text is already showing, skip (or increment a counter badge).
**Warning signs:** More than 4 toasts visible simultaneously; identical toasts stacking up.

### Pitfall 5: Entrance Animations Replay on Every Page Switch
**What goes wrong:** If entrance animations are CSS `animation` on `.ve-card`, they replay every time the user navigates away and back to the dashboard (because `display: none` removes the element from rendering, resetting animation state).
**Why it happens:** CSS animations replay when elements go from `display: none` to `display: block`.
**How to avoid:** Use a one-shot class (e.g., `ve-card--entering`) added via JS on initial load only, then remove after animation completes. Do NOT put the animation directly on `.ve-card`.
**Warning signs:** Cards sliding in every time the user clicks Dashboard in the nav.

## Code Examples

### Toast System Refactor
```javascript
// Source: Derived from existing showToast() at app.js line 670-678
// Enhanced with stacking, exit animation, click-to-dismiss

var toastContainer = null;
var MAX_TOASTS = 4;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.getElementById('toast-container');
    }
    return toastContainer;
}

function showToast(message, type, duration) {
    var container = getToastContainer();
    if (!container) return;

    // Duplicate suppression
    var existing = container.querySelectorAll('.ve-toast');
    for (var i = 0; i < existing.length; i++) {
        if (existing[i].textContent === message) return;
    }

    // Enforce max visible
    while (container.children.length >= MAX_TOASTS) {
        dismissToast(container.lastElementChild);
    }

    // Tiered duration by type
    if (!duration) {
        duration = (type === 'error') ? 8000 : (type === 'warning') ? 5000 : 3000;
    }

    var toast = document.createElement('div');
    toast.className = 've-toast ve-toast--' + (type || 'info');
    toast.textContent = message;
    toast.setAttribute('role', 'alert');

    // Newest at top
    container.prepend(toast);

    // Auto-dismiss
    var timer = setTimeout(function() { dismissToast(toast); }, duration);

    // Click to dismiss
    toast.addEventListener('click', function() {
        clearTimeout(timer);
        dismissToast(toast);
    });
}

function dismissToast(toast) {
    if (!toast || toast.classList.contains('ve-toast--exiting')) return;
    toast.classList.add('ve-toast--exiting');
    toast.addEventListener('animationend', function() {
        toast.remove();
    });
}
```

### Prefers-Reduced-Motion (CSS)
```css
/* Source: W3C WCAG 2.1 Technique C39 */
/* MUST be last rule in stylesheet */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}
```

### Prefers-Reduced-Motion (JS Guard)
```javascript
// Source: web.dev prefers-reduced-motion guide
var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

// Use in toast duration: instant dismiss if reduced motion
function getToastDuration(type) {
    if (prefersReducedMotion.matches) return 5000; // Longer for reading, no animation
    return (type === 'error') ? 8000 : (type === 'warning') ? 5000 : 3000;
}
```

### Entrance Animation (One-Shot)
```css
@keyframes ve-slide-up {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
}

.ve-card--entering {
    animation: ve-slide-up var(--ve-duration-normal) var(--ve-easing-out) both;
}

/* Stagger delays applied via JS or nth-child */
.ve-card--entering:nth-child(1) { animation-delay: 0ms; }
.ve-card--entering:nth-child(2) { animation-delay: 60ms; }
.ve-card--entering:nth-child(3) { animation-delay: 120ms; }
.ve-card--entering:nth-child(4) { animation-delay: 180ms; }
```

```javascript
// Trigger once on initial WebSocket connection
var entranceAnimated = false;
// In ws.onopen:
if (!entranceAnimated) {
    document.querySelectorAll('#page-dashboard .ve-card').forEach(function(card) {
        card.classList.add('ve-card--entering');
    });
    entranceAnimated = true;
    // Clean up after animations complete
    setTimeout(function() {
        document.querySelectorAll('.ve-card--entering').forEach(function(card) {
            card.classList.remove('ve-card--entering');
        });
    }, 600); // longest stagger + duration
}
```

### Gauge Transition (Updated)
```css
#gauge-fill {
    transition: stroke-dashoffset 0.5s ease-out, stroke 0.5s ease;
    will-change: stroke-dashoffset;
}
```

### Toast Exit Animation
```css
@keyframes ve-toast-out {
    from { opacity: 1; transform: translateX(0); }
    to   { opacity: 0; transform: translateX(100%); }
}

.ve-toast--exiting {
    animation: ve-toast-out 0.25s var(--ve-easing-default) forwards;
    pointer-events: none;
}
```

## State of the Art

| Old Approach (Current Code) | Current Approach (Phase 9 Target) | Impact |
|------------------------------|-----------------------------------|--------|
| Single toast, `body.appendChild()`, no stacking | Toast container with flex stacking, max 4 visible | Multiple simultaneous notifications readable |
| Gauge 0.8s transition, no deadband | 0.5s transition + 50W deadband | Gauge settles between 1Hz updates |
| No `prefers-reduced-motion` support | Global media query + JS `matchMedia` guard | WCAG 2.1 accessibility compliance |
| `flashValue()` on every text change | Threshold-based flash (significant changes only) | Reduced visual noise, meaningful highlights |
| No entrance animations | One-shot staggered slide-up on first connection | Professional first impression, SCADA feel |
| Toast removed instantly (`toast.remove()`) | Exit animation before removal (`animationend`) | Smooth departure, user sees toast leaving |

## Open Questions

1. **Flash threshold values**
   - What we know: Need to avoid flashing on every 1Hz update
   - What's unclear: Exact thresholds per metric (voltage, current, power, temperature) -- need to tune against live data
   - Recommendation: Start with generous thresholds (voltage > 2V, current > 0.5A, power > 100W, temp > 1C), tune in production

2. **Toast position on mobile**
   - What we know: Top-right works on desktop
   - What's unclear: On mobile (<768px), top-right may be under the hamburger or too narrow
   - Recommendation: Switch to full-width centered at bottom on mobile via media query

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ANIM-01 | Gauge arc 0.5s transition, deadband in JS | manual-only | Visual inspection in browser | N/A -- CSS/JS only |
| ANIM-02 | Staggered entrance animations on load | manual-only | Visual inspection in browser | N/A -- CSS/JS only |
| ANIM-03 | Value flash on significant changes only | manual-only | Visual inspection in browser | N/A -- CSS/JS only |
| ANIM-04 | prefers-reduced-motion disables all animations | manual-only | Toggle in Chrome DevTools > Rendering > Emulate prefers-reduced-motion | N/A -- CSS/JS only |
| NOTIF-01 | Toast stacking, no overlap, max 4 | manual-only | Trigger multiple events rapidly in browser | N/A -- CSS/JS only |
| NOTIF-05 | Toast exit animation + click-to-dismiss | manual-only | Click toasts, observe exit animation | N/A -- CSS/JS only |

**Justification for manual-only:** All phase 9 requirements are purely frontend CSS/JS visual behavior. The project has no browser testing infrastructure (no Playwright, Cypress, or headless browser tests). Adding browser automation tooling is out of scope for this phase. Backend tests (pytest) cannot verify CSS animations or DOM behavior.

### Sampling Rate
- **Per task commit:** Visual inspection in browser at `http://localhost:8080`
- **Per wave merge:** `python -m pytest tests/ -x -q` (ensure no backend regressions from any incidental changes)
- **Phase gate:** All 6 requirements visually verified in browser

### Wave 0 Gaps
None -- no new test files needed. All validation is manual visual inspection. Existing pytest infrastructure covers backend regression detection.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of `style.css` (998 lines), `app.js` (945 lines), `index.html` (280 lines)
- `.planning/research/STACK.md` -- CSS animation techniques, toast patterns, GPU acceleration
- `.planning/research/PITFALLS.md` -- Animation jank, toast stacking, gauge transition pitfalls
- `.planning/research/ARCHITECTURE.md` -- Integration points, data flow, anti-patterns
- [W3C WCAG 2.1 Technique C39](https://www.w3.org/WAI/WCAG21/Techniques/css/C39) -- prefers-reduced-motion standard
- [MDN prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion) -- media query reference
- [web.dev prefers-reduced-motion guide](https://web.dev/articles/prefers-reduced-motion) -- implementation patterns

### Secondary (MEDIUM confidence)
- [CSS-Tricks prefers-reduced-motion](https://css-tricks.com/almanac/rules/m/media/prefers-reduced-motion/) -- practical CSS patterns
- [Pope Tech accessible animation guide (2025)](https://blog.pope.tech/2025/12/08/design-accessible-animation-and-movement/) -- no-motion-first approach
- [Harrison Broadbent vanilla JS toast](https://harrisonbroadbent.com/blog/native-js-toast-notifications/) -- vanilla toast stacking pattern

### Tertiary (LOW confidence)
None -- all findings verified with primary or secondary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- CSS3 animations and vanilla JS are well-documented browser standards
- Architecture: HIGH -- all integration points verified against actual codebase
- Pitfalls: HIGH -- derived from direct code analysis and 1Hz update frequency constraints
- Animation patterns: HIGH -- GPU-composited properties are established browser behavior
- Toast stacking: HIGH -- standard pattern with flex container, verified across multiple sources

**Research date:** 2026-03-18
**Valid until:** 2026-06-18 (stable browser standards, 90-day validity)
