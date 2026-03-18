# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-18
**Core Value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern können wie einen echten Fronius-Inverter

## v2 Requirements

Requirements for v2.0 Dashboard & Power Control UI milestone.

### Dashboard (DASH)

- [ ] **DASH-01**: Venus OS themed UI (exakte Farben #387DC5/#141414, Fonts, Widget-Style)
- [ ] **DASH-02**: Live Power Gauge — zentrale Anzeige aktuelle Leistung vs 30kW Nennleistung
- [ ] **DASH-03**: 3-Phasen Detail — L1/L2/L3 Strom, Spannung, Leistung einzeln
- [ ] **DASH-04**: Inverter Status Panel — Operating/Sleeping/Throttled/Fault, Temperatur, DC Werte
- [ ] **DASH-05**: Tagesertrag Anzeige — heutiger Ertrag in kWh (in-memory, reset bei Restart)
- [ ] **DASH-06**: Mini-Sparklines — Leistungsverlauf letzte 60 Minuten (SVG, in-memory Ring Buffer)

### Power Control (CTRL)

- [ ] **CTRL-04**: Read-only Anzeige — aktueller Power Limit Wert + wer ihn gesetzt hat
- [ ] **CTRL-05**: Test-Slider mit Bestätigungsdialog — 0-100% mit Confirm vor Schreiben
- [ ] **CTRL-06**: Enable/Disable Toggle mit Bestätigung
- [ ] **CTRL-07**: Live Feedback — Bestätigung vom SE30K dass Limit akzeptiert wurde
- [ ] **CTRL-08**: Venus OS Override Detection — anzeigen wenn Venus OS die Kontrolle hat
- [ ] **CTRL-09**: EDPC Refresh Loop — Backend hält Power Limit aktiv (periodic refresh)
- [ ] **CTRL-10**: Override Log — Logbuch wer wann welchen Wert gesetzt hat

### Infrastructure (INFRA)

- [ ] **INFRA-01**: Real-time Updates via SSE oder WebSocket (push statt polling)
- [x] **INFRA-02**: DashboardCollector — decoded Inverter-Daten einmal pro Poll-Cycle
- [x] **INFRA-03**: TimeSeriesBuffer — 60-min Ring Buffer für Sparklines (collections.deque)
- [x] **INFRA-04**: 3-File Split — index.html + style.css + app.js (statt single-file)
- [ ] **INFRA-05**: Config + Register Viewer integriert ins neue Dashboard (Tabs/Sections)

## Future Requirements

### Multi-Inverter

- **MULTI-01**: Mehrere SolarEdge-Inverter gleichzeitig proxyen
- **MULTI-02**: Andere Inverter-Marken als Plugins (Huawei, Kostal, etc.)

### Erweiterte Steuerung

- **CTRL-11**: Einspeiseregelung mit konfigurierbarer Ramp-Rate
- **CTRL-12**: Scheduled Power Limiting (zeitgesteuerte Begrenzung)

### Webapp Erweiterungen

- **WEB-10**: Log-Viewer in Webapp
- **WEB-11**: Multi-Inverter Management UI
- **WEB-12**: Auto-Discovery von Invertern im Netzwerk

## Out of Scope

| Feature | Reason |
|---------|--------|
| Persistente Datenbank | Venus OS macht Langzeit-Logging, Webapp nur 60-min in-memory |
| TLS/Auth | Alles im selben LAN, kein Internet-Exposure |
| Mobile App | Responsive Webapp reicht |
| Vollständiger Energy Flow Diagram | Proxy hat nur PV-Daten, kein Grid/Battery/Load — wäre unvollständig |
| Docker/Container-Orchestrierung | Direktes Deployment auf LXC (Debian 13) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DASH-01 | Phase 5 | Pending |
| DASH-02 | Phase 6 | Pending |
| DASH-03 | Phase 6 | Pending |
| DASH-04 | Phase 8 | Pending |
| DASH-05 | Phase 8 | Pending |
| DASH-06 | Phase 6 | Pending |
| CTRL-04 | Phase 7 | Pending |
| CTRL-05 | Phase 7 | Pending |
| CTRL-06 | Phase 7 | Pending |
| CTRL-07 | Phase 7 | Pending |
| CTRL-08 | Phase 7 | Pending |
| CTRL-09 | Phase 7 | Pending |
| CTRL-10 | Phase 7 | Pending |
| INFRA-01 | Phase 6 | Pending |
| INFRA-02 | Phase 5 | Complete |
| INFRA-03 | Phase 5 | Complete |
| INFRA-04 | Phase 5 | Complete |
| INFRA-05 | Phase 6 | Pending |

**Coverage:**
- v2 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0

---
*Requirements defined: 2026-03-18*
*Last updated: 2026-03-18 after v2.0 roadmap creation*
