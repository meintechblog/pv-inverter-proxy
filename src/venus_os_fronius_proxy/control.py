"""Control state, validation, and SunSpec-to-SolarEdge translation.

Manages the Model 123 Immediate Controls write path:
- Validates WMaxLimPct values before forwarding to inverter
- Translates SunSpec integer+SF encoding to SolarEdge Float32
- Tracks control state for readback by Venus OS

Constants reference SolarEdge SE30K proprietary registers
(0xF300-0xF322) used for dynamic power control.
"""
from __future__ import annotations

import struct

from venus_os_fronius_proxy.sunspec_models import CONTROLS_ADDR, CONTROLS_DID, CONTROLS_LENGTH

# Model 123 address range in proxy register space
MODEL_123_START = CONTROLS_ADDR      # 40149
MODEL_123_END = CONTROLS_ADDR + 2 + CONTROLS_LENGTH - 1  # 40174

# Register offsets within Model 123 (relative to DID register)
WMAXLIMPCT_OFFSET = 5    # Register 40154 = 40149 + 5
WMAXLIM_ENA_OFFSET = 9   # Register 40158 = 40149 + 9

# Scale factor for WMaxLimPct (hardcoded per SunSpec standard)
WMAXLIMPCT_SF = -2

# SolarEdge proprietary control registers
SE_ENABLE_REG = 0xF300        # 62208 - Enable Dynamic Power Control
SE_POWER_LIMIT_REG = 0xF322   # 62242 - Dynamic Active Power Limit (Float32)
SE_CMD_TIMEOUT_REG = 0xF310   # 62224 - Command Timeout (uint32)

# SunSpec NaN encoding for uint16
_SUNSPEC_NAN_UINT16 = 0x7FC0


def validate_wmaxlimpct(raw_value: int, scale_factor: int = WMAXLIMPCT_SF) -> str | None:
    """Validate a WMaxLimPct raw value before forwarding to inverter.

    Args:
        raw_value: SunSpec integer register value
        scale_factor: SunSpec scale factor (default -2)

    Returns:
        None if valid, error string if invalid.
    """
    # Check for SunSpec NaN encoding
    if raw_value == _SUNSPEC_NAN_UINT16:
        return "Invalid value: NaN encoding (0x7FC0)"

    float_pct = raw_value * (10 ** scale_factor)

    if float_pct < 0:
        return f"Invalid value: negative ({float_pct}%)"

    if float_pct > 100:
        return f"Invalid value: exceeds 100% ({float_pct}%)"

    return None


def wmaxlimpct_to_se_registers(raw_value: int, scale_factor: int = WMAXLIMPCT_SF) -> tuple[int, int]:
    """Translate SunSpec WMaxLimPct to SolarEdge Float32 register pair.

    Converts SunSpec integer+SF encoding to IEEE 754 Float32 big-endian,
    split into two uint16 registers for Modbus write to 0xF322-0xF323.

    Args:
        raw_value: SunSpec integer register value
        scale_factor: SunSpec scale factor (default -2)

    Returns:
        Tuple of (hi_register, lo_register) encoding Float32.
    """
    float_pct = raw_value * (10 ** scale_factor)
    packed = struct.pack(">f", float_pct)
    return struct.unpack(">HH", packed)


class ControlState:
    """Tracks Model 123 control state for the proxy.

    Stores the last-written WMaxLimPct and WMaxLim_Ena values,
    provides readback as a complete Model 123 register block.
    WMaxLim_Ena defaults to DISABLED (0) on startup.
    """

    def __init__(self) -> None:
        self.wmaxlim_ena: int = 0
        self.wmaxlimpct_raw: int = 0
        self.scale_factor: int = WMAXLIMPCT_SF

    @property
    def is_enabled(self) -> bool:
        """Whether power limiting is currently enabled."""
        return self.wmaxlim_ena == 1

    @property
    def wmaxlimpct_float(self) -> float:
        """Current power limit as float percentage."""
        return self.wmaxlimpct_raw * (10 ** self.scale_factor)

    def update_wmaxlimpct(self, raw_value: int) -> None:
        """Store a new WMaxLimPct raw value."""
        self.wmaxlimpct_raw = raw_value

    def update_wmaxlim_ena(self, value: int) -> None:
        """Store a new WMaxLim_Ena value (0 or 1)."""
        self.wmaxlim_ena = value

    def get_model_123_readback(self) -> list[int]:
        """Return 26 uint16 registers representing the full Model 123 block.

        Layout: DID=123 at [0], Length=24 at [1], WMaxLimPct at [5],
        WMaxLim_Ena at [9]. All other fields zero.
        """
        regs = [0] * 26
        regs[0] = CONTROLS_DID      # 123
        regs[1] = CONTROLS_LENGTH   # 24
        regs[WMAXLIMPCT_OFFSET] = self.wmaxlimpct_raw
        regs[WMAXLIM_ENA_OFFSET] = self.wmaxlim_ena
        return regs

    def is_model_123_address(self, address: int, count: int) -> bool:
        """Check if an address range overlaps Model 123 registers.

        Args:
            address: Absolute SunSpec address (e.g. 40154)
            count: Number of registers

        Returns:
            True if any register in [address, address+count) overlaps
            [MODEL_123_START, MODEL_123_END].
        """
        return address <= MODEL_123_END and (address + count - 1) >= MODEL_123_START
