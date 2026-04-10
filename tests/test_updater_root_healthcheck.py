"""Hermetic tests for updater_root.healthcheck.

Uses virtual clock + fake aiohttp session so no real sleeping happens
and no HTTP traffic flows. Covers HEALTH-05 (3 consecutive ok),
HEALTH-06 (rollback triggers), the required-for-success schema check,
and the Venus-OS warn-only rule.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pv_inverter_proxy.updater_root import healthcheck as hc_mod
from pv_inverter_proxy.updater_root.healthcheck import (
    HealthCheckConfig,
    HealthCheckOutcome,
    HealthChecker,
)


# ---------------------------------------------------------------------
# Virtual clock + fake session plumbing

class _VClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class _FakeResponse:
    status: int
    body: dict | None = None
    raise_on_json: Exception | None = None

    async def json(self) -> dict:
        if self.raise_on_json is not None:
            raise self.raise_on_json
        return self.body or {}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


@dataclass
class _FakeSession:
    responses: list[Any]
    _idx: int = 0
    closed: bool = False
    raise_on_get: Exception | None = None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        if self.raise_on_get is not None:
            raise self.raise_on_get
        if self._idx >= len(self.responses):
            # repeat last response forever
            item = self.responses[-1]
        else:
            item = self.responses[self._idx]
            self._idx += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def _ok_body(version: str = "8.0.0", commit: str = "abc1234") -> dict:
    return {
        "status": "ok",
        "version": version,
        "commit": commit,
        "uptime_seconds": 10.5,
        "webapp": "ok",
        "modbus_server": "ok",
        "devices": {"se30k": "ok"},
        "venus_os": "ok",
    }


@pytest.fixture
def vclock(monkeypatch: pytest.MonkeyPatch) -> _VClock:
    clock = _VClock()

    async def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return clock


@pytest.fixture
def healthy_flag(tmp_path: Path) -> Path:
    flag = tmp_path / "healthy"
    flag.write_text("")
    return flag


@pytest.fixture
def missing_flag(tmp_path: Path) -> Path:
    return tmp_path / "not-there"


def _make_checker(
    responses: list[Any],
    *,
    healthy_flag_path: Path,
    expected_version: str | None = None,
    expected_commit: str | None = None,
    clock: _VClock | None = None,
    raise_on_get: Exception | None = None,
) -> tuple[HealthChecker, _FakeSession]:
    session = _FakeSession(responses=responses, raise_on_get=raise_on_get)

    async def session_factory() -> _FakeSession:
        return session

    cfg = HealthCheckConfig(
        health_url="http://127.0.0.1/api/health",
        healthy_flag_path=healthy_flag_path,
        hard_timeout_s=60.0,
        consecutive_ok_required=3,
        poll_interval_s=5.0,
        degraded_5xx_timeout_s=45.0,
    )
    checker = HealthChecker(
        config=cfg,
        expected_version=expected_version,
        expected_commit=expected_commit,
        session_factory=session_factory,
        clock=clock or (lambda: 0.0),
    )
    return checker, session


# ---------------------------------------------------------------------
# Happy paths

async def test_healthcheck_all_ok_waits_for_three_consecutive(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    responses = [
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
    ]
    checker, session = _make_checker(
        responses,
        healthy_flag_path=healthy_flag,
        clock=vclock,
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is True
    assert outcome.reason == "stable_ok"
    assert outcome.consecutive_ok >= 3
    assert outcome.probes == 3
    assert session.closed is True


async def test_healthcheck_transient_flakes_tolerated(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    responses = [
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=503),  # resets
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
    ]
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is True
    assert outcome.probes == 5


async def test_healthcheck_venus_warn_ignored(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    body = _ok_body()
    body["venus_os"] = "degraded"  # HEALTH-03 warn-only
    responses = [
        _FakeResponse(status=200, body=body),
        _FakeResponse(status=200, body=body),
        _FakeResponse(status=200, body=body),
    ]
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is True


# ---------------------------------------------------------------------
# Failure paths (HEALTH-06 rollback triggers)

async def test_healthcheck_version_mismatch_immediate_fail(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    responses = [_FakeResponse(status=200, body=_ok_body(version="7.9.9"))]
    checker, _ = _make_checker(
        responses,
        healthy_flag_path=healthy_flag,
        expected_version="8.0.0",
        clock=vclock,
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False
    assert outcome.reason == "version_mismatch"


async def test_healthcheck_timeout_no_flag(
    vclock: _VClock,
    missing_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    # All 503 forever
    responses = [_FakeResponse(status=503)] * 30
    checker, _ = _make_checker(
        responses, healthy_flag_path=missing_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False
    # Either degraded_5xx or timeout depending on timing
    assert outcome.reason in {"degraded_5xx_timeout", "timeout", "no_healthy_flag"}


async def test_healthcheck_systemctl_failed_immediate(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_false)
    responses = [_FakeResponse(status=200, body=_ok_body())]
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False
    assert outcome.reason == "systemctl_failed"


async def test_healthcheck_healthy_flag_required(
    vclock: _VClock,
    missing_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    # 20 oks but no healthy flag — must NOT return success
    responses = [_FakeResponse(status=200, body=_ok_body())] * 20
    checker, _ = _make_checker(
        responses, healthy_flag_path=missing_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False
    assert outcome.reason == "no_healthy_flag"


async def test_healthcheck_required_components_missing(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    body = _ok_body()
    body["webapp"] = "degraded"  # not ok -> required check fails
    responses = [_FakeResponse(status=200, body=body)] * 20
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False
    # Never got 3 consecutive oks
    assert outcome.reason in {"timeout", "no_healthy_flag"}


async def test_healthcheck_no_devices_ok(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    body = _ok_body()
    body["devices"] = {"se30k": "failed"}
    responses = [_FakeResponse(status=200, body=body)] * 20
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is False


async def test_healthcheck_connection_refused_resets_counter(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)

    class _ConnRefused(Exception):
        pass

    responses = [
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
        _ConnRefused("refused"),  # resets
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
        _FakeResponse(status=200, body=_ok_body()),
    ]
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.success is True


async def test_healthcheck_counts_probes(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_true)
    responses = [_FakeResponse(status=200, body=_ok_body())] * 3
    checker, _ = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    outcome = await checker.wait_for_healthy()
    assert outcome.probes == 3


async def test_healthcheck_session_closed_on_exception(
    vclock: _VClock,
    healthy_flag: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc_mod, "check_systemctl_active", _async_false)
    responses = [_FakeResponse(status=200, body=_ok_body())]
    checker, session = _make_checker(
        responses, healthy_flag_path=healthy_flag, clock=vclock
    )
    await checker.wait_for_healthy()
    assert session.closed is True


# ---------------------------------------------------------------------
# systemctl helpers

async def test_check_systemctl_active_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Proc:
        returncode = 0
        async def wait(self) -> int:
            return 0

    async def fake_exec(*args: Any, **kwargs: Any) -> _Proc:
        assert args[:2] == ("systemctl", "is-active")
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await hc_mod.check_systemctl_active() is True


async def test_check_systemctl_active_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Proc:
        returncode = 3
        async def wait(self) -> int:
            return 3

    async def fake_exec(*args: Any, **kwargs: Any) -> _Proc:
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await hc_mod.check_systemctl_active() is False


async def test_systemctl_restart_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Proc:
        returncode = 0
        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_exec(*args: Any, **kwargs: Any) -> _Proc:
        assert "restart" in args
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await hc_mod.systemctl_restart("my.service") is True


# ---------------------------------------------------------------------
# Helpers

async def _async_true(*args: Any, **kwargs: Any) -> bool:
    return True


async def _async_false(*args: Any, **kwargs: Any) -> bool:
    return False
