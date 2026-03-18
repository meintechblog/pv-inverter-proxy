# Roadmap: Venus OS Fronius Proxy

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-03-18)
- **v2.0 Dashboard & Power Control** — Phases 5-8 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-4) — SHIPPED 2026-03-18</summary>

- [x] Phase 1: Protocol Research & Validation (2/2 plans)
- [x] Phase 2: Core Proxy / Read Path (2/2 plans)
- [x] Phase 3: Control Path & Production Hardening (3/3 plans)
- [x] Phase 4: Configuration Webapp (2/2 plans)

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

### v2.0 Dashboard & Power Control

- [ ] **Phase 5: Data Pipeline & Theme Foundation** - Backend data collector, time series buffer, 3-file split, Venus OS theme
- [ ] **Phase 6: Live Dashboard** - WebSocket push, power gauge, 3-phase details, sparklines
- [ ] **Phase 7: Power Control** - Read-only display, test slider, enable/disable, override detection, EDPC refresh
- [ ] **Phase 8: Inverter Details & Polish** - Status panel, daily energy, existing config/register integration

## Phase Details

### Phase 5: Data Pipeline & Theme Foundation
**Goal**: Backend delivers decoded inverter data per poll cycle and frontend has Venus OS visual identity with proper file structure
**Depends on**: Phase 4
**Requirements**: INFRA-02, INFRA-03, INFRA-04, DASH-01
**Success Criteria** (what must be TRUE):
  1. DashboardCollector produces a structured JSON payload of decoded inverter data (power, voltage, current, frequency, temperature, status) after each poll cycle
  2. TimeSeriesBuffer stores 60 minutes of power history and serves it as an array suitable for sparkline rendering
  3. Frontend is split into index.html + style.css + app.js, all served correctly by the existing aiohttp webapp
  4. Opening the webapp shows Venus OS themed UI with correct colors (#387DC5 blue, #141414 dark background, #FAF9F5 text)
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — Backend data pipeline: DashboardCollector, TimeSeriesBuffer, REST endpoint, static handler
- [ ] 05-02-PLAN.md — Frontend 3-file split with Venus OS theme, sidebar navigation, ported v1.0 functionality

### Phase 6: Live Dashboard
**Goal**: Users see real-time inverter power data updating live without page refresh, with per-phase breakdown and trend sparklines
**Depends on**: Phase 5
**Requirements**: INFRA-01, INFRA-05, DASH-02, DASH-03, DASH-06
**Success Criteria** (what must be TRUE):
  1. WebSocket connection pushes updated inverter data to all connected browsers within one poll cycle (no manual refresh needed)
  2. Central power gauge shows current total power output vs 30kW rated capacity, updating live
  3. L1/L2/L3 section shows per-phase voltage, current, and power values updating in real-time
  4. Mini sparkline chart renders the last 60 minutes of power history as an SVG polyline, growing with each update
  5. Config and Register Viewer from v1.0 are accessible as tabs/sections within the new dashboard layout
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD

### Phase 7: Power Control
**Goal**: Users can view and test power limiting from the webapp with safety confirmations, and see who currently controls the inverter
**Depends on**: Phase 6
**Requirements**: CTRL-04, CTRL-05, CTRL-06, CTRL-07, CTRL-08, CTRL-09, CTRL-10
**Success Criteria** (what must be TRUE):
  1. Dashboard shows current power limit percentage and the source that set it (webapp manual, Venus OS, or none)
  2. User can drag a slider to set power limit 0-100% and must confirm via dialog before the value is written to the inverter
  3. User can toggle power limiting on/off with a confirmation step, and the inverter responds accordingly
  4. After applying a power limit, the UI shows confirmation that the SE30K accepted the new value (live feedback from actual register read-back)
  5. When Venus OS overrides the power limit, the dashboard clearly indicates Venus OS has control and logs the override event with timestamp and value
**Plans**: TBD

Plans:
- [ ] 07-01: TBD
- [ ] 07-02: TBD

### Phase 8: Inverter Details & Polish
**Goal**: Dashboard shows comprehensive inverter health information and daily production summary
**Depends on**: Phase 6
**Requirements**: DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. Inverter status panel displays operating state (Operating/Sleeping/Throttled/Fault), cabinet temperature, and DC input values
  2. Daily energy counter shows today's production in kWh, resetting on proxy restart, updating live
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

## Progress

**Execution Order:** Phases execute in numeric order: 5 -> 6 -> 7 -> 8

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|---------------|--------|-----------|
| 1. Protocol Research & Validation | v1.0 | 2/2 | Complete | 2026-03-18 |
| 2. Core Proxy (Read Path) | v1.0 | 2/2 | Complete | 2026-03-18 |
| 3. Control Path & Production Hardening | v1.0 | 3/3 | Complete | 2026-03-18 |
| 4. Configuration Webapp | v1.0 | 2/2 | Complete | 2026-03-18 |
| 5. Data Pipeline & Theme Foundation | v2.0 | 0/2 | Planning complete | - |
| 6. Live Dashboard | v2.0 | 0/? | Not started | - |
| 7. Power Control | v2.0 | 0/? | Not started | - |
| 8. Inverter Details & Polish | v2.0 | 0/? | Not started | - |
