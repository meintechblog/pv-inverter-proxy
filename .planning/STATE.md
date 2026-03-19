---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Setup & Onboarding
status: in-progress
stopped_at: Completed 15-01-PLAN.md
last_updated: "2026-03-19T20:53:00.000Z"
last_activity: 2026-03-19 — Completed 15-01 (Venus OS auto-detect backend + frontend banner)
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 5
  completed_plans: 5
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter
**Current focus:** v3.0 Setup & Onboarding — Phase 15 complete

## Current Position

Phase: 15 of 16 (Venus OS Auto-Detect)
Plan: 1 of 1
Status: Phase 15 complete (all plans delivered)
Last activity: 2026-03-19 — Completed 15-01 (Venus OS auto-detect backend + frontend banner)

Progress: [██████████] 100%

## Performance Metrics

**v1.0:** 4 phases, 9 plans, ~1 hour
**v2.0:** 4 phases, 7 plans, ~3 hours
**v2.1:** 4 phases, 7 plans
**v3.0:** 4 phases, plans TBD

## Accumulated Context

### Decisions

- 50W gauge deadband for 30kW inverter (09-01)
- Lock duration hard-capped at 900s — safety-critical (11-01)
- Locked writes silently accepted but NOT forwarded (11-01)
- Override log collapsed by default with event count badge (12-01)
- Empty venus host = not configured, proxy runs without MQTT (13-01)
- CONNACK rejection raises ConnectionError with return code (13-01)
- Portal ID discovery retries every 30s in while-True loop before main MQTT loop (13-02)
- 503 status for unconfigured Venus OS handlers (graceful degradation) (13-02)
- CONNACK validated in _mqtt_write_venus for consistency (13-02)
- Venus config change detected via tuple comparison of (host, port, portal_id) (14-01)
- Three-state venus status: connected/disconnected/not configured (14-01)
- Nested config API format {inverter: {...}, venus: {...}} (14-01)
- Connection bobbles replace Test Connection button for live status (14-02)
- venus-dependent class + mqtt-gated CSS for dashboard feature gating (14-02)
- MQTT setup guide card shown contextually when configured but disconnected (14-02)
- Detection is one-shot: flag set on first Model 123 write only (15-01)
- Banner placed before config form, outside form element (15-01)
- window._lastVenusDetected tracks state for input listener restore (15-01)

### Pending Todos

None.

### Blockers/Concerns

- ~~MQTT host + portal ID currently hardcoded in 5 locations~~ — Resolved in 13-01
- ~~CONNACK return code never parsed (silent false-positive)~~ — Resolved in 13-01
- Install script YAML key mismatch (`solaredge:` vs `inverter:`) — Phase 16 resolves this

## Session Continuity

Last session: 2026-03-19T20:53:00.000Z
Stopped at: Completed 15-01-PLAN.md
Resume file: .planning/phases/15-venus-os-auto-detect/15-01-SUMMARY.md
