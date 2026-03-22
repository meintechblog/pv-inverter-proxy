---
phase: 25-publisher-infrastructure
plan: 01
subsystem: infra
tags: [mqtt, aiomqtt, asyncio, queue, lwt, reconnect]

# Dependency graph
requires: []
provides:
  - MqttPublishConfig dataclass in config.py
  - AppContext mqtt_pub_task/mqtt_pub_connected/mqtt_pub_queue fields
  - mqtt_publisher.py with queue-based publish loop, LWT, and reconnect
  - aiomqtt and zeroconf dependencies
affects: [25-02, 26-publisher-infrastructure]

# Tech tracking
tech-stack:
  added: [aiomqtt, zeroconf]
  patterns: [queue-based-decoupling, exponential-backoff-reconnect, lwt-online-offline]

key-files:
  created:
    - src/venus_os_fronius_proxy/mqtt_publisher.py
    - tests/test_mqtt_publisher.py
  modified:
    - src/venus_os_fronius_proxy/config.py
    - src/venus_os_fronius_proxy/context.py
    - pyproject.toml
    - config/config.example.yaml
    - tests/test_config.py

key-decisions:
  - "aiomqtt for publisher (not raw sockets like venus_reader.py) -- needs QoS 1, LWT, reconnect"
  - "Queue-based decoupling: asyncio.Queue(maxsize=100) between broadcast chain and publisher"
  - "Exponential backoff 1s to 30s cap for reconnect on MqttError"

patterns-established:
  - "Queue producer pattern: try queue.put_nowait(msg) except QueueFull: pass"
  - "LWT online/offline on {prefix}/status with QoS 1 + retain"

requirements-completed: [CONN-01, CONN-02, PUB-03, PUB-05]

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 25 Plan 01: Publisher Infrastructure Summary

**MQTT publisher module with aiomqtt queue consumer, LWT online/offline, and exponential backoff reconnect (1-30s)**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-22T09:54:09Z
- **Completed:** 2026-03-22T10:02:23Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- MqttPublishConfig dataclass with 6 fields (enabled, host, port, topic_prefix, interval_s, client_id) and correct defaults
- AppContext extended with mqtt_pub_task, mqtt_pub_connected, mqtt_pub_queue fields
- mqtt_publisher.py: async queue consumer with LWT (offline will, online on connect), exponential backoff reconnect
- 11 new tests (9 publisher + 2 config) all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: MqttPublishConfig dataclass + AppContext fields + dependencies** - `c101a3d` (feat)
2. **Task 2 RED: Failing tests for mqtt_publisher** - `369b32f` (test)
3. **Task 2 GREEN: mqtt_publisher.py implementation + config tests** - `641f7d8` (feat)

_Note: Task 2 used TDD with separate RED and GREEN commits._

## Files Created/Modified
- `src/venus_os_fronius_proxy/mqtt_publisher.py` - Queue-based MQTT publish loop with LWT and reconnect
- `src/venus_os_fronius_proxy/config.py` - MqttPublishConfig dataclass + Config field + load_config support
- `src/venus_os_fronius_proxy/context.py` - AppContext mqtt_pub_task/connected/queue fields
- `pyproject.toml` - aiomqtt and zeroconf dependencies
- `config/config.example.yaml` - mqtt_publish YAML section with all fields
- `tests/test_mqtt_publisher.py` - 9 tests: connect, LWT, queue, backoff, shutdown
- `tests/test_config.py` - 2 new tests: mqtt_publish defaults and overrides

## Decisions Made
- Used aiomqtt (not raw sockets) for publisher -- needs QoS 1, LWT, automatic reconnect
- Queue-based decoupling via asyncio.Queue(maxsize=100) between poll loop and publisher
- Exponential backoff from 1s to 30s cap on connection loss

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_disconnect_sets_connected_false hanging**
- **Found during:** Task 2 (TDD GREEN phase)
- **Issue:** Original test design caused inner loop to block on queue.get() after first connect, never reaching the disconnect simulation
- **Fix:** Rewired test to inject MqttError via publish side_effect during queue consumption, properly simulating mid-operation disconnect
- **Files modified:** tests/test_mqtt_publisher.py
- **Verification:** All 9 tests pass within 1s total
- **Committed in:** 641f7d8 (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test)
**Impact on plan:** Test fix necessary for correctness. No scope creep.

## Issues Encountered
- System Python is 3.9 with old pip (21.2.4) that doesn't support editable installs from pyproject.toml -- used PYTHONPATH=src workaround for all verification commands

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- mqtt_publisher.py ready for Plan 02 to wire into application lifecycle (__main__.py)
- AppContext fields ready for queue creation and task management
- MqttPublishConfig loads from YAML, ready for webapp config UI integration

## Self-Check: PASSED

- FOUND: src/venus_os_fronius_proxy/mqtt_publisher.py
- FOUND: tests/test_mqtt_publisher.py
- FOUND: commit c101a3d (Task 1)
- FOUND: commit 369b32f (Task 2 RED)
- FOUND: commit 641f7d8 (Task 2 GREEN)

---
*Phase: 25-publisher-infrastructure*
*Completed: 2026-03-22*
