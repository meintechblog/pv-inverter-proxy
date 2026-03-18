# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-17
**Core Value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter

## v1 Requirements

### Protocol Research & Validation

- [x] **PROTO-01**: dbus-fronius Source Code analysiert -- exakte Fronius-Erwartungen (Discovery, Manufacturer-String, SunSpec Models) dokumentiert
- [x] **PROTO-02**: SolarEdge SE30K Register-Map per Modbus TCP live ausgelesen und validiert
- [x] **PROTO-03**: Register-Mapping-Spezifikation erstellt (SolarEdge -> Fronius SunSpec Translation Table)

### Modbus Proxy Core

- [x] **PROXY-01**: Modbus TCP Server laeuft und akzeptiert Verbindungen von Venus OS
- [x] **PROXY-02**: SunSpec Common Model (Model 1) korrekt bereitgestellt mit Fronius-Manufacturer-String
- [x] **PROXY-03**: SunSpec Inverter Model 103 (three-phase) korrekt bereitgestellt mit Live-Daten vom SE30K
- [x] **PROXY-04**: SunSpec Nameplate Model (Model 120) korrekt bereitgestellt
- [x] **PROXY-05**: SunSpec Model Chain korrekt aufgebaut (Header -> Common -> Inverter -> Nameplate -> End)
- [x] **PROXY-06**: SolarEdge Register werden per Modbus TCP Client async gepollt
- [x] **PROXY-07**: Venus OS wird aus Register-Cache bedient (nicht synchron durch-proxied)
- [x] **PROXY-08**: Scale Factors korrekt uebersetzt zwischen SolarEdge und Fronius SunSpec-Profil
- [x] **PROXY-09**: Venus OS erkennt und zeigt den Proxy als Fronius Inverter an

### Steuerung (Control Path)

- [ ] **CTRL-01**: Venus OS kann Leistungsbegrenzung (Active Power Limit) setzen via SunSpec Model 123
- [ ] **CTRL-02**: Leistungsbegrenzung wird korrekt an SolarEdge SE30K weitergeleitet
- [ ] **CTRL-03**: Steuerungsbefehle werden validiert bevor sie an den Inverter gesendet werden

### Webapp

- [ ] **WEB-01**: Webapp erreichbar ueber HTTP im LAN
- [ ] **WEB-02**: SolarEdge IP-Adresse und Modbus-Port konfigurierbar ueber UI
- [ ] **WEB-03**: Verbindungsstatus zu SolarEdge und Venus OS live angezeigt
- [ ] **WEB-04**: Service-Health-Status angezeigt (uptime, letzte erfolgreiche Polls)
- [ ] **WEB-05**: Register-Viewer zeigt Live Modbus Register (SolarEdge-Quell- und Fronius-Ziel-Register)

### Deployment & Betrieb

- [ ] **DEPL-01**: Laeuft als systemd Service mit Auto-Start und Restart-on-Failure
- [ ] **DEPL-02**: Automatische Reconnection bei Verbindungsabbruch zum SolarEdge
- [ ] **DEPL-03**: Graceful Handling wenn Inverter offline (Nacht/Wartung) -- keine Crash-Loops
- [ ] **DEPL-04**: Strukturiertes Logging (JSON) fuer systemd Journal

### Architektur

- [x] **ARCH-01**: Plugin-Interface definiert fuer Inverter-Marken (SolarEdge als erstes Plugin)
- [x] **ARCH-02**: Register-Mapping als austauschbares Modul (nicht hardcoded)

## v2 Requirements

### Multi-Inverter

- **MULTI-01**: Mehrere SolarEdge-Inverter gleichzeitig proxyen
- **MULTI-02**: Andere Inverter-Marken als Plugins (Huawei, SMA, etc.)

### Erweiterte Steuerung

- **CTRL-10**: Einspeiseregelung mit konfigurierbarer Ramp-Rate
- **CTRL-11**: Scheduled Power Limiting (zeitgesteuerte Begrenzung)

### Webapp Erweiterungen

- **WEB-10**: Log-Viewer in Webapp
- **WEB-11**: Multi-Inverter Management UI
- **WEB-12**: Auto-Discovery von Invertern im Netzwerk

## Out of Scope

| Feature | Reason |
|---------|--------|
| TLS/Auth fuer Webapp | Alles im selben LAN, kein Sicherheits-Overhead gewuenscht |
| Mobile App | Webapp reicht, responsive Design genuegt |
| Historische Datenbank | Venus OS macht Langzeit-Logging selbst |
| Docker/Container-Orchestrierung | Direktes Deployment auf LXC (Debian 13) |
| Andere Inverter-Marken in v1 | Nur SolarEdge SE30K, aber Architektur vorbereitet |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROTO-01 | Phase 1 | Complete |
| PROTO-02 | Phase 1 | Complete |
| PROTO-03 | Phase 1 | Complete |
| PROXY-01 | Phase 2 | Complete |
| PROXY-02 | Phase 2 | Complete |
| PROXY-03 | Phase 2 | Complete |
| PROXY-04 | Phase 2 | Complete |
| PROXY-05 | Phase 2 | Complete |
| PROXY-06 | Phase 2 | Complete |
| PROXY-07 | Phase 2 | Complete |
| PROXY-08 | Phase 2 | Complete |
| PROXY-09 | Phase 2 | Complete |
| CTRL-01 | Phase 3 | Pending |
| CTRL-02 | Phase 3 | Pending |
| CTRL-03 | Phase 3 | Pending |
| WEB-01 | Phase 4 | Pending |
| WEB-02 | Phase 4 | Pending |
| WEB-03 | Phase 4 | Pending |
| WEB-04 | Phase 4 | Pending |
| WEB-05 | Phase 4 | Pending |
| DEPL-01 | Phase 3 | Pending |
| DEPL-02 | Phase 3 | Pending |
| DEPL-03 | Phase 3 | Pending |
| DEPL-04 | Phase 3 | Pending |
| ARCH-01 | Phase 2 | Complete |
| ARCH-02 | Phase 2 | Complete |

**Coverage:**
- v1 requirements: 26 total
- Mapped to phases: 26
- Unmapped: 0

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after roadmap creation*
