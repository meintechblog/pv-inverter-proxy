---
phase: 44-passive-version-badge
plan: "01"
subsystem: updater-backend
tags: [updater, github, asyncio, scheduler, version, etag]
one_liner: "Pure-backend updater subsystem: Version parser, aiohttp GitHub Releases client with ETag cache, and asyncio check scheduler with defer-on-active-user — zero runtime wiring, 77 hermetic tests."
requires: []
provides:
  - "pv_inverter_proxy.updater.version.Version (NamedTuple with parse + ordering)"
  - "pv_inverter_proxy.updater.version.get_current_version()"
  - "pv_inverter_proxy.updater.version.get_commit_hash()"
  - "pv_inverter_proxy.updater.github_client.GithubReleaseClient"
  - "pv_inverter_proxy.updater.github_client.ReleaseInfo (frozen dataclass)"
  - "pv_inverter_proxy.updater.scheduler.UpdateCheckScheduler"
affects:
  - plan: 44-02
    how: "webapp-integration consumes GithubReleaseClient + UpdateCheckScheduler, wires them into __main__.py startup and webapp shared state"
  - plan: 44-03
    how: "frontend-display reads scheduler.last_check_at / last_check_failed_at from /api/update/available for UI footer"
tech-stack:
  added: []
  patterns:
    - "Atomic state file writes via tempfile + os.replace (mirrors state_file.py)"
    - "NamedTuple for version to get free tuple ordering"
    - "Hand-rolled aiohttp mock for hermetic async tests (no aioresponses dep)"
    - "Defensive importlib.metadata.version lookup with 'unknown' fallback"
key-files:
  created:
    - src/pv_inverter_proxy/updater/__init__.py
    - src/pv_inverter_proxy/updater/version.py
    - src/pv_inverter_proxy/updater/github_client.py
    - src/pv_inverter_proxy/updater/scheduler.py
    - tests/test_updater_version.py
    - tests/test_updater_github_client.py
    - tests/test_updater_scheduler.py
  modified: []
decisions:
  - "fetch_latest_release returns None on ALL error paths — no distinction between 'no release' and 'network failure' in Phase 44. Richer FetchResult contract deferred to Phase 47 if UI needs finer fault reporting."
  - "Scheduler last_check_failed_at tracks ONLY scheduler-level exceptions (fetch raised or callback raised). Network errors swallowed inside github_client are NOT reflected here — they surface via github_client's own structlog warnings."
  - "has_active_websocket_client probe failure does NOT block checks — scheduler logs the probe error and falls through to run the check anyway. A broken probe must not permanently lock out update checks."
  - "Zero new runtime dependencies — hand-rolled regex parser (no packaging/semver), hand-rolled aiohttp mock in tests (no aioresponses), importlib.metadata from stdlib."
  - "ETag cache file path is injectable via GithubReleaseClient constructor so tests can use tmp_path — real /etc/pv-inverter-proxy/update-state.json is NEVER touched by the test suite."
  - "Both sync and async on_update_available callbacks are supported via inspect.isawaitable — lets Plan 44-02 pass either a plain webapp setter or an async broadcast coroutine."
metrics:
  duration: "~45 minutes"
  completed: "2026-04-10"
  tasks_completed: 3
  tests_added: 77
  test_runtime_seconds: 2.63
  lines_added: 1794
---

# Phase 44 Plan 01: Updater Backend Summary

Plan 44-01 delivered the pure-backend updater subsystem for v8.0 Phase 44 (Passive Version Badge). Three new modules landed under `src/pv_inverter_proxy/updater/` with full unit-test coverage. Nothing existing was modified — the running service is completely unaffected until Plan 44-02 wires the scheduler into `__main__.py` and `webapp.py`.

## What Shipped

### `src/pv_inverter_proxy/updater/version.py` (CHECK-01 partial)

- `Version(NamedTuple)` with `major / minor / patch` and free tuple ordering.
- `Version.parse(raw)` — accepts `vX.Y` or `vX.Y.Z`, strips whitespace, raises `ValueError` on malformed input. Uses a single anchored regex (`^v?(\d+)\.(\d+)(?:\.(\d+))?$`) that is ReDoS-safe per STRIDE T-44-06.
- `Version.__str__` returns canonical `vX.Y.Z` form.
- `get_current_version()` → string via `importlib.metadata.version("pv-inverter-master")`, with `"unknown"` fallback on `PackageNotFoundError` or any other exception. Never raises.
- `get_commit_hash(install_dir=None)` → 7-char SHA via `subprocess.run(["git", "-C", ..., "rev-parse", "--short", "HEAD"])`. Returns `None` on `FileNotFoundError`, `TimeoutExpired`, `OSError`, non-zero exit, empty stdout. Never raises. Explicit argv list (no `shell=True`) per STRIDE T-44-09.

### `src/pv_inverter_proxy/updater/github_client.py` (CHECK-03, CHECK-06)

- `GithubReleaseClient(session, state_file=DEFAULT_STATE_FILE)` wraps a caller-supplied `aiohttp.ClientSession` (does NOT own it).
- Sends required headers on every request:
  - `User-Agent: pv-inverter-proxy/8.0 (github.com/meintechblog/pv-inverter-master)`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
- Uses `aiohttp.ClientTimeout(total=10)` per CHECK-03.
- ETag cached atomically to `/etc/pv-inverter-proxy/update-state.json` via tempfile + `os.replace` (mirrors `state_file.py`). Cache write failures are best-effort — logged but do NOT crash the fetch.
- On subsequent calls, sends `If-None-Match: <etag>`. 304 returns the cached `ReleaseInfo` (or `None` if no prior cache).
- Filters prereleases: `prerelease: true` → returns `None`, but still persists the new ETag.
- Every error path returns `None` and never raises:
  - `asyncio.TimeoutError`
  - `aiohttp.ClientError`
  - `json.JSONDecodeError`, `KeyError`, `ValueError`
  - HTTP 403, 429, 5xx, any non-200
  - Bare `Exception` (last-resort CHECK-06 catch-all)

### `src/pv_inverter_proxy/updater/scheduler.py` (CHECK-02, CHECK-06, CHECK-07)

- `UpdateCheckScheduler(client, on_update, has_active_ws, interval=3600, initial_delay=60)`.
- `start()` creates an `asyncio.Task` via `asyncio.create_task(..., name="update_check_scheduler")`. Idempotent.
- `stop()` cancels the task and awaits clean shutdown, swallowing `CancelledError`. Idempotent.
- Per-iteration flow:
  1. **Active-user probe (CHECK-07):** if `has_active_websocket_client()` returns True → log `update_check_deferred_user_active`, skip. Probe exceptions are caught and the iteration falls through anyway (broken probe cannot permanently block).
  2. **Fetch:** calls `client.fetch_latest_release()`. Exceptions caught → `last_check_failed_at = time.time()`.
  3. **Callback:** `on_update_available(release)` — `inspect.isawaitable` detects async and awaits. Exceptions also counted as iteration failure.
  4. **Success:** `last_check_at = time.time()`, log `update_available` or `update_not_available`.
- `CancelledError` is the only exception allowed to propagate (asyncio contract).
- Supports both sync (`def cb(r)`) and async (`async def cb(r)`) callbacks.
- Read-only properties `last_check_at` and `last_check_failed_at` for UI surfacing.

## Tests (77 total, 2.63s runtime)

| File | Tests | Covers |
|---|---|---|
| `tests/test_updater_version.py` | 41 | Parse success/failure, tuple ordering, `__str__`, `get_current_version` fallback (PackageNotFoundError + generic Exception), `get_commit_hash` (no-git, missing binary, timeout, OSError, non-zero rc, success, 7-char trim, empty stdout, default install dir). |
| `tests/test_updater_github_client.py` | 23 | Happy-path 200 with full header assertion, 10s timeout verification, ETag persistence + `If-None-Match` round-trip, 304 with/without prior cache, 403, 429, 5xx (parametrized 500/502/503/504), 418, prerelease filter, `asyncio.TimeoutError`, `aiohttp.ClientError`, malformed JSON, non-dict JSON, bare `Exception`, state file injection, non-writable state file, corrupt state file on load, default state file constant. |
| `tests/test_updater_scheduler.py` | 13 | Initial delay, interval timing, defer-on-active-user, defer-then-run flip, probe exception fallthrough, exception in fetch sets failed_at, exception in callback sets failed_at, clean cancellation, idempotent stop, async callback awaited, sync callback called, last_check_at updated on success, None release still counts as success. |

All tests hermetic — zero real network, tmp_path for every state file. Full updater suite runs in 2.63s including the timing-based scheduler tests.

**Regression check:** Full `pytest tests/ -q` run shows 761 prior-passing tests still pass. One pre-existing failure (`tests/test_webapp.py::test_config_get_venus_defaults`) is unrelated — it was already broken on HEAD before this plan. Logged to `.planning/phases/44-passive-version-badge/deferred-items.md` per scope boundary rule.

## Commits

| Task | Hash | Description |
|---|---|---|
| 1 | `0dacca6` | `feat(44-01): add version parser and current version resolution` |
| 2 | `fa0b2a7` | `feat(44-01): add GitHub release client with ETag caching` |
| 3 | `d4b0806` | `feat(44-01): add update check scheduler with defer-on-active-user` |

Each task was TDD: tests written first, then implementation. All three tasks passed their verification pytest run on first implementation attempt.

## Requirements Coverage (Nyquist)

| Requirement | How Validated | Test |
|---|---|---|
| CHECK-02 (asyncio scheduler, 1h default) | Unit | `test_updater_scheduler.py::test_interval_between_checks` + `DEFAULT_INTERVAL_SECONDS = 3600.0` constant |
| CHECK-03 (headers, timeout, ETag cache) | Unit | `test_fetch_sends_required_headers`, `test_fetch_uses_10s_timeout`, `test_fetch_persists_etag_and_sends_if_none_match_on_next_call` |
| CHECK-06 (fault tolerance) | Unit | All `test_fetch_{403,429,5xx,timeout,client_error,malformed_json,missing_key,unexpected_exception}_returns_none_no_raise` + `test_exception_in_{fetch,callback}_sets_failed_at_and_continues` |
| CHECK-07 (defer on active user) | Unit | `test_defer_when_user_active`, `test_defer_then_run_when_user_disconnects`, `test_active_probe_exception_does_not_crash` |

CHECK-01 (version source of truth) is partially delivered here (the version functions exist); the `/api/update/available` endpoint in CHECK-05 lands in Plan 44-02. CHECK-04 (UI badge) lands in Plan 44-03.

## Deviations from Plan

**None.** Plan executed exactly as written. Zero auto-fixes, zero Rule-4 architectural questions. All three tasks passed their pytest verification on the first implementation attempt.

Minor clarifications applied without deviation:
- Initial delay of `0.0` in scheduler tests is supported (scheduler skips the `asyncio.sleep` when `initial_delay <= 0`).
- Scheduler's `_run` guards `asyncio.sleep(0)` — we use a `> 0` check so tests with zero initial delay don't queue an unnecessary sleep.
- Added `test_stop_is_idempotent` and `test_none_release_still_updates_last_check_at` beyond the 11 tests in the plan — both were natural edge cases the design supports.
- Added parametrized 500/502/503/504 coverage instead of a single 500 test (covers all 5xx codes per CHECK-06).

## Threat Model — No New Flags

All files created/modified are covered by the plan's `<threat_model>` (T-44-01 through T-44-09). No new network endpoints, no new auth paths, no new file writes outside the documented `/etc/pv-inverter-proxy/update-state.json` cache. The only new subprocess call (`git rev-parse --short HEAD`) uses an explicit argv list — mitigation for T-44-09 is in place.

## Known Stubs

**None.** The plan is purely additive library code with no UI wiring. Plan 44-02 consumes these modules; this plan produces no dead code paths.

## Follow-ups for Plan 44-02

Plan 44-02 should:
1. Import `GithubReleaseClient` and `UpdateCheckScheduler` in `__main__.py`.
2. Share the existing aiohttp `ClientSession` (used for Shelly polling) with the GitHub client — do NOT spawn a second session.
3. Wire `has_active_websocket_client` to check `app["ws_clients"]` count (>0 means active).
4. Register `scheduler.stop()` in the shutdown/cleanup path.
5. Pass a callback that updates `app["latest_release"]` with the `ReleaseInfo` so webapp endpoints can read it.
6. Add `/api/update/available` endpoint returning `{current_version, latest_version, release_notes, published_at, tag_name, last_check_at, last_check_failed_at}` — use `get_current_version()` for `current_version` and `scheduler.last_check_at/last_check_failed_at` for the timestamps (CHECK-05, CHECK-06).
7. Consider investigating the pre-existing `test_config_get_venus_defaults` failure since 44-02 modifies webapp.py anyway.

## Self-Check: PASSED

**Files created (verified on disk):**
- `src/pv_inverter_proxy/updater/__init__.py` — FOUND
- `src/pv_inverter_proxy/updater/version.py` — FOUND
- `src/pv_inverter_proxy/updater/github_client.py` — FOUND
- `src/pv_inverter_proxy/updater/scheduler.py` — FOUND
- `tests/test_updater_version.py` — FOUND
- `tests/test_updater_github_client.py` — FOUND
- `tests/test_updater_scheduler.py` — FOUND

**Commits (verified via git log):**
- `0dacca6` — FOUND
- `fa0b2a7` — FOUND
- `d4b0806` — FOUND

**Test results:** 77/77 passing, 2.63s runtime.
**Import smoke test:** `from pv_inverter_proxy.updater.{version,github_client,scheduler} import ...` → `ok`.
**Full regression:** 761/762 existing tests still pass (1 pre-existing failure unrelated to this plan, logged to deferred-items.md).
