---
phase: 44-passive-version-badge
plan: "03"
subsystem: frontend-display
tags: [frontend, vanilla-js, css, design-system, deploy, version-badge, websocket, sidebar]
one_liner: "Vanilla-JS version footer + orange ve-dot SYSTEM sidebar badge wired to the WS 'available_update' message, deployed live to LXC 192.168.3.191 showing v8.0.0 (79be2a0). Closes Phase 44 code work; human visual verification pending."
requires:
  - 44-02
provides:
  - "ve-version-footer DOM element inside sidebar with monospace dim-text rendering"
  - "handleAvailableUpdate / renderVersionFooter / createSystemSidebarGroup / createSoftwareSidebarEntry JS helpers"
  - "_availableUpdateState module-level state in app.js"
  - "WebSocket 'available_update' message dispatch in ws.onmessage"
  - "Conditional SYSTEM sidebar group with orange ve-dot badge when update advertised"
  - "2s post-load REST fallback to /api/update/available if WS initial push is missed"
  - "Deploy-time COMMIT file fallback so get_commit_hash() returns real SHA on LXC (where .git/ is excluded from rsync)"
  - "Phase 44 deployed to 192.168.3.191: service restart clean, version_resolved version=8.0.0 commit=79be2a0"
affects:
  - plan: 46
    how: "Phase 46 will add click handler on the Software sidebar entry to navigate to /system/software page and render release_notes body via a Markdown subset renderer. Will also add a 'Check now' button wired to a new POST /api/update/check endpoint."
tech-stack:
  added: []
  patterns:
    - "Vanilla-JS state-driven re-render: handleAvailableUpdate stores state then calls renderSidebar() which is idempotent and rebuilds the SYSTEM group in place"
    - "Coarse 2s setTimeout fallback for WS initial-push reliability (single-shot, never on interval)"
    - "CSS-only badge color swap via .ve-sidebar-device--system-with-update .ve-dot descendant selector (no inline style on dot element, no class toggling in JS)"
    - "Deploy-time artifact injection: COMMIT file written into src tree pre-rsync, removed via EXIT trap, read by runtime as fallback when git/.git missing"
    - "All output sanitized through existing esc() helper — release_notes body NEVER interpolated as innerHTML in Phase 44"
key-files:
  created: []
  modified:
    - src/pv_inverter_proxy/static/index.html
    - src/pv_inverter_proxy/static/app.js
    - src/pv_inverter_proxy/static/style.css
    - src/pv_inverter_proxy/updater/version.py
    - deploy.sh
    - .gitignore
decisions:
  - "Release notes Markdown rendering deliberately deferred from Phase 44 to Phase 46 per phase scope document. Phase 44 shows only tag_name + GitHub link on the Software sidebar entry; the release_notes body string is stored in app_ctx but NEVER reaches the DOM, which sidesteps T-44-17 (XSS via malicious release notes) until Phase 46 adds an escaping Markdown renderer."
  - "Added 2s REST fallback on page load in case the WS initial push is missed. Single-shot setTimeout, never polls, only triggers when _availableUpdateState is still null. Cost: one degenerate-case GET per page load."
  - "Version footer uses --ve-mono font token to match register-viewer and other data-display styling conventions in the codebase."
  - "CHECK-06 failed-check indicator: footer text turns orange via ve-version-footer--failed class, tooltip shows last failure timestamp. Shows failed state only when last_check_failed_at is newer than last_check_at — prevents stale-failure false alarms after a recovered success."
  - "Badge CSS uses a descendant selector (.ve-sidebar-device--system-with-update .ve-dot) rather than inline style on the dot element. This keeps all color tokens in CSS (design-system-compliant) and makes it trivial to theme the entry differently in the future without touching JS."
  - "Rule 2 deviation: added COMMIT file fallback in deploy.sh + updater/version.py because the LXC rsync excludes .git/, making get_commit_hash() return None in production and rendering CHECK-01's 'commit hash in footer' dead on arrival. Production now shows v8.0.0 (79be2a0) as intended."
metrics:
  duration: "~7 minutes wall clock (frontend + LXC deploy)"
  completed: "2026-04-10"
  tasks_completed: 2
  tasks_pending_checkpoint: 1
  files_modified: 6
  commits: 2
---

# Phase 44 Plan 03: Frontend Display Summary

Plan 44-03 delivers the user-visible deliverable of Phase 44: a monospace version footer anchored at the bottom of the sidebar and a conditional SYSTEM sidebar group with an orange ve-dot update badge. The backend plumbing from 44-01 (updater library) and 44-02 (webapp wiring) is now surfaced to the browser. The full stack is deployed to the LXC at 192.168.3.191 and actively serving `v8.0.0 (79be2a0)` under the live service.

## What Shipped

### `src/pv_inverter_proxy/static/index.html`

One additive change: a new `<div id="ve-version-footer" class="ve-version-footer" title="">` element placed inside the `<nav class="sidebar">` immediately after the existing `.ve-sidebar-footer` (Export/Import row). Because the sidebar is a flex column with `.ve-sidebar-footer` using `margin-top: auto`, both footer rows naturally stack at the bottom in insertion order — Export/Import first, version row below. Initial content is a `v—` em-dash placeholder so there is no visual flicker before the first WS push.

### `src/pv_inverter_proxy/static/style.css`

One additive CSS block appended at the end of the file under a `/* ===== Phase 44 ... ===== */` comment header. All declarations use only existing `var(--ve-*)` tokens — zero new hex colors, zero rgba overrides.

- `.ve-version-footer` — 8px/16px padding, `var(--ve-text-dim)` color, `var(--ve-mono)` font, `var(--ve-border)` top border, `var(--ve-bg-surface)` background, `text-align: center`, `user-select: text` so users can copy the version string for bug reports.
- `.ve-version-footer--failed` — overrides color to `var(--ve-orange)` when CHECK-06's `last_check_failed_at` is newer than `last_check_at`.
- `.ve-sidebar-device--system-with-update .ve-dot` — descendant selector that overrides the default `.ve-dot` grey background to `var(--ve-orange)`. Keeps the JS badge-creation logic free of inline color styles (purely structural).
- `.ve-sidebar-device-github-link` — secondary text-dim link aligned to the right of the Software entry via `margin-left: auto`. Transitions only `color` using `var(--ve-duration-fast)` + `var(--ve-easing-default)`. Hover swaps to `var(--ve-blue-light)` + underline, no background change (avoids the rgba exception the plan initially suggested).

### `src/pv_inverter_proxy/static/app.js`

Five additive edits (zero existing lines removed, zero DOM restructuring):

1. **Module-level state** (after `_configuredInverters`): `var _availableUpdateState = null;` with inline comment describing the shape.
2. **Conditional SYSTEM group at end of `renderSidebar`** (before `highlightActiveSidebar()`): when `_availableUpdateState.available_update` is non-null, append `createSystemSidebarGroup(_availableUpdateState.available_update)` to the device-sidebar container.
3. **Four new helper functions** colocated immediately after `renderSidebar`:
   - `handleAvailableUpdate(data)` — stores data in module state, calls `renderVersionFooter()`, then calls `renderSidebar()` with no args (which re-runs the existing device loop and conditionally rebuilds the SYSTEM group).
   - `renderVersionFooter()` — resolves the `#ve-version-footer` element, writes `v{current_version} ({current_commit})` to the `.ve-version-footer-text` span (or just `v{version}` when commit is null), sets tooltip to last check timestamp in `toLocaleTimeString()` form, and toggles the `ve-version-footer--failed` class based on whether `last_check_failed_at` is newer than `last_check_at`.
   - `createSystemSidebarGroup(availableUpdate)` — builds a `.ve-sidebar-group` with "SYSTEM" header (click-to-collapse chevron), containing one child: `createSoftwareSidebarEntry`. Reuses the existing `.ve-sidebar-group-items` / `.ve-sidebar-group-items--collapsed` / `.ve-chevron` classes — no new collapse machinery.
   - `createSoftwareSidebarEntry(availableUpdate)` — builds a `.ve-sidebar-device.ve-sidebar-device--system-with-update` entry with: a plain `<span class="ve-dot"></span>` (colored by the descendant CSS selector), an `esc()`-wrapped "Software" label, and an optional `<a ... target="_blank" rel="noopener">GitHub →</a>` link when `html_url` is present. The href is also `esc()`-wrapped to prevent attribute injection (T-44-16 mitigation). Tooltip shows `Update available — {tag_name} — {published_at}`.
4. **WebSocket dispatch** (inside `ws.onmessage`, alongside the existing `device_list` handler): `if (msg.type === 'available_update') handleAvailableUpdate(msg.data);`
5. **Post-load REST fallback** (inside `DOMContentLoaded`, after `connectWebSocket()`): a one-shot `setTimeout(..., 2000)` that checks `_availableUpdateState === null` and fetches `/api/update/available` only if the WS push hasn't landed yet. Uses existing fetch API, silently catches errors, guards against racing the WS push with a second `=== null` check inside the `.then`.

### `src/pv_inverter_proxy/updater/version.py`

**Rule 2 deviation — Missing critical functionality:** Added `_read_commit_file_fallback()` and wired it into every error path of `get_commit_hash()`. Without this, the LXC (which excludes `.git/` from its rsync for size/security) would always surface `current_commit: null`, effectively breaking the commit-hash portion of CHECK-01 in production. The fallback reads a `COMMIT` file placed next to the installed `pv_inverter_proxy` package, validates it is pure hex, truncates to 7 chars, and lowercases. Returns `None` on any failure — preserves all 41 existing hermetic tests because they run in tmp dirs with no `COMMIT` file nearby.

### `deploy.sh`

**Rule 2 deviation (same issue, producer side):** Added three lines before the rsync invocation:

```bash
COMMIT_SHORT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "$COMMIT_SHORT" > src/pv_inverter_proxy/COMMIT
trap 'rm -f src/pv_inverter_proxy/COMMIT' EXIT
```

The dev-host `git rev-parse` runs before the sync, the resulting file ships inside the rsync payload, and the EXIT trap ensures the dev working tree stays clean regardless of whether rsync succeeds or fails. Echo is also updated to show the captured short SHA for deploy-operator visibility.

### `.gitignore`

One line: `src/pv_inverter_proxy/COMMIT` so the transient file never accidentally gets committed. Ignored file stays ignored even when deploy.sh writes it.

## Deployment Log (Task 2)

### Rsync / restart

```
>>> Syncing source code (commit=79be2a0)...
...
sent 6073 bytes  received 200 bytes  2023548 bytes/sec
total size is 914325  speedup is 145,76
>>> Installing package...
>>> Restarting service...
>>> Service status:
* pv-inverter-proxy.service - PV-Inverter-Master (Multi-Source Solar Aggregator for Venus OS)
     Loaded: loaded (/etc/systemd/system/pv-inverter-proxy.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-04-10 16:41:09 UTC
```

The service came up cleanly on the first try after the redeploy. Peak memory 38 MB.

### `journalctl` evidence

```json
{"component":"main","version":"8.0.0","commit":"79be2a0","event":"version_resolved","level":"info","timestamp":"2026-04-10T16:41:09.813144Z"}
{"component":"main","event":"update_scheduler_started","level":"info","timestamp":"2026-04-10T16:41:09.818046Z"}
{"component":"updater.scheduler","initial_delay_s":60.0,"interval_s":3600.0,"event":"update_scheduler_starting","level":"info","timestamp":"2026-04-10T16:41:09.818686Z"}
{"component":"updater.scheduler","event":"update_check_deferred_user_active","level":"info","timestamp":"2026-04-10T16:42:10.205740Z"}
```

- `version_resolved` fires with the real `8.0.0` from `importlib.metadata` and the fallback-delivered `79be2a0` short SHA. CHECK-01 verified at runtime.
- `update_scheduler_started` + `update_scheduler_starting` confirm CHECK-02 is live with the documented 60s initial delay and 3600s interval.
- `update_check_deferred_user_active` at 16:42:10 (exactly 60s after start) confirms CHECK-07 works in production — a pre-existing WebSocket browser tab was connected, so the scheduler deferred its first check to the next interval. This is the intended behavior, and it means `last_check_at` will remain `null` in the API response until a period of user inactivity allows a check to run.
- **Zero errors** in the full 5-minute journal window around deploy — no `update_check_iteration_failed`, no tracebacks, no exception markers.

### Endpoint verification

```json
$ curl -sS http://192.168.3.191/api/update/available
{
    "current_version": "8.0.0",
    "current_commit": "79be2a0",
    "available_update": null,
    "last_check_at": null,
    "last_check_failed_at": null
}
```

All required keys present. `current_version` is the real `8.0.0`, `current_commit` is a valid 7-char short SHA, `available_update` is `null` (no GitHub release exists newer than 8.0.0 at time of deploy, which is the expected steady state for the first tagged release), `last_check_at` is `null` because the first scheduler iteration was deferred by CHECK-07 (active WS client). `last_check_failed_at` is `null` because there have been no errors.

### Static asset verification

```
$ curl -sS http://192.168.3.191/static/index.html | grep -c 've-version-footer'  → 2
$ curl -sS http://192.168.3.191/static/app.js    | grep -c 'handleAvailableUpdate'  → 3
$ curl -sS http://192.168.3.191/static/style.css | grep -c 've-version-footer'     → 3
```

All three static files served from the LXC contain the Phase 44 additions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Deploy-time COMMIT file for CHECK-01**

- **Found during:** Task 2 (first deploy attempt)
- **Issue:** After the first deploy, `journalctl` showed `version_resolved version=8.0.0 commit=unknown` and the endpoint returned `current_commit: null`. Root cause: `deploy.sh` excludes `.git/` from rsync (for both security and size — it's also a worktree pointer issue documented in deploy.sh comments), so `get_commit_hash()` calling `git rev-parse` inside `/opt/pv-inverter-proxy` always fails with "fatal: cannot change to '.git'". The plan's Task 2 verification explicitly requires `current_commit is not None and len >= 7`, and CHECK-01 calls out "short commit hash" as a mandatory field in REQUIREMENTS.md. Without a fix, CHECK-01 would be half-delivered: the version number would show but the commit identifier would always be blank in production — user-visibly wrong.
- **Fix:**
  1. `deploy.sh` captures `git rev-parse --short HEAD` on the dev host and writes it to `src/pv_inverter_proxy/COMMIT` before the rsync invocation. A bash `EXIT` trap removes the file after the rsync finishes (or fails), so the dev working tree stays clean.
  2. `updater/version.py` gains a `_read_commit_file_fallback()` helper that reads `COMMIT` from the installed package directory (`Path(__file__).resolve().parent.parent / "COMMIT"`), validates the content is pure hex (max 40 chars), rejects `"unknown"` / empty strings, and returns the first 7 chars lowercased. `get_commit_hash()` calls this fallback in every single error path (git missing, non-zero exit, empty stdout, timeout, OSError, catch-all). If the real `git rev-parse` succeeds (e.g. on dev machines where you run against a local checkout), the fallback is never consulted — so existing behavior is unchanged.
  3. `.gitignore` adds `src/pv_inverter_proxy/COMMIT` to prevent accidental commits.
- **Test coverage:** Manual Python smoke test covered:
  - Missing file → `None` (preserves old behavior, all 41 hermetic tests still pass)
  - Valid hex → first 7 chars lowercased
  - `"unknown"` → `None`
  - Non-hex content → `None`
  - Empty → `None`
  - Full updater_version.py test suite: **41/41 passing**
- **Files modified:** `deploy.sh`, `.gitignore`, `src/pv_inverter_proxy/updater/version.py`
- **Commit:** `79be2a0`
- **Verified end-to-end:** Second deploy shows `"commit": "79be2a0"` in `version_resolved` log and `"current_commit": "79be2a0"` in the REST response.

### No other deviations

No Rule 1 bugs found, no Rule 3 blockers, no Rule 4 architectural questions. Plan otherwise executed exactly as written.

## Auth / Human Gates

**None during execution.** The deploy uses an existing, working SSH key for `root@192.168.3.191` (blue-green layout from Phase 43 already in place). No secrets, no interactive prompts.

**One pending human-verify checkpoint (Task 3)** — see below.

## Human Verification Checkpoint (Task 3)

Phase 44 is complete at the code level but requires visual verification in a real browser before we declare the phase closed. The plan's Task 3 is a `checkpoint:human-verify` — the executor does not mark it complete. Instructions for the user:

### Open in a browser

1. Open `http://192.168.3.191` in a fresh browser tab.
2. **Hard-refresh** with `Cmd+Shift+R` (macOS) or `Ctrl+Shift+R` (Windows/Linux) to bypass cached static assets.

### Expected visual state

- **Sidebar bottom:** immediately below the Export/Import buttons there is a new row showing **`v8.0.0 (79be2a0)`** in small monospace dim-grey text, center-aligned with a top border separating it from the Export/Import row.
- **Tooltip on hover over the footer:** once the scheduler has performed a check (may take several minutes because the test LXC has an active WS client and CHECK-07 defers each iteration), the tooltip shows `Letzter Update-Check: HH:MM:SS`. Before the first successful check, the tooltip is empty.
- **No orange badge in the sidebar.** No "SYSTEM" group is visible because `available_update` is `null` (no GitHub release newer than 8.0.0 has been tagged yet). This is the correct steady state for Phase 44.
- **All existing sidebar groups render unchanged:** INVERTERS, VENUS OS, MQTT PUBLISH. Device dots still update with live power readings. The Venus OS "Connected" label still shows.
- **All dashboard pages load:** click any inverter, verify Dashboard / Registers / Config tabs still work. No regressions.
- **Config Export/Import buttons still work.**
- **No JavaScript console errors** (open DevTools → Console, expect a clean slate).

### Optional live badge test (CHECK-04 visual)

To see the orange badge without waiting for a real release, tag a fake one on GitHub:

```bash
git tag v8.0.1-test
git push origin v8.0.1-test
gh release create v8.0.1-test --title "Phase 44 badge test" --notes "Visual verification"
```

Then SSH in and restart the service so the 60s initial delay + active-user defer cycle re-runs from scratch. Wait up to ~2 minutes (close your browser tab so the scheduler can run without deferring), then reopen. Expected: a new "SYSTEM" sidebar group appears at the bottom of the sidebar with a "Software" row containing an orange `ve-dot` and a "GitHub →" link that opens the release page in a new tab.

**Cleanup after visual verification:**

```bash
gh release delete v8.0.1-test --yes
git push origin :refs/tags/v8.0.1-test
git tag -d v8.0.1-test
```

Alternative: skip the live test and accept that the badge code path is exercised by Plan 44-02's 15 unit tests (`test_newer_release_sets_available_update`, `test_broadcast_invoked_when_update_changes`, etc.) plus code review.

### What to report back

Type `approved` to close Phase 44, or describe any issues encountered. Mention whether the live badge test was performed or deferred.

## Phase 44 Close Checklist

| Requirement | Status | Evidence |
|---|---|---|
| CHECK-01 version in footer from importlib.metadata | DONE (code + live) | `/api/update/available` returns `current_version: "8.0.0"`; footer DOM + JS wiring deployed; Rule 2 COMMIT fallback ensures commit hash populated even on .git-less LXC |
| CHECK-02 scheduler running as asyncio task | DONE (live) | `update_scheduler_started` + `update_scheduler_starting initial_delay_s=60.0 interval_s=3600.0` in production journal |
| CHECK-03 GitHub client headers + ETag + 10s timeout | DONE (unit) | 23 hermetic tests in 44-01; no live fetch observable yet because CHECK-07 deferred the first iteration |
| CHECK-04 orange ve-dot badge on System sidebar entry | DONE-CODE, PENDING-VISUAL | Code wired, static assets deployed, unit-tested via 15 wiring tests; visual verification requires either a live test tag or the user inspecting the code paths. Release notes Markdown rendering intentionally deferred to Phase 46 per phase scope. |
| CHECK-05 GET /api/update/available response shape | DONE (live) | `curl` returns all five required fields; 9 webapp route tests in 44-02 |
| CHECK-06 fault tolerance + last_check_failed_at surfaced | DONE (code) | Scheduler catches all exception classes, webapp reads the field, footer CSS class + tooltip wired; no real failure yet observed in production |
| CHECK-07 scheduler defers when WS client connected | DONE (live) | `update_check_deferred_user_active` log event observed in production on the first iteration attempt |

**Code-complete. Awaiting visual approval from Task 3 checkpoint.**

## Known Stubs

**None.** The version footer populates from real data at all times — the initial `v—` placeholder is replaced either by the WebSocket push or by the 2s REST fallback. The `available_update` dict is `null` in the happy path (no release tagged), and the frontend handles this by simply not rendering the SYSTEM group — not by rendering placeholder content. Release notes `body` is intentionally NOT in the DOM in Phase 44 (phase scope boundary — Phase 46 adds the Markdown renderer), which means no dead-code placeholder strings anywhere.

## Threat Model — No New Flags

All frontend changes are covered by the plan's `<threat_model>` T-44-16 through T-44-19:

- **T-44-16 (Tampering, html_url):** `esc()` applied to href attribute interpolation. `target="_blank" rel="noopener"` on the link prevents tabnabbing.
- **T-44-17 (Information Disclosure, release_notes):** `body` field is NEVER interpolated into the DOM in Phase 44. Only `tag_name`, `html_url`, and `published_at` reach the browser view. Deferred to Phase 46's escaping Markdown renderer.
- **T-44-18 (DoS, re-render churn):** `renderSidebar()` is idempotent and cheap (~5 DOM nodes). Broadcasts are coarse-deduped on the server (Plan 44-02), so typical churn is one re-render per scheduler iteration (1/hour).
- **T-44-19 (Tampering, REST fallback loop):** `setTimeout` runs **once**, not on an interval. Malformed responses set `_availableUpdateState = {}` and render as `vunknown`. No loop possible.

The `_read_commit_file_fallback` in `version.py` introduces one new filesystem read (`src/pv_inverter_proxy/COMMIT`). This is a read-only operation against a file that the install itself wrote during deploy — no trust boundary crossed. Content is validated as pure hex and truncated to 7 chars before use, so even a malicious deploy couldn't inject unexpected data into the footer tooltip.

## Commits

| Task | Hash | Description |
|---|---|---|
| 1 | `eebfd8c` | `feat(44-03): render version in footer and update badge on system sidebar` |
| 1 (fix) | `79be2a0` | `fix(44-03): ship deploy-time COMMIT file so production shows real SHA` |

Two commits instead of the plan's three because Task 2 had no file changes of its own (the deploy.sh change was folded into the Rule 2 fix needed to make Task 2's verification pass).

## Self-Check: PASSED

**Files modified (verified via git diff):**
- `src/pv_inverter_proxy/static/index.html` — FOUND (div insertion confirmed)
- `src/pv_inverter_proxy/static/app.js` — FOUND (handleAvailableUpdate + state var + ws dispatch + fallback fetch)
- `src/pv_inverter_proxy/static/style.css` — FOUND (ve-version-footer + ve-sidebar-device--system-with-update + github-link rules)
- `src/pv_inverter_proxy/updater/version.py` — FOUND (_read_commit_file_fallback added, all error paths delegated)
- `deploy.sh` — FOUND (COMMIT capture + EXIT trap + echo updated)
- `.gitignore` — FOUND (COMMIT entry added)

**Commits (verified via git log):**
- `eebfd8c` — FOUND
- `79be2a0` — FOUND

**Runtime evidence:**
- `curl http://192.168.3.191/api/update/available` → JSON with `"current_version":"8.0.0"`, `"current_commit":"79be2a0"`. Verified.
- `journalctl` → `version_resolved version=8.0.0 commit=79be2a0`. Verified.
- `journalctl` → `update_scheduler_started` + `update_scheduler_starting`. Verified.
- `journalctl` → `update_check_deferred_user_active` (CHECK-07 live). Verified.
- `journalctl` → zero errors in 5-minute window. Verified.
- `node --check src/pv_inverter_proxy/static/app.js` → JS syntax OK. Verified.
- Static assets on LXC contain all Phase 44 markers (grep counts ≥ 2 in each of index.html, app.js, style.css). Verified.
- Full `tests/test_updater_version.py` (41 tests) still passes after fallback logic added. Verified.
