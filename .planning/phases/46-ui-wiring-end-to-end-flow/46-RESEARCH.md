# Phase 46: UI Wiring & End-to-End Flow — Research

**Researched:** 2026-04-11
**Domain:** aiohttp webapp + vanilla JS SPA wiring Phase 45 update engine to the user
**Confidence:** HIGH (codebase verified) — LOW on two intentionally deferred product decisions (rollback window duration, update history source in Phase 46 vs 47)

## Summary

Phase 45 shipped the entire update execution pipeline: the trigger-file writer, maintenance mode + `update_in_progress` WebSocket broadcast, the root updater service, the status file writer with a 17-entry phase vocabulary, and the atomic `POST /api/update/start` endpoint. **Phase 46 is a wiring phase** — no new subsystems, just a UI and a security belt around the existing endpoint.

The work splits into four cleanly separated concerns:
1. **Read-path WS stream**: poll `/etc/pv-inverter-proxy/update-status.json` from the main service (via the existing `updater.status.load_status` reader), detect phase transitions, emit an `update_progress` WS message. Nothing touches the updater.
2. **Security belt** on `POST /api/update/start` and the new `POST /api/update/rollback`: CSRF (double-submit cookie), rate limit (asyncio lock + sliding window dict), concurrent guard (re-read status file), audit log (JSONL append).
3. **Frontend**: new `#system/software` hash route, a `ve-modal-overlay` confirmation dialog (base CSS already exists), a minimal pure-JS Markdown renderer, a progress checklist driven by the new `update_progress` WS messages, wiring into the existing `showToast()` and dirty-tracking config pattern.
4. **`/api/version` reconnect probe** for stale-tab detection (UI-08).

**Primary recommendation:** Keep all new backend code in a new `pv_inverter_proxy.updater.webapp_security` module (CSRF, rate limit, audit) and a new `pv_inverter_proxy.updater.progress_broadcaster` module (file-watch + WS push). Leave `webapp.py` changes to route registration + middleware wiring — it's already 2395 lines and the update handlers should not grow it further. Frontend lives in a new `static/software_page.js` loaded by `index.html`, avoiding further growth of the 3195-line `app.js`.

<user_constraints>
## User Constraints (from CONTEXT.md)

**No CONTEXT.md exists for Phase 46** — this research runs in standalone mode. The planner should run `/gsd-discuss-phase` before committing to the two LOW-confidence product decisions flagged in the **Assumptions Log** below (rollback window duration, history source).

Implicit constraints from CLAUDE.md (project-level, mandatory):
- Zero-dep vanilla JS frontend, no build tooling, no npm
- All CSS via `ve-*` classes and `--ve-*` CSS variables (no hardcoded colors)
- Python asyncio + aiohttp; no new heavy deps
- Auto-deploy to LXC 192.168.3.191 after code changes
- All config must be editable via webapp, never YAML-only

Implicit constraints from the memory index:
- `feedback_ui_consistency`: all device types must have identical UI patterns — the new `#system/software` page must reuse `ve-panel`, `ve-panel-header`, `ve-btn-pair`, `ve-cfg-*` conventions.
- `feedback_webapp_config`: all update config must be editable via webapp, not just YAML.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | New sidebar rubric `System / Software` | § F.1 sidebar rendering already supports a SYSTEM group (webapp static/app.js:130,188-213); just promote it from "only when update available" to always-visible |
| UI-02 | Software page shows version + commit + last check + Check now button | § A.1 `/api/update/available` already returns this payload; add Check-now endpoint that calls scheduler's check_once |
| UI-03 | Update-available card with version delta + Markdown-rendered release notes + Install + "View on GitHub" | § G minimal Markdown allow-list; release body already present in `available_update.release_notes` (webapp.py:540) |
| UI-04 | Confirmation modal with Cancel default-focus, no type-to-confirm | § H existing `ve-modal-overlay` CSS (style.css:1513-1547); extend with focus trap + ESC |
| UI-05 | Progress checklist driven by WS `update_progress` messages | § F.2 17 phases from `updater_root.status_writer.PHASES` (status_writer.py:35-58); new broadcaster polls status file |
| UI-06 | Success/failure toast via v2.1 toast stack | § A.4 `showToast()` already exists (app.js:3072) with success/error/warning/info + max-4 stacking |
| UI-07 | Rollback button bounded window after success + from history entries | § I LOW confidence — two sub-decisions flagged in assumptions |
| UI-08 | WS reconnect → fetch `/api/version` → reload on mismatch | § A.1 new endpoint; existing `app_ctx.current_version` already set at boot |
| UI-09 | State machine disables buttons while `state != idle` | § K single client-side `updateState` observable; data-update-disabled attribute |
| SEC-01 | CSRF token on all update POST endpoints | § B double-submit cookie pattern + aiohttp middleware |
| SEC-02 | Rate limit 1 attempt/60s + HTTP 429 + Retry-After | § C.2 in-memory sliding window keyed by `request.remote` |
| SEC-03 | Concurrent guard → HTTP 409 | § C.1 re-read status file; current phase not in `{idle, done, rollback_done, rollback_failed}` → 409 |
| SEC-04 | Audit log to `/var/lib/pv-inverter-proxy/update-audit.log` | § D JSONL, single-writer via asyncio.Lock |
| CFG-02 | All update config editable via webapp, dirty-tracking Save/Cancel | § J reuse `ve-cfg-save-pair` pattern (app.js:1158-1320) — but see § J CAVEAT: CFG-01 lives in Phase 47, so there's a sequencing issue |
</phase_requirements>

## Standard Stack

### Core — all already in the project, zero new deps
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiohttp | >=3.10,<4.0 `[VERIFIED: pyproject.toml:7]` | Web server, WebSocket, middleware | Existing stack; middleware is the idiomatic CSRF/rate-limit plug-in point |
| asyncio | stdlib | Lock, create_task, Queue for audit writer | Already used throughout |
| structlog | >=24.0 `[VERIFIED: pyproject.toml:8]` | Structured logging for audit + error paths | Existing stack |
| json (stdlib) | — | Audit JSONL + Markdown-safe DOM emission | Zero-dep |
| secrets (stdlib) | — | CSRF token generation (`secrets.token_urlsafe(32)`) | Cryptographically strong, stdlib, no dep |

### Frontend — zero dependencies (per CLAUDE.md)
| Asset | Purpose | Pattern |
|-------|---------|---------|
| New `static/software_page.js` | Avoid further growth of 3195-line `app.js`; loaded via second `<script src>` in `index.html` | Exposes `window.softwarePage = { init(), handleProgress(msg), ... }` |
| Inline CSS additions to `style.css` | Progress checklist, modal focus styles, audit/history styles | Use `ve-software-*`, `ve-update-*` class prefixes |
| Native `<dialog>` vs custom overlay | See § H — recommend custom overlay (the codebase already has `ve-modal-overlay` CSS; native `<dialog>` styling is inconsistent across Chromium/Firefox and the design system does not target it) | `CITED: https://developer.mozilla.org/en-US/docs/Web/HTML/Element/dialog` `[ASSUMED]` for Venus OS browser baseline |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Poll `update-status.json` every 250ms | `inotify` via `aiofiles.os` or `watchfiles` | New dep; the status file is written maybe 15 times per update — polling at 500ms adds negligible load and needs no new dep |
| Double-submit cookie CSRF | Synchronizer token in session | No session layer exists — double-submit needs nothing but a cookie and matching header, fits stateless LAN appliance |
| In-memory rate limit dict | Redis / SQLite | Overkill for single-instance LAN appliance; restart clears dict which is fine (attacker gets at most 1 extra attempt per restart) |
| asyncio.Lock for concurrent guard | fcntl file lock on trigger file | The trigger file is single-producer atomic-write; the real guard is the updater's `update-status.json` phase — re-reading that is the authoritative source |

**No new pip installs required.** All additions use stdlib + existing aiohttp/structlog.

## Architecture Patterns

### Recommended File Layout

```
src/pv_inverter_proxy/
├── updater/
│   ├── security.py          # NEW: CSRF middleware + rate limit + concurrent guard + audit log
│   ├── progress.py          # NEW: status-file watcher → update_progress WS broadcast
│   ├── markdown.py          # NEW: pure-JS minimal Markdown — NO, backend doesn't render MD
│   │                        #     (delete this line — rendering is client-side)
│   ├── trigger.py           # [EXISTS] no changes
│   ├── status.py            # [EXISTS] reader; new progress.py imports it
│   ├── maintenance.py       # [EXISTS] no changes
│   ├── scheduler.py         # [EXISTS] new `check_once()` method for Check-now button
│   └── version.py           # [EXISTS] /api/version will reuse Version dataclass
├── static/
│   ├── app.js               # [EXISTS] Add route dispatch for #system/software, WS handler for update_progress + version_info
│   ├── software_page.js     # NEW: ~600 LOC, the #system/software page
│   ├── software_markdown.js # NEW: ~120 LOC, minimal Markdown renderer with unit tests (tests run in Python subprocess via `node` NO — no Node. Use Python-side tests via `js2py`? NO. Test via end-to-end smoke instead; see Validation Architecture.)
│   ├── index.html           # [EXISTS] add second <script src> tag for software_page.js, add #software-root container
│   └── style.css            # [EXISTS] add ~150 LOC: progress checklist, modal focus styles, audit table
└── webapp.py                # [EXISTS] register middleware + 4 new routes (version, check-now, rollback, config update, audit log viewer) — do NOT grow handlers here, delegate to `updater/security.py` and `updater/progress.py`
```

### Pattern 1: CSRF Middleware — Double-Submit Cookie

**What:** Stateless CSRF protection without a session layer.

**When to use:** Single-user LAN appliance, no auth, HTTPS not guaranteed. Same-origin only.

**Flow:**
1. Any GET request without a `csrf_token` cookie → middleware sets one: `secrets.token_urlsafe(32)`, `SameSite=Strict`, `Path=/`, `HttpOnly=False` (JS must read it), `Max-Age=86400`.
2. Client reads cookie via `document.cookie` and echoes in `X-CSRF-Token` header on every mutating request.
3. Middleware for POST/PUT/DELETE on `/api/update/*` compares cookie value to header value; mismatch → HTTP 422 `{"error":"csrf_mismatch"}`.
4. Missing cookie or header → HTTP 422 `{"error":"csrf_missing"}`.

**Why double-submit and not synchronizer token:** The webapp has no session layer. Adding one for this single feature violates "minimal change". Double-submit is widely documented as acceptable for same-origin POST when `SameSite=Strict` is set; `SameSite=Strict` alone blocks cross-site POSTs in all Chromium/Firefox/Safari versions shipped in 2024+. The cookie echo is defense-in-depth against ancient browsers and same-site XSS in unrelated pages. `[CITED: OWASP CSRF Prevention Cheat Sheet — Double Submit Cookie Pattern]` `[ASSUMED]` exact current OWASP wording has not changed since 2024.

**Code sketch:**
```python
# src/pv_inverter_proxy/updater/security.py
import secrets
from aiohttp import web

CSRF_COOKIE_NAME = "pvim_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE = 86400

@web.middleware
async def csrf_middleware(request: web.Request, handler) -> web.StreamResponse:
    # Only enforce on mutating /api/update/* requests
    needs_check = (
        request.method in ("POST", "PUT", "DELETE")
        and request.path.startswith("/api/update/")
    )
    if needs_check:
        cookie_tok = request.cookies.get(CSRF_COOKIE_NAME)
        header_tok = request.headers.get(CSRF_HEADER_NAME)
        if not cookie_tok or not header_tok:
            return web.json_response(
                {"error": "csrf_missing"}, status=422
            )
        # secrets.compare_digest to avoid timing side channel
        if not secrets.compare_digest(cookie_tok, header_tok):
            return web.json_response(
                {"error": "csrf_mismatch"}, status=422
            )

    response = await handler(request)

    # Seed cookie on any GET that lacks it (the SPA hits /api/devices on load)
    if CSRF_COOKIE_NAME not in request.cookies:
        response.set_cookie(
            CSRF_COOKIE_NAME,
            secrets.token_urlsafe(32),
            max_age=CSRF_COOKIE_MAX_AGE,
            path="/",
            samesite="Strict",
            httponly=False,  # JS must read it
            secure=False,    # LAN HTTP, not HTTPS
        )
    return response
```

**Wire in `webapp.py::create_webapp`:**
```python
app = web.Application(middlewares=[csrf_middleware])
```

### Pattern 2: Rate Limit — Sliding Window In-Memory Dict

**What:** Prevent rapid repeated Install attempts.

**Key:** `request.remote` (aiohttp's `TCP remote address` — single-user LAN, no X-Forwarded-For needed since no reverse proxy exists).

**Window:** 60s fixed from first attempt. Simpler than sliding and matches the requirement wording exactly.

**Data:** `dict[str, float]` mapping IP → last-attempt timestamp. Entries older than 60s are evicted lazily on lookup.

**Response:** HTTP 429 + `Retry-After: <seconds_until_window_closes>` header (integer, min 1).

**Verified Phase 45 state:** No rate limiter exists. `POST /api/update/start` currently has zero guards (webapp.py:406-408 explicitly notes "Phase 45 scope deliberately omits auth / CSRF / rate limiting — those ship in Phase 46"). `[VERIFIED: webapp.py:406]`

### Pattern 3: Concurrent Guard — Read update-status.json

**What:** Reject Install when an update is already in flight.

**The right primitive:** NOT a local asyncio.Lock. The ground truth for "update in progress" lives in `/etc/pv-inverter-proxy/update-status.json` (written by root updater) and is read by the existing `updater.status.load_status` reader. The webapp process CANNOT use an asyncio.Lock because it does not own the update — it only writes the trigger.

**Algorithm:**
```python
from pv_inverter_proxy.updater.status import load_status, current_phase

IDLE_PHASES = frozenset({"idle", "done", "rollback_done", "rollback_failed"})

def is_update_running() -> bool:
    status = load_status()
    return current_phase(status) not in IDLE_PHASES
```

**Why this is correct:** The updater writes the status file at every transition (verified in `updater_root/status_writer.py:112-130`). A second request arriving during `pip_install` reads the file and sees `pip_install`, rejects with 409. After the updater writes `done` and exits, the next request sees `done` and is accepted. No process-local state needed.

**Race window:** Between reading status=done and writing the new trigger, a parallel request could also see status=done. The rate limit (1 per 60s per IP) and single-user LAN make this academic, but for defense in depth add a process-local `asyncio.Lock` around the check+write sequence (acquired for the duration of one handler call, not held across the updater run).

### Pattern 4: Progress Broadcaster — Status File Watcher

**What:** Turn `update-status.json` phase transitions into WS `update_progress` messages.

**Approach: polling at 500ms while update is active.** The status file is written ~15 times per update run (once per phase). Polling is trivial.

**Lifecycle:**
1. `progress_broadcaster.start(app)` spawns an asyncio task in `create_webapp`.
2. Task reads status file every 500ms.
3. When `current.phase` or `len(history)` changes, compute the diff (new entries) and emit one `update_progress` WS message per new entry via `broadcast_progress(app, entry)`.
4. Also emit when `current` transitions from None → dict (update started) and dict → None (update ended, but note Phase 45 status_writer keeps current populated after done — see status_writer.py:77).
5. Task only polls at 500ms while `current is not None`; otherwise back off to 5s idle polling. This avoids wasted work when no update is running.

**Message shape** (new in Phase 46):
```json
{
  "type": "update_progress",
  "data": {
    "phase": "pip_install",
    "at": "2026-04-11T12:34:56Z",
    "nonce": "abc-1234",
    "target_sha": "a1b2c3d4...",
    "old_sha": "0f0e0d0c...",
    "error": null,
    "sequence": 4
  }
}
```

`sequence` is the index of the entry in `history[]`, letting the client dedupe and order messages across reconnect races.

### Pattern 5: Audit Log — JSONL Append via Single-Writer Queue

**What:** Append one line per update-related request to `/var/lib/pv-inverter-proxy/update-audit.log`.

**Format:** JSONL, one dict per line, for easy `jq` / `journalctl`-style analysis.

**Fields (SEC-04):**
```json
{"ts":"2026-04-11T12:34:56Z","remote":"192.168.3.17","user_agent":"Mozilla/5.0...","method":"POST","path":"/api/update/start","outcome":"accepted","update_id":"abc-1234","target_sha":"a1b2c3d4..."}
```

Outcomes: `accepted` | `409_conflict` | `429_rate_limited` | `422_csrf_missing` | `422_csrf_mismatch` | `400_bad_request` | `500_write_failed`.

**Directory:** `/var/lib/pv-inverter-proxy/` — **already exists** (created by install.sh for backup directory in SAFETY-07, verified in REQUIREMENTS.md:29). `install.sh` must be updated to create `update-audit.log` with mode 0640 owner `root:pv-proxy` (pv-proxy can append, root can read).

**Concurrency:** A single `asyncio.Lock` held around the append. `open('a')` is O_APPEND in POSIX which is atomic for writes ≤ PIPE_BUF (4KB); one JSONL line is well under that. But asyncio's cooperative scheduling + ordering guarantees mean a Lock is simpler and future-proof.

**Rotation:** **Out of scope for Phase 46** — Phase 47 HELPER-04/HELPER-06 adds systemd journal rate limit + structured logging; audit log rotation can be added there or via external logrotate. Phase 46 only writes; growth is bounded by rate limit (~1440 entries/day worst case).

### Pattern 6: Frontend State Machine

**States:** `idle | checking | available | confirming | starting | running | success | failed | rollback_running`

**Transitions:**
```
idle --[WS:available_update with data]--> available
idle --[Check now clicked]--> checking --[response]--> idle|available
available --[Install clicked]--> confirming
confirming --[Cancel/ESC]--> available
confirming --[Confirm]--> starting
starting --[POST 202]--> running
starting --[POST 409]--> idle  (+ show "already running")
starting --[POST 429]--> idle  (+ show Retry-After toast)
starting --[POST 422]--> idle  (+ reload page to refresh CSRF cookie)
running --[WS update_progress phase=done]--> success
running --[WS update_progress phase=rollback_*]--> rollback_running
rollback_running --[WS update_progress phase=rollback_done]--> success  (but show rollback toast)
rollback_running --[WS update_progress phase=rollback_failed]--> failed
running --[WS update_progress error != null]--> failed
running --[WS reconnect + /api/version mismatch]--> success  (+ location.reload())
success --[user clicks "Dismiss" or 30s elapse]--> idle
failed --[user clicks "Dismiss"]--> idle
```

**Button disable rule:** Any button with `data-update-guard="true"` is disabled when `state ∈ {starting, running, rollback_running}`. Buttons include:
- Install (software page)
- Check now (software page)
- Rollback (software page + any history entry row)
- Save (software config panel — CFG-02 editable fields)

A single `setUpdateState(newState)` function toggles `disabled` on all `[data-update-guard]` elements.

### Pattern 7: `/api/version` Reconnect Probe (UI-08)

**New endpoint:**
```python
async def version_handler(request: web.Request) -> web.Response:
    app_ctx = request.app["app_ctx"]
    return web.json_response({
        "version": app_ctx.current_version,
        "commit": app_ctx.current_commit,
    })
```

**Client probe:** On WebSocket `onopen` (i.e., every reconnect), fetch `/api/version`. If the response differs from the stored boot version (stored in a module-level variable after the first `/api/version` call or the initial `available_update` WS message), call `location.reload()`.

**Why this works:** The webapp restart during an update loads new code; `app_ctx.current_version` is populated from `importlib.metadata.version()` on startup (verified — see webapp.py:321-322 in `_derive_health_payload`). After a successful update + restart the value changes; the WS reconnect fires → probe → reload.

**Edge case:** If the user opens the page during an update, they may see a pre-update version initially. That's fine — the progress view takes over and the reload happens at the end.

### Anti-Patterns to Avoid

- **Don't** use `innerHTML` on any user-supplied string (release notes, audit log entries, version strings). Use `textContent` or the Markdown renderer's DOM node emission. XSS via release notes is the primary threat.
- **Don't** store the CSRF token in localStorage — the cookie is the canonical store. localStorage is vulnerable to same-origin XSS from any future bug in `app.js`.
- **Don't** add a session layer — double-submit cookie needs none, and sessions are a significant attack-surface increase for a LAN appliance.
- **Don't** poll `/api/update/status` from the client — use WS `update_progress`. A REST poll fallback (like the `/api/update/available` 2s fallback at app.js:3152) is fine on initial page load but not steady-state.
- **Don't** use `fetch('/api/...', {credentials: 'same-origin'})` — aiohttp + vanilla `fetch()` already sends cookies for same-origin. Setting `credentials` explicitly is cargo-cult.
- **Don't** grow `webapp.py` or `app.js` — delegate to new modules as described above.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown rendering | A "clever" regex-based sanitizer | Strict allow-list parser emitting DOM nodes via `document.createElement` + `textContent` | Regex-based Markdown sanitizers have a 20-year track record of XSS bypasses. The allow-list below is what OWASP calls "safe sink" emission. |
| CSRF token generation | `Math.random()` or timestamp-based | `secrets.token_urlsafe(32)` on the server | `secrets` is the Python stdlib CSPRNG; `token_urlsafe` encodes 32 random bytes as URL-safe base64. `[CITED: docs.python.org/3/library/secrets.html]` |
| Rate limit store | Custom time-bucket arithmetic | `dict[str, float]` of last-attempt timestamps + `time.monotonic()` | Simpler, easier to test, no off-by-one time-window bugs |
| Confirm dialog | Custom focus trap from scratch | Extend the existing `ve-modal-overlay` pattern (style.css:1513) + a ~30 LOC focus-trap helper that stores `document.activeElement`, queries all `[tabindex]`/`<button>`/`<input>` in the modal, and handles Tab/Shift+Tab/Escape | The modal CSS already exists; the trap is ~30 lines |
| Audit log append serialization | Lock-free dance with `O_APPEND` | `asyncio.Lock()` around `await loop.run_in_executor(None, _append_line, line)` | One write per ~10 seconds worst case; blocking I/O in a thread is fine |
| Release notes fetch | Separate GitHub API call from UI | Reuse `available_update.release_notes` already in `/api/update/available` response | `[VERIFIED: webapp.py:540]` — body is already fetched by Phase 44 scheduler |

**Key insight:** The biggest trap in this phase is Markdown. **Do not try to output HTML as a string.** The safe pattern:

```javascript
// software_markdown.js — allow-list DOM emitter
function renderMarkdown(source, targetEl) {
    targetEl.textContent = '';  // clear
    if (typeof source !== 'string') return;
    const lines = source.split('\n');
    let paragraph = null;
    for (const line of lines) {
        if (/^#\s+/.test(line)) {
            paragraph = null;
            const h = document.createElement('h3');
            h.className = 've-md-h1';
            h.textContent = line.replace(/^#\s+/, '');
            targetEl.appendChild(h);
        } else if (/^##\s+/.test(line)) {
            paragraph = null;
            const h = document.createElement('h4');
            h.className = 've-md-h2';
            h.textContent = line.replace(/^##\s+/, '');
            targetEl.appendChild(h);
        } else if (/^[-*]\s+/.test(line)) {
            // collect into <ul><li>
            let ul = targetEl.lastElementChild;
            if (!ul || ul.tagName !== 'UL') {
                ul = document.createElement('ul');
                ul.className = 've-md-list';
                targetEl.appendChild(ul);
            }
            const li = document.createElement('li');
            renderInline(line.replace(/^[-*]\s+/, ''), li);
            ul.appendChild(li);
        } else if (line.trim() === '') {
            paragraph = null;
        } else {
            if (!paragraph) {
                paragraph = document.createElement('p');
                paragraph.className = 've-md-p';
                targetEl.appendChild(paragraph);
            } else {
                paragraph.appendChild(document.createElement('br'));
            }
            renderInline(line, paragraph);
        }
    }
}

function renderInline(text, parent) {
    // Walk the string finding **bold**, *italic*, `code`
    // Emit text nodes and createElement('strong'/'em'/'code') — NEVER innerHTML
    // Links are OUT OF SCOPE for Phase 46 — too much XSS surface (javascript: URIs, data: URIs, etc.)
    // If the user wants the GitHub link, use the separate "View on GitHub" button that comes from available_update.html_url.
    const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
    let lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
        if (match.index > lastIndex) {
            parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
        }
        const token = match[0];
        let el;
        if (token.startsWith('**')) {
            el = document.createElement('strong');
            el.textContent = token.slice(2, -2);
        } else if (token.startsWith('`')) {
            el = document.createElement('code');
            el.textContent = token.slice(1, -1);
        } else {
            el = document.createElement('em');
            el.textContent = token.slice(1, -1);
        }
        parent.appendChild(el);
        lastIndex = pattern.lastIndex;
    }
    if (lastIndex < text.length) {
        parent.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
}
```

**Allow-list (explicit):** `# H1`, `## H2`, `- list item`, `* list item`, `**bold**`, `*italic*`, `` `code` ``, paragraphs, line breaks. **Not allowed (XSS surface):** links, images, raw HTML, blockquotes, code fences (multi-line), tables, footnotes, `[text](url)`. If release notes contain a URL, it's shown as literal text — the "View on GitHub" button is the vetted navigation path.

## Runtime State Inventory

Phase 46 is a **pure wiring** phase — no renames, no migrations, no config schema changes (CFG-01 lives in Phase 47). The only runtime state introduced is:

| Category | Items | Action Required |
|----------|-------|------------------|
| Stored data | None | None |
| Live service config | None | None |
| OS-registered state | `/var/lib/pv-inverter-proxy/update-audit.log` (new file, created lazily on first write; directory exists from SAFETY-07) | install.sh update to pre-create file at mode 0640 root:pv-proxy so the first write doesn't race with directory permissions |
| Secrets / env vars | `pvim_csrf` cookie (session-lived, per-browser, not a shared secret) | None |
| Build artifacts | None | None |

**In-memory state (new, process-local, cleared on restart):**
- Rate limit dict: `dict[str, float]` — max ~50 entries in a normal day, trivially bounded, clears on restart (which is fine per rate limit semantics).
- Audit-log write lock: `asyncio.Lock` — held for microseconds.
- Progress broadcaster last-known-sequence: `int` — for dedupe across status file polls.

Nothing persists beyond process lifetime except the audit log itself.

## Common Pitfalls

### Pitfall 1: CSRF Cookie Not Seeded on First Request
**What goes wrong:** User opens the webapp, clicks Install immediately. CSRF cookie wasn't set yet (middleware only sets on response). POST fails with 422 `csrf_missing`.
**Why it happens:** The cookie is set on the _response_ to the first GET. If the user's first action is a POST (page reload + instant click), there's a race.
**How to avoid:** Seed the cookie on _every_ GET request, not just "if missing". Also include a 2nd-chance path: on 422 missing-cookie response, the client reloads the page once (not on 422 mismatch, which indicates a real attack).
**Warning signs:** Test coverage gap — add integration test "POST before any GET → 422, reload → GET seeds cookie → POST succeeds".

### Pitfall 2: Rate Limit IP Parsing
**What goes wrong:** `request.remote` returns IPv6-mapped IPv4 (`::ffff:192.168.3.17`) in some network configurations, making the rate limit key unstable across requests.
**Why it happens:** aiohttp surfaces the socket peer address verbatim.
**How to avoid:** Normalize IPs before key lookup: strip `::ffff:` prefix, or use `ipaddress.ip_address(raw)` and store the canonical form.
**Warning signs:** A single client appearing to get through two requests in the 60s window.

### Pitfall 3: `update-audit.log` Not Writable
**What goes wrong:** install.sh creates `/var/lib/pv-inverter-proxy/backups/` (SAFETY-07) but not `update-audit.log`. First write fails with EACCES because the pv-proxy user doesn't own the file.
**Why it happens:** The backups directory is mode 2775 owned `root:pv-proxy`, but the audit log is a file in that parent — file creation inherits the process's umask, not parent ownership.
**How to avoid:** install.sh Step 6c creates the file upfront: `install -m 0640 -o pv-proxy -g pv-proxy /dev/null /var/lib/pv-inverter-proxy/update-audit.log`. Document in the plan as a pre-flight concern.
**Warning signs:** First POST after a clean install fails with "audit_log_write_failed" in journal.

### Pitfall 4: WebSocket Reconnect During Update — Lost Progress Events
**What goes wrong:** Client's WS disconnects during `restarting` phase (the main service is restarting). On reconnect, it missed the `healthcheck` and `done` phases. Progress view is frozen on `restarting`.
**Why it happens:** WS is volatile; the new service instance doesn't know the client existed.
**How to avoid:** On `ws.onopen` (both first connect and reconnect), the client fetches `/api/update/status` (new REST endpoint) which returns the full `history[]` from update-status.json, and replays missed phases into the progress view before resuming live WS updates. Separately: `sequence` field on `update_progress` messages lets the client detect gaps and trigger the replay.
**Warning signs:** UI stuck on an intermediate phase after a real restart.

### Pitfall 5: CSRF + Restart = Stale Cookie
**What goes wrong:** Main service restarts during update. Client's CSRF cookie is still valid (server-side there's no session, so cookie keeps working). User hits rollback immediately. Works — but only because we use double-submit. **This is not a bug, it's why double-submit was chosen.** Document in threat register so it's not re-interrogated.

### Pitfall 6: Concurrent Guard False Negative After `done`
**What goes wrong:** `update-status.json` keeps `current` populated after `done` (status_writer.py:77 — "current stays populated so the UI can show the last result"). Naive guard that checks `current is not None` blocks all future updates.
**Why it happens:** The status writer doesn't clear `current` on completion — it's a feature for the UI, not a bug.
**How to avoid:** Use `current_phase(status)` helper (updater.status.py:166) which returns the phase string, and gate on `phase in IDLE_PHASES = {"idle", "done", "rollback_done", "rollback_failed"}`.
**Warning signs:** Second update never accepted on a host that has successfully updated once.

### Pitfall 7: Focus Management in Modal
**What goes wrong:** Modal opens, Cancel has default focus per UI-04, but user presses Tab and focus escapes to background buttons.
**Why it happens:** Custom overlay divs don't have a native focus trap (native `<dialog>` does, but we're not using it).
**How to avoid:** On open: store `document.activeElement` as `previousFocus`. Query all focusable elements in the modal (`button, [tabindex]:not([tabindex="-1"]), input, select, textarea`). Bind Tab to cycle forward, Shift+Tab to cycle backward, Escape to close. On close: restore `previousFocus.focus()`.
**Warning signs:** Keyboard users report they can tab "behind" the modal.

### Pitfall 8: Minimal Markdown Edge Cases
**What goes wrong:** Release notes contain `**unclosed bold` or `` `backtick at end` ``. Regex-based tokenizer produces unexpected output.
**How to avoid:** The allow-list regex `(\*\*[^*]+\*\*|\*[^*]+\*|` \`[^`]+\` `)` requires _closed_ tokens; anything not matching falls through as literal text via `createTextNode`. Unit-test with crafted unclosed inputs.
**Warning signs:** Tests that paste real GitHub release bodies and assert no XSS sinks appear.

### Pitfall 9: `Retry-After` Wrong Format
**What goes wrong:** HTTP spec allows `Retry-After` as seconds OR HTTP-date. Clients interpret both. Inconsistency causes client-side bugs.
**How to avoid:** Always use integer seconds: `response.headers["Retry-After"] = str(max(1, int(seconds_remaining)))`. `[CITED: RFC 9110 §10.2.3]`

## Code Examples

### Atomic Trigger Write Pattern (already in Phase 45, reuse verbatim)
```python
# From src/pv_inverter_proxy/updater/trigger.py:148-196 — DO NOT reimplement
from pv_inverter_proxy.updater.trigger import (
    TriggerPayload, generate_nonce, now_iso_utc, write_trigger,
)

payload = TriggerPayload(
    op="update",
    target_sha=target_sha,
    requested_at=now_iso_utc(),
    requested_by="webapp",  # Phase 46: consider extending to "webapp:{source_ip}" for audit
    nonce=generate_nonce(),
)
write_trigger(payload)  # os.replace inside — atomic, <5ms
```

### Phase 45 Status File Reader (reuse)
```python
# Source: src/pv_inverter_proxy/updater/status.py:166
from pv_inverter_proxy.updater.status import (
    load_status, current_phase,
    PHASE_IDLE, PHASE_DONE,  # + 15 more
)

status = load_status()  # never raises
phase = current_phase(status)  # "idle" if no current
is_running = phase not in {"idle", "done", "rollback_done", "rollback_failed"}
```

### Existing Toast API (reuse)
```javascript
// Source: src/pv_inverter_proxy/static/app.js:3072
showToast(message, type, actionLabel, actionCallback, duration);
// type: 'success' | 'error' | 'warning' | 'info'
// Example with action button:
showToast('Update complete', 'success', 'View', function() { navigateTo('system', 'software'); }, 5000);
```

### Existing Dirty-Tracking Config Pattern (reuse for CFG-02)
```javascript
// Source: src/pv_inverter_proxy/static/app.js:1149-1320 (buildInverterConfigForm)
// Pattern:
// 1. Render panel with ve-panel-header + ve-btn-pair ve-cfg-save-pair (hidden)
// 2. Store originals dict
// 3. Query all inputs, bind 'input'/'change' → checkDirty
// 4. checkDirty: compare each input to originals, toggle ve-input--dirty + savePair visibility
// 5. Cancel: restore originals, call checkDirty
// 6. Save: POST, on success reset originals to new values, call checkDirty
```

### Existing Modal Overlay CSS (reuse for UI-04)
```css
/* Source: src/pv_inverter_proxy/static/style.css:1513-1547 */
.ve-modal-overlay { position: fixed; top: 0; ... background: rgba(0,0,0,0.65); ... z-index: 1000; }
.ve-modal { background: var(--ve-bg-surface); border-radius: 12px; max-width: 420px; }
.ve-modal-body { padding: 24px; font-size: 1rem; line-height: 1.6; }
.ve-modal-actions { display: flex; gap: 8px; justify-content: flex-end; padding: 0 24px 20px; }
```
**Add in Phase 46** (new CSS):
```css
.ve-modal-title { padding: 20px 24px 0; font-weight: 600; color: var(--ve-text); font-size: 1.1rem; }
.ve-modal-actions .ve-btn:focus-visible { outline: 2px solid var(--ve-blue); outline-offset: 2px; }
.ve-update-progress { list-style: none; padding: 0; margin: 16px 0; }
.ve-update-progress li { padding: 8px 12px; border-left: 3px solid var(--ve-border); color: var(--ve-text-dim); transition: color var(--ve-duration-normal) var(--ve-easing-default); }
.ve-update-progress li.ve-progress--active { border-left-color: var(--ve-blue); color: var(--ve-text); font-weight: 500; }
.ve-update-progress li.ve-progress--done { border-left-color: var(--ve-green); color: var(--ve-text-dim); text-decoration: line-through; }
.ve-update-progress li.ve-progress--failed { border-left-color: var(--ve-red); color: var(--ve-red); }
```

### Existing WebSocket Broadcast Helper Pattern (reuse for `update_progress`)
```python
# Source: src/pv_inverter_proxy/webapp.py:1288-1315 (broadcast_available_update)
async def broadcast_update_progress(app: web.Application, entry: dict) -> None:
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({"type": "update_progress", "data": entry})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)
```

## State of the Art

| Old Approach (2019-2022) | Current Approach (2024+) | Impact |
|--------------------------|---------------------------|--------|
| CSRF via synchronizer tokens + session cookies | Double-submit cookie with `SameSite=Strict` | OWASP now accepts double-submit for same-origin; `SameSite=Strict` blocks cross-site POSTs at the browser level, eliminating most CSRF attack classes without a session layer. `[ASSUMED]` based on training; should be verified against current OWASP CSRF cheat sheet |
| Rate limit via Redis + Lua scripts | In-memory dict for single-instance appliances | Simpler, no infra; Redis becomes relevant only for multi-replica deployments |
| Custom WebSocket reconnect libraries (socket.io, SockJS) | Plain `new WebSocket()` with exponential backoff in 8 LOC | Already the pattern in app.js:427-481; no lib needed |
| Markdown rendering via marked.js / markdown-it | Allow-list DOM emitter for ~30 Markdown features | Zero-dep, no XSS surface, forces you to explicitly audit supported syntax |
| CSS-in-JS + React for admin UIs | Vanilla JS + design tokens (CSS custom properties) | Zero build step, instant reload, matches CLAUDE.md zero-dep constraint |

**Deprecated/obsolete for this phase:**
- Native `<dialog>` element — inconsistent styling support means the existing `ve-modal-overlay` pattern is the pragmatic choice for Venus OS browsers. `[ASSUMED]` for Venus OS browser baseline.
- Synchronous `XMLHttpRequest` — never; use `fetch()`.
- `document.write` or `innerHTML = unsafe_string` — XSS.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Double-submit cookie + SameSite=Strict satisfies SEC-01 for a single-user LAN appliance | § B | Medium — if the user lives on a network with other trusted devices, CSRF from a compromised peer is unaddressed. Mitigation: discuss-phase confirms LAN threat model |
| A2 | Rollback "bounded window" is 1 hour from a successful update | § I (UI-07) | HIGH — this is a product decision, not a technical one. REQUIREMENTS.md:150 says "Rollback nach mehr als 1 Stunde" is out of scope; that wording implies ≤1h window is in scope. Needs user confirmation |
| A3 | Update history for "rollback from history entry" comes from `update-status.json` `history[]` (not a separate history file) | § I (UI-07) | HIGH — HIST-01 (dedicated `update-history.json`) is Phase 47. Phase 46 either derives history from status file (single completed update only) or adds a mini history now. Needs planner decision |
| A4 | CFG-02 editable update fields come from Phase 47's config schema read lazily | § J | HIGH — CFG-01 (the YAML schema) is Phase 47. Phase 46 has no fields to edit unless CFG-01 is promoted to Phase 46. Three options: (a) move CFG-01 from Phase 47 to Phase 46 prereq, (b) scope CFG-02 to "panel exists but empty" until Phase 47, (c) defer CFG-02 entirely to Phase 47. Planner must pick |
| A5 | Venus OS browser is Chromium-based with WebSocket + `secrets` API + `URLSearchParams` support | § H, § G | LOW — Venus OS gui-v2 is Qt WebEngine (Chromium); all APIs are present |
| A6 | `/var/lib/pv-inverter-proxy/` directory exists at install time (created by Phase 43 install.sh) | § D, Runtime State | LOW — verified by REQUIREMENTS.md:29 SAFETY-07 |
| A7 | Phase 45 status file `current` keeps populated after `done` per status_writer.py:77 docstring | § C.3 | LOW — verified by reading status_writer.py directly |
| A8 | Minimal Markdown subset (H1/H2/bold/italic/code/list) is enough for typical GitHub release notes | § G | MEDIUM — if releases contain code fences or tables, output is degraded but not broken. Degradation is acceptable; discuss-phase can widen allow-list if pushback |
| A9 | `request.remote` returns a usable IPv4 string on the LXC's bridged network | § C.2, Pitfall 2 | LOW — verified aiohttp behavior; normalize with `ipaddress.ip_address()` as defense in depth |
| A10 | `install.sh` is the right place to pre-create `update-audit.log` | § D, Pitfall 3 | LOW — matches the existing Phase 43 SAFETY-07 pattern for backups directory |
| A11 | A 500ms poll of `update-status.json` is an acceptable load during an active update | § F | LOW — update runs for ~30s, so ~60 reads of a <1KB file. Trivial. |
| A12 | Phase 46 does NOT need to rotate the audit log | Pattern 5 | LOW — Phase 47 adds systemd rate limiting; logrotate is a deploy concern |

## Open Questions

1. **Rollback window duration (UI-07)** — 1 hour? Until next update check? Until page reload? **Recommendation:** default to 1 hour from `current.started_at + duration` to match REQUIREMENTS.md's "Rollback nach mehr als 1 Stunde" out-of-scope wording. Surfaces in discuss-phase.

2. **CFG-02 source fields without CFG-01** — Is CFG-01 promoted to a Phase 46 prerequisite, or is CFG-02 scoped to "panel skeleton, fields populated from Phase 47"? **Recommendation:** promote just enough of CFG-01 — specifically `update.github_repo`, `update.check_interval_hours`, `update.auto_install` — into Phase 46 as a 20-line config dataclass, so the webapp has real fields to edit. This is cheap and resolves the sequencing gap. The hot-reload piece (CFG-03) stays in Phase 47.

3. **Rollback from history entry** — HIST-01 (dedicated history file) is Phase 47. In Phase 46, "from any history entry" must mean "from the last successful update's record in `update-status.json`" (which holds at most one N-1 rollback candidate). **Recommendation:** Phase 46 rollback button operates on `target_sha="previous"` only (the Phase 45 rollback sentinel, trigger.py:67); history browsing ships in Phase 47.

4. **Audit log permissions** — mode 0640 root:pv-proxy means `pv-proxy` group can read but only owner writes. Since the webapp runs as `pv-proxy`, we actually need the webapp to _write_. Correct mode: **`0640 pv-proxy:pv-proxy`** (owner write, group read). Updater root can read everything so no root:write needed here.

5. **Does `/api/update/status` return only `current` or also the full `history[]` array?** **Recommendation:** return the full UpdateStatus (current + history + schema_version) — client uses history for replay after WS reconnect, and the response is <10KB.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| aiohttp | All HTTP + WS + middleware | ✓ | >=3.10,<4.0 `[VERIFIED: pyproject.toml:7]` | — |
| Python `secrets` stdlib | CSRF token generation | ✓ | 3.11+ (project floor) | — |
| Python `ipaddress` stdlib | Rate limit key normalization | ✓ | 3.11+ | — |
| asyncio.Lock | Audit log writer | ✓ | stdlib | — |
| pytest + pytest-asyncio | Test suite | ✓ | >=8.0 / >=0.23 `[VERIFIED: pyproject.toml:19-21]` | — |
| Node.js / jsdom | Frontend Markdown unit tests | ✗ | — | Python-side string-based tests OR end-to-end Playwright. **Recommendation:** Python-side helper that runs the JS renderer via a tiny `re.sub` translation matrix for tests OR accept that frontend markdown is tested manually at deploy time |
| Browser automation | E2E verification on LXC | ✗ (not in project) | — | Manual human-verify checklist, as Phase 44 does (per STATE.md:30 "pending human visual verification") |

**Missing dependencies with no fallback:** None blocking.

**Missing dependencies with fallback:** Frontend JS unit testing — accept manual verification for Markdown renderer correctness. Phase 46 plan should include a short checklist of real-world release-notes strings (a typical v8.0.0 release body) that the human tester pastes into a devtools console to verify output.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio `[VERIFIED: pyproject.toml:19-21]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| Quick run command | `pytest tests/test_updater_webapp_security.py tests/test_updater_progress_broadcaster.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | CSRF middleware rejects POST without cookie | unit | `pytest tests/test_updater_webapp_security.py::test_csrf_missing_returns_422 -x` | ❌ Wave 0 |
| SEC-01 | CSRF middleware rejects POST with mismatched cookie/header | unit | `pytest tests/test_updater_webapp_security.py::test_csrf_mismatch_returns_422 -x` | ❌ Wave 0 |
| SEC-01 | CSRF cookie seeded on first GET | unit | `pytest tests/test_updater_webapp_security.py::test_csrf_cookie_seeded_on_get -x` | ❌ Wave 0 |
| SEC-01 | CSRF uses secrets.compare_digest (timing-safe) | unit | `pytest tests/test_updater_webapp_security.py::test_csrf_timing_safe_compare -x` | ❌ Wave 0 |
| SEC-02 | Second POST within 60s → 429 + Retry-After | unit | `pytest tests/test_updater_webapp_security.py::test_rate_limit_second_attempt_429 -x` | ❌ Wave 0 |
| SEC-02 | After 60s window, POST is accepted | unit (with monkeypatched clock) | `pytest tests/test_updater_webapp_security.py::test_rate_limit_window_resets -x` | ❌ Wave 0 |
| SEC-02 | Retry-After header is integer seconds (RFC 9110) | unit | `pytest tests/test_updater_webapp_security.py::test_rate_limit_retry_after_format -x` | ❌ Wave 0 |
| SEC-03 | Concurrent update → 409 Conflict | unit (mock load_status) | `pytest tests/test_updater_webapp_security.py::test_concurrent_update_returns_409 -x` | ❌ Wave 0 |
| SEC-03 | Update in `done` phase does not block new update | unit | `pytest tests/test_updater_webapp_security.py::test_done_phase_allows_new_update -x` | ❌ Wave 0 |
| SEC-04 | Every request writes an audit line | unit (tmp_path) | `pytest tests/test_updater_webapp_security.py::test_audit_log_appends_jsonl -x` | ❌ Wave 0 |
| SEC-04 | 409/429/422 rejections also logged | unit | `pytest tests/test_updater_webapp_security.py::test_audit_log_rejected_requests -x` | ❌ Wave 0 |
| SEC-04 | Audit log is concurrency-safe | async unit (10 parallel writes) | `pytest tests/test_updater_webapp_security.py::test_audit_log_concurrent_safe -x` | ❌ Wave 0 |
| UI-01 | Sidebar renders SYSTEM > Software entry | manual | (human-verify, document in plan) | n/a |
| UI-02 | `/api/update/available` returns version+commit+last_check (already shipped Phase 44) | unit (existing) | `pytest tests/test_updater_webapp_routes.py -k available -x` | ✅ exists |
| UI-02 | Check-now endpoint calls scheduler.check_once() | unit | `pytest tests/test_updater_webapp_routes.py::test_check_now_triggers_scheduler -x` | ❌ Wave 0 |
| UI-03 | Markdown renderer produces allow-listed DOM only | manual + smoke | paste real release notes into devtools at deploy time | n/a |
| UI-04 | Confirmation modal focus starts on Cancel | manual | (human-verify) | n/a |
| UI-05 | Progress broadcaster emits WS message on phase change | async unit (monkeypatch load_status) | `pytest tests/test_updater_progress_broadcaster.py::test_phase_change_broadcasts -x` | ❌ Wave 0 |
| UI-05 | Broadcaster emits each history entry exactly once | async unit | `pytest tests/test_updater_progress_broadcaster.py::test_dedup_via_sequence -x` | ❌ Wave 0 |
| UI-05 | Broadcaster handles status file missing gracefully | async unit | `pytest tests/test_updater_progress_broadcaster.py::test_missing_status_file -x` | ❌ Wave 0 |
| UI-06 | Success/failure toast appears (reuses existing showToast) | manual | (human-verify) | n/a |
| UI-07 | Rollback button POSTs to /api/update/rollback with target_sha="previous" | integration | `pytest tests/test_updater_webapp_routes.py::test_rollback_writes_sentinel_trigger -x` | ❌ Wave 0 |
| UI-08 | `/api/version` returns version+commit | unit | `pytest tests/test_updater_webapp_routes.py::test_version_endpoint -x` | ❌ Wave 0 |
| UI-09 | State machine disable rule (client-side) | manual | (human-verify in devtools) | n/a |
| CFG-02 | PATCH /api/config/update accepts valid fields + rejects invalid | unit | `pytest tests/test_updater_webapp_routes.py::test_update_config_patch -x` | ❌ Wave 0 |
| EXEC-01 (regression) | /api/update/start still writes trigger < 100ms | unit (existing) | `pytest tests/test_updater_start_endpoint.py -x` | ✅ exists |

### Sampling Rate
- **Per task commit:** `pytest tests/test_updater_webapp_security.py tests/test_updater_progress_broadcaster.py tests/test_updater_webapp_routes.py -x -q` (fast, targeted)
- **Per wave merge:** `pytest tests/ -x -q` (full suite — currently ~57 files, expected runtime <30s based on existing suite shape)
- **Phase gate:** Full suite green + manual human-verify checklist on LXC 192.168.3.191 (modal behavior, toast stacking, progress checklist rendering, Markdown output for real release notes, rollback round-trip with deliberately broken release from the v8.0 Release Gate items in 45-VERIFICATION.md:196)

### Wave 0 Gaps

- [ ] `tests/test_updater_webapp_security.py` — new file; covers SEC-01..04 (CSRF, rate limit, concurrent guard, audit log)
- [ ] `tests/test_updater_progress_broadcaster.py` — new file; covers UI-05 progress broadcaster
- [ ] `tests/test_updater_webapp_routes.py` — EXTEND (file already exists per `ls tests/`); add tests for /api/version, /api/update/rollback, /api/update/status, /api/update/check-now, /api/config/update
- [ ] `tests/conftest.py` — may need a shared `csrf_client` fixture that sets up an aiohttp test client with CSRF cookies pre-seeded, so Phase 46 tests don't each repeat the handshake
- [ ] Human-verify checklist document at `.planning/phases/46-ui-wiring-end-to-end-flow/46-HUMAN-VERIFY.md` — manual UI steps (modal focus, Markdown output, rollback round-trip, toast stacking, stale-tab reload after update)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | NO (out of scope — LAN appliance, no auth in v8.0; noted in 45-02 T-45-02-02 accepted risk) | — |
| V3 Session Management | NO (stateless double-submit cookie, no sessions) | CSRF cookie with `SameSite=Strict` |
| V4 Access Control | NO | — |
| V5 Input Validation | YES | JSON schema checks in `update_start_handler` (already present, Phase 45); new PATCH /api/config/update needs allow-listed key validation |
| V6 Cryptography | YES | `secrets.token_urlsafe(32)` for CSRF; `secrets.compare_digest` for constant-time comparison |
| V7 Error Handling | YES | No stack traces in error responses; structured audit log with outcomes |
| V9 Communication | Partial | HTTPS not enforced (LAN appliance); `SameSite=Strict` + `Path=/` compensates for cookie protection |
| V11 Business Logic | YES | Rate limit (1/60s) + concurrent guard enforce sequential update business flow |
| V12 Files & Resources | YES | Audit log permissions (0640 pv-proxy:pv-proxy), status file read-only in webapp process |
| V13 API / Web Services | YES | CSRF on all POST, CORS not needed (same-origin), rate limit, concurrent guard |
| V14 Configuration | YES | CFG-02 config editing — validate allow-listed keys, reject unknown |

### Known Threat Patterns for aiohttp + vanilla JS LAN appliance

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| CSRF from browser tab open to hostile site | Tampering (T) | Double-submit cookie with `SameSite=Strict` header (SEC-01) |
| XSS via release notes injected HTML | Tampering (T) + EoP (E) | Allow-list DOM-emitter Markdown renderer; no `innerHTML` of untrusted strings |
| DoS by hammering Install button | Denial of Service (D) | Rate limit 1/60s per IP (SEC-02) + concurrent guard 409 (SEC-03) |
| Race: two Install clicks during slow network | Tampering (T) | Client-side state machine disables buttons on `starting` state; server-side 409 as backstop |
| Log injection into audit log | Tampering (T) | JSONL format forces quoting; `json.dumps` escapes newlines in user-agent/remote strings |
| Trigger file forgery by local non-root user | EoP (E) | SEC-07 from Phase 45: `/etc/pv-inverter-proxy/update-trigger.json` is mode 0664 root:pv-proxy; only pv-proxy (main service) + root can write. Unaffected by Phase 46. |
| Repudiation — "I didn't press Install" | Repudiation (R) | Audit log (SEC-04) records source IP, user-agent, timestamp, nonce for every attempt |
| Info disclosure via audit log readable by unprivileged user | Info Disclosure (I) | File mode 0640 pv-proxy:pv-proxy — only the service user and root can read |
| Timing attack on CSRF token comparison | Info Disclosure (I) | `secrets.compare_digest` is constant-time `[CITED: docs.python.org/3/library/secrets.html]` |
| Stale UI attack — user acts on pre-update state | Tampering (T) | `/api/version` reconnect probe + forced reload (UI-08) |
| Reflected XSS via error messages | Tampering (T) | All error responses use `web.json_response` which sets `Content-Type: application/json`; no HTML reflection path |
| Cookie theft via same-origin script | Info Disclosure (I) | Cookie is `HttpOnly=False` (JS must read it for header echo). Accepted risk — the SPA is the only JS origin; any XSS in the SPA already owns the session. |

**Threats DEFERRED to Phase 47 or beyond:**
- Helper not-responding banner (HELPER-02) — out of Phase 46 scope
- GPG signature enforcement (SEC-05 flip from optional to required) — Phase 47+
- Multi-user auth — v8.1 or later

**Accepted risks (with rationale, to be re-stated in plan threat register):**
- No authentication on the LAN — product decision from v8.0 kickoff (STATE.md:60-61)
- `HttpOnly=False` CSRF cookie — required for double-submit pattern; SPA is the only JS origin
- In-memory rate limit clears on restart — single-instance appliance, restart is rare

## Sources

### Primary (HIGH confidence — codebase verified)
- `src/pv_inverter_proxy/webapp.py:194-556,881-1316,2347-2391` — existing handlers, WS handler, broadcast helpers, route table, existing `update_start_handler` `[VERIFIED]`
- `src/pv_inverter_proxy/updater/trigger.py:1-196` — atomic trigger writer, reused verbatim `[VERIFIED]`
- `src/pv_inverter_proxy/updater/status.py:1-179` — status reader with `load_status()` and `current_phase()` `[VERIFIED]`
- `src/pv_inverter_proxy/updater/maintenance.py:1-139` — maintenance mode entry/drain `[VERIFIED]`
- `src/pv_inverter_proxy/updater_root/status_writer.py:35-180` — 17-phase PHASES frozenset, status file mode 0644 `[VERIFIED]`
- `src/pv_inverter_proxy/updater_root/runner.py:290-498` — which phases are written and in what order `[VERIFIED]`
- `src/pv_inverter_proxy/static/app.js:36,130-240,427-481,1149-1320,3072-3120` — existing state, sidebar rendering, WS handler, dirty-tracking pattern, toast API `[VERIFIED]`
- `src/pv_inverter_proxy/static/style.css:1513-1547,1612-1688` — existing modal overlay and toast CSS `[VERIFIED]`
- `src/pv_inverter_proxy/static/index.html:1-81` — sidebar container structure, existing #software-related markup `[VERIFIED]`
- `src/pv_inverter_proxy/context.py:71-78` — app_ctx.current_version, current_commit, maintenance_mode, ws_clients `[VERIFIED]`
- `src/pv_inverter_proxy/__main__.py:511-537` — scheduler wiring pattern for a Check-now handler `[VERIFIED]`
- `pyproject.toml:5-21` — dependency versions, pytest config `[VERIFIED]`
- `.planning/REQUIREMENTS.md:79-98,115-119` — UI/SEC/CFG requirement texts and traceability `[VERIFIED]`
- `.planning/STATE.md:28-92` — Phase 45 decisions + accepted risk register `[VERIFIED]`
- `.planning/phases/45-privileged-updater-service/45-VERIFICATION.md:69,180-224` — Phase 45 RESTART-03 confirmation + Phase 46 open items + v8.0 release gate `[VERIFIED]`
- `.planning/phases/45-privileged-updater-service/45-02-trigger-status-contracts-PLAN.md:326,360,568` — Phase 45 explicit handoff comments for Phase 46 `[VERIFIED]`
- `.planning/phases/45-privileged-updater-service/45-05-SUMMARY.md:239-263` — Phase 46 TODO list from Phase 45 closing `[VERIFIED]`
- `CLAUDE.md` (project + codex repo) — design tokens, conventions, zero-dep constraint `[VERIFIED]`

### Secondary (MEDIUM confidence — training knowledge + RFC references)
- RFC 9110 §10.2.3 — `Retry-After` header format `[CITED: datatracker.ietf.org/doc/html/rfc9110#section-10.2.3]`
- OWASP CSRF Prevention Cheat Sheet — double-submit cookie pattern `[CITED: cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html]` `[ASSUMED]` wording unchanged since 2024 training cutoff
- MDN Web Docs — `SameSite` cookie attribute semantics `[CITED: developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite]`
- Python stdlib `secrets` module — `token_urlsafe`, `compare_digest` `[CITED: docs.python.org/3/library/secrets.html]`
- aiohttp middleware documentation `[CITED: docs.aiohttp.org/en/stable/web_advanced.html#middlewares]`

### Tertiary (LOW confidence — flagged for human confirmation)
- Venus OS gui-v2 browser capabilities (Chromium + Qt WebEngine, WebSocket support, CSS custom properties, native `<dialog>` non-use) `[ASSUMED]`
- Current OWASP CSRF cheat sheet wording on double-submit acceptability for LAN appliances `[ASSUMED]`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps, everything verified in codebase
- Architecture: HIGH — patterns are all Phase 45 reuse or well-known web idioms
- Pitfalls: HIGH — derived from specific file/line audits of existing code
- Security (ASVS mapping): MEDIUM — classification is sound; exact OWASP wording for double-submit acceptability is `[ASSUMED]`
- Product decisions (rollback window, CFG-02 sequencing, history source): LOW — flagged as Open Questions and in Assumptions Log

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (30 days — aiohttp and stdlib APIs are stable; the only volatile piece is the OWASP CSRF cheat-sheet wording which is also stable)

## Project Constraints (from CLAUDE.md)

Directives extracted from `/Users/hulki/codex/pv-inverter-proxy/CLAUDE.md` that the planner must honor:

1. **Zero-dep frontend** — no npm, no build tooling. Vanilla JS only.
2. **Design tokens** — all colors via `var(--ve-*)`, no hardcoded hex except `#fff`/`#000` for high-contrast knobs. Durations via `var(--ve-duration-*)` and `var(--ve-easing-*)`.
3. **`ve-` class prefix** — all new classes namespaced `ve-software-*`, `ve-update-*`, `ve-md-*`.
4. **Spacing scale** — only `4, 8, 10, 12, 14, 16, 24, 32, 48` px.
5. **Border radius** — `4-6px` for buttons/inputs, `12px` for cards/panels, `50%` for dots/toggles.
6. **Typography** — card title 1rem/600, body 0.9rem/400, label 0.85rem/400.
7. **Config editing rule** — all update-related config must be editable via webapp, never YAML-only (CFG-02 ↔ `feedback_webapp_config`).
8. **UI consistency** — reuse `ve-panel`, `ve-btn-pair`, `ve-cfg-*` patterns; don't invent new conventions.
9. **Auto-deploy** — after code changes, deploy to LXC 192.168.3.191 (`feedback_auto_deploy`).
10. **Python asyncio + aiohttp backend, structlog, dataclasses for config** — no new deps.
11. **GSD workflow** — all file edits must go through a GSD command; research → plan → execute pipeline is mandatory.
12. **Design system known debt** — Phase 46 should NOT rename existing inconsistent classes (`sidebar`, `nav-item`, legacy names). Only new classes take the `ve-` prefix.
13. **Inline `style="display:none"`** — existing debt; new code should prefer a CSS class for initial-hidden state (e.g., `.ve-hidden`).
