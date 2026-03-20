# Phase 22: Device Registry & Aggregation - Research

**Researched:** 2026-03-20
**Domain:** Multi-device asyncio lifecycle management + SunSpec register aggregation
**Confidence:** HIGH

## Summary

Phase 22 transforms the proxy from a single-plugin architecture to a multi-device system. The core challenge is twofold: (1) DeviceRegistry must manage N independent poll loops as asyncio tasks with clean lifecycle (start/stop/enable/disable), and (2) AggregationLayer must sum physical values from heterogeneous plugins into one consistent SunSpec register set for Venus OS.

The existing codebase provides strong foundations: `AppContext.devices` dict, `DeviceState` dataclass, `plugin_factory()`, `ConnectionManager` with exponential backoff, and `DashboardCollector` are all ready. The main work is extracting `_poll_loop` from `proxy.py` into per-device tasks managed by DeviceRegistry, building the aggregation math, and rewiring `run_proxy()` + `__main__.py` to use the new components.

**Primary recommendation:** Build DeviceRegistry as a single new module (`device_registry.py`) that owns device lifecycle. Build AggregationLayer as a separate module (`aggregation.py`) that consumes DeviceState snapshots and feeds RegisterCache. Keep them decoupled -- DeviceRegistry does not know about SunSpec registers, AggregationLayer does not know about poll loops.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Neues Device wird sofort gestartet: Poll-Loop (asyncio Task) + DeviceState angelegt + Aggregation beruecksichtigt beim naechsten Zyklus
- Disabled = komplett raus: kein Polling, kein Beitrag zur Aggregation, keine Daten. Config-Eintrag bleibt aber erhalten
- Bei Remove/Disable: Poll-Task canceln, DeviceState cleanup, DashboardCollector fuer dieses Device entfernen. Kein asyncio Task Leak
- Exponential Backoff bei Offline-Devices: 5s -> 10s -> 30s -> 60s
- Wenn KEIN aktiver Inverter konfiguriert: Modbus-Server (Port 502) komplett stoppen, damit Venus OS den virtuellen Inverter nicht mehr im Netzwerk findet. Server wird erst wieder gestartet wenn mindestens 1 Inverter aktiv ist
- Power und Current werden summiert (Watt, Ampere)
- Energy (YieldDay, YieldTotal): Summe aller Devices
- Teilausfall: erreichbare Inverter summieren, offline-Inverter ignorieren (sofort, kein Caching des letzten Werts)
- Aggregierte Werte werden in SunSpec-Register konvertiert mit konsistenten Scale Factors
- Kein Fehler/Stale bei Teilausfall -- solange mindestens 1 Inverter online
- Config-Abschnitt: `virtual_inverter: name: "Meine PV-Anlage"`, Default: "Fronius PV Inverter Proxy"
- Venus OS sieht: Manufacturer="Fronius", Model=user-definierter Name
- Rated Power (WRtg Model 120): automatisch Summe aller aktiven Inverter rated_powers
- Modbus-Server bleibt auf Port 502 mit Unit ID 126
- AggregationLayer -> RegisterCache statt single Plugin
- _poll_loop in proxy.py wird durch DeviceRegistry Poll-Management ersetzt
- proxy.py behaelt: Modbus Server, StalenessAwareSlaveContext, ControlState
- Neuer Flow: N Plugins -> N DeviceStates -> AggregationLayer -> RegisterCache -> Modbus Server -> Venus OS

### Claude's Discretion
- DeviceRegistry Klasse vs Modul-Level Funktionen
- Aggregation Tick-Intervall (nach jedem Poll vs periodisch)
- Wie primary_device Compat-Accessor aufgeloest wird
- Error-Handling bei fehlgeschlagener Task-Erstellung
- Ob AggregationLayer eigenes Modul oder Teil von DeviceRegistry

### Deferred Ideas (OUT OF SCOPE)
- Power limit distribution across devices -- Phase 23
- Per-device REST API endpoints -- Phase 24
- Per-device UI dashboards -- Phase 24
- Device-centric sidebar navigation -- Phase 24
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REG-01 | DeviceRegistry verwaltet N Devices mit unabhaengigen Poll-Loops (asyncio Tasks pro Device) | DeviceRegistry class design, per-device poll loop extraction from proxy.py, ConnectionManager reuse |
| REG-02 | Devices koennen zur Laufzeit hinzugefuegt, entfernt, aktiviert und deaktiviert werden ohne Restart | start_device/stop_device/enable_device/disable_device methods with proper task cancellation |
| REG-03 | Wenn ein Device deaktiviert/entfernt wird, werden alle zugehoerigen Daten sauber aufgeraeumt | Task cancellation + await, DeviceState removal, DashboardCollector cleanup, plugin.close() |
| AGG-01 | Aggregation summiert Power, Current und Energy aller aktiven Inverter in physikalischen Einheiten | AggregationLayer.recalculate() decoding from per-device SunSpec regs, summing in physical units |
| AGG-02 | Aggregierte Werte werden in SunSpec-Register konvertiert mit konsistenten Scale Factors | Fixed SF strategy: SF=0 power, SF=-1 voltage, SF=-2 current/freq -- re-encode after summing |
| AGG-03 | Bei Teilausfall liefert Aggregation weiterhin Daten der erreichbaren Geraete | Per-device staleness tracking, aggregated cache stale only if ALL devices stale |
| AGG-04 | User kann Namen des virtuellen Inverters definieren | VirtualInverterConfig dataclass, Model 1 Common registers with user name, Model 120 WRtg sum |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio (stdlib) | Python 3.11+ | Per-device poll tasks, task lifecycle | Already used throughout, TaskGroup available |
| structlog | 24.x | Structured logging with device_id context | Already used project-wide |
| pymodbus | 3.6.x | RegisterCache, ModbusTcpServer, datablock | Already used, no changes needed |
| aiohttp | 3.10.x | OpenDTU HTTP polling (via plugin) | Already a dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses (stdlib) | Python 3.11+ | VirtualInverterConfig, AggregationResult | All new data structures |
| struct (stdlib) | Python 3.11+ | int16/uint16 conversion for SunSpec encoding | Already used in sunspec_models.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual task tracking | asyncio.TaskGroup | TaskGroup propagates exceptions and auto-cancels; but DeviceRegistry needs individual task control (start/stop single devices), so manual task tracking with dict is better |
| Event-driven aggregation | Periodic timer aggregation | Event-driven (after each poll) is more responsive and simpler -- no stale window between timer ticks |

**Installation:**
No new dependencies. All libraries already installed.

## Architecture Patterns

### Recommended Project Structure
```
src/venus_os_fronius_proxy/
    device_registry.py    # NEW: DeviceRegistry class
    aggregation.py        # NEW: AggregationLayer class
    proxy.py              # MODIFIED: decoupled from single plugin
    __main__.py           # MODIFIED: orchestrates registry + aggregation
    config.py             # MODIFIED: add VirtualInverterConfig
    context.py            # MODIFIED: remove compat accessors
    dashboard.py          # UNCHANGED internally
    connection.py         # UNCHANGED
    plugins/
        __init__.py       # UNCHANGED
        solaredge.py      # UNCHANGED
        opendtu.py        # UNCHANGED
```

### Pattern 1: DeviceRegistry as Task Manager
**What:** A class that maps `device_id -> (plugin, poll_task, DeviceState)` and provides start/stop/enable/disable lifecycle methods. Each device gets its own asyncio.Task running a poll loop.
**When to use:** Always -- this is the central component.

```python
@dataclass
class ManagedDevice:
    """Internal tracking for a device managed by DeviceRegistry."""
    entry: InverterEntry
    plugin: InverterPlugin
    device_state: DeviceState
    poll_task: asyncio.Task | None = None

class DeviceRegistry:
    def __init__(self, app_ctx: AppContext, config: Config, on_poll_success: Callable):
        self._app_ctx = app_ctx
        self._config = config
        self._managed: dict[str, ManagedDevice] = {}
        self._on_poll_success = on_poll_success  # callback to trigger aggregation

    async def start_device(self, device_id: str) -> None:
        """Create plugin, DeviceState, start poll task."""
        ...

    async def stop_device(self, device_id: str) -> None:
        """Cancel poll task, close plugin, remove DeviceState."""
        ...

    async def start_all(self) -> None:
        """Start all enabled devices from config."""
        ...

    async def stop_all(self) -> None:
        """Stop all devices (shutdown)."""
        ...

    def get_active_device_states(self) -> list[DeviceState]:
        """Return DeviceStates for all currently polling devices."""
        ...
```

### Pattern 2: Per-Device Poll Loop (extracted from proxy.py)
**What:** The existing `_poll_loop` function in proxy.py is extracted into a standalone async function used by DeviceRegistry. Each device gets its own instance with its own ConnectionManager, plugin, and poll counter.
**When to use:** DeviceRegistry calls this when starting a device.

Key difference from current `_poll_loop`: instead of writing directly to the shared RegisterCache, the per-device loop stores results on `DeviceState.last_poll_data` and calls a success callback that triggers aggregation.

```python
async def _device_poll_loop(
    device_id: str,
    plugin: InverterPlugin,
    device_state: DeviceState,
    poll_interval: float,
    on_success: Callable,
    app_ctx: AppContext,
) -> None:
    """Per-device poll loop. Runs as asyncio.Task, cancelled on stop."""
    conn_mgr = device_state.conn_mgr
    while True:
        if app_ctx.polling_paused:
            await asyncio.sleep(poll_interval)
            continue
        try:
            result = await plugin.poll()
            device_state.poll_counter["total"] += 1
            if result.success:
                device_state.poll_counter["success"] += 1
                conn_mgr.on_poll_success()
                device_state.last_poll_data = {
                    "common_registers": result.common_registers,
                    "inverter_registers": result.inverter_registers,
                }
                # Collect per-device dashboard data
                if device_state.collector is not None:
                    # ... collector.collect() with per-device cache
                    pass
                await on_success(device_id)
            else:
                conn_mgr.on_poll_failure()
        except asyncio.CancelledError:
            raise  # Propagate cancellation
        except Exception:
            device_state.poll_counter["total"] += 1
            conn_mgr.on_poll_failure()
        await asyncio.sleep(conn_mgr.sleep_duration)
```

### Pattern 3: AggregationLayer with Physical-Unit Math
**What:** After any device poll succeeds, AggregationLayer reads all active DeviceState snapshots, sums physical values, and encodes back to SunSpec registers for the shared RegisterCache.
**When to use:** Called via callback from DeviceRegistry on every successful poll.

```python
class AggregationLayer:
    def __init__(self, app_ctx: AppContext, cache: RegisterCache, config: Config):
        self._app_ctx = app_ctx
        self._cache = cache
        self._config = config

    def recalculate(self) -> None:
        """Sum all active device data into aggregated SunSpec registers."""
        active_states = [
            ds for ds in self._app_ctx.devices.values()
            if ds.last_poll_data is not None
        ]
        if not active_states:
            return  # No data -- cache stays stale

        # Decode each device's registers to physical units
        totals = self._sum_physical_values(active_states)

        # Encode aggregated values back to SunSpec Model 103
        inverter_regs = self._encode_aggregated_model_103(totals)
        common_regs = self._build_virtual_common()

        # Write to shared cache (Venus OS reads this)
        self._cache.update(COMMON_CACHE_ADDR, common_regs)
        self._cache.update(INVERTER_CACHE_ADDR, inverter_regs)
```

### Pattern 4: Modbus Server Start/Stop Based on Active Devices
**What:** When zero active inverters exist, stop the Modbus TCP server so Venus OS no longer sees the virtual Fronius. Restart when a device becomes active.
**When to use:** Checked in DeviceRegistry after start_device/stop_device.

```python
# In DeviceRegistry or __main__.py orchestration:
async def _update_modbus_server_state(self):
    active_count = len(self.get_active_device_states())
    if active_count == 0 and self._modbus_server_running:
        await self._stop_modbus_server()
    elif active_count > 0 and not self._modbus_server_running:
        await self._start_modbus_server()
```

### Anti-Patterns to Avoid
- **Aggregating raw register values:** NEVER add raw uint16 values from different plugins. They have different scale factors. Always decode to physical units first, sum, then re-encode.
- **Global RegisterCache for per-device data:** The shared Modbus-facing RegisterCache is ONLY for aggregated data. Per-device raw registers live in DeviceState.last_poll_data.
- **asyncio.TaskGroup for DeviceRegistry:** TaskGroup cancels ALL tasks if one fails. DeviceRegistry needs individual task lifecycle -- use a dict of tasks instead.
- **Blocking on device operations:** start_device/stop_device must be async and non-blocking. Plugin.connect() might take seconds for SolarEdge Modbus TCP.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff | Custom retry logic | `ConnectionManager` (existing) | Already handles 5s->60s backoff, night mode, state machine |
| Plugin instantiation | if/else chains | `plugin_factory()` (existing) | Already handles solaredge/opendtu dispatch |
| SunSpec register encoding | Manual bit manipulation | `_int16_as_uint16()`, `encode_string()` (existing) | Already battle-tested in sunspec_models.py |
| Per-device dashboard collection | New collector type | `DashboardCollector` (existing) | Works unchanged -- one instance per device |
| Config persistence | Custom serialization | `save_config()` (existing) | Already handles atomic write with temp file |

**Key insight:** Phase 21 built all the per-device primitives (DeviceState, plugin_factory, ConnectionManager, DashboardCollector). Phase 22 is primarily orchestration -- wiring these together with DeviceRegistry and adding aggregation math.

## Common Pitfalls

### Pitfall 1: Task Leak on Device Disable/Remove
**What goes wrong:** Cancelling an asyncio.Task does not immediately stop it. The task must `await` a cancellation point for `CancelledError` to be raised. If the poll loop catches generic `Exception` (without re-raising `CancelledError`), the task runs forever.
**Why it happens:** Common Python pattern of `except Exception: pass` accidentally swallows `CancelledError` (which is a BaseException in Python 3.9+ but was Exception before).
**How to avoid:** In the poll loop, always have `except asyncio.CancelledError: raise` BEFORE `except Exception`. After `task.cancel()`, always `await task` to ensure cleanup completes.
**Warning signs:** `len(asyncio.all_tasks())` grows over time after device operations.

### Pitfall 2: Scale Factor Inconsistency in Aggregation
**What goes wrong:** SolarEdge plugin returns registers with SF=0 for power (watts as raw value). OpenDTU plugin returns registers with SF=0 for power but SF=-2 for current. If the aggregation layer reads raw register values without checking per-field scale factors, the decoded physical values are wrong.
**Why it happens:** Each plugin independently encodes its registers. There is no enforced consistency between plugins' SF choices.
**How to avoid:** The AggregationLayer MUST decode each device's registers using the actual SF values from those registers (not assumed values). Then sum in physical units. Then re-encode with fixed, known SFs for the aggregated output.
**Warning signs:** Aggregated power does not match sum of individual device powers shown in per-device dashboards.

### Pitfall 3: Race Condition on Aggregation During Device Add/Remove
**What goes wrong:** While AggregationLayer.recalculate() iterates `app_ctx.devices`, a concurrent device add/remove modifies the dict. This causes `RuntimeError: dictionary changed size during iteration`.
**Why it happens:** asyncio is single-threaded but cooperative. If recalculate() has no await points, it is safe. But if stop_device() removes from dict before recalculate() finishes (both called from same event loop), iteration fails.
**How to avoid:** Take a snapshot of device IDs at the start of recalculate(): `device_ids = list(self._app_ctx.devices.keys())`. Iterate the snapshot list, handle missing devices gracefully.
**Warning signs:** Occasional KeyError or RuntimeError during device configuration changes.

### Pitfall 4: Modbus Server Stop/Start Breaks Venus OS Detection
**What goes wrong:** When the last device is disabled and Modbus server stops, Venus OS loses the virtual inverter. When a device is re-enabled and the server restarts, Venus OS may not re-discover it automatically. Venus OS scans for Modbus devices on startup, not continuously.
**Why it happens:** Venus OS caches discovered Modbus TCP devices and does not re-scan unless triggered.
**How to avoid:** Consider keeping the Modbus server running but returning stale/error responses (current behavior with StalenessAwareSlaveContext) instead of stopping it entirely. This preserves the Venus OS device entry. However, the user explicitly requested server stop -- so implement it but document that Venus OS may need a manual scan to rediscover.
**Warning signs:** After disabling and re-enabling all inverters, Venus OS shows no PV inverter until restarted.

### Pitfall 5: DashboardCollector Energy Baseline Breaks with Multiple Devices
**What goes wrong:** DashboardCollector tracks `_energy_at_start` for daily energy calculation. With multiple collectors (one per device + one aggregated), the aggregated daily energy must be the sum of individual daily energies, not computed from aggregated total energy. If the aggregated collector has its own baseline, adding/removing a device mid-day causes the aggregated daily counter to jump.
**Why it happens:** The current single-device collector assumes a stable energy counter from one source.
**How to avoid:** Compute aggregated daily energy as `sum(device.collector.daily_energy_wh)` rather than tracking a separate aggregated baseline. Each per-device collector tracks its own baseline independently.
**Warning signs:** Daily energy counter jumps by a large amount when a device is added or goes online mid-day.

## Code Examples

### Decoding SunSpec Registers to Physical Values (for Aggregation)

The aggregation layer needs to decode per-device registers. The existing `DashboardCollector._decode_all()` does this but reads from a datablock. For aggregation, decode directly from register lists:

```python
def decode_model_103_to_physical(inverter_regs: list[int]) -> dict:
    """Decode Model 103 register list to physical values.

    Args:
        inverter_regs: 52 uint16 values (DID + Length + 50 data)

    Returns:
        Dict with physical values in standard units (W, A, V, Hz, Wh, C)
    """
    def _sf(idx: int) -> int:
        raw = inverter_regs[idx]
        return raw - 65536 if raw > 32767 else raw

    def _val(idx: int, sf_idx: int) -> float:
        raw = inverter_regs[idx]
        if raw in (0x8000, 0xFFFF):
            return 0.0
        return raw * (10 ** _sf(sf_idx))

    return {
        "ac_current_a": _val(2, 6),
        "ac_current_l1_a": _val(3, 6),
        "ac_current_l2_a": _val(4, 6),
        "ac_current_l3_a": _val(5, 6),
        "ac_voltage_an_v": _val(10, 13),
        "ac_power_w": _val(14, 15),
        "ac_frequency_hz": _val(16, 17),
        "energy_total_wh": ((inverter_regs[24] << 16) | inverter_regs[25]) * (10 ** _sf(26)),
        "dc_current_a": _val(27, 28),
        "dc_voltage_v": _val(29, 30),
        "dc_power_w": _val(31, 32),
        "temperature_c": _val(33, 37),
        "status_code": inverter_regs[38],
    }
```

### Encoding Aggregated Physical Values Back to SunSpec Registers

```python
def encode_aggregated_model_103(totals: dict) -> list[int]:
    """Encode aggregated physical values to 52 uint16 SunSpec Model 103 registers.

    Uses FIXED scale factors for consistency:
    - Power: SF=0 (watts as integer)
    - Current: SF=-2 (0.01A resolution)
    - Voltage: SF=-1 (0.1V resolution)
    - Frequency: SF=-2 (0.01Hz resolution)
    - Energy: SF=0 (Wh as integer)
    - Temperature: SF=-1 (0.1C resolution)
    """
    regs = [0] * 52
    regs[0] = 103  # DID
    regs[1] = 50   # Length

    # AC Current (SF=-2)
    regs[2] = int(round(totals["ac_current_a"] * 100)) & 0xFFFF
    regs[3] = int(round(totals["ac_current_l1_a"] * 100)) & 0xFFFF
    regs[4] = int(round(totals["ac_current_l2_a"] * 100)) & 0xFFFF
    regs[5] = int(round(totals["ac_current_l3_a"] * 100)) & 0xFFFF
    regs[6] = _int16_as_uint16(-2)

    # AC Voltage (SF=-1) -- average, not sum
    regs[10] = int(round(totals["ac_voltage_an_v"] * 10)) & 0xFFFF
    regs[13] = _int16_as_uint16(-1)

    # AC Power (SF=0)
    regs[14] = int(round(totals["ac_power_w"])) & 0xFFFF
    regs[15] = 0

    # AC Frequency (SF=-2) -- average, not sum
    regs[16] = int(round(totals["ac_frequency_hz"] * 100)) & 0xFFFF
    regs[17] = _int16_as_uint16(-2)

    # Energy (SF=0, Wh)
    energy_wh = int(round(totals["energy_total_wh"]))
    regs[24] = (energy_wh >> 16) & 0xFFFF
    regs[25] = energy_wh & 0xFFFF
    regs[26] = 0

    # DC Current (SF=-2)
    regs[27] = int(round(totals["dc_current_a"] * 100)) & 0xFFFF
    regs[28] = _int16_as_uint16(-2)

    # DC Voltage (SF=-1) -- power-weighted average
    regs[29] = int(round(totals["dc_voltage_v"] * 10)) & 0xFFFF
    regs[30] = _int16_as_uint16(-1)

    # DC Power (SF=0)
    regs[31] = int(round(totals["dc_power_w"])) & 0xFFFF
    regs[32] = 0

    # Temperature (SF=-1) -- max across devices
    regs[33] = int(round(totals["temperature_c"] * 10)) & 0xFFFF
    regs[37] = _int16_as_uint16(-1)

    # Status -- worst-case
    regs[38] = totals["status_code"]

    return regs
```

### Device Lifecycle: Safe Task Cancellation

```python
async def stop_device(self, device_id: str) -> None:
    managed = self._managed.pop(device_id, None)
    if managed is None:
        return

    # 1. Cancel poll task
    if managed.poll_task is not None and not managed.poll_task.done():
        managed.poll_task.cancel()
        try:
            await managed.poll_task
        except asyncio.CancelledError:
            pass

    # 2. Close plugin connection
    try:
        await managed.plugin.close()
    except Exception:
        pass

    # 3. Remove from AppContext
    self._app_ctx.devices.pop(device_id, None)

    # 4. Trigger re-aggregation (device removed from sum)
    self._on_poll_success_sync()

    log.info("device_stopped", device_id=device_id)
```

## State of the Art

| Old Approach (v3.1) | Current Approach (v4.0 Phase 22) | What Changes |
|---------------------|----------------------------------|--------------|
| Single plugin in `run_proxy()` | DeviceRegistry manages N plugins | N poll tasks instead of 1 |
| `_poll_loop` writes directly to RegisterCache | Per-device poll stores on DeviceState, aggregation writes to cache | Decoupling via aggregation layer |
| `StalenessAwareSlaveContext` holds single plugin | StalenessAwareSlaveContext references aggregated cache only | Power limit writes deferred to Phase 23 |
| `AppContext.primary_device` compat accessors | Direct access via `app_ctx.devices[id]` | Compat accessors removed |
| One `DashboardCollector` | One per device + aggregated virtual snapshot | Per-device collectors unchanged |
| Fixed WRtg = 30000 in sunspec_models.py | Dynamic WRtg = sum of active rated_powers | Updated on device add/remove |

## Discretion Decisions (Researcher Recommendations)

### DeviceRegistry: Class (not module-level functions)
**Recommendation: Use a class.** The registry has state (managed devices dict, reference to app_ctx, on_poll_success callback). A class encapsulates this naturally. Module-level functions would require global state or passing context everywhere.

### Aggregation Trigger: After each poll (event-driven)
**Recommendation: Event-driven, triggered after each successful device poll.** This is simpler than a periodic timer and more responsive. With 1-5 devices at 1-5s poll intervals, recalculate() runs at most 5 times per second -- negligible CPU cost. No debounce needed at this scale.

### AggregationLayer: Separate module
**Recommendation: Separate module (`aggregation.py`).** The aggregation logic (decode N register sets, sum physical values, re-encode) is ~150 lines with clear single responsibility. Keeping it separate from DeviceRegistry maintains separation of concerns -- registry manages lifecycle, aggregation manages math.

### Voltage/Frequency Aggregation Strategy
**Recommendation: Simple average across active devices.** For the user's setup (1x SE30K + 2x Hoymiles), voltage and frequency are essentially identical (same grid). Simple average is correct and simple. Power-weighted average adds complexity for zero benefit in a single-grid installation.

### primary_device Compat Accessors
**Recommendation: Remove them in this phase.** The compat accessors in `context.py` (lines 54-89) exist for "Phase 21 single-device compat". Phase 22 replaces single-device operation with multi-device. All consumers (`__main__.py`, `proxy.py`, `webapp.py`) will be updated to use DeviceRegistry directly. Keeping dead compat code creates confusion.

## Open Questions

1. **Power limit forwarding during Phase 22**
   - What we know: `StalenessAwareSlaveContext._handle_control_write()` calls `self._plugin.write_power_limit()` on a single plugin
   - What's unclear: Phase 23 handles proper distribution, but Phase 22 needs the proxy to still work for Venus OS power limiting
   - Recommendation: Keep forwarding to the "primary" device (first active device) as a transitional measure. Phase 23 replaces this with PowerLimitDistributor

2. **WebSocket snapshot format change**
   - What we know: Current broadcast sends single-device snapshot format
   - What's unclear: Phase 24 handles new per-device snapshot format
   - Recommendation: In Phase 22, broadcast the aggregated snapshot in the SAME format as v3.1 (single inverter). This preserves frontend compatibility without changes. Add `device_count` field for future use

3. **Modbus server restart reliability**
   - What we know: User wants server to stop when 0 active inverters
   - What's unclear: Whether ModbusTcpServer.serve_forever() can be cleanly stopped and a new instance started on the same port
   - Recommendation: Test this during implementation. If port reuse fails, fall back to keeping server running but returning stale errors

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python3 -m pytest tests/ -x -q` |
| Full suite command | `python3 -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REG-01 | DeviceRegistry starts N devices with independent poll tasks | unit | `python3 -m pytest tests/test_device_registry.py::test_start_multiple_devices -x` | Wave 0 |
| REG-01 | Each device has its own ConnectionManager and poll counter | unit | `python3 -m pytest tests/test_device_registry.py::test_per_device_state -x` | Wave 0 |
| REG-02 | start_device creates plugin, DeviceState, starts poll task | unit | `python3 -m pytest tests/test_device_registry.py::test_start_device -x` | Wave 0 |
| REG-02 | stop_device cancels task and cleans up | unit | `python3 -m pytest tests/test_device_registry.py::test_stop_device -x` | Wave 0 |
| REG-02 | enable/disable at runtime without restart | unit | `python3 -m pytest tests/test_device_registry.py::test_enable_disable -x` | Wave 0 |
| REG-03 | Disabled device has no poll task, no DeviceState in app_ctx | unit | `python3 -m pytest tests/test_device_registry.py::test_disable_cleanup -x` | Wave 0 |
| REG-03 | No asyncio task leak after repeated start/stop cycles | unit | `python3 -m pytest tests/test_device_registry.py::test_no_task_leak -x` | Wave 0 |
| AGG-01 | Power and current summed correctly across devices | unit | `python3 -m pytest tests/test_aggregation.py::test_sum_power_current -x` | Wave 0 |
| AGG-01 | Energy summed correctly | unit | `python3 -m pytest tests/test_aggregation.py::test_sum_energy -x` | Wave 0 |
| AGG-02 | Aggregated registers have consistent SFs | unit | `python3 -m pytest tests/test_aggregation.py::test_consistent_scale_factors -x` | Wave 0 |
| AGG-02 | Decoded aggregated values match sum of individual decoded values | unit | `python3 -m pytest tests/test_aggregation.py::test_roundtrip_accuracy -x` | Wave 0 |
| AGG-03 | Partial failure: only reachable devices contribute | unit | `python3 -m pytest tests/test_aggregation.py::test_partial_failure -x` | Wave 0 |
| AGG-03 | All devices offline: cache stays stale | unit | `python3 -m pytest tests/test_aggregation.py::test_all_offline_stale -x` | Wave 0 |
| AGG-04 | Virtual inverter name in Common Model registers | unit | `python3 -m pytest tests/test_aggregation.py::test_virtual_name -x` | Wave 0 |
| AGG-04 | WRtg = sum of rated powers | unit | `python3 -m pytest tests/test_aggregation.py::test_wrtg_sum -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/ -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_device_registry.py` -- covers REG-01, REG-02, REG-03
- [ ] `tests/test_aggregation.py` -- covers AGG-01, AGG-02, AGG-03, AGG-04

## Sources

### Primary (HIGH confidence)
- Direct code analysis of `proxy.py`, `context.py`, `config.py`, `__main__.py`, `plugins/__init__.py`, `plugins/opendtu.py`, `dashboard.py`, `connection.py`, `register_cache.py`, `sunspec_models.py` -- all current source files read and analyzed
- `.planning/research/ARCHITECTURE.md` -- milestone architecture design
- `.planning/research/PITFALLS.md` -- 16 documented pitfalls with mitigations
- `.planning/phases/21-data-model-opendtu-plugin/21-CONTEXT.md` -- Phase 21 decisions and outputs

### Secondary (MEDIUM confidence)
- `.planning/phases/22-device-registry-aggregation/22-CONTEXT.md` -- User decisions for Phase 22

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all existing libraries
- Architecture: HIGH -- based on direct code analysis of all integration points
- Pitfalls: HIGH -- based on PITFALLS.md research + code analysis of specific failure modes
- Aggregation math: HIGH -- SunSpec register format well understood from existing codebase

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain, no external dependency changes expected)
