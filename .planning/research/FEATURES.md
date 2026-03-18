# Feature Landscape: Venus OS Dashboard & Power Control UI (v2.0)

**Domain:** Solar inverter monitoring dashboard with power control, Venus OS visual identity
**Researched:** 2026-03-18
**Confidence:** HIGH (Venus OS gui-v2 source inspected, existing codebase analyzed)

**Scope note:** This research covers NEW features for the v2.0 milestone only. Already shipped in v1.0: config editor, connection status dots, health metrics, register viewer (side-by-side SE30K/Fronius). Those are not repeated here.

## Venus OS Visual Identity Reference

Extracted from `victronenergy/gui-v2` repository `themes/color/Dark.json` and `themes/color/ColorDesign.json` (HIGH confidence -- direct source).

### Core Color Palette

| Token | Hex | Purpose |
|-------|-----|---------|
| `color_blue` (primary) | `#387DC5` | Buttons, active states, "OK" status |
| `color_blue_light` | `#73A2D3` | Hover states, secondary emphasis |
| `color_blue_dim` | `#27588A` | Pressed/down states |
| `color_orange` | `#F0962E` | Warnings, caution states |
| `color_green` | `#72B84C` | Positive indicators (regen, boat page) |
| `color_red` | `#F35C58` | Critical/error states |
| `color_black` (background primary) | `#000000` | Main background |
| `color_gray1` | `#141414` | Widget/card backgrounds |
| `color_gray2` | `#272622` | Surface/panel backgrounds |
| `color_gray9` (font primary) | `#FAF9F5` | Primary text |
| `color_gray5` (font secondary) | `#969591` | Secondary/dimmed text |
| `color_gray4` (font disabled) | `#64635F` | Disabled elements, borders |
| `color_darkBlue` | `#11263B` | Widget backgrounds on overview page |
| `color_darkishBlue` | `#1B3B5C` | Button pressed state |
| `color_critical_background` | `#AA403E` | Error backgrounds |
| `color_dimRed` | `#592220` | Dimmed red indicator |
| `color_dimGreen` | `#508135` | Dimmed green indicator |

### Design Principles (from gui-v2 architecture)

- **Layout:** Generation left, conversion/storage center, consumption right (flow diagram)
- **Technology:** Qt6/QML natively, WebAssembly for browser -- we replicate look only
- **Widget style:** Dark blue cards (`#11263B`) on black background, rounded corners
- **Typography:** Custom Victron fonts (we approximate with system sans-serif)
- **Animations:** Multi-dot flow animations between components (Venus OS signature)
- **Gauges:** Vertical fill gauges with wave animation effect

### Mapping to Our CSS Variables

The existing webapp uses `--bg: #1a1a2e` and `--surface: #16213e` which are already close to Venus OS's dark blue palette. Recommended changes:

| Current | Venus OS Equivalent | New Value |
|---------|---------------------|-----------|
| `--bg: #1a1a2e` | `color_black` | `#000000` or `#0D1117` (slightly softer) |
| `--surface: #16213e` | `color_darkBlue` | `#11263B` |
| `--border: #0f3460` | `color_darkishBlue` | `#1B3B5C` |
| `--accent: #e94560` | `color_blue` | `#387DC5` |
| `--green: #00c853` | `color_green` | `#72B84C` |
| `--red: #ff1744` | `color_red` | `#F35C58` |
| `--yellow: #ffab00` | `color_orange` | `#F0962E` |

---

## Table Stakes

Features users expect from a solar monitoring dashboard. Missing = feels like a toy.

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| **Live power display (total + per-phase)** | Core purpose of a monitoring dashboard. Every solar app shows current W. | LOW | API endpoint exposing parsed Model 103 data | Large number (e.g. "12,450 W"), prominent placement. Update every 1s via WebSocket. |
| **Per-phase breakdown (L1/L2/L3)** | SE30K is 3-phase. Users need to see balance across phases. | LOW | Model 103 registers already cached (offsets 3-5 for current, 10-12 for voltage) | Three columns or bars showing W/A/V per phase. |
| **Operating status indicator** | Users need to know: producing, sleeping, throttled, error. | LOW | Status register already mapped (offset 38 in Model 103) | Text + color badge. Map Sunspec states: 4=MPPT (green), 5=Throttled (orange), 7=Fault (red), 2/6/8=Standby (dim). |
| **Daily energy production** | "How much did I make today?" is the most common user question. | MEDIUM | Needs delta tracking -- Model 103 only has lifetime total (WH at offset 24). Must track midnight reset in-memory. | Store WH at midnight (or service start), show delta. Resets on service restart -- acceptable for in-memory. |
| **Total energy (lifetime)** | Context for daily number. Already available from registers. | LOW | Model 103 WH field (offset 24-25, uint32 + scale) | Display as MWh with one decimal. |
| **Venus OS color scheme** | User explicitly requested "exakte Venus OS Optik." | LOW | CSS variable changes only | Apply the color mapping table above. Biggest visual impact for least effort. |
| **Dark theme** | Venus OS is dark-themed. Current webapp already dark. Matches. | DONE | Already implemented | Just align colors more precisely to Venus OS palette. |

## Differentiators

Features that set this dashboard apart. Not expected, but specifically requested or high-value.

| Feature | Value Proposition | Complexity | Dependencies | Notes |
|---------|-------------------|------------|--------------|-------|
| **Power Control Slider (0-100%)** | Direct power limiting from webapp without Venus OS menu navigation. The whole point of v2.0. | HIGH | Backend: write to ControlState, translate to SE EDPC registers. Frontend: slider + feedback loop. | See "Power Control Safety Design" section below. |
| **Power Control Enable/Disable Toggle** | Must be able to enable/disable power limiting independently of percentage. Maps to WMaxLim_Ena register. | MEDIUM | ControlState.update_wmaxlim_ena() already exists | Toggle switch. When disabled, slider should be visually dimmed. |
| **Venus OS Override Detection** | Show WHEN Venus OS is actively controlling power limit (vs. user manual control). "Who is throttling?" | HIGH | Must detect writes from Venus OS to Model 123 registers vs. writes from webapp API. Need write-source tracking in ControlState. | Key differentiator: no other tool shows this. Display: "Venus OS: 70%" or "Manual: 50%" or "No limit active". |
| **Mini-sparklines (60-min power history)** | Visual trend without leaving the page. Requested in PROJECT.md. | MEDIUM | In-memory ring buffer (backend). SVG sparkline rendering (frontend). WebSocket initial history message. | 3,600 samples (1/sec, downsampled to 360 for display) in a deque. Render as inline SVG polyline (~15 lines JS). |
| **Inverter detail panel (V/A/Hz/Temp)** | Full electrical picture: voltage, current, frequency, temperature per phase. Beyond just power. | LOW | All data already in Model 103 cache (offsets 6-13 for V/A, offset 14-15 for Hz, offsets 32-36 for temp) | Grid layout. Mono font. Update via WebSocket. |
| **Live power limit feedback** | After sending a power limit command, show what the inverter actually accepted. Closed-loop confirmation. | MEDIUM | Read back EDPC registers from SolarEdge after write. Compare commanded vs. actual. | Essential for trust. Show: "Commanded: 70% | Actual: 71.2% | Applied: 0.8s ago". |
| **Power limit revert timeout display** | SunSpec Model 123 has WMaxLimPct_RvrtTms (revert timeout). Show countdown. | LOW | Already in register map at offset 40156. | "Reverts in: 45s" countdown. Important for safety -- users know the limit is temporary. |

## Anti-Features

Features to explicitly NOT build in v2.0.

| Anti-Feature | Why Tempting | Why Avoid | What to Do Instead |
|--------------|-------------|-----------|-------------------|
| **Historical database / persistent logging** | "Show me yesterday's production" | PROJECT.md explicitly out of scope. Venus OS + VRM already handles this. In-memory 60-min ring buffer is the right scope. Storage in LXC adds complexity and maintenance. | 60-min in-memory sparklines only. Link to VRM for history. |
| **Full Venus OS flow diagram replica** | Looks impressive, matches Venus OS exactly | gui-v2 flow diagram requires complex SVG path animations, multi-component layout (battery, grid, loads, PV). Our proxy only knows about PV -- no battery, no grid, no loads data. Building half a flow diagram looks worse than a focused power dashboard. | Focused power-centric dashboard with Venus OS colors/widgets, not a flow replica. |
| **Multi-inverter dashboard** | Future-proofing | v2.0 is single SE30K. Multi-inverter adds tab/grid UI complexity, backend routing, data multiplexing. Architecture supports plugins but UI should not prematurely abstract. | Single inverter view. Design CSS grid to not preclude future expansion. |
| **Battery/grid/load monitoring** | "Complete energy picture" | Proxy only has PV inverter data via Modbus. No access to battery BMS, grid meter, or load data. Would require separate D-Bus or MQTT connections to Venus OS itself. | Show only what we have: PV inverter data. Label clearly as "PV Inverter Dashboard". |
| **Configurable dashboard widgets** | "Let users arrange their view" | Massive frontend complexity for a single-file HTML app. Drag-and-drop, layout persistence, responsive breakpoints for custom layouts. | Fixed layout, well-designed. One good layout beats infinite bad ones. |
| **Power scheduling / automation** | "Limit power at peak hours" | Turns a monitoring tool into an automation platform. Venus OS + Node-RED already handles scheduling. Proxy should be a manual override / testing tool. | Manual slider only. Point users to Venus OS for automation. |
| **Export/CSV download** | "Download my data" | In-memory only, 60 minutes max. CSV of 60 data points is trivial but sets wrong expectations about data retention. | If asked, a simple "copy to clipboard" for current values. No file downloads. |
| **External charting library** | "Use Chart.js for prettier graphs" | Breaks single-file HTML constraint. CDN not available on LAN. 200KB+ for sparklines achievable in 15 LOC. | Inline SVG polyline sparklines. ~15 lines of vanilla JS. |
| **CSS framework (Tailwind/Bootstrap)** | "Faster styling" | Requires CDN (no internet on LAN) or build tooling. Overkill for a focused dashboard. | CSS custom properties with Venus OS palette. Already the existing pattern. |

## Power Control Safety Design

**This is the most critical UX feature in v2.0.** Sending wrong power limits to a 30kW inverter has real consequences (grid violations, revenue loss, equipment stress).

### Safety Principles

1. **Confirmation before action** -- Never apply power limit on slider drag. Require explicit "Apply" button press.
2. **Visual feedback loop** -- Show commanded value, actual inverter response, and any discrepancy.
3. **Timeout-based revert** -- Always send WMaxLimPct_RvrtTms with power limit. If webapp crashes or user forgets, inverter reverts to 100% after timeout.
4. **Enable/disable separation** -- Toggle to enable limiting is separate from percentage slider. Prevents accidental limit application.
5. **Clear state indication** -- Always show who is currently controlling: Venus OS, manual, or nobody.

### Recommended UI Flow

```
+--------------------------------------------------+
|  POWER CONTROL                                    |
|                                                   |
|  Status: [Venus OS controlling: 85%]  (blue)      |
|     -or- [Manual limit: 70%]          (orange)    |
|     -or- [No limit active]            (green)     |
|                                                   |
|  [x] Enable Power Limiting                        |
|                                                   |
|  Power Limit: [=====>-----------] 50%             |
|               0%              100%                |
|                                                   |
|  Revert Timeout: [300] seconds                    |
|                                                   |
|  [ Apply ]  [ Reset to 100% ]                     |
|                                                   |
|  Last command: 70% -> Applied (71.2% actual)      |
|  Reverts in: 4:32                                 |
+--------------------------------------------------+
```

### Safety Constraints

| Constraint | Implementation | Rationale |
|------------|----------------|-----------|
| Minimum revert timeout | 60 seconds floor | Prevents "permanent" limits from manual UI. Venus OS can set its own timeouts. |
| Maximum revert timeout | 3600 seconds (1 hour) | Prevents forgotten limits running overnight. |
| Default revert timeout | 300 seconds (5 minutes) | Reasonable test window. |
| Slider step size | 5% increments | Prevents accidental micro-adjustments. Fine control via number input. |
| Confirmation dialog for < 20% | "Are you sure? This limits a 30kW inverter to < 6kW." | Unusually low limits likely unintentional. |
| Confirmation dialog for 0% | "This will STOP power production entirely." | Zero-power is effectively an off switch. |
| Reset button always visible | Single click to restore 100% | Panic button. No confirmation needed for restoring full power. |
| Disable on disconnect | If SolarEdge connection drops, grey out controls | Cannot verify command delivery. |

## Feature Dependencies

```
[Venus OS Color Scheme]  (CSS only, no backend)
    +--independent

[Live Power Display]
    +--requires--> [DashboardCollector + WebSocket endpoint]
    +--enhances--> [Per-Phase Breakdown] (same data, different view)
    +--enhances--> [Operating Status] (same snapshot)

[Inverter Detail Panel]
    +--requires--> [DashboardCollector]
    +--same-data--> [Live Power Display]

[Daily Energy]
    +--requires--> [Ring Buffer Backend] (midnight delta tracking)
    +--requires--> [DashboardCollector]

[Mini-Sparklines]
    +--requires--> [TimeSeriesBuffer Backend]
    +--requires--> [WebSocket history message on connect]

[Power Control Slider]
    +--requires--> [WebSocket command handler]
    +--requires--> [ControlState backend] (already exists)
    +--requires--> [SolarEdge EDPC write path] (already exists)
    +--enhances--> [Power Limit Feedback] (read-back loop)
    +--enhances--> [Revert Timeout Display]

[Venus OS Override Detection]
    +--requires--> [Write-source tracking in ControlState]
    +--requires--> [WebSocket snapshot includes control.source]

[Power Limit Feedback]
    +--requires--> [EDPC register read-back from SolarEdge]
    +--requires--> [WebSocket power_ack message]
```

### Dependency Notes

- **DashboardCollector:** Central new component. Decodes raw registers into physical values (applying scale factors). Called every poll cycle. Feeds TimeSeriesBuffers and WebSocket broadcast. Foundation for all dashboard widgets.
- **TimeSeriesBuffer:** `collections.deque(maxlen=3600)` per metric. 6 buffers total. ~1.3 MB total memory.
- **ControlState already exists:** `control.py` has `ControlState` class with `update_wmaxlimpct()` and `update_wmaxlim_ena()`. Power control UI is wiring these to WebSocket commands and frontend.
- **EDPC write path exists:** `wmaxlimpct_to_se_registers()` translates SunSpec to SolarEdge Float32. Backend plumbing largely done.

## MVP Recommendation for v2.0

### Phase 1: Foundation (must ship together)

1. **Venus OS color scheme** -- CSS variable swap, biggest visual impact, zero backend work
2. **DashboardCollector + TimeSeriesBuffer** -- Foundation for all dashboard widgets
3. **WebSocket endpoint** -- Real-time data push + initial history
4. **Live power display + per-phase breakdown** -- Core dashboard purpose
5. **Operating status indicator** -- Essential context for power data

### Phase 2: Power Control (core v2.0 value)

6. **Power control WebSocket command handler** -- Backend for slider
7. **Power control slider + toggle** -- The main v2.0 feature
8. **Power limit feedback** -- Closed-loop confirmation
9. **Venus OS override detection** -- Key differentiator

### Phase 3: Polish

10. **Mini-sparklines** -- Visual trend, 60-min history
11. **Daily energy tracking** -- Most-asked metric
12. **Inverter detail panel** -- Complete electrical picture
13. **Revert timeout countdown** -- Safety visibility

### Defer to v2.x

- Venus OS flow-style layout (complex, diminishing returns without full system data)
- Power scheduling / automation

## Sparkline Implementation Notes

For the single-file HTML constraint, use inline SVG sparklines. No library needed -- a sparkline is ~15 lines of vanilla JS:

```javascript
function drawSparkline(svgEl, data, color) {
    const w = svgEl.clientWidth, h = svgEl.clientHeight;
    const max = Math.max(...data), min = Math.min(...data);
    const range = max - min || 1;
    const points = data.map((v, i) =>
        `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`
    ).join(' ');
    svgEl.innerHTML = `<polyline points="${points}" fill="none"
        stroke="${color}" stroke-width="1.5"/>`;
}
```

History sent once on WebSocket connect. Frontend appends each snapshot's value to its local array and redraws the SVG polyline.

## Sources

- [Victron gui-v2 repository](https://github.com/victronenergy/gui-v2) -- Theme colors from `themes/color/Dark.json` and `themes/color/ColorDesign.json` (HIGH confidence, direct source)
- [Venus OS gui-v2 ColorDesign.json](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/ColorDesign.json) -- HIGH confidence
- [Venus OS gui-v2 Dark.json](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/Dark.json) -- HIGH confidence
- [fnando/sparkline](https://github.com/fnando/sparkline) -- Zero-dependency SVG sparkline pattern reference (evaluated, not used)
- [aiohttp WebSocket docs](https://docs.aiohttp.org/en/stable/web_quickstart.html) -- WebSocket handler pattern
- Existing codebase analysis: `control.py`, `webapp.py`, `static/index.html` (HIGH confidence, direct source)

---
*Feature research for: Venus OS Fronius Proxy v2.0 Dashboard & Power Control UI*
*Researched: 2026-03-18*
