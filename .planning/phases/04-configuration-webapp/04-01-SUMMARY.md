---
phase: 04-configuration-webapp
plan: 01
subsystem: api
tags: [aiohttp, rest-api, sunspec, modbus, yaml-config]

# Dependency graph
requires:
  - phase: 02-core-proxy
    provides: proxy.py run_proxy, register_cache, sunspec_models, shared_ctx pattern
  - phase: 03-control-path
    provides: control.py ControlState, connection.py ConnectionManager, plugin reconfigure
provides:
  - aiohttp webapp with 7 REST API endpoints
  - side-by-side register viewer (SE source + Fronius target values)
  - config save/reload with atomic YAML write
  - plugin hot-reload via reconfigure method
  - WebappConfig dataclass for webapp port configuration
affects: [04-02-frontend]

# Tech tracking
tech-stack:
  added: [aiohttp]
  patterns: [aiohttp AppRunner factory, side-by-side register data model, atomic config save]

key-files:
  created:
    - src/venus_os_fronius_proxy/webapp.py
    - tests/test_webapp.py
    - tests/test_config_save.py
  modified:
    - src/venus_os_fronius_proxy/config.py
    - src/venus_os_fronius_proxy/plugin.py
    - src/venus_os_fronius_proxy/plugins/solaredge.py
    - src/venus_os_fronius_proxy/proxy.py
    - pyproject.toml

key-decisions:
  - "REGISTER_MODELS constant defines full SunSpec layout with SE source mapping for side-by-side viewer"
  - "aiohttp AppRunner pattern returns runner (caller manages site lifecycle)"
  - "Atomic config save via tempfile.mkstemp + os.replace"

patterns-established:
  - "Side-by-side register data: each field has se_value and fronius_value keys"
  - "App factory pattern: create_webapp returns AppRunner with shared_ctx/config/plugin injected"

requirements-completed: [WEB-01, WEB-02, WEB-03, WEB-04, WEB-05]

# Metrics
duration: 6min
completed: 2026-03-18
---

# Phase 4 Plan 1: Webapp API Backend Summary

**aiohttp REST API with 7 endpoints serving status, health, config CRUD, and side-by-side SE30K/Fronius register data**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-18T11:59:50Z
- **Completed:** 2026-03-18T12:05:47Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- All 7 API endpoints implemented: /, /api/status, /api/health, /api/config (GET/POST), /api/config/test, /api/registers
- Register viewer returns side-by-side SE30K source and Fronius target values per SunSpec field
- Config save/validate/reload with atomic YAML write and plugin hot-reload
- proxy.py stores raw SE30K poll data in shared_ctx for register viewer

## Task Commits

Each task was committed atomically:

1. **Task 1: Config save/validate + plugin reconfigure** - `b57cf88` (feat)
2. **Task 2: Webapp with side-by-side register API** - `474eaca` (feat)

_TDD: Both tasks followed RED-GREEN flow_

## Files Created/Modified
- `src/venus_os_fronius_proxy/webapp.py` - aiohttp app factory, 7 route handlers, REGISTER_MODELS constant
- `src/venus_os_fronius_proxy/config.py` - WebappConfig, save_config, validate_inverter_config
- `src/venus_os_fronius_proxy/plugin.py` - Added abstract reconfigure method
- `src/venus_os_fronius_proxy/plugins/solaredge.py` - Implemented reconfigure (close + update attrs)
- `src/venus_os_fronius_proxy/proxy.py` - _poll_loop stores last_se_poll in shared_ctx
- `pyproject.toml` - Added aiohttp dependency
- `tests/test_config_save.py` - 10 tests for config save/validate/reconfigure
- `tests/test_webapp.py` - 9 tests for all API endpoints
- `uv.lock` - Updated with aiohttp dependency tree

## Decisions Made
- REGISTER_MODELS constant defines full SunSpec layout with se_offset_key and se_base_addr for computing offsets into raw SE30K poll data
- aiohttp AppRunner pattern: create_webapp returns runner, caller manages TCPSite lifecycle
- Atomic config save via tempfile.mkstemp + os.replace for crash safety

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing pymodbus 3.12.1 renamed ModbusSlaveContext to ModbusDeviceContext, causing import failures in existing tests (test_connection.py, test_integration.py). This is out of scope for this plan. Logged to deferred-items.md.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All API endpoints ready for frontend consumption (Plan 02)
- Register viewer API returns structured data suitable for table rendering

---
*Phase: 04-configuration-webapp*
*Completed: 2026-03-18*
