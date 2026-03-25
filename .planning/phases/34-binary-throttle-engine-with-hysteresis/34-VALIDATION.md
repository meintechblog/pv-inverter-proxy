---
phase: 34
slug: binary-throttle-engine-with-hysteresis
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 34 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_distributor.py -x` |
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
| 34-01-01 | 01 | 1 | THRT-04 | unit | `python -m pytest tests/test_distributor.py -x -k binary` | Extend existing | ⬜ pending |
| 34-01-02 | 01 | 1 | THRT-05 | unit | `python -m pytest tests/test_distributor.py -x -k cooldown` | Extend existing | ⬜ pending |
| 34-01-03 | 01 | 1 | THRT-06 | unit | `python -m pytest tests/test_distributor.py -x -k "startup or reenable"` | Extend existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `tests/test_distributor.py` — add binary device helper (`_build_distributor_with_binary`) with mock plugins having `throttle_capabilities` and `switch()` method
- [ ] Add test cases for: binary dispatch, cooldown enforcement, startup grace, reverse re-enable, disable path with binary devices

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
