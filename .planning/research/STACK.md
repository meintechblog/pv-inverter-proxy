# Technology Stack: v2.0 Dashboard & Power Control

**Project:** Venus OS Fronius Proxy
**Researched:** 2026-03-18
**Focus:** Stack additions for Venus OS styled dashboard, real-time charts, power control UI
**Overall Confidence:** HIGH

## Existing Stack (DO NOT CHANGE)

| Technology | Version | Purpose |
|------------|---------|---------|
| Python 3.12 | 3.12 | Runtime |
| pymodbus | 3.8+ | Modbus TCP client/server |
| aiohttp | 3.x | HTTP server + WebSocket support (built-in) |
| structlog | latest | Structured logging |
| PyYAML | latest | Configuration |

The v1.0 stack is validated and shipped. The entire v2.0 dashboard requires **zero new Python or JavaScript dependencies**.

## New Stack Additions

### Real-Time Updates: aiohttp WebSocket (ZERO new dependencies)

**Decision:** Use aiohttp's built-in `WebSocketResponse`. No new Python packages needed.

**Why WebSocket over SSE (Server-Sent Events):**
- Bidirectional: Power control commands (slider changes, enable/disable) go client-to-server; live data goes server-to-client. SSE is unidirectional (server-to-client only), so you would still need separate POST endpoints for commands. WebSocket handles both in one connection.
- aiohttp has first-class WebSocket support via `web.WebSocketResponse()`. SSE requires manual `StreamResponse` with keep-alive hacks.
- Lower overhead: single TCP connection vs HTTP polling or SSE + separate POST requests.

**Why WebSocket over current HTTP polling:**
- Current frontend polls `/api/status`, `/api/health`, `/api/registers` every 2 seconds -- three HTTP requests per cycle. WebSocket replaces all three with a single pushed JSON message.
- Slider feedback needs sub-200ms round trips. HTTP polling at 2s intervals cannot provide responsive power control UX.
- Server pushes only when data changes, reducing unnecessary traffic.

**Pattern:** Server-push broadcast from poller loop to all connected WebSocket clients.

```python
# In webapp.py -- no new imports beyond aiohttp.web
import weakref

# On app startup:
app["ws_clients"] = weakref.WeakSet()

# WebSocket handler:
async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app["ws_clients"].add(ws)
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            # Handle power control commands from UI
            data = json.loads(msg.data)
            await handle_ws_command(request.app, data)
    return ws

# Broadcast from poller (called every poll cycle):
async def broadcast_state(app, state_dict):
    payload = json.dumps(state_dict)
    for ws in set(app["ws_clients"]):
        try:
            await ws.send_str(payload)
        except Exception:
            pass  # dead connections auto-removed by WeakSet
```

**Confidence:** HIGH -- verified against [aiohttp 3.13.3 official docs](https://docs.aiohttp.org/en/stable/web_quickstart.html). WebSocket support is stable, well-documented, and already a dependency.

### Charting: Inline SVG Sparklines (ZERO new dependencies)

**Decision:** Hand-rolled SVG sparklines in vanilla JavaScript. No charting library.

**Why no library at all:**
- The requirement is 60-minute mini-sparklines for power/voltage/frequency. This is a polyline in an SVG element -- roughly 15 lines of JavaScript.
- Adding even a tiny library (fnando/sparkline at ~1KB gzipped, or mitjafelicijan/sparklines via CDN) creates an external dependency for a single-file HTML app served from `importlib.resources`. CDN means internet dependency on a LAN-only device. Bundling means build tooling or inlining third-party code.
- The existing frontend already uses vanilla JS with zero external dependencies. Keep it that way.

**Implementation approach:**
```javascript
function drawSparkline(svgEl, data, color) {
    const w = svgEl.clientWidth, h = svgEl.clientHeight;
    const max = Math.max(...data), min = Math.min(...data);
    const range = max - min || 1;
    const points = data.map((v, i) =>
        `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`
    ).join(' ');
    svgEl.innerHTML = `<polyline points="${points}" fill="none"
        stroke="${color}" stroke-width="1.5"/>`;
}
```

That is the entire charting "library." It renders a smooth sparkline that updates every poll cycle by rewriting the SVG polyline. No canvas, no library, no build step.

**Ring buffer (Python side):** `collections.deque(maxlen=3600)` at 1 sample/second = 60 minutes. One deque per metric (AC Power, Phase A/B/C current, voltage, frequency, temperature). Serialized as a JSON array in the WebSocket broadcast -- send only every 10th sample or on initial connect to avoid bloating every message.

**Confidence:** HIGH -- pure SVG/JS, no external verification needed. The pattern is well-established.

### Venus OS Theme: CSS Custom Properties (ZERO new dependencies)

**Decision:** Extract Venus OS gui-v2 color palette into CSS custom properties. No CSS framework.

**Why not Tailwind/Bootstrap/etc:**
- Single-file HTML frontend constraint. CSS frameworks require build tooling or massive CDN includes.
- The existing CSS is already clean custom properties. Just swap the color values to match Venus OS.
- Venus OS gui-v2 uses QML, not CSS. We translate the color tokens, not import a framework.

**Official Venus OS gui-v2 Dark Theme Colors** (extracted from `victronenergy/gui-v2/themes/color/ColorDesign.json` and `Dark.json`):

```css
:root {
    /* Venus OS Core Palette */
    --ve-blue: #387DC5;
    --ve-blue-light: #73A2D3;
    --ve-blue-dim: #27588A;
    --ve-orange: #F0962E;
    --ve-red: #F35C58;
    --ve-green: #72B84C;

    /* Venus OS Dark Theme Backgrounds */
    --ve-bg-primary: #141414;      /* Gray 1 - deepest background */
    --ve-bg-surface: #272622;      /* Gray 2 - card/panel background */
    --ve-bg-elevated: #504F4B;     /* Gray 3 - elevated elements */
    --ve-border: #64635F;          /* Gray 4 - borders */

    /* Venus OS Text */
    --ve-text: #FAF9F5;            /* Gray 9 - primary text */
    --ve-text-secondary: #DCDBD7;  /* Gray 6 - secondary text */
    --ve-text-dim: #969591;         /* Gray 5 - dim/muted text */

    /* Venus OS Specific UI */
    --ve-settings-bg: #11253B;     /* Settings breadcrumb background */
    --ve-toast-info: #295C91;      /* Informative toast */
    --ve-toast-warning: #BD7624;   /* Warning toast */
    --ve-toast-error: #BF4845;     /* Error toast */
    --ve-critical-bg: #AA403E;     /* Critical background */
    --ve-slider-handle: #1D1D1B;   /* Slider handle background */
    --ve-slider-handle-border: #FAF9F5; /* Slider handle border */
    --ve-slider-separator: #C3D8EE; /* Slider track separator */
}
```

**Migration from current theme:** The existing `index.html` uses `--bg: #1a1a2e` (dark blue-purple) and `--accent: #e94560` (pinkish red). These shift to Venus OS's warm grays (`#141414`, `#272622`) and Victron blue (`#387DC5`). The overall feel changes from "generic dark tech" to "authentic Victron dashboard."

**Confidence:** HIGH -- colors extracted directly from the official `victronenergy/gui-v2` repository.

### Power Control UI: Native HTML Range + Toggle (ZERO new dependencies)

**Decision:** Use native HTML `<input type="range">` for the power limit slider, styled with CSS to match Venus OS. Use a CSS-only toggle switch for enable/disable.

**Why not a UI component library:**
- Single-file HTML constraint. No React, no Web Components library.
- Native range inputs are styleable with `-webkit-slider-*` and `::-moz-range-*` pseudo-elements. The Venus OS slider style (dark handle, light track) is achievable with ~20 lines of CSS.
- The toggle is a `<label>` wrapping a hidden checkbox with CSS pseudo-elements.

**Implementation sketch:**
```html
<!-- Power limit slider -->
<input type="range" id="power-limit" min="0" max="100" step="1"
    class="ve-slider" value="100">
<span id="power-limit-value">100%</span>

<!-- Enable/disable toggle -->
<label class="ve-toggle">
    <input type="checkbox" id="power-enable">
    <span class="ve-toggle-track"></span>
</label>
```

Commands sent via WebSocket (not REST POST), so the slider can send updates as the user drags (debounced at ~200ms) with immediate visual feedback. The WebSocket message format:

```json
{"cmd": "set_power_limit", "value": 75}
{"cmd": "set_power_enable", "value": true}
```

**Confidence:** HIGH -- standard HTML/CSS patterns.

## What NOT To Add

| Temptation | Why Not |
|------------|---------|
| Chart.js / D3.js / Plotly | Overkill for sparklines. 200KB+ for what 15 lines of SVG code does. Breaks single-file constraint. |
| Socket.io (python-socketio) | aiohttp has native WebSocket support. Socket.io adds protocol overhead, client library dependency, and complexity for zero benefit. |
| Tailwind CSS / Bootstrap | Requires CDN (no internet on LAN) or build tooling. Existing CSS custom properties work fine. |
| React / Vue / Svelte | Single-file HTML constraint. Vanilla JS is sufficient for this UI complexity. Would require build tooling. |
| Flask-SocketIO | Wrong framework. Already using aiohttp. |
| Any Python dashboard library (Dash, Streamlit, Panel) | These replace the entire web stack. We have a working aiohttp server. |
| External CDN for anything | LXC container is on a LAN. No guaranteed internet access. All assets must be self-contained. |
| SSE (Server-Sent Events) | Unidirectional. Would still need POST endpoints for power control commands. WebSocket is cleaner for bidirectional. |
| websockets package | aiohttp already includes WebSocket support. Adding `websockets` package would be redundant. |
| fnando/sparkline | ~1KB gzipped, nice API, but adds a dependency for something trivially implementable in 15 LOC. |
| mitjafelicijan/sparklines | Zero-dep library with CDN at `cdn.jsdelivr.net`, but CDN is unreliable on LAN-only device. |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Real-time transport | aiohttp WebSocket (built-in) | SSE via StreamResponse | SSE is unidirectional; power control needs bidirectional |
| Real-time transport | aiohttp WebSocket (built-in) | HTTP polling (current) | 2s polling is too slow for slider feedback; wastes bandwidth with 3 requests per cycle |
| Charting | Inline SVG polyline (15 LOC) | @fnando/sparkline (~1KB) | External dependency for trivial functionality; CDN not available on LAN |
| Charting | Inline SVG polyline (15 LOC) | mitjafelicijan/sparklines (CDN) | CDN dependency on LAN-only device |
| CSS theme | Venus OS custom properties | Tailwind CSS | Build tooling required; overkill for single-file HTML |
| UI controls | Native HTML range/checkbox | shoelace Web Components | Dependency; build tooling; overkill |

## Installation

```bash
# No new packages needed. Zero additions to requirements.
# Everything is built with existing aiohttp + vanilla JS/CSS/SVG.
```

## Python-Side Additions (no new packages)

| Component | Implementation | Module |
|-----------|---------------|--------|
| Ring buffer for sparkline data | `collections.deque(maxlen=3600)` | `collections` (stdlib) |
| WebSocket broadcast | `aiohttp.web.WebSocketResponse` | already installed |
| JSON serialization of state | `json.dumps()` | `json` (stdlib) |
| Timestamp tracking | `time.monotonic()` | `time` (stdlib) |
| Client tracking | `weakref.WeakSet()` | `weakref` (stdlib) |

## Integration with Existing Architecture

The existing `webapp.py` creates an `aiohttp.web.Application` with REST endpoints. The WebSocket additions integrate cleanly:

1. **Add route:** `app.router.add_get("/ws", ws_handler)` alongside existing REST routes
2. **Store clients:** `app["ws_clients"] = weakref.WeakSet()` in `create_webapp()`
3. **Broadcast hook:** The existing poller loop in `proxy.py` calls `broadcast_state()` after each successful poll, pushing fresh data to all connected WebSocket clients
4. **Fallback:** Keep existing REST endpoints (`/api/status`, `/api/health`, `/api/registers`) for backward compatibility and initial page load. WebSocket takes over for live updates after connection.
5. **Ring buffers:** Add to `shared_ctx` dict alongside existing `cache` and `poll_counter`

The single-process asyncio architecture means WebSocket broadcast happens in the same event loop as Modbus polling -- no IPC, no threads, no race conditions.

## Summary

**Zero new Python dependencies. Zero new JavaScript dependencies. Zero CDN includes. Zero build tooling.**

The entire v2.0 dashboard is achievable by:
1. Adding a WebSocket endpoint to the existing aiohttp webapp (built-in capability)
2. Adding CSS custom properties with Venus OS official color palette
3. Writing ~15 lines of SVG sparkline code in JavaScript
4. Styling native HTML range/checkbox inputs to match Venus OS
5. Using `collections.deque` for 60-minute ring buffers

This keeps the single-file HTML architecture, zero-dependency philosophy, and LAN-only deployment constraint fully intact.

## Sources

- [aiohttp WebSocket docs (v3.13.3)](https://docs.aiohttp.org/en/stable/web_quickstart.html) -- HIGH confidence
- [aiohttp Web Server Advanced -- WebSocket broadcast pattern](https://docs.aiohttp.org/en/stable/web_advanced.html) -- HIGH confidence
- [aiohttp multiple WebSocket clients (Issue #2940)](https://github.com/aio-libs/aiohttp/issues/2940) -- HIGH confidence
- [Venus OS gui-v2 theme directory](https://github.com/victronenergy/gui-v2/tree/main/themes/color) -- HIGH confidence
- [Venus OS gui-v2 ColorDesign.json (raw)](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/ColorDesign.json) -- HIGH confidence, direct source
- [Venus OS gui-v2 Dark.json (raw)](https://raw.githubusercontent.com/victronenergy/gui-v2/main/themes/color/Dark.json) -- HIGH confidence, direct source
- [Victron blue color (RAL5012 / ~#00539B)](https://communityarchive.victronenergy.com/questions/75079/victron-blue-color-code.html) -- MEDIUM confidence, community source
- [fnando/sparkline (evaluated, rejected)](https://github.com/fnando/sparkline) -- ~1KB gzipped, MIT license
- [mitjafelicijan/sparklines (evaluated, rejected)](https://github.com/mitjafelicijan/sparklines) -- CDN at jsdelivr, BSD license
