# Architecture: Dashboard & Power Control Integration

**Domain:** Real-time dashboard features for existing aiohttp+asyncio Modbus proxy
**Researched:** 2026-03-18 (updated for v2.0 WebSocket decision)
**Overall confidence:** HIGH (based on existing codebase analysis + verified aiohttp patterns)

## Executive Summary

The existing v1.0 architecture is well-suited for dashboard integration. The `shared_ctx` dict pattern already exposes `cache`, `conn_mgr`, `control_state`, and `poll_counter` to the webapp. The poll loop updates the cache every 1 second. New features -- WebSocket push, ring buffer history, power control API, and dashboard data endpoints -- integrate cleanly as additive changes with no modifications to proxy.py's core loop.

**Key decision: Use WebSocket over SSE.** While the initial architecture research recommended SSE (unidirectional server-to-client), v2.0's power control slider requires bidirectional communication: slider values flow client-to-server while live feedback flows server-to-client. WebSocket handles both in a single connection. aiohttp has first-class WebSocket support via `web.WebSocketResponse()` -- zero new dependencies.

## Existing Architecture (What We Have)

```
                    __main__.py
                   /          \
            run_proxy()    create_webapp()
            (proxy.py)      (webapp.py)
               |                |
     +---------+---------+     +-- 7 REST endpoints
     |                   |     +-- single-file HTML
  _poll_loop()    ModbusTcpServer
     |                   |
  SolarEdgePlugin   StalenessAwareSlaveContext
     |                   |
  SE30K:1502        RegisterCache + ControlState
```

**shared_ctx** dict (populated by `run_proxy`, consumed by webapp):
- `cache` -- RegisterCache (datablock + staleness)
- `conn_mgr` -- ConnectionManager (state machine)
- `control_state` -- ControlState (WMaxLimPct, WMaxLim_Ena)
- `poll_counter` -- {"success": N, "total": N}
- `last_se_poll` -- raw SE30K register data (common + inverter)

**Poll cycle:** 1 second. Cache updates on every successful poll. Webapp reads cache on HTTP request.

## New Components Needed

### 1. TimeSeriesBuffer (new module: `timeseries.py`)

In-memory ring buffer for 60-minute power history. One buffer per metric.

```python
import time
from collections import deque
from dataclasses import dataclass

@dataclass(slots=True)
class Sample:
    timestamp: float  # time.monotonic()
    value: float

class TimeSeriesBuffer:
    """Fixed-duration ring buffer for a single metric.

    Uses collections.deque(maxlen=N) for automatic eviction.
    At 1 sample/second for 60 minutes = 3,600 entries.
    Memory: ~60 bytes/Sample * 3,600 = ~210 KB per buffer.
    """

    def __init__(self, max_seconds: int = 3600):
        self._max_seconds = max_seconds
        self._buf: deque[Sample] = deque(maxlen=max_seconds + 60)

    def append(self, value: float, ts: float | None = None) -> None:
        self._buf.append(Sample(ts or time.monotonic(), value))

    def get_since(self, since_ts: float) -> list[Sample]:
        """Return samples newer than since_ts. O(n) scan from right."""
        result = []
        for s in reversed(self._buf):
            if s.timestamp <= since_ts:
                break
            result.append(s)
        result.reverse()
        return result

    def get_all(self) -> list[Sample]:
        return list(self._buf)

    def latest(self) -> Sample | None:
        return self._buf[-1] if self._buf else None
```

**Why `collections.deque`:** Thread-safe, O(1) append, automatic eviction via `maxlen`, zero dependencies. The 60-minute window is tiny (3,600 entries). No need for numpy ring buffers or external libraries.

**Metrics to buffer (6 buffers total):**

| Buffer | Source | Register offset in Model 103 |
|--------|--------|------------------------------|
| `ac_power_w` | inverter_registers[14] + SF[15] | AC Power + AC Power SF |
| `ac_current_a` | inverter_registers[2] + SF[6] | AC Current + SF |
| `ac_voltage_avg` | computed from AN/BN/CN | Phase voltages |
| `ac_frequency_hz` | inverter_registers[16] + SF[17] | AC Freq + SF |
| `dc_power_w` | inverter_registers[31] + SF[32] | DC Power + SF |
| `temperature_c` | inverter_registers[33] + SF[37] | Cab Temp + SF |

### 2. DashboardCollector (new module: `dashboard.py`)

Extracts dashboard-ready values from shared_ctx on each poll cycle. Feeds both TimeSeriesBuffers and WebSocket clients.

```python
class DashboardCollector:
    """Extracts decoded inverter values from RegisterCache.

    Called after each successful poll to:
    1. Decode raw registers into physical values (applying scale factors)
    2. Append to TimeSeriesBuffers
    3. Build snapshot dict for WebSocket broadcast
    """

    def __init__(self):
        self.buffers: dict[str, TimeSeriesBuffer] = {
            "ac_power_w": TimeSeriesBuffer(),
            "ac_current_a": TimeSeriesBuffer(),
            "ac_voltage_avg": TimeSeriesBuffer(),
            "ac_frequency_hz": TimeSeriesBuffer(),
            "dc_power_w": TimeSeriesBuffer(),
            "temperature_c": TimeSeriesBuffer(),
        }
        self._last_snapshot: dict | None = None

    def collect(self, cache: RegisterCache) -> dict:
        """Decode registers, update buffers, return snapshot."""
        # Read from cache.datablock (same as registers_handler does)
        # Apply scale factors to get physical values
        # Append to buffers
        # Return snapshot dict
        ...

    @property
    def snapshot(self) -> dict | None:
        return self._last_snapshot
```

**Integration point:** The DashboardCollector is called from the poll loop callback, NOT from an HTTP handler. This ensures data is collected regardless of whether any browser is connected.

### 3. WebSocket Handler (additions to `webapp.py`)

Manages bidirectional communication: server pushes live data, client sends power control commands.

```python
import weakref
import json
from aiohttp import web

# In create_webapp():
app["ws_clients"] = weakref.WeakSet()

async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for live data push + power control commands."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app["ws_clients"].add(ws)

    # Send initial state on connect
    collector = request.app["shared_ctx"].get("dashboard_collector")
    if collector and collector.snapshot:
        await ws.send_str(json.dumps({
            "type": "snapshot",
            "data": collector.snapshot
        }))
    # Send history for sparkline initialization
    if collector:
        history = {k: [[s.timestamp, s.value] for s in buf.get_all()]
                   for k, buf in collector.buffers.items()}
        await ws.send_str(json.dumps({
            "type": "history",
            "data": history
        }))

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            await handle_ws_command(request.app, data)
        elif msg.type == aiohttp.WSMsgType.ERROR:
            break

    request.app["ws_clients"].discard(ws)
    return ws

async def broadcast_to_clients(app: web.Application, snapshot: dict) -> None:
    """Broadcast snapshot to all connected WebSocket clients."""
    if not app["ws_clients"]:
        return
    payload = json.dumps({"type": "snapshot", "data": snapshot})
    dead = set()
    for ws in set(app["ws_clients"]):
        try:
            await ws.send_str(payload)
        except Exception:
            dead.add(ws)
    for ws in dead:
        app["ws_clients"].discard(ws)
```

**Why WebSocket instead of SSE (updated from initial research):**

| Criterion | WebSocket | SSE |
|-----------|-----------|-----|
| Data direction | Bidirectional (needed for power control) | Server-to-client only |
| Power control writes | Same connection as live data | Needs separate POST endpoints |
| Dependencies | Zero (aiohttp built-in) | Zero (aiohttp StreamResponse) |
| Auto-reconnect | Must implement in JS | Built into EventSource API |
| Slider feedback latency | Sub-100ms round trip | POST latency + SSE push latency |
| Protocol complexity | ~60 lines Python | ~40 lines Python + POST handlers |
| Frontend complexity | `new WebSocket(...)` + reconnect | `new EventSource(...)` + separate fetch() for commands |

**The v2.0 power control slider tips the balance.** Slider drag events need sub-200ms round trips for responsive UX. WebSocket provides this in a single connection. With SSE, each slider change would be a separate POST request, and feedback arrives via a different channel (the SSE stream). WebSocket keeps command+response in one connection with lower latency.

### 4. Power Control API (hybrid: WebSocket commands + REST fallback)

Primary: Power control commands via WebSocket messages.
Fallback: REST endpoints for non-WebSocket clients (curl, testing).

**WebSocket message protocol:**

```json
// Client -> Server
{"cmd": "set_power_limit", "percent": 75, "timeout": 300}
{"cmd": "set_power_enable", "enabled": true}
{"cmd": "reset_power"}

// Server -> Client (after command)
{"type": "power_ack", "success": true, "actual_pct": 75.2, "source": "webapp"}
{"type": "power_ack", "success": false, "error": "Inverter disconnected"}
```

**REST fallback endpoints** (kept for backward compatibility and testing):

```
POST /api/power/limit    -- Set power limit percentage
POST /api/power/enable   -- Enable/disable power limiting
POST /api/power/reset    -- Reset to 100%
GET  /api/power/status   -- Current control state + override detection
GET  /api/dashboard      -- Current snapshot (initial page load)
GET  /api/dashboard/history  -- 60-min history (initial sparkline data)
```

### 5. Override Detection Logic

Venus OS writes to Model 123 via Modbus. The webapp user writes via WebSocket. Need to detect WHO is controlling.

```python
@dataclass
class PowerControlStatus:
    enabled: bool
    limit_pct: float
    source: str  # "webapp" | "venus_os" | "none"
    last_change_ts: float
    venus_os_active: bool  # True if Venus OS wrote recently
```

**Implementation:** Extend `ControlState` (or wrap it) to track the source of the last write:
- Modbus write path (`StalenessAwareSlaveContext.async_setValues`) = "venus_os"
- WebSocket/HTTP path (`/api/power/limit` or WebSocket cmd) = "webapp"

## Data Flow: How New Features Integrate

### Real-Time Push Flow (WebSocket)

```
_poll_loop (every 1s)
    |
    v
plugin.poll() -> PollResult
    |
    v
cache.update() [existing]
    |
    v
dashboard_collector.collect(cache) [NEW -- called in poll loop]
    |
    +---> TimeSeriesBuffers.append() [NEW]
    |
    +---> broadcast_to_clients(app, snapshot) [NEW]
              |
              v
         All connected WebSocket clients in browser
```

### Integration with existing poll loop

The cleanest integration point is a **callback hook** in `_poll_loop`. After `cache.update()` succeeds, call the dashboard collector. This requires a small modification to `_poll_loop` in proxy.py:

```python
# In _poll_loop, after cache.update() calls:
if shared_ctx is not None and "dashboard_collector" in shared_ctx:
    collector = shared_ctx["dashboard_collector"]
    snapshot = collector.collect(cache)
    if "webapp" in shared_ctx:
        await broadcast_to_clients(shared_ctx["webapp"], snapshot)
```

**This is the ONLY change to proxy.py.** Everything else is additive.

### Power Control Write-Back Flow (via WebSocket)

```
Browser: slider change (debounced 200ms)
    |
    v
WebSocket: {"cmd": "set_power_limit", "percent": 75, "timeout": 300}
    |
    v
handle_ws_command (webapp.py) [NEW]
    |
    +-- validate (0-100%, timeout 60-3600s)
    +-- control_state.update_wmaxlimpct(raw_value) [existing]
    +-- control_state.update_wmaxlim_ena(1) [existing]
    +-- plugin.write_power_limit(True, 75.0) [existing]
    +-- mark source = "webapp" [NEW]
    +-- ws.send_str({"type": "power_ack", ...}) [NEW]
```

### Dashboard Initial Load Flow

```
Browser opens dashboard page
    |
    +-- GET / -> Venus OS styled HTML (single file)
    |
    +-- new WebSocket("/ws")
         |
         +-- Server sends {"type": "snapshot", ...} (current state)
         +-- Server sends {"type": "history", ...} (60-min sparkline data)
         |
         v
    WebSocket stays open for:
      - Server pushes {"type": "snapshot"} every 1 second
      - Client sends power control commands
```

## Component Boundaries (New + Modified)

| Component | Status | Responsibility | File |
|-----------|--------|---------------|------|
| TimeSeriesBuffer | **NEW** | Ring buffer for 60-min metric history | `timeseries.py` |
| DashboardCollector | **NEW** | Decode registers, feed buffers + broadcast | `dashboard.py` |
| WebSocket handler | **NEW** | Bidirectional: push data + receive commands | Added to `webapp.py` |
| PowerControlAPI | **NEW** | REST fallback for power control | Added to `webapp.py` |
| OverrideDetector | **NEW** | Track who last wrote power limit | Added to `control.py` |
| _poll_loop | **MODIFIED** | Add callback after cache.update() | `proxy.py` (3-4 lines) |
| create_webapp | **MODIFIED** | Register WebSocket route + collector in app | `webapp.py` |
| __main__.py | **MODIFIED** | Create DashboardCollector, add to shared_ctx | `__main__.py` |
| ControlState | **MODIFIED** | Add `last_source` and `last_change_ts` tracking | `control.py` |
| index.html | **REPLACED** | Full Venus OS styled dashboard | `static/index.html` |

## Register Decoding Strategy

The dashboard needs physical values (watts, amps, volts), not raw register integers. Decoding requires applying SunSpec scale factors.

### Current state
`registers_handler` returns raw register values without scale factor application. The frontend displays raw integers.

### New approach for dashboard
`DashboardCollector.collect()` reads directly from `cache.datablock` (same access pattern as `registers_handler`) and applies scale factors:

```python
def _decode_power(self, datablock) -> float:
    """Decode AC Power from Model 103 registers."""
    # AC Power at 40083 (offset 14 in Model 103)
    # AC Power SF at 40084 (offset 15)
    raw = datablock.getValues(40083 + 1, 1)[0]  # +1 for pymodbus offset
    sf = datablock.getValues(40084 + 1, 1)[0]
    # SF is int16 (signed)
    if sf > 32767:
        sf -= 65536
    return raw * (10 ** sf)
```

**Scale factor registers are in the same datablock**, updated every poll cycle alongside their data registers. No separate fetch needed.

## Snapshot Format (WebSocket payload)

```json
{
  "ts": 1710770400.0,
  "inverter": {
    "ac_power_w": 12450.0,
    "ac_current_a": 18.2,
    "ac_current_a_phase": [6.1, 6.0, 6.1],
    "ac_voltage_v_phase": [230.1, 231.0, 229.8],
    "ac_frequency_hz": 50.01,
    "dc_power_w": 12800.0,
    "dc_voltage_v": 720.0,
    "dc_current_a": 17.8,
    "temperature_c": 42.5,
    "energy_total_kwh": 21543.2,
    "status": "MPPT",
    "status_code": 7
  },
  "control": {
    "enabled": true,
    "limit_pct": 75.0,
    "source": "venus_os",
    "venus_os_active": true
  },
  "connection": {
    "state": "connected",
    "poll_success_rate": 99.8,
    "cache_stale": false,
    "uptime_s": 86400
  }
}
```

## History Format (sparkline initial load)

```json
{
  "ac_power_w": [[1710770000.0, 12400], [1710770001.0, 12450], ...],
  "ac_frequency_hz": [[1710770000.0, 50.01], [1710770001.0, 50.02], ...],
  ...
}
```

Frontend receives flat arrays of `[timestamp, value]` pairs. For sparklines, send downsampled data (every 10th sample = 360 points per metric for 60 minutes). Backend provides downsampling to keep initial load payload under ~50 KB.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Polling from the frontend for "real-time"
**What:** Keep the existing 2-second `setInterval(fetch)` pattern for dashboard data.
**Why bad:** Creates N * polling_rate HTTP requests. Adds latency. Cannot achieve sub-second updates. Wastes bandwidth re-sending unchanged data.
**Instead:** WebSocket pushes snapshots after each poll cycle. Single persistent connection per browser tab.

### Anti-Pattern 2: Reading registers in the WebSocket broadcast
**What:** Each WebSocket broadcast reads from `cache.datablock` directly.
**Why bad:** Scale factor decoding happens N times (once per client). Same work repeated.
**Instead:** DashboardCollector decodes once per poll cycle, broadcasts the pre-built snapshot.

### Anti-Pattern 3: Storing history in the frontend only
**What:** Let the browser accumulate WebSocket events for sparklines.
**Why bad:** Page refresh loses all history. Second tab has no history until 60 minutes pass.
**Instead:** Server-side TimeSeriesBuffers. Initial load via WebSocket `history` message. Incremental updates via `snapshot` messages.

### Anti-Pattern 4: Direct plugin.write_power_limit() from WebSocket handler
**What:** WebSocket command handler calls plugin.write_power_limit() without going through ControlState.
**Why bad:** Bypasses validation, bypasses readback update, ControlState falls out of sync, Venus OS reads stale Model 123 registers.
**Instead:** WebSocket handler updates ControlState first (same validation path as Modbus write), then calls plugin.write_power_limit(). Mirror the existing `_handle_control_write` logic.

### Anti-Pattern 5: Sending full history on every WebSocket message
**What:** Include 60-min history arrays in every 1-second snapshot broadcast.
**Why bad:** ~50 KB per message * 1/second = 50 KB/s bandwidth for data that barely changes.
**Instead:** Send history once on WebSocket connect. Send only current snapshot (< 1 KB) on each poll cycle. Frontend appends to its local sparkline array.

## Suggested Build Order

Dependencies dictate this order:

### Step 1: TimeSeriesBuffer + DashboardCollector (no webapp changes)
- `timeseries.py` -- pure Python, easily testable
- `dashboard.py` -- register decoding + buffer feeding
- Unit tests for both
- **Why first:** Foundation for everything else. No external integration needed.

### Step 2: Poll loop integration + shared_ctx wiring
- Add 3-4 lines to `proxy.py` `_poll_loop` for collector callback
- Create collector in `__main__.py`, add to `shared_ctx`
- **Why second:** Validates that data flows correctly before building UI.

### Step 3: WebSocket endpoint + REST fallback
- `GET /ws` -- WebSocket handler with initial snapshot + history
- `GET /api/dashboard` -- REST snapshot (for curl/testing)
- `GET /api/dashboard/history` -- REST history (for curl/testing)
- Broadcast hook from poll loop
- Test with `wscat ws://localhost/ws`
- **Why third:** Requires collector to already work. Verifiable before frontend.

### Step 4: Power Control API
- WebSocket command handler (set_power_limit, set_power_enable, reset)
- REST fallback endpoints (POST /api/power/*)
- Override detection in ControlState
- **Why fourth:** Needs careful safety validation, independent of dashboard display.

### Step 5: Frontend Dashboard
- Venus OS styled HTML/CSS/JS
- WebSocket integration
- Sparkline charts (inline SVG polyline)
- Power control slider + toggle
- **Why last:** Consumes all backend features. Can iterate on styling independently.

## Scalability Considerations

| Concern | Current (1 browser) | 5 browsers | Notes |
|---------|---------------------|------------|-------|
| WebSocket connections | 1 connection | 5 connections | Trivial for aiohttp |
| Broadcast cost | 1 JSON serialize + 1 send | 1 serialize + 5 sends | Serialize once, send N times |
| Memory (buffers) | ~1.3 MB (6 * 210 KB) | Same (server-side) | Shared, not per-client |
| History on connect | ~50 KB response | 5 * 50 KB | One-time per connect |
| Poll loop overhead | +1 collect() call/s | Same | Decoding is microseconds |

This is an admin dashboard for one solar installation. Performance is a non-concern.

## Sources

- [aiohttp WebSocket docs (v3.13.3)](https://docs.aiohttp.org/en/stable/web_quickstart.html) -- WebSocket handler pattern
- [aiohttp Web Server Advanced](https://docs.aiohttp.org/en/stable/web_advanced.html) -- WeakSet pattern for client tracking
- [aiohttp multiple WebSocket clients (Issue #2940)](https://github.com/aio-libs/aiohttp/issues/2940) -- broadcast pattern
- [Python deque as ring buffer](https://realpython.com/python-deque/) -- confirmed collections.deque with maxlen
- Existing codebase: `webapp.py`, `proxy.py`, `control.py`, `register_cache.py`, `__main__.py`
