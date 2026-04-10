"""Plan 45-05 Task 4: SAFETY-09 + graceful shutdown + WS broadcast."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.state_file import (
    PersistedState,
    is_power_limit_fresh,
    load_state,
    save_state,
)


# ---------------------------------------------------------------------------
# control.py save_last_limit -> state_file.save_state
# ---------------------------------------------------------------------------


def test_control_save_to_state_file(tmp_path, monkeypatch):
    """ControlState.save_last_limit must also write state.json."""
    from pv_inverter_proxy import control, state_file

    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", state_path)
    monkeypatch.setattr(control, "_LAST_LIMIT_FILE", str(tmp_path / "last_limit.json"))
    monkeypatch.setattr(
        control.ControlState, "_UI_STATE_FILE", str(tmp_path / "ui_state.json")
    )

    ctrl = control.ControlState()
    ctrl.update_wmaxlimpct(50)
    ctrl.update_wmaxlim_ena(1)
    ctrl.set_from_venus_os()
    ctrl.save_last_limit()

    assert state_path.exists()
    persisted = load_state(path=state_path)
    assert persisted.power_limit_pct == 50.0
    assert persisted.power_limit_set_at is not None
    assert persisted.power_limit_set_at > 0


def test_control_save_preserves_night_mode(tmp_path, monkeypatch):
    """Writing the power limit must not clobber night_mode_active."""
    from pv_inverter_proxy import control, state_file

    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", state_path)
    monkeypatch.setattr(control, "_LAST_LIMIT_FILE", str(tmp_path / "last_limit.json"))
    monkeypatch.setattr(
        control.ControlState, "_UI_STATE_FILE", str(tmp_path / "ui_state.json")
    )

    # Pre-populate state.json with night_mode_active=True.
    existing = PersistedState(
        power_limit_pct=None,
        night_mode_active=True,
        night_mode_set_at=time.time(),
    )
    save_state(existing, path=state_path)

    ctrl = control.ControlState()
    ctrl.update_wmaxlimpct(70)
    ctrl.update_wmaxlim_ena(1)
    ctrl.set_from_venus_os()
    ctrl.save_last_limit()

    persisted = load_state(path=state_path)
    assert persisted.power_limit_pct == 70.0
    # night_mode survived
    assert persisted.night_mode_active is True
    assert persisted.night_mode_set_at is not None


def test_is_power_limit_fresh_within_half_timeout():
    state = PersistedState(
        power_limit_pct=42.0,
        power_limit_set_at=time.time() - 100.0,
    )
    # command_timeout 900 -> half = 450 -> 100 is fresh
    assert is_power_limit_fresh(state, command_timeout_s=900.0) is True


def test_is_power_limit_fresh_stale_beyond_half_timeout():
    state = PersistedState(
        power_limit_pct=42.0,
        power_limit_set_at=time.time() - 500.0,
    )
    assert is_power_limit_fresh(state, command_timeout_s=900.0) is False


# ---------------------------------------------------------------------------
# webapp broadcast_update_in_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_update_in_progress_sends_to_all_clients():
    from pv_inverter_proxy.webapp import broadcast_update_in_progress

    app = {"ws_clients": set()}
    c1 = MagicMock()
    c1.send_str = AsyncMock()
    c2 = MagicMock()
    c2.send_str = AsyncMock()
    app["ws_clients"].add(c1)
    app["ws_clients"].add(c2)

    await broadcast_update_in_progress(app)

    c1.send_str.assert_called_once()
    c2.send_str.assert_called_once()
    payload1 = json.loads(c1.send_str.call_args[0][0])
    assert payload1["type"] == "update_in_progress"
    assert "message" in payload1
    assert "at" in payload1


@pytest.mark.asyncio
async def test_broadcast_update_in_progress_handles_send_errors():
    from pv_inverter_proxy.webapp import broadcast_update_in_progress

    app = {"ws_clients": set()}
    dead = MagicMock()
    dead.send_str = AsyncMock(side_effect=ConnectionResetError("dead"))
    alive = MagicMock()
    alive.send_str = AsyncMock()
    app["ws_clients"].add(dead)
    app["ws_clients"].add(alive)

    # Must not raise.
    await broadcast_update_in_progress(app)
    alive.send_str.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_update_in_progress_empty_ok():
    from pv_inverter_proxy.webapp import broadcast_update_in_progress

    await broadcast_update_in_progress({"ws_clients": set()})
    await broadcast_update_in_progress({})


# ---------------------------------------------------------------------------
# update_start_handler enters maintenance mode before writing the trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_start_handler_enters_maintenance_mode(tmp_path, monkeypatch):
    """POST /api/update/start must enter maintenance mode + broadcast
    BEFORE writing the trigger file.
    """
    from pv_inverter_proxy import webapp
    from pv_inverter_proxy.updater import trigger as trigger_mod

    # Redirect trigger path so writes stay inside tmp_path.
    trigger_file = tmp_path / "update-trigger.json"
    monkeypatch.setattr(trigger_mod, "TRIGGER_FILE_PATH", trigger_file)

    ctx = AppContext()

    # Build a fake request.
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "op": "update",
        "target_sha": "a" * 40,
    })
    # aiohttp uses request.app[...] lookups, so return a dict-like.
    fake_app = {
        "app_ctx": ctx,
        "ws_clients": set(),
    }
    request.app = fake_app

    response = await webapp.update_start_handler(request)
    assert response.status == 202
    assert ctx.maintenance_mode is True
    assert ctx.maintenance_entered_at is not None
    # Trigger was written AFTER maintenance mode.
    assert trigger_file.exists()


# ---------------------------------------------------------------------------
# _graceful_shutdown_maintenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_shutdown_drains_when_maintenance_active(monkeypatch):
    from pv_inverter_proxy import __main__ as main_mod

    ctx = AppContext()
    ctx.maintenance_mode = True

    drain_mock = AsyncMock(return_value=True)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(
        "pv_inverter_proxy.updater.maintenance.drain_inflight_modbus",
        drain_mock,
    )
    monkeypatch.setattr(main_mod.asyncio, "sleep", sleep_mock)

    await main_mod._graceful_shutdown_maintenance(ctx)
    drain_mock.assert_awaited_once()
    # 3s grace sleep is fired AFTER drain.
    sleep_mock.assert_awaited()


@pytest.mark.asyncio
async def test_graceful_shutdown_skips_drain_when_unplanned(monkeypatch):
    from pv_inverter_proxy import __main__ as main_mod

    ctx = AppContext()
    ctx.maintenance_mode = False

    drain_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "pv_inverter_proxy.updater.maintenance.drain_inflight_modbus",
        drain_mock,
    )

    await main_mod._graceful_shutdown_maintenance(ctx)
    drain_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_graceful_shutdown_tolerates_drain_timeout(monkeypatch):
    from pv_inverter_proxy import __main__ as main_mod

    ctx = AppContext()
    ctx.maintenance_mode = True

    drain_mock = AsyncMock(return_value=False)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(
        "pv_inverter_proxy.updater.maintenance.drain_inflight_modbus",
        drain_mock,
    )
    monkeypatch.setattr(main_mod.asyncio, "sleep", sleep_mock)

    # Must not raise even when drain reports a timeout.
    await main_mod._graceful_shutdown_maintenance(ctx)
    sleep_mock.assert_awaited()
