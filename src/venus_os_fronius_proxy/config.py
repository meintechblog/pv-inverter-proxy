"""YAML configuration loading with dataclass schema and sensible defaults.

Loads configuration from a YAML file (default: /etc/venus-os-fronius-proxy/config.yaml).
Missing file or missing keys silently use defaults. Unknown keys are ignored.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

log = structlog.get_logger()


DEFAULT_CONFIG_PATH = "/etc/venus-os-fronius-proxy/config.yaml"


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


# Backward compatibility alias
InverterConfig = InverterEntry


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


@dataclass
class Config:
    inverters: list[InverterEntry] = field(default_factory=lambda: [InverterEntry()])
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    webapp: WebappConfig = field(default_factory=WebappConfig)
    venus: VenusConfig = field(default_factory=VenusConfig)
    log_level: str = "INFO"

    @property
    def inverter(self) -> InverterEntry:
        """Backward compatibility: return first inverter entry."""
        return self.inverters[0] if self.inverters else InverterEntry()


def load_config(path: str | None = None) -> Config:
    """Load config from YAML file. Missing file or missing keys use defaults.

    Automatically migrates old single-inverter format (``inverter:``) to
    multi-inverter list (``inverters:``), creating a ``.bak`` backup.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}

    # --- Migration: single inverter -> inverters list ---
    migrated = False
    if "inverter" in data and "inverters" not in data:
        old = data.pop("inverter") or {}
        entry_dict = {
            "host": old.get("host", "192.168.3.18"),
            "port": old.get("port", 1502),
            "unit_id": old.get("unit_id", 1),
            "enabled": True,
            "id": _generate_id(),
            "manufacturer": "",
            "model": "",
            "serial": "",
            "firmware_version": "",
        }
        data["inverters"] = [entry_dict]
        migrated = True

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

    config = Config(
        inverters=inverters,
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
        log_level=data.get("log_level", "INFO"),
    )

    # --- Write back migrated config ---
    if migrated and os.path.exists(config_path):
        bak_path = config_path + ".bak"
        if not os.path.exists(bak_path):
            shutil.copy2(config_path, bak_path)
        save_config(config_path, config)
        log.info("config.migrated", config_path=config_path)

    return config


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

    if not (1 <= unit_id <= 247):
        return f"Unit ID must be 1-247, got {unit_id}"

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
    data = dataclasses.asdict(config)
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
