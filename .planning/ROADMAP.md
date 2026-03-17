# Roadmap: Venus OS Fronius Proxy

## Overview

This roadmap delivers a Modbus TCP proxy that makes a SolarEdge SE30K appear as a Fronius inverter to Venus OS. We start with protocol research (the single biggest risk), then build the core read-path proxy, then add the control write-path and production hardening, and finally layer on the config webapp. Each phase delivers a verifiable capability that builds on the previous one.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Protocol Research & Validation** - Verify dbus-fronius expectations, read SolarEdge registers, produce translation spec
- [ ] **Phase 2: Core Proxy (Read Path)** - Modbus TCP proxy that makes Venus OS discover and monitor the SolarEdge as a Fronius inverter
- [ ] **Phase 3: Control Path & Production Hardening** - Power limiting write path plus systemd service, reconnection, and logging
- [ ] **Phase 4: Configuration Webapp** - Web UI for configuration, connection status, and register inspection

## Phase Details

### Phase 1: Protocol Research & Validation
**Goal**: All protocol unknowns are resolved and a validated register mapping specification exists
**Depends on**: Nothing (first phase)
**Requirements**: PROTO-01, PROTO-02, PROTO-03
**Success Criteria** (what must be TRUE):
  1. dbus-fronius source code has been analyzed and the exact discovery requirements (manufacturer string, SunSpec model order, any HTTP dependencies) are documented
  2. SolarEdge SE30K registers have been read live via Modbus TCP and the actual register layout matches or has been reconciled with documentation
  3. A complete register mapping table exists that translates every needed SolarEdge register to its Fronius SunSpec equivalent (including scale factors)
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Project scaffolding, dbus-fronius expectations doc, register mapping spec with unit tests
- [ ] 01-02-PLAN.md — Live SE30K register validation via Modbus TCP

### Phase 2: Core Proxy (Read Path)
**Goal**: Venus OS discovers the proxy as a Fronius inverter and displays live monitoring data from the SolarEdge SE30K
**Depends on**: Phase 1
**Requirements**: PROXY-01, PROXY-02, PROXY-03, PROXY-04, PROXY-05, PROXY-06, PROXY-07, PROXY-08, PROXY-09, ARCH-01, ARCH-02
**Success Criteria** (what must be TRUE):
  1. Venus OS auto-discovers the proxy and shows it as a Fronius inverter in the device list
  2. Live power output, energy yield, and inverter status from the SolarEdge SE30K are displayed correctly in Venus OS
  3. The proxy serves a valid SunSpec model chain (Common -> Inverter 103 -> Nameplate 120 -> End) with correct Fronius manufacturer string
  4. SolarEdge registers are polled asynchronously and Venus OS reads from a local cache (not pass-through)
  5. The inverter-brand-specific code is isolated behind a plugin interface that can be swapped for other brands
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD
- [ ] 02-03: TBD

### Phase 3: Control Path & Production Hardening
**Goal**: Venus OS can throttle the SolarEdge inverter's power output and the proxy runs reliably as a system service
**Depends on**: Phase 2
**Requirements**: CTRL-01, CTRL-02, CTRL-03, DEPL-01, DEPL-02, DEPL-03, DEPL-04
**Success Criteria** (what must be TRUE):
  1. Venus OS can set an active power limit via SunSpec Model 123 and the SolarEdge SE30K reduces its output accordingly
  2. Invalid or out-of-range control commands are rejected before reaching the inverter
  3. The proxy runs as a systemd service that auto-starts on boot and restarts on failure
  4. The proxy reconnects automatically when the SolarEdge connection drops, and handles inverter-offline periods (night/maintenance) without crashing
  5. Structured JSON logs are written to the systemd journal
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

### Phase 4: Configuration Webapp
**Goal**: The proxy is configurable and monitorable through a web browser without SSH access
**Depends on**: Phase 3
**Requirements**: WEB-01, WEB-02, WEB-03, WEB-04, WEB-05
**Success Criteria** (what must be TRUE):
  1. A user can open the webapp in a browser and configure the SolarEdge IP address and Modbus port
  2. The webapp shows live connection status for both the SolarEdge inverter and Venus OS
  3. The webapp shows service health (uptime, last successful poll timestamps)
  4. A register viewer displays both the raw SolarEdge source registers and the translated Fronius target registers in real time
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Protocol Research & Validation | 0/2 | Planning complete | - |
| 2. Core Proxy (Read Path) | 0/? | Not started | - |
| 3. Control Path & Production Hardening | 0/? | Not started | - |
| 4. Configuration Webapp | 0/? | Not started | - |
