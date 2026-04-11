---
phase: 46-ui-wiring-end-to-end-flow
plan: 04
type: execute
wave: 2
depends_on: [46-01, 46-02]
files_modified:
  - src/pv_inverter_proxy/webapp.py
  - tests/test_updater_webapp_routes.py
autonomous: true
requirements: [UI-02, UI-07, UI-08]
threat_refs: [T-46-01, T-46-02, T-46-03, T-46-04, T-46-05, T-46-07]
decisions_implemented: [D-03, D-20, D-21, D-27, D-40, D-41]

must_haves:
  truths:
    - "csrf_middleware from Plan 46-01 is registered on the aiohttp app in create_webapp"
    - "A module-level RateLimiter instance enforces 60s/IP on POST /api/update/start and POST /api/update/rollback"
    - "POST /api/update/start returns HTTP 202 in under 100ms on the happy path (measured in a test)"
    - "Trigger file is written atomically AFTER all guard checks pass and audit_log_append is awaited"
    - "Every POST /api/update/{start,rollback} outcome is audit-logged (accepted, 409_conflict, 429_rate_limited, 422_invalid_csrf)"
    - "POST /api/update/rollback writes a trigger with target_sha='previous' (the Phase 45 sentinel)"
    - "GET /api/version returns {version, commit} from app_ctx.current_version + current_commit"
    - "GET /api/update/status returns the full UpdateStatus JSON (current + history)"
    - "POST /api/update/check triggers the Phase 44 scheduler.check_once() and returns {checked: true, available: bool}"
    - "progress broadcaster is started on app startup and stopped on cleanup"
  artifacts:
    - path: "src/pv_inverter_proxy/webapp.py"
      provides: "New handlers: version_handler, update_rollback_handler, update_status_handler, update_check_handler; existing update_start_handler hardened with CSRF+rate-limit+concurrent-guard+audit-log; csrf_middleware registered; progress broadcaster wired"
      contains: "csrf_middleware"
    - path: "tests/test_updater_webapp_routes.py"
      provides: "Tests for all new endpoints + <100ms latency regression"
      min_lines: 250
  key_links:
    - from: "webapp.py::create_webapp"
      to: "updater.security.csrf_middleware"
      via: "app = web.Application(middlewares=[csrf_middleware, ...existing])"
      pattern: "middlewares=\\[.*csrf_middleware"
    - from: "webapp.py::update_start_handler"
      to: "updater.security.is_update_running + rate_limiter.check + audit_log_append"
      via: "sequential guard calls before write_trigger()"
      pattern: "is_update_running|audit_log_append"
    - from: "webapp.py::update_rollback_handler"
      to: "updater.trigger.write_trigger with target_sha='previous'"
      via: "TriggerPayload(op='rollback', target_sha='previous', ...)"
      pattern: "target_sha=.previous."
    - from: "webapp.py::create_webapp startup"
      to: "updater.progress.start_broadcaster"
      via: "app.on_startup.append(start_broadcaster)"
      pattern: "start_broadcaster"
---

<objective>
Wire Plans 46-01 (security belt) and 46-02 (progress broadcaster) into `webapp.py`, add the five new routes the frontend needs, and harden the existing Phase 45 `update_start_handler` with full guard + audit + rate-limit behaviors.

Purpose: Without this plan, 46-01/46-02 are dormant and the frontend has no endpoints to call. This plan is the integration point between Phase 45's update execution engine and Phase 46's user experience.

Output: A hardened webapp.py with CSRF middleware + rate limiter + 5 new routes + progress broadcaster lifecycle hooks, plus a comprehensive test suite that verifies the <100ms latency requirement, all 4xx rejection paths, and the full audit log coverage.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-01-security-belt-PLAN.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-02-progress-broadcaster-PLAN.md
@src/pv_inverter_proxy/webapp.py
@src/pv_inverter_proxy/updater/trigger.py
@src/pv_inverter_proxy/updater/status.py

<interfaces>
<!-- Contracts from Plans 46-01 and 46-02 this plan consumes. -->

From updater/security.py (Plan 46-01):
```python
@web.middleware
async def csrf_middleware(request, handler): ...

class RateLimiter:
    def check(self, ip: str) -> tuple[bool, int]: ...   # (accepted, retry_after_seconds)

def is_update_running(status_path=None) -> tuple[bool, str]: ...   # (running, phase)

async def audit_log_append(*, ip: str, user_agent: str,
                           outcome: Literal["accepted","409_conflict","429_rate_limited","422_invalid_csrf"],
                           log_path=None, clock=None) -> None: ...

CSRF_COOKIE_NAME = "pvim_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
IDLE_PHASES = frozenset({"idle","done","rollback_done","rollback_failed"})
```

From updater/progress.py (Plan 46-02):
```python
async def start_broadcaster(app): ...
async def stop_broadcaster(app): ...
```

From updater/trigger.py (Phase 45, already shipped):
```python
@dataclass
class TriggerPayload:
    op: str          # "update" or "rollback"
    target_sha: str  # commit SHA or "previous" sentinel
    requested_at: str
    requested_by: str
    nonce: str

def generate_nonce() -> str: ...
def now_iso_utc() -> str: ...
def write_trigger(payload: TriggerPayload, *, trigger_path: Path | None = None) -> None: ...
```

From updater/status.py (Phase 45):
```python
def load_status(path=None) -> UpdateStatus: ...
# UpdateStatus is serializable via .to_dict() OR dataclasses.asdict — verify in status.py
```

From webapp.py (Phase 44/45, existing):
```python
# app_ctx is accessed via request.app["app_ctx"]
# app_ctx.current_version: str     # from importlib.metadata at startup
# app_ctx.current_commit: str | None
# app["ws_clients"]: set[web.WebSocketResponse]
# Existing handler at line 397: update_start_handler (Phase 45, needs hardening in this plan)
# Existing route table at line 2347-2378 (app.router.add_get/add_post)
```
</interfaces>
</context>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser POST -> webapp.py handlers | Untrusted request; CSRF + rate-limit + concurrent-guard + audit-log enforced at handler entry |
| webapp.py -> trigger file atomic write | Guarded: only after all preconditions pass; os.replace ensures no partial state |
| webapp.py -> app_ctx (in-process) | Trusted read-only access to version/commit |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-46-01 | Tampering | CSRF forgery of POST /api/update/* | mitigate | `csrf_middleware` registered in `create_webapp` via `web.Application(middlewares=[csrf_middleware, ...])`. Task 1 asserts middleware presence. |
| T-46-02 | DoS | Parallel Install -> corrupted state | mitigate | `update_start_handler` calls `is_update_running()` first; on True, audit-logs "409_conflict" and returns HTTP 409. Same in `update_rollback_handler`. |
| T-46-03 | DoS | Flood of Install attempts | mitigate | Module-level `_rate_limiter = RateLimiter()` checked per request; 429 + `Retry-After: <int>` on second attempt within 60s. |
| T-46-04 | Repudiation | Missing audit trail | mitigate | Every path (accepted/409/429/422) calls `audit_log_append`. Task 2 verifies all four outcome codes appear. |
| T-46-05 | Tampering | Trigger file partial write | mitigate | Reuses Phase 45 `write_trigger()` which does `open(tmp) -> fsync -> os.replace(final)`. No custom atomic logic. |
| T-46-07 | Spoofing | Stale tab acts on pre-update state | mitigate (partial) | `GET /api/version` returns current {version, commit}; frontend (Plan 46-03) reloads on mismatch. |
</threat_model>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Wave 0 test scaffold — tests/test_updater_webapp_routes.py new cases</name>
  <files>tests/test_updater_webapp_routes.py</files>
  <read_first>
    - tests/test_updater_webapp_routes.py (existing file — extend, do NOT replace)
    - tests/test_updater_start_endpoint.py (reference for /api/update/start test pattern)
    - src/pv_inverter_proxy/webapp.py lines 397-556, 2329-2391 (existing update_start_handler, create_webapp, route table)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-01-security-belt-PLAN.md (contracts this plan consumes)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-20, D-21, D-27, D-41
  </read_first>
  <behavior>
    Extend the existing `tests/test_updater_webapp_routes.py` with new test functions (one per behavior). Existing tests MUST continue to pass; only ADD new cases.

    Required new test functions (exact names):
    - test_csrf_middleware_registered_on_app
    - test_progress_broadcaster_started_on_app_startup
    - test_version_endpoint_returns_version_and_commit
    - test_version_endpoint_no_csrf_needed (GET is exempt)
    - test_update_status_endpoint_returns_current_and_history
    - test_update_check_endpoint_calls_scheduler_check_once
    - test_update_check_endpoint_returns_available_flag
    - test_update_start_returns_202_under_100ms (measure wall clock, must be < 0.1s)
    - test_update_start_without_csrf_cookie_returns_422
    - test_update_start_with_mismatched_csrf_returns_422
    - test_update_start_with_valid_csrf_returns_202
    - test_update_start_writes_trigger_file_atomically
    - test_update_start_second_attempt_within_60s_returns_429
    - test_update_start_429_includes_retry_after_header
    - test_update_start_when_phase_running_returns_409
    - test_update_start_audit_log_accepted_outcome
    - test_update_start_audit_log_429_outcome
    - test_update_start_audit_log_409_outcome
    - test_update_start_audit_log_422_outcome
    - test_update_rollback_writes_previous_sentinel_trigger
    - test_update_rollback_requires_csrf
    - test_update_rollback_when_phase_running_returns_409
    - test_update_rollback_rate_limited_with_start (shared limiter bucket)
    - test_existing_update_start_endpoint_still_exposed (regression)
    - test_phase_order_js_matches_python_phases (parses PHASE_ORDER from src/pv_inverter_proxy/static/software_page.js via regex, JSON-parses it, compares sorted list to sorted list from pv_inverter_proxy.updater_root.status_writer.PHASES; asserts equality with diff on mismatch — prevents JS/Python phase-name drift)
  </behavior>
  <action>
    Open `tests/test_updater_webapp_routes.py`. Do NOT delete existing tests. At the end of the file, add the new test functions.

    Use the project's existing aiohttp test client fixture. If the existing file uses `aiohttp_client`, reuse that. Provide fixtures for:
    - `tmp_status_path`: temp file the tests can monkeypatch into updater.status.load_status via `monkeypatch.setattr`
    - `tmp_trigger_path`: temp file for trigger writes
    - `tmp_audit_path`: temp file for audit log
    - `csrf_client`: an aiohttp test client that has performed a GET / first so the pvim_csrf cookie is seeded; exposes `client.csrf_token` and automatically includes `X-CSRF-Token` on POSTs

    For `test_update_start_returns_202_under_100ms`:
    ```python
    async def test_update_start_returns_202_under_100ms(csrf_client, tmp_status_path, tmp_trigger_path, monkeypatch):
        monkeypatch.setattr("pv_inverter_proxy.webapp.TRIGGER_PATH", tmp_trigger_path)  # adjust if const name differs
        # Force phase=idle so the guard passes
        fake_status = make_idle_status()
        monkeypatch.setattr("pv_inverter_proxy.updater.security.load_status", lambda *a, **k: fake_status)
        import time
        t0 = time.monotonic()
        resp = await csrf_client.post("/api/update/start", json={"target_sha": "abc123"})
        dt = time.monotonic() - t0
        assert resp.status == 202
        assert dt < 0.1, f"start latency {dt*1000:.1f}ms exceeds 100ms budget (D-20)"
    ```

    For `test_update_start_writes_trigger_file_atomically`: after the 202, assert `tmp_trigger_path.exists()` and the JSON payload has `op="update"`, `target_sha`, `nonce`, `requested_at` ISO 8601 UTC.

    For rate-limit tests: override the module-level `_rate_limiter` with a fresh `RateLimiter(clock=FakeClock())` so tests control time.

    For audit-log tests: override `AUDIT_LOG_PATH` via `monkeypatch.setattr("pv_inverter_proxy.updater.security.AUDIT_LOG_PATH", tmp_audit_path)`. After the POST, read the file and assert JSONL lines contain the expected outcome string.

    For `test_progress_broadcaster_started_on_app_startup`: build the app via `create_webapp(...)` with test fixtures, then assert `app.get("progress_broadcaster")` is not None (the APP_KEY from Plan 46-02).

    For `test_csrf_middleware_registered_on_app`:
    ```python
    async def test_csrf_middleware_registered_on_app():
        app = await create_webapp(...)
        from pv_inverter_proxy.updater.security import csrf_middleware
        names = [getattr(m, "__name__", str(m)) for m in app.middlewares]
        assert any("csrf_middleware" in n for n in names)
    ```

    Tests MUST be initially failing with either ImportError (missing helpers) OR AssertionError (missing behavior). That is the RED state.
  </action>
  <acceptance_criteria>
    - `grep -c "^async def test_\|^def test_" tests/test_updater_webapp_routes.py` increased by >= 25
    - `grep -q "test_update_start_returns_202_under_100ms" tests/test_updater_webapp_routes.py`
    - `grep -q "test_update_rollback_writes_previous_sentinel_trigger" tests/test_updater_webapp_routes.py`
    - `grep -q "test_csrf_middleware_registered_on_app" tests/test_updater_webapp_routes.py`
    - `grep -q "test_version_endpoint_returns_version_and_commit" tests/test_updater_webapp_routes.py`
    - `grep -q "test_update_start_audit_log_accepted_outcome" tests/test_updater_webapp_routes.py`
    - `grep -q "test_update_check_endpoint_calls_scheduler_check_once" tests/test_updater_webapp_routes.py`
    - `grep -q "def test_phase_order_js_matches_python_phases" tests/test_updater_webapp_routes.py`
    - `pytest tests/test_updater_webapp_routes.py -x -q --collect-only` exits 0 (tests collectible; existing tests still collect)
    - `pytest tests/test_updater_webapp_routes.py -x -q -k "test_update_start_returns_202_under_100ms or test_csrf_middleware_registered_on_app or test_version_endpoint_returns_version_and_commit" 2>&1 | grep -qE "FAILED|ERROR"` (new tests are RED before Task 2)
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_webapp_routes.py -x -q --collect-only 2>&1 | grep -q "test_update_start_returns_202_under_100ms"</automated>
  </verify>
  <done>New test cases added to the existing file, initially failing or erroring, contract for every new route locked in.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire security belt + progress broadcaster + new routes into webapp.py</name>
  <files>src/pv_inverter_proxy/webapp.py</files>
  <read_first>
    - src/pv_inverter_proxy/webapp.py lines 1-30 (imports section)
    - src/pv_inverter_proxy/webapp.py lines 246-556 (existing _derive_health_payload + update handlers)
    - src/pv_inverter_proxy/webapp.py lines 2329-2391 (create_webapp + route table — all edits land near here)
    - src/pv_inverter_proxy/updater/security.py (Plan 46-01 output — the contracts this task consumes)
    - src/pv_inverter_proxy/updater/progress.py (Plan 46-02 output)
    - src/pv_inverter_proxy/updater/trigger.py (TriggerPayload, write_trigger, generate_nonce, now_iso_utc)
    - src/pv_inverter_proxy/updater/status.py (load_status, status serialization)
    - src/pv_inverter_proxy/__main__.py lines 511-537 (existing scheduler wiring — for check_once reference)
    - tests/test_updater_webapp_routes.py (the red tests from Task 1 are the contract)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-03, D-20, D-21, D-27, D-41
  </read_first>
  <behavior>
    Implement the webapp.py changes so ALL Task 1 tests pass plus all existing tests remain green. Small, surgical edits only — do NOT grow webapp.py beyond the new handlers + middleware registration.
  </behavior>
  <action>
    Edit `src/pv_inverter_proxy/webapp.py` as follows:

    **(1) Imports** (add near existing updater imports, ~line 25-30):
    ```python
    from pv_inverter_proxy.updater.security import (
        csrf_middleware,
        RateLimiter,
        is_update_running,
        audit_log_append,
        IDLE_PHASES,
    )
    from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster
    from pv_inverter_proxy.updater.trigger import (
        TriggerPayload, write_trigger, generate_nonce, now_iso_utc,
    )
    from pv_inverter_proxy.updater.status import load_status
    ```

    **(2) Module-level rate limiter** (near other module-level state):
    ```python
    _update_rate_limiter = RateLimiter()  # single instance shared by /start and /rollback
    ```

    **(3) Helper: log_and_respond**
    A small helper keeps the handler tight:
    ```python
    async def _log_and_respond(
        request: web.Request,
        outcome: str,
        status: int,
        body: dict,
        *,
        extra_headers: dict | None = None,
    ) -> web.Response:
        try:
            await audit_log_append(
                ip=request.remote or "unknown",
                user_agent=request.headers.get("User-Agent", ""),
                outcome=outcome,  # type: ignore[arg-type]
            )
        except Exception:
            pass  # never block the response on audit failure
        headers = extra_headers or {}
        return web.json_response(body, status=status, headers=headers)
    ```

    **(4) REPLACE existing update_start_handler body** (Phase 45 version at line ~397). Preserve the function signature and docstring; replace the body with the following ordered pipeline. The existing Phase 45 code already validates the request body; keep that validation but add the four new guards BEFORE the trigger write.

    Handler pipeline (per D-20) — the sequence is mandatory for the <100ms latency requirement:
    ```python
    async def update_start_handler(request: web.Request) -> web.Response:
        # Phase 46: CSRF is already enforced by csrf_middleware at this point
        # because middleware runs before the handler. If we got here, CSRF is OK.
        # The 422 audit log is handled inline below as a safety net if middleware
        # were ever bypassed.

        # (a) Rate limit check
        accepted, retry_after = _update_rate_limiter.check(request.remote or "unknown")
        if not accepted:
            return await _log_and_respond(
                request,
                "429_rate_limited",
                429,
                {"error": "rate_limited", "retry_after": retry_after},
                extra_headers={"Retry-After": str(retry_after)},
            )

        # (b) Concurrent guard — status file is source of truth (D-10, D-11)
        running, phase = is_update_running()
        if running:
            return await _log_and_respond(
                request,
                "409_conflict",
                409,
                {"error": "update_in_progress", "phase": phase},
            )

        # (c) Parse + validate body (reuse existing Phase 45 validation)
        try:
            body = await request.json()
        except Exception:
            return await _log_and_respond(
                request,
                "409_conflict",  # closest existing outcome for bad_request; see Task note below
                400,
                {"error": "invalid_json"},
            )
        target_sha = (body or {}).get("target_sha") or "HEAD"

        # (d) Atomic trigger write (D-20, D-21) — reuses Phase 45 write_trigger
        try:
            payload = TriggerPayload(
                op="update",
                target_sha=target_sha,
                requested_at=now_iso_utc(),
                requested_by="webapp",  # Phase 46: consider widening later
                nonce=generate_nonce(),
            )
            write_trigger(payload)
        except Exception as exc:
            return await _log_and_respond(
                request,
                "409_conflict",
                500,
                {"error": "trigger_write_failed", "detail": str(exc)},
            )

        # (e) Audit log accepted + maintenance-mode broadcast (from Phase 45)
        # Maintenance mode + WS update_in_progress broadcast from Phase 45 stays intact.
        await broadcast_update_in_progress(request.app)
        return await _log_and_respond(
            request,
            "accepted",
            202,
            {"accepted": True, "nonce": payload.nonce},
        )
    ```
    NOTE: the Phase 45 maintenance-mode entry (SAFETY-09) happens BEFORE `write_trigger`. Executor must check the existing update_start_handler for a maintenance_mode.enter() call and preserve its ordering per Phase 45 note: maintenance mode enters + broadcasts BEFORE write_trigger so Venus OS sees DEVICE_BUSY on its very next poll (see STATE.md line 87). If the existing handler has that pattern, keep it in step (d).

    NOTE on 400: the audit outcome enum is exactly {accepted, 409_conflict, 429_rate_limited, 422_invalid_csrf}. For a truly bad request body, return 400 but do NOT audit-log it (not in enum). Or add a 5th outcome to security.py — DO NOT. Keep the enum closed per D-15; on bad JSON return 400 without audit. Update the `_log_and_respond` helper to skip audit when outcome is None.

    **(5) NEW handler: update_rollback_handler** (per D-03):
    ```python
    async def update_rollback_handler(request: web.Request) -> web.Response:
        accepted, retry_after = _update_rate_limiter.check(request.remote or "unknown")
        if not accepted:
            return await _log_and_respond(
                request, "429_rate_limited", 429,
                {"error": "rate_limited", "retry_after": retry_after},
                extra_headers={"Retry-After": str(retry_after)},
            )
        running, phase = is_update_running()
        if running:
            return await _log_and_respond(
                request, "409_conflict", 409,
                {"error": "update_in_progress", "phase": phase},
            )
        try:
            payload = TriggerPayload(
                op="rollback",
                target_sha="previous",   # D-03 sentinel
                requested_at=now_iso_utc(),
                requested_by="webapp",
                nonce=generate_nonce(),
            )
            write_trigger(payload)
        except Exception as exc:
            return web.json_response({"error": "trigger_write_failed", "detail": str(exc)}, status=500)
        await broadcast_update_in_progress(request.app)
        return await _log_and_respond(request, "accepted", 202, {"accepted": True, "nonce": payload.nonce})
    ```

    **(6) NEW handler: version_handler** (per D-27):
    ```python
    async def version_handler(request: web.Request) -> web.Response:
        app_ctx = request.app["app_ctx"]
        return web.json_response({
            "version": getattr(app_ctx, "current_version", None),
            "commit": getattr(app_ctx, "current_commit", None),
        })
    ```

    **(7) NEW handler: update_status_handler**:
    ```python
    async def update_status_handler(request: web.Request) -> web.Response:
        try:
            status = load_status()
        except Exception:
            return web.json_response({"current": None, "history": []})
        # Serialize the status object — adjust based on the real UpdateStatus type.
        # If it's a dataclass: dataclasses.asdict(status)
        # If it's a TypedDict / dict: return as-is
        from dataclasses import is_dataclass, asdict
        if is_dataclass(status):
            return web.json_response(asdict(status))
        if hasattr(status, "to_dict"):
            return web.json_response(status.to_dict())
        return web.json_response(status)
    ```

    **(8) NEW handler: update_check_handler** (per UI-02 Check-now button):
    ```python
    async def update_check_handler(request: web.Request) -> web.Response:
        accepted, retry_after = _update_rate_limiter.check(request.remote or "unknown")
        if not accepted:
            return await _log_and_respond(
                request, "429_rate_limited", 429,
                {"error": "rate_limited", "retry_after": retry_after},
                extra_headers={"Retry-After": str(retry_after)},
            )
        scheduler = request.app.get("update_scheduler")
        if scheduler is None:
            return web.json_response({"error": "scheduler_not_running"}, status=503)
        try:
            result = await scheduler.check_once()
        except Exception as exc:
            return web.json_response({"error": "check_failed", "detail": str(exc)}, status=500)
        available = bool(getattr(result, "available", False)) if result is not None else False
        latest = getattr(result, "latest_version", None) if result is not None else None
        return web.json_response({"checked": True, "available": available, "latest_version": latest})
    ```
    NOTE: if `scheduler.check_once` does not exist on the Phase 44 scheduler, add a thin method that calls the existing scheduler logic. Executor checks `updater/scheduler.py` first.

    **(9) Middleware registration in create_webapp** (line ~2329):
    Find the existing `app = web.Application(...)` line. Change it to include csrf_middleware as the FIRST middleware (so it runs before any body parsing):
    ```python
    app = web.Application(middlewares=[csrf_middleware])
    ```
    If the existing call already has middlewares, prepend csrf_middleware to the list.

    **(10) Startup + cleanup hooks in create_webapp**:
    ```python
    app.on_startup.append(start_broadcaster)
    app.on_cleanup.append(stop_broadcaster)
    ```

    **(11) Route registration** (line ~2347-2378 route table):
    Add AFTER the existing `/api/update/start` line:
    ```python
    app.router.add_get("/api/version", version_handler)
    app.router.add_get("/api/update/status", update_status_handler)
    app.router.add_post("/api/update/rollback", update_rollback_handler)
    app.router.add_post("/api/update/check", update_check_handler)
    ```

    **(12) Regression: do NOT remove or rename existing routes or handlers.** The existing `/api/update/start` route stays at its current path; only the handler body is extended.

    Run the full test suite:
    ```
    pytest tests/test_updater_webapp_routes.py tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_start_endpoint.py -x -q
    ```
    All new tests from Task 1 must pass. All existing tests in the four files must continue to pass.

    Deploy: this plan does NOT auto-deploy (Plan 46-05 gates the deploy).
  </action>
  <acceptance_criteria>
    - `grep -q "from pv_inverter_proxy.updater.security import" src/pv_inverter_proxy/webapp.py`
    - `grep -q "csrf_middleware" src/pv_inverter_proxy/webapp.py`
    - `grep -q "from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster" src/pv_inverter_proxy/webapp.py`
    - `grep -q "_update_rate_limiter = RateLimiter" src/pv_inverter_proxy/webapp.py`
    - `grep -q "is_update_running" src/pv_inverter_proxy/webapp.py`
    - `grep -q "audit_log_append" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def version_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def update_rollback_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def update_status_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def update_check_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q 'target_sha="previous"' src/pv_inverter_proxy/webapp.py`
    - `grep -q '"/api/version"' src/pv_inverter_proxy/webapp.py`
    - `grep -q '"/api/update/rollback"' src/pv_inverter_proxy/webapp.py`
    - `grep -q '"/api/update/status"' src/pv_inverter_proxy/webapp.py`
    - `grep -q '"/api/update/check"' src/pv_inverter_proxy/webapp.py`
    - `grep -q "middlewares=\[csrf_middleware" src/pv_inverter_proxy/webapp.py`
    - `grep -q "app.on_startup.append(start_broadcaster)" src/pv_inverter_proxy/webapp.py`
    - `grep -q "app.on_cleanup.append(stop_broadcaster)" src/pv_inverter_proxy/webapp.py`
    - `grep -q 'Retry-After' src/pv_inverter_proxy/webapp.py`
    - `pytest tests/test_updater_webapp_routes.py -x -q` exits 0 (all new + existing pass)
    - `pytest tests/test_updater_security.py tests/test_updater_progress.py -x -q` exits 0 (Plans 46-01 + 46-02 still green)
    - `pytest tests/test_updater_start_endpoint.py -x -q` exits 0 (Phase 45 regression)
    - `python -c "import ast; tree = ast.parse(open('src/pv_inverter_proxy/webapp.py').read()); fns = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}; assert 'version_handler' in fns; assert 'update_rollback_handler' in fns; assert 'update_status_handler' in fns; assert 'update_check_handler' in fns; assert 'update_start_handler' in fns"` exits 0
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_webapp_routes.py tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_start_endpoint.py -x -q</automated>
  </verify>
  <done>webapp.py has csrf_middleware registered, module-level RateLimiter, 4 new handlers, 4 new routes, progress broadcaster lifecycle hooks, hardened update_start_handler with 4-guard pipeline, and all tests pass including the <100ms latency regression.</done>
</task>

</tasks>

<verification>
- `pytest tests/test_updater_webapp_routes.py -x -q` — all new + existing green
- `pytest -x -q` (full suite) — no regressions
- grep checks for all 4 new routes and handlers present
- <100ms latency budget verified by `test_update_start_returns_202_under_100ms`
</verification>

<success_criteria>
UI-02 (partial): /api/update/status and /api/update/check endpoints exist and return expected shapes.
UI-07 (partial): /api/update/rollback endpoint exists and writes a trigger with target_sha="previous".
UI-08 (partial): /api/version endpoint returns current version+commit from app_ctx.
SEC-01 (wired): CSRF middleware registered in create_webapp and enforced on all /api/update/* mutating methods.
SEC-02 (wired): Second POST within 60s returns 429 + Retry-After header.
SEC-03 (wired): Concurrent update returns 409 with current phase in body.
SEC-04 (wired): Every outcome written to /var/lib/pv-inverter-proxy/update-audit.log.
D-20 verified: POST /api/update/start returns 202 in < 100ms on happy path (test enforces this).
D-21 verified: Trigger file written via Phase 45 atomic write_trigger (no new atomic code in webapp.py).
</success_criteria>

<output>
After completion, create `.planning/phases/46-ui-wiring-end-to-end-flow/46-04-SUMMARY.md` using `@$HOME/.claude/get-shit-done/templates/summary.md`.
</output>
