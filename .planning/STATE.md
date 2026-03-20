---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: Auto-Discovery & Inverter Management
status: completed
stopped_at: Completed 20-02-PLAN.md — v3.1 milestone complete
last_updated: "2026-03-20T17:05:47.609Z"
last_activity: 2026-03-20 — Completed 20-02 discovery UI with scan button, progress bar, result list, auto-scan onboarding
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 7
  completed_plans: 7
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Venus OS muss den SolarEdge-Inverter genauso erkennen und steuern koennen wie einen echten Fronius-Inverter
**Current focus:** v3.1 complete — all phases shipped

## Current Position

Phase: 20 of 20 (Discovery UI & Onboarding)
Plan: 2 of 2 complete
Status: Phase 20 complete — v3.1 milestone shipped
Last activity: 2026-03-20 — Completed 20-02 discovery UI with scan button, progress bar, result list, auto-scan onboarding

Progress: [██████████] 100%

## Performance Metrics

**v1.0:** 4 phases, 9 plans, ~1 hour
**v2.0:** 4 phases, 7 plans, ~3 hours
**v2.1:** 4 phases, 7 plans
**v3.0:** 4 phases, 6 plans

## Accumulated Context

### Decisions

- Nested config API format {inverter: {...}, venus: {...}} (14-01)
- Connection bobbles replace Test Connection button for live status (14-02)
- Detection is one-shot: flag set on first Model 123 write only (15-01)
- [Phase 16]: Migration warning (not auto-migration) for old solaredge: config key
- [Phase 16]: Port 502 check is warning not hard fail (previous install may hold port)
- [Phase 17-01]: Used device_id param (not slave) for pymodbus to match solaredge.py
- [Phase 17-01]: DiscoveredDevice.supported as @property (computed from manufacturer)
- [Phase 17-02]: Added supported field explicitly to asdict output (property not included by default)
- [Phase 17-02]: Scanner API tests placed in test_scanner.py alongside module tests
- [Phase 18-01]: Kept Config.inverter as backward-compat property (webapp.py still uses it)
- [Phase 18-01]: InverterConfig = InverterEntry alias for external backward compat
- [Phase 18-01]: Migration backup only created if .bak does not already exist
- [Phase 18-02]: config_get returns inverters list (breaking change for frontend, updated in Phase 19)
- [Phase 18-02]: config_save accepts both old single-inverter and new multi-inverter format
- [Phase 18-02]: _reconfigure_active helper extracts hot-reload into reusable function
- [Phase 19-01]: Inverters use instant CRUD (PUT/DELETE) not dirty-tracking like Venus config
- [Phase 19-01]: Delete uses inline No/Yes confirmation instead of modal dialog
- [Phase 19-01]: Edit form slides open with CSS max-height transition
- [Phase 19-01]: loadInverters() re-fetches after every mutation to sync active flags
- [Phase 20-01]: Scanner endpoint returns immediately with {status: started}, results via WebSocket
- [Phase 20-01]: Concurrent scan guard uses app-level _scan_running flag
- [Phase 20-01]: progress_callback uses asyncio.ensure_future to bridge sync to async WS broadcast
- [Phase 20-02]: Discover button placed LEFT of + button for visual scan-then-add flow
- [Phase 20-02]: Auto-scan single result auto-added silently with toast (no confirmation needed)
- [Phase 20-02]: Scan ports saved on blur (no explicit save button) for minimal friction

### Pending Todos

None.

### Blockers/Concerns

- SolarEdge allows only ONE simultaneous Modbus TCP connection — scanner must use sequential access with short timeouts

## Session Continuity

Last session: 2026-03-20T16:46:00Z
Stopped at: Completed 20-02-PLAN.md — v3.1 milestone complete
