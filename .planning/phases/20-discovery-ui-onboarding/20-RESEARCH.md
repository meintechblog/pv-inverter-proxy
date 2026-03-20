# Phase 20: Discovery UI & Onboarding - Research

**Researched:** 2026-03-20
**Domain:** Frontend UI (vanilla JS), WebSocket integration, aiohttp background tasks
**Confidence:** HIGH

## Summary

Phase 20 connects the existing Phase 17 scanner backend to the Phase 19 inverter management UI. The scope is purely frontend + API wiring -- no new scanner logic is needed. The core work involves: (1) enhancing `scanner_discover_handler()` to run as a background task with WebSocket progress streaming, (2) building a progress bar and results UI below the inverter panel, and (3) adding auto-scan logic when the inverter list is empty.

All building blocks exist: `scan_subnet()` already has a `progress_callback(phase, current, total)` signature, `broadcast_to_clients()` handles WS pushes, `POST /api/inverters` accepts manufacturer/model/serial fields, and `showToast()` provides user feedback. The implementation is largely integration work with well-defined interfaces on both sides.

**Primary recommendation:** Enhance the existing scanner endpoint to run as an `asyncio.create_task()` background task, streaming progress via new WS message types (`scan_progress`, `scan_complete`, `scan_error`). Frontend listens for these messages and renders a progress bar + result list below the inverter panel.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Progress bar is horizontal, placed **below** the inverter panel (not inside, not overlay)
- Progress text shows phase: "Scanning 192.168.3.x (142/253)..." then "Verifying SunSpec (3/5)..."
- Progress bar uses `var(--ve-blue)` fill color
- Progress streamed via existing WebSocket infrastructure (scanner progress_callback -> WS broadcast)
- Scan is non-blocking: Venus OS Config remains usable during scan
- Only the Discover button is disabled during scan
- Results shown as checkbox list: Manufacturer + Model + Host:Port + Unit ID per row
- "Alle uebernehmen" (Add All) button above results list
- Already-configured inverters greyed out with "Bereits konfiguriert" label, checkbox disabled
- Empty scan: orange `ve-hint-card` with troubleshooting tips
- Confirmed inverters saved as enabled=true immediately
- First confirmed inverter automatically becomes active proxy target
- Auto-scan triggers every time config page opens with empty inverter list (no localStorage flag)
- Single result: auto-add + toast. Multiple: show checkbox list. Zero: hint card with tips
- Auto-Discover button in panel header, left of + button: [Inverters (magnifying glass) +]
- During scan: button disabled + icon changes to spinner, tooltip "Scan laeuft..."
- Ports field below inverter list, always visible, compact. Label "Scan-Ports:" with `ve-text-dim`
- Ports persisted in config YAML under `scanner.ports`
- Comma-separated port values, default "502, 1502"

### Claude's Discretion
- Exact SVG icon for discover button (magnifying glass vs radar)
- Progress bar height and animation style
- Checkbox styling in result list
- Transition/animation when results appear after scan
- Toast text variations
- Responsive behavior of scan results on mobile

### Deferred Ideas (OUT OF SCOPE)
- Live connection status dots in inverter list
- Multi-proxy parallel output to Venus OS (MPRX-01/02)
- Scan abort/cancel functionality
- Scheduled periodic re-scan
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DISC-05 | User sees scan progress in UI (progress bar or animation during ~30s scan) | WS progress streaming via `progress_callback` -> `broadcast_to_clients`, horizontal progress bar with phase text |
| CONF-04 | Discovered inverters from scan are automatically created as config entries | Batch POST to `/api/inverters` for each confirmed device, using existing `inverters_add_handler` |
| UX-01 | When no inverter configured, background scan starts automatically on config page open | Hook into `loadInverters()` empty-list check, trigger scan programmatically |
| UX-02 | User can manually trigger re-scan via Auto-Discover button in config bar | New button in `ve-panel-header`, calls `POST /api/scanner/discover` |
| UX-03 | Scan results shown as preview list, user confirms adoption | Checkbox result list with Add All button, greyed-out already-configured entries |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiohttp | existing | Web server, WebSocket, REST API | Already in use, no new dependency |
| Vanilla JS | N/A | Frontend scan UI, progress bar, result list | Project convention: zero frontend dependencies |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio | stdlib | Background task for scan (`create_task`) | Running scan without blocking the HTTP response |
| dataclasses | stdlib | `ScanConfig`, `DiscoveredDevice` serialization | Already used for scanner data structures |

### Alternatives Considered
None -- this phase uses only existing project dependencies.

## Architecture Patterns

### Backend: Background Scan with WS Progress

**What:** Convert `scanner_discover_handler()` from synchronous await to background task with progress streaming.

**Current flow (blocking):**
```
POST /api/scanner/discover -> await scan_subnet() -> return JSON
```

**New flow (non-blocking):**
```
POST /api/scanner/discover -> create_task(scan_subnet()) -> return {"status": "started"}
                                    |
                                    v
                            progress_callback() -> broadcast WS {"type": "scan_progress", ...}
                            on complete -> broadcast WS {"type": "scan_complete", ...}
                            on error -> broadcast WS {"type": "scan_error", ...}
```

**Pattern:**
```python
# Source: aiohttp docs + existing webapp patterns
async def scanner_discover_handler(request: web.Request) -> web.Response:
    app = request.app
    # Prevent concurrent scans
    if app.get("_scan_running"):
        return web.json_response({"error": "Scan already running"}, status=409)

    config: Config = app["config"]
    skip_ips = {inv.host for inv in config.inverters if inv.enabled}

    try:
        body = await request.json()
    except Exception:
        body = {}

    ports = body.get("ports", [502, 1502])
    scan_config = ScanConfig(ports=ports, skip_ips=skip_ips)

    async def run_scan():
        app["_scan_running"] = True
        try:
            def progress_cb(phase, current, total):
                # Schedule WS broadcast from sync callback
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        _broadcast_scan_progress(app, phase, current, total)
                    )
                )
            # NOTE: progress_callback is called synchronously from scan_subnet
            devices = await scan_subnet(scan_config, progress_callback=progress_cb)
            await _broadcast_scan_complete(app, devices)
        except Exception as e:
            await _broadcast_scan_error(app, str(e))
        finally:
            app["_scan_running"] = False

    asyncio.create_task(run_scan())
    return web.json_response({"status": "started"})
```

**Important:** The `progress_callback` in `scan_subnet` is called from within `async for coro in asyncio.as_completed(tasks)` -- it runs in the same event loop, so it CAN directly await WS broadcast. The callback is synchronous but called from async context, so the simplest approach is to make `progress_callback` an async callable or use `ensure_future`:

```python
# Simpler: make progress_callback async-aware
async def _run_scan(app, scan_config):
    app["_scan_running"] = True
    try:
        def progress_cb(phase, current, total):
            asyncio.ensure_future(_broadcast_scan_progress(app, phase, current, total))
        devices = await scan_subnet(scan_config, progress_callback=progress_cb)
        await _broadcast_scan_complete(app, devices)
    except Exception as e:
        await _broadcast_scan_error(app, str(e))
    finally:
        app["_scan_running"] = False
```

### WS Message Types

```python
async def _broadcast_scan_progress(app, phase, current, total):
    """Broadcast scan progress to all WS clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({
        "type": "scan_progress",
        "data": {"phase": phase, "current": current, "total": total}
    })
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError):
            clients.discard(ws)

async def _broadcast_scan_complete(app, devices):
    """Broadcast scan results to all WS clients."""
    payload = json.dumps({
        "type": "scan_complete",
        "data": {
            "devices": [{**dataclasses.asdict(d), "supported": d.supported} for d in devices],
            "count": len(devices)
        }
    })
    # ... same broadcast pattern

async def _broadcast_scan_error(app, error):
    payload = json.dumps({"type": "scan_error", "data": {"error": error}})
    # ... same broadcast pattern
```

### Frontend: WS Message Routing

Add new message type handlers in the existing WS message router:

```javascript
// Source: existing app.js pattern at line 98-101
if (msg.type === 'scan_progress') handleScanProgress(msg.data);
if (msg.type === 'scan_complete') handleScanComplete(msg.data);
if (msg.type === 'scan_error') handleScanError(msg.data);
```

### Frontend: Discovery UI Structure

```
#inverter-panel (existing ve-panel)
  .ve-panel-header
    h2 "Inverters"
    #btn-discover-inverter  (NEW - magnifying glass icon)
    #btn-add-inverter       (existing + button)
  #inverter-list            (existing)
  #inverter-add-form        (existing, hidden)
  #scan-ports-field         (NEW - compact ports input)
  #scan-area                (NEW - progress bar + results appear here)
    #scan-progress          (progress bar, shown during scan)
    #scan-results           (checkbox list, shown after scan)
```

### Config: Scanner Ports Persistence

The `Config` dataclass needs a `scanner` section. Minimal addition:

```python
@dataclass
class ScannerConfig:
    ports: list[int] = field(default_factory=lambda: [502, 1502])

@dataclass
class Config:
    # ... existing fields ...
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
```

And in `load_config()` / `save_config()`, handle `scanner:` YAML section.

### Anti-Patterns to Avoid
- **Polling for scan status:** Do NOT use `setInterval` to poll a status endpoint. Use WebSocket push (already decided).
- **Blocking the HTTP response:** Do NOT `await scan_subnet()` in the handler. Use `asyncio.create_task()`.
- **Multiple concurrent scans:** Guard with `app["_scan_running"]` flag. SolarEdge allows only ONE Modbus TCP connection.
- **Forgetting to re-enable button:** Always re-enable the discover button on `scan_complete` AND `scan_error`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Progress streaming | HTTP polling endpoint | WebSocket broadcast | Already have WS infrastructure, real-time updates |
| Inverter creation | Custom batch endpoint | Loop over existing `POST /api/inverters` | Handler already validates, assigns IDs, saves config |
| Duplicate detection | Complex diffing logic | Compare `host:port:unit_id` tuples | Simple string comparison against configured inverters |
| Toast notifications | Custom notification system | Existing `showToast(msg, type)` | Already built with duplicate suppression, auto-dismiss |

**Key insight:** Every backend and frontend building block exists. This phase is purely integration -- connecting scanner output to inverter CRUD through a WebSocket progress channel.

## Common Pitfalls

### Pitfall 1: Race Condition on Concurrent Scans
**What goes wrong:** User clicks discover twice, two scans run simultaneously, SolarEdge rejects second connection.
**Why it happens:** No guard against concurrent scan execution.
**How to avoid:** Set `app["_scan_running"]` flag, return 409 if already running. Frontend also disables button.
**Warning signs:** "Connection refused" errors from SolarEdge during scan.

### Pitfall 2: Progress Callback is Synchronous
**What goes wrong:** `progress_callback` in `scan_subnet` is called synchronously. If you try to `await` inside it, it fails.
**Why it happens:** The callback is invoked from within the async `for coro in asyncio.as_completed(tasks)` loop but is not an async function itself.
**How to avoid:** Use `asyncio.ensure_future()` to schedule WS broadcast from sync callback context. This works because the callback runs inside the event loop.
**Warning signs:** `RuntimeWarning: coroutine was never awaited`.

### Pitfall 3: Stale UI After Scan
**What goes wrong:** User adds discovered inverters but the inverter list doesn't update.
**Why it happens:** Forgetting to call `loadInverters()` after batch-adding confirmed devices.
**How to avoid:** After all POST requests complete, call `loadInverters()` to refresh the list.

### Pitfall 4: Auto-Scan Infinite Loop
**What goes wrong:** Auto-scan triggers, finds 0 results, list is still empty, auto-scan triggers again on next `loadInverters()` call.
**Why it happens:** `loadInverters()` is called after mutations, and each call checks for empty list.
**How to avoid:** Only trigger auto-scan when navigating TO the config page (not after every `loadInverters()` call). Use a module-level flag like `_autoScanTriggered` that resets when leaving config page, or gate the auto-scan check to only run on initial load/navigation.
**Warning signs:** Network tab showing repeated POST /api/scanner/discover calls.

### Pitfall 5: Ports Field Sync
**What goes wrong:** User changes ports in the UI but scan uses old ports.
**Why it happens:** Ports field value not sent with scan request, or not saved to config before scan starts.
**How to avoid:** Read ports from input field when scan is triggered, pass as parameter to `POST /api/scanner/discover`. Save to config on blur/change.

## Code Examples

### Progress Bar HTML + CSS
```html
<!-- Below #inverter-list, inside #inverter-panel -->
<div id="scan-area" style="display:none">
  <div id="scan-progress" class="ve-scan-progress">
    <div class="ve-scan-bar">
      <div class="ve-scan-bar-fill" style="width:0%"></div>
    </div>
    <span class="ve-scan-status"></span>
  </div>
  <div id="scan-results"></div>
</div>
```

```css
.ve-scan-progress { padding: 12px 16px; }
.ve-scan-bar {
  height: 6px;
  background: var(--ve-border);
  border-radius: 3px;
  overflow: hidden;
}
.ve-scan-bar-fill {
  height: 100%;
  background: var(--ve-blue);
  border-radius: 3px;
  transition: width var(--ve-duration-fast) var(--ve-easing-default);
}
.ve-scan-status {
  display: block;
  margin-top: 6px;
  font-size: 0.85rem;
  color: var(--ve-text-dim);
}
```

### Scan Result Row
```javascript
function createScanResultRow(device, isConfigured) {
    var row = document.createElement('div');
    row.className = 've-scan-result';
    if (isConfigured) row.classList.add('ve-scan-result--configured');

    var identity = (device.manufacturer + ' ' + device.model).trim();
    var hostPort = device.ip + ':' + device.port;

    if (isConfigured) {
        row.innerHTML =
            '<span class="ve-scan-result-configured">Bereits konfiguriert</span>' +
            '<span class="ve-scan-result-host">' + hostPort + '</span>' +
            '<span class="ve-scan-result-identity">' + identity + '</span>' +
            '<span class="ve-scan-result-unit">Unit ' + device.unit_id + '</span>';
    } else {
        row.innerHTML =
            '<label class="ve-scan-result-check"><input type="checkbox" checked></label>' +
            '<span class="ve-scan-result-host">' + hostPort + '</span>' +
            '<span class="ve-scan-result-identity">' + identity + '</span>' +
            '<span class="ve-scan-result-unit">Unit ' + device.unit_id + '</span>';
    }
    row._device = device;
    return row;
}
```

### Batch Add Confirmed Devices
```javascript
async function addDiscoveredInverters(devices) {
    var added = 0;
    for (var i = 0; i < devices.length; i++) {
        var d = devices[i];
        try {
            var res = await fetch('/api/inverters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    host: d.ip, port: d.port, unit_id: d.unit_id,
                    manufacturer: d.manufacturer, model: d.model,
                    serial: d.serial_number, firmware_version: d.firmware_version,
                    enabled: true
                })
            });
            if (res.status === 201) added++;
        } catch (e) {
            console.error('Failed to add inverter:', d.ip, e);
        }
    }
    if (added > 0) {
        showToast(added + ' Inverter hinzugefuegt', 'success');
        loadInverters();
    }
}
```

### Auto-Scan Trigger
```javascript
// In loadInverters(), after setting empty-list hint:
if (!inverters || inverters.length === 0) {
    // ... show hint card ...
    // Auto-scan: only on page navigation, not after mutations
    if (!_scanRunning && !_autoScanDone) {
        _autoScanDone = true;
        triggerScan();
    }
    return;
}
```

### Duplicate Detection
```javascript
function isAlreadyConfigured(device, configuredInverters) {
    return configuredInverters.some(function(inv) {
        return inv.host === device.ip &&
               inv.port === device.port &&
               inv.unit_id === device.unit_id;
    });
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Blocking scan endpoint | Background task + WS streaming | Phase 20 | UI remains responsive during 30s scan |
| Manual inverter entry only | Auto-discover + manual | Phase 20 | Zero-config onboarding for new installations |
| No scanner config in YAML | `scanner.ports` in config | Phase 20 | Ports are persistent across restarts |

## Open Questions

1. **Progress callback threading model**
   - What we know: `progress_callback` is called synchronously within `scan_subnet`'s async loop
   - What's unclear: Whether `asyncio.ensure_future()` from within the same event loop will cause ordering issues with rapid progress updates
   - Recommendation: Test with throttling -- only broadcast every N progress updates (e.g., every 5th probe) to avoid WS message flooding. A /24 subnet with 2 ports = 508 probes; broadcasting all 508 would flood the WS.

2. **Batch add vs sequential add**
   - What we know: `POST /api/inverters` handles single inverter adds. Each call triggers `save_config()` which writes YAML atomically.
   - What's unclear: Whether rapid sequential POSTs cause file write contention
   - Recommendation: Sequential `await fetch()` calls (not `Promise.all()`) to avoid concurrent config writes. Or implement a batch add endpoint.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 with pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_scanner.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DISC-05 | WS progress broadcast during scan | unit | `pytest tests/test_scanner.py -x -k scan_progress` | No -- Wave 0 |
| CONF-04 | Scan results -> config entries via POST /api/inverters | integration | `pytest tests/test_webapp.py -x -k discover` | No -- Wave 0 |
| UX-01 | Auto-scan on empty inverter list | manual-only | Manual: open config page with no inverters | N/A |
| UX-02 | Manual re-scan via discover button | manual-only | Manual: click discover button | N/A |
| UX-03 | Scan results preview with checkboxes | manual-only | Manual: verify result list UI | N/A |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scanner.py tests/test_webapp.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_scanner.py` -- add test for background scan task + WS progress broadcasting
- [ ] `tests/test_webapp.py` -- add test for enhanced scanner_discover_handler returning {"status": "started"} and concurrent scan guard (409)
- [ ] `tests/test_config.py` -- add test for `ScannerConfig` dataclass and YAML round-trip of `scanner.ports`

## Sources

### Primary (HIGH confidence)
- `src/venus_os_fronius_proxy/scanner.py` -- `scan_subnet` signature, `progress_callback(phase, current, total)`, `DiscoveredDevice` fields
- `src/venus_os_fronius_proxy/webapp.py` -- `scanner_discover_handler`, `ws_handler`, `broadcast_to_clients`, `inverters_add_handler` signatures
- `src/venus_os_fronius_proxy/static/app.js` -- `loadInverters()`, `createInverterRow()`, `showToast()`, WS message routing pattern
- `src/venus_os_fronius_proxy/config.py` -- `Config` dataclass, `InverterEntry` fields, `save_config`/`load_config`
- `src/venus_os_fronius_proxy/static/index.html` -- inverter panel HTML structure

### Secondary (MEDIUM confidence)
- aiohttp `asyncio.create_task()` pattern for background work -- standard asyncio pattern, well-documented

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all existing project dependencies, no new libraries
- Architecture: HIGH -- all integration points inspected, signatures verified in source code
- Pitfalls: HIGH -- based on actual code inspection (sync callback, single Modbus connection constraint)

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable -- no external dependencies changing)
