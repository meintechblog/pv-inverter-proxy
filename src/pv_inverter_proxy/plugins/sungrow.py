"""Sungrow SG-RT inverter plugin.

Polls Sungrow SG-RT series inverters via Modbus TCP (function code 0x04,
input registers) and translates Sungrow-specific register data into SunSpec
Model 103 uint16 register arrays for DashboardCollector compatibility.

Phase 38 is read-only -- write_power_limit is a safe no-op.
Power control will be added in Phase 41.
"""
from __future__ import annotations

import structlog

from pymodbus.client import AsyncModbusTcpClient

from pv_inverter_proxy.plugin import InverterPlugin, PollResult, ThrottleCaps, WriteResult
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

# Sungrow connection defaults
DEFAULT_HOST = "192.168.2.151"
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1

# Sungrow input register read parameters
# Wire address = doc address - 1 (Sungrow docs are 1-based)
SUNGROW_INPUT_REG_START = 5002  # Wire address (doc 5003)
SUNGROW_INPUT_REG_COUNT = 36    # Wire 5002-5037

# Sungrow running state -> SunSpec Model 103 status code
SUNGROW_STATE_TO_SUNSPEC: dict[int, int] = {
    0x0000: 1,  # Stop -> OFF
    0x8000: 4,  # Run -> MPPT
    0x1300: 8,  # Standby -> STANDBY
    0x8100: 5,  # Derating -> THROTTLED
    0x5500: 7,  # Fault -> FAULT
}

# Value clamp ranges (T-38-02 mitigation: untrusted register values)
_CLAMP_VOLTAGE = (0.0, 1000.0)
_CLAMP_CURRENT = (0.0, 200.0)
_CLAMP_POWER = (0.0, 50000.0)
_CLAMP_TEMP = (-40.0, 100.0)


def _s16(val: int) -> int:
    """Convert unsigned 16-bit to signed int16."""
    return val if val < 0x8000 else val - 0x10000


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to range."""
    return max(lo, min(hi, value))


class SungrowPlugin(InverterPlugin):
    """Sungrow SG-RT inverter plugin.

    Polls live data via Modbus TCP using function code 0x04 (input registers)
    at wire addresses 5002-5037. Translates Sungrow register format to
    SunSpec Model 103 for aggregation compatibility.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        unit_id: int = DEFAULT_UNIT_ID,
        rated_power: int = 0,
    ):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.rated_power = rated_power
        self._client: AsyncModbusTcpClient | None = None
        # Cached DC channel data for dashboard use in Phase 39
        self.dc_channels: list[dict] = []

    async def connect(self) -> None:
        """Create Modbus TCP client and connect to Sungrow inverter."""
        self._client = AsyncModbusTcpClient(self.host, port=self.port)
        await self._client.connect()
        log.info(
            "sungrow_plugin_connected",
            host=self.host,
            port=self.port,
            unit_id=self.unit_id,
        )

    async def poll(self) -> PollResult:
        """Read Sungrow input registers and encode to SunSpec format.

        Uses read_input_registers (FC04) at wire addresses 5002-5037.
        Returns PollResult with 67 common + 52 inverter registers.
        """
        if self._client is None:
            return PollResult([], [], success=False, error="Not connected")

        try:
            result = await self._client.read_input_registers(
                SUNGROW_INPUT_REG_START,
                count=SUNGROW_INPUT_REG_COUNT,
                device_id=self.unit_id,
            )

            if result.isError():
                return PollResult(
                    [], [], success=False,
                    error=f"Sungrow read error: {result}",
                )

            raw = list(result.registers)

            # Parse Sungrow registers to physical values
            data = self._parse_sungrow_data(raw)

            # Cache DC channel data for dashboard
            self.dc_channels = [
                {
                    "name": "MPPT1",
                    "voltage_v": round(data["dc1_voltage_v"], 1),
                    "current_a": round(data["dc1_current_a"], 2),
                    "power_w": round(data["dc1_voltage_v"] * data["dc1_current_a"], 1),
                },
                {
                    "name": "MPPT2",
                    "voltage_v": round(data["dc2_voltage_v"], 1),
                    "current_a": round(data["dc2_current_a"], 2),
                    "power_w": round(data["dc2_voltage_v"] * data["dc2_current_a"], 1),
                },
            ]

            # Encode to SunSpec Model 103
            inverter_regs = self._encode_model_103(data)
            common_regs = self._build_common_registers()

            return PollResult(common_regs, inverter_regs, success=True)

        except Exception as e:
            log.warning("sungrow_poll_failed", error=str(e))
            return PollResult([], [], success=False, error=str(e))

    def _parse_sungrow_data(self, raw: list[int]) -> dict:
        """Parse 36 registers at wire 5002-5037 into physical values.

        Offsets relative to raw[0] = wire 5002.
        Sungrow conventions:
        - U32: high word at lower address
        - Scale factors: voltage 0.1V, current 0.1A, freq 0.1Hz, temp 0.1degC
        - Energy: 0.1 kWh (converted to Wh by multiplying by 100)
        """
        total_energy_wh = ((raw[1] << 16) | raw[2]) * 100  # U32, 0.1kWh -> Wh
        temperature_c = _clamp(_s16(raw[5]) * 0.1, *_CLAMP_TEMP)  # S16, 0.1degC
        dc1_voltage_v = _clamp(raw[8] * 0.1, *_CLAMP_VOLTAGE)    # wire 5010
        dc1_current_a = _clamp(raw[9] * 0.1, *_CLAMP_CURRENT)    # wire 5011
        dc2_voltage_v = _clamp(raw[10] * 0.1, *_CLAMP_VOLTAGE)   # wire 5012
        dc2_current_a = _clamp(raw[11] * 0.1, *_CLAMP_CURRENT)   # wire 5013
        total_dc_power_w = _clamp((raw[14] << 16) | raw[15], *_CLAMP_POWER)  # U32, wire 5016-5017
        phase_a_voltage_v = _clamp(raw[16] * 0.1, *_CLAMP_VOLTAGE)  # wire 5018
        phase_b_voltage_v = _clamp(raw[17] * 0.1, *_CLAMP_VOLTAGE)  # wire 5019
        phase_c_voltage_v = _clamp(raw[18] * 0.1, *_CLAMP_VOLTAGE)  # wire 5020
        phase_a_current_a = _clamp(raw[19] * 0.1, *_CLAMP_CURRENT)  # wire 5021
        phase_b_current_a = _clamp(raw[20] * 0.1, *_CLAMP_CURRENT)  # wire 5022
        phase_c_current_a = _clamp(raw[21] * 0.1, *_CLAMP_CURRENT)  # wire 5023
        total_active_power_w = _clamp((raw[28] << 16) | raw[29], *_CLAMP_POWER)  # U32, wire 5030-5031
        power_factor = _s16(raw[32]) * 0.001  # wire 5034
        frequency_hz = raw[33] * 0.1          # wire 5035
        running_state = raw[35]                # wire 5037

        return {
            "total_energy_wh": total_energy_wh,
            "temperature_c": temperature_c,
            "dc1_voltage_v": dc1_voltage_v,
            "dc1_current_a": dc1_current_a,
            "dc2_voltage_v": dc2_voltage_v,
            "dc2_current_a": dc2_current_a,
            "total_dc_power_w": total_dc_power_w,
            "phase_a_voltage_v": phase_a_voltage_v,
            "phase_b_voltage_v": phase_b_voltage_v,
            "phase_c_voltage_v": phase_c_voltage_v,
            "phase_a_current_a": phase_a_current_a,
            "phase_b_current_a": phase_b_current_a,
            "phase_c_current_a": phase_c_current_a,
            "total_active_power_w": total_active_power_w,
            "power_factor": power_factor,
            "frequency_hz": frequency_hz,
            "running_state": running_state,
        }

    def _encode_model_103(self, data: dict) -> list[int]:
        """Encode physical values into 52 uint16 SunSpec Model 103 registers.

        Follows the same layout as OpenDTU/Shelly plugins. Key difference:
        all three AC phases are populated (Sungrow is native 3-phase).
        """
        regs = [0] * 52
        regs[0] = 103  # DID
        regs[1] = 50   # Length

        # AC Current (offset 2-6), SF=-2
        total_current = abs(data["phase_a_current_a"] + data["phase_b_current_a"] + data["phase_c_current_a"])
        regs[2] = int(round(total_current * 100))       # Total AC current
        regs[3] = int(round(abs(data["phase_a_current_a"]) * 100))  # Phase A
        regs[4] = int(round(abs(data["phase_b_current_a"]) * 100))  # Phase B
        regs[5] = int(round(abs(data["phase_c_current_a"]) * 100))  # Phase C
        regs[6] = _int16_as_uint16(-2)                   # AC Current SF

        # AC Voltage (offset 7-13), SF=-1
        # Line voltages left as 0 (Sungrow reports phase voltages, not line-to-line)
        regs[10] = int(round(abs(data["phase_a_voltage_v"]) * 10))  # Voltage AN
        regs[11] = int(round(abs(data["phase_b_voltage_v"]) * 10))  # Voltage BN
        regs[12] = int(round(abs(data["phase_c_voltage_v"]) * 10))  # Voltage CN
        regs[13] = _int16_as_uint16(-1)                   # AC Voltage SF

        # AC Power (offset 14-15), SF=0
        regs[14] = int(round(abs(data["total_active_power_w"]))) & 0xFFFF
        regs[15] = 0                                       # AC Power SF

        # AC Frequency (offset 16-17), SF=-2
        regs[16] = int(round(data["frequency_hz"] * 100))
        regs[17] = _int16_as_uint16(-2)                    # Frequency SF

        # AC Energy (offset 24-26), acc32 in Wh + SF
        energy_wh = int(data["total_energy_wh"])
        regs[24] = (energy_wh >> 16) & 0xFFFF              # High word
        regs[25] = energy_wh & 0xFFFF                       # Low word
        regs[26] = 0                                        # Energy SF

        # DC Current (offset 27-28), SF=-2
        # Sum DC currents from both MPPTs
        dc_current_total = abs(data["dc1_current_a"] + data["dc2_current_a"])
        regs[27] = int(round(dc_current_total * 100))
        regs[28] = _int16_as_uint16(-2)                     # DC Current SF

        # DC Voltage (offset 29-30), SF=-1
        # Use MPPT1 as primary DC voltage channel
        regs[29] = int(round(abs(data["dc1_voltage_v"]) * 10))
        regs[30] = _int16_as_uint16(-1)                     # DC Voltage SF

        # DC Power (offset 31-32), SF=0
        regs[31] = int(round(abs(data["total_dc_power_w"])))
        regs[32] = 0                                        # DC Power SF

        # Temperature (offset 33-37), SF=-1
        regs[33] = int(round(data["temperature_c"] * 10))
        regs[37] = _int16_as_uint16(-1)                     # Temp SF

        # Status (offset 38)
        running_state = data["running_state"]
        regs[38] = SUNGROW_STATE_TO_SUNSPEC.get(running_state, 2)  # Default: SLEEPING

        return regs

    def _build_common_registers(self) -> list[int]:
        """Build 67 uint16 registers for Common Model (Model 1)."""
        regs = [0] * 67
        regs[0] = COMMON_DID      # 1
        regs[1] = COMMON_LENGTH   # 65

        # Manufacturer "Sungrow" at offset 2-17 (16 registers)
        regs[2:18] = encode_string("Sungrow", 16)

        # Model "SG-RT" at offset 18-33 (16 registers)
        regs[18:34] = encode_string("SG-RT", 16)

        # Serial at offset 50-65 (16 registers) -- empty, updated at runtime
        regs[50:66] = encode_string("", 16)

        # Device Address
        regs[66] = PROXY_UNIT_ID

        return regs

    def get_static_common_overrides(self) -> dict[int, int]:
        """Return register offset -> value for Common Model static fields."""
        overrides: dict[int, int] = {0: COMMON_DID, 1: COMMON_LENGTH}

        # Manufacturer "Sungrow" at offset 2-17
        sungrow_regs = encode_string("Sungrow", 16)
        for i, val in enumerate(sungrow_regs):
            overrides[2 + i] = val

        # Model at offset 18-33
        model_regs = encode_string("SG-RT", 16)
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
        regs[3] = self.rated_power   # WRtg
        regs[4] = 0                  # WRtg_SF
        return regs

    async def write_power_limit(self, enable: bool, limit_pct: float, *, force: bool = False) -> WriteResult:
        """No-op power limit write for Phase 38 (read-only).

        Power control will be implemented in Phase 41 via Sungrow holding
        register writes.
        """
        log.warning(
            "sungrow_write_power_limit_noop",
            msg="Power control not yet implemented for Sungrow (Phase 41)",
            enable=enable,
            limit_pct=limit_pct,
        )
        return WriteResult(success=True)

    async def reconfigure(self, host: str, port: int, unit_id: int) -> None:
        """Reconfigure connection parameters. Closes existing connection."""
        await self.close()
        self.host = host
        self.port = port
        self.unit_id = unit_id
        log.info(
            "sungrow_reconfigured",
            host=host,
            port=port,
            unit_id=unit_id,
        )

    @property
    def throttle_capabilities(self) -> ThrottleCaps:
        """Declare proportional throttle capabilities for Sungrow.

        Sungrow supports percentage-based power limiting via Modbus TCP
        with ~2s response time.
        """
        return ThrottleCaps(
            mode="proportional",
            response_time_s=2.0,
            cooldown_s=0.0,
            startup_delay_s=0.0,
        )

    async def close(self) -> None:
        """Clean up Modbus TCP connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            log.info("sungrow_plugin_closed", host=self.host)
