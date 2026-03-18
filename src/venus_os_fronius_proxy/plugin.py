from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PollResult:
    """Result from polling an inverter."""
    common_registers: list[int]    # 67 registers (DID + len + 65 data)
    inverter_registers: list[int]  # 52 registers (DID + len + 50 data)
    success: bool
    error: str | None = None


class InverterPlugin(ABC):
    """Interface for inverter brand plugins.

    Each brand plugin implements this ABC to provide:
    - Connection management to the physical inverter
    - Polling for live register data
    - Static identity overrides (manufacturer string, etc.)
    - Synthesized model data (Model 120 Nameplate)
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the inverter."""

    @abstractmethod
    async def poll(self) -> PollResult:
        """Read all registers needed for the SunSpec model chain.

        Returns PollResult with:
        - common_registers: 67 uint16 values (Model 1 DID + Length + 65 data fields)
        - inverter_registers: 52 uint16 values (Model 103 DID + Length + 50 data fields)
        - success: True if read succeeded
        - error: Error message if success is False
        """

    @abstractmethod
    def get_static_common_overrides(self) -> dict[int, int]:
        """Return register offset -> value for static Common Model fields.

        Offsets are relative to Common Model DID register (40002).
        E.g., {0: 1, 1: 65, 2: 0x4672, ...} for DID, Length, Manufacturer.
        """

    @abstractmethod
    def get_model_120_registers(self) -> list[int]:
        """Return 28 uint16 values for synthesized Model 120 (Nameplate).

        Includes DID (120) and Length (26) as first two values,
        followed by 26 data registers.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up connection resources."""
