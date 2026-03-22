# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (shipped 2026-03-20)
- v4.0 Multi-Source Virtual Inverter -- Phases 21-24 (shipped 2026-03-21)
- v5.0 MQTT Data Publishing -- Phases 25-27 (in progress)

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

### v5.0 MQTT Data Publishing (In Progress)

**Milestone Goal:** Publish inverter telemetry data to an external MQTT broker for integration with Home Assistant, Node-RED, Grafana, and other consumers. Zero-config Home Assistant integration via MQTT Auto-Discovery.

- [x] **Phase 25: Publisher Infrastructure & Broker Connectivity** - aiomqtt-based publisher with queue-decoupled architecture, config dataclass, LWT, reconnect, and mDNS broker discovery (completed 2026-03-22)
- [ ] **Phase 26: Telemetry Publishing & Home Assistant Discovery** - Per-device and virtual-PV topic hierarchy, JSON payloads, HA auto-discovery config payloads, wired into broadcast chain
- [ ] **Phase 27: Webapp Config & Status UI** - MQTT Publishing config panel, mDNS discover button, connection status dot, topic preview

## Phase Details

### Phase 25: Publisher Infrastructure & Broker Connectivity
**Goal**: The system can connect to a configurable MQTT broker, maintain a resilient connection, and discover brokers on the LAN
**Depends on**: Phase 24 (v4.0 complete)
**Requirements**: CONN-01, CONN-02, CONN-03, CONN-04, PUB-03, PUB-05
**Success Criteria** (what must be TRUE):
  1. The proxy connects to a configured MQTT broker (default mqtt-master.local:1883) and publishes an "online" availability message on connect
  2. When the broker becomes unreachable, the publisher reconnects automatically with exponential backoff without affecting inverter polling or WebSocket updates
  3. When the proxy shuts down or crashes, the broker receives an "offline" LWT message so subscribers know the proxy is unavailable
  4. The user can change broker host, port, and publish interval in config.yaml and the publisher hot-reloads without restarting the service
  5. An mDNS scan discovers MQTT brokers advertising _mqtt._tcp.local. on the LAN
**Plans:** 2/2 plans complete
Plans:
- [x] 25-01-PLAN.md — Config dataclass, publisher module with LWT/reconnect, unit tests
- [x] 25-02-PLAN.md — Lifecycle wiring (__main__.py + webapp.py hot-reload), mDNS discovery endpoint

### Phase 26: Telemetry Publishing & Home Assistant Discovery
**Goal**: All inverter data flows to the MQTT broker with per-device topics and Home Assistant discovers all sensors automatically
**Depends on**: Phase 25
**Requirements**: PUB-01, PUB-02, PUB-04, PUB-06, HA-01, HA-02, HA-03, HA-04
**Success Criteria** (what must be TRUE):
  1. Each inverter publishes a JSON telemetry payload (power, voltage, current, temperature, status, daily energy) to its own MQTT topic at the configured interval
  2. The virtual PV plant publishes an aggregated payload (total power, per-inverter contributions) to a separate topic
  3. Home Assistant auto-discovers all inverter sensors with correct device_class (power, energy, voltage, temperature) and state_class (measurement, total_increasing) without manual YAML configuration
  4. Each inverter appears as a grouped device in Home Assistant with manufacturer, model, and SW version metadata
  5. When telemetry data has not changed since the last publish, no redundant MQTT message is sent (change-based optimization)
**Plans:** 2 plans
Plans:
- [ ] 26-01-PLAN.md — Pure payload extraction + HA discovery config builder (mqtt_payloads.py)
- [ ] 26-02-PLAN.md — Publisher integration: HA discovery on connect, change detection, queue wiring

### Phase 27: Webapp Config & Status UI
**Goal**: Users can configure, monitor, and troubleshoot MQTT publishing entirely from the webapp
**Depends on**: Phase 26
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):
  1. The config page shows an MQTT Publishing section with enable/disable toggle, broker host, port, topic prefix, and publish interval fields
  2. A "Discover" button scans the LAN for MQTT brokers via mDNS and populates the broker field with the result
  3. A connection status dot on the dashboard shows whether the MQTT publisher is currently connected to the broker (green/red)
  4. A topic preview section shows the exact MQTT topics that will be published for each configured device
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 25 -> 26 -> 27

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 25. Publisher Infrastructure & Broker Connectivity | 2/2 | Complete    | 2026-03-22 |
| 26. Telemetry Publishing & Home Assistant Discovery | 0/2 | In progress | - |
| 27. Webapp Config & Status UI | 0/0 | Not started | - |
