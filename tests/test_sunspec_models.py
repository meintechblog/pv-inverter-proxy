"""Tests for SunSpec static model chain builder.

Verifies that build_initial_registers() produces the correct 177-register
layout matching the register-mapping-spec.md, and that apply_common_translation()
correctly substitutes Fronius identity while preserving passthrough fields.
"""
import struct

import pytest


class TestEncodeString:
    """Verify encode_string helper."""

    def test_encode_fronius_16_registers(self):
        from venus_os_fronius_proxy.sunspec_models import encode_string
        result = encode_string("Fronius", 16)
        assert len(result) == 16
        # First 4 registers: "Fr", "on", "iu", "s\0"
        assert result[0] == 0x4672
        assert result[1] == 0x6F6E
        assert result[2] == 0x6975
        assert result[3] == 0x7300
        # Remaining 12 are null
        assert result[4:] == [0x0000] * 12

    def test_encode_empty_string(self):
        from venus_os_fronius_proxy.sunspec_models import encode_string
        result = encode_string("", 8)
        assert len(result) == 8
        assert all(v == 0 for v in result)


class TestBuildInitialRegisters:
    """Verify build_initial_registers() produces correct 177-register layout."""

    def test_returns_177_items(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert len(regs) == 177

    def test_sunspec_header(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[0] == 0x5375  # "Su"
        assert regs[1] == 0x6E53  # "nS"

    def test_common_did_and_length(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[2] == 1   # Common DID
        assert regs[3] == 65  # Common Length

    def test_manufacturer_fronius(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers, encode_string
        regs = build_initial_registers()
        assert regs[4:20] == encode_string("Fronius", 16)

    def test_unit_id_126(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[68] == 126

    def test_model_103_header(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[69] == 103  # Inverter DID
        assert regs[70] == 50   # Inverter Length

    def test_model_120_did_and_length(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[121] == 120  # Nameplate DID
        assert regs[122] == 26   # Nameplate Length

    def test_model_120_dertyp(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[123] == 4  # DERTyp = PV

    def test_model_120_wrtg(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[124] == 30000  # WRtg
        assert regs[125] == 0      # WRtg_SF

    def test_model_120_vartg_q3_negative(self):
        """VArRtgQ3 = -18000 stored as uint16."""
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        expected = struct.unpack(">H", struct.pack(">h", -18000))[0]
        assert regs[130] == expected

    def test_model_120_pf_rtg_sf_negative(self):
        """PFRtg_SF = -2 stored as uint16."""
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        expected = struct.unpack(">H", struct.pack(">h", -2))[0]
        assert regs[139] == expected

    def test_model_123_header(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[149] == 123  # Controls DID
        assert regs[150] == 24   # Controls Length

    def test_end_marker(self):
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert regs[175] == 0xFFFF
        assert regs[176] == 0x0000

    def test_model_103_data_initialized_to_zero(self):
        """Model 103 data registers (indices 71-120) should be zeros initially."""
        from venus_os_fronius_proxy.sunspec_models import build_initial_registers
        regs = build_initial_registers()
        assert all(v == 0 for v in regs[71:121])


class TestApplyCommonTranslation:
    """Verify apply_common_translation() replaces identity while preserving passthrough."""

    def test_replaces_manufacturer(self):
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation, encode_string
        # Create fake SE30K common registers (67 values)
        se_regs = [0] * 67
        se_regs[0] = 1   # DID
        se_regs[1] = 65  # Length
        # SE manufacturer "SolarEdge"
        se_regs[2:18] = encode_string("SolarEdge", 16)

        translated = apply_common_translation(se_regs)
        assert translated[2:18] == encode_string("Fronius", 16)

    def test_replaces_device_address(self):
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation
        se_regs = [0] * 67
        se_regs[66] = 1  # SE unit ID

        translated = apply_common_translation(se_regs)
        assert translated[66] == 126

    def test_preserves_model_passthrough(self):
        """C_Model (offset 18-33) should pass through unchanged."""
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation, encode_string
        se_regs = [0] * 67
        se_regs[18:34] = encode_string("SE30K", 16)

        translated = apply_common_translation(se_regs)
        assert translated[18:34] == encode_string("SE30K", 16)

    def test_preserves_version_passthrough(self):
        """C_Version (offset 42-49) should pass through unchanged."""
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation, encode_string
        se_regs = [0] * 67
        se_regs[42:50] = encode_string("1.2.3", 8)

        translated = apply_common_translation(se_regs)
        assert translated[42:50] == encode_string("1.2.3", 8)

    def test_preserves_serial_passthrough(self):
        """C_SerialNumber (offset 50-65) should pass through unchanged."""
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation, encode_string
        se_regs = [0] * 67
        se_regs[50:66] = encode_string("SN12345", 16)

        translated = apply_common_translation(se_regs)
        assert translated[50:66] == encode_string("SN12345", 16)

    def test_enforces_did_and_length(self):
        from venus_os_fronius_proxy.sunspec_models import apply_common_translation
        se_regs = [0] * 67
        se_regs[0] = 99   # wrong DID
        se_regs[1] = 99   # wrong length

        translated = apply_common_translation(se_regs)
        assert translated[0] == 1
        assert translated[1] == 65


class TestNegativeInt16Encoding:
    """Verify negative int16 values round-trip correctly through uint16 encoding."""

    def test_negative_18000_roundtrip(self):
        from venus_os_fronius_proxy.sunspec_models import _int16_as_uint16
        uint_val = _int16_as_uint16(-18000)
        # Convert back
        signed_val = struct.unpack(">h", struct.pack(">H", uint_val))[0]
        assert signed_val == -18000

    def test_negative_100_roundtrip(self):
        from venus_os_fronius_proxy.sunspec_models import _int16_as_uint16
        uint_val = _int16_as_uint16(-100)
        signed_val = struct.unpack(">h", struct.pack(">H", uint_val))[0]
        assert signed_val == -100

    def test_negative_2_roundtrip(self):
        from venus_os_fronius_proxy.sunspec_models import _int16_as_uint16
        uint_val = _int16_as_uint16(-2)
        signed_val = struct.unpack(">h", struct.pack(">H", uint_val))[0]
        assert signed_val == -2


class TestConstants:
    """Verify key constants are exported."""

    def test_datablock_start(self):
        from venus_os_fronius_proxy.sunspec_models import DATABLOCK_START
        assert DATABLOCK_START == 40001

    def test_total_registers(self):
        from venus_os_fronius_proxy.sunspec_models import TOTAL_REGISTERS
        assert TOTAL_REGISTERS == 177

    def test_proxy_unit_id(self):
        from venus_os_fronius_proxy.sunspec_models import PROXY_UNIT_ID
        assert PROXY_UNIT_ID == 126
