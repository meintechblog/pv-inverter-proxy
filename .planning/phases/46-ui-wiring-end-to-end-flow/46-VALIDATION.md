---
phase: 46
slug: ui-wiring-end-to-end-flow
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-11
updated: 2026-04-11
---

# Phase 46 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `46-RESEARCH.md` Validation Architecture section.
> Updated 2026-04-11 with real task IDs from the 5 plans.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` (pytest section) |
| **Quick run command** | `pytest tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_webapp_routes.py tests/test_updater_config.py -x -q` |
| **Full suite command** | `pytest -x -q` |
| **Estimated runtime** | ~30 seconds for Phase 46 slice; <60s full suite |

---

## Sampling Rate

- **After every task commit:** Run the quick Phase 46 slice above
- **After every plan wave:** Run `pytest -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 46-01 Task 1 | 01 | 1 | SEC-01..04 | T-46-01..04,08 | Wave 0 test scaffold for security module | meta | `pytest tests/test_updater_security.py --collect-only` | ❌ W0 | ⬜ pending |
| 46-01 Task 2 | 01 | 1 | SEC-01 | T-46-01 | CSRF double-submit + compare_digest | unit | `pytest tests/test_updater_security.py -k csrf -x` | ❌ W0 | ⬜ pending |
| 46-01 Task 2 | 01 | 1 | SEC-02 | T-46-03 | Rate limit 60s/IP + integer Retry-After | unit | `pytest tests/test_updater_security.py -k rate_limit -x` | ❌ W0 | ⬜ pending |
| 46-01 Task 2 | 01 | 1 | SEC-03 | T-46-02 | Concurrent guard reads status file | unit | `pytest tests/test_updater_security.py -k concurrent_guard -x` | ❌ W0 | ⬜ pending |
| 46-01 Task 2 | 01 | 1 | SEC-04 | T-46-04,08 | JSONL audit log, 0o750 dir + 0o640 file, concurrency-safe | unit | `pytest tests/test_updater_security.py -k audit_log -x` | ❌ W0 | ⬜ pending |
| 46-02 Task 1 | 02 | 1 | UI-02 | — | Wave 0 test scaffold for progress broadcaster | meta | `pytest tests/test_updater_progress.py --collect-only` | ❌ W0 | ⬜ pending |
| 46-02 Task 2 | 02 | 1 | UI-02 | — | 500ms active poll, 5s idle, dedupe via sequence | unit | `pytest tests/test_updater_progress.py -x` | ❌ W0 | ⬜ pending |
| 46-03 Task 1 | 03 | 2 | UI-03 | T-46-06 | Markdown allow-list DOM emitter, no innerHTML | static | `grep -q createElement software_markdown.js && ! grep -qE "innerHTML\|outerHTML\|document.write" software_markdown.js` | ❌ W0 | ⬜ pending |
| 46-03 Task 2 | 03 | 2 | UI-04..09 | T-46-07 | State machine, modal, progress checklist, rollback, /api/version probe | static+smoke | `grep -q "showModal\|ROLLBACK_WINDOW_MS = 3600000\|lastSequenceSeen" software_page.js` | ❌ W0 | ⬜ pending |
| 46-03 Task 3 | 03 | 2 | UI-01 | — | Sidebar entry + script tags in index.html | static | `grep -q software_page.js index.html && grep -q "#system/software" index.html` | ❌ W0 | ⬜ pending |
| 46-03 Task 4 | 03 | 2 | UI-01..09 | — | ve-update-*, ve-dialog, ve-md-* CSS with design tokens only | static | `grep -q ve-update-busy style.css && no hex colors in new block` | ❌ W0 | ⬜ pending |
| 46-04 Task 1 | 04 | 2 | UI-02,07,08 + SEC-01..04 | T-46-01..05,07 | Wave 0 test scaffold for routes + <100ms regression | meta | `pytest tests/test_updater_webapp_routes.py --collect-only` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | UI-02 | — | Progress broadcaster started via on_startup | integration | `pytest tests/test_updater_webapp_routes.py::test_progress_broadcaster_started_on_app_startup` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | UI-08 | T-46-07 | GET /api/version returns version+commit | integration | `pytest tests/test_updater_webapp_routes.py::test_version_endpoint_returns_version_and_commit` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | UI-02 | — | GET /api/update/status returns current+history | integration | `pytest tests/test_updater_webapp_routes.py::test_update_status_endpoint_returns_current_and_history` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | UI-02 | — | POST /api/update/check triggers scheduler | integration | `pytest tests/test_updater_webapp_routes.py::test_update_check_endpoint_calls_scheduler_check_once` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | — (D-20) | — | /api/update/start returns 202 in <100ms | integration | `pytest tests/test_updater_webapp_routes.py::test_update_start_returns_202_under_100ms` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | — (D-21) | T-46-05 | /api/update/start writes trigger file atomically | integration | `pytest tests/test_updater_webapp_routes.py::test_update_start_writes_trigger_file_atomically` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | SEC-01 | T-46-01 | /api/update/start without CSRF -> 422 | integration | `pytest tests/test_updater_webapp_routes.py::test_update_start_without_csrf_cookie_returns_422` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | SEC-02 | T-46-03 | 2nd /api/update/start within 60s -> 429 + Retry-After | integration | `pytest tests/test_updater_webapp_routes.py::test_update_start_second_attempt_within_60s_returns_429` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | SEC-03 | T-46-02 | /api/update/start during active update -> 409 | integration | `pytest tests/test_updater_webapp_routes.py::test_update_start_when_phase_running_returns_409` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | SEC-04 | T-46-04 | All 4 outcomes audit-logged | integration | `pytest tests/test_updater_webapp_routes.py -k audit_log_` | ❌ W0 | ⬜ pending |
| 46-04 Task 2 | 04 | 2 | UI-07 | — | /api/update/rollback writes target_sha='previous' sentinel | integration | `pytest tests/test_updater_webapp_routes.py::test_update_rollback_writes_previous_sentinel_trigger` | ❌ W0 | ⬜ pending |
| 46-05 Task 1 | 05 | 3 | CFG-02 | — | UpdateConfig 3-field dataclass + validate | unit | `pytest tests/test_updater_config.py -x` | ❌ W0 | ⬜ pending |
| 46-05 Task 2 | 05 | 3 | CFG-02 | — | GET/PATCH /api/update/config + frontend dirty-tracking | integration | `pytest tests/test_updater_webapp_routes.py -k update_config_ -x` | ❌ W0 | ⬜ pending |
| 46-05 Task 3 | 05 | 3 | — (D-42) | — | Full suite green + LXC deploy smoke | e2e | `pytest -x -q && curl -sf http://192.168.3.191:8080/api/version` | n/a | ⬜ pending |
| 46-05 Task 4 | 05 | 3 | UI-01..09 + CFG-02 | — | Human end-to-end on LXC | manual | 15-step checklist in 46-HUMAN-VERIFY.md | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_updater_security.py` — NEW file; covers SEC-01..04 with 25 test functions (Plan 46-01 Task 1)
- [ ] `tests/test_updater_progress.py` — NEW file; covers UI-02 progress broadcaster with 15 test functions (Plan 46-02 Task 1)
- [ ] `tests/test_updater_webapp_routes.py` — EXTEND existing file; adds ~31 new test cases for /api/version, /api/update/{rollback,status,check,config}, CSRF wiring, rate limiting, audit log (Plans 46-04 Task 1 + 46-05 Task 2)
- [ ] `tests/test_updater_config.py` — NEW file; 15 tests for UpdateConfig dataclass + validate (Plan 46-05 Task 1)
- [ ] Verify pytest-asyncio already installed (Phase 45 dependency; if not, Wave 0 adds it to pyproject.toml)

No shared conftest fixture needed — each test file uses tmp_path + monkeypatch for isolation per the existing tests/ convention.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Modal focus + ESC | UI-04 | Browser accessibility behavior, not unit-testable | Plan 46-05 Task 4 step 7 |
| Toast stacking v2.1 | UI-06 | Visual layering + timing behavior | Plan 46-05 Task 4 step 4 |
| Progress checklist render | UI-02, UI-05 | Visual state of 17-phase checklist | Plan 46-05 Task 4 step 8 |
| Design system conformance | — | CSS token usage in devtools inspector | Plan 46-05 Task 4 general |
| Dirty-tracking Save/Cancel | CFG-02 | Visual border + button appearance | Plan 46-05 Task 4 step 4 |
| LXC auto-deploy | D-42 | Deploy pipeline | Plan 46-05 Task 3 |
| Rollback 1h window | UI-07 | Time-bound UI state | Plan 46-05 Task 4 step 15 |
| CSRF cookie SameSite=Strict | SEC-01 | Cookie attribute inspection in devtools | Plan 46-05 Task 4 step 5 |
| /api/version reload | UI-08 | Post-update browser tab reload | Plan 46-05 Task 4 step 10 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (last task is the human-verify checkpoint — gate:blocking)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every TDD task runs its file's test suite)
- [x] Wave 0 covers all MISSING references (4 new test files + 1 extended file)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (quick slice runs 4 files in ~10-15s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner — 2026-04-11
