"""Static SunSpec model chain builder.

Builds the initial 177-register datablock representing the proxy's SunSpec
model chain (addresses 40000-40176), and provides translation functions for
the Common Model identity substitution.

Layout: SunSpec Header + Common (Model 1) + Inverter (Model 103) +
        Nameplate (Model 120) + Controls (Model 123) + End Marker
"""
from __future__ import annotations

import struct

# Address constants (also used by other modules)
SUNSPEC_HEADER_ADDR = 40000
COMMON_ADDR = 40002
INVERTER_ADDR = 40069
NAMEPLATE_ADDR = 40121
CONTROLS_ADDR = 40149
END_ADDR = 40175
TOTAL_REGISTERS = 177  # 40000-40176 inclusive

# pymodbus datablock start (address + 1 due to internal offset)
DATABLOCK_START = 40001

# Model identifiers and lengths
COMMON_DID = 1
COMMON_LENGTH = 65
INVERTER_DID = 103
INVERTER_LENGTH = 50
NAMEPLATE_DID = 120
NAMEPLATE_LENGTH = 26
CONTROLS_DID = 123
CONTROLS_LENGTH = 24

PROXY_UNIT_ID = 126


def encode_string(text: str, num_registers: int) -> list[int]:
    """Encode ASCII string into uint16 register list, null-padded."""
    raw = text.encode("ascii").ljust(num_registers * 2, b"\x00")
    return [int.from_bytes(raw[i:i+2], "big") for i in range(0, num_registers * 2, 2)]


def _int16_as_uint16(value: int) -> int:
    """Convert signed int16 to unsigned uint16 for register storage."""
    return struct.unpack(">H", struct.pack(">h", value))[0]


def build_initial_registers() -> list[int]:
    """Build the full 177-register initial datablock.

    Addresses 40000-40176. Static values for: SunSpec header, Common identity,
    Model 120 Nameplate, Model 123 Controls header, End marker.
    Model 103 data (indices 71-120) initialized to zero, updated by poller.
    """
    regs = [0] * TOTAL_REGISTERS

    # SunSpec Header (40000-40001): "SunS"
    regs[0] = 0x5375  # "Su"
    regs[1] = 0x6E53  # "nS"

    # Common Model DID and Length (40002-40003)
    regs[2] = COMMON_DID     # 1
    regs[3] = COMMON_LENGTH  # 65

    # C_Manufacturer "Fronius" (40004-40019, 16 registers)
    regs[4:20] = encode_string("Fronius", 16)

    # C_Options (40036-40043) -- empty/null padded
    regs[36:44] = encode_string("", 8)

    # C_DeviceAddress (40068) = 126
    regs[68] = PROXY_UNIT_ID

    # Model 103 DID and Length (40069-40070) -- static header
    regs[69] = INVERTER_DID     # 103
    regs[70] = INVERTER_LENGTH  # 50
    # Registers 40071-40120 (indices 71-120) = zeros until first poll

    # Model 120 Nameplate (40121-40148) -- fully synthesized from SE30K specs
    regs[121] = NAMEPLATE_DID     # 120
    regs[122] = NAMEPLATE_LENGTH  # 26
    regs[123] = 4       # DERTyp = PV
    regs[124] = 30000   # WRtg = 30kW
    regs[125] = 0       # WRtg_SF
    regs[126] = 30000   # VARtg = 30kVA
    regs[127] = 0       # VARtg_SF
    regs[128] = 18000   # VArRtgQ1
    regs[129] = 18000   # VArRtgQ2
    regs[130] = _int16_as_uint16(-18000)  # VArRtgQ3
    regs[131] = _int16_as_uint16(-18000)  # VArRtgQ4
    regs[132] = 0       # VArRtg_SF
    regs[133] = 44      # ARtg = 44A
    regs[134] = 0       # ARtg_SF
    regs[135] = 100     # PFRtgQ1 = 1.00 (with SF -2)
    regs[136] = 100     # PFRtgQ2
    regs[137] = _int16_as_uint16(-100)   # PFRtgQ3
    regs[138] = _int16_as_uint16(-100)   # PFRtgQ4
    regs[139] = _int16_as_uint16(-2)     # PFRtg_SF
    # 40140-40148 = zeros (storage ratings N/A, padding)

    # Model 123 Immediate Controls (40149-40174)
    regs[149] = CONTROLS_DID     # 123
    regs[150] = CONTROLS_LENGTH  # 24
    # [151] Conn_WinTms = 0
    # [152] Conn_RvrtTms = 0
    # [153] Conn = 0
    # [154] WMaxLimPct = 100 (= 100% with SF 0)
    regs[154] = 100
    # [155] WMaxLimPct_WinTms = 0
    # [156] WMaxLimPct_RvrtTms = 0
    # [157] WMaxLimPct_RmpTms = 0
    # [158] WMaxLimPct_SF = 0 (Venus OS ignores SF, always writes plain integer %)
    regs[158] = 0
    # [159] WMaxLim_Ena = 0 (Venus OS sets this when it wants to control)

    # End Marker (40175-40176)
    regs[175] = 0xFFFF
    regs[176] = 0x0000

    return regs


def apply_common_translation(se_common_regs: list[int]) -> list[int]:
    """Translate SE30K Common Model registers for proxy serving.

    Input: 67 registers from SE30K (DID + Length + 65 data fields)
    Output: 67 registers with Fronius identity substituted

    Replaced: C_Manufacturer -> "Fronius", C_DeviceAddress -> 126
    Passthrough: C_Model (offset 18-33), C_Version (offset 42-49),
                 C_SerialNumber (offset 50-65)
    """
    translated = list(se_common_regs)

    # Enforce DID and Length
    translated[0] = COMMON_DID     # 1
    translated[1] = COMMON_LENGTH  # 65

    # Replace C_Manufacturer (offset 2-17, 16 registers)
    translated[2:18] = encode_string("Fronius", 16)

    # Replace C_DeviceAddress (offset 66)
    translated[66] = PROXY_UNIT_ID  # 126

    return translated
