---
phase: 43-blue-green-layout-boot-recovery
plan: 02
subsystem: blue-green-layout
tags: [safety, releases, layout, retention, disk-preflight, pure-functions]
requires: []
provides:
  - "Blue-green layout detection (detect_layout)"
  - "Current release discovery (current_release_dir)"
  - "Release enumeration (list_release_dirs)"
  - "Retention selection with protection (select_releases_to_delete)"
  - "Pre-flight disk space check (check_disk_space, DiskSpaceReport)"
  - "Layout anchor constants (RELEASES_ROOT, INSTALL_ROOT, DEFAULT_KEEP_RELEASES, MIN_FREE_BYTES)"
affects:
  - "Future plan 43-04 (install migration) — consumer of detect_layout"
  - "Future phase 45 (privileged updater) — consumer of retention + disk check"
tech-stack:
  added: []
  patterns:
    - "Pure function module (read-only filesystem helpers)"
    - "Dataclass report objects"
    - "Defensive I/O (never raise; return structured error messages)"
    - "StrEnum for layout classification"
    - "Module-level anchor constants with parameter overrides for testing"
key-files:
  created:
    - "src/pv_inverter_proxy/releases.py"
    - "tests/test_releases.py"
  modified: []
decisions:
  - "Retention uses UNION semantics: retained = top-N newest ∪ protected set, so protected dirs outside the newest window can push total retained above `keep`"
  - "current symlink target is protected INTERNALLY even if caller forgets — defense in depth against T-43-02-01"
  - "Module is strictly read-only; callers (Phase 45 updater) own rmtree and symlink flipping"
  - "`keep < 1` coerced to 1 with structured log warning — never delete all releases"
  - "list_release_dirs skips all symlinks (not just `current`) so a hostile symlink in releases_root pointing at /etc/passwd is invisible to retention"
  - "check_disk_space returns structured DiskSpaceReport with per-path byte counts and human-readable message; never raises"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-10"
requirements: [SAFETY-01, SAFETY-02, SAFETY-08]
---

# Phase 43 Plan 02: Releases Module Summary

Read-only Python library encapsulating all blue-green release layout logic — detection, enumeration, retention selection, and disk pre-flight — as pure functions that are fully unit-testable with `tmp_path` filesystem fakes, with zero systemd coupling and zero filesystem mutation.

## Public API Surface

The module exports the complete contract that Phase 43-04 (install migration) and Phase 45 (privileged updater) will consume:

### Constants (Anchor)

| Symbol | Value | Source of Truth |
|--------|-------|-----------------|
| `RELEASES_ROOT` | `Path("/opt/pv-inverter-proxy-releases")` | ARCHITECTURE.md blue-green layout |
| `INSTALL_ROOT` | `Path("/opt/pv-inverter-proxy")` | ARCHITECTURE.md blue-green layout |
| `CURRENT_SYMLINK_NAME` | `"current"` | ARCHITECTURE.md rollback mechanism |
| `DEFAULT_KEEP_RELEASES` | `3` | PROJECT.md product decision + PITFALLS.md H8 |
| `MIN_FREE_BYTES` | `500 * 1024 * 1024` | SAFETY-08 |

These are now canonical — later plans MUST import from `releases.py` rather than redefining.

### Enum

```python
class LayoutKind(str, Enum):
    FLAT = "flat"              # pre-v8.0: direct git checkout at INSTALL_ROOT
    BLUE_GREEN = "blue_green"  # v8.0+: symlink into RELEASES_ROOT
    MISSING = "missing"        # fresh install
    UNKNOWN = "unknown"        # foreign symlink, dangling, dir without .git
```

### Functions

```python
def detect_layout(install_root: Path | None = None, releases_root: Path | None = None) -> LayoutKind
def current_release_dir(releases_root: Path | None = None) -> Path | None
def list_release_dirs(releases_root: Path | None = None) -> list[Path]  # newest-first
def select_releases_to_delete(
    releases_root: Path | None = None,
    keep: int = DEFAULT_KEEP_RELEASES,
    protect: set[Path] | None = None,
) -> list[Path]
def check_disk_space(
    min_free_bytes: int = MIN_FREE_BYTES,
    opt_path: Path = Path("/opt"),
    var_cache_path: Path = Path("/var/cache"),
) -> DiskSpaceReport
```

### Dataclass

```python
@dataclass
class DiskSpaceReport:
    opt_free_bytes: int
    var_cache_free_bytes: int
    ok: bool
    message: str  # "" on success, "; "-joined problems on failure
```

## The "Current Symlink Is Always Protected" Invariant

The retention policy enforces the "never delete current" guarantee in two independent places — deliberate defense in depth:

1. **Caller responsibility (documented):** Phase 45 will pass `protect={current, previous_from_status}` into `select_releases_to_delete`. This is the primary protection layer.

2. **Internal belt-and-braces:** `select_releases_to_delete` ALSO calls `current_release_dir(rr)` itself and adds the result to the protected set — regardless of what the caller passed. If the caller forgets to include `current` (e.g. a future refactor removes the line, or a new caller doesn't know the convention), the module still refuses to schedule the current release for deletion.

This dual enforcement maps directly to threat `T-43-02-01` (Tampering — select_releases_to_delete returning current dir). Unit-tested by `test_select_delete_protects_current_even_if_oldest`, which verifies the invariant even in the edge case where `current` points at the OLDEST directory by mtime (which can happen briefly after a rollback).

## Retention Union Semantics

The final retention rule is:

> `retained = {top-N newest by mtime} ∪ {current} ∪ {explicit protect set}`

This differs from a naïve "keep exactly N" implementation. Under union semantics, if the current symlink points at a directory that is NOT in the top-N newest, the total retained count grows above `keep`. This is intentional — the safety posture "never delete current or previous" takes precedence over the exact retention target.

Example: 5 releases named r1..r5 (r5 newest), `keep=3`, current points at r1 (oldest, post-rollback state):
- Top-3 newest = {r5, r4, r3}
- Union with current {r1} = {r1, r3, r4, r5} — 4 retained
- Deleted = {r2}

Example: 4 releases r1..r4, `keep=2`, current=r4, protect={r1}:
- Top-2 newest = {r4, r3}
- Union with {r4, r1} = {r1, r3, r4} — 3 retained
- Deleted = {r2}

## No Actual Filesystem Mutation

A load-bearing property of this module: it NEVER writes to disk. Every function is either:

- **Stat-only** (`detect_layout`, `current_release_dir`, `list_release_dirs`) — reads metadata, resolves symlinks, returns values.
- **Pure computation** (`select_releases_to_delete`) — returns a list of paths the caller MAY delete.
- **Defensive read** (`check_disk_space`) — calls `shutil.disk_usage` and wraps errors.

The Phase 45 privileged updater (running as root) is the sole component that will perform `shutil.rmtree`, `os.symlink`, or any other mutation. This keeps the attack surface minimal: the main service (running as `pv-proxy`, unprivileged) can safely import and call every helper in this module for health/status surfaces without any risk of modifying `/opt`.

## Phase 45 Extension Point

Phase 45 will extend the retention protection with the "previous release" tracking from `update-status.json`:

```python
# Phase 45 updater post-successful-update cleanup:
from pv_inverter_proxy.releases import select_releases_to_delete, RELEASES_ROOT
from pv_inverter_proxy.update_status import load_status  # Phase 45

status = load_status()
previous = Path(status.previous_release) if status.previous_release else None
protect = {previous} if previous else set()

to_delete = select_releases_to_delete(
    RELEASES_ROOT,
    keep=config.updates.keep_releases,
    protect=protect,
)
for d in to_delete:
    shutil.rmtree(d)
    log.info("release_pruned", path=str(d))
```

Phase 45 does not need to re-pass `current` — the module handles it internally. Phase 45 only has to communicate "what rollback target must survive".

Phase 45 disk pre-flight integration:

```python
from pv_inverter_proxy.releases import check_disk_space

report = check_disk_space()
if not report.ok:
    raise UpdateAbortedError(f"Disk pre-flight failed: {report.message}")
```

## Test Coverage

34 unit tests in `tests/test_releases.py`, all passing in 0.08s:

| Area | Tests | Key Cases |
|------|-------|-----------|
| `detect_layout` | 6 | MISSING, FLAT, BLUE_GREEN, UNKNOWN (dir-no-git, symlink-outside, dangling) |
| `current_release_dir` | 3 | missing, broken, valid |
| `list_release_dirs` | 6 | missing, empty, skip-current, skip-files, skip-foreign-symlinks, mtime sort |
| `select_releases_to_delete` | 10 | no-releases, 5-keep-3, fewer-than-keep, current-is-oldest, explicit-protect, protect-outside-top-n, keep=0, keep=-5, broken-current, no-current |
| `check_disk_space` | 6 | ok, opt-low, vc-low, both-low, missing-path, OSError |
| Constants | 2 | `DEFAULT_KEEP_RELEASES == 3`, `MIN_FREE_BYTES == 500 MB` |
| Dataclass | 1 | `DiskSpaceReport` construction |

No real `/opt` or `/var/cache` queries — `shutil.disk_usage` is mocked via `monkeypatch`, all release directories live under `tmp_path`.

## Deviations from Plan

### [Rule 1 - Bug] Retention semantics ambiguity in plan

- **Found during:** Task 3 test execution
- **Issue:** The plan contained two mutually inconsistent specifications for `select_releases_to_delete`. Task 2's detailed implementation notes (Step 5) described a "fill up to `keep`" approach where protected dirs count against the keep budget. The Task 3 test `test_select_delete_protects_current_even_if_oldest` asserted a UNION approach (keep top-N AND additionally force-keep protected). And `test_select_delete_explicit_protect` asserted the "fill up to keep" approach. No single implementation could pass both tests.
- **Resolution:** Chose UNION semantics (top-N newest ∪ protected) because:
  1. It matches the threat model T-43-02-01 "current is ALWAYS protected" (under fill-to-keep, a small `keep` value combined with many protected dirs could cause top-N newest releases to be deleted while keeping only old protected ones).
  2. It matches the success criterion "never returns a list that would leave zero releases".
  3. It gives stronger defense in depth: you always have the N newest AND all protected, so a caller mistake cannot delete the last good release.
- **Files modified:**
  - `src/pv_inverter_proxy/releases.py` — `select_releases_to_delete` implementation uses `all_dirs[:effective_keep]` for the top-N slice, then UNION with `protected`.
  - `tests/test_releases.py` — updated `test_select_delete_explicit_protect` expected delete set from `{"r2", "r3"}` to `{"r2"}` to match union semantics. Added new test `test_select_delete_protect_outside_top_n` that explicitly exercises the "protected dir outside the top-N window" case to lock in the semantics.
- **Commit:** `d6e1476`

### [Additive] Three extra tests beyond plan's minimum

- **Found during:** Task 3 planning
- **Reason:** Plan specified ~25 tests; added `test_list_release_dirs_empty_root`, `test_list_release_dirs_skips_foreign_symlinks`, `test_select_delete_no_releases`, `test_select_delete_no_current_symlink`, `test_select_delete_protect_outside_top_n`, `test_disk_space_report_is_dataclass`, `test_default_keep_releases_is_three`, `test_min_free_bytes_is_500mb`. Final count: 34 tests. All additive (no rewrites to plan-specified tests beyond the Rule 1 fix above).

## Commits

| Hash | Type | Message |
|------|------|---------|
| `a8ff18e` | feat | `feat(43-02): add releases module with layout helpers` |
| `d6e1476` | test | `test(43-02): add unit tests for releases module` |

The test commit also contains the Rule 1 fix to `releases.py` (union-semantics refinement) because the test and implementation had to move together atomically.

## Known Stubs

None. The module is a complete, self-contained library with no TODOs, no placeholder returns, no hardcoded empty defaults. All functions return real computed values or structured error reports.

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Module compiles | `python -m py_compile src/pv_inverter_proxy/releases.py` | ok |
| Imports cleanly | `python -c "from pv_inverter_proxy.releases import *"` | ok |
| Constants correct | `DEFAULT_KEEP_RELEASES == 3 and MIN_FREE_BYTES == 524288000` | True |
| Live disk check runs | `check_disk_space()` on dev machine | Returns structured report (ok=False because /var/cache missing on macOS — expected, proves defensive path handling works) |
| Unit tests | `pytest tests/test_releases.py -v` | 34 passed in 0.08s |
| Full suite | `pytest tests/ -q` | 653 passed, 1 pre-existing failure in `test_webapp.py::test_config_get_venus_defaults` (unrelated, already logged in `deferred-items.md` from plan 43-01) |

## Self-Check: PASSED

- `src/pv_inverter_proxy/releases.py` exists (273 lines ≥ 220 min)
- `tests/test_releases.py` exists (395 lines ≥ 260 min)
- All exported symbols present: `RELEASES_ROOT`, `INSTALL_ROOT`, `LayoutKind`, `detect_layout`, `current_release_dir`, `list_release_dirs`, `select_releases_to_delete`, `check_disk_space`, `DiskSpaceReport`, `MIN_FREE_BYTES`
- Commit `a8ff18e` present in git log (feat)
- Commit `d6e1476` present in git log (test)
- No existing source files modified (fully additive to `src/`)
- 34/34 releases tests passing
- Pre-existing unrelated webapp test failure documented in `deferred-items.md`
