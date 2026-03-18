# Roadmap: Venus OS Fronius Proxy

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-03-18)
- ✅ **v2.0 Dashboard & Power Control** — Phases 5-8 (shipped 2026-03-18)
- 🚧 **v2.1 Dashboard Redesign & Polish** — Phases 9-12 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-03-18</summary>

- [x] Phase 1: Protocol Research & Validation (2/2 plans)
- [x] Phase 2: Core Proxy / Read Path (2/2 plans)
- [x] Phase 3: Control Path & Production Hardening (3/3 plans)
- [x] Phase 4: Configuration Webapp (2/2 plans)

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v2.0 Dashboard & Power Control (Phases 5-8) — SHIPPED 2026-03-18</summary>

- [x] Phase 5: Data Pipeline & Theme Foundation (2/2 plans)
- [x] Phase 6: Live Dashboard (2/2 plans)
- [x] Phase 7: Power Control (2/2 plans)
- [x] Phase 8: Inverter Details & Polish (1/1 plan)

Full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

### 🚧 v2.1 Dashboard Redesign & Polish (In Progress)

**Milestone Goal:** Alle Dashboard-Funktionen auf einer einzigen Seite vereinen, Venus OS Info anzeigen, und das Gesamterlebnis mit Animationen, Statistiken und Smart Notifications abrunden.

- [x] **Phase 9: CSS Animations & Toast System** - Animation foundation and notification infrastructure (completed 2026-03-18)
- [x] **Phase 10: Peak Statistics & Smart Notifications** - Backend stats tracking and event-driven toasts (completed 2026-03-18)
- [x] **Phase 11: Venus OS Widget & Lock Toggle** - Venus OS info display and control lock (completed 2026-03-18)
- [ ] **Phase 12: Unified Dashboard Layout** - Single-page merge of all widgets

## Phase Details

### Phase 9: CSS Animations & Toast System
**Goal**: Users see smooth, performant animations throughout the dashboard and have a reliable notification system for important events
**Depends on**: Phase 8 (existing dashboard)
**Requirements**: ANIM-01, ANIM-02, ANIM-03, ANIM-04, NOTIF-01, NOTIF-05
**Success Criteria** (what must be TRUE):
  1. Power gauge arc animates smoothly when values change (no jumps or jank)
  2. Dashboard widgets appear with staggered entrance animations on page load
  3. Value changes in cards produce a subtle highlight flash
  4. All animations are disabled when prefers-reduced-motion is active in the browser
  5. Multiple toast notifications stack visually without overlapping, each dismissible by click with an exit animation
**Plans**: 2 plans

Plans:
- [ ] 09-01-PLAN.md — Animation foundation: CSS variables, gauge 0.5s transition + deadband, entrance animations, value flash thresholds, prefers-reduced-motion
- [ ] 09-02-PLAN.md — Toast system refactor: stacking container, exit animations, click-to-dismiss, duplicate suppression

### Phase 10: Peak Statistics & Smart Notifications
**Goal**: Users can see daily performance stats at a glance and receive automatic alerts for important inverter events
**Depends on**: Phase 9 (toast system must exist for notification triggers)
**Requirements**: STATS-01, STATS-02, STATS-03, NOTIF-02, NOTIF-03, NOTIF-04
**Success Criteria** (what must be TRUE):
  1. Dashboard shows today's peak power (kW), operating hours, and efficiency indicator -- all reset on restart
  2. A toast appears when Venus OS overrides the power limit, showing the override value
  3. A toast appears when the inverter reports a fault or temperature warning
  4. A toast appears when the inverter transitions to/from night mode (sleep/wake)
**Plans**: 2 plans

Plans:
- [ ] 10-01-PLAN.md — Peak stats backend + UI: DashboardCollector tracking (peak power, operating hours, efficiency), stats card in dashboard, tests
- [ ] 10-02-PLAN.md — Smart notifications: snapshot-diff event detection for Venus OS override, inverter fault, temperature warning, night mode transitions

### Phase 11: Venus OS Widget & Lock Toggle
**Goal**: Users can see Venus OS connection status and control whether Venus OS is allowed to override power limits
**Depends on**: Phase 9 (animations for toggle), Phase 10 (override toast for feedback)
**Requirements**: VENUS-01, VENUS-02, VENUS-03, VENUS-04
**Success Criteria** (what must be TRUE):
  1. Dashboard shows a Venus OS widget with connection status (Online/Offline), IP address, and last contact timestamp
  2. Widget displays current override status (whether Venus OS has control and at what value)
  3. An Apple-style toggle allows the user to lock/unlock Venus OS control, with a confirmation dialog before locking
  4. Lock automatically expires after max 15 minutes -- Venus OS is never permanently locked out
**Plans**: 2 plans

Plans:
- [x] 11-01-PLAN.md — Backend lock state + write path lock check + auto-unlock + snapshot extension + POST /api/venus-lock endpoint + tests
- [ ] 11-02-PLAN.md — Frontend Venus OS widget card with connection status, override display, Apple-style lock toggle, confirmation dialog, countdown timer

### Phase 12: Unified Dashboard Layout
**Goal**: All dashboard functionality lives on a single page with no separate power control page
**Depends on**: Phase 9, 10, 11 (all widgets must exist before layout merge)
**Requirements**: LAYOUT-01, LAYOUT-02, LAYOUT-03
**Success Criteria** (what must be TRUE):
  1. Power control (slider, toggle, override log) appears inline below the power gauge -- no navigation required
  2. All widgets (gauge, power control, 3-phase, sparkline, status, daily energy, peak stats, Venus OS) are visible in a compact grid on one page
  3. Sidebar navigation shows only Dashboard, Config, and Registers (power control page removed)
**Plans**: TBD

Plans:
- [ ] 12-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 9 -> 10 -> 11 -> 12

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|---------------|--------|-----------|
| 1. Protocol Research & Validation | v1.0 | 2/2 | Complete | 2026-03-18 |
| 2. Core Proxy (Read Path) | v1.0 | 2/2 | Complete | 2026-03-18 |
| 3. Control Path & Production Hardening | v1.0 | 3/3 | Complete | 2026-03-18 |
| 4. Configuration Webapp | v1.0 | 2/2 | Complete | 2026-03-18 |
| 5. Data Pipeline & Theme Foundation | v2.0 | 2/2 | Complete | 2026-03-18 |
| 6. Live Dashboard | v2.0 | 2/2 | Complete | 2026-03-18 |
| 7. Power Control | v2.0 | 2/2 | Complete | 2026-03-18 |
| 8. Inverter Details & Polish | v2.0 | 1/1 | Complete | 2026-03-18 |
| 9. CSS Animations & Toast System | 2/2 | Complete   | 2026-03-18 | - |
| 10. Peak Statistics & Smart Notifications | 2/2 | Complete    | 2026-03-18 | - |
| 11. Venus OS Widget & Lock Toggle | 2/2 | Complete    | 2026-03-18 | - |
| 12. Unified Dashboard Layout | v2.1 | 0/? | Not started | - |
