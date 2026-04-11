"""Unit tests for GET /api/update/available and broadcast_available_update.

Covers Plan 44-02 CHECK-05 (endpoint response shape) and CHECK-06
(last_check_failed_at surfaced to the UI). Uses aiohttp.test_utils
make_mocked_request so no TCP server is spun up -- the handler is
exercised directly against a mocked Request object.
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.webapp import (
    broadcast_available_update,
    update_available_handler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_ctx():
    """Return (app, ctx) with a populated AppContext ready for handler calls."""
    ctx = AppContext()
    ctx.current_version = "8.0.0"
    ctx.current_commit = "abc123d"
    ctx.available_update = None
    ctx.update_last_check_at = 1712755200.0
    ctx.update_last_check_failed_at = None
    app = web.Application()
    app["app_ctx"] = ctx
    return app, ctx


# ---------------------------------------------------------------------------
# Route handler tests (CHECK-05)
# ---------------------------------------------------------------------------


async def test_update_available_no_update(app_with_ctx):
    """Cold state: version resolved, no release advertised yet."""
    app, ctx = app_with_ctx
    req = make_mocked_request("GET", "/api/update/available", app=app)
    resp = await update_available_handler(req)
    data = json.loads(resp.body.decode())
    assert data["current_version"] == "8.0.0"
    assert data["current_commit"] == "abc123d"
    assert data["available_update"] is None
    assert data["last_check_at"] == 1712755200.0
    assert data["last_check_failed_at"] is None


async def test_update_available_with_update(app_with_ctx):
    """Update is available: full release dict passes through verbatim."""
    app, ctx = app_with_ctx
    ctx.available_update = {
        "latest_version": "v8.1.0",
        "tag_name": "v8.1.0",
        "release_notes": "## Added\n- feature",
        "published_at": "2026-05-01T00:00:00Z",
        "html_url": "https://github.com/meintechblog/pv-inverter-master/releases/tag/v8.1.0",
    }
    req = make_mocked_request("GET", "/api/update/available", app=app)
    resp = await update_available_handler(req)
    data = json.loads(resp.body.decode())
    assert data["available_update"]["latest_version"] == "v8.1.0"
    assert data["available_update"]["tag_name"] == "v8.1.0"
    assert "feature" in data["available_update"]["release_notes"]
    assert data["available_update"]["html_url"].endswith("/v8.1.0")
    assert data["current_version"] == "8.0.0"


async def test_update_available_unknown_version(app_with_ctx):
    """When the running build can't be identified, surface 'unknown' verbatim."""
    app, ctx = app_with_ctx
    ctx.current_version = "unknown"
    ctx.current_commit = None
    req = make_mocked_request("GET", "/api/update/available", app=app)
    resp = await update_available_handler(req)
    data = json.loads(resp.body.decode())
    assert data["current_version"] == "unknown"
    assert data["current_commit"] is None


async def test_update_available_failed_check(app_with_ctx):
    """CHECK-06: last_check_failed_at must be surfaced when set."""
    app, ctx = app_with_ctx
    ctx.update_last_check_failed_at = 1712755500.0
    req = make_mocked_request("GET", "/api/update/available", app=app)
    resp = await update_available_handler(req)
    data = json.loads(resp.body.decode())
    assert data["last_check_failed_at"] == 1712755500.0


async def test_update_available_cold_start(app_with_ctx):
    """Cold start: no check has run yet -- both timestamps None."""
    app, ctx = app_with_ctx
    ctx.update_last_check_at = None
    ctx.update_last_check_failed_at = None
    ctx.available_update = None
    req = make_mocked_request("GET", "/api/update/available", app=app)
    resp = await update_available_handler(req)
    data = json.loads(resp.body.decode())
    assert data["last_check_at"] is None
    assert data["last_check_failed_at"] is None
    assert data["available_update"] is None


# ---------------------------------------------------------------------------
# Broadcast helper tests
# ---------------------------------------------------------------------------


class _FakeWs:
    """Minimal stand-in for aiohttp WebSocketResponse for broadcast tests."""

    def __init__(self, raise_on_send: Exception | None = None) -> None:
        self.sent: list[str] = []
        self.raise_on_send = raise_on_send

    async def send_str(self, payload: str) -> None:
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append(payload)


async def test_broadcast_available_update_no_clients(app_with_ctx):
    """No clients connected -> silent no-op, never touches app_ctx."""
    app, ctx = app_with_ctx
    app["ws_clients"] = set()
    # Should not raise
    await broadcast_available_update(app)


async def test_broadcast_available_update_sends_payload(app_with_ctx):
    """Single WS client receives the full available_update snapshot as JSON."""
    app, ctx = app_with_ctx
    ctx.available_update = {
        "latest_version": "v8.1.0",
        "tag_name": "v8.1.0",
        "release_notes": "notes",
        "published_at": "2026-05-01T00:00:00Z",
        "html_url": "https://github.com/meintechblog/pv-inverter-master/releases/tag/v8.1.0",
    }
    ws = _FakeWs()
    app["ws_clients"] = {ws}
    await broadcast_available_update(app)
    assert len(ws.sent) == 1
    msg = json.loads(ws.sent[0])
    assert msg["type"] == "available_update"
    assert msg["data"]["current_version"] == "8.0.0"
    assert msg["data"]["available_update"]["latest_version"] == "v8.1.0"
    assert msg["data"]["last_check_at"] == 1712755200.0


async def test_broadcast_available_update_prunes_dead_client(app_with_ctx):
    """Clients that raise ConnectionResetError on send must be discarded."""
    app, ctx = app_with_ctx
    dead_ws = _FakeWs(raise_on_send=ConnectionResetError())
    live_ws = _FakeWs()
    clients = {dead_ws, live_ws}
    app["ws_clients"] = clients
    await broadcast_available_update(app)
    assert dead_ws not in clients
    assert live_ws in clients
    assert len(live_ws.sent) == 1


async def test_broadcast_available_update_missing_app_ctx(app_with_ctx):
    """If the app is misconfigured without app_ctx, broadcast must no-op."""
    app, _ctx = app_with_ctx
    app["app_ctx"] = None
    ws = _FakeWs()
    app["ws_clients"] = {ws}
    await broadcast_available_update(app)
    assert ws.sent == []


# ===========================================================================
# Phase 46 Plan 04: Route wiring tests (D-20, D-21, D-27, D-41)
# ---------------------------------------------------------------------------
# These tests pin the integration between Plan 46-01 (security belt) and
# Plan 46-02 (progress broadcaster) with webapp.py's new route table +
# hardened update_start_handler. They must all hold together in one test
# file so the <100ms latency regression stays adjacent to the CSRF / rate
# limit / audit-log coverage.
# ===========================================================================
import re as _re  # noqa: E402
import time as _time  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

import pytest as _pytest  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from pv_inverter_proxy.updater import security as _security_mod  # noqa: E402
from pv_inverter_proxy.updater import trigger as _trigger_mod  # noqa: E402

FULL_SHA = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


class _FakeClock:
    """Monotonic clock used by the rate limiter under test."""

    def __init__(self, start: float = 1_000.0) -> None:
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class _FakeScheduler:
    """Minimal UpdateCheckScheduler stand-in exposing ``check_once``."""

    def __init__(self, result=None, raise_exc: Exception | None = None) -> None:
        self.result = result
        self.raise_exc = raise_exc
        self.calls = 0

    async def check_once(self):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class _FakeReleaseInfo:
    """Minimal duck-typed ReleaseInfo for the check endpoint tests."""

    def __init__(self, *, available: bool, latest_version: str | None) -> None:
        self.available = available
        self.latest_version = latest_version


class _StubAppCtx:
    """Tiny AppContext stand-in for handlers that read current_version."""

    def __init__(
        self,
        *,
        current_version: str | None = "8.0.0",
        current_commit: str | None = "deadbeef",
    ) -> None:
        self.current_version = current_version
        self.current_commit = current_commit
        # Phase 44 fields surfaced by /api/update/available.
        self.available_update = None
        self.update_last_check_at = None
        self.update_last_check_failed_at = None
        # Maintenance-mode entry requires these attrs on the real path;
        # None/default values short-circuit it without crashing.
        self.maintenance_mode = False
        self.maintenance_entered_at = None
        self._slave_ctx = None


@_pytest.fixture
def tmp_trigger_path(tmp_path, monkeypatch):
    """Redirect TRIGGER_FILE_PATH to a tmp file."""
    p = tmp_path / "update-trigger.json"
    monkeypatch.setattr(_trigger_mod, "TRIGGER_FILE_PATH", p)
    return p


@_pytest.fixture
def tmp_audit_path(tmp_path, monkeypatch):
    """Redirect AUDIT_LOG_PATH to a tmp file."""
    p = tmp_path / "audit.log"
    monkeypatch.setattr(_security_mod, "AUDIT_LOG_PATH", p)
    return p


@_pytest.fixture
def fresh_rate_limiter(monkeypatch):
    """Swap the module-level rate limiter for a fresh FakeClock-backed one."""
    import pv_inverter_proxy.webapp as _webapp_mod

    clock = _FakeClock()
    limiter = _security_mod.RateLimiter(clock=clock)
    monkeypatch.setattr(_webapp_mod, "_update_rate_limiter", limiter)
    return limiter, clock


@_pytest.fixture
def force_idle(monkeypatch):
    """Force is_update_running() to return (False, 'idle')."""
    import pv_inverter_proxy.webapp as _webapp_mod

    monkeypatch.setattr(
        _webapp_mod,
        "is_update_running",
        lambda *a, **k: (False, "idle"),
    )


@_pytest.fixture
async def webapp_client(
    tmp_trigger_path,
    tmp_audit_path,
    fresh_rate_limiter,
    force_idle,
    monkeypatch,
):
    """Full in-process aiohttp client built via create_webapp.

    Uses a stub AppContext so no Venus/Modbus infra is spun up. The
    csrf middleware is registered, so GET / seeds the cookie.
    """
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config

    # Fast no-op for maintenance mode entry so update_start_handler stays
    # focused on the guard pipeline during tests.
    async def _noop_enter_maintenance(ctx, reason=""):
        return None

    # Patch the maintenance import target used in update_start_handler.
    import pv_inverter_proxy.updater.maintenance as _maint_mod

    monkeypatch.setattr(
        _maint_mod, "enter_maintenance_mode", _noop_enter_maintenance
    )

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(ctx, Config(), "")
    app = runner.app
    # Inject the fake scheduler so update_check_handler has a target.
    app["update_scheduler"] = _FakeScheduler(
        result=_FakeReleaseInfo(available=False, latest_version=None)
    )
    server = TestServer(app)
    async with TestClient(server) as client:
        # Hit a GET so the CSRF cookie is seeded.
        await client.get("/api/update/available")
        yield client
    await runner.cleanup()


def _csrf_headers(client: TestClient) -> dict:
    """Pull the pvim_csrf cookie off the client jar and build the header."""
    jar = client.session.cookie_jar
    token = None
    for cookie in jar:
        if cookie.key == _security_mod.CSRF_COOKIE_NAME:
            token = cookie.value
            break
    assert token, "CSRF cookie was not seeded by GET request"
    return {_security_mod.CSRF_HEADER_NAME: token}


# ---------------------------------------------------------------------------
# Middleware + broadcaster registration (D-41)
# ---------------------------------------------------------------------------


async def test_csrf_middleware_registered_on_app(
    tmp_audit_path, force_idle, monkeypatch
):
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(ctx, Config(), "")
    try:
        app = runner.app
        names = [getattr(m, "__name__", str(m)) for m in app.middlewares]
        assert any("csrf_middleware" in n for n in names), (
            f"csrf_middleware not registered; middlewares={names}"
        )
    finally:
        await runner.cleanup()


async def test_progress_broadcaster_started_on_app_startup(
    tmp_audit_path, force_idle, monkeypatch
):
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config
    from pv_inverter_proxy.updater.progress import APP_KEY

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(ctx, Config(), "")
    try:
        app = runner.app
        assert app.get(APP_KEY) is not None, (
            "progress broadcaster not stashed under APP_KEY on startup"
        )
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# /api/version (D-27)
# ---------------------------------------------------------------------------


async def test_version_endpoint_returns_version_and_commit(webapp_client):
    resp = await webapp_client.get("/api/version")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"version": "8.0.0", "commit": "deadbeef"}


async def test_version_endpoint_no_csrf_needed(webapp_client):
    # GET bypasses csrf_middleware — fresh client without header must work.
    resp = await webapp_client.get("/api/version")
    assert resp.status == 200


# ---------------------------------------------------------------------------
# /api/update/status
# ---------------------------------------------------------------------------


async def test_update_status_endpoint_returns_current_and_history(
    webapp_client, monkeypatch
):
    from pv_inverter_proxy.updater.status import UpdateStatus
    import pv_inverter_proxy.webapp as _webapp_mod

    fake_status = UpdateStatus(
        current={"phase": "idle", "nonce": "n1"},
        history=[{"phase": "idle", "at": "2026-04-11T00:00:00Z"}],
    )
    monkeypatch.setattr(_webapp_mod, "load_status", lambda *a, **k: fake_status)
    resp = await webapp_client.get("/api/update/status")
    assert resp.status == 200
    data = await resp.json()
    assert "current" in data and "history" in data
    assert data["current"]["phase"] == "idle"
    assert len(data["history"]) == 1


# ---------------------------------------------------------------------------
# /api/update/check
# ---------------------------------------------------------------------------


async def test_update_check_endpoint_calls_scheduler_check_once(webapp_client):
    headers = _csrf_headers(webapp_client)
    sched = webapp_client.server.app["update_scheduler"]
    resp = await webapp_client.post("/api/update/check", headers=headers)
    assert resp.status == 200
    assert sched.calls == 1


async def test_update_check_endpoint_returns_available_flag(webapp_client):
    headers = _csrf_headers(webapp_client)
    webapp_client.server.app["update_scheduler"] = _FakeScheduler(
        result=_FakeReleaseInfo(available=True, latest_version="v8.1.0")
    )
    resp = await webapp_client.post("/api/update/check", headers=headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["checked"] is True
    assert data["available"] is True
    assert data["latest_version"] == "v8.1.0"


# ---------------------------------------------------------------------------
# /api/update/start happy path + <100ms latency (D-20, D-21)
# ---------------------------------------------------------------------------


async def test_update_start_returns_202_under_100ms(
    webapp_client, tmp_trigger_path, fresh_rate_limiter
):
    headers = _csrf_headers(webapp_client)
    # Warm-up so first-call import costs don't contaminate the budget.
    await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    # After warm-up, reset the limiter so the next call is accepted.
    _limiter, clock = fresh_rate_limiter
    clock.advance(61)

    t0 = _time.monotonic()
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    dt = _time.monotonic() - t0
    assert resp.status == 202, await resp.text()
    assert dt < 0.1, f"start latency {dt * 1000:.1f}ms exceeds 100ms budget (D-20)"


async def test_update_start_with_valid_csrf_returns_202(
    webapp_client, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 202


async def test_update_start_without_csrf_cookie_returns_422(
    tmp_trigger_path, tmp_audit_path, fresh_rate_limiter, force_idle, monkeypatch
):
    """POST without seeding the CSRF cookie must be 422 csrf_missing."""
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config
    import pv_inverter_proxy.updater.maintenance as _maint_mod

    async def _noop(ctx, reason=""):
        return None

    monkeypatch.setattr(_maint_mod, "enter_maintenance_mode", _noop)

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(ctx, Config(), "")
    try:
        server = TestServer(runner.app)
        async with TestClient(server) as client:
            # NO prior GET → no cookie → middleware returns 422 csrf_missing.
            resp = await client.post(
                "/api/update/start",
                json={"op": "update", "target_sha": FULL_SHA},
            )
            assert resp.status == 422
            data = await resp.json()
            assert data["error"] == "csrf_missing"
    finally:
        await runner.cleanup()


async def test_update_start_with_mismatched_csrf_returns_422(webapp_client):
    headers = {_security_mod.CSRF_HEADER_NAME: "wrong-token-value"}
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 422
    data = await resp.json()
    assert data["error"] == "csrf_mismatch"


async def test_update_start_writes_trigger_file_atomically(
    webapp_client, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 202
    assert tmp_trigger_path.exists()
    import json as _json

    written = _json.loads(tmp_trigger_path.read_text())
    assert written["op"] == "update"
    assert written["target_sha"] == FULL_SHA
    assert written["requested_at"].endswith("Z")
    assert written["nonce"]


# ---------------------------------------------------------------------------
# Rate-limit (D-12/D-13/D-14)
# ---------------------------------------------------------------------------


async def test_update_start_second_attempt_within_60s_returns_429(
    webapp_client, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    r1 = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert r1.status == 202
    r2 = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert r2.status == 429


async def test_update_start_429_includes_retry_after_header(
    webapp_client, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    r2 = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert r2.status == 429
    assert "Retry-After" in r2.headers
    assert int(r2.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------------------
# Concurrent guard (D-10, D-11)
# ---------------------------------------------------------------------------


async def test_update_start_when_phase_running_returns_409(
    webapp_client, tmp_trigger_path, monkeypatch
):
    import pv_inverter_proxy.webapp as _webapp_mod

    monkeypatch.setattr(
        _webapp_mod,
        "is_update_running",
        lambda *a, **k: (True, "backup"),
    )
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 409
    data = await resp.json()
    assert data["error"] == "update_in_progress"
    assert data["phase"] == "backup"


# ---------------------------------------------------------------------------
# Audit log (D-15..D-19)
# ---------------------------------------------------------------------------


def _read_audit_lines(path: _Path) -> list[dict]:
    import json as _json

    if not path.exists():
        return []
    return [
        _json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


async def test_update_start_audit_log_accepted_outcome(
    webapp_client, tmp_audit_path, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 202
    lines = _read_audit_lines(tmp_audit_path)
    outcomes = [line["outcome"] for line in lines]
    assert "accepted" in outcomes


async def test_update_start_audit_log_429_outcome(
    webapp_client, tmp_audit_path, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    lines = _read_audit_lines(tmp_audit_path)
    outcomes = [line["outcome"] for line in lines]
    assert "429_rate_limited" in outcomes


async def test_update_start_audit_log_409_outcome(
    webapp_client, tmp_audit_path, tmp_trigger_path, monkeypatch
):
    import pv_inverter_proxy.webapp as _webapp_mod

    monkeypatch.setattr(
        _webapp_mod,
        "is_update_running",
        lambda *a, **k: (True, "backup"),
    )
    headers = _csrf_headers(webapp_client)
    await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    lines = _read_audit_lines(tmp_audit_path)
    outcomes = [line["outcome"] for line in lines]
    assert "409_conflict" in outcomes


async def test_update_start_audit_log_422_outcome(
    webapp_client, tmp_audit_path, tmp_trigger_path
):
    # Mismatched CSRF produces csrf_mismatch via the middleware, which
    # logs 422_invalid_csrf through audit_log_append.
    headers = {_security_mod.CSRF_HEADER_NAME: "mismatch-value"}
    resp = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert resp.status == 422
    lines = _read_audit_lines(tmp_audit_path)
    outcomes = [line["outcome"] for line in lines]
    assert "422_invalid_csrf" in outcomes


# ---------------------------------------------------------------------------
# /api/update/rollback (D-03)
# ---------------------------------------------------------------------------


async def test_update_rollback_writes_previous_sentinel_trigger(
    webapp_client, tmp_trigger_path
):
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post(
        "/api/update/rollback",
        headers=headers,
    )
    assert resp.status == 202, await resp.text()
    assert tmp_trigger_path.exists()
    import json as _json

    written = _json.loads(tmp_trigger_path.read_text())
    assert written["op"] == "rollback"
    assert written["target_sha"] == "previous"


async def test_update_rollback_requires_csrf(
    tmp_trigger_path, tmp_audit_path, fresh_rate_limiter, force_idle, monkeypatch
):
    """POST /api/update/rollback without CSRF → 422."""
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config
    import pv_inverter_proxy.updater.maintenance as _maint_mod

    async def _noop(ctx, reason=""):
        return None

    monkeypatch.setattr(_maint_mod, "enter_maintenance_mode", _noop)

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(ctx, Config(), "")
    try:
        async with TestClient(TestServer(runner.app)) as client:
            resp = await client.post("/api/update/rollback")
            assert resp.status == 422
    finally:
        await runner.cleanup()


async def test_update_rollback_when_phase_running_returns_409(
    webapp_client, tmp_trigger_path, monkeypatch
):
    import pv_inverter_proxy.webapp as _webapp_mod

    monkeypatch.setattr(
        _webapp_mod,
        "is_update_running",
        lambda *a, **k: (True, "healthcheck"),
    )
    headers = _csrf_headers(webapp_client)
    resp = await webapp_client.post("/api/update/rollback", headers=headers)
    assert resp.status == 409
    data = await resp.json()
    assert data["error"] == "update_in_progress"
    assert data["phase"] == "healthcheck"


async def test_update_rollback_rate_limited_with_start(
    webapp_client, tmp_trigger_path
):
    """Start + rollback share the same module-level rate limiter bucket."""
    headers = _csrf_headers(webapp_client)
    r1 = await webapp_client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
        headers=headers,
    )
    assert r1.status == 202
    r2 = await webapp_client.post("/api/update/rollback", headers=headers)
    assert r2.status == 429


# ---------------------------------------------------------------------------
# Regression: existing /api/update/start route still exposed
# ---------------------------------------------------------------------------


async def test_existing_update_start_endpoint_still_exposed(webapp_client):
    """Sanity check: route table still contains POST /api/update/start."""
    app = webapp_client.server.app
    routes = [
        (r.method, r.resource.canonical if r.resource else "")
        for r in app.router.routes()
    ]
    assert ("POST", "/api/update/start") in routes
    assert ("POST", "/api/update/rollback") in routes
    assert ("GET", "/api/version") in routes
    assert ("GET", "/api/update/status") in routes
    assert ("POST", "/api/update/check") in routes


# ---------------------------------------------------------------------------
# JS / Python phase-name drift guard
# ---------------------------------------------------------------------------


def test_phase_order_js_matches_python_phases():
    """Assert PHASE_ORDER in software_page.js == PHASES frozenset.

    Plan 46-03 creates software_page.js; when this test runs before
    that plan lands, the JS file is absent and we skip rather than
    fail (the test's purpose is drift detection once both exist).
    """
    js_path = (
        _Path(__file__).parent.parent
        / "src"
        / "pv_inverter_proxy"
        / "static"
        / "software_page.js"
    )
    if not js_path.exists():
        _pytest.skip("software_page.js not yet created (Plan 46-03)")

    content = js_path.read_text(encoding="utf-8")
    # Expect: const PHASE_ORDER = [ "trigger_received", ... ];
    match = _re.search(
        r"PHASE_ORDER\s*=\s*(\[[^\]]*\])",
        content,
        _re.DOTALL,
    )
    assert match, "PHASE_ORDER constant not found in software_page.js"
    import json as _json

    raw = match.group(1)
    # JS single/double quotes → JSON parser accepts double quotes only.
    raw_json = raw.replace("'", '"')
    # Strip trailing commas (legal in JS, illegal in JSON).
    raw_json = _re.sub(r",\s*]", "]", raw_json)
    js_phases = _json.loads(raw_json)

    from pv_inverter_proxy.updater_root.status_writer import PHASES

    assert sorted(js_phases) == sorted(PHASES), (
        f"JS PHASE_ORDER drift from Python PHASES\n"
        f"  JS only:    {sorted(set(js_phases) - PHASES)}\n"
        f"  Python only: {sorted(PHASES - set(js_phases))}"
    )


# ===========================================================================
# Phase 46 Plan 05: GET/PATCH /api/update/config (CFG-02 / D-04 / D-06)
# ---------------------------------------------------------------------------
# These tests pin the minimal UpdateConfig contract end-to-end through
# create_webapp + csrf_middleware. They use the existing webapp_client
# fixture and write a tmp config.yaml that the handlers read/write.
# ===========================================================================


@_pytest.fixture
def update_config_path(tmp_path, monkeypatch):
    """Point ``app["config_path"]`` at a tmp YAML file for the update tests.

    Returns the :class:`Path` so tests can assert persisted values.
    """
    cfg = tmp_path / "config.yaml"
    # Seed with an unrelated sibling key to exercise the preserve-siblings
    # contract of save_update_config.
    cfg.write_text(
        "log_level: INFO\n"
        "proxy:\n"
        "  port: 502\n"
    )
    return cfg


@_pytest.fixture
async def webapp_client_with_cfg(
    tmp_trigger_path,
    tmp_audit_path,
    fresh_rate_limiter,
    force_idle,
    monkeypatch,
    update_config_path,
):
    """Same as :func:`webapp_client` but with a real tmp config path.

    The baseline fixture passes ``""`` as ``config_path`` which is fine
    for the other route tests but breaks the update-config tests that
    need a writable YAML file.
    """
    import pv_inverter_proxy.webapp as _webapp_mod
    from pv_inverter_proxy.config import Config

    async def _noop_enter_maintenance(ctx, reason=""):
        return None

    import pv_inverter_proxy.updater.maintenance as _maint_mod

    monkeypatch.setattr(
        _maint_mod, "enter_maintenance_mode", _noop_enter_maintenance
    )

    ctx = _StubAppCtx()
    runner = await _webapp_mod.create_webapp(
        ctx, Config(), str(update_config_path)
    )
    app = runner.app
    app["update_scheduler"] = _FakeScheduler(
        result=_FakeReleaseInfo(available=False, latest_version=None)
    )
    server = TestServer(app)
    async with TestClient(server) as client:
        await client.get("/api/update/available")
        yield client, update_config_path
    await runner.cleanup()


# ---- GET /api/update/config ----------------------------------------------


async def test_update_config_get_returns_three_fields(webapp_client_with_cfg):
    client, _cfg = webapp_client_with_cfg
    resp = await client.get("/api/update/config")
    assert resp.status == 200
    data = await resp.json()
    # Defaults are returned when no 'update:' section exists yet.
    assert set(data.keys()) == {
        "github_repo",
        "check_interval_hours",
        "auto_install",
    }
    assert data["github_repo"] == "hulki/pv-inverter-proxy"
    assert data["check_interval_hours"] == 24
    assert data["auto_install"] is False


async def test_update_config_get_does_not_require_csrf(webapp_client_with_cfg):
    """GET is unauthenticated — no CSRF header needed."""
    client, _cfg = webapp_client_with_cfg
    # Hit GET without csrf headers (just the cookie jar from fixture).
    resp = await client.get("/api/update/config")
    assert resp.status == 200


async def test_update_config_get_reads_existing_section(
    webapp_client_with_cfg,
):
    """GET reflects a pre-seeded update: section from the YAML file."""
    client, cfg = webapp_client_with_cfg
    import yaml as _yaml

    existing = _yaml.safe_load(cfg.read_text()) or {}
    existing["update"] = {
        "github_repo": "forked/pv-inverter-proxy",
        "check_interval_hours": 12,
        "auto_install": True,
    }
    cfg.write_text(_yaml.safe_dump(existing))
    resp = await client.get("/api/update/config")
    assert resp.status == 200
    data = await resp.json()
    assert data["github_repo"] == "forked/pv-inverter-proxy"
    assert data["check_interval_hours"] == 12
    assert data["auto_install"] is True


# ---- PATCH /api/update/config: CSRF -------------------------------------


async def test_update_config_patch_requires_csrf(webapp_client_with_cfg):
    """PATCH without X-CSRF-Token → 422 csrf_missing (no save)."""
    client, cfg = webapp_client_with_cfg
    resp = await client.patch(
        "/api/update/config",
        json={"check_interval_hours": 6},
    )
    assert resp.status == 422
    body = await resp.json()
    assert body.get("error") == "csrf_missing"


async def test_update_config_patch_rejects_csrf_mismatch(
    webapp_client_with_cfg,
):
    """PATCH with a bogus header token → 422 csrf_mismatch."""
    client, _cfg = webapp_client_with_cfg
    # The jar already has a seeded cookie from the fixture's GET call.
    resp = await client.patch(
        "/api/update/config",
        json={"check_interval_hours": 6},
        headers={"X-CSRF-Token": "NOT-THE-REAL-TOKEN"},
    )
    assert resp.status == 422
    body = await resp.json()
    assert body.get("error") == "csrf_mismatch"


# ---- PATCH /api/update/config: happy path -------------------------------


async def test_update_config_patch_accepts_single_field(
    webapp_client_with_cfg,
):
    client, cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    resp = await client.patch(
        "/api/update/config",
        json={"check_interval_hours": 6},
        headers=headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["check_interval_hours"] == 6
    # Unspecified fields fall back to defaults.
    assert data["github_repo"] == "hulki/pv-inverter-proxy"
    assert data["auto_install"] is False

    # Verify the file actually moved.
    import yaml as _yaml

    reloaded = _yaml.safe_load(cfg.read_text())
    assert reloaded["update"]["check_interval_hours"] == 6


async def test_update_config_patch_accepts_all_three_fields(
    webapp_client_with_cfg,
):
    client, cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    resp = await client.patch(
        "/api/update/config",
        json={
            "github_repo": "forked/repo",
            "check_interval_hours": 12,
            "auto_install": True,
        },
        headers=headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {
        "github_repo": "forked/repo",
        "check_interval_hours": 12,
        "auto_install": True,
    }


# ---- PATCH /api/update/config: 422 validation ---------------------------


async def test_update_config_patch_rejects_unknown_key_with_422(
    webapp_client_with_cfg,
):
    client, cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    resp = await client.patch(
        "/api/update/config",
        json={"release_channel": "beta"},
        headers=headers,
    )
    assert resp.status == 422
    body = await resp.json()
    assert body.get("error") == "validation_failed"
    assert "release_channel" in (body.get("detail") or "")
    # Config file must NOT have been touched on a validation failure.
    import yaml as _yaml

    reloaded = _yaml.safe_load(cfg.read_text()) or {}
    assert "update" not in reloaded


async def test_update_config_patch_rejects_invalid_type_with_422(
    webapp_client_with_cfg,
):
    client, _cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    resp = await client.patch(
        "/api/update/config",
        json={"check_interval_hours": -5},
        headers=headers,
    )
    assert resp.status == 422
    body = await resp.json()
    assert body.get("error") == "validation_failed"
    assert "check_interval_hours" in (body.get("detail") or "")


async def test_update_config_patch_rejects_invalid_json_with_400(
    webapp_client_with_cfg,
):
    client, _cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    # Send a raw non-JSON body with JSON content-type.
    resp = await client.patch(
        "/api/update/config",
        data=b"<not json>",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp.status == 400
    body = await resp.json()
    assert body.get("error") == "invalid_json"


# ---- Preservation of sibling config keys (CFG-02 safety net) ------------


async def test_update_config_patch_preserves_other_config_keys(
    webapp_client_with_cfg,
):
    """PATCH must not clobber unrelated top-level keys in config.yaml.

    The fixture seeds ``log_level: INFO`` + ``proxy.port: 502``; after a
    patch those keys must still be present and unchanged.
    """
    client, cfg = webapp_client_with_cfg
    headers = _csrf_headers(client)
    resp = await client.patch(
        "/api/update/config",
        json={"auto_install": True},
        headers=headers,
    )
    assert resp.status == 200

    import yaml as _yaml

    reloaded = _yaml.safe_load(cfg.read_text())
    assert reloaded["log_level"] == "INFO"
    assert reloaded["proxy"] == {"port": 502}
    assert reloaded["update"]["auto_install"] is True


# ---- Route table ---------------------------------------------------------


async def test_update_config_routes_registered(webapp_client_with_cfg):
    client, _cfg = webapp_client_with_cfg
    app = client.server.app
    routes = [
        (r.method, r.resource.canonical if r.resource else "")
        for r in app.router.routes()
    ]
    assert ("GET", "/api/update/config") in routes
    assert ("PATCH", "/api/update/config") in routes
