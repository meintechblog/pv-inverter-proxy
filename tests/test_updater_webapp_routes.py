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
