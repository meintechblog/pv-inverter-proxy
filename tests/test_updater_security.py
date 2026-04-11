"""Unit tests for pv_inverter_proxy.updater.security (SEC-01..SEC-04).

Covers:
    SEC-01: CSRF double-submit cookie middleware (D-07, D-08, D-09)
    SEC-02: Concurrent-update guard reading update-status.json (D-10, D-11)
    SEC-03: In-memory sliding-window rate limiter (D-12, D-13, D-14)
    SEC-04: JSONL audit log writer with lazy dir creation (D-15..D-19)

Hermetic — every test uses pytest ``tmp_path`` or monkeypatches.
Nothing touches ``/var/lib/pv-inverter-proxy/`` or
``/etc/pv-inverter-proxy/``.

These tests are the RED state contract for Task 2. The initial commit of
this file fails at collection time because ``pv_inverter_proxy.updater.security``
does not yet exist — that is the expected TDD RED signal.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

# Import under test. Before Task 2 this raises ModuleNotFoundError at
# collection time, failing all tests (the RED state). After Task 2 it
# resolves and the body of each test runs.
from pv_inverter_proxy.updater import security as security_mod
from pv_inverter_proxy.updater.security import (
    AUDIT_LOG_DIR_MODE,
    AUDIT_LOG_FILE_MODE,
    AUDIT_LOG_PATH,
    CSRF_COOKIE_MAX_AGE,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    IDLE_PHASES,
    RATE_LIMIT_WINDOW_SECONDS,
    RateLimiter,
    audit_log_append,
    csrf_middleware,
    is_update_running,
)
from pv_inverter_proxy.updater.status import UpdateStatus


# ---------------------------------------------------------------------------
# FakeClock — injectable time source for rate-limiter tests
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# aiohttp test fixtures for CSRF middleware
# ---------------------------------------------------------------------------


async def _ok_post(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _ok_get(request: web.Request) -> web.Response:
    return web.json_response({"hello": "world"})


@pytest.fixture
async def csrf_client():
    """aiohttp TestClient with csrf_middleware wired to a dummy handler."""
    app = web.Application(middlewares=[csrf_middleware])
    app.router.add_post("/api/update/ping", _ok_post)
    app.router.add_get("/api/ping", _ok_get)
    app.router.add_get("/api/update/status", _ok_get)
    async with TestClient(TestServer(app)) as client:
        yield client


# ---------------------------------------------------------------------------
# Audit log fixture — redirects AUDIT_LOG_PATH to tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override AUDIT_LOG_PATH and return the tmp target.

    Uses nested `lib/pv-inverter-proxy/` so the test exercises the
    lazy-parent-mkdir code path.
    """
    p = tmp_path / "lib" / "pv-inverter-proxy" / "update-audit.log"
    monkeypatch.setattr(security_mod, "AUDIT_LOG_PATH", p)
    return p


# ===========================================================================
# SEC-01: CSRF middleware
# ===========================================================================


async def test_csrf_rejects_missing_cookie(csrf_client) -> None:
    """POST /api/update/* with no cookie at all → 422 csrf_missing."""
    resp = await csrf_client.post(
        "/api/update/ping",
        headers={CSRF_HEADER_NAME: "anything"},
    )
    assert resp.status == 422
    body = await resp.json()
    assert body == {"error": "csrf_missing"}


async def test_csrf_rejects_missing_header(csrf_client) -> None:
    """POST with cookie but no X-CSRF-Token header → 422 csrf_missing."""
    csrf_client.session.cookie_jar.update_cookies(
        {CSRF_COOKIE_NAME: "tok-abc"}
    )
    resp = await csrf_client.post("/api/update/ping")
    assert resp.status == 422
    body = await resp.json()
    assert body == {"error": "csrf_missing"}


async def test_csrf_rejects_mismatched_cookie_header(csrf_client) -> None:
    """POST with cookie != header → 422 csrf_mismatch."""
    csrf_client.session.cookie_jar.update_cookies(
        {CSRF_COOKIE_NAME: "cookie-token"}
    )
    resp = await csrf_client.post(
        "/api/update/ping",
        headers={CSRF_HEADER_NAME: "header-token"},
    )
    assert resp.status == 422
    body = await resp.json()
    assert body == {"error": "csrf_mismatch"}


async def test_csrf_accepts_matching_cookie_header(csrf_client) -> None:
    """POST with cookie == header → handler runs, 200."""
    token = "matching-token-xyz"
    csrf_client.session.cookie_jar.update_cookies({CSRF_COOKIE_NAME: token})
    resp = await csrf_client.post(
        "/api/update/ping",
        headers={CSRF_HEADER_NAME: token},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"ok": True}


async def test_csrf_cookie_seeded_on_get_without_cookie(csrf_client) -> None:
    """GET /api/ping without cookie → response has Set-Cookie with csrf."""
    resp = await csrf_client.get("/api/ping")
    assert resp.status == 200
    # aiohttp response surfaces Set-Cookie via resp.cookies
    assert CSRF_COOKIE_NAME in resp.cookies
    cookie = resp.cookies[CSRF_COOKIE_NAME]
    assert cookie.value  # non-empty
    assert len(cookie.value) >= 20  # token_urlsafe(32) yields >= 43 chars


async def test_csrf_cookie_not_reseeded_when_present(csrf_client) -> None:
    """GET with existing cookie → response does NOT include Set-Cookie."""
    csrf_client.session.cookie_jar.update_cookies(
        {CSRF_COOKIE_NAME: "preexisting-token"}
    )
    resp = await csrf_client.get("/api/ping")
    assert resp.status == 200
    # When cookie is present on the request, middleware must NOT re-seed
    assert CSRF_COOKIE_NAME not in resp.cookies


async def test_csrf_cookie_attributes_samesite_strict_path_root_maxage_86400(
    csrf_client,
) -> None:
    """Seeded cookie has SameSite=Strict, Path=/, Max-Age=86400."""
    resp = await csrf_client.get("/api/ping")
    assert CSRF_COOKIE_NAME in resp.cookies
    cookie = resp.cookies[CSRF_COOKIE_NAME]
    # http.cookies.Morsel exposes attributes via subscript
    assert cookie["samesite"].lower() == "strict"
    assert cookie["path"] == "/"
    assert int(cookie["max-age"]) == CSRF_COOKIE_MAX_AGE == 86400


async def test_csrf_uses_compare_digest(
    csrf_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSRF check routes through secrets.compare_digest (timing-safe)."""
    calls: list[tuple[str, str]] = []
    # Patch the name as resolved inside the security module
    import pv_inverter_proxy.updater.security as sec

    real = sec.secrets.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(sec.secrets, "compare_digest", spy)
    token = "compare-digest-test-token"
    csrf_client.session.cookie_jar.update_cookies({CSRF_COOKIE_NAME: token})
    resp = await csrf_client.post(
        "/api/update/ping",
        headers={CSRF_HEADER_NAME: token},
    )
    assert resp.status == 200
    assert calls, "secrets.compare_digest was never called"
    # Called with the cookie and header values
    assert (token, token) in calls or (calls[-1] == (token, token))


# ===========================================================================
# SEC-03: RateLimiter (before SEC-02 because tests are simpler / pure)
# ===========================================================================


def test_rate_limit_first_request_accepted() -> None:
    rl = RateLimiter(window_seconds=60, clock=FakeClock(t=1000.0))
    accepted, retry_after = rl.check("192.168.3.17")
    assert accepted is True
    assert retry_after == 0


def test_rate_limit_second_request_within_60s_rejected() -> None:
    clock = FakeClock(t=1000.0)
    rl = RateLimiter(window_seconds=60, clock=clock)
    ok1, _ = rl.check("192.168.3.17")
    assert ok1
    # 10s later, same IP
    clock.t += 10
    ok2, retry_after = rl.check("192.168.3.17")
    assert ok2 is False
    assert retry_after >= 1
    # Retry-After reflects remaining window: 60 - 10 = 50 seconds
    assert retry_after <= 60


def test_rate_limit_retry_after_is_integer_seconds() -> None:
    """Retry-After must be an int (RFC 9110 §10.2.3, Pitfall 9)."""
    clock = FakeClock(t=1000.0)
    rl = RateLimiter(window_seconds=60, clock=clock)
    rl.check("10.0.0.1")
    clock.t += 5.7  # fractional advance
    accepted, retry_after = rl.check("10.0.0.1")
    assert accepted is False
    assert isinstance(retry_after, int)
    assert retry_after >= 1  # must never be 0 when rejected


def test_rate_limit_window_resets_after_60s() -> None:
    """A second request after the full window is accepted."""
    clock = FakeClock(t=1000.0)
    rl = RateLimiter(window_seconds=60, clock=clock)
    assert rl.check("192.168.3.17")[0] is True
    clock.t += 60  # exactly at the window boundary
    accepted, retry_after = rl.check("192.168.3.17")
    assert accepted is True
    assert retry_after == 0


def test_rate_limit_per_ip_isolation() -> None:
    """Two different IPs are tracked independently."""
    clock = FakeClock(t=1000.0)
    rl = RateLimiter(window_seconds=60, clock=clock)
    assert rl.check("192.168.3.17")[0] is True
    assert rl.check("192.168.3.18")[0] is True  # different IP, allowed
    clock.t += 5
    assert rl.check("192.168.3.17")[0] is False
    assert rl.check("192.168.3.18")[0] is False


# ===========================================================================
# SEC-02: Concurrent-update guard
# ===========================================================================


def _fake_status_with_phase(phase: str | None) -> UpdateStatus:
    """Build an UpdateStatus whose current_phase() returns ``phase``."""
    if phase is None or phase == "idle":
        return UpdateStatus(current=None, history=[])
    return UpdateStatus(
        current={"phase": phase, "nonce": "n", "target_sha": "s"},
        history=[],
    )


def _patch_load_status(
    monkeypatch: pytest.MonkeyPatch, phase: str | None
) -> None:
    status = _fake_status_with_phase(phase)
    monkeypatch.setattr(
        "pv_inverter_proxy.updater.security.load_status",
        lambda *args, **kwargs: status,
    )


def test_concurrent_guard_idle_phase_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "idle")
    running, phase = is_update_running()
    assert running is False
    assert phase == "idle"


def test_concurrent_guard_done_phase_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "done")
    running, phase = is_update_running()
    assert running is False
    assert phase == "done"


def test_concurrent_guard_rollback_done_phase_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "rollback_done")
    running, phase = is_update_running()
    assert running is False
    assert phase == "rollback_done"


def test_concurrent_guard_rollback_failed_phase_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "rollback_failed")
    running, phase = is_update_running()
    assert running is False
    assert phase == "rollback_failed"


def test_concurrent_guard_running_phase_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "pip_install")
    running, phase = is_update_running()
    assert running is True
    assert phase == "pip_install"


def test_concurrent_guard_restarting_phase_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_load_status(monkeypatch, "restarting")
    running, phase = is_update_running()
    assert running is True
    assert phase == "restarting"


# ===========================================================================
# SEC-04: Audit log writer
# ===========================================================================


async def test_audit_log_writes_jsonl_line_per_call(
    audit_log_path: Path,
) -> None:
    await audit_log_append(
        ip="192.168.3.17",
        user_agent="pytest/1.0",
        outcome="accepted",
    )
    assert audit_log_path.exists()
    lines = audit_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["ip"] == "192.168.3.17"
    assert row["ua"] == "pytest/1.0"
    assert row["outcome"] == "accepted"


async def test_audit_log_outcomes_all_four_values(
    audit_log_path: Path,
) -> None:
    outcomes = [
        "accepted",
        "409_conflict",
        "429_rate_limited",
        "422_invalid_csrf",
    ]
    for o in outcomes:
        await audit_log_append(ip="1.2.3.4", user_agent="t", outcome=o)
    lines = audit_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    seen = [json.loads(line)["outcome"] for line in lines]
    assert seen == outcomes


async def test_audit_log_creates_parent_dir_lazily_with_mode_0o750(
    audit_log_path: Path,
) -> None:
    parent = audit_log_path.parent
    assert not parent.exists()
    await audit_log_append(
        ip="10.0.0.1", user_agent="ua", outcome="accepted"
    )
    assert parent.exists()
    mode = parent.stat().st_mode & 0o777
    assert mode == AUDIT_LOG_DIR_MODE == 0o750


async def test_audit_log_file_mode_is_0o640(audit_log_path: Path) -> None:
    await audit_log_append(
        ip="10.0.0.1", user_agent="ua", outcome="accepted"
    )
    assert audit_log_path.exists()
    mode = audit_log_path.stat().st_mode & 0o777
    assert mode == AUDIT_LOG_FILE_MODE == 0o640


async def test_audit_log_each_line_is_valid_json_with_ts_ip_ua_outcome_keys(
    audit_log_path: Path,
) -> None:
    for i in range(3):
        await audit_log_append(
            ip=f"10.0.0.{i}",
            user_agent=f"ua-{i}",
            outcome="accepted",
        )
    lines = audit_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        row = json.loads(line)  # raises on invalid JSON
        assert set(row.keys()) == {"ts", "ip", "ua", "outcome"}
        assert isinstance(row["ts"], str) and row["ts"].endswith("Z")
        assert isinstance(row["ip"], str)
        assert isinstance(row["ua"], str)
        assert row["outcome"] == "accepted"


async def test_audit_log_concurrent_writes_serialized(
    audit_log_path: Path,
) -> None:
    """10 concurrent appends produce exactly 10 valid JSONL lines, no truncation."""
    async def one(i: int) -> None:
        await audit_log_append(
            ip=f"10.0.0.{i}",
            user_agent="ua",
            outcome="accepted",
        )

    await asyncio.gather(*(one(i) for i in range(10)))
    lines = audit_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    # Every line parses as JSON → no interleaved writes
    ips = sorted(json.loads(line)["ip"] for line in lines)
    assert ips == sorted(f"10.0.0.{i}" for i in range(10))
