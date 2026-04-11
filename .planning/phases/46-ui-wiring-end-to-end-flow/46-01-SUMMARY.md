---
phase: 46-ui-wiring-end-to-end-flow
plan: 01
subsystem: updater/security
tags: [security, csrf, rate-limit, audit-log, concurrent-guard, sec-01, sec-02, sec-03, sec-04]
requires:
  - pv_inverter_proxy.updater.status.load_status
  - pv_inverter_proxy.updater.status.current_phase
  - aiohttp.web middleware protocol
  - stdlib: secrets, asyncio, json, os, time, datetime
provides:
  - pv_inverter_proxy.updater.security.csrf_middleware
  - pv_inverter_proxy.updater.security.RateLimiter
  - pv_inverter_proxy.updater.security.is_update_running
  - pv_inverter_proxy.updater.security.audit_log_append
  - pv_inverter_proxy.updater.security.IDLE_PHASES
  - pv_inverter_proxy.updater.security.CSRF_COOKIE_NAME
  - pv_inverter_proxy.updater.security.CSRF_HEADER_NAME
  - pv_inverter_proxy.updater.security.AUDIT_LOG_PATH
affects: []
tech_stack:
  added: []
  patterns:
    - "Double-submit cookie CSRF with secrets.compare_digest"
    - "Sliding-window in-memory rate limit keyed on normalized IP"
    - "File-as-source-of-truth concurrent guard (not asyncio.Lock)"
    - "asyncio.Lock + run_in_executor for serialized JSONL appends"
    - "Lazy filesystem setup (mkdir + chmod on first write)"
key_files:
  created:
    - src/pv_inverter_proxy/updater/security.py
    - tests/test_updater_security.py
  modified: []
decisions:
  - "D-07..D-09: CSRF = double-submit cookie with SameSite=Strict and timing-safe compare"
  - "D-10/D-11: Concurrent guard reads update-status.json via load_status/current_phase (not asyncio.Lock)"
  - "D-12..D-14: Rate limit = in-memory dict keyed on request.remote, 60s sliding window, integer Retry-After"
  - "D-15..D-19: JSONL audit log at /var/lib/pv-inverter-proxy/update-audit.log with lazy 0o750 dir / 0o640 file"
  - "D-40: New module lives at pv_inverter_proxy/updater/security.py with zero webapp.py coupling"
requirements: [SEC-01, SEC-02, SEC-03, SEC-04]
threat_refs: [T-46-01, T-46-02, T-46-03, T-46-04, T-46-08]
metrics:
  tasks_total: 2
  tasks_completed: 2
  files_created: 2
  tests_added: 25
  completed_at: 2026-04-11
---

# Phase 46 Plan 01: Security Belt Summary

**One-liner:** Standalone `updater/security.py` primitive library delivering CSRF double-submit middleware, per-IP sliding rate limiter, status-file-driven concurrent-update guard, and serialized JSONL audit log — all zero-dep stdlib + aiohttp, with 25 hermetic tests exercising every acceptance criterion.

## What Was Built

A single self-contained module (`src/pv_inverter_proxy/updater/security.py`, 424 LOC) exposing four primitives plus supporting constants:

### SEC-01 — CSRF Middleware (`csrf_middleware`)
- aiohttp `@web.middleware` that gates `POST/PUT/PATCH/DELETE /api/update/*`
- Missing cookie or header → `422 csrf_missing`
- Mismatched cookie vs header → `422 csrf_mismatch` (via `secrets.compare_digest`, timing-safe)
- Lazy cookie seeding on every request that lacks `pvim_csrf`, using `secrets.token_urlsafe(32)`
- Cookie attributes: `SameSite=Strict`, `Path=/`, `Max-Age=86400`, `HttpOnly=False`, `Secure=False`
- Seeding also happens on the `422 csrf_missing` rejection response so a reload+retry succeeds (Pitfall 1 mitigation)

### SEC-03 — `RateLimiter`
- In-memory `dict[str, float]` keyed on normalized source IP
- Sliding 60-second window, injectable clock for hermetic tests
- Returns `(accepted: bool, retry_after_seconds: int)`
- Retry-After is always `int` ≥ 1 when rejected (RFC 9110 §10.2.3, Pitfall 9)
- Lazy eviction of stale entries on each `check()` (memory-bounded)
- `_normalize_ip()` helper strips `::ffff:` IPv4-mapped prefix (Pitfall 2)

### SEC-02 — `is_update_running`
- Reads `update-status.json` via `updater.status.load_status` + `current_phase`
- Returns `(running, phase_string)`; `running = phase not in IDLE_PHASES`
- `IDLE_PHASES = frozenset({"idle", "done", "rollback_done", "rollback_failed"})`
- **Critical:** file is the source of truth, not `asyncio.Lock` — survives webapp restart during update (D-11, Pitfall 6)
- Fails open on status-load errors (consistent with Phase 45 NonceDedupStore pattern)

### SEC-04 — `audit_log_append`
- Async function writing one JSON line per call to `/var/lib/pv-inverter-proxy/update-audit.log`
- Schema: `{ts: ISO8601Z, ip, ua, outcome}` where outcome ∈ `{accepted, 409_conflict, 429_rate_limited, 422_invalid_csrf}`
- Module-level `asyncio.Lock` + `run_in_executor` serialize 10 concurrent writes without interleaving
- Lazy parent `mkdir(mode=0o750)` + explicit `chmod(parent, 0o750)` on first write
- Lazy file `chmod(0o640)` on creation; existing files keep their mode so ops hardening isn't reverted
- `PermissionError` on chmod is swallowed (best-effort for CI/test environments)

### Test Coverage — `tests/test_updater_security.py` (25 tests, 456 LOC)
| Section | Tests | Notes |
|---------|-------|-------|
| SEC-01 CSRF | 8 | aiohttp `TestClient` + `TestServer`, dummy POST/GET handlers |
| SEC-03 Rate Limit | 5 | Pure sync, `FakeClock` for deterministic time advance |
| SEC-02 Concurrent Guard | 6 | `monkeypatch.setattr` on `load_status` to drive phases |
| SEC-04 Audit Log | 6 | `tmp_path` fixture redirects `AUDIT_LOG_PATH`, concurrent `asyncio.gather` test |

All tests hermetic — zero access to `/etc/pv-inverter-proxy/` or `/var/lib/pv-inverter-proxy/`.

## Tasks & Commits

| Task | Type | Commit | Files |
|------|------|--------|-------|
| 1. Wave 0 test scaffold (RED) | test | `72ad536` | `tests/test_updater_security.py`, plan copy |
| 2. Implement `updater/security.py` (GREEN) | feat | `814bccb` | `src/pv_inverter_proxy/updater/security.py` |

## Verification Results

```
$ PYTHONPATH=src pytest tests/test_updater_security.py -x -q
.........................                                                [100%]
25 passed in 0.19s

$ python -c "from pv_inverter_proxy.updater.security import \
    csrf_middleware, RateLimiter, is_update_running, audit_log_append, \
    IDLE_PHASES, CSRF_COOKIE_NAME, AUDIT_LOG_PATH"
all exports OK

$ grep -n 'from pv_inverter_proxy.webapp\|import.*webapp' \
    src/pv_inverter_proxy/updater/security.py
(no matches — zero webapp coupling)
```

### Acceptance Criteria Matrix

| Criterion | Status |
|-----------|--------|
| `CSRF_COOKIE_NAME = "pvim_csrf"` literal | PASS |
| `CSRF_HEADER_NAME = "X-CSRF-Token"` literal | PASS |
| `IDLE_PHASES` frozenset defined | PASS |
| `secrets.compare_digest` used for CSRF | PASS |
| `samesite="Strict"` on cookie | PASS |
| `token_urlsafe(32)` for cookie seeding | PASS |
| `RATE_LIMIT_WINDOW_SECONDS = 60` | PASS |
| `0o640` / `0o750` file/dir modes | PASS |
| `/var/lib/pv-inverter-proxy/update-audit.log` path literal | PASS |
| `from pv_inverter_proxy.updater.status import load_status, current_phase` | PASS |
| `asyncio.Lock` present (for audit serialization only) | PASS |
| No `asyncio.Lock` as source-of-truth for guard (D-11) | PASS |
| No `webapp` imports | PASS |
| 25/25 unit tests green | PASS |
| Runtime contract smoke test | PASS |

## Threat Model Coverage

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-46-01 (CSRF tampering) | `csrf_middleware` + `compare_digest` + `SameSite=Strict` | Mitigated |
| T-46-02 (concurrent DoS) | `is_update_running` reads status file | Mitigated |
| T-46-03 (rate-limit DoS) | `RateLimiter` 60s sliding window per IP | Mitigated |
| T-46-04 (repudiation) | `audit_log_append` on every outcome | Mitigated |
| T-46-08 (audit log info disclosure) | Lazy mkdir `0o750` + file `0o640` | Mitigated |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Plan file copy from main repo**
- **Found during:** Task 1 startup
- **Issue:** `46-01-security-belt-PLAN.md` did not yet exist in this worktree; it was present only in the main repo at `/Users/hulki/codex/pv-inverter-proxy/.planning/phases/46-ui-wiring-end-to-end-flow/`.
- **Fix:** Copied the plan into the worktree alongside `46-CONTEXT.md`/`46-RESEARCH.md` so downstream tooling can reference it from this branch.
- **Files modified:** `.planning/phases/46-ui-wiring-end-to-end-flow/46-01-security-belt-PLAN.md` (new)
- **Commit:** `72ad536`

**2. [Rule 3 — Blocking] Worktree branch base mismatch**
- **Found during:** `<worktree_branch_check>` step
- **Issue:** `git merge-base HEAD 7986de61` returned `67e9625…`, meaning the worktree branch was rooted on an older commit that predates phases 43/44/45/46 docs. `git reset --soft` to `7986de61` left the working tree in a stale state.
- **Fix:** After the soft reset, ran `git checkout HEAD -- .` to restore the working tree to match the target base (all Phase 43/44/45 source + `46-CONTEXT.md`/`46-RESEARCH.md`/`46-VALIDATION.md`). Worktree now tracks `7986de61` cleanly.
- **Commit:** N/A (pre-task plumbing)

### Test Acceptance Regex (Documentation-Only)

The plan's grep acceptance `grep -c "^def test_" tests/test_updater_security.py >= 25` is literal — it does not match `async def test_`. My 25 tests mix sync (11) and async (14), so that literal regex returns 11. I kept the structural split (sync rate-limit/guard tests, async CSRF/audit-log tests) because it produces clearer, faster tests and matches the project's `asyncio_mode = auto` pyproject setting. The **intent** — 25 runnable test functions — is fully satisfied, verified by `grep -cE "^(async )?def test_"` which returns `25`, and the exact test-name acceptance greps all pass. This is a plan-regex defect, not an implementation deviation; the module behavior is unchanged.

### Python Version Note

The worktree's `.venv` resolves to the main repo's editable install, so tests were run with `PYTHONPATH=<worktree>/src` to force resolution against the worktree's new `security.py`. The test count (25), assertion results, and contract smoke test all execute against the worktree copy of the module. Plan 46-04 (which wires this into `webapp.py`) will exercise it through the normal installed path.

## Auth Gates

None — no external authentication was required for this plan.

## Known Stubs

None. The module is complete; Plan 46-04 is responsible for wiring (explicit out-of-scope per D-40 and plan `<action>` step 8).

## Self-Check: PASSED

- `src/pv_inverter_proxy/updater/security.py` — FOUND
- `tests/test_updater_security.py` — FOUND
- Commit `72ad536` — FOUND
- Commit `814bccb` — FOUND
- All 25 tests green — VERIFIED
- No webapp.py coupling — VERIFIED
- `IDLE_PHASES` exact contents `{idle, done, rollback_done, rollback_failed}` — VERIFIED
- `from pv_inverter_proxy.updater.status import current_phase, load_status` present — VERIFIED
- `AUDIT_LOG_PATH = Path("/var/lib/pv-inverter-proxy/update-audit.log")` — VERIFIED
