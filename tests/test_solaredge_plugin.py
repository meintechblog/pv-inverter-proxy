"""Tests for SolarEdge SE30K plugin."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pv_inverter_proxy.plugin import InverterPlugin, PollResult
from pv_inverter_proxy.plugins.solaredge import (
    SolarEdgePlugin,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    COMMON_READ_ADDR,
    COMMON_READ_COUNT,
    INVERTER_READ_ADDR,
    INVERTER_READ_COUNT,
)
from pv_inverter_proxy.sunspec_models import PROXY_UNIT_ID


def _make_mock_response(registers, is_error=False):
    """Create a mock Modbus response."""
    resp = MagicMock()
    resp.isError.return_value = is_error
    resp.registers = registers
    return resp


# Sample register data for tests
SAMPLE_COMMON = list(range(67))   # 67 registers
SAMPLE_INVERTER = list(range(52)) # 52 registers


class TestPluginInterface:
    def test_plugin_interface(self):
        """SolarEdgePlugin is a subclass of InverterPlugin."""
        assert issubclass(SolarEdgePlugin, InverterPlugin)

    def test_plugin_instance(self):
        """SolarEdgePlugin can be instantiated."""
        plugin = SolarEdgePlugin()
        assert isinstance(plugin, InverterPlugin)


class TestConnectionParams:
    def test_plugin_default_connection_params(self):
        """Default connection parameters match SE30K network config."""
        plugin = SolarEdgePlugin()
        assert plugin.host == "192.168.3.18"
        assert plugin.port == 1502
        assert plugin.unit_id == 1

    def test_custom_connection_params(self):
        """Custom connection parameters are stored."""
        plugin = SolarEdgePlugin(host="10.0.0.1", port=502, unit_id=3)
        assert plugin.host == "10.0.0.1"
        assert plugin.port == 502
        assert plugin.unit_id == 3

    def test_default_constants(self):
        """Module-level defaults match expected values."""
        assert DEFAULT_HOST == "192.168.3.18"
        assert DEFAULT_PORT == 1502
        assert DEFAULT_UNIT_ID == 1


class TestPoll:
    @pytest.mark.asyncio
    async def test_poll_reads_registers(self):
        """poll() reads Common (67) and Inverter (52) registers and returns PollResult."""
        plugin = SolarEdgePlugin()
        mock_client = AsyncMock()
        mock_client.connected = True

        common_resp = _make_mock_response(SAMPLE_COMMON)
        inverter_resp = _make_mock_response(SAMPLE_INVERTER)
        mock_client.read_holding_registers = AsyncMock(
            side_effect=[common_resp, inverter_resp]
        )

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is True
        assert result.error is None
        assert result.common_registers == SAMPLE_COMMON
        assert result.inverter_registers == SAMPLE_INVERTER
        assert len(result.common_registers) == 67
        assert len(result.inverter_registers) == 52

        # Verify correct addresses and counts
        calls = mock_client.read_holding_registers.call_args_list
        assert calls[0].args == (COMMON_READ_ADDR,)
        assert calls[0].kwargs["count"] == COMMON_READ_COUNT
        assert calls[0].kwargs["device_id"] == 1
        assert calls[1].args == (INVERTER_READ_ADDR,)
        assert calls[1].kwargs["count"] == INVERTER_READ_COUNT
        assert calls[1].kwargs["device_id"] == 1

    @pytest.mark.asyncio
    async def test_poll_handles_read_error(self):
        """poll() returns PollResult(success=False) on Modbus read error."""
        plugin = SolarEdgePlugin()
        mock_client = AsyncMock()
        mock_client.connected = True

        error_resp = _make_mock_response([], is_error=True)
        mock_client.read_holding_registers = AsyncMock(return_value=error_resp)

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is False
        assert result.error is not None
        assert result.common_registers == []
        assert result.inverter_registers == []

    @pytest.mark.asyncio
    async def test_poll_handles_inverter_read_error(self):
        """poll() returns failure when inverter read errors but common succeeds."""
        plugin = SolarEdgePlugin()
        mock_client = AsyncMock()
        mock_client.connected = True

        common_resp = _make_mock_response(SAMPLE_COMMON)
        inverter_err = _make_mock_response([], is_error=True)
        mock_client.read_holding_registers = AsyncMock(
            side_effect=[common_resp, inverter_err]
        )

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is False
        assert "Inverter read error" in result.error

    @pytest.mark.asyncio
    async def test_poll_handles_exception(self):
        """poll() returns PollResult(success=False) on ConnectionError without raising."""
        plugin = SolarEdgePlugin()
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.read_holding_registers = AsyncMock(
            side_effect=ConnectionError("Connection lost")
        )

        plugin._client = mock_client
        result = await plugin.poll()

        assert result.success is False
        assert "Connection lost" in result.error

    @pytest.mark.asyncio
    async def test_poll_not_connected(self):
        """poll() before connect() returns PollResult(success=False)."""
        plugin = SolarEdgePlugin()
        result = await plugin.poll()

        assert result.success is False
        assert result.error == "Not connected"


class TestStaticOverrides:
    def test_get_static_common_overrides(self):
        """get_static_common_overrides() returns Fronius identity and unit ID 126."""
        plugin = SolarEdgePlugin()
        overrides = plugin.get_static_common_overrides()

        # DID and Length
        assert overrides[0] == 1   # COMMON_DID
        assert overrides[1] == 65  # COMMON_LENGTH

        # Manufacturer "Fronius" at offsets 2-17
        assert 2 in overrides
        assert 17 in overrides

        # C_DeviceAddress at offset 66
        assert overrides[66] == PROXY_UNIT_ID  # 126

    def test_fronius_manufacturer_encoding(self):
        """Manufacturer override encodes 'Fronius' correctly."""
        plugin = SolarEdgePlugin()
        overrides = plugin.get_static_common_overrides()

        # First register of manufacturer: "Fr" = 0x4672
        assert overrides[2] == 0x4672

        # "on" = 0x6F6E
        assert overrides[3] == 0x6F6E


class TestModel120:
    def test_get_model_120_registers(self):
        """get_model_120_registers() returns 28-element list with correct header."""
        plugin = SolarEdgePlugin()
        regs = plugin.get_model_120_registers()

        assert len(regs) == 28
        assert regs[0] == 120   # NAMEPLATE_DID
        assert regs[1] == 26    # NAMEPLATE_LENGTH
        assert regs[2] == 4     # DERTyp = PV
        assert regs[3] == 30000 # WRtg = 30kW

    def test_model_120_nameplate_values(self):
        """Model 120 contains SE30K nameplate ratings."""
        plugin = SolarEdgePlugin()
        regs = plugin.get_model_120_registers()

        assert regs[5] == 30000  # VARtg = 30kVA
        assert regs[12] == 44    # ARtg = 44A


class TestMappingInPlugin:
    def test_mapping_in_plugin(self):
        """Register mapping data is in the plugin, not in proxy core.

        The plugin provides get_model_120_registers() and
        get_static_common_overrides() -- these are the mapping concerns.
        The proxy core should only know about the datablock.
        """
        plugin = SolarEdgePlugin()

        # Model 120 registers are fully defined in the plugin
        model_120 = plugin.get_model_120_registers()
        assert len(model_120) == 28
        assert model_120[0] == 120

        # Static overrides are fully defined in the plugin
        overrides = plugin.get_static_common_overrides()
        assert isinstance(overrides, dict)
        assert len(overrides) > 0

        # These methods are defined on InverterPlugin ABC
        assert hasattr(InverterPlugin, 'get_model_120_registers')
        assert hasattr(InverterPlugin, 'get_static_common_overrides')


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_client(self):
        """connect() creates AsyncModbusTcpClient and connects."""
        plugin = SolarEdgePlugin()
        with patch(
            "pv_inverter_proxy.plugins.solaredge.AsyncModbusTcpClient"
        ) as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            await plugin.connect()

            MockClient.assert_called_once_with(
                DEFAULT_HOST, port=DEFAULT_PORT, timeout=2, retries=1,
            )
            mock_instance.connect.assert_awaited_once()
            assert plugin._client is mock_instance

    @pytest.mark.asyncio
    async def test_close_disconnects(self):
        """close() disconnects the client."""
        plugin = SolarEdgePlugin()
        mock_client = MagicMock()
        plugin._client = mock_client

        await plugin.close()

        mock_client.close.assert_called_once()
