# Requirements: Venus OS Fronius Proxy

**Defined:** 2026-03-19
**Core Value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter

## v3.0 Requirements

Requirements for Setup & Onboarding milestone. Each maps to roadmap phases.

### Config

- [x] **CFG-01**: Config Page zeigt vorausgefuellte Defaults (192.168.3.18:1502, Unit 1) beim ersten Besuch
- [x] **CFG-02**: "Test Connection" Button entfernt, ersetzt durch Live Connection-Bobble (gruen/rot/amber) nach Save & Apply
- [x] **CFG-03**: MQTT konfigurierbar — Venus OS IP, Port, Portal ID als Config-Felder statt hardcoded
- [x] **CFG-04**: Portal ID Auto-Discovery per MQTT Wildcard (`N/+/system/0/Serial`) wenn Portal ID leer

### Setup Flow

- [x] **SETUP-01**: Venus OS Auto-Config — Proxy erkennt eingehende Modbus-Verbindung und legt Venus OS Config-Eintrag mit Connection-Bobble an
- [x] **SETUP-02**: MQTT Setup Guide — Hinweis-Card wenn MQTT nicht verbunden mit Anleitung (Venus OS Remote Console → Settings → Services → MQTT on LAN)
- [x] **SETUP-03**: Dashboard MQTT-Gate — Lock Toggle, Override, Venus Settings ausgegraut mit Overlay-Hint bis MQTT connected

### Install & Docs

- [ ] **DOCS-01**: Install Script fixen — YAML Key Mismatch (`solaredge:` → `inverter:`), Venus Config Section, sichere curl Flags
- [ ] **DOCS-02**: README aktualisieren — Setup-Flow dokumentieren, Venus OS >= 3.7 Voraussetzung, Badges, Screenshots

## Future Requirements

### Extended Onboarding

- **ONBOARD-01**: Progressive Setup Checklist Banner (Inverter → SolarEdge → MQTT → Venus OS)
- **ONBOARD-02**: Network Scanner fuer SolarEdge Inverter

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-step Setup Wizard (Next/Back) | Over-engineering fuer 6 Felder — single Config Page reicht |
| Venus OS Auto-Provisioning (dbus write) | Fragil ueber Firmware-Versionen, bypassed User-Consent |
| SolarEdge Network Scanner | User kennt IP aus SolarEdge Portal, Scan dauert 5+ min |
| Separate Onboarding Page / First-Run | Adds routing + state mgmt, single-page Tool braucht das nicht |
| Live Modbus Probe bei Keystroke | Stoert SE30K, validate format client-side reicht |
| Full Service Restart bei Config Change | Hot-reload Pattern existiert bereits |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CFG-01 | Phase 14 | Complete |
| CFG-02 | Phase 14 | Complete |
| CFG-03 | Phase 13 | Complete |
| CFG-04 | Phase 13 | Complete |
| SETUP-01 | Phase 15 | Complete |
| SETUP-02 | Phase 14 | Complete |
| SETUP-03 | Phase 14 | Complete |
| DOCS-01 | Phase 16 | Pending |
| DOCS-02 | Phase 16 | Pending |

**Coverage:**
- v3.0 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-19 after roadmap creation*
