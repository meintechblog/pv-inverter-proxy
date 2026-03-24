"""Tests for the Shelly plugin (smart plugs/switches via local HTTP API).

Covers requirements PLUG-01 through PLUG-07:
- PLUG-01: ShellyPlugin implements InverterPlugin ABC
- PLUG-02: Gen1Profile and Gen2Profile parse their respective JSON formats
- PLUG-03: Auto-detection of Gen1 vs Gen2+ via /shelly endpoint
- PLUG-04: Poll returns PollResult with SunSpec Model 103 registers
- PLUG-05: Register encoding matches OpenDTU pattern
- PLUG-06: Energy counter offset tracking (counter resets)
- PLUG-07: Missing fields produce 0.0 defaults, no crash
"""
from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock, patch

import aiohttp
import pytest

from pv_inverter_proxy.plugins.shelly import ShellyPlugin
from pv_inverter_proxy.plugins.shelly_profiles import (
    Gen1Profile,
    Gen2Profile,
    ShellyPollData,
    ShellyProfile,
)
from pv_inverter_proxy.plugin import InverterPlugin, PollResult, WriteResult
from pv_inverter_proxy.sunspec_models import _int16_as_uint16


# --- Sample JSON fixtures ---

SAMPLE_GEN1_STATUS = {
    "relays": [{"ison": True}],
    "meters": [{"power": 342.5, "voltage": 230.4, "current": 1.49, "total": 117920}],
    "temperature": 45.2,
}

SAMPLE_GEN2_SWITCH_STATUS = {
    "id": 0,
    "output": True,
    "apower": 342.5,
    "voltage": 230.4,
    "current": 1.49,
    "freq": 50.01,
    "aenergy": {"total": 14567.89},
    "temperature": {"tC": 45.2},
}

SAMPLE_GEN1_SHELLY = {
    "type": "SHSW-PM",
    "mac": "AABBCCDDEEFF",
    "auth": False,
    "fw": "20230913-114244/v1.14.0-gcb84623",
}

SAMPLE_GEN2_SHELLY = {
    "id": "shellyplus1pm-aabbccddeeff",
    "mac": "AABBCCDDEEFF",
    "model": "SNSW-001P16EU",
    "gen": 2,
    "fw_id": "20231107-164738/1.0.8-g",
    "app": "Plus1PM",
    "auth_en": False,
}

SAMPLE_GEN1_MINIMAL = {
    "relays": [{"ison": False}],
    "meters": [{"power": 0.0, "total": 0}],
}


# --- Helpers ---

def _mock_session(responses: dict[str, dict] | None = None):
    """Create a mock aiohttp.ClientSession that returns different JSON per URL path."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    type(session).closed = PropertyMock(return_value=False)

    _responses = responses or {}

    def _make_cm(url, **kwargs):
        # Extract path from URL
        path = url
        if "://" in url:
            path = "/" + url.split("://", 1)[1].split("/", 1)[1] if "/" in url.split("://", 1)[1] else "/"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        # Find matching response by checking if path ends with any key
        for key, value in _responses.items():
            if path.endswith(key) or key in path:
                mock_resp.json = AsyncMock(return_value=value)
                break
        else:
            mock_resp.json = AsyncMock(return_value={})

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    session.get.side_effect = _make_cm

    # POST support
    def _make_post_cm(url, **kwargs):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"type": "success"})
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    session.post.side_effect = _make_post_cm

    return session


# --- Test Classes ---

class TestABCCompliance:
    """PLUG-01: ShellyPlugin implements InverterPlugin ABC."""

    def test_is_subclass_of_inverter_plugin(self):
        assert issubclass(ShellyPlugin, InverterPlugin)

    def test_can_be_instantiated(self):
        plugin = ShellyPlugin(host="192.168.1.100")
        assert plugin is not None

    def test_all_abstract_methods_implemented(self):
        """All 7 abstract methods must be present and callable."""
        plugin = ShellyPlugin(host="192.168.1.100")
        assert hasattr(plugin, "connect")
        assert hasattr(plugin, "poll")
        assert hasattr(plugin, "get_static_common_overrides")
        assert hasattr(plugin, "get_model_120_registers")
        assert hasattr(plugin, "write_power_limit")
        assert hasattr(plugin, "reconfigure")
        assert hasattr(plugin, "close")


class TestProfiles:
    """PLUG-02: Gen1Profile and Gen2Profile parse their respective JSON formats."""

    async def test_gen1_profile_poll_status(self):
        """Gen1Profile.poll_status fetches /status and returns ShellyPollData."""
        profile = Gen1Profile()
        session = _mock_session({"/status": SAMPLE_GEN1_STATUS})

        data = await profile.poll_status(session, "192.168.1.100")

        assert isinstance(data, ShellyPollData)
        assert data.power_w == 342.5
        assert data.voltage_v == 230.4
        assert data.current_a == 1.49
        # Gen1 total is in Watt-minutes: 117920 / 60 = 1965.333...
        assert abs(data.energy_total_wh - 117920 / 60.0) < 0.01
        assert data.temperature_c == 45.2
        assert data.relay_on is True

    async def test_gen1_profile_default_frequency(self):
        """Gen1 does not report frequency, defaults to 50.0 Hz."""
        profile = Gen1Profile()
        session = _mock_session({"/status": SAMPLE_GEN1_STATUS})

        data = await profile.poll_status(session, "192.168.1.100")

        assert data.frequency_hz == 50.0

    async def test_gen2_profile_poll_status(self):
        """Gen2Profile.poll_status fetches /rpc/Switch.GetStatus and returns ShellyPollData."""
        profile = Gen2Profile()
        session = _mock_session({"/rpc/Switch.GetStatus": SAMPLE_GEN2_SWITCH_STATUS})

        data = await profile.poll_status(session, "192.168.1.100")

        assert isinstance(data, ShellyPollData)
        assert data.power_w == 342.5
        assert data.voltage_v == 230.4
        assert data.current_a == 1.49
        assert data.frequency_hz == 50.01
        assert data.energy_total_wh == 14567.89
        assert data.temperature_c == 45.2
        assert data.relay_on is True

    async def test_gen2_profile_energy_already_wh(self):
        """Gen2 aenergy.total is already in Wh, no conversion needed."""
        profile = Gen2Profile()
        session = _mock_session({"/rpc/Switch.GetStatus": SAMPLE_GEN2_SWITCH_STATUS})

        data = await profile.poll_status(session, "192.168.1.100")

        # Should be exactly 14567.89, no /60 conversion
        assert data.energy_total_wh == 14567.89


class TestAutoDetection:
    """PLUG-03: Auto-detection of Gen1 vs Gen2+ via /shelly endpoint."""

    async def test_gen2_detected_from_shelly_endpoint(self):
        """When /shelly returns gen=2, Gen2Profile is selected."""
        plugin = ShellyPlugin(host="192.168.1.100")
        session = _mock_session({"/shelly": SAMPLE_GEN2_SHELLY})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        assert isinstance(plugin._profile, Gen2Profile)
        assert plugin._generation == "gen2"

    async def test_gen1_detected_when_no_gen_field(self):
        """When /shelly has no gen field, Gen1Profile is selected."""
        plugin = ShellyPlugin(host="192.168.1.100")
        session = _mock_session({"/shelly": SAMPLE_GEN1_SHELLY})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        assert isinstance(plugin._profile, Gen1Profile)
        assert plugin._generation == "gen1"

    async def test_explicit_gen2_skips_detection(self):
        """When generation="gen2" is explicit, no /shelly probe needed."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")
        session = _mock_session({})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        assert isinstance(plugin._profile, Gen2Profile)
        # Should NOT have called GET /shelly
        session.get.assert_not_called()

    async def test_explicit_gen1_skips_detection(self):
        """When generation="gen1" is explicit, no /shelly probe needed."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen1")
        session = _mock_session({})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        assert isinstance(plugin._profile, Gen1Profile)
        session.get.assert_not_called()

    async def test_device_info_stored(self):
        """connect() stores device info from /shelly for later use."""
        plugin = ShellyPlugin(host="192.168.1.100")
        session = _mock_session({"/shelly": SAMPLE_GEN2_SHELLY})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        assert plugin._device_info.get("mac") == "AABBCCDDEEFF"


class TestPollSuccess:
    """PLUG-04: Poll returns PollResult with correct register structure."""

    async def test_poll_success_gen2(self):
        """poll() returns PollResult(success=True) with 67 common and 52 inverter registers."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")
        session = _mock_session({"/rpc/Switch.GetStatus": SAMPLE_GEN2_SWITCH_STATUS})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        result = await plugin.poll()

        assert result.success is True
        assert result.error is None
        assert len(result.common_registers) == 67
        assert len(result.inverter_registers) == 52

    async def test_poll_not_connected(self):
        """poll() before connect() returns success=False."""
        plugin = ShellyPlugin(host="192.168.1.100")

        result = await plugin.poll()

        assert result.success is False
        assert result.error is not None

    async def test_poll_network_error(self):
        """poll() returns success=False on network error."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")

        # Create a session that raises on get
        session = AsyncMock(spec=aiohttp.ClientSession)
        type(session).closed = PropertyMock(return_value=False)
        session.get.side_effect = aiohttp.ClientError("Connection refused")

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        result = await plugin.poll()

        assert result.success is False
        assert result.error is not None


class TestRegisterEncoding:
    """PLUG-05: SunSpec Model 103 register encoding matches OpenDTU pattern."""

    async def _poll_gen2(self, status=None):
        """Helper: create connected plugin, poll, return result."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")
        resp = status or SAMPLE_GEN2_SWITCH_STATUS
        session = _mock_session({"/rpc/Switch.GetStatus": resp})
        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()
        return await plugin.poll()

    async def test_ac_power_register(self):
        """AC power 342.5W at offset 14, SF=0 -> 342 (banker's rounding)."""
        result = await self._poll_gen2()
        assert result.inverter_registers[14] == 342
        assert result.inverter_registers[15] == 0  # SF

    async def test_ac_current_register(self):
        """AC current 1.49A with SF=-2 at offset 2 -> 149."""
        result = await self._poll_gen2()
        assert result.inverter_registers[2] == 149
        assert result.inverter_registers[3] == 149  # Phase A same as total
        assert result.inverter_registers[6] == _int16_as_uint16(-2)

    async def test_ac_voltage_register(self):
        """AC voltage 230.4V with SF=-1 at offset 10 -> 2304."""
        result = await self._poll_gen2()
        assert result.inverter_registers[10] == 2304
        assert result.inverter_registers[13] == _int16_as_uint16(-1)

    async def test_frequency_register(self):
        """Frequency 50.01Hz with SF=-2 at offset 16 -> 5001."""
        result = await self._poll_gen2()
        assert result.inverter_registers[16] == 5001
        assert result.inverter_registers[17] == _int16_as_uint16(-2)

    async def test_temperature_register(self):
        """Temperature 45.2C with SF=-1 at offset 33 -> 452."""
        result = await self._poll_gen2()
        assert result.inverter_registers[33] == 452
        assert result.inverter_registers[37] == _int16_as_uint16(-1)

    async def test_energy_acc32_register(self):
        """Energy 14568Wh (rounded from 14567.89) as acc32 at offset 24-25."""
        result = await self._poll_gen2()
        energy_wh = 14568  # round(14567.89)
        assert result.inverter_registers[24] == (energy_wh >> 16) & 0xFFFF
        assert result.inverter_registers[25] == energy_wh & 0xFFFF
        assert result.inverter_registers[26] == 0  # SF

    async def test_status_mppt_when_relay_on(self):
        """Status = 4 (MPPT) when relay is on."""
        result = await self._poll_gen2()
        assert result.inverter_registers[38] == 4

    async def test_status_sleeping_when_relay_off(self):
        """Status = 2 (SLEEPING) when relay is off."""
        off_status = dict(SAMPLE_GEN2_SWITCH_STATUS, output=False)
        result = await self._poll_gen2(status=off_status)
        assert result.inverter_registers[38] == 2

    async def test_dc_registers_zero(self):
        """Shelly has no DC data, all DC registers should be 0."""
        result = await self._poll_gen2()
        assert result.inverter_registers[27] == 0  # DC current
        assert result.inverter_registers[29] == 0  # DC voltage
        assert result.inverter_registers[31] == 0  # DC power


class TestEnergyTracking:
    """PLUG-06: Energy counter offset tracking prevents total from decreasing."""

    def test_normal_increment(self):
        """Normal energy increases pass through."""
        plugin = ShellyPlugin(host="192.168.1.100")
        assert plugin._track_energy(100) == 100
        assert plugin._track_energy(200) == 200
        assert plugin._track_energy(300) == 300

    def test_counter_reset_detected(self):
        """When raw energy drops (counter reset), offset accumulates."""
        plugin = ShellyPlugin(host="192.168.1.100")
        assert plugin._track_energy(100) == 100
        assert plugin._track_energy(200) == 200
        # Counter resets to 50 (e.g., Shelly reboot)
        assert plugin._track_energy(50) == 250  # 200 offset + 50 new
        assert plugin._track_energy(80) == 280  # 200 offset + 80 new

    def test_multiple_resets(self):
        """Multiple counter resets accumulate correctly."""
        plugin = ShellyPlugin(host="192.168.1.100")
        plugin._track_energy(100)
        plugin._track_energy(200)
        plugin._track_energy(50)   # Reset 1: offset = 200
        plugin._track_energy(100)
        result = plugin._track_energy(30)  # Reset 2: offset = 200 + 100 = 300
        assert result == 330  # 300 + 30

    def test_zero_start(self):
        """First reading starts from zero correctly."""
        plugin = ShellyPlugin(host="192.168.1.100")
        assert plugin._track_energy(0) == 0
        assert plugin._track_energy(50) == 50


class TestMissingFields:
    """PLUG-07: Missing fields produce 0.0 defaults, no crash."""

    async def test_gen1_minimal_response(self):
        """Gen1 response missing voltage/current/temperature produces defaults."""
        profile = Gen1Profile()
        session = _mock_session({"/status": SAMPLE_GEN1_MINIMAL})

        data = await profile.poll_status(session, "192.168.1.100")

        assert data.voltage_v == 0.0
        assert data.current_a == 0.0
        assert data.temperature_c == 0.0
        assert data.power_w == 0.0
        assert data.relay_on is False

    async def test_gen2_missing_temperature(self):
        """Gen2 response with no temperature field produces 0.0."""
        no_temp = {
            "id": 0,
            "output": True,
            "apower": 100.0,
            "voltage": 230.0,
            "current": 0.43,
            "freq": 50.0,
            "aenergy": {"total": 1000.0},
        }
        profile = Gen2Profile()
        session = _mock_session({"/rpc/Switch.GetStatus": no_temp})

        data = await profile.poll_status(session, "192.168.1.100")

        assert data.temperature_c == 0.0

    async def test_gen2_missing_energy(self):
        """Gen2 response with no aenergy field produces 0.0."""
        no_energy = {
            "id": 0,
            "output": True,
            "apower": 100.0,
            "voltage": 230.0,
            "current": 0.43,
            "freq": 50.0,
        }
        profile = Gen2Profile()
        session = _mock_session({"/rpc/Switch.GetStatus": no_energy})

        data = await profile.poll_status(session, "192.168.1.100")

        assert data.energy_total_wh == 0.0

    async def test_gen1_empty_meters(self):
        """Gen1 response with empty meters list produces all defaults."""
        empty_meters = {"relays": [{"ison": False}], "meters": [{}]}
        profile = Gen1Profile()
        session = _mock_session({"/status": empty_meters})

        data = await profile.poll_status(session, "192.168.1.100")

        assert data.power_w == 0.0
        assert data.voltage_v == 0.0
        assert data.current_a == 0.0
        assert data.energy_total_wh == 0.0

    async def test_poll_with_missing_fields_produces_valid_registers(self):
        """Full poll with minimal data produces valid 52-register array."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen1")
        session = _mock_session({"/status": SAMPLE_GEN1_MINIMAL})

        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        result = await plugin.poll()

        assert result.success is True
        assert len(result.inverter_registers) == 52
        # All values should be 0 or valid defaults
        assert result.inverter_registers[14] == 0  # AC power
        assert result.inverter_registers[38] == 2  # SLEEPING (relay off)


class TestWritePowerLimit:
    """write_power_limit is a no-op for Shelly (CTRL-03 preview)."""

    async def test_write_power_limit_noop(self):
        """write_power_limit always returns success=True without any HTTP call."""
        plugin = ShellyPlugin(host="192.168.1.100")

        result = await plugin.write_power_limit(True, 50.0)

        assert result.success is True
        assert isinstance(result, WriteResult)

    async def test_write_power_limit_disable_noop(self):
        """Disabling power limit also returns success."""
        plugin = ShellyPlugin(host="192.168.1.100")

        result = await plugin.write_power_limit(False, 100.0)

        assert result.success is True


class TestCommonRegisters:
    """Common Model and Nameplate register generation."""

    def test_common_registers_manufacturer_shelly(self):
        """get_static_common_overrides includes Shelly manufacturer."""
        plugin = ShellyPlugin(host="192.168.1.100", name="TestShelly")
        overrides = plugin.get_static_common_overrides()

        assert overrides[0] == 1   # DID
        assert overrides[1] == 65  # Length
        # "Sh" = 0x5368
        assert overrides[2] == 0x5368

    def test_model_120_nameplate(self):
        """get_model_120_registers returns 28 regs with DID=120."""
        plugin = ShellyPlugin(host="192.168.1.100", rated_power=400)
        regs = plugin.get_model_120_registers()

        assert len(regs) == 28
        assert regs[0] == 120  # DID
        assert regs[1] == 26   # Length
        assert regs[2] == 4    # DERTyp = PV
        assert regs[3] == 400  # WRtg
        assert regs[4] == 0    # WRtg_SF


class TestReconfigure:
    """Reconfigure updates host and resets profile."""

    async def test_reconfigure_resets_state(self):
        """reconfigure() closes session and resets profile."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")
        session = _mock_session({})
        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        await plugin.reconfigure("192.168.1.200", 80, 1)

        assert plugin._host == "192.168.1.200"
        assert plugin._profile is None
        assert plugin._generation == ""

    async def test_close_cleans_session(self):
        """close() closes the aiohttp session."""
        plugin = ShellyPlugin(host="192.168.1.100", generation="gen2")
        session = _mock_session({})
        with patch("pv_inverter_proxy.plugins.shelly.aiohttp.ClientSession", return_value=session):
            await plugin.connect()

        await plugin.close()

        session.close.assert_called_once()
        assert plugin._session is None
