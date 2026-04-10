---
phase: 44-passive-version-badge
plan: "02"
subsystem: webapp-integration
tags: [updater, webapp, asyncio, aiohttp, websocket, version, scheduler]
one_liner: "Wire Plan 44-01 updater backend into the running service: bump to 8.0.0, extend AppContext, register GET /api/update/available, broadcast available_update over WS, and start UpdateCheckScheduler on a shared aiohttp session with module-level callback."
requires:
  - 44-01
provides:
  - "pyproject.toml version 8.0.0 (so importlib.metadata returns the real build)"
  - "AppContext.current_version / current_commit / available_update / update_last_check_at / update_last_check_failed_at fields"
  - "GET /api/update/available route returning {current_version, current_commit, available_update, last_check_at, last_check_failed_at}"
  - "broadcast_available_update(app) helper in webapp.py"
  - "ws_handler initial push includes available_update snapshot on client connect"
  - "Module-level _on_update_available(app_ctx, release) in __main__.py (importable for tests)"
  - "Module-level _has_active_ws_client(app_ctx) in __main__.py"
  - "Single shared aiohttp.ClientSession for the update scheduler, closed in graceful shutdown"
affects:
  - plan: 44-03
    how: "consumes GET /api/update/available and WS 'available_update' messages for the footer badge + release-notes modal"
  - plan: 45
    how: "reuses the shared aiohttp.ClientSession pattern and extends broadcast_available_update with update_in_progress events for the self-update flow"
tech-stack:
  added: []
  patterns:
    - "Shared aiohttp.ClientSession created once per process, closed in graceful shutdown"
    - "Module-level scheduler callback bound via tiny closure so tests can import the function directly"
    - "Coarse-grained broadcast de-dup: compare available_update dict before calling broadcast_available_update"
    - "Stale-preserving semantics: a transient fetch error (release=None) leaves available_update unchanged"
    - "ws_handler initial-push pattern mirrors device_list: one send_json on connect, broadcast_* for follow-ups"
key-files:
  created:
    - tests/test_updater_webapp_routes.py
    - tests/test_updater_wiring.py
  modified:
    - pyproject.toml
    - src/pv_inverter_proxy/context.py
    - src/pv_inverter_proxy/webapp.py
    - src/pv_inverter_proxy/__main__.py
decisions:
  - "Refactored the scheduler callback from a closure inside run_with_shutdown() into a module-level async _on_update_available(app_ctx, release) so tests can import it directly — addresses plan-checker's non-blocking concern #2 about testability."
  - "Shared aiohttp.ClientSession is created once in run_with_shutdown() and passed to GithubReleaseClient — no per-request sessions, no second session for GitHub. Matches STACK.md recommendation and the Plan 44-01 SUMMARY follow-up #2."
  - "Bumped version 6.0.0 -> 8.0.0. CHECK-01 requires importlib.metadata.version('pv-inverter-master') to return the real version; 6.0.0 would have been user-visibly wrong."
  - "When the scheduler callback receives release=None (network error, prerelease filtered, or no release), it leaves app_ctx.available_update UNCHANGED. A transient failure must not clear a previously-announced update; the scheduler's own last_check_failed_at tracks the failure and the next successful fetch will refresh state. Prevents UI flicker."
  - "When current_version is 'unknown' or unparseable (dev builds), the callback DEFENSIVELY advertises the release as available so the user always has an upgrade path — better to show a spurious badge than to hide a real release."
  - "Broadcast de-dup is coarse-grained (dict equality). Follow-up in Phase 45 may switch to hash-based equality if broadcasts become hot, but for a 1h scheduler interval the current approach is more than fast enough."
metrics:
  duration: "~25 minutes"
  completed: "2026-04-10"
  tasks_completed: 3
  tests_added: 24
  lines_added: 687
  files_modified: 4
  files_created: 2
---

# Phase 44 Plan 02: Webapp Integration Summary

Plan 44-02 wires the pure-backend updater subsystem delivered in Plan 44-01 into the running `pv-inverter-proxy` service. The running process now resolves its own version + git commit at startup, exposes them via `GET /api/update/available`, runs the `UpdateCheckScheduler` as an asyncio task alongside the heartbeat / device-list / healthy-flag loops, and broadcasts `available_update` messages over the existing WebSocket channel whenever the advertised release changes. No frontend changes yet (Plan 44-03 consumes this surface for the footer badge + release-notes modal).

## What Shipped

### `pyproject.toml` — version bump (CHECK-01)

`version = "6.0.0"` -> `version = "8.0.0"`. A single-line change that makes `importlib.metadata.version("pv-inverter-master")` return the real build identifier once the LXC deploy in Plan 44-03 runs `pip install -e .`.

### `src/pv_inverter_proxy/context.py` — AppContext extension

Added five new fields to the `AppContext` dataclass (all defaulting to `None`), sharing the existing convention used for `mqtt_pub_*` / `venus_*` state:

```python
# Phase 44: Passive Version Badge (CHECK-01, CHECK-05, CHECK-06)
current_version: str | None = None
current_commit: str | None = None
available_update: dict | None = None
update_last_check_at: float | None = None
update_last_check_failed_at: float | None = None
```

No new imports — all types are primitives.

### `src/pv_inverter_proxy/webapp.py` — REST route + WS snapshot + broadcast helper

Four additive changes:

1. **Import** `Version` from `pv_inverter_proxy.updater.version` alongside the existing updater-adjacent imports.
2. **`update_available_handler`** — new async handler placed immediately after `health_handler`. Reads `app_ctx.current_version`, `current_commit`, `available_update`, `update_last_check_at`, `update_last_check_failed_at` and returns them as JSON. Wired in `create_webapp()` at `GET /api/update/available`.
3. **`broadcast_available_update(app)`** — new helper placed next to `broadcast_device_list`, mirroring its payload-dump + dead-client-prune pattern exactly. Emits `{"type": "available_update", "data": {...}}` to every connected WebSocket client.
4. **`ws_handler` initial push** — after the `device_list` send, the handler now also sends one `available_update` message so fresh clients immediately know the current version + any pending release without waiting for the next broadcast.

### `src/pv_inverter_proxy/__main__.py` — scheduler wiring

Added imports for `aiohttp`, the three updater modules (`version`, `github_client`, `scheduler`), `releases.INSTALL_ROOT`, and `broadcast_available_update` from webapp.

**New module-level functions** (placed above `main()`, so tests can import them directly):

- `async def _on_update_available(app_ctx, release)` — scheduler callback. Bumps `update_last_check_at` every iteration; if `release` is `None` it preserves the existing `available_update`; otherwise it version-compares against `app_ctx.current_version` using `Version.parse`, defensively treats `"unknown"` / unparseable current versions as "show the release", and builds a plain-dict summary of `tag_name`, `release_notes`, `published_at`, `html_url`. Broadcasts via `broadcast_available_update(app_ctx.webapp)` only when the dict actually changed (coarse de-dup) and the webapp is attached.
- `def _has_active_ws_client(app_ctx) -> bool` — CHECK-07 probe. Returns `False` when `app_ctx.webapp is None`, when `ws_clients` is missing, or when the weakset is empty; returns `True` otherwise. Defensive `TypeError` guard for malformed client containers.

**Inside `run_with_shutdown`:**

- Immediately after signal handler registration, resolve `current_version` via `get_current_version()` and `current_commit` via `get_commit_hash(INSTALL_ROOT)`. Both are cached on `app_ctx`. A top-level try/except defaults to `"unknown"` / `None` on unexpected failures.
- After the heartbeat task is created, construct a **single shared** `aiohttp.ClientSession` with the required GitHub `User-Agent` header, pass it to `GithubReleaseClient`, bind the module-level callback via a tiny `async _update_cb` closure, bind the probe via `_update_active_probe`, and call `UpdateCheckScheduler.start()`. The returned task is tracked as `update_scheduler_task`.
- In the graceful-shutdown block, `update_scheduler_task` is added to the cancel loop alongside `heartbeat_task`, `device_list_task`, `healthy_flag_task`. After the cancel loop, `update_http_session.close()` runs in a best-effort try/except so shutdown cannot block on a hung HTTP session.

### Tests — 24 new tests

**`tests/test_updater_webapp_routes.py`** (9 tests):

| Test | Covers |
| --- | --- |
| `test_update_available_no_update` | Cold state: version resolved, no release advertised |
| `test_update_available_with_update` | Full release dict passes through verbatim |
| `test_update_available_unknown_version` | `"unknown"` / `None` commit surface correctly |
| `test_update_available_failed_check` | CHECK-06: `last_check_failed_at` surfaced when set |
| `test_update_available_cold_start` | Both timestamps `None` before the first check |
| `test_broadcast_available_update_no_clients` | No-op when `ws_clients` empty |
| `test_broadcast_available_update_sends_payload` | Single client receives full snapshot as JSON |
| `test_broadcast_available_update_prunes_dead_client` | `ConnectionResetError` -> client discarded |
| `test_broadcast_available_update_missing_app_ctx` | No-op when `app_ctx` absent from app |

All use `aiohttp.test_utils.make_mocked_request` and a tiny `_FakeWs` class — no TCP server, no event loop beyond the implicit one provided by `asyncio_mode = "auto"`.

**`tests/test_updater_wiring.py`** (15 tests):

| Test | Covers |
| --- | --- |
| `test_newer_release_sets_available_update` | Newer release -> dict populated + `last_check_at` bumped |
| `test_same_version_clears_available_update` | Same version -> stale marker cleared |
| `test_older_release_clears_available_update` | Older release (dev build) -> stale marker cleared |
| `test_none_release_leaves_state_unchanged` | Transient fetch error -> `available_update` preserved |
| `test_unknown_current_version_shows_release_as_available` | Defensive "always show" for unknown current |
| `test_malformed_tag_does_not_crash` | Unparseable latest tag -> no crash + cleared |
| `test_unparseable_current_version_defensively_advertises` | Dev-build current version -> always show release |
| `test_release_fields_persisted_verbatim` | Full ReleaseInfo round-trips through the dict |
| `test_broadcast_invoked_when_update_changes` | Transition None -> dict triggers exactly one broadcast |
| `test_broadcast_skipped_when_nothing_changes` | Equal dict re-poll -> no broadcast (coarse de-dup) |
| `test_broadcast_skipped_when_webapp_missing` | `app_ctx.webapp is None` -> state still updated, no broadcast |
| `test_has_active_ws_client_no_webapp` | `webapp is None` -> `False` |
| `test_has_active_ws_client_empty_set` | Empty `ws_clients` -> `False` |
| `test_has_active_ws_client_with_connected_client` | Non-empty `ws_clients` -> `True` |
| `test_has_active_ws_client_missing_key` | `ws_clients` key absent -> `False` |

The tests import `_on_update_available` and `_has_active_ws_client` **directly** from `pv_inverter_proxy.__main__`, exercising the module-level refactor end-to-end.

## Test Results

| Suite | Count | Runtime |
| --- | --- | --- |
| `tests/test_updater_webapp_routes.py` | 9 passed | 0.35s |
| `tests/test_updater_wiring.py` | 15 passed | 0.36s |
| `tests/test_updater_version.py` (44-01) | 41 passed | — |
| `tests/test_updater_github_client.py` (44-01) | 23 passed | — |
| `tests/test_updater_scheduler.py` (44-01) | 13 passed | — |
| **All updater + context + websocket** | **109 passed** | **8.00s** |
| **Full `tests/` suite** | **785 passed, 1 failed** | **45.98s** |

The single failure (`tests/test_webapp.py::test_config_get_venus_defaults`) is the pre-existing failure documented in `.planning/phases/44-passive-version-badge/deferred-items.md` by Plan 44-01. It is unrelated to Phase 44 and existed before either plan started. No new regressions introduced by this plan.

## Commits

| Task | Hash | Description |
| --- | --- | --- |
| 1 | `298f12f` | `feat(44-02): bump version to 8.0.0 and extend AppContext with update fields` |
| 2 | `41a6e2f` | `feat(44-02): add update availability route and WS broadcast helper` |
| 3 | `bc591ff` | `feat(44-02): wire update scheduler into main startup` |

Each task was verified against the plan's `<verify>` block and the full test suite before committing.

## Requirements Coverage (Nyquist)

| Requirement | How Validated | Test |
| --- | --- | --- |
| CHECK-01 (version in footer from importlib.metadata) | Unit + manual in 44-03 | Version bump verified via `grep`, `_on_update_available` tests consume `ctx.current_version` |
| CHECK-02 (scheduler as asyncio task) | Unit + manual in 44-03 | `UpdateCheckScheduler.start()` called in `run_with_shutdown`, task registered in shutdown cancel tuple |
| CHECK-05 (GET /api/update/available response shape) | Unit | `test_update_available_*` (5 tests cover no-update, with-update, unknown-version, failed-check, cold-start) |
| CHECK-06 (fault tolerance + failed_check surfaced) | Unit | `test_update_available_failed_check` + `test_none_release_leaves_state_unchanged` |
| CHECK-07 (defer when WS client connected) | Unit | `test_has_active_ws_client_*` (4 tests cover no-webapp, empty, connected, missing-key) |

CHECK-04 (UI badge display) and the end-to-end deploy/curl smoke test land in Plan 44-03.

## Deviations from Plan

**None — plan executed exactly as written** with one cosmetic simplification:

- Plan's Task 3 suggested either a closure-based callback (with a `_on_update_available_pure` helper in the test file for drift detection) OR a module-level refactor. I used the **module-level refactor** as recommended by the plan, so tests import directly from `__main__` with no drift-risk helper. This matches the plan-checker's non-blocking concern #2 about callback testability and keeps the test file thin.

No auto-fixes (Rules 1-3) required. No architectural questions (Rule 4).

## Auth / Human Gates

None. This plan is pure code — no deploys, no secrets, no interactive verification. Plan 44-03 owns the LXC deploy + curl verification.

## Known Stubs

**None.** All fields are wired end-to-end: the scheduler writes into `app_ctx`, the route reads from `app_ctx`, the WebSocket initial-push reads from `app_ctx`, and the broadcast helper reads from `app_ctx`. No placeholder strings, no mock data, no unwired components. The only "empty" state is the legitimate `None` default before the first scheduler iteration (which the cold-start test explicitly covers).

## Threat Model — No New Flags

All changes are covered by the plan's `<threat_model>` (T-44-10 through T-44-15):

- No new network endpoints beyond `GET /api/update/available`, which exposes only already-public data (GitHub release info + pyproject version).
- No new file writes outside the ETag cache already established in Plan 44-01.
- The scheduler callback is single-writer (only the scheduler task mutates `update_*` fields); webapp handlers and the WS broadcast helper are read-only.
- The shared `aiohttp.ClientSession` is closed in the shutdown path inside a try/except (T-44-13 mitigation).

No new threat surface introduced.

## Follow-ups for Plan 44-03

1. Consume `GET /api/update/available` on page load to populate the footer badge.
2. Subscribe to WS `{"type": "available_update"}` messages for live updates without polling.
3. Wire the release-notes modal to `available_update.release_notes` and `html_url`.
4. Manually verify on LXC after deploy: `curl http://192.168.3.191/api/update/available` should return real `current_version: "8.0.0"` and populated `current_commit`.
5. Inspect logs: `journalctl -u pv-inverter-proxy -n 50` should show `version_resolved version=8.0.0 commit=<7char>` and `update_scheduler_started`. After the first 60s initial delay, a `update_check_*` log line should appear.
6. Consider investigating the pre-existing `test_config_get_venus_defaults` failure in a separate cleanup pass (now tracked for two plans).

## Self-Check: PASSED

**Files created (verified on disk):**
- `tests/test_updater_webapp_routes.py` — FOUND
- `tests/test_updater_wiring.py` — FOUND

**Files modified (verified via git diff stats):**
- `pyproject.toml` — FOUND (1 line changed, version 6.0.0 -> 8.0.0)
- `src/pv_inverter_proxy/context.py` — FOUND (7 lines added: 5 new fields + comment)
- `src/pv_inverter_proxy/webapp.py` — FOUND (route, handler, broadcast helper, ws initial push, import)
- `src/pv_inverter_proxy/__main__.py` — FOUND (imports, version resolution, scheduler wiring, shutdown extension, module-level callback + probe)

**Commits (verified via git log):**
- `298f12f` — FOUND
- `41a6e2f` — FOUND
- `bc591ff` — FOUND

**Import smoke tests:**
- `from pv_inverter_proxy.webapp import update_available_handler, broadcast_available_update` — ok
- `from pv_inverter_proxy.__main__ import _on_update_available, _has_active_ws_client` — ok
- `from pv_inverter_proxy.context import AppContext; ctx = AppContext(); ctx.current_version` — ok

**Test results:**
- `tests/test_updater_webapp_routes.py`: 9 passed
- `tests/test_updater_wiring.py`: 15 passed
- Full suite: 785 passed, 1 pre-existing unrelated failure (`test_config_get_venus_defaults`)
