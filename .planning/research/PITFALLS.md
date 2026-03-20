# Domain Pitfalls: Multi-Source Virtual Inverter (v4.0)

**Domain:** Multi-source PV aggregation, OpenDTU integration, device-centric management, coordinated power limiting
**Researched:** 2026-03-20
**Applies to:** v4.0 milestone (adding OpenDTU/Hoymiles, virtual inverter aggregation, device-centric UI to existing single-inverter proxy)

## Critical Pitfalls

Mistakes that cause data corruption, broken Venus OS integration, or require architectural rewrites.

### Pitfall 1: Single-Plugin Architecture Baked Into proxy.py

**What goes wrong:** The entire `proxy.py` module assumes a single `InverterPlugin` instance. `run_proxy()` takes one plugin, creates one `StalenessAwareSlaveContext` with one plugin reference, runs one `_poll_loop`. The control write path (`async_setValues`) forwards power limits to `self._plugin` (singular). Adding a second inverter source (OpenDTU) requires aggregating data from multiple plugins into one Modbus register set, but the current architecture has no aggregation layer -- the poll loop writes directly from plugin output to the register cache.

**Why it happens:** The v1.0 design correctly solved the single-inverter problem. The `InverterPlugin` ABC was designed for brand abstraction (different protocols to same register output), not for concurrent multi-source aggregation.

**Consequences:**
- Naively adding a second poll loop creates race conditions on `cache.update()` -- two pollers writing to the same register addresses
- Venus OS sees inconsistent data: one poll cycle writes SolarEdge power, next overwrites with OpenDTU power instead of sum
- Power limit writes go to only one plugin -- the other inverter is uncontrolled
- Night mode state machine breaks: SolarEdge sleeping + OpenDTU producing should NOT trigger night mode

**Prevention:**
- Insert an **aggregation layer** between individual plugin pollers and the register cache. Each plugin writes to its own per-device data store. A separate aggregation step sums power/current/energy values and writes the combined result to the Modbus register cache.
- The aggregation step runs after ANY individual poller updates, with a small debounce (e.g., 200ms) to coalesce near-simultaneous updates.
- `StalenessAwareSlaveContext` should reference the aggregator, not any individual plugin.
- Power limit writes from Venus OS go to the aggregator, which distributes to individual plugins according to the limiting strategy.
- Night mode should be per-device, not global. The aggregated state is "night" only when ALL devices are sleeping.

**Detection:** If Venus OS shows power values that oscillate between individual inverter outputs rather than their sum, the aggregation layer is missing or broken.

**Phase:** Virtual Inverter Aggregation phase. This is the foundational architecture change -- must be designed before OpenDTU plugin or device-centric UI.

---

### Pitfall 2: OpenDTU Power Limit Has 18-25 Second Latency

**What goes wrong:** Unlike SolarEdge where Modbus TCP register writes take effect within 1-2 seconds, Hoymiles micro-inverters via OpenDTU have an inherent 18-25 second delay between sending a limit command and the inverter actually adjusting power output. The OpenDTU sends the command over its proprietary 2.4GHz radio, which has limited bandwidth and must wait for the inverter's next polling cycle. This means Venus OS power limiting strategies designed for SolarEdge's fast response will oscillate badly with Hoymiles.

**Why it happens:** Hardware limitation of Hoymiles micro-inverters -- they poll their DTU periodically rather than maintaining a persistent connection. The radio protocol is half-duplex with limited slots. OpenDTU GitHub issue #571 documents this as 25-90 seconds in worst cases.

**Consequences:**
- Venus OS sends a limit command, waits 5s for effect (as with Fronius/SolarEdge), sees no change, sends another
- Multiple limit commands queue up, eventually all take effect simultaneously causing overshoot
- The EDPC refresh loop (currently 5s interval) re-sends limits before the previous one takes effect, flooding the OpenDTU command queue
- User perceives the system as broken when power does not immediately respond to slider changes

**Prevention:**
- Track per-device limit response characteristics: `limit_latency_s` as a device property (SolarEdge: 2s, Hoymiles: 25s)
- After sending a limit to OpenDTU, mark the device as "limit pending" and suppress re-sends for at least 30s
- Do NOT include OpenDTU-connected inverters in Venus OS's automatic power limiting by default -- mark them as "monitoring only" until the user explicitly opts into limiting
- Show limit state in the device dashboard: "Limit sent (waiting for inverter response...)" with a countdown
- The EDPC refresh loop must skip devices that have a pending limit change younger than their `limit_latency_s`
- Consider using `/api/limit/status` polling to confirm the limit was actually applied before sending the next one

**Detection:** If the override log shows rapid-fire limit writes to an OpenDTU device within 30 seconds, the latency guard is not working.

**Phase:** OpenDTU Plugin phase. Must be addressed in the plugin design, not retrofitted.

---

### Pitfall 3: Aggregated SunSpec Registers Have Invalid Scale Factors

**What goes wrong:** SunSpec Model 103 uses scale factors (SF registers) to encode physical values. SolarEdge SE30K might report AC current with SF=-2 (meaning raw value 1234 = 12.34A), while Hoymiles via OpenDTU reports current in different units entirely (REST API returns plain floating-point watts/amps). When summing values from heterogeneous sources into one SunSpec register set, the scale factors must be consistent. If SolarEdge says SF=-2 and the aggregator naively adds an OpenDTU value encoded with the same SF, the decoded physical value is wrong.

**Why it happens:** SunSpec integer-with-scale-factor encoding is not additive across different sources. You cannot add raw register values -- you must decode to physical units, sum, then re-encode with a consistent scale factor.

**Consequences:**
- Venus OS reads the aggregated power register and calculates wildly wrong total power (10x too high or too low)
- Energy totals drift: cumulative kWh for Venus OS does not match sum of individual inverter readings
- 3-phase current distribution shows impossible values (negative current on one phase)

**Prevention:**
- All aggregation MUST happen in physical units (watts, amps, volts), never in raw register values
- Each plugin provides decoded float values. The aggregator sums floats, then encodes back to SunSpec with a fixed, known scale factor.
- Use a single SF per field across the aggregated output (e.g., always SF=-1 for current, SF=0 for power in watts)
- Add a validation step: `abs(aggregated_power - sum(individual_powers)) < 10W` as a sanity check
- For non-summable fields (voltage, frequency, temperature), use the primary inverter's values or weighted average

**Detection:** If Venus OS total power does not match the sum shown in the proxy dashboard's individual device panels, scale factor encoding is broken.

**Phase:** Virtual Inverter Aggregation phase. The aggregation math must handle unit conversion as a core requirement.

---

### Pitfall 4: SolarEdge Single Modbus TCP Connection Blocks OpenDTU Polling Architecture

**What goes wrong:** SolarEdge allows exactly ONE simultaneous Modbus TCP connection. The current proxy holds this connection permanently for the 1-second poll loop. If a future architecture change (e.g., shared connection pool, health check probe, scanner re-scan) tries to open a second connection, the SE30K silently drops the first one. The existing proxy loses its polling connection, cache goes stale after 30s, and Venus OS gets Modbus exception 0x04.

**Why it happens:** SolarEdge firmware limitation (confirmed in SolarEdge SunSpec Technical Note and multiple GitHub issues). The inverter's TCP server accepts only one client. A second `connect()` either fails or displaces the existing connection.

**Consequences:**
- Auto-discovery scan (which probes Modbus ports) disconnects the running proxy from SolarEdge
- If the user triggers a re-scan from the config page while the proxy is running, SolarEdge data goes stale for 30+ seconds
- Any monitoring tool (Home Assistant, EVCC) connecting to SolarEdge directly breaks the proxy
- During v4.0 development/testing, running two proxy instances simultaneously will cause mutual interference

**Prevention:**
- The scanner MUST skip hosts that have an active inverter connection. Add an exclusion list to `scan_subnet()` based on currently connected inverter hosts.
- Document prominently: "SolarEdge allows only one Modbus TCP client. Do not connect Home Assistant or other tools directly to the inverter while the proxy is running."
- Add connection loss detection: if 3 consecutive polls fail after a period of successful polling, check if another client stole the connection and log a specific warning.
- Consider implementing a Modbus TCP proxy/multiplexer for SolarEdge in a future version (out of scope for v4.0 but should be noted).

**Detection:** Sudden transition from `CONNECTED` to `RECONNECTING` without network changes. The connection manager logs should show "connection reset by peer" rather than timeout.

**Phase:** OpenDTU Plugin phase (scan exclusion) and Device Management phase (connection conflict detection).

---

### Pitfall 5: Config Migration From v3.1 Single-Inverter to v4.0 Multi-Device Breaks Running Systems

**What goes wrong:** v3.1 config has `inverters:` as a flat list of Modbus TCP devices. v4.0 needs to distinguish device types (modbus/solaredge vs opendtu/hoymiles), add device-specific settings (OpenDTU URL, authentication), and potentially restructure the config entirely. If the migration is not backward-compatible, existing users who update via `pip install -e .` get a broken config.

**Why it happens:** The `InverterEntry` dataclass has Modbus-specific fields (host, port, unit_id) that do not apply to OpenDTU devices. Adding `type: "opendtu"` entries to the same list creates an awkward union type. But restructuring the config (e.g., separate `modbus_inverters:` and `opendtu_inverters:` sections) breaks the existing migration path.

**Consequences:**
- Existing v3.1 configs fail to load if new required fields are missing
- `load_config()` creates default entries with wrong device types
- The `get_active_inverter()` function returns the first enabled entry regardless of type -- it might try to use Modbus TCP to connect to an OpenDTU device
- Config saved by v4.0 cannot be read by v3.1 if user downgrades

**Prevention:**
- Add an optional `type` field to `InverterEntry` with default `"solaredge"` (backward compatible -- existing entries without `type` are assumed SolarEdge/Modbus)
- Add OpenDTU-specific optional fields with sensible defaults: `opendtu_url: ""`, `opendtu_user: "admin"`, `opendtu_password: ""`
- The `load_config()` migration path already handles `inverter:` to `inverters:` -- add a second migration step that adds `type: "solaredge"` to entries that lack it
- `get_active_inverter()` should be deprecated in favor of `get_active_devices_by_type()` that returns typed collections
- Add a config `version: 2` field. On load, if version < 2, run migration and bump version.

**Detection:** Startup log should print the effective config with device types. If any device has `type: None`, migration failed.

**Phase:** Config/Data Model phase. Must be the first phase -- all other v4.0 features depend on the multi-device config structure.

---

### Pitfall 6: Power Limit Distribution Creates Feedback Loops With Venus OS

**What goes wrong:** Venus OS sends a total power limit to the virtual Fronius inverter (e.g., "limit to 50%"). The proxy must distribute this across individual inverters. If the proxy limits SolarEdge to 50% and OpenDTU to 50%, the total output drops. Venus OS sees the reduced output, recalculates, and sends a new (potentially different) limit. The proxy redistributes again. This creates an oscillation loop, especially because OpenDTU has 25s latency while SolarEdge responds in 2s.

**Why it happens:** The proxy is a "man in the middle" that transforms a single control signal into multiple control signals. Venus OS has no visibility into the individual inverters -- it only sees the aggregated output. The feedback loop emerges from the mismatch between Venus OS's control cycle (5s) and the heterogeneous inverter response times.

**Consequences:**
- Power output oscillates between 0% and 100% in a sawtooth pattern
- Venus OS ESS regulation becomes unstable, potentially exporting or importing when it should not
- In worst case, repeated rapid power changes stress inverter electronics and trip protection circuits
- The override log fills with hundreds of rapid-fire limit changes

**Prevention:**
- Default to "SolarEdge only" for Venus OS power limiting. OpenDTU inverters contribute to total power monitoring but do NOT receive power limit commands unless explicitly configured by the user.
- If multi-source limiting is enabled, use a **priority-based sequential approach**: apply limits to the highest-priority (fastest-responding) inverter first, wait for confirmation, then adjust lower-priority inverters only if needed.
- Implement a **dead-time** after distributing limits: suppress new limit distributions for `max(device_latencies) + margin` seconds (e.g., 30s for Hoymiles)
- Rate-limit the aggregator's response to Venus OS limit commands: accept at most one limit change per 5 seconds
- Log and expose the limit distribution ratios in the dashboard so the user can debug oscillation

**Detection:** If the control log shows limit values oscillating by more than 10% within 60 seconds, the feedback loop is active.

**Phase:** Power Limiting Strategy phase. This must be designed carefully with explicit dead-times and priority ordering.

## Moderate Pitfalls

### Pitfall 7: OpenDTU REST Polling Overwhelms ESP32 Under Load

**What goes wrong:** OpenDTU runs on an ESP32 microcontroller with limited CPU, memory, and concurrent connection capacity. Polling `/api/livedata/status` every 1 second (matching SolarEdge poll rate) puts significant load on the ESP32. The ESP32 must serialize JSON (which is expensive), serve HTTP, AND maintain its 2.4GHz radio communication with Hoymiles inverters. Under load, OpenDTU may become unresponsive or drop radio packets, causing stale inverter data.

**Why it happens:** ESP32 is a constrained embedded device. The OpenDTU web server is secondary to its primary function (radio communication with inverters). HTTP request handling competes for CPU time with the radio protocol stack.

**Consequences:**
- OpenDTU becomes unresponsive to REST requests, proxy sees timeouts
- Radio communication degrades, inverter data becomes stale (high `data_age` values)
- Power limit commands get delayed or lost because the command queue backs up
- In extreme cases, ESP32 watchdog triggers and OpenDTU reboots

**Prevention:**
- Poll OpenDTU at 5-second intervals, not 1 second. Hoymiles data updates every ~15 seconds via radio anyway, so faster polling gains nothing.
- Use HTTP keepalive (persistent connection) to avoid TCP handshake overhead on every request
- Set aggressive HTTP timeouts (3s connect, 5s read) to fail fast rather than block
- Check `data_age` field in the response -- if > 30s, the inverter data is stale regardless of poll frequency
- Consider using OpenDTU's MQTT output instead of REST for a future optimization (push vs pull), but REST is simpler for initial implementation
- Monitor OpenDTU's `/api/system/status` for heap memory and uptime to detect resource exhaustion

**Detection:** If `data_age` values consistently exceed 30 seconds, the ESP32 is likely overloaded. If REST requests timeout more than 10% of the time, reduce poll frequency.

**Phase:** OpenDTU Plugin phase. Set poll interval to 5s from the start, do not copy SolarEdge's 1s interval.

---

### Pitfall 8: Device Lifecycle Management Leaks asyncio Tasks

**What goes wrong:** When a user adds or removes an inverter device at runtime, the system must start/stop poll loops, connection managers, and timeseries buffers. If a device is removed but its poll loop task is not properly cancelled and awaited, the task continues running in the background, writing data to a device store that no longer exists. Adding the same device back creates a duplicate task. Over time, leaked tasks accumulate memory and CPU usage.

**Why it happens:** The current architecture creates tasks in `__main__.py` and `run_proxy()` without a centralized task registry. `asyncio.create_task()` returns a task reference that must be stored and cancelled explicitly. Without a device lifecycle manager, there is no single place that tracks "device X has tasks [poll, edpc_refresh, connection_manager]".

**Consequences:**
- Removed devices continue consuming network bandwidth (polling a disconnected inverter)
- Memory leak: each leaked task holds references to its plugin, cache, and shared context
- Re-adding a device creates duplicate pollers that fight over the same connection (especially bad for SolarEdge's single-connection limit)
- Shutdown does not clean up all tasks, causing "task was destroyed but it is pending" warnings

**Prevention:**
- Create a `DeviceManager` class that maps `device_id -> {plugin, poll_task, edpc_task, conn_mgr, data_store}`
- `add_device()` creates all resources and starts tasks. `remove_device()` cancels all tasks (with `await`), closes the plugin connection, and removes the data store entry.
- Use `asyncio.TaskGroup` (Python 3.11+) or a manual task set with proper exception handling
- On shutdown, iterate all devices and call `remove_device()` sequentially
- Add a `/api/debug/tasks` endpoint that lists running asyncio tasks for debugging

**Detection:** After removing a device, check `len(asyncio.all_tasks())` -- if it does not decrease, tasks leaked.

**Phase:** Device Management phase. The DeviceManager must be built before hot-add/remove is implemented.

---

### Pitfall 9: UI Architecture Shift From Monolithic to Device-Centric Breaks State Management

**What goes wrong:** The current frontend (`app.js`) is a monolithic single-page app with global state. Variables like `_cfgOriginal`, `_snapshot`, `_sparklineData` are all global. The dashboard renders one inverter's data. Shifting to device-centric navigation (per-inverter dashboard + registers + config) requires either (a) duplicating all state per device or (b) switching to a component-based architecture. Neither is easy with vanilla JS and no framework.

**Why it happens:** The zero-dependency vanilla JS constraint was the right call for v1.0-v3.1 (simple, no build tooling), but the complexity jump to multi-device management pushes against the limits of global-state vanilla JS.

**Consequences:**
- Switching between device dashboards leaks event listeners (sparkline timers, WebSocket handlers)
- Global `_snapshot` gets overwritten when switching devices, causing flicker
- Config dirty tracking (`_cfgOriginal`) does not know which device's config is being edited
- Ring buffers for sparklines are per-device but currently stored globally -- navigating away loses history

**Prevention:**
- Introduce a lightweight device context pattern: `_devices = {}` map with per-device state objects containing snapshot, sparkline buffer, config original, etc.
- On navigation, do NOT destroy the previous device's DOM -- hide it (`display:none`) and show the target device's panel. This preserves state and avoids re-rendering.
- Alternatively, extract state into a `DeviceState` class per device and re-render when switching, but always from the cached state object.
- WebSocket messages should include a `device_id` field. The frontend routes each message to the correct device's state object.
- Sparkline ring buffers must persist across navigation -- store them in `_devices[id].sparklines`, not as global arrays.

**Detection:** Navigate between two device dashboards rapidly. If sparkline data disappears or the gauge shows wrong values after switching back, state management is broken.

**Phase:** Device-Centric UI phase. Plan the state management pattern before building any device-specific views.

---

### Pitfall 10: OpenDTU Authentication Credentials Stored in Plaintext Config

**What goes wrong:** OpenDTU requires HTTP Basic Authentication for write operations (power limit configuration). The default credentials are `admin`/`openDTU42`. These must be stored in the proxy's config YAML to send limit commands. Storing passwords in plaintext YAML is a security concern, even in a LAN-only deployment.

**Why it happens:** The project explicitly declares TLS/Auth as out of scope ("alles im selben LAN"). But storing credentials still creates practical issues: config files in git, config displayed in debug logs, config visible in the webapp's config page.

**Consequences:**
- Password visible in `config.yaml` file on disk (readable by any user on the LXC)
- If config is ever committed to git or backed up to cloud storage, credentials leak
- The existing `save_config()` serializes the entire `Config` dataclass to YAML via `dataclasses.asdict()` -- passwords included
- The webapp's config API endpoint (`/api/config`) returns the full config to the browser -- password visible in browser dev tools

**Prevention:**
- Never return passwords in API responses: mask with `"****"` in GET `/api/config`
- On POST `/api/config`, if password field is `"****"`, keep the existing stored password (do not overwrite)
- Log the OpenDTU URL but never log the password in structlog output
- Consider using a separate credentials file or environment variable for sensitive values, but for v4.0 the plaintext YAML approach is acceptable given the LAN-only constraint -- just mask it in API/UI/logs
- Add a `.gitignore` entry for `config.local.yaml` (already present as `.bak` pattern)

**Detection:** Check `/api/config` response for plaintext passwords. Check structlog output for password values.

**Phase:** OpenDTU Plugin phase. Implement credential masking from day one.

---

### Pitfall 11: Partial Aggregation When One Source Is Offline

**What goes wrong:** If SolarEdge is producing 10kW and OpenDTU/Hoymiles is producing 1kW, Venus OS sees 11kW total. If OpenDTU goes offline (ESP32 reboot, WiFi dropout), the aggregator must decide: report 10kW (SolarEdge only) or report "stale" (because one source is missing)? If it reports 10kW, Venus OS sees a sudden 1kW drop and may adjust ESS regulation. If it reports stale, Venus OS loses visibility into the still-functioning SolarEdge.

**Why it happens:** Partial failure in multi-source aggregation is an inherently ambiguous state. The correct behavior depends on context that the aggregator does not have (is the 1kW drop real or just a data gap?).

**Consequences:**
- Reporting only available sources: Venus OS sees phantom power drops/jumps whenever any source goes offline/online, triggering unnecessary ESS regulation changes
- Reporting stale: Venus OS loses all monitoring/control even though the primary inverter (SolarEdge, 10kW) is working fine
- Energy totals become inconsistent: daily kWh counter jumps when a source comes back online

**Prevention:**
- Use "last known value with decay" for offline sources: when a source goes offline, continue using its last known power value for up to 60 seconds, then linearly decay to 0 over the next 60 seconds. This smooths the transition.
- Track per-source `data_age` in the aggregated dashboard. Show a warning badge per device: "OpenDTU: data 45s stale"
- NEVER mark the entire aggregated feed as stale unless ALL sources are stale. As long as any source is producing fresh data, the Modbus server should serve data.
- For energy (kWh) totals: accumulate per-source independently. The aggregated total is always the sum of individually-tracked per-source totals, not a single counter.
- Log partial-aggregation events at WARN level with source identification.

**Detection:** If Venus OS power reading drops by exactly one device's contribution and that device's status shows "offline", the aggregator is not using graceful degradation.

**Phase:** Virtual Inverter Aggregation phase. The aggregation engine must handle partial data from day one.

---

### Pitfall 12: WebSocket Broadcast Payload Grows Linearly With Device Count

**What goes wrong:** The current WebSocket broadcast sends the entire dashboard snapshot every second. With one inverter, this is ~2KB. With N devices, each having their own snapshot (power, voltage, current, temperature, sparklines, status), the payload grows to N * 2KB. The sparkline data (60 minutes of 1-second samples = 3600 points per metric) is particularly large. Broadcasting this to multiple browser clients every second creates significant bandwidth and CPU load.

**Why it happens:** The monolithic snapshot design sends everything regardless of what changed. There is no delta/diff mechanism.

**Consequences:**
- Browser performance degrades with many devices (JSON parsing latency)
- Network bandwidth saturates on slow connections (LAN is fast but WiFi to mobile devices is slower)
- Server-side JSON serialization blocks the event loop briefly on each broadcast

**Prevention:**
- Send per-device snapshots only when that device's data changes (delta broadcasting)
- Do NOT send sparkline history on every broadcast -- send it once on WebSocket connect, then only new data points
- Add a `device_id` field to all WebSocket messages so the frontend can route to the correct device state
- Consider separate WebSocket "channels" per device: client subscribes to device IDs it is currently viewing
- Compress sparkline data: instead of 3600 float values, send only new points since last broadcast (1 point per second per metric)

**Detection:** Measure WebSocket message sizes. If average message > 10KB or total broadcast bandwidth > 100KB/s, optimization is needed.

**Phase:** Device-Centric UI phase. Design the WebSocket protocol before implementing multi-device broadcasting.

## Minor Pitfalls

### Pitfall 13: OpenDTU Firmware Version Compatibility

**What goes wrong:** The OpenDTU REST API has had breaking changes (2024-01-30: livedata/status restructured, 2025-08-07: limit/config parameters changed). The proxy plugin must target a specific API version. If the user has an older or newer OpenDTU firmware, the plugin may parse responses incorrectly or send malformed limit commands.

**Prevention:**
- Check OpenDTU firmware version via `/api/system/status` on first connection. Log a warning if the version is outside the tested range.
- Parse JSON responses defensively with `.get()` and fallback values rather than direct key access.
- Document the tested OpenDTU firmware version in the config page and README.

**Phase:** OpenDTU Plugin phase.

---

### Pitfall 14: Device ID Collision When Re-Adding Scanned Inverters

**What goes wrong:** The v3.1 scanner generates device IDs via `uuid.uuid4().hex[:12]`. If a user removes a SolarEdge inverter and re-adds it via scan, it gets a new ID. Any per-device state (sparkline history, energy totals, config overrides) associated with the old ID is orphaned. Worse, if the config is not cleaned up, both old and new entries exist for the same physical device.

**Prevention:**
- Use the inverter's serial number as the canonical device identifier, not a random UUID. SolarEdge provides serial via Modbus Common Model registers. OpenDTU provides serial in the REST API response.
- Fall back to `host:port` as identifier only if serial is unavailable (e.g., device is offline during scan).
- On scan results, match against existing devices by serial number before creating new entries.

**Phase:** Device Management phase. Change the ID strategy before implementing add/remove.

---

### Pitfall 15: `shared_ctx` Dict Becomes Unmanageable With Per-Device State

**What goes wrong:** The current `shared_ctx` dict already has 15+ keys (cache, conn_mgr, control_state, poll_counter, last_se_poll, dashboard_collector, webapp, venus_task, venus_mqtt_connected, venus_os_detected, etc.). Adding per-device state (one set of these keys per device) makes the dict a tangled mess. Key naming collisions become likely (`cache` vs `cache_device_1`).

**Prevention:**
- Replace the flat `shared_ctx` dict with a typed `AppContext` dataclass that has clear structure:
  ```python
  @dataclass
  class DeviceContext:
      plugin: InverterPlugin
      poll_task: asyncio.Task
      conn_mgr: ConnectionManager
      cache: RegisterCache  # per-device raw data
      data: DeviceData      # decoded physical values

  @dataclass
  class AppContext:
      devices: dict[str, DeviceContext]
      aggregator: Aggregator
      venus: VenusContext
      webapp: web.Application
      config: Config
      config_path: str
  ```
- Migrate to `AppContext` incrementally: start by wrapping the existing dict, then migrate consumers one by one.

**Phase:** Config/Data Model phase. Define the typed context structure before adding device-specific state.

---

### Pitfall 16: OpenDTU Serves Multiple Micro-Inverters But Plugin May Treat It As One Device

**What goes wrong:** The OpenDTU at 192.168.3.98 serves TWO Hoymiles inverters (HM-400 + HM-600). The `/api/livedata/status` response returns an `inverters` array with both. If the plugin treats the OpenDTU endpoint as a single device, it aggregates the two micro-inverters internally and loses per-inverter visibility. The user cannot see individual HM-400 vs HM-600 data or control them independently.

**Prevention:**
- One OpenDTU connection can yield multiple device entries. The plugin should create one `DeviceContext` per Hoymiles serial number found in the OpenDTU response, not one per OpenDTU endpoint.
- Power limit commands must include the target inverter's serial number (the `/api/limit/config` POST requires a `serial` field).
- The device tree in the UI should show: OpenDTU (192.168.3.98) -> HM-400 (serial) + HM-600 (serial), with the OpenDTU being a "gateway" not a "device".

**Phase:** OpenDTU Plugin phase. Design the one-gateway-to-many-inverters relationship from the start.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Config/Data Model | v3.1 -> v4.0 config migration breaks existing installs (Pitfall 5) | Add `type` field with `"solaredge"` default, version config |
| Config/Data Model | `shared_ctx` dict becomes unmanageable (Pitfall 15) | Typed `AppContext` dataclass |
| OpenDTU Plugin | 18-25s power limit latency causes oscillation (Pitfall 2) | Per-device latency tracking, dead-time after limit send |
| OpenDTU Plugin | ESP32 overwhelmed by frequent polling (Pitfall 7) | 5s poll interval, HTTP keepalive, respect `data_age` |
| OpenDTU Plugin | API breaking changes across firmware versions (Pitfall 13) | Version check on connect, defensive JSON parsing |
| OpenDTU Plugin | One OpenDTU serves multiple micro-inverters (Pitfall 16) | Per-serial device entries, gateway concept |
| OpenDTU Plugin | Credentials in plaintext config (Pitfall 10) | Mask in API/UI/logs from day one |
| Virtual Inverter Aggregation | Single-plugin architecture does not support aggregation (Pitfall 1) | Aggregation layer between pollers and register cache |
| Virtual Inverter Aggregation | Scale factor encoding produces wrong sums (Pitfall 3) | Aggregate in physical units, re-encode with fixed SF |
| Virtual Inverter Aggregation | Partial source failure causes phantom power drops (Pitfall 11) | Last-known-value decay, per-source staleness tracking |
| Power Limiting Strategy | Feedback loops with Venus OS ESS regulation (Pitfall 6) | Priority-based sequential limiting, dead-time enforcement |
| Device Management | SolarEdge single-connection conflicts with scan (Pitfall 4) | Scan exclusion list for connected hosts |
| Device Management | asyncio task leaks on device add/remove (Pitfall 8) | DeviceManager with explicit task lifecycle |
| Device Management | UUID-based IDs cause orphaned state on re-add (Pitfall 14) | Serial-number-based device identity |
| Device-Centric UI | Global state breaks with multi-device navigation (Pitfall 9) | Per-device state objects, hide/show vs destroy/recreate |
| Device-Centric UI | WebSocket payloads grow linearly with devices (Pitfall 12) | Delta broadcasting, per-device subscriptions |

## Codebase-Specific Observations

Patterns in the existing code that will interact with v4.0 features:

1. **`run_proxy()` is monolithic:** It creates the plugin, cache, control state, Modbus server, and poll loop all in one function. v4.0 needs these to be independent, composable components. Refactoring `run_proxy()` into a `ProxyEngine` class with pluggable components is prerequisite work.

2. **`PollResult` assumes SunSpec register format:** The `InverterPlugin.poll()` returns `common_registers` and `inverter_registers` as raw uint16 lists matching SunSpec Model 1 and Model 103 layout. OpenDTU returns JSON with physical values (watts, amps, volts). The plugin ABC needs either (a) a new return type for non-Modbus sources or (b) the OpenDTU plugin must synthesize SunSpec registers from JSON values. Option (b) keeps the aggregation layer simpler but adds complexity to the plugin.

3. **`ControlState` is a singleton:** There is one `ControlState` tracking one power limit. With multiple inverters, each needs its own limit state, plus the virtual inverter needs an aggregate limit state. The EDPC refresh loop also assumes one plugin and one control state.

4. **`DashboardCollector.collect()` reads from a single register cache:** It decodes SunSpec registers using hardcoded address offsets. For aggregated data, it needs to decode from the aggregated register cache, not from any individual device's cache.

5. **Night mode is global:** `ConnectionManager` tracks one state machine (CONNECTED/RECONNECTING/NIGHT_MODE). With multiple devices, each needs its own connection state. The aggregated state logic ("all sleeping = aggregated night mode") does not exist yet.

## Sources

- Direct code analysis of existing codebase: `proxy.py`, `plugin.py`, `control.py`, `config.py`, `__main__.py`, `plugins/solaredge.py`, `webapp.py`, `dashboard.py` (HIGH confidence)
- [OpenDTU Web API Documentation](https://www.opendtu.solar/firmware/web_api/) (HIGH confidence)
- [OpenDTU GitHub Issue #571: Power limit 25-90 second delay](https://github.com/tbnobody/OpenDTU/issues/571) (HIGH confidence)
- [SolarEdge single Modbus TCP connection limit](https://github.com/binsentsu/home-assistant-solaredge-modbus/issues/82) (HIGH confidence)
- [dbus-opendtu Venus OS integration issues](https://github.com/henne49/dbus-opendtu) (MEDIUM confidence)
- [OpenDTU-OnBattery Dynamic Power Limiter](https://github.com/hoylabs/OpenDTU-OnBattery/wiki/Dynamic-Power-Limiter) (MEDIUM confidence)
- [SolarEdge SunSpec Technical Note](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf) (HIGH confidence)
- [OpenDTU GitHub: API breaking changes](https://github.com/tbnobody/OpenDTU) (MEDIUM confidence)
