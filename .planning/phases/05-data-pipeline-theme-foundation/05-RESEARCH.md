# Phase 5: Data Pipeline & Theme Foundation - Research

**Researched:** 2026-03-18
**Domain:** Backend data pipeline (register decoding, time series), frontend restructure (3-file split, Venus OS theme)
**Confidence:** HIGH

## Summary

Phase 5 builds two independent foundations: (1) a backend DashboardCollector that decodes raw Modbus registers into physical units on every poll cycle, feeding a TimeSeriesBuffer ring buffer for 60-minute history; and (2) a frontend restructure that splits the current single-file `index.html` into `index.html` + `style.css` + `app.js` with Venus OS visual identity.

The existing codebase is well-prepared for both. The `shared_ctx` dict pattern in `proxy.py` provides the hook point for DashboardCollector integration (3-4 lines added to `_poll_loop`). The `webapp.py` already serves static files via `importlib.resources`, which extends naturally to serve `.css` and `.js`. Scale factor decoding logic is partially present in `registers_handler` and `REGISTER_MODELS` provides the complete register layout.

**Primary recommendation:** Build backend (DashboardCollector + TimeSeriesBuffer) first with tests, then restructure frontend. No WebSocket yet -- Phase 5 delivers the data pipeline and theme, Phase 6 adds real-time push.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Venus OS Grundpalette aus gui-v2: #387DC5 (primary blue), #141414 (background), #FAF9F5 (text), #969591 (dim text)
- Eigene Akzente erlaubt -- Victron Blau (#387DC5) als Akzentfarbe
- Kein exakter Pixel-Clone, aber erkennbar Venus OS inspiriert
- Eigenes Proxy-Branding: kleines Logo/Icon fuer den Proxy Service, Titel "Venus OS Fronius Proxy"
- Kein Victron Logo (Copyright), aber Victron-Farbschema
- Venus OS Widget-Style: abgerundete Panels mit Victron-typischem Border-Style, aehnlich GX Touch Display
- Cards/Panels folgen dem Venus OS Designsystem
- Sidebar Navigation links mit Icons -- Dashboard | Config | Registers (wie Venus OS GX Touch)
- Voll responsive -- Desktop, Tablet UND Handy
- Kompakter Header: Logo + "Venus OS Fronius Proxy" + Connection Status Dots, schlank
- Sidebar collapsed auf Mobile zu Icon-only oder Hamburger-Menue
- Kompletter Datensatz -- alle Register decoded mit Scale Factors, Control-Status inclusive
- 3-File Split: index.html + style.css + app.js via importlib.resources
- DashboardCollector: full dataset decoded with scale factors, control status inclusive

### Claude's Discretion
- Power Gauge Darstellung (Tacho vs Zahl vs Bar)
- Exact spacing, typography, icon choices
- Sidebar Icon-Set
- Mobile breakpoints
- Ring Buffer sampling rate (1/s vs 1/min)

### Deferred Ideas (OUT OF SCOPE)
- None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-02 | DashboardCollector -- decoded Inverter-Daten einmal pro Poll-Cycle | Architecture patterns: DashboardCollector class, register decoding with scale factors from REGISTER_MODELS, integration via shared_ctx callback |
| INFRA-03 | TimeSeriesBuffer -- 60-min Ring Buffer fuer Sparklines (collections.deque) | Architecture patterns: TimeSeriesBuffer with dataclass Sample, deque(maxlen=3660), one buffer per metric |
| INFRA-04 | 3-File Split -- index.html + style.css + app.js (statt single-file) | Architecture patterns: importlib.resources serving pattern, static file handlers, content-type mapping |
| DASH-01 | Venus OS themed UI (exakte Farben #387DC5/#141414, Fonts, Widget-Style) | Standard stack: CSS custom properties with Venus OS gui-v2 palette, sidebar layout, responsive breakpoints |

</phase_requirements>

## Standard Stack

### Core (ZERO new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiohttp | >=3.10,<4.0 | HTTP server, static file serving | Already installed; serves index.html via importlib.resources |
| collections.deque | stdlib | Ring buffer for TimeSeriesBuffer | O(1) append, automatic maxlen eviction, zero deps |
| dataclasses | stdlib | Sample dataclass for time series entries | Slots=True for memory efficiency |
| importlib.resources | stdlib | Serve static files from package | Already used for index.html, extend to .css/.js |
| time.monotonic | stdlib | Timestamps for time series | Monotonic, no clock drift issues |
| json | stdlib | Snapshot serialization | For /api/dashboard REST endpoint |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| struct | stdlib | int16 signed conversion for scale factors | When SF value > 32767 needs sign extension |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dataclass Sample | Named tuple | Dataclass with slots is equally fast, more readable |
| deque(maxlen) | array.array | Array is more compact but lacks automatic eviction |
| importlib.resources per-file | aiohttp.web.static | web.static requires a directory path; importlib.resources works with packaged data |

**Installation:**
```bash
# No new packages needed. Zero additions to requirements.
```

## Architecture Patterns

### Recommended Project Structure
```
src/venus_os_fronius_proxy/
    dashboard.py          # NEW: DashboardCollector class
    timeseries.py         # NEW: TimeSeriesBuffer + Sample
    static/
        __init__.py       # existing (empty)
        index.html        # REWRITTEN: shell with sidebar layout
        style.css         # NEW: Venus OS themed CSS
        app.js            # NEW: frontend logic (polling, DOM updates)
    webapp.py             # MODIFIED: add static file handlers for .css/.js
    proxy.py              # MODIFIED: add collector callback (3-4 lines)
    __main__.py           # MODIFIED: create DashboardCollector, add to shared_ctx
```

### Pattern 1: DashboardCollector -- Register Decoding

**What:** Class that reads raw registers from `cache.datablock`, applies SunSpec scale factors, and produces a structured snapshot dict.

**When to use:** Called once per successful poll cycle in `_poll_loop`.

**Example:**
```python
# Source: existing REGISTER_MODELS in webapp.py + ARCHITECTURE.md design
from dataclasses import dataclass
from venus_os_fronius_proxy.register_cache import RegisterCache

# SunSpec Model 103 base address (inverter model)
MODEL_103_BASE = 40069
# pymodbus internal offset (+1)
_PB_OFFSET = 1

# SunSpec operating status codes
INVERTER_STATUS = {
    1: "OFF",
    2: "SLEEPING",
    3: "STARTING",
    4: "MPPT",
    5: "THROTTLED",
    6: "SHUTTING_DOWN",
    7: "FAULT",
    8: "STANDBY",
}

class DashboardCollector:
    def __init__(self):
        self.buffers: dict[str, TimeSeriesBuffer] = { ... }
        self._last_snapshot: dict | None = None

    def collect(self, cache: RegisterCache, control_state=None) -> dict:
        """Decode registers, update buffers, return snapshot."""
        db = cache.datablock

        # Read scale factors first (they rarely change but are needed for all values)
        current_sf = self._read_int16(db, 40075)  # AC Current SF
        voltage_sf = self._read_int16(db, 40082)  # AC Voltage SF
        power_sf = self._read_int16(db, 40084)    # AC Power SF
        freq_sf = self._read_int16(db, 40086)     # AC Frequency SF
        # ... etc

        # Decode values: raw * 10^SF
        ac_power = db.getValues(40083 + _PB_OFFSET, 1)[0] * (10 ** power_sf)
        # ... etc

        snapshot = {"ts": time.time(), "inverter": {...}, "control": {...}}
        self._last_snapshot = snapshot
        return snapshot

    @staticmethod
    def _read_int16(db, addr: int) -> int:
        """Read a register as signed int16 (for scale factors)."""
        raw = db.getValues(addr + _PB_OFFSET, 1)[0]
        return raw - 65536 if raw > 32767 else raw
```

**Key insight:** Scale factors are stored as signed int16 in SunSpec. Raw uint16 > 32767 means negative. The proxy datablock stores uint16, so conversion is needed. This is the single most common bug in SunSpec decoding.

### Pattern 2: TimeSeriesBuffer -- Ring Buffer

**What:** Fixed-duration ring buffer using `collections.deque(maxlen=N)`.

**When to use:** One buffer per metric. Fed by DashboardCollector after each poll.

**Example:**
```python
# Source: ARCHITECTURE.md design
from collections import deque
from dataclasses import dataclass
import time

@dataclass(slots=True)
class Sample:
    timestamp: float
    value: float

class TimeSeriesBuffer:
    def __init__(self, max_seconds: int = 3600):
        # Extra 60 for margin before eviction
        self._buf: deque[Sample] = deque(maxlen=max_seconds + 60)

    def append(self, value: float, ts: float | None = None) -> None:
        self._buf.append(Sample(ts or time.monotonic(), value))

    def get_all(self) -> list[Sample]:
        return list(self._buf)

    def latest(self) -> Sample | None:
        return self._buf[-1] if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)
```

**Memory:** ~60 bytes/Sample * 3,660 maxlen = ~215 KB per buffer. 6 buffers = ~1.3 MB total. Negligible for the LXC.

### Pattern 3: Static File Serving via importlib.resources

**What:** Extend the existing `index_handler` pattern to serve `.css` and `.js` files.

**When to use:** For the 3-file split.

**Example:**
```python
# Source: existing index_handler in webapp.py
import importlib.resources as pkg_resources

CONTENT_TYPES = {
    "index.html": "text/html",
    "style.css": "text/css",
    "app.js": "application/javascript",
}

async def static_handler(request: web.Request) -> web.Response:
    """Serve static files from the package."""
    filename = request.match_info["filename"]
    if filename not in CONTENT_TYPES:
        raise web.HTTPNotFound()
    try:
        ref = pkg_resources.files("venus_os_fronius_proxy") / "static" / filename
        content = ref.read_text(encoding="utf-8")
        return web.Response(text=content, content_type=CONTENT_TYPES[filename])
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        raise web.HTTPNotFound()

# In create_webapp():
app.router.add_get("/static/{filename}", static_handler)
# Keep existing: app.router.add_get("/", index_handler)
```

### Pattern 4: Venus OS CSS Custom Properties

**What:** CSS variable definitions matching Venus OS gui-v2 Dark theme.

**Example:**
```css
/* Source: victronenergy/gui-v2 themes/color/Dark.json + ColorDesign.json */
:root {
    /* Venus OS Core Palette */
    --ve-blue: #387DC5;
    --ve-blue-light: #73A2D3;
    --ve-blue-dim: #27588A;
    --ve-orange: #F0962E;
    --ve-red: #F35C58;
    --ve-green: #72B84C;

    /* Backgrounds */
    --ve-bg: #141414;
    --ve-bg-surface: #272622;
    --ve-bg-widget: #11263B;
    --ve-border: #64635F;

    /* Text */
    --ve-text: #FAF9F5;
    --ve-text-dim: #969591;
    --ve-text-secondary: #DCDBD7;

    /* Semantic */
    --ve-ok: var(--ve-blue);
    --ve-warning: var(--ve-orange);
    --ve-error: var(--ve-red);
    --ve-success: var(--ve-green);
}
```

### Pattern 5: Sidebar Navigation Layout

**What:** GX Touch inspired sidebar with icons, responsive collapse.

**Example structure:**
```html
<div class="app-shell">
    <nav class="sidebar">
        <div class="sidebar-header"><!-- logo --></div>
        <a class="nav-item active" data-page="dashboard">
            <svg class="nav-icon"><!-- dashboard icon --></svg>
            <span class="nav-label">Dashboard</span>
        </a>
        <a class="nav-item" data-page="config">
            <svg class="nav-icon"><!-- settings icon --></svg>
            <span class="nav-label">Config</span>
        </a>
        <a class="nav-item" data-page="registers">
            <svg class="nav-icon"><!-- list icon --></svg>
            <span class="nav-label">Registers</span>
        </a>
    </nav>
    <main class="content">
        <header class="top-bar"><!-- title + status dots --></header>
        <div id="page-dashboard" class="page active">...</div>
        <div id="page-config" class="page">...</div>
        <div id="page-registers" class="page">...</div>
    </main>
</div>
```

**Responsive strategy:**
- Desktop (>1024px): Sidebar expanded with labels
- Tablet (768-1024px): Sidebar collapsed to icon-only
- Mobile (<768px): Sidebar hidden, hamburger menu toggles overlay

### Pattern 6: Poll Loop Integration (3-4 Lines)

**What:** Minimal change to `_poll_loop` in proxy.py.

**Where:** After `cache.update(INVERTER_CACHE_ADDR, result.inverter_registers)` (line ~272).

```python
# After the two cache.update() calls in the success branch:
if shared_ctx is not None and "dashboard_collector" in shared_ctx:
    shared_ctx["dashboard_collector"].collect(
        cache, shared_ctx.get("control_state")
    )
```

**Note:** No broadcast yet in Phase 5. The collector just decodes + buffers. WebSocket broadcast is Phase 6.

### Anti-Patterns to Avoid

- **Decoding in HTTP handler:** Do NOT decode registers in a REST endpoint handler. Decode once in the poll loop via DashboardCollector. Handlers read the pre-built snapshot.
- **Global CSS without namespacing:** Do NOT use bare element selectors like `section { ... }`. Use `.ve-panel`, `.ve-card`, etc. to avoid conflicts with existing register viewer styles.
- **Inline styles in HTML:** Do NOT put any styles in index.html. All styles go in style.css. The HTML file should only have structure.
- **Serving static via filesystem path:** Do NOT use `aiohttp.web.static()` with a filesystem path. Continue using `importlib.resources` for package compatibility.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Ring buffer | Custom linked list or array shifting | `collections.deque(maxlen=N)` | O(1) append, automatic eviction, thread-safe, zero deps |
| Signed int16 from uint16 | Bitwise operations ad-hoc | `struct.unpack('>h', struct.pack('>H', raw))[0]` or simple `raw - 65536 if raw > 32767` | Standard pattern, handles edge cases |
| CSS framework | Tailwind/Bootstrap | CSS custom properties | No CDN, no build tools, LAN-only deployment |
| Icon library | Font Awesome, Material Icons | Inline SVG icons | No external deps, ~20 lines per icon, cacheable |
| Responsive framework | Any grid framework | CSS Grid + Flexbox + media queries | Native browser support, zero deps |

**Key insight:** This phase has ZERO new dependencies. Everything is stdlib Python + vanilla HTML/CSS/JS. Resist the temptation to add anything.

## Common Pitfalls

### Pitfall 1: Scale Factor Sign Bug
**What goes wrong:** Scale factors in SunSpec are signed int16 stored as uint16 in the datablock. A scale factor of -2 is stored as 65534 (0xFFFE). Reading it as uint16 gives 65534, not -2. Applying `10^65534` crashes or produces garbage.
**Why it happens:** `cache.datablock.getValues()` returns uint16 values. Developers forget to convert.
**How to avoid:** Always use `_read_int16()` helper for scale factor registers. Unit test with known SF values (-2 is the most common for this inverter).
**Warning signs:** Power values in megawatts or zero when inverter is producing.

### Pitfall 2: pymodbus +1 Address Offset
**What goes wrong:** SunSpec register 40083 (AC Power) is accessed via `datablock.getValues(40084, 1)` in pymodbus due to its internal +1 offset. Using 40083 reads the wrong register.
**Why it happens:** pymodbus ModbusSequentialDataBlock uses `address - self.address + 1` internally.
**How to avoid:** Define `_PB_OFFSET = 1` constant, always use `addr + _PB_OFFSET` when calling getValues.
**Warning signs:** All values shifted by one register -- current reads voltage, power reads frequency, etc.

### Pitfall 3: AC Energy is uint32 (2 registers)
**What goes wrong:** AC Energy (lifetime Wh) at register 40093 spans 2 registers (uint32). Reading only 1 register gives the high word, which may be zero for low energy values or the wrong magnitude.
**Why it happens:** Most Model 103 fields are single uint16. AC Energy is the exception (size=2 in REGISTER_MODELS).
**How to avoid:** Read `getValues(40093 + _PB_OFFSET, 2)` and combine: `(hi << 16) | lo`. The existing `_poll_loop` already does this at line 265-268 for `last_energy_wh`.
**Warning signs:** Energy value wrapping at 65535 Wh (~65 kWh) or showing 0 when it should show megawatts.

### Pitfall 4: importlib.resources Content-Type
**What goes wrong:** Serving `.css` as `text/html` or `.js` without proper content-type causes browsers to reject the file (MIME type mismatch).
**Why it happens:** The existing `index_handler` hardcodes `content_type="text/html"`.
**How to avoid:** Use a content-type lookup dict keyed by filename. Map `.css` to `text/css`, `.js` to `application/javascript`.
**Warning signs:** Browser console shows "Refused to apply style" or "Refused to execute script" errors.

### Pitfall 5: CSS Transition from Old to New Theme
**What goes wrong:** The existing `index.html` has inline styles using old variable names (`--bg`, `--surface`, `--accent`). If the new `style.css` uses different variable names (`--ve-bg`, `--ve-bg-surface`), the existing config and register viewer sections break visually.
**How to avoid:** The 3-file split is a COMPLETE rewrite of the frontend. Port ALL existing functionality (status, health, config, registers) into the new layout. Do not partially migrate.
**Warning signs:** Some sections use old dark blue theme, others use new Venus OS warm grays.

### Pitfall 6: Sidebar Layout Breaks Existing Content
**What goes wrong:** The new sidebar navigation changes the page structure from a simple vertical scroll to a sidebar+content layout. Existing sections (config form, register viewer) may overflow or misalign in the new layout.
**How to avoid:** Each "page" within the content area should be independently scrollable. Use `overflow-y: auto` on `.content` area. Test register viewer (the widest section) at mobile widths.
**Warning signs:** Horizontal scrollbar appears, register viewer columns overlap.

## Code Examples

### Complete DashboardCollector Snapshot Structure

```python
# Expected snapshot dict structure (from ARCHITECTURE.md, refined)
snapshot = {
    "ts": 1710770400.0,          # time.time() for client display
    "inverter": {
        "ac_power_w": 12450.0,
        "ac_current_a": 18.2,
        "ac_current_l1_a": 6.1,
        "ac_current_l2_a": 6.0,
        "ac_current_l3_a": 6.1,
        "ac_voltage_ab_v": 400.1,
        "ac_voltage_bc_v": 399.8,
        "ac_voltage_ca_v": 400.5,
        "ac_voltage_an_v": 230.1,
        "ac_voltage_bn_v": 231.0,
        "ac_voltage_cn_v": 229.8,
        "ac_frequency_hz": 50.01,
        "ac_va": 12600.0,          # Apparent power
        "ac_var": 450.0,           # Reactive power
        "ac_pf": 98.5,             # Power factor (%)
        "dc_power_w": 12800.0,
        "dc_voltage_v": 720.0,
        "dc_current_a": 17.8,
        "temperature_cab_c": 42.5,
        "temperature_sink_c": 38.2,
        "energy_total_wh": 21543200,  # uint32, raw Wh
        "status": "MPPT",
        "status_code": 4,
        "status_vendor": 0,
    },
    "control": {
        "enabled": True,
        "limit_pct": 75.0,
        "wmaxlimpct_raw": 7500,
    },
    "connection": {
        "state": "connected",
        "poll_success": 4523,
        "poll_total": 4530,
        "cache_stale": False,
    },
}
```

### Register Address Map for DashboardCollector

```python
# Complete address map for all decoded fields
# Source: REGISTER_MODELS in webapp.py
DECODE_MAP = {
    # Field name           Address  Size  SF Address   Notes
    "ac_current":         (40071,   1,    40075),      # Total AC current
    "ac_current_l1":      (40072,   1,    40075),      # Phase A
    "ac_current_l2":      (40073,   1,    40075),      # Phase B
    "ac_current_l3":      (40074,   1,    40075),      # Phase C
    "ac_voltage_ab":      (40076,   1,    40082),      # Line-line
    "ac_voltage_bc":      (40077,   1,    40082),
    "ac_voltage_ca":      (40078,   1,    40082),
    "ac_voltage_an":      (40079,   1,    40082),      # Line-neutral
    "ac_voltage_bn":      (40080,   1,    40082),
    "ac_voltage_cn":      (40081,   1,    40082),
    "ac_power":           (40083,   1,    40084),      # Total AC power (W)
    "ac_frequency":       (40085,   1,    40086),      # Hz
    "ac_va":              (40087,   1,    40088),      # Apparent power
    "ac_var":             (40089,   1,    40090),      # Reactive power
    "ac_pf":              (40091,   1,    40092),      # Power factor
    "ac_energy":          (40093,   2,    40095),      # Lifetime Wh (uint32!)
    "dc_current":         (40096,   1,    40097),
    "dc_voltage":         (40098,   1,    40099),
    "dc_power":           (40100,   1,    40101),
    "temperature_cab":    (40102,   1,    40106),      # Cabinet temp
    "temperature_sink":   (40103,   1,    40106),      # Heat sink temp
    "status":             (40107,   1,    None),       # No SF, enum
    "status_vendor":      (40108,   1,    None),       # No SF, vendor code
}
```

### Responsive Sidebar CSS Pattern

```css
/* Sidebar responsive pattern */
.app-shell {
    display: grid;
    grid-template-columns: 220px 1fr;
    min-height: 100vh;
}

.sidebar {
    background: var(--ve-bg-surface);
    border-right: 1px solid var(--ve-border);
    padding: 16px 0;
    display: flex;
    flex-direction: column;
    transition: width 0.2s;
}

/* Tablet: icon-only sidebar */
@media (max-width: 1024px) {
    .app-shell { grid-template-columns: 56px 1fr; }
    .nav-label { display: none; }
}

/* Mobile: hidden sidebar */
@media (max-width: 768px) {
    .app-shell { grid-template-columns: 1fr; }
    .sidebar {
        position: fixed;
        left: -220px;
        width: 220px;
        height: 100vh;
        z-index: 100;
        transition: left 0.3s;
    }
    .sidebar.open { left: 0; }
}
```

## State of the Art

| Old Approach (v1.0) | Current Approach (v2.0 Phase 5) | Impact |
|---------------------|--------------------------------|--------|
| Single-file index.html (489 lines) | 3-file split: HTML + CSS + JS | Maintainable, testable, separates concerns |
| Generic dark blue theme (#1a1a2e) | Venus OS gui-v2 exact palette (#141414, #387DC5) | Authentic Victron visual identity |
| HTTP polling every 2s for all data | DashboardCollector pre-decodes on poll cycle | Foundation for WebSocket push in Phase 6 |
| Raw register display only | Physical values with units (kW, V, A, Hz) | Human-readable dashboard data |
| No history tracking | 60-min TimeSeriesBuffer per metric | Foundation for sparklines in Phase 6 |
| Flat page layout | Sidebar navigation (Dashboard/Config/Registers) | Multi-page app feel, GX Touch inspired |

## Open Questions

1. **Ring buffer sampling rate: 1/s vs downsampled**
   - What we know: Poll cycle is 1/s. Storing every sample = 3,600 per metric per hour. ~1.3 MB total for 6 buffers.
   - What's unclear: Whether 1/s granularity is needed for sparklines, or if 1 sample per 10s (360 points) suffices.
   - Recommendation: Store at 1/s (memory is cheap at 1.3 MB). Downsample when serializing for API response. This preserves data for future use without wasting bandwidth.

2. **Daily energy tracking (Tagesertrag)**
   - What we know: Model 103 has lifetime Wh (uint32). Delta tracking needs a "start of day" reference. Service restart loses this.
   - What's unclear: Whether to implement this in Phase 5 or defer to Phase 8 (DASH-05).
   - Recommendation: DashboardCollector should track `energy_at_start` on first collect(). Include `energy_today_wh` in snapshot. This is trivial to add during INFRA-02 implementation.

3. **Existing page functionality migration**
   - What we know: Config editor, register viewer, status dots all need to work in the new layout.
   - What's unclear: How much of the existing JavaScript can be reused vs needs rewriting.
   - Recommendation: Full rewrite of the JS into app.js. The logic is simple (~230 lines). Porting into a new structure is faster than adapting the old code.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-02 | DashboardCollector decodes registers with scale factors | unit | `python -m pytest tests/test_dashboard.py -x` | No -- Wave 0 |
| INFRA-02 | DashboardCollector produces correct snapshot dict | unit | `python -m pytest tests/test_dashboard.py::test_snapshot_structure -x` | No -- Wave 0 |
| INFRA-02 | Scale factor int16 sign conversion | unit | `python -m pytest tests/test_dashboard.py::test_int16_conversion -x` | No -- Wave 0 |
| INFRA-02 | AC Energy uint32 (2-register) decoding | unit | `python -m pytest tests/test_dashboard.py::test_uint32_energy -x` | No -- Wave 0 |
| INFRA-03 | TimeSeriesBuffer append and get_all | unit | `python -m pytest tests/test_timeseries.py -x` | No -- Wave 0 |
| INFRA-03 | TimeSeriesBuffer maxlen eviction | unit | `python -m pytest tests/test_timeseries.py::test_eviction -x` | No -- Wave 0 |
| INFRA-04 | Static handler serves .css with correct content-type | unit | `python -m pytest tests/test_webapp.py::test_static_css -x` | No -- Wave 0 |
| INFRA-04 | Static handler serves .js with correct content-type | unit | `python -m pytest tests/test_webapp.py::test_static_js -x` | No -- Wave 0 |
| INFRA-04 | Static handler returns 404 for unknown files | unit | `python -m pytest tests/test_webapp.py::test_static_404 -x` | No -- Wave 0 |
| DASH-01 | CSS file contains Venus OS color variables | smoke | `python -m pytest tests/test_theme.py::test_venus_colors -x` | No -- Wave 0 |
| DASH-01 | HTML references style.css and app.js | smoke | `python -m pytest tests/test_theme.py::test_html_references -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_dashboard.py` -- covers INFRA-02 (DashboardCollector decoding)
- [ ] `tests/test_timeseries.py` -- covers INFRA-03 (TimeSeriesBuffer)
- [ ] `tests/test_theme.py` -- covers DASH-01 + INFRA-04 (CSS colors, static serving)
- [ ] No framework install needed -- pytest already configured in pyproject.toml

## Sources

### Primary (HIGH confidence)
- `src/venus_os_fronius_proxy/webapp.py` -- REGISTER_MODELS register layout, existing index_handler pattern, create_webapp factory
- `src/venus_os_fronius_proxy/proxy.py` -- _poll_loop structure, shared_ctx population, cache.update() hook point
- `src/venus_os_fronius_proxy/control.py` -- ControlState API, WMaxLimPct decoding, Model 123 layout
- `src/venus_os_fronius_proxy/register_cache.py` -- RegisterCache.datablock access pattern
- `src/venus_os_fronius_proxy/__main__.py` -- shared_ctx wiring, webapp creation, lifecycle
- `.planning/research/ARCHITECTURE.md` -- DashboardCollector design, TimeSeriesBuffer design, snapshot format
- `.planning/research/FEATURES.md` -- Venus OS gui-v2 color palette from Dark.json/ColorDesign.json
- `.planning/research/STACK.md` -- Zero-dep approach validation, CSS custom properties strategy
- `.planning/research/PITFALLS.md` -- Scale factor bugs, single-file maintainability, browser performance

### Secondary (MEDIUM confidence)
- Victron gui-v2 GitHub repository -- color tokens (referenced in FEATURES.md, not directly re-fetched)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero new deps, all stdlib + existing aiohttp
- Architecture: HIGH -- based on existing codebase analysis and pre-existing architecture research
- Pitfalls: HIGH -- scale factor bug is the #1 SunSpec decoding issue; pymodbus offset is documented in existing code comments
- Theme/CSS: HIGH -- Venus OS palette extracted from official source in prior research

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable domain, no fast-moving dependencies)
