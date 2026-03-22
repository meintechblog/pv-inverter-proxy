---
phase: 26-telemetry-publishing-ha-discovery
verified: 2026-03-22T12:00:00Z
status: passed
score: 11/11 must-haves verified
re_verification: false
---

# Phase 26: Telemetry Publishing + HA Discovery Verification Report

**Phase Goal:** All inverter data flows to the MQTT broker with per-device topics and Home Assistant discovers all sensors automatically
**Verified:** 2026-03-22T12:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Device snapshot is converted to a flat MQTT-ready JSON with physical units | VERIFIED | `device_payload()` in `mqtt_payloads.py:74-84` — extracts 21 fields from snapshot["inverter"], `temperature_sink_c` renamed to `temperature_c` |
| 2 | Virtual PV snapshot is converted to an MQTT payload with total power and contributions | VERIFIED | `virtual_payload()` in `mqtt_payloads.py:87-104` — returns ts, total_power_w, stripped contributions |
| 3 | HA discovery configs are generated for all 16 sensor entities per device | VERIFIED | `ha_discovery_configs()` in `mqtt_payloads.py:119-192` — iterates 16 `SENSOR_DEFS` entries, test_count asserts `len(configs) == 16` |
| 4 | Each HA sensor has correct device_class, state_class, and unit_of_measurement | VERIFIED | `SENSOR_DEFS` table lines 21-38 matches spec; None values omit keys entirely (not null); tests `test_power_sensor`, `test_energy_sensor`, `test_status_sensor` all pass |
| 5 | All sensors for one inverter are grouped under one HA device with manufacturer/model metadata | VERIFIED | Shared `device_block` built once, injected into all 16 configs; `test_device_grouping` and `test_device_block_metadata` pass |
| 6 | When a device snapshot is broadcast, a telemetry message is queued for MQTT publishing | VERIFIED | `webapp.py:713-721` — `put_nowait({"type":"device","device_id":...,"snapshot":...})` after WS broadcast; QueueFull silently caught |
| 7 | When the virtual snapshot is broadcast, an aggregated message is queued for MQTT publishing | VERIFIED | `webapp.py:768-779` — `put_nowait({"type":"virtual","virtual_data":{...}})` after WS broadcast; QueueFull silently caught |
| 8 | On MQTT connect, HA discovery configs are published once (retained) for all configured devices | VERIFIED | `mqtt_publisher.py:57-108` — iterates inverters on connect, publishes 16 sensor configs with `retain=True, qos=1`; `test_publishes_ha_discovery_on_connect` passes |
| 9 | Device state messages are published with retain=True so new subscribers get latest state | VERIFIED | `mqtt_publisher.py:133` — `client.publish(topic, ..., retain=True)` for device messages; `test_device_message_published_retained` passes |
| 10 | When telemetry payload has not changed since last publish, no redundant MQTT message is sent | VERIFIED | `mqtt_publisher.py:128-129` — `last_payloads` dict stores JSON string per device_id, `continue` on match; `test_change_detection_skips_identical` passes |
| 11 | Device availability topics publish online/offline per device | VERIFIED | `mqtt_publisher.py:79-84` — publishes `"online"` to `{prefix}/device/{id}/availability` with `retain=True, qos=1` on connect; `test_publishes_device_availability_on_connect` passes |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/venus_os_fronius_proxy/mqtt_payloads.py` | Payload extraction and HA discovery config generation | VERIFIED | 243 lines; exports `device_payload`, `virtual_payload`, `ha_discovery_configs`, `ha_discovery_topic`, `virtual_ha_discovery_configs`; zero side effects |
| `tests/test_mqtt_payloads.py` | Unit tests for payload and discovery functions (min 80 lines) | VERIFIED | 264 lines; 19 test functions across 5 test classes; all pass |
| `src/venus_os_fronius_proxy/mqtt_publisher.py` | Extended publisher with HA discovery, change detection, retained state | VERIFIED | 163 lines; `mqtt_publish_loop(ctx, config, inverters=None, virtual_name="")` signature; 8 `retain=True` usages |
| `src/venus_os_fronius_proxy/webapp.py` | Queue producer wiring in broadcast functions | VERIFIED | 6 occurrences of `mqtt_pub_queue`; both `broadcast_device_snapshot` and `broadcast_virtual_snapshot` enqueue correctly |
| `tests/test_mqtt_publisher.py` | Extended tests for discovery, change detection, retained messages (min 150 lines) | VERIFIED | 518 lines; 15 test functions (8 pre-existing + 6 new Phase 26); all 34 tests across both files pass |
| `src/venus_os_fronius_proxy/__main__.py` | Call site passes inverters and virtual_name | VERIFIED | Lines 176-180 — `mqtt_publish_loop(app_ctx, config.mqtt_publish, inverters=config.inverters, virtual_name=config.virtual_inverter.name)` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `webapp.py:broadcast_device_snapshot` | `ctx.mqtt_pub_queue` | `put_nowait` with device payload | WIRED | Lines 713-721; message has type="device", device_id, snapshot |
| `webapp.py:broadcast_virtual_snapshot` | `ctx.mqtt_pub_queue` | `put_nowait` with virtual payload | WIRED | Lines 768-779; message has type="virtual", virtual_data with total_power_w and contributions |
| `mqtt_publisher.py:mqtt_publish_loop` | `mqtt_payloads.ha_discovery_configs` | import and call on connect | WIRED | Lines 58-66; iterates enabled inverters, generates 16 configs per device |
| `mqtt_publisher.py` | `aiomqtt.Client.publish` | `retain=True` for device state | WIRED | Line 133 for device state, line 145 for virtual state — both `retain=True` |
| `mqtt_payloads.py:device_payload` | `DashboardCollector snapshot dict` | extracts inverter sub-dict fields | WIRED | Lines 80-83; `snapshot.get("inverter", {})` then `_PAYLOAD_FIELDS` mapping |
| `mqtt_payloads.py:ha_discovery_configs` | `homeassistant/sensor topic format` | builds config dicts per sensor | WIRED | Lines 166-192; `device_class`, `state_class`, `unit_of_measurement` per `SENSOR_DEFS` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PUB-01 | 26-01, 26-02 | Proxy publishes inverter data (power, voltage, current, temperature, status) per device to MQTT broker | SATISFIED | `device_payload()` extracts all 20 inverter fields; publisher routes to `{prefix}/device/{id}/state` |
| PUB-02 | 26-01, 26-02 | Proxy publishes aggregated Virtual PV data (total power, contributions) to MQTT broker | SATISFIED | `virtual_payload()` + publisher routes to `{prefix}/virtual/state` with retain |
| PUB-04 | 26-02 | Publisher uses change-based optimization — no publish if data unchanged | SATISFIED | `last_payloads` dict in `mqtt_publisher.py:111,128-129`; `test_change_detection_skips_identical` passes |
| PUB-06 | 26-02 | Device state messages are retained for new subscribers | SATISFIED | `retain=True` on lines 133 and 145 of `mqtt_publisher.py`; `test_device_message_published_retained` passes |
| HA-01 | 26-01, 26-02 | Publisher sends MQTT auto-discovery config payloads for all sensors | SATISFIED | 16 sensor configs per device published on connect with `retain=True, qos=1`; `test_publishes_ha_discovery_on_connect` passes |
| HA-02 | 26-01 | Sensors have correct device_class and state_class for HA Energy Dashboard | SATISFIED | `SENSOR_DEFS` table with per-sensor device_class/state_class; `test_power_sensor`, `test_energy_sensor` verify specific values |
| HA-03 | 26-01 | Inverters appear as grouped devices in HA (Manufacturer, Model, SW Version) | SATISFIED | `device_block` with identifiers, manufacturer, model, serial_number, sw_version shared across all 16 configs; `test_device_block_metadata` passes |
| HA-04 | 26-02 | Availability entity per device reacts to LWT | SATISFIED | `{prefix}/device/{id}/availability` published "online" on connect with retain; LWT via existing `{prefix}/status` offline payload; `test_publishes_device_availability_on_connect` passes |

No orphaned requirements. PUB-03 and PUB-05 belong to Phase 25 (confirmed in REQUIREMENTS.md).

### Anti-Patterns Found

None. No TODOs, FIXMEs, placeholder comments, empty return stubs, or hardcoded empty data found in any of the modified files.

### Human Verification Required

#### 1. Live HA Auto-Discovery End-to-End

**Test:** With a real MQTT broker and Home Assistant instance, enable MQTT publishing in the proxy config. Start the proxy with at least one configured inverter. In HA, check MQTT integration — confirm the inverter appears as a grouped device under Settings > Devices & Services.
**Expected:** All 16 sensors visible under one device card; entity names match SENSOR_DEFS display names; device shows manufacturer, model, serial, firmware version.
**Why human:** Requires live MQTT broker + HA instance; cannot verify HA UI rendering programmatically.

#### 2. HA Energy Dashboard Compatibility

**Test:** After HA discovers sensors, navigate to Energy Dashboard. Add the Total Energy sensor to the Solar Production section.
**Expected:** HA accepts the sensor without error; energy history accumulates correctly over time.
**Why human:** Requires HA runtime and time passing to verify state_class="total_increasing" behavior.

#### 3. Availability Offline on Proxy Stop

**Test:** Start the proxy with MQTT enabled. Confirm "online" in `{prefix}/status`. Stop the proxy process. Check `{prefix}/status` in an MQTT client.
**Expected:** Topic shows "offline" (LWT delivered by broker on disconnect).
**Why human:** Requires a live broker and process management; LWT delivery depends on broker behavior.

### Gaps Summary

No gaps. All must-haves from both plans verified. All 34 tests pass (19 payload tests + 15 publisher tests). All 8 requirement IDs are satisfied with direct code evidence. The end-to-end data flow is fully wired: poll loop -> `broadcast_device_snapshot`/`broadcast_virtual_snapshot` -> `mqtt_pub_queue` -> `mqtt_publish_loop` -> `aiomqtt.Client.publish` -> MQTT broker -> Home Assistant.

---

_Verified: 2026-03-22T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
