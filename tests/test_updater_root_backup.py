"""Hermetic unit tests for updater_root.backup.

Writes exclusively into tmp_path — never touches
``/var/lib/pv-inverter-proxy`` or ``/opt/pv-inverter-proxy-releases``.
"""
from __future__ import annotations

import os
import tarfile
import time
from pathlib import Path

from pv_inverter_proxy.updater_root.backup import (
    BACKUP_FILE_MODE,
    BackupResult,
    apply_backup_retention,
    apply_release_retention,
    create_backup,
)


def _mk_release(tmp_path: Path, name: str, with_venv: bool = True) -> Path:
    release = tmp_path / name
    release.mkdir()
    if with_venv:
        venv = release / ".venv"
        venv.mkdir()
        (venv / "marker.txt").write_text(f"venv-marker-{name}")
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").write_text("#!/bin/sh\necho fake\n")
    (release / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return release


def _mk_config(tmp_path: Path, body: str = "inverter:\n  host: 1.2.3.4\n") -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body)
    return cfg


# ---------- create_backup ----------


def test_create_backup_produces_three_files(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-a")
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    assert isinstance(result, BackupResult)
    assert result.venv_tarball.exists()
    assert result.config_copy.exists()
    assert result.pyproject_copy.exists()


def test_venv_tarball_roundtrip(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-b")
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with tarfile.open(result.venv_tarball, "r:gz") as tar:
        tar.extractall(extract_dir)
    marker = extract_dir / ".venv" / "marker.txt"
    assert marker.exists()
    assert marker.read_text() == "venv-marker-rel-b"


def test_config_snapshot_literal_copy(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-c")
    original = "inverter:\n  host: 192.0.2.7\n  port: 1502\n"
    cfg = _mk_config(tmp_path, body=original)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    assert result.config_copy.read_text() == original


def test_pyproject_snapshot(tmp_path: Path):
    release = tmp_path / "rel-d"
    release.mkdir()
    (release / ".venv").mkdir()
    pyproj_body = '[project]\nname = "pv-inverter-master"\nversion = "8.0.0"\n'
    (release / "pyproject.toml").write_text(pyproj_body)
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    assert result.pyproject_copy.read_text() == pyproj_body


def test_pyproject_missing_placeholder(tmp_path: Path):
    release = tmp_path / "rel-e"
    release.mkdir()
    (release / ".venv").mkdir()
    # no pyproject.toml
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    assert result.pyproject_copy.exists()
    assert "missing" in result.pyproject_copy.read_text()


def test_file_modes_0640(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-f")
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    for p in (result.venv_tarball, result.config_copy, result.pyproject_copy):
        mode = os.stat(p).st_mode & 0o777
        assert mode == BACKUP_FILE_MODE, f"{p.name} has mode {oct(mode)}"


def test_timestamp_in_name(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-g")
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    # 2024-04-10T12:20:00Z
    fixed = time.mktime((2024, 4, 10, 12, 20, 0, 0, 0, 0)) - time.timezone
    result = create_backup(release, cfg, backups, now=fixed)
    assert result.timestamp_str == "20240410T122000Z"
    assert "20240410T122000Z" in result.venv_tarball.name
    assert "20240410T122000Z" in result.config_copy.name
    assert "20240410T122000Z" in result.pyproject_copy.name


def test_create_backup_handles_missing_venv(tmp_path: Path):
    release = _mk_release(tmp_path, "rel-h", with_venv=False)
    cfg = _mk_config(tmp_path)
    backups = tmp_path / "backups"
    result = create_backup(release, cfg, backups)
    # Tarball still exists (empty) so retention sees a consistent set.
    assert result.venv_tarball.exists()
    with tarfile.open(result.venv_tarball, "r:gz") as tar:
        assert tar.getmembers() == []


# ---------- apply_backup_retention ----------


def test_apply_backup_retention_keeps_newest(tmp_path: Path):
    backups = tmp_path / "backups"
    backups.mkdir()
    stamps = [
        "20240101T000000Z",
        "20240102T000000Z",
        "20240103T000000Z",
        "20240104T000000Z",
        "20240105T000000Z",
    ]
    for i, ts in enumerate(stamps):
        (backups / f"venv-{ts}.tar.gz").write_text("x")
        (backups / f"config-{ts}.yaml").write_text("x")
        (backups / f"pyproject-{ts}.toml").write_text("x")
        # space mtimes out so sort is deterministic
        mt = 1_700_000_000 + i
        for ext in ("tar.gz", "yaml", "toml"):
            p = backups / f"venv-{ts}.tar.gz"
            if ext == "yaml":
                p = backups / f"config-{ts}.yaml"
            elif ext == "toml":
                p = backups / f"pyproject-{ts}.toml"
            os.utime(p, (mt, mt))
    deleted = apply_backup_retention(backups, keep=3)
    # Two oldest sets deleted -> 6 files
    assert len(deleted) == 6
    # Newest 3 sets still present -> 9 files
    remaining = sorted(p.name for p in backups.iterdir())
    assert len(remaining) == 9
    for ts in stamps[-3:]:
        assert f"venv-{ts}.tar.gz" in remaining
    for ts in stamps[:2]:
        assert f"venv-{ts}.tar.gz" not in remaining


def test_apply_backup_retention_keep_all_if_under(tmp_path: Path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for ts in ("20240101T000000Z", "20240102T000000Z"):
        (backups / f"venv-{ts}.tar.gz").write_text("x")
        (backups / f"config-{ts}.yaml").write_text("x")
        (backups / f"pyproject-{ts}.toml").write_text("x")
    deleted = apply_backup_retention(backups, keep=3)
    assert deleted == []
    assert len(list(backups.iterdir())) == 6


def test_apply_backup_retention_missing_dir(tmp_path: Path):
    deleted = apply_backup_retention(tmp_path / "nope", keep=3)
    assert deleted == []


def test_apply_backup_retention_missing_sibling_ok(tmp_path: Path):
    """Deletion tolerates missing siblings in a set."""
    backups = tmp_path / "backups"
    backups.mkdir()
    for i, ts in enumerate(
        [
            "20240101T000000Z",
            "20240102T000000Z",
            "20240103T000000Z",
            "20240104T000000Z",
        ]
    ):
        (backups / f"venv-{ts}.tar.gz").write_text("x")
        (backups / f"config-{ts}.yaml").write_text("x")
        # intentionally skip pyproject for oldest set
        if ts != "20240101T000000Z":
            (backups / f"pyproject-{ts}.toml").write_text("x")
        mt = 1_700_000_000 + i
        for p in backups.glob(f"*{ts}*"):
            os.utime(p, (mt, mt))
    deleted = apply_backup_retention(backups, keep=3)
    # Oldest set missing pyproject -> only 2 files deleted
    assert len(deleted) == 2


def test_apply_backup_retention_keep_coerced_to_one(tmp_path: Path):
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "venv-20240101T000000Z.tar.gz").write_text("x")
    (backups / "config-20240101T000000Z.yaml").write_text("x")
    (backups / "pyproject-20240101T000000Z.toml").write_text("x")
    deleted = apply_backup_retention(backups, keep=0)
    # keep coerced to 1 -> nothing deleted
    assert deleted == []
    assert len(list(backups.iterdir())) == 3


# ---------- apply_release_retention ----------


def _mk_releases_root(tmp_path: Path, names: list[str]) -> Path:
    """Create a releases root with numbered directories and a 'current' symlink."""
    rr = tmp_path / "releases"
    rr.mkdir()
    for i, n in enumerate(names):
        d = rr / n
        d.mkdir()
        (d / "marker").write_text(n)
        mt = 1_700_000_000 + i * 10
        os.utime(d, (mt, mt))
    # Point current at the newest (last name)
    link = rr / "current"
    link.symlink_to(rr / names[-1])
    return rr


def test_apply_release_retention_deletes_and_preserves_current(tmp_path: Path):
    names = ["v7.0-aaa", "v7.1-bbb", "v7.2-ccc", "v8.0-ddd", "v8.1-eee"]
    rr = _mk_releases_root(tmp_path, names)
    deleted = apply_release_retention(rr, keep=3)
    assert len(deleted) == 2
    # Newest 3 + symlink survive
    remaining = sorted(p.name for p in rr.iterdir() if p.name != "current")
    assert remaining == sorted(names[-3:])
    assert (rr / "current").is_symlink()


def test_apply_release_retention_protects_previous(tmp_path: Path):
    names = ["v7.0-aaa", "v7.1-bbb", "v7.2-ccc", "v8.0-ddd", "v8.1-eee"]
    rr = _mk_releases_root(tmp_path, names)
    prev = rr / "v7.0-aaa"  # would normally be deleted
    deleted = apply_release_retention(rr, keep=3, protect={prev})
    # prev must survive
    assert prev.exists()
    assert prev not in deleted
    # Exactly one release should be deleted: v7.1-bbb (v7.2 falls in the
    # top-3 newest window, v7.0 is protected)
    assert len(deleted) == 1
    assert deleted[0].name == "v7.1-bbb"


def test_apply_release_retention_empty(tmp_path: Path):
    rr = tmp_path / "releases"
    rr.mkdir()
    deleted = apply_release_retention(rr, keep=3)
    assert deleted == []
