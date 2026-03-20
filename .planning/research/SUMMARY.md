# Project Research Summary

**Project:** Venus OS Fronius Proxy — v4.0 Multi-Source Virtual Inverter
**Domain:** Multi-source PV aggregation proxy with device-centric management
**Researched:** 2026-03-20
**Confidence:** HIGH

## Executive Summary

This v4.0 milestone transforms the proxy from a single-inverter bridge (SolarEdge SE30K -> Venus OS) into a multi-source virtual inverter that aggregates N physical inverters into one logical Fronius device. The core value proposition is that Venus OS continues to see exactly one SunSpec inverter, while the proxy transparently aggregates SolarEdge Modbus TCP and Hoymiles micro-inverters via OpenDTU REST API. The recommended approach requires no new Python dependencies (aiohttp already handles HTTP REST polling), adds 5 focused new modules (OpenDTU plugin, DeviceRegistry, AggregationLayer, PowerLimitDistributor, plugin factory), and modifies 7 existing files. The existing InverterPlugin ABC fits the OpenDTU use case without changes.

The biggest architectural shift is decoupling `proxy.py` from a single plugin instance. Currently the poll loop, register cache, and Modbus server all assume one inverter. A new AggregationLayer must sit between per-device pollers and the register cache, summing physical values (not raw registers) before encoding into the SunSpec format Venus OS reads. This aggregation-in-physical-units requirement is non-negotiable: naive addition of raw SunSpec register values produces wrong results due to heterogeneous scale factors across device types.

The primary risks are operational rather than technical. OpenDTU power limits take 18-25 seconds to activate on Hoymiles hardware (vs 1-2 seconds for SolarEdge), which will cause Venus OS ESS regulation oscillation if not explicitly handled with per-device dead-times and priority-based sequential limiting. A secondary risk is the UI state management shift from monolithic global state to per-device context objects — this requires careful planning before any device-centric views are built. Both risks are well-understood and have clear mitigations identified in research.

## Key Findings

### Recommended Stack

The v4.0 stack requires zero new dependencies. Every capability needed — async HTTP client, JSON parsing, concurrent polling, config persistence — is already present in the installed package set. `aiohttp.ClientSession` replaces pymodbus as the transport for OpenDTU, with `aiohttp.BasicAuth` handling write authentication. All aggregation is pure Python arithmetic on dataclasses. No message broker, database, or task queue is needed for 2-5 inverters on the same LAN.

**Core technologies:**
- `aiohttp.ClientSession`: OpenDTU REST polling and limit control — already a dependency, async-native, no reason to add httpx
- `asyncio.gather`: parallel polling of all device plugins — same pattern as existing code, handles per-device exceptions without killing others
- Python dataclasses: DeviceEntry, VirtualInverterConfig, PowerLimitConfig, AppContext — sufficient for config validation without pydantic's 5MB overhead
- Extended YAML config: backward-compatible `type` field on InverterEntry — existing migration path handles v3.1 -> v4.0 transparently with a default of `"solaredge"`
- Vanilla JS with per-device state map: zero-dependency frontend extended with `_devices[id]` context objects — preserves the no-build-tooling constraint

### Expected Features

**Must have (table stakes) — without these v4.0 has no value:**
- OpenDTU plugin (poll + display) — foundation; without Hoymiles data there is nothing to aggregate
- Virtual inverter aggregation — the core value proposition; Venus OS sees one Fronius, receives sum of all sources
- Aggregated Model 120 nameplate — Venus OS needs correct WRtg for ESS calculations; wrong value = wrong power limiting
- Device sidebar navigation — structural prerequisite; current 3-tab nav cannot accommodate N devices
- Per-inverter dashboard — users must see individual source performance; reuses existing gauge/sparkline/phase components
- Aggregate dashboard (Virtual PV view) — the home view; combined power, total yield, all-source health at a glance
- Per-inverter config — each source needs editable connection settings with type-specific fields
- Source health indicators — without per-source status dots users cannot diagnose which source is down
- OpenDTU power limit control — Venus OS ESS sends limit commands; if Hoymiles cannot be limited it defeats zero-export setups

**Should have (differentiators that make v4.0 feel complete):**
- Priority-based power limiting — throttle cheapest/least-critical inverter first; without it proxy splits equally which is rarely correct
- Per-inverter exclusion from limiting — boolean flag, large value for mixed setups
- Venus OS as own device section — consolidates scattered Venus OS info into coherent sidebar view
- Custom virtual inverter name — user names the aggregate device shown to Venus OS
- Source contribution breakdown — visual proof multi-source is working (stacked bar or percentage labels)

**Defer to v4.1+:**
- Central "+" device management wizard — users can add via config page initially
- Per-inverter register viewer for OpenDTU — SolarEdge viewer exists; OpenDTU equivalent can follow
- OpenDTU auto-discovery via HTTP scan — users typically know their OpenDTU IP
- Graceful degradation with last-known-value decay — initially zero-fill offline sources with error state shown

### Architecture Approach

The target architecture introduces an AggregationLayer as the central new abstraction. Each physical inverter runs its own asyncio poll task managed by a DeviceRegistry. When any device poll completes, the AggregationLayer recalculates the aggregated register set and writes it to the single Modbus-facing RegisterCache. Venus OS reads from this aggregated cache unchanged. Power limit writes from Venus OS are intercepted by a new PowerLimitDistributor that applies priority ordering and dead-times before calling each device plugin's `write_power_limit()`. The frontend shifts from fixed tabs to dynamic device-centric navigation with per-device state objects in `_devices[id]`.

**Major components:**
1. `device_registry.py` (NEW) — manages DeviceEntry lifecycle: plugin creation, poll task start/stop, per-device connection managers and dashboard collectors
2. `plugins/opendtu.py` (NEW) — implements InverterPlugin ABC over HTTP REST; synthesizes SunSpec uint16 registers from OpenDTU JSON so the existing DashboardCollector works unchanged
3. `aggregation.py` (NEW) — sums active device outputs in physical units (W, A, V, Wh), re-encodes with fixed scale factors, writes to RegisterCache; triggered event-driven after each device poll
4. `power_distributor.py` (NEW) — receives Venus OS limit commands, distributes by priority config with per-device dead-times (30s for Hoymiles, 2s for SolarEdge)
5. `plugins/__init__.py` (NEW) — plugin factory: `create_plugin(entry: InverterEntry) -> InverterPlugin` dispatches on `entry.type`
6. Modified `proxy.py` — decoupled from single plugin; accepts AggregationLayer + PowerLimitDistributor; `_poll_loop` extracted to DeviceRegistry
7. Modified `webapp.py` — device CRUD endpoints, per-device snapshots, multi-device WebSocket format with `devices` dict + `virtual` aggregated key
8. Modified `config.py` — adds `type` field (default `"solaredge"` for backward compat), VirtualInverterConfig, PowerLimitConfig, typed AppContext replacing flat shared_ctx dict

**Files unchanged:** `register_cache.py`, `sunspec_models.py`, `timeseries.py`, `scanner.py`, `venus_reader.py`, `connection.py`

### Critical Pitfalls

1. **Aggregating raw SunSpec registers (not physical units) produces wrong sums** — decode all values to physical units (W, A, V) before summing; re-encode with a single fixed scale factor per field; validate `abs(aggregated_power - sum(individual_powers)) < 10W`

2. **OpenDTU power limit 18-25s latency causes Venus OS ESS oscillation** — mark device as "limit pending" after each send; suppress re-sends for 30s; implement dead-time in PowerLimitDistributor; default to SolarEdge-only limiting until user opts in to Hoymiles limiting

3. **Single-plugin architecture baked into proxy.py creates race conditions when naively adding a second poller** — insert AggregationLayer between per-device pollers and the shared register cache before adding any second plugin; each device writes to its own isolated data store, never directly to the Modbus-facing cache

4. **asyncio task leaks on device add/remove** — DeviceRegistry must track all tasks per device and cancel+await them on remove; use explicit task registry, not fire-and-forget `create_task`

5. **Config migration breaks existing v3.1 installs** — `type: "solaredge"` default on InverterEntry means existing configs load without changes; add `config_version: 2` field; run migration step in `load_config()` that adds `type` to entries that lack it

6. **One OpenDTU gateway serves multiple Hoymiles serials** — create one DeviceEntry per Hoymiles serial found in `/api/livedata/status` response, not one per OpenDTU endpoint; power limit POST requires the target inverter's serial number

## Implications for Roadmap

Based on research, the architecture's own build order is the correct phase sequence. Each phase has clear prerequisites and delivers independently testable value.

### Phase 1: Config Data Model + AppContext Refactor
**Rationale:** Every subsequent phase requires the multi-device config structure. Cannot add OpenDTU or aggregation without `type` field on InverterEntry and typed AppContext replacing the flat shared_ctx dict. Config migration must be correct before any runtime changes.
**Delivers:** Backward-compatible config that loads v3.1 files correctly; typed AppContext with `devices`, `aggregator`, `venus`, `config` structure; `config_version: 2` migration path; VirtualInverterConfig and PowerLimitConfig dataclasses
**Addresses:** Table-stakes per-inverter config (data model foundation)
**Avoids:** Pitfall 5 (config migration breaks installs), Pitfall 15 (unmanageable shared_ctx dict)

### Phase 2: OpenDTU Plugin
**Rationale:** Self-contained, testable in isolation against real hardware at 192.168.3.98. Does not touch existing proxy code. All OpenDTU-specific decisions (poll interval, auth, serial-per-device, limit latency handling) must be locked in at the plugin level before aggregation uses it.
**Delivers:** Working `plugins/opendtu.py` that polls `/api/livedata/status` at 5s interval, synthesizes SunSpec registers, writes power limits via `/api/limit/config`; firmware version check on connect; credential masking in API/logs; `plugins/__init__.py` plugin factory
**Uses:** `aiohttp.ClientSession`, `aiohttp.BasicAuth` (no new dependencies)
**Avoids:** Pitfall 2 (limit latency — per-device dead-time designed in from start), Pitfall 7 (ESP32 overload — 5s not 1s poll), Pitfall 10 (plaintext credentials masked), Pitfall 13 (firmware version compat via defensive parsing), Pitfall 16 (one-gateway-to-many-serials via per-serial DeviceEntry)

### Phase 3: DeviceRegistry + Per-Device Poll Loops
**Rationale:** Foundation for multi-device operation. Must exist before aggregation or REST API changes. Extracts poll loop from proxy.py into per-device asyncio tasks with proper lifecycle management.
**Delivers:** `device_registry.py` with add/remove/enable/disable; per-device `ConnectionManager`, `DashboardCollector`, poll tasks; explicit task cancellation on remove; serial-number-based device identity
**Addresses:** Device sidebar navigation (structural backend support)
**Avoids:** Pitfall 8 (asyncio task leaks — explicit task registry), Pitfall 14 (UUID vs serial-number device identity)

### Phase 4: AggregationLayer + Proxy Decoupling
**Rationale:** This is the core architectural change. Decouples proxy.py from a single plugin and wires DeviceRegistry outputs through the AggregationLayer into the shared RegisterCache. After this phase, Venus OS sees the virtual aggregated inverter.
**Delivers:** `aggregation.py` summing in physical units with fixed output scale factors; `proxy.py` refactored to accept AggregationLayer; aggregated Model 120 nameplate with combined WRtg; per-device night mode (global night = all sources sleeping); end-to-end: OpenDTU + SolarEdge -> aggregated -> Venus OS
**Avoids:** Pitfall 1 (single-plugin architecture), Pitfall 3 (wrong scale factor sums — aggregate in physical units), Pitfall 11 (partial aggregation on source loss — never mark aggregated stale unless all sources stale)

### Phase 5: PowerLimitDistributor
**Rationale:** Power limiting is the most safety-critical feature. Must work correctly before being exposed in UI. StalenessAwareSlaveContext write interception must route to the distributor, not any individual plugin.
**Delivers:** `power_distributor.py` with priority-based sequential distribution; per-device dead-times (30s Hoymiles, 2s SolarEdge); feedback loop prevention via rate-limiting; power limit priority/exclusion config YAML section
**Addresses:** Table-stakes OpenDTU power limit control; differentiator priority-based limiting; per-inverter exclusion from limiting
**Avoids:** Pitfall 6 (Venus OS ESS feedback oscillation — dead-time + priority order), Pitfall 2 cascades (limit latency handled via pending state)

### Phase 6: Device-Centric REST API
**Rationale:** Backend API must exist before frontend can render device views. All device CRUD, per-device snapshots, and multi-device WebSocket format defined here.
**Delivers:** New webapp endpoints (`/api/devices`, `/api/devices/{id}`, `/api/devices/{id}/config`, `/api/virtual`, `/api/power-limit/config`); multi-device WebSocket snapshot format with `devices` dict + `virtual` key; per-device register viewer data endpoint
**Implements:** Architecture component: Modified `webapp.py`

### Phase 7: Device-Centric Frontend
**Rationale:** Pure frontend work, depends on all backend phases being complete. Dynamic navigation, per-device state management, and virtual PV view all built here.
**Delivers:** Dynamic sidebar generated from `/api/devices`; per-device dashboard pages reusing existing gauge/sparkline/phase components; aggregate Virtual PV view; source contribution breakdown; power limit priority config UI (drag-reorder list); per-device health status dots in sidebar
**Addresses:** All remaining table-stakes and differentiator UI features
**Avoids:** Pitfall 9 (global state breaks multi-device navigation — use `_devices[id]` objects, hide/show not destroy/recreate), Pitfall 12 (WebSocket payload grows linearly — delta broadcasting, sparkline history sent once on connect)

### Phase Ordering Rationale

- Config data model is Phase 1 because every other phase extends InverterEntry or AppContext; attempting any other phase without it requires reverting later
- OpenDTU plugin is Phase 2 because it is fully isolated and can be validated against real hardware (192.168.3.98) without touching any running code
- DeviceRegistry is Phase 3 because AggregationLayer needs it to iterate active devices; poll loop extraction also unblocks proxy.py decoupling
- AggregationLayer is Phase 4 (not earlier) because it requires both the plugin and the registry to be stable; this is the highest-risk phase and needs clean inputs
- PowerLimitDistributor is Phase 5 because proxy decoupling must be complete before write interception works correctly in the multi-device context
- REST API (Phase 6) precedes Frontend (Phase 7) because the frontend discovers device list dynamically from the API and makes no hardcoded assumptions about device count or types
- This ordering means at no point does a second poller exist without the aggregation boundary already in place — the primary architectural pitfall is structurally prevented

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (AggregationLayer):** Scale factor encoding math and the partial-aggregation staleness strategy need concrete implementation decisions before coding; specifically the "last-known-value with 60s decay" vs "zero-fill immediately" tradeoff for offline sources
- **Phase 5 (PowerLimitDistributor):** Dead-time values (30s for Hoymiles) are best estimates from GitHub issues — validate against real hardware before hardcoding; the Venus OS EDPC refresh rate (currently ~5s) must be confirmed so dead-times are correctly sized relative to it
- **Phase 7 (Frontend):** WebSocket delta protocol design (what triggers a broadcast, what fields are included, how sparkline history is served on connect) should be spec'd before implementation; the hide/show vs destroy/recreate navigation decision affects the entire DOM structure

Phases with standard patterns (skip research-phase):
- **Phase 1 (Config):** Dataclass extension with defaults is standard Python; config migration is already done once in this codebase (inverter: -> inverters:); no ambiguity
- **Phase 2 (OpenDTU Plugin):** Official API docs are complete and HIGH confidence; the InverterPlugin ABC pattern is established with SolarEdge as the reference implementation
- **Phase 3 (DeviceRegistry):** asyncio task lifecycle is well-documented; the per-device poll loop already exists in proxy.py and needs extraction, not reinvention
- **Phase 6 (REST API):** aiohttp route patterns are well-established throughout the existing webapp.py

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies confirmed; all APIs in installed packages; OpenDTU API official docs verified; no alternatives seriously compete |
| Features | HIGH | Existing codebase analyzed directly; OpenDTU API verified against official docs; Venus OS SunSpec behavior confirmed via victronenergy/dbus-fronius |
| Architecture | HIGH | Direct code analysis of all source files; target architecture derived from actual coupling points identified in code; build order is dependency-driven not speculative |
| Pitfalls | HIGH | Critical pitfalls grounded in specific codebase code paths (not speculation); OpenDTU limit latency sourced from GitHub issue #571 with measured numbers |

**Overall confidence:** HIGH

### Gaps to Address

- **OpenDTU limit dead-time value:** 30s is derived from GitHub issues; measure on real Hoymiles HM-800 at 192.168.3.98 during Phase 2 testing and adjust the constant before Phase 5 implementation
- **Venus OS EDPC refresh rate:** The existing 5-second EDPC refresh loop's exact interval should be confirmed against the Venus OS side to ensure dead-time sizing prevents double-sends without being unnecessarily long
- **Two Hoymiles serials on one OpenDTU:** Research assumes two inverters (HM-400 + HM-600) but the actual serials at 192.168.3.98 must be confirmed from a live `/api/livedata/status` response during Phase 2; device count affects Phase 3 DeviceEntry design
- **WebSocket broadcast batching threshold:** The 1Hz debounce recommendation for 5+ devices is a design estimate; with only 2-3 devices actual performance may not require batching — validate during Phase 6 before adding complexity
- **SolarEdge scan exclusion during concurrent operation:** The scanner's exclusion list behavior for hosts with active connections needs a test scenario during Phase 3 to confirm no accidental disconnects when the config UI triggers discovery

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `plugin.py`, `plugins/solaredge.py`, `proxy.py`, `config.py`, `__main__.py`, `webapp.py`, `dashboard.py`, `control.py`, `connection.py`
- [OpenDTU Web API documentation](https://www.opendtu.solar/firmware/web_api/) — REST endpoints, authentication, response formats, limit_type semantics
- [aiohttp ClientSession documentation](https://docs.aiohttp.org/en/stable/client.html) — already a dependency, no new integration needed
- [SolarEdge SunSpec Technical Note](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf) — single Modbus TCP connection limit confirmed
- [OpenDTU GitHub Issue #571](https://github.com/tbnobody/OpenDTU/issues/571) — 25-90 second power limit latency on Hoymiles hardware, confirmed measurement

### Secondary (MEDIUM confidence)
- [OpenDTU GitHub Discussion #602](https://github.com/tbnobody/OpenDTU/discussions/602) — limit_type and limit_value parameter usage
- [OpenDTU GitHub Discussion #742](https://github.com/tbnobody/OpenDTU/discussions/742) — limit type 0=absolute watts, 1=relative percentage
- [OpenDTU-OnBattery Dynamic Power Limiter](https://github.com/hoylabs/OpenDTU-OnBattery/wiki/Dynamic-Power-Limiter) — priority-based power distribution strategies
- [dbus-opendtu Venus OS integration](https://github.com/henne49/dbus-opendtu) — alternative approach confirms OpenDTU API patterns
- [SolarEdge single connection GitHub issue](https://github.com/binsentsu/home-assistant-solaredge-modbus/issues/82) — confirms single-client limitation in practice
- [victronenergy/dbus-fronius](https://github.com/victronenergy/dbus-fronius) — Venus OS Fronius driver; SunSpec power limiting via Model 123/704

### Tertiary (LOW confidence — needs validation)
- [OpenDTU GitHub: API breaking changes](https://github.com/tbnobody/OpenDTU) — changelog analysis; exact version compatibility ranges need validation against the target firmware version running at 192.168.3.98

---
*Research completed: 2026-03-20*
*Ready for roadmap: yes*
