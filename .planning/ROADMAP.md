# Roadmap: Venus OS Fronius Proxy

## Milestones

- ✅ **v1.0 MVP** -- Phases 1-4 (shipped 2026-03-18)
- ✅ **v2.0 Dashboard & Power Control** -- Phases 5-8 (shipped 2026-03-18)
- ✅ **v2.1 Dashboard Redesign & Polish** -- Phases 9-12 (shipped 2026-03-18)
- 🚧 **v3.0 Setup & Onboarding** -- Phases 13-16 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) -- SHIPPED 2026-03-18</summary>

- [x] Phase 1: Protocol Research & Validation (2/2 plans)
- [x] Phase 2: Core Proxy / Read Path (2/2 plans)
- [x] Phase 3: Control Path & Production Hardening (3/3 plans)
- [x] Phase 4: Configuration Webapp (2/2 plans)

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v2.0 Dashboard & Power Control (Phases 5-8) -- SHIPPED 2026-03-18</summary>

- [x] Phase 5: Data Pipeline & Theme Foundation (2/2 plans)
- [x] Phase 6: Live Dashboard (2/2 plans)
- [x] Phase 7: Power Control (2/2 plans)
- [x] Phase 8: Inverter Details & Polish (1/1 plan)

Full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

<details>
<summary>✅ v2.1 Dashboard Redesign & Polish (Phases 9-12) -- SHIPPED 2026-03-18</summary>

- [x] Phase 9: CSS Animations & Toast System (2/2 plans)
- [x] Phase 10: Peak Statistics & Smart Notifications (2/2 plans)
- [x] Phase 11: Venus OS Widget & Lock Toggle (2/2 plans)
- [x] Phase 12: Unified Dashboard Layout (1/1 plan)

Full details: `.planning/milestones/v2.1-ROADMAP.md`

</details>

### 🚧 v3.0 Setup & Onboarding (In Progress)

**Milestone Goal:** Neuen Usern einen reibungslosen Setup-Flow bieten -- von Install bis volle Venus OS Integration in wenigen Minuten.

- [x] **Phase 13: MQTT Config Backend** - VenusConfig dataclass, parameterize MQTT, CONNACK fix, de-hardcode all hardcoded Venus OS references (completed 2026-03-19)
- [x] **Phase 14: Config Page & Dashboard UX** - Config page with defaults and connection bobbles, MQTT setup guide, dashboard MQTT gate (completed 2026-03-19)
- [x] **Phase 15: Venus OS Auto-Detect** - Detect incoming Modbus connection from Venus OS and prompt user to configure MQTT (completed 2026-03-19)
- [ ] **Phase 16: Install Script & README** - Fix install script YAML mismatch, add venus config section, update README with setup flow

## Phase Details

### Phase 13: MQTT Config Backend
**Goal**: MQTT connection parameters are configurable and reliable instead of hardcoded
**Depends on**: Phase 12 (v2.1 complete)
**Requirements**: CFG-03, CFG-04
**Success Criteria** (what must be TRUE):
  1. User can set Venus OS IP, MQTT port, and Portal ID in config.yaml and the proxy uses those values for all MQTT communication
  2. If Portal ID is left blank, the proxy auto-discovers it via MQTT wildcard subscription and logs the discovered value
  3. MQTT connection failures are detected and reported accurately (no silent false-positive connections)
  4. All five previously hardcoded Venus OS IP/portal ID references in the codebase are eliminated
**Plans**: 2 plans

Plans:
- [ ] 13-01-PLAN.md — VenusConfig dataclass + parameterize venus_reader + CONNACK fix
- [ ] 13-02-PLAN.md — De-hardcode webapp + portal ID auto-discovery + dashboard wiring

### Phase 14: Config Page & Dashboard UX
**Goal**: Users can configure the proxy through the web UI and see live connection status for all components
**Depends on**: Phase 13
**Requirements**: CFG-01, CFG-02, SETUP-02, SETUP-03
**Success Criteria** (what must be TRUE):
  1. Config page shows pre-filled defaults (192.168.3.18:1502, Unit 1) on first visit -- user does not need to guess values
  2. After Save & Apply, a live connection bobble (green/red/amber) shows whether SolarEdge and MQTT connections are active
  3. When MQTT is not connected, an inline setup guide card explains how to enable MQTT on LAN in Venus OS Remote Console
  4. Dashboard elements that depend on MQTT (Lock Toggle, Override Detection, Venus Settings) are visually greyed out with an overlay hint until MQTT is connected
  5. Power gauge, inverter status, and power slider remain fully functional without MQTT
**Plans**: 2 plans

Plans:
- [ ] 14-01-PLAN.md — Extend config API for Venus fields + MQTT hot-reload + fix status handler
- [ ] 14-02-PLAN.md — Frontend: Venus config section, connection bobbles, MQTT gate, setup guide

### Phase 15: Venus OS Auto-Detect
**Goal**: The proxy detects when Venus OS connects and guides the user to complete MQTT setup
**Depends on**: Phase 14
**Requirements**: SETUP-01
**Success Criteria** (what must be TRUE):
  1. When Venus OS sends its first Modbus write to the proxy, the config page shows a banner indicating Venus OS is connected
  2. The banner prompts the user to enter the Venus OS IP for MQTT configuration with a Test & Apply flow
  3. Auto-detect does not auto-save config -- user must confirm before any configuration change takes effect
**Plans**: 1 plan

Plans:
- [ ] 15-01-PLAN.md — Backend detection flag + frontend auto-detect banner

### Phase 16: Install Script & README
**Goal**: A new user can install and configure the proxy with a single curl command and clear documentation
**Depends on**: Phase 13 (config format must be stable)
**Requirements**: DOCS-01, DOCS-02
**Success Criteria** (what must be TRUE):
  1. Install script generates correct YAML config with `inverter:` key (not `solaredge:`) and includes the new `venus:` section
  2. Install script uses secure curl flags and includes pre-flight checks (port 502 availability, existing config preservation)
  3. README documents the full setup flow: install, configure SolarEdge, configure Venus OS MQTT, verify dashboard
  4. README states Venus OS >= 3.7 as prerequisite
**Plans**: TBD

Plans:
- [ ] 16-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 13 -> 14 -> 15 -> 16

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
| 9. CSS Animations & Toast System | v2.1 | 2/2 | Complete | 2026-03-18 |
| 10. Peak Statistics & Smart Notifications | v2.1 | 2/2 | Complete | 2026-03-18 |
| 11. Venus OS Widget & Lock Toggle | v2.1 | 2/2 | Complete | 2026-03-18 |
| 12. Unified Dashboard Layout | v2.1 | 1/1 | Complete | 2026-03-18 |
| 13. MQTT Config Backend | 2/2 | Complete    | 2026-03-19 | - |
| 14. Config Page & Dashboard UX | 2/2 | Complete    | 2026-03-19 | - |
| 15. Venus OS Auto-Detect | 1/1 | Complete   | 2026-03-19 | - |
| 16. Install Script & README | v3.0 | 0/? | Not started | - |
