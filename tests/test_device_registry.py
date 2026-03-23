"""Tests for DeviceRegistry per-device lifecycle management."""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-mock dashboard module to avoid timeseries.py slots= incompatibility on Python < 3.10
if "pv_inverter_proxy.dashboard" not in sys.modules:
    _mock_dashboard = MagicMock()
    _mock_dashboard.DashboardCollector = MagicMock
    sys.modules["pv_inverter_proxy.dashboard"] = _mock_dashboard

from pv_inverter_proxy.config import Config, InverterEntry, GatewayConfig
from pv_inverter_proxy.connection import ConnectionManager, ConnectionState
from pv_inverter_proxy.context import AppContext, DeviceState
from pv_inverter_proxy.plugin import PollResult


def _make_config(*entries: InverterEntry) -> Config:
    """Create a Config with given inverter entries."""
    return Config(inverters=list(entries))


def _ok_result() -> PollResult:
    return PollResult(
        success=True,
        common_registers=[0] * 67,
        inverter_registers=[0] * 52,
    )


def _fail_result() -> PollResult:
    return PollResult(
        success=False,
        common_registers=[],
        inverter_registers=[],
        error="timeout",
    )


def _make_mock_plugin(poll_result=None):
    """Create a mock InverterPlugin."""
    plugin = AsyncMock()
    plugin.connect = AsyncMock()
    plugin.close = AsyncMock()
    plugin.poll = AsyncMock(return_value=poll_result or _ok_result())
    # get_model_120_registers is a sync method, must be MagicMock (not AsyncMock)
    plugin.get_model_120_registers = MagicMock(return_value=None)
    # get_static_common_overrides is also sync
    plugin.get_static_common_overrides = MagicMock(return_value={})
    return plugin


@pytest.fixture
def app_ctx():
    return AppContext()


@pytest.fixture
def entry_a():
    return InverterEntry(id="dev_a", host="192.168.1.10", port=502, enabled=True, type="solaredge")


@pytest.fixture
def entry_b():
    return InverterEntry(id="dev_b", host="192.168.1.11", port=502, enabled=True, type="solaredge")


@pytest.fixture
def entry_disabled():
    return InverterEntry(id="dev_off", host="192.168.1.12", port=502, enabled=False, type="solaredge")


def _patch_factories(mock_plugin):
    """Return context manager patching plugin_factory."""
    return patch("pv_inverter_proxy.plugins.plugin_factory", return_value=mock_plugin)


@pytest.mark.asyncio
async def test_start_device(app_ctx, entry_a):
    """start_device creates plugin, DeviceState, and starts poll task."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_device("dev_a")

    assert "dev_a" in app_ctx.devices
    assert "dev_a" in registry.get_active_device_ids()
    assert registry.get_active_count() == 1

    # Let poll loop run once
    await asyncio.sleep(0.05)
    mock_plugin.poll.assert_called()

    await registry.stop_all()


@pytest.mark.asyncio
async def test_start_multiple_devices(app_ctx, entry_a, entry_b):
    """start_all starts N devices, each with independent poll task."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a, entry_b)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_all()

    assert registry.get_active_count() == 2
    assert set(registry.get_active_device_ids()) == {"dev_a", "dev_b"}

    await registry.stop_all()


@pytest.mark.asyncio
async def test_stop_device(app_ctx, entry_a):
    """stop_device cancels poll task, calls plugin.close(), removes DeviceState."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_device("dev_a")
        await asyncio.sleep(0.02)
        await registry.stop_device("dev_a")

    assert "dev_a" not in app_ctx.devices
    assert registry.get_active_count() == 0
    mock_plugin.close.assert_called_once()


@pytest.mark.asyncio
async def test_enable_disable(app_ctx, entry_a):
    """disable_device stops poll + cleans up; enable_device starts fresh poll."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_device("dev_a")
        assert registry.get_active_count() == 1

        await registry.disable_device("dev_a")
        assert registry.get_active_count() == 0
        assert "dev_a" not in app_ctx.devices

        # Re-enable
        await registry.enable_device("dev_a")
        assert registry.get_active_count() == 1
        assert "dev_a" in app_ctx.devices

    await registry.stop_all()


@pytest.mark.asyncio
async def test_disabled_device_skipped(app_ctx, entry_a, entry_disabled):
    """start_all skips entries where entry.enabled=False."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a, entry_disabled)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_all()

    assert registry.get_active_count() == 1
    assert "dev_a" in registry.get_active_device_ids()
    assert "dev_off" not in registry.get_active_device_ids()

    await registry.stop_all()


@pytest.mark.asyncio
async def test_no_task_leak(app_ctx, entry_a):
    """After 5x start/stop cycles, asyncio task count stays stable."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        baseline = len(asyncio.all_tasks())

        for _ in range(5):
            await registry.start_device("dev_a")
            await asyncio.sleep(0.02)
            await registry.stop_device("dev_a")
            await asyncio.sleep(0.02)

        final = len(asyncio.all_tasks())
        assert final <= baseline + 1, f"Task leak: baseline={baseline}, final={final}"


@pytest.mark.asyncio
async def test_per_device_state(app_ctx, entry_a, entry_b):
    """Each device gets its own ConnectionManager, poll_counter, DashboardCollector."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a, entry_b)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_all()

    state_a = app_ctx.devices["dev_a"]
    state_b = app_ctx.devices["dev_b"]

    assert state_a is not state_b
    assert state_a.conn_mgr is not state_b.conn_mgr
    assert state_a.poll_counter is not state_b.poll_counter
    assert state_a.collector is not state_b.collector

    await registry.stop_all()


@pytest.mark.asyncio
async def test_on_poll_success_callback(app_ctx, entry_a):
    """Successful poll calls on_poll_success callback with device_id."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    mock_plugin = _make_mock_plugin()
    with _patch_factories(mock_plugin):
        await registry.start_device("dev_a")
        await asyncio.sleep(0.05)

    on_success.assert_called_with("dev_a")

    await registry.stop_all()


@pytest.mark.asyncio
async def test_poll_loop_handles_cancel(app_ctx, entry_a):
    """CancelledError propagates out of poll loop (not caught by except Exception)."""
    from pv_inverter_proxy.device_registry import _device_poll_loop

    on_success = AsyncMock()

    mock_plugin = _make_mock_plugin()
    # Make poll raise CancelledError
    mock_plugin.poll = AsyncMock(side_effect=asyncio.CancelledError)

    device_state = DeviceState(
        conn_mgr=ConnectionManager(poll_interval=0.01),
        poll_counter={"success": 0, "total": 0},
    )

    task = asyncio.create_task(
        _device_poll_loop(
            device_id="dev_a",
            plugin=mock_plugin,
            device_state=device_state,
            poll_interval=0.01,
            on_success=on_success,
            app_ctx=app_ctx,
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_backoff_on_failure(app_ctx, entry_a):
    """After poll failure, sleep_duration follows ConnectionManager backoff."""
    from pv_inverter_proxy.device_registry import DeviceRegistry

    config = _make_config(entry_a)
    on_success = AsyncMock()
    registry = DeviceRegistry(app_ctx, config, on_poll_success=on_success)

    # Override proxy poll_interval so the poll loop runs fast
    config.proxy.poll_interval = 0.01

    mock_plugin = _make_mock_plugin(poll_result=_fail_result())
    with _patch_factories(mock_plugin):
        await registry.start_device("dev_a")
        # Let enough poll failures happen (need 3+ for RECONNECTING with 3-strike rule)
        await asyncio.sleep(0.3)

    state = app_ctx.devices.get("dev_a")
    if state and state.conn_mgr:
        cm = state.conn_mgr
        # After 3+ failures, state should be RECONNECTING and backoff > initial
        assert cm.state != ConnectionState.CONNECTED
        assert cm.sleep_duration >= ConnectionManager.INITIAL_BACKOFF

    await registry.stop_all()
