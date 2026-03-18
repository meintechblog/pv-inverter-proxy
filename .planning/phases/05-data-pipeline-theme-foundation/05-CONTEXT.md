# Phase 5: Data Pipeline & Theme Foundation - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend delivers decoded inverter data per poll cycle and frontend has Venus OS visual identity with proper file structure. This phase builds the foundation that Phases 6-8 consume — no live WebSocket push yet, no interactive widgets yet.

</domain>

<decisions>
## Implementation Decisions

### Venus OS Farbschema
- Venus OS Grundpalette aus gui-v2: #387DC5 (primary blue), #141414 (background), #FAF9F5 (text), #969591 (dim text)
- Eigene Akzente erlaubt — Victron Blau (#387DC5) als Akzentfarbe
- Kein exakter Pixel-Clone, aber erkennbar Venus OS inspiriert
- Eigenes Proxy-Branding: kleines Logo/Icon für den Proxy Service, Titel "Venus OS Fronius Proxy"
- Kein Victron Logo (Copyright), aber Victron-Farbschema

### Widget-Style
- Venus OS Widget-Style: abgerundete Panels mit Victron-typischem Border-Style, ähnlich GX Touch Display
- Cards/Panels folgen dem Venus OS Designsystem

### Dashboard Layout
- **Sidebar Navigation links** mit Icons — Dashboard | Config | Registers (wie Venus OS GX Touch)
- **Voll responsive** — Desktop, Tablet UND Handy
- **Kompakter Header**: Logo + "Venus OS Fronius Proxy" + Connection Status Dots, schlank
- Sidebar collapsed auf Mobile zu Icon-only oder Hamburger-Menü

### Power Gauge Design
- Claude's Discretion — Tacho-Gauge, große Zahl, oder Card. Soll prominent und informativ sein.

### DashboardCollector Daten
- **Kompletter Datensatz** — alle Register decoded:
  - Power: AC Power total + L1/L2/L3, DC Power
  - Energy: AC Energy Gesamtertrag, Tagesertrag (in-memory)
  - Spannungen: AC Voltage L1/L2/L3, AC Voltage L-L, DC Voltage
  - Ströme: AC Current L1/L2/L3, DC Current
  - Netz: Frequenz, Power Factor, Scheinleistung (VA), Blindleistung (VAR)
  - Temperatur: Sink Temperature
  - Status: Inverter Status (Operating/Sleeping/Throttled/Fault), Status Vendor Code
- **Fertig umgerechnet** mit Scale Factors → echte Einheiten (kW, V, A, °C, Hz)
- **Control-Status inclusive** im gleichen Payload: Power Limit %, Enable/Disable, Quelle, Zeitstempel

### File Split
- 3-File Split: index.html + style.css + app.js
- Served via aiohttp importlib.resources (bestehendes Pattern erweitern)

### Claude's Discretion
- Power Gauge Darstellung (Tacho vs Zahl vs Bar)
- Exact spacing, typography, icon choices
- Sidebar Icon-Set
- Mobile breakpoints
- Ring Buffer sampling rate (1/s vs 1/min)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Venus OS Visual Identity
- `.planning/research/FEATURES.md` — Venus OS gui-v2 color palette (extracted from Dark.json)
- `.planning/research/STACK.md` — Zero-dependency approach, CSS variable strategy

### Architecture
- `.planning/research/ARCHITECTURE.md` — DashboardCollector design, TimeSeriesBuffer, SSE/WebSocket decision, integration points
- `.planning/research/PITFALLS.md` — File organization, WebSocket memory leaks, single-file scalability

### Existing Code
- `src/venus_os_fronius_proxy/webapp.py` — Existing aiohttp webapp with REGISTER_MODELS constant (defines SE30K register layout)
- `src/venus_os_fronius_proxy/proxy.py` — shared_ctx pattern, _poll_loop, cache.update() hook point
- `src/venus_os_fronius_proxy/static/index.html` — Current single-file HTML (to be split)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `webapp.py:REGISTER_MODELS` — Full SunSpec register layout with field names, addresses, types, and SE source mapping. DashboardCollector can reuse this to decode registers.
- `shared_ctx` dict — Already passes cache, conn_mgr, control_state, poll_counter between proxy and webapp. DashboardCollector hooks into this.
- `webapp.py` REST endpoints — 7 existing endpoints (status, health, config, registers, etc.) serve as pattern for new dashboard endpoints.

### Established Patterns
- `importlib.resources` for static file serving — extend to serve .css and .js files
- `aiohttp.web.AppRunner` factory pattern — webapp created separately, wired into __main__.py
- Scale factor decoding already exists in `webapp.py:registers_handler()` for the register viewer

### Integration Points
- `_poll_loop()` in proxy.py — callback hook after `cache.update()` for feeding DashboardCollector (3-4 lines change)
- `__main__.py` — wire DashboardCollector into shared_ctx
- `static/` package — add style.css and app.js alongside index.html

</code_context>

<specifics>
## Specific Ideas

- Venus OS GX Touch als Referenz für Sidebar und Widget-Style
- Power Gauge soll prominent sein — "Tacho-Feeling" oder große Zahl, nicht versteckt in einer kleinen Card
- Sidebar soll auch auf Tablet gut funktionieren (collapsed icons)

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-data-pipeline-theme-foundation*
*Context gathered: 2026-03-18*
