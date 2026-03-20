# Architecture: Multi-Source Virtual Inverter (v4.0)

**Domain:** Multi-source PV aggregation proxy with device-centric UI
**Researched:** 2026-03-20
**Confidence:** HIGH (based on direct code analysis + OpenDTU API docs)

## Current Architecture (v3.1)

```
__main__.py
    |
    +-- SolarEdgePlugin (single instance)
    |       |
    +-- run_proxy(plugin, shared_ctx)
    |       |
    |   +-- _poll_loop(plugin, cache, conn_mgr, ...)
    |   |       polls plugin.poll() -> cache.update() -> DashboardCollector.collect()
    |   |       -> WebSocket broadcast
    |   |
    |   +-- ModbusTcpServer(StalenessAwareSlaveContext)
    |           reads from RegisterCache (single datablock)
    |           intercepts Model 123 writes -> plugin.write_power_limit()
    |
    +-- create_webapp(shared_ctx, config, config_path, plugin)
    |       REST API + WebSocket + static files
    |
    +-- venus_mqtt_loop(shared_ctx, host, port, portal_id)
            MQTT subscriber for Venus OS ESS data
```

**Key coupling points that must change:**

1. **Single plugin assumption:** `__main__.py` creates one `SolarEdgePlugin`, passes it to `run_proxy()` and `create_webapp()`. No concept of multiple concurrent plugins.
2. **Single RegisterCache + datablock:** `run_proxy()` builds one 177-register datablock (40000-40176). The cache addresses are hardcoded constants (`COMMON_CACHE_ADDR = 40003`, `INVERTER_CACHE_ADDR = 40070`).
3. **Single DashboardCollector:** One collector tied to one plugin's poll results. Snapshot format assumes one inverter.
4. **Tight proxy-plugin coupling:** `_poll_loop` directly calls `plugin.poll()`, `plugin.connect()`, `plugin.close()`. The `StalenessAwareSlaveContext` holds a single `plugin` reference for write forwarding.
5. **Frontend assumes single inverter:** Dashboard shows one gauge, one status, one set of phase details. Navigation has fixed pages (dashboard, config, registers).

## Target Architecture (v4.0)

```
__main__.py
    |
    +-- DeviceRegistry
    |       manages: Dict[device_id, DeviceEntry]
    |       DeviceEntry = { plugin, poll_task, conn_mgr, collector, poll_counter }
    |
    +-- AggregationLayer
    |       subscribes to all device collectors
    |       sums active inverters -> virtual PV output
    |       writes aggregated values to RegisterCache (Modbus datablock)
    |
    +-- run_proxy(aggregation_layer, shared_ctx)
    |       |
    |   +-- ModbusTcpServer(StalenessAwareSlaveContext)
    |           reads aggregated RegisterCache
    |           intercepts Model 123 writes -> PowerLimitDistributor
    |
    +-- PowerLimitDistributor
    |       receives Venus OS limit commands
    |       distributes across devices by priority config
    |       calls device.plugin.write_power_limit() per device
    |
    +-- create_webapp(shared_ctx, config, config_path, device_registry)
    |       REST API: /api/devices, /api/devices/{id}/dashboard, etc.
    |       WebSocket: per-device + aggregated snapshots
    |
    +-- venus_mqtt_loop(shared_ctx, ...)
            unchanged
```

## Component Design

### 1. DeviceRegistry (NEW: `device_registry.py`)

Central manager for all inverter devices. Each device gets its own poll loop, connection manager, and dashboard collector running as independent asyncio tasks.

```python
@dataclass
class DeviceEntry:
    id: str                         # from InverterEntry.id (12-char hex)
    config: InverterEntry           # host, port, unit_id, enabled, ...
    device_type: str                # "solaredge" | "opendtu"
    plugin: InverterPlugin          # brand-specific plugin instance
    poll_task: asyncio.Task | None  # background poll loop
    conn_mgr: ConnectionManager     # per-device reconnection state
    collector: DashboardCollector   # per-device data collection
    poll_counter: dict              # {"success": 0, "total": 0}
    enabled: bool                   # runtime enable/disable
```

**Responsibilities:**
- Create/destroy plugin instances based on config
- Start/stop per-device poll loops as asyncio tasks
- Provide device snapshots to AggregationLayer and webapp
- Handle add/remove/enable/disable lifecycle
- Expose `get_device(id)`, `get_all_devices()`, `get_active_devices()`

**Why a new module:** The DeviceRegistry crosses the boundary between config, plugin lifecycle, and polling. Stuffing it into `__main__.py` or `proxy.py` would make either file too complex. It deserves its own module with clear API.

### 2. OpenDTU Plugin (NEW: `plugins/opendtu.py`)

Implements `InverterPlugin` ABC for Hoymiles micro-inverters via OpenDTU REST API.

**API endpoints used:**
- `GET /api/livedata/status?inv={serial}` -- power, voltage, current, yield, temperature
- `GET /api/limit/status` -- current power limit percentage
- `POST /api/limit/config` -- set power limit (with Basic Auth)

**Key differences from SolarEdge plugin:**

| Aspect | SolarEdge | OpenDTU |
|--------|-----------|---------|
| Protocol | Modbus TCP (pymodbus) | HTTP REST (aiohttp client) |
| Data format | Raw uint16 registers | JSON with physical units |
| Power limit | EDPC registers (61762, 61441) | REST POST with limit_type |
| Connection | Persistent TCP socket | Stateless HTTP per-poll |
| Multi-inverter | One unit_id per connection | Multiple serials per OpenDTU |
| Rated power | Hardcoded from datasheet | `max_power` from `/api/limit/status` |

**PollResult translation:** OpenDTU returns JSON with physical values (watts, volts, amps). The plugin must convert these back to SunSpec uint16 register format with scale factors so the existing `DashboardCollector._decode_all()` works unchanged.

```python
class OpenDTUPlugin(InverterPlugin):
    def __init__(self, host: str, serial: str, auth: tuple[str, str] = ("admin", "openDTU42")):
        self.host = host
        self.serial = serial
        self._auth = aiohttp.BasicAuth(*auth)
        self._session: aiohttp.ClientSession | None = None
        self._max_power_w: float = 0  # from limit/status

    async def poll(self) -> PollResult:
        # GET /api/livedata/status?inv={serial}
        # Convert JSON -> common_registers + inverter_registers
        ...

    async def write_power_limit(self, enable: bool, limit_pct: float) -> WriteResult:
        # POST /api/limit/config
        # data={"serial": self.serial, "limit_type": 1, "limit_value": limit_pct}
        ...
```

**InverterPlugin ABC change needed:** The current `PollResult` returns raw `common_registers` and `inverter_registers` (SunSpec uint16 arrays). This format is SolarEdge-specific but actually works well as a universal intermediate format because the `DashboardCollector` already knows how to decode SunSpec Model 103 registers. The OpenDTU plugin should synthesize these registers from JSON data. This avoids changing the collector at all.

**Reconfigure semantics:** For OpenDTU, `reconfigure()` updates `host` and `serial`. No persistent connection to close (HTTP is stateless), but the aiohttp session should be recreated.

### 3. AggregationLayer (NEW: `aggregation.py`)

Sums all active device outputs into a single virtual PV inverter that Venus OS sees via Modbus.

**Aggregated fields (from Model 103):**
- `AC_Power` (W): sum of all devices
- `AC_Current` (A): sum of all devices per phase (L1/L2/L3)
- `AC_Energy` (Wh): sum of all devices
- `DC_Power` (W): sum of all devices
- `DC_Voltage` (V): weighted average by power (informational only)
- `DC_Current` (A): sum of all devices
- `Temperature`: max across all devices (worst-case for safety)
- `Status`: worst-case (FAULT > THROTTLED > MPPT > SLEEPING > OFF)

**Aggregated fields (from Model 120 Nameplate):**
- `WRtg` (rated power): sum of all devices' rated power

**How it works:**
```
DeviceRegistry.device_collectors
    |
    v (each collector produces a snapshot dict after poll)
AggregationLayer.recalculate()
    |
    v  synthesizes aggregated common_registers + inverter_registers
RegisterCache.update(COMMON_CACHE_ADDR, aggregated_common)
RegisterCache.update(INVERTER_CACHE_ADDR, aggregated_inverter)
    |
    v  Venus OS reads from cache via ModbusTcpServer (unchanged)
```

**Trigger:** Called after any device's poll completes. Not on a timer -- event-driven from poll success callbacks.

**Staleness:** The aggregated cache is stale if ALL active devices are stale. If at least one device is providing fresh data, the aggregated output is fresh. This prevents Venus OS from seeing the proxy as dead when one of several inverters goes offline.

### 4. PowerLimitDistributor (NEW: `power_distributor.py`)

Distributes Venus OS power limit commands across multiple physical inverters based on a configurable priority order.

**Algorithm:**
1. Venus OS writes `WMaxLimPct` (e.g., 50%) to Model 123
2. Distributor calculates absolute limit: `total_rated_W * limit_pct / 100`
3. Iterates devices in priority order (configurable)
4. Each device gets `min(its_rated_W, remaining_budget_W)`
5. Converts per-device absolute limit back to percentage of that device's rating
6. Calls `device.plugin.write_power_limit(enable, device_pct)`

**Priority config (in `config.yaml`):**
```yaml
power_limit:
  priority:
    - device_id_1   # throttled last (highest priority = most important)
    - device_id_2   # throttled first (lowest priority = least important)
  excluded:
    - device_id_3   # never throttled, always runs at 100%
```

**Why priority-based:** The user's SolarEdge SE30K (30kW) is the primary inverter. Hoymiles micro-inverters (e.g., 2x 800W) are secondary. When Venus OS limits total PV output, throttle the small inverters first before touching the big one (or vice versa -- user-configurable).

### 5. Modified: proxy.py

**Changes:**
- `run_proxy()` no longer creates a plugin or poll loop. It receives an `AggregationLayer` that provides the RegisterCache.
- `StalenessAwareSlaveContext` no longer holds a single plugin. Instead, write interceptions go to the `PowerLimitDistributor`.
- The `_poll_loop` function moves to `DeviceRegistry` (it becomes per-device, managed by the registry).
- `run_proxy()` becomes a thin wrapper: build ModbusTcpServer, serve from aggregated cache.

**Backward compatibility:** When only one device is configured (common case during migration), the aggregation layer is a passthrough -- no behavioral change.

### 6. Modified: DashboardCollector

**Per-device collectors (unchanged internally):** Each device gets its own `DashboardCollector` instance. The collector's `collect()` method works identically -- it decodes SunSpec registers from a cache/datablock, regardless of which plugin produced them.

**New aggregated snapshot:** The webapp needs both per-device and aggregated snapshots. The `AggregationLayer` produces an aggregated `DashboardCollector` snapshot for the "Virtual Inverter" view.

**Snapshot format evolution:**
```python
# v3.1 (current): single inverter snapshot
{
    "ts": ...,
    "inverter": { "ac_power_w": ..., ... },
    "inverter_name": "SolarEdge SE30K",
    "control": { ... },
    "connection": { ... },
    ...
}

# v4.0: multi-device snapshot
{
    "ts": ...,
    "devices": {
        "abc123def456": {
            "inverter": { "ac_power_w": ..., ... },
            "inverter_name": "SolarEdge SE30K",
            "device_type": "solaredge",
            "connection": { ... },
        },
        "789xyz012abc": {
            "inverter": { "ac_power_w": ..., ... },
            "inverter_name": "HM-800 via OpenDTU",
            "device_type": "opendtu",
            "connection": { ... },
        },
    },
    "virtual": {
        "inverter": { "ac_power_w": ..., ... },  # aggregated
        "inverter_name": "Virtual PV Inverter",
        "rated_power_w": 31600,  # sum
    },
    "control": { ... },   # applies to virtual/aggregated
    "venus_os": { ... },
    "venus_mqtt_connected": ...,
    ...
}
```

### 7. Modified: config.py

**New config structure:**
```yaml
inverters:
  - id: abc123def456
    type: solaredge       # NEW field
    host: 192.168.3.18
    port: 1502
    unit_id: 1
    enabled: true
    manufacturer: SolarEdge
    model: SE30K
    serial: RW00IBNM4

  - id: 789xyz012abc
    type: opendtu          # NEW field
    host: 192.168.3.98
    port: 80               # HTTP port
    unit_id: 1             # ignored for OpenDTU
    enabled: true
    manufacturer: Hoymiles
    model: HM-800
    serial: 116180123456
    # OpenDTU-specific:
    opendtu_serial: "116180123456"   # inverter serial for API calls
    opendtu_auth_user: admin
    opendtu_auth_pass: openDTU42

virtual_inverter:
  name: "PV Anlage"        # user-configurable name shown to Venus OS

power_limit:
  priority: []              # device IDs in priority order
  excluded: []              # device IDs excluded from limiting
```

**InverterEntry changes:**
- Add `type: str = "solaredge"` field (default preserves backward compatibility)
- Add `opendtu_serial: str = ""` for OpenDTU-specific config
- Add `opendtu_auth_user: str = "admin"` and `opendtu_auth_pass: str = "openDTU42"`

**New dataclasses:**
```python
@dataclass
class VirtualInverterConfig:
    name: str = "PV Anlage"

@dataclass
class PowerLimitConfig:
    priority: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
```

### 8. Modified: __main__.py

**Current:** Creates single `SolarEdgePlugin`, calls `run_proxy(plugin, ...)`.
**New:** Creates `DeviceRegistry` from config, creates `AggregationLayer`, creates `PowerLimitDistributor`, starts everything.

```python
# Pseudocode for new startup flow
device_registry = DeviceRegistry(config)
aggregation = AggregationLayer(device_registry, cache)
distributor = PowerLimitDistributor(device_registry, config.power_limit)

# Start per-device poll loops
await device_registry.start_all()

# Start proxy with aggregated cache
proxy_task = asyncio.create_task(
    run_proxy(aggregation, distributor, shared_ctx)
)

# Start webapp with device registry (not single plugin)
runner = await create_webapp(shared_ctx, config, config_path, device_registry)
```

### 9. Modified: webapp.py

**New REST endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/devices` | GET | List all devices with status |
| `/api/devices/{id}` | GET | Single device detail + snapshot |
| `/api/devices/{id}/registers` | GET | Per-device register viewer data |
| `/api/devices/{id}/config` | GET/PUT | Per-device configuration |
| `/api/devices` | POST | Add new device |
| `/api/devices/{id}` | DELETE | Remove device |
| `/api/devices/{id}/enable` | POST | Enable device |
| `/api/devices/{id}/disable` | POST | Disable device |
| `/api/virtual` | GET | Aggregated virtual inverter snapshot |
| `/api/power-limit/config` | GET/PUT | Priority order + exclusions |

**WebSocket changes:** The broadcast snapshot format changes to include `devices` dict and `virtual` aggregated data. The frontend must handle both formats during migration (check for `devices` key).

### 10. Modified: Frontend (index.html, app.js, style.css)

**Navigation model change:**
```
v3.1: Dashboard | Config | Registers   (fixed tabs)

v4.0: Virtual PV   | SE30K      | HM-800     | Venus OS | Config
      (aggregated)  (per-device)  (per-device)  (status)  (global)
```

**Device menu items:** Dynamically generated from `/api/devices`. Each device gets a nav entry with status dot (green/orange/red). Clicking a device shows its dashboard + registers.

**Virtual PV page:** Shows aggregated gauge, aggregated sparklines, combined 3-phase details. This is the "main" view equivalent to today's dashboard.

**Per-device pages:** Each shows the same dashboard layout as today but with that device's data only. Register viewer shows that device's registers.

**Config page:** Becomes device-centric. "+" button to add device (SolarEdge or OpenDTU). Each device has inline config. Power limit priority is a drag-reorder list.

## Data Flow Diagram

```
                    OpenDTU REST              SolarEdge Modbus TCP
                    192.168.3.98              192.168.3.18:1502
                         |                          |
              OpenDTUPlugin.poll()       SolarEdgePlugin.poll()
                         |                          |
                    PollResult                 PollResult
                   (synthesized                (native SunSpec
                    SunSpec regs)               registers)
                         |                          |
               DeviceRegistry: per-device poll tasks
                    |                          |
           device_collector.collect()  device_collector.collect()
                    |                          |
                    +------- both feed --------+
                              |
                     AggregationLayer.recalculate()
                              |
                    aggregated_registers -> RegisterCache -> ModbusTcpServer
                              |                                    |
                    aggregated_snapshot                     Venus OS reads
                              |                            Venus OS writes
                         WebSocket                               |
                         broadcast                    PowerLimitDistributor
                              |                     distributes to plugins
                         Browser
                    (per-device + virtual views)
```

## What Changes vs What Extends

### New Files (5)

| File | Purpose | Estimated LOC |
|------|---------|---------------|
| `device_registry.py` | Device lifecycle management | ~200 |
| `plugins/opendtu.py` | OpenDTU/Hoymiles plugin | ~180 |
| `aggregation.py` | Multi-device sum into virtual inverter | ~150 |
| `power_distributor.py` | Priority-based limit distribution | ~120 |
| `plugins/__init__.py` | Plugin factory: `create_plugin(type, config)` | ~30 |

### Modified Files (7)

| File | Change Scope | What Changes |
|------|-------------|--------------|
| `config.py` | Medium | Add `type` to InverterEntry, add VirtualInverterConfig, PowerLimitConfig |
| `proxy.py` | Large | Decouple from single plugin, accept AggregationLayer + PowerLimitDistributor |
| `__main__.py` | Large | Orchestrate DeviceRegistry, AggregationLayer, PowerLimitDistributor |
| `webapp.py` | Large | Device CRUD endpoints, per-device register viewer, multi-device WebSocket |
| `plugin.py` | Small | Add optional `device_type` property, maybe `rated_power_w` property |
| `dashboard.py` | Small | DashboardCollector unchanged internally; snapshot wrapper adds `devices` dict |
| `connection.py` | None | Already generic, works per-device as-is |

### Unchanged Files (5)

| File | Why Unchanged |
|------|---------------|
| `register_cache.py` | Already generic -- wraps any datablock |
| `sunspec_models.py` | Static SunSpec constants -- unchanged |
| `timeseries.py` | Already generic -- TimeSeriesBuffer per metric |
| `scanner.py` | Scans for SunSpec devices -- still useful for SolarEdge discovery |
| `venus_reader.py` | MQTT to Venus OS -- independent of inverter count |

## Patterns to Follow

### Pattern: Plugin Factory
```python
# plugins/__init__.py
def create_plugin(entry: InverterEntry) -> InverterPlugin:
    if entry.type == "solaredge":
        return SolarEdgePlugin(host=entry.host, port=entry.port, unit_id=entry.unit_id)
    elif entry.type == "opendtu":
        return OpenDTUPlugin(
            host=entry.host,
            serial=entry.opendtu_serial,
            auth=(entry.opendtu_auth_user, entry.opendtu_auth_pass),
        )
    raise ValueError(f"Unknown device type: {entry.type}")
```

### Pattern: Per-Device Poll Loop (extracted from proxy.py)
Each device runs its own `_poll_loop` as an asyncio task. The DeviceRegistry manages task lifecycle. When a device is disabled, its poll task is cancelled. When re-enabled, a new task starts.

The existing `_poll_loop` in proxy.py is almost reusable as-is. Extract it to DeviceRegistry or a shared module, parametrize to callback on success instead of directly updating the aggregated cache.

### Pattern: Event-Driven Aggregation
```python
# After each device poll succeeds:
async def on_device_poll_success(device_id: str):
    device = self.registry.get_device(device_id)
    device.collector.collect(device.cache, ...)

    # Recalculate aggregated output
    self.aggregation.recalculate()

    # Broadcast to WebSocket
    snapshot = self.build_multi_device_snapshot()
    await broadcast_to_clients(self.app, snapshot)
```

### Pattern: Backward-Compatible Snapshot
During migration, support both old format (single inverter) and new format (multi-device). Frontend checks:
```javascript
if (snapshot.devices) {
    // v4.0 multi-device format
    renderMultiDevice(snapshot);
} else {
    // v3.1 legacy format
    renderSingleDevice(snapshot);
}
```

### Pattern: shared_ctx as State Bus (continued)
All device state flows through shared_ctx. The DeviceRegistry is stored at `shared_ctx["device_registry"]`.

## Anti-Patterns to Avoid

### Anti-Pattern: Global RegisterCache for Per-Device Data
Do NOT put per-device raw registers into the shared Modbus-facing RegisterCache. That cache is only for the aggregated virtual inverter that Venus OS reads. Per-device data stays in per-device collectors and is served via REST/WebSocket only.

### Anti-Pattern: Thread-per-Plugin
Do NOT use threads for parallel polling. All plugins use async I/O (pymodbus is async, aiohttp client is async). asyncio tasks are the correct concurrency primitive. Keep the existing single-process, single-thread, async-everything model.

### Anti-Pattern: Abstract Base Class Proliferation
Do NOT create abstract classes for AggregationLayer, PowerLimitDistributor, DeviceRegistry. They each have exactly one implementation. Use concrete classes. The InverterPlugin ABC is correct because it has multiple implementations (SolarEdge, OpenDTU).

### Anti-Pattern: Per-Device Modbus Server
Do NOT give each device its own Modbus port. Venus OS connects to one proxy on port 502 and sees one virtual inverter. That is the whole point.

### Anti-Pattern: OpenDTU WebSocket Instead of REST Polling
OpenDTU supports WebSocket for live data, but the polling approach is simpler, more resilient, and consistent with how the SolarEdge plugin works. REST polling at 1Hz is fine for micro-inverters producing < 1kW.

## Build Order (Dependency-Driven)

### Phase 1: OpenDTU Plugin
**What:** Implement `plugins/opendtu.py` conforming to `InverterPlugin` ABC.
**Why first:** Self-contained, testable in isolation. Does not touch existing code. Can be validated against real OpenDTU at 192.168.3.98.
**Dependencies:** None. Only needs `plugin.py` ABC (unchanged).
**Deliverable:** Working plugin that can poll OpenDTU and return PollResult, write power limits.

### Phase 2: DeviceRegistry + Plugin Factory
**What:** `device_registry.py` and `plugins/__init__.py`. Extract poll loop from proxy.py into reusable per-device function.
**Why second:** Foundation for multi-device operation. Must exist before aggregation or webapp changes.
**Dependencies:** Phase 1 (OpenDTU plugin exists to instantiate).
**Deliverable:** Registry that creates plugins from config, starts/stops poll tasks.

### Phase 3: AggregationLayer
**What:** `aggregation.py` that sums device outputs into RegisterCache.
**Why third:** Needed before proxy.py can serve aggregated data to Venus OS.
**Dependencies:** Phase 2 (DeviceRegistry provides device collectors).
**Deliverable:** Venus OS sees aggregated power from all devices.

### Phase 4: Proxy Decoupling
**What:** Modify `proxy.py` to use AggregationLayer instead of single plugin. Modify `__main__.py` orchestration.
**Why fourth:** Integrates Phases 2-3 into the running system. After this, Venus OS sees the virtual inverter.
**Dependencies:** Phases 2-3.
**Deliverable:** End-to-end: OpenDTU + SolarEdge -> aggregated -> Venus OS.

### Phase 5: PowerLimitDistributor
**What:** `power_distributor.py` + modify `StalenessAwareSlaveContext` to route writes to distributor.
**Why fifth:** Power limiting is the most complex feature. Must work correctly before exposing in UI.
**Dependencies:** Phase 4 (proxy decoupled from single plugin).
**Deliverable:** Venus OS power limit distributed across devices by priority.

### Phase 6: Device-Centric REST API
**What:** New webapp endpoints for device CRUD, per-device snapshots, multi-device WebSocket format.
**Why sixth:** Backend API must exist before frontend can render device views.
**Dependencies:** Phase 2 (DeviceRegistry available for CRUD).
**Deliverable:** Full REST API for device management.

### Phase 7: Device-Centric Frontend
**What:** Dynamic navigation, per-device pages, virtual PV page, priority config UI.
**Why last:** Pure frontend, depends on all backend phases.
**Dependencies:** Phase 6 (REST API available).
**Deliverable:** Full device-centric UI.

## Scalability Notes

| Concern | 1 device (current) | 3-5 devices (v4.0 target) | 10+ devices |
|---------|--------------------|-----------------------------|-------------|
| Polling | 1 task, 1Hz | 3-5 tasks, 1Hz each | Fine, all async |
| Memory | ~1.3MB ring buffers | ~4-7MB | Acceptable |
| WebSocket | 1 snapshot/s | 3-5 snapshots/s (or batched) | Batch to 1 combined/s |
| Aggregation | Passthrough | Sum on each poll (~0.1ms) | Fine |
| Modbus serving | 1 datablock | 1 datablock (aggregated) | Fine |

**WebSocket optimization for 5+ devices:** Instead of broadcasting after every device poll (up to 5x/second), batch: recalculate aggregation after each poll but only broadcast the combined snapshot at 1Hz max. Use a debounce timer.

## Sources

- Direct code analysis of all source files in repository (HIGH confidence)
- [OpenDTU Web API documentation](https://www.opendtu.solar/firmware/web_api/) (HIGH confidence)
- [OpenDTU limit config discussion](https://github.com/tbnobody/OpenDTU/discussions/602) (MEDIUM confidence)
- [OpenDTU GitHub repository](https://github.com/tbnobody/OpenDTU) (HIGH confidence)
- Existing architecture decisions in PROJECT.md (HIGH confidence)
