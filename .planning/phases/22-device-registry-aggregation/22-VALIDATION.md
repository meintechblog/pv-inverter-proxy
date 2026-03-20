---
phase: 22
slug: device-registry-aggregation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run python -m pytest tests/ -x -q` |
| **Full suite command** | `uv run python -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run python -m pytest tests/ -x -q`
- **After every plan wave:** Run `uv run python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | REG-01, REG-02, REG-03 | unit | `uv run python -m pytest tests/test_device_registry.py -x -q` | ❌ W0 | ⬜ pending |
| 22-02-01 | 02 | 2 | AGG-01, AGG-02, AGG-03, AGG-04 | unit | `uv run python -m pytest tests/test_aggregation.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_device_registry.py` — stubs for REG-01..03 (lifecycle, cleanup, task management)
- [ ] `tests/test_aggregation.py` — stubs for AGG-01..04 (summation, scale factors, partial failure, custom name)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Venus OS sees aggregated inverter | AGG-02 | Requires Venus OS + Modbus | Deploy to LXC, verify Venus OS shows combined power |
| Modbus server stops when 0 inverters | REG-03 | Port binding behavior | Disable all inverters, verify port 502 is closed |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
