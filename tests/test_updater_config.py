"""Tests for the Phase 46 minimal UpdateConfig dataclass (CFG-02, D-04/D-05/D-06).

These tests pin the exact 3-field contract for ``UpdateConfig`` and the
behavior of ``load_update_config`` / ``save_update_config`` /
``validate_update_config_patch``.

Phase 46 intentionally ships only three fields:
    github_repo: str
    check_interval_hours: int
    auto_install: bool

The full config schema (CFG-01) waits for Phase 47.

The module uses direct YAML read-modify-write under an ``update:`` key so
it can share the same ``config.yaml`` as the existing ``Config`` dataclass
without colliding with its sibling keys (``inverters:``, ``venus:`` …).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Dataclass contract (D-04)
# ---------------------------------------------------------------------------


def test_default_values_match_d04():
    """Defaults match the inline D-04 specification verbatim."""
    from pv_inverter_proxy.updater.config import UpdateConfig

    uc = UpdateConfig()
    assert uc.github_repo == "hulki/pv-inverter-proxy"
    assert uc.check_interval_hours == 24
    assert uc.auto_install is False


def test_dataclass_has_exactly_three_fields():
    """D-04 locks the schema to exactly three fields. No silent drift."""
    from pv_inverter_proxy.updater.config import UpdateConfig

    fields = dataclasses.fields(UpdateConfig)
    names = {f.name for f in fields}
    assert len(fields) == 3, f"expected 3 fields, got {len(fields)}: {names}"
    assert names == {"github_repo", "check_interval_hours", "auto_install"}


def test_default_update_config_constant_is_a_default_instance():
    from pv_inverter_proxy.updater.config import (
        DEFAULT_UPDATE_CONFIG,
        UpdateConfig,
    )

    assert isinstance(DEFAULT_UPDATE_CONFIG, UpdateConfig)
    assert DEFAULT_UPDATE_CONFIG == UpdateConfig()


def test_allowed_keys_constant_matches_dataclass_fields():
    from pv_inverter_proxy.updater.config import (
        ALLOWED_UPDATE_CONFIG_KEYS,
        UpdateConfig,
    )

    names = {f.name for f in dataclasses.fields(UpdateConfig)}
    assert set(ALLOWED_UPDATE_CONFIG_KEYS) == names


# ---------------------------------------------------------------------------
# load_update_config: read-side roundtrip + defaults
# ---------------------------------------------------------------------------


def test_load_update_config_missing_file_returns_defaults(tmp_path: Path):
    from pv_inverter_proxy.updater.config import UpdateConfig, load_update_config

    missing = tmp_path / "nope.yaml"
    uc = load_update_config(str(missing))
    assert uc == UpdateConfig()


def test_load_update_config_missing_section_returns_defaults(tmp_path: Path):
    from pv_inverter_proxy.updater.config import UpdateConfig, load_update_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"inverters": [], "log_level": "INFO"}))
    uc = load_update_config(str(config_path))
    assert uc == UpdateConfig()


def test_load_update_config_partial_section_fills_defaults(tmp_path: Path):
    from pv_inverter_proxy.updater.config import load_update_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"update": {"check_interval_hours": 6}})
    )
    uc = load_update_config(str(config_path))
    assert uc.check_interval_hours == 6
    # other fields fall back to defaults
    assert uc.github_repo == "hulki/pv-inverter-proxy"
    assert uc.auto_install is False


def test_load_update_config_full_section_roundtrip(tmp_path: Path):
    from pv_inverter_proxy.updater.config import load_update_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "update": {
                    "github_repo": "forked/pv-inverter-proxy",
                    "check_interval_hours": 12,
                    "auto_install": True,
                }
            }
        )
    )
    uc = load_update_config(str(config_path))
    assert uc.github_repo == "forked/pv-inverter-proxy"
    assert uc.check_interval_hours == 12
    assert uc.auto_install is True


def test_load_update_config_rejects_invalid_types_and_uses_defaults(
    tmp_path: Path,
):
    """Garbage values in YAML must not crash — fall back to defaults per field."""
    from pv_inverter_proxy.updater.config import load_update_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "update": {
                    "github_repo": 42,  # wrong type
                    "check_interval_hours": -3,  # non-positive
                    "auto_install": "yes",  # not a bool
                }
            }
        )
    )
    uc = load_update_config(str(config_path))
    assert uc.github_repo == "hulki/pv-inverter-proxy"
    assert uc.check_interval_hours == 24
    assert uc.auto_install is False


# ---------------------------------------------------------------------------
# save_update_config: write-side preservation + isolation
# ---------------------------------------------------------------------------


def test_save_update_config_preserves_other_top_level_keys(tmp_path: Path):
    """save_update_config must not clobber ``inverters:``, ``venus:`` etc."""
    from pv_inverter_proxy.updater.config import (
        UpdateConfig,
        save_update_config,
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "inverters": [
                    {"host": "10.0.0.99", "port": 1502, "unit_id": 1}
                ],
                "venus": {"host": "192.168.3.5", "port": 1883},
                "log_level": "DEBUG",
            }
        )
    )
    save_update_config(
        str(config_path),
        UpdateConfig(
            github_repo="o/r",
            check_interval_hours=3,
            auto_install=True,
        ),
    )
    reloaded = yaml.safe_load(config_path.read_text())
    assert reloaded["inverters"] == [
        {"host": "10.0.0.99", "port": 1502, "unit_id": 1}
    ]
    assert reloaded["venus"] == {"host": "192.168.3.5", "port": 1883}
    assert reloaded["log_level"] == "DEBUG"
    assert reloaded["update"] == {
        "github_repo": "o/r",
        "check_interval_hours": 3,
        "auto_install": True,
    }


def test_save_update_config_writes_exactly_three_keys(tmp_path: Path):
    from pv_inverter_proxy.updater.config import (
        UpdateConfig,
        save_update_config,
    )

    config_path = tmp_path / "config.yaml"
    save_update_config(str(config_path), UpdateConfig())
    reloaded = yaml.safe_load(config_path.read_text())
    assert set(reloaded["update"].keys()) == {
        "github_repo",
        "check_interval_hours",
        "auto_install",
    }


def test_save_update_config_creates_file_when_missing(tmp_path: Path):
    from pv_inverter_proxy.updater.config import (
        UpdateConfig,
        load_update_config,
        save_update_config,
    )

    config_path = tmp_path / "fresh.yaml"
    save_update_config(
        str(config_path),
        UpdateConfig(github_repo="a/b", check_interval_hours=48, auto_install=True),
    )
    assert config_path.exists()
    uc = load_update_config(str(config_path))
    assert uc.github_repo == "a/b"
    assert uc.check_interval_hours == 48
    assert uc.auto_install is True


def test_save_then_load_roundtrip(tmp_path: Path):
    from pv_inverter_proxy.updater.config import (
        UpdateConfig,
        load_update_config,
        save_update_config,
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"proxy": {"port": 502}}))
    original = UpdateConfig(
        github_repo="x/y", check_interval_hours=7, auto_install=False
    )
    save_update_config(str(config_path), original)
    reloaded = load_update_config(str(config_path))
    assert reloaded == original
    # Sibling still present
    assert yaml.safe_load(config_path.read_text())["proxy"] == {"port": 502}


# ---------------------------------------------------------------------------
# validate_update_config_patch: API validation helper
# ---------------------------------------------------------------------------


def test_validate_patch_accepts_subset_of_three_keys():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"check_interval_hours": 6})
    assert ok is True
    assert err is None

    ok, err = validate_update_config_patch(
        {"github_repo": "o/r", "auto_install": True}
    )
    assert ok is True
    assert err is None

    ok, err = validate_update_config_patch(
        {
            "github_repo": "o/r",
            "check_interval_hours": 12,
            "auto_install": False,
        }
    )
    assert ok is True
    assert err is None


def test_validate_patch_rejects_unknown_key():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch(
        {"github_repo": "o/r", "release_channel": "beta"}
    )
    assert ok is False
    assert err is not None
    assert "release_channel" in err


def test_validate_patch_rejects_empty_patch_allowed_or_not():
    """An empty object is a no-op patch — neither valid nor invalid per spec.

    The webapp layer separately decides whether to call save when the patch
    is empty. Here we just assert the helper does NOT crash and returns a
    stable result. We pin the behavior to ``accepted``: an empty patch is
    a legal subset of the 3 keys (the subset of zero keys).
    """
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({})
    assert ok is True
    assert err is None


def test_validate_patch_rejects_non_dict():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch([])  # type: ignore[arg-type]
    assert ok is False
    assert err is not None


def test_validate_patch_rejects_empty_github_repo():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"github_repo": ""})
    assert ok is False
    assert err is not None
    assert "github_repo" in err

    ok, err = validate_update_config_patch({"github_repo": "   "})
    assert ok is False


def test_validate_patch_rejects_negative_check_interval():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"check_interval_hours": -1})
    assert ok is False
    assert err is not None
    assert "check_interval_hours" in err


def test_validate_patch_rejects_zero_check_interval():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"check_interval_hours": 0})
    assert ok is False
    assert err is not None


def test_validate_patch_rejects_non_int_check_interval():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"check_interval_hours": "6"})
    assert ok is False
    assert err is not None

    ok, err = validate_update_config_patch({"check_interval_hours": 6.5})
    assert ok is False
    assert err is not None


def test_validate_patch_rejects_bool_as_check_interval():
    """``bool`` is a subclass of ``int`` in Python — the validator must reject it."""
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"check_interval_hours": True})
    assert ok is False
    assert err is not None


def test_validate_patch_rejects_non_bool_auto_install():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"auto_install": "yes"})
    assert ok is False
    assert err is not None
    assert "auto_install" in err

    ok, err = validate_update_config_patch({"auto_install": 1})
    assert ok is False
    assert err is not None


def test_validate_patch_rejects_non_string_github_repo():
    from pv_inverter_proxy.updater.config import validate_update_config_patch

    ok, err = validate_update_config_patch({"github_repo": 42})
    assert ok is False
    assert err is not None
