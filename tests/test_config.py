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


# --- Multi-inverter config tests ---


def test_inverter_entry_fields():
    """InverterEntry has all identity fields with correct defaults."""
    from venus_os_fronius_proxy.config import InverterEntry

    entry = InverterEntry()
    assert entry.host == "192.168.3.18"
    assert entry.port == 1502
    assert entry.unit_id == 1
    assert entry.enabled is True
    assert isinstance(entry.id, str)
    assert len(entry.id) == 12
    assert entry.manufacturer == ""
    assert entry.model == ""
    assert entry.serial == ""
    assert entry.firmware_version == ""


def test_inverter_entry_unique_ids():
    """Two InverterEntry instances have different id values."""
    from venus_os_fronius_proxy.config import InverterEntry

    a = InverterEntry()
    b = InverterEntry()
    assert a.id != b.id


def test_config_inverters_is_list():
    """Config().inverters is a list containing one InverterEntry with default host."""
    from venus_os_fronius_proxy.config import Config, InverterEntry

    cfg = Config()
    assert isinstance(cfg.inverters, list)
    assert len(cfg.inverters) == 1
    assert isinstance(cfg.inverters[0], InverterEntry)
    assert cfg.inverters[0].host == "192.168.3.18"


def test_migration_old_format(tmp_path: Path):
    """load_config on old single-inverter YAML migrates to inverters list."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'inverter:\n  host: "1.2.3.4"\n  port: 502\n  unit_id: 3\n'
    )

    cfg = load_config(str(cfg_file))
    assert isinstance(cfg.inverters, list)
    assert len(cfg.inverters) == 1
    entry = cfg.inverters[0]
    assert entry.host == "1.2.3.4"
    assert entry.port == 502
    assert entry.unit_id == 3
    assert entry.enabled is True
    assert entry.manufacturer == ""
    assert entry.model == ""
    assert entry.serial == ""
    assert entry.firmware_version == ""


def test_migration_preserves_values(tmp_path: Path):
    """Migrated entry preserves all original host/port/unit_id exactly."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'inverter:\n  host: "10.20.30.40"\n  port: 1503\n  unit_id: 7\n'
    )

    cfg = load_config(str(cfg_file))
    entry = cfg.inverters[0]
    assert entry.host == "10.20.30.40"
    assert entry.port == 1503
    assert entry.unit_id == 7


def test_migration_writeback(tmp_path: Path):
    """After migration, YAML file on disk contains inverters key, not inverter key."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'inverter:\n  host: "1.2.3.4"\n  port: 502\n  unit_id: 3\n'
    )

    load_config(str(cfg_file))

    content = cfg_file.read_text()
    assert "inverters:" in content
    assert "inverter:" not in content.replace("inverters:", "")


def test_migration_backup(tmp_path: Path):
    """After migration, a .bak file exists with original content."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    original_content = 'inverter:\n  host: "1.2.3.4"\n  port: 502\n  unit_id: 3\n'
    cfg_file.write_text(original_content)

    load_config(str(cfg_file))

    bak_file = tmp_path / "config.yaml.bak"
    assert bak_file.exists()
    assert bak_file.read_text() == original_content


def test_migration_no_double_run(tmp_path: Path):
    """Loading already-migrated file does NOT create another .bak or re-migrate."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'inverter:\n  host: "1.2.3.4"\n  port: 502\n  unit_id: 3\n'
    )

    # First load triggers migration
    load_config(str(cfg_file))
    bak_file = tmp_path / "config.yaml.bak"
    assert bak_file.exists()
    bak_mtime = bak_file.stat().st_mtime

    # Modify bak content to detect if it gets overwritten
    bak_file.write_text("SENTINEL")

    # Second load should not re-migrate
    load_config(str(cfg_file))
    assert bak_file.read_text() == "SENTINEL"  # Not overwritten


def test_fresh_install_default(tmp_path: Path):
    """load_config on nonexistent file returns Config with one InverterEntry."""
    from venus_os_fronius_proxy.config import load_config, InverterEntry

    cfg = load_config(str(tmp_path / "nonexistent.yaml"))
    assert isinstance(cfg.inverters, list)
    assert len(cfg.inverters) == 1
    assert isinstance(cfg.inverters[0], InverterEntry)


def test_active_inverter_first_enabled():
    """get_active_inverter returns first entry where enabled=True."""
    from venus_os_fronius_proxy.config import Config, InverterEntry, get_active_inverter

    cfg = Config(inverters=[
        InverterEntry(host="1.1.1.1", enabled=True),
        InverterEntry(host="2.2.2.2", enabled=True),
    ])
    result = get_active_inverter(cfg)
    assert result is not None
    assert result.host == "1.1.1.1"


def test_active_inverter_skip_disabled():
    """With entries [disabled, enabled], returns the second."""
    from venus_os_fronius_proxy.config import Config, InverterEntry, get_active_inverter

    cfg = Config(inverters=[
        InverterEntry(host="1.1.1.1", enabled=False),
        InverterEntry(host="2.2.2.2", enabled=True),
    ])
    result = get_active_inverter(cfg)
    assert result is not None
    assert result.host == "2.2.2.2"


def test_active_inverter_none_enabled():
    """All disabled returns None."""
    from venus_os_fronius_proxy.config import Config, InverterEntry, get_active_inverter

    cfg = Config(inverters=[
        InverterEntry(host="1.1.1.1", enabled=False),
        InverterEntry(host="2.2.2.2", enabled=False),
    ])
    result = get_active_inverter(cfg)
    assert result is None


def test_load_multi_inverter_format(tmp_path: Path):
    """YAML with inverters list loads correctly as list of InverterEntry."""
    from venus_os_fronius_proxy.config import load_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'inverters:\n'
        '  - host: "1.1.1.1"\n'
        '    port: 502\n'
        '    unit_id: 1\n'
        '    enabled: true\n'
        '    id: "aabbccddee11"\n'
        '  - host: "2.2.2.2"\n'
        '    port: 1502\n'
        '    unit_id: 2\n'
        '    enabled: false\n'
        '    id: "aabbccddee22"\n'
    )

    cfg = load_config(str(cfg_file))
    assert len(cfg.inverters) == 2
    assert cfg.inverters[0].host == "1.1.1.1"
    assert cfg.inverters[0].id == "aabbccddee11"
    assert cfg.inverters[1].host == "2.2.2.2"
    assert cfg.inverters[1].enabled is False
