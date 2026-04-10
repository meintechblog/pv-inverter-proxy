---
phase: 45-privileged-updater-service
plan: 04
type: execute
wave: 4
depends_on:
  - "45-03"
files_modified:
  - src/pv_inverter_proxy/updater_root/runner.py
  - src/pv_inverter_proxy/updater_root/healthcheck.py
  - src/pv_inverter_proxy/updater_root/status_writer.py
  - src/pv_inverter_proxy/updater_root/pip_ops.py
  - src/pv_inverter_proxy/updater_root/__main__.py
  - config/pv-inverter-proxy-updater.path
  - config/pv-inverter-proxy-updater.service
  - install.sh
  - tests/test_updater_root_runner.py
  - tests/test_updater_root_healthcheck.py
  - tests/test_updater_root_status_writer.py
autonomous: false
requirements:
  - EXEC-03
  - EXEC-06
  - EXEC-07
  - EXEC-08
  - EXEC-09
  - EXEC-10
  - RESTART-04
  - RESTART-05
  - HEALTH-05
  - HEALTH-06
  - HEALTH-07
  - HEALTH-08
  - HEALTH-09
exec_10_delivery_note: |
  EXEC-10 delivered via git SHA integrity, NOT tarball + SHA256SUMS download.
  
  Architectural decision (Phase 45 research): the updater uses `git fetch` +
  `git checkout --detach <target_sha>` to install new releases. Git SHAs are
  cryptographic content hashes (Merkle tree). A SHA that passes
  `is_sha_on_main` (45-03 Task 1: `git merge-base --is-ancestor refs/remotes/origin/main <sha>`)
  has ALREADY been integrity-verified by git's own tree hash. Separate
  SHA256SUMS verification would be redundant in this install path.
  
  The `verify_sha256sums_file` primitive built in 45-03 Task 4 is retained as a
  library helper for Phase 47's potential tarball-based alternative install
  path (e.g., for airgapped deploys), but is NOT called by the Phase 45 runner
  state machine. GPG signature verification via `git tag -v` is the SEC-05
  optional path; full GPG is Phase 47.
  
  This resolves plan-checker BLOCKER 1 (EXEC-10 never wired in runner) without
  requiring a download step. REQUIREMENTS.md EXEC-10 text has been updated to
  reflect the git-SHA integrity model.
must_haves:
  truths:
    - "pv-inverter-proxy-updater.path watches /etc/pv-inverter-proxy/update-trigger.json and activates pv-inverter-proxy-updater.service on modification"
    - "pv-inverter-proxy-updater.service is Type=oneshot, User=root, runs python -m pv_inverter_proxy.updater_root"
    - "Updater runs a state machine: trigger_received -> backup -> extract -> pip_install -> smoke_import -> config_dryrun -> restarting -> healthcheck -> done OR rollback"
    - "Status file is written with monotonic phase history (HEALTH-09)"
    - "PENDING marker is written BEFORE the symlink flip so Phase 43 recovery.py can undo on next boot"
    - "healthcheck poller requires 3 consecutive /api/health ok + /run/pv-inverter-proxy/healthy present + version matches target, over 15s, with a 60s hard timeout"
    - "Rollback on failure: symlink flip to previous release + systemctl restart + health re-check; max 1 rollback per attempt (HEALTH-08)"
    - "Second failure writes phase=rollback_failed with CRITICAL state and leaves symlink as-is"
    - "Root helper NEVER imports main service modules except releases, recovery, state_file (enforced by Plan 45-03 trust boundary test)"
    - "End-to-end test on LXC: writing a same-SHA trigger triggers a full cycle (backup, reinstall, restart, health-check, success)"
  artifacts:
    - path: "src/pv_inverter_proxy/updater_root/runner.py"
      provides: "UpdateRunner state machine orchestrator"
      contains: "class UpdateRunner"
    - path: "src/pv_inverter_proxy/updater_root/healthcheck.py"
      provides: "HealthChecker with 3-of-N consecutive ok + version match"
      contains: "class HealthChecker"
    - path: "src/pv_inverter_proxy/updater_root/status_writer.py"
      provides: "StatusFileWriter atomic phase-progression writer"
      contains: "def write_phase"
    - path: "src/pv_inverter_proxy/updater_root/pip_ops.py"
      provides: "pip install --dry-run + real install + compileall wrappers"
      contains: "async def pip_install"
    - path: "src/pv_inverter_proxy/updater_root/__main__.py"
      provides: "CLI entry point for systemd helper service"
      contains: "def main"
    - path: "config/pv-inverter-proxy-updater.path"
      provides: "Path unit watching update-trigger.json"
    - path: "config/pv-inverter-proxy-updater.service"
      provides: "Oneshot unit running updater_root"
  key_links:
    - from: "pv-inverter-proxy-updater.path"
      to: "pv-inverter-proxy-updater.service"
      via: "Unit= directive + PathModified="
      pattern: "PathModified=/etc/pv-inverter-proxy/update-trigger\\.json"
    - from: "runner.py::UpdateRunner._flip_symlink"
      to: "recovery.PENDING_MARKER_PATH"
      via: "Phase 43 recovery schema — written BEFORE flip"
      pattern: "PendingMarker"
    - from: "runner.py"
      to: "healthcheck.py::HealthChecker.wait_for_healthy"
      via: "post-restart call"
      pattern: "wait_for_healthy"
---

<objective>
Compose Plan 45-03's primitives into an end-to-end update orchestrator. Add the systemd path+service unit pair, install them, wire the entry point, write the state machine that drives: trigger->backup->extract->install->smoke->restart->health->(done|rollback). By the end of this plan, writing a trigger file as root on the LXC triggers a full observable update cycle via journalctl.

Purpose: This is the gate. After Plan 45-04, the user has "CLI-only end-to-end update works" — the top-line Phase 45 success criterion. No UI wiring (Phase 46) yet, but the entire backend is alive and testable.

Output: Orchestrator state machine, post-restart health checker with rollback logic, systemd unit pair, install.sh extension, a unit-tested fake-subprocess runner test suite, and an LXC observation test.
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
@src/pv_inverter_proxy/releases.py
@src/pv_inverter_proxy/recovery.py
@src/pv_inverter_proxy/updater_root/git_ops.py
@src/pv_inverter_proxy/updater_root/backup.py
@src/pv_inverter_proxy/updater_root/trigger_reader.py
@src/pv_inverter_proxy/updater_root/gpg_verify.py
@config/pv-inverter-proxy.service
@config/pv-inverter-proxy-recovery.service
@install.sh

<interfaces>
From Plan 45-03 (composed in this plan):
```python
# git_ops.py
async def run_git(*args, cwd, timeout_s=60): ...  # GitResult
async def git_fetch(repo_dir, remote="origin"): ...
async def git_rev_parse(repo_dir, ref): ...  # str | None
async def is_sha_on_main(repo_dir, sha, main_ref="refs/remotes/origin/main"): ...  # bool
async def git_clone_shared(source, dest): ...
async def git_checkout_detach(repo_dir, sha): ...

# backup.py
def create_backup(release_dir, config_path, backups_root=None, now=None): ...  # BackupResult
def apply_backup_retention(backups_root=None, keep=3): ...  # list[Path]
def apply_release_retention(releases_root=None, keep=3, protect=None): ...  # list[Path]

# trigger_reader.py
class NonceDedupStore: ...
class TriggerValidationError(Exception): ...
class NonceReplayError(TriggerValidationError): ...
def read_and_validate_trigger(path, dedup_store): ...  # ValidatedTrigger

# gpg_verify.py
@dataclass GpgConfig(allow_unsigned=True, keyring_path=None)
def verify_sha256sums_file(sums_path, files_dir): ...  # list[(name, match, hash)]
async def verify_sha256sums_signature(sums_path, sig_path, config): ...  # GpgResult
```

From Phase 43:
```python
# recovery.py
PENDING_MARKER_PATH: Path = Path("/var/lib/pv-inverter-proxy/update-pending.marker")

@dataclass
class PendingMarker:
    previous_release: str
    target_release: str
    created_at: float
    reason: str = "update"
    schema_version: int = 1

# releases.py
RELEASES_ROOT = Path("/opt/pv-inverter-proxy-releases")
INSTALL_ROOT = Path("/opt/pv-inverter-proxy")
CURRENT_SYMLINK_NAME = "current"
```

From Plan 45-01 (/api/health schema):
```json
{
  "status": "ok" | "starting" | "degraded",
  "version": "8.0.0",
  "commit": "abc1234",
  "uptime_seconds": 42.1,
  "webapp": "ok",
  "modbus_server": "ok",
  "devices": {"se30k": "ok"},
  "venus_os": "ok" | "disabled" | "degraded"
}
```

From Plan 45-02 (trigger schema read by this plan's runner):
```json
{"op": "update"|"rollback", "target_sha": "<sha|previous>",
 "requested_at": "...", "requested_by": "...", "nonce": "..."}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: updater_root/status_writer.py — phase-progression status file (HEALTH-09)</name>
  <files>src/pv_inverter_proxy/updater_root/status_writer.py, tests/test_updater_root_status_writer.py</files>
  <behavior>
    API:
    - `STATUS_FILE_PATH = Path("/etc/pv-inverter-proxy/update-status.json")`
    - `STATUS_FILE_MODE = 0o644`
    - `class StatusFileWriter`:
        * `__init__(self, path: Path | None = None, clock: Callable[[], float] = time.time)`
        * `begin(self, nonce: str, target_sha: str, old_sha: str) -> None`: initializes current + empties history except for a trigger_received entry
        * `write_phase(self, phase: str, *, error: str | None = None) -> None`:
            - Appends to history list with {phase, at: iso_utc, error: error if error else absent}
            - Updates current.phase = phase
            - Atomic write via tempfile + os.replace
            - Mode 0o644
        * `finalize(self, outcome: str) -> None`: outcome ∈ {"done", "rollback_done", "rollback_failed"}
            - Sets current.phase = outcome
            - Writes final entry to history
            - current stays populated (NOT None) so UI can show the last result
        * `load_existing(self) -> dict | None`: for re-entry case (unused in Plan 45-04 but available for Plan 46)

    Phase allowlist (monotonic progression gate):
    ```
    PHASES = [
        "trigger_received", "backup", "extract", "pip_install_dryrun",
        "pip_install", "compileall", "smoke_import", "config_dryrun",
        "pending_marker_written", "symlink_flipped", "restarting",
        "healthcheck", "done",
        # Rollback branch (enters after any of the above fails, up to config_dryrun
        # before symlink flip, or after healthcheck fails post-restart)
        "rollback_starting", "rollback_symlink_flipped", "rollback_restarting",
        "rollback_healthcheck", "rollback_done", "rollback_failed",
    ]
    ```

    Test cases:
    - test_begin_writes_current: begin() -> file exists, current populated, history has 1 entry (trigger_received)
    - test_write_phase_appends: begin + write_phase("backup") + write_phase("extract") -> history has 3 entries in order
    - test_write_phase_updates_current: current.phase is the latest written phase
    - test_write_phase_error_field: write_phase("rollback", error="smoke import failed") -> last entry has error field
    - test_finalize_sets_outcome: finalize("done") -> current.phase == "done"
    - test_atomic_write_no_partial: monkeypatch os.replace to raise -> file unchanged (if it existed before)
    - test_mode_0644: os.stat(status).st_mode & 0o777 == 0o644
    - test_load_existing_missing_returns_none: load_existing() on missing path -> None
    - test_load_existing_corrupt_returns_none: file with garbage -> None (defensive)
    - test_unknown_phase_allowed_but_logs: writing a phase not in PHASES logs a warning but writes successfully (don't block on typos)
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/status_writer.py`:

    ```python
    """Atomic phase-progression writer for /etc/pv-inverter-proxy/update-status.json
    (HEALTH-09). The updater calls write_phase() at every state transition.

    Mode is 0644 so the main service (pv-proxy) can read the status for
    UI surfacing, while only root (this module) writes.
    """
    from __future__ import annotations

    import json
    import os
    import time
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Callable

    import structlog

    log = structlog.get_logger(component="updater_root.status")

    STATUS_FILE_PATH: Path = Path("/etc/pv-inverter-proxy/update-status.json")
    STATUS_FILE_MODE: int = 0o644

    PHASES = frozenset({
        "trigger_received", "backup", "extract", "pip_install_dryrun",
        "pip_install", "compileall", "smoke_import", "config_dryrun",
        "pending_marker_written", "symlink_flipped", "restarting",
        "healthcheck", "done",
        "rollback_starting", "rollback_symlink_flipped", "rollback_restarting",
        "rollback_healthcheck", "rollback_done", "rollback_failed",
    })


    def _iso_utc(t: float) -> str:
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


    class StatusFileWriter:
        def __init__(
            self,
            path: Path | None = None,
            clock: Callable[[], float] = time.time,
        ) -> None:
            self._path = path or STATUS_FILE_PATH
            self._clock = clock
            self._state: dict = {
                "schema_version": 1,
                "current": None,
                "history": [],
            }

        def begin(self, nonce: str, target_sha: str, old_sha: str) -> None:
            now = self._clock()
            self._state["current"] = {
                "nonce": nonce,
                "phase": "trigger_received",
                "target_sha": target_sha,
                "old_sha": old_sha,
                "started_at": _iso_utc(now),
            }
            self._state["history"] = [
                {"phase": "trigger_received", "at": _iso_utc(now)},
            ]
            self._flush()

        def write_phase(self, phase: str, *, error: str | None = None) -> None:
            if phase not in PHASES:
                log.warning("status_unknown_phase", phase=phase)
            if self._state["current"] is None:
                log.warning("status_write_phase_without_begin", phase=phase)
                return
            now = self._clock()
            self._state["current"]["phase"] = phase
            entry: dict = {"phase": phase, "at": _iso_utc(now)}
            if error is not None:
                entry["error"] = error
            self._state["history"].append(entry)
            self._flush()

        def finalize(self, outcome: str) -> None:
            self.write_phase(outcome)

        def load_existing(self) -> dict | None:
            if not self._path.exists():
                return None
            try:
                data = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError) as e:
                log.warning("status_load_failed", error=str(e))
                return None
            if not isinstance(data, dict):
                return None
            return data

        def _flush(self) -> None:
            tmp = self._path.with_suffix(".json.tmp")
            blob = json.dumps(self._state, indent=2, sort_keys=True)
            try:
                tmp.write_text(blob)
                os.replace(tmp, self._path)
                os.chmod(self._path, STATUS_FILE_MODE)
            except OSError as e:
                log.error("status_flush_failed", path=str(self._path), error=str(e))
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                raise
    ```

    Create tests/test_updater_root_status_writer.py with all behavior cases.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_status_writer.py -x -v</automated>
  </verify>
  <done>Status writer exists; tests pass; monotonic progression verified.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: updater_root/pip_ops.py — pip install --dry-run + real install + compileall</name>
  <files>src/pv_inverter_proxy/updater_root/pip_ops.py, tests/test_updater_root_pip_ops.py</files>
  <behavior>
    API:
    - `@dataclass PipResult(returncode, stdout, stderr)`
    - `async def create_venv(venv_dir: Path) -> PipResult`: runs `python3 -m venv <venv_dir>`
    - `async def pip_install_dry_run(venv_python: Path, project_dir: Path) -> PipResult`:
        * EXEC-07: runs `<venv_python> -m pip install --dry-run -e <project_dir>`
        * Returns PipResult; caller checks .ok
    - `async def pip_install(venv_python: Path, project_dir: Path) -> PipResult`:
        * runs `<venv_python> -m pip install -e <project_dir>`
    - `async def compileall(venv_python: Path, src_dir: Path) -> PipResult`:
        * EXEC-09: runs `<venv_python> -m compileall -q <src_dir>`
    - `async def smoke_import(venv_python: Path) -> PipResult`:
        * EXEC-08: runs `<venv_python> -c "import pv_inverter_proxy; print('ok')"`
    - `async def config_dryrun(venv_python: Path, config_path: Path) -> PipResult`:
        * EXEC-08: runs `<venv_python> -c "from pv_inverter_proxy.config import load_config; load_config('<path>')"`
        * This runs against the NEW code but the EXISTING config.yaml — catches schema incompatibilities

    Timeouts:
    - dry_run: 300s
    - install: 600s
    - compileall: 120s
    - smoke_import: 30s
    - config_dryrun: 30s

    Test cases (hermetic with subprocess fakes):
    - test_pip_install_dry_run_passes_correct_args: monkeypatch create_subprocess_exec, capture argv, assert "--dry-run" in args
    - test_pip_install_wraps_timeout: fake subprocess that hangs, assert raises PipTimeoutError
    - test_compileall_invokes_compileall: argv contains "compileall" and "-q"
    - test_smoke_import_argv: argv[-1] == "import pv_inverter_proxy; print('ok')"
    - test_config_dryrun_path_escaped: config path with spaces passed as separate argv element, not interpolated
    - test_all_use_exec_not_shell: verify no shell=True
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/pip_ops.py` following the same async
    subprocess pattern as git_ops.py. Reuse the GitTimeoutError-style exception but
    namespaced as `PipTimeoutError`. Do NOT import from git_ops; copy the run_subprocess
    helper if it makes sense (they both have the same shape).

    Use explicit argv for every call:
    ```python
    await asyncio.create_subprocess_exec(
        str(venv_python), "-m", "pip", "install", "--dry-run", "-e", str(project_dir),
        stdout=PIPE, stderr=PIPE,
    )
    ```

    Create tests/test_updater_root_pip_ops.py with monkeypatch-based subprocess fakes.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_pip_ops.py -x -v</automated>
  </verify>
  <done>pip_ops.py exists with all 6 functions; tests pass.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: updater_root/healthcheck.py — post-restart health poller with rollback triggers</name>
  <files>src/pv_inverter_proxy/updater_root/healthcheck.py, tests/test_updater_root_healthcheck.py</files>
  <behavior>
    API:
    - `@dataclass HealthCheckConfig: health_url="http://127.0.0.1/api/health", healthy_flag_path=Path("/run/pv-inverter-proxy/healthy"), hard_timeout_s=60.0, consecutive_ok_required=3, poll_interval_s=5.0, degraded_5xx_timeout_s=45.0`
    - `@dataclass HealthCheckOutcome: success: bool, reason: str, last_response: dict | None, probes: int, consecutive_ok: int`
    - `class HealthChecker`:
        * `__init__(self, config, expected_version: str | None, expected_commit: str | None, session_factory: Callable | None = None, clock: Callable | None = None)`
        * `async def wait_for_healthy(self) -> HealthCheckOutcome`
    - `async def check_systemctl_active(unit: str = "pv-inverter-proxy.service") -> bool`: wraps `systemctl is-active --quiet`
    - `async def systemctl_restart(unit: str = "pv-inverter-proxy.service") -> bool`: wraps `systemctl restart`

    Decision logic for wait_for_healthy (HEALTH-05, HEALTH-06):
    1. Track t_start = clock()
    2. Track consecutive_ok_count = 0
    3. Loop until (consecutive_ok_count >= consecutive_ok_required) OR (clock() - t_start >= hard_timeout_s):
        a. await asyncio.sleep(poll_interval_s)
        b. Check systemctl is-active; if failed -> return HealthCheckOutcome(success=False, reason="systemctl_failed")
        c. aiohttp GET health_url with 5s timeout
        d. If request raises (connection refused, timeout, etc.) -> consecutive_ok=0; record last_error
        e. If returns 5xx -> consecutive_ok=0; if 5xx+unreachable > degraded_5xx_timeout_s since start -> return early fail
        f. If returns 200 with valid JSON:
            - If expected_version not None AND response["version"] != expected_version -> return (False, "version_mismatch")
            - If response["status"] == "ok" AND required-for-success (see below) -> consecutive_ok += 1
            - Else -> consecutive_ok = 0
        g. Check healthy_flag_path.exists() for HEALTH-04 signal
    4. After loop:
        - If consecutive_ok >= required AND healthy_flag exists -> return (True, "stable_ok")
        - If timeout AND no healthy flag after hard_timeout_s -> return (False, "no_healthy_flag")
        - If timeout -> return (False, "timeout")

    Required-for-success (from Plan 45-01's schema):
    - response["webapp"] == "ok"
    - response["modbus_server"] == "ok"
    - any(v == "ok" for v in response["devices"].values())
    - response["venus_os"] is warn-only, ignored

    Test cases (hermetic with aiohttp client mocked):
    - test_healthcheck_all_ok_first_try_still_waits_for_consecutive: fake returns 3 oks -> success after 3 polls, not 1
    - test_healthcheck_version_mismatch_immediate_fail: fake returns version!=expected -> fail with version_mismatch
    - test_healthcheck_timeout_no_flag: fake always returns 503 -> fail with no_healthy_flag or timeout
    - test_healthcheck_transient_flakes_tolerated: ok, fail, ok, ok, ok -> success (consecutive resets on fail, rebuilds to 3)
    - test_healthcheck_systemctl_failed_immediate: monkeypatch check_systemctl_active to False -> fail with systemctl_failed
    - test_healthcheck_healthy_flag_required: 3 consecutive ok BUT healthy flag missing -> still fails (flag must also be present)
    - test_healthcheck_venus_warn_ignored: response has venus_os=degraded but everything else ok -> success
    - test_healthcheck_counts_probes: outcome.probes reflects number of loop iterations
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/healthcheck.py`. Use aiohttp for the HTTP
    call (already a project dep). Build the ClientSession locally in the method so the
    updater_root process owns its own connections (no shared pool with the main service).

    For systemctl helpers, reuse the subprocess-exec pattern from git_ops/pip_ops:

    ```python
    async def check_systemctl_active(unit: str = "pv-inverter-proxy.service") -> bool:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", "--quiet", unit,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        return rc == 0


    async def systemctl_restart(unit: str = "pv-inverter-proxy.service") -> bool:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "restart", unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    ```

    For the HealthChecker, accept a `session_factory` callable so tests can inject a fake
    session that returns pre-canned responses:

    ```python
    async def wait_for_healthy(self) -> HealthCheckOutcome:
        t0 = self._clock()
        consecutive_ok = 0
        probes = 0
        last_response: dict | None = None
        session = await self._session_factory()
        try:
            while True:
                elapsed = self._clock() - t0
                if elapsed >= self._cfg.hard_timeout_s:
                    break
                if consecutive_ok >= self._cfg.consecutive_ok_required \
                   and self._cfg.healthy_flag_path.exists():
                    return HealthCheckOutcome(True, "stable_ok", last_response, probes, consecutive_ok)
                await asyncio.sleep(self._cfg.poll_interval_s)
                probes += 1
                if not await check_systemctl_active():
                    return HealthCheckOutcome(False, "systemctl_failed", last_response, probes, 0)
                try:
                    async with session.get(self._cfg.health_url, timeout=5) as resp:
                        if resp.status >= 500:
                            consecutive_ok = 0
                            continue
                        body = await resp.json()
                        last_response = body
                        if self._expected_version and body.get("version") != self._expected_version:
                            return HealthCheckOutcome(False, "version_mismatch", body, probes, consecutive_ok)
                        if self._is_required_ok(body):
                            consecutive_ok += 1
                        else:
                            consecutive_ok = 0
                except Exception as e:
                    consecutive_ok = 0
                    last_response = {"error": str(e)}
        finally:
            await session.close()
        if consecutive_ok >= self._cfg.consecutive_ok_required:
            if not self._cfg.healthy_flag_path.exists():
                return HealthCheckOutcome(False, "no_healthy_flag", last_response, probes, consecutive_ok)
            return HealthCheckOutcome(True, "stable_ok", last_response, probes, consecutive_ok)
        return HealthCheckOutcome(False, "timeout", last_response, probes, consecutive_ok)
    ```

    For tests use a monkeypatched `clock` (virtual time) so the test doesn't sleep 60s:
    ```python
    class VirtualClock:
        def __init__(self): self.t = 0.0
        def __call__(self): return self.t

    async def fake_sleep(s): clock.t += s
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    ```

    And a fake session:
    ```python
    class FakeResponse:
        def __init__(self, status, body): self.status = status; self._body = body
        async def json(self): return self._body
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class FakeSession:
        def __init__(self, responses): self.responses = iter(responses)
        def get(self, url, **kw): return next(self.responses)
        async def close(self): pass
    ```

    Also monkeypatch `check_systemctl_active` to return True (or False for the systemctl-failed test).

    Create tests/test_updater_root_healthcheck.py with all behavior cases.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_healthcheck.py -x -v</automated>
  </verify>
  <done>
    - HealthChecker passes all tests
    - Tests complete in under 2s total (virtual clock, no real sleeps)
    - Required-for-success logic matches Plan 45-01 schema
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: updater_root/runner.py — orchestrator state machine</name>
  <files>src/pv_inverter_proxy/updater_root/runner.py, tests/test_updater_root_runner.py</files>
  <behavior>
    API:
    - `@dataclass UpdateRunnerConfig`:
        releases_root, install_root, current_symlink, backups_root,
        trigger_path, status_path, config_path, dedup_path, pending_marker_path,
        main_service_unit, gpg_config, pip_install_timeout_s, keep_releases
    - `@classmethod UpdateRunnerConfig.default() -> UpdateRunnerConfig`: production paths

    - `class UpdateRunner`:
        * `__init__(self, config: UpdateRunnerConfig, clock=time.time)`
        * `async def run(self) -> int`: entry point, returns exit code (0 success, 1 failure, 2 rollback, 3 rollback_failed)

    State machine (sketch):
    ```
    async def run(self):
        # Phase: trigger_received
        status.begin(...)  # after reading trigger
        trigger = read_and_validate_trigger(...)
        if not is_sha_on_main(current_release_dir, trigger.target_sha):
            status.finalize("rollback_failed")  # NOT rollback — this is a pre-flight reject
            return 1
        disk = check_disk_space()
        if not disk.ok:
            fail with reason=disk_space
        old_sha = await git_rev_parse(current_release_dir, "HEAD")
        # Phase: backup
        backup_result = create_backup(current_release_dir, config_path, backups_root)
        # Phase: extract (new release dir)
        new_release_dir = releases_root / f"<version>-<shortsha>"  # mkdir
        await git_clone_shared(current_release_dir, new_release_dir)
        await git_checkout_detach(new_release_dir, trigger.target_sha)
        # Phase: pip_install_dryrun
        await create_venv(new_release_dir / ".venv")
        dry = await pip_install_dry_run(new_venv_python, new_release_dir)
        if not dry.ok: fail
        # Phase: pip_install
        inst = await pip_install(new_venv_python, new_release_dir)
        if not inst.ok: fail (no symlink flip yet — safe abort)
        # Phase: compileall
        await compileall(new_venv_python, new_release_dir / "src")
        # Phase: smoke_import
        smoke = await smoke_import(new_venv_python)
        if not smoke.ok: fail (still pre-flip, safe)
        # Phase: config_dryrun
        cfg = await config_dryrun(new_venv_python, config_path)
        if not cfg.ok: fail (still pre-flip, safe)
        # Phase: pending_marker_written — POINT OF NO RETURN
        write_pending_marker(previous_release=current_release_dir, target_release=new_release_dir)
        # Phase: symlink_flipped
        atomic_symlink_flip(current_symlink, new_release_dir)
        # Phase: restarting
        await systemctl_restart(main_service_unit)
        # Phase: healthcheck
        new_commit = await git_rev_parse(new_release_dir, "HEAD")
        # Read new version from new venv's importlib.metadata? Or just
        # verify commit matches. For Plan 45-04 we assert commit matches.
        hc = HealthChecker(hc_config, expected_version=None, expected_commit=new_commit)
        outcome = await hc.wait_for_healthy()
        if outcome.success:
            clear_pending_marker()
            apply_release_retention(protect={current_release_dir})  # previous is protected
            apply_backup_retention()
            status.finalize("done")
            return 0
        else:
            # ROLLBACK (HEALTH-07)
            return await self._rollback(old_sha, current_release_dir, outcome.reason)

    async def _rollback(self, old_sha, previous_release_dir, reason):
        status.write_phase("rollback_starting", error=reason)
        atomic_symlink_flip(current_symlink, previous_release_dir)
        status.write_phase("rollback_symlink_flipped")
        await systemctl_restart(main_service_unit)
        status.write_phase("rollback_restarting")
        hc2 = HealthChecker(hc_config, expected_version=None, expected_commit=old_sha)
        outcome2 = await hc2.wait_for_healthy()
        if outcome2.success:
            clear_pending_marker()
            status.finalize("rollback_done")
            return 2
        status.finalize("rollback_failed")  # CRITICAL — user must SSH
        return 3
    ```

    HEALTH-08 enforcement: _rollback is called AT MOST ONCE per run() invocation. If
    _rollback itself fails, status goes to rollback_failed, NOT to another rollback attempt.

    Test strategy: the runner has too many moving parts for a pure unit test. Instead:
    - Split it into a plain state-machine class with injected async callables for ALL
      side effects (git, pip, backup, healthcheck, symlink flip, systemctl, status writer).
    - Unit test the state machine with fakes for each primitive.
    - Only the `__main__.py` wires the real primitives.

    Test cases:
    - test_happy_path: all primitives succeed -> run() returns 0, status has full phase history ending in "done", retention called, pending marker cleared
    - test_sha_not_on_main_aborts_early: is_sha_on_main fake returns False -> no backup, no extract, status=failed
    - test_pip_dryrun_fail_no_flip: dryrun fake returns non-zero -> no symlink flip, no pending marker
    - test_smoke_import_fail_no_flip: smoke fake returns non-zero -> no symlink flip
    - test_config_dryrun_fail_no_flip: cfg fake returns non-zero -> no symlink flip
    - test_healthcheck_fail_triggers_rollback: healthcheck fake returns success=False -> _rollback called, status has rollback_starting + rollback_symlink_flipped + rollback_restarting + rollback_done; return code 2
    - test_healthcheck_fail_second_healthcheck_also_fails_rollback_failed: both hc calls fail -> rollback_failed, return 3
    - test_rollback_symlink_failure_marks_rollback_failed: atomic_symlink_flip fake raises on second call -> rollback_failed
    - test_disk_space_preflight_aborts: check_disk_space fake returns ok=False -> no backup, no further action
    - test_pending_marker_written_before_flip: assert the sequence — pending_marker_written phase comes BEFORE symlink_flipped
    - test_max_one_rollback: monkey the runner to verify _rollback is called at most once even if the mock scheduler would invite a second

    All tests use dependency-injected fakes — no real subprocess, no real filesystem writes
    outside tmp_path for status and backups.
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/runner.py`.

    Design: the UpdateRunner takes a `primitives` bag (a dataclass of all the async/sync
    callables it needs). Production construction wires the real primitives; tests wire fakes.

    ```python
    @dataclass
    class UpdateRunnerPrimitives:
        # Git
        is_sha_on_main: Callable[[Path, str], Awaitable[bool]]
        git_rev_parse: Callable[[Path, str], Awaitable[str | None]]
        git_clone_shared: Callable[[Path, Path], Awaitable[Any]]
        git_checkout_detach: Callable[[Path, str], Awaitable[Any]]
        # Disk
        check_disk_space: Callable[[], Any]
        # Backup
        create_backup: Callable[[Path, Path, Path], Any]
        apply_release_retention: Callable[..., list[Path]]
        apply_backup_retention: Callable[..., list[Path]]
        # Pip
        create_venv: Callable[[Path], Awaitable[Any]]
        pip_install_dry_run: Callable[[Path, Path], Awaitable[Any]]
        pip_install: Callable[[Path, Path], Awaitable[Any]]
        compileall: Callable[[Path, Path], Awaitable[Any]]
        smoke_import: Callable[[Path], Awaitable[Any]]
        config_dryrun: Callable[[Path, Path], Awaitable[Any]]
        # Systemd
        systemctl_restart: Callable[[str], Awaitable[bool]]
        # Symlink
        atomic_symlink_flip: Callable[[Path, Path], None]
        # Health
        make_health_checker: Callable[..., HealthChecker]
        # Status
        status_writer_factory: Callable[[], StatusFileWriter]
        # Recovery
        write_pending_marker: Callable[[Path, Path, Path, float], None]
        clear_pending_marker: Callable[[Path | None], None]
        # Trigger
        read_trigger: Callable[[Path, NonceDedupStore], ValidatedTrigger]
        make_dedup_store: Callable[[Path], NonceDedupStore]


    class UpdateRunner:
        def __init__(self, config: UpdateRunnerConfig, primitives: UpdateRunnerPrimitives, clock=time.time):
            self._cfg = config
            self._p = primitives
            self._clock = clock
            self._rollback_count = 0

        async def run(self) -> int:
            # ... state machine as sketched above ...
    ```

    For `write_pending_marker`, create a small helper in runner.py that uses the Phase 43
    PendingMarker schema:

    ```python
    def _write_pending_marker(
        pending_path: Path,
        previous_release: Path,
        target_release: Path,
        created_at: float,
    ) -> None:
        from pv_inverter_proxy.recovery import PendingMarker
        from dataclasses import asdict
        marker = PendingMarker(
            previous_release=str(previous_release),
            target_release=str(target_release),
            created_at=created_at,
            reason="update",
        )
        tmp = pending_path.with_suffix(".marker.tmp")
        tmp.write_text(json.dumps(asdict(marker), indent=2))
        os.replace(tmp, pending_path)
        os.chmod(pending_path, 0o644)
    ```

    (Note: importing recovery.PendingMarker is ALLOWED per trust boundary — schema-only.)

    For `_atomic_symlink_flip`, reuse the Phase 43 pattern:
    ```python
    def _atomic_symlink_flip(current_link: Path, new_target: Path) -> None:
        tmp = current_link.with_name(current_link.name + ".new")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(new_target)
        os.replace(tmp, current_link)
    ```

    Create `tests/test_updater_root_runner.py` with the full fake-primitives test suite.
    Each test constructs an `UpdateRunnerPrimitives` with AsyncMock/MagicMock for the
    callables, asserts the sequence of calls and the final return code.

    For sequence assertions, capture calls via a shared list:
    ```python
    calls = []
    primitives = UpdateRunnerPrimitives(
        is_sha_on_main=async_recorder(calls, "is_sha_on_main", return_value=True),
        ...
    )
    runner = UpdateRunner(config, primitives)
    rc = await runner.run()
    assert rc == 0
    assert [name for name, *_ in calls] == [
        "read_trigger", "is_sha_on_main", "check_disk_space", "git_rev_parse",
        "create_backup", "git_clone_shared", "create_venv", "pip_install_dry_run",
        "git_checkout_detach", "pip_install", "compileall", "smoke_import",
        "config_dryrun", "write_pending_marker", "atomic_symlink_flip",
        "systemctl_restart", "make_health_checker", ...
    ]
    ```

    (Order is flexible within reason, but symlink_flipped MUST come after pending_marker_written and smoke_import/config_dryrun MUST come before symlink flip.)
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_runner.py -x -v</automated>
  </verify>
  <done>
    - UpdateRunner state machine passes all test cases
    - Test suite runs in under 5s (all fakes, no sleep)
    - Sequence assertions enforce: pending_marker_written BEFORE symlink_flipped, smoke_import BEFORE symlink_flipped, rollback called AT MOST ONCE
  </done>
</task>

<task type="auto">
  <name>Task 5: updater_root/__main__.py entry point + systemd units + install.sh extension</name>
  <files>src/pv_inverter_proxy/updater_root/__main__.py, config/pv-inverter-proxy-updater.path, config/pv-inverter-proxy-updater.service, install.sh</files>
  <action>
    Part A — `src/pv_inverter_proxy/updater_root/__main__.py`:

    ```python
    """Entry point for pv-inverter-proxy-updater.service (Phase 45).

    Runs as root via systemd oneshot unit. Wires real primitives into the
    UpdateRunner state machine, executes one update attempt, writes status,
    and exits with a returncode that systemd records in the journal.
    """
    from __future__ import annotations

    import asyncio
    import sys
    import time
    from pathlib import Path

    import aiohttp
    import structlog

    from pv_inverter_proxy.updater_root.runner import (
        UpdateRunner, UpdateRunnerConfig, UpdateRunnerPrimitives,
    )
    from pv_inverter_proxy.updater_root import (
        git_ops, backup, trigger_reader, pip_ops, gpg_verify,
    )
    from pv_inverter_proxy.updater_root.healthcheck import (
        HealthChecker, HealthCheckConfig, check_systemctl_active, systemctl_restart,
    )
    from pv_inverter_proxy.updater_root.status_writer import StatusFileWriter
    from pv_inverter_proxy.releases import check_disk_space
    from pv_inverter_proxy.recovery import PENDING_MARKER_PATH, clear_pending_marker


    def _configure_logging() -> None:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.PrintLoggerFactory(),
        )


    async def _async_main() -> int:
        log = structlog.get_logger(component="updater_root")
        log.info("updater_starting")

        config = UpdateRunnerConfig.default()
        primitives = _make_production_primitives(config)

        runner = UpdateRunner(config, primitives)
        try:
            rc = await runner.run()
        except Exception as e:
            log.critical("updater_unhandled_exception", error=str(e), error_type=type(e).__name__)
            return 1
        log.info("updater_complete", returncode=rc)
        return rc


    def _make_production_primitives(config: UpdateRunnerConfig) -> UpdateRunnerPrimitives:
        def _make_health_checker(expected_commit: str | None = None) -> HealthChecker:
            hc_cfg = HealthCheckConfig()
            async def _session_factory():
                return aiohttp.ClientSession()
            return HealthChecker(
                config=hc_cfg,
                expected_version=None,
                expected_commit=expected_commit,
                session_factory=_session_factory,
            )

        def _status_writer_factory():
            return StatusFileWriter(path=config.status_path)

        return UpdateRunnerPrimitives(
            is_sha_on_main=git_ops.is_sha_on_main,
            git_rev_parse=git_ops.git_rev_parse,
            git_clone_shared=git_ops.git_clone_shared,
            git_checkout_detach=git_ops.git_checkout_detach,
            check_disk_space=check_disk_space,
            create_backup=backup.create_backup,
            apply_release_retention=backup.apply_release_retention,
            apply_backup_retention=backup.apply_backup_retention,
            create_venv=pip_ops.create_venv,
            pip_install_dry_run=pip_ops.pip_install_dry_run,
            pip_install=pip_ops.pip_install,
            compileall=pip_ops.compileall,
            smoke_import=pip_ops.smoke_import,
            config_dryrun=pip_ops.config_dryrun,
            systemctl_restart=systemctl_restart,
            atomic_symlink_flip=_atomic_symlink_flip,
            make_health_checker=_make_health_checker,
            status_writer_factory=_status_writer_factory,
            write_pending_marker=_write_pending_marker,
            clear_pending_marker=clear_pending_marker,
            read_trigger=trigger_reader.read_and_validate_trigger,
            make_dedup_store=lambda p: trigger_reader.NonceDedupStore(p),
        )


    def main() -> int:
        _configure_logging()
        return asyncio.run(_async_main())


    if __name__ == "__main__":
        sys.exit(main())
    ```

    (Move `_atomic_symlink_flip` and `_write_pending_marker` helpers into runner.py or
    a shared `fs_ops.py` so they're reusable from both runner tests and __main__.)

    Part B — `config/pv-inverter-proxy-updater.path`:

    ```ini
    [Unit]
    Description=Watch for pv-inverter-proxy update triggers (Phase 45, EXEC-03)
    # NEVER make this Requires= or PartOf= the main service unit — this unit must
    # outlive main service restarts so the updater_root process is not killed
    # when it restarts the main service.

    [Path]
    PathModified=/etc/pv-inverter-proxy/update-trigger.json
    Unit=pv-inverter-proxy-updater.service

    [Install]
    WantedBy=multi-user.target
    ```

    Part C — `config/pv-inverter-proxy-updater.service`:

    ```ini
    [Unit]
    Description=PV-Inverter-Proxy Privileged Updater (Phase 45)
    After=network-online.target
    # Critical: no Requires= / BindsTo= / PartOf= pv-inverter-proxy.service.
    # If the main service is stopping/restarting, this unit must continue running.

    [Service]
    Type=oneshot
    RemainAfterExit=no
    User=root
    Group=root
    # Use INSTALL_ROOT (symlink to current release) so we always pick up the
    # running venv. This is the one place where we deliberately read the
    # SYMLINKED layout — if a previous update broke the symlink, recovery
    # (Phase 43) has already flipped it back before the main service starts,
    # and this unit activates on the NEXT trigger write from a then-running
    # webapp.
    ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy.updater_root
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier=pv-inverter-proxy-updater
    # Long timeout — a full update can take minutes (pip install, git clone).
    TimeoutStartSec=900
    # No restart — oneshot semantics. If it fails, the next trigger write
    # re-activates via the path unit.

    [Install]
    WantedBy=multi-user.target
    ```

    Part D — install.sh extension:

    After the existing "Step 7: Systemd services (main + recovery)" block, extend it to
    also install the updater units. Replace the existing Step 7 block with:

    ```bash
    # --- Step 7: Systemd services (main + recovery + updater) ---
    info "Installing systemd services..."
    cp "$INSTALL_DIR/config/pv-inverter-proxy.service" /etc/systemd/system/
    cp "$INSTALL_DIR/config/pv-inverter-proxy-recovery.service" /etc/systemd/system/
    cp "$INSTALL_DIR/config/pv-inverter-proxy-updater.path" /etc/systemd/system/
    cp "$INSTALL_DIR/config/pv-inverter-proxy-updater.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl enable pv-inverter-proxy-recovery.service
    systemctl enable pv-inverter-proxy-updater.path
    # Start the path unit immediately so it begins watching on install.
    # The .service it activates is Type=oneshot and won't run until the
    # trigger file is modified by POST /api/update/start.
    systemctl restart pv-inverter-proxy-updater.path || \
        systemctl start pv-inverter-proxy-updater.path
    ok "Services installed and enabled (main + recovery + updater)"
    ```
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -c "from pv_inverter_proxy.updater_root.__main__ import main; print('import_ok')" && bash -n install.sh && echo install_sh_ok && grep -q 'pv-inverter-proxy-updater\.path' install.sh && echo path_unit_installed</automated>
  </verify>
  <done>
    - updater_root/__main__.py importable
    - config/pv-inverter-proxy-updater.path + .service exist
    - install.sh registers both new units
    - grep shows the new units in install.sh
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 6: LXC end-to-end dry-run test — write a trigger, observe full cycle in journal</name>
  <what-built>
    - updater_root orchestrator (runner.py, status_writer.py, healthcheck.py, pip_ops.py, __main__.py)
    - Systemd path+service unit pair installed and enabled
    - install.sh extended
  </what-built>
  <how-to-verify>
    This is the single most important test in Phase 45. We're going to write a trigger
    file as root on the LXC, watch the updater service execute end-to-end, and verify
    the health-check succeeds against the same code the service is already running.
    The target_sha = current HEAD, so no actual code changes — we're testing the
    plumbing, not a version bump. Plan 45-05 will test the version-bump path.

    1. Deploy to LXC and run install.sh:
       ```
       ./deploy.sh
       ssh root@192.168.3.191 'cd /opt/pv-inverter-proxy && bash install.sh'
       ```

    2. Verify units are loaded:
       ```
       ssh root@192.168.3.191 'systemctl list-unit-files | grep pv-inverter-proxy-updater'
       ```
       Expected:
       ```
       pv-inverter-proxy-updater.path     enabled
       pv-inverter-proxy-updater.service  disabled  # oneshot, no Install in [Install] section needed
       ```
       (Disabled is correct — the path unit activates it.)

    3. Verify the path unit is actively watching:
       ```
       ssh root@192.168.3.191 'systemctl status pv-inverter-proxy-updater.path'
       ```
       Expected: "Active: active (waiting)"

    4. Capture current HEAD SHA on the LXC:
       ```
       SHA=$(ssh root@192.168.3.191 'cd /opt/pv-inverter-proxy && git rev-parse HEAD')
       echo "Testing with SHA=$SHA"
       ```

    5. Start a journalctl follow in another terminal:
       ```
       ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy-updater -f --since "1 minute ago"'
       ```

    6. From the dev machine, POST a trigger via the webapp:
       ```
       curl -X POST http://192.168.3.191/api/update/start \
         -H 'Content-Type: application/json' \
         -d "{\"op\":\"update\",\"target_sha\":\"$SHA\"}"
       ```
       Expected: HTTP 202 with update_id.

    7. Observe the journal — you should see these log lines in order within ~60s:
       - `updater_starting`
       - `trigger_received` phase
       - `git_exec ... merge-base --is-ancestor` (is_sha_on_main check) — returns 0
       - `backup_starting`, `backup_complete`
       - `git_exec ... clone --shared` (new release dir)
       - `pip install --dry-run` output (no errors)
       - `pip install -e .` output
       - `compileall` output
       - `smoke_import` OK
       - `config_dryrun` OK
       - `pending_marker_written`
       - `symlink_flipped` — NEW release dir is now current
       - `systemctl restart pv-inverter-proxy.service` issued
       - Main service restart visible in separate journal (the updater is unaffected)
       - `healthcheck` — 3 consecutive oks, stable_ok
       - `updater_complete returncode=0`

    8. Verify main service still works:
       ```
       curl -s http://192.168.3.191/api/health | python3 -m json.tool
       ```
       Expected: status=ok, version=8.0.0, commit matches SHA from step 4.

    9. Verify status file was written:
       ```
       ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/update-status.json'
       ```
       Expected: JSON with `current.phase == "done"`, full history array.

    10. Verify pending marker was cleared (success path):
       ```
       ssh root@192.168.3.191 'ls -la /var/lib/pv-inverter-proxy/update-pending.marker 2>&1 || echo "cleared - OK"'
       ```
       Expected: "cleared - OK".

    11. Verify new release directory exists and symlink points at it:
       ```
       ssh root@192.168.3.191 'ls -la /opt/pv-inverter-proxy-releases/'
       ```
       Expected: two or three release dirs, `current` symlink -> newest.

    12. Verify backup was created:
       ```
       ssh root@192.168.3.191 'ls -la /var/lib/pv-inverter-proxy/backups/'
       ```
       Expected: venv-*.tar.gz, config-*.yaml, pyproject-*.toml all dated now.

    13. Verify retention didn't delete the running release (regression against Phase 43):
       ```
       ssh root@192.168.3.191 'readlink /opt/pv-inverter-proxy-releases/current'
       # Verify target still exists
       ssh root@192.168.3.191 'ls $(readlink /opt/pv-inverter-proxy-releases/current) | head -3'
       ```

    14. Venus OS connectivity check (critical — the main service restarted):
       ```
       ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy --since "2 minutes ago" | grep -i "venus\|modbus" | tail -20'
       ```
       Expected: Modbus server restarts cleanly, Venus OS reconnects. NOTE: maintenance
       mode is NOT implemented yet (Plan 45-05), so a brief Venus OS disconnect IS
       expected here — that's what 45-05 fixes.

    15. Repeat the test with a 2nd POST — verify nonce dedup does NOT short-circuit
       (each webapp call generates a fresh nonce):
       ```
       curl -X POST http://192.168.3.191/api/update/start \
         -H 'Content-Type: application/json' \
         -d "{\"op\":\"update\",\"target_sha\":\"$SHA\"}"
       ```
       Expected: second full cycle runs, journal shows new `updater_starting`, old+new status history present.

    16. Test the "same trigger re-fires" replay protection — copy the existing trigger
       file back onto itself (same nonce):
       ```
       ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/update-trigger.json > /tmp/t && cp /tmp/t /etc/pv-inverter-proxy/update-trigger.json'
       sleep 3
       ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy-updater --since "30 seconds ago" | tail -10'
       ```
       Expected: updater activates, trigger_reader raises NonceReplayError, updater exits
       with returncode!=0, nothing changes on disk, journal shows the dedup rejection.

    If ANY of steps 1-16 fails, STOP and document the specific failure. Do not proceed to
    Plan 45-05 until Task 6 is green.
  </how-to-verify>
  <resume-signal>Type "approved" if all 16 checks pass. If Venus OS disconnect is longer than 15s in step 14, note it — Plan 45-05 will fix it. Other failures need root-cause analysis before proceeding.</resume-signal>
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
| main service → filesystem (trigger) → updater.path → updater.service | File-mediated IPC, root-consumer side validates |
| updater.service → subprocess (git, pip, systemctl) | Root running explicit argv |
| updater.service → HTTP /api/health | Local loopback only |
| updater.service → main service lifecycle | systemctl restart issued from outside the dying cgroup |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-45-04-01 | Denial of service | Rollback infinite loop | mitigate | HEALTH-08: `_rollback_count` is checked; `_rollback` is called at most once per runner.run() invocation. Second failure writes rollback_failed and exits. Unit test test_max_one_rollback enforces. |
| T-45-04-02 | Elevation of privilege | Updater self-restart-kill | mitigate | updater.service has NO Requires=/PartOf=/BindsTo=pv-inverter-proxy.service. The updater runs in its own cgroup and survives the main service restart. Explicitly documented in the unit file header comment. |
| T-45-04-03 | Tampering | Symlink flip partial state | mitigate | _atomic_symlink_flip uses tmp + os.replace — POSIX-atomic; either old or new symlink exists, never neither. Pattern mirrors Phase 43 recovery._atomic_symlink_flip. |
| T-45-04-04 | Denial of service | Main service bind fails after restart (address in use) | partial | Plan 45-05 verifies and enforces SO_REUSEADDR on the Modbus server bind. For Plan 45-04 testing, any bind failure during Task 6 is documented and escalated to 45-05 as a hard dependency. |
| T-45-04-05 | Repudiation | Unknown whether update happened | mitigate | Status file phase history is append-only. journalctl -u pv-inverter-proxy-updater is the primary audit trail. Nonce is logged on trigger_received so a trigger can always be traced to a specific webapp call. |
| T-45-04-06 | Tampering | Recovery PENDING marker race | mitigate | Pending marker written BEFORE symlink_flipped phase. If the updater dies between pending-write and symlink-flip, recovery.py on next boot sees a PENDING marker with previous==target (no-op), and clears it. If it dies AFTER symlink flip, recovery flips back on next boot. Test test_pending_marker_written_before_flip enforces sequence. |
| T-45-04-07 | Information disclosure | pip install stdout may leak credentials | accept | pyproject.toml is expected to have no auth-gated deps. If a future release adds a private PyPI index, the credentials would be in pip.conf (outside the logged output). Structured logging does not capture pip stdout verbatim; only success/fail is logged. |
| T-45-04-08 | Denial of service | systemctl restart hangs | mitigate | Main service unit has TimeoutStopSec=15 (Phase 43) and KillMode=mixed. systemctl restart returns within 15s or systemd sends SIGKILL. HealthChecker's 60s hard timeout bounds the updater wait. |
| T-45-04-09 | Tampering | GitHub API tag->SHA mapping spoofed | partial | EXEC-04 is_sha_on_main is the security root of trust: even if GitHub API returned a malicious SHA, it would need to be reachable from the locally-cached origin/main refs. git_fetch on every update attempt refreshes these refs, but an attacker would need to compromise git fetch AND the API call simultaneously. v8.0 accepted residual risk, v8.1+ adds GPG mitigation. |
| T-45-04-10 | Elevation of privilege | HealthChecker returns success on wrong version | mitigate | If a bad update deploys the wrong code but the old binary is still running (e.g., symlink flip succeeded but restart silently ran the old venv), HealthChecker's expected_commit parameter detects version_mismatch and forces rollback. Test test_healthcheck_version_mismatch_immediate_fail enforces. |
</threat_model>

<verification>
## Validation Strategy

| REQ | Test Type | Evidence |
|-----|-----------|----------|
| EXEC-03 | LXC smoke (Task 6 steps 2-3) | path unit active (waiting), service enabled |
| EXEC-06 | LXC smoke (Task 6 step 11) | New release dir exists with isolated .venv |
| EXEC-07 | Unit (runner::test_pip_dryrun_fail_no_flip) + LXC smoke (step 7) | Dry-run called BEFORE real install |
| EXEC-08 | Unit (runner::test_smoke_import_fail_no_flip, test_config_dryrun_fail_no_flip) + LXC smoke | Both checks fail-fast before symlink |
| EXEC-09 | Unit (pip_ops::test_compileall_*) + LXC smoke (step 7) | compileall in journal |
| RESTART-04 | Unit (runner::test_pending_marker_written_before_flip) + LXC smoke (step 7,11) | Atomic flip + restart sequence |
| RESTART-05 | LXC smoke (step 8) | Updater survives main service restart and reports success |
| HEALTH-05 | Unit (healthcheck::test_healthcheck_all_ok_first_try_still_waits_for_consecutive) | 3 consecutive ok required |
| HEALTH-06 | Unit (healthcheck tests: systemctl_failed, version_mismatch, no_healthy_flag) | All rollback triggers |
| HEALTH-07 | Unit (runner::test_healthcheck_fail_triggers_rollback) | Rollback mechanism |
| HEALTH-08 | Unit (runner::test_max_one_rollback, test_healthcheck_fail_second_healthcheck_also_fails_rollback_failed) | Single-rollback cap |
| HEALTH-09 | LXC smoke (step 9) | status.json with phase progression |

## Failure Rollback

This plan has the highest blast radius of Phase 45. If Task 6 fails:

1. **If the test trigger leaves the LXC in a broken state:**
   - Phase 43 boot-time recovery should undo the symlink flip on next reboot
   - If recovery fails: SSH and manually `ln -sfn <previous release dir> /opt/pv-inverter-proxy-releases/current`, `systemctl restart pv-inverter-proxy`
   - `git revert` the Plan 45-04 commit in the dev repo

2. **If the updater is stuck in a loop or writing garbage:**
   - `systemctl disable --now pv-inverter-proxy-updater.path`
   - Inspect `/etc/pv-inverter-proxy/update-status.json` and delete if corrupt
   - Delete `/var/lib/pv-inverter-proxy/processed-nonces.json` to clear dedup state
   - `git revert HEAD`, redeploy

3. **If the main service itself is broken post-test:**
   - `journalctl -u pv-inverter-proxy-recovery -b` — check if boot-time recovery ran
   - Manually flip symlink back, restart
   - Root-cause the bad release before re-attempting

The existence of Phase 43 recovery is the safety net that makes this plan survivable.
</verification>

<success_criteria>
- All unit tests pass (status_writer, pip_ops, healthcheck, runner, ~40 tests total)
- Systemd path+service units installed on LXC, path is `active (waiting)`
- Task 6 step 7 journal shows full phase sequence in order, no failures
- /api/health post-update returns status=ok with matching commit
- /etc/pv-inverter-proxy/update-status.json shows current.phase=done
- No pending marker left behind on success
- Nonce replay protection verified (step 16)
- Venus OS reconnects after the transient disconnect (Plan 45-05 will minimize the gap)
- Phase 45 top-line success criterion 1, 2 satisfied (trigger -> full cycle observable in journal)
</success_criteria>

<output>
After completion, create `.planning/phases/45-privileged-updater-service/45-04-SUMMARY.md` capturing:
- Full journal excerpt from Task 6 step 7 (the phase progression)
- Final status.json from step 9
- Measured update duration (time from POST /api/update/start to updater_complete)
- Any Venus OS disconnect duration (document as baseline for Plan 45-05 to improve)
- Confirmation that Task 6 step 16 nonce replay was rejected
- Output of `systemctl status pv-inverter-proxy-updater.path`
</output>
