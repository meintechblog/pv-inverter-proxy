---
phase: 46-ui-wiring-end-to-end-flow
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/updater/security.py
  - tests/test_updater_security.py
autonomous: true
requirements: [SEC-01, SEC-02, SEC-03, SEC-04]
threat_refs: [T-46-01, T-46-02, T-46-03, T-46-04, T-46-08]
decisions_implemented: [D-07, D-08, D-09, D-10, D-11, D-12, D-13, D-14, D-15, D-16, D-17, D-18, D-19, D-40]

must_haves:
  truths:
    - "POST /api/update/* without a csrf_token cookie returns HTTP 422 csrf_missing"
    - "POST /api/update/* with cookie != X-CSRF-Token header returns HTTP 422 csrf_mismatch"
    - "GET requests without csrf_token cookie receive a Set-Cookie with SameSite=Strict"
    - "CSRF comparison uses secrets.compare_digest (timing-safe)"
    - "Second POST from same request.remote within 60s returns HTTP 429 + integer Retry-After header"
    - "POST rejected with HTTP 409 when current_phase(load_status()) not in IDLE_PHASES"
    - "Every decision (accepted|409_conflict|429_rate_limited|422_invalid_csrf) writes one JSONL line to /var/lib/pv-inverter-proxy/update-audit.log"
    - "Audit log directory is created lazily at mode 0o750; file mode is 0o640"
  artifacts:
    - path: "src/pv_inverter_proxy/updater/security.py"
      provides: "csrf_middleware, rate_limit_check, concurrent_guard, audit_log_append, IDLE_PHASES"
      min_lines: 200
    - path: "tests/test_updater_security.py"
      provides: "SEC-01..SEC-04 unit tests"
      min_lines: 250
  key_links:
    - from: "security.py::concurrent_guard"
      to: "updater.status::load_status + current_phase"
      via: "direct function call (status file is source of truth, NOT asyncio.Lock)"
      pattern: "from pv_inverter_proxy.updater.status import (load_status|current_phase)"
    - from: "security.py::audit_log_append"
      to: "/var/lib/pv-inverter-proxy/update-audit.log"
      via: "asyncio.Lock + json.dumps + file write in thread executor"
      pattern: "AUDIT_LOG_PATH.*/var/lib/pv-inverter-proxy/update-audit.log"
---

<objective>
Build the Phase 46 security belt: CSRF middleware (double-submit cookie), in-memory rate limiter (sliding 60s), concurrent-update guard (reads update-status.json), and JSONL audit log writer.

Purpose: Every mutating update endpoint added in Plan 46-04 must be protected by these four primitives before it is exposed. SEC-01..SEC-04 are mitigations for T-46-01 (CSRF), T-46-02 (concurrent DoS), T-46-03 (rate-limit DoS), T-46-04 (repudiation), and T-46-08 (audit log info disclosure).

Output: A self-contained `updater/security.py` module with no webapp.py coupling (it will be wired in Plan 46-04), plus a comprehensive pytest suite that exercises all four primitives with monkeypatched time and status helpers.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md
@src/pv_inverter_proxy/updater/status.py
@src/pv_inverter_proxy/updater/trigger.py

<interfaces>
<!-- Existing Phase 45 contracts this plan depends on. -->

From src/pv_inverter_proxy/updater/status.py:
```python
PHASE_IDLE = "idle"
PHASE_DONE = "done"
PHASE_ROLLBACK_DONE = "rollback_done"  # verify exact name; if missing use PHASE_ROLLBACK_FAILED sentinel per D-10
PHASE_ROLLBACK_FAILED = "rollback_failed"

def load_status(path: Path | None = None) -> UpdateStatus: ...
def current_phase(status: UpdateStatus) -> str: ...
```

Required new exports from updater/security.py:
```python
IDLE_PHASES: frozenset[str] = frozenset({"idle", "done", "rollback_done", "rollback_failed"})
CSRF_COOKIE_NAME: str = "pvim_csrf"
CSRF_HEADER_NAME: str = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE: int = 86400
RATE_LIMIT_WINDOW_SECONDS: int = 60
AUDIT_LOG_PATH: Path = Path("/var/lib/pv-inverter-proxy/update-audit.log")

@web.middleware
async def csrf_middleware(request: web.Request, handler) -> web.StreamResponse: ...

class RateLimiter:
    def __init__(self, window_seconds: int = 60, clock: Callable[[], float] = time.monotonic) -> None: ...
    def check(self, ip: str) -> tuple[bool, int]:  # (accepted, retry_after_seconds)

def is_update_running(status_path: Path | None = None) -> tuple[bool, str]:  # (running, current_phase_string)

async def audit_log_append(
    *,
    ip: str,
    user_agent: str,
    outcome: Literal["accepted", "409_conflict", "429_rate_limited", "422_invalid_csrf"],
    log_path: Path = AUDIT_LOG_PATH,
    clock: Callable[[], str] | None = None,
) -> None: ...
```
</interfaces>
</context>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser -> aiohttp POST /api/update/* | Untrusted user input crosses here; CSRF + rate limit + concurrent guard enforced at this boundary |
| webapp process (pv-proxy uid) -> update-audit.log file | Single writer; file mode 0o640 owner pv-proxy:pv-proxy protects confidentiality from other local users |
| webapp process -> update-status.json (read-only) | Webapp NEVER writes status file; only reads via updater.status.load_status |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-46-01 | Tampering | POST /api/update/* via CSRF from a rogue same-LAN tab | mitigate | Double-submit cookie: secrets.token_urlsafe(32), SameSite=Strict, secrets.compare_digest of cookie vs X-CSRF-Token header; reject with 422 on any mismatch. Implemented in `csrf_middleware`. |
| T-46-02 | Denial of Service | Parallel Install clicks corrupt state / spawn duplicate updaters | mitigate | `is_update_running()` reads update-status.json via load_status()+current_phase(); when phase not in IDLE_PHASES -> 409. Status file is single source of truth (D-11 rejects asyncio.Lock). |
| T-46-03 | Denial of Service | Flood of Install POSTs from compromised tab | mitigate | In-memory `RateLimiter` keyed on `request.remote`, 60s sliding window, 429 + integer `Retry-After` seconds per RFC 9110. |
| T-46-04 | Repudiation | "I never pressed Install" / missing audit trail | mitigate | `audit_log_append` writes JSONL to /var/lib/pv-inverter-proxy/update-audit.log on EVERY outcome (accepted + all rejection types). Fields: ts, ip, ua, outcome. |
| T-46-08 | Information Disclosure | Audit log readable by unprivileged local users | mitigate | Parent dir mode 0o750 (lazy mkdir), file mode 0o640, both created lazily in first `audit_log_append` call via os.chmod after open. |
</threat_model>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Wave 0 test scaffold — tests/test_updater_security.py</name>
  <files>tests/test_updater_security.py</files>
  <read_first>
    - src/pv_inverter_proxy/updater/status.py (for PHASE_* constants and load_status signature)
    - tests/test_updater_start_endpoint.py (for aiohttp test client pattern used in this project)
    - tests/test_updater_status.py (for monkeypatching load_status in tests)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-07..D-19
  </read_first>
  <behavior>
    The test file must declare (initially failing) tests for every acceptance criterion in Task 2. Each test imports from `pv_inverter_proxy.updater.security` which does NOT yet exist — all tests MUST fail with ImportError before Task 2 lands.

    Required test functions (exact names, will be grepped in acceptance):
    - test_csrf_rejects_missing_cookie
    - test_csrf_rejects_missing_header
    - test_csrf_rejects_mismatched_cookie_header
    - test_csrf_accepts_matching_cookie_header
    - test_csrf_cookie_seeded_on_get_without_cookie
    - test_csrf_cookie_not_reseeded_when_present
    - test_csrf_cookie_attributes_samesite_strict_path_root_maxage_86400
    - test_csrf_uses_compare_digest (monkeypatch secrets.compare_digest and verify it was called)
    - test_rate_limit_first_request_accepted
    - test_rate_limit_second_request_within_60s_rejected
    - test_rate_limit_retry_after_is_integer_seconds
    - test_rate_limit_window_resets_after_60s (use injectable clock)
    - test_rate_limit_per_ip_isolation (two different IPs both allowed)
    - test_concurrent_guard_idle_phase_allows (monkeypatch load_status -> phase=idle)
    - test_concurrent_guard_done_phase_allows
    - test_concurrent_guard_rollback_done_phase_allows
    - test_concurrent_guard_rollback_failed_phase_allows
    - test_concurrent_guard_running_phase_blocks (phase=pip_install)
    - test_concurrent_guard_restarting_phase_blocks
    - test_audit_log_writes_jsonl_line_per_call
    - test_audit_log_outcomes_all_four_values (accepted, 409_conflict, 429_rate_limited, 422_invalid_csrf)
    - test_audit_log_creates_parent_dir_lazily_with_mode_0o750
    - test_audit_log_file_mode_is_0o640
    - test_audit_log_each_line_is_valid_json_with_ts_ip_ua_outcome_keys
    - test_audit_log_concurrent_writes_serialized (10 asyncio.gather tasks appending, verify 10 valid JSONL lines, no truncation)

    Every test uses `tmp_path` for audit log location (AUDIT_LOG_PATH override) and monkeypatches `updater.status.load_status` where a concurrent-guard test needs a particular phase.
  </behavior>
  <action>
    Create `tests/test_updater_security.py` with the 25 test functions listed above. Each test must be a concrete, runnable pytest case — no TODO stubs. Use `pytest-asyncio` (`@pytest.mark.asyncio` or `asyncio_mode=auto` from pyproject.toml).

    For aiohttp middleware tests, use `aiohttp.test_utils.TestClient` + `aiohttp.web.Application([csrf_middleware])` with a dummy POST handler that echoes `{"ok": True}` on `/api/update/ping`. For GET-seeding tests use a dummy GET handler on `/api/ping`.

    For the rate-limit tests inject a fake clock: `class FakeClock: def __init__(self, t=0.0): self.t=t\n    def __call__(self): return self.t` and instantiate `RateLimiter(window_seconds=60, clock=fake_clock)`. Advance time via `fake_clock.t += 30` etc.

    For concurrent-guard tests, monkeypatch via `monkeypatch.setattr("pv_inverter_proxy.updater.security.load_status", fake_load_status)` where `fake_load_status` returns a simple object whose `current_phase()` is driven by the test. The module under test must import `load_status` and `current_phase` at module scope so monkeypatching works.

    For audit-log tests, override AUDIT_LOG_PATH via a fixture:
    ```python
    @pytest.fixture
    def audit_log_path(tmp_path, monkeypatch):
        p = tmp_path / "lib" / "pv-inverter-proxy" / "update-audit.log"
        monkeypatch.setattr("pv_inverter_proxy.updater.security.AUDIT_LOG_PATH", p)
        return p
    ```

    The test file MUST fail at collection time (ImportError) until Task 2 creates the module. That failure IS the RED state.
  </action>
  <acceptance_criteria>
    - File `tests/test_updater_security.py` exists
    - `grep -c "^def test_" tests/test_updater_security.py` >= 25
    - `grep -q "test_csrf_rejects_missing_cookie" tests/test_updater_security.py`
    - `grep -q "test_csrf_uses_compare_digest" tests/test_updater_security.py`
    - `grep -q "test_rate_limit_retry_after_is_integer_seconds" tests/test_updater_security.py`
    - `grep -q "test_concurrent_guard_done_phase_allows" tests/test_updater_security.py`
    - `grep -q "test_audit_log_concurrent_writes_serialized" tests/test_updater_security.py`
    - `grep -q "test_audit_log_file_mode_is_0o640" tests/test_updater_security.py`
    - Running `pytest tests/test_updater_security.py --collect-only` exits non-zero (ImportError on `pv_inverter_proxy.updater.security`) — this is the expected RED state before Task 2
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_security.py --collect-only 2>&1 | grep -qE "(ImportError|ModuleNotFoundError).*updater.security"</automated>
  </verify>
  <done>The test file is committed as a failing red test; import of `pv_inverter_proxy.updater.security` is the only reason tests fail.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement updater/security.py — CSRF, rate limit, concurrent guard, audit log</name>
  <files>src/pv_inverter_proxy/updater/security.py</files>
  <read_first>
    - src/pv_inverter_proxy/updater/status.py (full file — need load_status, current_phase, PHASE_* constants)
    - src/pv_inverter_proxy/updater/trigger.py (for style reference and os.fsync atomic write pattern)
    - tests/test_updater_security.py (the red tests from Task 1 are the exact contract)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-07..D-19, D-40
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md Patterns 1, 2, 3, 5 and Pitfalls 1, 2, 3, 6, 9
  </read_first>
  <behavior>
    The module IS the contract defined in the `<interfaces>` block above. Tests from Task 1 pin every behavior. Implementation satisfies all 25 tests with zero flakiness.
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/security.py` with the following EXACT shape. Do NOT add extra features not listed here.

    1. Module docstring: "Phase 46 security belt: CSRF double-submit cookie, rate limiter, concurrent-update guard, and JSONL audit log. Per 46-CONTEXT.md D-07..D-19."

    2. Imports:
    ```python
    from __future__ import annotations
    import asyncio
    import json
    import os
    import secrets
    import time
    from dataclasses import dataclass, field
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Callable, Literal

    import structlog
    from aiohttp import web

    from pv_inverter_proxy.updater.status import load_status, current_phase
    ```

    3. Constants (per D-07..D-19):
    ```python
    CSRF_COOKIE_NAME = "pvim_csrf"
    CSRF_HEADER_NAME = "X-CSRF-Token"
    CSRF_COOKIE_MAX_AGE = 86400
    RATE_LIMIT_WINDOW_SECONDS = 60
    IDLE_PHASES: frozenset[str] = frozenset({"idle", "done", "rollback_done", "rollback_failed"})
    AUDIT_LOG_PATH = Path("/var/lib/pv-inverter-proxy/update-audit.log")
    AUDIT_LOG_DIR_MODE = 0o750
    AUDIT_LOG_FILE_MODE = 0o640
    _logger = structlog.get_logger(__name__)
    _audit_lock = asyncio.Lock()
    AuditOutcome = Literal["accepted", "409_conflict", "429_rate_limited", "422_invalid_csrf"]
    ```

    4. CSRF middleware (per D-07, D-08, D-09):
    ```python
    @web.middleware
    async def csrf_middleware(request: web.Request, handler):
        needs_check = (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and request.path.startswith("/api/update/")
        )
        if needs_check:
            cookie_tok = request.cookies.get(CSRF_COOKIE_NAME)
            header_tok = request.headers.get(CSRF_HEADER_NAME)
            if not cookie_tok or not header_tok:
                return web.json_response({"error": "csrf_missing"}, status=422)
            if not secrets.compare_digest(cookie_tok, header_tok):
                return web.json_response({"error": "csrf_mismatch"}, status=422)
        response = await handler(request)
        if CSRF_COOKIE_NAME not in request.cookies:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                secrets.token_urlsafe(32),
                max_age=CSRF_COOKIE_MAX_AGE,
                path="/",
                samesite="Strict",
                httponly=False,
                secure=False,
            )
        return response
    ```
    CRITICAL: cookie seeding happens on the RESPONSE path for any request that lacked the cookie — including POSTs that already rejected, so the next attempt can succeed after a reload (Pitfall 1 mitigation).

    5. `RateLimiter` class (per D-12, D-13, D-14, Pitfall 2, Pitfall 9):
    ```python
    class RateLimiter:
        def __init__(self, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
            self._window = window_seconds
            self._clock = clock
            self._last_seen: dict[str, float] = {}

        def check(self, ip: str) -> tuple[bool, int]:
            """Returns (accepted, retry_after_seconds). retry_after is 0 when accepted."""
            now = self._clock()
            # Lazy eviction of stale entries
            stale = [k for k, t in self._last_seen.items() if now - t >= self._window]
            for k in stale:
                del self._last_seen[k]
            normalized = _normalize_ip(ip)
            last = self._last_seen.get(normalized)
            if last is None or now - last >= self._window:
                self._last_seen[normalized] = now
                return True, 0
            retry_after = max(1, int(self._window - (now - last)))
            return False, retry_after
    ```
    Add `_normalize_ip(raw: str) -> str` that strips `::ffff:` IPv4-mapped prefix and handles None by returning `"unknown"` (Pitfall 2).

    6. Concurrent guard (per D-10, D-11, Pitfall 6):
    ```python
    def is_update_running(status_path: Path | None = None) -> tuple[bool, str]:
        """Returns (running, current_phase_string). Never raises."""
        try:
            status = load_status(status_path) if status_path is not None else load_status()
        except Exception:
            _logger.warning("status_load_failed_concurrent_guard_fails_open")
            return False, "unknown"
        phase = current_phase(status)
        return phase not in IDLE_PHASES, phase
    ```
    Fail open on status load error (consistent with NonceDedupStore behavior from Phase 45, STATE.md line 82).

    7. Audit log writer (per D-15..D-19, D-16 mode bits, D-17 async lock, Pitfall 3):
    ```python
    async def audit_log_append(
        *,
        ip: str,
        user_agent: str,
        outcome: AuditOutcome,
        log_path: Path | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        path = log_path if log_path is not None else AUDIT_LOG_PATH
        ts = clock() if clock is not None else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = json.dumps({
            "ts": ts,
            "ip": _normalize_ip(ip),
            "ua": user_agent or "",
            "outcome": outcome,
        }, separators=(",", ":"), ensure_ascii=False) + "\n"
        async with _audit_lock:
            await asyncio.get_running_loop().run_in_executor(None, _append_audit_line, path, line)

    def _append_audit_line(path: Path, line: str) -> None:
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, mode=AUDIT_LOG_DIR_MODE, exist_ok=True)
            try:
                os.chmod(parent, AUDIT_LOG_DIR_MODE)
            except PermissionError:
                pass
        existed = path.exists()
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        if not existed:
            try:
                os.chmod(path, AUDIT_LOG_FILE_MODE)
            except PermissionError:
                pass
    ```

    8. Do NOT import `webapp.py` or register routes here. This module is pure primitives. Plan 46-04 is responsible for wiring `csrf_middleware`, constructing a module-level `RateLimiter` instance, and calling `is_update_running` + `audit_log_append` inside the new update handlers.

    Run `pytest tests/test_updater_security.py -x -q` after writing — ALL 25 tests must pass. If the concurrent-guard tests fail because `load_status` isn't imported at module scope, leave the top-level import in place so monkeypatching works.

    Deploy scope: this plan does NOT deploy to LXC. Plan 46-05 is the auto-deploy gate (per D-42).
  </action>
  <acceptance_criteria>
    - `src/pv_inverter_proxy/updater/security.py` exists
    - `grep -q "CSRF_COOKIE_NAME = \"pvim_csrf\"" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "CSRF_HEADER_NAME = \"X-CSRF-Token\"" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "IDLE_PHASES" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "secrets.compare_digest" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "SameSite=Strict\|samesite=\"Strict\"" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "token_urlsafe(32)" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "RATE_LIMIT_WINDOW_SECONDS = 60" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "0o640" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "0o750" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "/var/lib/pv-inverter-proxy/update-audit.log" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "from pv_inverter_proxy.updater.status import load_status, current_phase" src/pv_inverter_proxy/updater/security.py`
    - `grep -q "asyncio.Lock" src/pv_inverter_proxy/updater/security.py`
    - `! grep -q "asyncio.Lock.*update_in_progress" src/pv_inverter_proxy/updater/security.py` (no asyncio.Lock as source of truth per D-11)
    - `pytest tests/test_updater_security.py -x -q` exits 0 with all 25 tests green
    - `python -c "from pv_inverter_proxy.updater import security; assert callable(security.csrf_middleware); assert callable(security.audit_log_append); assert callable(security.is_update_running); assert security.IDLE_PHASES == frozenset({'idle','done','rollback_done','rollback_failed'})"` exits 0
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_security.py -x -q</automated>
  </verify>
  <done>All 25 SEC-01..SEC-04 tests pass. Module is self-contained (no webapp.py imports). Ready for Plan 46-04 to wire into webapp routes.</done>
</task>

</tasks>

<verification>
- `pytest tests/test_updater_security.py -x -q` — 25/25 green
- `python -c "from pv_inverter_proxy.updater.security import csrf_middleware, RateLimiter, is_update_running, audit_log_append, IDLE_PHASES, CSRF_COOKIE_NAME, AUDIT_LOG_PATH"` exits 0
- Module has ZERO coupling to webapp.py (no `from pv_inverter_proxy import webapp` anywhere)
</verification>

<success_criteria>
SEC-01 verified: CSRF middleware blocks POST /api/update/* without cookie or header, accepts matching cookie+header, seeds cookie on any GET, uses `secrets.compare_digest`.
SEC-02 verified: `RateLimiter.check(ip)` returns `(False, int>=1)` for 2nd request within 60s, resets after 60s.
SEC-03 verified: `is_update_running()` returns True when phase in {trigger_received, backup, extract, pip_install, config_dryrun, restarting, healthcheck, rollback}, False when phase in IDLE_PHASES.
SEC-04 verified: `audit_log_append` writes one JSONL line per call with ts/ip/ua/outcome, serializes concurrent writes, creates parent dir lazily at 0o750, file at 0o640.
</success_criteria>

<output>
After completion, create `.planning/phases/46-ui-wiring-end-to-end-flow/46-01-SUMMARY.md` using `@$HOME/.claude/get-shit-done/templates/summary.md`.
</output>
