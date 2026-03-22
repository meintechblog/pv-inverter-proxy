"""mDNS discovery for MQTT brokers on the LAN.

Scans for _mqtt._tcp.local. services using zeroconf AsyncZeroconf.
Manual-only -- triggered via REST endpoint, not at startup (per D-14).
"""
from __future__ import annotations

import asyncio

import structlog
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf, AsyncServiceInfo

log = structlog.get_logger(component="mdns_discovery")

SERVICE_TYPE = "_mqtt._tcp.local."


async def discover_mqtt_brokers(timeout: float = 3.0) -> list[dict]:
    """Scan LAN for MQTT brokers advertising _mqtt._tcp.local.

    Args:
        timeout: Scan duration in seconds (default 3.0 per D-15).

    Returns:
        List of dicts with keys: host (str), port (int), name (str).
    """
    found_names: list[str] = []

    def on_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found_names.append(name)

    aiozc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(
            aiozc.zeroconf, SERVICE_TYPE, handlers=[on_state_change]
        )
        await asyncio.sleep(timeout)
        await browser.async_cancel()

        results = []
        for name in found_names:
            info = AsyncServiceInfo(SERVICE_TYPE, name)
            await info.async_request(aiozc.zeroconf, timeout=1000)
            if info.server and info.port:
                results.append({
                    "host": info.server.rstrip("."),
                    "port": info.port,
                    "name": name.replace(f".{SERVICE_TYPE}", ""),
                })

        log.info("mdns_scan_complete", brokers_found=len(results), timeout=timeout)
        return results
    finally:
        await aiozc.async_close()
