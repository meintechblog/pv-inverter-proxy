# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (shipped 2026-03-20)
- v4.0 Multi-Source Virtual Inverter -- Phases 21-24 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-4) -- SHIPPED 2026-03-18</summary>

- [x] Phase 1: Protocol Research & Validation (2/2 plans)
- [x] Phase 2: Core Proxy / Read Path (2/2 plans)
- [x] Phase 3: Control Path & Production Hardening (3/3 plans)
- [x] Phase 4: Configuration Webapp (2/2 plans)

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>v2.0 Dashboard & Power Control (Phases 5-8) -- SHIPPED 2026-03-18</summary>

- [x] Phase 5: Data Pipeline & Theme Foundation (2/2 plans)
- [x] Phase 6: Live Dashboard (2/2 plans)
- [x] Phase 7: Power Control (2/2 plans)
- [x] Phase 8: Inverter Details & Polish (1/1 plan)

Full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

<details>
<summary>v2.1 Dashboard Redesign & Polish (Phases 9-12) -- SHIPPED 2026-03-18</summary>

- [x] Phase 9: CSS Animations & Toast System (2/2 plans)
- [x] Phase 10: Peak Statistics & Smart Notifications (2/2 plans)
- [x] Phase 11: Venus OS Widget & Lock Toggle (2/2 plans)
- [x] Phase 12: Unified Dashboard Layout (1/1 plan)

Full details: `.planning/milestones/v2.1-ROADMAP.md`

</details>

<details>
<summary>v3.0 Setup & Onboarding (Phases 13-16) -- SHIPPED 2026-03-19</summary>

- [x] Phase 13: MQTT Config Backend (2/2 plans) -- completed 2026-03-19
- [x] Phase 14: Config Page & Dashboard UX (2/2 plans) -- completed 2026-03-19
- [x] Phase 15: Venus OS Auto-Detect (1/1 plan) -- completed 2026-03-19
- [x] Phase 16: Install Script & README (1/1 plan) -- completed 2026-03-19

Full details: `.planning/milestones/v3.0-ROADMAP.md`

</details>

<details>
<summary>v3.1 Auto-Discovery & Inverter Management (Phases 17-20) -- SHIPPED 2026-03-20</summary>

- [x] Phase 17: Discovery Engine (2/2 plans) -- completed 2026-03-20
- [x] Phase 18: Multi-Inverter Config (2/2 plans) -- completed 2026-03-20
- [x] Phase 19: Inverter Management UI (1/1 plan) -- completed 2026-03-20
- [x] Phase 20: Discovery UI & Onboarding (2/2 plans) -- completed 2026-03-20

Full details: `.planning/milestones/v3.1-ROADMAP.md`

</details>

### v4.0 Multi-Source Virtual Inverter (In Progress)

**Milestone Goal:** Aggregate N physical inverters (SolarEdge + Hoymiles/OpenDTU) into one virtual Fronius device for Venus OS, with device-centric webapp and priority-based power limiting.

- [ ] **Phase 21: Data Model & OpenDTU Plugin** - Typed config, AppContext refactor, and OpenDTU plugin for Hoymiles inverters
- [ ] **Phase 22: Device Registry & Aggregation** - Multi-device poll management and virtual inverter aggregation for Venus OS
- [ ] **Phase 23: Power Limit Distribution** - Priority-based power limiting across heterogeneous inverters
- [ ] **Phase 24: Device-Centric API & Frontend** - Per-device REST endpoints, WebSocket updates, and device-centric UI

## Phase Details

### Phase 21: Data Model & OpenDTU Plugin
**Goal**: The system supports typed device configurations and can poll Hoymiles inverters via OpenDTU REST API
**Depends on**: Phase 20 (v3.1 complete)
**Requirements**: DATA-01, DATA-02, DATA-03, DTU-01, DTU-02, DTU-03, DTU-04, DTU-05
**Success Criteria** (what must be TRUE):
  1. Fresh config with typed inverter entries loads cleanly (no v3.1 migration, fresh config only)
  2. An OpenDTU gateway at 192.168.3.98 is polled and each Hoymiles inverter behind it appears as a separate device with AC power, voltage, current, and daily yield data
  3. A power limit can be sent to a specific Hoymiles inverter via the OpenDTU API and the system waits the appropriate dead-time before sending another
  4. The AppContext provides typed per-device state instead of a flat shared dictionary
**Plans**: 2 plans

Plans:
- [x] 21-01-PLAN.md — Config data model refactor (typed InverterEntry, GatewayConfig, AppContext, no migration)
- [ ] 21-02-PLAN.md — OpenDTU plugin (poll, SunSpec register synthesis, power limit, dead-time guard)

### Phase 22: Device Registry & Aggregation
**Goal**: Multiple inverters run independent poll loops and their combined output appears as one virtual Fronius inverter to Venus OS
**Depends on**: Phase 21
**Requirements**: REG-01, REG-02, REG-03, AGG-01, AGG-02, AGG-03, AGG-04
**Success Criteria** (what must be TRUE):
  1. Each configured device has its own independent poll loop; adding, removing, enabling, or disabling a device at runtime does not require a restart
  2. When a device is removed or disabled, its poll task, snapshot data, and collector are fully cleaned up with no asyncio task leaks
  3. Venus OS sees a single aggregated Fronius inverter whose power equals the sum of all active inverters (SolarEdge + Hoymiles combined)
  4. If one inverter goes offline, Venus OS still receives aggregated data from the remaining reachable inverters
  5. The user can set a custom name for the virtual inverter that Venus OS displays
**Plans**: TBD

Plans:
- [ ] 22-01: DeviceRegistry with per-device poll lifecycle management
- [ ] 22-02: AggregationLayer and proxy decoupling (physical-unit summation, SunSpec re-encoding)

### Phase 23: Power Limit Distribution
**Goal**: Venus OS power limit commands are distributed across inverters based on user-defined priority with correct handling of heterogeneous latencies
**Depends on**: Phase 22
**Requirements**: PWR-01, PWR-02, PWR-03, PWR-04
**Success Criteria** (what must be TRUE):
  1. The user can define which inverter gets throttled first when Venus OS sends a power limit command
  2. Individual inverters can be excluded from power limiting (monitoring only) and still contribute to the aggregated power reading
  3. Power limit distribution respects per-device latency: SolarEdge limits apply immediately while Hoymiles limits use a 25-30s dead-time guard to prevent oscillation
  4. When Venus OS requests e.g. 50% limit, the highest-priority inverter is throttled first; lower-priority inverters are only throttled if the first cannot absorb the full reduction
**Plans**: TBD

Plans:
- [ ] 23-01: PowerLimitDistributor with priority ordering, dead-time guards, and exclusion support

### Phase 24: Device-Centric API & Frontend
**Goal**: Each device (inverter, Venus OS, virtual PV) has its own sidebar entry, dashboard view, and management interface
**Depends on**: Phase 23
**Requirements**: API-01, API-02, API-03, UI-01, UI-02, UI-03, UI-04, UI-05, UI-06
**Success Criteria** (what must be TRUE):
  1. The sidebar dynamically lists all configured devices; clicking an inverter shows its individual dashboard with power, phases/channels, and status
  2. Venus OS has its own sidebar entry showing ESS status, MQTT configuration, and Portal ID
  3. A "Virtual PV" view shows the aggregated power of all active inverters with per-inverter contribution breakdown
  4. The user can add new devices (inverter or Venus OS) via a "+" button in the sidebar, which triggers manual discovery (no auto-scan)
  5. When a device is disabled or removed, all its data disappears from the UI immediately
**Plans**: TBD

Plans:
- [ ] 24-01: Device-centric REST API (CRUD, per-device snapshots, multi-device WebSocket)
- [ ] 24-02: Device-centric frontend (dynamic sidebar, per-device views, virtual PV dashboard, device management)

## Progress

**Execution Order:**
Phases execute in numeric order: 21 -> 22 -> 23 -> 24

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 21. Data Model & OpenDTU Plugin | v4.0 | 1/2 | In progress | - |
| 22. Device Registry & Aggregation | v4.0 | 0/2 | Not started | - |
| 23. Power Limit Distribution | v4.0 | 0/1 | Not started | - |
| 24. Device-Centric API & Frontend | v4.0 | 0/2 | Not started | - |
