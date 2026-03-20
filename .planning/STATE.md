---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: Multi-Source Virtual Inverter
status: executing
stopped_at: Completed 21-02-PLAN.md
last_updated: "2026-03-20T19:17:42.000Z"
last_activity: 2026-03-20 -- Completed 21-02 OpenDTU plugin
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 21 - Data Model & OpenDTU Plugin

## Current Position

Phase: 21 of 24 (Data Model & OpenDTU Plugin)
Plan: 2 of 2 in current phase
Status: phase-complete
Last activity: 2026-03-20 -- Completed 21-02 (OpenDTU plugin)

Progress: [██░░░░░░░░] 25%

## Performance Metrics

**Prior milestones:**
- v1.0: 4 phases, 9 plans, ~1 hour
- v2.0: 4 phases, 7 plans, ~3 hours
- v2.1: 4 phases, 7 plans
- v3.0: 4 phases, 6 plans
- v3.1: 4 phases, 7 plans

**v4.0:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 21 | 2/2 | 18min | 9min |

## Accumulated Context

### Decisions

- [v4.0 Roadmap]: Coarse granularity -- 4 phases (21-24) covering 28 requirements
- [v4.0 Roadmap]: Config refactor + OpenDTU plugin bundled in Phase 21 (both foundational)
- [v4.0 Roadmap]: Discovery uses manual scan only -- no auto-scan-on-empty-list
- [v3.1]: SolarEdge single-connection constraint remains (scanner uses sequential access)
- [v3.1]: Inverters use instant CRUD (PUT/DELETE) not dirty-tracking
- [21-01]: Removed old inverter: migration code entirely (fresh config only)
- [21-01]: AppContext uses object type hints to avoid circular imports
- [21-01]: Compat property accessors on AppContext for minimal diff during migration
- [21-02]: DC channel summation: sum power+current, power-weighted average for voltage
- [21-02]: Fixed SunSpec scale factors: SF=0 power, SF=-1 voltage, SF=-2 current/freq
- [21-02]: Dead-time guard at 30s (25s typical + 5s margin)

### Pending Todos

None.

### Blockers/Concerns

- OpenDTU dead-time (25-30s) estimated from GitHub issues -- validate on real HM-800 during Phase 21
- Hoymiles serials at 192.168.3.98 must be confirmed from live API response
- SolarEdge single-connection constraint affects concurrent polling design

## Session Continuity

Last session: 2026-03-20T19:17:42.000Z
Stopped at: Completed 21-02-PLAN.md (Phase 21 complete)
Resume file: .planning/phases/22-device-registry/22-01-PLAN.md
