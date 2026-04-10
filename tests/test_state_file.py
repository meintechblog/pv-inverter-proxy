"""Unit tests for state_file.py (SAFETY-09).

Tests cover:
- Load defaults on missing / corrupt / wrong-type / wrong-schema / empty files
- Save-then-load round-trip
- Forward-compat: unknown keys are ignored
- Atomic write semantics (no leftover .tmp on success)
- File mode 0644 after save
- Parent-missing raises FileNotFoundError (real install bug, not swallowed)
- is_power_limit_fresh staleness gate behavior
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from pv_inverter_proxy.state_file import (
    PersistedState,
    is_power_limit_fresh,
    load_state,
    save_state,
)


def test_load_state_missing_file_returns_defaults(tmp_path: Path):
    state = load_state(tmp_path / "state.json")
    assert state == PersistedState()
    assert state.power_limit_pct is None
    assert state.power_limit_set_at is None
    assert state.night_mode_active is False
    assert state.night_mode_set_at is None
    assert state.schema_version == 1


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    original = PersistedState(
        power_limit_pct=42.5,
        power_limit_set_at=1700000000.0,
        night_mode_active=True,
        night_mode_set_at=1700000100.0,
    )
    save_state(original, path)
    loaded = load_state(path)
    assert loaded == original


def test_load_state_corrupt_json_returns_defaults(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json")
    state = load_state(path)
    assert state == PersistedState()


def test_load_state_json_array_returns_defaults(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]")
    state = load_state(path)
    assert state == PersistedState()


def test_load_state_wrong_schema_version_returns_defaults(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "schema_version": 99,
        "power_limit_pct": 50.0,
    }))
    state = load_state(path)
    assert state == PersistedState()


def test_load_state_ignores_unknown_keys(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "power_limit_pct": 75.0,
        "power_limit_set_at": 1700000000.0,
        "unknown_future_field": "whatever",
        "another_one": 123,
    }))
    state = load_state(path)
    assert state.power_limit_pct == 75.0
    assert state.power_limit_set_at == 1700000000.0
    assert state.schema_version == 1


def test_save_state_file_mode_0644(tmp_path: Path):
    path = tmp_path / "state.json"
    save_state(PersistedState(power_limit_pct=10.0), path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o644


def test_save_state_parent_missing_raises(tmp_path: Path):
    path = tmp_path / "nonexistent_dir" / "state.json"
    with pytest.raises(FileNotFoundError):
        save_state(PersistedState(), path)


def test_save_state_no_leftover_tmp_file(tmp_path: Path):
    path = tmp_path / "state.json"
    save_state(PersistedState(power_limit_pct=33.3), path)
    assert path.exists()
    assert not (tmp_path / "state.json.tmp").exists()


def test_is_power_limit_fresh_within_window():
    state = PersistedState(
        power_limit_pct=50.0,
        power_limit_set_at=1_000_000.0,
    )
    # command_timeout = 900s, half = 450s, age = 100s -> fresh
    assert is_power_limit_fresh(state, 900.0, now=1_000_100.0) is True


def test_is_power_limit_fresh_outside_window():
    state = PersistedState(
        power_limit_pct=50.0,
        power_limit_set_at=1_000_000.0,
    )
    # age = 500s > 450s -> stale
    assert is_power_limit_fresh(state, 900.0, now=1_000_500.0) is False


def test_is_power_limit_fresh_none_limit():
    state = PersistedState(power_limit_set_at=1_000_000.0)  # pct missing
    assert is_power_limit_fresh(state, 900.0, now=1_000_001.0) is False


def test_load_state_empty_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("")
    state = load_state(path)
    assert state == PersistedState()
