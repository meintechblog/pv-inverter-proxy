# Venus OS Fronius Proxy

## What This Is

Ein Multi-Source PV-Aggregator, der beliebige Inverter (SolarEdge via Modbus TCP, Hoymiles via OpenDTU REST) zu einem virtuellen PV-Inverter buendelt und gegenueber Venus OS (Victron) als Fronius-Inverter erscheinen laesst. Venus OS erkennt, monitort und steuert die aggregierte PV-Anlage nativ. Device-zentrische Webapp mit pro-Inverter Dashboards, zentraler Konfiguration und flexiblem Regelverhalten fuer Power Limiting.

## Core Value

Venus OS muss alle PV-Inverter (egal welche Marke/Protokoll) als einen einzigen virtuellen Fronius-Inverter erkennen und steuern koennen — aggregiertes Monitoring UND koordinierte Steuerung (Leistungsbegrenzung, Einspeiseregelung).

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

- ✓ Auto-Discovery: Netzwerk-Scan findet SunSpec-Inverter automatisch — v3.1
- ✓ Auto-Scan bei Ersteinrichtung wenn kein Inverter konfiguriert — v3.1
- ✓ Manueller Re-Scan ueber Config-UI mit Fortschrittsbalken — v3.1
- ✓ Multi-Inverter Config mit Enable/Disable Toggle und Loeschen — v3.1
- ✓ Inverter-Eintraege aus Scan-Ergebnissen automatisch angelegt — v3.1
- ✓ Konfigurierbare Scan-Ports (Default: 502, 1502) persistent — v3.1
- ✓ Unit ID Scan (Default: 1, optional 2-10 fuer RS485 Chains) — v3.1

- ✓ OpenDTU Plugin: Hoymiles Micro-WR ueber OpenDTU REST API integriert — v4.0
- ✓ Device-zentrische UI: Pro Inverter eigener Menuepunkt mit Dashboard + Registers + Config — v4.0
- ✓ Virtueller PV-Inverter: Alle aktiven Inverter zu einem aggregierten Fronius-Device fuer Venus OS — v4.0
- ✓ Flexibles Regelverhalten: Prioritaets-Reihenfolge fuer Power Limiting (Wasserfall-Algorithmus) — v4.0
- ✓ Inverter aus Regelverhalten ausschliessbar (Monitoring-Only) — v4.0
- ✓ Benutzerdefinierter Name fuer den virtuellen Inverter (Default: "Fronius PV-Inverter-Master") — v4.0
- ✓ Venus OS als eigenes Device mit eigenem Menuepunkt (ESS, MQTT, Status) — v4.0
- ✓ Zentrales Device-Management: "+" zum Hinzufuegen von Invertern und Venus OS — v4.0

- ✓ Shelly Plugin: Shelly Smart Devices als Inverter-Plugin mit Profil-System (Gen1/Gen2/Gen3) — v6.0
- ✓ Auto-Detection der Shelly-Generation beim Hinzufuegen — v6.0
- ✓ Shelly Polling: Leistung, Spannung, Strom, Energie, Temperatur via REST API — v6.0
- ✓ Shelly Switch-Steuerung: On/Off per Webapp (kein Power-Limiting) — v6.0
- ✓ Shelly Device-Dashboard: Gauge, AC-Werte, Connection-Card mit On/Off Toggle — v6.0
- ✓ Shelly Aggregation: Daten fliessen in virtuellen PV-Inverter ein (DC-Skip fuer Zero-DC Devices) — v6.0
- ✓ Shelly Add-Device Flow: Dritte Option neben SolarEdge/OpenDTU mit mDNS Discovery — v6.0
- ✓ Throttle Capabilities: ThrottleCaps mit Score (0-10) pro Device — v6.0
- ✓ Binary Throttle Engine: Relay-Steuerung mit Cooldown-Hysterese und Startup-Grace — v6.0
- ✓ Smart Auto-Throttle: Score-basierte Waterfall-Reihenfolge mit Live-Convergence-Messung — v6.0
- ✓ Auto-Throttle UI: Toggle, Presets, Throttle-Tabelle, State-Contribution-Bar — v6.0

### Active

## Current Milestone: v7.0 Sungrow SG-RT Plugin

**Goal:** Full-Stack Integration des Sungrow SG-RT Wechselrichters als vierter Inverter-Typ mit Modbus TCP Polling, 3-Phasen Dashboard, Power Limiting, Discovery und Throttle-Integration.

**Target features:**
- Sungrow Plugin mit Modbus TCP Polling und SunSpec Register Encoding
- Power Limiting via Modbus Holding Register Write
- 3-Phasen AC Dashboard mit MPPT DC Channels
- Add-Device Flow mit Modbus Probe und Netzwerk-Discovery
- Config UI und Throttle Integration

### Out of Scope

- Persistente Datenbank — Venus OS macht Langzeit-Logging, Webapp nur in-memory
- TLS/Auth — Alles im selben LAN, kein Internet-Exposure
- Mobile App — Responsive Webapp reicht
- Vollstaendiger Energy Flow Diagram — Proxy hat nur PV-Daten, kein Grid/Battery/Load
- Docker/Container-Orchestrierung — Direktes Deployment auf LXC (Debian 13)
- Venus OS Modbus-Polling (Battery/Grid) — Register-Adressen unsicher, separater Client noetig
- Shelly Cloud API — Nur lokale REST API, kein Cloud-Account noetig

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

## Context

**Shipped v3.1** with ~8,650 LOC total (Python src + HTML/CSS/JS + tests). 20 phases across 5 milestones shipped.

Tech stack: Python 3.12, pymodbus 3.8+, aiohttp (HTTP + WebSocket), paho-mqtt, structlog, PyYAML, vanilla JS.

**Infrastructure:**
- SolarEdge SE30K: 192.168.3.18:1502 (Modbus TCP)
- Venus OS (Victron Cerbo/RPi5): 192.168.3.146 (v3.71)
- LXC Container: 192.168.3.191 (Debian 13, Proxmox)
- Proxy: Port 502 (Modbus) + Port 80 (Webapp)

**Live verified:** Full-featured dashboard with inline power control, Venus OS lock toggle, peak statistics. Config page with inverter management, auto-discovery with progress bar, auto-scan on empty config. curl one-liner install.

## Context

**Shipped v4.0** with ~5,500 LOC Python (src) + ~4,300 LOC HTML/CSS/JS + ~7,400 LOC tests. 24 phases across 6 milestones shipped.

Tech stack: Python 3.12, pymodbus 3.8+, aiohttp (HTTP + WebSocket + REST client for OpenDTU), paho-mqtt, structlog, PyYAML, vanilla JS.

**Architecture v4.0:**
- DeviceRegistry: per-device asyncio poll loops with independent lifecycle
- AggregationLayer: SunSpec register summation across heterogeneous sources
- PowerLimitDistributor: Waterfall algorithm with Throttling Order
- Device-centric SPA: dynamic sidebar, hash routing, per-device sub-tabs

**Infrastructure:**
- SolarEdge SE30K: 192.168.3.18:1502 (Modbus TCP)
- OpenDTU (Hoymiles): 192.168.3.98 (REST API)
- Venus OS (Victron Cerbo/RPi5): 192.168.3.146 (v3.71)
- LXC Container: 192.168.3.191 (Debian 13, Proxmox)
- Proxy: Port 502 (Modbus) + Port 80 (Webapp)

## Completed Milestone: v6.0 Shelly Plugin (shipped 2026-03-25)

**Delivered:** Shelly Smart Devices als drittes Inverter-Plugin mit Gen1/Gen2/Gen3 Profil-System, On/Off-Steuerung, mDNS Discovery, Aggregation, und Smart Auto-Throttle mit Score-basierter Waterfall-Reihenfolge und Live-Convergence-Messung.

**10 phases, 12 plans, 23 tasks. See .planning/milestones/ for archive.**

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-06 after Phase 38 (Plugin Core) complete — SungrowPlugin backend ready*
