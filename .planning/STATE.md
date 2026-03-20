---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: Multi-Source Virtual Inverter
status: in-progress
stopped_at: Phase 23 context gathered
last_updated: "2026-03-20T22:15:31.850Z"
last_activity: 2026-03-20 -- Completed 22-02 (AggregationLayer + Rewire)
progress:
  total_phases: 4
  completed_phases: 2
  total_plans: 4
  completed_plans: 4
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 22 - Device Registry & Aggregation

## Current Position

Phase: 22 of 24 (Device Registry & Aggregation)
Plan: 2 of 2 in current phase
Status: in-progress
Last activity: 2026-03-20 -- Completed 22-02 (AggregationLayer + Rewire)

Progress: [█████░░░░░] 50%

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
| 22 | 2/2 | 25min | 12min |

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
- [22-01]: Lazy imports for plugin_factory/DashboardCollector to avoid Python 3.9 slots= incompatibility
- [22-01]: Poll loop stores raw data but defers cache writes and aggregation to Plan 02
- [22-01]: enable/disable_device delegate to start/stop_device for simplicity
- [22-02]: Power limit forwarding deferred to Phase 23 -- local-only acceptance with warning log
- [22-02]: Modbus server kept running when 0 active devices (stale errors) to preserve Venus OS discovery
- [22-02]: Fixed SFs for aggregated output: SF=0 power, SF=-1 voltage, SF=-2 current/freq
- [22-02]: Webapp plugin references made optional with None guards for multi-device mode

### Pending Todos

None.

### Blockers/Concerns

- OpenDTU dead-time (25-30s) estimated from GitHub issues -- validate on real HM-800 during Phase 21
- Hoymiles serials at 192.168.3.98 must be confirmed from live API response
- SolarEdge single-connection constraint affects concurrent polling design

## Session Continuity

Last session: 2026-03-20T22:15:31.846Z
Stopped at: Phase 23 context gathered
Resume file: .planning/phases/23-power-limit-distribution/23-CONTEXT.md
