---
phase: 43-blue-green-layout-boot-recovery
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/releases.py
  - tests/test_releases.py
autonomous: true
requirements:
  - SAFETY-01
  - SAFETY-02
  - SAFETY-08
must_haves:
  truths:
    - "A Python helper can identify the current release directory by following the symlink"
    - "A retention function can list release directories and identify which to delete (keeping current, previous, and N-2 newer)"
    - "A disk pre-flight helper reports whether /opt and /var/cache have >= 500 MB free"
    - "A migration detector can distinguish a flat layout (direct .git/ in /opt/pv-inverter-proxy) from a blue-green layout (symlink to releases dir)"
  artifacts:
    - path: "src/pv_inverter_proxy/releases.py"
      provides: "Blue-green layout helpers: layout detection, retention, disk pre-flight"
      min_lines: 220
      exports:
        - "RELEASES_ROOT"
        - "INSTALL_ROOT"
        - "LayoutKind"
        - "detect_layout"
        - "current_release_dir"
        - "list_release_dirs"
        - "select_releases_to_delete"
        - "check_disk_space"
        - "DiskSpaceReport"
        - "MIN_FREE_BYTES"
    - path: "tests/test_releases.py"
      provides: "Unit tests with tmp_path fakes for symlinks, fake release dirs, disk space mocking"
      min_lines: 260
  key_links:
    - from: "src/pv_inverter_proxy/releases.py"
      to: "stdlib shutil.disk_usage, os.readlink, pathlib.Path.is_symlink"
      via: "layout detection + retention sorting"
      pattern: "is_symlink|readlink|disk_usage"
---

<objective>
Create a self-contained Python module that encapsulates all blue-green layout logic — layout detection, current release discovery, release listing, retention selection, and disk pre-flight — as pure functions that are fully unit-testable with filesystem fakes (`tmp_path`). No systemd coupling. No actual symlink flipping (that's plan 43-04 migration + plan 45 update flow).

Purpose: This is the callable library that later phases will use. Plan 43-04 will call `detect_layout()` to decide whether to migrate. Plan 45 (privileged updater) will call `select_releases_to_delete()` after successful update and `check_disk_space()` before download. Landing the logic standalone with full test coverage means Phases 45/46 can trust the helpers without re-verifying the layout math. It also gives us a single source of truth for the anchor constants (`RELEASES_ROOT`, `INSTALL_ROOT`, retention count, disk threshold).

Output: One new source module (`releases.py`), one new test file. No existing files modified. No actual filesystem changes on the target LXC — this plan is pure Python helpers.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@CLAUDE.md

<interfaces>
<!-- Anchor constants (decided by research, see research/ARCHITECTURE.md Rollback Mechanism + PITFALLS.md C1/H8): -->

Layout anchors (do not re-derive):
- `RELEASES_ROOT = Path("/opt/pv-inverter-proxy-releases")` — directory containing one subdir per release
- `INSTALL_ROOT = Path("/opt/pv-inverter-proxy")` — becomes a symlink to `RELEASES_ROOT / "current"`
- `CURRENT_SYMLINK = RELEASES_ROOT / "current"` — the atomic swap target; also points at a release subdir
- `DEFAULT_KEEP_RELEASES = 3` — from PROJECT.md product decision and PITFALLS.md H8
- `MIN_FREE_BYTES = 500 * 1024 * 1024` — 500 MB, from SAFETY-08

Release directory naming (from ARCHITECTURE.md Blue-Green layout):
```
/opt/pv-inverter-proxy-releases/
  v7.0-abc1234/
  v8.0-def5678/
  current -> v8.0-def5678
```
Pattern: `v<semver>-<short_sha>` where semver is `\d+\.\d+(\.\d+)?` and short_sha is 7-12 hex chars. Helper code should NOT over-validate the name — any directory sibling of `current` is a candidate, any non-matching name (e.g. stray `.tmp`, `backup.bak`) should be skipped (warn, not fail).

Retention rule (from SAFETY-02): keep `keep_releases` most recent, but NEVER delete:
1. The directory pointed at by `current` symlink
2. The directory that was the "previous current" (the rollback target)

Implementation: sort release dirs by mtime descending. Keep the top N. Additionally force-keep the current symlink target even if it's not in the top N (edge case: clock skew, touch). Return the list of dirs that CAN be safely deleted.

The "previous" directory is NOT tracked by the layout itself — it's tracked in the update-status.json file (Phase 45). For Phase 43, `select_releases_to_delete()` takes an optional `protect: set[Path]` parameter so callers can add extra directories to the keep set. Phase 45 will pass `{current, previous_from_status}`.

Existing code pattern (config.py dataclass style):
```python
@dataclass
class DiskSpaceReport:
    opt_free_bytes: int
    var_cache_free_bytes: int
    ok: bool
    message: str
```

Existing test pattern (tests/test_config.py): plain pytest functions, `tmp_path` fixture, no mocks when avoidable. For `shutil.disk_usage` mocking, use `monkeypatch.setattr(shutil, "disk_usage", ...)`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create releases.py with layout detection and current release discovery</name>
  <files>src/pv_inverter_proxy/releases.py</files>
  <behavior>
    Module exposes layout detection and constants:

    1. Constants (module-level):
       - `RELEASES_ROOT: Path = Path("/opt/pv-inverter-proxy-releases")`
       - `INSTALL_ROOT: Path = Path("/opt/pv-inverter-proxy")`
       - `CURRENT_SYMLINK_NAME: str = "current"` (the symlink name inside RELEASES_ROOT)
       - `DEFAULT_KEEP_RELEASES: int = 3`
       - `MIN_FREE_BYTES: int = 500 * 1024 * 1024`  # SAFETY-08

    2. `class LayoutKind(StrEnum)`:
       - `FLAT` — `INSTALL_ROOT` is a real directory containing `.git/` (pre-v8.0 layout)
       - `BLUE_GREEN` — `INSTALL_ROOT` is a symlink pointing into `RELEASES_ROOT`
       - `MISSING` — `INSTALL_ROOT` does not exist (fresh install)
       - `UNKNOWN` — something else (real dir without .git, broken symlink, etc.)

    3. `def detect_layout(install_root: Path | None = None, releases_root: Path | None = None) -> LayoutKind`:
       - Both arguments default to the module-level constants (override for tests).
       - If `install_root` does not exist → `MISSING`.
       - If `install_root.is_symlink()`:
         - Resolve the link. If it resolves under `releases_root` → `BLUE_GREEN`.
         - If the link is broken or points elsewhere → `UNKNOWN`.
       - If `install_root.is_dir()` and `(install_root / ".git").exists()` → `FLAT`.
       - Otherwise → `UNKNOWN`.

    4. `def current_release_dir(releases_root: Path | None = None) -> Path | None`:
       - Reads `releases_root / "current"` symlink.
       - Returns the resolved target Path if valid, `None` if missing or broken.
       - Must NOT crash if the symlink dangles (`.resolve(strict=True)` raises `FileNotFoundError`; use `strict=False` and manually verify `.exists()`).
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/releases.py` with the following content (tasks 2 and 3 will append to this file):

    ```python
    """Blue-green release layout helpers (SAFETY-01, SAFETY-02, SAFETY-08).

    Pure-function module encapsulating the layout anchors and logic for the
    v8.0 auto-update system. No systemd coupling, no actual symlink flipping
    — those are the responsibility of install.sh (migration, plan 43-04)
    and the privileged updater (plan 45).

    Layout:
        /opt/pv-inverter-proxy-releases/
            v7.0-abc1234/       # full checkout + .venv
            v8.0-def5678/       # full checkout + .venv
            current -> v8.0-def5678
        /opt/pv-inverter-proxy -> /opt/pv-inverter-proxy-releases/current
    """
    from __future__ import annotations

    import shutil
    from dataclasses import dataclass
    from enum import Enum
    from pathlib import Path

    import structlog

    log = structlog.get_logger(component="releases")

    # -- Anchor constants (see .planning/research/ARCHITECTURE.md) --
    RELEASES_ROOT: Path = Path("/opt/pv-inverter-proxy-releases")
    INSTALL_ROOT: Path = Path("/opt/pv-inverter-proxy")
    CURRENT_SYMLINK_NAME: str = "current"
    DEFAULT_KEEP_RELEASES: int = 3
    MIN_FREE_BYTES: int = 500 * 1024 * 1024  # 500 MB, SAFETY-08


    class LayoutKind(str, Enum):
        FLAT = "flat"
        BLUE_GREEN = "blue_green"
        MISSING = "missing"
        UNKNOWN = "unknown"


    def detect_layout(
        install_root: Path | None = None,
        releases_root: Path | None = None,
    ) -> LayoutKind:
        ir = install_root or INSTALL_ROOT
        rr = releases_root or RELEASES_ROOT

        # Symlink? Resolve and check destination
        if ir.is_symlink():
            try:
                resolved = ir.resolve(strict=False)
            except OSError:
                return LayoutKind.UNKNOWN
            if not resolved.exists():
                log.warning("install_root_dangling_symlink", path=str(ir))
                return LayoutKind.UNKNOWN
            try:
                resolved.relative_to(rr.resolve(strict=False))
                return LayoutKind.BLUE_GREEN
            except ValueError:
                # symlink points outside releases root — foreign layout
                return LayoutKind.UNKNOWN

        if not ir.exists():
            return LayoutKind.MISSING

        if ir.is_dir() and (ir / ".git").exists():
            return LayoutKind.FLAT

        return LayoutKind.UNKNOWN


    def current_release_dir(releases_root: Path | None = None) -> Path | None:
        rr = releases_root or RELEASES_ROOT
        link = rr / CURRENT_SYMLINK_NAME
        if not link.is_symlink():
            return None
        try:
            target = link.resolve(strict=False)
        except OSError:
            return None
        if not target.exists():
            return None
        return target
    ```
  </action>
  <verify>
    <automated>python -c "from pv_inverter_proxy.releases import LayoutKind, detect_layout, current_release_dir, RELEASES_ROOT, INSTALL_ROOT, DEFAULT_KEEP_RELEASES, MIN_FREE_BYTES; assert DEFAULT_KEEP_RELEASES == 3; assert MIN_FREE_BYTES == 500 * 1024 * 1024; print('ok')"</automated>
  </verify>
  <done>Module file exists, imports cleanly, layout detection and current-release helpers present and exported.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add release listing, retention selection, and disk pre-flight to releases.py</name>
  <files>src/pv_inverter_proxy/releases.py</files>
  <behavior>
    Append to `releases.py`:

    1. `def list_release_dirs(releases_root: Path | None = None) -> list[Path]`:
       - Returns all direct subdirectories of `releases_root`, excluding the `current` symlink itself.
       - Sorted by modification time, newest first.
       - Non-directory entries and the `current` symlink are skipped (not errors).
       - If `releases_root` does not exist, returns `[]`.

    2. `def select_releases_to_delete(
            releases_root: Path | None = None,
            keep: int = DEFAULT_KEEP_RELEASES,
            protect: set[Path] | None = None,
        ) -> list[Path]`:
       - Lists all release dirs (via `list_release_dirs`).
       - Always adds the current symlink target to the protected set (if resolvable).
       - Always adds every path in `protect` to the protected set.
       - From the remaining unprotected dirs, sorted newest-first, KEEP the first `max(0, keep - len(protected_in_top))` so that the total retained count is `keep` (but protected dirs beyond that are still retained). Simpler spec: retain the `keep` newest dirs UNION the protect set; return the rest.
       - `keep < 1` is coerced to `1` with a warning (never delete everything).
       - Return type is a list of `Path` objects that are SAFE to delete. Caller does the actual `shutil.rmtree`.

    3. `@dataclass class DiskSpaceReport`:
       - `opt_free_bytes: int`
       - `var_cache_free_bytes: int`
       - `ok: bool`
       - `message: str` (empty string when ok, human-readable reason when not)

    4. `def check_disk_space(
            min_free_bytes: int = MIN_FREE_BYTES,
            opt_path: Path = Path("/opt"),
            var_cache_path: Path = Path("/var/cache"),
        ) -> DiskSpaceReport`:
       - Calls `shutil.disk_usage()` on both paths.
       - Each path must have >= `min_free_bytes` free.
       - If a path does not exist, treat it as insufficient (ok=False) with a clear message.
       - Any `OSError` during disk_usage → ok=False with error in message.
       - Build a clear message like `"/opt has 412 MB free (need 500 MB)"` using MB for display.

    Detailed implementation notes for `select_releases_to_delete`:
    - Step 1: `all_dirs = list_release_dirs(rr)` (newest first by mtime)
    - Step 2: `protected: set[Path] = set(protect or set())`
    - Step 3: `current = current_release_dir(rr)` — add to protected if present
    - Step 4: `effective_keep = max(1, keep)` with warning if `keep < 1`
    - Step 5: Build retained set: start with all protected. Then walk `all_dirs` newest-first, adding to retained until `len(retained) >= effective_keep` OR we run out of dirs.
    - Step 6: Return `[d for d in all_dirs if d not in retained]` — preserves newest-first order for callers that want to log "deleting X oldest releases".
  </behavior>
  <action>
    Append to `src/pv_inverter_proxy/releases.py`:

    ```python


    def list_release_dirs(releases_root: Path | None = None) -> list[Path]:
        rr = releases_root or RELEASES_ROOT
        if not rr.exists() or not rr.is_dir():
            return []
        dirs: list[Path] = []
        for entry in rr.iterdir():
            if entry.name == CURRENT_SYMLINK_NAME:
                continue
            if entry.is_symlink():
                continue
            if not entry.is_dir():
                continue
            dirs.append(entry)
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return dirs


    def select_releases_to_delete(
        releases_root: Path | None = None,
        keep: int = DEFAULT_KEEP_RELEASES,
        protect: set[Path] | None = None,
    ) -> list[Path]:
        rr = releases_root or RELEASES_ROOT
        all_dirs = list_release_dirs(rr)
        if not all_dirs:
            return []

        effective_keep = keep
        if effective_keep < 1:
            log.warning(
                "retention_keep_coerced",
                requested=keep,
                coerced=1,
                reason="refusing to delete all releases",
            )
            effective_keep = 1

        # Build protected set: explicit caller set + current symlink target
        protected: set[Path] = set()
        for p in (protect or set()):
            try:
                protected.add(p.resolve(strict=False))
            except OSError:
                protected.add(p)
        current = current_release_dir(rr)
        if current is not None:
            protected.add(current.resolve(strict=False))

        # Walk newest-first, retain until we hit the keep count
        retained: set[Path] = set(protected)
        for d in all_dirs:
            if len(retained) >= effective_keep:
                break
            retained.add(d.resolve(strict=False))

        # Result: dirs in all_dirs not in retained, preserving newest-first order
        to_delete: list[Path] = [
            d for d in all_dirs
            if d.resolve(strict=False) not in retained
        ]
        return to_delete


    @dataclass
    class DiskSpaceReport:
        opt_free_bytes: int
        var_cache_free_bytes: int
        ok: bool
        message: str


    def _free_bytes(path: Path) -> tuple[int, str | None]:
        """Return (free_bytes, error_message_or_None)."""
        if not path.exists():
            return 0, f"{path} does not exist"
        try:
            usage = shutil.disk_usage(str(path))
            return usage.free, None
        except OSError as e:
            return 0, f"disk_usage({path}) failed: {e}"


    def check_disk_space(
        min_free_bytes: int = MIN_FREE_BYTES,
        opt_path: Path = Path("/opt"),
        var_cache_path: Path = Path("/var/cache"),
    ) -> DiskSpaceReport:
        opt_free, opt_err = _free_bytes(opt_path)
        vc_free, vc_err = _free_bytes(var_cache_path)

        problems: list[str] = []
        if opt_err:
            problems.append(opt_err)
        elif opt_free < min_free_bytes:
            problems.append(
                f"{opt_path} has {opt_free // (1024*1024)} MB free "
                f"(need {min_free_bytes // (1024*1024)} MB)"
            )
        if vc_err:
            problems.append(vc_err)
        elif vc_free < min_free_bytes:
            problems.append(
                f"{var_cache_path} has {vc_free // (1024*1024)} MB free "
                f"(need {min_free_bytes // (1024*1024)} MB)"
            )

        return DiskSpaceReport(
            opt_free_bytes=opt_free,
            var_cache_free_bytes=vc_free,
            ok=not problems,
            message="; ".join(problems),
        )
    ```
  </action>
  <verify>
    <automated>python -c "from pv_inverter_proxy.releases import list_release_dirs, select_releases_to_delete, check_disk_space, DiskSpaceReport; r = check_disk_space(); print('ok', r.ok, len(r.message))"</automated>
  </verify>
  <done>All helpers are importable. `check_disk_space()` runs on the dev machine without crashing (will likely report ok=True since macOS has plenty of space; that's fine for smoke test).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Write unit tests for releases.py</name>
  <files>tests/test_releases.py</files>
  <behavior>
    pytest tests using `tmp_path` to fake a releases root + symlinks + release directories. Use `monkeypatch` only for `shutil.disk_usage` mocking.

    Test coverage:

    **detect_layout:**
    - MISSING when install_root does not exist
    - FLAT when install_root is a dir containing .git
    - UNKNOWN when install_root is a dir without .git
    - BLUE_GREEN when install_root is a symlink pointing inside releases_root
    - UNKNOWN when install_root is a symlink pointing outside releases_root
    - UNKNOWN when install_root is a dangling symlink

    **current_release_dir:**
    - Returns None when symlink does not exist
    - Returns None when symlink is broken
    - Returns resolved Path when symlink is valid

    **list_release_dirs:**
    - Returns [] when releases_root does not exist
    - Skips the `current` symlink
    - Skips files (not dirs)
    - Skips other symlinks
    - Returns dirs sorted by mtime, newest first

    **select_releases_to_delete:**
    - With keep=3 and 5 dirs, returns the 2 oldest for deletion
    - With keep=3 and only 2 dirs, returns [] (nothing to delete)
    - With keep=3 and 5 dirs, current symlink points at the OLDEST — that one is still retained (not in delete list) even though it's not in top 3 by mtime
    - With `protect={dir1, dir2}`, both are excluded from delete list
    - `keep=0` coerced to 1 with warning; returns all-but-one
    - `keep=-5` coerced to 1
    - Current symlink pointing at a nonexistent dir does not crash (edge case)

    **check_disk_space:**
    - ok=True when both paths have >= threshold free (mock disk_usage)
    - ok=False when /opt is below threshold (message mentions /opt)
    - ok=False when /var/cache is below threshold (message mentions /var/cache)
    - ok=False with both messages when both below
    - ok=False when a path does not exist
    - ok=False when disk_usage raises OSError
  </behavior>
  <action>
    Create `tests/test_releases.py`:

    ```python
    """Unit tests for releases.py (SAFETY-01, SAFETY-02, SAFETY-08)."""
    from __future__ import annotations

    import os
    import shutil
    import time
    from collections import namedtuple
    from pathlib import Path

    import pytest

    from pv_inverter_proxy import releases
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


    def test_list_release_dirs_sorted_newest_first(tmp_path: Path):
        root = tmp_path / "releases"
        root.mkdir()
        _make_release(root, "old", mtime_offset=-1000)
        _make_release(root, "new", mtime_offset=0)
        _make_release(root, "middle", mtime_offset=-500)
        dirs = list_release_dirs(root)
        assert [d.name for d in dirs] == ["new", "middle", "old"]


    # -------- select_releases_to_delete --------

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
        # retained: {r4 (current), r1 (protected)} ∪ top-2-newest-added-until-2
        # retained already has 2, so nothing more added
        # deleted: r2, r3
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


    # -------- check_disk_space --------

    DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


    def _mock_disk_usage(tmp_path: Path, monkeypatch, opt_free: int, vc_free: int) -> tuple[Path, Path]:
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


    def test_disk_space_ok(tmp_path: Path, monkeypatch):
        opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES + 1, MIN_FREE_BYTES + 1)
        r = check_disk_space(opt_path=opt, var_cache_path=vc)
        assert r.ok is True
        assert r.message == ""


    def test_disk_space_opt_low(tmp_path: Path, monkeypatch):
        opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES - 1, MIN_FREE_BYTES + 1)
        r = check_disk_space(opt_path=opt, var_cache_path=vc)
        assert r.ok is False
        assert "opt" in r.message.lower() or str(opt) in r.message


    def test_disk_space_var_cache_low(tmp_path: Path, monkeypatch):
        opt, vc = _mock_disk_usage(tmp_path, monkeypatch, MIN_FREE_BYTES + 1, MIN_FREE_BYTES - 1)
        r = check_disk_space(opt_path=opt, var_cache_path=vc)
        assert r.ok is False
        assert "var_cache" in r.message or str(vc) in r.message


    def test_disk_space_both_low(tmp_path: Path, monkeypatch):
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


    def test_disk_space_oserror(tmp_path: Path, monkeypatch):
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
    ```
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && python -m pytest tests/test_releases.py -x -q</automated>
  </verify>
  <done>All ~25 tests pass. No use of real `/opt` or `/var/cache` — all filesystem work goes through `tmp_path`.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| releases.py -> filesystem | Pure read operations on /opt/pv-inverter-proxy-releases/. Write operations (rmtree) are NOT in this module; this module only returns "what to delete" and the caller (plan 45 updater, running as root) executes. |
| unprivileged caller -> releases.py | Main service (pv-proxy) calls these as read helpers for health/status surface. No mutation. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-43-02-01 | Tampering | select_releases_to_delete returning current dir | mitigate | Current symlink target is ALWAYS added to the protected set, even if the symlink is broken or the caller forgot to protect it. Explicitly tested (test_select_delete_protects_current_even_if_oldest). |
| T-43-02-02 | Tampering | malicious symlink in releases root pointing outside | mitigate | `list_release_dirs` skips symlinks entirely — only real subdirectories count. A symlink inside releases_root pointing at /etc/passwd would be invisible to the retention logic, therefore never deleted. |
| T-43-02-03 | Denial of Service | retention deleting all releases (keep=0 bug) | mitigate | `keep < 1` is coerced to 1 with a warning log. Tested (test_select_delete_keep_zero_coerced, test_select_delete_keep_negative_coerced). |
| T-43-02-04 | Denial of Service | detect_layout on huge or recursive symlink chain | mitigate | Uses `resolve(strict=False)` which does not follow recursively beyond OS limits; catches OSError and returns UNKNOWN. |
| T-43-02-05 | Denial of Service | check_disk_space crashing on missing paths | mitigate | `_free_bytes` checks `path.exists()` first and returns a structured error; `OSError` is caught and converted to `ok=False`. Never raises. |
| T-43-02-06 | Information Disclosure | logging release directory paths | accept | Paths are deterministic (`/opt/pv-inverter-proxy-releases/v<version>-<sha>`) and not sensitive. Logged at WARNING level only on edge cases. |
| T-43-02-07 | Elevation of Privilege | releases.py running as root via import | accept | Module does not exec, does not shell out, uses only pathlib + shutil.disk_usage. Safe to import in either pv-proxy or root context. |
</threat_model>

<validation_strategy>
**SAFETY-01 (blue-green layout):** Validated by `detect_layout` tests — all 6 layout states (MISSING, FLAT, BLUE_GREEN with valid symlink, UNKNOWN from symlink outside root, UNKNOWN from dangling symlink, UNKNOWN from dir without .git) have explicit tests. The actual creation of the layout is plan 43-04 (install.sh migration); this plan validates the detection logic that migration will depend on.

**SAFETY-02 (retention):** Validated by `select_releases_to_delete` tests — 7 cases including the tricky "current symlink points at oldest" edge case and the "broken current symlink" defensive case.

**SAFETY-08 (disk pre-flight):** Validated by `check_disk_space` tests — 6 cases: ok / opt low / vc low / both low / missing path / OSError. Uses monkeypatch to simulate `shutil.disk_usage`, no real filesystem queries.

**Nyquist validation per task:**
- Task 1 verify: Import smoke test + constant assertion (`DEFAULT_KEEP_RELEASES == 3`, `MIN_FREE_BYTES == 500 * 1024 * 1024`). Catches symbol typos and magic-number drift.
- Task 2 verify: Import + live `check_disk_space()` call on the dev machine. This exercises the real `shutil.disk_usage` path (dev machine has plenty of space so ok=True is expected but irrelevant; what matters is the call does not raise).
- Task 3 verify: Full pytest run. Each test maps to a documented behavior in Task 1/2.

**Why unit tests suffice (no LXC integration test in this plan):** The module is a pure library. Its consumers (plan 43-04 migration, plan 45 updater) will have their own integration tests that exercise the real /opt/pv-inverter-proxy-releases layout. Testing this module in isolation keeps the feedback loop fast and pins the contract.
</validation_strategy>

<rollback_plan>
1. **Additive only** — `releases.py` and `test_releases.py` are new files. Delete both to revert.
2. **Git operation:** `git rm src/pv_inverter_proxy/releases.py tests/test_releases.py && git commit -m "revert(43-02): remove releases module"`
3. **Service impact:** Zero. Nothing imports `releases.py` yet. Phase 43-04 and Phase 45 will add callers.
4. **Re-attempt:** Specific failing test identified by pytest output; fix the logic in `releases.py` and re-run.
</rollback_plan>

<verification>
1. `python -m pytest tests/test_releases.py -x -q` passes (all tests)
2. `python -c "from pv_inverter_proxy.releases import *; print(DEFAULT_KEEP_RELEASES, MIN_FREE_BYTES)"` outputs `3 524288000`
3. `python -m py_compile src/pv_inverter_proxy/releases.py` clean
4. Full test suite unaffected: `python -m pytest tests/ -x -q`
</verification>

<success_criteria>
- [ ] `src/pv_inverter_proxy/releases.py` exists, exports all symbols listed in `must_haves.artifacts`
- [ ] Layout constants match architecture decisions (RELEASES_ROOT, INSTALL_ROOT, DEFAULT_KEEP_RELEASES=3, MIN_FREE_BYTES=500MB)
- [ ] `detect_layout` distinguishes 4 states and is tested for all of them
- [ ] `select_releases_to_delete` always protects current symlink target and explicit protect set
- [ ] `select_releases_to_delete` never returns a list that would leave zero releases
- [ ] `check_disk_space` is defensive against missing paths and OSError
- [ ] `tests/test_releases.py` has at least 25 tests, all passing
- [ ] No existing file modified (fully additive)
- [ ] Full test suite passes (no regressions)
</success_criteria>

<output>
After completion, create `.planning/phases/43-blue-green-layout-boot-recovery/43-02-SUMMARY.md` documenting:
- Public API surface (for plans 43-03, 43-04, 45 to reference)
- Layout anchor constants (source of truth for the entire update system)
- The "current symlink is always protected" invariant and why it's enforced twice (caller's protect set + internal current lookup) — defense in depth
- The "no actual filesystem mutation" property — this module is pure read + pure function, callers do the rmtree
- How Phase 45 will extend this with the "previous release" protection by passing `protect={previous_from_status}` into `select_releases_to_delete`
</output>
