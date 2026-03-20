# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (in progress)

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

### v3.1 Auto-Discovery & Inverter Management (In Progress)

- [x] **Phase 17: Discovery Engine** - Backend network scanner with SunSpec verification finds inverters on the LAN (completed 2026-03-20)
- [x] **Phase 18: Multi-Inverter Config** - Config structure supports multiple inverters with migration from single-inverter format (completed 2026-03-20)
- [x] **Phase 19: Inverter Management UI** - Config page lists inverters with enable/disable and delete controls (completed 2026-03-20)
- [ ] **Phase 20: Discovery UI & Onboarding** - Scan button, progress feedback, result preview, and auto-scan on first setup

## Phase Details

### Phase 17: Discovery Engine
**Goal**: System can autonomously find and identify SunSpec-compatible inverters on the local network
**Depends on**: Nothing (first phase of v3.1)
**Requirements**: DISC-01, DISC-02, DISC-03, DISC-04
**Success Criteria** (what must be TRUE):
  1. Running a scan against the local subnet returns a list of IPs that have open Modbus TCP ports (configurable, default 502 and 1502)
  2. Each discovered Modbus device is verified as SunSpec-compliant via "SunS" magic number at register 40000
  3. For verified devices, manufacturer, model, serial number, and firmware version are extracted from SunSpec Common Block
  4. Unit ID 1 is always scanned per IP; unit IDs 2-10 are optionally scanned for RS485 chain discovery
  5. The scanner handles SolarEdge single-connection constraint gracefully (sequential access, short timeouts, no stale connections)
**Plans**: 2 plans

Plans:
- [ ] 17-01-PLAN.md -- Scanner module TDD: TCP probe, SunSpec verification, subnet detection, scan orchestration
- [ ] 17-02-PLAN.md -- Common Block parsing, unit ID scanning, REST API endpoint

### Phase 18: Multi-Inverter Config
**Goal**: Config system stores and serves multiple inverter entries, with seamless migration from the existing single-inverter format
**Depends on**: Phase 17
**Requirements**: CONF-01, CONF-05
**Success Criteria** (what must be TRUE):
  1. Config YAML supports a list of inverter entries, each with host, port, unit_id, model, serial, and enabled flag
  2. Existing single-inverter config files are automatically migrated to the list format on first load without data loss
  3. REST API exposes endpoints to list, add, update, and remove inverter entries
  4. The proxy uses the first enabled inverter as the active proxy target (backward compatible behavior)
**Plans**: 2 plans

Plans:
- [ ] 18-01-PLAN.md -- InverterEntry dataclass, Config migration, get_active_inverter, __main__.py + config.example.yaml
- [ ] 18-02-PLAN.md -- CRUD /api/inverters endpoints, updated config handlers, scanner skip_ips

### Phase 19: Inverter Management UI
**Goal**: User can view, enable/disable, and delete inverter entries from the config page
**Depends on**: Phase 18
**Requirements**: CONF-02, CONF-03
**Success Criteria** (what must be TRUE):
  1. Config page displays a list of all configured inverters showing model, serial, host:port, and enabled status
  2. Each inverter has a toggle slider that enables or disables it, with change persisted on save
  3. Each inverter has a delete action with confirmation that removes it from config
  4. The active (proxied) inverter is visually distinguished from disabled entries
**Plans**: 1 plan

Plans:
- [x] 19-01-PLAN.md -- Inverter list UI with toggle, delete, edit, and add (HTML + CSS + JS)

### Phase 20: Discovery UI & Onboarding
**Goal**: User can trigger scans, see live progress, preview results, and new setups auto-discover inverters
**Depends on**: Phase 17, Phase 18, Phase 19
**Requirements**: DISC-05, CONF-04, UX-01, UX-02, UX-03
**Success Criteria** (what must be TRUE):
  1. An "Auto-Discover" button in the config page triggers a network scan and shows real-time progress (animation or progress bar during the ~30s scan)
  2. Scan results appear as a preview list showing manufacturer, model, serial, host, port, and unit ID for each found inverter
  3. User confirms which discovered inverters to add; confirmed entries are automatically created in config
  4. When no inverter is configured, opening the config page automatically starts a background scan
  5. Already-configured inverters are visually marked in scan results to prevent accidental duplicates
**Plans**: 2 plans

Plans:
- [ ] 20-01-PLAN.md -- Background scan endpoint with WS progress streaming, ScannerConfig persistence
- [ ] 20-02-PLAN.md -- Discovery UI: discover button, progress bar, result list, auto-scan onboarding, ports field

## Progress

**Execution Order:** 17 -> 18 -> 19 -> 20

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
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
| 13. MQTT Config Backend | v3.0 | 2/2 | Complete | 2026-03-19 |
| 14. Config Page & Dashboard UX | v3.0 | 2/2 | Complete | 2026-03-19 |
| 15. Venus OS Auto-Detect | v3.0 | 1/1 | Complete | 2026-03-19 |
| 16. Install Script & README | v3.0 | 1/1 | Complete | 2026-03-19 |
| 17. Discovery Engine | 2/2 | Complete    | 2026-03-20 | - |
| 18. Multi-Inverter Config | 2/2 | Complete    | 2026-03-20 | - |
| 19. Inverter Management UI | v3.1 | Complete    | 2026-03-20 | 2026-03-20 |
| 20. Discovery UI & Onboarding | v3.1 | 0/2 | Not started | - |
