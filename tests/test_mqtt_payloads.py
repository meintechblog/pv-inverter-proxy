"""Tests for mqtt_payloads — payload extraction and HA discovery config builders."""
from __future__ import annotations

import time

import pytest

from venus_os_fronius_proxy.mqtt_payloads import (
    device_payload,
    ha_discovery_configs,
    ha_discovery_topic,
    virtual_ha_discovery_configs,
    virtual_payload,
)


def _make_snapshot(**overrides):
    """Build a realistic DashboardCollector snapshot dict."""
    inverter = {
        "ac_power_w": 12500.0,
        "dc_power_w": 12800.0,
        "ac_voltage_an_v": 230.1,
        "ac_voltage_bn_v": 231.2,
        "ac_voltage_cn_v": 229.8,
        "ac_current_a": 18.1,
        "ac_current_l1_a": 6.0,
        "ac_current_l2_a": 6.1,
        "ac_current_l3_a": 6.0,
        "ac_frequency_hz": 50.01,
        "dc_voltage_v": 640.5,
        "dc_current_a": 20.0,
        "energy_total_wh": 45000000,
        "daily_energy_wh": 32000,
        "temperature_sink_c": 42.3,
        "status": "MPPT",
        "status_code": 4,
        "peak_power_w": 14200.0,
        "operating_hours": 18500.5,
        "efficiency_pct": 97.6,
    }
    inverter.update(overrides.pop("inverter_overrides", {}))
    base = {
        "ts": time.time(),
        "inverter": inverter,
        "inverter_name": "SolarEdge SE30K",
        "inverter_serial": "RW00IBNM4",
        "rated_power_w": 30000,
        "connection": {"state": "connected"},
    }
    base.update(overrides)
    return base


class _FakeInverterEntry:
    """Minimal stand-in for config.InverterEntry."""
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "abc123def456")
        self.name = kwargs.get("name", "Spielturm SE30K")
        self.manufacturer = kwargs.get("manufacturer", "SolarEdge")
        self.model = kwargs.get("model", "SE30K")
        self.serial = kwargs.get("serial", "RW00IBNM4")
        self.firmware_version = kwargs.get("firmware_version", "4.18.37")
        self.type = kwargs.get("type", "solaredge")


# ── device_payload tests ──────────────────────────────────────────────


class TestDevicePayload:
    def test_extracts_all_fields(self):
        snap = _make_snapshot()
        result = device_payload(snap)
        expected_keys = {
            "ts", "ac_power_w", "dc_power_w",
            "ac_voltage_an_v", "ac_voltage_bn_v", "ac_voltage_cn_v",
            "ac_current_a", "ac_current_l1_a", "ac_current_l2_a", "ac_current_l3_a",
            "ac_frequency_hz", "dc_voltage_v", "dc_current_a",
            "energy_total_wh", "daily_energy_wh",
            "temperature_c",  # renamed from temperature_sink_c
            "status", "status_code",
            "peak_power_w", "operating_hours", "efficiency_pct",
        }
        assert set(result.keys()) == expected_keys
        assert len(result) == 21

    def test_maps_temperature(self):
        snap = _make_snapshot()
        result = device_payload(snap)
        assert result["temperature_c"] == 42.3
        assert "temperature_sink_c" not in result

    def test_handles_missing_keys(self):
        snap = {"ts": 100.0, "inverter": {}}
        result = device_payload(snap)
        assert result["ts"] == 100.0
        assert result["ac_power_w"] is None
        assert result["temperature_c"] is None
        assert result["status"] is None

    def test_preserves_types(self):
        snap = _make_snapshot()
        result = device_payload(snap)
        assert isinstance(result["ac_power_w"], float)
        assert isinstance(result["energy_total_wh"], int)
        assert isinstance(result["status"], str)


# ── virtual_payload tests ─────────────────────────────────────────────


class TestVirtualPayload:
    def test_structure(self):
        vdata = {
            "total_power_w": 15000.0,
            "virtual_name": "My Virtual PV",
            "contributions": [
                {
                    "device_id": "abc123",
                    "name": "Spielturm",
                    "power_w": 12500.0,
                    "throttle_order": 1,
                    "throttle_enabled": True,
                    "current_limit_pct": 100.0,
                },
                {
                    "device_id": "def456",
                    "name": "Garage",
                    "power_w": 2500.0,
                    "throttle_order": 2,
                    "throttle_enabled": False,
                    "current_limit_pct": 50.0,
                },
            ],
        }
        result = virtual_payload(vdata)
        assert "ts" in result
        assert result["total_power_w"] == 15000.0
        assert len(result["contributions"]) == 2
        # Only device_id, name, power_w are kept
        for c in result["contributions"]:
            assert set(c.keys()) == {"device_id", "name", "power_w"}


# ── ha_discovery_configs tests ────────────────────────────────────────


class TestHaDiscoveryConfigs:
    def _get_configs(self):
        entry = _FakeInverterEntry()
        snap = _make_snapshot()
        return ha_discovery_configs("abc123def456", "pvproxy", entry, snap)

    def test_count(self):
        configs = self._get_configs()
        assert len(configs) == 16

    def test_power_sensor(self):
        configs = self._get_configs()
        ac_power = [c for c in configs if c["name"] == "AC Power"]
        assert len(ac_power) == 1
        cfg = ac_power[0]
        assert cfg["device_class"] == "power"
        assert cfg["state_class"] == "measurement"
        assert cfg["unit_of_measurement"] == "W"

    def test_energy_sensor(self):
        configs = self._get_configs()
        total_energy = [c for c in configs if c["name"] == "Total Energy"]
        assert len(total_energy) == 1
        cfg = total_energy[0]
        assert cfg["device_class"] == "energy"
        assert cfg["state_class"] == "total_increasing"
        assert cfg["unit_of_measurement"] == "Wh"

    def test_daily_energy_sensor(self):
        configs = self._get_configs()
        daily = [c for c in configs if c["name"] == "Daily Energy"]
        assert len(daily) == 1
        cfg = daily[0]
        assert cfg["device_class"] == "energy"
        assert cfg["state_class"] == "total"
        assert cfg["unit_of_measurement"] == "Wh"

    def test_status_sensor(self):
        configs = self._get_configs()
        status = [c for c in configs if c["name"] == "Status"]
        assert len(status) == 1
        cfg = status[0]
        # Status is an enum — no device_class, no state_class, no unit
        assert "device_class" not in cfg or cfg.get("device_class") is None
        assert "state_class" not in cfg or cfg.get("state_class") is None
        assert "unit_of_measurement" not in cfg or cfg.get("unit_of_measurement") is None

    def test_device_grouping(self):
        configs = self._get_configs()
        ids_set = {tuple(c["device"]["identifiers"]) for c in configs}
        assert len(ids_set) == 1
        assert ("pv_proxy_abc123def456",) in ids_set

    def test_unique_ids_unique(self):
        configs = self._get_configs()
        unique_ids = [c["unique_id"] for c in configs]
        assert len(unique_ids) == len(set(unique_ids))
        for uid in unique_ids:
            assert "abc123def456" in uid

    def test_availability(self):
        configs = self._get_configs()
        for cfg in configs:
            assert "availability" in cfg
            assert len(cfg["availability"]) == 2
            topics = [a["topic"] for a in cfg["availability"]]
            assert "pvproxy/status" in topics
            assert "pvproxy/device/abc123def456/availability" in topics
            assert cfg["availability_mode"] == "all"

    def test_value_templates(self):
        configs = self._get_configs()
        ac_power = [c for c in configs if c["name"] == "AC Power"][0]
        assert ac_power["value_template"] == "{{ value_json.ac_power_w }}"
        temp = [c for c in configs if c["name"] == "Temperature"][0]
        assert temp["value_template"] == "{{ value_json.temperature_c }}"

    def test_device_block_metadata(self):
        configs = self._get_configs()
        dev = configs[0]["device"]
        assert dev["name"] == "Spielturm SE30K"
        assert dev["manufacturer"] == "SolarEdge"
        assert dev["model"] == "SE30K"
        assert dev["serial_number"] == "RW00IBNM4"
        assert dev["sw_version"] == "4.18.37"
        assert dev["via_device"] == "pv_proxy"


# ── ha_discovery_topic tests ──────────────────────────────────────────


class TestHaDiscoveryTopic:
    def test_format(self):
        topic = ha_discovery_topic("abc123def456", "ac_power")
        assert topic == "homeassistant/sensor/pv_proxy_abc123def456/ac_power/config"


# ── virtual_ha_discovery_configs tests ────────────────────────────────


class TestVirtualHaDiscoveryConfigs:
    def test_returns_configs(self):
        configs = virtual_ha_discovery_configs("pvproxy", "My Virtual PV")
        assert len(configs) >= 2  # at least power + energy
        names = [c["name"] for c in configs]
        assert "Total Power" in names or "AC Power" in names

    def test_virtual_device_block(self):
        configs = virtual_ha_discovery_configs("pvproxy", "My Virtual PV")
        dev = configs[0]["device"]
        assert "pv_proxy_virtual" in dev["identifiers"]
        assert dev["name"] == "My Virtual PV"

    def test_virtual_state_topic(self):
        configs = virtual_ha_discovery_configs("pvproxy", "My Virtual PV")
        for cfg in configs:
            assert cfg["state_topic"] == "pvproxy/virtual/state"
