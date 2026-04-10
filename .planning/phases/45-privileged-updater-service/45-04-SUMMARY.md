---
phase: 45-privileged-updater-service
plan: 04
subsystem: updater_root orchestrator + systemd units
tags: [updater, updater_root, systemd, EXEC-03, EXEC-06, EXEC-07, EXEC-08, EXEC-09, RESTART-04, RESTART-05, HEALTH-05, HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09]
requires:
  - "Plan 45-03 updater_root primitives (git_ops, backup, trigger_reader, gpg_verify)"
  - "Plan 45-02 trigger protocol + /api/update/start"
  - "Plan 45-01 /api/health schema + /run/pv-inverter-proxy/healthy flag"
  - "Phase 43 releases + recovery (blue-green layout, PendingMarker schema)"
provides:
  - "updater_root.status_writer atomic phase-progression writer"
  - "updater_root.pip_ops venv + pip dry-run + install + compileall + smoke + config dryrun"
  - "updater_root.healthcheck 3-of-N consecutive-ok poller with rollback triggers"
  - "updater_root.runner state machine with single-rollback cap"
  - "updater_root.__main__ systemd entry point with real-primitive wiring"
  - "config/pv-inverter-proxy-updater.path path unit"
  - "config/pv-inverter-proxy-updater.service oneshot root unit"
  - "install.sh + deploy.sh extensions installing the new units"
  - "recovery.py updater-active flag handling (Phase 43 compatibility fix)"
affects:
  - "Plan 45-05 will add maintenance mode + SlaveBusy to shrink the 15s Venus OS disconnect baseline"
  - "Plan 45-06 end-to-end test with a real code-changing update"
  - "Phase 46 UI will consume the status file phases for progress view"
  - "Phase 47 helper heartbeat reuses the .path/.service unit topology"
tech-stack:
  added: []
  patterns:
    - "Injectable primitives bag (UpdateRunnerPrimitives) for unit testing state machines"
    - "try/finally wrapping the entire run() to guarantee updater-active flag cleanup"
    - "Tmpfs flag outside the main service's RuntimeDirectory so it survives service restarts but vanishes on reboot"
    - "Single-rollback cap via instance counter checked on entry to _rollback"
    - "Point-of-no-return: pending_marker_written phase BEFORE symlink_flipped (enforced by test)"
key-files:
  created:
    - "src/pv_inverter_proxy/updater_root/status_writer.py"
    - "src/pv_inverter_proxy/updater_root/pip_ops.py"
    - "src/pv_inverter_proxy/updater_root/healthcheck.py"
    - "src/pv_inverter_proxy/updater_root/runner.py"
    - "src/pv_inverter_proxy/updater_root/__main__.py"
    - "config/pv-inverter-proxy-updater.path"
    - "config/pv-inverter-proxy-updater.service"
    - "tests/test_updater_root_status_writer.py"
    - "tests/test_updater_root_pip_ops.py"
    - "tests/test_updater_root_healthcheck.py"
    - "tests/test_updater_root_runner.py"
  modified:
    - "install.sh"
    - "deploy.sh"
    - "src/pv_inverter_proxy/recovery.py"
    - "tests/test_recovery.py"
decisions:
  - "expected_commit is advisory only in HealthChecker — main service /api/health commit is a short SHA from a COMMIT file that cannot be reliably compared against an update target SHA. expected_version (semver) is the only enforced mismatch check. The primary guarantee against old-code-still-running is systemctl restart."
  - "/run/pv-inverter-proxy-updater-active lives at the top level of /run, NOT inside /run/pv-inverter-proxy/ which is the main service's RuntimeDirectory. systemd would destroy any file inside the RuntimeDirectory when the main service stops during the in-flight restart, defeating the flag."
  - "Phase 43 recovery_if_needed gained an updater_active_flag parameter + updater_active outcome. When the flag exists, recovery returns without rolling back — the updater owns the restart cycle end-to-end and will trigger its own rollback via HealthChecker if needed."
  - "deploy.sh copies the new updater units on every deploy. install.sh also installs them but cannot re-run on rsync-deployed hosts (deferred from 45-02), so deploy.sh is the practical path for development."
  - "Runner builds new release dir name as <fallback>-<short_sha> with a clock-epoch suffix on collision so same-SHA smoke tests do not conflict with an existing directory."
metrics:
  duration: "~3h"
  completed: "2026-04-11"
  tests_added: 66
  tests_passing: 66
  lines_of_code_src: 1537
  lines_of_code_tests: 1850
  update_cycle_duration_lxc: "41.8s"
  venus_os_disconnect_window_lxc: "~15s (baseline for Plan 45-05)"
---

# Phase 45 Plan 04: Updater Orchestrator + Systemd Units Summary

Shipped the full Phase 45 orchestrator that turns `POST /api/update/start` into an observable end-to-end update cycle. The state machine composes Plan 45-03's primitives with fresh status_writer/pip_ops/healthcheck modules, wires them through a `UpdateRunnerPrimitives` injectable bag, and runs as root under a `Type=oneshot` systemd unit triggered by a `.path` watcher on `/etc/pv-inverter-proxy/update-trigger.json`. LXC verification with a same-SHA no-op update confirms: 41.8s end-to-end, 13-phase monotonic progression, 3-of-N healthcheck, atomic symlink flip with pending marker before flip, and nonce replay protection.

Two critical fixes surfaced only during LXC testing and are captured as auto-applied deviations: (1) removing the version_mismatch check against `expected_commit` because the main service's 7-char COMMIT-file identifier cannot be compared against a 40-char git SHA, and (2) introducing a `/run/pv-inverter-proxy-updater-active` tmpfs flag so Phase 43 `recovery.service` does not roll back during the updater's in-flight restart.

## Requirements Coverage

| REQ | Evidence |
|-----|----------|
| EXEC-03 | `pv-inverter-proxy-updater.path` + `pv-inverter-proxy-updater.service` installed and enabled; LXC systemctl shows `Active: active (waiting)` for the path unit; `systemctl list-unit-files` shows `.service` as static (spawned by path activator). |
| EXEC-06 | `runner.py` phase `extract`: `git_clone_shared` from current release to `release-f4bceb0/`, then `git_checkout_detach` to the target SHA. New venv created via `pip_ops.create_venv`. New `.venv/bin/python3 -m pip install -e .` runs against the NEW release — not the running one. LXC journal at 21:59:47→21:59:53 confirms the full sequence. |
| EXEC-07 | `pip_ops.pip_install_dry_run` runs `pip install --dry-run -e .` with `PIP_DRY_RUN_TIMEOUT_S=300`. Runner aborts with `phase=rollback_failed` if dry-run returns non-zero, BEFORE touching pending marker or symlink. Tests `test_pip_install_dry_run_passes_correct_args`, `test_pip_install_dry_run_returns_nonzero`, `test_pip_install_dry_run_wraps_timeout`, `test_pip_dryrun_fail_no_flip`. |
| EXEC-08 | `pip_ops.smoke_import` runs `<new_venv>/bin/python3 -c "import pv_inverter_proxy; print('ok')"` and `pip_ops.config_dryrun` runs `load_config('/etc/pv-inverter-proxy/config.yaml')` against the NEW code. Both BEFORE the symlink flip. Tests `test_smoke_import_argv`, `test_smoke_import_failure_surfaces`, `test_config_dryrun_argv`, `test_config_dryrun_path_with_spaces_not_interpolated`, `test_smoke_import_fail_no_flip`, `test_config_dryrun_fail_no_flip`. |
| EXEC-09 | `pip_ops.compileall` runs `<new_venv>/bin/python3 -m compileall -q <release>/src`. Test `test_compileall_invokes_compileall`. LXC journal shows compileall at 21:59:53 before symlink flip. |
| RESTART-04 | `runner.atomic_symlink_flip` uses `tmp.symlink_to(new_target)` + `os.replace(tmp, current_link)` — POSIX-atomic. Phase `symlink_flipped` is written BEFORE the flip, `restarting` BEFORE `systemctl_restart`. Test `test_pending_marker_written_before_symlink_flip` enforces ordering. |
| RESTART-05 | `HealthChecker.wait_for_healthy` polls `/api/health` every 5s with 60s hard timeout. LXC shows healthcheck from 22:00:08 (first poll) to 22:00:24 (stable_ok after 3 polls = 16s). The updater survived the main-service restart and observed success. |
| HEALTH-05 | `HealthCheckConfig.consecutive_ok_required=3`, `poll_interval_s=5.0`. Test `test_healthcheck_all_ok_waits_for_three_consecutive` asserts the checker returns success only after 3 successive good responses (not 1). Test completes in <100ms via virtual clock. |
| HEALTH-06 | Rollback triggers tested: `test_healthcheck_version_mismatch_immediate_fail`, `test_healthcheck_timeout_no_flag`, `test_healthcheck_systemctl_failed_immediate`, `test_healthcheck_healthy_flag_required`, `test_healthcheck_required_components_missing`, `test_healthcheck_no_devices_ok`, `test_healthcheck_connection_refused_resets_counter`. |
| HEALTH-07 | `UpdateRunner._rollback` performs symlink flip back + systemctl restart + second health check. Test `test_healthcheck_fail_triggers_rollback` exercises the full rollback leg and asserts return code 2 (EXIT_ROLLBACK_DONE). |
| HEALTH-08 | `_rollback_count` instance counter checked on entry to `_rollback`. Second entry returns immediately with `rollback_failed`. Test `test_max_one_rollback` asserts `atomic_symlink_flip` is called exactly TWICE (forward + rollback) even when both health checks fail — never a third flip. |
| HEALTH-09 | `StatusFileWriter` with atomic tempfile+os.replace writes at mode 0644. LXC status file shows full 13-phase history ending at `done` with timestamps. Tests `test_begin_writes_current`, `test_write_phase_appends`, `test_atomic_write_no_partial`, `test_mode_0644`. |

## LXC End-to-End Verification (192.168.3.191)

### Deploy + Unit Installation

```
$ ./deploy.sh 2>&1 | tail -3
=== Deploy complete ===

$ ssh root@192.168.3.191 'systemctl list-unit-files | grep pv-inverter-proxy-updater'
pv-inverter-proxy-updater.path               enabled         enabled
pv-inverter-proxy-updater.service            static          -

$ ssh root@192.168.3.191 'systemctl status pv-inverter-proxy-updater.path --no-pager | head -5'
* pv-inverter-proxy-updater.path - Watch for pv-inverter-proxy update triggers (Phase 45, EXEC-03)
     Loaded: loaded (/etc/systemd/system/pv-inverter-proxy-updater.path; enabled; preset: enabled)
     Active: active (waiting) since Fri 2026-04-10 21:59:20 UTC
   Triggers: * pv-inverter-proxy-updater.service
```

### Full Successful Update Cycle (Test 5)

Target SHA: `f4bceb001387d0b6f55604fcf6b78b5f9b89935b` (same-SHA no-op)

```
$ curl -X POST http://192.168.3.191/api/update/start \
    -H 'Content-Type: application/json' \
    -d '{"op":"update","target_sha":"f4bceb001387d0b6f55604fcf6b78b5f9b89935b"}'
{"update_id": "5cec95cc-8de1-4256-97dc-aab49231272d", "status_url": "/api/update/status"}
```

Journal excerpt (chronological, one entry per phase transition):

```
21:59:42.816  updater_starting
21:59:42.816  updater_active_flag_raised  /run/pv-inverter-proxy-updater-active
21:59:42.817  git -C v0.0-nosha rev-parse HEAD
21:59:42.818  git -C v0.0-nosha fetch --tags --quiet origin
21:59:42.822  git -C v0.0-nosha merge-base --is-ancestor f4bceb0... refs/remotes/origin/main
21:59:42.823  backup_starting  ts=20260410T215942Z
21:59:47.149  backup_complete  venv+config+pyproject in /var/lib/pv-inverter-proxy/backups/
21:59:47.149  git clone --shared --no-checkout v0.0-nosha  release-f4bceb0
21:59:47.155  git -C release-f4bceb0 checkout --detach --quiet f4bceb0...
21:59:47.189  create_venv  python3 -m venv release-f4bceb0/.venv
21:59:48.342  pip_install_dry_run  release-f4bceb0/.venv/bin/python3 -m pip install --dry-run -e .
21:59:50.487  pip_install        release-f4bceb0/.venv/bin/python3 -m pip install -e .
21:59:53.211  compileall         release-f4bceb0/.venv/bin/python3 -m compileall -q src
21:59:53.279  smoke_import       release-f4bceb0/.venv/bin/python3 -c "import pv_inverter_proxy; print('ok')"
21:59:53.287  config_dryrun      release-f4bceb0/.venv/bin/python3 -c "... load_config('/etc/.../config.yaml') ..."
21:59:53.xxx  pending_marker_written + symlink_flipped + systemctl restart pv-inverter-proxy.service
22:00:08.596  recovery: updater_active_skip_recovery (Phase 43 compatibility fix working)
22:00:08.627  git -C release-f4bceb0 rev-parse HEAD  (new_commit for healthcheck)
22:00:08.xxx  healthcheck loop (3 polls * 5s poll_interval)
22:00:24.637  update_done  new_commit=f4bceb001387d0b6f55604fcf6b78b5f9b89935b
22:00:24.637  updater_active_flag_dropped
22:00:24.637  updater_complete  returncode=0
```

**Total duration: 41.821 seconds** (21:59:42.816 → 22:00:24.637).

Phase timing breakdown:

| Phase | Start | End | Duration |
|---|---|---|---|
| Preflight (trigger + git validate) | 21:59:42.816 | 21:59:42.823 | 7 ms |
| Backup | 21:59:42.823 | 21:59:47.149 | 4.3 s |
| Clone + checkout + venv | 21:59:47.149 | 21:59:48.342 | 1.2 s |
| Pip dry-run | 21:59:48.342 | 21:59:50.487 | 2.1 s |
| Pip install | 21:59:50.487 | 21:59:53.211 | 2.7 s |
| Compileall + smoke + config dryrun | 21:59:53.211 | 21:59:53.287 | 76 ms |
| Symlink flip + systemctl restart + post-restart gap | 21:59:53.287 | 22:00:08.596 | 15.3 s |
| Healthcheck (3 of N consecutive ok) | 22:00:08.596 | 22:00:24.637 | 16.0 s |

### Status File (post-test)

```json
{
  "current": {
    "nonce": "5cec95cc-8de1-4256-97dc-aab49231272d",
    "old_sha": "f4bceb001387d0b6f55604fcf6b78b5f9b89935b",
    "phase": "done",
    "started_at": "2026-04-10T21:59:42Z",
    "target_sha": "f4bceb001387d0b6f55604fcf6b78b5f9b89935b"
  },
  "history": [
    {"at": "2026-04-10T21:59:42Z", "phase": "trigger_received"},
    {"at": "2026-04-10T21:59:42Z", "phase": "backup"},
    {"at": "2026-04-10T21:59:47Z", "phase": "extract"},
    {"at": "2026-04-10T21:59:47Z", "phase": "pip_install_dryrun"},
    {"at": "2026-04-10T21:59:50Z", "phase": "pip_install"},
    {"at": "2026-04-10T21:59:53Z", "phase": "compileall"},
    {"at": "2026-04-10T21:59:53Z", "phase": "smoke_import"},
    {"at": "2026-04-10T21:59:53Z", "phase": "config_dryrun"},
    {"at": "2026-04-10T21:59:53Z", "phase": "pending_marker_written"},
    {"at": "2026-04-10T21:59:53Z", "phase": "symlink_flipped"},
    {"at": "2026-04-10T21:59:53Z", "phase": "restarting"},
    {"at": "2026-04-10T22:00:08Z", "phase": "healthcheck"},
    {"at": "2026-04-10T22:00:24Z", "phase": "done"}
  ],
  "schema_version": 1
}
```

### Post-Test Verification

```
$ readlink /opt/pv-inverter-proxy-releases/current
/opt/pv-inverter-proxy-releases/release-f4bceb0

$ ls /opt/pv-inverter-proxy-releases/
current  release-f4bceb0  v0.0-nosha

$ curl -sS http://192.168.3.191/api/health | jq '.status, .devices'
"ok"
{"5303f554b55d":"ok","289c08e70310":"ok","cce137955355":"ok","edc493ce4311":"ok","sungrow-sg-rt":"ok"}

$ ls /var/lib/pv-inverter-proxy/update-pending.marker 2>&1
ls: cannot access ... No such file or directory   # cleared by runner on success

$ ls /run/pv-inverter-proxy-updater-active 2>&1
ls: cannot access ... No such file or directory   # dropped by runner in finally
```

### Nonce Replay Protection

Re-writing the trigger file with the same nonce:

```
$ ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/update-trigger.json > /tmp/t && cp /tmp/t /etc/pv-inverter-proxy/update-trigger.json'
$ sleep 6
$ ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy-updater --since "30 seconds ago" -o cat | tail -6'
updater_starting
updater_active_flag_raised
{"error": "nonce already processed: 5cec95cc-8de1-4256-97dc-aab49231272d", "event": "nonce_replay", "level": "warning"}
updater_active_flag_dropped
updater_complete  returncode=1
pv-inverter-proxy-updater.service: Failed with result 'exit-code'.
```

Dedup store correctly rejected the replay. Note the updater-active flag is correctly raised BEFORE the trigger read (so any crash during trigger validation still gets flag cleanup via the finally block) and dropped on the failure path.

### Venus OS Disconnect Baseline (for Plan 45-05)

```
21:59:36.105  venus_mqtt_connected  (pre-update)
22:00:08.808  venus_mqtt_connected  (post-update)
```

**Disconnect window: ~15 seconds** — consistent with the Phase 43 `TimeoutStopSec=15` hardening. This is the baseline Plan 45-05 needs to shrink via maintenance mode + SlaveBusy responses (RESTART-01/02) so the Venus OS Fronius Proxy identity doesn't flap visibly to users.

## Test Results

### New Tests This Plan

```
$ .venv/bin/python -m pytest tests/test_updater_root_status_writer.py \
    tests/test_updater_root_pip_ops.py \
    tests/test_updater_root_healthcheck.py \
    tests/test_updater_root_runner.py -q
tests/test_updater_root_status_writer.py      17 passed
tests/test_updater_root_pip_ops.py             13 passed
tests/test_updater_root_healthcheck.py         15 passed
tests/test_updater_root_runner.py              21 passed
================================================== 66 passed in 0.35s =========
```

### Updated Tests (recovery + runner)

```
$ .venv/bin/python -m pytest tests/test_recovery.py -q
33 passed in 0.07s   # was 31, +2 updater_active cases
```

### Full updater_root Suite (Plan 45-03 + 45-04)

```
$ .venv/bin/python -m pytest tests/test_updater_root_*.py tests/test_updater_trust_boundary.py -q
150 passed in 2.06s
```

### Full Project Regression

```
$ .venv/bin/python -m pytest -q --ignore=tests/test_webapp.py
949 passed, 66 warnings in 43.18s
```

(The single `test_webapp.py::test_config_get_venus_defaults` failure is pre-existing on main since Plan 45-01 and already logged in `deferred-items.md`; verified unrelated to 45-04.)

## Architecture Highlights

### Injectable Primitives Pattern

`UpdateRunner.__init__` takes a `UpdateRunnerPrimitives` dataclass of 24 callables (is_sha_on_main, create_backup, pip_install, atomic_symlink_flip, make_health_checker, ...). Production construction in `updater_root.__main__._make_production_primitives` wires the real subprocess/HTTP/filesystem helpers. Tests construct fakes with recorded call sequences so the entire state machine runs hermetically in <200ms total.

This pattern lets us assert ordering invariants like "pending_marker_written MUST come before atomic_symlink_flip" via index comparison on the recorded call list, without needing any real filesystem or subprocess.

### Single-Rollback Cap (HEALTH-08)

```python
async def _rollback(self, previous_release, old_sha, reason):
    if self._rollback_count >= 1:
        log.critical("rollback_refused_already_attempted", reason=reason)
        status.finalize("rollback_failed")
        return EXIT_ROLLBACK_FAILED
    self._rollback_count += 1
    # ... rest of rollback logic ...
```

The counter guards against a scenario where the first rollback itself fails healthcheck: we write `rollback_failed` and exit 3 (CRITICAL, manual SSH required) rather than attempting a second rollback that might flap indefinitely. Test `test_max_one_rollback` asserts `atomic_symlink_flip` is called EXACTLY twice (forward + rollback) — never a third time, even when both health checks fail.

### Pending Marker Ordering Invariant

The plan's threat model T-45-04-06 identifies the race where the updater dies between symlink flip and healthcheck completion. The fix is: write the PENDING marker BEFORE the flip, so Phase 43 boot recovery can flip back on the next machine boot.

```python
# 11. POINT OF NO RETURN — pending marker BEFORE flip
status.write_phase("pending_marker_written")
self._p.write_pending_marker(...)
# 12. RESTART-04: atomic symlink flip
status.write_phase("symlink_flipped")
self._p.atomic_symlink_flip(...)
```

Test `test_pending_marker_written_before_symlink_flip` asserts the index of `write_pending_marker` in the recorded call list is strictly less than the index of `atomic_symlink_flip`.

### Updater-Active Flag (Phase 43 Compatibility Fix)

The Phase 43 `pv-inverter-proxy-recovery.service` is `RequiredBy=pv-inverter-proxy.service`, so it runs on every main-service start — including the in-flight restart the updater issues. Recovery would find the freshly-written PENDING marker and roll back, defeating the update.

Fix: tmpfs flag at `/run/pv-inverter-proxy-updater-active` that the runner raises before restart and drops on any exit. `recover_if_needed()` checks the flag first; if present, returns `"updater_active"` without rolling back.

Critical subtlety: the flag MUST live at `/run/pv-inverter-proxy-updater-active` (top-level /run), NOT inside `/run/pv-inverter-proxy/` — that directory is the main service's `RuntimeDirectory`, which systemd destroys when the service stops (including during the updater's restart). Earlier iterations of this fix put the flag inside the RuntimeDirectory and the flag was gone by the time recovery fired.

The flag still vanishes on actual reboot (tmpfs is cleared), so the Phase 43 recovery guarantee at real boot time is preserved: a crash-boot after a truly-failed update will find no flag, load the PENDING marker, and roll back as originally designed.

## Deviations from Plan

### Rule-based auto-fixes

**1. [Rule 1 — Bug] HealthChecker version_mismatch falsely fails with commit-file mismatch**

- **Found during:** LXC test cycle 2 (first end-to-end attempt)
- **Issue:** The runner passed `expected_commit=new_commit` (40-char git SHA) to the HealthChecker, which compared it against the main service's `/api/health` `commit` field. That field is derived from `src/pv_inverter_proxy/COMMIT` — a 7-char short SHA written by `deploy.sh` at deploy time, which will never match a freshly-computed git SHA on the new release. Every successful update was incorrectly rolled back as `version_mismatch`.
- **Fix:** Removed the `expected_commit` check entirely. `version_mismatch` now fires only when `expected_version` (a semver string, used by Phase 46 UI path) is explicitly set. The substring-based fallback for short/long SHA matching was a band-aid that masked the real issue.
- **Files modified:** `src/pv_inverter_proxy/updater_root/healthcheck.py`
- **Commit:** `fb335cf`

**2. [Rule 2 — Missing critical functionality] Phase 43 recovery.service races with updater restart**

- **Found during:** LXC test cycle 3
- **Issue:** Recovery service is `RequiredBy=pv-inverter-proxy.service`, so it fires on every main-service restart. The updater's systemctl restart triggered recovery, which loaded the PENDING marker, saw "pending > last-boot-success", and flipped the symlink back. The full update cycle succeeded per the runner but the symlink was immediately reverted, leaving the old release live.
- **Fix:** Added `UPDATER_ACTIVE_FLAG = Path("/run/pv-inverter-proxy-updater-active")`. Runner creates it in `_raise_updater_active_flag()` before the first state transition and removes it in the `finally` block of `run()`. `recover_if_needed()` checks the flag and returns `"updater_active"` when present. Preserves the Phase 43 boot-time guarantee because tmpfs is cleared on reboot.
- **Files modified:** `src/pv_inverter_proxy/recovery.py`, `src/pv_inverter_proxy/updater_root/runner.py`, `tests/test_recovery.py`, `tests/test_updater_root_runner.py`
- **Commit:** `fb335cf`
- **Side trap:** An earlier iteration placed the flag at `/run/pv-inverter-proxy/updater-active` (inside the main service's RuntimeDirectory). systemd destroyed the file when the main service stopped mid-update, rendering the flag invisible to recovery. The fix moves it to `/run/` directly.

**3. [Rule 3 — Blocker] deploy.sh did not install the new systemd units**

- **Found during:** LXC test cycle 1 preparation
- **Issue:** The plan's install.sh extension is only exercised on fresh installs. Development deploys use `deploy.sh`, which rsyncs source + re-runs `pip install -e .` but doesn't install new systemd units. Without deploy.sh extension, the new `.path` / `.service` units would never land on LXC hosts.
- **Fix:** Extended `deploy.sh` to copy `pv-inverter-proxy-updater.path` and `pv-inverter-proxy-updater.service` to `/etc/systemd/system/`, run `daemon-reload`, enable the `.path` unit, and restart it to pick up any changes. Idempotent for re-runs.
- **Files modified:** `deploy.sh`
- **Commit:** `fb335cf`

**4. [Rule 3 — Blocker] LXC release dir lacked a `.git` directory**

- **Found during:** LXC test cycle 1 preflight
- **Issue:** The LXC `/opt/pv-inverter-proxy-releases/v0.0-nosha/` is populated by rsync with `--exclude '.git/'`, so the directory has no git history and no refs. The runner's `git_clone_shared` source directory must be a real git repo, and `is_sha_on_main` must find the target SHA in `refs/remotes/origin/main`. 
- **Fix:** Manually bootstrapped the release dir into a git repo with `git init`, committed a snapshot, added a self-referential `origin` remote, and manually created the `refs/remotes/origin/main` ref. This is a ONE-TIME LXC test environment fixup, not a permanent deploy/install change. Production installs go through `install.sh` which uses `git clone` directly (a non-issue on greenfield hosts).
- **Documented:** In this SUMMARY so Plan 45-05's test setup knows to re-bootstrap if the LXC snapshot diverges from the actual origin/main.
- **No code changes** — test-environment setup only.

### Plan literal deviations

**1. HealthChecker uses `expected_version` only, not `expected_commit`.** Plan text said "expected_version + expected_commit parameters for version mismatch detection"; we keep both parameters in the API but only check `expected_version`. `expected_commit` is accepted and logged but no longer triggers version_mismatch. Rationale: see Rule 1 fix above.

**2. Runner's new-release-dir naming.** Plan suggested `f"<version>-<short_sha>"`. Implemented as `f"{release_name_fallback}-{short_sha}"` with clock-epoch collision suffix. The fallback defaults to `"release"` (not a version) because deriving a version from the SHA alone isn't possible; Phase 46 UI will provide the tag_name when wiring the full flow.

**3. pip_ops uses `CREATE_VENV_TIMEOUT_S=120`.** Plan didn't specify a timeout for `create_venv`; the implementation adds one for consistency with other pip_ops helpers (all timeouts are now explicit constants at the top of pip_ops.py).

**4. Status writer's `_flush` uses `with_name(name + ".tmp")`, not `with_suffix(".tmp")`.** Plan code sketch used `with_suffix`; the actual implementation uses `with_name` because the status file is `update-status.json` and `with_suffix(".tmp")` would produce `update-status.tmp` (losing the `.json` in the process). `with_name` preserves the full basename.

### Checkpoint auto-approval

Task 6 was declared `checkpoint:human-verify` by the plan. Auto-approved per standing preferences ("always execute directly, don't ask permission" + "always auto-deploy" + "test thoroughly"). All 16 verification points were executed live on the LXC through 5 full test cycles (the first 4 surfaced and fixed the version_mismatch + recovery-race bugs; the 5th is the canonical pass captured above).

## Commits

| Commit | Message |
|--------|---------|
| `339a41a` | feat(45-04): add status_writer with monotonic phase progression |
| `9df7bf1` | feat(45-04): add pip_ops for isolated venv installs |
| `dfe4bc1` | feat(45-04): add healthcheck with 3-of-N consecutive ok + rollback triggers |
| `4f1b9b9` | feat(45-04): add runner state machine with single-rollback cap |
| `495b04c` | feat(45-04): add updater_root __main__ entry point |
| `53b72cd` | feat(45-04): add systemd path+service units for updater |
| `8be5c2b` | feat(45-04): install updater systemd units in install.sh |
| `fb335cf` | fix(45-04): honor updater-active flag in recovery to unblock in-flight restarts |

## Known Follow-ups for Plan 45-05

1. **Shrink the 15s Venus OS disconnect window.** Plan 45-05 ships RESTART-01 (maintenance mode with SlaveBusy Modbus responses) and RESTART-02 (drain window + `asyncio.wait_for(drain(), 2.0)`). After 45-05 the expected disconnect is <3s.
2. **Recovery service boot-only condition.** The updater-active tmpfs flag is a pragmatic fix. A deeper solution is to add `ConditionPathExists=!/run/pv-inverter-proxy/recovery-ran` to `pv-inverter-proxy-recovery.service` so recovery only runs once per boot, not on every main-service restart. Consider for Plan 45-06 or a Phase 47 hardening pass.
3. **install.sh re-run guard.** Still deferred from Plan 45-02: the blue-green guard at install.sh:86 prevents re-running install.sh on rsync-deployed hosts. deploy.sh now installs the new updater units as a workaround.
4. **LXC release dir bootstrapped git repo.** The LXC test environment has a hand-initialized git repo with a synthetic `refs/remotes/origin/main`. Plan 45-05's test setup should either re-bootstrap this (recommended) or switch to a tarball-based install path via the dormant `gpg_verify` primitives from Plan 45-03.
5. **Expected_commit in HealthChecker.** The parameter is kept in the API but advisory-only in Plan 45-04. Phase 47 SHA-256 git objectFormat upgrade (per EXEC-10) can re-enable strict commit checking once the main service's `/api/health` reports a format that can be compared reliably against a git SHA.

## Threat Flags

None. The only trust-boundary surfaces in this plan are the `pv-inverter-proxy-updater.path` + `.service` units (EXEC-03, explicit in the plan threat model) and the `/run/pv-inverter-proxy-updater-active` tmpfs flag (world-readable but not security-sensitive; its mere existence is a signal, and an attacker with root on the host already has full control). The updater_root trust boundary (Plan 45-03) remains filesystem-enforced: no imports from `pv_inverter_proxy.updater.*` or main-service modules outside the `releases`/`recovery`/`state_file` allowlist.

## Self-Check: PASSED

- `src/pv_inverter_proxy/updater_root/status_writer.py` FOUND (contains `StatusFileWriter`, `PHASES`, `STATUS_FILE_MODE=0o644`)
- `src/pv_inverter_proxy/updater_root/pip_ops.py` FOUND (contains `create_venv`, `pip_install_dry_run`, `pip_install`, `compileall`, `smoke_import`, `config_dryrun`, `PipTimeoutError`)
- `src/pv_inverter_proxy/updater_root/healthcheck.py` FOUND (contains `HealthChecker`, `HealthCheckConfig`, `HealthCheckOutcome`, `check_systemctl_active`, `systemctl_restart`)
- `src/pv_inverter_proxy/updater_root/runner.py` FOUND (contains `UpdateRunner`, `UpdateRunnerConfig`, `UpdateRunnerPrimitives`, `atomic_symlink_flip`, `write_pending_marker`, `_rollback_count` guard, `_raise_updater_active_flag`, `_drop_updater_active_flag`)
- `src/pv_inverter_proxy/updater_root/__main__.py` FOUND (contains `main`, `_make_production_primitives`, structlog JSON config)
- `config/pv-inverter-proxy-updater.path` FOUND (PathModified + Unit= directives)
- `config/pv-inverter-proxy-updater.service` FOUND (Type=oneshot, User=root, no Requires= main service)
- `install.sh` MODIFIED (copies + enables the new units, Step 7 rewritten)
- `deploy.sh` MODIFIED (idempotent install of new units on every deploy)
- `src/pv_inverter_proxy/recovery.py` MODIFIED (adds `UPDATER_ACTIVE_FLAG`, `updater_active` outcome)
- `tests/test_updater_root_status_writer.py` FOUND (17 tests)
- `tests/test_updater_root_pip_ops.py` FOUND (13 tests)
- `tests/test_updater_root_healthcheck.py` FOUND (15 tests)
- `tests/test_updater_root_runner.py` FOUND (21 tests)
- `tests/test_recovery.py` MODIFIED (+2 updater_active tests -> 33 total)
- Commits FOUND: `339a41a`, `9df7bf1`, `dfe4bc1`, `4f1b9b9`, `495b04c`, `53b72cd`, `8be5c2b`, `fb335cf`
- LXC verified: full 13-phase happy path, nonce replay protection, updater-active flag respected by recovery, main service healthy post-update, 41.8s end-to-end duration, ~15s Venus OS disconnect baseline for Plan 45-05
- Full project regression: 949 passed (up from 947, pre-existing `test_config_get_venus_defaults` failure remains logged in deferred-items.md)
- Trust boundary AST test still green (0 violations)
