"""Plugin registry and factory for inverter type dispatch."""
from __future__ import annotations

from pv_inverter_proxy.config import GatewayConfig, InverterEntry


def plugin_factory(
    entry: InverterEntry,
    gateway_config: GatewayConfig | None = None,
):
    """Create the appropriate InverterPlugin for an InverterEntry.

    Args:
        entry: InverterEntry with type field ("solaredge", "opendtu", "shelly", or "sungrow").
        gateway_config: Optional GatewayConfig for opendtu entries.
            If None for opendtu, a default is created from entry.gateway_host.

    Returns:
        An InverterPlugin instance configured for the entry.

    Raises:
        ValueError: For unknown inverter types.
    """
    if entry.type == "solaredge":
        from pv_inverter_proxy.plugins.solaredge import SolarEdgePlugin
        return SolarEdgePlugin(host=entry.host, port=entry.port, unit_id=entry.unit_id)
    elif entry.type == "opendtu":
        from pv_inverter_proxy.plugins.opendtu import OpenDTUPlugin
        if gateway_config is None:
            gateway_config = GatewayConfig(
                host=entry.gateway_host,
                user=entry.gateway_user or "admin",
                password=entry.gateway_password or "openDTU42",
            )
        return OpenDTUPlugin(
            gateway_config=gateway_config,
            serial=entry.serial,
            name=entry.name,
        )
    elif entry.type == "shelly":
        from pv_inverter_proxy.plugins.shelly import ShellyPlugin
        return ShellyPlugin(
            host=entry.host,
            generation=entry.shelly_gen,
            name=entry.name,
            rated_power=entry.rated_power,
        )
    elif entry.type == "sungrow":
        from pv_inverter_proxy.plugins.sungrow import SungrowPlugin
        return SungrowPlugin(
            host=entry.host,
            port=entry.port,
            unit_id=entry.unit_id,
            rated_power=entry.rated_power,
        )
    else:
        raise ValueError(f"Unknown inverter type: {entry.type} (valid: solaredge, opendtu, shelly, sungrow)")
