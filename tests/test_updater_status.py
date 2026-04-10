"""Unit tests for pv_inverter_proxy.updater.status (HEALTH-09).

Hermetic — every test uses pytest tmp_path. No touching
/etc/pv-inverter-proxy/.

Covers the defensive-read guarantee: load_status never raises, regardless
of file state (missing, empty, truncated, corrupt, wrong schema, wrong
top-level type).
"""
from __future__ import annotations

import json
from pathlib import Path

from pv_inverter_proxy.updater import status as status_mod
from pv_inverter_proxy.updater.status import (
    STATUS_FILE_PATH,
    UpdateStatus,
    current_phase,
    load_status,
)


# ---------------------------------------------------------------------------
# Missing file / IO errors
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "nonexistent.json"
    assert not target.exists()
    status = load_status(path=target)
    assert isinstance(status, UpdateStatus)
    assert status.current is None
    assert status.history == []
    assert status.schema_version == 1


def test_load_unreadable_directory_returns_idle(tmp_path: Path) -> None:
    # Passing a directory as the file path → OSError on read_text
    target = tmp_path  # directory, not file
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


# ---------------------------------------------------------------------------
# Corrupt / partial content
# ---------------------------------------------------------------------------


def test_load_empty_file_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text("")
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


def test_load_partial_write_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text('{"curre')  # truncated mid-key
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


def test_load_garbage_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text("not json at all")
    status = load_status(path=target)
    assert status.current is None


# ---------------------------------------------------------------------------
# Wrong top-level type
# ---------------------------------------------------------------------------


def test_load_json_list_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text("[1, 2, 3]")
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


def test_load_json_string_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text('"just a string"')
    status = load_status(path=target)
    assert status.current is None


def test_load_json_null_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text("null")
    status = load_status(path=target)
    assert status.current is None


# ---------------------------------------------------------------------------
# Schema version handling
# ---------------------------------------------------------------------------


def test_load_missing_schema_version_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text(json.dumps({"current": None, "history": []}))
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


def test_load_unsupported_schema_version_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text(
        json.dumps({"schema_version": 2, "current": {"phase": "extract"}, "history": []})
    )
    status = load_status(path=target)
    assert status.current is None
    assert status.history == []


# ---------------------------------------------------------------------------
# Valid schema
# ---------------------------------------------------------------------------


def test_load_valid_running_status(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    payload = {
        "schema_version": 1,
        "current": {
            "nonce": "11111111-2222-4333-8444-555555555555",
            "phase": "pip_install",
            "target_sha": "0" * 40,
            "old_sha": "1" * 40,
            "started_at": "2026-04-10T14:22:00Z",
        },
        "history": [
            {"phase": "trigger_received", "at": "2026-04-10T14:22:00Z"},
            {"phase": "backup", "at": "2026-04-10T14:22:01Z"},
            {"phase": "extract", "at": "2026-04-10T14:22:02Z"},
        ],
    }
    target.write_text(json.dumps(payload))
    status = load_status(path=target)
    assert status.current is not None
    assert status.current["phase"] == "pip_install"
    assert status.current["nonce"] == "11111111-2222-4333-8444-555555555555"
    assert len(status.history) == 3
    assert status.history[2]["phase"] == "extract"
    assert status.schema_version == 1


def test_load_valid_idle_status(tmp_path: Path) -> None:
    """current=None with a populated history is valid (last update done)."""
    target = tmp_path / "update-status.json"
    payload = {
        "schema_version": 1,
        "current": None,
        "history": [{"phase": "done", "at": "2026-04-10T14:25:00Z"}],
    }
    target.write_text(json.dumps(payload))
    status = load_status(path=target)
    assert status.current is None
    assert len(status.history) == 1


def test_load_current_not_dict_returns_idle(tmp_path: Path) -> None:
    """current=42 is invalid; defensive load returns idle."""
    target = tmp_path / "update-status.json"
    target.write_text(json.dumps({"schema_version": 1, "current": 42, "history": []}))
    status = load_status(path=target)
    assert status.current is None


def test_load_history_not_list_returns_idle(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    target.write_text(
        json.dumps({"schema_version": 1, "current": None, "history": "oops"})
    )
    status = load_status(path=target)
    assert status.history == []


def test_load_missing_history_defaults_empty(tmp_path: Path) -> None:
    """If history key is missing but schema is valid, default to []."""
    target = tmp_path / "update-status.json"
    target.write_text(json.dumps({"schema_version": 1, "current": None}))
    status = load_status(path=target)
    assert status.history == []


# ---------------------------------------------------------------------------
# current_phase helper
# ---------------------------------------------------------------------------


def test_current_phase_idle_when_current_none() -> None:
    status = UpdateStatus(current=None, history=[])
    assert current_phase(status) == "idle"


def test_current_phase_returns_phase_string() -> None:
    status = UpdateStatus(current={"phase": "pip_install"}, history=[])
    assert current_phase(status) == "pip_install"


def test_current_phase_idle_when_phase_missing() -> None:
    status = UpdateStatus(current={"nonce": "abc"}, history=[])
    assert current_phase(status) == "idle"


# ---------------------------------------------------------------------------
# Never-raises contract (parametric fuzz)
# ---------------------------------------------------------------------------


def test_load_never_raises_for_arbitrary_bytes(tmp_path: Path) -> None:
    target = tmp_path / "update-status.json"
    # A grab-bag of pathological contents
    payloads = [
        b"\x00\x00\x00",
        b'{"schema_version": 1, "current": ',  # truncated
        b"\xff\xfe\xfd",  # invalid utf-8
        b"{" * 10000,
        b"],,,",
    ]
    for p in payloads:
        target.write_bytes(p)
        status = load_status(path=target)  # must not raise
        assert isinstance(status, UpdateStatus)
        assert status.current is None


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_module_constants_match_spec() -> None:
    assert STATUS_FILE_PATH == Path("/etc/pv-inverter-proxy/update-status.json")
    assert status_mod.STATUS_FILE_PATH == STATUS_FILE_PATH
