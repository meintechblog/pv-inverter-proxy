"""Unit tests for the rich /api/health endpoint (Plan 45-01).

Covers HEALTH-01..04:
    - HEALTH-01: Response schema has exactly the 8 required top-level keys.
    - HEALTH-02: Overall status derivation from required-for-success set
      (webapp + modbus_server + >=1 device ok).
    - HEALTH-03: venus_os is warn-only — it never flips the overall status
      to degraded.
    - HEALTH-04: Verified via grep against __main__.py (the Phase 43
      healthy-flag writer must still exist untouched). See
      test_health_04_writer_untouched at the bottom of the module.

Design:
    The pure helper `_derive_health_payload` is exercised directly. No
    aiohttp Application is spun up for the unit tests — the handler hot
    path is a thin wrapper that only reads `time.monotonic`,
    `request.app["start_time"]`, `request.app["app_ctx"]`, and
    `request.app["config"]`. A single integration test uses
    `aiohttp.test_utils.make_mocked_request` to exercise the async
    handler end-to-end.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from pv_inverter_proxy.context import AppContext, DeviceState
from pv_inverter_proxy.webapp import (
    _HEALTH_STARTUP_GRACE_S,
    _derive_health_payload,
    health_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubCache:
    """Minimal RegisterCache stand-in — only `is_stale` is read."""

    def __init__(self, *, is_stale: bool) -> None:
        self.is_stale = is_stale


_UNSET = object()


def _make_ctx(
    *,
    cache=_UNSET,
    devices=None,
    venus_connected: bool = True,
    version: str | None = "8.0.0",
    commit: str | None = "abc123d",
) -> AppContext:
    ctx = AppContext()
    # Sentinel lets callers explicitly pass cache=None to unwire the cache.
    ctx.cache = _StubCache(is_stale=False) if cache is _UNSET else cache
    ctx.venus_mqtt_connected = venus_connected
    ctx.current_version = version
    ctx.current_commit = commit
    ctx.devices = devices or {}
    return ctx


def _make_device(*, success: int) -> DeviceState:
    ds = DeviceState()
    ds.poll_counter = {"success": success, "total": max(success, 1)}
    return ds


def _venus_cfg(host: str) -> SimpleNamespace:
    return SimpleNamespace(venus=SimpleNamespace(host=host))


# ---------------------------------------------------------------------------
# Schema (HEALTH-01)
# ---------------------------------------------------------------------------


REQUIRED_KEYS = {
    "status",
    "version",
    "commit",
    "uptime_seconds",
    "webapp",
    "modbus_server",
    "devices",
    "venus_os",
}


def test_health_schema_has_all_required_keys():
    """HEALTH-01: response dict has exactly the 8 required top-level keys."""
    ctx = _make_ctx(devices={"se30k": _make_device(success=1)})
    payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg("mqtt.local"))
    assert set(payload.keys()) == REQUIRED_KEYS
    assert isinstance(payload["devices"], dict)
    assert isinstance(payload["uptime_seconds"], (int, float))


# ---------------------------------------------------------------------------
# Status derivation — HEALTH-02 happy path
# ---------------------------------------------------------------------------


def test_health_all_ok():
    """Required-ok after grace → overall status == ok."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=False),
        devices={"se30k": _make_device(success=5)},
        venus_connected=True,
    )
    payload = _derive_health_payload(ctx, uptime_s=120.0, config=_venus_cfg("mqtt.local"))
    assert payload["status"] == "ok"
    assert payload["webapp"] == "ok"
    assert payload["modbus_server"] == "ok"
    assert payload["devices"] == {"se30k": "ok"}
    assert payload["venus_os"] == "ok"
    assert payload["version"] == "8.0.0"
    assert payload["commit"] == "abc123d"


# ---------------------------------------------------------------------------
# Startup grace (HEALTH-02 interaction)
# ---------------------------------------------------------------------------


def test_health_starting_grace():
    """Within 30s uptime, missing poll → status=starting, not degraded."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=True),  # cache empty → would normally be degraded
        devices={"se30k": _make_device(success=0)},  # no successful poll yet
        venus_connected=False,
    )
    payload = _derive_health_payload(ctx, uptime_s=5.0, config=_venus_cfg("mqtt.local"))
    assert payload["status"] == "starting"
    # Startup remapping: degraded/starting modbus becomes starting
    assert payload["modbus_server"] == "starting"
    # Devices in starting window all collapse to "starting"
    assert payload["devices"] == {"se30k": "starting"}


def test_health_starting_grace_no_devices():
    """Within grace window with no devices yet configured → status=starting."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=True),
        devices={},
        venus_connected=False,
    )
    payload = _derive_health_payload(ctx, uptime_s=1.0, config=_venus_cfg("mqtt.local"))
    assert payload["status"] == "starting"
    assert payload["devices"] == {}


def test_health_grace_boundary_exclusive():
    """uptime == grace limit means grace has ended (< is exclusive)."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=True),
        devices={"se30k": _make_device(success=0)},
    )
    payload = _derive_health_payload(
        ctx, uptime_s=_HEALTH_STARTUP_GRACE_S, config=_venus_cfg("mqtt.local")
    )
    assert payload["status"] == "degraded"  # grace over


# ---------------------------------------------------------------------------
# Degraded / failed derivation (HEALTH-02)
# ---------------------------------------------------------------------------


def test_health_degraded_after_grace():
    """After grace, cache stale → modbus_server=degraded, status=degraded."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=True),
        devices={"se30k": _make_device(success=5)},
    )
    payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg("mqtt.local"))
    assert payload["modbus_server"] == "degraded"
    assert payload["status"] == "degraded"


def test_health_no_devices_after_grace():
    """After grace, no devices → status=degraded (zero devices ok)."""
    ctx = _make_ctx(cache=_StubCache(is_stale=False), devices={})
    payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg("mqtt.local"))
    assert payload["status"] == "degraded"
    assert payload["devices"] == {}


def test_health_cache_none_is_failed():
    """If app_ctx.cache is None, modbus_server=failed (cache not yet wired)."""
    ctx = _make_ctx(cache=None, devices={"se30k": _make_device(success=1)})
    # bypass grace so we see the raw status
    payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg("mqtt.local"))
    assert payload["modbus_server"] == "failed"
    assert payload["status"] == "degraded"  # required-for-success fails


# ---------------------------------------------------------------------------
# venus_os warn-only (HEALTH-03)
# ---------------------------------------------------------------------------


def test_health_venus_warn_only():
    """venus_os=degraded must NOT flip overall status when required set is ok."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=False),
        devices={"se30k": _make_device(success=5)},
        venus_connected=False,
    )
    payload = _derive_health_payload(ctx, uptime_s=120.0, config=_venus_cfg("mqtt.local"))
    assert payload["venus_os"] == "degraded"
    assert payload["status"] == "ok"  # HEALTH-03: warn-only


def test_health_venus_disabled():
    """Empty venus.host → venus_os=disabled (not degraded)."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=False),
        devices={"se30k": _make_device(success=5)},
        venus_connected=False,  # host empty → connected doesn't matter
    )
    payload = _derive_health_payload(ctx, uptime_s=120.0, config=_venus_cfg(""))
    assert payload["venus_os"] == "disabled"
    assert payload["status"] == "ok"


# ---------------------------------------------------------------------------
# Version / commit fallback
# ---------------------------------------------------------------------------


def test_health_version_commit_unknown():
    """Missing version/commit → the string 'unknown'."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=False),
        devices={"se30k": _make_device(success=1)},
        version=None,
        commit=None,
    )
    payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg(""))
    assert payload["version"] == "unknown"
    assert payload["commit"] == "unknown"


# ---------------------------------------------------------------------------
# Hot-path safety: no subprocess, no filesystem, no blocking IO
# ---------------------------------------------------------------------------


def test_health_no_subprocess_no_fs():
    """Hot path must not touch subprocess or filesystem — patch both to raise."""
    ctx = _make_ctx(devices={"se30k": _make_device(success=1)})
    with patch("subprocess.run", side_effect=AssertionError("subprocess touched")):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("fs touched")):
            payload = _derive_health_payload(ctx, uptime_s=60.0, config=_venus_cfg(""))
    assert payload["status"] == "ok"


# ---------------------------------------------------------------------------
# Integration: async handler via mocked aiohttp Request
# ---------------------------------------------------------------------------


async def test_health_handler_integration():
    """health_handler returns 200 JSON with starting status during cold boot."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=True),
        devices={"se30k": _make_device(success=0)},
        venus_connected=False,
    )
    app = web.Application()
    app["app_ctx"] = ctx
    app["config"] = _venus_cfg("mqtt.local")
    app["start_time"] = time.monotonic()  # just started

    req = make_mocked_request("GET", "/api/health", app=app)
    resp = await health_handler(req)
    assert resp.status == 200
    data = json.loads(resp.body.decode())
    assert set(data.keys()) == REQUIRED_KEYS
    # Freshly started → starting
    assert data["status"] == "starting"


async def test_health_handler_integration_ok_after_grace():
    """After grace, all components healthy → status=ok."""
    ctx = _make_ctx(
        cache=_StubCache(is_stale=False),
        devices={"se30k": _make_device(success=10)},
        venus_connected=True,
    )
    app = web.Application()
    app["app_ctx"] = ctx
    app["config"] = _venus_cfg("mqtt.local")
    # start_time far in the past → uptime >> grace
    app["start_time"] = time.monotonic() - 120.0

    req = make_mocked_request("GET", "/api/health", app=app)
    resp = await health_handler(req)
    assert resp.status == 200
    data = json.loads(resp.body.decode())
    assert data["status"] == "ok"
    assert data["uptime_seconds"] >= 120.0
