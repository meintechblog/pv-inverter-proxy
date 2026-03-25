"""YAML configuration loading with dataclass schema and sensible defaults.

Loads configuration from a YAML file (default: /etc/pv-inverter-proxy/config.yaml).
Missing file or missing keys silently use defaults. Unknown keys are ignored.
"""
from __future__ import annotations

import ipaddress
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field

import structlog
import yaml

log = structlog.get_logger()


DEFAULT_CONFIG_PATH = "/etc/pv-inverter-proxy/config.yaml"

AUTO_THROTTLE_PRESETS: dict[str, dict[str, float]] = {
    "aggressive": {
        "convergence_tolerance_pct": 10.0,
        "convergence_max_samples": 5,
        "target_change_tolerance_pct": 5.0,
        "binary_off_threshold_w": 100.0,
    },
    "balanced": {
        "convergence_tolerance_pct": 5.0,
        "convergence_max_samples": 10,
        "target_change_tolerance_pct": 2.0,
        "binary_off_threshold_w": 50.0,
    },
    "conservative": {
        "convergence_tolerance_pct": 3.0,
        "convergence_max_samples": 20,
        "target_change_tolerance_pct": 1.0,
        "binary_off_threshold_w": 25.0,
    },
}


def _generate_id() -> str:
    """Generate a 12-character hex identifier for an inverter entry."""
    return uuid.uuid4().hex[:12]


@dataclass
class InverterEntry:
    """A single inverter connection entry."""
    host: str = "192.168.3.18"
    port: int = 1502
    unit_id: int = 1
    enabled: bool = True
    id: str = field(default_factory=_generate_id)
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    firmware_version: str = ""
    type: str = "solaredge"       # Discriminator: "solaredge" or "opendtu"
    name: str = ""                # User-friendly display name
    gateway_host: str = ""        # OpenDTU gateway IP (opendtu type only)
    gateway_user: str = ""        # OpenDTU Basic Auth username (empty = default "admin")
    gateway_password: str = ""    # OpenDTU Basic Auth password (empty = default "openDTU42")
    shelly_gen: str = ""              # Shelly generation: "gen1" or "gen2" (auto-detected, persisted)
    rated_power: int = 0           # Rated power in watts (0 = unknown)
    throttle_order: int = 1           # TO 1 = first to throttle
    throttle_enabled: bool = True     # False = monitoring-only (no limit commands)
    throttle_dead_time_s: float = 0.0 # Per-device dead-time in seconds (default: no wait)


@dataclass
class VirtualInverterConfig:
    """Configuration for the aggregated virtual inverter identity."""
    name: str = "Fronius PV-Inverter-Proxy"


@dataclass
class GatewayConfig:
    """Configuration for a gateway device (e.g., OpenDTU)."""
    host: str = ""
    user: str = "admin"
    password: str = "openDTU42"
    poll_interval: float = 5.0


@dataclass
class ProxyConfig:
    host: str = "0.0.0.0"
    port: int = 502
    poll_interval: float = 1.0
    staleness_timeout: float = 30.0


@dataclass
class NightModeConfig:
    threshold_seconds: float = 300.0


@dataclass
class WebappConfig:
    port: int = 80


@dataclass
class VenusConfig:
    host: str = ""           # Empty = not configured (proxy runs without MQTT)
    port: int = 1883         # MQTT standard port
    portal_id: str = ""      # Empty = auto-discover via N/+/system/0/Serial
    name: str = ""           # Display name for sidebar (default: "Venus OS")


@dataclass
class ScannerConfig:
    ports: list[int] = field(default_factory=lambda: [502, 1502])


@dataclass
class MqttPublishConfig:
    """Configuration for external MQTT data publishing."""
    enabled: bool = False
    host: str = "mqtt-master.local"
    port: int = 1883
    topic_prefix: str = "pv-inverter-proxy"
    interval_s: int = 5
    client_id: str = "pv-proxy-pub"
    name: str = ""           # Display name for sidebar (default: "MQTT Publishing")


@dataclass
class Config:
    inverters: list[InverterEntry] = field(default_factory=lambda: [InverterEntry()])
    gateways: dict[str, list[GatewayConfig]] = field(default_factory=dict)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    webapp: WebappConfig = field(default_factory=WebappConfig)
    venus: VenusConfig = field(default_factory=VenusConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    mqtt_publish: MqttPublishConfig = field(default_factory=MqttPublishConfig)
    virtual_inverter: VirtualInverterConfig = field(default_factory=VirtualInverterConfig)
    auto_throttle: bool = False
    auto_throttle_preset: str = "balanced"
    log_level: str = "INFO"

    @property
    def inverter(self) -> InverterEntry:
        """Backward compatibility: return first inverter entry."""
        return self.inverters[0] if self.inverters else InverterEntry()


def load_config(path: str | None = None) -> Config:
    """Load config from YAML file. Missing file or missing keys use defaults.

    Supports typed multi-inverter entries (solaredge, opendtu) and gateway configs.
    Old single-inverter ``inverter:`` format is ignored (fresh config only).
    """
    config_path = path or DEFAULT_CONFIG_PATH
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}

    # --- Build inverters list ---
    raw_inverters = data.get("inverters", [])
    if raw_inverters:
        inverters = [
            InverterEntry(**{
                k: v for k, v in entry.items()
                if k in InverterEntry.__dataclass_fields__
            })
            for entry in raw_inverters
        ]
    else:
        inverters = [InverterEntry()]

    # --- Build gateways dict ---
    raw_gateways = data.get("gateways", {})
    gateways: dict[str, list[GatewayConfig]] = {}
    for gw_type, gw_list in raw_gateways.items():
        if isinstance(gw_list, list):
            gateways[gw_type] = [
                GatewayConfig(**{
                    k: v for k, v in gw.items()
                    if k in GatewayConfig.__dataclass_fields__
                })
                for gw in gw_list
                if isinstance(gw, dict)
            ]

    config = Config(
        inverters=inverters,
        gateways=gateways,
        proxy=ProxyConfig(**{
            k: v for k, v in data.get("proxy", {}).items()
            if k in ProxyConfig.__dataclass_fields__
        }),
        night_mode=NightModeConfig(**{
            k: v for k, v in data.get("night_mode", {}).items()
            if k in NightModeConfig.__dataclass_fields__
        }),
        webapp=WebappConfig(**{
            k: v for k, v in data.get("webapp", {}).items()
            if k in WebappConfig.__dataclass_fields__
        }),
        venus=VenusConfig(**{
            k: v for k, v in data.get("venus", {}).items()
            if k in VenusConfig.__dataclass_fields__
        }),
        scanner=ScannerConfig(**{
            k: v for k, v in data.get("scanner", {}).items()
            if k in ScannerConfig.__dataclass_fields__
        }),
        mqtt_publish=MqttPublishConfig(**{
            k: v for k, v in data.get("mqtt_publish", {}).items()
            if k in MqttPublishConfig.__dataclass_fields__
        }),
        virtual_inverter=VirtualInverterConfig(**{
            k: v for k, v in data.get("virtual_inverter", {}).items()
            if k in VirtualInverterConfig.__dataclass_fields__
        }),
        auto_throttle=data.get("auto_throttle", False),
        auto_throttle_preset=data.get("auto_throttle_preset", "balanced") if data.get("auto_throttle_preset", "balanced") in AUTO_THROTTLE_PRESETS else "balanced",
        log_level=data.get("log_level", "INFO"),
    )

    return config


def get_gateway_for_inverter(config: Config, entry: InverterEntry) -> GatewayConfig | None:
    """Return the GatewayConfig matching an opendtu inverter's gateway_host.

    Returns None for non-opendtu types or if no matching gateway is found.
    """
    if entry.type != "opendtu":
        return None
    for gw in config.gateways.get("opendtu", []):
        if gw.host == entry.gateway_host:
            return gw
    return None


def get_active_inverter(config: Config) -> InverterEntry | None:
    """Return the first enabled inverter entry, or None if all disabled."""
    for entry in config.inverters:
        if entry.enabled:
            return entry
    return None


def validate_inverter_config(host: str, port: int, unit_id: int) -> str | None:
    """Validate inverter connection parameters.

    Returns None on success, error string on failure.
    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"Invalid IP address: {host}"

    if not (1 <= port <= 65535):
        return f"Port must be 1-65535, got {port}"

    if not (0 <= unit_id <= 247):
        return f"Unit ID must be 0-247, got {unit_id}"

    return None


def validate_venus_config(host: str, port: int) -> str | None:
    """Validate Venus OS MQTT connection parameters. Returns None on success."""
    if not host:
        return None  # Empty host = not configured, which is valid
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"Invalid IP address: {host}"
    if not (1 <= port <= 65535):
        return f"Port must be 1-65535, got {port}"
    return None


def save_config(config_path: str, config: Config) -> None:
    """Save config to YAML file atomically using temp file + os.replace."""
    data = asdict(config)
    config_dir = os.path.dirname(os.path.abspath(config_path))
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
