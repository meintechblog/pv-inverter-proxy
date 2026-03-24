"""mDNS discovery for Shelly devices on the LAN and HTTP probe.

Scans for _shelly._tcp.local. services using zeroconf AsyncZeroconf.
Also provides probe_shelly_device() to query a single Shelly's /shelly endpoint.
Manual-only -- triggered via REST endpoint, not at startup.
"""
from __future__ import annotations

import asyncio
import socket

import aiohttp
import structlog
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

log = structlog.get_logger(component="shelly_discovery")

SHELLY_SERVICE_TYPE = "_shelly._tcp.local."


async def discover_shelly_devices(
    timeout: float = 3.0, skip_ips: set[str] | None = None
) -> list[dict]:
    """Scan LAN for Shelly devices advertising _shelly._tcp.local.

    Args:
        timeout: Scan duration in seconds.
        skip_ips: Set of IP addresses to exclude (already configured devices).

    Returns:
        List of dicts with keys: host, name, generation, model, firmware.
    """
    found_names: list[str] = []

    def on_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found_names.append(name)

    aiozc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(
            aiozc.zeroconf, SHELLY_SERVICE_TYPE, handlers=[on_state_change]
        )
        await asyncio.sleep(timeout)
        await browser.async_cancel()

        results = []
        for name in found_names:
            info = AsyncServiceInfo(SHELLY_SERVICE_TYPE, name)
            await info.async_request(aiozc.zeroconf, timeout=1000)

            # Extract IP from addresses or fallback to server
            if info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
            elif info.server:
                ip = info.server.rstrip(".")
            else:
                continue

            # Skip already-configured devices
            if skip_ips and ip in skip_ips:
                continue

            # Parse TXT record properties
            props = info.properties or {}
            gen = _decode_txt(props.get(b"gen", b"1"))
            app = _decode_txt(props.get(b"app", b""))
            ver = _decode_txt(props.get(b"ver", b""))

            results.append({
                "host": ip,
                "name": name.replace(f".{SHELLY_SERVICE_TYPE}", ""),
                "generation": f"gen{gen}",
                "model": app,
                "firmware": ver,
            })

        log.info("shelly_mdns_scan_complete", devices_found=len(results), timeout=timeout)
        return results
    finally:
        await aiozc.async_close()


async def probe_shelly_device(host: str, timeout: float = 5.0) -> dict:
    """Probe a single Shelly device by querying its /shelly HTTP endpoint.

    Args:
        host: IP address or hostname of the Shelly device.
        timeout: HTTP request timeout in seconds.

    Returns:
        Dict with success, generation, model, mac, gen_display on success.
        Dict with success=False and error message on failure.
    """
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(f"http://{host}/shelly") as resp:
                data = await resp.json()

        gen_value = data.get("gen", 0)
        if gen_value >= 2:
            generation = "gen2"
            gen_display = f"Gen{gen_value}"
        else:
            generation = "gen1"
            gen_display = "Gen1"

        # Gen2+ uses "app", Gen1 uses "type"
        model = data.get("app", data.get("type", "Unknown"))
        mac = data.get("mac", "")

        return {
            "success": True,
            "generation": generation,
            "model": model,
            "mac": mac,
            "gen_display": gen_display,
        }
    except Exception as e:
        return {"success": False, "error": f"Could not reach Shelly at {host}: {e}"}


def _decode_txt(value: bytes | str) -> str:
    """Decode a TXT record value from bytes to str."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
