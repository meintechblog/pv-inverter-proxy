---
phase: 46-ui-wiring-end-to-end-flow
plan: 03
type: execute
wave: 2
depends_on: [46-01]
files_modified:
  - src/pv_inverter_proxy/static/software_page.js
  - src/pv_inverter_proxy/static/software_markdown.js
  - src/pv_inverter_proxy/static/index.html
  - src/pv_inverter_proxy/static/style.css
  - src/pv_inverter_proxy/static/app.js
autonomous: true
requirements: [UI-01, UI-03, UI-04, UI-05, UI-06, UI-07, UI-09]
threat_refs: [T-46-06, T-46-07]
decisions_implemented: [D-02, D-03, D-27, D-28, D-29, D-30, D-31, D-32, D-33, D-34, D-35, D-36, D-37, D-38, D-39]

must_haves:
  truths:
    - "Sidebar has a System > Software entry that hash-routes to #system/software"
    - "#system/software page shows version card, release-notes card, rollback card, update-config card"
    - "Markdown renderer produces DOM via document.createElement + textContent (never innerHTML)"
    - "Install confirmation uses native <dialog> with Cancel autofocus and ESC close"
    - "Rollback confirmation uses native <dialog> with the same pattern"
    - "Rollback button visibility is gated by sessionStorage.lastUpdateSuccessAt within a 1-hour window"
    - "body.ve-update-busy disables all .ve-update-action buttons during starting/running phases"
    - "WebSocket update_progress messages dedupe by monotonic sequence field"
    - "On WS reconnect, /api/version is fetched and triggers location.reload() on mismatch"
    - "17-phase progress checklist renders PHASE_ORDER that matches updater_root.status_writer.PHASES byte-for-byte"
---

# Plan 46-03: Frontend Software Page

> **HISTORY NOTE:** This plan file was lost during Wave 2 worktree merging (it existed
> only as an untracked file in main and was deleted to unblock a merge conflict). The
> plan was written, executed, and completed successfully — see `46-03-SUMMARY.md` for
> the full record of what was built. This stub exists so phase verification, code review,
> and other tooling that expects a PLAN.md file can still find one.

<objective>
Build the `#system/software` page — the entire user-facing surface for Phase 46. Sidebar
entry, version card, release-notes card with safe Markdown rendering, confirmation modal,
17-phase progress checklist, rollback button with 1-hour visibility window, update-config
panel skeleton (wiring lives in Plan 46-05), and the client state machine that disables
buttons during an update.
</objective>

<threat_model>
- **T-46-06 (XSS via release notes):** Mitigated by Markdown allow-list DOM emitter in
  `software_markdown.js`. Uses `document.createElement` + `textContent` exclusively.
  Forbids raw HTML, links, images, code fences, nested lists, and `javascript:`/`data:`
  URIs. Acceptance check greps for absence of `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`.
- **T-46-07 (Stale version cache after update):** Mitigated by `/api/version` probe on
  every WebSocket reconnect. If version or commit changed, client calls `location.reload()`.
</threat_model>

<tasks>
See `46-03-SUMMARY.md` for the full record of tasks executed:
1. Add allow-list Markdown DOM emitter (`software_markdown.js`, 138 LOC)
2. Implement software page controller + state machine (`software_page.js`, 938 LOC)
3. Wire software page into `index.html` (sidebar entry, script tags, `#software-root`)
4. Add `ve-update-*`/`ve-software-*`/`ve-md-*`/`ve-dialog` CSS (+225 lines)

All tasks committed atomically:
- `30a261c` feat(46-03): add allow-list Markdown DOM emitter
- `46f1f82` feat(46-03): implement software page controller + state machine
- `60cdcab` feat(46-03): wire software page into index.html
- `b5d745e` feat(46-03): add ve-update-*/ve-software-*/ve-md-*/ve-dialog CSS
- `e6be765` docs(46-03): complete frontend software page plan
</tasks>

<verification>
Executed and passed:
- `grep -q createElement software_markdown.js && ! grep -qE "innerHTML|outerHTML|insertAdjacentHTML|document.write" software_markdown.js`
- Zero native `confirm()` in `software_page.js` (rollback uses `<dialog>` per D-31/D-32)
- PHASE_ORDER byte-parity with Python `updater_root.status_writer.PHASES` (19 phases — NOT 17 as originally assumed; see SUMMARY deviations)
- Zero hardcoded hex colors in new style.css block; 38 `var(--ve-*)` token references
- Node smoke-import of both JS files exits 0
- All 4 task verify blocks green
</verification>
