"""Shelly device profile system for Gen1 and Gen2+ API abstraction.

Gen1 Shelly devices (Shelly 1PM, Shelly Plug S, etc.) use a REST API at
/status and /relay/0 endpoints. Gen2+ devices (Shelly Plus 1PM, Pro series)
use an RPC-based API at /rpc/Switch.GetStatus and /rpc/Switch.Set endpoints.

This module provides a unified ShellyPollData dataclass and profile ABCs
so the ShellyPlugin can work with both generations without conditionals.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp
import structlog

log = structlog.get_logger()


@dataclass
class ShellyPollData:
    """Unified data structure from a Shelly device poll."""
    power_w: float = 0.0
    voltage_v: float = 0.0
    current_a: float = 0.0
    frequency_hz: float = 50.0
    energy_total_wh: float = 0.0
    temperature_c: float = 0.0
    relay_on: bool = False


class ShellyProfile(ABC):
    """Abstract profile for Shelly device generation-specific API calls."""

    @abstractmethod
    async def poll_status(self, session: aiohttp.ClientSession, host: str) -> ShellyPollData:
        """Poll the device for current status data."""

    @abstractmethod
    async def switch(self, session: aiohttp.ClientSession, host: str, on: bool) -> bool:
        """Send on/off command to the device relay."""

    @abstractmethod
    async def get_device_info(self, session: aiohttp.ClientSession, host: str) -> dict:
        """Get device information (model, firmware, etc.)."""


class Gen1Profile(ShellyProfile):
    """Profile for Shelly Gen1 devices (REST API at /status, /relay/0).

    Gen1 energy counter (meters[0].total) is in Watt-minutes, must convert to Wh.
    Gen1 does not report AC frequency -- defaults to 50.0 Hz.
    """

    async def poll_status(self, session: aiohttp.ClientSession, host: str) -> ShellyPollData:
        """Poll GET http://{host}/status and extract meter data."""
        url = f"http://{host}/status"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        meter = data.get("meters", [{}])[0] if data.get("meters") else {}

        return ShellyPollData(
            power_w=meter.get("power", 0.0),
            voltage_v=meter.get("voltage", 0.0),
            current_a=meter.get("current", 0.0),
            frequency_hz=50.0,  # Gen1 does not report frequency
            energy_total_wh=meter.get("total", 0) / 60.0,  # Watt-minutes to Wh
            temperature_c=data.get("temperature", 0.0),
            relay_on=data.get("relays", [{}])[0].get("ison", False) if data.get("relays") else False,
        )

    async def switch(self, session: aiohttp.ClientSession, host: str, on: bool) -> bool:
        """Send GET http://{host}/relay/0?turn=on|off."""
        action = "on" if on else "off"
        url = f"http://{host}/relay/0?turn={action}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            await resp.json()
        return True

    async def get_device_info(self, session: aiohttp.ClientSession, host: str) -> dict:
        """GET http://{host}/shelly for device info."""
        url = f"http://{host}/shelly"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return await resp.json()


class Gen2Profile(ShellyProfile):
    """Profile for Shelly Gen2+ devices (RPC API at /rpc/Switch.*).

    Gen2 energy counter (aenergy.total) is already in Wh.
    Gen2 reports frequency via the freq field.
    """

    async def poll_status(self, session: aiohttp.ClientSession, host: str) -> ShellyPollData:
        """Poll GET http://{host}/rpc/Switch.GetStatus?id=0."""
        url = f"http://{host}/rpc/Switch.GetStatus?id=0"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        # Temperature handling: Gen2 returns {"tC": 45.2, "tF": 113.4} or may be absent
        temp_data = data.get("temperature")
        temperature_c = 0.0
        if isinstance(temp_data, dict):
            temperature_c = temp_data.get("tC", 0.0)

        return ShellyPollData(
            power_w=data.get("apower", 0.0),
            voltage_v=data.get("voltage", 0.0),
            current_a=data.get("current", 0.0),
            frequency_hz=data.get("freq", 50.0),
            energy_total_wh=data.get("aenergy", {}).get("total", 0.0),
            temperature_c=temperature_c,
            relay_on=data.get("output", False),
        )

    async def switch(self, session: aiohttp.ClientSession, host: str, on: bool) -> bool:
        """POST http://{host}/rpc/Switch.Set with JSON body."""
        url = f"http://{host}/rpc/Switch.Set"
        payload = {"id": 0, "on": on}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            await resp.json()
        return True

    async def get_device_info(self, session: aiohttp.ClientSession, host: str) -> dict:
        """GET http://{host}/rpc/Shelly.GetDeviceInfo for device info."""
        url = f"http://{host}/rpc/Shelly.GetDeviceInfo"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return await resp.json()
