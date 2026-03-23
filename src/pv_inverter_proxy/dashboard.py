"""DashboardCollector: decode raw Modbus registers into physical units.

Called once per successful poll cycle in _poll_loop. Produces a structured
snapshot dict consumed by the /api/dashboard REST endpoint and (later)
WebSocket broadcast.
"""
from __future__ import annotations

import datetime
import json
import time

from pv_inverter_proxy.register_cache import RegisterCache
from pv_inverter_proxy.timeseries import TimeSeriesBuffer

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


_DAILY_ENERGY_FILE = "/etc/pv-inverter-proxy/daily_energy.json"


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
        self._energy_date: str | None = None  # YYYY-MM-DD for daily reset
        # Peak stats (in-memory, reset on restart)
        self._peak_power_w: float = 0.0
        self._operating_seconds: float = 0.0
        self._last_collect_ts: float | None = None
        # Load persistent daily energy baseline
        self._load_daily_energy()

    def _load_daily_energy(self) -> None:
        """Load daily stats from persistent file (energy baseline, peak, hours)."""
        try:
            with open(_DAILY_ENERGY_FILE) as f:
                data = json.load(f)
            today = datetime.date.today().isoformat()
            if data.get("date") == today:
                self._energy_at_start = data.get("baseline_wh")
                self._energy_date = today
                self._peak_power_w = data.get("peak_power_w", 0.0)
                self._operating_seconds = data.get("operating_seconds", 0.0)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_daily_stats(self, baseline_wh: int) -> None:
        """Persist daily stats to survive restarts."""
        today = datetime.date.today().isoformat()
        try:
            with open(_DAILY_ENERGY_FILE, "w") as f:
                json.dump({
                    "date": today,
                    "baseline_wh": baseline_wh,
                    "peak_power_w": self._peak_power_w,
                    "operating_seconds": self._operating_seconds,
                }, f)
            self._energy_date = today
        except OSError:
            pass

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
        app_ctx: object | None = None,
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

        # Track daily energy (persistent across restarts, resets at midnight)
        energy_wh = inverter.get("energy_total_wh", 0)
        today = datetime.date.today().isoformat()

        # Reset all daily stats at midnight
        if self._energy_date != today:
            self._energy_at_start = None
            self._energy_date = today
            self._peak_power_w = 0.0
            self._operating_seconds = 0.0

        if self._energy_at_start is None and energy_wh > 0:
            self._energy_at_start = energy_wh

        # Compute daily energy delta from baseline
        daily_wh = energy_wh - self._energy_at_start if self._energy_at_start is not None else 0
        inverter["daily_energy_wh"] = max(0, daily_wh)

        # Peak stats tracking
        ac_power = inverter.get("ac_power_w", 0) or 0
        if ac_power > self._peak_power_w:
            self._peak_power_w = ac_power

        # Operating hours (only count time in MPPT)
        now_mono = time.monotonic()
        if self._last_collect_ts is not None and inverter.get("status") == "MPPT":
            delta = now_mono - self._last_collect_ts
            if 0 < delta < 10:  # guard against large gaps
                self._operating_seconds += delta
        self._last_collect_ts = now_mono

        # Efficiency = AC power / DC power
        dc_power = inverter.get("dc_power_w", 0) or 0
        efficiency_pct = round(ac_power / dc_power * 100, 1) if dc_power > 0 else 0.0

        inverter["peak_power_w"] = self._peak_power_w
        inverter["operating_hours"] = round(self._operating_seconds / 3600, 4)
        inverter["efficiency_pct"] = efficiency_pct

        # Persist daily stats every ~60s (not every poll to reduce disk writes)
        if self._energy_at_start is not None:
            save_interval = getattr(self, "_last_save_ts", 0)
            if now_mono - save_interval > 60:
                self._save_daily_stats(self._energy_at_start)
                self._last_save_ts = now_mono

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
                "clamp_min_pct": getattr(control_state, "clamp_min_pct", 0),
                "clamp_max_pct": getattr(control_state, "clamp_max_pct", 100),
            }

        # Build venus_os section (Phase 11: lock state)
        venus_os: dict = {}
        if control_state is not None:
            venus_os = {
                "last_source": getattr(control_state, "last_source", "none"),
                "last_change_ts": getattr(control_state, "last_change_ts", 0.0),
                "is_locked": getattr(control_state, "is_locked", False),
                "lock_remaining_s": getattr(control_state, "lock_remaining_s", None),
            }

        # Build connection section
        connection: dict = {
            "state": conn_mgr.state.value if conn_mgr is not None else "unknown",
            "poll_success": poll_counter["success"] if poll_counter else 0,
            "poll_total": poll_counter["total"] if poll_counter else 0,
            "cache_stale": cache.is_stale,
        }

        # Read inverter identity from original SE30K poll data (not translated cache)
        def _decode_regs(regs: list[int]) -> str:
            result = b""
            for r in regs:
                result += r.to_bytes(2, "big")
            return result.rstrip(b"\x00").decode("ascii", errors="replace").strip()

        inverter_mfr = ""
        inverter_model = ""
        inverter_serial = ""
        last_poll = getattr(app_ctx, "last_poll_data", None) if app_ctx is not None else None
        if last_poll:
            se_common = last_poll.get("common_registers", [])
            if len(se_common) >= 66:
                # Common Model: DID(0) + Len(1) + Manufacturer(2-17) + Model(18-33) + ... + Serial(50-65)
                inverter_mfr = _decode_regs(se_common[2:18])
                inverter_model = _decode_regs(se_common[18:34])
                inverter_serial = _decode_regs(se_common[50:66])

        # Read rated power from Model 120 WRtg (register 40124, SF at 40125)
        wrtg_raw = db.getValues(40124 + _PB_OFFSET, 1)[0]
        wrtg_sf_raw = db.getValues(40125 + _PB_OFFSET, 1)[0]
        wrtg_sf = wrtg_sf_raw - 65536 if wrtg_sf_raw > 32767 else wrtg_sf_raw
        rated_power_w = wrtg_raw * (10 ** wrtg_sf) if wrtg_raw not in (0x8000, 0xFFFF) else 30000

        snapshot = {
            "ts": time.time(),
            "inverter": inverter,
            "inverter_name": f"{inverter_mfr} {inverter_model}".strip(),
            "inverter_serial": inverter_serial,
            "rated_power_w": rated_power_w,
            "control": control,
            "venus_os": venus_os,
            "connection": connection,
            "override_log": override_log.get_all() if override_log else [],
            "venus_mqtt_connected": app_ctx.venus_mqtt_connected if app_ctx is not None else False,
            "venus_os_detected": app_ctx.venus_os_detected if app_ctx is not None else False,
            "venus_os_client_ip": app_ctx.venus_os_client_ip if app_ctx is not None else "",
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

    def collect_from_raw(
        self,
        common_registers: list[int],
        inverter_registers: list[int],
        conn_mgr: object | None = None,
        poll_counter: dict | None = None,
        control_state: object | None = None,
        app_ctx: object | None = None,
        nameplate_registers: list[int] | None = None,
    ) -> dict:
        """Build snapshot directly from raw poll registers (no RegisterCache needed).

        Used by DeviceRegistry per-device poll loop in v4.0 multi-device mode.
        Reuses aggregation.decode_model_103_to_physical for consistent decode.
        """
        from pv_inverter_proxy.aggregation import decode_model_103_to_physical

        # Decode inverter identity from common registers
        def _decode_regs(regs: list[int]) -> str:
            result = b""
            for r in regs:
                result += r.to_bytes(2, "big")
            return result.rstrip(b"\x00").decode("ascii", errors="replace").strip()

        inverter_mfr = ""
        inverter_model = ""
        inverter_serial = ""
        if len(common_registers) >= 66:
            inverter_mfr = _decode_regs(common_registers[2:18])
            inverter_model = _decode_regs(common_registers[18:34])
            inverter_serial = _decode_regs(common_registers[50:66])

        # Decode physical values from Model 103
        phys = decode_model_103_to_physical(inverter_registers) if len(inverter_registers) >= 40 else {}

        # Map to dashboard inverter structure
        inverter: dict = {}
        for key, val in phys.items():
            inverter[key] = val

        # Status text
        status_code = phys.get("status_code", 0)
        inverter["status"] = INVERTER_STATUS.get(status_code, f"UNKNOWN({status_code})")

        # Daily energy tracking
        energy_wh = phys.get("energy_total_wh", 0)
        today = datetime.date.today().isoformat()
        if self._energy_date != today:
            self._energy_at_start = None
            self._energy_date = today
            self._peak_power_w = 0.0
            self._operating_seconds = 0.0
        if self._energy_at_start is None and energy_wh > 0:
            self._energy_at_start = energy_wh
        daily_wh = energy_wh - self._energy_at_start if self._energy_at_start is not None else 0
        inverter["daily_energy_wh"] = max(0, daily_wh)

        # Peak and operating stats
        ac_power = phys.get("ac_power_w", 0) or 0
        if ac_power > self._peak_power_w:
            self._peak_power_w = ac_power
        now_mono = time.monotonic()
        if self._last_collect_ts is not None and inverter.get("status") == "MPPT":
            delta = now_mono - self._last_collect_ts
            if 0 < delta < 10:
                self._operating_seconds += delta
        self._last_collect_ts = now_mono

        inverter["peak_power_w"] = self._peak_power_w
        inverter["operating_hours"] = round(self._operating_seconds / 3600, 4)
        dc_power = inverter.get("dc_power_w", 0) or 0
        inverter["efficiency_pct"] = round(ac_power / dc_power * 100, 1) if dc_power > 0 else 0.0

        # Persist daily stats periodically
        if self._energy_at_start is not None:
            save_interval = getattr(self, "_last_save_ts", 0)
            if now_mono - save_interval > 60:
                self._save_daily_stats(self._energy_at_start)
                self._last_save_ts = now_mono

        # Control section
        control: dict = {}
        if control_state is not None:
            control = {
                "enabled": control_state.is_enabled,
                "limit_pct": control_state.wmaxlimpct_float,
                "wmaxlimpct_raw": control_state.wmaxlimpct_raw,
                "last_source": getattr(control_state, "last_source", "none"),
                "last_change_ts": getattr(control_state, "last_change_ts", 0.0),
                "revert_remaining_s": _revert_remaining(control_state),
                "clamp_min_pct": getattr(control_state, "clamp_min_pct", 0),
                "clamp_max_pct": getattr(control_state, "clamp_max_pct", 100),
            }

        # Connection section
        connection: dict = {
            "state": conn_mgr.state.value if conn_mgr is not None else "unknown",
            "poll_success": poll_counter["success"] if poll_counter else 0,
            "poll_total": poll_counter["total"] if poll_counter else 0,
        }

        snapshot = {
            "ts": time.time(),
            "inverter": inverter,
            "inverter_name": f"{inverter_mfr} {inverter_model}".strip(),
            "inverter_serial": inverter_serial,
            "rated_power_w": self._decode_rated_power(nameplate_registers),
            "control": control,
            "venus_os": {},
            "connection": connection,
            "override_log": [],
            "venus_mqtt_connected": app_ctx.venus_mqtt_connected if app_ctx is not None else False,
            "venus_os_detected": app_ctx.venus_os_detected if app_ctx is not None else False,
            "venus_os_client_ip": app_ctx.venus_os_client_ip if app_ctx is not None else "",
        }

        # Feed time series buffers
        buf_map = {
            "ac_power_w": phys.get("ac_power_w"),
            "dc_power_w": phys.get("dc_power_w"),
            "ac_voltage_an_v": phys.get("ac_voltage_an_v"),
            "temperature_sink_c": phys.get("temperature_c"),
            "ac_frequency_hz": phys.get("ac_frequency_hz"),
            "energy_total_wh": phys.get("energy_total_wh"),
        }
        for buf_key, value in buf_map.items():
            if value is not None and buf_key in self._buffers:
                self._buffers[buf_key].append(float(value))

        self._last_snapshot = snapshot
        return snapshot

    @staticmethod
    def _decode_rated_power(nameplate_registers: list[int] | None) -> int:
        """Extract WRtg from Model 120 nameplate registers."""
        if not nameplate_registers or len(nameplate_registers) < 5:
            return 0
        wrtg_raw = nameplate_registers[3]
        wrtg_sf_raw = nameplate_registers[4]
        wrtg_sf = wrtg_sf_raw - 65536 if wrtg_sf_raw > 32767 else wrtg_sf_raw
        if wrtg_raw in (0x8000, 0xFFFF, 0):
            return 0
        return int(wrtg_raw * (10 ** wrtg_sf))

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
        """Read all DECODE_MAP fields, apply scale factors.

        SunSpec sentinel values (0x8000 for int16, 0xFFFF for uint16)
        indicate "not implemented" or "not available" and are returned as None.
        """
        # Cache scale factors (read once)
        sf_cache: dict[int, int] = {}
        result: dict[str, float | None] = {}

        for field_name, (addr, size, sf_addr) in DECODE_MAP.items():
            # Skip special fields handled in collect()
            if field_name in ("ac_energy", "status", "status_vendor"):
                continue

            raw = db.getValues(addr + _PB_OFFSET, 1)[0]

            # SunSpec "Not Implemented" sentinels
            if raw in (0x8000, 0xFFFF):
                result[field_name] = None
                continue

            if sf_addr is not None:
                if sf_addr not in sf_cache:
                    sf_cache[sf_addr] = self._read_int16(db, sf_addr)
                sf = sf_cache[sf_addr]
                # Scale factor sentinel: treat as no scaling
                if sf in (-32768, 32768):
                    result[field_name] = float(raw)
                else:
                    result[field_name] = raw * (10 ** sf)
            else:
                result[field_name] = float(raw)

        return result
