"""Tests for the OpenDTU plugin (Hoymiles micro-inverters via REST API).

Covers requirements DTU-01 through DTU-05:
- DTU-01: Poll OpenDTU REST API, translate JSON to SunSpec registers
- DTU-02: Serial-based filtering for multi-inverter gateways
- DTU-03: Power limit via POST /api/limit/config with Basic Auth
- DTU-04: Implements all InverterPlugin ABC methods
- DTU-05: Dead-time guard suppresses re-sends for 30s
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import aiohttp
import pytest

from venus_os_fronius_proxy.plugins.opendtu import OpenDTUPlugin
from venus_os_fronius_proxy.plugin import InverterPlugin, PollResult, WriteResult
from venus_os_fronius_proxy.config import GatewayConfig
from venus_os_fronius_proxy.sunspec_models import _int16_as_uint16


# --- Sample OpenDTU API response ---

SAMPLE_LIVEDATA = {
    "inverters": [
        {
            "serial": "112183818450",
            "name": "Spielturm",
            "data_age": 4,
            "reachable": True,
            "producing": True,
            "limit_relative": 100.0,
            "limit_absolute": 400.0,
            "AC": {"0": {
                "Power": {"v": 285.3, "u": "W", "d": 1},
                "Voltage": {"v": 230.1, "u": "V", "d": 1},
                "Current": {"v": 1.24, "u": "A", "d": 2},
                "Frequency": {"v": 50.01, "u": "Hz", "d": 2},
            }},
            "DC": {
                "0": {
                    "Power": {"v": 145.2, "u": "W", "d": 1},
                    "Voltage": {"v": 32.1, "u": "V", "d": 1},
                    "Current": {"v": 4.52, "u": "A", "d": 2},
                    "YieldTotal": {"v": 1234.567, "u": "kWh", "d": 3},
                    "YieldDay": {"v": 1.23, "u": "kWh", "d": 3},
                },
                "1": {
                    "Power": {"v": 140.0, "u": "W", "d": 1},
                    "Voltage": {"v": 31.5, "u": "V", "d": 1},
                    "Current": {"v": 4.44, "u": "A", "d": 2},
                    "YieldTotal": {"v": 1100.0, "u": "kWh", "d": 3},
                    "YieldDay": {"v": 1.10, "u": "kWh", "d": 3},
                },
            },
            "INV": {"0": {"Temperature": {"v": 35.2, "u": "\u00b0C", "d": 1}}},
        },
        {
            "serial": "114182600464",
            "name": "Balkon",
            "data_age": 3,
            "reachable": True,
            "producing": True,
            "limit_relative": 100.0,
            "limit_absolute": 600.0,
            "AC": {"0": {
                "Power": {"v": 410.0, "u": "W", "d": 1},
                "Voltage": {"v": 229.8, "u": "V", "d": 1},
                "Current": {"v": 1.78, "u": "A", "d": 2},
                "Frequency": {"v": 50.00, "u": "Hz", "d": 2},
            }},
            "DC": {
                "0": {
                    "Power": {"v": 210.0, "u": "W", "d": 1},
                    "Voltage": {"v": 33.0, "u": "V", "d": 1},
                    "Current": {"v": 6.36, "u": "A", "d": 2},
                    "YieldTotal": {"v": 2500.0, "u": "kWh", "d": 3},
                    "YieldDay": {"v": 2.50, "u": "kWh", "d": 3},
                },
                "1": {
                    "Power": {"v": 200.0, "u": "W", "d": 1},
                    "Voltage": {"v": 32.5, "u": "V", "d": 1},
                    "Current": {"v": 6.15, "u": "A", "d": 2},
                    "YieldTotal": {"v": 2400.0, "u": "kWh", "d": 3},
                    "YieldDay": {"v": 2.40, "u": "kWh", "d": 3},
                },
            },
            "INV": {"0": {"Temperature": {"v": 33.0, "u": "\u00b0C", "d": 1}}},
        },
    ],
    "total": {},
    "hints": {"time_sync": False, "radio_problem": False, "default_password": True},
}


# --- Helpers ---

def _make_gateway(host: str = "192.168.3.98") -> GatewayConfig:
    return GatewayConfig(host=host, user="admin", password="openDTU42")


def _make_plugin(serial: str = "112183818450", name: str = "Spielturm") -> OpenDTUPlugin:
    return OpenDTUPlugin(
        gateway_config=_make_gateway(),
        serial=serial,
        name=name,
    )


def _mock_session(json_response=None, raise_error=None):
    """Create a mock aiohttp.ClientSession that returns json_response on GET."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=json_response or SAMPLE_LIVEDATA)

    # session.get() returns an async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_response)
    cm.__aexit__ = AsyncMock(return_value=False)

    if raise_error:
        cm.__aenter__.side_effect = raise_error

    session.get.return_value = cm

    # session.post() returns an async context manager
    post_response = AsyncMock()
    post_response.status = 200
    post_response.json = AsyncMock(return_value={"type": "success"})
    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=post_response)
    post_cm.__aexit__ = AsyncMock(return_value=False)
    session.post.return_value = post_cm

    # closed property
    type(session).closed = PropertyMock(return_value=False)

    return session


# --- Tests ---

class TestABCCompliance:
    """DTU-04: Plugin implements all InverterPlugin ABC methods."""

    def test_abc_compliance(self):
        plugin = _make_plugin()
        assert isinstance(plugin, InverterPlugin)

    def test_all_abstract_methods_implemented(self):
        """All 7 abstract methods must be present."""
        plugin = _make_plugin()
        assert hasattr(plugin, "connect")
        assert hasattr(plugin, "poll")
        assert hasattr(plugin, "get_static_common_overrides")
        assert hasattr(plugin, "get_model_120_registers")
        assert hasattr(plugin, "write_power_limit")
        assert hasattr(plugin, "reconfigure")
        assert hasattr(plugin, "close")


class TestPollSuccess:
    """DTU-01: Poll OpenDTU REST API and translate JSON to SunSpec registers."""

    @pytest.mark.asyncio
    async def test_poll_success(self):
        """Given valid JSON for serial 112183818450 producing 285.3W,
        poll() returns PollResult(success=True) with correct AC power register."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.success is True
        assert result.error is None
        assert len(result.common_registers) == 67
        assert len(result.inverter_registers) == 52
        # AC Power at offset 14, SF=0 -> 285W (rounded from 285.3)
        assert result.inverter_registers[14] == 285
        # AC Power SF at offset 15 = 0
        assert result.inverter_registers[15] == 0

    @pytest.mark.asyncio
    async def test_poll_serial_filter(self):
        """DTU-02: Given 2 inverters, plugin for serial A only sees serial A data."""
        plugin = _make_plugin(serial="112183818450")
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.success is True
        # Should see 285W (Spielturm), not 410W (Balkon)
        assert result.inverter_registers[14] == 285

    @pytest.mark.asyncio
    async def test_poll_other_serial(self):
        """Plugin for second serial sees second inverter data."""
        plugin = _make_plugin(serial="114182600464", name="Balkon")
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.success is True
        assert result.inverter_registers[14] == 410

    @pytest.mark.asyncio
    async def test_poll_unreachable_inverter(self):
        """Given JSON where target serial has reachable=false, returns success=False."""
        unreachable_data = {
            "inverters": [{
                "serial": "112183818450",
                "name": "Spielturm",
                "reachable": False,
                "producing": False,
                "AC": {"0": {}},
                "DC": {},
                "INV": {"0": {}},
            }],
        }
        plugin = _make_plugin()
        plugin._session = _mock_session(json_response=unreachable_data)

        result = await plugin.poll()

        assert result.success is False
        assert "reachable" in result.error.lower() or "unreachable" in result.error.lower()

    @pytest.mark.asyncio
    async def test_poll_serial_not_found(self):
        """Serial not in response returns success=False."""
        plugin = _make_plugin(serial="999999999999")
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.success is False
        assert "999999999999" in result.error

    @pytest.mark.asyncio
    async def test_poll_gateway_offline(self):
        """Given aiohttp.ClientError, poll() returns success=False."""
        plugin = _make_plugin()
        plugin._session = _mock_session(raise_error=aiohttp.ClientError("Connection refused"))

        result = await plugin.poll()

        assert result.success is False
        assert result.error is not None


class TestRegisterEncoding:
    """DTU-01: SunSpec Model 103 register encoding from physical values."""

    @pytest.mark.asyncio
    async def test_register_encoding_ac_current(self):
        """AC current 1.24A with SF=-2 encodes to register value 124."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        # AC Current at offset 2, SF=-2 -> 1.24 * 100 = 124
        assert result.inverter_registers[2] == 124
        # AC Current L1 at offset 3 (same as total for single-phase)
        assert result.inverter_registers[3] == 124
        # SF at offset 6
        assert result.inverter_registers[6] == _int16_as_uint16(-2)

    @pytest.mark.asyncio
    async def test_register_encoding_ac_voltage(self):
        """AC voltage 230.1V with SF=-1 encodes to register value 2301."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        # AC Voltage AN at offset 10, SF=-1 -> 230.1 * 10 = 2301
        assert result.inverter_registers[10] == 2301
        # SF at offset 13
        assert result.inverter_registers[13] == _int16_as_uint16(-1)

    @pytest.mark.asyncio
    async def test_register_encoding_dc_channels_summed(self):
        """Two DC channels (145.2W + 140.0W) sum to 285W for DC power register."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        # DC Power at offset 31, SF=0
        # 145.2 + 140.0 = 285.2 -> rounded to 285
        assert result.inverter_registers[31] == 285
        assert result.inverter_registers[32] == 0  # DC Power SF

    @pytest.mark.asyncio
    async def test_register_encoding_energy_total(self):
        """YieldTotal 1234.567 + 1100.0 kWh = 2334567 Wh as acc32."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        # Total energy: (1234.567 + 1100.0) * 1000 = 2334567 Wh
        total_wh = 2334567
        high_word = (total_wh >> 16) & 0xFFFF
        low_word = total_wh & 0xFFFF
        assert result.inverter_registers[24] == high_word
        assert result.inverter_registers[25] == low_word
        assert result.inverter_registers[26] == 0  # Energy SF

    @pytest.mark.asyncio
    async def test_register_encoding_frequency(self):
        """AC frequency 50.01Hz with SF=-2 encodes to 5001."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.inverter_registers[16] == 5001
        assert result.inverter_registers[17] == _int16_as_uint16(-2)

    @pytest.mark.asyncio
    async def test_register_encoding_temperature(self):
        """Temperature 35.2C with SF=-1 encodes to 352."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.inverter_registers[33] == 352
        assert result.inverter_registers[37] == _int16_as_uint16(-1)

    @pytest.mark.asyncio
    async def test_register_encoding_status_producing(self):
        """Producing inverter has status 4 (MPPT)."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        assert result.inverter_registers[38] == 4  # MPPT

    @pytest.mark.asyncio
    async def test_register_encoding_dc_current_summed(self):
        """DC current summed across channels: 4.52 + 4.44 = 8.96A -> 896."""
        plugin = _make_plugin()
        plugin._session = _mock_session()

        result = await plugin.poll()

        # DC Current at offset 27, SF=-2
        assert result.inverter_registers[27] == 896
        assert result.inverter_registers[28] == _int16_as_uint16(-2)


class TestWritePowerLimit:
    """DTU-03: Power limit via POST /api/limit/config with Basic Auth."""

    @pytest.mark.asyncio
    async def test_write_power_limit_success(self):
        """write_power_limit(True, 50.0) POSTs correct payload."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        result = await plugin.write_power_limit(True, 50.0)

        assert result.success is True
        # Verify POST was called
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        # Check URL contains /api/limit/config
        assert "/api/limit/config" in call_kwargs[0][0] or "/api/limit/config" in str(call_kwargs)
        # Check JSON body
        posted_json = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert posted_json["serial"] == "112183818450"
        assert posted_json["limit_type"] == 1
        assert posted_json["limit_value"] == 50.0

    @pytest.mark.asyncio
    async def test_write_power_limit_disabled(self):
        """write_power_limit(False, 100.0) POSTs limit_value=100."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        result = await plugin.write_power_limit(False, 100.0)

        assert result.success is True
        call_kwargs = session.post.call_args
        posted_json = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert posted_json["limit_value"] == 100.0


class TestDeadTimeGuard:
    """DTU-05: Dead-time guard suppresses re-sends for 30s."""

    @pytest.mark.asyncio
    async def test_dead_time_guard(self):
        """After successful write, calling again within 30s returns success without POST."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        # First call should POST
        result1 = await plugin.write_power_limit(True, 50.0)
        assert result1.success is True
        assert session.post.call_count == 1

        # Second call within dead time should NOT POST
        result2 = await plugin.write_power_limit(True, 50.0)
        assert result2.success is True
        assert session.post.call_count == 1  # Still 1, no new POST

    @pytest.mark.asyncio
    async def test_dead_time_guard_expired(self):
        """After 30s+ elapsed, write_power_limit sends new POST."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        # First call
        await plugin.write_power_limit(True, 50.0)
        assert session.post.call_count == 1

        # Simulate time passing beyond dead time
        with patch("venus_os_fronius_proxy.plugins.opendtu.time") as mock_time:
            # Set monotonic to return a value 31s after the first call
            mock_time.monotonic.return_value = time.monotonic() + 31.0
            result = await plugin.write_power_limit(True, 60.0)

        assert result.success is True
        assert session.post.call_count == 2  # New POST


class TestSessionLifecycle:
    """Session management and cleanup."""

    @pytest.mark.asyncio
    async def test_close_cleans_session(self):
        """After close(), aiohttp session is closed."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        await plugin.close()

        session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_creates_session(self):
        """connect() creates an aiohttp.ClientSession."""
        plugin = _make_plugin()

        with patch("venus_os_fronius_proxy.plugins.opendtu.aiohttp.ClientSession") as mock_cls:
            await plugin.connect()
            mock_cls.assert_called_once()
            assert plugin._session is not None


class TestCommonRegisters:
    """Common Model register generation."""

    def test_common_registers(self):
        """get_static_common_overrides() includes Hoymiles manufacturer."""
        plugin = _make_plugin()
        overrides = plugin.get_static_common_overrides()

        # Should have DID=1, Length=65
        assert overrides[0] == 1
        assert overrides[1] == 65
        # Manufacturer "Hoymiles" at offset 2-17 (16 registers)
        # First two chars "Ho" = 0x486F
        assert overrides[2] == 0x486F

    def test_model_120_nameplate(self):
        """get_model_120_registers() returns 28 regs with DID=120, WRtg from max_power."""
        plugin = _make_plugin()
        plugin._max_power_w = 400

        regs = plugin.get_model_120_registers()

        assert len(regs) == 28
        assert regs[0] == 120  # DID
        assert regs[1] == 26   # Length
        # WRtg at offset 4 (index 4 since DID=0, Length=1, DERTyp=2, WRtg=3... wait)
        # Per plan: WRtg at offset 4, WRtg_SF at offset 5
        # But DID=idx0, Length=idx1, DERTyp=idx2, WRtg=idx3, WRtg_SF=idx4
        # Plan says offset 4 and 5 -- let's match the plan
        assert regs[3] == 400  # WRtg
        assert regs[4] == 0    # WRtg_SF


class TestReconfigure:
    """Reconfigure is a no-op for OpenDTU but should close the session."""

    @pytest.mark.asyncio
    async def test_reconfigure_closes_session(self):
        """reconfigure() closes the existing session."""
        plugin = _make_plugin()
        session = _mock_session()
        plugin._session = session

        await plugin.reconfigure("192.168.3.99", 80, 1)

        session.close.assert_called_once()
