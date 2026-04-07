# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (shipped 2026-03-20)
- v4.0 Multi-Source Virtual Inverter -- Phases 21-24 (shipped 2026-03-21)
- v5.0 MQTT Data Publishing -- Phases 25-27 (shipped 2026-03-22)
- v6.0 Shelly Plugin -- Phases 28-37 (shipped 2026-03-25)
- v7.0 Sungrow SG-RT Plugin -- Phases 38-42 (in progress)

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

- [x] Phase 13: MQTT Config Backend (2/2 plans)
- [x] Phase 14: Config Page & Dashboard UX (2/2 plans)
- [x] Phase 15: Venus OS Auto-Detect (1/1 plan)
- [x] Phase 16: Install Script & README (1/1 plan)

Full details: `.planning/milestones/v3.0-ROADMAP.md`

</details>

<details>
<summary>v3.1 Auto-Discovery & Inverter Management (Phases 17-20) -- SHIPPED 2026-03-20</summary>

- [x] Phase 17: Discovery Engine (2/2 plans)
- [x] Phase 18: Multi-Inverter Config (2/2 plans)
- [x] Phase 19: Inverter Management UI (1/1 plan)
- [x] Phase 20: Discovery UI & Onboarding (2/2 plans)

Full details: `.planning/milestones/v3.1-ROADMAP.md`

</details>

<details>
<summary>v4.0 Multi-Source Virtual Inverter (Phases 21-24) -- SHIPPED 2026-03-21</summary>

- [x] Phase 21: Data Model & OpenDTU Plugin (2/2 plans)
- [x] Phase 22: Device Registry & Aggregation (2/2 plans)
- [x] Phase 23: Power Limit Distribution (2/2 plans)
- [x] Phase 24: Device-Centric API & Frontend (2/2 plans)

Full details: `.planning/milestones/v4.0-ROADMAP.md`

</details>

<details>
<summary>v5.0 MQTT Data Publishing (Phases 25-27) -- SHIPPED 2026-03-22</summary>

- [x] Phase 25: Publisher Infrastructure & Broker Connectivity (2/2 plans)
- [x] Phase 26: Telemetry Publishing & Home Assistant Discovery (2/2 plans)
- [x] Phase 27: Webapp Config & Status UI (2/2 plans)

Full details: `.planning/milestones/v5.0-ROADMAP.md`

</details>

<details>
<summary>v6.0 Shelly Plugin (Phases 28-37) -- SHIPPED 2026-03-25</summary>

- [x] Phase 28: Plugin Core & Profiles (1/1 plan)
- [x] Phase 29: Switch Control & Config Wiring (1/1 plan)
- [x] Phase 30: Add-Device Flow & Discovery (2/2 plans)
- [x] Phase 31: Device Dashboard & Connection Card (1/1 plan)
- [x] Phase 32: Aggregation Integration (1/1 plan)
- [x] Phase 33: Device Throttle Capabilities & Scoring (2/2 plans)
- [x] Phase 34: Binary Throttle Engine with Hysteresis (1/1 plan)
- [x] Phase 35: Smart Auto-Throttle Algorithm (2/2 plans)
- [x] Phase 36: Auto-Throttle UI & Live Tuning (2/2 plans)
- [x] Phase 37: Distributor Wiring & DC Average Fix (1/1 plan)

Full details: `.planning/milestones/v6.0-ROADMAP.md`

</details>

### v7.0 Sungrow SG-RT Plugin (In Progress)

**Milestone Goal:** Full-Stack Integration des Sungrow SG-RT Wechselrichters als vierter Inverter-Typ mit Modbus TCP Polling, SunSpec Encoding, 3-Phasen Dashboard, Power Limiting, Discovery und Throttle-Integration.

- [x] **Phase 38: Plugin Core** - Modbus TCP polling, SunSpec encoding, config entry, ThrottleCaps declaration (completed 2026-04-06)
- [ ] **Phase 39: Dashboard** - Power gauge, 3-phase AC, MPPT DC channels, state card, register viewer
- [ ] **Phase 40: Add Device & Discovery** - Type card, Modbus probe, network scan with Sungrow detection
- [ ] **Phase 41: Power Control** - Write register research, write_power_limit, waterfall distributor integration
- [ ] **Phase 42: Integration** - Aggregation wiring, MQTT publishing, config UI, E2E verification

## Phase Details

### Phase 38: Plugin Core
**Goal**: A working SungrowPlugin can connect to a Sungrow SG-RT inverter via Modbus TCP, poll all essential data, encode it as SunSpec registers, and declare its throttle capabilities
**Depends on**: Phase 37 (v6.0 complete)
**Requirements**: PLUG-01, PLUG-02, PLUG-03, PLUG-04
**Success Criteria** (what must be TRUE):
  1. SungrowPlugin implements the full InverterPlugin ABC and polls live data (AC power/voltage/current/frequency, DC MPPT1+MPPT2, temperature, energy counters, running state) from a Sungrow SG-RT at the configured interval
  2. Polled data is encoded into SunSpec Model 103 registers identical to the pattern used by SolarEdge and OpenDTU plugins
  3. User can change host/port/unit_id via reconfigure() without restarting the proxy
  4. Plugin declares ThrottleCaps with proportional mode and ~2s Modbus response time, producing a valid throttle_score
**Plans:** 2/2 plans complete
Plans:
- [x] 38-01-PLAN.md -- SungrowPlugin TDD: tests + implementation (Modbus TCP polling, SunSpec encoding, reconfigure, ThrottleCaps)
- [x] 38-02-PLAN.md -- Plugin factory wiring (register sungrow type in plugin_factory)

### Phase 39: Dashboard
**Goal**: Each Sungrow device has a full dashboard with power gauge, 3-phase AC table, dual MPPT DC channels, inverter state card, and register viewer
**Depends on**: Phase 38
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. The Sungrow device dashboard shows a power gauge scaled to the device's rated power (8kW for SG8.0RT)
  2. The 3-phase AC table displays L1/L2/L3 voltage, current, and power values updating in real-time
  3. The DC section shows MPPT1 and MPPT2 channels with voltage, current, and power per tracker
  4. The connection card displays inverter state (Run/Standby/Derating/Fault) and temperature
  5. The register viewer shows all Sungrow registers with Sungrow-specific labels (wire addresses 5002-5037)
**Plans**: TBD
**UI hint**: yes

### Phase 40: Add Device & Discovery
**Goal**: Users can add Sungrow inverters through the webapp with Modbus probe validation, and discover Sungrow devices on the network
**Depends on**: Phase 39
**Requirements**: ADD-01, ADD-02, ADD-03
**Success Criteria** (what must be TRUE):
  1. The add-device dialog shows "Sungrow" as a fourth option alongside SolarEdge, OpenDTU, and Shelly
  2. After entering a Sungrow IP, the webapp probes the device via Modbus TCP and displays the detected device type code and serial number before confirming
  3. The Discover button finds Sungrow inverters on the LAN by scanning port 502 and detecting Sungrow device type responses
**Plans**: TBD
**UI hint**: yes

### Phase 41: Power Control
**Goal**: Users can set a power limit (0-100%) on a Sungrow inverter, and the waterfall distributor includes Sungrow in its score-based throttle ordering
**Depends on**: Phase 38
**Requirements**: CTRL-01, CTRL-02
**Success Criteria** (what must be TRUE):
  1. The proxy can write a power limit percentage to the Sungrow inverter via Modbus holding registers and the inverter responds with actual derating
  2. When auto-throttle is active, the Sungrow device participates in the score-based waterfall at its declared throttle_score position
  3. Power limit changes are reflected in the device snapshot and visible on the dashboard within one poll cycle
**Plans**: TBD

### Phase 42: Integration
**Goal**: Sungrow devices are fully wired into the virtual PV inverter ecosystem -- aggregation, MQTT publishing, and config UI all work seamlessly
**Depends on**: Phase 39, Phase 40, Phase 41
**Requirements**: CFG-01, CFG-02, CFG-03
**Success Criteria** (what must be TRUE):
  1. The Sungrow config form allows editing Host, Port, Unit ID, Rated Power, and Throttle Enabled with save-and-apply behavior
  2. Sungrow AC and DC data flows into the virtual PV inverter aggregation and Venus OS shows the combined power including Sungrow contribution
  3. MQTT publisher includes Sungrow device telemetry alongside SolarEdge, OpenDTU, and Shelly devices
  4. End-to-end: adding a Sungrow device, seeing it on the dashboard, and verifying its data in Venus OS works without manual intervention
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 38 -> 39 -> 40 -> 41 -> 42
(Note: Phase 41 depends only on Phase 38, so it can run in parallel with 39/40 if desired)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 38. Plugin Core | 2/2 | Complete    | 2026-04-06 |
| 39. Dashboard | 0/? | Not started | - |
| 40. Add Device & Discovery | 0/? | Not started | - |
| 41. Power Control | 0/? | Not started | - |
| 42. Integration | 0/? | Not started | - |
