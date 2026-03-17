---
phase: 1
slug: protocol-research-validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (standard for Python projects) |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | PROTO-01 | manual-only | N/A (documentation deliverable) | N/A | ⬜ pending |
| 01-02-01 | 02 | 1 | PROTO-02 | integration | `python3 scripts/validate_se30k.py` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | PROTO-03 | unit | `pytest tests/test_register_mapping.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/validate_se30k.py` — live register validation script (PROTO-02)
- [ ] `tests/test_register_mapping.py` — translation table unit tests (PROTO-03)
- [ ] `pyproject.toml` — test framework config + pymodbus dependency
- [ ] `requirements.txt` — pymodbus dependency for validation scripts

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| dbus-fronius discovery expectations documented | PROTO-01 | Documentation deliverable — no code to test | Review 01-RESEARCH.md Section "dbus-fronius Discovery Mechanism" for completeness |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
