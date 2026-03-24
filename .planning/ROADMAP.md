# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (shipped 2026-03-20)
- v4.0 Multi-Source Virtual Inverter -- Phases 21-24 (shipped 2026-03-21)
- v5.0 MQTT Data Publishing -- Phases 25-27 (shipped 2026-03-22)
- v6.0 Shelly Plugin -- Phases 28-32 (in progress)

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

<details>
<summary>v4.0 Multi-Source Virtual Inverter (Phases 21-24) -- SHIPPED 2026-03-21</summary>

- [x] Phase 21: Data Model & OpenDTU Plugin (2/2 plans) -- completed 2026-03-20
- [x] Phase 22: Device Registry & Aggregation (2/2 plans) -- completed 2026-03-20
- [x] Phase 23: Power Limit Distribution (2/2 plans) -- completed 2026-03-21
- [x] Phase 24: Device-Centric API & Frontend (2/2 plans) -- completed 2026-03-21

Full details: `.planning/milestones/v4.0-ROADMAP.md`

</details>

<details>
<summary>v5.0 MQTT Data Publishing (Phases 25-27) -- SHIPPED 2026-03-22</summary>

- [x] Phase 25: Publisher Infrastructure & Broker Connectivity (2/2 plans) -- completed 2026-03-22
- [x] Phase 26: Telemetry Publishing & Home Assistant Discovery (2/2 plans) -- completed 2026-03-22
- [x] Phase 27: Webapp Config & Status UI (2/2 plans) -- completed 2026-03-22

Full details: `.planning/milestones/v5.0-ROADMAP.md`

</details>

### v6.0 Shelly Plugin (In Progress)

**Milestone Goal:** Shelly Smart Devices als drittes Inverter-Plugin integrieren -- misst Energiedaten des angeschlossenen Micro-PV-WR, ermoeglicht On/Off-Steuerung, unterstuetzt verschiedene Shelly-Generationen ueber austauschbare API-Profile.

- [x] **Phase 28: Plugin Core & Profiles** - ShellyPlugin with Gen1/Gen2 profiles, auto-detection, polling, SunSpec encoding, graceful degradation (completed 2026-03-24)
- [x] **Phase 29: Switch Control & Config Wiring** - On/Off relay control, switch status display, power-limit no-op, plugin_factory integration (completed 2026-03-24)
- [x] **Phase 30: Add-Device Flow & Discovery** - Shelly as third option in add-device dialog, auto-detection UI, LAN discovery, config page (completed 2026-03-24)
- [ ] **Phase 31: Device Dashboard & Connection Card** - Gauge, AC values, Shelly-specific connection card with on/off toggle
- [ ] **Phase 32: Aggregation Integration** - Shelly data flows into virtual PV inverter, DC-averaging skip

## Phase Details

### Phase 28: Plugin Core & Profiles
**Goal**: A working ShellyPlugin can connect to any Shelly device, auto-detect its generation, poll energy data, and encode it as SunSpec registers
**Depends on**: Phase 27 (v5.0 complete)
**Requirements**: PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05, PLUG-06, PLUG-07
**Success Criteria** (what must be TRUE):
  1. ShellyPlugin implements the full InverterPlugin ABC and can be instantiated with a Shelly device IP
  2. On first connect, the plugin auto-detects Gen1 vs Gen2+ by probing the /shelly endpoint and selects the correct API profile
  3. The plugin polls power (W), voltage (V), current (A), frequency (Hz), energy (Wh), and temperature (C) from the Shelly device at the configured interval
  4. Polled data is encoded into SunSpec Model 103 registers identical to how OpenDTU encodes its data
  5. Missing fields (e.g., no temperature on some Gen1 models) result in zero/default values instead of errors
**Plans**: 1 plan
Plans:
- [ ] 28-01-PLAN.md -- ShellyPlugin with Gen1/Gen2 profiles, tests, and factory wiring

### Phase 29: Switch Control & Config Wiring
**Goal**: Users can turn Shelly relays on/off from the proxy, and Shelly devices are recognized by the plugin factory
**Depends on**: Phase 28
**Requirements**: CTRL-01, CTRL-02, CTRL-03
**Success Criteria** (what must be TRUE):
  1. The proxy can send on/off switch commands to a Shelly device via the correct Gen1 or Gen2 relay endpoint
  2. The current switch state (on/off) is visible in the device data returned by the plugin
  3. When Venus OS sends a power-limit command, write_power_limit() succeeds as a no-op and the device is excluded from throttling by default
**Plans**: 1 plan
Plans:
- [ ] 29-01-PLAN.md -- Switch control API route, ShellyPlugin.switch() method, throttle_enabled default

### Phase 30: Add-Device Flow & Discovery
**Goal**: Users can add Shelly devices through the webapp with automatic generation detection, and discover Shelly devices on the LAN
**Depends on**: Phase 29
**Requirements**: UI-01, UI-02, UI-05, UI-06
**Success Criteria** (what must be TRUE):
  1. The add-device dialog shows "Shelly Device" as a third option alongside SolarEdge and OpenDTU
  2. After entering a Shelly IP, the webapp probes the device and displays the detected generation (Gen1/Gen2/Gen3) before confirming
  3. The device config page shows the Shelly host and detected generation as a readonly field
  4. The Discover button in the add-device flow finds Shelly devices on the LAN by scanning and probing /shelly
**Plans**: 2 plans
Plans:
- [ ] 30-01-PLAN.md -- Shelly probe endpoint, mDNS discovery module, unit tests
- [ ] 30-02-PLAN.md -- Frontend: type card, form, probe flow, discovery UI, config page fields

### Phase 31: Device Dashboard & Connection Card
**Goal**: Each Shelly device has a full dashboard with power gauge, AC values, and Shelly-specific connection info including on/off control
**Depends on**: Phase 30
**Requirements**: UI-03, UI-04
**Success Criteria** (what must be TRUE):
  1. The Shelly device dashboard shows a power gauge and AC values (power, voltage, current, frequency) but no DC section
  2. The connection card displays Shelly-specific info (generation, model) and the current switch state with on/off buttons
  3. On/off buttons in the connection card send switch commands and the UI reflects the new state within one poll cycle
**Plans**: TBD

### Phase 32: Aggregation Integration
**Goal**: Shelly energy data is included in the virtual PV inverter totals and the aggregator handles Shelly's lack of DC data correctly
**Depends on**: Phase 31
**Requirements**: AGG-01, AGG-02
**Success Criteria** (what must be TRUE):
  1. A Shelly device's power and energy values are summed into the virtual PV inverter's aggregated SunSpec registers
  2. The DC-averaging calculation in the aggregator skips Shelly devices without producing errors or skewing averages
  3. The virtual PV inverter's total power on Venus OS includes the Shelly device's contribution
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 28 -> 29 -> 30 -> 31 -> 32

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 28. Plugin Core & Profiles | 0/1 | Complete    | 2026-03-24 |
| 29. Switch Control & Config Wiring | 0/1 | Complete    | 2026-03-24 |
| 30. Add-Device Flow & Discovery | 0/2 | Complete    | 2026-03-24 |
| 31. Device Dashboard & Connection Card | 0/? | Not started | - |
| 32. Aggregation Integration | 0/? | Not started | - |
