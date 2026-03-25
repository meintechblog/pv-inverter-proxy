"""Tests for AggregationLayer: SunSpec register aggregation from N devices."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock

from pv_inverter_proxy.aggregation import (
    AggregationLayer,
    decode_model_103_to_physical,
    encode_aggregated_model_103,
)
from pv_inverter_proxy.config import Config, InverterEntry, VirtualInverterConfig
from pv_inverter_proxy.context import AppContext, DeviceState
from pv_inverter_proxy.register_cache import RegisterCache
from pv_inverter_proxy.sunspec_models import (
    DATABLOCK_START,
    _int16_as_uint16,
    build_initial_registers,
    encode_string,
)


def _make_inverter_regs(
    ac_power_w: float = 5000,
    ac_current_a: float = 10.0,
    ac_current_l1_a: float = 3.33,
    ac_current_l2_a: float = 3.33,
    ac_current_l3_a: float = 3.34,
    ac_voltage_an_v: float = 230.0,
    ac_frequency_hz: float = 50.0,
    energy_total_wh: float = 100000,
    dc_current_a: float = 12.0,
    dc_voltage_v: float = 420.0,
    dc_power_w: float = 5040,
    temperature_c: float = 45.0,
    status_code: int = 4,
) -> list[int]:
    """Build a 52-register Model 103 block with known physical values.

    Uses SF=0 for power, SF=-2 for current, SF=-1 for voltage, SF=-2 for freq,
    SF=0 for energy, SF=-1 for temperature -- same as our encoding.
    """
    regs = [0] * 52
    regs[0] = 103  # DID
    regs[1] = 50   # Length

    # AC Current (SF=-2 at index 6)
    regs[2] = int(round(ac_current_a * 100)) & 0xFFFF
    regs[3] = int(round(ac_current_l1_a * 100)) & 0xFFFF
    regs[4] = int(round(ac_current_l2_a * 100)) & 0xFFFF
    regs[5] = int(round(ac_current_l3_a * 100)) & 0xFFFF
    regs[6] = _int16_as_uint16(-2)

    # AC Voltage (SF=-1 at index 13)
    regs[10] = int(round(ac_voltage_an_v * 10)) & 0xFFFF
    regs[13] = _int16_as_uint16(-1)

    # AC Power (SF=0 at index 15)
    regs[14] = int(round(ac_power_w)) & 0xFFFF
    regs[15] = 0

    # AC Frequency (SF=-2 at index 17)
    regs[16] = int(round(ac_frequency_hz * 100)) & 0xFFFF
    regs[17] = _int16_as_uint16(-2)

    # Energy (SF=0 at index 26)
    energy = int(round(energy_total_wh))
    regs[24] = (energy >> 16) & 0xFFFF
    regs[25] = energy & 0xFFFF
    regs[26] = 0

    # DC Current (SF=-2 at index 28)
    regs[27] = int(round(dc_current_a * 100)) & 0xFFFF
    regs[28] = _int16_as_uint16(-2)

    # DC Voltage (SF=-1 at index 30)
    regs[29] = int(round(dc_voltage_v * 10)) & 0xFFFF
    regs[30] = _int16_as_uint16(-1)

    # DC Power (SF=0 at index 32)
    regs[31] = int(round(dc_power_w)) & 0xFFFF
    regs[32] = 0

    # Temperature (SF=-1 at index 37)
    regs[33] = int(round(temperature_c * 10)) & 0xFFFF
    regs[37] = _int16_as_uint16(-1)

    # Status
    regs[38] = status_code

    return regs


def _make_app_ctx_with_devices(**device_kwargs) -> tuple[AppContext, RegisterCache]:
    """Create AppContext with devices and a real RegisterCache."""
    initial = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial)
    cache = RegisterCache(datablock, staleness_timeout=30.0)

    app_ctx = AppContext()
    for dev_id, regs in device_kwargs.items():
        ds = DeviceState()
        if regs is not None:
            ds.last_poll_data = {"inverter_registers": regs, "common_registers": [0] * 67}
        app_ctx.devices[dev_id] = ds

    return app_ctx, cache


def _make_config(inverters=None, virtual_name=""):
    """Create a Config with optional inverters and virtual name."""
    if inverters is None:
        inverters = [InverterEntry(id="dev1", enabled=True), InverterEntry(id="dev2", enabled=True)]
    vi = VirtualInverterConfig(name=virtual_name) if virtual_name else VirtualInverterConfig()
    return Config(inverters=inverters, virtual_inverter=vi)


# --- Tests ---


def test_sum_power_current():
    """2 devices with known power/current -> aggregated = sum."""
    regs1 = _make_inverter_regs(ac_power_w=3000, ac_current_a=6.0,
                                 ac_current_l1_a=2.0, ac_current_l2_a=2.0, ac_current_l3_a=2.0)
    regs2 = _make_inverter_regs(ac_power_w=5000, ac_current_a=10.0,
                                 ac_current_l1_a=3.33, ac_current_l2_a=3.33, ac_current_l3_a=3.34)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    # Decode the aggregated registers from the cache
    # Inverter regs start at datablock address 40070
    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["ac_power_w"] - 8000) < 10
    assert abs(result["ac_current_a"] - 16.0) < 0.2


def test_sum_energy():
    """2 devices with different energy_total_wh -> sum."""
    regs1 = _make_inverter_regs(energy_total_wh=50000)
    regs2 = _make_inverter_regs(energy_total_wh=75000)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["energy_total_wh"] - 125000) < 10


def test_voltage_frequency_averaged():
    """2 devices with different voltages -> simple average."""
    regs1 = _make_inverter_regs(ac_voltage_an_v=228.0, ac_frequency_hz=49.98)
    regs2 = _make_inverter_regs(ac_voltage_an_v=232.0, ac_frequency_hz=50.02)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["ac_voltage_an_v"] - 230.0) < 0.2
    assert abs(result["ac_frequency_hz"] - 50.0) < 0.02


def test_consistent_scale_factors():
    """Aggregated registers have consistent fixed SFs."""
    regs1 = _make_inverter_regs()
    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1)
    config = _make_config(inverters=[InverterEntry(id="dev1", enabled=True)])
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)

    def _sf(idx):
        raw = agg_regs[idx]
        return raw - 65536 if raw > 32767 else raw

    assert _sf(6) == -2   # current SF
    assert _sf(13) == -1  # voltage SF
    assert agg_regs[15] == 0    # power SF=0
    assert _sf(17) == -2  # frequency SF
    assert agg_regs[26] == 0    # energy SF=0
    assert _sf(28) == -2  # DC current SF
    assert _sf(30) == -1  # DC voltage SF
    assert agg_regs[32] == 0    # DC power SF=0
    assert _sf(37) == -1  # temperature SF


def test_roundtrip_accuracy():
    """Encode known values -> decode back -> within 1% tolerance."""
    known = {
        "ac_current_a": 25.5,
        "ac_current_l1_a": 8.5,
        "ac_current_l2_a": 8.5,
        "ac_current_l3_a": 8.5,
        "ac_voltage_an_v": 231.0,
        "ac_power_w": 5880,
        "ac_frequency_hz": 50.01,
        "energy_total_wh": 150000,
        "dc_current_a": 14.0,
        "dc_voltage_v": 420.0,
        "dc_power_w": 5880,
        "temperature_c": 42.5,
        "status_code": 4,
    }

    encoded = encode_aggregated_model_103(known)
    decoded = decode_model_103_to_physical(encoded)

    for key in known:
        if key == "status_code":
            assert decoded[key] == known[key]
        else:
            expected = known[key]
            actual = decoded[key]
            if expected == 0:
                assert abs(actual) < 1
            else:
                assert abs(actual - expected) / abs(expected) < 0.01, \
                    f"{key}: expected {expected}, got {actual}"


def test_partial_failure():
    """2 devices, 1 with last_poll_data=None -> uses only reachable device."""
    regs1 = _make_inverter_regs(ac_power_w=7000)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=None)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["ac_power_w"] - 7000) < 10
    assert not cache.is_stale


def test_all_offline_stale():
    """All devices have last_poll_data=None -> cache stays stale."""
    app_ctx, cache = _make_app_ctx_with_devices(dev1=None, dev2=None)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    assert cache.is_stale  # no update should have happened


def test_virtual_name():
    """Common Model registers contain custom virtual name."""
    regs1 = _make_inverter_regs()
    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1)
    config = _make_config(
        inverters=[InverterEntry(id="dev1", enabled=True)],
        virtual_name="Meine PV-Anlage",
    )
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    # Common Model starts at datablock address 40003, C_Model at offset 18 (16 regs)
    # Common = DID(1) + Len(1) + Manufacturer(16) + Model(16) + ...
    # So C_Model is at 40003 + 18 = 40021
    common_regs = cache.datablock.getValues(40003, 67)

    # C_Manufacturer at offset 2-17
    mfr_bytes = b""
    for r in common_regs[2:18]:
        mfr_bytes += r.to_bytes(2, "big")
    manufacturer = mfr_bytes.rstrip(b"\x00").decode("ascii")
    assert manufacturer == "Fronius"

    # C_Model at offset 18-33
    model_bytes = b""
    for r in common_regs[18:34]:
        model_bytes += r.to_bytes(2, "big")
    model_name = model_bytes.rstrip(b"\x00").decode("ascii")
    assert model_name == "Meine PV-Anlage"


def test_virtual_name_default():
    """When name is empty, Model defaults to 'Fronius PV-Inverter-Proxy'."""
    regs1 = _make_inverter_regs()
    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1)
    config = _make_config(inverters=[InverterEntry(id="dev1", enabled=True)])
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    common_regs = cache.datablock.getValues(40003, 67)
    model_bytes = b""
    for r in common_regs[18:34]:
        model_bytes += r.to_bytes(2, "big")
    model_name = model_bytes.rstrip(b"\x00").decode("ascii")
    assert model_name == "Fronius PV-Inverter-Proxy"


def test_wrtg_sum():
    """WRtg Model 120 = sum of rated_powers from active InverterEntries."""
    regs1 = _make_inverter_regs()
    regs2 = _make_inverter_regs()
    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config(inverters=[
        InverterEntry(id="dev1", enabled=True, rated_power=30000),
        InverterEntry(id="dev2", enabled=True, rated_power=800),
    ])
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    # WRtg is at Model 120 offset 3 (40121+3=40124), datablock address 40125
    wrtg = cache.datablock.getValues(40125, 1)[0]
    assert wrtg == 30800


def test_temperature_max():
    """Aggregated temperature = max across devices."""
    regs1 = _make_inverter_regs(temperature_c=35.0)
    regs2 = _make_inverter_regs(temperature_c=52.0)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["temperature_c"] - 52.0) < 0.2


def test_status_worst_case():
    """If any device has status != MPPT(4), use worst (highest) status code."""
    regs1 = _make_inverter_regs(status_code=4)  # MPPT
    regs2 = _make_inverter_regs(status_code=5)  # THROTTLED

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert result["status_code"] == 5


def test_dc_voltage_skips_zero_dc_devices():
    """Mixed fleet: SolarEdge (real DC) + Shelly (zero DC) -> dc_voltage_v uses only real DC devices."""
    # SolarEdge: real DC power and voltage
    regs_solaredge = _make_inverter_regs(dc_power_w=5040, dc_voltage_v=420.0)
    # Shelly: zero DC (relay device, no DC power)
    regs_shelly = _make_inverter_regs(dc_power_w=0, dc_voltage_v=0.0)

    app_ctx, cache = _make_app_ctx_with_devices(solaredge=regs_solaredge, shelly=regs_shelly)
    config = _make_config(inverters=[
        InverterEntry(id="solaredge", enabled=True),
        InverterEntry(id="shelly", enabled=True),
    ])
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("solaredge"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    # Should be 420.0 (only SolarEdge), NOT 210.0 (average of 420 and 0)
    assert abs(result["dc_voltage_v"] - 420.0) < 0.2


def test_dc_voltage_all_zero_dc():
    """All devices have dc_power_w=0 -> dc_voltage_v == 0.0 (no division by zero)."""
    regs1 = _make_inverter_regs(dc_power_w=0, dc_voltage_v=0.0)
    regs2 = _make_inverter_regs(dc_power_w=0, dc_voltage_v=0.0)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert result["dc_voltage_v"] == 0.0


def test_dc_voltage_two_real_dc_devices():
    """Two real DC devices (420V and 380V) -> dc_voltage_v == 400.0 (normal average)."""
    regs1 = _make_inverter_regs(dc_power_w=5040, dc_voltage_v=420.0)
    regs2 = _make_inverter_regs(dc_power_w=3800, dc_voltage_v=380.0)

    app_ctx, cache = _make_app_ctx_with_devices(dev1=regs1, dev2=regs2)
    config = _make_config()
    agg = AggregationLayer(app_ctx, cache, config)

    asyncio.get_event_loop().run_until_complete(agg.recalculate("dev1"))

    agg_regs = cache.datablock.getValues(40070, 52)
    result = decode_model_103_to_physical(agg_regs)

    assert abs(result["dc_voltage_v"] - 400.0) < 0.2
