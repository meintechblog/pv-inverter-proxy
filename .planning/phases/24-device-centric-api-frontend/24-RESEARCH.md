# Phase 24: Device-Centric API & Frontend - Research

**Researched:** 2026-03-21
**Domain:** REST API restructure + Vanilla JS SPA frontend overhaul
**Confidence:** HIGH

## Summary

Phase 24 transforms the proxy from a single-dashboard/single-config/single-register layout into a device-centric architecture where every device (inverter, Venus OS, virtual PV) gets its own sidebar entry, dashboard, register viewer, and config sub-tab. The backend already has full per-device state via DeviceRegistry (Phase 22) and PowerLimitDistributor (Phase 23). The work is primarily: (1) new REST endpoints that expose per-device snapshots, (2) WebSocket messages tagged with device IDs, (3) a complete frontend restructure with dynamic sidebar, hash routing (`#device/{id}/dashboard`), and type-specific dashboard layouts.

The existing codebase has strong foundations to build on: `app_ctx.devices` dict holds per-device `DeviceState` with `last_poll_data` and `DashboardCollector`, the inverters CRUD API (`/api/inverters`) already supports add/update/delete/toggle, the `showToast()` system is in place, and all CSS design tokens are defined. The main challenge is the frontend restructure: moving from 3 static pages to N dynamic device pages with sub-tabs, while preserving the existing responsive design and ve-* component library.

**Primary recommendation:** Split into 2 plans: (1) Backend API endpoints + WebSocket per-device tagging, (2) Frontend restructure (sidebar, routing, device pages, add/delete flows).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Sidebar grouped by type: **INVERTERS** (SE30K, HM-800, HM-600) -> **VENUS OS** -> **VIRTUAL PV**. Collapsible sections.
- Each sidebar entry shows: **Name + Status-Dot + Live-kW** (power for inverters, "Connected" for Venus OS)
- Device names are **user-definable with auto-default** from Manufacturer+Model. New config field `display_name` on InverterEntry.
- **Virtual PV is always visible** in sidebar, even with only 1 inverter
- Per-device pages have **Sub-Tabs**: `Dashboard` | `Registers` | `Config`
- **Venus OS page**: Single page (no sub-tabs), shows MQTT connection status, ESS mode, Portal ID, and Config
- **Disable UX**: Last data stays visible but **greyed out**. Sidebar entry shows dimmed with "Disabled" label. No data clearing on disable.
- **Delete UX**: **Toast with Undo** -- device removed, 5-second toast "Device geloescht -- Rueckgaengig". After timeout, permanently gone. No inline-confirm.
- **Virtual PV Contribution**: Stacked horizontal bar shows proportional power per inverter, color-coded. Legend below with names + kW.
- **Throttle info in contribution table**: Additional columns: TO number, Throttle On/Off, current limit (%).
- Hash routing extended to `#device/{id}/dashboard`
- Type-specific layouts: SolarEdge gets 3-Phase AC table, OpenDTU gets DC-channel table
- Manufacturer + Model displayed in Config sub-tab after successful connection

### Claude's Discretion
- '+' button exact placement and add-flow UX design
- Virtual PV gauge vs. large number display
- Loading skeleton design
- Error state handling per device type
- Sub-tab visual implementation (underline tabs, pill tabs, etc.)
- OpenDTU dashboard layout specifics (DC channel table format)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | REST Endpoints liefern per-Device Snapshots und Status (/api/devices/{id}/snapshot) | New endpoint pattern, DashboardCollector.last_snapshot already per-device |
| API-02 | WebSocket broadcastet per-Device Updates mit Device-ID Tag | Current broadcast_to_clients sends untagged snapshot; needs device_id field + per-device collector data |
| API-03 | CRUD Endpoints fuer Device-Management (GET/POST/PUT/DELETE /api/devices) | Existing /api/inverters CRUD can be extended; needs display_name field support |
| UI-01 | Dynamische Sidebar zeigt alle konfigurierten Devices als eigene Menuepunkte | Replace static nav-items with dynamic rendering from /api/devices list |
| UI-02 | Jeder Inverter hat eigene Ansicht mit Dashboard, Registers, Config sub-tabs | New page template system with type-specific widgets |
| UI-03 | Venus OS hat eigenen Menuepunkt (ESS Status, MQTT Config, Portal ID) | Consolidate existing venus-ess-panel + venus config form into Venus OS device page |
| UI-04 | Virtual PV-Inverter hat eigene Ansicht mit aggregiertem Dashboard und Beitragsanzeige | New contribution view with stacked bar chart + throttle table |
| UI-05 | Zentrales "+" im Sidebar zum Hinzufuegen neuer Devices -- Discover-Button, kein Auto-Scan | Adapt existing add form + scanner, move to modal or sidebar add flow |
| UI-06 | Device deaktiviert/entfernt -> sofort aus UI entfernt | Toast-with-undo for delete, greyed-out for disable; WS broadcast triggers UI update |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiohttp | 3.x (existing) | REST API + WebSocket server | Already in use, no change needed |
| Vanilla JS | ES5/ES6 | Frontend SPA | Project convention: zero dependencies, no build tooling |
| CSS Custom Properties | N/A | Design tokens | All `--ve-*` tokens already defined in style.css |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | existing | Backend logging | All new endpoint handlers |
| dataclasses | stdlib | Config models | InverterEntry.display_name field |

No new dependencies are needed. The entire phase uses existing libraries.

## Architecture Patterns

### Backend API Structure

```
/api/devices                    GET    → list all devices (inverters + venus + virtual)
/api/devices                    POST   → add new device (type: solaredge|opendtu)
/api/devices/{id}               GET    → single device detail
/api/devices/{id}               PUT    → update device config
/api/devices/{id}               DELETE → delete device
/api/devices/{id}/snapshot      GET    → per-device dashboard snapshot
/api/devices/{id}/registers     GET    → per-device register data
/api/devices/virtual/snapshot   GET    → aggregated virtual PV snapshot + contribution
/ws                             WS     → tagged messages: {type:"device_snapshot", device_id:"xxx", data:{...}}
```

Keep existing `/api/inverters` endpoints as aliases or deprecate them. The new `/api/devices` unifies inverters, Venus OS, and virtual PV under one umbrella.

### Frontend Page Structure

```
#device/{id}/dashboard    → Device dashboard (type-specific)
#device/{id}/registers    → Device register viewer
#device/{id}/config       → Device config form
#device/venus/dashboard   → Venus OS page (single, no sub-tabs)
#device/virtual/dashboard → Virtual PV aggregated view
```

### Recommended Project Structure (Frontend)

The single `app.js` file will grow significantly. Structure the code with clear sections:

```
app.js sections:
├── Navigation & Routing (extended hash router)
├── Sidebar Renderer (dynamic device list)
├── Device Page Factory (creates type-specific pages)
├── Sub-Tab System (Dashboard / Registers / Config)
├── Type-Specific Renderers
│   ├── SolarEdge Dashboard (3-phase AC table, gauge, status)
│   ├── OpenDTU Dashboard (DC channel table, gauge)
│   ├── Venus OS Page (MQTT status, ESS, config)
│   └── Virtual PV Page (contribution bar, throttle table)
├── WebSocket Handler (per-device message routing)
├── Config Forms (per-device dirty tracking)
├── Add/Delete Flows (toast-with-undo)
└── Existing utilities (toast, gauge, sparkline)
```

### Pattern 1: Device-Tagged WebSocket Messages

**What:** Each WebSocket broadcast includes device_id so the frontend can route updates to the correct device page.
**When to use:** Every poll success callback.

```python
# Backend: broadcast_to_clients with device tagging
async def broadcast_device_snapshot(app, device_id, snapshot):
    payload = json.dumps({
        "type": "device_snapshot",
        "device_id": device_id,
        "data": snapshot,
    })
    for ws in set(app["ws_clients"]):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError):
            app["ws_clients"].discard(ws)
```

```javascript
// Frontend: route device snapshots to active page
ws.onmessage = function(event) {
    var msg = JSON.parse(event.data);
    if (msg.type === 'device_snapshot') {
        updateSidebarEntry(msg.device_id, msg.data);
        if (isActiveDevice(msg.device_id)) {
            renderDeviceDashboard(msg.device_id, msg.data);
        }
    }
    if (msg.type === 'virtual_snapshot') {
        updateVirtualPVPage(msg.data);
    }
};
```

### Pattern 2: Hash Router with Device Context

**What:** Extend the existing hash-based router to support `#device/{id}/{tab}` patterns.
**When to use:** All device navigation.

```javascript
function parseHash() {
    var hash = window.location.hash.replace('#', '');
    var parts = hash.split('/');
    if (parts[0] === 'device' && parts.length >= 3) {
        return { type: 'device', id: parts[1], tab: parts[2] };
    }
    return { type: 'page', id: hash || 'dashboard' };
}

function navigateTo(route) {
    if (route.type === 'device') {
        window.location.hash = 'device/' + route.id + '/' + route.tab;
        showDevicePage(route.id, route.tab);
    }
}
```

### Pattern 3: Toast-with-Undo Delete

**What:** Delete immediately via API, show toast with undo button, re-add if undo clicked within 5s.
**When to use:** Device deletion.

```javascript
function deleteDeviceWithUndo(deviceId, deviceName) {
    // Store device data before delete for undo
    var deviceData = getCachedDevice(deviceId);

    fetch('/api/devices/' + deviceId, { method: 'DELETE' })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) { showToast('Delete failed: ' + data.error, 'error'); return; }

            removeFromSidebar(deviceId);

            var toast = showToastWithAction(
                'Device geloescht',
                'Rueckgaengig',
                function() {
                    // Undo: re-add via POST
                    fetch('/api/devices', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(deviceData)
                    }).then(function() { refreshSidebar(); });
                },
                5000
            );
        });
}
```

### Pattern 4: Dynamic Sidebar with Grouped Sections

**What:** Sidebar sections rendered from device list, grouped by type.
**When to use:** On initial load and after any device add/remove.

```javascript
function renderSidebar(devices) {
    var sidebar = document.getElementById('sidebar');
    // Keep header, clear device items

    var groups = {
        inverters: devices.filter(function(d) { return d.type !== 'venus'; }),
        venus: [{ id: 'venus', name: 'Venus OS', status: venusConnected }],
        virtual: [{ id: 'virtual', name: 'Virtual PV', power_w: totalPower }]
    };

    // Render collapsible groups with headers
    renderSidebarGroup('INVERTERS', groups.inverters);
    renderSidebarGroup('VENUS OS', groups.venus);
    renderSidebarGroup('VIRTUAL PV', groups.virtual);
}
```

### Anti-Patterns to Avoid

- **Monolithic page rebuild:** Do NOT re-render the entire page on every WebSocket message. Only update the active device's dashboard widgets and sidebar live values.
- **DOM ID collisions:** The current dashboard uses global IDs like `#gauge-value`, `#l1-voltage`. With N devices, each device page must use scoped element references (query within container, not by global ID).
- **Polling fallback for all devices:** The existing POLL_INTERVAL fallback should NOT poll `/api/dashboard` for every device. WebSocket is the primary data channel; REST is only for initial load.
- **Keeping old navigation alongside new:** The old Dashboard/Config/Registers nav items MUST be removed. Don't try to keep backward compatibility with old hashes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Color assignment for stacked bars | Manual hex assignment | Predefined palette from `--ve-*` tokens | Design system consistency, accessible contrast |
| Device type detection | String comparisons everywhere | Single `getDeviceType(device)` utility | Centralize logic, reduce bugs |
| Sub-tab state | Custom state machine | Hash router already handles this via URL | URL-driven state is simpler and bookmarkable |
| Undo timer | Manual setTimeout management | Extend existing `showToast()` with action callback | Consistent UX, existing animation system |

## Common Pitfalls

### Pitfall 1: WebSocket Message Ordering
**What goes wrong:** If multiple devices poll at slightly different rates, WebSocket messages arrive in unpredictable order. Frontend could flash between device data.
**Why it happens:** Each device poll triggers an independent broadcast.
**How to avoid:** Frontend must check `device_id` in every message and only update if it matches the currently viewed device. Sidebar entries update regardless.
**Warning signs:** Dashboard values flickering between different devices.

### Pitfall 2: DOM Element Scope Collision
**What goes wrong:** Current code uses `document.getElementById('gauge-value')` which assumes exactly one gauge on the page. With per-device dashboards, these collide.
**How to avoid:** Create device pages with a container element. All queries scope within that container: `container.querySelector('.ve-gauge-value')`. Use classes instead of IDs for repeated widgets.
**Warning signs:** Updating device A's page changes values on device B's page.

### Pitfall 3: Delete-Undo Race Condition
**What goes wrong:** User deletes a device, the backend removes it, then tries to undo but the device ID was already cleaned from DeviceRegistry.
**Why it happens:** The delete API permanently removes from config and stops the poll task.
**How to avoid:** Store the full device config before delete. Undo re-adds via POST `/api/devices` which creates a new entry (possibly with a new ID). Accept that undo creates a fresh device that starts polling again.
**Warning signs:** Undo fails silently, or device reappears but with no data.

### Pitfall 4: Virtual PV Page Data Staleness
**What goes wrong:** Virtual PV contribution data lags behind individual device updates because aggregation happens after each device poll independently.
**Why it happens:** AggregationLayer.recalculate() runs per-device, not synchronously across all devices.
**How to avoid:** The virtual PV snapshot endpoint should read the latest aggregated state from the RegisterCache + compute per-device contributions from `app_ctx.devices`. Accept that contributions may be from different poll cycles.

### Pitfall 5: Sidebar Overflow with Many Devices
**What goes wrong:** With 5+ inverters, the sidebar becomes too tall, especially on mobile.
**Why it happens:** Each entry shows name + dot + live kW.
**How to avoid:** Make inverter group collapsible. Sidebar already has `overflow-y: auto`. On mobile, the hamburger menu handles this naturally.

### Pitfall 6: Config display_name vs name Confusion
**What goes wrong:** InverterEntry already has a `name` field (user-friendly display name). Adding `display_name` creates confusion.
**Why it happens:** The field was called `name` in Phase 21 config.
**How to avoid:** Use the existing `name` field on InverterEntry. The CONTEXT.md says "display_name" but `name` already exists and serves this purpose. Just ensure auto-default logic fills `name` from Manufacturer+Model if empty.
**Warning signs:** Two name fields with unclear precedence.

## Code Examples

### Per-Device Snapshot Endpoint

```python
async def device_snapshot_handler(request: web.Request) -> web.Response:
    """GET /api/devices/{id}/snapshot -- per-device dashboard data."""
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]

    ds = app_ctx.devices.get(device_id)
    if ds is None:
        return web.json_response({"error": "Device not found"}, status=404)

    if ds.collector is None or ds.collector.last_snapshot is None:
        return web.json_response({"error": "No data yet"}, status=503)

    snapshot = dict(ds.collector.last_snapshot)
    # Add device metadata
    entry = _find_entry(request.app["config"], device_id)
    if entry:
        snapshot["device_id"] = device_id
        snapshot["device_type"] = entry.type
        snapshot["display_name"] = entry.name or f"{entry.manufacturer} {entry.model}".strip()
        snapshot["enabled"] = entry.enabled

    return web.json_response(snapshot)
```

### Virtual PV Contribution Endpoint

```python
async def virtual_snapshot_handler(request: web.Request) -> web.Response:
    """GET /api/devices/virtual/snapshot -- aggregated + per-device contributions."""
    app_ctx = request.app["app_ctx"]
    config = request.app["config"]

    contributions = []
    total_power = 0

    for entry in config.inverters:
        ds = app_ctx.devices.get(entry.id)
        power_w = 0
        if ds and ds.collector and ds.collector.last_snapshot:
            power_w = ds.collector.last_snapshot.get("inverter", {}).get("ac_power_w", 0)

        total_power += power_w
        contributions.append({
            "device_id": entry.id,
            "name": entry.name or f"{entry.manufacturer} {entry.model}".strip(),
            "power_w": power_w,
            "throttle_order": entry.throttle_order,
            "throttle_enabled": entry.throttle_enabled,
            "current_limit_pct": _get_current_limit(app_ctx, entry.id),
            "enabled": entry.enabled,
        })

    return web.json_response({
        "total_power_w": total_power,
        "contributions": contributions,
        "virtual_name": config.virtual_inverter.name,
    })
```

### Sidebar Entry HTML Structure

```html
<!-- Collapsible group -->
<div class="ve-sidebar-group" data-group="inverters">
    <div class="ve-sidebar-group-header">
        <span class="ve-sidebar-group-label">INVERTERS</span>
        <span class="ve-sidebar-group-chevron">&#9660;</span>
    </div>
    <div class="ve-sidebar-group-items">
        <a class="ve-sidebar-device" data-device-id="abc123" data-tab="dashboard">
            <span class="ve-dot" style="background:var(--ve-green)"></span>
            <span class="ve-sidebar-device-name">SE30K</span>
            <span class="ve-sidebar-device-power">12.3 kW</span>
        </a>
        <!-- More entries -->
    </div>
</div>
```

### Sub-Tab Navigation

```html
<div class="ve-device-tabs">
    <button class="ve-device-tab ve-device-tab--active" data-tab="dashboard">Dashboard</button>
    <button class="ve-device-tab" data-tab="registers">Registers</button>
    <button class="ve-device-tab" data-tab="config">Config</button>
</div>
<div class="ve-device-tab-content" id="device-content">
    <!-- Rendered by JS based on active tab -->
</div>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single dashboard page | Per-device pages | Phase 24 | Complete frontend restructure |
| Global config page | Per-device config sub-tab | Phase 24 | Config fields scoped to device |
| Static sidebar (3 items) | Dynamic grouped sidebar | Phase 24 | Sidebar renders from API data |
| Untagged WS broadcast | Device-tagged WS messages | Phase 24 | Frontend routes updates correctly |
| Inline delete confirm | Toast-with-undo | Phase 24 | Simpler UX, reversible action |
| `name` field unused | `name` field = display name | Phase 24 | Auto-populated from manufacturer+model |

## Open Questions

1. **display_name vs name field**
   - What we know: InverterEntry already has `name: str = ""` field (added Phase 21)
   - What's unclear: CONTEXT.md mentions adding `display_name` -- is this a new field or should we use existing `name`?
   - Recommendation: Use existing `name` field. It already exists, is persisted in config, and serves the exact purpose. No new field needed.

2. **Virtual PV throttle current_limit_pct source**
   - What we know: PowerLimitDistributor has `DeviceLimitState.current_limit_pct` per device
   - What's unclear: How to access distributor state from the webapp endpoint
   - Recommendation: Add a `get_device_limits()` method on PowerLimitDistributor that returns a dict of `{device_id: current_limit_pct}`. Access via `app_ctx.device_registry` -> distributor reference.

3. **Old page hashes (#dashboard, #config, #registers)**
   - What we know: Users may have bookmarks to old hashes
   - What's unclear: Should we redirect or just drop them?
   - Recommendation: Add a compatibility redirect: `#dashboard` -> `#device/virtual/dashboard`, `#config` -> first inverter config, `#registers` -> first inverter registers. Log a console warning about deprecated hashes.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | GET /api/devices/{id}/snapshot returns per-device data | unit | `python -m pytest tests/test_webapp.py::test_device_snapshot -x` | No, Wave 0 |
| API-02 | WS broadcasts include device_id tag | unit | `python -m pytest tests/test_websocket.py::test_device_tagged_broadcast -x` | No, Wave 0 |
| API-03 | CRUD /api/devices endpoints work | unit | `python -m pytest tests/test_webapp.py::test_devices_crud -x` | No, Wave 0 |
| UI-01 | Sidebar renders device list from API | manual-only | Manual browser test | N/A |
| UI-02 | Per-device sub-tabs render correctly | manual-only | Manual browser test | N/A |
| UI-03 | Venus OS page shows MQTT + ESS + Config | manual-only | Manual browser test | N/A |
| UI-04 | Virtual PV shows contributions + throttle | manual-only | Manual browser test | N/A |
| UI-05 | Add device flow works | manual-only | Manual browser test | N/A |
| UI-06 | Disable greys out, delete shows undo toast | manual-only | Manual browser test | N/A |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_webapp.py` -- add test_device_snapshot, test_devices_crud, test_virtual_snapshot test functions
- [ ] `tests/test_websocket.py` -- add test_device_tagged_broadcast for API-02
- [ ] No new framework install needed -- pytest + pytest-asyncio already configured

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `webapp.py` -- existing REST API patterns, WS handler, inverter CRUD
- Codebase inspection: `device_registry.py` -- DeviceRegistry lifecycle, ManagedDevice dataclass
- Codebase inspection: `aggregation.py` -- AggregationLayer, per-device decode/aggregate
- Codebase inspection: `distributor.py` -- PowerLimitDistributor, DeviceLimitState
- Codebase inspection: `context.py` -- AppContext.devices dict, DeviceState
- Codebase inspection: `config.py` -- InverterEntry fields (name, type, throttle_order, etc.)
- Codebase inspection: `app.js` -- current navigation, WebSocket, rendering patterns
- Codebase inspection: `style.css` -- ve-* design tokens, component patterns
- Codebase inspection: `index.html` -- current HTML structure

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions from user discussion session

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, all existing
- Architecture: HIGH - straightforward REST + WebSocket + vanilla JS patterns
- Pitfalls: HIGH - identified from direct codebase analysis (DOM ID collisions, WS ordering, undo race conditions)

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (stable domain, no external API changes)
