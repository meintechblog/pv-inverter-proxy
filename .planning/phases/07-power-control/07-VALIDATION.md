---
phase: 07
slug: power-control
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 07 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~12 seconds |

## Sampling Rate

- **After every task commit:** `python -m pytest tests/ -x -q`
- **Max feedback latency:** 12 seconds

## Manual-Only Verifications

| Behavior | Requirement | Why Manual |
|----------|-------------|------------|
| Slider + confirm dialog UX | CTRL-05 | Visual interaction |
| Venus OS override indicator | CTRL-08 | Requires live Venus OS |
| SE30K accepts limit | CTRL-07 | Requires live inverter |

## Validation Sign-Off

- [ ] All tasks have automated verify or checkpoint
- [ ] Feedback latency < 12s
**Approval:** pending
