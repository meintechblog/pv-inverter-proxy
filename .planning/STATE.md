---
gsd_state_version: 1.0
milestone: v5.0
milestone_name: MQTT Data Publishing
status: unknown
stopped_at: Completed 27-02-PLAN.md
last_updated: "2026-03-22T11:22:36.175Z"
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 6
  completed_plans: 6
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-22)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 27 — Webapp Config & Status UI

## Current Position

Phase: 27 (Webapp Config & Status UI) — EXECUTING
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
- Plans complete: 5
- Phases complete: 2

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
- [Phase 25]: Publisher lifecycle mirrors venus_task pattern: conditional start, cancel on shutdown, hot-reload on config save
- [Phase 26]: SENSOR_DEFS as list-of-tuples for data-driven HA config generation
- [Phase 26]: Pure-function payload module (mqtt_payloads.py) with zero side effects, no MQTT dependency
- [Phase 26]: Use ha_discovery_topic() function rather than embedding _topic in config dicts
- [Phase 26]: JSON hash comparison for change detection with compact separators
- [Phase 26]: Legacy message format kept as backward-compatible fallback in publisher
- [Phase 27]: Status dot inline-style for dynamic green/red, topic preview seeded from config.inverters then replaced by WS data

### Research Flags

- Phase 26: Verify HA discovery schema against target HA version (default_entity_id vs object_id)
- Phase 25: Verify mqtt-master.local advertises _mqtt._tcp.local. via Avahi before building scan

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-03-22T11:22:36.172Z
Stopped at: Completed 27-02-PLAN.md
Resume point: Plan 27-02
