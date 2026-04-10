"""Unit tests for releases.py (SAFETY-01, SAFETY-02, SAFETY-08)."""
from __future__ import annotations

import os
import shutil
import time
from collections import namedtuple
from pathlib import Path

import pytest

from pv_inverter_proxy.releases import (
    DEFAULT_KEEP_RELEASES,
    MIN_FREE_BYTES,
    DiskSpaceReport,
    LayoutKind,
    check_disk_space,
    current_release_dir,
    detect_layout,
    list_release_dirs,
    select_releases_to_delete,
)


# -------- Fixtures --------

def _make_release(root: Path, name: str, mtime_offset: float = 0.0) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "pyproject.toml").write_text("[project]\nname = \"x\"\n")
    if mtime_offset:
        now = time.time()
        os.utime(d, (now + mtime_offset, now + mtime_offset))
    return d


def _point_current(root: Path, target: Path) -> None:
    link = root / "current"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


# -------- detect_layout --------

def test_detect_layout_missing(tmp_path: Path):
    assert detect_layout(tmp_path / "nope", tmp_path / "releases") == LayoutKind.MISSING


def test_detect_layout_flat(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    (install / ".git").mkdir()
    assert detect_layout(install, tmp_path / "releases") == LayoutKind.FLAT


def test_detect_layout_unknown_dir_no_git(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "random_file.txt").write_text("hi")
    assert detect_layout(install, tmp_path / "releases") == LayoutKind.UNKNOWN


def test_detect_layout_blue_green(tmp_path: Path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    release = _make_release(releases_root, "v8.0-abc1234")
    install = tmp_path / "install"
    install.symlink_to(release)
    assert detect_layout(install, releases_root) == LayoutKind.BLUE_GREEN


def test_detect_layout_symlink_outside_releases(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    install = tmp_path / "install"
    install.symlink_to(elsewhere)
    assert detect_layout(install, releases_root) == LayoutKind.UNKNOWN


def test_detect_layout_dangling_symlink(tmp_path: Path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    install = tmp_path / "install"
    install.symlink_to(tmp_path / "does_not_exist")
    assert detect_layout(install, releases_root) == LayoutKind.UNKNOWN


# -------- current_release_dir --------

def test_current_release_dir_missing_symlink(tmp_path: Path):
    (tmp_path / "releases").mkdir()
    assert current_release_dir(tmp_path / "releases") is None


def test_current_release_dir_broken_symlink(tmp_path: Path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    (releases_root / "current").symlink_to(tmp_path / "nope")
    assert current_release_dir(releases_root) is None


def test_current_release_dir_valid(tmp_path: Path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    target = _make_release(releases_root, "v8.0-def5678")
    _point_current(releases_root, target)
    result = current_release_dir(releases_root)
    assert result is not None
    assert result.resolve() == target.resolve()


# -------- list_release_dirs --------

def test_list_release_dirs_missing_root(tmp_path: Path):
    assert list_release_dirs(tmp_path / "nope") == []


def test_list_release_dirs_empty_root(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    assert list_release_dirs(root) == []


def test_list_release_dirs_skips_current_symlink(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    r1 = _make_release(root, "v8.0-aaa1111")
    _point_current(root, r1)
    dirs = list_release_dirs(root)
    assert len(dirs) == 1
    assert dirs[0].name == "v8.0-aaa1111"


def test_list_release_dirs_skips_files(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "v8.0-aaa1111")
    (root / "stray.txt").write_text("junk")
    dirs = list_release_dirs(root)
    assert len(dirs) == 1


def test_list_release_dirs_skips_foreign_symlinks(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "v8.0-aaa1111")
    # Non-"current" symlink pointing elsewhere — must be ignored
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "foreign").symlink_to(elsewhere)
    dirs = list_release_dirs(root)
    assert len(dirs) == 1
    assert dirs[0].name == "v8.0-aaa1111"


def test_list_release_dirs_sorted_newest_first(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "old", mtime_offset=-1000)
    _make_release(root, "new", mtime_offset=0)
    _make_release(root, "middle", mtime_offset=-500)
    dirs = list_release_dirs(root)
    assert [d.name for d in dirs] == ["new", "middle", "old"]


# -------- select_releases_to_delete --------

def test_select_delete_no_releases(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    assert select_releases_to_delete(root, keep=3) == []


def test_select_delete_five_keep_three(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    names = ["r1", "r2", "r3", "r4", "r5"]
    for i, n in enumerate(names):
        _make_release(root, n, mtime_offset=-(5 - i) * 100)  # r5 newest, r1 oldest
    _point_current(root, root / "r5")
    to_delete = select_releases_to_delete(root, keep=3)
    names_deleted = sorted(d.name for d in to_delete)
    assert names_deleted == ["r1", "r2"]  # r3, r4, r5 retained


def test_select_delete_fewer_than_keep(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "r1")
    _make_release(root, "r2")
    _point_current(root, root / "r1")
    assert select_releases_to_delete(root, keep=3) == []


def test_select_delete_protects_current_even_if_oldest(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "oldest", mtime_offset=-1000)
    _make_release(root, "mid", mtime_offset=-500)
    _make_release(root, "newest", mtime_offset=0)
    _make_release(root, "newer", mtime_offset=100)
    _make_release(root, "newest_of_all", mtime_offset=200)
    _point_current(root, root / "oldest")  # current is OLDEST
    to_delete = select_releases_to_delete(root, keep=3)
    names = {d.name for d in to_delete}
    # oldest (current, protected) kept
    # newest 3 by mtime: newest_of_all, newer, newest
    # retained total = {oldest} ∪ {newest_of_all, newer, newest} = 4 total
    # deleted = {mid}
    assert names == {"mid"}


def test_select_delete_explicit_protect(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    r1 = _make_release(root, "r1", mtime_offset=-300)
    r2 = _make_release(root, "r2", mtime_offset=-200)
    r3 = _make_release(root, "r3", mtime_offset=-100)
    r4 = _make_release(root, "r4", mtime_offset=0)
    _point_current(root, r4)
    to_delete = select_releases_to_delete(root, keep=2, protect={r1})
    names = {d.name for d in to_delete}
    # Union semantics: top-2 newest {r4, r3} ∪ protected {r4 (current), r1}
    # = {r1, r3, r4} retained, delete {r2}
    assert names == {"r2"}


def test_select_delete_protect_outside_top_n(tmp_path: Path):
    """Protected dirs outside the top-N window are retained in addition
    to the top-N, so total retained can exceed `keep`."""
    root = tmp_path / "releases"
    root.mkdir()
    r1 = _make_release(root, "r1", mtime_offset=-400)
    r2 = _make_release(root, "r2", mtime_offset=-300)
    r3 = _make_release(root, "r3", mtime_offset=-200)
    r4 = _make_release(root, "r4", mtime_offset=-100)
    r5 = _make_release(root, "r5", mtime_offset=0)
    _point_current(root, r5)
    # keep=2 → top-2 = {r5, r4}; protect {r1} → union = {r1, r4, r5}
    # Delete: {r2, r3}
    to_delete = select_releases_to_delete(root, keep=2, protect={r1})
    names = {d.name for d in to_delete}
    assert names == {"r2", "r3"}


def test_select_delete_keep_zero_coerced(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "r1", mtime_offset=-200)
    _make_release(root, "r2", mtime_offset=-100)
    _make_release(root, "r3", mtime_offset=0)
    _point_current(root, root / "r3")
    # keep=0 coerced to 1; r3 is current (protected); delete r1, r2
    to_delete = select_releases_to_delete(root, keep=0)
    names = {d.name for d in to_delete}
    assert names == {"r1", "r2"}


def test_select_delete_keep_negative_coerced(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "r1", mtime_offset=-100)
    _make_release(root, "r2", mtime_offset=0)
    _point_current(root, root / "r2")
    to_delete = select_releases_to_delete(root, keep=-5)
    names = {d.name for d in to_delete}
    assert names == {"r1"}


def test_select_delete_broken_current_does_not_crash(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "r1", mtime_offset=-200)
    _make_release(root, "r2", mtime_offset=-100)
    _make_release(root, "r3", mtime_offset=0)
    (root / "current").symlink_to(root / "does_not_exist")
    to_delete = select_releases_to_delete(root, keep=2)
    # current is broken — treated as no protection; top 2 by mtime = r3, r2
    # deleted = r1
    names = {d.name for d in to_delete}
    assert names == {"r1"}


def test_select_delete_no_current_symlink(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    _make_release(root, "r1", mtime_offset=-200)
    _make_release(root, "r2", mtime_offset=-100)
    _make_release(root, "r3", mtime_offset=0)
    # no current symlink at all
    to_delete = select_releases_to_delete(root, keep=2)
    names = {d.name for d in to_delete}
    assert names == {"r1"}


# -------- check_disk_space --------

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


def _mock_disk_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opt_free: int,
    vc_free: int,
) -> tuple[Path, Path]:
    opt = tmp_path / "opt"
    vc = tmp_path / "var_cache"
    opt.mkdir()
    vc.mkdir()

    def fake_disk_usage(path: str):
        p = Path(path)
        if p == opt:
            return DiskUsage(total=10**12, used=0, free=opt_free)
        if p == vc:
            return DiskUsage(total=10**12, used=0, free=vc_free)
        raise FileNotFoundError(path)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)
    return opt, vc


def test_disk_space_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES + 1, MIN_FREE_BYTES + 1)
    r = check_disk_space(opt_path=opt, var_cache_path=vc)
    assert r.ok is True
    assert r.message == ""
    assert r.opt_free_bytes == MIN_FREE_BYTES + 1
    assert r.var_cache_free_bytes == MIN_FREE_BYTES + 1


def test_disk_space_opt_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES - 1, MIN_FREE_BYTES + 1)
    r = check_disk_space(opt_path=opt, var_cache_path=vc)
    assert r.ok is False
    assert "opt" in r.message.lower() or str(opt) in r.message
    assert "MB" in r.message


def test_disk_space_var_cache_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES + 1, MIN_FREE_BYTES - 1)
    r = check_disk_space(opt_path=opt, var_cache_path=vc)
    assert r.ok is False
    assert "var_cache" in r.message or str(vc) in r.message


def test_disk_space_both_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    opt, vc = _mock_disk_usage(tmp_path, monkeypatch, 1, 1)
    r = check_disk_space(opt_path=opt, var_cache_path=vc)
    assert r.ok is False
    assert ";" in r.message  # both problems joined


def test_disk_space_missing_path(tmp_path: Path):
    r = check_disk_space(
        opt_path=tmp_path / "nope_opt",
        var_cache_path=tmp_path / "nope_vc",
    )
    assert r.ok is False
    assert "does not exist" in r.message


def test_disk_space_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    opt = tmp_path / "opt"
    vc = tmp_path / "vc"
    opt.mkdir()
    vc.mkdir()

    def raising(path: str):
        raise OSError("simulated")

    monkeypatch.setattr(shutil, "disk_usage", raising)
    r = check_disk_space(opt_path=opt, var_cache_path=vc)
    assert r.ok is False
    assert "failed" in r.message


def test_disk_space_report_is_dataclass():
    r = DiskSpaceReport(opt_free_bytes=1, var_cache_free_bytes=2, ok=True, message="")
    assert r.opt_free_bytes == 1
    assert r.var_cache_free_bytes == 2
    assert r.ok is True
    assert r.message == ""


def test_default_keep_releases_is_three():
    assert DEFAULT_KEEP_RELEASES == 3


def test_min_free_bytes_is_500mb():
    assert MIN_FREE_BYTES == 500 * 1024 * 1024
