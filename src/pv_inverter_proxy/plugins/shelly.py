"""Shelly plugin for smart plugs and switches monitoring micro-PV inverters.

Polls Shelly devices over their local HTTP/JSON API, auto-detects Gen1 vs
Gen2+ generations via profile-based abstraction, extracts power/voltage/
current/frequency/energy/temperature data, and encodes it into SunSpec
Model 103 registers identical to the OpenDTU pattern.

Shelly devices cannot do percentage-based power limiting -- write_power_limit()
is a no-op. Switch on/off control is handled separately (Phase 29).
"""
from __future__ import annotations

import aiohttp
import structlog

from pv_inverter_proxy.plugin import InverterPlugin, PollResult, WriteResult
from pv_inverter_proxy.plugins.shelly_profiles import (
    Gen1Profile,
    Gen2Profile,
    ShellyPollData,
    ShellyProfile,
)
from pv_inverter_proxy.sunspec_models import (
    COMMON_DID,
    COMMON_LENGTH,
    NAMEPLATE_DID,
    NAMEPLATE_LENGTH,
    PROXY_UNIT_ID,
    _int16_as_uint16,
    encode_string,
)

log = structlog.get_logger()


class ShellyPlugin(InverterPlugin):
    """Shelly plugin implementing InverterPlugin ABC.

    Supports Gen1 (Shelly 1PM, Plug S) and Gen2+ (Plus 1PM, Pro series)
    devices via swappable profile objects. Auto-detects the generation
    by probing the /shelly endpoint on first connect.
    """

    def __init__(
        self,
        host: str,
        generation: str = "",
        name: str = "",
        rated_power: int = 0,
    ):
        self._host = host
        self._name = name or host
        self._rated_power = rated_power
        self._generation = generation  # "" = auto-detect, "gen1", "gen2"
        self._session: aiohttp.ClientSession | None = None
        self._profile: ShellyProfile | None = None
        self._energy_offset_wh: float = 0.0
        self._last_energy_raw_wh: float = 0.0
        self._device_info: dict = {}

    async def connect(self) -> None:
        """Create aiohttp session and auto-detect Shelly generation if needed."""
        self._session = aiohttp.ClientSession()

        if self._generation not in ("gen1", "gen2"):
            # Auto-detect via GET /shelly
            try:
                url = f"http://{self._host}/shelly"
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()

                gen = data.get("gen", 0)
                if gen >= 3:
                    self._generation = "gen3"
                elif gen >= 2:
                    self._generation = "gen2"
                else:
                    self._generation = "gen1"
                self._device_info = data
            except Exception as e:
                log.warning(
                    "shelly_detection_failed",
                    host=self._host,
                    error=str(e),
                    fallback="gen1",
                )
                self._generation = "gen1"

        self._profile = Gen2Profile() if self._generation in ("gen2", "gen3") else Gen1Profile()

        log.info(
            "shelly_plugin_connected",
            host=self._host,
            generation=self._generation,
            name=self._name,
        )

    async def poll(self) -> PollResult:
        """Poll Shelly device and encode data to SunSpec Model 103 registers."""
        if self._session is None or self._profile is None:
            return PollResult([], [], success=False, error="Not connected")

        try:
            data = await self._profile.poll_status(self._session, self._host)
        except Exception as e:
            log.warning(
                "shelly_poll_failed",
                host=self._host,
                error=str(e),
            )
            return PollResult([], [], success=False, error=str(e))

        tracked_energy = self._track_energy(data.energy_total_wh)
        inverter_regs = self._encode_model_103(data, tracked_energy)
        common_regs = self._build_common_registers()

        return PollResult(common_regs, inverter_regs, success=True)

    def _track_energy(self, raw_energy_wh: float) -> float:
        """Track energy with counter reset detection.

        Shelly devices reset their energy counter on reboot. This method
        detects when the raw value drops below the previous reading and
        accumulates an offset so the total never decreases.
        """
        if raw_energy_wh < self._last_energy_raw_wh:
            # Counter reset detected -- accumulate previous total as offset
            self._energy_offset_wh += self._last_energy_raw_wh
        self._last_energy_raw_wh = raw_energy_wh
        return raw_energy_wh + self._energy_offset_wh

    def _encode_model_103(self, data: ShellyPollData, energy_wh: float) -> list[int]:
        """Encode Shelly data into 52 uint16 SunSpec Model 103 registers.

        Register layout matches OpenDTU encoding exactly.
        Shelly has no DC data -- DC registers are all zero.
        """
        regs = [0] * 52
        regs[0] = 103   # DID
        regs[1] = 50    # Length

        # AC Current (offset 2-6)
        regs[2] = int(round(data.current_a * 100))    # Total AC current, SF=-2
        regs[3] = int(round(data.current_a * 100))    # Phase A (single-phase)
        regs[4] = 0  # Phase B (N/A)
        regs[5] = 0  # Phase C (N/A)
        regs[6] = _int16_as_uint16(-2)                 # AC Current SF

        # AC Voltage (offset 7-13)
        regs[10] = int(round(data.voltage_v * 10))     # AC Voltage AN, SF=-1
        regs[13] = _int16_as_uint16(-1)                 # AC Voltage SF

        # AC Power (offset 14-15)
        regs[14] = int(round(data.power_w)) & 0xFFFF   # AC Power, SF=0
        regs[15] = 0                                     # AC Power SF

        # AC Frequency (offset 16-17)
        regs[16] = int(round(data.frequency_hz * 100))  # Frequency, SF=-2
        regs[17] = _int16_as_uint16(-2)                  # Frequency SF

        # AC Energy (offset 24-26): acc32 in Wh + SF
        energy_int = int(round(energy_wh))
        regs[24] = (energy_int >> 16) & 0xFFFF  # High word
        regs[25] = energy_int & 0xFFFF            # Low word
        regs[26] = 0                               # Energy SF

        # DC registers all zero (Shelly has no DC data)
        regs[27] = 0                               # DC Current
        regs[28] = _int16_as_uint16(-2)            # DC Current SF
        regs[29] = 0                               # DC Voltage
        regs[30] = _int16_as_uint16(-1)            # DC Voltage SF
        regs[31] = 0                               # DC Power
        regs[32] = 0                               # DC Power SF

        # Temperature (offset 33-37)
        regs[33] = int(round(data.temperature_c * 10))  # Cab temp, SF=-1
        regs[37] = _int16_as_uint16(-1)                  # Temp SF

        # Status (offset 38): MPPT when relay on, SLEEPING when off
        regs[38] = 4 if data.relay_on else 2

        return regs

    def _build_common_registers(self) -> list[int]:
        """Build 67 uint16 registers for Common Model (Model 1)."""
        regs = [0] * 67
        regs[0] = COMMON_DID      # 1
        regs[1] = COMMON_LENGTH   # 65

        # Manufacturer "Shelly" at offset 2-17 (16 registers)
        regs[2:18] = encode_string("Shelly", 16)

        # Model (name) at offset 18-33 (16 registers)
        regs[18:34] = encode_string(self._name, 16)

        # Serial (MAC) at offset 50-65 (16 registers)
        mac = self._device_info.get("mac", "")
        regs[50:66] = encode_string(mac, 16)

        # Device Address
        regs[66] = PROXY_UNIT_ID

        return regs

    def get_static_common_overrides(self) -> dict[int, int]:
        """Return register offset -> value for Common Model static fields."""
        overrides: dict[int, int] = {0: COMMON_DID, 1: COMMON_LENGTH}

        # Manufacturer "Shelly" at offset 2-17
        shelly_regs = encode_string("Shelly", 16)
        for i, val in enumerate(shelly_regs):
            overrides[2 + i] = val

        # Model at offset 18-33
        model_regs = encode_string(self._name, 16)
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
        regs[3] = self._rated_power  # WRtg
        regs[4] = 0                  # WRtg_SF
        return regs

    async def write_power_limit(
        self, enable: bool, limit_pct: float, *, force: bool = False
    ) -> WriteResult:
        """No-op: Shelly cannot do percentage-based power limiting."""
        return WriteResult(success=True)

    async def switch(self, on: bool) -> bool:
        """Switch relay on/off. Delegates to the generation-specific profile."""
        if self._session is None or self._profile is None:
            return False
        try:
            return await self._profile.switch(self._session, self._host, on)
        except Exception as e:
            log.warning("shelly_switch_failed", host=self._host, on=on, error=str(e))
            return False

    async def reconfigure(self, host: str, port: int, unit_id: int) -> None:
        """Reconfigure connection: close session, update host, reset profile."""
        await self.close()
        self._host = host
        self._profile = None
        self._generation = ""  # Re-detect on next connect

    async def close(self) -> None:
        """Clean up aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            log.info("shelly_plugin_closed", host=self._host)
        self._session = None
