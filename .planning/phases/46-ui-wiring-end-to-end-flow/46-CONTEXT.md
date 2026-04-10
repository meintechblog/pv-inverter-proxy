# Phase 46: UI Wiring & End-to-End Flow — Context

**Gathered:** 2026-04-11
**Status:** Ready for planning
**Source:** Inline decisions during `/gsd-plan-phase 46` (no full discuss-phase run)

<domain>
## Phase Boundary

Phase 46 **wires** the Phase 45 update engine into the webapp UI with a full security belt. Phase 45 already ships: trigger file writer, maintenance mode, update status file (`/etc/pv-inverter-proxy/update-status.json`) with 17-phase vocabulary, one-shot `update_in_progress` WebSocket broadcast, and the root updater.

**Phase 46 delivers:**
- `#system/software` page (new hash route) with version card, release notes (Markdown-rendered), Install button, rollback button, and update-config form
- Confirmation modal with CSRF-protected `POST /api/update/start` that returns 202 < 100ms
- Progress broadcaster that polls `update-status.json` every 500ms and emits `update_progress` WebSocket messages per phase transition
- Client state machine that disables all update buttons while running and reuses the existing v2.1 toast stacking system
- `/api/version` reconnect detection that triggers `location.reload()` when the version changes
- Concurrent-update guard (reads status file, not `asyncio.Lock`), 60-second rate limiter per source IP, JSONL audit log at `/var/lib/pv-inverter-proxy/update-audit.log`
- Rollback endpoint + UI with a 1-hour visibility window after successful updates
- Minimal `UpdateConfig` dataclass (3 fields only) wired into existing dirty-tracking Save/Cancel pattern

**Out of scope (Phase 47+):**
- Full config schema (CFG-01)
- Dedicated update history file (HIST-01)
- Rollback browsing from arbitrary historical entries
- Audit log rotation

</domain>

<decisions>
## Implementation Decisions

### Decision Mode
- **D-01** (LOCKED): CONTEXT.md was authored inline from research findings + 4 product decisions, NOT from a full discuss-phase run. Researcher flagged 3 LOW-confidence product questions (A2/A3/A4) which are resolved below.

### Rollback Window (UI-07, UI-08)
- **D-02** (LOCKED): Rollback button visibility window is **1 hour fixed** after a successful update. Client-side timer stores `lastUpdateSuccessAt` in `sessionStorage`; button hides when `now - lastUpdateSuccessAt > 3600000ms`.
- **D-03** (LOCKED): Rollback history source is the **update-status.json only**. The rollback endpoint accepts `target_sha="previous"` sentinel and rolls back to whatever the status file records as the previous version. Phase 46 does NOT ship per-history-entry rollback buttons — that waits for HIST-01 in Phase 47.

### Config Scope (CFG-02)
- **D-04** (LOCKED): Phase 46 promotes a **minimal 3-field `UpdateConfig` dataclass**:
  - `github_repo: str` — e.g. `"hulki/pv-inverter-proxy"`
  - `check_interval_hours: int` — default 24
  - `auto_install: bool` — default `False`
- **D-05** (LOCKED): The full config schema (CFG-01) stays in Phase 47. Phase 46 wires only these 3 fields into the existing `ve-cfg-save-pair` dirty-tracking pattern.
- **D-06** (LOCKED): Config editing requires a server-side endpoint. If `PATCH /api/config` does not exist from earlier phases, Plan 46-05 adds it (scoped to the 3 update fields for now).

### CSRF Protection (SEC-01)
- **D-07** (LOCKED): **Double-submit cookie** pattern with stdlib `secrets.token_urlsafe(32)`. Cookie `csrf_token` (HttpOnly=False, SameSite=Strict, Secure=False on LAN). Client reads cookie, sends header `X-CSRF-Token`. aiohttp middleware enforces `secrets.compare_digest(cookie, header)` on every POST/PATCH.
- **D-08** (LOCKED): Token is issued lazily: if the cookie is missing on any GET, middleware sets it in the response. No dedicated `/api/csrf` endpoint.
- **D-09** (LOCKED): Rationale: zero-dep, no session layer needed, `SameSite=Strict` covers the cross-site POST class, timing-safe comparison prevents token oracle.

### Concurrent-Update Guard (SEC-02)
- **D-10** (LOCKED): The guard reads `update-status.json` via the existing `updater.status.load_status()` + `current_phase()` helpers. A new POST is accepted only when `current_phase() in IDLE_PHASES = {idle, done, rollback_done, rollback_failed}`. Otherwise respond `409 Conflict` with `{"error": "update_in_progress", "phase": "<current>"}`.
- **D-11** (LOCKED): Do **NOT** use `asyncio.Lock` as the single source of truth — the webapp process does not own the updater; only the root updater writes the status file. Use the status file as the authoritative source.

### Rate Limiting (SEC-03)
- **D-12** (LOCKED): Sliding 60-second window, in-memory `dict[str, float]` keyed by `request.remote` (source IP from aiohttp, NOT `X-Forwarded-For` — this is a LAN appliance with no reverse proxy in scope).
- **D-13** (LOCKED): A second `POST /api/update/start` from the same source IP within 60s of the first → `429 Too Many Requests` with `Retry-After: <seconds_remaining>` header. Entries older than 60s are lazily evicted on each call.
- **D-14** (LOCKED): 409 vs 429 flow: 409 = update is actively running (status file ≠ idle). 429 = no update running but same IP retried within 60s of its previous accepted or rejected request.

### Audit Log (SEC-04)
- **D-15** (LOCKED): Format is **JSONL** (one JSON object per line). Fields per line:
  ```json
  {"ts": "<ISO 8601 UTC>", "ip": "<request.remote>", "ua": "<User-Agent>", "outcome": "accepted|409_conflict|429_rate_limited|422_invalid_csrf"}
  ```
- **D-16** (LOCKED): Path `/var/lib/pv-inverter-proxy/update-audit.log`. Directory created lazily on first write (`os.makedirs(parent, mode=0o750, exist_ok=True)`). File mode `0o640`, owner `pv-proxy:pv-proxy` (webapp user). Deploy script does NOT pre-create — lazy creation is fine.
- **D-17** (LOCKED): Concurrent-safe append via a module-level `asyncio.Lock` wrapping `open('a')` + `json.dumps` + `write('\n')`. Single-line writes are small enough that atomicity within the lock is sufficient.
- **D-18** (LOCKED): Rotation is **out of scope** for Phase 46. Phase 47+ can add log rotation if needed.
- **D-19** (LOCKED): Every request (accepted or rejected) is logged — including 422 invalid CSRF, 409 conflict, and 429 rate limited.

### Atomic Trigger File & <100ms Latency
- **D-20** (LOCKED): `POST /api/update/start` handler runs (a) CSRF check, (b) rate-limit check, (c) concurrent-guard check, (d) atomic trigger file write, (e) audit log append, (f) returns 202 immediately. No awaits on update execution — the root updater picks up the trigger file asynchronously.
- **D-21** (LOCKED): Atomic write pattern: `open(tmp, 'w')` → `json.dump(payload, f)` → `f.flush()` → `os.fsync()` → `os.replace(tmp, final)`. Reuses any existing Phase 45 `write_trigger_file()` helper if present.

### WebSocket Progress Protocol (UI-02, UI-03)
- **D-22** (LOCKED): New module `updater/progress.py` polls `update-status.json` every **500ms** while `current_phase() not in IDLE_PHASES`. Stops polling when idle. Poller is a single module-level `asyncio.Task` started on app startup.
- **D-23** (LOCKED): Message envelope:
  ```json
  {"type": "update_progress", "data": {"phase": "<name>", "at": "<ISO 8601>", "sequence": <int>, "error": "<str or null>"}}
  ```
- **D-24** (LOCKED): Dedupe via the `sequence` field from `history[]` in the status file (monotonic int). Broadcaster tracks `last_sequence_sent` per poll cycle; only new entries are emitted.
- **D-25** (LOCKED): On WS reconnect, client fetches `/api/update/status` to replay any missed sequence numbers, then resumes live broadcasts. Gaps detected by client comparing `data.sequence` to previously-seen max.
- **D-26** (LOCKED): The 17-phase vocabulary comes from `updater_root/status_writer.py`'s `PHASES` frozenset. Client-side checklist renders all 17 phases; each is marked pending/running/done/failed based on the latest event.

### Version Reload Detection (UI-03)
- **D-27** (LOCKED): `GET /api/version` returns `{"version": "<semver>", "commit": "<sha>"}`. Client stores this on first load in a module-level variable. On every WS reconnect, client re-fetches `/api/version`; if `version` or `commit` changed, client calls `location.reload()`. This handles the post-update success case.

### Minimal Markdown Subset (UI-01)
- **D-28** (LOCKED): Pure-JS implementation in new file `webapp/static/software_markdown.js` (~120 LOC). Allow-list:
  - `# H1`, `## H2`, `### H3` (single `#` with space)
  - `**bold**`, `*italic*`, `` `code` ``
  - `- list item` (flat, no nesting)
  - blank line → paragraph break
  - plain text → `textContent` (never `innerHTML`)
- **D-29** (LOCKED): **Forbidden**: raw HTML, links (even markdown `[text](url)`), images, tables, nested lists, `javascript:` URIs, HTML entities beyond `&amp;`/`&lt;`/`&gt;`. Rationale: zero-XSS for untrusted GitHub release notes.
- **D-30** (LOCKED): Implementation emits DOM nodes directly (`document.createElement` + `textContent`), never builds innerHTML strings.

### Modal Dialog (UI-04)
- **D-31** (LOCKED): Use native `<dialog>` element (supported in all modern browsers, zero-dep). Styled with existing `ve-modal-overlay` CSS where applicable; new `ve-dialog` class if the overlay doesn't fit.
- **D-32** (LOCKED): Cancel has default focus (autofocus attribute on Cancel button). ESC key closes dialog (native `<dialog>` behavior). No type-to-confirm.
- **D-33** (LOCKED): Title: "Update installieren?" Body: shows version delta (`v{current} → v{target}`), release notes preview, and warning "Der Update-Prozess startet den Service neu." Buttons: "Abbrechen" (default focus) / "Installieren" (primary).

### Client State Machine (UI-05, UI-06)
- **D-34** (LOCKED): Single global `updateState` object: `{ phase: 'idle|confirming|starting|running|success|failed', version, lastUpdateSuccessAt }`. Driven by WS messages + fetch responses.
- **D-35** (LOCKED): Button disable strategy: CSS class `ve-update-busy` toggled on `<body>`; CSS rule `.ve-update-busy .ve-update-action { pointer-events: none; opacity: 0.5; }`. All disable-able buttons get class `ve-update-action`.
- **D-36** (LOCKED): Buttons to disable while `phase ∈ {starting, running}`: Install, Check now, Rollback, and the update-config Save button.

### Toast Integration (UI-06)
- **D-37** (LOCKED): Reuse existing `showToast(message, type)` API from v2.1 toast stack. Types used: `success`, `error`. Do NOT introduce a new toast primitive.

### Frontend File Layout
- **D-38** (LOCKED): New files (do NOT grow `app.js` or `webapp.py`):
  - `webapp/static/software_page.js` (~600 LOC) — page controller, state machine, WS handler, fetch calls
  - `webapp/static/software_markdown.js` (~120 LOC) — Markdown parser
  - CSS additions to `webapp/static/style.css` for `ve-update-*` classes
- **D-39** (LOCKED): `index.html` adds `<script src="software_page.js">` and `<script src="software_markdown.js">` tags, plus the `#system/software` nav entry and page container div.

### Backend File Layout
- **D-40** (LOCKED): New Python modules:
  - `pv_inverter_proxy/updater/security.py` — CSRF middleware, rate limiter, audit log writer, concurrent-update guard
  - `pv_inverter_proxy/updater/progress.py` — status file poller + WS broadcaster
  - `pv_inverter_proxy/updater/config.py` — `UpdateConfig` dataclass + load/save helpers (3 fields)
- **D-41** (LOCKED): New routes added to existing `webapp.py` handler (do NOT create a new router module): `GET /api/version`, `POST /api/update/start`, `POST /api/update/rollback`, `GET /api/update/status`, `PATCH /api/update/config`, `GET /api/update/config`, `POST /api/update/check`.

### Deploy Target
- **D-42** (LOCKED): Auto-deploy to LXC at `192.168.3.191` after all plans pass verification (per user memory).

### Claude's Discretion
- Exact CSS token values for new `ve-update-*` classes (must conform to CLAUDE.md design system)
- Exact Python function signatures inside the new modules
- Choice of test file names and fixture layout
- Internal layout of the `UpdateStatus` response shape beyond the minimum {version, commit, phase, history[]}

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 46 Research
- `.planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md` — Full technical research, 9 pitfalls, Validation Architecture

### Phase 45 (predecessor — reuse, don't duplicate)
- `.planning/phases/45-*/` — All Phase 45 artifacts
- `src/pv_inverter_proxy/updater/trigger.py` — Trigger file writer (atomic pattern)
- `src/pv_inverter_proxy/updater/status.py` — `load_status()`, `current_phase()`, `IDLE_PHASES`
- `src/pv_inverter_proxy/updater/maintenance.py` — Maintenance mode helpers
- `src/pv_inverter_proxy/updater_root/status_writer.py` — `PHASES` frozenset (17 entries)

### Webapp (existing patterns to extend)
- `src/pv_inverter_proxy/webapp.py` — aiohttp server, existing routes + WS handler
- `src/pv_inverter_proxy/static/app.js` — existing `showToast()`, nav router, config dirty-tracking
- `src/pv_inverter_proxy/static/index.html` — sidebar structure, hash routing
- `src/pv_inverter_proxy/static/style.css` — `ve-*` design tokens, `ve-modal-overlay`, `ve-cfg-save-pair`

### Project Conventions
- `CLAUDE.md` — Design system (ve-* classes, CSS variables, zero-dep frontend, asyncio backend)
- `.planning/REQUIREMENTS.md` — UI-01..UI-09, SEC-01..SEC-04, CFG-02

</canonical_refs>

<specifics>
## Specific Ideas

- Dedupe by `history[].sequence` is the correct approach — Phase 45 already writes monotonic sequence numbers (Pitfall 6 in RESEARCH.md)
- Poll interval 500ms is fast enough for UI responsiveness but slow enough not to starve the event loop
- `fs.fsync` on the trigger file is MANDATORY — the root updater may poll before the page cache flushes
- Lazy directory creation for audit log means deploy script stays simple
- Sidebar nav: `#system/software` becomes a sub-entry under an existing "System" parent if one exists, otherwise a top-level entry

</specifics>

<deferred>
## Deferred Ideas

- **CFG-01** (full config schema with validation, env var mapping, YAML persistence) → Phase 47
- **HIST-01** (dedicated `update-history.json` with arbitrary entry browsing) → Phase 47
- **Rollback from any history entry** (UI ships with only the `target_sha="previous"` sentinel in Phase 46)
- **Audit log rotation** → Phase 47+ if ever needed
- **Multi-user auth / session layer** → not planned (LAN appliance, single user)
- **Reverse proxy support** (trusted `X-Forwarded-For`) → not planned

</deferred>

---

*Phase: 46-ui-wiring-end-to-end-flow*
*Context gathered: 2026-04-11 via inline /gsd-plan-phase questions (discuss-phase skipped)*
