---
gsd_state_version: 1.0
milestone: v5.0
milestone_name: MQTT Data Publishing
status: unknown
stopped_at: Completed 25-01-PLAN.md
last_updated: "2026-03-22T10:03:36.243Z"
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 2
  completed_plans: 1
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-22)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 25 — Publisher Infrastructure & Broker Connectivity

## Current Position

Phase: 25 (Publisher Infrastructure & Broker Connectivity) — EXECUTING
Plan: 2 of 2

## Performance Metrics

**Prior milestones:**

- v1.0: 4 phases, 9 plans
- v2.0: 4 phases, 7 plans
- v2.1: 4 phases, 7 plans
- v3.0: 4 phases, 6 plans
- v3.1: 4 phases, 7 plans
- v4.0: 4 phases, 8 plans

**Current milestone (v5.0):**

- Phases: 3 (25-27)
- Plans complete: 0
- Phases complete: 0

## Accumulated Context

### Decisions

- [v4.0]: DeviceRegistry per-device asyncio poll loops with independent lifecycle
- [v4.0]: AggregationLayer SunSpec register summation across heterogeneous sources
- [v4.0]: Device-centric SPA with hash routing and per-device sub-tabs
- Existing MQTT: hand-rolled raw socket client in venus_reader.py for Venus OS subscriber
- [v5.0]: Use aiomqtt (not raw sockets) for publisher -- QoS 1, LWT, reconnect needed
- [v5.0]: Use zeroconf for mDNS broker discovery
- [v5.0]: Queue-based decoupling between broadcast chain and publisher (asyncio.Queue, maxsize=100)
- [v5.0]: Leave venus_reader.py untouched -- existing Venus OS MQTT subscriber is separate
- [v5.0]: HA discovery payloads built into initial architecture, not bolted on later
- [Phase 25]: aiomqtt for publisher with QoS 1, LWT, exponential backoff reconnect
- [Phase 25]: Queue-based decoupling: asyncio.Queue(maxsize=100) between broadcast chain and publisher

### Research Flags

- Phase 26: Verify HA discovery schema against target HA version (default_entity_id vs object_id)
- Phase 25: Verify mqtt-master.local advertises _mqtt._tcp.local. via Avahi before building scan

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-03-22T10:03:36.240Z
Stopped at: Completed 25-01-PLAN.md
Resume point: Plan Phase 25
