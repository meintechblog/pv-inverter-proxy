---
phase: 20-discovery-ui-onboarding
verified: 2026-03-20T17:10:00Z
status: human_needed
score: 18/18 must-haves verified
re_verification: false
human_verification:
  - test: "Click discover button and observe scan UX end-to-end"
    expected: "Button gets disabled with spinning magnifying glass icon, blue progress bar fills with correct phase text (Scanning network X/Y then Verifying SunSpec X/Y), results appear as checkbox list after completion"
    why_human: "Animation behavior, spinner visual, progress bar fill timing cannot be verified programmatically"
  - test: "Open config page with zero configured inverters"
    expected: "Auto-scan fires immediately without user action, progress bar appears, single found device is auto-added with toast notification"
    why_human: "Auto-scan trigger on navigation requires browser rendering and WS connection"
  - test: "Already-configured inverters in scan results"
    expected: "Row is greyed out (opacity 0.5) with 'Bereits konfiguriert' label, no checkbox shown"
    why_human: "Requires actual scan returning a device matching a configured inverter"
  - test: "Change Scan-Ports field value and blur, then refresh"
    expected: "Updated ports value persists across page refresh (loaded from /api/scanner/config)"
    why_human: "Requires live browser with API calls and page refresh"
  - test: "Empty scan result (no inverters found)"
    expected: "Orange hint card appears with 'Keine Inverter gefunden' header and troubleshooting text"
    why_human: "Requires a real scan against a subnet with no inverters, or mocking WS scan_complete with empty devices"
---

# Phase 20: Discovery UI & Onboarding Verification Report

**Phase Goal:** User can trigger scans, see live progress, preview results, and new setups auto-discover inverters
**Verified:** 2026-03-20T17:10:00Z
**Status:** human_needed (all automated checks passed)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

#### Plan 01 (Backend) — 7 truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /api/scanner/discover returns immediately with `{status: started}` | VERIFIED | `webapp.py:974` returns `{"status": "started"}` after `create_task(_run_scan)` |
| 2 | Concurrent scan requests return 409 with error message | VERIFIED | `webapp.py:958-959` checks `_scan_running` flag, returns 409 `{"error": "Scan already running"}` |
| 3 | WebSocket clients receive scan_progress messages during scan | VERIFIED | `_broadcast_scan_progress` at `webapp.py:569` sends `{"type": "scan_progress", "data": {...}}` via `ensure_future` from `_run_scan` |
| 4 | WebSocket clients receive scan_complete with device list when scan finishes | VERIFIED | `_broadcast_scan_complete` at `webapp.py:585` serializes actual device list from `scan_subnet` result |
| 5 | WebSocket clients receive scan_error if scan fails | VERIFIED | `_broadcast_scan_error` at `webapp.py:604` called in `_run_scan` except block |
| 6 | scanner.ports persists in config YAML and round-trips correctly | VERIFIED | `ScannerConfig` at `config.py:75`, `load_config` parsing at line 157, test `test_scanner_config_yaml_roundtrip` passes |
| 7 | GET/PUT /api/scanner/config reads and updates scanner ports | VERIFIED | Routes at `webapp.py:1128-1129`, handlers at lines 921 and 927 |

#### Plan 02 (Frontend) — 11 truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 8 | User sees discover button (magnifying glass icon) in inverter panel header, left of + button | VERIFIED | `index.html:265` `#btn-discover-inverter` precedes `#btn-add-inverter` at line 271; SVG icon at lines 266-270 |
| 9 | Clicking discover button triggers POST /api/scanner/discover and shows progress bar | VERIFIED | `app.js:1341-1344` click handler calls `triggerScan()`; `triggerScan()` at line 1309 fetches `/api/scanner/discover` |
| 10 | Progress bar fills with blue and shows phase text | VERIFIED | `handleScanProgress` at `app.js:1146` sets `fill.style.width = pct + '%'`; text "Scanning network" and "Verifying SunSpec" present |
| 11 | Discover button disabled with spinner icon during scan | VERIFIED | `setScanButtonState(true)` at `app.js:1326` adds `ve-scanning` class and sets `disabled = true`; CSS at `style.css:1896-1901` triggers `ve-spin` animation |
| 12 | Scan results appear as checkbox list with manufacturer, model, host:port, unit ID | VERIFIED | `createScanResultRow` at `app.js:1229` builds rows with all four fields |
| 13 | Already-configured inverters are greyed out with "Bereits konfiguriert" label | VERIFIED | `createScanResultRow` at `app.js:1239` renders configured label; `ve-scan-result--configured` CSS at `style.css:1858` sets `opacity: 0.5` |
| 14 | "Add All" button above results adds all checked devices via POST /api/inverters | VERIFIED | `handleScanComplete` at `app.js:1194` creates button; `addDiscoveredInverters` at line 1262 POSTs to `/api/inverters` |
| 15 | Empty scan shows orange hint card with troubleshooting tips | VERIFIED | `handleScanComplete` at `app.js:1178` renders `ve-hint-card` with "Keine Inverter gefunden" text when `devices.length === 0` |
| 16 | When config page opens with empty inverter list, scan starts automatically | VERIFIED | `loadInverters` at `app.js:861-864` calls `triggerScan()` if `!_autoScanDone`; `_autoScanDone` reset to false on config navigation at line 34 |
| 17 | Single auto-scan result is auto-added with toast notification | VERIFIED | `handleScanComplete` at `app.js:1185-1187` calls `addDiscoveredInverters([devices[0]])` when `_autoScanDone && devices.length === 1 && !isAlreadyConfigured` |
| 18 | Scan-Ports field shows comma-separated ports, persisted via PUT /api/scanner/config | VERIFIED | Ports loaded from API at `app.js:820-822`; blur handler at line 1347 saves via PUT; HTML field at `index.html:294` |

**Score:** 18/18 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/venus_os_fronius_proxy/config.py` | ScannerConfig dataclass with ports field | VERIFIED | `class ScannerConfig` at line 75 with `ports: list[int]` and default `[502, 1502]`; wired into `Config` at line 86 |
| `src/venus_os_fronius_proxy/webapp.py` | Background scan with WS progress broadcasting | VERIFIED | `_broadcast_scan_progress`, `_broadcast_scan_complete`, `_broadcast_scan_error`, `_run_scan` all present and substantive |
| `src/venus_os_fronius_proxy/static/index.html` | Discover button, scan area, ports field HTML | VERIFIED | `#btn-discover-inverter` with SVG at line 265; `#scan-area` at line 296; `#scan-ports-field` at line 292 |
| `src/venus_os_fronius_proxy/static/style.css` | Scan progress bar, result row, ports field styles | VERIFIED | `.ve-scan-bar` at line 1819; `.ve-scan-bar-fill` at line 1825; `.ve-scan-result` at line 1850; `.ve-scan-ports` at line 1799 |
| `src/venus_os_fronius_proxy/static/app.js` | WS message handlers, scan UI logic, auto-scan, batch add | VERIFIED | `handleScanProgress` at line 1146; `handleScanComplete` at 1164; `handleScanError` at 1221; `triggerScan` at 1290; `addDiscoveredInverters` at 1262; `_autoScanDone` at line 17 |
| `tests/test_config.py` | Scanner config default and round-trip tests | VERIFIED | `test_scanner_config_default_ports` at line 285; `test_scanner_config_yaml_roundtrip` at line 293; both pass |
| `tests/test_webapp.py` | Scanner discover and concurrent guard tests | VERIFIED | `test_scanner_discover_returns_started` at line 672; `test_scanner_discover_concurrent_guard` at line 682; both pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `webapp.py scanner_discover_handler` | `scanner._run_scan` | `asyncio.create_task` | WIRED | `create_task(_run_scan(app, scan_config))` at `webapp.py:973` |
| `webapp.py _run_scan` | `_broadcast_scan_progress` | `asyncio.ensure_future` | WIRED | `ensure_future(_broadcast_scan_progress(app, phase, current, total))` at `webapp.py:622` |
| `app.js btn-discover-inverter click` | `POST /api/scanner/discover` | `fetch in triggerScan()` | WIRED | Click at `app.js:1341` → `triggerScan()` → `fetch('/api/scanner/discover', ...)` at line 1309 |
| `app.js ws.onmessage` | `handleScanProgress, handleScanComplete, handleScanError` | `msg.type routing` | WIRED | Lines 109-111: `msg.type === 'scan_progress'`, `msg.type === 'scan_complete'`, `msg.type === 'scan_error'` |
| `app.js addDiscoveredInverters` | `POST /api/inverters` | `sequential fetch calls` | WIRED | `fetch('/api/inverters', { method: 'POST', ... })` at `app.js:1270` |
| `app.js loadInverters` | `triggerScan` | `empty list auto-scan check` | WIRED | `if (!_scanRunning && !_autoScanDone) { _autoScanDone = true; triggerScan(); }` at lines 861-863 |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DISC-05 | 20-01, 20-02 | User sieht Scan-Fortschritt im UI (Fortschrittsbalken oder Animation) | SATISFIED | `handleScanProgress` drives progress bar fill via WS; `ve-scan-bar-fill` width animated in CSS |
| CONF-04 | 20-01, 20-02 | Gefundene Inverter aus Scan werden automatisch als Config-Eintraege angelegt | SATISFIED | `addDiscoveredInverters` POSTs to `/api/inverters`; "Alle uebernehmen" button and auto-add single result both implemented |
| UX-01 | 20-02 | Wenn kein Inverter konfiguriert ist, startet automatisch ein Hintergrund-Scan beim Oeffnen der Config-Seite | SATISFIED | `loadInverters` triggers `triggerScan()` on empty list when `_autoScanDone` is false; `_autoScanDone` resets on config navigation |
| UX-02 | 20-02 | User kann manuell einen Re-Scan triggern ueber einen Auto-Discover Button in der Config-Leiste | SATISFIED | `#btn-discover-inverter` in panel header with click handler at `app.js:1341` |
| UX-03 | 20-02 | Scan-Ergebnisse werden als Vorschau-Liste angezeigt, User bestaetigt Uebernahme | SATISFIED | `createScanResultRow` builds checkbox list; "Alle uebernehmen" button confirms batch add |

All 5 requirements satisfied. No orphaned requirements (REQUIREMENTS.md shows DISC-05, CONF-04, UX-01, UX-02, UX-03 all mapped to Phase 20).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `style.css` | 1740, 1903 | Duplicate `@keyframes ve-spin` declaration | Warning | Pre-existing at 1740 (spinner); Phase 20 added second at 1903 (scan button). CSS last-declaration-wins, so both animate identically. No functional impact but creates dead code. |

No blocker anti-patterns found. No TODO/FIXME/placeholder patterns in phase-modified files. No hardcoded hex colors in the new scan CSS section (lines 1799+). Existing `#fff`/`#000` instances are pre-existing and permitted by CLAUDE.md for high-contrast toggle knobs.

### Human Verification Required

#### 1. Scan UX animation and progress flow

**Test:** Start a real network scan via the discover button in the config page inverter panel header.
**Expected:** Button icon spins during scan; blue bar fills from left to right with text "Scanning network (X/Y)..." progressing to "Verifying SunSpec (X/Y)..."; button re-enables after completion.
**Why human:** CSS animation (`ve-spin`) and progress bar fill progression require browser rendering; WS timing cannot be verified statically.

#### 2. Auto-scan onboarding on empty inverter list

**Test:** Delete all configured inverters (or use a fresh config), then navigate away from the config page and back to it.
**Expected:** Scan fires automatically without clicking anything; progress bar appears; if exactly one device is found and not already configured, it is auto-added with a toast ("Inverter hinzugefuegt") and the list reloads.
**Why human:** Requires browser navigation events and live WS connection; `_autoScanDone` reset logic depends on `navigateTo()` being triggered by actual hash navigation.

#### 3. Duplicate detection (Bereits konfiguriert)

**Test:** Run a scan when at least one already-configured inverter is on the network.
**Expected:** That inverter's row appears greyed out (50% opacity) with "Bereits konfiguriert" in place of a checkbox; it cannot be added again.
**Why human:** Requires a real scan response containing a device matching a configured host+port+unit_id combination.

#### 4. Ports field persistence across page refresh

**Test:** Change the Scan-Ports input from "502, 1502" to "502" and click elsewhere to trigger blur; then refresh the page.
**Expected:** The input shows "502" after refresh (loaded from `/api/scanner/config` which persists to YAML).
**Why human:** Requires browser interaction, live API call, and page refresh cycle.

#### 5. Empty scan hint card

**Test:** Trigger a scan against a subnet with no responding inverters (or wait for scan to complete with zero results).
**Expected:** Orange hint card appears in the scan area with header "Keine Inverter gefunden" and troubleshooting text about checking device power, Modbus TCP, and ports.
**Why human:** Requires a scan that actually returns zero devices; cannot mock WS messages in static verification.

### Gaps Summary

No gaps. All 18 observable truths are verified against the actual codebase. All key links are wired end-to-end. All five requirements are satisfied with concrete implementation evidence. The five items flagged for human verification are UX-layer behaviors (animations, WS-driven progress, browser navigation events) that are correct in the code but require a running browser to confirm the integrated experience.

The only minor code quality issue is a duplicate `@keyframes ve-spin` declaration in `style.css` (line 1740 pre-existing, line 1903 added in Phase 20). This has no functional impact since CSS last-declaration-wins, but the duplicate at line 1903 could be removed.

---

_Verified: 2026-03-20T17:10:00Z_
_Verifier: Claude (gsd-verifier)_
