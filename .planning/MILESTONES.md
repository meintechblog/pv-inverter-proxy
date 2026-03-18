# Milestones

## v2.1 Dashboard Redesign & Polish (Shipped: 2026-03-18)

**Phases:** 9-12 (4 phases, 7 plans)
**Commits:** 34 | **LOC:** +1,223/-79 | **Timeline:** ~2 hours
**Git range:** `feat(09-01)` → `feat(12-01)`

**Key accomplishments:**
1. CSS animation foundation: gauge 0.5s + deadband, entrance animations, prefers-reduced-motion
2. Toast notification system: stacking (max 4), exit animations, click-to-dismiss, duplicate suppression
3. Peak statistics: peak kW, operating hours (MPPT), efficiency indicator with dashboard card
4. Smart event notifications: override, fault, temperature (75C), night mode transitions
5. Venus OS Widget: connection status, Apple-style lock toggle (900s safety cap), confirmation dialog
6. Unified single-page dashboard: inline power control, collapsible override log, 2-row bottom grid

**Requirements:** 19/19 complete (4 ANIM, 5 NOTIF, 3 STATS, 4 VENUS, 3 LAYOUT)

---

## v2.0 Dashboard & Power Control (Shipped: 2026-03-18)

**Phases:** 5-8 (4 phases, 7 plans)
**Commits:** 39 | **LOC:** +3,471/-466 | **Timeline:** ~3 hours
**Git range:** `feat(05-01)` → `feat(08-01)`

**Key accomplishments:**
1. DashboardCollector backend with decoded Modbus registers & 60-min TimeSeriesBuffer
2. Venus OS themed 3-file frontend (HTML/CSS/JS) with sidebar navigation
3. WebSocket push infrastructure for real-time updates without polling
4. Live dashboard: SVG power gauge, 3-phase cards, sparkline chart
5. Power Control page: slider with confirmation, Venus OS override detection, EDPC refresh
6. Inverter status panel with daily energy counter, DC values, temperature display

**Requirements:** 18/18 complete (6 DASH, 7 CTRL, 5 INFRA)

---

## v1.0 Venus OS Fronius Proxy (Shipped: 2026-03-18)

**Phases:** 1-4 (4 phases, 9 plans)

**Key accomplishments:**
1. Modbus TCP proxy translating SolarEdge SE30K to Fronius SunSpec profile
2. Venus OS native recognition as "Fronius SE30K-RW00IBNM4"
3. Bidirectional control: power limiting via Model 123 → SE EDPC translation
4. Plugin architecture for future inverter brands
5. Configuration webapp with register viewer and connection status
6. systemd service with auto-start, night mode state machine

---

