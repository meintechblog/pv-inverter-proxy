# Phase 26: Telemetry Publishing & Home Assistant Discovery - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire telemetry data from DashboardCollector snapshots through the Phase 25 asyncio.Queue into MQTT topics. Per-device + virtual PV payloads. Home Assistant MQTT Auto-Discovery config payloads for zero-config sensor creation. Change-based publish optimization.

</domain>

<decisions>
## Implementation Decisions

### Telemetry Topics & Payloads
- **D-01:** Per-device topic: `{prefix}/{device_id}/state` — flat JSON with physical units (W, V, A, °C)
- **D-02:** Virtual PV topic: `{prefix}/virtual/state` — total_power_w, contributions array
- **D-03:** Payload fields from DashboardCollector snapshot: ac_power_w, dc_power_w, dc_voltage_v, dc_current_a, ac_voltage_an_v, temperature_sink_c, status, daily_energy_wh, peak_power_w
- **D-04:** Retained messages for device state (PUB-06)
- **D-05:** Change-based optimization: hash previous payload, skip publish if identical (PUB-04)

### Home Assistant Auto-Discovery
- **D-06:** Discovery topic: `homeassistant/sensor/{node_id}/{object_id}/config` — retained JSON
- **D-07:** One discovery config per sensor (power, energy, voltage, current, temperature, status)
- **D-08:** device_class mapping: power→power, energy→energy (state_class: total_increasing), voltage→voltage, current→current, temperature→temperature
- **D-09:** Device grouping via `device` block: identifiers=[device_id], manufacturer, model, sw_version from snapshot
- **D-10:** Availability topic references LWT from Phase 25: `{prefix}/status`

### Integration
- **D-11:** Producer side: hook into broadcast_device_snapshot and broadcast_virtual_snapshot in webapp.py — put_nowait to queue
- **D-12:** Consumer side: mqtt_publisher.py loop already consumes queue — extend with payload formatting + HA discovery
- **D-13:** HA discovery payloads sent once on connect (not every interval)

### Claude's Discretion
- Exact JSON field names in payloads
- HA sensor naming convention (e.g. "PV Proxy Spielturm Power")
- Whether to send discovery cleanup on device removal
- Hash algorithm for change detection (recommend json.dumps + hash)

</decisions>

<canonical_refs>
## Canonical References

### Phase 25 artifacts (publisher infrastructure)
- `src/venus_os_fronius_proxy/mqtt_publisher.py` — Queue consumer loop to extend
- `src/venus_os_fronius_proxy/config.py` — MqttPublishConfig with topic_prefix

### Data sources
- `src/venus_os_fronius_proxy/dashboard.py` — DashboardCollector snapshot format
- `src/venus_os_fronius_proxy/webapp.py` — broadcast_device_snapshot, broadcast_virtual_snapshot

### Research
- `.planning/research/FEATURES.md` — HA discovery patterns, topic conventions
- `.planning/research/PITFALLS.md` — Change-based optimization, retain flag policy

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mqtt_publisher.py` from Phase 25 — queue consumer loop, aiomqtt client, LWT
- `DashboardCollector.last_snapshot` — decoded physical values ready for JSON
- `broadcast_device_snapshot` / `broadcast_virtual_snapshot` in webapp.py — hook points for queue producer

### Integration Points
- `mqtt_publisher.py` — extend with payload formatting, HA discovery, change detection
- `webapp.py` — add queue.put_nowait calls in broadcast functions
- New file possible: `mqtt_payloads.py` for payload/discovery formatting (keeps publisher lean)

</code_context>

<deferred>
## Deferred Ideas

- Webapp MQTT config UI — Phase 27
- MQTT auth/TLS — Future

</deferred>

---

*Phase: 26-telemetry-publishing-ha-discovery*
*Context gathered: 2026-03-22*
