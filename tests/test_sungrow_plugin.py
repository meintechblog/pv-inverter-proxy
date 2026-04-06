"""Tests for Sungrow SG-RT plugin."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pv_inverter_proxy.plugin import InverterPlugin, PollResult, ThrottleCaps
from pv_inverter_proxy.plugins.sungrow import (
    SungrowPlugin,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    SUNGROW_INPUT_REG_START,
    SUNGROW_INPUT_REG_COUNT,
    SUNGROW_STATE_TO_SUNSPEC,
)
from pv_inverter_proxy.sunspec_models import PROXY_UNIT_ID


def _make_mock_response(registers, is_error=False):
    """Create a mock Modbus response."""
    resp = MagicMock()
    resp.isError.return_value = is_error
    resp.registers = registers
    return resp


def _make_sample_sungrow_registers() -> list[int]:
    """Build 36-element list representing wire addresses 5002-5037.

    Offsets relative to raw[0] = wire 5002:
      raw[1]=100, raw[2]=0 -> total energy = (100<<16|0)*100 = 655360000 Wh (= 655360 kWh)
      raw[5]=350 -> temperature = 35.0 degC (signed)
      raw[8]=2300 -> DC1 voltage = 230.0V
      raw[9]=45 -> DC1 current = 4.5A
      raw[10]=2310 -> DC2 voltage = 231.0V
      raw[11]=42 -> DC2 current = 4.2A
      raw[14]=0, raw[15]=4000 -> total DC power = (0<<16|4000) = 4000W
      raw[16]=2310 -> phase A voltage = 231.0V
      raw[17]=2320 -> phase B voltage = 232.0V
      raw[18]=2305 -> phase C voltage = 230.5V
      raw[19]=58 -> phase A current = 5.8A
      raw[20]=57 -> phase B current = 5.7A
      raw[21]=59 -> phase C current = 5.9A
      raw[28]=0, raw[29]=3900 -> total active power = (0<<16|3900) = 3900W
      raw[32]=998 -> power factor = 0.998
      raw[33]=500 -> frequency = 50.0 Hz
      raw[35]=0x8000 -> running state = Run
    """
    raw = [0] * 36
    raw[1] = 100      # total energy high word
    raw[2] = 0        # total energy low word
    raw[5] = 350      # temperature (0.1 degC)
    raw[8] = 2300     # DC1 voltage (0.1V)
    raw[9] = 45       # DC1 current (0.1A)
    raw[10] = 2310    # DC2 voltage (0.1V)
    raw[11] = 42      # DC2 current (0.1A)
    raw[14] = 0       # total DC power high word (U32: high<<16|low = 4000W)
    raw[15] = 4000    # total DC power low word
    raw[16] = 2310    # phase A voltage (0.1V)
    raw[17] = 2320    # phase B voltage (0.1V)
    raw[18] = 2305    # phase C voltage (0.1V)
    raw[19] = 58      # phase A current (0.1A)
    raw[20] = 57      # phase B current (0.1A)
    raw[21] = 59      # phase C current (0.1A)
    raw[28] = 0       # total active power high word (U32: high<<16|low = 3900W)
    raw[29] = 3900    # total active power low word
    raw[32] = 998     # power factor
    raw[33] = 500     # frequency (0.1 Hz)
    raw[35] = 0x8000  # running state = Run
    return raw


SAMPLE_SUNGROW = _make_sample_sungrow_registers()


class TestPluginInterface:
    def test_is_subclass(self):
        """SungrowPlugin is a subclass of InverterPlugin."""
        assert issubclass(SungrowPlugin, InverterPlugin)

    def test_can_instantiate(self):
        """SungrowPlugin can be instantiated with host/port/unit_id/rated_power."""
        plugin = SungrowPlugin(host="10.0.0.1", port=502, unit_id=1, rated_power=8000)
        assert isinstance(plugin, InverterPlugin)
        assert plugin.host == "10.0.0.1"
        assert plugin.port == 502
        assert plugin.unit_id == 1
        assert plugin.rated_power == 8000

    def test_default_params(self):
        """Default connection parameters match Sungrow defaults."""
        plugin = SungrowPlugin()
        assert plugin.host == DEFAULT_HOST
        assert plugin.port == DEFAULT_PORT
        assert plugin.unit_id == DEFAULT_UNIT_ID


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_client(self):
        """connect() creates AsyncModbusTcpClient and calls client.connect()."""
        plugin = SungrowPlugin(host="10.0.0.1", port=502)
        with patch(
            "pv_inverter_proxy.plugins.sungrow.AsyncModbusTcpClient"
        ) as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            await plugin.connect()

            MockClient.assert_called_once_with("10.0.0.1", port=502)
            mock_instance.connect.assert_awaited_once()
            assert plugin._client is mock_instance


class TestPoll:
    @pytest.mark.asyncio
    async def test_poll_reads_input_registers(self):
        """poll() calls read_input_registers (FC04) at address 5002 with count=36."""
        plugin = SungrowPlugin(host="10.0.0.1", port=502, unit_id=1, rated_power=8000)
        mock_client = AsyncMock()
        mock_client.connected = True

        resp = _make_mock_response(SAMPLE_SUNGROW)
        mock_client.read_input_registers = AsyncMock(return_value=resp)

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is True
        assert result.error is None
        assert len(result.common_registers) == 67
        assert len(result.inverter_registers) == 52

        # Verify read_input_registers (FC04) called, NOT read_holding_registers
        mock_client.read_input_registers.assert_called_once_with(
            5002, count=36, device_id=1,
        )

    @pytest.mark.asyncio
    async def test_poll_handles_modbus_error(self):
        """poll() returns success=False with error on Modbus read error."""
        plugin = SungrowPlugin()
        mock_client = AsyncMock()
        mock_client.connected = True

        error_resp = _make_mock_response([], is_error=True)
        mock_client.read_input_registers = AsyncMock(return_value=error_resp)

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_poll_handles_exception(self):
        """poll() returns PollResult(success=False) on ConnectionError."""
        plugin = SungrowPlugin()
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.read_input_registers = AsyncMock(
            side_effect=ConnectionError("Connection lost")
        )

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is False
        assert "Connection lost" in result.error

    @pytest.mark.asyncio
    async def test_poll_not_connected(self):
        """poll() before connect() returns PollResult(success=False)."""
        plugin = SungrowPlugin()
        result = await plugin.poll()

        assert result.success is False
        assert result.error == "Not connected"


class TestSungrowParsing:
    """Test _parse_sungrow_data() correctly converts raw registers."""

    def test_parse_energy(self):
        """U32 high-word-first for total energy, converted from 0.1kWh to Wh."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        # (100 << 16 | 0) = 6553600 raw, * 100 (0.1kWh->Wh) = 655360000 Wh
        assert data["total_energy_wh"] == 655360000

    def test_parse_temperature_signed(self):
        """S16 temperature at 0.1 degC resolution."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert abs(data["temperature_c"] - 35.0) < 0.01

    def test_parse_negative_temperature(self):
        """Negative S16 temperature."""
        plugin = SungrowPlugin()
        raw = list(SAMPLE_SUNGROW)
        raw[5] = 0xFFCE  # -50 as unsigned -> -5.0 degC
        data = plugin._parse_sungrow_data(raw)
        assert abs(data["temperature_c"] - (-5.0)) < 0.01

    def test_parse_dc_values(self):
        """DC voltage and current at 0.1 resolution."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert abs(data["dc1_voltage_v"] - 230.0) < 0.01
        assert abs(data["dc1_current_a"] - 4.5) < 0.01
        assert abs(data["dc2_voltage_v"] - 231.0) < 0.01
        assert abs(data["dc2_current_a"] - 4.2) < 0.01

    def test_parse_total_dc_power(self):
        """U32 total DC power."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert data["total_dc_power_w"] == 4000

    def test_parse_ac_voltages(self):
        """Phase voltages at 0.1V resolution."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert abs(data["phase_a_voltage_v"] - 231.0) < 0.01
        assert abs(data["phase_b_voltage_v"] - 232.0) < 0.01
        assert abs(data["phase_c_voltage_v"] - 230.5) < 0.01

    def test_parse_ac_currents(self):
        """Phase currents at 0.1A resolution."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert abs(data["phase_a_current_a"] - 5.8) < 0.01
        assert abs(data["phase_b_current_a"] - 5.7) < 0.01
        assert abs(data["phase_c_current_a"] - 5.9) < 0.01

    def test_parse_total_active_power(self):
        """U32 total active power."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert data["total_active_power_w"] == 3900

    def test_parse_frequency(self):
        """Frequency at 0.1 Hz resolution."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert abs(data["frequency_hz"] - 50.0) < 0.01

    def test_parse_running_state(self):
        """Running state is raw value."""
        plugin = SungrowPlugin()
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        assert data["running_state"] == 0x8000


class TestSunSpecEncoding:
    """Test _encode_model_103() produces correct 52-register SunSpec layout."""

    def _get_encoded(self):
        plugin = SungrowPlugin(rated_power=8000)
        data = plugin._parse_sungrow_data(SAMPLE_SUNGROW)
        return plugin._encode_model_103(data)

    def test_model_103_header(self):
        """regs[0]=103 (DID), regs[1]=50 (Length)."""
        regs = self._get_encoded()
        assert len(regs) == 52
        assert regs[0] == 103
        assert regs[1] == 50

    def test_ac_current_total(self):
        """AC current at regs[2] with SF=-2."""
        regs = self._get_encoded()
        # Total current = 5.8 + 5.7 + 5.9 = 17.4A -> *100 = 1740
        expected = int(round((5.8 + 5.7 + 5.9) * 100))
        assert regs[2] == expected
        assert regs[6] == 0xFFFE  # SF = -2

    def test_ac_current_three_phase(self):
        """All three phases populated (regs[3], regs[4], regs[5] non-zero)."""
        regs = self._get_encoded()
        assert regs[3] != 0  # Phase A current
        assert regs[4] != 0  # Phase B current
        assert regs[5] != 0  # Phase C current
        # Verify individual values
        assert regs[3] == int(round(5.8 * 100))  # 580
        assert regs[4] == int(round(5.7 * 100))  # 570
        assert regs[5] == int(round(5.9 * 100))  # 590

    def test_ac_voltage(self):
        """AC voltage AN at regs[10] with SF=-1."""
        regs = self._get_encoded()
        assert regs[10] == int(round(231.0 * 10))  # 2310
        assert regs[13] == 0xFFFF  # SF = -1

    def test_ac_power(self):
        """AC power at regs[14] with SF=0."""
        regs = self._get_encoded()
        assert regs[14] == 3900  # total active power in W
        assert regs[15] == 0     # SF = 0

    def test_frequency(self):
        """Frequency at regs[16] with SF=-2."""
        regs = self._get_encoded()
        assert regs[16] == int(round(50.0 * 100))  # 5000
        assert regs[17] == 0xFFFE  # SF = -2

    def test_energy_acc32(self):
        """Energy at regs[24-25] as acc32 Wh."""
        regs = self._get_encoded()
        energy_wh = (regs[24] << 16) | regs[25]
        assert energy_wh == 655360000

    def test_dc_values(self):
        """DC current/voltage/power at correct offsets."""
        regs = self._get_encoded()
        # DC current = dc1 + dc2 = 4.5 + 4.2 = 8.7A -> *100 = 870
        assert regs[27] == int(round(8.7 * 100))
        assert regs[28] == 0xFFFE  # DC Current SF = -2
        # DC voltage = dc1 voltage (primary) = 230.0V -> *10 = 2300
        assert regs[29] == int(round(230.0 * 10))
        assert regs[30] == 0xFFFF  # DC Voltage SF = -1
        # DC power = total DC = 4000W
        assert regs[31] == 4000
        assert regs[32] == 0  # DC Power SF = 0

    def test_temperature(self):
        """Temperature at regs[33] with SF=-1."""
        regs = self._get_encoded()
        assert regs[33] == int(round(35.0 * 10))  # 350
        assert regs[37] == 0xFFFF  # SF = -1

    def test_status_running(self):
        """Running state 0x8000 maps to SunSpec 4 (MPPT)."""
        regs = self._get_encoded()
        assert regs[38] == 4  # MPPT


class TestSungrowStateCodes:
    """Test Sungrow running state to SunSpec status mapping."""

    def _encode_with_state(self, state_code):
        plugin = SungrowPlugin()
        raw = list(SAMPLE_SUNGROW)
        raw[35] = state_code
        data = plugin._parse_sungrow_data(raw)
        regs = plugin._encode_model_103(data)
        return regs[38]

    def test_run_to_mppt(self):
        """0x8000 (Run) -> SunSpec 4 (MPPT)."""
        assert self._encode_with_state(0x8000) == 4

    def test_stop_to_off(self):
        """0x0000 (Stop) -> SunSpec 1 (OFF)."""
        assert self._encode_with_state(0x0000) == 1

    def test_standby_to_standby(self):
        """0x1300 (Standby) -> SunSpec 8 (STANDBY)."""
        assert self._encode_with_state(0x1300) == 8

    def test_derating_to_throttled(self):
        """0x8100 (Derating) -> SunSpec 5 (THROTTLED)."""
        assert self._encode_with_state(0x8100) == 5

    def test_fault_to_fault(self):
        """0x5500 (Fault) -> SunSpec 7 (FAULT)."""
        assert self._encode_with_state(0x5500) == 7

    def test_unknown_to_sleeping(self):
        """Unknown state -> SunSpec 2 (SLEEPING)."""
        assert self._encode_with_state(0x9999) == 2


class TestReconfigure:
    @pytest.mark.asyncio
    async def test_reconfigure_updates_params(self):
        """reconfigure() calls close() and updates host/port/unit_id."""
        plugin = SungrowPlugin(host="10.0.0.1", port=502, unit_id=1)
        mock_client = MagicMock()
        plugin._client = mock_client

        await plugin.reconfigure("10.0.0.2", 1502, 3)

        mock_client.close.assert_called_once()
        assert plugin.host == "10.0.0.2"
        assert plugin.port == 1502
        assert plugin.unit_id == 3
        assert plugin._client is None


class TestThrottleCaps:
    def test_throttle_capabilities(self):
        """throttle_capabilities returns proportional mode with 2.0s response."""
        plugin = SungrowPlugin()
        caps = plugin.throttle_capabilities
        assert isinstance(caps, ThrottleCaps)
        assert caps.mode == "proportional"
        assert caps.response_time_s == 2.0
        assert caps.cooldown_s == 0.0
        assert caps.startup_delay_s == 0.0


class TestWritePowerLimit:
    @pytest.mark.asyncio
    async def test_write_power_limit_noop(self):
        """write_power_limit() returns WriteResult(success=True) as no-op."""
        plugin = SungrowPlugin()
        result = await plugin.write_power_limit(enable=True, limit_pct=50.0)
        assert result.success is True
        assert result.error is None


class TestCommonRegisters:
    def test_build_common_registers(self):
        """_build_common_registers() returns 67 registers with correct identity."""
        plugin = SungrowPlugin()
        regs = plugin._build_common_registers()
        assert len(regs) == 67
        assert regs[0] == 1   # COMMON_DID
        assert regs[1] == 65  # COMMON_LENGTH
        assert regs[66] == PROXY_UNIT_ID  # 126

    def test_manufacturer_sungrow(self):
        """Manufacturer field contains 'Sungrow'."""
        plugin = SungrowPlugin()
        regs = plugin._build_common_registers()
        # First register of manufacturer: "Su" = 0x5375
        assert regs[2] == 0x5375


class TestModel120:
    def test_model_120_registers(self):
        """get_model_120_registers() returns 28 registers with correct header."""
        plugin = SungrowPlugin(rated_power=8000)
        regs = plugin.get_model_120_registers()
        assert len(regs) == 28
        assert regs[0] == 120   # NAMEPLATE_DID
        assert regs[1] == 26    # NAMEPLATE_LENGTH
        assert regs[2] == 4     # DERTyp = PV
        assert regs[3] == 8000  # WRtg = rated_power
