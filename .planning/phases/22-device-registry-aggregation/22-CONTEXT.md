# Phase 22: Device Registry & Aggregation - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

DeviceRegistry manages N devices with independent poll loops (asyncio tasks). AggregationLayer sums all active inverter outputs into one virtual Fronius inverter for Venus OS. proxy.py decoupled from single plugin — RegisterCache fed by aggregated data. No power limit distribution (Phase 23), no UI changes (Phase 24).

</domain>

<decisions>
## Implementation Decisions

### Device Lifecycle
- Neues Device wird sofort gestartet: Poll-Loop (asyncio Task) + DeviceState angelegt + Aggregation beruecksichtigt beim naechsten Zyklus
- Disabled = komplett raus: kein Polling, kein Beitrag zur Aggregation, keine Daten. Config-Eintrag bleibt aber erhalten
- Bei Remove/Disable: Poll-Task canceln, DeviceState cleanup, DashboardCollector fuer dieses Device entfernen. Kein asyncio Task Leak
- Exponential Backoff bei Offline-Devices: 5s → 10s → 30s → 60s (aus Phase 21 CONTEXT deferred hierhin)
- Wenn KEIN aktiver Inverter konfiguriert: Modbus-Server (Port 502) komplett stoppen, damit Venus OS den virtuellen Inverter nicht mehr im Netzwerk findet. Server wird erst wieder gestartet wenn mindestens 1 Inverter aktiv ist

### Aggregation fuer Venus OS
- Power und Current werden summiert (Watt, Ampere — physikalische Einheiten)
- Spannung und Frequenz: Claude entscheidet (einfacher Durchschnitt oder vom groessten Inverter — User ist es egal)
- Energy (YieldDay, YieldTotal): Summe aller Devices
- Teilausfall: erreichbare Inverter summieren, offline-Inverter ignorieren (sofort, kein Caching des letzten Werts)
- Aggregierte Werte werden in SunSpec-Register konvertiert mit konsistenten Scale Factors
- Kein Fehler/Stale bei Teilausfall — solange mindestens 1 Inverter online

### Virtueller Inverter Name & Identity
- Config-Abschnitt: `virtual_inverter: name: "Meine PV-Anlage"`
- Default-Name wenn leer: "Fronius PV Inverter Proxy"
- Venus OS sieht: Manufacturer="Fronius", Model=user-definierter Name
- So bleibt Venus OS Auto Power Limit aktiviert (braucht Manufacturer=Fronius)
- Rated Power (WRtg Model 120): automatisch Summe aller aktiven Inverter rated_powers
- WRtg aktualisiert sich automatisch bei Device-Aenderungen

### Proxy Decoupling
- Modbus-Server bleibt auf Port 502 mit Unit ID 126 (keine Aenderung)
- RegisterCache wird von AggregationLayer befuellt statt von einzelnem Plugin
- _poll_loop in proxy.py wird durch DeviceRegistry Poll-Management ersetzt
- proxy.py behaelt: Modbus Server, StalenessAwareSlaveContext, ControlState
- Neuer Flow: N Plugins → N DeviceStates → AggregationLayer → RegisterCache → Modbus Server → Venus OS

### Claude's Discretion
- DeviceRegistry Klasse vs Modul-Level Funktionen
- Aggregation Tick-Intervall (nach jedem Poll vs periodisch)
- Wie primary_device Compat-Accessor aufgeloest wird
- Error-Handling bei fehlgeschlagener Task-Erstellung
- Ob AggregationLayer eigenes Modul oder Teil von DeviceRegistry

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 21 Output (Foundation)
- `src/venus_os_fronius_proxy/context.py` — AppContext, DeviceState, devices dict, primary_device accessor
- `src/venus_os_fronius_proxy/config.py` — InverterEntry (type, name, gateway_host), GatewayConfig, Config
- `src/venus_os_fronius_proxy/plugins/__init__.py` — plugin_factory(entry, gateway_config)
- `src/venus_os_fronius_proxy/plugins/opendtu.py` — OpenDTU plugin reference
- `src/venus_os_fronius_proxy/plugins/solaredge.py` — SolarEdge plugin reference

### Proxy & Poll Infrastructure
- `src/venus_os_fronius_proxy/proxy.py` — _poll_loop, run_proxy, StalenessAwareSlaveContext (must be decoupled)
- `src/venus_os_fronius_proxy/__main__.py` — App startup, plugin creation, AppContext wiring

### Dashboard & Broadcast
- `src/venus_os_fronius_proxy/dashboard.py` — DashboardCollector (per-device collectors needed + aggregated collector)
- `src/venus_os_fronius_proxy/webapp.py` — broadcast_to_clients, WebSocket handler

### Research
- `.planning/research/ARCHITECTURE.md` — DeviceRegistry design, AggregationLayer, suggested build order
- `.planning/research/PITFALLS.md` — Scale factor aggregation trap, partial failure handling

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AppContext.devices: dict[str, DeviceState]` — Already exists, DeviceRegistry populates it
- `DeviceState` — Has collector, conn_mgr, poll_counter fields ready
- `plugin_factory(entry, gateway_config)` — Creates correct plugin by type
- `ConnectionManager` — Reconnect with exponential backoff (reuse pattern for DeviceRegistry)
- `_poll_loop` in proxy.py — Reference for per-device poll logic (will be extracted/refactored)
- `DashboardCollector.collect()` — Per-device data collection pattern
- `broadcast_to_clients()` — WebSocket broadcast infrastructure

### Established Patterns
- asyncio.create_task for background loops
- Atomic config save (temp file + os.replace)
- Dataclasses for all structures
- Structlog logging

### Integration Points
- DeviceRegistry replaces _poll_loop in proxy.py
- AggregationLayer feeds RegisterCache instead of single plugin
- __main__.py creates DeviceRegistry instead of single plugin + poll_loop
- webapp.py _reconfigure_active needs rework for multi-device
- Model 120 WRtg register updated dynamically from aggregated rated_power

</code_context>

<specifics>
## Specific Ideas

- DeviceRegistry should feel like a "device manager" — start_device, stop_device, get_device_state
- Each device gets its own DashboardCollector for per-device snapshots (Phase 24 needs these)
- One aggregated DashboardCollector for the virtual inverter (Venus OS dashboard)
- primary_device accessor in AppContext can be removed once DeviceRegistry manages everything

</specifics>

<deferred>
## Deferred Ideas

- Power limit distribution across devices — Phase 23
- Per-device REST API endpoints — Phase 24
- Per-device UI dashboards — Phase 24
- Device-centric sidebar navigation — Phase 24

</deferred>

---

*Phase: 22-device-registry-aggregation*
*Context gathered: 2026-03-20*
