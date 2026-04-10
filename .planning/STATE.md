---
gsd_state_version: 1.0
milestone: v8.0
milestone_name: Auto-Update System
status: defining_requirements
stopped_at: Milestone v8.0 started — gathering requirements
last_updated: "2026-04-10T12:00:00.000Z"
last_activity: 2026-04-10
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-10)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Milestone v8.0 — Auto-Update System (defining requirements)

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-04-10 — Milestone v8.0 started

Progress: [..........] 0%

## Performance Metrics

**Prior milestones:**

- v1.0: 4 phases, 9 plans
- v2.0: 4 phases, 7 plans
- v2.1: 4 phases, 7 plans
- v3.0: 4 phases, 6 plans
- v3.1: 4 phases, 7 plans
- v4.0: 4 phases, 8 plans
- v5.0: 3 phases, 6 plans
- v6.0: 10 phases, 12 plans
- v7.0: 1 formal phase (38) + ad-hoc polish commits

## Accumulated Context

### Decisions

- [v6.0]: Profile-based Gen1/Gen2 abstraction (dict, not class hierarchy)
- [v6.0]: Scoring formula: proportional base=7, binary base=3, with response/cooldown/startup penalties
- [v6.0->post]: Higher score = throttled first (fastest responders handle throttling)
- [v7.0]: Per-device aggregate toggle independent of throttle_enabled — display + aggregation respect it, throttle distributor stays independent

### Sungrow Reference

- Live device: SG8.0RT at 192.168.2.151:502 via WiNet-S Dongle
- Register map verified: wire 5002-5037 covers all essential data
- U32 values: high word at lower address, low word always 0
- 3-phase inverter (3P4L), rated 8kW

### v8.0 Auto-Update Context

- Service runs as `pv-proxy` user (no sudo) under systemd on Debian 13 LXC
- Code at /opt/pv-inverter-proxy, installed via `pip install -e .`
- Config at /etc/pv-inverter-proxy/config.yaml (must be preserved across updates)
- GitHub repo: github.com:meintechblog/pv-inverter-master
- Target LXC: 192.168.3.191
- Self-restart challenge: service cannot restart itself via systemctl as non-root
- Rollback requirement: bad commit must not lock user out of webapp

### Blockers/Concerns

- Root-privilege strategy for update helper: polkit rule, setuid helper, or separate privileged sidecar service — TBD in research
- Health-check definition after restart: what counts as "healthy" enough to keep new version

## Session Continuity

Last session: 2026-04-10
Stopped at: Milestone v8.0 started — gathering requirements
Resume point: Continue new-milestone workflow → research → requirements → roadmap
