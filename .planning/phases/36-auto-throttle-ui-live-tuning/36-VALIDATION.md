---
phase: 36
slug: auto-throttle-ui-live-tuning
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio (backend), manual browser (frontend) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_distributor.py tests/test_throttle_caps.py -x` |
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
| 36-01-01 | 01 | 1 | THRT-10, THRT-12 | unit | `python -m pytest tests/test_distributor.py -x -k preset` | Extend existing | ⬜ pending |
| 36-02-01 | 02 | 2 | THRT-10, THRT-11 | manual+grep | `grep -c "auto-throttle" src/pv_inverter_proxy/static/index.html` | New HTML | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `tests/test_distributor.py` — add preset parameter tests

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Auto-Throttle toggle in virtual dashboard | THRT-10 | DOM/UI interaction | Open webapp, navigate to virtual PV, toggle Auto-Throttle |
| Connection card shows throttle info | THRT-11 | Visual verification | Check each device card for score, mode, response time |
| Contribution bar throttle states | THRT-11 | Visual color verification | Verify segment colors match active/throttled/disabled/cooldown |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
