---
phase: 45-privileged-updater-service
plan: 01
subsystem: webapp / health endpoint
tags: [health, updater, HEALTH-01, HEALTH-02, HEALTH-03, HEALTH-04]
requires: [HEALTH-04 writer in __main__ from Phase 43, current_version/current_commit in AppContext from Phase 44]
provides:
  - "/api/health returning the rich 8-field schema"
  - "_derive_health_payload pure helper for downstream plans"
affects:
  - "Phase 45-04 updater orchestrator (polls /api/health after restart)"
tech-stack:
  added: []
  patterns:
    - "Pure derivation helper factored out for hermetic unit testing"
    - "Startup grace window collapses transient degraded → starting"
key-files:
  created:
    - "tests/test_health_endpoint.py"
    - ".planning/phases/45-privileged-updater-service/deferred-items.md"
  modified:
    - "src/pv_inverter_proxy/webapp.py"
    - "tests/test_webapp.py"
decisions:
  - "Grace window boundary is exclusive: uptime_s < 30.0 is in-grace, uptime_s == 30.0 is post-grace (matches Python's natural `<` semantics, tested explicitly)"
  - "venus_os `disabled` takes precedence over `venus_mqtt_connected` to prevent a warn when host is empty by design"
  - "Grace remap only rewrites `modbus_server` and `devices` — `venus_os` stays honest because HEALTH-03 already makes it warn-only"
metrics:
  duration: "~45m"
  completed: "2026-04-10"
  tests_added: 14
  tests_passing: 14
---

# Phase 45 Plan 01: Rich /api/health Endpoint Summary

Rewrote `/api/health` into the component-level JSON contract the Phase 45-04 updater orchestrator will read after a restart to decide success or trigger rollback. Derivation is a pure function so every branch is covered by hermetic unit tests — zero aiohttp server needed for the happy path.

## Final Live Schema (copy-pasted from LXC curl)

```json
{
    "status": "ok",
    "version": "8.0.0",
    "commit": "26bef2a",
    "uptime_seconds": 9.0,
    "webapp": "ok",
    "modbus_server": "ok",
    "devices": {
        "5303f554b55d": "ok",
        "289c08e70310": "ok",
        "cce137955355": "ok",
        "edc493ce4311": "ok",
        "sungrow-sg-rt": "ok"
    },
    "venus_os": "ok"
}
```

At `uptime_seconds: 0.0` (fastest possible poll from inside the LXC immediately after `systemctl restart`):

```json
{
    "status": "starting",
    "version": "8.0.0",
    "commit": "26bef2a",
    "uptime_seconds": 0.0,
    "webapp": "ok",
    "modbus_server": "starting",
    "devices": {
        "5303f554b55d": "starting",
        "289c08e70310": "starting",
        "cce137955355": "starting",
        "edc493ce4311": "starting",
        "sungrow-sg-rt": "starting"
    },
    "venus_os": "ok"
}
```

`modbus_server` and all devices show `starting` (grace remap), `venus_os` stays `ok` because MQTT reconnects almost instantly on this LXC.

## Requirements Coverage

| REQ | Evidence |
|-----|----------|
| HEALTH-01 | 8-field schema verified in live curl + `test_health_schema_has_all_required_keys` + `tests/test_webapp.py::test_health_endpoint` |
| HEALTH-02 | Required-for-success derivation covered by `test_health_all_ok`, `test_health_no_devices_after_grace`, `test_health_degraded_after_grace`, `test_health_cache_none_is_failed` |
| HEALTH-03 | Warn-only venus covered by `test_health_venus_warn_only` and `test_health_venus_disabled` — both assert `status == "ok"` with `venus_os != "ok"` |
| HEALTH-04 | Phase 43 `_healthy_flag_watcher` in `__main__.py` left untouched (grep confirmed `HEALTHY_FLAG_PATH` + `_write_healthy_flag_once` still in place). Live verified `/run/pv-inverter-proxy/healthy` exists after restart. |

## Test Results

- `tests/test_health_endpoint.py`: **14 tests, all passing** (new file)
- `tests/test_webapp.py`: 32 tests, 31 passing (1 pre-existing unrelated failure, see Deferred Issues)
- Full suite: **790 pass, 1 fail (unrelated)**

```
$ PYTHONPATH=…/src pytest tests/test_health_endpoint.py -v
test_health_schema_has_all_required_keys PASSED
test_health_all_ok PASSED
test_health_starting_grace PASSED
test_health_starting_grace_no_devices PASSED
test_health_grace_boundary_exclusive PASSED
test_health_degraded_after_grace PASSED
test_health_no_devices_after_grace PASSED
test_health_cache_none_is_failed PASSED
test_health_venus_warn_only PASSED
test_health_venus_disabled PASSED
test_health_version_commit_unknown PASSED
test_health_no_subprocess_no_fs PASSED
test_health_handler_integration PASSED
test_health_handler_integration_ok_after_grace PASSED
======================== 14 passed in 0.31s ========================
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocker] Worktree branch was missing Phases 43 + 44**

- **Found during:** Task 1 GREEN phase
- **Issue:** `worktree-agent-a284487d` branched off `main@67e9625` (pre-Phase 43). The plan assumes `AppContext.current_version`, `AppContext.healthy_flag_written`, `AppContext.venus_mqtt_connected`, and Phase 43's `_write_healthy_flag_once` all exist. None of them did on the worktree base.
- **Fix:** `git stash && git merge main --no-edit && git stash pop` — brought in 37 commits spanning Phases 43, 44, and the Phase 45 planning docs.
- **Files touched (by merge, not by this plan):** `src/pv_inverter_proxy/context.py`, `src/pv_inverter_proxy/__main__.py`, `src/pv_inverter_proxy/updater/*`, plus release layout + systemd recovery infrastructure.
- **Commit:** `b5d397d` (merge commit)

**2. [Rule 1 — Schema contract] Existing test asserted legacy health keys**

- **Found during:** Task 1 regression sweep
- **Issue:** `tests/test_webapp.py::test_health_endpoint` asserted the old keys (`poll_success_rate`, `cache_stale`, `poll_total`, `poll_success`) which are gone from the new schema.
- **Fix:** Rewrote assertions to match the new 8-field schema.
- **Verified safe:** Grep across `src/pv_inverter_proxy/static/` (JS, HTML) confirmed no frontend consumer references the old keys.
- **Commit:** `a33bcb0`

### Checkpoint auto-approval

Task 2 was declared `checkpoint:human-verify` by the plan. The executor auto-approved the checkpoint under the user's standing preference ("always auto-deploy after code changes" + "always execute directly, don't ask permission") and performed the deploy + curl + journal sweep itself. All seven of the plan's "how-to-verify" bullets were checked live. Documented in commit `a0f37d1`.

## Deferred Issues

- **`tests/test_webapp.py::test_config_get_venus_defaults` fails on baseline `main`** — Pre-existing failure in the `/api/config` GET path, unrelated to `/api/health`. Confirmed by stashing only Plan 45-01 changes and rerunning the test against clean `main`. Logged in `.planning/phases/45-privileged-updater-service/deferred-items.md` for separate triage. Scope boundary rule forbids fixing it here.

## Self-Check: PASSED

- `src/pv_inverter_proxy/webapp.py` FOUND (contains `_HEALTH_STARTUP_GRACE_S`, `_derive_health_payload`, rewritten `health_handler`)
- `tests/test_health_endpoint.py` FOUND (14 tests)
- `.planning/phases/45-privileged-updater-service/deferred-items.md` FOUND
- Commits FOUND: `e5ea093` (RED), `a33bcb0` (GREEN), `26bef2a` (deferred log), `a0f37d1` (LXC smoke verified)
- LXC live schema verified: all 8 fields present, `status=ok` reached by 0.3s, `starting` state observed at 0.0s
- Phase 43 writer grep-verified intact: `_write_healthy_flag_once` still in `__main__.py:42`, invoked at line 441
