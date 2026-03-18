# Domain Pitfalls: v2.0 Dashboard & Power Control UI

**Domain:** Real-time dashboard + power control UI for solar inverter Modbus proxy
**Researched:** 2026-03-18
**Overall Confidence:** MEDIUM-HIGH (verified against codebase, web research, aiohttp issue tracker)
**Scope:** Pitfalls specific to ADDING dashboard UI, charts, and power control to an existing working Modbus proxy controlling a real 30kW SolarEdge SE30K inverter.

---

## Critical Pitfalls

Mistakes that could damage hardware, cause safety incidents, or require significant rewrites.

### Pitfall 1: Accidental Power Limit via UI Misclick or Slider Drift

**What goes wrong:** A user opens the webapp, accidentally drags the power limit slider to 0%, and the proxy immediately writes `WMaxLimPct=0` to the SolarEdge inverter via the EDPC registers (0xF322). The 30kW inverter drops to zero output. If this happens during peak production, the system loses significant generation. Worse: the SolarEdge inverter persists the last power reduction state in its memory -- even if the proxy restarts or loses connection, the inverter stays throttled until AC power cycle or next morning sunrise.

**Why it happens:** Developers treat power control sliders like volume knobs -- instant feedback, no consequences. But writing to a real inverter is a physical actuator command, not a UI preference. The existing `control.py` validates the range (0-100%) but has no protection against rapid unintended changes.

**Consequences:**
- Immediate loss of up to 30kW generation from a single misclick
- SolarEdge retains the limit even if proxy disconnects (SE command timeout fallback behavior)
- Venus OS may also be sending its own power limit commands simultaneously, creating a conflict

**Prevention:**
- **Confirmation dialog** for any power limit change below current output level (e.g., "Reduce from 85% to 10%? This will cut 22.5kW of production.")
- **Debounce slider input** -- do not send Modbus writes on every `oninput` event. Use `onchange` (mouseup/touchend) with a 500ms debounce minimum
- **Two-step activation**: slider sets the value, separate "Apply" button sends the write
- **Visual danger zone**: red coloring below 20%, amber below 50%
- **Undo button with timeout**: after applying, show "Undo (15s)" that reverts to previous value

**Detection:** Log every power limit write with timestamp, source (webapp vs Venus OS), old value, new value. Alert if more than 3 writes per minute from webapp.

**Phase:** Power Control UI phase -- this is the FIRST thing to get right before any slider is exposed.

**Confidence:** HIGH -- based on codebase analysis of `control.py` and SolarEdge EDPC behavior from [SolarEdge Power Control documentation](https://knowledge-center.solaredge.com/sites/kc/files/application_note_power_control_configuration.pdf) and [community reports of power limits reverting](https://github.com/binsentsu/home-assistant-solaredge-modbus/issues/232).

---

### Pitfall 2: Race Condition Between Venus OS and Webapp Power Control

**What goes wrong:** Venus OS writes `WMaxLimPct=50%` via Modbus (for ESS feed-in limiting). Milliseconds later, the webapp user sets `WMaxLimPct=100%` via the REST API. The proxy forwards 100% to SolarEdge, overriding Venus OS's safety limit. Now the inverter produces full power while Venus OS believes it is throttled to 50%.

This is not theoretical -- the existing codebase in `proxy.py` line 102-124 (`async_setValues`) processes Venus OS Modbus writes, while `webapp.py` would add a separate REST endpoint for the same control path. Both go through `ControlState` but there is no arbitration.

**Why it happens:** The proxy has two control interfaces (Modbus from Venus OS, HTTP from webapp) but no concept of "who owns the power limit right now." Both can write independently.

**Consequences:**
- Venus OS ESS feed-in limiting bypassed -- potential grid compliance violation
- Venus OS displays "Throttled" but inverter runs at full power
- Ping-pong effect: Venus OS re-writes its limit, webapp re-writes its limit, rapid oscillation of inverter output

**Prevention:**
- **Implement control source arbitration** with clear priority: Venus OS > Webapp (always)
- **Override detection**: Track the last writer and timestamp. If Venus OS wrote within the last N seconds, the webapp should show "Venus OS is controlling power limit" and DISABLE the slider
- **Read-only mode by default**: Power control slider starts disabled, requires explicit "Take Manual Control" toggle
- **Venus OS override indicator**: The `shared_ctx["control_state"]` already tracks `wmaxlim_ena` -- extend it with `last_writer: "venus_os" | "webapp"` and `last_write_time`
- **Auto-relinquish**: If webapp takes control, auto-revert to Venus OS control after a configurable timeout (e.g., 5 minutes)

**Detection:** Log every control write with source tag. Dashboard shows "Control Source: Venus OS (auto)" vs "Control Source: Manual (webapp) -- reverts in 4:32".

**Phase:** Power Control UI phase -- must be designed BEFORE the slider endpoint exists.

**Confidence:** HIGH -- based on direct codebase analysis of `proxy.py` `StalenessAwareSlaveContext.async_setValues()` and `webapp.py` architecture.

---

### Pitfall 3: SolarEdge Command Timeout Causes Silent Revert to Fallback

**What goes wrong:** The webapp user sets a power limit of 70%. The proxy writes this to SolarEdge register 0xF322. The SolarEdge EDPC protocol requires periodic refresh of dynamic power commands -- if the inverter does not receive a command update within the "Command Timeout" period (register 0xF310), it reverts to its fallback active power limit (which may be 100% or 0%, depending on configuration).

The current proxy code in `control.py` writes the limit ONCE when Venus OS commands it. It does not periodically refresh. If Venus OS stops sending commands (e.g., because production is stable), the SolarEdge timeout expires and the limit reverts.

**Why it happens:** Developers treat Modbus writes as "set and forget." SolarEdge's EDPC protocol is a watchdog-based system -- it requires the command to be refreshed at least every `CommandTimeout/2` seconds.

**Consequences:**
- Power limit silently reverts to fallback value
- Dashboard shows 70% but inverter is actually at 100% (or 0%)
- Venus OS ESS feed-in limiting breaks because the inverter ignores stale commands

**Prevention:**
- **Implement a periodic command refresh loop**: If a power limit is active, re-write the current limit value to SolarEdge every `CommandTimeout/2` seconds (typically every 30s if timeout is 60s)
- **Read back the actual inverter power limit** from SolarEdge registers and compare to commanded value. Display discrepancy in dashboard as "Commanded: 70% / Actual: 100% -- MISMATCH"
- **Set CommandTimeout register (0xF310) to a known value** on proxy startup (e.g., 120 seconds) so the refresh interval is predictable
- **Dashboard warning**: If command refresh fails 2+ times, show "Power limit may have reverted -- check inverter"

**Detection:** Poll SolarEdge power output and compare to expected output under the current limit. If output exceeds limit by >10%, the command has likely reverted.

**Phase:** Power Control backend phase -- this is infrastructure, not UI. Must be implemented before the slider is useful.

**Confidence:** MEDIUM -- SolarEdge EDPC timeout behavior confirmed via [community discussion](https://github.com/WillCodeForCats/solaredge-modbus-multi/discussions/207) and [SolarEdge power control documentation](https://knowledge-center.solaredge.com/sites/kc/files/application_note_power_control_configuration.pdf). Exact register behavior for SE30K needs field verification.

---

### Pitfall 4: WebSocket Memory Leak on Long-Running Connections

**What goes wrong:** The dashboard opens a WebSocket for live data streaming (1-second updates). The browser tab stays open for days. The aiohttp server accumulates memory because: (a) send buffers grow when the browser tab is backgrounded (browser throttles WebSocket processing), (b) disconnected clients are not detected promptly, (c) each WebSocket connection holds references to message history.

On the LXC container (limited RAM), this eventually causes OOM and the entire proxy service crashes -- including the Modbus proxy that Venus OS depends on.

**Why it happens:** aiohttp WebSocket has known issues with memory accumulation on long-running connections. Multiple open GitHub issues document this: [#2309 (abrupt disconnect detection)](https://github.com/aio-libs/aiohttp/issues/2309), [#6325 (memory not released after disconnect)](https://github.com/aio-libs/aiohttp/issues/6325), [#10528 (memory leak on server)](https://github.com/aio-libs/aiohttp/issues/10528). The send buffer grows when the consumer (browser) is slower than the producer (server pushing updates every second).

**Consequences:**
- Proxy process memory grows unbounded
- OOM kill takes down the entire service (Modbus proxy + webapp)
- Venus OS loses its "Fronius inverter" until systemd restarts the service

**Prevention:**
- **Use Server-Sent Events (SSE) instead of WebSocket** for the live data feed. SSE is unidirectional (server-to-client only, which is all we need for dashboard updates), has simpler lifecycle management, built-in browser reconnection, and lower memory footprint. Power control commands go via normal HTTP POST, not through the data stream
- **If WebSocket is required**: configure heartbeat with `ws_response = web.WebSocketResponse(heartbeat=10.0)` to detect dead connections within 20 seconds
- **Limit concurrent connections**: Maximum 5 WebSocket connections (it's a single-user LAN tool). Reject with 503 if exceeded
- **Bound the send buffer**: If a message cannot be sent within 5 seconds (client is backlogged), drop the message rather than buffering it. For dashboard data, a dropped frame is better than OOM
- **Monitor connection count and memory**: Add `/api/health` fields for `websocket_connections` and `process_memory_mb`

**Detection:** Add process memory to health endpoint. Alert (log warning) if memory exceeds 100MB or connection count exceeds 5.

**Phase:** Dashboard live data phase -- architectural decision (SSE vs WebSocket) must be made before implementation.

**Confidence:** HIGH -- verified against aiohttp GitHub issues and real-world memory leak reports.

---

## Moderate Pitfalls

### Pitfall 5: Ring Buffer Overflow / Memory Growth for Sparkline Data

**What goes wrong:** The 60-minute sparkline requires storing ~3,600 data points (1 per second) per metric. With multiple metrics (total power, 3x phase power, voltage, current, frequency, temperature = ~10 metrics), that is 36,000 data points in memory. Using Python dicts with timestamps, this can consume significantly more memory than expected due to Python object overhead (~200 bytes per dict vs ~16 bytes for a raw tuple).

**Why it happens:** Developers use `collections.deque(maxlen=3600)` which is correct for bounding, but store rich objects (`{"timestamp": ..., "power": ..., "voltage": ...}`) instead of compact tuples or numpy arrays. Python object overhead is 5-10x the raw data size.

**Prevention:**
- Use `collections.deque(maxlen=3600)` -- this IS the right approach for this scale
- Store tuples `(timestamp, value)` not dicts -- 3x more memory efficient
- One deque per metric, not one deque of dicts containing all metrics
- For 10 metrics x 3,600 points x ~100 bytes/tuple = ~3.6MB. Acceptable for LXC, but monitor it
- Do NOT use numpy (adds dependency for minimal benefit at this scale)
- **Thread safety**: `deque.append()` is thread-safe in CPython (GIL), but if using asyncio (no threads), this is not a concern. Do NOT add unnecessary locking

**Detection:** Include ring buffer size and approximate memory in health endpoint.

**Phase:** Sparkline/chart phase.

**Confidence:** HIGH -- Python memory model well understood, `deque(maxlen=N)` behavior verified.

---

### Pitfall 6: Venus OS UI Color/Style Mismatch Breaks User Trust

**What goes wrong:** The dashboard claims to replicate "Venus OS style" but uses wrong colors, wrong fonts, wrong widget proportions. The user (who sees the real Venus OS daily) immediately notices the mismatch, perceives the tool as unprofessional, and loses trust in the data it displays.

**Why it happens:** Developers pick "close enough" dark theme colors instead of extracting exact values from Venus OS. Venus OS uses a very specific design language (Victron's GUI-V2 framework based on Qt/QML) with specific color codes, border radii, typography, and widget spacing.

The current `index.html` already has a custom dark theme (`--bg: #1a1a2e`, `--accent: #e94560`) that does NOT match Venus OS. Venus OS uses different blues, different greens for "OK" status, different gauge styles.

**Prevention:**
- **Extract exact colors from Venus OS screenshots** or the [Venus OS GUI source](https://github.com/victronenergy/gui-v2). Key colors to match:
  - Background: Venus OS dark navy, not generic dark blue
  - Accent/highlight: Venus OS uses specific teal/cyan tones for active elements
  - Status green: Venus OS's "running" green is a specific shade
  - Warning amber and error red: must match exactly
- **Match widget patterns**: Venus OS uses specific tile/card layouts with rounded corners, specific padding, specific header bar style
- **Do NOT try to be pixel-perfect** -- match the feel, not the pixels. Use the same color palette, similar spacing, same information hierarchy
- **Side-by-side comparison test**: Open Venus OS remote console and webapp side by side. If they feel like different products, iterate

**Detection:** User feedback. Side-by-side screenshot comparison during review.

**Phase:** Dashboard UI phase -- colors and layout should be defined in a CSS variables file BEFORE building widgets.

**Confidence:** MEDIUM -- Venus OS visual style known from screenshots and GUI source repo, but exact color extraction not performed in this research.

---

### Pitfall 7: Dashboard Update Rate Causes Browser Performance Issues

**What goes wrong:** The dashboard receives 1-second updates and re-renders the entire DOM on each update. With sparkline charts (Canvas/SVG redraws), multiple gauges, 3-phase detail tables, and status indicators all updating simultaneously, the browser struggles. Mobile browsers and older tablets (common for solar monitoring) drop frames, causing laggy interaction and high CPU usage.

**Why it happens:** Developers build the dashboard on a fast desktop browser and don't test on the actual viewing device. Single-file HTML (the current architecture) means no framework-level optimization (virtual DOM, batched updates).

**Consequences:**
- Dashboard feels sluggish and unresponsive
- Browser tab consumes excessive CPU/battery on always-on monitoring displays
- Power control slider becomes unresponsive during chart redraws

**Prevention:**
- **Throttle visual updates to 2-second intervals** even if data arrives every second. Human perception of power changes does not require sub-second resolution
- **Only update changed values**: Compare new data to displayed data, skip DOM updates for unchanged fields
- **Use CSS transforms for animations** (hardware accelerated) instead of DOM manipulation
- **Sparkline chart**: Use a single Canvas element with incremental draw (shift pixels left, draw new point) instead of full redraw. Pre-allocate the pixel buffer
- **Lazy render off-screen sections**: If the inverter detail panel is collapsed, do not update its DOM
- **Test on a Raspberry Pi browser** (Chromium on RPi4) since that is a realistic Venus OS companion device

**Detection:** Use browser Performance tab to measure frame times. Target: <16ms per frame (60fps) or at worst <50ms (20fps).

**Phase:** Dashboard UI phase -- must be considered during chart library selection and update architecture.

**Confidence:** HIGH -- standard web performance knowledge, applicable to single-file HTML architecture.

---

### Pitfall 8: Power Control UI Shows Stale State After Network Interruption

**What goes wrong:** The user has the dashboard open, sets power limit to 60%. The LAN has a brief interruption (5 seconds). The WebSocket/SSE reconnects, but the dashboard still shows "Power Limit: 60%" from its local state. Meanwhile, during the disconnection, Venus OS overwrote the limit to 30% for ESS feed-in control. The user sees 60% but the inverter is at 30%.

**Why it happens:** Client-side state diverges from server-side state during disconnections. The reconnection logic restores the data stream but does not force a full state reconciliation.

**Consequences:**
- User makes decisions based on stale control state
- User tries to "increase" from 60% to 80%, not knowing actual state is 30% -- this doubles the output unexpectedly

**Prevention:**
- **On every reconnect, force a full state fetch** via HTTP GET before resuming the live stream. The reconnection handler should: (1) fetch `/api/control-state`, (2) update all UI elements, (3) then subscribe to live stream
- **Server-side authoritative state**: The dashboard should ALWAYS show server state, never cached client state. Every live update should include control state, not just sensor data
- **Visual "reconnecting" indicator**: While disconnected, grey out the entire dashboard and show "Reconnecting..." -- do NOT show stale data as if it were live
- **Timestamp on every data frame**: Include `server_time` in every update. If `server_time` is >5 seconds old, show a staleness warning

**Detection:** Deliberately disconnect WiFi for 10 seconds during testing. Verify dashboard state matches server state after reconnection.

**Phase:** Dashboard live data phase -- reconnection logic is part of the data streaming architecture.

**Confidence:** HIGH -- standard real-time UI pattern.

---

### Pitfall 9: Single-File HTML Becomes Unmaintainable at Dashboard Scale

**What goes wrong:** The v1.0 architecture uses a single `index.html` file (currently ~200 lines for a simple config UI). The v2.0 dashboard adds: Venus OS styled layout, live data widgets, sparkline charts, power control panel, 3-phase detail view, register viewer (existing), configuration panel (existing). This easily reaches 2,000-4,000 lines in a single file with inline CSS and JavaScript.

**Why it happens:** "No build tooling" was a good v1.0 decision for a simple config page. But a full dashboard with charts, live data, and interactive controls exceeds the complexity threshold where single-file HTML becomes a maintenance burden.

**Consequences:**
- CSS conflicts between sections (global styles leak)
- JavaScript global scope pollution
- Impossible to test individual components
- Merge conflicts on every change
- Developer productivity drops as the file grows

**Prevention:**
- **Keep single-file HTML** (no build tooling constraint is valid) but use disciplined organization:
  - CSS: Use BEM naming convention or CSS custom properties scoped by section
  - JavaScript: Use IIFE modules `(function() { /* chart code */ })()`  or ES module pattern with `<script type="module">`
  - Structure: Clear section comments, consistent ordering (CSS -> HTML -> JS)
- **Extract chart rendering** into a separate inline `<script>` block with a clean API: `SparklineChart.init(canvas, options)`, `SparklineChart.addPoint(value)`
- **Consider loading separate JS files** via `importlib.resources` (serve `/static/dashboard.js`, `/static/chart.js`) without needing npm/webpack. This keeps "no build tooling" while allowing file separation
- **Component pattern**: Each dashboard widget is a function that creates its DOM subtree and returns an update function: `const widget = createPowerGauge(container); widget.update(newValue);`

**Detection:** If any single section of the HTML file exceeds 500 lines, it should be extracted.

**Phase:** Dashboard UI phase -- file organization decision should be made at the START, not after the file is already 3,000 lines.

**Confidence:** HIGH -- based on current codebase architecture in `webapp.py` (serves from `importlib.resources`).

---

## Minor Pitfalls

### Pitfall 10: Sparkline Y-Axis Scale Jumps Confuse Users

**What goes wrong:** The sparkline chart auto-scales the Y-axis. During a cloud passing, power drops from 25kW to 5kW. The chart rescales, making the 5kW reading look like it fills the same visual space as the previous 25kW. The user glances at the chart and thinks power is still high.

**Prevention:**
- **Fixed Y-axis maximum** based on inverter nameplate rating (30kW for SE30K). The chart always shows 0-30kW range
- Show the numeric value alongside the chart, not embedded in it
- Use a subtle horizontal line at the current value's position to anchor perception

**Phase:** Chart/sparkline phase.

---

### Pitfall 11: Temperature and Status Registers Misinterpreted

**What goes wrong:** The dashboard displays raw register values for temperature (e.g., "3420") instead of applying the scale factor (SF=-1, actual = 342.0 C -- still wrong, probably 34.2 C with SF=-2). The `register_cache.py` stores raw uint16 values. The webapp must apply scale factors correctly for display.

**Prevention:**
- Create a display decoder layer that applies scale factors from the SunSpec model definitions
- Temperature: raw value * 10^(Temp SF). SF is in register 40106
- Status: map numeric status codes to human-readable strings ("1=OFF, 2=SLEEPING, 3=STARTING, 4=MPPT, 5=THROTTLED, 6=SHUTTING_DOWN, 7=FAULT")
- Unit test every display conversion

**Phase:** Dashboard data display phase.

---

### Pitfall 12: No Visual Distinction Between "No Data" and "Zero Production"

**What goes wrong:** At night, the inverter produces 0W. The dashboard shows "0 W". During a connection failure, the dashboard also shows "0 W" (or the last cached value, which might be 0W from night mode). The user cannot distinguish "inverter is fine, no sun" from "proxy lost connection, data is stale."

**Prevention:**
- **Always show data age**: "0 W (2s ago)" vs "0 W (stale -- 45s ago)"
- **Use the existing `cache.is_stale` flag** from `register_cache.py` to visually differentiate: fresh data = normal styling, stale data = dimmed with warning icon
- **Show connection state prominently**: The existing `/api/status` endpoint returns `solaredge` connection state -- display it as a persistent header badge
- **Night mode indicator**: When `ConnectionState.NIGHT_MODE` is active (from `connection.py`), show a moon icon and "Night Mode" label instead of zero values

**Phase:** Dashboard UI phase -- visual state indicators should be designed with the initial layout.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Dashboard Layout (CSS/HTML) | Venus OS color mismatch (#6) | Extract exact Venus OS color palette FIRST, define as CSS variables |
| Dashboard Layout (CSS/HTML) | Single file unmaintainability (#9) | Decide file organization pattern before writing widgets |
| Live Data Streaming | WebSocket memory leak (#4) | Use SSE instead of WebSocket; bound connections |
| Live Data Streaming | Stale state after reconnect (#8) | Full state fetch on every reconnect |
| Sparkline Charts | Browser performance (#7) | Throttle to 2s updates, incremental canvas draw |
| Sparkline Charts | Y-axis auto-scale confusion (#10) | Fixed 0-30kW Y-axis |
| Ring Buffer Backend | Memory growth (#5) | Tuple-based deques, monitor in health endpoint |
| Power Control UI | Accidental power change (#1) | Confirmation dialog, debounced slider, two-step apply |
| Power Control UI | Venus OS race condition (#2) | Source arbitration, Venus OS always wins |
| Power Control Backend | SE command timeout revert (#3) | Periodic command refresh loop |
| Inverter Detail View | Scale factor misinterpretation (#11) | Display decoder layer with unit tests |
| All Dashboard Phases | No data vs zero distinction (#12) | Data age display, connection state badge |

## Sources

- [aiohttp WebSocket disconnect detection issue #2309](https://github.com/aio-libs/aiohttp/issues/2309)
- [aiohttp memory not released after WebSocket disconnect #6325](https://github.com/aio-libs/aiohttp/issues/6325)
- [aiohttp memory leak on server #10528](https://github.com/aio-libs/aiohttp/issues/10528)
- [aiohttp growing memory in web_protocol.py #10671](https://github.com/aio-libs/aiohttp/issues/10671)
- [SolarEdge Power Control Options Application Note](https://knowledge-center.solaredge.com/sites/kc/files/application_note_power_control_configuration.pdf)
- [SolarEdge power limit overruled community report](https://github.com/binsentsu/home-assistant-solaredge-modbus/issues/232)
- [SolarEdge power control functions discussion](https://github.com/WillCodeForCats/solaredge-modbus-multi/discussions/207)
- [Victron dbus-fronius driver](https://github.com/victronenergy/dbus-fronius)
- [SSE vs WebSocket comparison (2026)](https://www.nimbleway.com/blog/server-sent-events-vs-websockets-what-is-the-difference-2026-guide)
- [WebSocket heartbeat/ping-pong configuration guide](https://oneuptime.com/blog/post/2026-01-24-websocket-heartbeat-ping-pong/view)
- [Energy dashboard UX best practices](https://www.aufaitux.com/blog/energy-management-dashboard-design/)
- Project codebase: `control.py`, `proxy.py`, `register_cache.py`, `webapp.py`, `connection.py`, `static/index.html`
