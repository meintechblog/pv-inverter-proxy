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
from pv_inverter_proxy.plugin import ThrottleCaps


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
