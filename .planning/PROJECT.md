# Venus OS Fronius Proxy

## What This Is

Ein Modbus-TCP-Proxy-Dienst, der einen SolarEdge-Wechselrichter (zunächst SE30K) gegenüber Venus OS (Victron) als Fronius-Inverter erscheinen lässt. Venus OS kann den Inverter dann nativ erkennen, monitoren und steuern — ohne Modifikationen am Venus OS selbst. Der Proxy läuft als Dienst in einem LXC-Container auf Proxmox und wird über eine einfache Webapp konfiguriert.

## Core Value

Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern können wie einen echten Fronius-Inverter — Monitoring UND aktive Steuerung (Leistungsbegrenzung, Einspeiseregelung).

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Modbus-Proxy übersetzt SolarEdge-Register auf Fronius-kompatibles Sunspec-Profil
- [ ] Venus OS erkennt den Proxy als Fronius-Inverter
- [ ] Live-Daten (Leistung, Ertrag, Status) werden korrekt durchgereicht
- [ ] Steuerungsbefehle (Leistungsbegrenzung) von Venus OS werden an SolarEdge weitergeleitet
- [ ] Webapp zur Konfiguration (SolarEdge IP/Port, Verbindungsstatus, Mapping-Übersicht)
- [ ] Läuft als Systemdienst im LXC-Container
- [ ] Architektur ermöglicht künftig weitere Inverter-Marken als Plugins

### Out of Scope

- Sicherheitsfeatures (TLS, Auth) — alles im selben LAN, nicht nötig
- Mobile App — Webapp reicht
- Historische Datenbank / Langzeit-Logging — Venus OS macht das selbst
- Andere Inverter-Marken in v1 — nur SolarEdge SE30K, aber Architektur vorbereitet

## Context

- **SolarEdge SE30K**: Modbus TCP aktiv auf 192.168.3.18:1502. Register-Dokumentation muss recherchiert werden (SolarEdge nutzt Sunspec-kompatibles Modbus-Profil mit eigenen Erweiterungen).
- **Venus OS**: Fresh Install auf 192.168.3.146. Victron unterstützt Fronius-Inverter nativ — der Proxy muss das Fronius-Sunspec-Profil exakt nachbilden, damit Venus OS den Proxy als echten Fronius erkennt.
- **LXC-Container**: Debian 13 (Trixie) auf Proxmox, erreichbar unter 192.168.3.191 (root SSH).
- **Fronius-Integration in Venus OS**: Muss recherchiert werden — vermutlich Sunspec Modbus TCP, aber exaktes Discovery-Protokoll und erwartete Register müssen ermittelt werden.

## Constraints

- **Deployment**: LXC-Container auf Proxmox (Debian 13) — kein Docker, kein K8s
- **Netzwerk**: Alle Geräte im selben LAN (192.168.3.0/24), keine besonderen Sicherheitsanforderungen
- **Protokoll**: Modbus TCP in beide Richtungen (SolarEdge ↔ Proxy ↔ Venus OS)
- **Kompatibilität**: Muss sich exakt wie ein Fronius-Inverter verhalten, damit Venus OS es nativ akzeptiert

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Plugin-Architektur für Inverter-Marken | User will künftig andere Marken anbinden | — Pending |
| Tech Stack | Noch offen — Research soll empfehlen | — Pending |
| Kein Sicherheits-Overhead | Alles im selben LAN, User will es einfach | — Pending |

---
*Last updated: 2026-03-17 after initialization*
