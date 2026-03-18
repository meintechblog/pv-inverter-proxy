---
phase: 02
slug: core-proxy-read-path
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (already in pyproject.toml) |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | ARCH-01, ARCH-02 | unit | `python -m pytest tests/test_plugin.py -v` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | PROXY-06, PROXY-07 | unit | `python -m pytest tests/test_poller.py -v` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | PROXY-01, PROXY-05, PROXY-08 | unit | `python -m pytest tests/test_server.py -v` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | PROXY-02, PROXY-03, PROXY-04 | unit | `python -m pytest tests/test_translation.py -v` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | PROXY-09 | integration | `python -m pytest tests/test_integration.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_plugin.py` — stubs for ARCH-01, ARCH-02 (plugin interface)
- [ ] `tests/test_poller.py` — stubs for PROXY-06, PROXY-07 (polling and cache)
- [ ] `tests/test_server.py` — stubs for PROXY-01, PROXY-05, PROXY-08 (Modbus server, model chain, scale factors)
- [ ] `tests/test_translation.py` — stubs for PROXY-02, PROXY-03, PROXY-04 (register translation)
- [ ] `tests/test_integration.py` — stubs for PROXY-09 (end-to-end discovery)
- [ ] `tests/conftest.py` — shared fixtures (mock SE30K registers, test cache)

*Existing infrastructure: pytest already configured, 27 register mapping tests passing.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Venus OS discovers proxy as Fronius | PROXY-09 | Requires live Venus OS instance | 1. Start proxy on LXC. 2. Add device in Venus OS at 192.168.3.191:502. 3. Verify "Fronius" appears in device list. |
| Live power data displays correctly | PROXY-03 | Requires live SE30K + Venus OS | 1. Run proxy during daytime. 2. Check Venus OS shows non-zero power. 3. Compare with SE30K direct readings. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
