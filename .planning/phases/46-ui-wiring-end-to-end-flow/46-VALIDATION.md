---
phase: 46
slug: ui-wiring-end-to-end-flow
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-11
---

# Phase 46 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `46-RESEARCH.md` Validation Architecture section.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (pytest section) |
| **Quick run command** | `pytest tests/updater/ tests/webapp/ -x -q` |
| **Full suite command** | `pytest -x` |
| **Estimated runtime** | ~30 seconds for Phase 46 slice |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/updater/ tests/webapp/ -x -q`
- **After every plan wave:** Run `pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Populated by the planner. Each task with code output must map to at least one automated check. See `46-RESEARCH.md` §Validation Architecture for the detailed map of 21 automated tests.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 46-01-XX | 01 | 1 | SEC-01 | T-46-01 | CSRF rejects missing/mismatched token | unit | `pytest tests/updater/test_security.py::test_csrf_rejects_missing` | ❌ W0 | ⬜ pending |
| 46-01-XX | 01 | 1 | SEC-02 | T-46-02 | Concurrent update → 409 | unit | `pytest tests/updater/test_security.py::test_concurrent_returns_409` | ❌ W0 | ⬜ pending |
| 46-01-XX | 01 | 1 | SEC-03 | T-46-03 | 2nd request within 60s → 429 + Retry-After | unit | `pytest tests/updater/test_security.py::test_rate_limit_60s_window` | ❌ W0 | ⬜ pending |
| 46-01-XX | 01 | 1 | SEC-04 | T-46-04 | Audit log appends JSONL per outcome | unit | `pytest tests/updater/test_security.py::test_audit_log_all_outcomes` | ❌ W0 | ⬜ pending |
| 46-02-XX | 02 | 2 | UI-02 | — | Progress broadcaster dedupes via sequence | unit | `pytest tests/updater/test_progress.py::test_dedupe_by_sequence` | ❌ W0 | ⬜ pending |
| 46-02-XX | 02 | 2 | UI-02 | — | 500ms poll stops when idle | unit | `pytest tests/updater/test_progress.py::test_poller_stops_on_idle` | ❌ W0 | ⬜ pending |
| 46-03-XX | 03 | 2 | UI-01 | — | Markdown rejects raw HTML | unit | `pytest tests/webapp/test_markdown.py::test_rejects_raw_html` (Python port) OR `node tests/webapp/markdown.test.js` | ❌ W0 | ⬜ pending |
| 46-03-XX | 03 | 2 | UI-01 | — | Markdown emits DOM-safe output | unit | same | ❌ W0 | ⬜ pending |
| 46-04-XX | 04 | 3 | — | — | `/api/update/start` returns 202 < 100ms | integration | `pytest tests/webapp/test_update_api.py::test_start_latency_under_100ms` | ❌ W0 | ⬜ pending |
| 46-04-XX | 04 | 3 | — | — | Trigger file atomically written after 202 | integration | `pytest tests/webapp/test_update_api.py::test_trigger_file_atomic_write` | ❌ W0 | ⬜ pending |
| 46-04-XX | 04 | 3 | — | — | `/api/version` returns current version+commit | integration | `pytest tests/webapp/test_update_api.py::test_version_endpoint` | ❌ W0 | ⬜ pending |
| 46-04-XX | 04 | 3 | UI-08 | — | Rollback endpoint calls updater with `target_sha="previous"` | integration | `pytest tests/webapp/test_update_api.py::test_rollback_previous_sentinel` | ❌ W0 | ⬜ pending |
| 46-05-XX | 05 | 3 | CFG-02 | — | `PATCH /api/update/config` updates the 3 fields | integration | `pytest tests/webapp/test_config_api.py::test_patch_update_config` | ❌ W0 | ⬜ pending |
| 46-05-XX | 05 | 3 | CFG-02 | — | Invalid config values → 422 | integration | `pytest tests/webapp/test_config_api.py::test_invalid_config_422` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> **Planner note:** Replace generic `46-01-XX` task IDs with the actual task IDs as plans are authored. Every task producing code output must link to a concrete test here.

---

## Wave 0 Requirements

- [ ] `tests/updater/test_security.py` — CSRF, rate limit, audit log, concurrent guard tests (stubs for SEC-01..SEC-04)
- [ ] `tests/updater/test_progress.py` — status file poller + dedupe tests (stubs for UI-02)
- [ ] `tests/webapp/test_markdown.py` — Markdown sanitizer tests (stubs for UI-01). If the Markdown module is pure JS, add a Python port OR a Node-based test runner — planner decides.
- [ ] `tests/webapp/test_update_api.py` — end-to-end API tests for `/api/update/start`, `/api/version`, `/api/update/rollback`, `/api/update/status` (stubs for UI-02..UI-08, SEC-01..SEC-04)
- [ ] `tests/webapp/test_config_api.py` — config PATCH/GET tests (stubs for CFG-02)
- [ ] `tests/conftest.py` — shared fixtures: temp status file factory, temp audit log path, aiohttp test client, fake trigger file dir
- [ ] Verify `pytest-asyncio` is already installed (Phase 45 should have added it; if not, Wave 0 adds it to `pyproject.toml`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Modal focus + ESC | UI-04 | Browser accessibility behavior, not unit-testable | Open `#system/software` on LXC, click Install, verify Cancel has focus, press ESC, verify dialog closes |
| Toast stacking v2.1 | UI-06 | Visual layering + timing behavior | Trigger success + failure toasts rapidly, verify they stack per existing v2.1 pattern |
| Progress checklist render | UI-02 | Visual state of 17-phase checklist | Trigger actual update on LXC staging, watch all phase transitions visually |
| Design system conformance | — | CSS token usage | Inspect new `ve-update-*` classes in devtools, confirm all colors resolve to `var(--ve-*)` |
| Dirty-tracking Save/Cancel | CFG-02 | Visual border + button appearance | Edit a config field, verify green border + Save/Cancel appears, click Cancel, verify revert |
| LXC auto-deploy | — | Deploy pipeline | After all plans pass, verify `192.168.3.191` shows new build |
| Rollback 1h window | UI-07 | Time-bound UI state | Simulate successful update, verify rollback button visible, wait (or mock `Date.now`) past 1h, verify hidden |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter after plans are finalized

**Approval:** pending
