# Venus OS Fronius Proxy

## What This Is

Ein Modbus-TCP-Proxy-Dienst, der einen SolarEdge SE30K gegenüber Venus OS (Victron) als Fronius-Inverter erscheinen lässt. Venus OS erkennt, monitort und steuert den Inverter nativ — inkl. Live-Leistungsdaten, Einspeiseregelung und Power Limiting. Der Proxy laeuft als systemd-Service auf einem LXC-Container und bietet ein Venus OS styled Dark-Theme Web-Dashboard mit Live-Monitoring, Power Control und Inverter-Details.

## Core Value

Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter — Monitoring UND aktive Steuerung (Leistungsbegrenzung, Einspeiseregelung).

## Requirements

### Validated

- ✓ Modbus-Proxy uebersetzt SolarEdge-Register auf Fronius-kompatibles SunSpec-Profil — v1.0
- ✓ Venus OS erkennt den Proxy als Fronius-Inverter — v1.0
- ✓ Live-Daten (Leistung, Ertrag, Status) werden korrekt durchgereicht — v1.0
- ✓ Steuerungsbefehle (Leistungsbegrenzung) von Venus OS werden an SolarEdge weitergeleitet — v1.0
- ✓ Webapp zur Konfiguration (SolarEdge IP/Port, Verbindungsstatus, Register-Viewer) — v1.0
- ✓ Laeuft als systemd-Service mit Auto-Start und Restart-on-Failure — v1.0
- ✓ Architektur ermoeglicht weitere Inverter-Marken als Plugins — v1.0
- ✓ Venus OS themed Dashboard UI (exakte Farben, Fonts, Widget-Style) — v2.0
- ✓ Live Power Gauge mit 3-Phasen-Details (L1/L2/L3) — v2.0
- ✓ WebSocket Push fuer Real-time Updates ohne Polling — v2.0
- ✓ Mini-Sparklines fuer Leistungsverlauf (60 min in-memory Ring Buffer) — v2.0
- ✓ Power Control UI (Slider 0-100%, Enable/Disable, Confirmation Dialog) — v2.0
- ✓ Venus OS Override Detection und Override Log — v2.0
- ✓ EDPC Refresh Loop haelt Power Limit aktiv — v2.0
- ✓ Live Feedback vom SE30K nach Limit-Aenderung — v2.0
- ✓ Inverter Status Panel (Operating/Sleeping/Throttled/Fault, Temperatur, DC) — v2.0
- ✓ Tagesertrag Anzeige (kWh, in-memory, reset bei Restart) — v2.0

### Active

- [ ] Unified Dashboard — Power Control inline unter Power Gauge (keine separate Seite)
- [ ] Venus OS Info Widget — Connection Status, IP, letzter Kontakt, Override-Anzeige
- [ ] Venus OS Lock Toggle — Apple-style Slider um Venus OS Kontrolle zu sperren/erlauben
- [ ] Peak-Statistiken — heutiger Peak (kW), Betriebsstunden, Effizienz (in-memory)
- [ ] Smooth Animations — animierter Gauge, Transitions, Micro-Interactions
- [ ] Smart Notifications — Toast-Alerts bei Override, Fault, Temperatur-Warnung, Nachtmodus

### Out of Scope

- Persistente Datenbank — Venus OS macht Langzeit-Logging, Webapp nur 60-min in-memory
- TLS/Auth — Alles im selben LAN, kein Internet-Exposure
- Mobile App — Responsive Webapp reicht
- Vollstaendiger Energy Flow Diagram — Proxy hat nur PV-Daten, kein Grid/Battery/Load
- Docker/Container-Orchestrierung — Direktes Deployment auf LXC (Debian 13)

## Context

**Shipped v2.0** with 2,442 LOC Python (src) + 2,220 LOC HTML/CSS/JS + 3,656 LOC tests.

Tech stack: Python 3.12, pymodbus 3.8+, aiohttp (HTTP + WebSocket), structlog, PyYAML, vanilla JS.

**Infrastructure:**
- SolarEdge SE30K: 192.168.3.18:1502 (Modbus TCP)
- Venus OS (Victron Cerbo/RPi5): 192.168.3.146 (v3.71)
- LXC Container: 192.168.3.191 (Debian 13, Proxmox)
- Proxy: Port 502 (Modbus) + Port 80 (Webapp)

**Live verified:** Venus OS shows "Fronius SE30K-RW00IBNM4" with ~10-14 kW live power, 3-phase data, 20+ MWh total energy. Power control via Model 123 → SE proprietary EDPC translation confirmed. Dashboard WebSocket push working, power control slider with confirmation tested.

## Constraints

- **Deployment**: LXC-Container auf Proxmox (Debian 13) — kein Docker, kein K8s
- **Netzwerk**: Alle Geraete im selben LAN (192.168.3.0/24)
- **Protokoll**: Modbus TCP in beide Richtungen (SolarEdge ↔ Proxy ↔ Venus OS)
- **Kompatibilitaet**: Muss sich exakt wie ein Fronius-Inverter verhalten
- **Frontend**: Zero dependencies — vanilla JS, kein Build-Tooling

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Plugin-Architektur fuer Inverter-Marken | User will kuenftig andere Marken anbinden | ✓ Good — InverterPlugin ABC mit 6 Methoden |
| Python + pymodbus + asyncio | Stabile Modbus-Bibliothek, async server+client | ✓ Good — clean dual-task pattern |
| Manufacturer "Fronius" statt "SolarEdge" | Auto Power Limit in Venus OS | ✓ Good — auto-enabled ohne User-Config |
| SunSpec Model 120+123 synthetisiert | SE30K hat diese nicht nativ | ✓ Good — Venus OS braucht beide |
| Cache-basiertes Proxy-Modell | Poller + Server async entkoppelt | ✓ Good — keine Pass-through-Latenz |
| Night Mode State Machine | Inverter nachts offline | ✓ Good — kein Crash, synthetic registers |
| Kein Sicherheits-Overhead | Alles im selben LAN | ✓ Good — einfach, wie gewuenscht |
| 3-File Frontend (HTML+CSS+JS) | Kein Build-Tooling, einfaches Deployment | ✓ Good — importlib.resources serving |
| Venus OS exakte UI Kopie | User will native Integration-Optik | ✓ Good — #387DC5/#141414 Farbschema |
| In-Memory Ring Buffer statt DB | Einfach, kein Storage, 60 min reicht | ✓ Good — deque-basiert, ~1.3MB |
| WebSocket statt SSE | Power Control braucht bidirektionale Kommunikation | ✓ Good — aiohttp native WS |
| Zero new dependencies | Alles mit stdlib + aiohttp | ✓ Good — vanilla JS frontend |
| Slider mit Confirmation Dialog | Safety: kein versehentliches Power Limiting | ✓ Good — User-tested |
| Venus OS Priority Window 60s | Venus OS Override immer respektiert | ✓ Good — verhindert Konflikte |
| EDPC Refresh 30s | CommandTimeout/2 haelt Limit aktiv | ✓ Good — auto-revert nach 300s |

## Current Milestone: v2.1 Dashboard Redesign & Polish

**Goal:** Alle Dashboard-Funktionen (inkl. Power Control) auf einer einzigen Seite vereinen, Venus OS Instanz-Info anzeigen, und das Gesamterlebnis mit Animationen, Statistiken und Smart Notifications abrunden.

**Target features:**
- Power Control inline im Dashboard (kompakte Section unter Power Gauge)
- Venus OS Info Widget (Connection, Control Status, Apple-style Lock Toggle)
- Peak-Statistiken (Peak kW, Betriebsstunden, Effizienz)
- Smooth CSS Animations und Micro-Interactions
- Smart Toast-Notifications bei wichtigen Events

---
*Last updated: 2026-03-18 after v2.1 milestone start*
