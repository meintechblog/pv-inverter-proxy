# Phase 30: Add-Device Flow & Discovery - Research

**Researched:** 2026-03-24
**Domain:** Webapp UI for adding Shelly devices (add-device modal, generation probe, mDNS discovery, config page)
**Confidence:** HIGH

## Summary

Phase 30 extends the existing add-device modal in app.js with a third device type card ("Shelly Device"), a Shelly-specific form, an auto-detection probe on Add click, and mDNS-based LAN discovery. All infrastructure exists: the type picker pattern, form rendering per type, hint-card feedback, WebSocket-based scan progress, and the zeroconf library for mDNS. The backend already imports ShellyPlugin, InverterEntry already has `shelly_gen` and `rated_power` fields, and `inverters_add_handler` already sets `throttle_enabled=False` for Shelly.

The work is purely additive: add a third card to the type picker, add a "shelly" branch in `showAddForm()`, create a `/api/shelly/probe` endpoint that calls `GET /shelly` on the target IP and returns the generation + model, create a `/api/shelly/discover` endpoint that browses `_shelly._tcp.local.` via zeroconf, and extend `buildInverterConfigForm()` with Shelly-specific fields (readonly generation badge, rated power input).

The main risk is mDNS: Gen1 Shelly devices do NOT advertise `_shelly._tcp` (only Gen2+). The CONTEXT.md locks mDNS as the discovery method, so Gen1 devices that don't advertise this service won't appear in discovery results. This is acceptable -- Gen1 devices can still be added manually by IP.

**Primary recommendation:** Follow the existing OpenDTU auth-test pattern for the probe (fetch to backend, hint-card result in form area) and the existing MQTT mDNS discovery pattern for Shelly discovery (same zeroconf library, same `AsyncServiceBrowser` + `AsyncServiceInfo` flow, different service type).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Add-device modal shows "Shelly Device" as third type card alongside "SolarEdge Inverter" and "OpenDTU Inverter"
- **D-02:** Shelly form fields: Host IP (required), Name (optional), Rated Power in W (optional, default 0)
- **D-03:** Rated power defaults to 0W (empty). User fills in if Shelly monitors a micro-inverter for WRtg aggregation
- **D-04:** Generation probe triggers automatically on Add click (single-click flow). User enters IP, clicks Add, app probes /shelly, shows result, saves
- **D-05:** Successful probe shows green hint-card in the form area with detected generation (Gen1/Gen2/Gen3) and model name, then auto-saves
- **D-06:** Failed probe (unreachable, not a Shelly) shows hint-card in the form area (not a toast) so user can correct the IP and retry. Consistent with existing OpenDTU auth-test pattern
- **D-07:** Discovery uses mDNS (`_shelly._tcp` service) as primary method via zeroconf library. Faster and more reliable than IP-range HTTP scanning
- **D-08:** Discover button scope is type-filtered: when Shelly is selected, only mDNS discovery runs. Existing Modbus/SunSpec scan runs only when SolarEdge is selected
- **D-09:** Discovery results show in the same checkbox-list pattern as existing scan results (Phase 20 pattern)
- **D-10:** Shelly device config page shows: Host IP (editable), Generation (readonly badge -- Gen1/Gen2), Rated Power (editable, W)
- **D-11:** Generation is readonly because it's auto-detected and cannot change for a given device

### Claude's Discretion
- Exact hint-card text for successful/failed probe
- mDNS browse timeout duration
- Discovery result card styling details
- How to handle mDNS unavailability (fallback or error message)
- Whether to show MAC/firmware info from /shelly response in discovery results

### Deferred Ideas (OUT OF SCOPE)
- Plugin Deployment Runbook -- belongs in documentation, not a phase
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | "Shelly Device" als dritte Option im Add-Device Dialog | Add third `ve-add-type-card` with `data-type="shelly"` to `showAddDeviceModal()`. Pattern identical to existing two cards. |
| UI-02 | Auto-Detection und Generation-Anzeige beim Hinzufuegen (testet /shelly Endpoint) | New `/api/shelly/probe` endpoint in webapp.py, called from Add button handler in app.js. Follows OpenDTU auth-test pattern exactly. |
| UI-05 | Config-Seite mit Shelly-Host und erkannter Generation (readonly) | Extend `buildInverterConfigForm()` with Shelly branch: host (editable), generation (readonly badge), rated_power (editable). |
| UI-06 | Auto-Discovery von Shelly-Devices im LAN | New `discover_shelly_devices()` in a shelly_discovery.py module using zeroconf `_shelly._tcp.local.` + `/shelly` probe. New `/api/shelly/discover` endpoint. |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| zeroconf | >=0.140,<1.0 | mDNS browsing for `_shelly._tcp.local.` | Already in project deps, used by MQTT discovery |
| aiohttp | >=3.10,<4.0 | HTTP probe to `/shelly` endpoint on discovered devices | Already in project, used everywhere |

### Supporting

No new libraries needed. Both zeroconf and aiohttp are existing project dependencies.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mDNS `_shelly._tcp` | IP-range HTTP scan with `/shelly` probe | Slower (scans 254+ IPs), noisier, but finds Gen1 devices that don't advertise `_shelly._tcp`. mDNS is the locked decision (D-07). |
| Separate discovery module | Inline in webapp.py | Discovery logic is reusable and testable. Separate module follows MQTT discovery pattern. |

## Architecture Patterns

### Recommended File Changes
```
src/pv_inverter_proxy/
  shelly_discovery.py        # NEW: discover_shelly_devices() via mDNS (~60 LOC)
  webapp.py                  # MODIFY: add /api/shelly/probe and /api/shelly/discover endpoints
  static/
    app.js                   # MODIFY: add Shelly card, form, probe flow, discovery integration
    style.css                # MODIFY: minor -- generation badge styling (if needed)
```

### Pattern 1: Shelly Probe Endpoint (follows OpenDTU auth-test)

**What:** Backend endpoint that probes a Shelly device at a given IP by calling `GET http://{ip}/shelly`, returns generation + device info.

**When to use:** When user clicks Add for a Shelly device.

**Example:**
```python
# Source: Existing OpenDTU test-auth pattern in webapp.py
async def shelly_probe_handler(request: web.Request) -> web.Response:
    """POST /api/shelly/probe -- probe a Shelly device at given host."""
    try:
        body = await request.json()
        host = body["host"]
    except (KeyError, ValueError, TypeError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{host}/shelly"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()

        gen_value = data.get("gen", 0)
        generation = "gen2" if gen_value >= 2 else "gen1"
        # Gen2: "app" field has model name; Gen1: "type" field
        model = data.get("app", data.get("type", "Unknown"))
        mac = data.get("mac", "")

        return web.json_response({
            "success": True,
            "generation": generation,
            "model": model,
            "mac": mac,
            "gen_display": f"Gen{gen_value}" if gen_value >= 2 else "Gen1",
        })
    except Exception as e:
        return web.json_response({
            "success": False,
            "error": f"Could not reach Shelly at {host}: {e}",
        })
```

### Pattern 2: Shelly mDNS Discovery (follows MQTT discovery)

**What:** Browse `_shelly._tcp.local.` via zeroconf, then probe each found device's `/shelly` endpoint to get full info.

**When to use:** User clicks Discover button with Shelly type selected.

**Example:**
```python
# Source: Existing mdns_discovery.py pattern
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf, AsyncServiceInfo

SHELLY_SERVICE_TYPE = "_shelly._tcp.local."

async def discover_shelly_devices(timeout: float = 3.0) -> list[dict]:
    """Scan LAN for Shelly devices via mDNS _shelly._tcp.local. service."""
    found_names: list[str] = []

    def on_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found_names.append(name)

    aiozc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(
            aiozc.zeroconf, SHELLY_SERVICE_TYPE, handlers=[on_state_change]
        )
        await asyncio.sleep(timeout)
        await browser.async_cancel()

        results = []
        for name in found_names:
            info = AsyncServiceInfo(SHELLY_SERVICE_TYPE, name)
            await info.async_request(aiozc.zeroconf, timeout=1000)
            if info.server and info.port:
                ip = info.server.rstrip(".")
                # Also resolve IP from addresses if hostname doesn't resolve
                if info.addresses:
                    import socket
                    ip = socket.inet_ntoa(info.addresses[0])

                # Extract TXT records for gen, app, ver
                txt = {}
                if info.properties:
                    for k, v in info.properties.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else str(v)
                        txt[key] = val

                results.append({
                    "host": ip,
                    "name": name.replace(f".{SHELLY_SERVICE_TYPE}", ""),
                    "generation": f"gen{txt.get('gen', '1')}",
                    "model": txt.get("app", ""),
                    "firmware": txt.get("ver", ""),
                })

        return results
    finally:
        await aiozc.async_close()
```

### Pattern 3: Type-Filtered Discovery (D-08)

**What:** The Discover button calls different endpoints depending on the selected device type. Shelly calls `/api/shelly/discover`, SolarEdge calls `/api/scanner/discover`.

**When to use:** Add-device modal Discover button.

**Example:**
```javascript
// Source: Existing triggerAddModalScan pattern in app.js
// In the Discover button handler, check selectedType:
if (selectedType === 'shelly') {
    triggerShellyDiscover(formArea);
} else {
    triggerAddModalScan(formArea);  // existing Modbus/OpenDTU scan
}
```

### Pattern 4: Shelly Config Page Fields (D-10, D-11)

**What:** Extend `buildInverterConfigForm()` to show Shelly-specific fields when `device.type === 'shelly'`.

**When to use:** Device config page for Shelly devices.

**Example:**
```javascript
// Source: Existing buildInverterConfigForm pattern
// After the common fields (name, host), add Shelly-specific:
if (device.type === 'shelly') {
    // Generation badge (readonly)
    html += '<div class="ve-form-group"><label>Generation</label>' +
        '<input type="text" class="ve-input" value="' + esc(device.shelly_gen || 'Unknown') + '" readonly style="opacity:0.6"></div>';
    // Rated Power (editable)
    html += '<div class="ve-form-group"><label>Rated Power (W)</label>' +
        '<input type="number" class="ve-input ve-cfg-rated-power" value="' + (device.rated_power || 0) + '" min="0"></div>';
}
```

### Anti-Patterns to Avoid

- **Running Modbus scan when Shelly is selected:** Type-filtered discovery (D-08) means only the relevant scan runs. Don't scan all protocols on every discover click.
- **Using a toast for probe errors:** D-06 explicitly says hint-card in form area, consistent with OpenDTU auth-test pattern.
- **Making generation editable:** D-11 locks it as readonly. Users cannot change a device's generation.
- **Probing before Add click:** D-04 says probe triggers on Add click (single-click flow), not on a separate "Test" button.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| mDNS browsing | Custom UDP multicast listener | zeroconf `AsyncServiceBrowser` | Already in project, handles all mDNS complexity |
| HTTP probe | Custom socket connection | aiohttp.ClientSession with timeout | Already in project, handles timeouts/errors cleanly |
| Progress UI | Custom progress component | Existing `ve-scan-progress` + `ve-hint-card` CSS | Established patterns from Phase 20 |
| Device type cards | New UI component | Existing `ve-add-type-card` pattern | Just add a third card to the picker |
| Form rendering | New form system | Existing `showAddForm()` switch pattern | Add "shelly" branch |

**Key insight:** Every UI pattern needed already exists -- type picker cards, per-type form rendering, hint-card feedback, scan result lists. This phase is purely additive: add one more branch to each existing switch/if-else.

## Common Pitfalls

### Pitfall 1: Gen1 Devices Not Found via mDNS
**What goes wrong:** Users with Gen1 Shelly devices click Discover and find nothing, because Gen1 does NOT advertise `_shelly._tcp.local.` (only Gen2+ does).
**Why it happens:** Gen1 devices only advertise `_http._tcp.local.` which is too generic for targeted discovery.
**How to avoid:** Show a hint when discovery returns empty results: "No Shelly devices found via mDNS. Gen1 devices may not support mDNS discovery -- enter the IP manually." This is Claude's discretion per CONTEXT.md.
**Warning signs:** Empty discovery results on a network with known Gen1 Shelly devices.

### Pitfall 2: Probe Timeout Too Short
**What goes wrong:** Shelly device is reachable but slow to respond (especially Gen1 on WiFi). Probe fails with timeout, user thinks device is unreachable.
**Why it happens:** Shelly devices on congested WiFi can take 2-3 seconds to respond to HTTP.
**How to avoid:** Use 5-second timeout for the probe (matching the existing ShellyPlugin connect timeout). Don't go shorter than 3 seconds.
**Warning signs:** Intermittent "Could not reach" errors for devices that work fine when polled.

### Pitfall 3: Not Persisting shelly_gen After Probe
**What goes wrong:** Device is added without `shelly_gen` field, so on next restart the ShellyPlugin has to auto-detect again (extra HTTP call on every connect).
**Why it happens:** Probe result not passed to the add handler's InverterEntry construction.
**How to avoid:** The probe endpoint returns `generation`, the frontend passes it in the add payload, and `inverters_add_handler` stores it in `entry.shelly_gen`.
**Warning signs:** `shelly_gen: ""` in config.yaml for devices that were successfully probed.

### Pitfall 4: Discovery Results Not Deduped Against Existing Devices
**What goes wrong:** Discovery shows Shelly devices that are already configured, confusing the user.
**Why it happens:** mDNS returns ALL Shelly devices, including ones already in the config.
**How to avoid:** Filter discovery results against `config.inverters` by IP before returning. Same pattern as `_run_scan` which uses `skip_ips`.
**Warning signs:** Duplicate devices after clicking a discovery result that was already configured.

### Pitfall 5: Rated Power Field Missing from Update Handler
**What goes wrong:** User changes rated_power on the config page, clicks Save, but the value doesn't persist.
**Why it happens:** `inverters_update_handler` has an explicit allowlist of fields it accepts. If `rated_power` is not in the list, the field is silently dropped.
**How to avoid:** Verify `rated_power` is in the update handler's field list. Currently it IS listed (line 1592: `"rated_power"` is in the for-loop), so this is already handled.
**Warning signs:** Rated power resets to 0 after page reload.

## Code Examples

### Existing Add-Device Type Picker (what to extend)
```javascript
// Source: app.js line 1843-1847 -- current type picker
'<div class="ve-add-type-picker">' +
'  <div class="ve-add-type-card" data-type="solaredge">SolarEdge Inverter</div>' +
'  <div class="ve-add-type-card" data-type="opendtu">OpenDTU Inverter</div>' +
'</div>'
// ADD: '<div class="ve-add-type-card" data-type="shelly">Shelly Device</div>'
```

### Existing OpenDTU Auth-Test Pattern (template for Shelly probe)
```javascript
// Source: app.js lines 1963-1988 -- auto-test before add
if (type === 'opendtu') {
    addBtn.disabled = true;
    addBtn.textContent = 'Testing...';
    fetch('/api/opendtu/test-auth', { method: 'POST', ... })
    .then(function(r) { return r.json(); })
    .then(function(result) {
        if (result.success) {
            authHint.className = 've-hint-card ve-hint-card--success';
            _doAdd();
        } else {
            authHint.className = 've-hint-card';
            authHint.innerHTML = '<div class="ve-hint-header">' + result.error + '</div>';
        }
    });
}
// Shelly probe follows identical pattern but with /api/shelly/probe
```

### Existing MQTT mDNS Discovery (template for Shelly discovery)
```python
# Source: mdns_discovery.py -- same zeroconf pattern
async def discover_mqtt_brokers(timeout: float = 3.0) -> list[dict]:
    found_names: list[str] = []
    def on_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found_names.append(name)

    aiozc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(aiozc.zeroconf, SERVICE_TYPE, handlers=[on_state_change])
        await asyncio.sleep(timeout)
        await browser.async_cancel()
        # ... resolve each name to host/port
    finally:
        await aiozc.async_close()
```

### /shelly Response Samples (for probe parsing)
```json
// Gen1 response -- no "gen" field
{"type": "SHSW-PM", "mac": "AABBCCDDEEFF", "auth": false, "fw": "20230913-114244/v1.14.0-gcb84623"}

// Gen2 response -- "gen": 2
{"id": "shellyplus1pm-aabbccddeeff", "mac": "AABBCCDDEEFF", "model": "SNSW-001P16EU", "gen": 2, "fw_id": "20231107-164738/1.0.8-g", "ver": "1.0.8", "app": "Plus1PM", "auth_en": false}

// Gen3 response -- "gen": 3
{"id": "shelly1pmminig3-aabbccddeeff", "mac": "AABBCCDDEEFF", "model": "S3SW-001P8EU", "gen": 3, "fw_id": "20240101-...", "ver": "1.2.0", "app": "Mini1PMG3", "auth_en": false}
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/test_shelly_discovery.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | Shelly type card added to modal (visual, no backend logic) | manual-only | N/A -- visual check in browser | N/A |
| UI-02 | Probe endpoint returns generation and model for valid Shelly, error for unreachable | unit | `pytest tests/test_shelly_discovery.py::TestProbeHandler -x` | Wave 0 |
| UI-05 | Config page shows Shelly-specific fields (visual) | manual-only | N/A -- visual check in browser | N/A |
| UI-06 | mDNS discovery finds Shelly devices advertising _shelly._tcp | unit | `pytest tests/test_shelly_discovery.py::TestShellyDiscovery -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_shelly_discovery.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_shelly_discovery.py` -- covers UI-02 (probe) and UI-06 (mDNS discovery)
- Mock fixtures: reuse `test_mdns_discovery.py` patterns (AsyncZeroconf mock, fake browser)
- Mock Shelly `/shelly` HTTP responses for probe tests (Gen1 and Gen2 JSON fixtures already documented in Phase 28 research)

## Open Questions

1. **Gen1 mDNS visibility**
   - What we know: Gen1 devices do NOT advertise `_shelly._tcp.local.` (only Gen2+ does). Gen1 advertises `_http._tcp.local.` which is too generic.
   - What's unclear: Whether any Gen1 firmware versions added `_shelly._tcp` support.
   - Recommendation: Accept the limitation. Show informative empty-state hint. Gen1 users add by IP manually. This aligns with D-07 which specifically chose mDNS over IP scanning.

2. **mDNS TXT record IP vs hostname**
   - What we know: `AsyncServiceInfo.server` returns a hostname (e.g., `shellyplus1pm-aabbccddeeff.local.`), not an IP. `info.addresses` returns raw IPv4 bytes.
   - What's unclear: Whether all Shelly devices have addresses populated.
   - Recommendation: Use `info.addresses[0]` converted via `socket.inet_ntoa()` for the IP. Fall back to `info.server.rstrip(".")` if no addresses. Same approach as the ShellyDiscovery Go tool.

3. **Should discovery results show MAC/firmware?**
   - What we know: mDNS TXT records include `app` (model), `ver` (firmware), and the service name contains the MAC. The `/shelly` probe also returns `mac` and `fw`.
   - What's unclear: Whether showing this extra info is worth the UI complexity.
   - Recommendation: Show model name and IP in the discovery result row (matching existing scan result card pattern). MAC/firmware is noise for most users.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `app.js` lines 1833-2027 (add-device flow), `webapp.py` lines 1530-1571 (add handler), `mdns_discovery.py` (mDNS pattern), `config.py` (InverterEntry fields), `plugins/shelly.py` (connect auto-detection)
- Existing tests: `test_mdns_discovery.py` (zeroconf mock patterns)

### Secondary (MEDIUM confidence)
- [Shelly Gen2 mDNS docs](https://shelly-api-docs.shelly.cloud/gen2/General/mDNS/) -- `_shelly._tcp` service type, TXT record fields (gen, app, ver)
- [Shelly mDNS KB article](https://kb.shelly.cloud/knowledge-base/kbsa-discovering-shelly-devices-via-mdns) -- discovery examples, TXT records
- [ShellyDiscovery Go tool](https://github.com/shelly-tools/ShellyDiscovery) -- reference mDNS implementation

### Tertiary (LOW confidence)
- Gen1 mDNS `_shelly._tcp` support -- conflicting information, official Gen2 docs imply Gen2+ only

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero new deps, both zeroconf and aiohttp already in project
- Architecture: HIGH -- all UI patterns exist and have been mapped to specific code lines
- Pitfalls: HIGH -- mDNS Gen1 limitation verified against official docs, probe patterns proven by OpenDTU flow
- Discovery: MEDIUM -- mDNS TXT record parsing untested in this project, but zeroconf pattern is identical to MQTT discovery

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (Shelly mDNS API is stable, UI patterns are internal)
