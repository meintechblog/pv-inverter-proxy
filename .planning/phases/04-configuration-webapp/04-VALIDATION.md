---
phase: 04
slug: configuration-webapp
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (already configured) |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v --timeout=30`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

*Task IDs will be filled after planning. Template rows for expected coverage:*

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | WEB-01 | unit | `python -m pytest tests/test_webapp.py -v` | TBD | pending |
| TBD | TBD | TBD | WEB-02 | unit | `python -m pytest tests/test_webapp.py -v -k config` | TBD | pending |
| TBD | TBD | TBD | WEB-03, WEB-04 | unit | `python -m pytest tests/test_webapp.py -v -k status` | TBD | pending |
| TBD | TBD | TBD | WEB-05 | unit | `python -m pytest tests/test_webapp.py -v -k register` | TBD | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_webapp.py` — tests for aiohttp API endpoints (config GET/PUT, status, registers)
- [ ] `tests/conftest.py` — extend with aiohttp test client fixtures

*Existing infrastructure: pytest configured, 153 tests passing from Phase 3.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Webapp accessible in browser | WEB-01 | Requires browser on LAN | 1. Open http://192.168.3.191:80 in browser. 2. Verify page loads with dark theme. |
| Register viewer shows live data | WEB-05 | Requires live SE30K + browser | 1. Open webapp during daytime. 2. Verify registers update every 2s. 3. Check flash animation on change. |
| Config save + hot-reload works | WEB-02 | Requires live environment | 1. Change SE IP in webapp. 2. Verify proxy reconnects to new address. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
