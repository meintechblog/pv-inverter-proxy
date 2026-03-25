---
gsd_state_version: 1.0
milestone: v6.0
milestone_name: Shelly Plugin
status: Milestone complete
stopped_at: Completed 37-01-PLAN.md
last_updated: "2026-03-25T21:10:32.398Z"
progress:
  total_phases: 10
  completed_phases: 8
  total_plans: 12
  completed_plans: 12
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-24)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Phase 37 — distributor-wiring-dc-average-fix

## Current Position

Phase: 37
Plan: Not started

## Performance Metrics

**Prior milestones:**

- v1.0: 4 phases, 9 plans
- v2.0: 4 phases, 7 plans
- v2.1: 4 phases, 7 plans
- v3.0: 4 phases, 6 plans
- v3.1: 4 phases, 7 plans
- v4.0: 4 phases, 8 plans
- v5.0: 3 phases, 6 plans

## Accumulated Context

### Decisions

- [v4.0]: DeviceRegistry per-device asyncio poll loops with independent lifecycle
- [v4.0]: AggregationLayer SunSpec register summation across heterogeneous sources
- [v4.0]: Device-centric SPA with hash routing and per-device sub-tabs
- [v5.0]: aiomqtt for publisher, queue-based decoupling, HA discovery
- [v6.0]: Profile-based Gen1/Gen2 abstraction (dict, not class hierarchy) -- from research
- [v6.0]: Zero new deps -- reuse aiohttp for all Shelly HTTP communication
- [v6.0]: write_power_limit() as no-op -- Shelly only supports on/off switching
- [Phase 28]: Profile-based Gen1/Gen2 abstraction using ShellyProfile ABC -- swappable API implementations
- [Phase 28]: Zero new deps for Shelly -- reuse aiohttp, energy offset tracking for counter resets
- [Phase 29]: ShellyPlugin.switch() wraps profile.switch() with session injection and error handling
- [Phase 29]: Shelly devices default throttle_enabled=False (on/off only, no percentage limiting)
- [Phase 30]: Reused mDNS discovery pattern from mdns_discovery.py for Shelly devices
- [Phase 30]: Gen2+ devices map to generation=gen2 with gen_display showing actual gen number
- [Phase 30]: Probe-on-Add: single click probes Shelly, shows generation, then auto-saves
- [Phase 30]: Type-filtered discovery: Discover button routes to mDNS for Shelly vs Modbus scan for SolarEdge
- [Phase 33]: Scoring formula: proportional base=7, binary base=3, none=0 with response/cooldown/startup penalties
- [Phase 33]: Used hasattr guard pattern for throttle_capabilities to handle plugins without the property gracefully
- [Phase 34]: Separate dispatch paths: switch() for binary, write_power_limit() for proportional
- [Phase 34]: Cooldown uses ThrottleCaps.cooldown_s (intrinsic), not InverterEntry.throttle_dead_time_s (config)
- [Phase 35]: Auto waterfall: each device own tier, sorted by effective score descending
- [Phase 35]: Convergence tracking: 5% tolerance, 50W binary-off threshold, 10-sample rolling average
- [Phase 35]: AC power extraction uses register indices 14/15 verified against aggregation.py
- [Phase 36]: Preset validation rejects silently (keeps current value) rather than returning 400
- [Phase 36]: throttle_state derived fresh each broadcast cycle, not cached
- [Phase 36]: THROTTLE_STATE_COLORS at module level for shared access between build and update functions
- [Phase 36]: Contribution bar falls back to CONTRIBUTION_COLORS when throttle_state undefined
- [Phase 37]: DC voltage averaging filters by dc_power_w > 0 to exclude Shelly relay devices

### Roadmap Evolution

- Phase 33 added: Binary Throttle (Relay On/Off) for Shelly Devices

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-03-25T21:07:16.836Z
Stopped at: Completed 37-01-PLAN.md
Resume point: Plan phase 28 (Plugin Core & Profiles)
