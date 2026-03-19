# Phase 13: MQTT Config Backend - Research

**Researched:** 2026-03-19
**Domain:** MQTT connection configurability, portal ID auto-discovery, connection failure detection
**Confidence:** HIGH

## Summary

Phase 13 eliminates all hardcoded Venus OS connection parameters (IP, port, portal ID) from the codebase and makes them configurable via `config.yaml`. The scope is strictly backend: add a `VenusConfig` dataclass, thread it through all MQTT consumers, parse CONNACK for real failure detection, and implement portal ID auto-discovery via MQTT wildcard subscription.

The codebase has exactly five hardcoded references across two files: `venus_reader.py` (lines 18-19: `PORTAL_ID` and `VENUS_HOST` constants) and `webapp.py` (line 598: `AsyncModbusTcpClient("192.168.3.146")`, line 677: `_mqtt_write_venus("192.168.3.146", "88a29ec1e5f4", ...)`). All five must be replaced with config reads in a single coordinated change. The existing config system (`config.py` dataclasses + `load_config`/`save_config` with atomic writes) already supports the exact extension pattern needed -- no new infrastructure required.

The MQTT CONNACK return code is currently silently ignored (`venus_reader.py` line 31 and `webapp.py` line 637), creating false-positive connections that are invisible to users. Fixing this is prerequisite to exposing MQTT status in the dashboard (Phase 14). Portal ID auto-discovery uses the documented `N/+/system/0/Serial` wildcard subscription on Venus OS MQTT broker -- HIGH confidence from official Victron documentation.

**Primary recommendation:** Extend `Config` with `VenusConfig(host, port, portal_id)`, parameterize `venus_mqtt_loop()`, de-hardcode `webapp.py`, parse CONNACK, add `discover_portal_id()` helper, store `venus_mqtt_connected` in `shared_ctx`, and store `venus_task` in `shared_ctx` for cancellable hot-reload.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CFG-03 | MQTT konfigurierbar -- Venus OS IP, Port, Portal ID als Config-Felder statt hardcoded | VenusConfig dataclass pattern mirrors existing InverterConfig. Five hardcoded references identified at exact locations. Config load/save already supports nested dataclasses. |
| CFG-04 | Portal ID Auto-Discovery per MQTT Wildcard (`N/+/system/0/Serial`) wenn Portal ID leer | Victron TOPICS.md documents `N/+/system/0/Serial` wildcard. Existing raw socket MQTT client in `venus_reader.py` already has subscribe/parse infrastructure. Portal ID is extracted from topic prefix (split on `/`, index 1). |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python dataclasses | stdlib | VenusConfig dataclass | Same pattern as InverterConfig, ProxyConfig -- zero new code patterns |
| PyYAML | existing (>=6.0) | Persist venus config section | load_config/save_config already handles nested dataclasses via `dataclasses.asdict()` |
| Python socket | stdlib | Raw MQTT client (existing) | Already implements CONNECT/SUBSCRIBE/PUBLISH/PINGREQ in venus_reader.py |
| asyncio | stdlib | Event loop, task management | Already used for venus_mqtt_loop, task cancellation for hot-reload |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | existing | Log config loading, MQTT connection events, CONNACK errors | Every new log statement |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw socket MQTT | paho-mqtt / aiomqtt | Would add dependency for no benefit; raw client is ~60 LOC and works; paho threading model conflicts with asyncio |
| Manual CONNACK parse | paho-mqtt auto-parse | Not worth adding a dependency for 3 lines of byte checking |

**Installation:**
```bash
# No new packages needed
```

## Architecture Patterns

### Recommended Project Structure
No new files. All changes are within existing modules:
```
src/venus_os_fronius_proxy/
  config.py          # Add VenusConfig dataclass + extend Config + validate_venus_config()
  venus_reader.py    # Parameterize venus_mqtt_loop(host, port, portal_id), add CONNACK parse, add discover_portal_id(), write shared_ctx["venus_mqtt_connected"]
  webapp.py          # De-hardcode 3 references, read host/portal from request.app["config"].venus
  __main__.py        # Pass config.venus to venus_mqtt_loop(), store task in shared_ctx["venus_task"]
  dashboard.py       # Include venus_mqtt_connected in snapshot
```

### Pattern 1: Config Dataclass Extension
**What:** Add `VenusConfig` following the exact pattern of `InverterConfig`
**When to use:** This is the only pattern for adding config sections in this codebase
**Example:**
```python
# Source: existing config.py pattern (InverterConfig)
@dataclass
class VenusConfig:
    host: str = ""           # Empty = not configured (proxy runs without MQTT)
    port: int = 1883         # MQTT standard port
    portal_id: str = ""      # Empty = auto-discover via N/+/system/0/Serial

@dataclass
class Config:
    inverter: InverterConfig = field(default_factory=InverterConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    webapp: WebappConfig = field(default_factory=WebappConfig)
    venus: VenusConfig = field(default_factory=VenusConfig)  # NEW
    log_level: str = "INFO"
```

`load_config()` must be extended with the same `data.get("venus", {})` pattern used for other sections.

### Pattern 2: Parameterized Background Task with Cancellation
**What:** Pass config values to `venus_mqtt_loop()` as parameters instead of module-level constants, store task reference in `shared_ctx` for cancellable restart
**When to use:** Any configurable background task that needs hot-reload
**Example:**
```python
# In __main__.py
async def venus_mqtt_loop(shared_ctx: dict, host: str, port: int, portal_id: str) -> None:
    ...

# Start conditionally
if config.venus.host:
    venus_task = asyncio.create_task(
        venus_mqtt_loop(shared_ctx, config.venus.host, config.venus.port, config.venus.portal_id)
    )
    shared_ctx["venus_task"] = venus_task  # For hot-reload cancellation
```

### Pattern 3: CONNACK Validation
**What:** Parse MQTT 3.1.1 CONNACK byte 4 (return code) before declaring connected
**When to use:** Every MQTT CONNECT in the codebase (venus_reader.py `_mqtt_connect` and webapp.py `_mqtt_write_venus`)
**Example:**
```python
# MQTT 3.1.1 spec: CONNACK is 4 bytes, byte[3] is return code
# 0x00 = accepted, 0x01-0x05 = various rejections
connack = s.recv(4)
if len(connack) < 4 or connack[3] != 0:
    raise ConnectionError(f"MQTT CONNACK rejected: rc={connack[3] if len(connack) >= 4 else 'short'}")
```

### Pattern 4: Portal ID Auto-Discovery
**What:** Subscribe to `N/+/system/0/Serial` wildcard, extract portal ID from first matching topic
**When to use:** When `config.venus.portal_id` is empty and `config.venus.host` is set
**Example:**
```python
async def discover_portal_id(host: str, port: int = 1883, timeout: float = 10.0) -> str | None:
    """Connect to Venus OS MQTT, subscribe to wildcard, extract portal ID from topic prefix."""
    # Connect + subscribe to N/+/system/0/Serial
    # First PUBLISH message will have topic N/{portal_id}/system/0/Serial
    # Extract portal_id = topic.split("/")[1]
    # Return portal_id or None on timeout
```

### Pattern 5: Connection State in shared_ctx
**What:** Write `shared_ctx["venus_mqtt_connected"]` as a bool from venus_mqtt_loop
**When to use:** Follows existing pattern -- all state flows through shared_ctx, never parallel channels
**Example:**
```python
# In venus_mqtt_loop, after successful CONNACK:
shared_ctx["venus_mqtt_connected"] = True

# On disconnect/error:
shared_ctx["venus_mqtt_connected"] = False
```

### Anti-Patterns to Avoid
- **New WebSocket message types for MQTT status:** Do NOT add `{"type": "mqtt_status"}` messages. Include `venus_mqtt_connected` in the existing dashboard snapshot. This follows the locked "extend snapshot, not protocol" decision.
- **Separate status polling loop:** Do NOT create a health-check loop for MQTT. The existing `venus_mqtt_loop` already runs continuously and should write status on connect/disconnect.
- **Partially de-hardcoding:** Do NOT update venus_reader.py without also updating webapp.py. All five references must be updated together to prevent config/runtime drift.
- **New Python modules:** Do NOT create `mqtt_config.py` or `venus_config.py`. All changes fit in existing modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Config persistence | Custom file writer | Existing `save_config()` with atomic write | Already handles tempfile + os.replace correctly |
| Config validation | Custom IP regex | `ipaddress.ip_address()` (already used in `validate_inverter_config`) | Edge cases (IPv6, leading zeros) handled by stdlib |
| MQTT protocol | Custom packet builder beyond existing | Existing `_mqtt_connect`, `_mqtt_subscribe`, `_mqtt_publish` in venus_reader.py | Already works; refactor signature, don't rewrite |
| YAML merging (for config migration) | Custom YAML merger | Dataclass defaults in `load_config()` | Missing `venus:` section in old config files simply uses VenusConfig defaults |

**Key insight:** The existing codebase already has every building block needed. This phase is pure parameter threading and connection hardening -- no new infrastructure.

## Common Pitfalls

### Pitfall 1: CONNACK Never Parsed (Silent False-Positive Connection)
**What goes wrong:** `s.recv(4)` at venus_reader.py:31 and webapp.py:637 reads the CONNACK but ignores the return code. A rejected MQTT connection appears successful.
**Why it happens:** Raw socket MQTT implementation skips protocol-level validation.
**How to avoid:** Parse byte[3] of CONNACK. If non-zero, raise `ConnectionError` with the return code. Do this in both `_mqtt_connect()` AND `_mqtt_write_venus()`.
**Warning signs:** MQTT shows "connected" in logs but `shared_ctx["venus_settings"]` never updates.

### Pitfall 2: Partial De-hardcoding Creates Config/Runtime Drift
**What goes wrong:** If venus_reader.py reads from config but webapp.py still has hardcoded IPs, MQTT reads go to one host while writes go to another.
**Why it happens:** Five hardcoded references across two files are easy to miss partially.
**How to avoid:** Enumerate all five locations before starting. Verify with `grep -rn "192.168.3.146\|88a29ec1e5f4" src/` after completion. Must return zero results.
**Warning signs:** Venus settings display correctly (reader works) but ESS setting writes fail silently (writer still hits old IP).

### Pitfall 3: venus_mqtt_loop Task Is Fire-and-Forget
**What goes wrong:** `venus_task` in `__main__.py` line 155 is a local variable. To implement config hot-reload later (save new Venus IP, restart MQTT), you need a task reference to cancel.
**Why it happens:** Original code never needed to restart the MQTT loop.
**How to avoid:** Store task in `shared_ctx["venus_task"]` immediately after creation. This phase MUST do this even though hot-reload UI is in Phase 14.
**Warning signs:** Two MQTT connections running simultaneously after a config change.

### Pitfall 4: Missing venus Section in Existing Config Files
**What goes wrong:** Existing users have config.yaml without a `venus:` section. If defaults are removed from code, the proxy crashes on startup.
**Why it happens:** Config schema evolution without migration.
**How to avoid:** Keep all defaults in `VenusConfig` dataclass (`host=""`, `port=1883`, `portal_id=""`). `load_config()` uses `data.get("venus", {})` which returns empty dict for missing section, and empty dict + dataclass defaults = working VenusConfig. Log a startup info message when venus section is missing: "venus config not found, MQTT features disabled".
**Warning signs:** Proxy fails to start after code update on existing installations.

### Pitfall 5: Blocking Socket in _mqtt_write_venus Blocks Event Loop
**What goes wrong:** `_mqtt_write_venus()` (webapp.py:625-655) is a synchronous function with `time.sleep(0.5)` called from an async handler. It blocks the aiohttp event loop for 500ms+ per write.
**Why it happens:** Pre-existing issue, but de-hardcoding this function is in scope so it should be noted.
**How to avoid:** This phase should NOT refactor the blocking behavior (scope creep). But when de-hardcoding, read `host` and `portal_id` from `request.app["config"].venus` and pass them through. The blocking issue is tracked as a known concern (PITFALLS.md Pitfall 9).
**Warning signs:** Dashboard freezes briefly during ESS setting changes.

### Pitfall 6: Portal ID Auto-Discovery Timeout
**What goes wrong:** `discover_portal_id()` subscribes to `N/+/system/0/Serial` but Venus OS MQTT broker might not publish immediately. If the function waits forever, it blocks startup.
**Why it happens:** Venus OS may not publish to wildcard subscriptions until the first R/ keep-alive is sent, or the broker may have a delayed response.
**How to avoid:** Set a hard timeout (10 seconds). If no message received, return `None` and log a warning. The proxy should still start and retry discovery on the next MQTT reconnect cycle.
**Warning signs:** Proxy startup hangs indefinitely when portal_id is empty.

## Code Examples

### VenusConfig Dataclass (config.py)
```python
# Source: follows existing InverterConfig pattern in config.py
@dataclass
class VenusConfig:
    host: str = ""
    port: int = 1883
    portal_id: str = ""
```

### load_config Extension (config.py)
```python
# Source: follows existing data.get() pattern in load_config()
venus=VenusConfig(**{
    k: v for k, v in data.get("venus", {}).items()
    if k in VenusConfig.__dataclass_fields__
}),
```

### validate_venus_config (config.py)
```python
def validate_venus_config(host: str, port: int) -> str | None:
    """Validate Venus OS MQTT connection parameters. Returns None on success."""
    if not host:
        return None  # Empty host = not configured, which is valid
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"Invalid IP address: {host}"
    if not (1 <= port <= 65535):
        return f"Port must be 1-65535, got {port}"
    return None
```

### CONNACK Parsing (venus_reader.py)
```python
# Source: MQTT 3.1.1 spec section 3.2
def _mqtt_connect(host: str, port: int = 1883, client_id: str = "pv-proxy-sub") -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((host, port))
    cid = client_id.encode()
    payload = struct.pack("!H", 4) + b"MQTT" + bytes([4, 2, 0, 60])
    payload += struct.pack("!H", len(cid)) + cid
    s.send(bytes([0x10, len(payload)]) + payload)
    connack = s.recv(4)
    if len(connack) < 4 or connack[3] != 0:
        s.close()
        raise ConnectionError(f"MQTT CONNACK rejected: rc={connack[3] if len(connack) >= 4 else 'short'}")
    return s
```

### Parameterized venus_mqtt_loop (venus_reader.py)
```python
async def venus_mqtt_loop(shared_ctx: dict, host: str, port: int, portal_id: str) -> None:
    """Background task: subscribe to Venus OS MQTT and update settings."""
    if not host:
        logger.info("venus_mqtt_disabled", reason="no host configured")
        return

    # If portal_id empty, discover it first
    if not portal_id:
        portal_id = await discover_portal_id(host, port)
        if not portal_id:
            logger.warning("portal_id_discovery_failed", host=host)
            # Retry on next reconnect cycle

    portal = portal_id
    prefix = f"N/{portal}"
    # ... rest of existing loop with host/port/portal as params
```

### Portal ID Discovery (venus_reader.py)
```python
async def discover_portal_id(host: str, port: int = 1883, timeout: float = 10.0) -> str | None:
    """Auto-discover Venus OS portal ID via MQTT wildcard subscription."""
    loop = asyncio.get_event_loop()
    try:
        def _discover_blocking():
            s = _mqtt_connect(host, port, client_id="pv-proxy-discover")
            _mqtt_subscribe(s, ["N/+/system/0/Serial"])
            s.settimeout(timeout)
            try:
                data = s.recv(8192)
                for topic, payload in _parse_mqtt_messages(data):
                    if "/system/0/Serial" in topic:
                        parts = topic.split("/")
                        if len(parts) >= 2:
                            portal_id = parts[1]
                            logger.info("portal_id_discovered", portal_id=portal_id)
                            return portal_id
            except socket.timeout:
                pass
            finally:
                try:
                    s.close()
                except Exception:
                    pass
            return None

        return await asyncio.wait_for(
            loop.run_in_executor(None, _discover_blocking),
            timeout=timeout + 2
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("portal_id_discovery_error", error=str(e))
        return None
```

### De-hardcoded webapp.py (venus_write_handler)
```python
# Source: existing venus_write_handler at webapp.py:572
async def venus_write_handler(request: web.Request) -> web.Response:
    # ...
    venus_cfg = request.app["config"].venus
    if not venus_cfg.host:
        return web.json_response(
            {"success": False, "error": "Venus OS not configured"}, status=503,
        )
    client = AsyncModbusTcpClient(venus_cfg.host, port=502)
    # ... rest unchanged
```

### De-hardcoded webapp.py (venus_dbus_handler)
```python
# Source: existing venus_dbus_handler at webapp.py:658
async def venus_dbus_handler(request: web.Request) -> web.Response:
    # ...
    venus_cfg = request.app["config"].venus
    if not venus_cfg.host or not venus_cfg.portal_id:
        return web.json_response(
            {"success": False, "error": "Venus OS MQTT not configured"}, status=503,
        )
    ok = _mqtt_write_venus(venus_cfg.host, venus_cfg.portal_id, path, value)
    # ...
```

### __main__.py Conditional Start
```python
# Start Venus MQTT reader only if host is configured
venus_task = None
if config.venus.host:
    from venus_os_fronius_proxy.venus_reader import venus_mqtt_loop
    venus_task = asyncio.create_task(
        venus_mqtt_loop(shared_ctx, config.venus.host, config.venus.port, config.venus.portal_id)
    )
    shared_ctx["venus_task"] = venus_task
else:
    logger.info("venus_mqtt_skipped", reason="no venus.host in config")
    shared_ctx["venus_mqtt_connected"] = False
```

### Dashboard Snapshot Extension (dashboard.py)
```python
# In collect(), add venus_mqtt_connected to snapshot
snapshot = {
    "ts": time.time(),
    "inverter": inverter,
    # ... existing fields ...
    "venus_mqtt_connected": shared_ctx.get("venus_mqtt_connected", False) if shared_ctx else False,
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level constants for MQTT host/portal | Config dataclass + parameter injection | This phase | All MQTT consumers read from config |
| Ignore CONNACK return code | Parse byte[3], raise on non-zero | This phase | False-positive connections detected |
| Manual portal ID entry | Auto-discover via N/+/system/0/Serial wildcard | This phase | Users only need to know Venus OS IP |
| Fire-and-forget venus_task | Task stored in shared_ctx for cancellation | This phase | Enables hot-reload in Phase 14 |
| Hardcoded "active" in status_handler | Real venus_mqtt_connected from shared_ctx | This phase | Accurate connection status for Phase 14 UI |

## Open Questions

1. **R/ keep-alive needed during discovery?**
   - What we know: Venus OS MQTT broker requires `R/{portalId}/...` keep-alive every 60s to continue publishing. During discovery, we subscribe to `N/+/...` wildcard.
   - What's unclear: Whether the broker responds to wildcard subscriptions without an R/ keep-alive.
   - Recommendation: Try without R/ keep-alive first (since we don't know the portal ID yet). If discovery fails, add an `R/+/system/0/Serial` publish as fallback. The 10-second timeout handles the failure case.

2. **Should `_mqtt_write_venus` also use the configured port?**
   - What we know: Current code connects to port 1883 for MQTT writes. VenusConfig has a `port` field.
   - What's unclear: Whether any Venus OS installation uses a non-standard MQTT port.
   - Recommendation: Yes, thread `config.venus.port` through to `_mqtt_write_venus`. Consistency matters even if 1883 is standard.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.23+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `cd "/Users/hulki/codex/venus os fronius proxy" && python -m pytest tests/ -x -q` |
| Full suite command | `cd "/Users/hulki/codex/venus os fronius proxy" && python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CFG-03a | VenusConfig dataclass with defaults | unit | `python -m pytest tests/test_config.py -x -k venus` | Extend existing |
| CFG-03b | load_config parses venus section | unit | `python -m pytest tests/test_config.py -x -k venus` | Extend existing |
| CFG-03c | save_config roundtrip with venus | unit | `python -m pytest tests/test_config_save.py -x -k venus` | Extend existing |
| CFG-03d | validate_venus_config accepts valid / rejects invalid | unit | `python -m pytest tests/test_config_save.py -x -k validate_venus` | Extend existing |
| CFG-03e | venus_mqtt_loop accepts host/port/portal params | unit | `python -m pytest tests/test_venus_reader.py -x` | Wave 0 |
| CFG-03f | All hardcoded IPs eliminated | unit (grep guard) | `python -m pytest tests/test_venus_reader.py -x -k hardcoded` | Wave 0 |
| CFG-03g | CONNACK rejection raises ConnectionError | unit | `python -m pytest tests/test_venus_reader.py -x -k connack` | Wave 0 |
| CFG-03h | shared_ctx["venus_mqtt_connected"] set on connect/disconnect | unit | `python -m pytest tests/test_venus_reader.py -x -k connected` | Wave 0 |
| CFG-03i | webapp reads venus host from config (not hardcoded) | unit | `python -m pytest tests/test_webapp.py -x -k venus` | Extend existing |
| CFG-03j | Dashboard snapshot includes venus_mqtt_connected | unit | `python -m pytest tests/test_dashboard.py -x -k venus` | Extend existing |
| CFG-04a | discover_portal_id extracts ID from topic | unit | `python -m pytest tests/test_venus_reader.py -x -k discover` | Wave 0 |
| CFG-04b | discover_portal_id returns None on timeout | unit | `python -m pytest tests/test_venus_reader.py -x -k discover_timeout` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_venus_reader.py` -- covers CFG-03e, CFG-03f, CFG-03g, CFG-03h, CFG-04a, CFG-04b (new file, currently no venus_reader tests exist)
- [ ] Extend `tests/test_config.py` -- covers CFG-03a, CFG-03b (add VenusConfig tests to existing file)
- [ ] Extend `tests/test_config_save.py` -- covers CFG-03c, CFG-03d (add venus roundtrip + validation tests)
- [ ] Extend `tests/test_webapp.py` -- covers CFG-03i (add venus config reading tests)
- [ ] Extend `tests/test_dashboard.py` -- covers CFG-03j (add venus_mqtt_connected in snapshot test)

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `config.py`, `venus_reader.py`, `webapp.py`, `__main__.py`, `dashboard.py` -- all hardcoded references identified at exact line numbers
- MQTT 3.1.1 specification -- CONNACK return code at byte[3], values 0x00-0x05
- [victronenergy/venus-html5-app TOPICS.md](https://github.com/victronenergy/venus-html5-app/blob/master/TOPICS.md) -- `N/+/system/0/Serial` wildcard for portal ID discovery
- [victronenergy/dbus-mqtt](https://github.com/victronenergy/dbus-mqtt) -- R/ keep-alive every 60s requirement

### Secondary (MEDIUM confidence)
- [Victron Community: MQTT local](https://community.victronenergy.com/questions/155407/mqtt-local-via-mqtt-broker.html) -- Portal ID wildcard pattern confirmed by community

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero new dependencies, all building blocks exist in codebase
- Architecture: HIGH -- based on direct code analysis with exact line references for all five hardcoded locations
- Pitfalls: HIGH -- all pitfalls observed in current codebase or documented in MQTT 3.1.1 spec
- Auto-discovery: HIGH -- Victron officially documents N/+/system/0/Serial wildcard pattern

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable domain, no fast-moving dependencies)
