---
phase: 35
slug: smart-auto-throttle-algorithm
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_distributor.py -x -k auto` |
| **Full suite command** | `python -m pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_distributor.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 35-01-01 | 01 | 1 | THRT-07 | unit | `python -m pytest tests/test_distributor.py -x -k auto_throttle` | Extend existing | ⬜ pending |
| 35-01-02 | 01 | 1 | THRT-08 | unit | `python -m pytest tests/test_distributor.py -x -k "proportional_before_binary"` | Extend existing | ⬜ pending |
| 35-01-03 | 01 | 1 | THRT-09 | unit | `python -m pytest tests/test_distributor.py -x -k convergence` | Extend existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `tests/test_distributor.py` — add auto-throttle test helpers with mock plugins having varied throttle_scores
- [ ] Add test cases for: auto ordering, proportional-before-binary, convergence measurement, effective score update

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
