---
phase: 30
slug: add-device-flow-discovery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/test_shelly_discovery.py -x` |
| **Full suite command** | `python -m pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_shelly_discovery.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 30-01-01 | 01 | 1 | UI-01 | manual | N/A — visual check in browser | N/A | ⬜ pending |
| 30-01-02 | 01 | 1 | UI-02 | unit | `pytest tests/test_shelly_discovery.py::TestProbeHandler -x` | ❌ W0 | ⬜ pending |
| 30-01-03 | 01 | 1 | UI-05 | manual | N/A — visual check in browser | N/A | ⬜ pending |
| 30-01-04 | 01 | 1 | UI-06 | unit | `pytest tests/test_shelly_discovery.py::TestShellyDiscovery -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_shelly_discovery.py` — covers UI-02 (probe handler) and UI-06 (mDNS discovery)
- [ ] Mock fixtures: reuse `test_mdns_discovery.py` patterns (AsyncZeroconf mock, fake browser)
- [ ] Mock Shelly `/shelly` HTTP responses for probe tests (Gen1 and Gen2 JSON fixtures)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Shelly type card in add-device dialog | UI-01 | Visual DOM check | Open add-device modal, verify third "Shelly Device" card appears |
| Shelly config page fields | UI-05 | Visual DOM check | Navigate to Shelly device config, verify Host/Gen/Rated Power fields |
| mDNS discovery on real LAN | UI-06 | Requires physical Shelly device | Click Discover with Shelly selected, verify device appears |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
