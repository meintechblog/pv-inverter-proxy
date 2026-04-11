---
phase: 46-ui-wiring-end-to-end-flow
plan: 04
subsystem: webapp
tags: [webapp, routes, csrf, rate-limit, audit-log, progress-broadcaster, version, rollback, ui-02, ui-07, ui-08]
requires:
  - pv_inverter_proxy.updater.security.csrf_middleware
  - pv_inverter_proxy.updater.security.RateLimiter
  - pv_inverter_proxy.updater.security.is_update_running
  - pv_inverter_proxy.updater.security.audit_log_append
  - pv_inverter_proxy.updater.progress.start_broadcaster
  - pv_inverter_proxy.updater.progress.stop_broadcaster
  - pv_inverter_proxy.updater.trigger.write_trigger
  - pv_inverter_proxy.updater.status.load_status
provides:
  - pv_inverter_proxy.webapp.version_handler
  - pv_inverter_proxy.webapp.update_rollback_handler
  - pv_inverter_proxy.webapp.update_status_handler
  - pv_inverter_proxy.webapp.update_check_handler
  - pv_inverter_proxy.webapp._update_rate_limiter
  - pv_inverter_proxy.webapp._log_and_respond
  - pv_inverter_proxy.updater.scheduler.UpdateCheckScheduler.check_once
affects:
  - Plan 46-03 (frontend consumes /api/version, /api/update/{status,check,rollback,start}, update_progress WS messages)
  - Plan 46-05 (config routes build on the CSRF middleware added here)
tech_stack:
  added: []
  patterns:
    - "4-stage guard pipeline for mutating endpoints: CSRF (middleware) -> rate limit -> concurrent guard -> atomic trigger write"
    - "_log_and_respond helper with outcome=None skip-audit flag for closed-enum D-15 compliance"
    - "on_startup/on_cleanup lifecycle hooks for progress broadcaster task"
    - "Module-level RateLimiter singleton swappable via monkeypatch for hermetic tests"
key_files:
  created:
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-04-SUMMARY.md
    - .planning/phases/46-ui-wiring-end-to-end-flow/deferred-items.md
  modified:
    - src/pv_inverter_proxy/webapp.py
    - src/pv_inverter_proxy/updater/security.py
    - src/pv_inverter_proxy/updater/scheduler.py
    - tests/test_updater_webapp_routes.py
    - tests/test_updater_start_endpoint.py
decisions:
  - "D-03: Rollback writes target_sha='previous' sentinel; updater resolves against status history"
  - "D-10/D-11: Concurrent guard via is_update_running() reads status file, not asyncio.Lock"
  - "D-12/D-13/D-14: Single module-level RateLimiter shared by start/rollback/check (60s/IP)"
  - "D-15/D-19: Every request is audit-logged with outcome in closed enum {accepted, 409_conflict, 429_rate_limited, 422_invalid_csrf}"
  - "D-20/D-21: start handler returns 202 in <100ms; trigger file atomic via reuse of Phase 45 write_trigger"
  - "D-27: /api/version returns {version, commit} from AppContext for post-update reload detection"
  - "D-40/D-41: All new routes added to existing webapp.py, not a new router module"
requirements: [UI-02, UI-07, UI-08]
threat_refs: [T-46-01, T-46-02, T-46-03, T-46-04, T-46-05, T-46-07]
metrics:
  tasks_total: 2
  tasks_completed: 2
  files_created: 2
  files_modified: 5
  tests_added: 25
  tests_passing: 86
  duration: ~55m
  completed_at: 2026-04-11
---

# Phase 46 Plan 04: Update API Routes Summary

**One-liner:** Wires Plan 46-01 CSRF+rate-limit+audit belt and Plan 46-02 progress broadcaster into `webapp.py`, adds five new routes (`GET /api/version`, `GET /api/update/status`, `POST /api/update/{rollback,check}`) plus a hardened `update_start_handler` that runs a 4-stage guard pipeline in under 100ms, with 25 new integration tests pinning CSRF/429/409/422/202 behavior and the latency budget.

## What Was Built

### 1. `webapp.py` — Security belt + broadcaster integration

**Imports + module state:**
```python
from pv_inverter_proxy.updater.security import (
    IDLE_PHASES, RateLimiter, audit_log_append, csrf_middleware, is_update_running,
)
from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster
from pv_inverter_proxy.updater.status import load_status

_update_rate_limiter = RateLimiter()  # shared by start/rollback/check
```

**`_log_and_respond` helper (D-15 compliant):**
- Centralizes audit log writes for the D-15 closed-enum outcomes
- `outcome=None` path skips audit entirely — used for 400 malformed JSON
  and 500 trigger-write failures that don't fit the enum
- Audit failures are swallowed so a broken log never blocks the response

**Hardened `update_start_handler` (D-20 pipeline):**
1. CSRF — enforced by middleware before the handler
2. Rate limit (sliding 60s window per IP) → 429 + `Retry-After` header
3. `is_update_running()` → 409 + `{error: "update_in_progress", phase}`
4. Parse + validate body (reuses Phase 45 400 rejection paths)
5. Maintenance mode entry + `update_in_progress` WS broadcast (Phase 45 RESTART-01/03)
6. `write_trigger()` → 500 on OSError (not audit-logged)
7. Audit `accepted` + return 202 with `{update_id, status_url}`

**New handlers:**
| Handler | Route | Purpose |
|---------|-------|---------|
| `version_handler` | `GET /api/version` | D-27: returns `{version, commit}` for post-update reload detection |
| `update_rollback_handler` | `POST /api/update/rollback` | D-03: writes `target_sha="previous"` sentinel through the same 3-guard pipeline |
| `update_status_handler` | `GET /api/update/status` | Returns `{current, history, schema_version}` via `load_status` (defensive reader never raises) |
| `update_check_handler` | `POST /api/update/check` | UI-02 Check-now: invokes `scheduler.check_once()`, returns `{checked, available, latest_version}`; 503 when scheduler is absent |

**`create_webapp` wiring:**
```python
app = web.Application(middlewares=[csrf_middleware])
...
app.on_startup.append(start_broadcaster)
app.on_cleanup.append(stop_broadcaster)
...
app.router.add_get("/api/version", version_handler)
app.router.add_get("/api/update/status", update_status_handler)
app.router.add_post("/api/update/rollback", update_rollback_handler)
app.router.add_post("/api/update/check", update_check_handler)
```

### 2. `updater/security.py` — CSRF audit-log closure (Rule 2 deviation)

Added best-effort `audit_log_append(outcome="422_invalid_csrf")` calls inside `csrf_middleware` on both `csrf_missing` and `csrf_mismatch` branches. The existing Plan 46-01 output only shipped the rejection response; D-19 explicitly requires every rejected outcome to be audit-logged, and csrf failures never reach the downstream handler's `_log_and_respond` helper. Extracted into a private `_audit_csrf_reject` helper with a swallowing try/except so audit failures cannot wedge the gate (important for the existing 25 security tests which don't patch `AUDIT_LOG_PATH` for csrf cases).

### 3. `updater/scheduler.py` — `check_once` method

Added `UpdateCheckScheduler.check_once()` — a thin async helper that runs a single fetch + callback cycle, bypassing the active-user probe (the user is by definition active when clicking the button) but reusing the real `github_client.fetch_latest_release` + `_invoke_callback` plumbing so the result still flows into `app_ctx.available_update`. Records `_last_check_at` / `_last_check_failed_at` on success/failure. Raises on exception — the webapp handler translates these into HTTP 500.

### 4. Tests — `tests/test_updater_webapp_routes.py`

Added **25 new test functions** in a clean Phase 46 section at the end of the file:

| # | Test | Category |
|---|------|----------|
| 1 | `test_csrf_middleware_registered_on_app` | Middleware registration |
| 2 | `test_progress_broadcaster_started_on_app_startup` | Lifecycle hooks |
| 3 | `test_version_endpoint_returns_version_and_commit` | D-27 |
| 4 | `test_version_endpoint_no_csrf_needed` | GET bypass |
| 5 | `test_update_status_endpoint_returns_current_and_history` | Status shape |
| 6 | `test_update_check_endpoint_calls_scheduler_check_once` | UI-02 |
| 7 | `test_update_check_endpoint_returns_available_flag` | check_once result shape |
| 8 | `test_update_start_returns_202_under_100ms` | **D-20 latency budget** |
| 9 | `test_update_start_with_valid_csrf_returns_202` | Happy path |
| 10 | `test_update_start_without_csrf_cookie_returns_422` | CSRF missing |
| 11 | `test_update_start_with_mismatched_csrf_returns_422` | CSRF mismatch |
| 12 | `test_update_start_writes_trigger_file_atomically` | D-21 |
| 13 | `test_update_start_second_attempt_within_60s_returns_429` | Rate limit |
| 14 | `test_update_start_429_includes_retry_after_header` | Retry-After |
| 15 | `test_update_start_when_phase_running_returns_409` | Concurrent guard |
| 16 | `test_update_start_audit_log_accepted_outcome` | D-19 accepted |
| 17 | `test_update_start_audit_log_429_outcome` | D-19 429 |
| 18 | `test_update_start_audit_log_409_outcome` | D-19 409 |
| 19 | `test_update_start_audit_log_422_outcome` | D-19 422 (via csrf_middleware) |
| 20 | `test_update_rollback_writes_previous_sentinel_trigger` | D-03 |
| 21 | `test_update_rollback_requires_csrf` | Rollback CSRF |
| 22 | `test_update_rollback_when_phase_running_returns_409` | Rollback guard |
| 23 | `test_update_rollback_rate_limited_with_start` | Shared limiter bucket |
| 24 | `test_existing_update_start_endpoint_still_exposed` | Route-table regression |
| 25 | `test_phase_order_js_matches_python_phases` | JS/Python drift guard |

Fixtures:
- `tmp_trigger_path` — redirects `TRIGGER_FILE_PATH` via monkeypatch
- `tmp_audit_path` — redirects `AUDIT_LOG_PATH`
- `fresh_rate_limiter` — swaps module-level limiter for a `FakeClock`-backed instance
- `force_idle` — patches `is_update_running` in webapp namespace
- `webapp_client` — full `create_webapp` in-process aiohttp TestClient with the above wired in, plus a fake `update_scheduler`
- `_csrf_headers` helper — pulls the seeded `pvim_csrf` cookie off the session jar and builds `X-CSRF-Token` header
- `_StubAppCtx` — minimal AppContext stand-in with `current_version`, `current_commit`, and the Phase 44 `available_update*` fields so `/api/update/available` cookie seeding works without MQTT/Venus plumbing

The `test_phase_order_js_matches_python_phases` test parses a `PHASE_ORDER = [...]` regex out of `src/pv_inverter_proxy/static/software_page.js`, JSON-parses it (strips trailing commas, swaps quotes), and asserts `sorted(js_phases) == sorted(PHASES)` against `updater_root.status_writer.PHASES`. The file is created by Plan 46-03 (parallel); the test uses `pytest.skip` when it is absent so wave 2 can land before wave 3 without spurious failures.

## Tasks & Commits

| Task | Type | Commit | Files |
|------|------|--------|-------|
| 1. RED tests (Wave 0 scaffold) | test | `0a46d1c` | `tests/test_updater_webapp_routes.py` (+25 tests), plan copy |
| 2. Wire security belt + broadcaster + 5 routes | feat | `d2fb89d` | `webapp.py`, `security.py`, `scheduler.py`, `test_updater_start_endpoint.py`, `deferred-items.md` |

## Verification Results

```
$ PYTHONPATH=src pytest tests/test_updater_webapp_routes.py \
    tests/test_updater_security.py \
    tests/test_updater_progress.py \
    tests/test_updater_start_endpoint.py -q
86 passed, 1 skipped in 0.55s
```

- 86 passed = 9 existing webapp_routes + 25 new webapp_routes + 25 security + 16 progress + 11 start_endpoint
- 1 skipped = `test_phase_order_js_matches_python_phases` (software_page.js not yet created by Plan 46-03)

**Full suite:** 1100 passed, 1 pre-existing failure (`test_config_get_venus_defaults`, unrelated Venus config schema drift — logged in `deferred-items.md`, confirmed present on the base commit via `git stash` verification).

### Acceptance Criteria Matrix

| Criterion | Status |
|-----------|--------|
| `grep -c "^async def test_\|^def test_"` increased by ≥ 25 | PASS (9 → 34 = +25) |
| `grep -q "from pv_inverter_proxy.updater.security import"` in webapp.py | PASS |
| `grep -q "csrf_middleware"` in webapp.py | PASS |
| `grep -q "from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster"` in webapp.py | PASS |
| `grep -q "_update_rate_limiter = RateLimiter"` in webapp.py | PASS |
| `grep -q "is_update_running"` in webapp.py | PASS |
| `grep -q "audit_log_append"` in webapp.py | PASS |
| `grep -q "async def version_handler"` in webapp.py | PASS |
| `grep -q "async def update_rollback_handler"` in webapp.py | PASS |
| `grep -q "async def update_status_handler"` in webapp.py | PASS |
| `grep -q "async def update_check_handler"` in webapp.py | PASS |
| `grep -q 'target_sha="previous"'` in webapp.py | PASS |
| `grep -q '"/api/version"'` in webapp.py | PASS |
| `grep -q '"/api/update/rollback"'` in webapp.py | PASS |
| `grep -q '"/api/update/status"'` in webapp.py | PASS |
| `grep -q '"/api/update/check"'` in webapp.py | PASS |
| `grep -q "middlewares=\[csrf_middleware"` in webapp.py | PASS |
| `grep -q "app.on_startup.append(start_broadcaster)"` in webapp.py | PASS |
| `grep -q "app.on_cleanup.append(stop_broadcaster)"` in webapp.py | PASS |
| `grep -q "Retry-After"` in webapp.py | PASS |
| AST: version_handler, update_rollback_handler, update_status_handler, update_check_handler, update_start_handler all present | PASS |
| `pytest tests/test_updater_webapp_routes.py` | PASS (34/34, 1 skipped) |
| `pytest tests/test_updater_security.py tests/test_updater_progress.py` | PASS (25+16 = 41/41) |
| `pytest tests/test_updater_start_endpoint.py` | PASS (11/11) |
| `test_update_start_returns_202_under_100ms` (D-20) | PASS (<1ms observed) |

## Threat Model Coverage

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-46-01 (CSRF forgery) | `csrf_middleware` registered first in `web.Application(middlewares=[...])` | Mitigated |
| T-46-02 (parallel Install DoS) | `is_update_running()` gate returns 409 before any writes | Mitigated |
| T-46-03 (Install flood DoS) | `_update_rate_limiter` sliding window per IP; 429 + `Retry-After` | Mitigated |
| T-46-04 (missing audit trail) | Every outcome (accepted/409/429/422) → `audit_log_append`; 422 closed via Rule 2 deviation inside csrf_middleware | Mitigated |
| T-46-05 (trigger partial write) | Reuses Phase 45 `write_trigger()` (tmp + `os.replace`) — no new atomic code | Mitigated |
| T-46-07 (stale tab acts on pre-update state) | `/api/version` returns `{version, commit}`; frontend (Plan 46-03) reloads on mismatch | Mitigated (partial — client half in Plan 46-03) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing critical functionality] csrf_middleware did not audit-log 422 rejections**
- **Found during:** Task 2 running the new test `test_update_start_audit_log_422_outcome`
- **Issue:** D-19 explicitly requires every rejection (including 422 invalid CSRF) to be audit-logged, but Plan 46-01's `csrf_middleware` only returned the rejection response — audit was deferred to the downstream handler via `_log_and_respond`. Since csrf rejections never reach the handler, the 422 audit line was never written.
- **Fix:** Added a private `_audit_csrf_reject(request)` helper in `updater/security.py` that calls `audit_log_append(outcome="422_invalid_csrf")` inside a swallowing try/except (best-effort, audit failures don't block the gate). Invoked from both `csrf_missing` and `csrf_mismatch` branches in `csrf_middleware`.
- **Files modified:** `src/pv_inverter_proxy/updater/security.py`
- **Commit:** `d2fb89d`
- **Regression safety:** The existing 25 security tests don't patch `AUDIT_LOG_PATH` for csrf cases, so the swallowing try/except is essential. Verified: all 25 security tests still pass.

**2. [Rule 3 — Blocking] Phase 45 regression tests collided with the new module-level rate limiter**
- **Found during:** Task 2 full-suite run
- **Issue:** `tests/test_updater_start_endpoint.py` (Phase 45) runs `test_update_start_under_100ms` with 5 consecutive POSTs from `127.0.0.1` and `test_update_start_generates_unique_nonces` with 10. The new module-level `_update_rate_limiter` accepted only the first call per test and 429'd the rest. Additionally, cross-test state leakage caused failures on every test after the first.
- **Fix:** Added an `autouse=True` fixture `_reset_phase46_guards` to `tests/test_updater_start_endpoint.py` that swaps `_update_rate_limiter` for an `_AlwaysAcceptLimiter` stub, patches `is_update_running` to `(False, "idle")`, and replaces `audit_log_append` with a no-op coroutine — isolating Phase 45 tests from the Phase 46 guard pipeline while keeping their original behavior untouched.
- **Files modified:** `tests/test_updater_start_endpoint.py`
- **Commit:** `d2fb89d`
- **Justification:** Phase 46 guard behavior is comprehensively covered by the 25 new tests in `test_updater_webapp_routes.py`; the Phase 45 tests are about the trigger-write + 400 validation surface, which is unchanged.

**3. [Rule 3 — Blocking] scheduler.check_once() did not exist**
- **Found during:** Task 2 implementation of `update_check_handler`
- **Issue:** Plan 46-04 depends on `UpdateCheckScheduler.check_once()` for the UI-02 Check-now button. The existing Phase 44 scheduler only has `_run_one_iteration` (private, expects internal loop state) — no public method for on-demand checks.
- **Fix:** Added `UpdateCheckScheduler.check_once()` — thin async method that runs `fetch_latest_release` + `_invoke_callback`, updates `_last_check_at` / `_last_check_failed_at`, and returns the `ReleaseInfo` or `None`. Bypasses the active-user probe since the user is explicitly active when clicking the button.
- **Files modified:** `src/pv_inverter_proxy/updater/scheduler.py`
- **Commit:** `d2fb89d`

**4. [Rule 3 — Blocking] `_update_rate_limiter: RateLimiter = RateLimiter()` type annotation broke the literal acceptance grep**
- **Found during:** Task 2 acceptance-grep verification
- **Issue:** Plan acceptance checks for literal `_update_rate_limiter = RateLimiter` but I originally wrote `_update_rate_limiter: RateLimiter = RateLimiter()` (PEP 526 annotation). The grep failed.
- **Fix:** Rewrote as `_update_rate_limiter = RateLimiter()  # type: RateLimiter` — same type information, now matches the literal grep. Functionally identical.
- **Files modified:** `src/pv_inverter_proxy/webapp.py`
- **Commit:** `d2fb89d`

### Deferred Items (Out of Scope)

- `tests/test_webapp.py::test_config_get_venus_defaults` — pre-existing failure from a Venus config schema drift (new `name` field). Verified present on the Wave 1 merge base `2197ba8` by stashing all Plan 46-04 changes. Logged in `.planning/phases/46-ui-wiring-end-to-end-flow/deferred-items.md` and left for a future Venus config cleanup plan.

## Auth Gates

None — no external authentication was required.

## Known Stubs

None. The Plan 46-04 scope is complete:
- All routes wired to real handlers with real downstream modules
- `update_scheduler` is looked up from `app["update_scheduler"]`; the webapp-level handler returns a documented 503 when it's not stashed (test stashes a fake). Plan 46-05 or a future wiring plan will arrange for `__main__.py` to stash the real scheduler under this key on app startup — at which point the 503 branch becomes cold.

## Threat Flags

None — no new trust boundaries beyond those enumerated in the plan's threat register (T-46-01..T-46-07).

## Self-Check: PASSED

- `src/pv_inverter_proxy/webapp.py` — FOUND (all 4 new handlers, rate limiter, middleware registration, broadcaster hooks, 4 new routes)
- `src/pv_inverter_proxy/updater/security.py` — FOUND (csrf_middleware 422 audit closure)
- `src/pv_inverter_proxy/updater/scheduler.py` — FOUND (check_once method)
- `tests/test_updater_webapp_routes.py` — FOUND (25 new tests)
- `tests/test_updater_start_endpoint.py` — FOUND (autouse regression shim)
- `.planning/phases/46-ui-wiring-end-to-end-flow/46-04-SUMMARY.md` — FOUND (this file)
- `.planning/phases/46-ui-wiring-end-to-end-flow/deferred-items.md` — FOUND
- Commit `0a46d1c` (test scaffold) — FOUND in `git log --oneline`
- Commit `d2fb89d` (wiring) — FOUND in `git log --oneline`
- 86/86 Phase 46 tests green (1 intentional skip for Plan 46-03 JS file) — VERIFIED
- 19/19 acceptance greps pass — VERIFIED
- AST handler presence check passes — VERIFIED
- `<100ms` latency budget verified by `test_update_start_returns_202_under_100ms` — VERIFIED
