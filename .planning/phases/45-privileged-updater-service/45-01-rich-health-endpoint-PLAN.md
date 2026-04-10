---
phase: 45-privileged-updater-service
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/webapp.py
  - src/pv_inverter_proxy/context.py
  - src/pv_inverter_proxy/__main__.py
  - tests/test_health_endpoint.py
autonomous: false
requirements:
  - HEALTH-01
  - HEALTH-02
  - HEALTH-03
  - HEALTH-04
must_haves:
  truths:
    - "GET /api/health returns JSON with status, version, commit, uptime_seconds, webapp, modbus_server, devices, venus_os fields"
    - "Each component reports ok | starting | degraded | failed consistently"
    - "Required-for-success is: webapp=ok AND modbus_server=ok AND at least one device=ok"
    - "venus_os status is warn-only: degraded venus_os does not flip overall status to degraded"
    - "/run/pv-inverter-proxy/healthy flag is written exactly once after the first device produces a successful poll (already wired in __main__; preserved)"
    - "During the first 30s of uptime, overall status is 'starting' instead of 'degraded' (avoids startup false-negatives the updater would misread)"
    - "Health endpoint is hot-path safe: zero blocking IO, no subprocess, no file reads (reads app_ctx only)"
  artifacts:
    - path: "src/pv_inverter_proxy/webapp.py"
      provides: "health_handler rewritten with component aggregation + startup grace"
      contains: "def health_handler"
    - path: "tests/test_health_endpoint.py"
      provides: "Unit tests for health_handler component aggregation and status derivation"
      contains: "test_health"
  key_links:
    - from: "src/pv_inverter_proxy/webapp.py::health_handler"
      to: "app_ctx.devices / app_ctx.cache / app_ctx.venus_mqtt_connected"
      via: "direct attribute reads"
      pattern: "app_ctx\\.(devices|cache|venus_mqtt_connected|current_version|current_commit)"
    - from: "src/pv_inverter_proxy/__main__.py::_healthy_flag_watcher"
      to: "/run/pv-inverter-proxy/healthy"
      via: "Path.touch()"
      pattern: "HEALTHY_FLAG_PATH"
---

<objective>
Rewrite `/api/health` to return the rich per-component schema required by HEALTH-01..04. This is the first building block of Phase 45: the updater root helper (Plan 45-04) polls this endpoint after restart to decide success/rollback, and the schema must exist on the OLD code before the new code ships (so rollback to the pre-Phase-45 version would also return the same fields — which it already does from Phase 44 for `version`+`commit`).

Purpose: Give the updater an authoritative post-restart signal. Without a rich health endpoint the updater cannot distinguish "webapp responds but Modbus is dead" from "fully healthy", which is the difference between a silent bad update and an auto-rollback.

Output: Extended `health_handler` in `webapp.py`, optional `ComponentStatus` helper, three unit tests proving status derivation, and an LXC deploy smoke check confirming the endpoint returns the new schema.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@src/pv_inverter_proxy/webapp.py
@src/pv_inverter_proxy/context.py
@src/pv_inverter_proxy/__main__.py

<interfaces>
<!-- Key state the new health_handler reads -->
<!-- Extracted from src/pv_inverter_proxy/context.py -->

From src/pv_inverter_proxy/context.py:
```python
@dataclass
class DeviceState:
    collector: object = None
    poll_counter: dict = field(default_factory=lambda: {"success": 0, "total": 0})
    conn_mgr: object = None
    last_poll_data: dict | None = None
    plugin: object = None

@dataclass
class AppContext:
    cache: object = None            # RegisterCache, has .is_stale, .last_successful_poll
    devices: dict[str, DeviceState] = field(default_factory=dict)
    venus_mqtt_connected: bool = False
    healthy_flag_written: bool = False
    current_version: str | None = None
    current_commit: str | None = None
    # (other fields unused by health_handler)
```

From src/pv_inverter_proxy/webapp.py (existing handler - to be rewritten):
```python
async def health_handler(request: web.Request) -> web.Response:
    """Return uptime, poll success rate, and cache staleness."""
    app_ctx = request.app["app_ctx"]
    # returns {uptime_seconds, poll_success_rate, poll_total, poll_success,
    #         cache_stale, last_poll_age, device_count}
```

From src/pv_inverter_proxy/__main__.py (already in place, do NOT re-implement):
```python
HEALTHY_FLAG_PATH = Path("/run/pv-inverter-proxy/healthy")

def _write_healthy_flag_once(app_ctx, logger) -> None:
    # Writes /run/pv-inverter-proxy/healthy once the first device poll succeeds.
    # Phase 43 already shipped this; Plan 45-01 MUST NOT duplicate or refactor it.
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite health_handler with component aggregation + startup grace</name>
  <files>src/pv_inverter_proxy/webapp.py, src/pv_inverter_proxy/context.py</files>
  <behavior>
    Schema (HEALTH-01):
    - Response is a dict with exactly these top-level keys:
      {status, version, commit, uptime_seconds, webapp, modbus_server, devices, venus_os}
    - status ∈ {"ok", "starting", "degraded"}
    - webapp, modbus_server, venus_os ∈ {"ok", "starting", "degraded", "failed", "disabled"}
    - devices is an object {device_id: "ok" | "starting" | "degraded" | "failed"}
    - version is app_ctx.current_version or "unknown"; commit is app_ctx.current_commit or "unknown"
    - uptime_seconds is round(time.monotonic() - app["start_time"], 1)

    Component derivation (HEALTH-02, HEALTH-03):
    - webapp: always "ok" inside the handler (if the handler is running, the webapp is up)
    - modbus_server: "ok" if app_ctx.cache is not None AND cache is not stale
        - if cache is None -> "failed"
        - if cache.is_stale -> "degraded" (startup-grace will remap to "starting" if uptime < 30s)
    - devices: {device_id: "ok" if ds.poll_counter["success"] > 0 else "starting"}
        - if there are zero devices, devices == {} and it is counted as "no device ok"
    - venus_os: "ok" if app_ctx.venus_mqtt_connected is True
              else "disabled" if config.venus.host is empty
              else "degraded" (never "failed" — HEALTH-03 warn-only)

    Overall status derivation:
    - Required-for-success (HEALTH-02): webapp=="ok" AND modbus_server=="ok" AND >=1 device=="ok"
    - Startup grace (H5-inspired, 30s): if uptime_seconds < 30 AND required-for-success is False,
      overall status = "starting" (not "degraded"). Also remap modbus_server and devices values
      from "degraded"/"starting" to "starting" in this window so the updater doesn't see a
      flickering degraded during startup.
    - After 30s: if required-for-success is True, overall status = "ok".
    - After 30s: if NOT required-for-success, overall status = "degraded".
    - venus_os degraded NEVER flips overall status to degraded (HEALTH-03).

    Test cases (hermetic, use a stub AppContext + app dict):
    - test_health_all_ok: cache.is_stale=False, one device with success>0, venus connected -> status=ok
    - test_health_starting_grace: uptime=5s, no poll yet -> status=starting, modbus_server=starting, devices={d1:starting}
    - test_health_degraded_after_grace: uptime=60s, cache.is_stale=True -> status=degraded, modbus_server=degraded
    - test_health_venus_warn_only: all required ok, venus_mqtt_connected=False, venus.host set -> status=ok, venus_os=degraded
    - test_health_venus_disabled: venus.host="" -> venus_os=disabled
    - test_health_no_devices: uptime=60s, devices={} -> status=degraded (no device produced an ok)
    - test_health_version_commit_unknown: current_version=None -> version="unknown"
    - test_health_no_subprocess_no_fs: mock subprocess.run and Path to raise; handler still returns 200
  </behavior>
  <action>
    Step 1: Add a small private helper at module scope in webapp.py:

    ```python
    _HEALTH_STARTUP_GRACE_S = 30.0

    def _derive_health_payload(app_ctx, uptime_s: float, config) -> dict:
        # Pure function, no IO, fully testable.
        # Build components first, then derive overall status.
        webapp_s = "ok"

        cache = app_ctx.cache
        if cache is None:
            modbus_s = "failed"
        elif cache.is_stale:
            modbus_s = "degraded"
        else:
            modbus_s = "ok"

        devices_s: dict[str, str] = {}
        for dev_id, ds in app_ctx.devices.items():
            if ds.poll_counter.get("success", 0) > 0:
                devices_s[dev_id] = "ok"
            else:
                devices_s[dev_id] = "starting"

        if getattr(config.venus, "host", "") == "":
            venus_s = "disabled"
        elif app_ctx.venus_mqtt_connected:
            venus_s = "ok"
        else:
            venus_s = "degraded"  # warn-only per HEALTH-03

        required_ok = (
            webapp_s == "ok"
            and modbus_s == "ok"
            and any(s == "ok" for s in devices_s.values())
        )

        in_grace = uptime_s < _HEALTH_STARTUP_GRACE_S

        if required_ok:
            overall = "ok"
        elif in_grace:
            overall = "starting"
            if modbus_s in ("degraded", "failed"):
                modbus_s = "starting"
            devices_s = {k: ("ok" if v == "ok" else "starting") for k, v in devices_s.items()}
        else:
            overall = "degraded"

        return {
            "status": overall,
            "version": app_ctx.current_version or "unknown",
            "commit": app_ctx.current_commit or "unknown",
            "uptime_seconds": round(uptime_s, 1),
            "webapp": webapp_s,
            "modbus_server": modbus_s,
            "devices": devices_s,
            "venus_os": venus_s,
        }
    ```

    Step 2: Rewrite `health_handler` to call the helper:

    ```python
    async def health_handler(request: web.Request) -> web.Response:
        app_ctx = request.app["app_ctx"]
        config = request.app["config"]
        uptime = time.monotonic() - request.app["start_time"]
        payload = _derive_health_payload(app_ctx, uptime, config)
        return web.json_response(payload)
    ```

    Step 3: Create `tests/test_health_endpoint.py` with the behavior cases above using a
    minimal stub AppContext and a stub config namespace (`SimpleNamespace(venus=SimpleNamespace(host=...))`).
    Call `_derive_health_payload` directly (unit test) — no aiohttp needed for these cases.
    One additional test (`test_health_handler_integration`) instantiates a tiny aiohttp
    Application, sets `app["start_time"]`, `app["config"]`, `app["app_ctx"]`, and asserts
    `await health_handler(web.Request...)` returns a 200 JSON with status=="starting".

    Step 4: NO changes to `_healthy_flag_watcher` in __main__.py — Phase 43 already wrote
    that correctly. Do not duplicate. Verify via grep that HEALTH-04 is still met:
    `grep -n "_write_healthy_flag_once" src/pv_inverter_proxy/__main__.py` must return hits.

    Step 5: Add docstring to `health_handler` referencing HEALTH-01..04.

    Do NOT touch context.py in this plan UNLESS a field is genuinely missing. All fields
    needed (current_version, current_commit, venus_mqtt_connected, healthy_flag_written,
    cache, devices) already exist (verified in context.py line 13-76).
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_health_endpoint.py -x -v</automated>
  </verify>
  <done>
    - tests/test_health_endpoint.py passes all 8 cases
    - health_handler uses _derive_health_payload (no legacy fields in response)
    - grep "def health_handler" webapp.py shows the new docstring citing HEALTH-01..04
    - context.py unchanged (verified via git diff)
    - No new subprocess calls, no new file reads inside the handler hot path
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: LXC deploy smoke test — verify rich /api/health schema on live service</name>
  <what-built>
    - `GET /api/health` now returns the rich schema with all 8 required fields
    - Overall status reflects component aggregation
    - Startup grace prevents "degraded" in the first 30s
  </what-built>
  <how-to-verify>
    1. Deploy to LXC: `./deploy.sh` (or the standard auto-deploy to 192.168.3.191)
    2. Wait for restart to complete: `ssh root@192.168.3.191 'systemctl is-active pv-inverter-proxy'` returns "active"
    3. Fetch health endpoint: `curl -s http://192.168.3.191/api/health | python3 -m json.tool`
    4. Expected output (exact key set, values may differ):
       ```json
       {
         "status": "ok",
         "version": "8.0.0",
         "commit": "<some 7-char hex>",
         "uptime_seconds": 45.3,
         "webapp": "ok",
         "modbus_server": "ok",
         "devices": {"se30k": "ok"},
         "venus_os": "ok"
       }
       ```
    5. Immediately after a systemctl restart, within 5 seconds, curl again. Expected: `status=="starting"`, `modbus_server=="starting"`, `devices` values all "starting".
    6. Confirm `/run/pv-inverter-proxy/healthy` exists (Phase 43 behavior preserved):
       `ssh root@192.168.3.191 'ls -la /run/pv-inverter-proxy/healthy'`
    7. No crashes in journal: `ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy -n 50 | grep -i "traceback\|error" || echo OK'`
  </how-to-verify>
  <resume-signal>Type "approved" if schema matches and startup grace works, or describe discrepancies.</resume-signal>
  <files>(no files — human verification only)</files>
  <action>See &lt;how-to-verify&gt; — checkpoint tasks are human-driven.</action>
  <verify>
    <automated>echo "checkpoint — human verifies per how-to-verify block"</automated>
  </verify>
  <done>User types the resume-signal value.</done>

</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| LAN client → webapp (`/api/health`) | Unauthenticated LAN clients can read health status |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-45-01-01 | Information disclosure | health_handler response | accept | Health response already exposed less-sensitive data (version, commit, poll counts) in Phase 44. New fields (device IDs, component status) are LAN-only info with no secrets. No PII. Project decision: LAN is trusted (PROJECT.md). |
| T-45-01-02 | Denial of service | health_handler hot path | mitigate | Handler is pure in-memory reads, no subprocess, no file IO, no DB. O(devices) aggregation is trivial. A flood of /api/health requests cannot starve the event loop. |
| T-45-01-03 | Tampering | Component status derivation | mitigate | `_derive_health_payload` is a pure function; unit tests cover all derivation paths. No external input influences the derivation — only AppContext state. |
| T-45-01-04 | Spoofing | Version/commit fields | accept | current_version/current_commit are resolved once at startup from importlib.metadata + git rev-parse. An attacker with code-exec already owns the process; spoofing these fields is the least of the problems. |
| T-45-01-05 | Repudiation | Updater trust in /api/health | mitigate | Plan 45-04's healthcheck reads *this* version field and asserts version == target_sha expectation. Phase 45-01 ensures the field is always present, so a missing version is not a silent "assume ok". |
</threat_model>

<verification>
## Validation Strategy

| REQ | Test Type | Evidence |
|-----|-----------|----------|
| HEALTH-01 | Unit (test_health_endpoint.py) + LXC smoke (Task 2) | Response has all 8 required keys; live curl shows schema |
| HEALTH-02 | Unit (test_health_all_ok, test_health_no_devices) | Required-for-success derivation |
| HEALTH-03 | Unit (test_health_venus_warn_only) | venus degraded does NOT flip overall status |
| HEALTH-04 | Grep-verify (existing Phase 43 code unchanged) | `_write_healthy_flag_once` in __main__.py still fires on first success |

## Failure Rollback

If Task 2 fails (wrong schema or crashes in journal):
1. `git revert HEAD` — Plan 45-01 is self-contained, rollback is a single commit revert
2. Redeploy previous version
3. Debug offline before re-attempting
</verification>

<success_criteria>
- tests/test_health_endpoint.py passes all cases
- LXC /api/health returns the exact 8-field schema
- Overall status derivation matches HEALTH-02/03 rules (verified both in unit tests and live curl)
- /run/pv-inverter-proxy/healthy still created on first successful poll (HEALTH-04, Phase 43 behavior preserved)
- Plans 45-02..45-05 can assume `/api/health` exists in the rich form
- Phase 44 /api/update/available endpoint unchanged and still works
</success_criteria>

<output>
After completion, create `.planning/phases/45-privileged-updater-service/45-01-SUMMARY.md` capturing:
- Final health schema (copy-paste from a live curl)
- Test file path + count of tests passing
- Any deviations from the startup-grace semantics above
- Confirmation that HEALTH-04 Phase 43 code was left untouched
</output>
