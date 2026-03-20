# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-20
**Core Value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter

## v3.1 Requirements

Requirements for Auto-Discovery & Inverter Management. Each maps to roadmap phases.

### Discovery

- [x] **DISC-01**: System kann das lokale Subnet scannen und alle IPs auf konfigurierbaren Ports (Default: 502, 1502) auf Modbus TCP testen
- [x] **DISC-02**: System verifiziert gefundene Modbus-Geraete via SunSpec "SunS" Magic Number an Register 40000
- [x] **DISC-03**: System liest Manufacturer, Model, Serial Number und Firmware-Version aus SunSpec Common Block
- [x] **DISC-04**: System scannt Unit ID 1 (Primary) und optional 2-10 (RS485 Followers) pro gefundener IP
- [ ] **DISC-05**: User sieht Scan-Fortschritt im UI (Fortschrittsbalken oder Animation waehrend des ~30s Scans)

### Config Management

- [x] **CONF-01**: Config unterstuetzt mehrere Inverter-Eintraege (Liste statt einzelner Eintrag)
- [x] **CONF-02**: User kann jeden Inverter-Eintrag per Toggle-Slider aktivieren/deaktivieren
- [x] **CONF-03**: User kann Inverter-Eintraege loeschen
- [ ] **CONF-04**: Gefundene Inverter aus Scan werden automatisch als Config-Eintraege angelegt
- [x] **CONF-05**: Bestehende Single-Inverter Config wird automatisch ins Multi-Inverter Format migriert

### UX/Onboarding

- [ ] **UX-01**: Wenn kein Inverter konfiguriert ist, startet automatisch ein Hintergrund-Scan beim Oeffnen der Config-Seite
- [ ] **UX-02**: User kann manuell einen Re-Scan triggern ueber einen Auto-Discover Button in der Config-Leiste
- [ ] **UX-03**: Scan-Ergebnisse werden als Vorschau-Liste angezeigt, User bestaetigt Uebernahme

## Future Requirements

### Multi-Proxy

- **MPRX-01**: Mehrere Inverter gleichzeitig als separate Fronius-Devices an Venus OS durchreichen
- **MPRX-02**: Jeder aktive Inverter bekommt eigenen Modbus-Server-Port

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-Inverter parallel an Venus OS | v3.1 baut Management, aber nur ein aktiver Proxy-Inverter. Parallel-Support als Future Scope |
| Andere Inverter-Marken discovern | Discovery ist SunSpec-basiert, koennte theoretisch andere finden, aber Proxy unterstuetzt nur SolarEdge |
| mDNS/UPnP Discovery | Modbus TCP hat kein Service Discovery — direkter Port-Scan ist zuverlaessiger |
| Cloud-basierte Discovery | Alles lokal im LAN, kein Internet-Zugriff noetig |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DISC-01 | Phase 17 | Complete |
| DISC-02 | Phase 17 | Complete |
| DISC-03 | Phase 17 | Complete |
| DISC-04 | Phase 17 | Complete |
| DISC-05 | Phase 20 | Pending |
| CONF-01 | Phase 18 | Complete |
| CONF-02 | Phase 19 | Complete |
| CONF-03 | Phase 19 | Complete |
| CONF-04 | Phase 20 | Pending |
| CONF-05 | Phase 18 | Complete |
| UX-01 | Phase 20 | Pending |
| UX-02 | Phase 20 | Pending |
| UX-03 | Phase 20 | Pending |

**Coverage:**
- v3.1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-20 after roadmap creation*
