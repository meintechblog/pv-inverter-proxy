"""Tests for DashboardCollector register decoding."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock

from pv_inverter_proxy.register_cache import RegisterCache
from pv_inverter_proxy.sunspec_models import build_initial_registers, DATABLOCK_START
from pv_inverter_proxy.connection import ConnectionManager, ConnectionState
from pv_inverter_proxy.control import ControlState
from pv_inverter_proxy.dashboard import DashboardCollector, _PB_OFFSET, DECODE_MAP


def _make_cache_with_values(overrides: dict[int, int | list[int]] | None = None) -> RegisterCache:
    """Build a RegisterCache with known register values.

    Args:
        overrides: dict of {sunspec_addr: value_or_list} to set in the datablock.
    """
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    cache.last_successful_poll = time.monotonic()
    cache._has_been_updated = True

    if overrides:
        for addr, val in overrides.items():
            if isinstance(val, list):
                datablock.setValues(addr + _PB_OFFSET, val)
            else:
                datablock.setValues(addr + _PB_OFFSET, [val])

    return cache


def test_read_int16_negative():
    """_read_int16 with raw=65534 returns -2 (scale factor sign conversion)."""
    cache = _make_cache_with_values({40084: 65534})  # AC Power SF
    result = DashboardCollector._read_int16(cache.datablock, 40084)
    assert result == -2


def test_read_int16_positive():
    """_read_int16 with raw=100 returns 100 (positive passthrough)."""
    cache = _make_cache_with_values({40084: 100})
    result = DashboardCollector._read_int16(cache.datablock, 40084)
    assert result == 100


def test_collect_snapshot_keys():
    """collect() produces correct snapshot dict keys."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40071: 1820,  # AC Current
        40075: 65535,  # Current SF (-1)
        40079: 2301,  # AC Voltage AN
        40082: 65535,  # Voltage SF (-1)
        40083: 12450,  # AC Power
        40084: 65534,  # Power SF (-2)
        40085: 5001,  # AC Frequency
        40086: 65534,  # Freq SF (-2)
        40103: 382,  # Sink Temp
        40106: 65535,  # Temp SF (-1)
        40107: 4,  # Status = MPPT
        40093: [0, 21543200],  # AC Energy (uint32: hi=0, lo=21543200)
        40095: 0,  # Energy SF (10^0 = 1)
    })

    snapshot = collector.collect(cache)
    inv = snapshot["inverter"]
    assert "ac_power_w" in inv
    assert "ac_current_a" in inv
    assert "ac_voltage_an_v" in inv
    assert "ac_frequency_hz" in inv
    assert "temperature_sink_c" in inv
    assert "status" in inv
    assert "energy_total_wh" in inv
    assert "control" in snapshot
    assert "connection" in snapshot


def test_collect_scale_factor_application():
    """collect() applies scale factor: raw=12450, sf=65534(-2) -> 124.5."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40083: 12450,  # AC Power raw
        40084: 65534,  # Power SF = -2
        # Set other SFs to avoid issues
        40075: 0,  # Current SF
        40082: 0,  # Voltage SF
        40086: 0,  # Freq SF
        40088: 0,  # VA SF
        40090: 0,  # VAR SF
        40092: 0,  # PF SF
        40095: 0,  # Energy SF
        40097: 0,  # DC Current SF
        40099: 0,  # DC Voltage SF
        40101: 0,  # DC Power SF
        40106: 0,  # Temp SF
        40107: 4,  # Status
    })

    snapshot = collector.collect(cache)
    assert snapshot["inverter"]["ac_power_w"] == pytest.approx(124.5)


def test_collect_uint32_energy_low():
    """collect() decodes AC Energy as uint32: hi=0, lo=21543200 -> 21543200."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40093: [0, 21543200],  # hi=0, lo=21543200
        40095: 0,  # Energy SF (10^0 = 1)
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    snapshot = collector.collect(cache)
    assert snapshot["inverter"]["energy_total_wh"] == 21543200


def test_collect_uint32_energy_high():
    """collect() decodes AC Energy as uint32: hi=1, lo=0 -> 65536."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40093: [1, 0],  # hi=1, lo=0 -> (1 << 16) | 0 = 65536
        40095: 0,
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    snapshot = collector.collect(cache)
    assert snapshot["inverter"]["energy_total_wh"] == 65536


def test_collect_feeds_timeseries_buffer():
    """collect() feeds TimeSeriesBuffer for ac_power_w."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40083: 5000, 40084: 0,  # AC Power = 5000W
        40075: 0, 40082: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40093: [0, 0], 40095: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    assert len(collector._buffers["ac_power_w"]) == 0
    collector.collect(cache)
    assert len(collector._buffers["ac_power_w"]) == 1


def test_last_snapshot_property():
    """last_snapshot property returns the most recent collect() result."""
    collector = DashboardCollector()
    assert collector.last_snapshot is None

    cache = _make_cache_with_values({
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40093: [0, 0], 40095: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    result = collector.collect(cache)
    assert collector.last_snapshot is result
    assert collector.last_snapshot is not None


def test_collect_with_control_state():
    """collect() includes control state when provided."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40093: [0, 0], 40095: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    cs = ControlState()
    cs.update_wmaxlimpct(75)
    cs.update_wmaxlim_ena(1)

    snapshot = collector.collect(cache, control_state=cs)
    assert snapshot["control"]["enabled"] is True
    assert snapshot["control"]["limit_pct"] == 75.0
    assert snapshot["control"]["wmaxlimpct_raw"] == 75


def test_collect_with_connection_info():
    """collect() includes connection info from poll_counter and conn_mgr."""
    collector = DashboardCollector()
    cache = _make_cache_with_values({
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40093: [0, 0], 40095: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,
    })

    conn_mgr = ConnectionManager(poll_interval=1.0)
    poll_counter = {"success": 4523, "total": 4530}

    snapshot = collector.collect(
        cache, conn_mgr=conn_mgr, poll_counter=poll_counter,
    )
    assert snapshot["connection"]["poll_success"] == 4523
    assert snapshot["connection"]["poll_total"] == 4530
    assert snapshot["connection"]["state"] == "connected"
    assert snapshot["connection"]["cache_stale"] == cache.is_stale


# --- Daily energy tests ---

def _zero_sf_overrides():
    """Common scale-factor overrides setting all SFs to 0."""
    return {
        40075: 0, 40082: 0, 40084: 0, 40086: 0,
        40088: 0, 40090: 0, 40092: 0,
        40097: 0, 40099: 0, 40101: 0, 40106: 0,
        40107: 4,  # Status = MPPT
    }


def test_daily_energy_first_collect_zero():
    """First collect() with energy > 0 sets baseline; daily_energy_wh == 0."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 1000000]  # energy_total_wh = 1000000
    overrides[40095] = 0  # Energy SF

    cache = _make_cache_with_values(overrides)
    snapshot = collector.collect(cache)
    inv = snapshot["inverter"]

    assert "daily_energy_wh" in inv
    assert inv["daily_energy_wh"] == 0


def test_daily_energy_delta():
    """Second collect() returns delta from baseline as daily_energy_wh."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40095] = 0

    # First collect: baseline
    overrides[40093] = [0, 1000000]
    cache1 = _make_cache_with_values(overrides)
    collector.collect(cache1)

    # Second collect: energy increased by 5000
    overrides[40093] = [0, 1005000]
    cache2 = _make_cache_with_values(overrides)
    snapshot = collector.collect(cache2)

    assert snapshot["inverter"]["daily_energy_wh"] == 5000


def test_daily_energy_reset_new_instance():
    """New DashboardCollector instance starts with daily_energy_wh == 0."""
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 5000000]
    overrides[40095] = 0

    collector = DashboardCollector()
    cache = _make_cache_with_values(overrides)
    snapshot = collector.collect(cache)

    assert snapshot["inverter"]["daily_energy_wh"] == 0


# --- Peak stats tests ---


def test_peak_power_tracking():
    """peak_power_w tracks max ac_power_w across multiple collect() calls."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0

    # First: 5000W (sf=0)
    overrides[40083] = 5000
    overrides[40084] = 0
    cache = _make_cache_with_values(overrides)
    snap1 = collector.collect(cache)
    assert snap1["inverter"]["peak_power_w"] == 5000

    # Second: 8000W -- new peak
    overrides[40083] = 8000
    cache = _make_cache_with_values(overrides)
    snap2 = collector.collect(cache)
    assert snap2["inverter"]["peak_power_w"] == 8000

    # Third: 3000W -- peak stays at 8000
    overrides[40083] = 3000
    cache = _make_cache_with_values(overrides)
    snap3 = collector.collect(cache)
    assert snap3["inverter"]["peak_power_w"] == 8000


def test_operating_hours_mppt_only(monkeypatch):
    """operating_hours increments only when status is MPPT."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    mono_time = [100.0]

    def fake_monotonic():
        return mono_time[0]

    import pv_inverter_proxy.dashboard as dash_mod
    monkeypatch.setattr(dash_mod.time, "monotonic", fake_monotonic)

    # First collect: MPPT (code 4) -- baseline, no delta yet
    overrides[40107] = 4
    cache = _make_cache_with_values(overrides)
    snap1 = collector.collect(cache)
    assert snap1["inverter"]["operating_hours"] == 0.0

    # Second collect: still MPPT, 5 seconds later
    mono_time[0] = 105.0
    cache = _make_cache_with_values(overrides)
    snap2 = collector.collect(cache)
    assert snap2["inverter"]["operating_hours"] == pytest.approx(5.0 / 3600, abs=0.001)

    # Third collect: SLEEPING (code 2), 5 seconds later -- no increment
    mono_time[0] = 110.0
    overrides[40107] = 2
    cache = _make_cache_with_values(overrides)
    snap3 = collector.collect(cache)
    # Should still be 5 seconds
    assert snap3["inverter"]["operating_hours"] == pytest.approx(5.0 / 3600, abs=0.001)


def test_efficiency_calculation():
    """efficiency_pct = ac_power / dc_power * 100."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0

    # AC=9500W, DC=10000W -> 95% efficiency
    overrides[40083] = 9500   # AC power
    overrides[40084] = 0      # AC power SF
    overrides[40100] = 10000  # DC power
    overrides[40101] = 0      # DC power SF
    cache = _make_cache_with_values(overrides)
    snap1 = collector.collect(cache)
    assert snap1["inverter"]["efficiency_pct"] == 95.0

    # AC=5000W, DC=5200W -> 96.2%
    overrides[40083] = 5000
    overrides[40100] = 5200
    cache = _make_cache_with_values(overrides)
    snap2 = collector.collect(cache)
    assert snap2["inverter"]["efficiency_pct"] == 96.2


def test_peak_stats_in_snapshot():
    """All three peak stat fields appear in snapshot['inverter']."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    snapshot = collector.collect(cache)
    inv = snapshot["inverter"]

    assert "peak_power_w" in inv
    assert "operating_hours" in inv
    assert "efficiency_pct" in inv


def test_peak_stats_reset_new_instance():
    """New DashboardCollector instance starts with peak stats at zero."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 5000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    snap1 = collector.collect(cache)
    assert snap1["inverter"]["peak_power_w"] == 5000

    # New instance -- peak resets
    collector2 = DashboardCollector()
    overrides[40083] = 1000
    cache = _make_cache_with_values(overrides)
    snap2 = collector2.collect(cache)
    assert snap2["inverter"]["peak_power_w"] == 1000


# --- Venus OS lock section (Phase 11) ---


def test_snapshot_venus_os_section():
    """Snapshot includes venus_os dict with is_locked, lock_remaining_s, last_source, last_change_ts."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    cs = ControlState()
    snapshot = collector.collect(cache, control_state=cs)

    assert "venus_os" in snapshot
    vo = snapshot["venus_os"]
    assert "is_locked" in vo
    assert "lock_remaining_s" in vo
    assert "last_source" in vo
    assert "last_change_ts" in vo
    assert vo["is_locked"] is False
    assert vo["lock_remaining_s"] is None


# --- Venus MQTT connected (Phase 13) ---


def test_snapshot_includes_venus_mqtt_connected():
    """Snapshot includes venus_mqtt_connected=True when app_ctx has the attr."""
    from types import SimpleNamespace
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    ctx = SimpleNamespace(venus_mqtt_connected=True, venus_os_detected=False, venus_os_client_ip="", last_poll_data=None)
    snapshot = collector.collect(cache, app_ctx=ctx)

    assert snapshot["venus_mqtt_connected"] is True


def test_snapshot_venus_mqtt_default_false():
    """venus_mqtt_connected defaults to False when app_ctx has it False."""
    from types import SimpleNamespace
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    ctx = SimpleNamespace(venus_mqtt_connected=False, venus_os_detected=False, venus_os_client_ip="", last_poll_data=None)
    snapshot = collector.collect(cache, app_ctx=ctx)

    assert snapshot["venus_mqtt_connected"] is False


def test_snapshot_venus_mqtt_no_shared_ctx():
    """venus_mqtt_connected is False when app_ctx is None."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    snapshot = collector.collect(cache, app_ctx=None)

    assert snapshot["venus_mqtt_connected"] is False


def test_snapshot_venus_os_locked():
    """When locked, venus_os section shows is_locked=True and lock_remaining_s > 0."""
    collector = DashboardCollector()
    overrides = _zero_sf_overrides()
    overrides[40093] = [0, 0]
    overrides[40095] = 0
    overrides[40083] = 1000
    overrides[40084] = 0

    cache = _make_cache_with_values(overrides)
    cs = ControlState()
    cs.lock(900.0)
    snapshot = collector.collect(cache, control_state=cs)

    vo = snapshot["venus_os"]
    assert vo["is_locked"] is True
    assert vo["lock_remaining_s"] is not None
    assert vo["lock_remaining_s"] > 0
