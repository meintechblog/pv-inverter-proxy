---
phase: 29
slug: switch-control-config-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/test_shelly_plugin.py tests/test_webapp.py -x` |
| **Full suite command** | `python -m pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_shelly_plugin.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 29-01-01 | 01 | 1 | CTRL-01 | unit | `pytest tests/test_shelly_plugin.py::TestSwitchControl -x` | ❌ W0 | ⬜ pending |
| 29-01-02 | 01 | 1 | CTRL-01 | integration | `pytest tests/test_webapp.py::TestShellySwitchRoute -x` | ❌ W0 | ⬜ pending |
| 29-01-03 | 01 | 1 | CTRL-02 | unit | `pytest tests/test_shelly_plugin.py::TestRegisterEncoding::test_status_mppt_when_relay_on -x` | ✅ Phase 28 | ⬜ pending |
| 29-01-04 | 01 | 1 | CTRL-03 | unit | `pytest tests/test_shelly_plugin.py::TestWritePowerLimit -x` | ✅ Phase 28 | ⬜ pending |
| 29-01-05 | 01 | 1 | CTRL-03 | unit | `pytest tests/test_webapp.py::TestShellyThrottleDefault -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_shelly_plugin.py::TestSwitchControl` — CTRL-01 unit tests for ShellyPlugin.switch()
- [ ] `tests/test_webapp.py::TestShellySwitchRoute` — CTRL-01 integration test for switch route
- [ ] `tests/test_webapp.py::TestShellyThrottleDefault` — CTRL-03 throttle_enabled default test

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Shelly relay toggle | CTRL-01 | Requires physical hardware | Send POST to /api/devices/{id}/shelly/switch, verify relay clicks |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
