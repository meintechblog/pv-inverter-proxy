---
phase: 16
slug: install-script-readme
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | bash (shellcheck + grep assertions) |
| **Config file** | none |
| **Quick run command** | `bash -n install.sh && echo "syntax ok"` |
| **Full suite command** | `bash -n install.sh && grep -q 'inverter:' install.sh && grep -q 'venus:' install.sh` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run syntax check
- **After every plan wave:** Run full assertions
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | DOCS-01 | grep | `grep -q 'inverter:' install.sh && grep -q 'venus:' install.sh && grep -q '\-f' install.sh` | ✅ | ⬜ pending |
| 16-01-02 | 01 | 1 | DOCS-02 | grep | `grep -q '## Installation' README.md && grep -q 'Venus OS' README.md && grep -q '>= 3.7' README.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements. No new test framework needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Install script runs end-to-end on fresh LXC | DOCS-01 | Requires clean environment | Run curl one-liner on fresh Debian LXC, verify service starts |
| README flow matches actual UX | DOCS-02 | Requires human reading | Follow README steps, verify each matches real behavior |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
