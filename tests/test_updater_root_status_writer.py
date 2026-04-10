"""Tests for updater_root.status_writer.

Covers HEALTH-09: monotonic phase progression, atomic write, mode 0644,
and defensive load_existing.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from pv_inverter_proxy.updater_root.status_writer import (
    PHASES,
    STATUS_FILE_MODE,
    StatusFileWriter,
)


class _FixedClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def status_path(tmp_path: Path) -> Path:
    return tmp_path / "update-status.json"


@pytest.fixture
def clock() -> _FixedClock:
    return _FixedClock()


@pytest.fixture
def writer(status_path: Path, clock: _FixedClock) -> StatusFileWriter:
    return StatusFileWriter(path=status_path, clock=clock)


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text())


def test_begin_writes_current(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    data = _read_json(status_path)
    assert data["current"]["nonce"] == "n1"
    assert data["current"]["target_sha"] == "a" * 40
    assert data["current"]["old_sha"] == "b" * 40
    assert data["current"]["phase"] == "trigger_received"
    assert len(data["history"]) == 1
    assert data["history"][0]["phase"] == "trigger_received"
    assert data["schema_version"] == 1


def test_write_phase_appends(writer: StatusFileWriter, status_path: Path, clock: _FixedClock) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    clock.advance(1)
    writer.write_phase("backup")
    clock.advance(1)
    writer.write_phase("extract")
    data = _read_json(status_path)
    history = [h["phase"] for h in data["history"]]
    assert history == ["trigger_received", "backup", "extract"]


def test_write_phase_updates_current(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    writer.write_phase("backup")
    writer.write_phase("extract")
    data = _read_json(status_path)
    assert data["current"]["phase"] == "extract"


def test_write_phase_error_field(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    writer.write_phase("rollback_starting", error="smoke import failed")
    data = _read_json(status_path)
    last = data["history"][-1]
    assert last["phase"] == "rollback_starting"
    assert last["error"] == "smoke import failed"


def test_finalize_sets_outcome(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    writer.write_phase("backup")
    writer.finalize("done")
    data = _read_json(status_path)
    assert data["current"]["phase"] == "done"
    assert data["history"][-1]["phase"] == "done"


def test_finalize_rollback_done(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    writer.finalize("rollback_done")
    data = _read_json(status_path)
    assert data["current"]["phase"] == "rollback_done"


def test_finalize_rollback_failed(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    writer.finalize("rollback_failed")
    data = _read_json(status_path)
    assert data["current"]["phase"] == "rollback_failed"


def test_atomic_write_no_partial(
    writer: StatusFileWriter,
    status_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    before = status_path.read_text()

    def boom(src, dst):  # noqa: ANN001
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        writer.write_phase("backup")
    # Original file content untouched
    assert status_path.read_text() == before


def test_mode_0644(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    mode = stat.S_IMODE(os.stat(status_path).st_mode)
    assert mode == STATUS_FILE_MODE
    assert mode == 0o644


def test_load_existing_missing_returns_none(writer: StatusFileWriter) -> None:
    assert writer.load_existing() is None


def test_load_existing_corrupt_returns_none(
    writer: StatusFileWriter, status_path: Path
) -> None:
    status_path.write_text("not json {{{")
    assert writer.load_existing() is None


def test_load_existing_wrong_type_returns_none(
    writer: StatusFileWriter, status_path: Path
) -> None:
    status_path.write_text("[1, 2, 3]")
    assert writer.load_existing() is None


def test_load_existing_valid_returns_dict(
    writer: StatusFileWriter, status_path: Path
) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    loaded = writer.load_existing()
    assert loaded is not None
    assert loaded["current"]["nonce"] == "n1"


def test_unknown_phase_allowed_but_logs(
    writer: StatusFileWriter, status_path: Path
) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    # Typo phase: still written, just logged as warning
    writer.write_phase("backupz")
    data = _read_json(status_path)
    assert data["current"]["phase"] == "backupz"
    assert data["history"][-1]["phase"] == "backupz"


def test_write_phase_without_begin_is_safe(
    writer: StatusFileWriter, status_path: Path
) -> None:
    # Before begin(), write_phase should no-op (defensive)
    writer.write_phase("backup")
    # No file should have been written
    assert not status_path.exists()


def test_phases_contains_expected_set() -> None:
    # Sanity: the phase allowlist includes all documented phases
    required = {
        "trigger_received", "backup", "extract",
        "pip_install_dryrun", "pip_install", "compileall",
        "smoke_import", "config_dryrun",
        "pending_marker_written", "symlink_flipped",
        "restarting", "healthcheck", "done",
        "rollback_starting", "rollback_symlink_flipped",
        "rollback_restarting", "rollback_healthcheck",
        "rollback_done", "rollback_failed",
    }
    assert required.issubset(PHASES)


def test_history_iso_utc_format(writer: StatusFileWriter, status_path: Path) -> None:
    writer.begin(nonce="n1", target_sha="a" * 40, old_sha="b" * 40)
    data = _read_json(status_path)
    at = data["history"][0]["at"]
    # ISO-8601 UTC Z form
    assert at.endswith("Z")
    assert "T" in at
    assert len(at) == 20  # YYYY-MM-DDTHH:MM:SSZ
