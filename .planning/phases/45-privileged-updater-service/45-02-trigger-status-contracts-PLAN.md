---
phase: 45-privileged-updater-service
plan: 02
type: execute
wave: 2
depends_on:
  - "45-01"
files_modified:
  - src/pv_inverter_proxy/updater/trigger.py
  - src/pv_inverter_proxy/updater/status.py
  - src/pv_inverter_proxy/webapp.py
  - install.sh
  - tests/test_updater_trigger.py
  - tests/test_updater_status.py
autonomous: false
requirements:
  - EXEC-01
  - EXEC-02
  - SEC-07
must_haves:
  truths:
    - "POST /api/update/start writes a valid trigger JSON atomically and returns HTTP 202 in under 100ms"
    - "Trigger JSON schema is exactly {op, target_sha, requested_at, requested_by, nonce} — extra fields rejected at the CONSUMER side (Plan 45-03), producer writes only these"
    - "Trigger file is written via tempfile + os.replace, so a concurrent reader never sees a half-written file"
    - "update-trigger.json has mode 0664 and owner root:pv-proxy (writable by main service, readable by root helper)"
    - "update-status.json is readable by main service via updater/status.py without race or partial-read errors (defensive load)"
    - "Empty status file (status has not been created yet by updater) is reported as phase=None, not an error"
  artifacts:
    - path: "src/pv_inverter_proxy/updater/trigger.py"
      provides: "write_trigger() atomic write, generate_nonce(), TriggerPayload schema"
      contains: "def write_trigger"
    - path: "src/pv_inverter_proxy/updater/status.py"
      provides: "load_status() defensive read, UpdateStatus dataclass"
      contains: "def load_status"
    - path: "src/pv_inverter_proxy/webapp.py"
      provides: "POST /api/update/start handler + route registration"
      contains: "update_start_handler"
    - path: "install.sh"
      provides: "Per-file permissions for trigger (0664 root:pv-proxy) and status (0644 root:root)"
      contains: "update-trigger.json"
    - path: "tests/test_updater_trigger.py"
      provides: "Schema, atomicity, concurrent-write, permission tests"
    - path: "tests/test_updater_status.py"
      provides: "Defensive load tests (missing, corrupt, partial, wrong schema)"
  key_links:
    - from: "src/pv_inverter_proxy/webapp.py::update_start_handler"
      to: "src/pv_inverter_proxy/updater/trigger.py::write_trigger"
      via: "direct function call"
      pattern: "write_trigger\\("
    - from: "install.sh"
      to: "/etc/pv-inverter-proxy/update-trigger.json"
      via: "install -o root -g pv-proxy -m 0664"
      pattern: "update-trigger\\.json"
---

<objective>
Ship the main-service-side plumbing for the update trigger protocol: an atomic trigger writer, a defensive status reader, the `POST /api/update/start` REST route, and install.sh per-file permission setup. After this plan, a `curl -X POST http://lxc/api/update/start` returns HTTP 202, the trigger file is on disk, and root can read it. NO consumer yet — the root helper comes in Plan 45-03/04.

Purpose: Establish the wire protocol before building the root helper. The schema, permissions, and atomic write pattern are the contract; Plan 45-03's trigger_reader will validate against this contract, and bugs in the contract here would cascade.

Output: `updater/trigger.py` (new), `updater/status.py` (new), `update_start_handler` route, install.sh file-level permissions block, unit tests, LXC smoke test posting a trigger and observing the file on disk with correct ownership.
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
@.planning/phases/43-blue-green-layout-boot-recovery/43-01-SUMMARY.md
@src/pv_inverter_proxy/state_file.py
@src/pv_inverter_proxy/webapp.py
@install.sh

<interfaces>
<!-- Existing atomic-write pattern from Phase 43 — Plan 45-02 reuses the same approach -->

From src/pv_inverter_proxy/state_file.py (reference pattern, DO NOT import):
```python
def save_state(state: PersistedState, path: Path | None = None) -> None:
    """Atomic write via tempfile + os.replace, chmod 0o644 on success."""
    target = path or STATE_FILE_PATH
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(asdict(state), indent=2, sort_keys=True)
    tmp.write_text(payload)
    os.replace(tmp, target)
    os.chmod(target, 0o644)
```

From .planning/research/ARCHITECTURE.md:
- Trigger file: `/etc/pv-inverter-proxy/update-trigger.json`
- Status file: `/etc/pv-inverter-proxy/update-status.json`
- Trigger schema v1: `{op, target_sha, requested_at, requested_by, nonce}`
- Trigger permissions (SEC-07): mode 0664, owner root:pv-proxy
- Status permissions (SEC-07): mode 0644, owner root:root
- Phase-based status schema (from research/ARCHITECTURE.md lines 329-348):
```json
{
  "current": {"nonce": "...", "phase": "...", "target_sha": "...",
              "old_sha": "...", "started_at": "..."},
  "history": [{"phase": "...", "at": "..."}, ...]
}
```

From src/pv_inverter_proxy/webapp.py (route registration pattern, line ~2087):
```python
app.router.add_get("/api/health", health_handler)
app.router.add_get("/api/update/available", update_available_handler)
# Plan 45-02 adds:
# app.router.add_post("/api/update/start", update_start_handler)
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: updater/trigger.py — atomic write + schema + nonce generation</name>
  <files>src/pv_inverter_proxy/updater/trigger.py, tests/test_updater_trigger.py</files>
  <behavior>
    Schema (EXEC-02):
    - TriggerPayload dataclass with exactly: op, target_sha, requested_at, requested_by, nonce
    - op ∈ {"update", "rollback"}
    - target_sha: 40-char lowercase hex string for "update"; for "rollback" may be the string "previous" (short-circuit)
    - requested_at: ISO-8601 UTC string ending with "Z" (e.g. "2026-04-10T14:22:00Z")
    - requested_by: short string (e.g. "webapp", "cli", "self-test")
    - nonce: UUID4 string

    Functions:
    - `generate_nonce() -> str`: returns str(uuid.uuid4())
    - `now_iso_utc() -> str`: returns datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    - `write_trigger(payload: TriggerPayload, path: Path | None = None) -> None`:
        * Serializes payload via asdict + json.dumps(indent=2, sort_keys=True)
        * Writes to `target.with_suffix(".json.tmp")` first
        * Calls os.replace(tmp, target) — atomic on POSIX
        * Calls os.chmod(target, 0o664)
        * Raises OSError on write failure (same error-handling contract as state_file.save_state)
        * Never silently swallows errors

    Validation (producer-side, light):
    - `TriggerPayload.validate() -> None`: raises ValueError on:
        * op not in {"update", "rollback"}
        * op=="update" and target_sha does not match `^[0-9a-f]{40}$` (full SHA required)
        * op=="rollback" and target_sha not in {"previous", or a 40-char hex}
        * nonce empty
        * requested_at not ending with "Z"
    - Producer validates before writing; consumer (Plan 45-03) re-validates with stricter rules.

    Test cases (hermetic, use tmp_path fixture):
    - test_write_trigger_atomic_replace: write to tmp dir, assert file exists, assert JSON round-trips exactly
    - test_write_trigger_correct_schema_keys: asserts sorted keys == ["nonce", "op", "requested_at", "requested_by", "target_sha"]
    - test_write_trigger_mode_0664: os.stat(trigger).st_mode & 0o777 == 0o664
    - test_write_trigger_no_tmp_leftover: after successful write, `.json.tmp` does not exist
    - test_write_trigger_tmp_cleanup_on_failure: monkeypatch os.replace to raise OSError, assert tmp is not leaked
      (NOTE: state_file.save_state has an explicit tmp.unlink best-effort cleanup — replicate)
    - test_validate_rejects_short_sha: target_sha="abc123" -> ValueError
    - test_validate_rejects_bad_op: op="delete" -> ValueError
    - test_validate_accepts_rollback_previous: op="rollback", target_sha="previous" -> no raise
    - test_generate_nonce_uuid4_shape: len == 36, 4 dashes
    - test_write_trigger_under_concurrent_readers: write trigger N=20 times back-to-back in a threadpool;
      in a separate thread continuously `read_text()` the target; assert every read either raises
      FileNotFoundError OR parses as valid JSON — never a ValueError (proves os.replace atomicity
      from the reader's perspective).
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/trigger.py`:

    ```python
    """Atomic trigger file writer for the v8.0 update protocol (EXEC-01, EXEC-02, SEC-07).

    The main service (pv-proxy user) writes a trigger file atomically and the
    root updater (Plan 45-03) watches for PathModified. The schema is v1; any
    additive evolution MUST bump a schema_version field in a future release.

    Atomicity pattern mirrors state_file.save_state: tempfile in same directory
    + os.replace + explicit 0o664 chmod. No fsync — the write is not
    crash-durability critical (a crash before os.replace means no trigger
    was issued, which is the correct failure mode).
    """
    from __future__ import annotations

    import json
    import os
    import re
    import uuid
    from dataclasses import asdict, dataclass
    from datetime import datetime, timezone
    from pathlib import Path

    import structlog

    log = structlog.get_logger(component="updater.trigger")

    TRIGGER_FILE_PATH: Path = Path("/etc/pv-inverter-proxy/update-trigger.json")
    TRIGGER_FILE_MODE: int = 0o664

    _SHA_RE = re.compile(r"^[0-9a-f]{40}$")
    _VALID_OPS = {"update", "rollback"}


    @dataclass
    class TriggerPayload:
        op: str
        target_sha: str
        requested_at: str
        requested_by: str
        nonce: str

        def validate(self) -> None:
            if self.op not in _VALID_OPS:
                raise ValueError(f"invalid op: {self.op!r}")
            if self.op == "update":
                if not _SHA_RE.match(self.target_sha):
                    raise ValueError(
                        f"update requires full 40-char hex SHA, got {self.target_sha!r}"
                    )
            else:  # rollback
                if self.target_sha != "previous" and not _SHA_RE.match(self.target_sha):
                    raise ValueError(
                        f"rollback target_sha must be 'previous' or full SHA, got {self.target_sha!r}"
                    )
            if not self.nonce:
                raise ValueError("nonce must not be empty")
            if not self.requested_at.endswith("Z"):
                raise ValueError(f"requested_at must end with Z, got {self.requested_at!r}")
            if not self.requested_by:
                raise ValueError("requested_by must not be empty")


    def generate_nonce() -> str:
        return str(uuid.uuid4())


    def now_iso_utc() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


    def write_trigger(
        payload: TriggerPayload,
        path: Path | None = None,
    ) -> None:
        """Atomically write a trigger file. Raises ValueError / OSError on failure."""
        payload.validate()
        target = path or TRIGGER_FILE_PATH
        tmp = target.with_suffix(".json.tmp")
        blob = json.dumps(asdict(payload), indent=2, sort_keys=True)
        try:
            tmp.write_text(blob)
            os.replace(tmp, target)
            os.chmod(target, TRIGGER_FILE_MODE)
        except OSError as e:
            log.error("trigger_write_failed", path=str(target), error=str(e))
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
    ```

    Create tests/test_updater_trigger.py implementing all behavior cases.
    Use pytest tmp_path fixture for isolation — do NOT touch /etc/pv-inverter-proxy/.

    For the concurrent-reader test use `threading.Thread` (NOT asyncio) so the test
    is deterministic. 100 iterations is enough.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_trigger.py -x -v</automated>
  </verify>
  <done>
    - trigger.py exists with the exact API above
    - All test cases pass
    - No writes to /etc/pv-inverter-proxy during tests (all hermetic in tmp_path)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: updater/status.py — defensive status file reader</name>
  <files>src/pv_inverter_proxy/updater/status.py, tests/test_updater_status.py</files>
  <behavior>
    Schema (HEALTH-09, matches ARCHITECTURE.md lines 329-348):
    - UpdateStatus dataclass with:
        current: dict | None  (contains {nonce, phase, target_sha, old_sha, started_at})
        history: list[dict]   (each entry {phase, at, error?})
        schema_version: int = 1
    - Phase enum (as str constants, not Python Enum): "idle", "trigger_received", "backup",
      "extract", "pip_install", "config_dryrun", "restarting", "healthcheck", "done",
      "rollback", "rollback_failed"

    Functions:
    - `load_status(path: Path | None = None) -> UpdateStatus`:
        * Returns UpdateStatus(current=None, history=[], schema_version=1) on:
            - missing file
            - OSError on read
            - json.JSONDecodeError (corrupt)
            - top-level not dict
            - schema_version != 1
        * Never raises
        * Logs warning on unexpected shapes
    - `current_phase(status: UpdateStatus) -> str`:
        * Returns "idle" if status.current is None
        * Otherwise status.current.get("phase", "idle")

    Test cases (hermetic):
    - test_load_missing_file: load(nonexistent) -> idle, empty history
    - test_load_empty_file: tmp file with "" -> idle (JSONDecodeError swallowed)
    - test_load_partial_write: tmp file with "{\"curre" (truncated) -> idle
    - test_load_wrong_schema: {"schema_version": 2, "current": null} -> idle
    - test_load_missing_schema_version: {"current": null} -> idle (treated as wrong schema)
    - test_load_valid: full valid JSON -> current populated, history populated
    - test_current_phase_idle: status.current=None -> "idle"
    - test_current_phase_running: status.current={"phase": "pip_install"} -> "pip_install"
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/status.py` following the same defensive-read pattern
    as recovery.load_pending_marker and state_file.load_state. Match module conventions:
    - structlog logger with `component="updater.status"`
    - Never raise from load_status
    - Dataclass with explicit fields
    - Path constant STATUS_FILE_PATH at module top

    Implement the exact API above. No watching/polling — Phase 46 will add a WebSocket
    broadcaster. Plan 45-02 only provides the read primitive.

    Do NOT implement a writer in this module. Writes happen in updater_root/runner.py
    (Plan 45-03/45-04) as root; the main service never writes the status file.

    Create tests/test_updater_status.py with all behavior cases.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_status.py -x -v</automated>
  </verify>
  <done>
    - status.py exists with load_status / current_phase
    - All defensive cases return a safe UpdateStatus, never raise
    - Zero writes to /etc/pv-inverter-proxy during tests
  </done>
</task>

<task type="auto">
  <name>Task 3: POST /api/update/start route + install.sh file permissions</name>
  <files>src/pv_inverter_proxy/webapp.py, install.sh</files>
  <action>
    Part A — webapp.py:

    Add `update_start_handler` near `update_available_handler` (~line 266):

    ```python
    async def update_start_handler(request: web.Request) -> web.Response:
        """POST /api/update/start — EXEC-01, EXEC-02.

        Writes a trigger file atomically and returns HTTP 202. The actual
        update work happens in the root helper (pv-inverter-proxy-updater.service)
        triggered via the .path unit on PathModified.

        Phase 45 scope: NO auth, NO CSRF, NO rate limit (those ship in Phase 46).
        A valid JSON body is required:

            {"op": "update", "target_sha": "<40-char hex>"}

        Or for rollback:

            {"op": "rollback", "target_sha": "previous"}

        Response body:
            202: {"update_id": <nonce>, "status_url": "/api/update/status"}
            400: {"error": "<reason>"}
            500: {"error": "trigger_write_failed"}
        """
        from pv_inverter_proxy.updater.trigger import (
            TriggerPayload, generate_nonce, now_iso_utc, write_trigger,
        )

        try:
            body = await request.json()
        except (ValueError, TypeError) as e:
            return web.json_response({"error": f"invalid_json: {e}"}, status=400)

        if not isinstance(body, dict):
            return web.json_response({"error": "body_must_be_object"}, status=400)

        op = body.get("op")
        target_sha = body.get("target_sha")
        if not isinstance(op, str) or not isinstance(target_sha, str):
            return web.json_response(
                {"error": "op and target_sha required as strings"},
                status=400,
            )

        nonce = generate_nonce()
        payload = TriggerPayload(
            op=op,
            target_sha=target_sha,
            requested_at=now_iso_utc(),
            requested_by="webapp",
            nonce=nonce,
        )

        try:
            payload.validate()
        except ValueError as e:
            return web.json_response({"error": f"invalid_payload: {e}"}, status=400)

        try:
            write_trigger(payload)
        except OSError as e:
            return web.json_response(
                {"error": f"trigger_write_failed: {e}"},
                status=500,
            )

        return web.json_response(
            {"update_id": nonce, "status_url": "/api/update/status"},
            status=202,
        )
    ```

    Register the route near the existing update route (~line 2092):
    ```python
    app.router.add_post("/api/update/start", update_start_handler)
    ```

    **CRITICAL**: this handler must complete in under 100ms (EXEC-01). The write is sync
    (Path.write_text + os.replace) but targets /etc which is on the same filesystem as
    the tempfile — atomic and fast. No network IO, no subprocess, no await. Do NOT add
    auth/CSRF/rate-limit in this plan; those are Phase 46 work.

    Part B — install.sh file-level permissions:

    After the existing "Step 6a: State + backups dirs" block (line ~236), add a new block:

    ```bash
    # --- Step 6b: Update protocol file permissions (SEC-07) ---
    # update-trigger.json: mode 0664, owner root:pv-proxy.
    #   pv-proxy (main service) writes via tempfile+os.replace.
    #   root (updater.path) reads and consumes it.
    # update-status.json: mode 0644, owner root:root.
    #   ONLY the root updater writes; everyone (including pv-proxy) reads.
    #
    # We `touch` both files so they exist with the correct perms on fresh installs.
    # Existing files are chown/chmod'd — we do NOT truncate them (an in-progress
    # update must survive a re-install.sh run).
    info "Setting update protocol file permissions (SEC-07)..."
    TRIGGER_FILE="$CONFIG_DIR/update-trigger.json"
    STATUS_FILE="$CONFIG_DIR/update-status.json"

    if [ ! -e "$TRIGGER_FILE" ]; then
        # Create an empty placeholder so perms are correct from the start.
        # The main service will overwrite atomically on first POST /api/update/start.
        # An empty file is NOT a valid trigger (schema rejects) — safe to leave.
        install -o root -g "$SERVICE_USER" -m 0664 /dev/null "$TRIGGER_FILE"
    else
        chown "root:$SERVICE_USER" "$TRIGGER_FILE"
        chmod 0664 "$TRIGGER_FILE"
    fi

    if [ ! -e "$STATUS_FILE" ]; then
        install -o root -g root -m 0644 /dev/null "$STATUS_FILE"
    else
        chown "root:root" "$STATUS_FILE"
        chmod 0644 "$STATUS_FILE"
    fi
    ok "Update protocol files permissioned"
    ```

    Place this block BEFORE Step 7 (Systemd services).

    NOTE on research flag "/etc permissions": The directory /etc/pv-inverter-proxy/
    remains pv-proxy-owned from Phase 43. We do NOT chown the directory — only the
    two specific files. pv-proxy needs to be able to create new files in the
    directory for Phase 47 hot-reload work, so directory ownership stays pv-proxy.
    File-level ownership is enforced here.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -c "from pv_inverter_proxy.webapp import update_start_handler; print('import_ok')" && bash -n install.sh && echo install_sh_syntax_ok</automated>
  </verify>
  <done>
    - update_start_handler importable, route registered
    - install.sh passes bash -n syntax check
    - Permission block mentions both trigger (0664 root:pv-proxy) and status (0644 root:root)
    - Handler returns HTTP 202 on valid input, 400 on invalid, 500 on write failure
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: LXC deploy + smoke test trigger POST</name>
  <what-built>
    - `updater/trigger.py` module with atomic write
    - `updater/status.py` module with defensive read
    - `POST /api/update/start` route returning HTTP 202
    - install.sh file-level permissions for trigger and status files
  </what-built>
  <how-to-verify>
    1. Deploy to LXC (`./deploy.sh` or equivalent auto-deploy)
    2. SSH to LXC and run install.sh to apply the new file permissions:
       `ssh root@192.168.3.191 'cd /opt/pv-inverter-proxy && bash install.sh'`
    3. Verify permissions:
       ```
       ssh root@192.168.3.191 'ls -l /etc/pv-inverter-proxy/update-trigger.json /etc/pv-inverter-proxy/update-status.json'
       ```
       Expected:
       ```
       -rw-rw-r-- 1 root pv-proxy 0 ... update-trigger.json
       -rw-r--r-- 1 root root     0 ... update-status.json
       ```
    4. POST a trigger:
       ```
       curl -i -X POST http://192.168.3.191/api/update/start \
         -H 'Content-Type: application/json' \
         -d '{"op":"update","target_sha":"0000000000000000000000000000000000000000"}'
       ```
       Expected: HTTP/1.1 202, body has `update_id` and `status_url`.
    5. Verify trigger file contents:
       `ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/update-trigger.json'`
       Expected: JSON with all 5 schema fields, pretty-printed, sorted keys.
    6. POST an invalid trigger (short SHA):
       ```
       curl -i -X POST http://192.168.3.191/api/update/start \
         -H 'Content-Type: application/json' \
         -d '{"op":"update","target_sha":"abc"}'
       ```
       Expected: HTTP/1.1 400, body `{"error":"invalid_payload: ..."}`.
    7. Measure latency (EXEC-01 < 100ms):
       ```
       for i in 1 2 3 4 5; do
         curl -s -o /dev/null -w "%{time_total}\n" -X POST http://192.168.3.191/api/update/start \
           -H 'Content-Type: application/json' \
           -d '{"op":"update","target_sha":"1111111111111111111111111111111111111111"}'
       done
       ```
       Expected: All 5 times under 0.1s (100ms).
    8. Confirm no updater service exists yet (will fail — expected):
       `ssh root@192.168.3.191 'systemctl status pv-inverter-proxy-updater.path || echo "absent - OK, Plan 45-04 will install"'`
    9. Verify status file still exists and is readable by unprivileged user:
       `ssh pv-proxy@192.168.3.191 'cat /etc/pv-inverter-proxy/update-status.json 2>&1 || cat /etc/pv-inverter-proxy/update-status.json'`
       Expected: empty output (empty file), no permission error.
  </how-to-verify>
  <resume-signal>Type "approved" if all 9 checks pass, or describe discrepancies (especially latency above 100ms).</resume-signal>
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
| LAN client → webapp POST /api/update/start | Unauthenticated LAN trigger write (no CSRF/rate limit until Phase 46) |
| pv-proxy → filesystem (/etc/pv-inverter-proxy/) | Main service writes trigger; updater (Plan 45-03+) reads |
| webapp → updater (via file contract) | One-way, filesystem-enforced trust channel |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-45-02-01 | Tampering | Trigger file schema | mitigate | Plan 45-03 will re-validate with stricter rules (SHA must be reachable from origin/main per EXEC-04, tag regex per SEC-06). Producer-side validation here is defense-in-depth only; the security boundary is consumer-side. |
| T-45-02-02 | Elevation of privilege | POST /api/update/start unauthenticated in Phase 45 | accept | Phase 45 is CLI-only validation. The risk window is limited to "Plan 45-04 is shipped but Phase 46 (CSRF + rate limit) not yet" — this is a sequential phase ordering decision. Mitigation: SEC-01..04 in Phase 46 land BEFORE the UI surfaces an Install button. The trigger file on its own is inert until the updater consumes it. |
| T-45-02-03 | Denial of service | Trigger file flood | mitigate | write_trigger is atomic (tempfile + os.replace). Flooding POST /api/update/start overwrites the same file — only the last write wins. Path-unit triggers on PathModified, so N writes collapse to 1 or 2 updater activations. Plan 45-03 nonce dedup ensures each unique trigger runs at most once. |
| T-45-02-04 | Spoofing | requested_by field | accept | Phase 45 hardcodes "webapp" in update_start_handler. Phase 46 will add audit log with source IP. No authn in v8.0. |
| T-45-02-05 | Information disclosure | Status file 0644 world-readable | accept | Status file contains phase name, target SHA, timestamps — all non-sensitive metadata. SEC-07 explicitly requires 0644 so the main service (pv-proxy) can read it for UI surfacing. |
| T-45-02-06 | Tampering | Trigger file writable by pv-proxy | mitigate | File ownership root:pv-proxy with mode 0664 means only pv-proxy (and root) can write. A compromise of pv-proxy already has full code-exec in the main service context; writing a trigger is not additional privilege. The security root of trust is Plan 45-03's SHA reachability check against origin/main. |
| T-45-02-07 | Race | os.replace vs pathunit PathModified | mitigate | Atomic replace guarantees readers see either old or new content, never partial. PathModified may fire on both the tempfile creation and the rename; Plan 45-03 must be idempotent — nonce dedup handles this. |
| T-45-02-08 | Race | install.sh re-run mid-update | mitigate | install.sh does NOT truncate existing trigger/status files (only re-chowns/chmods). An in-progress update survives. |
</threat_model>

<verification>
## Validation Strategy

| REQ | Test Type | Evidence |
|-----|-----------|----------|
| EXEC-01 | Integration (Task 4 curl latency test) | 5 consecutive POSTs under 100ms |
| EXEC-01 | Unit (tests/test_updater_trigger.py) | Atomic write semantics |
| EXEC-02 | Unit (tests/test_updater_trigger.py::test_validate_*) | Schema validation |
| EXEC-02 | Unit (tests/test_updater_trigger.py::test_write_trigger_correct_schema_keys) | Key set exactly matches |
| SEC-07 | LXC smoke (Task 4 ls -l output) | Ownership root:pv-proxy 0664 and root:root 0644 |

## Failure Rollback

If Task 4 fails:
1. `git revert HEAD` reverts the webapp route, install.sh changes, and new modules atomically
2. If only file permissions are wrong, `ssh root@lxc 'chown root:pv-proxy /etc/pv-inverter-proxy/update-trigger.json && chmod 0664 ...'` — manual fix before re-deploy
3. If latency > 100ms, profile the handler with `time` around write_trigger — likely a disk-level issue, not a code issue
</verification>

<success_criteria>
- updater/trigger.py and updater/status.py both pass unit tests
- POST /api/update/start returns 202 in under 100ms (measured on LXC)
- /etc/pv-inverter-proxy/update-trigger.json has mode 0664 and owner root:pv-proxy after install.sh
- /etc/pv-inverter-proxy/update-status.json has mode 0644 and owner root:root
- Schema validation rejects short SHAs, bad ops, empty nonces
- No updater consumer required for this plan — the trigger file just sits on disk
- Plan 45-03 can now assume trigger files exist with the v1 schema and read them as root
</success_criteria>

<output>
After completion, create `.planning/phases/45-privileged-updater-service/45-02-SUMMARY.md` capturing:
- Measured POST latency (5 samples from curl)
- Final install.sh Step 6b block (copy-paste)
- Decision log for any deviation from the schema
- Confirmation that permission research flag is resolved (file-level chown, NOT directory-level)
</output>
