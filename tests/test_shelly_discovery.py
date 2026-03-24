"""Tests for Shelly mDNS discovery and HTTP probe."""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from pv_inverter_proxy.shelly_discovery import (
    SHELLY_SERVICE_TYPE,
    discover_shelly_devices,
    probe_shelly_device,
)


class TestShellyDiscovery:
    """Tests for discover_shelly_devices via mDNS."""

    @pytest.mark.asyncio
    async def test_discover_empty_scan(self):
        """No devices found returns empty list, async_close called."""
        mock_aiozc = AsyncMock()
        mock_aiozc.zeroconf = MagicMock()

        with patch(
            "pv_inverter_proxy.shelly_discovery.AsyncZeroconf",
            return_value=mock_aiozc,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceBrowser",
        ) as mock_browser_cls:
            mock_browser = AsyncMock()
            mock_browser_cls.return_value = mock_browser

            result = await discover_shelly_devices(timeout=0.01)

        assert result == []
        mock_aiozc.async_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discover_finds_device(self):
        """Fake browser adds one service, result has correct fields."""
        mock_aiozc = AsyncMock()
        mock_aiozc.zeroconf = MagicMock()

        mock_info = MagicMock()
        mock_info.addresses = [socket.inet_aton("192.168.1.50")]
        mock_info.server = "shellyplus1pm-aabb.local."
        mock_info.properties = {
            b"gen": b"2",
            b"app": b"Plus1PM",
            b"ver": b"1.0.8",
        }
        mock_info.async_request = AsyncMock()

        def fake_browser_init(zeroconf, stype, handlers=None):
            # Simulate a device being found
            for handler in (handlers or []):
                from zeroconf import ServiceStateChange
                handler(zeroconf, stype, f"shellyplus1pm-aabb.{stype}", ServiceStateChange.Added)
            browser = AsyncMock()
            return browser

        with patch(
            "pv_inverter_proxy.shelly_discovery.AsyncZeroconf",
            return_value=mock_aiozc,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceBrowser",
            side_effect=fake_browser_init,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceInfo",
            return_value=mock_info,
        ):
            result = await discover_shelly_devices(timeout=0.01)

        assert len(result) == 1
        assert result[0]["host"] == "192.168.1.50"
        assert result[0]["generation"] == "gen2"
        assert result[0]["model"] == "Plus1PM"
        assert result[0]["firmware"] == "1.0.8"
        assert result[0]["name"] == "shellyplus1pm-aabb"

    @pytest.mark.asyncio
    async def test_discover_skips_existing_ips(self):
        """Devices with IPs in skip_ips are excluded from results."""
        mock_aiozc = AsyncMock()
        mock_aiozc.zeroconf = MagicMock()

        mock_info = MagicMock()
        mock_info.addresses = [socket.inet_aton("192.168.1.50")]
        mock_info.server = "shellyplus1pm-aabb.local."
        mock_info.properties = {b"gen": b"2", b"app": b"Plus1PM", b"ver": b"1.0.8"}
        mock_info.async_request = AsyncMock()

        def fake_browser_init(zeroconf, stype, handlers=None):
            for handler in (handlers or []):
                from zeroconf import ServiceStateChange
                handler(zeroconf, stype, f"shellyplus1pm-aabb.{stype}", ServiceStateChange.Added)
            return AsyncMock()

        with patch(
            "pv_inverter_proxy.shelly_discovery.AsyncZeroconf",
            return_value=mock_aiozc,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceBrowser",
            side_effect=fake_browser_init,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceInfo",
            return_value=mock_info,
        ):
            result = await discover_shelly_devices(timeout=0.01, skip_ips={"192.168.1.50"})

        assert result == []

    @pytest.mark.asyncio
    async def test_discover_calls_close_on_error(self):
        """async_close is called even when browser raises."""
        mock_aiozc = AsyncMock()
        mock_aiozc.zeroconf = MagicMock()

        with patch(
            "pv_inverter_proxy.shelly_discovery.AsyncZeroconf",
            return_value=mock_aiozc,
        ), patch(
            "pv_inverter_proxy.shelly_discovery.AsyncServiceBrowser",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await discover_shelly_devices(timeout=0.01)

        mock_aiozc.async_close.assert_awaited_once()

    def test_service_type_constant(self):
        """SHELLY_SERVICE_TYPE is the correct mDNS service type."""
        assert SHELLY_SERVICE_TYPE == "_shelly._tcp.local."


class TestProbeHandler:
    """Tests for probe_shelly_device HTTP probe."""

    @pytest.mark.asyncio
    async def test_probe_gen2_device(self):
        """Gen2 device returns correct generation and model."""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "gen": 2,
            "app": "Plus1PM",
            "mac": "AABBCCDDEEFF",
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pv_inverter_proxy.shelly_discovery.aiohttp.ClientSession", return_value=mock_session):
            result = await probe_shelly_device("192.168.1.50")

        assert result["success"] is True
        assert result["generation"] == "gen2"
        assert result["model"] == "Plus1PM"
        assert result["mac"] == "AABBCCDDEEFF"
        assert result["gen_display"] == "Gen2"

    @pytest.mark.asyncio
    async def test_probe_gen1_device(self):
        """Gen1 device (no gen field) returns correct generation and model."""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "type": "SHSW-PM",
            "mac": "CCDDEEFF0011",
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pv_inverter_proxy.shelly_discovery.aiohttp.ClientSession", return_value=mock_session):
            result = await probe_shelly_device("192.168.1.51")

        assert result["success"] is True
        assert result["generation"] == "gen1"
        assert result["model"] == "SHSW-PM"
        assert result["mac"] == "CCDDEEFF0011"
        assert result["gen_display"] == "Gen1"

    @pytest.mark.asyncio
    async def test_probe_gen3_device(self):
        """Gen3 device returns gen2 generation string (gen2+ family)."""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "gen": 3,
            "app": "Mini1PMG3",
            "mac": "112233445566",
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pv_inverter_proxy.shelly_discovery.aiohttp.ClientSession", return_value=mock_session):
            result = await probe_shelly_device("192.168.1.52")

        assert result["success"] is True
        assert result["generation"] == "gen2"
        assert result["model"] == "Mini1PMG3"
        assert result["gen_display"] == "Gen3"

    @pytest.mark.asyncio
    async def test_probe_unreachable(self):
        """Unreachable device returns success=False with error."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pv_inverter_proxy.shelly_discovery.aiohttp.ClientSession", return_value=mock_session):
            result = await probe_shelly_device("192.168.1.99")

        assert result["success"] is False
        assert "error" in result
        assert "192.168.1.99" in result["error"]
