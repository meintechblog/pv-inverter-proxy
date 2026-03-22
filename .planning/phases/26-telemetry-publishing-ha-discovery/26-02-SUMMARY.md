---
phase: 26-telemetry-publishing-ha-discovery
plan: 02
subsystem: mqtt
tags: [mqtt, home-assistant, ha-discovery, aiomqtt, change-detection, retained-messages]

requires:
  - phase: 26-telemetry-publishing-ha-discovery/01
    provides: mqtt_payloads.py pure-function module (device_payload, virtual_payload, ha_discovery_configs)
  - phase: 25-publisher-infrastructure
    provides: mqtt_publisher.py with queue-based publish loop, LWT, reconnect backoff

provides:
  - End-to-end MQTT telemetry data flow from poll loop through broadcast to MQTT broker
  - HA auto-discovery configs published on connect for all enabled devices + virtual device
  - Change-detection optimization preventing redundant MQTT publishes
  - Retained device state messages for late-joining subscribers
  - Per-device availability topics (online/offline)

affects: [26-telemetry-publishing-ha-discovery, ha-integration, mqtt-config-ui]

tech-stack:
  added: []
  patterns: [queue-producer-in-broadcast, change-detection-via-json-hash, ha-discovery-on-connect]

key-files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/mqtt_publisher.py
    - src/venus_os_fronius_proxy/webapp.py
    - src/venus_os_fronius_proxy/__main__.py
    - tests/test_mqtt_publisher.py

key-decisions:
  - "Use ha_discovery_topic() function rather than embedding _topic in config dicts"
  - "Legacy message format (topic+payload) kept as backward-compatible else branch"
  - "JSON hash comparison for change detection (compact separators for deterministic output)"

patterns-established:
  - "Queue producer pattern: put_nowait after WS broadcast, QueueFull silently caught"
  - "Discovery-on-connect pattern: iterate inverters, publish 16 sensor configs + availability per device"
  - "Change detection: per-device JSON string cache, skip publish if hash matches"

requirements-completed: [PUB-01, PUB-02, PUB-04, PUB-06, HA-01, HA-04]

duration: 4min
completed: 2026-03-22
---

# Phase 26 Plan 02: MQTT Publisher Wiring Summary

**End-to-end MQTT telemetry with HA auto-discovery, retained state, and change-detection optimization**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-22T10:45:20Z
- **Completed:** 2026-03-22T10:49:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Queue producers wired into both broadcast functions (device + virtual snapshots)
- HA discovery configs (16 sensors per device + virtual) published on MQTT connect with retain+QoS 1
- Change detection prevents redundant publishes via JSON hash comparison
- Device state messages published with retain=True for late-joining subscribers
- Per-device availability topics publish "online" on connect
- 6 new tests added, all 34 tests (15 publisher + 19 payloads) passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire queue producers into webapp.py broadcast functions** - `6f3bfec` (feat)
2. **Task 2 RED: Add failing tests for HA discovery, change detection** - `f2c8959` (test)
3. **Task 2 GREEN: Implement HA discovery, change detection, retained state** - `9d1d376` (feat)

## Files Created/Modified
- `src/venus_os_fronius_proxy/webapp.py` - Queue producer calls in broadcast_device_snapshot and broadcast_virtual_snapshot
- `src/venus_os_fronius_proxy/mqtt_publisher.py` - Extended with HA discovery on connect, change detection, retained state, new signature
- `src/venus_os_fronius_proxy/__main__.py` - Pass inverters and virtual_name to mqtt_publish_loop
- `tests/test_mqtt_publisher.py` - 6 new tests for discovery, availability, retain, change detection, virtual

## Decisions Made
- Used `ha_discovery_topic()` function to generate topics rather than embedding `_topic` key in config dicts (cleaner separation)
- Kept legacy message format (topic+payload keys) as backward-compatible fallback in the else branch
- Used compact JSON separators `(",",":")` for deterministic change detection hashing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed KeyError on legacy message format**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Existing test_consumes_queue_messages used old format `{"topic": ..., "payload": ...}` without "type" key. Using `msg["type"]` would KeyError.
- **Fix:** Changed to `msg.get("type")` with else branch for legacy format backward compatibility
- **Files modified:** src/venus_os_fronius_proxy/mqtt_publisher.py
- **Verification:** All 8 existing tests still pass
- **Committed in:** 9d1d376

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for backward compatibility with existing test patterns. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Complete MQTT data flow operational: poll -> broadcast -> queue -> publisher -> broker
- HA auto-discovery enabled for all device sensors
- Ready for Phase 27 (mDNS broker discovery and config UI)

---
*Phase: 26-telemetry-publishing-ha-discovery*
*Completed: 2026-03-22*
