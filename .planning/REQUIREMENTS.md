# Requirements: PV-Inverter-Proxy v6.0 — Shelly Plugin

**Defined:** 2026-03-24
**Core Value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen

## Plugin Core

- [x] **PLUG-01**: ShellyPlugin implementiert InverterPlugin ABC (poll, connect, close, write_power_limit, get_model_120_registers, reconfigure)
- [x] **PLUG-02**: Profil-System mit Gen1 (REST /status, /relay) und Gen2+ (RPC /rpc/Switch.GetStatus, /rpc/Switch.Set) API-Adaptern
- [x] **PLUG-03**: Auto-Detection der Shelly-Generation via GET /shelly (gen-Feld vorhanden = Gen2+, fehlt = Gen1)
- [x] **PLUG-04**: Polling liefert Leistung (W), Spannung (V), Strom (A), Frequenz (Hz), Energie (Wh), Temperatur (C)
- [x] **PLUG-05**: SunSpec Model 103 Register-Encoding aus Shelly JSON (wie OpenDTU)
- [x] **PLUG-06**: Energy-Counter Offset-Tracking (Shelly resettet bei Reboot, Tagesertrag darf nicht springen)
- [x] **PLUG-07**: Fehlende Felder graceful behandeln (Gen1 hat weniger Daten, manche Modelle ohne Temperatur)

## Device Control

- [x] **CTRL-01**: On/Off Switch-Steuerung per Webapp (relay on/off statt Power-Limit Prozent)
- [x] **CTRL-02**: Switch-Status (on/off) in Connection Card anzeigen
- [x] **CTRL-03**: write_power_limit() als No-Op (Shelly kann kein %-Limiting), throttle_enabled default false

## UI Integration

- [ ] **UI-01**: "Shelly Device" als dritte Option im Add-Device Dialog
- [ ] **UI-02**: Auto-Detection und Generation-Anzeige beim Hinzufuegen (testet /shelly Endpoint)
- [ ] **UI-03**: Device Dashboard mit Gauge, AC-Werte (kein DC-Section — Capability-Flag)
- [ ] **UI-04**: Connection Card mit Shelly-spezifischen Infos (Generation, Switch-Status, On/Off Buttons)
- [ ] **UI-05**: Config-Seite mit Shelly-Host und erkannter Generation (readonly)
- [ ] **UI-06**: Auto-Discovery von Shelly-Devices im LAN (Netzwerk-Scan mit /shelly Probe auf gefundene Hosts)

## Aggregation

- [ ] **AGG-01**: Shelly-Daten fliessen korrekt in den virtuellen PV-Inverter ein (AggregationLayer)
- [ ] **AGG-02**: DC-Averaging im Aggregator ueberspringt Shelly (kein DC-Data)

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLUG-01 | Phase 28 | Complete |
| PLUG-02 | Phase 28 | Complete |
| PLUG-03 | Phase 28 | Complete |
| PLUG-04 | Phase 28 | Complete |
| PLUG-05 | Phase 28 | Complete |
| PLUG-06 | Phase 28 | Complete |
| PLUG-07 | Phase 28 | Complete |
| CTRL-01 | Phase 29 | Complete |
| CTRL-02 | Phase 29 | Complete |
| CTRL-03 | Phase 29 | Complete |
| UI-01 | Phase 30 | Pending |
| UI-02 | Phase 30 | Pending |
| UI-03 | Phase 31 | Pending |
| UI-04 | Phase 31 | Pending |
| UI-05 | Phase 30 | Pending |
| UI-06 | Phase 30 | Pending |
| AGG-01 | Phase 32 | Pending |
| AGG-02 | Phase 32 | Pending |

## Future Requirements

- Shelly Auth-Support (Digest Auth fuer Gen2+)
- Multi-Channel Support (Shelly 2.5, Shelly Pro 2PM)

## Out of Scope

- Shelly Cloud API — Nur lokale REST API, kein Cloud-Account
- Shelly Scripting/Automation — Nur Polling + Switch, keine Shelly-interne Logik
- Shelly Firmware Updates — Nicht ueber unsere Webapp
