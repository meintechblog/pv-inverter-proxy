"""Plan 45-05 Task 2 tests for updater/maintenance.py + proxy.py gate."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.updater.maintenance import (
    MAINTENANCE_STRATEGY,
    drain_inflight_modbus,
    enter_maintenance_mode,
    exit_maintenance_mode,
    is_modbus_write_allowed,
)


# ---------------------------------------------------------------------------
# enter / exit / is_modbus_write_allowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_maintenance_mode_sets_flag():
    ctx = AppContext()
    assert ctx.maintenance_mode is False
    assert ctx.maintenance_entered_at is None
    await enter_maintenance_mode(ctx, reason="update")
    assert ctx.maintenance_mode is True
    assert ctx.maintenance_entered_at is not None
    assert ctx.maintenance_entered_at > 0


@pytest.mark.asyncio
async def test_exit_maintenance_mode_clears_flag():
    ctx = AppContext()
    await enter_maintenance_mode(ctx)
    await exit_maintenance_mode(ctx)
    assert ctx.maintenance_mode is False


def test_is_modbus_write_allowed_true_when_not_active():
    ctx = AppContext()
    assert is_modbus_write_allowed(ctx) is True


def test_is_modbus_write_allowed_false_when_active():
    ctx = AppContext()
    ctx.maintenance_mode = True
    assert is_modbus_write_allowed(ctx) is False


# ---------------------------------------------------------------------------
# drain_inflight_modbus
# ---------------------------------------------------------------------------


@dataclass
class _FakeSlaveCtx:
    _inflight_count: int = 0
    _inflight_drained: asyncio.Event | None = None


@pytest.mark.asyncio
async def test_drain_inflight_no_requests_returns_immediately():
    ctx = AppContext()
    ctx._slave_ctx = _FakeSlaveCtx(_inflight_count=0, _inflight_drained=asyncio.Event())
    ctx._slave_ctx._inflight_drained.set()
    result = await drain_inflight_modbus(ctx, timeout_s=2.0)
    assert result is True


@pytest.mark.asyncio
async def test_drain_inflight_with_pending_waits():
    ctx = AppContext()
    ev = asyncio.Event()
    slave = _FakeSlaveCtx(_inflight_count=1, _inflight_drained=ev)
    ctx._slave_ctx = slave

    async def _release():
        await asyncio.sleep(0.05)
        slave._inflight_count = 0
        ev.set()

    release_task = asyncio.create_task(_release())
    result = await drain_inflight_modbus(ctx, timeout_s=1.0)
    await release_task
    assert result is True


@pytest.mark.asyncio
async def test_drain_inflight_timeout():
    ctx = AppContext()
    ev = asyncio.Event()
    ctx._slave_ctx = _FakeSlaveCtx(_inflight_count=1, _inflight_drained=ev)
    result = await drain_inflight_modbus(ctx, timeout_s=0.1)
    assert result is False


@pytest.mark.asyncio
async def test_drain_inflight_no_slave_ctx_returns_true():
    ctx = AppContext()
    # No _slave_ctx attribute — drain is a no-op, treat as drained.
    result = await drain_inflight_modbus(ctx, timeout_s=0.1)
    assert result is True


# ---------------------------------------------------------------------------
# proxy.py maintenance gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_write_rejected_in_maintenance_slavebusy(monkeypatch):
    """With MAINTENANCE_STRATEGY='slavebusy', writes return DEVICE_BUSY."""
    from pv_inverter_proxy import proxy as proxy_mod
    from pv_inverter_proxy.control import ControlState
    from pv_inverter_proxy.proxy import StalenessAwareSlaveContext
    from pv_inverter_proxy.register_cache import RegisterCache
    from pymodbus.datastore import ModbusSequentialDataBlock
    from pymodbus.datastore.context import ExcCodes

    monkeypatch.setattr(proxy_mod, "MAINTENANCE_STRATEGY", "slavebusy")

    datablock = ModbusSequentialDataBlock(1, [0] * 2000)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.update(40003, [0] * 10)  # make cache non-stale
    ctrl = ControlState()
    ctx = AppContext()
    ctx.maintenance_mode = True
    distributor = MagicMock()
    distributor.distribute = AsyncMock()
    slave = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=ctrl,
        app_ctx=ctx, distributor=distributor, hr=datablock,
    )

    # Writing to WMaxLimPct (40154) should return DEVICE_BUSY, not call distribute.
    result = await slave.async_setValues(6, 40154, [42])
    assert result == ExcCodes.DEVICE_BUSY
    distributor.distribute.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_write_silent_drop_in_maintenance(monkeypatch):
    """With MAINTENANCE_STRATEGY='silent_drop', writes are swallowed."""
    from pv_inverter_proxy import proxy as proxy_mod
    from pv_inverter_proxy.control import ControlState
    from pv_inverter_proxy.proxy import StalenessAwareSlaveContext
    from pv_inverter_proxy.register_cache import RegisterCache
    from pymodbus.datastore import ModbusSequentialDataBlock

    monkeypatch.setattr(proxy_mod, "MAINTENANCE_STRATEGY", "silent_drop")

    datablock = ModbusSequentialDataBlock(1, [0] * 2000)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.update(40003, [0] * 10)
    ctrl = ControlState()
    ctx = AppContext()
    ctx.maintenance_mode = True
    distributor = MagicMock()
    distributor.distribute = AsyncMock()
    slave = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=ctrl,
        app_ctx=ctx, distributor=distributor, hr=datablock,
    )

    result = await slave.async_setValues(6, 40154, [42])
    assert result is None
    distributor.distribute.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_write_passes_when_maintenance_inactive():
    """Normal path: no maintenance -> distributor is called."""
    from pv_inverter_proxy.control import ControlState
    from pv_inverter_proxy.proxy import StalenessAwareSlaveContext
    from pv_inverter_proxy.register_cache import RegisterCache
    from pymodbus.datastore import ModbusSequentialDataBlock

    datablock = ModbusSequentialDataBlock(1, [0] * 2000)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.update(40003, [0] * 10)
    ctrl = ControlState()
    ctx = AppContext()
    ctx.maintenance_mode = False
    distributor = MagicMock()
    distributor.distribute = AsyncMock()
    slave = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=ctrl,
        app_ctx=ctx, distributor=distributor, hr=datablock,
    )

    await slave.async_setValues(6, 40154, [42])
    distributor.distribute.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_read_allowed_in_maintenance():
    """Reads continue to serve the cache even while maintenance is active."""
    from pv_inverter_proxy.control import ControlState
    from pv_inverter_proxy.proxy import StalenessAwareSlaveContext
    from pv_inverter_proxy.register_cache import RegisterCache
    from pv_inverter_proxy.sunspec_models import DATABLOCK_START, build_initial_registers

    initial = build_initial_registers()
    from pymodbus.datastore import ModbusSequentialDataBlock
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.update(40003, initial[:10])  # marks cache fresh
    ctrl = ControlState()
    ctx = AppContext()
    ctx.maintenance_mode = True
    slave = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=ctrl,
        app_ctx=ctx, hr=datablock,
    )

    # fc=3 holding read: must NOT raise or return ExcCodes during maintenance.
    values = slave.getValues(3, 40003, 5)
    assert isinstance(values, list)
    assert len(values) == 5


@pytest.mark.asyncio
async def test_proxy_inflight_counter_increments_and_drains():
    """async_setValues must increment and decrement the in-flight counter."""
    from pv_inverter_proxy.control import ControlState
    from pv_inverter_proxy.proxy import StalenessAwareSlaveContext
    from pv_inverter_proxy.register_cache import RegisterCache
    from pymodbus.datastore import ModbusSequentialDataBlock

    datablock = ModbusSequentialDataBlock(1, [0] * 2000)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.update(40003, [0] * 10)
    ctrl = ControlState()
    ctx = AppContext()
    distributor = MagicMock()
    distributor.distribute = AsyncMock()
    slave = StalenessAwareSlaveContext(
        cache=cache, plugin=None, control_state=ctrl,
        app_ctx=ctx, distributor=distributor, hr=datablock,
    )

    assert slave._inflight_count == 0
    assert slave._inflight_drained is not None
    await slave.async_setValues(6, 40154, [10])
    assert slave._inflight_count == 0
    assert slave._inflight_drained.is_set()


def test_maintenance_strategy_is_valid():
    assert MAINTENANCE_STRATEGY in ("slavebusy", "silent_drop")
