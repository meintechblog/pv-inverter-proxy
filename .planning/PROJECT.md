# Venus OS Fronius Proxy

## What This Is

Ein Modbus-TCP-Proxy-Dienst, der einen SolarEdge SE30K gegenüber Venus OS (Victron) als Fronius-Inverter erscheinen lässt. Venus OS erkennt, monitort und steuert den Inverter nativ — inkl. Live-Leistungsdaten, Einspeiseregelung und Power Limiting. Der Proxy läuft als systemd-Service auf einem LXC-Container und bietet eine Dark-Themed Web-Dashboard zur Konfiguration und Überwachung.

## Core Value

Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern können wie einen echten Fronius-Inverter — Monitoring UND aktive Steuerung (Leistungsbegrenzung, Einspeiseregelung).

## Requirements

### Validated

- ✓ Modbus-Proxy übersetzt SolarEdge-Register auf Fronius-kompatibles SunSpec-Profil — v1.0
- ✓ Venus OS erkennt den Proxy als Fronius-Inverter — v1.0
- ✓ Live-Daten (Leistung, Ertrag, Status) werden korrekt durchgereicht — v1.0
- ✓ Steuerungsbefehle (Leistungsbegrenzung) von Venus OS werden an SolarEdge weitergeleitet — v1.0
- ✓ Webapp zur Konfiguration (SolarEdge IP/Port, Verbindungsstatus, Register-Viewer) — v1.0
- ✓ Läuft als systemd-Service mit Auto-Start und Restart-on-Failure — v1.0
- ✓ Architektur ermöglicht weitere Inverter-Marken als Plugins — v1.0

### Active

- [ ] Venus OS Dashboard UI (exakte Venus OS Optik, Live-Leistungsdaten, 3-Phasen)
- [ ] Power Control UI (Slider 0-100%, Enable/Disable, Live Feedback vom Inverter)
- [ ] Venus OS Override Anzeige (wer drosselt gerade, welcher Wert)
- [ ] Mini-Graphen für Leistungsverlauf (letzte 60 Minuten, in-memory)
- [ ] Inverter-Info Dashboard (Spannung, Strom, Frequenz, Temperatur, Status)

## Current Milestone: v2.0 Dashboard & Power Control

**Goal:** Professionelles Dashboard im Venus OS Stil mit Live-Inverter-Monitoring und direkter Power-Control-Steuerung über die Webapp.

**Target features:**
- Venus OS styled Dashboard (exakte Farben, Fonts, Widgets)
- Live-Leistungs-Dashboard mit 3-Phasen-Details
- Power Limiting Test-UI (Slider, Toggle, Live Feedback)
- Venus OS Override Detection (wer kontrolliert gerade)
- Mini-Sparklines für Leistungsverlauf (60 min, in-memory Ring Buffer)

### Out of Scope

- Sicherheitsfeatures (TLS, Auth) — alles im selben LAN, nicht nötig
- Mobile App — Webapp reicht
- Historische Datenbank / Langzeit-Logging — Venus OS macht das, Webapp nur 60-min in-memory
- Andere Inverter-Marken in v1 — nur SolarEdge SE30K, aber Architektur vorbereitet

## Context

**Shipped v1.0** with 1,851 LOC Python (source) + 2,676 LOC tests.

Tech stack: Python 3.12, pymodbus 3.8+, aiohttp, structlog, PyYAML.

**Infrastructure:**
- SolarEdge SE30K: 192.168.3.18:1502 (Modbus TCP)
- Venus OS (Victron Cerbo/RPi5): 192.168.3.146 (v3.71)
- LXC Container: 192.168.3.191 (Debian 13, Proxmox)
- Proxy: Port 502 (Modbus) + Port 80 (Webapp)

**Live verified:** Venus OS shows "Fronius SE30K-RW00IBNM4" with ~10-14 kW live power, 3-phase data, 20+ MWh total energy. Power control via Model 123 → SE proprietary EDPC translation confirmed.

## Constraints

- **Deployment**: LXC-Container auf Proxmox (Debian 13) — kein Docker, kein K8s
- **Netzwerk**: Alle Geräte im selben LAN (192.168.3.0/24)
- **Protokoll**: Modbus TCP in beide Richtungen (SolarEdge ↔ Proxy ↔ Venus OS)
- **Kompatibilität**: Muss sich exakt wie ein Fronius-Inverter verhalten

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Plugin-Architektur für Inverter-Marken | User will künftig andere Marken anbinden | ✓ Good — InverterPlugin ABC mit 6 Methoden |
| Python + pymodbus + asyncio | Stabile Modbus-Bibliothek, async server+client | ✓ Good — clean dual-task pattern |
| Manufacturer "Fronius" statt "SolarEdge" | Auto Power Limit in Venus OS | ✓ Good — auto-enabled ohne User-Config |
| SunSpec Model 120+123 synthetisiert | SE30K hat diese nicht nativ | ✓ Good — Venus OS braucht beide |
| Cache-basiertes Proxy-Modell | Poller + Server async entkoppelt | ✓ Good — keine Pass-through-Latenz |
| Night Mode State Machine | Inverter nachts offline | ✓ Good — kein Crash, synthetic registers |
| Kein Sicherheits-Overhead | Alles im selben LAN | ✓ Good — einfach, wie gewünscht |
| Single-file HTML Frontend | Kein Build-Tooling nötig | ✓ Good — importlib.resources serving |

---
| Venus OS exakte UI Kopie | User will native Integration-Optik | — Pending |
| In-Memory Ring Buffer statt DB | Einfach, kein Storage, 60 min reicht | — Pending |

---
*Last updated: 2026-03-18 after v2.0 milestone start*
