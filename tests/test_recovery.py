"""Unit tests for recovery.py (SAFETY-04).

All tests use ``tmp_path`` for filesystem operations — no test touches
``/opt``, ``/var``, or ``/run``. The recovery module's core functions
accept override paths for every file they interact with, which makes
the entire code path testable without systemd or root.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from pv_inverter_proxy import recovery
from pv_inverter_proxy.recovery import (
    PendingMarker,
    clear_pending_marker,
    load_pending_marker,
    recover_if_needed,
)


# -------- Fixtures / helpers --------


def _write_marker(path: Path, **kwargs) -> None:
    data = {
        "schema_version": 1,
        "previous_release": "/opt/pv-inverter-proxy-releases/v7.0-abc1234",
        "target_release": "/opt/pv-inverter-proxy-releases/v8.0-def5678",
        "created_at": 1_700_000_000.0,
        "reason": "update",
    }
    data.update(kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _setup_releases(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (releases_root, v1_dir, v2_dir) with current -> v2."""
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    v1 = releases_root / "v7.0-abc1234"
    v1.mkdir()
    (v1 / "pyproject.toml").write_text("[project]\nname='x'\n")
    v2 = releases_root / "v8.0-def5678"
    v2.mkdir()
    (v2 / "pyproject.toml").write_text("[project]\nname='x'\n")
    (releases_root / "current").symlink_to(v2)
    return releases_root, v1, v2


# -------- load_pending_marker --------


def test_load_pending_missing(tmp_path: Path):
    assert load_pending_marker(tmp_path / "nope.marker") is None


def test_load_pending_corrupt_json(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text("{bad json")
    assert load_pending_marker(path) is None


def test_load_pending_array_not_dict(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text("[1,2,3]")
    assert load_pending_marker(path) is None


def test_load_pending_wrong_schema(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path, schema_version=99)
    assert load_pending_marker(path) is None


def test_load_pending_missing_schema_version(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text(
        json.dumps(
            {
                "previous_release": "/opt/x",
                "target_release": "/opt/y",
                "created_at": 1.0,
            }
        )
    )
    assert load_pending_marker(path) is None


def test_load_pending_missing_previous(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_release": "/opt/x",
                "created_at": 1.0,
            }
        )
    )
    assert load_pending_marker(path) is None


def test_load_pending_previous_not_absolute(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path, previous_release="relative/path")
    assert load_pending_marker(path) is None


def test_load_pending_previous_wrong_type(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path, previous_release=123)
    assert load_pending_marker(path) is None


def test_load_pending_target_not_absolute(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path, target_release="rel")
    assert load_pending_marker(path) is None


def test_load_pending_missing_created_at(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "previous_release": "/opt/x",
                "target_release": "/opt/y",
            }
        )
    )
    assert load_pending_marker(path) is None


def test_load_pending_created_at_wrong_type(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path, created_at="not a number")
    assert load_pending_marker(path) is None


def test_load_pending_valid(tmp_path: Path):
    path = tmp_path / "marker"
    _write_marker(path)
    m = load_pending_marker(path)
    assert m is not None
    assert m.previous_release == "/opt/pv-inverter-proxy-releases/v7.0-abc1234"
    assert m.target_release == "/opt/pv-inverter-proxy-releases/v8.0-def5678"
    assert m.created_at == 1_700_000_000.0
    assert m.reason == "update"
    assert m.schema_version == 1


def test_load_pending_reason_defaults(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "previous_release": "/opt/x",
                "target_release": "/opt/y",
                "created_at": 1.0,
            }
        )
    )
    m = load_pending_marker(path)
    assert m is not None
    assert m.reason == "update"


def test_load_pending_integer_created_at_ok(tmp_path: Path):
    """JSON integer created_at should be accepted and coerced to float."""
    path = tmp_path / "marker"
    _write_marker(path, created_at=1700000000)
    m = load_pending_marker(path)
    assert m is not None
    assert isinstance(m.created_at, float)
    assert m.created_at == 1_700_000_000.0


# -------- clear_pending_marker --------


def test_clear_pending_removes_file(tmp_path: Path):
    path = tmp_path / "marker"
    path.write_text("hi")
    clear_pending_marker(path)
    assert not path.exists()


def test_clear_pending_missing_ok(tmp_path: Path):
    # Should not raise
    clear_pending_marker(tmp_path / "nope")


def test_clear_pending_swallows_oserror(tmp_path: Path, monkeypatch):
    """Unlinkable file should log warning but not raise."""
    path = tmp_path / "marker"
    path.write_text("x")

    real_unlink = Path.unlink

    def raising_unlink(self, missing_ok=False):
        if self == path:
            raise OSError("simulated EPERM")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", raising_unlink)
    # Must not raise
    clear_pending_marker(path)


# -------- recover_if_needed --------


def test_recover_no_pending(tmp_path: Path):
    releases_root, _, _ = _setup_releases(tmp_path)
    outcome = recover_if_needed(
        pending_path=tmp_path / "no_marker",
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome == "no_pending"


def test_recover_no_pending_on_corrupt(tmp_path: Path):
    releases_root, _, _ = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    marker.write_text("{garbage")
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome == "no_pending"


def test_recover_stale_cleaned(tmp_path: Path):
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=1_000_000.0,
    )
    success = tmp_path / "last-success"
    success.write_text("")
    os.utime(success, (2_000_000.0, 2_000_000.0))  # newer than marker
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=success,
        releases_root=releases_root,
    )
    assert outcome == "stale_pending_cleaned"
    assert not marker.exists()
    # current symlink unchanged
    assert (releases_root / "current").resolve() == v2.resolve()


def test_recover_target_missing(tmp_path: Path):
    releases_root, _, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(tmp_path / "nonexistent"),
        target_release=str(v2),
    )
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome == "target_missing"
    assert marker.exists()  # NOT cleared - human intervention needed
    assert (releases_root / "current").resolve() == v2.resolve()  # untouched


def test_recover_rolled_back(tmp_path: Path):
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=time.time(),
    )
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome == "rolled_back"
    assert not marker.exists()
    assert (releases_root / "current").resolve() == v1.resolve()


def test_recover_updater_active_skips_rollback(tmp_path: Path):
    """Phase 45-04: when the updater-active tmpfs flag is set, recovery
    must NOT roll back — the updater is managing the restart cycle
    itself and will handle rollback via HealthChecker if needed.
    """
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=time.time(),
    )
    # Simulate the updater raising its active flag before restart
    flag = tmp_path / "updater-active"
    flag.touch()
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
        updater_active_flag=flag,
    )
    assert outcome == "updater_active"
    # Marker stays — updater may still roll back via HealthChecker
    assert marker.exists()
    # Symlink untouched (still pointing at v2 = the new release)
    assert (releases_root / "current").resolve() == v2.resolve()


def test_recover_updater_active_flag_missing_falls_through(tmp_path: Path):
    """When the updater-active flag does not exist, recovery runs its
    normal path and rolls back as Phase 43 specified.
    """
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=time.time(),
    )
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
        updater_active_flag=tmp_path / "not-there",
    )
    assert outcome == "rolled_back"


def test_recover_rolled_back_idempotent(tmp_path: Path):
    """Second call after rollback returns no_pending (marker gone)."""
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(marker, previous_release=str(v1), target_release=str(v2))
    outcome1 = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome1 == "rolled_back"
    outcome2 = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome2 == "no_pending"


def test_recover_flip_failed(tmp_path: Path, monkeypatch):
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(marker, previous_release=str(v1), target_release=str(v2))

    def raising_flip(current_link, new_target):
        raise OSError("simulated EPERM")

    monkeypatch.setattr(recovery, "_atomic_symlink_flip", raising_flip)
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=tmp_path / "no_success",
        releases_root=releases_root,
    )
    assert outcome == "flip_failed"
    assert marker.exists()  # NOT cleared - user intervention needed
    assert (releases_root / "current").resolve() == v2.resolve()  # untouched


def test_recover_last_success_older_than_marker_triggers_rollback(tmp_path: Path):
    """If last_success exists but is OLDER than the marker, rollback proceeds."""
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=5_000_000.0,
    )
    success = tmp_path / "last-success"
    success.write_text("")
    os.utime(success, (1_000_000.0, 1_000_000.0))  # OLDER than marker
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=success,
        releases_root=releases_root,
    )
    assert outcome == "rolled_back"
    assert (releases_root / "current").resolve() == v1.resolve()


def test_recover_last_success_equal_to_marker_triggers_rollback(tmp_path: Path):
    """Edge: equal mtimes — treat as not-stale, proceed to rollback (defensive)."""
    releases_root, v1, v2 = _setup_releases(tmp_path)
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(v1),
        target_release=str(v2),
        created_at=5_000_000.0,
    )
    success = tmp_path / "last-success"
    success.write_text("")
    os.utime(success, (5_000_000.0, 5_000_000.0))  # EQUAL to marker
    outcome = recover_if_needed(
        pending_path=marker,
        last_success_path=success,
        releases_root=releases_root,
    )
    # Not strictly greater than, so not stale -> proceeds with rollback
    assert outcome == "rolled_back"


# -------- main --------


def test_main_returns_zero_no_pending(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(recovery, "PENDING_MARKER_PATH", tmp_path / "nope")
    monkeypatch.setattr(recovery, "LAST_BOOT_SUCCESS_PATH", tmp_path / "nope2")
    assert recovery.main() == 0


def test_main_returns_zero_even_on_exception(tmp_path: Path, monkeypatch):
    """Safety net: unexpected exceptions must never propagate to systemd."""

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(recovery, "recover_if_needed", boom)
    assert recovery.main() == 0


def test_main_returns_zero_on_target_missing(tmp_path: Path, monkeypatch):
    """Even critical outcomes like target_missing exit 0 — never block boot."""
    marker = tmp_path / "marker"
    _write_marker(
        marker,
        previous_release=str(tmp_path / "nonexistent"),
        target_release=str(tmp_path / "nonexistent2"),
    )
    monkeypatch.setattr(recovery, "PENDING_MARKER_PATH", marker)
    monkeypatch.setattr(recovery, "LAST_BOOT_SUCCESS_PATH", tmp_path / "no_success")
    # Real RELEASES_ROOT would not be writable; keep defaults and let
    # target_missing short-circuit before the flip attempt.
    assert recovery.main() == 0


# -------- _atomic_symlink_flip --------


def test_atomic_symlink_flip_direct(tmp_path: Path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    v1 = releases_root / "v1"
    v1.mkdir()
    v2 = releases_root / "v2"
    v2.mkdir()
    current = releases_root / "current"
    current.symlink_to(v2)
    recovery._atomic_symlink_flip(current, v1)
    assert current.is_symlink()
    assert current.resolve() == v1.resolve()
    # Leftover .new should not exist
    assert not (releases_root / "current.new").exists()


def test_atomic_symlink_flip_cleans_stale_tmp(tmp_path: Path):
    """If current.new already exists from a prior crashed attempt, it is cleaned."""
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    v1 = releases_root / "v1"
    v1.mkdir()
    v2 = releases_root / "v2"
    v2.mkdir()
    current = releases_root / "current"
    current.symlink_to(v2)
    # Stale tmp from previous crashed run
    stale_tmp = releases_root / "current.new"
    stale_tmp.symlink_to(v2)
    recovery._atomic_symlink_flip(current, v1)
    assert current.resolve() == v1.resolve()
    assert not stale_tmp.exists()
