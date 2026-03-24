# Phase 29: Switch Control & Config Wiring - Research

**Researched:** 2026-03-24
**Domain:** Shelly relay switch control via webapp API + config wiring for plugin factory
**Confidence:** HIGH

## Summary

Phase 29 wires together the Shelly switch control infrastructure that Phase 28 already built at the profile level. The Gen1Profile.switch() and Gen2Profile.switch() methods are fully implemented -- Gen1 uses `GET /relay/0?turn=on|off`, Gen2 uses `POST /rpc/Switch.Set` with JSON body `{"id": 0, "on": true/false}`. What is missing is: (1) a webapp API route to expose switch commands to the frontend, (2) the relay_on state surfaced in the device snapshot so the UI can show current switch state, and (3) config wiring so Shelly devices default to `throttle_enabled: false` when added through the webapp.

The existing codebase provides a clean reference pattern: the OpenDTU power control route at `POST /api/devices/{id}/opendtu/power` demonstrates exactly how device-specific control endpoints are structured -- type check the plugin, parse JSON body, call the plugin method, return success/error. The Shelly switch route follows this same pattern with a simpler body (`{"on": true/false}`).

The ShellyPlugin already encodes relay_on into the SunSpec status register (MPPT=4 when on, SLEEPING=2 when off), so the dashboard already shows "MPPT" or "SLEEPING". However, the frontend needs an explicit `relay_on` boolean for the on/off buttons rather than decoding SunSpec status codes.

**Primary recommendation:** Add a `POST /api/devices/{id}/shelly/switch` route following the OpenDTU power control pattern, surface `relay_on` in the device snapshot via a public accessor on ShellyPlugin, and default `throttle_enabled=False` for Shelly entries in the add handler.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CTRL-01 | On/Off Switch-Steuerung per Webapp (relay on/off statt Power-Limit Prozent) | Gen1Profile.switch() and Gen2Profile.switch() already implemented. Need webapp API route at POST /api/devices/{id}/shelly/switch and ShellyPlugin.switch() public method that delegates to profile. See "Switch Control API Route" section. |
| CTRL-02 | Switch-Status (on/off) in Connection Card anzeigen | relay_on is already in ShellyPollData and encoded as SunSpec status (MPPT/SLEEPING). Need to expose explicit relay_on boolean in device snapshot. See "Switch State in Snapshot" section. |
| CTRL-03 | write_power_limit() als No-Op, throttle_enabled default false | write_power_limit() already returns WriteResult(success=True). Need inverters_add_handler to default throttle_enabled=False for type="shelly". See "Config Wiring" section. |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiohttp | >=3.10,<4.0 | HTTP server (webapp routes) + client (Shelly API calls) | Already used for all webapp routes and Shelly HTTP calls |
| structlog | >=24.0 | Structured logging for switch actions | Already used project-wide |

### Supporting

No new libraries needed. All changes are within existing modules.

**Installation:**
```bash
# No new packages needed
pip install -e .  # existing command unchanged
```

## Architecture Patterns

### Files to Modify

```
src/pv_inverter_proxy/
  plugins/
    shelly.py               # MODIFY: add public switch() method, relay_on accessor
  webapp.py                 # MODIFY: add shelly_switch_handler, update inverters_add_handler
  config.py                 # NO CHANGE: throttle_enabled default already in InverterEntry
```

### Pattern 1: Device-Specific Control Route (Reference: OpenDTU Power Handler)

**What:** Add `POST /api/devices/{id}/shelly/switch` following the exact pattern of `opendtu_power_handler` at webapp.py line 1717.

**When to use:** Any device type needs a control action beyond standard poll/power-limit.

**Example:**
```python
# Source: Existing opendtu_power_handler pattern at webapp.py:1717
async def shelly_switch_handler(request: web.Request) -> web.Response:
    """Send on/off command to a Shelly device relay.

    Body: {"on": true|false}
    """
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    ds = app_ctx.devices.get(device_id)
    if not ds or not ds.plugin:
        return web.json_response({"success": False, "error": "Device not found"}, status=404)

    if not isinstance(ds.plugin, ShellyPlugin):
        return web.json_response({"success": False, "error": "Not a Shelly device"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    on = body.get("on")
    if on is None or not isinstance(on, bool):
        return web.json_response({"success": False, "error": "'on' must be true or false"}, status=400)

    success = await ds.plugin.switch(on)
    log.info("user_action", action=f"shelly_switch_{'on' if on else 'off'}", device_id=device_id)
    return web.json_response({"success": success})
```

### Pattern 2: Public Plugin Method Delegating to Profile

**What:** Add `ShellyPlugin.switch(on: bool) -> bool` that delegates to `self._profile.switch(session, host, on)`.

**When to use:** Exposing a profile-level capability through the plugin's public API.

**Example:**
```python
# Source: Follows existing profile delegation pattern in ShellyPlugin.poll()
async def switch(self, on: bool) -> bool:
    """Switch relay on/off. Delegates to the generation-specific profile."""
    if self._session is None or self._profile is None:
        return False
    try:
        return await self._profile.switch(self._session, self._host, on)
    except Exception as e:
        log.warning("shelly_switch_failed", host=self._host, on=on, error=str(e))
        return False
```

### Pattern 3: Switch State in Device Snapshot

**What:** Add `relay_on` boolean to the device snapshot so the frontend can show on/off state and buttons.

**When to use:** Device-specific state that the generic dashboard snapshot does not capture.

**Approach:** The SunSpec status register already encodes relay_on (MPPT=4 vs SLEEPING=2), which the dashboard decodes as a status string. For CTRL-02, two options exist:

**Option A (recommended): Decode from existing status in snapshot**
The snapshot already contains `inverter.status` = "MPPT" or "SLEEPING". The frontend can derive: `relay_on = (status === "MPPT")`. This requires zero backend changes for CTRL-02 -- the frontend interprets existing data.

**Option B: Add explicit relay_on to snapshot**
Add a `relay_on` property to ShellyPlugin, update `collect_from_raw` to include it. This is cleaner but requires touching DashboardCollector which is shared code.

**Recommendation:** Use Option A for the snapshot (zero DashboardCollector changes). The switch handler response can confirm the new state. The frontend uses the status field from the existing snapshot to derive relay_on.

### Pattern 4: Config Wiring for throttle_enabled Default

**What:** When adding a Shelly device via `inverters_add_handler`, default `throttle_enabled=False`.

**Where:** webapp.py `inverters_add_handler` (line 1529). Currently does not set throttle_enabled based on device type.

**Example:**
```python
# In inverters_add_handler, after creating InverterEntry:
entry = InverterEntry(
    ...
    type=dev_type,
    throttle_enabled=body.get("throttle_enabled", dev_type != "shelly"),
    ...
)
```

### Anti-Patterns to Avoid

- **Adding a ShellyPlugin-specific field to DashboardCollector.collect_from_raw():** This method is generic over all plugin types. Adding relay_on here creates plugin-specific coupling. Use the existing status field instead.
- **Using write_power_limit() for switch control:** write_power_limit() is the ABC method for percentage-based throttling via Venus OS/PowerLimitDistributor. Switch on/off is a separate control path with different semantics.
- **Returning error from write_power_limit():** The distributor retries on failure. A no-op must return success to prevent retry spam.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| API route validation | Custom request parser | Follow opendtu_power_handler pattern | Proven error handling, consistent response format |
| Switch state tracking | Separate state variable | Read from SunSpec status register (MPPT vs SLEEPING) | Already tracked by poll loop, no extra state to sync |
| Device type check | isinstance in every handler | Pattern from opendtu handlers: isinstance(ds.plugin, ShellyPlugin) | Consistent with existing codebase |

**Key insight:** Phase 28 did the hard work (profiles, switch methods, SunSpec encoding). Phase 29 is pure wiring -- connecting existing profile methods to webapp routes, and setting config defaults. No new algorithmic complexity.

## Common Pitfalls

### Pitfall 1: Switch Command While Disconnected
**What goes wrong:** User clicks "switch on" in webapp before the plugin has connected (no session, no profile). The switch call fails silently or crashes.
**Why it happens:** Plugin connection is async and may not be ready when the user interacts.
**How to avoid:** ShellyPlugin.switch() must check `self._session is not None and self._profile is not None` before delegating. Return False with a log warning if not connected.
**Warning signs:** 500 errors on POST /api/devices/{id}/shelly/switch.

### Pitfall 2: Switch State Stale Until Next Poll
**What goes wrong:** User switches relay off, but the dashboard still shows "MPPT" (on) for up to 5 seconds until the next poll cycle updates the SunSpec status register.
**Why it happens:** The switch command fires-and-forgets to the Shelly device. The poll loop is the only source of truth for displayed state.
**How to avoid:** Accept this as expected behavior (5s stale window is acceptable at 5s poll intervals). The frontend can show an "updating..." intermediate state after the switch command returns. No need to force an immediate poll.
**Warning signs:** UI confusion if the button state flips instantly but the status badge does not.

### Pitfall 3: Forgetting throttle_enabled Default for Shelly
**What goes wrong:** User adds a Shelly device and the PowerLimitDistributor tries to send percentage limits to it. write_power_limit() succeeds as no-op, but the distributor wastes budget allocation on a device that cannot actually throttle.
**Why it happens:** InverterEntry defaults throttle_enabled=True. Shelly devices need it False.
**How to avoid:** Set `throttle_enabled=False` when `type="shelly"` in the add handler.
**Warning signs:** Uneven power distribution in the distributor logs when Shelly devices absorb limit budget they cannot apply.

### Pitfall 4: Plugin Factory Already Wired
**What goes wrong:** Developer adds a second "shelly" branch in plugin_factory, not realizing Phase 28 already added it.
**Why it happens:** Not reading the current codebase before implementing.
**How to avoid:** The plugin factory at `plugins/__init__.py` already handles `type="shelly"`. Verify before modifying.
**Warning signs:** Duplicate elif branches.

## Code Examples

### Existing Gen1 Switch Method (Already Implemented)
```python
# Source: plugins/shelly_profiles.py line 74
async def switch(self, session: aiohttp.ClientSession, host: str, on: bool) -> bool:
    """Send GET http://{host}/relay/0?turn=on|off."""
    action = "on" if on else "off"
    url = f"http://{host}/relay/0?turn={action}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        await resp.json()
    return True
```

### Existing Gen2 Switch Method (Already Implemented)
```python
# Source: plugins/shelly_profiles.py line 118
async def switch(self, session: aiohttp.ClientSession, host: str, on: bool) -> bool:
    """POST http://{host}/rpc/Switch.Set with JSON body."""
    url = f"http://{host}/rpc/Switch.Set"
    payload = {"id": 0, "on": on}
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        await resp.json()
    return True
```

### Existing OpenDTU Power Handler (Reference Pattern)
```python
# Source: webapp.py line 1717
async def opendtu_power_handler(request: web.Request) -> web.Response:
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    ds = app_ctx.devices.get(device_id)
    if not ds or not ds.plugin:
        return web.json_response({"success": False, "error": "Device not found"}, status=404)
    if not isinstance(ds.plugin, OpenDTUPlugin):
        return web.json_response({"success": False, "error": "Not an OpenDTU device"}, status=400)
    body = await request.json()
    action = body.get("action", "")
    result = await ds.plugin.send_power_command(action)
    return web.json_response({"success": result.success, "error": result.error})
```

### Route Registration Pattern
```python
# Source: webapp.py line 1819-1820 (OpenDTU reference)
app.router.add_post("/api/devices/{id}/shelly/switch", shelly_switch_handler)
```

## Existing Implementation Inventory

What Phase 28 already built (verified by reading current source):

| Component | Status | Location |
|-----------|--------|----------|
| ShellyPlugin class | Complete | `plugins/shelly.py` |
| Gen1Profile.switch() | Complete | `plugins/shelly_profiles.py:74` |
| Gen2Profile.switch() | Complete | `plugins/shelly_profiles.py:118` |
| write_power_limit() no-op | Complete | `plugins/shelly.py:231` |
| plugin_factory "shelly" branch | Complete | `plugins/__init__.py:40` |
| InverterEntry.shelly_gen field | Complete | `config.py:45` |
| relay_on in ShellyPollData | Complete | `plugins/shelly_profiles.py:30` |
| relay_on mapped to SunSpec status | Complete | `plugins/shelly.py:177` (MPPT=4/SLEEPING=2) |
| Test suite (PLUG-01 to PLUG-07) | Complete | `tests/test_shelly_plugin.py` |

What Phase 29 must add:

| Component | Action | Location |
|-----------|--------|----------|
| ShellyPlugin.switch() public method | Add | `plugins/shelly.py` |
| shelly_switch_handler API route | Add | `webapp.py` |
| Route registration | Add | `webapp.py` create_app() |
| throttle_enabled default for Shelly | Modify | `webapp.py` inverters_add_handler |
| Tests for switch + config wiring | Add | `tests/test_shelly_plugin.py` (extend) |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/test_shelly_plugin.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTRL-01 | ShellyPlugin.switch(True/False) delegates to profile and returns bool | unit | `pytest tests/test_shelly_plugin.py::TestSwitchControl -x` | Wave 0 |
| CTRL-01 | POST /api/devices/{id}/shelly/switch returns success JSON | integration | `pytest tests/test_webapp.py::TestShellySwitchRoute -x` | Wave 0 |
| CTRL-02 | Device snapshot status is "MPPT" when relay on, "SLEEPING" when off | unit | `pytest tests/test_shelly_plugin.py::TestRegisterEncoding::test_status_mppt_when_relay_on -x` | Exists (Phase 28) |
| CTRL-03 | write_power_limit() returns success=True always | unit | `pytest tests/test_shelly_plugin.py::TestWritePowerLimit -x` | Exists (Phase 28) |
| CTRL-03 | inverters_add with type=shelly defaults throttle_enabled=False | unit | `pytest tests/test_webapp.py::TestShellyThrottleDefault -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_shelly_plugin.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_shelly_plugin.py::TestSwitchControl` -- CTRL-01 unit tests for ShellyPlugin.switch()
- [ ] `tests/test_webapp.py` -- CTRL-01 integration test for shelly_switch_handler route (or separate test file)
- [ ] `tests/test_webapp.py` -- CTRL-03 test for throttle_enabled default when adding Shelly
- Note: CTRL-02 and CTRL-03 (write_power_limit no-op) are already tested by Phase 28 test suite

## Open Questions

1. **Should switch handler trigger an immediate poll?**
   - What we know: After switching, the status register remains stale until the next poll cycle (up to 5s).
   - What's unclear: Whether users expect instant UI feedback.
   - Recommendation: Do not force immediate poll. The 5s delay is acceptable. The switch handler's success response confirms the command was sent. Frontend can show a transient "updating" indicator.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `plugins/shelly.py` (ShellyPlugin with write_power_limit no-op), `plugins/shelly_profiles.py` (Gen1/Gen2 switch methods), `webapp.py` (opendtu_power_handler reference pattern), `config.py` (InverterEntry), `distributor.py` (throttle_enabled check), `device_registry.py` (DeviceState/plugin accessor)
- Phase 28 research: `.planning/phases/28-plugin-core-profiles/28-RESEARCH.md` (Shelly API endpoints, profile pattern)

### Secondary (MEDIUM confidence)
- Shelly Gen1 relay endpoint: `GET /relay/0?turn=on|off` (documented in Phase 28 research, verified in code)
- Shelly Gen2 Switch.Set endpoint: `POST /rpc/Switch.Set` with `{"id": 0, "on": bool}` (documented in Phase 28 research, verified in code)

## Metadata

**Confidence breakdown:**
- Switch control implementation: HIGH -- profile methods already exist, webapp pattern proven by OpenDTU
- Config wiring: HIGH -- clear one-line change in add handler, distributor already checks throttle_enabled
- Switch state visibility: HIGH -- SunSpec status register already encodes relay_on, dashboard decodes it
- Test coverage: HIGH -- existing test suite covers PLUG-01 through PLUG-07, Phase 29 adds switch + config tests

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (implementation is pure wiring of existing components)
