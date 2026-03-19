"""Tests for YAML configuration loading with defaults and overrides."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_load_config_defaults(tmp_path: Path):
    """load_config() with nonexistent file returns Config with all defaults."""
    from venus_os_fronius_proxy.config import load_config

    cfg = load_config(str(tmp_path / "nonexistent.yaml"))

    assert cfg.inverter.host == "192.168.3.18"
    assert cfg.inverter.port == 1502
    assert cfg.inverter.unit_id == 1
    assert cfg.proxy.host == "0.0.0.0"
    assert cfg.proxy.port == 502
    assert cfg.proxy.poll_interval == 1.0
    assert cfg.proxy.staleness_timeout == 30.0
    assert cfg.night_mode.threshold_seconds == 300.0
    assert cfg.log_level == "INFO"


def test_load_config_partial_override(tmp_path: Path):
    """YAML with partial inverter override keeps other defaults."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text('inverter:\n  host: "10.0.0.1"\n')

    cfg = load_config(str(cfg_file))

    assert cfg.inverter.host == "10.0.0.1"
    assert cfg.inverter.port == 1502  # default preserved
    assert cfg.proxy.port == 502      # default preserved


def test_load_config_log_level(tmp_path: Path):
    """YAML with log_level override returns correct level."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text('log_level: "DEBUG"\n')

    cfg = load_config(str(cfg_file))

    assert cfg.log_level == "DEBUG"


def test_load_config_night_mode(tmp_path: Path):
    """YAML with night_mode override returns correct threshold."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("night_mode:\n  threshold_seconds: 600.0\n")

    cfg = load_config(str(cfg_file))

    assert cfg.night_mode.threshold_seconds == 600.0


def test_venus_config_defaults():
    """VenusConfig() has host="", port=1883, portal_id=""."""
    from venus_os_fronius_proxy.config import VenusConfig

    vc = VenusConfig()
    assert vc.host == ""
    assert vc.port == 1883
    assert vc.portal_id == ""


def test_load_config_venus_section(tmp_path: Path):
    """load_config with venus section in YAML populates VenusConfig fields."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'venus:\n  host: "10.0.0.1"\n  port: 1884\n  portal_id: "abc123"\n'
    )

    cfg = load_config(str(cfg_file))

    assert cfg.venus.host == "10.0.0.1"
    assert cfg.venus.port == 1884
    assert cfg.venus.portal_id == "abc123"


def test_load_config_missing_venus(tmp_path: Path):
    """load_config without venus section uses VenusConfig defaults (no crash)."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text('inverter:\n  host: "10.0.0.1"\n')

    cfg = load_config(str(cfg_file))

    assert cfg.venus.host == ""
    assert cfg.venus.port == 1883
    assert cfg.venus.portal_id == ""
