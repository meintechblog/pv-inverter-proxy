# Phase 21: Data Model & OpenDTU Plugin - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor config data model to support typed devices (solaredge + opendtu), implement OpenDTU plugin for Hoymiles inverter polling and power limiting, and replace flat shared_ctx with typed AppContext. No DeviceRegistry (Phase 22), no aggregation (Phase 22), no UI changes (Phase 24).

</domain>

<decisions>
## Implementation Decisions

### OpenDTU Device-Modell
- 1 Config-Eintrag pro Hoymiles Inverter (nicht pro Gateway)
- Jeder Eintrag hat: type:"opendtu", gateway_host, serial, name, enabled
- Name wird automatisch aus OpenDTU API uebernommen (User kann aendern)
- Optionales name-Feld fuer ALLE Device-Typen (SolarEdge + OpenDTU)
- Wenn name leer: Fallback auf Manufacturer+Model (SolarEdge) oder Serial (OpenDTU)
- OpenDTU-Inverter sollen per manuellem Discover gefunden werden koennen (Gateway-Host scannen, alle Serials auflisten)

### Config Structure (frischer Schnitt, keine Migration)
- KEINE Migration von v3.1 Config — frische Config, alles neu anlernen
- App ist noch nirgendwo produktiv im Einsatz, sauberer Schnitt
- Bestehender v3.1 Config-Format wird nicht mehr unterstuetzt
- Config-Struktur mit type-Feld pro Device:
  ```yaml
  inverters:
    - type: solaredge
      host: 192.168.3.18
      port: 1502
      unit_id: 1
      name: "SE30K Dach"
      enabled: true
    - type: opendtu
      gateway_host: 192.168.3.98
      serial: "112183818450"
      name: "Spielturm"
      enabled: true
  ```
- Gateway-Credentials (user/password) werden pro Gateway-Host gespeichert, nicht pro Inverter
  ```yaml
  gateways:
    opendtu:
      - host: 192.168.3.98
        user: admin
        password: openDTU42
        poll_interval: 5
  ```

### OpenDTU Auth & Polling
- Credentials pro Gateway (nicht pro Inverter) — weniger Redundanz
- Default: admin/openDTU42 (OpenDTU Standard)
- Poll-Intervall: 5s Default, konfigurierbar pro Gateway
- Bei Gateway offline: Retry mit exponential Backoff (5s → 10s → 30s → 60s) + Status-Dot
- Shared aiohttp.ClientSession pro Gateway (Connection Pooling)
- OpenDTU Plugin implementiert InverterPlugin ABC
- Dead-Time Guard fuer Power Limit: 25-30s Wartezeit nach Limit-Befehl an Hoymiles

### AppContext Refactor
- shared_ctx (flacher dict) wird zu @dataclass AppContext mit typisierten Feldern
- Jedes Device bekommt ein DeviceState-Objekt (collector, poll_counter, connection_state)
- Bestehender Code (__main__.py, webapp.py, proxy.py, dashboard.py) wird auf AppContext umgestellt
- Kein Functional Change fuer bestehende SolarEdge-Funktionalitaet — nur Strukturaenderung

### Claude's Discretion
- Exakte Felder des AppContext Dataclass
- DeviceState Dataclass Struktur
- OpenDTU Plugin interne Implementierung (aiohttp Session Management, JSON Parsing)
- Error-Handling Details bei OpenDTU API-Fehlern
- Ob Gateway-Config in eigener Dataclass oder als Dict in Config

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Plugin Architecture
- `src/venus_os_fronius_proxy/plugin.py` — InverterPlugin ABC (poll, write_power_limit, reconfigure, close)
- `src/venus_os_fronius_proxy/plugins/solaredge.py` — Reference implementation: AsyncModbusTcpClient, PollResult, reconfigure pattern

### Config System
- `src/venus_os_fronius_proxy/config.py` — InverterEntry, Config, ScannerConfig, VenusConfig, load_config, save_config
- `src/venus_os_fronius_proxy/__main__.py` — shared_ctx setup, plugin instantiation, poll loop start

### AppContext Users (files that access shared_ctx)
- `src/venus_os_fronius_proxy/proxy.py` — _poll_loop, run_proxy, StalenessAwareSlaveContext
- `src/venus_os_fronius_proxy/webapp.py` — REST handlers, WebSocket, broadcast
- `src/venus_os_fronius_proxy/dashboard.py` — DashboardCollector.collect()
- `src/venus_os_fronius_proxy/venus_reader.py` — venus_mqtt_loop

### OpenDTU API
- REST: GET `http://{host}/api/livedata/status` — returns all inverter data
- REST: POST `http://{host}/api/limit/config` — set power limit (Basic Auth required)
- REST: GET `http://{host}/api/limit/status` — current limit status per serial

### Research
- `.planning/research/STACK.md` — Zero new deps, aiohttp.ClientSession
- `.planning/research/ARCHITECTURE.md` — 5 new modules, integration points
- `.planning/research/PITFALLS.md` — Dead-time, single-connection, scale factors

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `InverterPlugin` ABC — poll(), write_power_limit(), reconfigure(), close() — OpenDTU plugin implements this
- `SolarEdgePlugin` — Reference for poll result format, error handling, connection management
- `PollResult` dataclass — success, common_registers, inverter_registers
- `ConnectionManager` — Reconnect with exponential backoff (reusable pattern for OpenDTU)
- `load_config` / `save_config` — YAML persistence with atomic write
- `validate_inverter_config` — Input validation pattern

### Established Patterns
- Dataclasses for all data structures
- Structlog for logging
- asyncio throughout (no threads)
- Atomic config save via temp file + os.replace()

### Integration Points
- New `plugins/opendtu.py` module
- Config.py: new type field, GatewayConfig dataclass
- `__main__.py`: AppContext replaces shared_ctx, plugin factory based on type
- All webapp.py/proxy.py/dashboard.py handlers: migrate from shared_ctx["key"] to app_ctx.key

</code_context>

<specifics>
## Specific Ideas

- OpenDTU at 192.168.3.98 has 2 inverters: "Spielturm" (HM-400, serial 112183818450) and "Balkon" (HM-600, serial 114182600464)
- OpenDTU API returns name per inverter — use as default device name
- Gateway credentials separate from inverter entries to avoid redundancy
- Poll interval 5s default but konfigurierbar — important for ESP32 stability
- Dead-time guard critical: 25s minimum between power limit commands to same Hoymiles

</specifics>

<deferred>
## Deferred Ideas

- DeviceRegistry with per-device poll lifecycle — Phase 22
- Virtual inverter aggregation — Phase 22
- Power limit distribution with priorities — Phase 23
- Device-centric UI — Phase 24
- OpenDTU MQTT als Alternative zu REST — Future Scope (EXT-02)

</deferred>

---

*Phase: 21-data-model-opendtu-plugin*
*Context gathered: 2026-03-20*
