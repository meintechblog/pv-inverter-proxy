---
phase: 02-core-proxy-read-path
plan: 02
subsystem: proxy
tags: [modbus-tcp, pymodbus, asyncio, sunspec, solaredge, polling, cache-staleness]

# Dependency graph
requires:
  - phase: 02-core-proxy-read-path
    provides: InverterPlugin ABC, PollResult, build_initial_registers(), apply_common_translation(), RegisterCache
provides:
  - SolarEdgePlugin implementing InverterPlugin (polls SE30K with two read_holding_registers calls)
  - Proxy server orchestration (ModbusTcpServer + async poller on same event loop)
  - StalenessAwareSlaveContext (returns Modbus SLAVE_FAILURE when cache stale)
  - Entry point via python -m venus_os_fronius_proxy
  - Synthesized Model 120 nameplate from SE30K datasheet specs
  - Common Model identity translation (SolarEdge -> Fronius)
affects: [03-power-control-write-path, 04-webapp-config]

# Tech tracking
tech-stack:
  added: [pymodbus.client.AsyncModbusTcpClient, pymodbus.server.ModbusTcpServer]
  patterns: [asyncio.gather for concurrent server+poller, polling-with-retry in tests, unique ports per integration test]

key-files:
  created:
    - src/venus_os_fronius_proxy/plugins/solaredge.py
    - src/venus_os_fronius_proxy/proxy.py
    - src/venus_os_fronius_proxy/__main__.py
    - tests/test_solaredge_plugin.py
    - tests/test_proxy.py
  modified: []

key-decisions:
  - "Raising plain Exception in StalenessAwareSlaveContext.getValues() because pymodbus request handler catches all exceptions and returns ExceptionResponse(SLAVE_FAILURE=0x04)"
  - "Each integration test uses unique port via _next_port() to avoid address-in-use conflicts from TCP TIME_WAIT"
  - "Unit ID filter test handles both isError() and ModbusIOException since pymodbus client framing may raise on unknown-slave responses"

patterns-established:
  - "Integration tests start real ModbusTcpServer on high ports with mock plugins"
  - "Polling-with-retry helper reads registers in tight loop instead of fixed asyncio.sleep"
  - "Plugin owns all brand-specific register mapping (Model 120, Common overrides)"

requirements-completed: [PROXY-01, PROXY-03, PROXY-06, PROXY-09]

# Metrics
duration: 9min
completed: 2026-03-18
---

# Phase 2 Plan 2: SolarEdge Plugin and Proxy Server Summary

**SolarEdge SE30K plugin polling via AsyncModbusTcpClient, proxy server on unit ID 126 with staleness-aware context returning Modbus exception 0x04 after 30s without successful poll**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-18T07:31:25Z
- **Completed:** 2026-03-18T07:40:26Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- SolarEdgePlugin reads Common (67 regs at 40002) and Inverter (52 regs at 40069) in two separate calls, synthesizes Model 120 nameplate, provides Fronius identity overrides
- Proxy orchestrates ModbusTcpServer + background poller as concurrent asyncio tasks, with configurable poll_interval for fast testing
- StalenessAwareSlaveContext rejects reads when cache is stale, ensuring Venus OS gets Modbus errors instead of outdated data
- Full SunSpec model chain walkable end-to-end: Header -> 1 -> 103 -> 120 -> 123 -> 0xFFFF
- 101 total tests passing (75 existing + 17 plugin unit + 9 proxy integration)

## Task Commits

Each task was committed atomically (TDD: RED -> GREEN):

1. **Task 1: SolarEdge SE30K plugin**
   - `bdd65c3` (test) - 17 failing tests for plugin interface, polling, overrides, Model 120
   - `4447b01` (feat) - SolarEdgePlugin implementation passing all 17 tests

2. **Task 2: Proxy server orchestration with staleness-aware context**
   - `6519447` (test) - 9 failing integration tests for server, discovery, cache, staleness
   - `8f033bf` (feat) - proxy.py + __main__.py implementation passing all 9 tests

## Files Created/Modified
- `src/venus_os_fronius_proxy/plugins/solaredge.py` - SolarEdge SE30K plugin implementing InverterPlugin ABC
- `src/venus_os_fronius_proxy/proxy.py` - Proxy orchestration: StalenessAwareSlaveContext, _poll_loop, _start_server, run_proxy
- `src/venus_os_fronius_proxy/__main__.py` - Entry point for python -m venus_os_fronius_proxy
- `tests/test_solaredge_plugin.py` - 17 unit tests for SolarEdge plugin
- `tests/test_proxy.py` - 9 integration tests for proxy server

## Decisions Made
- Used plain `raise Exception()` in StalenessAwareSlaveContext instead of `ModbusIOException(exception_code=0x04)` because pymodbus 3.8.6 `ModbusIOException.__init__` does not accept `exception_code` parameter; the request handler's generic except clause returns `ExceptionResponse(SLAVE_FAILURE)` for any raised exception
- Each integration test allocates a unique port via `_next_port()` counter to prevent TCP `EADDRINUSE` from socket TIME_WAIT between tests
- Unit ID test handles both `result.isError()` and `ModbusIOException` since pymodbus client framing may raise on unknown-slave error responses

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ModbusIOException constructor mismatch**
- **Found during:** Task 2 (proxy.py StalenessAwareSlaveContext)
- **Issue:** Plan specified `ModbusIOException(exception_code=0x04)` but pymodbus 3.8.6 `ModbusIOException.__init__` signature is `(string, function_code)` -- `exception_code` is not a valid parameter
- **Fix:** Changed to `raise Exception("Cache stale...")` which pymodbus request handler catches and converts to `ExceptionResponse(SLAVE_FAILURE=0x04)` automatically
- **Files modified:** src/venus_os_fronius_proxy/proxy.py
- **Verification:** Staleness test passes, server returns error to client when cache is stale
- **Committed in:** 8f033bf

**2. [Rule 1 - Bug] Fixed port reuse conflicts in integration tests**
- **Found during:** Task 2 (test_proxy.py)
- **Issue:** All tests sharing a single fixture on port 15502 caused `EADDRINUSE` from TCP TIME_WAIT between test teardowns
- **Fix:** Replaced shared fixture with per-test port allocation via `_next_port()` counter and inline setup/teardown
- **Files modified:** tests/test_proxy.py
- **Verification:** All 9 integration tests pass reliably without port conflicts
- **Committed in:** 8f033bf

**3. [Rule 1 - Bug] Fixed unit ID test for pymodbus client framing behavior**
- **Found during:** Task 2 (test_proxy.py)
- **Issue:** When server rejects unknown unit ID, pymodbus sends exception response that client framer cannot decode, raising `ModbusIOException` instead of returning `result.isError()`
- **Fix:** Test now handles both `isError()` and `ModbusIOException` as valid error indicators
- **Files modified:** tests/test_proxy.py
- **Verification:** test_unit_id_126_only passes consistently
- **Committed in:** 8f033bf

---

**Total deviations:** 3 auto-fixed (3 bugs)
**Impact on plan:** All fixes necessary for pymodbus 3.8.6 API compatibility and test reliability. No scope change.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Complete read-path proxy ready for Phase 3 (power control write path)
- SolarEdgePlugin provides the connection infrastructure for write-path extensions
- Model 123 header is in the register chain; Phase 3 will add write handling for WMaxLimPct
- proxy.py structure (asyncio.gather server+poller) can accommodate additional tasks
- 101 tests provide regression safety for Phase 3 development

## Self-Check: PASSED

All 5 files verified present. All 4 task commits verified in git log.

---
*Phase: 02-core-proxy-read-path*
*Completed: 2026-03-18*
