"""Tests for DashboardCollector register decoding."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock

from venus_os_fronius_proxy.register_cache import RegisterCache
from venus_os_fronius_proxy.sunspec_models import build_initial_registers, DATABLOCK_START
from venus_os_fronius_proxy.connection import ConnectionManager, ConnectionState
from venus_os_fronius_proxy.control import ControlState
from venus_os_fronius_proxy.dashboard import DashboardCollector, _PB_OFFSET, DECODE_MAP


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
    cs.update_wmaxlimpct(7500)
    cs.update_wmaxlim_ena(1)

    snapshot = collector.collect(cache, control_state=cs)
    assert snapshot["control"]["enabled"] is True
    assert snapshot["control"]["limit_pct"] == 75.0
    assert snapshot["control"]["wmaxlimpct_raw"] == 7500


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
