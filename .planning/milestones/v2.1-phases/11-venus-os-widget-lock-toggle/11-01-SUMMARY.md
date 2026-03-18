---
phase: 11-venus-os-widget-lock-toggle
plan: 01
subsystem: api
tags: [modbus, lock, safety, venus-os, control-state]

# Dependency graph
requires:
  - phase: 07-webapp-power-control
    provides: ControlState source tracking, override log, edpc_refresh_loop
provides:
  - ControlState lock/unlock/check_lock_expiry methods with 900s hard cap
  - Lock check in Modbus write path (both WMaxLimPct and WMaxLim_Ena)
  - Auto-unlock in edpc_refresh_loop
  - venus_os section in dashboard snapshot
  - POST /api/venus-lock endpoint
affects: [11-venus-os-widget-lock-toggle]

# Tech tracking
tech-stack:
  added: []
  patterns: [lock-guard-in-write-path, auto-unlock-safety-timer]

key-files:
  created: []
  modified:
    - src/venus_os_fronius_proxy/control.py
    - src/venus_os_fronius_proxy/proxy.py
    - src/venus_os_fronius_proxy/dashboard.py
    - src/venus_os_fronius_proxy/webapp.py
    - tests/test_control.py
    - tests/test_proxy.py
    - tests/test_webapp.py
    - tests/test_dashboard.py

key-decisions:
  - "Lock duration hard-capped at 900s (15 min) regardless of input - safety-critical"
  - "Locked writes silently accepted but NOT forwarded - prevents Venus OS retry storms"
  - "Lock defaults to unlocked on restart - safe default, no persistence"
  - "Lock check placed before source tracking - locked writes do not change last_source"

patterns-established:
  - "Lock guard pattern: check is_locked before forwarding writes, accept locally regardless"
  - "Auto-unlock in edpc_refresh_loop: safety timer checked every iteration"

requirements-completed: [VENUS-01, VENUS-02, VENUS-03, VENUS-04]

# Metrics
duration: 8min
completed: 2026-03-18
---

# Phase 11 Plan 01: Venus OS Lock Backend Summary

**Backend lock state with 900s hard cap, proxy write-path guard, auto-unlock in edpc loop, venus_os snapshot section, and POST /api/venus-lock endpoint**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-18T21:11:13Z
- **Completed:** 2026-03-18T21:19:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 8

## Accomplishments
- ControlState extended with lock/unlock/check_lock_expiry methods and lock_remaining_s property, hard-capped at 900s
- Proxy _handle_control_write blocks forwarding when locked (both WMaxLimPct and WMaxLim_Ena paths) while still accepting writes locally
- edpc_refresh_loop auto-unlocks expired locks with broadcast notification
- Dashboard snapshot includes venus_os section with is_locked, lock_remaining_s, last_source, last_change_ts
- POST /api/venus-lock endpoint handles lock/unlock actions with validation
- 22 new tests (21 lock-specific) across 4 test files, all passing

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for all lock behavior** - `1d5a349` (test)
2. **Task 1 (GREEN): Implement lock state, proxy guard, auto-unlock, snapshot, endpoint** - `cde552c` (feat)

_Note: Task 2 (comprehensive tests) was folded into Task 1's TDD RED phase since TDD requires tests first._

## Files Created/Modified
- `src/venus_os_fronius_proxy/control.py` - Added lock/unlock/check_lock_expiry/lock_remaining_s, auto-unlock in edpc loop
- `src/venus_os_fronius_proxy/proxy.py` - Added is_locked check in both WMaxLimPct and WMaxLim_Ena write paths
- `src/venus_os_fronius_proxy/dashboard.py` - Added venus_os section to snapshot dict
- `src/venus_os_fronius_proxy/webapp.py` - Added venus_lock_handler and POST /api/venus-lock route
- `tests/test_control.py` - 12 new tests: lock defaults, lock/unlock, 900s cap, expiry, remaining_s, edpc auto-unlock
- `tests/test_proxy.py` - 4 new tests: locked writes not forwarded, source not updated, unlocked still forwards
- `tests/test_webapp.py` - 4 new tests: lock endpoint, unlock endpoint, invalid action, invalid JSON
- `tests/test_dashboard.py` - 2 new tests: venus_os section default and locked states

## Decisions Made
- Lock duration hard-capped at 900s regardless of input (safety-critical, non-negotiable)
- Locked writes silently accepted locally but NOT forwarded to inverter (prevents Venus OS retry storms)
- Lock defaults to False on startup (safe default - restart always unlocks)
- Locked writes do not call set_from_venus_os or log to override_log (lock means "pretend write didn't happen" for source tracking)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing failure in tests/test_solaredge_plugin.py::TestPoll::test_poll_reads_registers (KeyError) - unrelated to our changes, not in scope

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Backend lock infrastructure complete, ready for frontend Venus OS widget and lock toggle (Phase 11 Plan 02 if applicable)
- All 93 targeted tests passing (71 existing + 22 new)

---
*Phase: 11-venus-os-widget-lock-toggle*
*Completed: 2026-03-18*
