---
gsd_state_version: 1.0
milestone: v7.0
milestone_name: Sungrow SG-RT Plugin
status: executing
stopped_at: Roadmap created for v7.0 (5 phases, 17 requirements)
last_updated: "2026-04-06T09:06:47.173Z"
last_activity: 2026-04-06
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-06)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 38 — Plugin Core

## Current Position

Phase: 39
Plan: Not started
Status: Executing Phase 38
Last activity: 2026-04-06

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

## Accumulated Context

### Decisions

- [v6.0]: Profile-based Gen1/Gen2 abstraction (dict, not class hierarchy)
- [v6.0]: Scoring formula: proportional base=7, binary base=3, with response/cooldown/startup penalties
- [v6.0->post]: Higher score = throttled first (fastest responders handle throttling)

### Sungrow Research

- Live device: SG8.0RT at 192.168.2.151:502 via WiNet-S Dongle
- Modbus TCP read-only confirmed working parallel to Loxone
- Register map verified: wire 5002-5037 covers all essential data
- Sungrow uses 1-based doc addresses (wire = doc - 1)
- U32 values: high word at lower address, low word always 0 for current values
- 3-phase inverter (3P4L), rated 8kW
- State register at wire 5037 (0x8100 = Derating observed)
- Power limiting via Holding Registers needs research (write registers not yet probed)

### Blockers/Concerns

- Modbus TCP shared with Loxone -- read-only is safe, write (power limiting) needs testing
- Power limit write registers for Sungrow SG-RT not yet identified

## Session Continuity

Last session: 2026-04-06
Stopped at: Roadmap created for v7.0 (5 phases, 17 requirements)
Resume point: `/gsd-plan-phase 38`
