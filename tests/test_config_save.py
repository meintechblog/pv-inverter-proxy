"""Tests for config save, validate, and plugin reconfigure."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


def test_webapp_config_defaults():
    """WebappConfig has port field defaulting to 80."""
    from venus_os_fronius_proxy.config import WebappConfig

    wc = WebappConfig()
    assert wc.port == 80


def test_config_has_webapp_field():
    """Config dataclass includes webapp field of type WebappConfig."""
    from venus_os_fronius_proxy.config import Config, WebappConfig

    cfg = Config()
    assert isinstance(cfg.webapp, WebappConfig)
    assert cfg.webapp.port == 80


def test_save_config_roundtrip(tmp_path: Path):
    """save_config writes YAML that load_config can reload identically."""
    from venus_os_fronius_proxy.config import Config, load_config, save_config

    original = Config()
    original.inverter.host = "10.0.0.99"
    original.inverter.port = 1503
    original.inverter.unit_id = 5
    original.log_level = "DEBUG"

    config_path = str(tmp_path / "config.yaml")
    save_config(config_path, original)

    reloaded = load_config(config_path)
    assert reloaded.inverter.host == "10.0.0.99"
    assert reloaded.inverter.port == 1503
    assert reloaded.inverter.unit_id == 5
    assert reloaded.log_level == "DEBUG"
    assert reloaded.proxy.port == 502  # default preserved
    assert reloaded.webapp.port == 80  # default preserved


def test_save_config_atomic(tmp_path: Path):
    """save_config uses os.replace for atomic write."""
    from venus_os_fronius_proxy.config import Config, save_config

    config_path = str(tmp_path / "config.yaml")
    with patch("venus_os_fronius_proxy.config.os.replace") as mock_replace:
        # Allow normal write flow but intercept os.replace
        mock_replace.side_effect = lambda src, dst: Path(src).rename(dst)
        save_config(config_path, Config())
        mock_replace.assert_called_once()


def test_validate_inverter_config_valid():
    """validate_inverter_config returns None for valid input."""
    from venus_os_fronius_proxy.config import validate_inverter_config

    result = validate_inverter_config("192.168.1.1", 1502, 1)
    assert result is None


def test_validate_inverter_config_invalid_ip():
    """validate_inverter_config returns error for invalid IP."""
    from venus_os_fronius_proxy.config import validate_inverter_config

    result = validate_inverter_config("not-an-ip", 1502, 1)
    assert result is not None
    assert isinstance(result, str)


def test_validate_inverter_config_port_out_of_range():
    """validate_inverter_config returns error for port out of range."""
    from venus_os_fronius_proxy.config import validate_inverter_config

    assert validate_inverter_config("192.168.1.1", 0, 1) is not None
    assert validate_inverter_config("192.168.1.1", 70000, 1) is not None


def test_validate_inverter_config_unit_id_out_of_range():
    """validate_inverter_config returns error for unit_id out of range."""
    from venus_os_fronius_proxy.config import validate_inverter_config

    assert validate_inverter_config("192.168.1.1", 1502, 0) is not None
    assert validate_inverter_config("192.168.1.1", 1502, 248) is not None


def test_inverter_plugin_reconfigure_is_abstract():
    """InverterPlugin.reconfigure is abstract method."""
    from venus_os_fronius_proxy.plugin import InverterPlugin
    import inspect

    assert hasattr(InverterPlugin, "reconfigure")
    # Check it's in the abstract methods set
    assert "reconfigure" in InverterPlugin.__abstractmethods__


@pytest.mark.asyncio
async def test_solaredge_reconfigure():
    """SolarEdgePlugin.reconfigure calls close and updates attributes."""
    from venus_os_fronius_proxy.plugins.solaredge import SolarEdgePlugin

    plugin = SolarEdgePlugin(host="1.2.3.4", port=1502, unit_id=1)
    plugin.close = AsyncMock()

    await plugin.reconfigure("10.0.0.1", 1503, 2)

    plugin.close.assert_awaited_once()
    assert plugin.host == "10.0.0.1"
    assert plugin.port == 1503
    assert plugin.unit_id == 2
