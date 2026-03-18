"""SolarEdge SE30K inverter plugin.

Polls the SE30K via Modbus TCP and provides register data
translated for Fronius proxy serving.
"""
from __future__ import annotations

import logging

from pymodbus.client import AsyncModbusTcpClient

from venus_os_fronius_proxy.plugin import InverterPlugin, PollResult
from venus_os_fronius_proxy.sunspec_models import (
    encode_string,
    _int16_as_uint16,
    COMMON_DID,
    COMMON_LENGTH,
    NAMEPLATE_DID,
    NAMEPLATE_LENGTH,
    PROXY_UNIT_ID,
)

logger = logging.getLogger(__name__)

# SE30K connection defaults
DEFAULT_HOST = "192.168.3.18"
DEFAULT_PORT = 1502
DEFAULT_UNIT_ID = 1

# Register read parameters
COMMON_READ_ADDR = 40002   # Common Model DID register
COMMON_READ_COUNT = 67     # DID + Length + 65 data
INVERTER_READ_ADDR = 40069 # Inverter Model DID register
INVERTER_READ_COUNT = 52   # DID + Length + 50 data


class SolarEdgePlugin(InverterPlugin):
    """SolarEdge SE30K inverter plugin.

    Polls the SE30K via Modbus TCP and provides register data
    translated for Fronius proxy serving.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        unit_id: int = DEFAULT_UNIT_ID,
    ):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._client: AsyncModbusTcpClient | None = None

    async def connect(self) -> None:
        self._client = AsyncModbusTcpClient(self.host, port=self.port)
        await self._client.connect()
        logger.info("Connected to SolarEdge at %s:%d", self.host, self.port)

    async def poll(self) -> PollResult:
        if self._client is None or not self._client.connected:
            return PollResult(
                common_registers=[], inverter_registers=[],
                success=False, error="Not connected",
            )
        try:
            # Read Common Model (67 registers starting at 40002)
            common = await self._client.read_holding_registers(
                COMMON_READ_ADDR, count=COMMON_READ_COUNT, slave=self.unit_id,
            )
            # Read Inverter Model 103 (52 registers starting at 40069)
            inverter = await self._client.read_holding_registers(
                INVERTER_READ_ADDR, count=INVERTER_READ_COUNT, slave=self.unit_id,
            )

            if common.isError():
                return PollResult(
                    common_registers=[], inverter_registers=[],
                    success=False, error=f"Common read error: {common}",
                )
            if inverter.isError():
                return PollResult(
                    common_registers=[], inverter_registers=[],
                    success=False, error=f"Inverter read error: {inverter}",
                )

            return PollResult(
                common_registers=list(common.registers),
                inverter_registers=list(inverter.registers),
                success=True,
            )
        except Exception as e:
            logger.warning("Poll failed: %s", e)
            return PollResult(
                common_registers=[], inverter_registers=[],
                success=False, error=str(e),
            )

    def get_static_common_overrides(self) -> dict[int, int]:
        """Return offset -> value for Common Model static overrides.

        Offsets relative to Common Model DID register (40002).
        Overrides: DID, Length, Manufacturer ("Fronius"), DeviceAddress (126).
        """
        overrides: dict[int, int] = {0: COMMON_DID, 1: COMMON_LENGTH}
        fronius_regs = encode_string("Fronius", 16)
        for i, val in enumerate(fronius_regs):
            overrides[2 + i] = val  # C_Manufacturer at offset 2-17
        overrides[66] = PROXY_UNIT_ID  # C_DeviceAddress
        return overrides

    def get_model_120_registers(self) -> list[int]:
        """Return 28 uint16 values for synthesized Model 120 (Nameplate).

        SE30K does not provide Model 120; we synthesize from datasheet specs.
        """
        regs = [0] * 28  # DID + Length + 26 data
        regs[0] = NAMEPLATE_DID      # 120
        regs[1] = NAMEPLATE_LENGTH   # 26
        regs[2] = 4       # DERTyp = PV
        regs[3] = 30000   # WRtg = 30kW
        regs[4] = 0       # WRtg_SF
        regs[5] = 30000   # VARtg = 30kVA
        regs[6] = 0       # VARtg_SF
        regs[7] = 18000   # VArRtgQ1
        regs[8] = 18000   # VArRtgQ2
        regs[9] = _int16_as_uint16(-18000)   # VArRtgQ3
        regs[10] = _int16_as_uint16(-18000)  # VArRtgQ4
        regs[11] = 0      # VArRtg_SF
        regs[12] = 44     # ARtg = 44A
        regs[13] = 0      # ARtg_SF
        regs[14] = 100    # PFRtgQ1
        regs[15] = 100    # PFRtgQ2
        regs[16] = _int16_as_uint16(-100)    # PFRtgQ3
        regs[17] = _int16_as_uint16(-100)    # PFRtgQ4
        regs[18] = _int16_as_uint16(-2)      # PFRtg_SF
        # 19-27 = zeros (storage ratings N/A, padding)
        return regs

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            logger.info("Disconnected from SolarEdge")
