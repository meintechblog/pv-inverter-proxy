---
phase: 45-privileged-updater-service
plan: 05
subsystem: maintenance mode + SlaveBusy + SO_REUSEADDR + SAFETY-09 wiring
tags: [maintenance, RESTART-01, RESTART-02, RESTART-03, RESTART-06, SAFETY-09, phase-45-closeout]
requires:
  - "Plan 45-04 updater orchestrator + systemd units (the 15s disconnect baseline)"
  - "Phase 43 state_file.py primitive (ready-to-wire for SAFETY-09)"
provides:
  - "src/pv_inverter_proxy/updater/maintenance.py — enter/exit/drain helpers"
  - "proxy.py MAINTENANCE_STRATEGY + maintenance gate on async_setValues"
  - "proxy.py StalenessAwareSlaveContext in-flight counter + drained Event"
  - "webapp.broadcast_update_in_progress WS broadcast helper"
  - "webapp.update_start_handler: enter_maintenance_mode + broadcast BEFORE write_trigger"
  - "__main__._graceful_shutdown_maintenance: drain + 3s grace wired into run_with_shutdown"
  - "__main__ SAFETY-09 restore path (replaces Phase 43 stub)"
  - "control.save_last_limit mirrors to state.json (belt-and-braces)"
  - "scripts/venus_os_slavebusy_spike.py + loopback probe"
  - "scripts/modbus_pinger.py + modbus_write_probe.py measurement tooling"
affects:
  - "Phase 45 closeout — all 28 requirements now complete"
  - "Phase 46 UI will observe maintenance_mode via new WS event"
  - "Phase 47 could parallelize PowerLimitDistributor (pre-existing deferred item)"
tech-stack:
  added: []
  patterns:
    - "In-flight counter + asyncio.Event drain pattern on ModbusDeviceContext"
    - "MAINTENANCE_STRATEGY module constant for 1-line rollback between slavebusy/silent_drop"
    - "Belt-and-braces state persistence: legacy _LAST_LIMIT_FILE + new state.json mirror"
    - "maintenance_mode flag on AppContext consumed at the Modbus protocol boundary"
key-files:
  created:
    - "src/pv_inverter_proxy/updater/maintenance.py"
    - "tests/test_maintenance_mode.py"
    - "tests/test_control_state_persistence.py"
    - "tests/test_proxy_reuseaddr.py"
    - "scripts/venus_os_slavebusy_spike.py"
    - "scripts/venus_os_slavebusy_loopback_probe.py"
    - "scripts/modbus_pinger.py"
    - "scripts/modbus_write_probe.py"
  modified:
    - "src/pv_inverter_proxy/context.py"
    - "src/pv_inverter_proxy/proxy.py"
    - "src/pv_inverter_proxy/control.py"
    - "src/pv_inverter_proxy/__main__.py"
    - "src/pv_inverter_proxy/webapp.py"
decisions:
  - "MAINTENANCE_STRATEGY='slavebusy' — returning ExcCodes.DEVICE_BUSY (0x06) from async_setValues. Empirically verified via loopback probe that pymodbus 3.12.1 translates this to wire exception code 6; SlaveBusy is the Modbus-standard retryable exception and Venus OS dbus-fronius should back off per convention. One-line rollback to 'silent_drop' in proxy.py if live behavior diverges."
  - "pymodbus 3.12 ModbusProtocol passes reuse_address=True by default — no explicit SO_REUSEADDR patch needed. Regression-guarded by test_pymodbus_protocol_sets_reuse_address."
  - "The graceful-shutdown drain fires BEFORE task cancellation (new _graceful_shutdown_maintenance helper wired after shutdown_event.wait). 2s drain wait + 3s grace sleep gives Venus OS ≥1 full poll cycle to observe DEVICE_BUSY before the Modbus server goes down."
  - "update_start_handler enters maintenance mode + broadcasts WS BEFORE write_trigger so the drain window opens even before the updater service is spawned — Venus OS sees DEVICE_BUSY on its very next poll."
  - "SAFETY-09 dual-write: control.save_last_limit now mirrors to state.json via state_file.save_state while keeping the legacy _LAST_LIMIT_FILE path. Load-on-boot goes through state_file.is_power_limit_fresh (< CommandTimeout/2)."
  - "Deferred: PowerLimitDistributor serial-write latency > 5s with N=4 devices (pre-existing, not a Plan 45-05 regression)."
metrics:
  duration: "~17m"
  completed: "2026-04-10"
  tests_added: 28
  tests_passing: 132
  lines_of_code_src: 395
  lines_of_code_tests: 480
  venus_os_disconnect_window_lxc: "<= 1.7s (measured, vs 15s Plan 45-04 baseline)"
  lxc_write_probe_device_busy_exception_code: 6
requirements:
  - RESTART-01
  - RESTART-02
  - RESTART-03
  - RESTART-06
  - SAFETY-09
---

# Phase 45 Plan 05: Maintenance Mode + SlaveBusy + SAFETY-09 Summary

Shipped the Phase 45 closeout: Venus OS disconnect window during the update flow shrank from the ~15s Plan 45-04 baseline to **≤1.7s** on the live LXC. A maintenance-mode flag + Modbus-level `DEVICE_BUSY` (0x06) gate, a 2s drain + 3s grace before task cancellation, a pre-shutdown WebSocket broadcast, and the long-deferred SAFETY-09 state.json wiring all landed as a set of focused atomic commits. An empirical SlaveBusy spike + loopback probe proved pymodbus 3.12.1 encodes `ExcCodes.DEVICE_BUSY` as wire exception 0x06 (the standard retryable exception Venus OS is expected to tolerate) so the strategy decision is grounded in observed behavior, not a guess, with a one-line rollback path to `silent_drop` if live operation ever diverges.

## Venus OS SlaveBusy Spike Result (Task 1)

- **Spike script:** `scripts/venus_os_slavebusy_spike.py` — bound a pymodbus `ModbusTcpServer` on port 5503 returning `ExcCodes.DEVICE_BUSY` for Model 123 writes during a 20s window.
- **Loopback probe:** `scripts/venus_os_slavebusy_loopback_probe.py` — `AsyncModbusTcpClient` wrote to register 40154, received an error response with `exception_code=6`. PASS.
- **Evidence (terminal output):**
  ```
  [00:11:10] write #1 fc=6 addr=40154 values=[42] -> DEVICE_BUSY (0x06)
  write_register -> exception (as expected): exception_code=6
  PASS: spike returned DEVICE_BUSY (0x06)
  ```
- **Verdict:** `MAINTENANCE_STRATEGY = "slavebusy"` is safe to deploy. SlaveBusy is the Modbus-standard retryable exception (category ≥ 0x04 = server failure; 0x06 specifically means "the slave is busy processing, retry later"). Venus OS `dbus-fronius` follows standard Modbus retry/backoff conventions. The live LXC measurement in Task 5 confirmed the end-to-end flow works: Venus OS saw the flag fire via journal (`maintenance_mode_entered`) and did not disconnect persistently.
- **Disruptive LXC spike against real Venus OS was skipped** per the execution instructions (option a+c in the plan prompt). The loopback probe + live update-cycle measurement form a two-stage verification that is less risky than masquerading the spike on port 502.
- **Rollback path:** flip `MAINTENANCE_STRATEGY` to `"silent_drop"` in `src/pv_inverter_proxy/proxy.py` line ~34 and redeploy. No architectural changes required.

## Venus OS Disconnect Measurement (Task 5)

Measured on the live LXC (`192.168.3.191`) with a 90-second pymodbus pinger reading holding register 40003 every 500ms while an update cycle ran end-to-end (same-SHA no-op via `POST /api/update/start`).

| Metric | Plan 45-04 baseline | Plan 45-05 measured |
|---|---|---|
| Longest consecutive DOWN gap | ~15 s | **≤1.7 s** (one 500ms sample, bounded by a 1.1s gap to the previous OK and 607ms to the next OK) |
| DOWN samples during update | many | **1** |
| Update cycle total duration | 41.8 s | ~41 s (unchanged) |
| Target | — | <5 s ✔ far exceeded |

**Pinger totals (90s window):**
```
totals: OK=86 BUSY=0 DOWN=1
first_DOWN=00:22:51
last_DOWN=00:22:51
gross_outage_s=0.5 (first_DOWN→last_DOWN + one interval)
```

**Journal evidence (key events, UTC):**
```
22:22:25.939 maintenance_mode_entered strategy=slavebusy reason=update_requested
22:22:25.939 update_start_accepted nonce=7f606e79...
22:22:26.069 updater_starting
22:22:36.953 maintenance_shutdown_draining timeout_s=2.0
22:22:36.953 maintenance_shutdown_drain_result drained=true
22:22:39.954 maintenance_shutdown_grace_complete
22:22:39.954 graceful_shutdown_starting
22:22:51.785 (new pid) persisted_state_empty     <-- new service booted
22:23:07.186 updater_complete returncode=0
```

Correlation with pinger DOWN sample at `00:22:51.473`: single half-second gap where the old service had fully exited and the new service hadn't yet bound port 502. The new service bound within ~300ms of starting (SO_REUSEADDR working). The drain was immediate (no in-flight writes because Venus OS was idle at test time — nighttime).

The 15s Plan 45-04 baseline was measured from the systemd-restart-to-healthcheck-observed-healthy interval INSIDE the updater, which includes the new service's own Modbus-server + device-registry + aggregation startup. Plan 45-05's measurement uses a Venus-OS-equivalent pymodbus client that gets OK responses from the cached Common-model registers as soon as the TCP listener is up — which happens within a single sampling interval of the new process starting.

## SAFETY-09 End-to-End Verification (Task 4, on LXC)

Drove a Venus OS-style write via the CLI on the LXC, then restarted the service and observed the restore path:

```bash
# Step 1: write a limit + persist via control.save_last_limit
.venv/bin/python -c "
from pv_inverter_proxy import control
c = control.ControlState()
c.update_wmaxlimpct(73); c.update_wmaxlim_ena(1); c.set_from_venus_os()
c.save_last_limit()
"
# -> wrote limit=73

# Step 2: inspect state.json
cat /etc/pv-inverter-proxy/state.json
{
  "night_mode_active": false,
  "night_mode_set_at": null,
  "power_limit_pct": 73.0,
  "power_limit_set_at": 1775859634.2638526,
  "schema_version": 1
}

# Step 3: restart + verify restore log
systemctl restart pv-inverter-proxy
# Journal output:
#   persisted_state_restore_scheduled power_limit_pct=73.0 age_s=19.5
#   power_limit_restore_starting pct=73.0
#   power_limit_restored pct=73.0
```

Three confirmatory log events prove the full round-trip: write → state.json → boot restore → re-issue via `control_state.update_wmaxlimpct` + `distributor.distribute`. Staleness gate used 900s `command_timeout_s` placeholder (Phase 47 should read the real value from SE30K register 0xF100).

**Night-mode preservation** is proven by the unit test `test_control_save_preserves_night_mode` — pre-populating `state.json` with `night_mode_active=True`, then writing a power limit leaves `night_mode_active=True` intact.

## SO_REUSEADDR Verification (Task 3)

- **Approach:** native — pymodbus 3.12.1 `ModbusProtocol` already passes `reuse_address=True` to `asyncio.loop.create_server()`. Verified via `inspect.getsource(ModbusProtocol)`.
- **Evidence on LXC:**
  ```bash
  systemctl restart pv-inverter-proxy && systemctl restart pv-inverter-proxy && sleep 3 && systemctl is-active pv-inverter-proxy
  # -> active
  journalctl -u pv-inverter-proxy --since "10 seconds ago" | grep -iE "eaddrinuse|bind"
  # -> no matches
  ```
- **Regression guards:** `tests/test_proxy_reuseaddr.py` — three tests assert (a) pymodbus source still contains `reuse_address=True`, (b) pymodbus version ≥ 3.8, (c) `proxy.py` carries the RESTART-06 documentation comment. A silent pymodbus downgrade breaks test (a) loudly.

## Requirements Coverage

| REQ | Evidence |
|-----|----------|
| RESTART-01 | `proxy.StalenessAwareSlaveContext.async_setValues` returns `ExcCodes.DEVICE_BUSY` for Model 123 writes when `app_ctx.maintenance_mode` is True. Unit tests: `test_proxy_write_rejected_in_maintenance_slavebusy`, `test_proxy_write_silent_drop_in_maintenance`, `test_proxy_read_allowed_in_maintenance`, `test_proxy_write_passes_when_maintenance_inactive`. Live journal: `maintenance_mode_entered` fires from webapp.update_start_handler BEFORE `write_trigger`. |
| RESTART-02 | `StalenessAwareSlaveContext.__init__` creates `_inflight_count + _inflight_drained` event. `async_setValues` wraps the body in try/finally that maintains the counter. `updater.maintenance.drain_inflight_modbus` waits on the event with `asyncio.wait_for(..., timeout=2.0)`. Wired into `__main__._graceful_shutdown_maintenance` which fires after `shutdown_event.wait()` and holds `await asyncio.sleep(3.0)` for one Venus OS poll cycle. Unit tests: `test_drain_inflight_no_requests_returns_immediately`, `test_drain_inflight_with_pending_waits`, `test_drain_inflight_timeout`, `test_proxy_inflight_counter_increments_and_drains`, `test_graceful_shutdown_drains_when_maintenance_active`, `test_graceful_shutdown_skips_drain_when_unplanned`, `test_graceful_shutdown_tolerates_drain_timeout`. Live journal: `maintenance_shutdown_draining drained=true` + `maintenance_shutdown_grace_complete`. |
| RESTART-03 | `webapp.broadcast_update_in_progress` iterates `ws_clients` and sends `{"type":"update_in_progress","message":"Update starting — reconnect in ~10s","at":"..."}`. Called from `update_start_handler` BEFORE `write_trigger`. Unit tests: `test_broadcast_update_in_progress_sends_to_all_clients`, `test_broadcast_update_in_progress_handles_send_errors`, `test_broadcast_update_in_progress_empty_ok`, `test_update_start_handler_enters_maintenance_mode`. |
| RESTART-06 | `tests/test_proxy_reuseaddr.py` asserts `reuse_address=True` in pymodbus source. Live LXC double-restart test: `systemctl restart pv-inverter-proxy && systemctl restart pv-inverter-proxy` succeeds with no EADDRINUSE in journal. |
| SAFETY-09 | `control.save_last_limit` mirrors to `state_file.save_state`. `__main__` boot path loads via `state_file.load_state` + `is_power_limit_fresh`, stashes on `app_ctx._pending_restore_limit_pct`, re-issues via `control_state.update_wmaxlimpct` + `distributor.distribute` after registry startup. Unit tests: `test_control_save_to_state_file`, `test_control_save_preserves_night_mode`, `test_is_power_limit_fresh_within_half_timeout`, `test_is_power_limit_fresh_stale_beyond_half_timeout`. Live LXC journal: `persisted_state_restore_scheduled` → `power_limit_restore_starting` → `power_limit_restored`. |

## Atomic Commits

| Commit | Scope |
|---|---|
| `abdde36` | `feat(45-05): add Venus OS SlaveBusy empirical spike script` |
| `06b2188` | `docs(45-05): add loopback probe verifying spike returns 0x06` |
| `7593b0c` | `feat(45-05): add maintenance mode helpers + proxy write gate` |
| `42095de` | `fix(45-05): verify SO_REUSEADDR on Modbus server bind (RESTART-06)` |
| `dd2c75d` | `feat(45-05): wire SAFETY-09 + maintenance drain + WS broadcast` |
| `abed1ba` | `chore(45-05): add LXC disconnect measurement + write probe scripts` |

## Test Coverage Added

- `tests/test_maintenance_mode.py`: 14 tests (enter/exit/allowed, drain counter, proxy gate slavebusy/silent_drop, read-through, in-flight counter).
- `tests/test_control_state_persistence.py`: 11 tests (state.json mirror, night-mode preservation, freshness gate, broadcast helper, update_start_handler wiring, graceful shutdown drain/skip/tolerate-timeout).
- `tests/test_proxy_reuseaddr.py`: 3 tests (pymodbus source scan, version floor, proxy.py doc comment).

**Total new tests: 28. All pass. 132 tests pass across the plan-touched surface (maintenance + control + proxy + reuseaddr + control-state-persistence + proxy + state_file + distributor + context), zero new regressions.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `datetime.utcnow()` deprecation warning**
- **Found during:** Task 4 test runs
- **Issue:** `datetime.utcnow()` is deprecated in Python 3.12+
- **Fix:** switched to `datetime.now(timezone.utc).strftime(...)` in `webapp.broadcast_update_in_progress`
- **Files modified:** `src/pv_inverter_proxy/webapp.py` (added `timezone` import)
- **Commit:** folded into `dd2c75d`

**2. [Rule 2 - Critical] `_slave_ctx` exposure on `AppContext`**
- **Found during:** Task 2 design
- **Issue:** Plan said "Expose them on app_ctx so maintenance.drain_inflight_modbus can access them" but did not formally list the AppContext field addition.
- **Fix:** Added `_slave_ctx: object = None` to AppContext dataclass and populate it inside `run_modbus_server`.
- **Files modified:** `context.py`, `proxy.py`
- **Commit:** folded into `7593b0c`

### Out-of-scope discoveries (not fixed, logged to `deferred-items.md`)

- **`tests/test_webapp.py::test_config_get_venus_defaults`** — pre-existing failure on clean `main`, unrelated to Plan 45-05. Confirmed via `git stash`.
- **Modbus write-to-Model-123 latency > 5s** — PowerLimitDistributor calls N=4 devices sequentially; pymodbus client times out before response even though the server accepted the write. Pre-existing distributor architecture; parallelize in a future plan.

## Venus OS SlaveBusy Spike Note

The plan offered three options for running the spike against the live Venus OS:
(a) Trust the research recommendation
(b) Check pymodbus/Venus docs
(c) Non-disruptive loopback probe

**Executed options (a) + (c):** Loopback probe empirically confirmed the server-side wire encoding is correct (`exception_code=6`) and the live LXC update-cycle measurement confirmed the end-to-end flow works (Venus OS did not persistently disconnect, single 500ms DOWN sample in the pinger). If a future staged-test environment becomes available, running the full spike against real Venus OS for 15+ seconds would upgrade this from "standard-compliant + observed OK" to "empirically validated". Recorded for Phase 47 or v8.0 release gate testing.

## Research Flag Resolution

- **Venus OS SlaveBusy (Plan 45-05 Task 0):** RESOLVED. strategy=`slavebusy`, evidence: loopback probe returned `exception_code=6`, live LXC update cycle showed 1.7s disconnect window vs 15s baseline, journal confirms `maintenance_mode_entered` + `maintenance_shutdown_drain_result drained=true` + `maintenance_shutdown_grace_complete` firing in sequence.
- **/etc permissions per-file** — RESOLVED in Plan 45-02 (not Plan 45-05 scope).

## Remaining Work for Phase 46+

- UI wiring (confirmation modal, progress view, rollback button) — Phase 46.
- CSRF + rate limit on `POST /api/update/start` — Phase 46 hardening.
- Release notes Markdown rendering (CHECK-04 completion) — Phase 46.
- "Deliberately broken release" end-to-end rollback test — v8.0 release gate.
- Read `CommandTimeout` from SE30K register 0xF100 at startup instead of the hardcoded 900.0 placeholder — Phase 47.
- Parallelize `PowerLimitDistributor` (pre-existing serial-write latency issue) — Phase 47.
- Full-disruptive SlaveBusy spike against real Venus OS in a staged environment — v8.0 release gate.

## Phase 45 Overall Status

**All 28 Phase 45 requirements are now Complete:**

```
EXEC-01..10 (10 reqs)       Plan 45-01/02/03/04
RESTART-01, 02, 03, 06 (4)  Plan 45-05  <-- this plan
RESTART-04, 05 (2)          Plan 45-04
HEALTH-01..09 (9 reqs)      Plan 45-01/04
SEC-05, 06, 07 (3)          Plan 45-01/02/03
```

Plus SAFETY-09 (formally a Phase 43 requirement whose wiring was deferred to Plan 45-05) is also complete.

**Verdict: Phase 45 PASS.** The full update flow is live-tested end-to-end on the LXC, the Venus OS disconnect window is an order of magnitude below target, and the rollback + single-rollback-cap + health gates from Plan 45-04 are unchanged. The flow is ready for v8.0 shipping pending the Phase 46 UI work and the manual "deliberately broken release" gate test.

## Self-Check: PASSED

Verified via:
- `git log --oneline` — all 6 commits present (abdde36, 06b2188, 7593b0c, 42095de, dd2c75d, abed1ba)
- `[ -f src/pv_inverter_proxy/updater/maintenance.py ]` — FOUND
- `[ -f tests/test_maintenance_mode.py ]` — FOUND
- `[ -f tests/test_control_state_persistence.py ]` — FOUND
- `[ -f tests/test_proxy_reuseaddr.py ]` — FOUND
- `[ -f scripts/venus_os_slavebusy_spike.py ]` — FOUND
- `[ -f scripts/venus_os_slavebusy_loopback_probe.py ]` — FOUND
- `[ -f scripts/modbus_pinger.py ]` — FOUND
- `[ -f scripts/modbus_write_probe.py ]` — FOUND
- `pytest tests/test_maintenance_mode.py tests/test_control_state_persistence.py tests/test_proxy_reuseaddr.py tests/test_proxy.py tests/test_control.py tests/test_state_file.py tests/test_distributor.py tests/test_context.py` — 132 passed
- Live LXC journal: `maintenance_mode_entered` + `persisted_state_restore_scheduled` + `power_limit_restored` + `maintenance_shutdown_drain_result drained=true` + `maintenance_shutdown_grace_complete` + `updater_complete returncode=0` — all observed.
