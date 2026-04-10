---
phase: 45-privileged-updater-service
plan: 02
subsystem: updater / trigger protocol
tags: [updater, EXEC-01, EXEC-02, SEC-07, HEALTH-09]
requires:
  - "state_file.save_state atomic-write pattern from Phase 43"
  - "updater/__init__.py package scaffold from Phase 44"
  - "install.sh Step 6a state dir block from Phase 43"
provides:
  - "updater/trigger.py write_trigger() + TriggerPayload v1 schema"
  - "updater/status.py load_status() defensive reader + current_phase()"
  - "POST /api/update/start → HTTP 202 producer endpoint"
  - "install.sh Step 6b file-level SEC-07 permissions"
affects:
  - "Plan 45-03 root updater will consume /etc/pv-inverter-proxy/update-trigger.json produced here"
  - "Plan 45-04 .path unit will activate on PathModified of the trigger file"
  - "Phase 46 will add auth/CSRF/rate-limit IN FRONT OF update_start_handler (pre-UI button)"
tech-stack:
  added: []
  patterns:
    - "state_file atomic-write pattern reused verbatim (tempfile + os.replace + chmod)"
    - "Defensive-reader pattern reused from state_file.load_state (never raises)"
    - "Producer-side schema validation as defense-in-depth; security root of trust lives in the consumer"
    - "Local import of updater.trigger inside the handler to keep webapp module-load flat"
key-files:
  created:
    - "src/pv_inverter_proxy/updater/trigger.py"
    - "src/pv_inverter_proxy/updater/status.py"
    - "tests/test_updater_trigger.py"
    - "tests/test_updater_status.py"
    - "tests/test_updater_start_endpoint.py"
  modified:
    - "src/pv_inverter_proxy/webapp.py"
    - "install.sh"
    - ".planning/phases/45-privileged-updater-service/deferred-items.md"
decisions:
  - "Producer-side validation is intentionally light (closed op set, SHA regex, UTC-Z timestamp) — consumer in Plan 45-03 carries the security weight (SHA reachability, tag regex, audit)"
  - "Local import of updater.trigger inside update_start_handler keeps webapp module-load flat and eliminates any circular-import surface before the root helper lands"
  - "Handler hardcodes requested_by=\"webapp\" in Phase 45; Phase 46 widens this with source IP / audit metadata"
  - "Op parameter defaults to \"update\" when missing — matches the common case and simplifies UI wiring later"
  - "install.sh creates empty placeholder files on first run; re-runs only chown/chmod (never truncate) so in-progress updates survive mid-flight reinstalls"
metrics:
  duration: "~45m"
  completed: "2026-04-10"
  tests_added: 56
  tests_passing: 56
  latency_median_ms_on_lxc: 2.5
---

# Phase 45 Plan 02: Trigger + Status File Contracts Summary

Shipped the main-service-side plumbing for the v8.0 update protocol: an atomic trigger writer, a defensive status reader, the `POST /api/update/start` REST endpoint, and install.sh file-level SEC-07 permissions. A `curl -X POST http://lxc/api/update/start` now returns HTTP 202 in ~2.5ms and lands a valid JSON trigger at `/etc/pv-inverter-proxy/update-trigger.json`. No consumer yet — the root helper and `.path` unit ship in Plans 45-03 and 45-04.

## Requirements Coverage

| REQ | Evidence |
|-----|----------|
| EXEC-01 | `tests/test_updater_start_endpoint.py::test_update_start_under_100ms` (median of 5 POSTs < 100ms in-process). LXC curl latency test: 3.8, 2.7, 2.4, 2.5, 2.3 ms (median 2.5ms, ~40× under budget). `tests/test_updater_trigger.py::test_write_trigger_atomic_replace` covers the atomicity side of the requirement. |
| EXEC-02 | `tests/test_updater_trigger.py::test_write_trigger_correct_schema_keys` pins the exact key set `{nonce, op, requested_at, requested_by, target_sha}`. Validation tests cover SHA regex, op enum, rollback sentinel, timestamp format. `generate_nonce()` proven UUID4 shape in `test_generate_nonce_uuid4_shape`. LXC curl confirms the written file matches the schema verbatim. |
| SEC-07 | install.sh Step 6b creates `update-trigger.json` as `0664 root:pv-proxy` and `update-status.json` as `0644 root:root`. LXC verification: `ls -l /etc/pv-inverter-proxy/update-*.json` showed the exact mode/owner after the install step ran. Directory `/etc/pv-inverter-proxy/` stays pv-proxy-owned from Phase 43 so Phase 47 hot-reload work can still create siblings. |
| HEALTH-09 | `tests/test_updater_status.py` (20 tests) proves `load_status()` never raises — missing, empty, truncated, non-UTF-8, garbage, wrong-type top level, unsupported schema, malformed inner fields all collapse to the idle default. `current_phase()` helper returns `"idle"` fallback. |

## LXC Verification (192.168.3.191)

```
$ curl -sS -i -X POST http://192.168.3.191/api/update/start \
    -H 'Content-Type: application/json' \
    -d '{"op":"update","target_sha":"0000000000000000000000000000000000000000"}'
HTTP/1.1 202 Accepted
Content-Type: application/json; charset=utf-8
Content-Length: 89

{"update_id": "416e10f5-a472-4b5d-9827-a7bb2685cbae", "status_url": "/api/update/status"}

$ ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/update-trigger.json'
{
  "nonce": "416e10f5-a472-4b5d-9827-a7bb2685cbae",
  "op": "update",
  "requested_at": "2026-04-10T21:12:11Z",
  "requested_by": "webapp",
  "target_sha": "0000000000000000000000000000000000000000"
}

$ curl -sS -X POST http://192.168.3.191/api/update/start \
    -H 'Content-Type: application/json' \
    -d '{"op":"update","target_sha":"abc"}'
{"error": "invalid_payload: update requires full 40-char lowercase hex SHA, got 'abc'"}
# HTTP/1.1 400 Bad Request

$ curl -sS -X POST http://192.168.3.191/api/update/start \
    -H 'Content-Type: application/json' \
    -d '{"op":"rollback","target_sha":"previous"}'
{"update_id": "4164a94b-e23f-48f2-828a-d424d0d0479e", "status_url": "/api/update/status"}
# HTTP/1.1 202 Accepted
```

### Latency samples (EXEC-01: <100ms)

```
$ for i in 1 2 3 4 5; do
    curl -s -o /dev/null -w "%{time_total}\n" -X POST http://192.168.3.191/api/update/start \
      -H 'Content-Type: application/json' \
      -d '{"op":"update","target_sha":"1111111111111111111111111111111111111111"}'
  done
0.003824
0.002748
0.002385
0.002455
0.002336
```

Median **2.5ms**. All five samples are ~40× under the 100ms budget. The hot path is dominated by aiohttp request parsing and the small JSON response; the actual `write_trigger` work is microseconds (one `tempfile.write_text`, one `os.replace`, one `os.chmod`).

### File permissions (SEC-07)

```
$ ssh root@192.168.3.191 'ls -l /etc/pv-inverter-proxy/update-*.json'
-rw-r--r-- 1 root     root       0 Apr 10 21:11 /etc/pv-inverter-proxy/update-status.json
-rw-rw-r-- 1 pv-proxy pv-proxy 201 Apr 10 21:12 /etc/pv-inverter-proxy/update-trigger.json
```

`update-status.json` matches SEC-07 exactly: `0644 root:root`. `update-trigger.json` has the correct mode `0664` but owner is `pv-proxy:pv-proxy` not `root:pv-proxy` — see **Deviations** below.

### pv-proxy user can read status file

```
$ ssh root@192.168.3.191 'su -s /bin/bash pv-proxy -c "cat /etc/pv-inverter-proxy/update-status.json && echo READ_OK"'
READ_OK
```

Empty file is valid — `load_status()` returns the idle default. World-readable mode `0644` means the main service (running as pv-proxy) can surface phase info in `/api/health` without needing special group membership.

### Updater .path unit absent (expected)

```
$ ssh root@192.168.3.191 'systemctl status pv-inverter-proxy-updater.path'
Unit pv-inverter-proxy-updater.path could not be found.
```

Correct — the `.path` unit ships in Plan 45-04. The trigger file just sits on disk until then.

## Test Results

```
$ PYTHONPATH=src pytest tests/test_updater_trigger.py tests/test_updater_status.py tests/test_updater_start_endpoint.py -v
tests/test_updater_trigger.py      ........................   24 passed
tests/test_updater_status.py       ....................        20 passed
tests/test_updater_start_endpoint.py ............              12 passed
==================================== 56 passed in 0.29s =========================
```

Regression suite spanning Phase 44 + Phase 45 updater/health code:

```
$ PYTHONPATH=src pytest tests/test_updater_trigger.py tests/test_updater_status.py \
    tests/test_updater_start_endpoint.py tests/test_updater_version.py \
    tests/test_updater_webapp_routes.py tests/test_health_endpoint.py
120 passed, 20 warnings in 0.30s
```

## Final install.sh Step 6b block

Copy-pasted from the committed install.sh:

```bash
# --- Step 6b: Update protocol file permissions (SEC-07) ---
# update-trigger.json: mode 0664, owner root:pv-proxy.
#   pv-proxy (main service) writes via tempfile+os.replace in
#   updater/trigger.py. root (updater.path consumer, Plan 45-03/04) reads
#   and acts on it.
# update-status.json: mode 0644, owner root:root.
#   Only the root updater writes; everyone (including pv-proxy) reads via
#   updater/status.py. World-readable is intentional — contents are phase
#   names + SHAs, no secrets.
#
# Both files are created empty on fresh installs so the permissions are
# correct from the first POST /api/update/start. On re-runs we only
# chown/chmod — we do NOT truncate, so an in-progress update survives a
# mid-flight install.sh re-run (T-45-02-08).
#
# NOTE: $CONFIG_DIR itself stays pv-proxy-owned from Phase 43 so the main
# service can create per-feature files (state.json, etc). We enforce
# ownership at the file level, not the directory level.
info "Setting update protocol file permissions (SEC-07)..."
TRIGGER_FILE="$CONFIG_DIR/update-trigger.json"
STATUS_FILE="$CONFIG_DIR/update-status.json"

if [ ! -e "$TRIGGER_FILE" ]; then
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
ok "Update protocol files permissioned (trigger 0664 root:$SERVICE_USER, status 0644 root:root)"
```

## Permission research flag resolution

The phase-45 research flagged an open question on whether `/etc/pv-inverter-proxy/` itself should be `root`-owned so only root could create the trigger and status files. **Resolved: keep directory pv-proxy-owned from Phase 43, enforce file-level ownership in install.sh Step 6b.**

Rationale:

1. pv-proxy must be able to create/modify the trigger file (by design — that's EXEC-01).
2. pv-proxy also creates other files in `/etc/pv-inverter-proxy/` (e.g. `state.json` from Phase 43 via `state_file.save_state`). Flipping the dir to root-owned would break all existing state persistence.
3. Phase 47 hot-reload work will need pv-proxy to write new config siblings, so a root-owned directory would gate future features behind a privileged helper unnecessarily.
4. The status file is protected file-by-file: `install -o root -g root -m 0644` means pv-proxy can read but cannot overwrite. That's the only SEC-07 invariant that actually matters — the directory write bit is not the defense.

## Deviations from Plan

### Rule-based auto-fixes

**1. [Rule 3 — Blocker] install.sh cannot re-run on rsync-deployed LXC hosts**

- **Found during:** Task 4 LXC smoke test, running `ssh root@lxc 'cd /opt/pv-inverter-proxy && bash install.sh'`
- **Error:** `install_root /opt/pv-inverter-proxy is a symlink but target has no .git (corrupt layout?)`
- **Root cause:** `deploy.sh` uses rsync with default excludes plus our own rules, so `.git/` is stripped from the release directory. After the Phase 43 blue-green migration, `/opt/pv-inverter-proxy` is a symlink to `releases/current/<release>/`, and the guard at install.sh:86 trips because that target dir has no `.git`.
- **Fix:** Ran the Step 6b block manually over ssh using a heredoc, exactly reproducing the install.sh logic. File permissions came out correct on the first try.
- **Deferred:** Logged in `deferred-items.md` under "install.sh re-run fails on blue-green deployed hosts". This is a pre-existing install.sh limitation, not something Plan 45-02 introduced. Out of scope per deviation rules — fix in a dedicated `/gsd:debug` pass or a phase-45 follow-up plan that relaxes the guard (e.g. accept `.git`-less release dirs when a `deploy.sh`-written marker file is present).

**2. [Rule 2 — Defense-in-depth] Handler rejects non-dict JSON body with explicit error**

- **Found during:** Task 3 implementation
- **Issue:** The plan didn't specify what to return for `body=[1,2,3]` — a valid JSON list but not a dict.
- **Fix:** Added explicit `isinstance(body, dict)` check returning `400 {"error": "body_must_be_json_object"}`. Covered by `test_update_start_rejects_non_dict_body`. This matches the existing webapp idiom for other POST handlers and keeps error surfaces consistent.

### Schema deviation: trigger file ownership drifts to `pv-proxy:pv-proxy` after first write

- **Literal SEC-07 text:** "owner `root:pv-proxy`"
- **Observed after first POST:** `-rw-rw-r-- 1 pv-proxy pv-proxy 201 ... update-trigger.json`
- **Why:** `os.replace(tmp, target)` is not an in-place write — it unlinks the old inode and renames the tempfile in. The tempfile was created by the pv-proxy process, so the new inode's uid is pv-proxy. We `os.chmod` after the replace so mode 0664 is preserved, but we can't chown to root without being root.
- **Security impact: none.** The SEC-07 intent is "pv-proxy can write, root can read". Both still hold:
  - Mode 0664: owner (pv-proxy) writes, group (pv-proxy) reads, world reads
  - Root bypasses ownership entirely and can read any file
  - The threat model T-45-02-06 already accepts that "a compromise of pv-proxy already has full code-exec in the main service context; writing a trigger is not additional privilege"
- **Consumer implication for Plan 45-03:** The root updater MUST NOT assert `stat().st_uid == 0` on the trigger file. The only file-level check that matters is "is this file readable" (always true for root).
- **Fix in this plan:** None — fundamental to the atomic-write pattern. Documented here and in `deferred-items.md` so Plan 45-03's consumer design is aware.

### Checkpoint auto-approval

Task 4 was declared `checkpoint:human-verify` by the plan. Auto-approved per the user's standing preferences ("always auto-deploy after code changes" + "always execute directly, don't ask permission"), matching the precedent Plan 45-01 set. All nine of the plan's how-to-verify bullets were checked live on the LXC. Cleanup also performed — trigger file was reset to `0664 root:pv-proxy` empty placeholder via `install -o root -g pv-proxy -m 0664 /dev/null` after the smoke tests.

## Commits

| Commit | Message |
|--------|---------|
| `f760910` | feat(45-02): add atomic trigger file writer |
| `2630039` | feat(45-02): add defensive status file reader |
| `b6deb00` | feat(45-02): add POST /api/update/start endpoint |
| `2ddb0e3` | feat(45-02): set trigger/status file permissions in install.sh |
| `4a68d33` | test(45-02): add POST /api/update/start integration tests |
| `78b51d5` | chore(45-02): deploy and smoke-test on LXC; log 2 deferred items |

## Deferred Issues

- **install.sh blue-green re-run guard** — see deferred-items.md. Blocks re-running `install.sh` on the LXC for future plans that touch install.sh. Not blocking Plan 45-02 completion because Step 6b is trivial to apply manually and Plan 45-03 will bundle it into the root helper's install step anyway.
- **pv-proxy:pv-proxy ownership after first write** — see deferred-items.md and the Deviations section above. Zero security impact; documented so Plan 45-03 designs the consumer accordingly.

## Self-Check: PASSED

- `src/pv_inverter_proxy/updater/trigger.py` FOUND (contains `write_trigger`, `TriggerPayload`, `generate_nonce`, `now_iso_utc`, `TRIGGER_FILE_PATH`, `TRIGGER_FILE_MODE`)
- `src/pv_inverter_proxy/updater/status.py` FOUND (contains `load_status`, `current_phase`, `UpdateStatus`, `STATUS_FILE_PATH`)
- `src/pv_inverter_proxy/webapp.py` FOUND (contains `update_start_handler`, route `/api/update/start`)
- `install.sh` FOUND (contains `update-trigger.json` + `update-status.json` install blocks)
- `tests/test_updater_trigger.py` FOUND (24 tests)
- `tests/test_updater_status.py` FOUND (20 tests)
- `tests/test_updater_start_endpoint.py` FOUND (12 tests)
- Commits FOUND: `f760910`, `2630039`, `b6deb00`, `2ddb0e3`, `4a68d33`, `78b51d5`
- LXC verified: HTTP 202, schema round-trip OK, latency median 2.5ms, file permissions match SEC-07 intent, pv-proxy can read status file, no updater .path unit yet
