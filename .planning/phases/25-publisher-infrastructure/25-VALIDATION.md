---
phase: 25
slug: publisher-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 1 | CONN-01, PUB-03, PUB-05 | unit | `pytest tests/test_mqtt_publisher.py -x` | ❌ W0 | ⬜ pending |
| 25-01-02 | 01 | 1 | CONN-02 | unit | `pytest tests/test_mqtt_publisher.py::test_reconnect -x` | ❌ W0 | ⬜ pending |
| 25-02-01 | 02 | 1 | CONN-03 | unit | `pytest tests/test_mdns_discovery.py -x` | ❌ W0 | ⬜ pending |
| 25-02-02 | 02 | 1 | CONN-04 | integration | `pytest tests/test_mqtt_publisher.py::test_hot_reload -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_mqtt_publisher.py` — stubs for CONN-01, CONN-02, PUB-03, PUB-05
- [ ] `tests/test_mdns_discovery.py` — stubs for CONN-03

*Existing test infrastructure (pytest, conftest.py) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LWT delivered on crash | PUB-05 | Requires killing process + checking broker | `kill -9 <pid>`, verify "offline" on `pvproxy/status` topic |
| mDNS finds real broker | CONN-03 | Requires LAN broker with Avahi | Run `POST /api/mqtt/discover`, verify broker in response |
| Hot-reload on live system | CONN-04 | Requires running service + config change | Edit config.yaml, verify publisher reconnects to new broker |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
