"""DashboardCollector: decode raw Modbus registers into physical units.

Called once per successful poll cycle in _poll_loop. Produces a structured
snapshot dict consumed by the /api/dashboard REST endpoint and (later)
WebSocket broadcast.
"""
from __future__ import annotations

import time

from venus_os_fronius_proxy.register_cache import RegisterCache
from venus_os_fronius_proxy.timeseries import TimeSeriesBuffer

# pymodbus internal +1 offset for datablock access
_PB_OFFSET = 1

# SunSpec operating status codes (Model 103)
INVERTER_STATUS = {
    1: "OFF",
    2: "SLEEPING",
    3: "STARTING",
    4: "MPPT",
    5: "THROTTLED",
    6: "SHUTTING_DOWN",
    7: "FAULT",
    8: "STANDBY",
}

# Complete address map for all decoded Model 103 fields.
# Format: field_name -> (address, size, sf_address_or_None)
DECODE_MAP = {
    "ac_current": (40071, 1, 40075),
    "ac_current_l1": (40072, 1, 40075),
    "ac_current_l2": (40073, 1, 40075),
    "ac_current_l3": (40074, 1, 40075),
    "ac_voltage_ab": (40076, 1, 40082),
    "ac_voltage_bc": (40077, 1, 40082),
    "ac_voltage_ca": (40078, 1, 40082),
    "ac_voltage_an": (40079, 1, 40082),
    "ac_voltage_bn": (40080, 1, 40082),
    "ac_voltage_cn": (40081, 1, 40082),
    "ac_power": (40083, 1, 40084),
    "ac_frequency": (40085, 1, 40086),
    "ac_va": (40087, 1, 40088),
    "ac_var": (40089, 1, 40090),
    "ac_pf": (40091, 1, 40092),
    "ac_energy": (40093, 2, 40095),
    "dc_current": (40096, 1, 40097),
    "dc_voltage": (40098, 1, 40099),
    "dc_power": (40100, 1, 40101),
    "temperature_cab": (40102, 1, 40106),
    "temperature_sink": (40103, 1, 40106),
    "status": (40107, 1, None),
    "status_vendor": (40108, 1, None),
}

# Snapshot field name suffixes (units) for fields with scale factors
_UNIT_SUFFIXES = {
    "ac_current": "_a",
    "ac_current_l1": "_a",
    "ac_current_l2": "_a",
    "ac_current_l3": "_a",
    "ac_voltage_ab": "_v",
    "ac_voltage_bc": "_v",
    "ac_voltage_ca": "_v",
    "ac_voltage_an": "_v",
    "ac_voltage_bn": "_v",
    "ac_voltage_cn": "_v",
    "ac_power": "_w",
    "ac_frequency": "_hz",
    "ac_va": "",
    "ac_var": "",
    "ac_pf": "",
    "dc_current": "_a",
    "dc_voltage": "_v",
    "dc_power": "_w",
    "temperature_cab": "_c",
    "temperature_sink": "_c",
}


def _revert_remaining(control_state: object) -> float | None:
    """Return seconds until auto-revert, or None if no revert pending."""
    deadline = getattr(control_state, "webapp_revert_at", None)
    if deadline is not None:
        return max(0.0, deadline - time.monotonic())
    return None


class DashboardCollector:
    """Decodes raw registers, updates time series buffers, produces snapshots."""

    def __init__(self) -> None:
        self._buffers: dict[str, TimeSeriesBuffer] = {
            "ac_power_w": TimeSeriesBuffer(),
            "dc_power_w": TimeSeriesBuffer(),
            "ac_voltage_an_v": TimeSeriesBuffer(),
            "temperature_sink_c": TimeSeriesBuffer(),
            "ac_frequency_hz": TimeSeriesBuffer(),
            "energy_total_wh": TimeSeriesBuffer(),
        }
        self._last_snapshot: dict | None = None
        self._energy_at_start: int | None = None

    @property
    def last_snapshot(self) -> dict | None:
        """Return the most recent collect() result."""
        return self._last_snapshot

    def collect(
        self,
        cache: RegisterCache,
        control_state: object | None = None,
        conn_mgr: object | None = None,
        poll_counter: dict | None = None,
        override_log: object | None = None,
    ) -> dict:
        """Decode registers, update buffers, return snapshot."""
        db = cache.datablock
        decoded = self._decode_all(db)

        # Build inverter section
        inverter: dict = {}
        for field_name, (addr, size, sf_addr) in DECODE_MAP.items():
            if field_name == "ac_energy":
                # Special: uint32 energy with scale factor
                raw_energy = self._read_uint32(db, addr)
                sf = self._read_int16(db, sf_addr) if sf_addr is not None else 0
                energy_wh = raw_energy * (10 ** sf)
                inverter["energy_total_wh"] = energy_wh
            elif field_name == "status":
                raw_status = db.getValues(addr + _PB_OFFSET, 1)[0]
                inverter["status"] = INVERTER_STATUS.get(raw_status, f"UNKNOWN({raw_status})")
                inverter["status_code"] = raw_status
            elif field_name == "status_vendor":
                inverter["status_vendor"] = db.getValues(addr + _PB_OFFSET, 1)[0]
            else:
                suffix = _UNIT_SUFFIXES.get(field_name, "")
                key = field_name + suffix
                inverter[key] = decoded[field_name]

        # Track daily energy
        energy_wh = inverter.get("energy_total_wh", 0)
        if self._energy_at_start is None and energy_wh > 0:
            self._energy_at_start = energy_wh

        # Build control section
        control: dict = {}
        if control_state is not None:
            control = {
                "enabled": control_state.is_enabled,
                "limit_pct": control_state.wmaxlimpct_float,
                "wmaxlimpct_raw": control_state.wmaxlimpct_raw,
                "last_source": getattr(control_state, "last_source", "none"),
                "last_change_ts": getattr(control_state, "last_change_ts", 0.0),
                "revert_remaining_s": _revert_remaining(control_state),
            }

        # Build connection section
        connection: dict = {
            "state": conn_mgr.state.value if conn_mgr is not None else "unknown",
            "poll_success": poll_counter["success"] if poll_counter else 0,
            "poll_total": poll_counter["total"] if poll_counter else 0,
            "cache_stale": cache.is_stale,
        }

        snapshot = {
            "ts": time.time(),
            "inverter": inverter,
            "control": control,
            "connection": connection,
            "override_log": override_log.get_all() if override_log else [],
        }

        # Feed time series buffers
        buf_map = {
            "ac_power_w": inverter.get("ac_power_w"),
            "dc_power_w": inverter.get("dc_power_w"),
            "ac_voltage_an_v": inverter.get("ac_voltage_an_v"),
            "temperature_sink_c": inverter.get("temperature_sink_c"),
            "ac_frequency_hz": inverter.get("ac_frequency_hz"),
            "energy_total_wh": inverter.get("energy_total_wh"),
        }
        for buf_key, value in buf_map.items():
            if value is not None and buf_key in self._buffers:
                self._buffers[buf_key].append(float(value))

        self._last_snapshot = snapshot
        return snapshot

    @staticmethod
    def _read_int16(db: object, addr: int) -> int:
        """Read a register as signed int16 (for scale factors).

        Raw uint16 > 32767 means negative in SunSpec signed int16 encoding.
        """
        raw = db.getValues(addr + _PB_OFFSET, 1)[0]
        return raw - 65536 if raw > 32767 else raw

    @staticmethod
    def _read_uint32(db: object, addr: int) -> int:
        """Read 2 consecutive registers as uint32 (hi << 16 | lo)."""
        regs = db.getValues(addr + _PB_OFFSET, 2)
        return (regs[0] << 16) | regs[1]

    def _decode_all(self, db: object) -> dict:
        """Read all DECODE_MAP fields, apply scale factors."""
        # Cache scale factors (read once)
        sf_cache: dict[int, int] = {}
        result: dict[str, float] = {}

        for field_name, (addr, size, sf_addr) in DECODE_MAP.items():
            # Skip special fields handled in collect()
            if field_name in ("ac_energy", "status", "status_vendor"):
                continue

            raw = db.getValues(addr + _PB_OFFSET, 1)[0]

            if sf_addr is not None:
                if sf_addr not in sf_cache:
                    sf_cache[sf_addr] = self._read_int16(db, sf_addr)
                sf = sf_cache[sf_addr]
                result[field_name] = raw * (10 ** sf)
            else:
                result[field_name] = float(raw)

        return result
