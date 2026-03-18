"""YAML configuration loading with dataclass schema and sensible defaults.

Loads configuration from a YAML file (default: /etc/venus-os-fronius-proxy/config.yaml).
Missing file or missing keys silently use defaults. Unknown keys are ignored.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = "/etc/venus-os-fronius-proxy/config.yaml"


@dataclass
class InverterConfig:
    host: str = "192.168.3.18"
    port: int = 1502
    unit_id: int = 1


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
class Config:
    inverter: InverterConfig = field(default_factory=InverterConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    webapp: WebappConfig = field(default_factory=WebappConfig)
    log_level: str = "INFO"


def load_config(path: str | None = None) -> Config:
    """Load config from YAML file. Missing file or missing keys use defaults."""
    config_path = path or DEFAULT_CONFIG_PATH
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}

    return Config(
        inverter=InverterConfig(**{
            k: v for k, v in data.get("inverter", {}).items()
            if k in InverterConfig.__dataclass_fields__
        }),
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
        log_level=data.get("log_level", "INFO"),
    )


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
