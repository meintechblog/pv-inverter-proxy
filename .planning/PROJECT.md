# Venus OS Fronius Proxy

## What This Is

Ein Modbus-TCP-Proxy-Dienst, der einen SolarEdge SE30K gegenueber Venus OS (Victron) als Fronius-Inverter erscheinen laesst. Venus OS erkennt, monitort und steuert den Inverter nativ — inkl. Live-Leistungsdaten, Einspeiseregelung und Power Limiting. Der Proxy laeuft als systemd-Service auf einem LXC-Container und bietet ein einheitliches Venus OS styled Dark-Theme Dashboard mit Live-Monitoring, inline Power Control, Venus OS Lock Toggle, Peak-Statistiken und Smart Notifications — alles auf einer Seite.

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
- ✓ Smooth CSS Animations (Gauge 0.5s + deadband, Entrance, prefers-reduced-motion) — v2.1
- ✓ Toast Stacking System (max 4, exit animation, click-to-dismiss, duplicate suppression) — v2.1
- ✓ Peak Statistiken (Peak kW, Operating Hours, Efficiency) — v2.1
- ✓ Smart Event Notifications (Override, Fault, Temp >75C, Nachtmodus) — v2.1
- ✓ Venus OS Info Widget (Connection Status, Override-Anzeige) — v2.1
- ✓ Venus OS Lock Toggle (Apple-style, 900s Safety Cap, Confirmation Dialog) — v2.1
- ✓ Unified Dashboard (Power Control inline, 2-Row Grid, keine separate Seite) — v2.1

- ✓ Config Page mit Defaults, Save & Apply mit Live-Connection-Bobble — v3.0
- ✓ Venus OS Auto-Detect nach eingehender Modbus-Verbindung (gruenes Banner) — v3.0
- ✓ MQTT konfigurierbar (Venus OS IP, Port, Portal ID aus Config statt hardcoded) — v3.0
- ✓ Portal ID Auto-Discovery per MQTT Wildcard — v3.0
- ✓ MQTT Setup Guide mit Hinweis + ausgegraute Dashboard-Elemente bis MQTT connected — v3.0
- ✓ Install Script poliert (curl one-liner, sichere Flags, pre-flight checks) — v3.0
- ✓ README mit vollstaendigem v3.0 Setup-Flow — v3.0

### Active

(Keine — naechstes Milestone definieren mit `/gsd:new-milestone`)

### Out of Scope

- Persistente Datenbank — Venus OS macht Langzeit-Logging, Webapp nur in-memory
- TLS/Auth — Alles im selben LAN, kein Internet-Exposure
- Mobile App — Responsive Webapp reicht
- Vollstaendiger Energy Flow Diagram — Proxy hat nur PV-Daten, kein Grid/Battery/Load
- Docker/Container-Orchestrierung — Direktes Deployment auf LXC (Debian 13)
- Venus OS Modbus-Polling (Battery/Grid) — Register-Adressen unsicher, separater Client noetig

## Context

**Shipped v3.0** with ~3,000 LOC Python (src) + ~3,200 LOC HTML/CSS/JS + ~4,500 LOC tests. 41 files changed, +5,438 lines in v3.0.

Tech stack: Python 3.12, pymodbus 3.8+, aiohttp (HTTP + WebSocket), paho-mqtt, structlog, PyYAML, vanilla JS.

**Infrastructure:**
- SolarEdge SE30K: 192.168.3.18:1502 (Modbus TCP)
- Venus OS (Victron Cerbo/RPi5): 192.168.3.146 (v3.71)
- LXC Container: 192.168.3.191 (Debian 13, Proxmox)
- Proxy: Port 502 (Modbus) + Port 80 (Webapp)

**Live verified:** Venus OS shows "Fronius SE30K-RW00IBNM4" with ~10-14 kW live power. Unified dashboard with inline power control, Venus OS lock toggle, peak statistics, smart notifications, CSS animations. Config page with live connection bobbles, Venus OS auto-detect banner, MQTT setup guide. curl one-liner install.

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
| Venus OS Lock: silent accept | Locked writes accepted but not forwarded | ✓ Good — Venus OS sieht keinen Fehler |
| Lock 900s Hard Cap | Venus OS nie permanent aussperrbar | ✓ Good — Safety non-negotiable |
| Client-side event detection | Snapshot-Diff statt neue WS Message Types | ✓ Good — extend snapshot, not protocol |
| Gauge 50W Deadband | Verhindert Jitter bei 1Hz Updates | ✓ Good — smooth Industrial feel |
| VenusConfig Dataclass + Hot-Reload | MQTT Config aenderbar ohne Restart | ✓ Good — cancel old task, start new loop |
| Nested Config API {inverter, venus} | Zwei Config-Bereiche sauber getrennt | ✓ Good — backward compatible |
| Connection Bobbles statt Test Button | Live-Status statt One-Shot Test | ✓ Good — permanent sichtbar |
| MQTT Gate auf Dashboard | Venus-Widgets ausgegraut ohne MQTT | ✓ Good — klare UX, kein Fehler |
| Model 123 Write Detection | Venus OS Erkennung ueber Modbus Write | ✓ Good — zuverlaessig, kein False Positive |
| No Auto-Save bei Detection | User muss Config bestaetigen | ✓ Good — Safety first |

---
*Last updated: 2026-03-19 after v3.0 milestone completion*
