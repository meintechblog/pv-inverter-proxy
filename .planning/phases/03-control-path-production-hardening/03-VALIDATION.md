---
phase: 03
slug: control-path-production-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 03 — Validation Strategy

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
| TBD | TBD | TBD | CTRL-01, CTRL-02 | unit | `python -m pytest tests/test_control.py -v` | TBD | pending |
| TBD | TBD | TBD | CTRL-03 | unit | `python -m pytest tests/test_control.py -v -k validation` | TBD | pending |
| TBD | TBD | TBD | DEPL-02, DEPL-03 | unit | `python -m pytest tests/test_reconnection.py -v` | TBD | pending |
| TBD | TBD | TBD | DEPL-04 | unit | `python -m pytest tests/test_logging.py -v` | TBD | pending |
| TBD | TBD | TBD | DEPL-01 | integration | manual systemd verification | TBD | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_control.py` — tests for Model 123 write interception, validation, SE30K forwarding
- [ ] `tests/test_reconnection.py` — tests for exponential backoff, night mode state machine, reconnection
- [ ] `tests/test_logging.py` — tests for structured JSON log output, component tags, health heartbeat
- [ ] `tests/conftest.py` — extend shared fixtures with mock SE30K write responses

*Existing infrastructure: pytest configured, 101 tests passing from Phase 2.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| systemd service auto-starts on boot | DEPL-01 | Requires live LXC with systemd | 1. Install service on LXC. 2. Reboot. 3. Check `systemctl status venus-os-fronius-proxy`. |
| Power limit actually reduces SE30K output | CTRL-01 | Requires live SE30K + Venus OS | 1. Start proxy. 2. Set power limit in Venus OS. 3. Verify SE30K reduces output. |
| Graceful shutdown removes limit | DEPL-01 | Requires live SE30K | 1. Set limit. 2. `systemctl stop`. 3. Verify SE30K at full power. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
