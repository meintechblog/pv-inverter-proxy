---
phase: 28
slug: plugin-core-profiles
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/test_shelly_plugin.py -x` |
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
| 28-01-01 | 01 | 1 | PLUG-01 | unit | `pytest tests/test_shelly_plugin.py::TestABCCompliance -x` | ❌ W0 | ⬜ pending |
| 28-01-02 | 01 | 1 | PLUG-02 | unit | `pytest tests/test_shelly_plugin.py::TestProfiles -x` | ❌ W0 | ⬜ pending |
| 28-01-03 | 01 | 1 | PLUG-03 | unit | `pytest tests/test_shelly_plugin.py::TestAutoDetection -x` | ❌ W0 | ⬜ pending |
| 28-01-04 | 01 | 1 | PLUG-04 | unit | `pytest tests/test_shelly_plugin.py::TestPollSuccess -x` | ❌ W0 | ⬜ pending |
| 28-01-05 | 01 | 1 | PLUG-05 | unit | `pytest tests/test_shelly_plugin.py::TestRegisterEncoding -x` | ❌ W0 | ⬜ pending |
| 28-01-06 | 01 | 1 | PLUG-06 | unit | `pytest tests/test_shelly_plugin.py::TestEnergyTracking -x` | ❌ W0 | ⬜ pending |
| 28-01-07 | 01 | 1 | PLUG-07 | unit | `pytest tests/test_shelly_plugin.py::TestMissingFields -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_shelly_plugin.py` — stubs for PLUG-01 through PLUG-07 (~300 LOC)
- [ ] Mock fixtures: reuse `_mock_session` pattern from `test_opendtu_plugin.py`
- [ ] Sample JSON responses for Gen1 `/status` and Gen2 `/rpc/Switch.GetStatus?id=0`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Shelly device poll | PLUG-04 | Requires physical hardware | Connect to Shelly device on LAN, verify poll returns non-zero values |
| Energy counter reset survival | PLUG-06 | Requires device reboot | Reboot Shelly device, verify energy total does not decrease |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
