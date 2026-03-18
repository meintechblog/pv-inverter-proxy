---
phase: 9
slug: css-animations-toast-system
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (existing) |
| **Config file** | pyproject.toml |
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
| 09-01-01 | 01 | 1 | ANIM-01 | manual | Browser: gauge arc transition | N/A | ⬜ pending |
| 09-01-02 | 01 | 1 | ANIM-02 | manual | Browser: staggered widget entrance | N/A | ⬜ pending |
| 09-01-03 | 01 | 1 | ANIM-03 | manual | Browser: value flash on change | N/A | ⬜ pending |
| 09-01-04 | 01 | 1 | ANIM-04 | manual + grep | `grep 'prefers-reduced-motion' src/venus_os_fronius_proxy/static/style.css` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | NOTIF-01 | manual | Browser: multiple toasts stack | N/A | ⬜ pending |
| 09-02-02 | 02 | 1 | NOTIF-05 | manual | Browser: click dismiss + exit anim | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements. CSS animations and toast system are frontend-only — verified visually in browser.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gauge arc smooth animation | ANIM-01 | Visual smoothness not testable via unit test | Open dashboard, observe gauge transition on value change. No jumps or jank. |
| Staggered widget entrance | ANIM-02 | Visual timing not testable via unit test | Reload dashboard page, observe widgets appearing sequentially |
| Value flash highlight | ANIM-03 | Visual feedback on data change | Watch cards during live WebSocket updates, verify subtle flash on significant changes |
| prefers-reduced-motion | ANIM-04 | Requires browser media query emulation | Enable reduced-motion in browser DevTools, verify all animations disabled |
| Toast stacking | NOTIF-01 | Multi-toast visual layout | Trigger multiple events rapidly, verify toasts stack without overlap |
| Toast dismiss + exit | NOTIF-05 | Click interaction + visual animation | Click a toast, verify exit animation plays and toast is removed |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
