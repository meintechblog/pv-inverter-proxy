# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-20
**Core Value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen

## v4.0 Requirements

Requirements for Multi-Source Virtual Inverter. Each maps to roadmap phases.

### Data Model & Infrastructure

- [ ] **DATA-01**: Config unterstuetzt typisierte Device-Eintraege (type: solaredge | opendtu) mit typspezifischen Feldern
- [ ] **DATA-02**: Typisierter AppContext ersetzt flachen shared_ctx dict — jedes Device hat eigenen State
- [ ] **DATA-03**: Bestehende v3.1 Configs werden automatisch migriert (type: solaredge als Default)

### OpenDTU Integration

- [ ] **DTU-01**: System pollt OpenDTU REST API (/api/livedata/status) und liest AC Power, Voltage, Current, YieldDay, DC Channel Daten pro Hoymiles Inverter
- [ ] **DTU-02**: Jeder Hoymiles Inverter hinter einem OpenDTU Gateway wird als eigenes Device behandelt (1 OpenDTU → N Devices via Serial)
- [ ] **DTU-03**: System kann Power Limit pro Hoymiles Inverter setzen via POST /api/limit/config mit OpenDTU Basic Auth
- [ ] **DTU-04**: OpenDTU Plugin implementiert InverterPlugin ABC (poll, write_power_limit, reconfigure, close)
- [ ] **DTU-05**: System handelt die 18-25s Latenz bei Hoymiles Power Limit korrekt (Dead-Time Guard, kein Oszillieren)

### Device Registry & Poll Management

- [ ] **REG-01**: DeviceRegistry verwaltet N Devices mit unabhaengigen Poll-Loops (asyncio Tasks pro Device)
- [ ] **REG-02**: Devices koennen zur Laufzeit hinzugefuegt, entfernt, aktiviert und deaktiviert werden ohne Restart
- [ ] **REG-03**: Wenn ein Device deaktiviert/entfernt wird, werden alle zugehoerigen Daten (Snapshot, Collector, Poll-Task) sauber aufgeraeumt

### Virtual Inverter Aggregation

- [ ] **AGG-01**: Aggregation summiert Power, Current und Energy aller aktiven Inverter in physikalischen Einheiten (Watt, Ampere, Wh)
- [ ] **AGG-02**: Aggregierte Werte werden in SunSpec-Register konvertiert mit konsistenten Scale Factors fuer Venus OS
- [ ] **AGG-03**: Bei Teilausfall einzelner Inverter liefert die Aggregation weiterhin Daten der erreichbaren Geraete
- [ ] **AGG-04**: User kann den Namen des virtuellen Inverters fuer Venus OS definieren (Standardname vorausgewaehlt)

### Power Limit Distribution

- [ ] **PWR-01**: User definiert Prioritaets-Reihenfolge: welcher Inverter bei Limitierung zuerst gedrosselt wird
- [ ] **PWR-02**: Individuelle Inverter koennen vom Regelverhalten ausgeschlossen werden (nur Monitoring)
- [ ] **PWR-03**: Distribution beruecksichtigt unterschiedliche Latenzzeiten (SolarEdge instant vs Hoymiles 25s)
- [ ] **PWR-04**: Power Limit wird anteilig nach Prioritaet auf die Inverter verteilt (hoechste Prio wird zuerst gedrosselt)

### Device-Centric REST API

- [ ] **API-01**: REST Endpoints liefern per-Device Snapshots und Status (/api/devices/{id}/snapshot)
- [ ] **API-02**: WebSocket broadcastet per-Device Updates mit Device-ID Tag
- [ ] **API-03**: CRUD Endpoints fuer Device-Management (GET/POST/PUT/DELETE /api/devices)

### Device-Centric Frontend

- [ ] **UI-01**: Dynamische Sidebar zeigt alle konfigurierten Devices als eigene Menuepunkte
- [ ] **UI-02**: Jeder Inverter hat eigene Ansicht mit Dashboard (Leistung, Phasen/Channels, Status) und Registers
- [ ] **UI-03**: Venus OS hat eigenen Menuepunkt (ESS Status, MQTT Config, Portal ID)
- [ ] **UI-04**: Virtueller PV-Inverter hat eigene Ansicht mit aggregiertem Dashboard und Beitragsanzeige pro Inverter
- [ ] **UI-05**: Zentrales "+" im Sidebar zum Hinzufuegen neuer Devices (Inverter oder Venus OS)
- [ ] **UI-06**: Wenn ein Device deaktiviert/entfernt wird, verschwinden sofort alle zugehoerigen Daten aus der UI

## Future Requirements

### Erweiterte Inverter-Unterstuetzung

- **EXT-01**: Weitere Inverter-Marken als Plugins (Fronius nativ, Huawei, etc.)
- **EXT-02**: OpenDTU MQTT als Alternative zu REST Polling (effizienter fuer ESP32)

### Erweiterte Aggregation

- **EAGG-01**: Anteilige Beitragsanzeige pro Inverter im aggregierten Dashboard (Tortendiagramm)
- **EAGG-02**: Historische Vergleichsansicht zwischen Invertern

## Out of Scope

| Feature | Reason |
|---------|--------|
| Persistente Datenbank | Venus OS macht Langzeit-Logging, Webapp nur in-memory |
| TLS/Auth fuer Webapp | Alles im selben LAN, kein Internet-Exposure |
| Mobile App | Responsive Webapp reicht |
| Andere Inverter-Marken ausser SolarEdge/Hoymiles | Plugin-Architektur ist erweiterbar, aber v4.0 fokussiert auf diese zwei |
| Mehrere virtuelle Inverter an Venus OS | Ein aggregierter virtueller Inverter reicht |
| OpenDTU MQTT statt REST | REST ist einfacher, MQTT als Future Scope |
| Energy Flow Diagram | Proxy hat nur PV-Daten, kein Grid/Battery/Load |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | TBD | Pending |
| DATA-02 | TBD | Pending |
| DATA-03 | TBD | Pending |
| DTU-01 | TBD | Pending |
| DTU-02 | TBD | Pending |
| DTU-03 | TBD | Pending |
| DTU-04 | TBD | Pending |
| DTU-05 | TBD | Pending |
| REG-01 | TBD | Pending |
| REG-02 | TBD | Pending |
| REG-03 | TBD | Pending |
| AGG-01 | TBD | Pending |
| AGG-02 | TBD | Pending |
| AGG-03 | TBD | Pending |
| AGG-04 | TBD | Pending |
| PWR-01 | TBD | Pending |
| PWR-02 | TBD | Pending |
| PWR-03 | TBD | Pending |
| PWR-04 | TBD | Pending |
| API-01 | TBD | Pending |
| API-02 | TBD | Pending |
| API-03 | TBD | Pending |
| UI-01 | TBD | Pending |
| UI-02 | TBD | Pending |
| UI-03 | TBD | Pending |
| UI-04 | TBD | Pending |
| UI-05 | TBD | Pending |
| UI-06 | TBD | Pending |

**Coverage:**
- v4.0 requirements: 28 total
- Mapped to phases: 0
- Unmapped: 28

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-20 after initial definition*
