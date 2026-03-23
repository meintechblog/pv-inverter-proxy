"""OpenDTU plugin for Hoymiles micro-inverters.

Polls Hoymiles inverters via OpenDTU REST API and translates JSON responses
to SunSpec uint16 register arrays for DashboardCollector compatibility.
Supports power limiting via POST /api/limit/config with dead-time guard.
"""
from __future__ import annotations

import json
import time

import aiohttp
import structlog

from pv_inverter_proxy.config import GatewayConfig
from pv_inverter_proxy.plugin import InverterPlugin, PollResult, WriteResult
from pv_inverter_proxy.sunspec_models import (
    encode_string,
    _int16_as_uint16,
    COMMON_DID,
    COMMON_LENGTH,
    NAMEPLATE_DID,
    NAMEPLATE_LENGTH,
    PROXY_UNIT_ID,
)

log = structlog.get_logger()

# Dead-time guard: suppress power limit re-sends for this duration
DEAD_TIME_S = 30.0


class OpenDTUPlugin(InverterPlugin):
    """OpenDTU plugin for Hoymiles micro-inverters.

    Polls /api/livedata/status for live data, translates JSON to SunSpec
    Model 103 register arrays. Sends power limits via POST /api/limit/config
    with Basic Auth and a 30s dead-time guard.
    """

    def __init__(
        self,
        gateway_config: GatewayConfig,
        serial: str,
        name: str = "",
    ):
        self._gw = gateway_config
        self.serial = serial
        self.name = name or serial
        self._session: aiohttp.ClientSession | None = None
        self._max_power_w: int = 400  # Default, updated from /api/limit/status
        self._last_limit_ts: float = 0.0
        self._limit_pending: bool = False
        # Cached OpenDTU status (updated every poll)
        self.opendtu_status: dict = {}
        self.dc_channels: list[dict] = []

    async def connect(self) -> None:
        """Create aiohttp.ClientSession with Basic Auth for the gateway."""
        auth = aiohttp.BasicAuth(self._gw.user, self._gw.password)
        self._session = aiohttp.ClientSession(auth=auth)
        log.info(
            "opendtu_plugin_connected",
            gateway=self._gw.host,
            serial=self.serial,
            name=self.name,
        )

    async def poll(self) -> PollResult:
        """Poll OpenDTU /api/livedata/status and convert to SunSpec registers."""
        if self._session is None:
            return PollResult([], [], success=False, error="Not connected")

        try:
            url = f"http://{self._gw.host}/api/livedata/status"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        except Exception as e:
            log.warning("opendtu_poll_failed", serial=self.serial, error=str(e))
            return PollResult([], [], success=False, error=str(e))

        # Find our inverter by serial
        inv = self._find_inverter(data)
        if inv is None:
            serials = [str(i.get("serial", "?")) for i in data.get("inverters", []) if isinstance(i, dict)] if isinstance(data, dict) else []
            return PollResult(
                [], [], success=False,
                error=f"Serial {self.serial} not found (got: {serials})",
            )

        if not inv.get("reachable", False):
            return PollResult(
                [], [], success=False,
                error=f"Inverter {self.serial} is unreachable",
            )

        # Update rated power from OpenDTU limit_absolute at 100%
        limit_abs = inv.get("limit_absolute", 0)
        limit_rel = inv.get("limit_relative", 100)
        if limit_abs and limit_rel and limit_rel > 0:
            rated = int(round(limit_abs / limit_rel * 100))
            if rated > 0:
                self._max_power_w = rated

        # Cache OpenDTU-specific status for instant access
        self.opendtu_status = {
            "producing": inv.get("producing", False),
            "reachable": inv.get("reachable", False),
            "limit_relative": limit_rel,
            "limit_absolute": limit_abs,
        }

        # Extract physical values
        ac = inv.get("AC", {}).get("0", {})
        ac_power_w = ac.get("Power", {}).get("v", 0.0)
        ac_voltage_v = ac.get("Voltage", {}).get("v", 0.0)
        ac_current_a = ac.get("Current", {}).get("v", 0.0)
        ac_freq_hz = ac.get("Frequency", {}).get("v", 0.0)

        # Sum DC channels + cache per-string data
        dc_channels_raw = inv.get("DC", {})
        dc_power_w = 0.0
        dc_current_a = 0.0
        dc_voltage_sum = 0.0
        dc_power_sum = 0.0
        total_yield_kwh = 0.0
        total_yield_day_kwh = 0.0
        cached_dc = []

        for ch_key in sorted(dc_channels_raw.keys()):
            ch = dc_channels_raw[ch_key]
            ch_power = ch.get("Power", {}).get("v", 0.0)
            ch_voltage = ch.get("Voltage", {}).get("v", 0.0)
            ch_current = ch.get("Current", {}).get("v", 0.0)
            ch_yield_day = ch.get("YieldDay", {}).get("v", 0.0)
            ch_yield_total = ch.get("YieldTotal", {}).get("v", 0.0)

            dc_power_w += ch_power
            dc_current_a += ch_current
            dc_voltage_sum += ch_voltage * ch_power
            dc_power_sum += ch_power
            total_yield_kwh += ch_yield_total
            total_yield_day_kwh += ch_yield_day

            cached_dc.append({
                "name": ch.get("name", {}).get("u", "") if isinstance(ch.get("name"), dict) else (ch.get("name") or f"String {int(ch_key) + 1}"),
                "voltage_v": round(ch_voltage, 1),
                "current_a": round(ch_current, 2),
                "power_w": round(ch_power, 1),
                "yield_day_wh": round(ch_yield_day * 1000) if ch_yield_day < 100 else round(ch_yield_day),
                "yield_total_kwh": round(ch_yield_total, 1),
            })

        self.dc_channels = cached_dc

        # Power-weighted average voltage
        dc_voltage_v = dc_voltage_sum / dc_power_sum if dc_power_sum > 0 else 0.0

        # Temperature
        temperature_c = inv.get("INV", {}).get("0", {}).get("Temperature", {}).get("v", 0.0)

        # Status: 4=MPPT if producing, 2=SLEEPING if not
        producing = inv.get("producing", False)
        status_code = 4 if producing else 2

        # Convert energy from kWh to Wh
        energy_total_wh = int(round(total_yield_kwh * 1000))
        yield_day_wh = int(round(total_yield_day_kwh * 1000))

        # Encode registers
        inverter_regs = self._encode_model_103(
            ac_power_w=ac_power_w,
            ac_voltage_v=ac_voltage_v,
            ac_current_a=ac_current_a,
            ac_freq_hz=ac_freq_hz,
            dc_power_w=dc_power_w,
            dc_voltage_v=dc_voltage_v,
            dc_current_a=dc_current_a,
            temperature_c=temperature_c,
            energy_total_wh=energy_total_wh,
            yield_day_wh=yield_day_wh,
            status_code=status_code,
        )
        common_regs = self._build_common_registers()

        return PollResult(common_regs, inverter_regs, success=True)

    def _find_inverter(self, data: dict | None) -> dict | None:
        """Find inverter by serial in the API response."""
        if not isinstance(data, dict):
            return None
        for inv in data.get("inverters", []):
            if isinstance(inv, dict) and str(inv.get("serial", "")) == str(self.serial):
                return inv
        return None

    def _encode_model_103(
        self,
        ac_power_w: float,
        ac_voltage_v: float,
        ac_current_a: float,
        ac_freq_hz: float,
        dc_power_w: float,
        dc_voltage_v: float,
        dc_current_a: float,
        temperature_c: float,
        energy_total_wh: int,
        yield_day_wh: int,
        status_code: int,
    ) -> list[int]:
        """Encode physical values into 52 uint16 SunSpec Model 103 registers."""
        regs = [0] * 52
        regs[0] = 103   # DID
        regs[1] = 50    # Length

        # AC Current (offset 2-6)
        regs[2] = int(round(ac_current_a * 100))    # Total AC current, SF=-2
        regs[3] = int(round(ac_current_a * 100))    # Phase A (single-phase)
        regs[4] = 0  # Phase B (N/A)
        regs[5] = 0  # Phase C (N/A)
        regs[6] = _int16_as_uint16(-2)               # AC Current SF

        # AC Voltage (offset 7-13)
        regs[10] = int(round(ac_voltage_v * 10))     # AC Voltage AN, SF=-1
        regs[13] = _int16_as_uint16(-1)               # AC Voltage SF

        # AC Power (offset 14-15)
        regs[14] = int(round(ac_power_w)) & 0xFFFF   # AC Power, SF=0
        regs[15] = 0                                   # AC Power SF

        # AC Frequency (offset 16-17)
        regs[16] = int(round(ac_freq_hz * 100))      # Frequency, SF=-2
        regs[17] = _int16_as_uint16(-2)               # Frequency SF

        # AC Energy (offset 24-26): acc32 in Wh + SF
        regs[24] = (energy_total_wh >> 16) & 0xFFFF  # High word
        regs[25] = energy_total_wh & 0xFFFF            # Low word
        regs[26] = 0                                   # Energy SF (already in Wh)

        # DC Current (offset 27-28)
        regs[27] = int(round(dc_current_a * 100))    # DC Current, SF=-2
        regs[28] = _int16_as_uint16(-2)               # DC Current SF

        # DC Voltage (offset 29-30)
        regs[29] = int(round(dc_voltage_v * 10))     # DC Voltage, SF=-1
        regs[30] = _int16_as_uint16(-1)               # DC Voltage SF

        # DC Power (offset 31-32)
        regs[31] = int(round(dc_power_w))            # DC Power, SF=0
        regs[32] = 0                                   # DC Power SF

        # Temperature (offset 33-37)
        regs[33] = int(round(temperature_c * 10))    # Cab temp, SF=-1
        regs[37] = _int16_as_uint16(-1)               # Temp SF

        # Status (offset 38)
        regs[38] = status_code  # 4=MPPT, 2=SLEEPING

        return regs

    def _build_common_registers(self) -> list[int]:
        """Build 67 uint16 registers for Common Model (Model 1)."""
        regs = [0] * 67
        regs[0] = COMMON_DID      # 1
        regs[1] = COMMON_LENGTH   # 65

        # Manufacturer "Hoymiles" at offset 2-17 (16 registers)
        regs[2:18] = encode_string("Hoymiles", 16)

        # Model (name or serial) at offset 18-33 (16 registers)
        regs[18:34] = encode_string(self.name, 16)

        # Serial at offset 50-65 (16 registers)
        regs[50:66] = encode_string(self.serial, 16)

        # Device Address
        regs[66] = PROXY_UNIT_ID

        return regs

    def get_static_common_overrides(self) -> dict[int, int]:
        """Return register offset -> value for Common Model static fields."""
        overrides: dict[int, int] = {0: COMMON_DID, 1: COMMON_LENGTH}

        # Manufacturer "Hoymiles" at offset 2-17
        hoymiles_regs = encode_string("Hoymiles", 16)
        for i, val in enumerate(hoymiles_regs):
            overrides[2 + i] = val

        # Model at offset 18-33
        model_regs = encode_string(self.name, 16)
        for i, val in enumerate(model_regs):
            overrides[18 + i] = val

        # Device Address
        overrides[66] = PROXY_UNIT_ID

        return overrides

    def get_model_120_registers(self) -> list[int]:
        """Return 28 uint16 values for synthesized Model 120 (Nameplate)."""
        regs = [0] * 28
        regs[0] = NAMEPLATE_DID      # 120
        regs[1] = NAMEPLATE_LENGTH   # 26
        regs[2] = 4                  # DERTyp = PV
        regs[3] = self._max_power_w  # WRtg
        regs[4] = 0                  # WRtg_SF
        return regs

    async def write_power_limit(self, enable: bool, limit_pct: float, *, force: bool = False) -> WriteResult:
        """Write power limit to Hoymiles via OpenDTU POST /api/limit/config.

        Uses a dead-time guard to suppress re-sends within 30s of the last command.
        """
        if self._session is None:
            return WriteResult(success=False, error="Not connected")

        # Dead-time guard (skipped for explicit user requests via force=True)
        now = time.monotonic()
        if not force and self._limit_pending and (now - self._last_limit_ts) < DEAD_TIME_S:
            log.debug(
                "dead_time_suppressed",
                serial=self.serial,
                elapsed=now - self._last_limit_ts,
            )
            return WriteResult(success=True)

        # If disabling, set to 100% (full power = no limit)
        if not enable:
            limit_pct = 100.0

        url = f"http://{self._gw.host}/api/limit/config"
        payload = {
            "serial": self.serial,
            "limit_type": 257,  # Relative percentage, non-persistent (temporary)
            "limit_value": limit_pct,
        }
        form_data = {"data": json.dumps(payload)}

        try:
            async with self._session.post(url, data=form_data) as resp:
                await resp.json()

            self._last_limit_ts = time.monotonic()
            self._limit_pending = True
            log.info(
                "opendtu_power_limit_set",
                serial=self.serial,
                limit_pct=limit_pct,
                enable=enable,
            )
            return WriteResult(success=True)
        except Exception as e:
            log.warning(
                "opendtu_power_limit_failed",
                serial=self.serial,
                error=str(e),
            )
            return WriteResult(success=False, error=str(e))

    async def reconfigure(self, host: str, port: int, unit_id: int) -> None:
        """Reconfigure is mostly a no-op for OpenDTU (config is gateway_host + serial).

        Closes existing session to allow reconnect on next poll.
        """
        log.warning(
            "opendtu_reconfigure_noop",
            serial=self.serial,
            msg="host/port/unit_id are SolarEdge concepts; closing session for reconnect",
        )
        await self.close()

    async def get_inverter_status(self) -> dict:
        """Query OpenDTU for this inverter's live status and limits.

        Returns dict with: producing, reachable, limit_relative, limit_absolute.
        """
        if self._session is None or self._session.closed:
            return {"error": "Not connected"}
        try:
            url = f"http://{self._gw.host}/api/livedata/status"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
            if not isinstance(data, dict):
                return {"error": "Invalid response from OpenDTU"}
            for inv in data.get("inverters", []):
                if not isinstance(inv, dict):
                    continue
                if str(inv.get("serial", "")) == str(self.serial):
                    return {
                        "producing": inv.get("producing", False),
                        "reachable": inv.get("reachable", False),
                        "limit_relative": inv.get("limit_relative", 100),
                        "limit_absolute": inv.get("limit_absolute", 0),
                    }
            return {"error": f"Serial {self.serial} not found in OpenDTU"}
        except Exception as e:
            return {"error": str(e)}

    async def send_power_command(self, action: str) -> WriteResult:
        """Send power on/off/restart to this inverter via OpenDTU.

        action: "on", "off", or "restart"
        """
        if self._session is None:
            return WriteResult(success=False, error="Not connected")

        url = f"http://{self._gw.host}/api/power/config"
        payload = {"serial": self.serial}
        if action == "on":
            payload["power"] = True
        elif action == "off":
            payload["power"] = False
        elif action == "restart":
            payload["restart"] = True
        else:
            return WriteResult(success=False, error=f"Unknown action: {action}")

        form_data = {"data": json.dumps(payload)}
        try:
            async with self._session.post(url, data=form_data) as resp:
                await resp.json()
            log.info("opendtu_power_command", serial=self.serial, action=action)
            return WriteResult(success=True)
        except Exception as e:
            log.warning("opendtu_power_command_failed", serial=self.serial, action=action, error=str(e))
            return WriteResult(success=False, error=str(e))

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            log.info("opendtu_plugin_closed", serial=self.serial)
        self._session = None
