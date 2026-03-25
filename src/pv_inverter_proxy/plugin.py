from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


ThrottleMode = Literal["proportional", "binary", "none"]


@dataclass
class PollResult:
    """Result from polling an inverter."""
    common_registers: list[int]    # 67 registers (DID + len + 65 data)
    inverter_registers: list[int]  # 52 registers (DID + len + 50 data)
    success: bool
    error: str | None = None


@dataclass
class WriteResult:
    """Result from writing a power limit to the inverter."""
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class ThrottleCaps:
    """Throttle capabilities declared by an inverter plugin."""
    mode: ThrottleMode
    response_time_s: float
    cooldown_s: float
    startup_delay_s: float


def compute_throttle_score(caps: ThrottleCaps) -> float:
    """Compute throttle speed score 0-10 from capabilities.

    Higher = faster regulation. Proportional > binary > none.
    """
    if caps.mode == "none":
        return 0.0
    if caps.mode == "proportional":
        base = 7.0
    else:  # binary
        base = 3.0
    response_bonus = max(0.0, 3.0 * (1.0 - caps.response_time_s / 10.0))
    cooldown_penalty = min(2.0, caps.cooldown_s / 150.0)
    startup_penalty = min(1.0, caps.startup_delay_s / 30.0)
    score = base + response_bonus - cooldown_penalty - startup_penalty
    return round(max(0.0, min(10.0, score)), 1)


def get_throttle_caps(plugin: object) -> ThrottleCaps | None:
    """Safely extract ThrottleCaps from a plugin, returning None if unavailable."""
    if hasattr(plugin, "throttle_capabilities"):
        return plugin.throttle_capabilities
    return None


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
    async def write_power_limit(self, enable: bool, limit_pct: float, *, force: bool = False) -> WriteResult:
        """Write power limit to the inverter.

        Args:
            enable: True to enable dynamic power control, False to disable
            limit_pct: Power limit as float percentage (0.0-100.0)

        Returns:
            WriteResult with success/error status
        """

    @abstractmethod
    async def reconfigure(self, host: str, port: int, unit_id: int) -> None:
        """Reconfigure connection parameters for hot-reload.

        Closes existing connection and updates host/port/unit_id.
        Does NOT reconnect -- the poll loop's ConnectionManager handles that.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up connection resources."""

    @property
    @abstractmethod
    def throttle_capabilities(self) -> ThrottleCaps:
        """Declare this device's throttle capabilities."""
