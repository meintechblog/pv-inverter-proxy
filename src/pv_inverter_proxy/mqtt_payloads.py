"""Pure-function module for MQTT telemetry payloads and HA auto-discovery configs.

Converts DashboardCollector snapshots into flat JSON payloads for MQTT publishing
and generates Home Assistant MQTT Auto-Discovery configuration payloads.

No side effects, no MQTT dependency — pure data transformation.
"""
from __future__ import annotations

import time
from typing import Any

# ── Sensor definitions ────────────────────────────────────────────────
#
# Each tuple: (display_name, payload_field_key, device_class, state_class,
#              unit_of_measurement, suggested_display_precision)
#
# device_class=None means HA treats it as a generic sensor (enum/string).
# state_class=None means HA won't track long-term statistics for it.

SENSOR_DEFS: list[tuple[str, str, str | None, str | None, str | None, int | None]] = [
    ("AC Power",        "ac_power_w",       "power",       "measurement",      "W",   0),
    ("DC Power",        "dc_power_w",       "power",       "measurement",      "W",   0),
    ("AC Voltage L1",   "ac_voltage_an_v",  "voltage",     "measurement",      "V",   1),
    ("AC Voltage L2",   "ac_voltage_bn_v",  "voltage",     "measurement",      "V",   1),
    ("AC Voltage L3",   "ac_voltage_cn_v",  "voltage",     "measurement",      "V",   1),
    ("AC Current",      "ac_current_a",     "current",     "measurement",      "A",   1),
    ("AC Frequency",    "ac_frequency_hz",  "frequency",   "measurement",      "Hz",  2),
    ("DC Voltage",      "dc_voltage_v",     "voltage",     "measurement",      "V",   1),
    ("DC Current",      "dc_current_a",     "current",     "measurement",      "A",   1),
    ("Temperature",     "temperature_c",    "temperature", "measurement",      "\u00b0C", 1),
    ("Total Energy",    "energy_total_wh",  "energy",      "total_increasing", "Wh",  0),
    ("Daily Energy",    "daily_energy_wh",  "energy",      "total",            "Wh",  0),
    ("Peak Power",      "peak_power_w",     "power",       "measurement",      "W",   0),
    ("Operating Hours", "operating_hours",  "duration",    "total_increasing", "h",   2),
    ("Efficiency",      "efficiency_pct",   None,          "measurement",      "%",   1),
    ("Status",          "status",           None,          None,               None,  None),
]

# Fields extracted from snapshot["inverter"] into the flat payload.
# Maps payload key -> snapshot inverter key (most are identity; temperature is renamed).
_PAYLOAD_FIELDS: dict[str, str] = {
    "ac_power_w": "ac_power_w",
    "dc_power_w": "dc_power_w",
    "ac_voltage_an_v": "ac_voltage_an_v",
    "ac_voltage_bn_v": "ac_voltage_bn_v",
    "ac_voltage_cn_v": "ac_voltage_cn_v",
    "ac_current_a": "ac_current_a",
    "ac_current_l1_a": "ac_current_l1_a",
    "ac_current_l2_a": "ac_current_l2_a",
    "ac_current_l3_a": "ac_current_l3_a",
    "ac_frequency_hz": "ac_frequency_hz",
    "dc_voltage_v": "dc_voltage_v",
    "dc_current_a": "dc_current_a",
    "energy_total_wh": "energy_total_wh",
    "daily_energy_wh": "daily_energy_wh",
    "temperature_c": "temperature_sink_c",  # rename
    "status": "status",
    "status_code": "status_code",
    "peak_power_w": "peak_power_w",
    "operating_hours": "operating_hours",
    "efficiency_pct": "efficiency_pct",
}


def _slugify(name: str) -> str:
    """Convert sensor display name to a snake_case object_id."""
    return name.lower().replace(" ", "_")


# ── Payload extraction ────────────────────────────────────────────────


def device_payload(snapshot: dict[str, Any], device_name: str = "") -> dict[str, Any]:
    """Extract flat telemetry dict from a DashboardCollector snapshot.

    Returns a dict with keys: name, ts, and 20 inverter fields.
    Missing inverter keys produce None values for graceful degradation.
    """
    inverter = snapshot.get("inverter", {})
    result: dict[str, Any] = {"name": device_name, "ts": snapshot.get("ts")}
    for payload_key, inverter_key in _PAYLOAD_FIELDS.items():
        result[payload_key] = inverter.get(inverter_key)
    return result


def virtual_payload(virtual_data: dict[str, Any]) -> dict[str, Any]:
    """Extract MQTT payload from virtual PV snapshot data.

    Keeps only device_id, name, power_w from each contribution
    (strips throttle_order, throttle_enabled, current_limit_pct).
    """
    contributions = []
    for c in virtual_data.get("contributions", []):
        contributions.append({
            "device_id": c.get("device_id"),
            "name": c.get("name"),
            "power_w": c.get("power_w"),
        })
    return {
        "ts": time.time(),
        "total_power_w": virtual_data.get("total_power_w"),
        "contributions": contributions,
    }


# ── HA Auto-Discovery ────────────────────────────────────────────────


def ha_discovery_topic(device_id: str, sensor_field: str) -> str:
    """Return the HA MQTT discovery topic path for a sensor.

    Format: homeassistant/sensor/{node_id}/{object_id}/config
    """
    node_id = f"pv_proxy_{device_id}"
    return f"homeassistant/sensor/{node_id}/{sensor_field}/config"


def ha_discovery_configs(
    device_id: str,
    topic_prefix: str,
    inverter_entry: Any,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate HA auto-discovery config dicts for all 16 sensor entities.

    Each config is a dict ready for JSON serialization and publishing to
    the corresponding ha_discovery_topic().

    Args:
        device_id: 12-char hex device identifier.
        topic_prefix: MQTT topic prefix (e.g. "pv-inverter-proxy").
        inverter_entry: InverterEntry dataclass (or duck-typed object with
            name, manufacturer, model, serial, firmware_version).
        snapshot: Optional current snapshot (unused currently, reserved for
            future dynamic config).

    Returns:
        List of 16 config dicts, one per SENSOR_DEFS entry.
    """
    node_id = f"pv_proxy_{device_id}"
    state_topic = f"{topic_prefix}/device/{device_id}/state"

    # Device block shared across all sensors (D-09)
    device_name = (
        inverter_entry.name
        or f"{inverter_entry.manufacturer} {inverter_entry.model}".strip()
        or "Unknown Inverter"
    )
    device_block: dict[str, Any] = {
        "identifiers": [node_id],
        "name": device_name,
        "manufacturer": inverter_entry.manufacturer or "Unknown",
        "model": inverter_entry.model or "Unknown",
        "serial_number": inverter_entry.serial,
        "sw_version": inverter_entry.firmware_version or "Unknown",
        "via_device": "pv_proxy",
    }

    # Availability references LWT (D-10)
    availability = [
        {"topic": f"{topic_prefix}/status"},
        {"topic": f"{topic_prefix}/device/{device_id}/availability"},
    ]

    configs: list[dict[str, Any]] = []
    for display_name, field_key, device_class, state_class, unit, precision in SENSOR_DEFS:
        object_id = _slugify(display_name)
        unique_id = f"pv_proxy_{device_id}_{object_id}"

        cfg: dict[str, Any] = {
            "name": display_name,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": "{{ value_json." + field_key + " }}",
            "availability": availability,
            "availability_mode": "all",
            "device": device_block,
        }

        if device_class is not None:
            cfg["device_class"] = device_class
        if state_class is not None:
            cfg["state_class"] = state_class
        if unit is not None:
            cfg["unit_of_measurement"] = unit
        if precision is not None:
            cfg["suggested_display_precision"] = precision

        configs.append(cfg)

    return configs


def virtual_ha_discovery_configs(
    topic_prefix: str,
    virtual_name: str,
) -> list[dict[str, Any]]:
    """Generate HA auto-discovery configs for the virtual PV device.

    Creates sensors for total power and daily energy at minimum.
    """
    node_id = "pv_proxy_virtual"
    state_topic = f"{topic_prefix}/virtual/state"

    device_block: dict[str, Any] = {
        "identifiers": [node_id],
        "name": virtual_name,
        "manufacturer": "PV-Inverter-Proxy",
        "model": "Virtual Aggregator",
        "via_device": "pv_proxy",
    }

    availability = [
        {"topic": f"{topic_prefix}/status"},
    ]

    # Virtual sensors: total power + total energy
    virtual_sensors: list[tuple[str, str, str, str, str, int]] = [
        ("Total Power", "total_power_w", "power", "measurement", "W", 0),
        ("Daily Energy", "daily_energy_wh", "energy", "total", "Wh", 0),
    ]

    configs: list[dict[str, Any]] = []
    for display_name, field_key, device_class, state_class, unit, precision in virtual_sensors:
        object_id = _slugify(display_name)
        unique_id = f"pv_proxy_virtual_{object_id}"
        configs.append({
            "name": display_name,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": "{{ value_json." + field_key + " }}",
            "device_class": device_class,
            "state_class": state_class,
            "unit_of_measurement": unit,
            "suggested_display_precision": precision,
            "availability": availability,
            "availability_mode": "all",
            "device": device_block,
        })

    return configs
