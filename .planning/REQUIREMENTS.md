# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-22
**Core Value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen

## v5.0 Requirements

Requirements for MQTT Data Publishing milestone. Each maps to roadmap phases.

### MQTT Publishing

- [x] **PUB-01**: Proxy publisht Inverter-Daten (Leistung, Spannung, Strom, Temperatur, Status) pro Device an MQTT Broker
- [x] **PUB-02**: Proxy publisht aggregierte Virtual-PV-Daten (Gesamtleistung, Contributions) an MQTT Broker
- [x] **PUB-03**: Publish-Intervall ist konfigurierbar (Default: 5s)
- [x] **PUB-04**: Publisher nutzt Change-based Optimization — kein Publish wenn Daten unveraendert
- [x] **PUB-05**: Publisher nutzt LWT fuer Online/Offline-Availability-Tracking
- [x] **PUB-06**: Device-Status-Messages sind retained fuer neue Subscriber

### Home Assistant Integration

- [x] **HA-01**: Publisher sendet MQTT Auto-Discovery Config Payloads fuer alle Sensoren
- [x] **HA-02**: Sensoren haben korrekte device_class und state_class fuer HA Energy Dashboard
- [x] **HA-03**: Inverter erscheinen als gruppierte Devices in HA (Manufacturer, Model, SW Version)
- [x] **HA-04**: Availability-Entity pro Device reagiert auf LWT

### Broker Connectivity

- [x] **CONN-01**: MQTT Broker Host/Port ist konfigurierbar (Default: mqtt-master.local:1883)
- [x] **CONN-02**: Publisher reconnected automatisch mit Exponential Backoff bei Verbindungsverlust
- [x] **CONN-03**: mDNS Autodiscovery findet MQTT Broker im LAN
- [x] **CONN-04**: Broker-Konfiguration ist hot-reloadable ohne Service-Restart

### Webapp Config

- [x] **UI-01**: Config-Seite zeigt MQTT Publishing Settings (Enable/Disable, Broker, Port, Intervall)
- [x] **UI-02**: mDNS Discovery Button findet Broker im LAN und fuellt Formular
- [ ] **UI-03**: Connection-Status-Dot zeigt ob MQTT Publisher verbunden ist
- [ ] **UI-04**: Topic-Preview zeigt die generierten MQTT Topics

## Future Requirements

### Advanced MQTT

- **ADV-01**: MQTT Username/Password Authentication
- **ADV-02**: TLS-verschluesselte MQTT Verbindung
- **ADV-03**: Custom Topic Templates (User-definierbare Topic-Struktur)

## Out of Scope

| Feature | Reason |
|---------|--------|
| MQTT Bridge/Relay | Proxy ist Publisher, kein Broker |
| Bidirektionale MQTT Steuerung | Steuerung laeuft ueber Venus OS, nicht MQTT |
| InfluxDB/Grafana direkt | MQTT ist der Transport, Consumers bauen Dritte |
| Refactor venus_reader.py MQTT | Bestehender Venus OS MQTT Client bleibt wie er ist |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PUB-01 | Phase 26 | Complete |
| PUB-02 | Phase 26 | Complete |
| PUB-03 | Phase 25 | Complete |
| PUB-04 | Phase 26 | Complete |
| PUB-05 | Phase 25 | Complete |
| PUB-06 | Phase 26 | Complete |
| HA-01 | Phase 26 | Complete |
| HA-02 | Phase 26 | Complete |
| HA-03 | Phase 26 | Complete |
| HA-04 | Phase 26 | Complete |
| CONN-01 | Phase 25 | Complete |
| CONN-02 | Phase 25 | Complete |
| CONN-03 | Phase 25 | Complete |
| CONN-04 | Phase 25 | Complete |
| UI-01 | Phase 27 | Pending |
| UI-02 | Phase 27 | Pending |
| UI-03 | Phase 27 | Pending |
| UI-04 | Phase 27 | Pending |

**Coverage:**
- v5.0 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0

---
*Requirements defined: 2026-03-22*
*Last updated: 2026-03-22 after roadmap creation*
