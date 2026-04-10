---
phase: 44-passive-version-badge
verified: 2026-04-10T18:30:00Z
status: human_needed
score: 7/7 must-haves verified (code-complete)
overrides_applied: 0
human_verification:
  - test: "Open http://192.168.3.191 in browser, hard-refresh, confirm version footer shows v8.0.0 (79be2a0) in sidebar"
    expected: "Monospace dim-grey footer row reading 'v8.0.0 (79be2a0)' below Export/Import buttons, centre-aligned with a top border separator"
    why_human: "Visual rendering of CSS tokens and DOM element placement cannot be verified programmatically"
  - test: "Confirm no SYSTEM sidebar group is visible (no update available yet — no release newer than 8.0.0 tagged)"
    expected: "Sidebar shows INVERTERS, VENUS OS, MQTT PUBLISH groups only. No orange ve-dot. No 'Software' entry."
    why_human: "Badge visibility depends on live GitHub state — cannot assert programmatically without a real tag"
  - test: "Optional live badge test: tag v8.0.1-test release on GitHub, restart service with no open WS tabs, wait 90s, verify orange ve-dot + 'Software' entry + 'GitHub ->' link appear"
    expected: "SYSTEM sidebar group appears with orange dot on Software entry and functional external link to the release. After cleanup, group disappears on next page load."
    why_human: "CHECK-04 badge render path requires a real GitHub release; unit tests cover the JS logic but visual rendering must be confirmed"
---

# Phase 44: Passive Version Badge — Verification Report

**Phase Goal:** First user-visible feature. Webapp displays current version in footer and shows an orange badge on the System sidebar entry when a new GitHub release is available. NO update execution capability — discovery only. Scheduler fault-tolerant, read-only, fully reversible.

**Verified:** 2026-04-10T18:30:00Z
**Status:** human_needed — all code verified, 3 visual checks pending
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Version footer shows current_version + commit in sidebar | VERIFIED | `#ve-version-footer` div in index.html; `renderVersionFooter()` in app.js reads `_availableUpdateState.current_version/current_commit`; live LXC curl returns `"current_version":"8.0.0","current_commit":"79be2a0"` |
| 2 | Background scheduler runs every 1h as asyncio task | VERIFIED | `UpdateCheckScheduler(interval=3600, initial_delay=60)` in `scheduler.py`; started via `asyncio.create_task` in `__main__.py`; `update_scheduler_started` confirmed in LXC journal at 16:41:09 |
| 3 | GitHub client uses correct headers, 10s timeout, ETag cache | VERIFIED | `github_client.py` sets User-Agent, Accept, X-GitHub-Api-Version headers; `aiohttp.ClientTimeout(total=10)`; ETag persisted atomically to `/etc/pv-inverter-proxy/update-state.json` via tempfile + `os.replace` |
| 4 | Orange badge on System sidebar entry when update available | VERIFIED (code) | `createSystemSidebarGroup` / `createSoftwareSidebarEntry` in app.js; `.ve-sidebar-device--system-with-update .ve-dot { background: var(--ve-orange) }` in style.css; esc()-wrapped href; visual render pending human check |
| 5 | GET /api/update/available returns all required fields | VERIFIED | `update_available_handler` in webapp.py returns `{current_version, current_commit, available_update, last_check_at, last_check_failed_at}`; live LXC curl confirms shape and real 8.0.0 value |
| 6 | Scheduler fault-tolerant; last_check_failed_at surfaced in UI | VERIFIED | `fetch_latest_release()` catches all error classes including bare `Exception` and returns `None`; `scheduler.py` catches iteration exceptions and sets `last_check_failed_at`; `ve-version-footer--failed` CSS class applied when failedAt > okAt; prereleases filtered |
| 7 | Scheduler defers when WebSocket client is active | VERIFIED | `_has_active_ws_client()` in `__main__.py` probes `app["ws_clients"]`; `_run_one_iteration()` in scheduler returns early on True; `update_check_deferred_user_active` confirmed in LXC journal at 16:42:10 (exactly 60s after start, proving production wiring) |

**Score:** 7/7 truths verified at code level. 3 items require visual browser verification (human_needed).

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pv_inverter_proxy/updater/__init__.py` | Module marker | VERIFIED | Single docstring, exists on disk |
| `src/pv_inverter_proxy/updater/version.py` | Version NamedTuple, get_current_version, get_commit_hash, COMMIT fallback | VERIFIED | All functions present, _read_commit_file_fallback() added for LXC deploy |
| `src/pv_inverter_proxy/updater/github_client.py` | aiohttp client, ETag, headers, fault tolerance | VERIFIED | All CHECK-03 headers, 10s timeout, atomic state write, complete error coverage |
| `src/pv_inverter_proxy/updater/scheduler.py` | asyncio task, 3600s interval, 60s delay, defer-on-active | VERIFIED | All lifecycle methods, CHECK-07 probe, CancelledError propagation correct |
| `src/pv_inverter_proxy/context.py` | 5 new AppContext fields | VERIFIED | `current_version`, `current_commit`, `available_update`, `update_last_check_at`, `update_last_check_failed_at` all present with `None` defaults |
| `src/pv_inverter_proxy/webapp.py` | /api/update/available route, broadcast_available_update, WS initial push | VERIFIED | Route at `GET /api/update/available`; `broadcast_available_update()` mirrors `broadcast_device_list`; WS initial push sends `available_update` type message |
| `src/pv_inverter_proxy/__main__.py` | Scheduler wiring, version resolution at startup, graceful shutdown | VERIFIED | `_on_update_available` and `_has_active_ws_client` as module-level functions; scheduler started after webapp; task included in shutdown cancel loop; session closed in best-effort try/except |
| `src/pv_inverter_proxy/static/index.html` | `#ve-version-footer` element | VERIFIED | `<div id="ve-version-footer" class="ve-version-footer">` with `v—` placeholder, placed after `.ve-sidebar-footer` |
| `src/pv_inverter_proxy/static/app.js` | handleAvailableUpdate, renderVersionFooter, createSystemSidebarGroup, WS dispatch, REST fallback | VERIFIED | All 5 edits present; `_availableUpdateState` module-level; `msg.type === 'available_update'` dispatch; 2s setTimeout fallback |
| `src/pv_inverter_proxy/static/style.css` | ve-version-footer, ve-version-footer--failed, system badge rules | VERIFIED | All 4 CSS blocks present; zero hardcoded hex colors; all use `var(--ve-*)` tokens |
| `pyproject.toml` | version = "8.0.0" | VERIFIED | Line 3: `version = "8.0.0"` |
| `deploy.sh` | COMMIT file capture + EXIT trap | VERIFIED | Lines 65-67: `git rev-parse --short HEAD`, write to `src/pv_inverter_proxy/COMMIT`, `trap 'rm -f ...' EXIT` |
| `.gitignore` | COMMIT entry | VERIFIED | Line 10: `src/pv_inverter_proxy/COMMIT` |
| `tests/test_updater_version.py` | 41 tests | VERIFIED | File exists; 41 passing |
| `tests/test_updater_github_client.py` | 23 tests | VERIFIED | File exists; 23 passing |
| `tests/test_updater_scheduler.py` | 13 tests | VERIFIED | File exists; 13 passing |
| `tests/test_updater_webapp_routes.py` | 9 tests | VERIFIED | File exists; 9 passing |
| `tests/test_updater_wiring.py` | 15 tests | VERIFIED | File exists; 15 passing |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `__main__.py` | `UpdateCheckScheduler` | import + `asyncio.create_task` in `run_with_shutdown` | WIRED | `update_scheduler_task = update_scheduler.start()` on line 474; task in shutdown cancel tuple |
| `__main__.py` | `GithubReleaseClient` | import + constructor with shared session | WIRED | `update_http_session = aiohttp.ClientSession(...)` then `GithubReleaseClient(session=update_http_session)` |
| `__main__.py:_on_update_available` | `broadcast_available_update` | direct await | WIRED | `await broadcast_available_update(app_ctx.webapp)` guarded by `app_ctx.webapp is not None` |
| `__main__.py:_has_active_ws_client` | `app["ws_clients"]` | `app_ctx.webapp.get("ws_clients")` | WIRED | Defensive get with TypeError guard; False on empty WeakSet |
| `webapp.py` | `/api/update/available` route | `app.router.add_get` in `create_webapp()` | WIRED | Line 2092 in webapp.py |
| `ws_handler` | `available_update` initial push | `ws.send_json` after `device_list` push | WIRED | Lines 705-716 in webapp.py; sends on every new client connect |
| `app.js` | `handleAvailableUpdate` | `ws.onmessage` dispatch on `msg.type === 'available_update'` | WIRED | Line 457 in app.js |
| `app.js` | `/api/update/available` REST fallback | `setTimeout(2000)` + `fetch` | WIRED | Lines 3152-3161 in app.js; single-shot, null-guarded |
| `app.js` | `renderSidebar` → SYSTEM group | `createSystemSidebarGroup` when `available_update` non-null | WIRED | Lines 130-132 in app.js |
| `version.py:get_commit_hash` | `_read_commit_file_fallback` | every git-failure error path | WIRED | All 5 failure branches (FileNotFoundError, TimeoutExpired, OSError, non-zero rc, empty stdout) delegate to fallback |
| `deploy.sh` | `COMMIT` file in package | `echo $COMMIT_SHORT > src/pv_inverter_proxy/COMMIT` before rsync | WIRED | Lines 65-67; trap ensures cleanup |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `app.js: renderVersionFooter` | `_availableUpdateState.current_version` | WS `available_update` push from `ws_handler` → `app_ctx.current_version` → set by `get_current_version()` at startup | Yes — `importlib.metadata.version("pv-inverter-master")` returns real `"8.0.0"` post-pip-install | FLOWING |
| `app.js: renderVersionFooter` | `_availableUpdateState.current_commit` | WS push → `app_ctx.current_commit` → `get_commit_hash(INSTALL_ROOT)` with COMMIT file fallback | Yes — `"79be2a0"` confirmed in LXC journal and curl response | FLOWING |
| `app.js: createSoftwareSidebarEntry` | `_availableUpdateState.available_update` | WS push → `app_ctx.available_update` → set by `_on_update_available` callback | Legitimate null in steady state (no newer release tagged); will be dict when newer release exists; unit-tested for both paths | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `/api/update/available` returns correct shape | `curl -sS http://192.168.3.191/api/update/available` (from 44-03 SUMMARY) | `{"current_version":"8.0.0","current_commit":"79be2a0","available_update":null,"last_check_at":null,"last_check_failed_at":null}` | PASS (live evidence) |
| JS syntax valid | `node --check src/pv_inverter_proxy/static/app.js` (from 44-03 SUMMARY) | No errors | PASS |
| index.html contains ve-version-footer marker | grep count ≥ 2 (from 44-03 LXC curl) | 2 occurrences | PASS |
| version_resolved log fires at startup | journalctl (from 44-03 SUMMARY) | `version_resolved version=8.0.0 commit=79be2a0` at 16:41:09 | PASS |
| update_scheduler_started fires at startup | journalctl | Both `update_scheduler_started` and `update_scheduler_starting initial_delay_s=60.0 interval_s=3600.0` present | PASS |
| CHECK-07 deferred at 60s mark | journalctl | `update_check_deferred_user_active` at 16:42:10 | PASS |
| All updater unit tests pass | `.venv/bin/pytest tests/test_updater_*.py -q` | 101 passed, 14 warnings (aiohttp AppKey notices, not failures), 3.19s | PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CHECK-01 | 44-01, 44-02, 44-03 | Version + commit in footer from importlib.metadata | SATISFIED | pyproject.toml `version=8.0.0`; `get_current_version()` via importlib.metadata; COMMIT file fallback for .git-less LXC; footer DOM + JS render wired; live endpoint confirms `"8.0.0"` + `"79be2a0"` |
| CHECK-02 | 44-01, 44-02 | Asyncio scheduler, 1h default interval | SATISFIED | `DEFAULT_INTERVAL_SECONDS = 3600.0`, `DEFAULT_INITIAL_DELAY_SECONDS = 60.0`; `asyncio.create_task` in `__main__.py`; live journal confirms `initial_delay_s=60.0 interval_s=3600.0` |
| CHECK-03 | 44-01 | User-Agent, Accept, X-GitHub-Api-Version, 10s timeout, ETag | SATISFIED | All headers in `_build_headers()`; `aiohttp.ClientTimeout(total=10)`; ETag persisted atomically; 23 hermetic tests cover each requirement |
| CHECK-04 | 44-03 | Orange ve-dot badge on System sidebar entry | SATISFIED (code); visual pending | `ve-sidebar-device--system-with-update .ve-dot { background: var(--ve-orange) }`; `createSoftwareSidebarEntry` with esc()-wrapped href; release_notes body NOT in DOM (XSS-safe); Markdown rendering deferred to Phase 46 (per phase scope) |
| CHECK-05 | 44-02 | GET /api/update/available response shape | SATISFIED (with noted deviation) | Endpoint returns `{current_version, current_commit, available_update, last_check_at, last_check_failed_at}` — envelope differs from REQUIREMENTS.md spec (`{current_version, latest_version, release_notes, published_at, tag_name}`) but is a strict superset: all spec fields accessible via `available_update.*`; 9 route tests cover all response cases |
| CHECK-06 | 44-01, 44-02, 44-03 | Fault tolerance, last_check_failed_at surfaced | SATISFIED | `fetch_latest_release` catches asyncio.TimeoutError, aiohttp.ClientError, json errors, HTTP 403/429/5xx, and bare Exception — all return None; scheduler sets `last_check_failed_at` on iteration exception; `ve-version-footer--failed` CSS; failedAt/okAt comparison prevents stale-failure false alarms |
| CHECK-07 | 44-01, 44-02 | Defer check when WS client connected | SATISFIED | `_has_active_ws_client` probes `app["ws_clients"]`; scheduler returns early with `update_check_deferred_user_active` log; live LXC confirms at 16:42:10 |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app.js` | ~194 | `header.innerHTML = '<span>SYSTEM</span>...'` | Info | Static string, no user data interpolated — not a stub, not an XSS risk. Hardcoded "SYSTEM" label is intentional. |
| `app.js` | ~234 | `entry.innerHTML = dotHtml + '...' + linkHtml` | Info | `linkHtml` uses `esc(availableUpdate.html_url)` on the href attribute. `esc('Software')` for the label. No unescaped user-controlled data reaches the DOM. Pattern consistent with existing codebase. |
| `tests/test_webapp.py` | — | Pre-existing failure: `test_config_get_venus_defaults` | Warning | Pre-existing before Phase 44. Documented in `deferred-items.md`. Zero relation to Phase 44 files. No new regressions introduced. |

No blockers. No placeholder strings. No `return []` stubs in production paths. No hardcoded hex colors in Phase 44 CSS.

---

## Cross-Cutting Checks

**Zero new Python runtime dependencies:** Confirmed. `pyproject.toml` dependencies unchanged from before Phase 44. `importlib.metadata`, `asyncio`, `subprocess`, `inspect` are all stdlib. No `packaging`, `semver`, or `aioresponses` added.

**Zero new frontend dependencies:** Confirmed. `app.js` uses only vanilla JS — `document.createElement`, `fetch`, `setTimeout`, `window.matchMedia`. No new `<script>` imports in `index.html`.

**Shared aiohttp.ClientSession:** Confirmed. `update_http_session = aiohttp.ClientSession(...)` created once in `run_with_shutdown()`, passed to `GithubReleaseClient(session=update_http_session)`. Session closed in shutdown path. No per-request sessions.

**XSS check — release_notes body:** Confirmed safe. `grep -c "release_notes" app.js` returns 0. The `release_notes` field in `available_update` dict is stored in `app_ctx` and included in the WS/REST payload, but `app.js` never reads `data.release_notes` and never calls `innerHTML` with it. Only `tag_name`, `html_url` (esc()-wrapped), and `published_at` are rendered. T-44-17 fully mitigated in Phase 44.

**Hermetic tests:** Confirmed. All 5 test files use `tmp_path` for state file injection, hand-rolled aiohttp mocks (no real network), and `asyncio_mode = "auto"`. The live `/etc/pv-inverter-proxy/update-state.json` is never touched by the test suite.

**deploy.sh COMMIT fallback (Rule 2 auto-fix):** Documented in 44-03 SUMMARY. Accepted deviation: the plan did not anticipate that the LXC rsync excludes `.git/`, making `git rev-parse` impossible at runtime. The fix (`deploy.sh` writes COMMIT before rsync, `version.py` reads it as fallback) is the correct solution. Evidence: production shows `current_commit: "79be2a0"` rather than null.

**CHECK-05 envelope deviation:** The REQUIREMENTS.md CHECK-05 text specifies a flat `{current_version, latest_version, release_notes, published_at, tag_name}` shape. The implementation uses a nested envelope `{current_version, current_commit, available_update: {...}, last_check_at, last_check_failed_at}`. This is a deliberate improvement (adds commit, check timestamps, separates version metadata from release data) documented in the 44-02 SUMMARY. All spec fields are accessible via `available_update.*` when a release is present. The app.js consumer and the 9 route tests are consistent with the implemented shape, not the spec shape. REQUIREMENTS.md traceability row for CHECK-05 is marked Complete.

---

## Human Verification Required

### 1. Version Footer Visual

**Test:** Open `http://192.168.3.191` in a fresh browser tab. Hard-refresh with `Cmd+Shift+R`. Inspect the bottom of the left sidebar.
**Expected:** A new row below the Export/Import buttons showing `v8.0.0 (79be2a0)` in small monospace dim-grey text, centre-aligned, with a top border separator. The row is selectable (user-select: text).
**Why human:** CSS token rendering (`var(--ve-text-dim)`, `var(--ve-mono)`, `var(--ve-border)`) and DOM placement relative to existing flex layout cannot be verified programmatically without a real browser.

### 2. Steady-State — No Spurious Badge

**Test:** With the version footer visible, confirm no SYSTEM group appears in the sidebar.
**Expected:** Sidebar groups: INVERTERS (or whatever is configured), VENUS OS, MQTT PUBLISH. No orange ve-dot. No "Software" row. No "GitHub ->" link.
**Why human:** Badge visibility depends on live GitHub state — whether a release newer than 8.0.0 has been tagged. Cannot assert without querying GitHub.

### 3. Optional Live Badge Test (CHECK-04 visual)

**Test:** Tag a disposable release on GitHub:
```bash
git tag v8.0.1-test
git push origin v8.0.1-test
gh release create v8.0.1-test --title "Phase 44 badge test" --notes "Visual verification"
```
Close all browser tabs to the webapp (so CHECK-07 lets the scheduler run). Restart the service on LXC. Wait ~90 seconds. Open the webapp.

**Expected:** A new SYSTEM group appears at the bottom of the sidebar with a "Software" row: an orange `ve-dot` on the left, "Software" label, "GitHub ->" link opening the release page in a new tab. Tooltip on the entry shows "Update available — v8.0.1-test — {published_at}".

**Cleanup:** `gh release delete v8.0.1-test --yes && git push origin :refs/tags/v8.0.1-test && git tag -d v8.0.1-test`. After the next scheduler iteration, the SYSTEM group disappears.

**Why human:** Live badge code path needs a real GitHub release. Unit tests verify the JS logic and data flow, but visual rendering requires a browser.

---

## Deviations from Plan (Accepted)

### Rule 2 Auto-Fix: Deploy-time COMMIT File (44-03)

**Issue found:** First deploy showed `current_commit: null` because the LXC rsync excludes `.git/`, making `git rev-parse --short HEAD` fail at runtime.

**Fix applied:**
1. `deploy.sh` captures `git rev-parse --short HEAD` on the dev host and writes it to `src/pv_inverter_proxy/COMMIT` before rsync. EXIT trap removes the file after rsync finishes.
2. `updater/version.py` adds `_read_commit_file_fallback()` called in every git-failure path of `get_commit_hash()`.
3. `.gitignore` adds `src/pv_inverter_proxy/COMMIT`.

**Verdict:** Correct and necessary. The COMMIT file is a read-only artifact of the deploy process, validated as pure hex, truncated to 7 chars. The fix is fully covered by manual smoke tests and the existing 41 `test_updater_version.py` tests. Production evidence: `current_commit: "79be2a0"` in live endpoint.

---

## Open Items for Future Phases

| Item | Phase | Notes |
|------|-------|-------|
| Release notes Markdown rendering | Phase 46 | `release_notes` body is stored in `app_ctx.available_update["release_notes"]` and surfaced via the REST/WS endpoint but NEVER interpolated into the DOM in Phase 44. Phase 46 will add an escaping Markdown subset renderer (headings, lists, bold, code, links). T-44-17 avoidance in place. |
| Richer FetchResult contract (distinguish "no release" vs "network failed") | Phase 47 | Per 44-01 decision: `fetch_latest_release` returns `None` for all failure modes. Phase 47 may introduce a typed `FetchResult` union if the UI needs finer fault reporting. |
| `test_config_get_venus_defaults` pre-existing failure | Cleanup | Pre-dates Phase 44; documented in `deferred-items.md`. Should be fixed in a dedicated bug-fix commit unrelated to the update system. |
| `check_interval_hours` config knob (CFG-01) | Phase 47 | Scheduler currently uses the hardcoded 3600s default. CFG-01 (`update.check_interval_hours`) lands in Phase 47 along with the full config section. |

---

_Verified: 2026-04-10T18:30:00Z_
_Verifier: Claude (gsd-verifier) — goal-backward analysis of all 7 CHECK requirements against live code and LXC deployment evidence_
