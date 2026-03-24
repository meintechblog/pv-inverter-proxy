# Project: PV-Inverter-Master

## Design System

All frontend code follows the Venus OS gui-v2 dark theme. Every new element MUST use these conventions.

### Color Tokens (CSS Variables)

| Token | Value | Usage |
|-------|-------|-------|
| `--ve-accent` | `var(--ve-blue)` | Generic accent — decoded column, spinner accent |
| `--ve-blue` | `#387DC5` | Primary accent, active states, links, gauge fill |
| `--ve-blue-light` | `#73A2D3` | Hover states |
| `--ve-blue-dim` | `#27588A` | Active nav background |
| `--ve-orange` | `#F0962E` | Warning, hint cards, sun/solar elements |
| `--ve-red` | `#F35C58` | Error, disconnect, cancel hover |
| `--ve-green` | `#72B84C` | Success, save button, connected, auto-detect banner |
| `--ve-bg` | `#141414` | Page background (60%) |
| `--ve-bg-surface` | `#272622` | Sidebar, panels (30%) |
| `--ve-bg-widget` | `#11263B` | Dashboard cards |
| `--ve-border` | `#64635F` | Borders, separators |
| `--ve-text` | `#FAF9F5` | Primary text |
| `--ve-text-dim` | `#969591` | Labels, secondary text |
| `--ve-text-secondary` | `#DCDBD7` | Subtle text |
| `--ve-ok` | `var(--ve-blue)` | Alias: healthy state |
| `--ve-warning` | `var(--ve-orange)` | Alias: warning state |
| `--ve-error` | `var(--ve-red)` | Alias: error state |
| `--ve-success` | `var(--ve-green)` | Alias: success state |

| `--ve-radius` | `12px` | Default border radius for cards/panels |
| `--ve-radius-sm` | `6px` | Buttons, inputs, small elements |

**Rule:** NEVER use hardcoded hex colors. Always use `var(--ve-*)`. Exception: `#fff` / `#000` for high-contrast toggle knobs only.
**Rule:** Use `var(--ve-duration-*)` and `var(--ve-easing-*)` for transitions, not hardcoded values.

### Typography

| Token | Value |
|-------|-------|
| `--ve-font` | `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` |
| `--ve-mono` | `'Courier New', monospace` |

| Role | Size | Weight |
|------|------|--------|
| Card title / h2 | `1rem` (16px) | 600 |
| Body text | `0.9rem` (14.4px) | 400 |
| Label / secondary | `0.85rem` (13.6px) | 400 |
| Small / badge | `0.8rem` (12.8px) | 400 |
| Register data | `0.85em` | 400 (monospace) |

### Spacing Scale

Use only these values: `4px`, `8px`, `10px`, `12px`, `14px`, `16px`, `24px`, `32px`, `48px`.

- Card padding: `16px`
- Form group margin: `10px 0`
- Grid gap: `1rem` (16px)
- Button padding: `8px 16px` (normal), `4px 14px` (small)

### Border Radius Scale

| Role | Value |
|------|-------|
| Buttons, badges, inputs | `4px` - `6px` |
| Cards, panels | `12px` |
| Status dots, toggles | `50%` (circle) |
| Toggle track | `10px` |
| MQTT overlay | `8px` |

### Animation Tokens

| Token | Value |
|-------|-------|
| `--ve-duration-fast` | `150ms` |
| `--ve-duration-normal` | `300ms` |
| `--ve-duration-slow` | `500ms` |
| `--ve-easing-default` | `cubic-bezier(0.4, 0, 0.2, 1)` |
| `--ve-easing-out` | `cubic-bezier(0, 0, 0.2, 1)` |

Always use `transition: [property] var(--ve-duration-*) var(--ve-easing-*)`.

### Naming Convention

All classes use `ve-` prefix (Venus Energy):

| Pattern | Examples |
|---------|----------|
| `ve-card` | Base card |
| `ve-card-title` | Card heading |
| `ve-panel` | Config/form container |
| `ve-panel-header` | Panel header with inline actions |
| `ve-btn`, `ve-btn--primary`, `ve-btn--sm` | Button variants |
| `ve-btn--save`, `ve-btn--cancel` | Action buttons |
| `ve-btn-pair` | Save + Cancel group |
| `ve-dot`, `ve-dot--dim` | Connection status indicator |
| `ve-input`, `ve-input--dirty` | Form input + dirty state |
| `ve-form-group` | Label + input wrapper |
| `ve-hint-card`, `ve-hint-card--success` | Notification cards |
| `ve-hint-header`, `ve-hint-subtext` | Hint card internals |
| `ve-reg-*` | Register viewer (header, row, addr, name, value, decoded) |
| `ve-toggle`, `ve-toggle-label` | Toggle switches |
| `ve-switch`, `ve-switch-knob` | Register filter toggle |
| `ve-gauge-*` | Power gauge elements |
| `ve-phase-*` | 3-phase AC table |
| `ve-spinner-*` | Loading spinner |
| `mqtt-gated` | MQTT dependency overlay |
| `venus-dependent` | Elements requiring Venus OS |
| `ve-config-grid` | Config 2-column layout |
| `ve-dashboard-top` | Gauge + phases row |
| `ve-dashboard-grid` | Main dashboard grid |
| `ve-dashboard-info-row` | Connection + Venus row |
| `ve-doc-link` | Documentation badge |

### Component Patterns

**Status Dots:**
- `.ve-dot` — 10px circle, `background: var(--ve-text-dim)` (default grey)
- Green: `var(--ve-green)` — connected
- Orange: `var(--ve-orange)` — connecting/warning
- Red: `var(--ve-red)` — disconnected/error
- Add `ve-dot--dim` for uninitialized state

**Buttons:**
- Primary: `ve-btn ve-btn--primary` — blue background
- Save: `ve-btn ve-btn--sm ve-btn--save` — green, appears only when dirty
- Cancel: `ve-btn ve-btn--sm ve-btn--cancel` — transparent, red on hover
- Always pair Save + Cancel in `ve-btn-pair` span

**Cards:**
- Dashboard: `ve-card` with `ve-bg-widget` background, `12px` radius
- Config: `ve-panel` with `ve-bg-surface` background, `12px` radius
- Hint: `ve-hint-card` (orange), `ve-hint-card--success` (green)

**MQTT Gate:**
- Add `venus-dependent` class to elements needing MQTT
- JS adds `mqtt-gated` class when MQTT disconnected
- Overlay: dark semi-transparent (`rgba(20,20,20,0.82)`) with centered text

**Config Forms:**
- Dirty tracking: compare against `_cfgOriginal` on every `input` event
- Changed fields: add `ve-input--dirty` (subtle green border)
- Save/Cancel buttons: show/hide via `_cfgUpdateSaveBtn(section)`
- Cancel restores original values via `_cfgCancel(section)`

**Register Viewer:**
- 5-column grid: Addr | Name | SE30K Source | Fronius Target | Decoded
- Hide Empty toggle: `ve-empty` class + `ve-show-empty` to reveal
- Decoded column: SunSpec scale factor + enum lookup from `SUNSPEC_DECODE` map
- Loading spinner until first data arrives

### Responsive Breakpoints

| Breakpoint | Layout |
|------------|--------|
| > 1024px | Full desktop: sidebar visible, 2-column dashboard |
| <= 1024px | Tablet: hamburger nav, dashboard top stacks to 1 column |
| <= 768px | Mobile: single column everything |
| <= 480px | Small mobile: config grid 1 column, compact register table |

### URL Navigation

Pages persist via `window.location.hash` (`#dashboard`, `#config`, `#registers`). On load, hash is read and correct page restored.

### Known Technical Debt

These exist from organic growth. Fix when touching the relevant code:

1. **Three status dot components:** `ve-dot` (12px), `ve-status-indicator` (10px), `ve-status-dot` (10px) — should consolidate to one
2. **Two toggle implementations:** `ve-toggle` (pseudo-element knob, bounce easing) vs `ve-switch` (explicit knob element) — should consolidate
3. **Missing `ve-` prefix:** `sidebar`, `nav-item`, `hamburger`, `content`, `page`, `mqtt-gated`, `venus-dependent`, `sparkline-line/fill` — legacy names, don't rename without updating all references
4. **Mixed units:** spacing uses mix of `px`/`rem`/`em` — prefer `px` for spacing, `rem` for font sizes
5. **Hardcoded transition durations:** many use literal `0.15s` instead of `var(--ve-duration-fast)` — fix when editing
6. **Inline `style="display:none"`:** several HTML elements use inline styles for initial hide — should use CSS class

## Code Conventions

- **Python:** asyncio, structlog logging, dataclasses for config
- **Frontend:** Zero dependencies, vanilla JS, no build tooling
- **Deployment:** `pip install -e .` on LXC, `importlib.resources` serves static files
- **Config:** YAML with nested `inverter:` and `venus:` sections
