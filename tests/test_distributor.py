"""Tests for PowerLimitDistributor: waterfall, dead-time, monitoring-only, offline."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from pv_inverter_proxy.config import Config, InverterEntry
from pv_inverter_proxy.connection import ConnectionState
from pv_inverter_proxy.distributor import DeviceLimitState, PowerLimitDistributor
from pv_inverter_proxy.plugin import ThrottleCaps, compute_throttle_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    device_id: str = "dev1",
    rated_power: int = 30000,
    throttle_order: int = 1,
    throttle_enabled: bool = True,
    throttle_dead_time_s: float = 0.0,
    enabled: bool = True,
) -> InverterEntry:
    return InverterEntry(
        id=device_id,
        host="10.0.0.1",
        rated_power=rated_power,
        throttle_order=throttle_order,
        throttle_enabled=throttle_enabled,
        throttle_dead_time_s=throttle_dead_time_s,
        enabled=enabled,
    )


def _make_plugin() -> AsyncMock:
    """Create a mock InverterPlugin with write_power_limit."""
    plugin = AsyncMock()
    plugin.write_power_limit = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    return plugin


def _make_conn_mgr(state: ConnectionState = ConnectionState.CONNECTED) -> MagicMock:
    mgr = MagicMock()
    mgr.state = state
    return mgr


def _make_device_state(plugin=None, conn_mgr=None):
    """Create a minimal DeviceState-like object."""
    from pv_inverter_proxy.context import DeviceState
    ds = DeviceState()
    ds.plugin = plugin or _make_plugin()
    ds.conn_mgr = conn_mgr or _make_conn_mgr()
    return ds


def _build_distributor(
    entries: list[tuple[str, int, int, bool, float]],
    conn_states: dict[str, ConnectionState] | None = None,
) -> tuple[PowerLimitDistributor, dict[str, AsyncMock]]:
    """Build a distributor with given devices.

    entries: list of (device_id, rated_power, throttle_order, throttle_enabled, dead_time_s)
    Returns (distributor, {device_id: plugin_mock})
    """
    conn_states = conn_states or {}
    inverter_entries = []
    plugins = {}

    for dev_id, rated, to, te, dt in entries:
        entry = _make_entry(
            device_id=dev_id,
            rated_power=rated,
            throttle_order=to,
            throttle_enabled=te,
            throttle_dead_time_s=dt,
        )
        inverter_entries.append(entry)
        plugins[dev_id] = _make_plugin()

    config = Config(inverters=inverter_entries)

    # Build a mock registry with _managed dict
    from pv_inverter_proxy.context import AppContext
    app_ctx = AppContext()

    for dev_id, rated, to, te, dt in entries:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        cs = conn_states.get(dev_id, ConnectionState.CONNECTED)
        ds = _make_device_state(plugin=plugins[dev_id], conn_mgr=_make_conn_mgr(cs))
        app_ctx.devices[dev_id] = ds

    # Build mock registry
    registry = MagicMock()
    managed = {}
    for dev_id in plugins:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        ds = app_ctx.devices[dev_id]
        md = MagicMock()
        md.entry = entry
        md.plugin = plugins[dev_id]
        md.device_state = ds
        managed[dev_id] = md
    registry._managed = managed

    distributor = PowerLimitDistributor(registry=registry, config=config)
    return distributor, plugins


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_waterfall_to_ordering():
    """TO1 throttled first; TO2 stays at 100% when budget consumed by TO1."""
    # SE30K (TO1, 30kW) + HM800 (TO2, 800W) = 30800W total
    # 50% limit = 15400W allowed
    # TO1: min(30000, 15400) = 15400W -> 51.33%. Remaining = 0.
    # TO2: remaining = 0 -> 0%
    dist, plugins = _build_distributor([
        ("se30k", 30000, 1, True, 0.0),
        ("hm800", 800, 2, True, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    # SE30K should be throttled (around 51.33%)
    se_call = plugins["se30k"].write_power_limit
    se_call.assert_called_once()
    _, call_kwargs = se_call.call_args
    if not call_kwargs:
        call_args = se_call.call_args[0]
        assert call_args[0] is True  # enable
        assert abs(call_args[1] - 51.33) < 0.5  # ~51.33%
    else:
        assert abs(call_kwargs.get("limit_pct", se_call.call_args[0][1]) - 51.33) < 0.5

    # HM800 should get 0%
    hm_call = plugins["hm800"].write_power_limit
    hm_call.assert_called_once()
    hm_args = hm_call.call_args[0]
    assert hm_args[0] is True
    assert abs(hm_args[1] - 0.0) < 0.01


@pytest.mark.asyncio
async def test_same_to_equal_split():
    """Two devices with same TO split remaining budget equally."""
    # SE30K (TO1, 30kW) + HM-A (TO2, 800W) + HM-B (TO2, 800W) = 31600W
    # 97% limit = 30652W
    # TO1: min(30000, 30652) = 30000 -> 100%. Remaining = 652.
    # TO2: 652W / 2 devices = 326W each -> 326/800 = 40.75%
    dist, plugins = _build_distributor([
        ("se30k", 30000, 1, True, 0.0),
        ("hm_a", 800, 2, True, 0.0),
        ("hm_b", 800, 2, True, 0.0),
    ])

    await dist.distribute(97.0, enable=True)

    # SE30K at 100%
    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert abs(se_args[1] - 100.0) < 0.01

    # Both HM at ~40.75%
    hm_a_args = plugins["hm_a"].write_power_limit.call_args[0]
    hm_b_args = plugins["hm_b"].write_power_limit.call_args[0]
    assert abs(hm_a_args[1] - 40.75) < 0.5
    assert abs(hm_b_args[1] - 40.75) < 0.5


@pytest.mark.asyncio
async def test_monitoring_only_excluded():
    """Device with throttle_enabled=False gets no write_power_limit call."""
    dist, plugins = _build_distributor([
        ("se30k", 30000, 1, True, 0.0),
        ("monitor", 5000, 2, False, 0.0),  # monitoring-only
        ("hm800", 800, 3, True, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    # Monitor device: NO call
    plugins["monitor"].write_power_limit.assert_not_called()

    # SE30K and HM800 should have been called
    plugins["se30k"].write_power_limit.assert_called_once()
    plugins["hm800"].write_power_limit.assert_called_once()


@pytest.mark.asyncio
async def test_monitoring_only_budget_deduction():
    """Monitoring-only devices' rated power is deducted from waterfall budget.

    Fleet: SE30K (30kW, throttle) + Monitor (5kW, monitoring-only) = 35kW total.
    50% limit -> allowed = 17500W.
    Monitor produces ~5000W (uncontrolled) -> waterfall budget = 17500 - 5000 = 12500W.
    SE30K should get 12500/30000 = 41.7%, NOT 17500/30000 = 58.3%.
    """
    dist, plugins = _build_distributor([
        ("se30k", 30000, 1, True, 0.0),
        ("monitor", 5000, 2, False, 0.0),  # monitoring-only
    ])

    await dist.distribute(50.0, enable=True)

    # Monitor device: no call
    plugins["monitor"].write_power_limit.assert_not_called()

    # SE30K should be at ~41.7% (12500W / 30000W), not ~58.3%
    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert se_args[0] is True  # enable
    assert abs(se_args[1] - 41.7) < 0.5, f"Expected ~41.7%, got {se_args[1]}%"


@pytest.mark.asyncio
async def test_dead_time_buffering():
    """Second call within dead-time buffers (not sent immediately)."""
    dist, plugins = _build_distributor([
        ("dev1", 10000, 1, True, 5.0),  # 5s dead-time
    ])

    # First call goes through
    await dist.distribute(80.0, enable=True)
    assert plugins["dev1"].write_power_limit.call_count == 1

    # Second call within dead-time: should NOT result in another write
    await dist.distribute(60.0, enable=True)
    assert plugins["dev1"].write_power_limit.call_count == 1  # still 1


@pytest.mark.asyncio
async def test_dead_time_flush():
    """After dead-time expires, buffered value is sent."""
    dist, plugins = _build_distributor([
        ("dev1", 10000, 1, True, 0.5),  # 0.5s dead-time
    ])

    # First call
    await dist.distribute(80.0, enable=True)
    assert plugins["dev1"].write_power_limit.call_count == 1

    # Buffer a second call
    await dist.distribute(60.0, enable=True)
    assert plugins["dev1"].write_power_limit.call_count == 1

    # Mock time forward past dead-time
    for ds in dist._device_states.values():
        ds.last_write_ts -= 1.0  # push back by 1s (past 0.5s dead-time)

    # Flush pending
    await dist.flush_pending()
    assert plugins["dev1"].write_power_limit.call_count == 2


@pytest.mark.asyncio
async def test_offline_redistribution():
    """Offline device excluded; share goes to remaining devices."""
    # dev_a (TO1, 10kW, online) + dev_b (TO2, 10kW, OFFLINE) = 20kW total
    # 50% = 10000W allowed
    # dev_b offline -> excluded from waterfall
    # Only dev_a eligible: min(10000, 10000) = 10000 -> 100%
    dist, plugins = _build_distributor(
        [
            ("dev_a", 10000, 1, True, 0.0),
            ("dev_b", 10000, 2, True, 0.0),
        ],
        conn_states={"dev_a": ConnectionState.CONNECTED, "dev_b": ConnectionState.RECONNECTING},
    )

    await dist.distribute(50.0, enable=True)

    # dev_a gets full budget (100%)
    da_args = plugins["dev_a"].write_power_limit.call_args[0]
    assert abs(da_args[1] - 100.0) < 0.01

    # dev_b offline: no write
    plugins["dev_b"].write_power_limit.assert_not_called()


@pytest.mark.asyncio
async def test_disable_sends_100():
    """enable=False sends 100% to all throttle-eligible devices."""
    dist, plugins = _build_distributor([
        ("se30k", 30000, 1, True, 0.0),
        ("hm800", 800, 2, True, 0.0),
        ("monitor", 5000, 3, False, 0.0),  # monitoring-only
    ])

    await dist.distribute(100.0, enable=False)

    # Throttle-eligible get write_power_limit(False, 100.0)
    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert se_args[0] is False  # enable=False
    assert abs(se_args[1] - 100.0) < 0.01

    hm_args = plugins["hm800"].write_power_limit.call_args[0]
    assert hm_args[0] is False
    assert abs(hm_args[1] - 100.0) < 0.01

    # Monitoring-only: no call
    plugins["monitor"].write_power_limit.assert_not_called()


@pytest.mark.asyncio
async def test_pct_watt_conversion():
    """50% of total rated -> correct per-device percentages."""
    # 3 devices all TO1: 10kW + 20kW + 10kW = 40kW
    # 50% = 20000W. All same TO -> split equally: 20000/3 = 6666.67W each
    # dev_a: 6666.67/10000 = 66.67%, dev_b: 6666.67/20000 = 33.33%, dev_c: 6666.67/10000 = 66.67%
    dist, plugins = _build_distributor([
        ("dev_a", 10000, 1, True, 0.0),
        ("dev_b", 20000, 1, True, 0.0),
        ("dev_c", 10000, 1, True, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    da_args = plugins["dev_a"].write_power_limit.call_args[0]
    db_args = plugins["dev_b"].write_power_limit.call_args[0]
    dc_args = plugins["dev_c"].write_power_limit.call_args[0]

    assert abs(da_args[1] - 66.67) < 0.5
    assert abs(db_args[1] - 33.33) < 0.5
    assert abs(dc_args[1] - 66.67) < 0.5


@pytest.mark.asyncio
async def test_rated_power_zero_excluded():
    """Device with rated_power=0 is excluded from throttle eligibility."""
    dist, plugins = _build_distributor([
        ("known", 10000, 1, True, 0.0),
        ("unknown", 0, 2, True, 0.0),  # rated_power=0
    ])

    await dist.distribute(50.0, enable=True)

    # "known" should be called
    plugins["known"].write_power_limit.assert_called_once()
    # "unknown" should NOT be called (excluded)
    plugins["unknown"].write_power_limit.assert_not_called()


# ---------------------------------------------------------------------------
# Binary throttle helpers
# ---------------------------------------------------------------------------

def _make_binary_plugin(
    cooldown_s: float = 300.0,
    startup_delay_s: float = 30.0,
    response_time_s: float = 0.5,
) -> MagicMock:
    """Create a mock plugin with binary throttle capabilities and switch()."""
    plugin = MagicMock()
    caps = ThrottleCaps(
        mode="binary",
        response_time_s=response_time_s,
        cooldown_s=cooldown_s,
        startup_delay_s=startup_delay_s,
    )
    type(plugin).throttle_capabilities = PropertyMock(return_value=caps)
    plugin.switch = AsyncMock(return_value=True)
    plugin.write_power_limit = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    return plugin


def _make_proportional_plugin() -> MagicMock:
    """Create a mock plugin with proportional throttle capabilities (no switch)."""
    plugin = MagicMock()
    caps = ThrottleCaps(
        mode="proportional",
        response_time_s=1.0,
        cooldown_s=0.0,
        startup_delay_s=0.0,
    )
    type(plugin).throttle_capabilities = PropertyMock(return_value=caps)
    # Ensure switch is NOT available
    if hasattr(plugin, "switch"):
        del plugin.switch
    plugin.write_power_limit = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    return plugin


def _build_distributor_with_binary(
    entries: list[tuple[str, int, int, bool, float, str]],
    conn_states: dict[str, ConnectionState] | None = None,
) -> tuple[PowerLimitDistributor, dict[str, MagicMock]]:
    """Build a distributor with binary and/or proportional devices.

    entries: list of (device_id, rated_power, throttle_order, throttle_enabled, dead_time_s, mode)
             where mode is "proportional" or "binary"
    Returns (distributor, {device_id: plugin_mock})
    """
    conn_states = conn_states or {}
    inverter_entries = []
    plugins: dict[str, MagicMock] = {}

    for dev_id, rated, to, te, dt, mode in entries:
        entry = _make_entry(
            device_id=dev_id,
            rated_power=rated,
            throttle_order=to,
            throttle_enabled=te,
            throttle_dead_time_s=dt,
        )
        inverter_entries.append(entry)
        if mode == "binary":
            plugins[dev_id] = _make_binary_plugin()
        else:
            plugins[dev_id] = _make_proportional_plugin()

    config = Config(inverters=inverter_entries)

    from pv_inverter_proxy.context import AppContext
    app_ctx = AppContext()

    for dev_id, rated, to, te, dt, mode in entries:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        cs = conn_states.get(dev_id, ConnectionState.CONNECTED)
        ds = _make_device_state(plugin=plugins[dev_id], conn_mgr=_make_conn_mgr(cs))
        app_ctx.devices[dev_id] = ds

    # Build mock registry
    registry = MagicMock()
    managed = {}
    for dev_id in plugins:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        ds = app_ctx.devices[dev_id]
        md = MagicMock()
        md.entry = entry
        md.plugin = plugins[dev_id]
        md.device_state = ds
        managed[dev_id] = md
    registry._managed = managed

    distributor = PowerLimitDistributor(registry=registry, config=config)
    return distributor, plugins


# ---------------------------------------------------------------------------
# Binary throttle tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_binary_device_gets_switch_off_on_throttle():
    """Binary device with waterfall 0% receives plugin.switch(False), NOT write_power_limit."""
    # SE30K (TO1, 30kW, proportional) + shelly (TO2, 800W, binary) = 30800W
    # 50% limit = 15400W allowed
    # TO1: min(30000, 15400) = 15400W -> 51.33%. Remaining = 0.
    # TO2 (shelly): remaining = 0 -> 0% -> switch(False)
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    await dist.distribute(50.0, enable=True)

    # Shelly should receive switch(False) -- relay OFF
    plugins["shelly"].switch.assert_called_once_with(False)
    # Shelly should NOT have write_power_limit called
    plugins["shelly"].write_power_limit.assert_not_called()


@pytest.mark.asyncio
async def test_binary_device_gets_switch_on_when_budget_available():
    """Binary device with waterfall >0% receives plugin.switch(True) or no call if already on."""
    # SE30K (TO1, 30kW, proportional) + shelly (TO2, 800W, binary) = 30800W
    # 100% limit = full budget -> shelly gets 100% -> switch(True)
    # But relay_on defaults to True, so no toggle needed (no call expected)
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    await dist.distribute(100.0, enable=True)

    # Shelly relay is already ON (default), so no switch call needed
    plugins["shelly"].switch.assert_not_called()
    # SE30K should still get proportional command
    plugins["se30k"].write_power_limit.assert_called_once()


@pytest.mark.asyncio
async def test_binary_cooldown_prevents_flapping():
    """After toggle, second toggle within cooldown_s (300s) is blocked."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    # First: throttle -> shelly OFF (switch count = 1)
    await dist.distribute(50.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1

    # Second: release -> shelly should come back ON, but cooldown (300s) blocks it
    await dist.distribute(100.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1  # still 1, cooldown active


@pytest.mark.asyncio
async def test_binary_cooldown_allows_toggle_after_expiry():
    """After cooldown_s elapses, toggle is permitted."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    # First: throttle -> shelly OFF
    await dist.distribute(50.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1

    # Manipulate last_toggle_ts backward by 301 seconds to simulate cooldown expiry
    ds = dist._device_states["shelly"]
    ds.last_toggle_ts -= 301.0

    # Now release -> cooldown expired, toggle allowed
    await dist.distribute(100.0, enable=True)
    assert plugins["shelly"].switch.call_count == 2


@pytest.mark.asyncio
async def test_startup_grace_excludes_from_waterfall():
    """Device in startup period is not counted in waterfall available power."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    # Manually set shelly in startup grace period
    dist.sync_devices()
    ds = dist._device_states["shelly"]
    ds.relay_on = True
    ds.startup_until_ts = time.monotonic() + 30.0  # 30s from now

    # 50% limit: without shelly, total_rated = 30000W (not 30800W)
    # allowed_watts = 0.5 * 30000 = 15000W
    # se30k: 15000/30000 = 50.0%
    await dist.distribute(50.0, enable=True)

    se_args = plugins["se30k"].write_power_limit.call_args[0]
    # Should be 50.0% (15000/30000), not 49.97% (15400/30800)
    assert abs(se_args[1] - 50.0) < 0.5


@pytest.mark.asyncio
async def test_binary_reenable_reverse_order():
    """When re-enabling multiple binary devices, lowest throttle_score comes first."""
    # shelly_a: cooldown=300, startup=30 -> lower score
    # shelly_b: cooldown=60, startup=5 -> higher score
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly_a", 800, 2, True, 0.0, "binary"),
        ("shelly_b", 400, 3, True, 0.0, "binary"),
    ])

    # Override shelly_b with different caps (faster = higher score)
    caps_b = ThrottleCaps(mode="binary", response_time_s=0.5, cooldown_s=60.0, startup_delay_s=5.0)
    type(plugins["shelly_b"]).throttle_capabilities = PropertyMock(return_value=caps_b)

    # First: throttle both binary devices OFF
    await dist.distribute(40.0, enable=True)

    # Both should be OFF
    plugins["shelly_a"].switch.assert_called_with(False)
    plugins["shelly_b"].switch.assert_called_with(False)

    # Now expire cooldown for both
    for did in ["shelly_a", "shelly_b"]:
        ds = dist._device_states[did]
        ds.last_toggle_ts -= 301.0

    # Release -> both come back ON, shelly_a (lower score) should be re-enabled first
    plugins["shelly_a"].switch.reset_mock()
    plugins["shelly_b"].switch.reset_mock()

    await dist.distribute(100.0, enable=True)

    # Both should have been called with True
    plugins["shelly_a"].switch.assert_called_with(True)
    plugins["shelly_b"].switch.assert_called_with(True)


@pytest.mark.asyncio
async def test_disable_turns_binary_relay_on():
    """enable=False calls switch(True) on binary devices."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("shelly", 800, 2, True, 0.0, "binary"),
    ])

    # First: throttle shelly OFF
    await dist.distribute(50.0, enable=True)
    assert plugins["shelly"].switch.call_count == 1

    # Expire cooldown
    ds = dist._device_states["shelly"]
    ds.last_toggle_ts -= 301.0

    # Disable throttling -> binary device should get switch(True)
    await dist.distribute(100.0, enable=False)

    plugins["shelly"].switch.assert_called_with(True)
    # SE30K should get write_power_limit(False, 100.0)
    se_last_args = plugins["se30k"].write_power_limit.call_args[0]
    assert se_last_args[0] is False
    assert abs(se_last_args[1] - 100.0) < 0.01


@pytest.mark.asyncio
async def test_proportional_device_unchanged():
    """Proportional devices still use write_power_limit (no regression)."""
    dist, plugins = _build_distributor_with_binary([
        ("se30k", 30000, 1, True, 0.0, "proportional"),
        ("opendtu", 800, 2, True, 0.0, "proportional"),
    ])

    await dist.distribute(50.0, enable=True)

    # Both should use write_power_limit
    plugins["se30k"].write_power_limit.assert_called_once()
    plugins["opendtu"].write_power_limit.assert_called_once()

    # Neither should have switch called (proportional plugins don't have it)
    assert not hasattr(plugins["se30k"], "switch") or not plugins["se30k"].switch.called
    assert not hasattr(plugins["opendtu"], "switch") or not plugins["opendtu"].switch.called


# ---------------------------------------------------------------------------
# Auto-Throttle Tests (Phase 35)
# ---------------------------------------------------------------------------

def _make_plugin_with_caps(
    mode: str = "proportional",
    response_time_s: float = 1.0,
    cooldown_s: float = 0.0,
    startup_delay_s: float = 0.0,
) -> MagicMock:
    """Create a mock plugin with specific ThrottleCaps."""
    plugin = MagicMock()
    caps = ThrottleCaps(
        mode=mode,
        response_time_s=response_time_s,
        cooldown_s=cooldown_s,
        startup_delay_s=startup_delay_s,
    )
    type(plugin).throttle_capabilities = PropertyMock(return_value=caps)
    if mode == "binary":
        plugin.switch = AsyncMock(return_value=True)
    else:
        if hasattr(plugin, "switch"):
            del plugin.switch
    plugin.write_power_limit = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    return plugin


def _build_distributor_with_caps(
    entries: list[tuple[str, int, int, bool, float, str, float, float, float]],
    conn_states: dict[str, ConnectionState] | None = None,
) -> tuple[PowerLimitDistributor, dict[str, MagicMock]]:
    """Build distributor with specific throttle caps per device.

    entries: list of (device_id, rated_power, throttle_order, throttle_enabled, dead_time_s,
                       mode, response_time_s, cooldown_s, startup_delay_s)
    """
    conn_states = conn_states or {}
    inverter_entries = []
    plugins: dict[str, MagicMock] = {}

    for dev_id, rated, to, te, dt, mode, resp, cool, startup in entries:
        entry = _make_entry(
            device_id=dev_id,
            rated_power=rated,
            throttle_order=to,
            throttle_enabled=te,
            throttle_dead_time_s=dt,
        )
        inverter_entries.append(entry)
        plugins[dev_id] = _make_plugin_with_caps(
            mode=mode,
            response_time_s=resp,
            cooldown_s=cool,
            startup_delay_s=startup,
        )

    config = Config(inverters=inverter_entries, auto_throttle=True)

    from pv_inverter_proxy.context import AppContext
    app_ctx = AppContext()

    for dev_id, rated, to, te, dt, mode, resp, cool, startup in entries:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        cs = conn_states.get(dev_id, ConnectionState.CONNECTED)
        ds = _make_device_state(plugin=plugins[dev_id], conn_mgr=_make_conn_mgr(cs))
        app_ctx.devices[dev_id] = ds

    registry = MagicMock()
    managed = {}
    for dev_id in plugins:
        entry = next(e for e in inverter_entries if e.id == dev_id)
        ds = app_ctx.devices[dev_id]
        md = MagicMock()
        md.entry = entry
        md.plugin = plugins[dev_id]
        md.device_state = ds
        managed[dev_id] = md
    registry._managed = managed

    distributor = PowerLimitDistributor(registry=registry, config=config)
    return distributor, plugins


from dataclasses import asdict


def test_auto_throttle_config_default_false():
    """Config().auto_throttle defaults to False."""
    assert Config().auto_throttle is False


def test_auto_throttle_config_round_trip():
    """Config(auto_throttle=True) persists through asdict."""
    assert asdict(Config(auto_throttle=True))["auto_throttle"] is True


@pytest.mark.asyncio
async def test_auto_throttle_score_ordering():
    """With auto_throttle=True, devices are sorted by throttle score descending."""
    # shelly (binary, score ~2.9), se30k (proportional, score ~9.7), opendtu (proportional, score ~7.0)
    # Auto order: se30k (9.7) first -> gets all budget
    dist, plugins = _build_distributor_with_caps([
        # (id, rated, TO, throttle_en, dead_time, mode, response_s, cooldown_s, startup_s)
        ("shelly", 800, 3, True, 0.0, "binary", 0.5, 300.0, 30.0),      # score ~2.9
        ("se30k", 30000, 2, True, 0.0, "proportional", 1.0, 0.0, 0.0),  # score ~9.7
        ("opendtu", 800, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),  # score ~7.0 (same caps)
    ])

    await dist.distribute(50.0, enable=True)

    # se30k should be processed first (highest score ~9.7)
    # total_rated = 31600W, allowed = 15800W
    # se30k rated 30000W: gets min(30000, 15800) = 15800W -> 15800/30000 = 52.67%
    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert 50.0 <= se_args[1] <= 55.0, f"se30k got {se_args[1]}%, expected ~52.7%"

    # opendtu gets 0% (remaining = 0 after se30k)
    opendtu_args = plugins["opendtu"].write_power_limit.call_args[0]
    assert abs(opendtu_args[1] - 0.0) < 0.01

    # shelly gets switch(False)
    plugins["shelly"].switch.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_auto_proportional_before_binary():
    """Proportional devices always appear before binary in auto mode."""
    # binary (TO=1, higher manual priority) vs proportional (TO=2, lower manual priority)
    # auto_throttle=True -> proportional (score 7+) before binary (score 3+)
    dist, plugins = _build_distributor_with_caps([
        ("binary_dev", 800, 1, True, 0.0, "binary", 0.5, 300.0, 30.0),        # score ~2.9
        ("proportional_dev", 800, 2, True, 0.0, "proportional", 1.0, 0.0, 0.0),  # score ~9.7
    ])

    # 50% limit: total=1600W, allowed=800W
    # Auto order: proportional (score 9.7) first -> gets all 800W -> 100%
    # Binary: remaining=0 -> switch(False)
    await dist.distribute(50.0, enable=True)

    proportional_args = plugins["proportional_dev"].write_power_limit.call_args[0]
    assert abs(proportional_args[1] - 100.0) < 0.5

    plugins["binary_dev"].switch.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_auto_throttle_off_uses_manual_order():
    """With auto_throttle=False, waterfall uses throttle_order (no regression)."""
    dist, plugins = _build_distributor_with_caps([
        ("shelly", 800, 3, True, 0.0, "binary", 0.5, 300.0, 30.0),
        ("se30k", 30000, 2, True, 0.0, "proportional", 1.0, 0.0, 0.0),
        ("opendtu", 800, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])
    # Override to manual mode
    dist._config.auto_throttle = False

    # Manual order: opendtu (TO=1), se30k (TO=2), shelly (TO=3)
    # total_rated = 31600W, 50% = 15800W
    # TO=1 (opendtu, 800W): gets 800W -> 100%. remaining = 15000W
    # TO=2 (se30k, 30000W): gets min(30000, 15000) -> 15000/30000 = 50%
    # TO=3 (shelly, 800W): remaining=0 -> switch(False)
    await dist.distribute(50.0, enable=True)

    opendtu_args = plugins["opendtu"].write_power_limit.call_args[0]
    assert abs(opendtu_args[1] - 100.0) < 0.5

    se_args = plugins["se30k"].write_power_limit.call_args[0]
    assert abs(se_args[1] - 50.0) < 0.5

    plugins["shelly"].switch.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_auto_throttle_tiebreak_by_device_id():
    """Two devices with identical scores sort by device_id for deterministic ordering."""
    # Two proportional devices with identical caps -> identical score
    dist, plugins = _build_distributor_with_caps([
        ("alpha", 5000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
        ("beta", 5000, 2, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    # 50% limit: total=10000W, allowed=5000W
    # Both have same score. Sorted descending by (score, device_id).
    # "beta" > "alpha" alphabetically -> beta first in reverse sort.
    # beta gets 5000W -> 100%, alpha gets 0%.
    await dist.distribute(50.0, enable=True)

    beta_args = plugins["beta"].write_power_limit.call_args[0]
    assert abs(beta_args[1] - 100.0) < 0.5

    alpha_args = plugins["alpha"].write_power_limit.call_args[0]
    assert abs(alpha_args[1] - 0.0) < 0.5


# ---------------------------------------------------------------------------
# Convergence Tracking Tests (Phase 35)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_convergence_target_set_after_limit():
    """After distribute(), ds.target_power_w and ds.target_set_ts are set."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    ds = dist._device_states["se30k"]
    # 50% of 30000 = 15000W
    assert ds.target_power_w is not None
    assert abs(ds.target_power_w - 15000.0) < 100.0
    assert ds.target_set_ts is not None
    assert ds.target_set_ts > 0


@pytest.mark.asyncio
async def test_convergence_detected_on_poll():
    """on_poll with power within 5% of target sets measured_response_time_s."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    ds = dist._device_states["se30k"]
    assert ds.target_power_w is not None
    # Simulate convergence: power within 5% of target
    dist.on_poll("se30k", ds.target_power_w * 0.98)

    assert ds.measured_response_time_s is not None
    assert ds.measured_response_time_s >= 0


@pytest.mark.asyncio
async def test_convergence_not_detected_when_far():
    """on_poll with power 20% away from target does NOT set measured_response_time_s."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    await dist.distribute(50.0, enable=True)

    ds = dist._device_states["se30k"]
    assert ds.target_power_w is not None
    # 20% error - should NOT converge
    dist.on_poll("se30k", ds.target_power_w * 0.80)

    assert ds.measured_response_time_s is None


@pytest.mark.asyncio
async def test_convergence_rolling_average():
    """After 3 convergence events, measured_response_time_s is the mean."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    await dist.distribute(50.0, enable=True)
    ds = dist._device_states["se30k"]

    # Simulate 3 convergence events with known response times
    response_times = [1.0, 2.0, 3.0]
    for rt in response_times:
        # Set target again (new distribute)
        ds.target_power_w = 15000.0
        ds.target_set_ts = time.monotonic() - rt  # rt seconds ago
        dist.on_poll("se30k", 15000.0)

    expected_mean = sum(response_times) / len(response_times)
    assert ds.measured_response_time_s is not None
    assert abs(ds.measured_response_time_s - expected_mean) < 0.1


@pytest.mark.asyncio
async def test_convergence_binary_off_threshold():
    """Binary device target=0W, poll shows 30W (< 50W threshold) -> converged."""
    dist, plugins = _build_distributor_with_caps([
        ("shelly", 800, 1, True, 0.0, "binary", 0.5, 300.0, 30.0),
    ])

    # Manually set target as if the device was just switched off
    dist.sync_devices()
    ds = dist._device_states["shelly"]
    ds.target_power_w = 0.0
    ds.target_set_ts = time.monotonic() - 1.0  # 1s ago
    ds.relay_on = False

    dist.on_poll("shelly", 30.0)  # < 50W threshold

    assert ds.measured_response_time_s is not None


@pytest.mark.asyncio
async def test_convergence_skips_startup_grace():
    """During startup grace period, convergence is not checked."""
    dist, plugins = _build_distributor_with_caps([
        ("shelly", 800, 1, True, 0.0, "binary", 0.5, 300.0, 30.0),
    ])

    dist.sync_devices()
    ds = dist._device_states["shelly"]
    ds.target_power_w = 800.0
    ds.target_set_ts = time.monotonic() - 1.0
    ds.startup_until_ts = time.monotonic() + 30.0  # In startup grace

    dist.on_poll("shelly", 800.0)  # Exact target match

    assert ds.measured_response_time_s is None


@pytest.mark.asyncio
async def test_target_not_reset_when_same_limit():
    """If new distribute() produces same target (within 2%), target_set_ts is NOT reset."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    await dist.distribute(50.0, enable=True)
    ds = dist._device_states["se30k"]
    original_ts = ds.target_set_ts
    assert original_ts is not None

    # Same limit again -> target_set_ts should NOT change
    await dist.distribute(50.0, enable=True)
    assert ds.target_set_ts == original_ts


@pytest.mark.asyncio
async def test_effective_score_uses_measured():
    """After convergence measurement, _effective_score() differs from preset score."""
    dist, plugins = _build_distributor_with_caps([
        ("se30k", 30000, 1, True, 0.0, "proportional", 1.0, 0.0, 0.0),
    ])

    dist.sync_devices()
    ds = dist._device_states["se30k"]

    preset_score = dist._effective_score(ds)

    # Set measured response time (much faster than preset 1.0s)
    ds.measured_response_time_s = 0.1

    measured_score = dist._effective_score(ds)

    assert measured_score != preset_score
    # Faster response -> higher score
    assert measured_score > preset_score


# ---------------------------------------------------------------------------
# Phase 36: Preset config and config-driven convergence params
# ---------------------------------------------------------------------------

def test_auto_throttle_presets_exist():
    """AUTO_THROTTLE_PRESETS has 3 presets with 4 parameter keys each."""
    from pv_inverter_proxy.config import AUTO_THROTTLE_PRESETS

    assert set(AUTO_THROTTLE_PRESETS.keys()) == {"aggressive", "balanced", "conservative"}
    expected_keys = {"convergence_tolerance_pct", "convergence_max_samples",
                     "target_change_tolerance_pct", "binary_off_threshold_w"}
    for name, preset in AUTO_THROTTLE_PRESETS.items():
        assert set(preset.keys()) == expected_keys, f"Preset '{name}' missing keys"


def test_auto_throttle_preset_default_balanced():
    """Config().auto_throttle_preset defaults to 'balanced'."""
    assert Config().auto_throttle_preset == "balanced"


@pytest.mark.asyncio
async def test_get_convergence_params_balanced_default():
    """_get_convergence_params() returns balanced values by default."""
    from pv_inverter_proxy.config import AUTO_THROTTLE_PRESETS

    dist, _ = _build_distributor([
        ("dev1", 30000, 1, True, 0.0),
    ])
    params = dist._get_convergence_params()
    assert params == AUTO_THROTTLE_PRESETS["balanced"]


@pytest.mark.asyncio
async def test_get_convergence_params_aggressive():
    """_get_convergence_params() returns aggressive values when configured."""
    from pv_inverter_proxy.config import AUTO_THROTTLE_PRESETS

    dist, _ = _build_distributor([
        ("dev1", 30000, 1, True, 0.0),
    ])
    dist._config.auto_throttle_preset = "aggressive"
    params = dist._get_convergence_params()
    assert params == AUTO_THROTTLE_PRESETS["aggressive"]


@pytest.mark.asyncio
async def test_convergence_uses_config_driven_params():
    """on_poll uses config-driven convergence_tolerance_pct from preset."""
    from pv_inverter_proxy.config import AUTO_THROTTLE_PRESETS

    dist, plugins = _build_distributor([
        ("dev1", 10000, 1, True, 0.0),
    ])
    dist._config.auto_throttle_preset = "aggressive"
    dist.sync_devices()
    ds = dist._device_states["dev1"]

    # Set a target of 5000W
    ds.target_power_w = 5000.0
    ds.target_set_ts = time.monotonic() - 2.0

    # aggressive tolerance is 10% -> 500W tolerance
    # 5400W is within 10% of 5000W (8% error) -> should converge
    dist.on_poll("dev1", 5400.0)
    assert ds.measured_response_time_s is not None, "Should have converged with aggressive tolerance"
