---
phase: 45-privileged-updater-service
plan: 05
type: execute
wave: 5
depends_on:
  - "45-04"
files_modified:
  - src/pv_inverter_proxy/updater/maintenance.py
  - src/pv_inverter_proxy/context.py
  - src/pv_inverter_proxy/proxy.py
  - src/pv_inverter_proxy/control.py
  - src/pv_inverter_proxy/__main__.py
  - src/pv_inverter_proxy/webapp.py
  - src/pv_inverter_proxy/distributor.py
  - scripts/venus_os_slavebusy_spike.py
  - tests/test_maintenance_mode.py
  - tests/test_control_state_persistence.py
autonomous: false
requirements:
  - RESTART-01
  - RESTART-02
  - RESTART-03
  - RESTART-06
must_haves:
  truths:
    - "Venus OS SlaveBusy empirical spike is run and documented BEFORE any implementation work"
    - "AppContext gains a maintenance_mode boolean flag, wired into the Modbus server write path"
    - "During maintenance_mode, Modbus writes return exception 0x06 (SlaveBusy) OR fall through silently — decision is made based on the empirical spike result"
    - "Main service has a graceful shutdown path: SIGTERM -> maintenance_mode=True -> 3s drain -> asyncio.wait_for(drain_in_flight(), 2.0) -> stop"
    - "Pre-shutdown WebSocket broadcast 'update_in_progress' fires before the shutdown event triggers"
    - "pymodbus AsyncModbusTcpServer is verified to bind with SO_REUSEADDR; if not, a monkey-patch is applied at server construction"
    - "control.py power limit writes persist to state.json via state_file.save_state on every update"
    - "__main__.py boot-path calls state_file.load_state and is_power_limit_fresh; if fresh, re-issues the last known limit (SAFETY-09 completion)"
    - "End-to-end LXC test shows Venus OS disconnect during update is less than ~5s (vs baseline from Plan 45-04)"
  artifacts:
    - path: "scripts/venus_os_slavebusy_spike.py"
      provides: "Empirical spike test harness — run BEFORE any other task in this plan"
    - path: "src/pv_inverter_proxy/updater/maintenance.py"
      provides: "enter_maintenance_mode, exit_maintenance_mode, is_modbus_write_allowed"
      contains: "def enter_maintenance_mode"
    - path: "src/pv_inverter_proxy/proxy.py"
      provides: "Modbus server bind with SO_REUSEADDR + maintenance mode hook in async_setValues"
      contains: "SO_REUSEADDR"
    - path: "src/pv_inverter_proxy/control.py"
      provides: "save_last_limit now writes to state_file.save_state with power_limit fields"
      contains: "save_state"
    - path: "src/pv_inverter_proxy/__main__.py"
      provides: "Boot-path state.json restoration + graceful-shutdown maintenance sequence"
      contains: "maintenance_mode"
  key_links:
    - from: "webapp.py POST /api/update/start"
      to: "updater.maintenance.enter_maintenance_mode(app_ctx)"
      via: "handler call BEFORE write_trigger"
      pattern: "enter_maintenance_mode"
    - from: "proxy.py StalenessAwareSlaveContext.async_setValues"
      to: "app_ctx.maintenance_mode"
      via: "early-return gate"
      pattern: "maintenance_mode"
    - from: "control.py save_last_limit"
      to: "state_file.save_state"
      via: "direct call on every power limit update"
      pattern: "save_state\\("
---

<objective>
Close the gap between "updater works" (Plan 45-04) and "updater works AND Venus OS survives restart cleanly". Implement maintenance mode + SlaveBusy response + 3s drain + pre-shutdown WS broadcast + SO_REUSEADDR verification, AND complete the SAFETY-09 state.json wiring that Phase 43 deferred to here. This is the plan where Phase 45 becomes a real production-safe update flow.

Purpose: Prevent the known Venus OS disconnect-during-restart issue from being the permanent user-visible regression of Phase 45. The empirical spike (Task 0) is the first step — we refuse to guess about Venus OS behavior.

Output: Empirical spike + script that proves Venus OS tolerates (or rejects) SlaveBusy, maintenance mode module, state.json wiring, install.sh verification, and an end-to-end LXC test that compares Venus OS disconnect duration against the Plan 45-04 baseline.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@src/pv_inverter_proxy/state_file.py
@src/pv_inverter_proxy/proxy.py
@src/pv_inverter_proxy/control.py
@src/pv_inverter_proxy/__main__.py
@src/pv_inverter_proxy/webapp.py
@src/pv_inverter_proxy/distributor.py
@src/pv_inverter_proxy/context.py

<interfaces>
From Phase 43 state_file.py (already shipped, Plan 45-05 completes the wiring):
```python
STATE_FILE_PATH: Path = Path("/etc/pv-inverter-proxy/state.json")

@dataclass
class PersistedState:
    power_limit_pct: float | None = None
    power_limit_set_at: float | None = None
    night_mode_active: bool = False
    night_mode_set_at: float | None = None
    schema_version: int = 1

def load_state(path: Path | None = None) -> PersistedState: ...  # never raises
def save_state(state: PersistedState, path: Path | None = None) -> None: ...  # raises OSError
def is_power_limit_fresh(state, command_timeout_s, now=None) -> bool: ...
```

From proxy.py (current Modbus write path, Plan 45-05 adds maintenance gate):
```python
class StalenessAwareSlaveContext(ModbusDeviceContext):
    async def async_setValues(self, fc_as_hex, address, values):
        """Intercept writes to Model 123 registers for power control."""
        abs_addr = address
        # ... Venus OS detection ...
        if (self._control is not None
            and self._control.is_model_123_address(abs_addr, len(values))):
            self._handle_local_control_write(abs_addr, values)
            if self._distributor is not None:
                await self._distributor.distribute(...)
            return
        self.setValues(fc_as_hex, address, values)
```

From control.py (current persistence path, Plan 45-05 migrates to state_file.py):
```python
_LAST_LIMIT_FILE = "/etc/pv-inverter-proxy/.last_limit.json"  # current

def save_last_limit(self) -> None:
    """Persist current limit for restart recovery."""
    try:
        with open(_LAST_LIMIT_FILE, "w") as f:
            json.dump({"raw": ..., "source": ..., "ts": ...}, f)
```

From __main__.py (current SAFETY-09 stub — Plan 45-05 completes it):
```python
# Existing code (Phase 43 stub):
persisted = load_state()
if persisted.power_limit_pct is not None:
    fresh = is_power_limit_fresh(persisted, command_timeout_s=900.0)
    log.info("persisted_state_loaded", ..., note="restoration wiring deferred to Phase 45")
else:
    log.info("persisted_state_empty")
# Plan 45-05 replaces the log with actual re-issue to ControlState + distributor.
```
</interfaces>

## Critical research flag: Venus OS SlaveBusy

Task 0 MUST run first. The SlaveBusy strategy is NOT assumed — it is measured empirically
on the live LXC with Venus OS at 192.168.3.146 connected. If SlaveBusy causes Venus OS
to log errors or disconnect, the strategy switches to "silently drop writes during
maintenance mode" (return success without forwarding).
</context>

<tasks>

<task type="auto">
  <name>Task 0 (BLOCKING): Venus OS SlaveBusy empirical spike</name>
  <files>scripts/venus_os_slavebusy_spike.py</files>
  <action>
    Create `scripts/venus_os_slavebusy_spike.py` — a standalone pymodbus test server that:
    1. Binds on a non-conflicting port (e.g. 5503) locally on the LXC
    2. Serves a minimal Model 123 Immediate Controls register block (matching the real
       proxy's layout for Model 123 addresses 40149-40174)
    3. Returns Modbus exception 0x06 (SlaveBusy) for EVERY write to Model 123 for a
       configurable duration (default 10 seconds), then returns normal
    4. Logs every write attempt + response

    Then a second script (or same file with a CLI flag) that:
    1. Uses pymodbus client to connect to the REAL Venus OS Modbus target (192.168.3.146)
       — NO, actually we cannot do this, Venus OS is a Modbus CLIENT not server. Venus OS
       connects TO our proxy.
    2. So the spike is actually: temporarily run the spike server on the proxy's usual
       port 502 in place of the real proxy (stop pv-inverter-proxy.service first), connect
       Venus OS to it (Venus OS will auto-reconnect — it's been polling the proxy anyway),
       and observe Venus OS behavior during the SlaveBusy window.

    Correct procedure:

    ```python
    """Venus OS SlaveBusy spike — Plan 45-05 Task 0.

    Usage on LXC (root):
        systemctl stop pv-inverter-proxy.service
        python3 scripts/venus_os_slavebusy_spike.py --port 502 --slavebusy-duration 15
        # Wait ~2 minutes with the spike server running, watch Venus OS UI
        # Ctrl-C the spike, restart the real service:
        systemctl start pv-inverter-proxy.service

    What to observe on Venus OS:
        1. Does the Fronius device stay visible or disconnect?
        2. Are there errors in /var/log/messages or the Venus OS UI?
        3. After the SlaveBusy window ends, does Venus OS resume writes normally?
        4. Does the device reconnect automatically or require a manual refresh?

    Record the answers in 45-05-SUMMARY.md under section "Venus OS SlaveBusy Spike Result".
    """
    from __future__ import annotations

    import argparse
    import asyncio
    import time

    from pymodbus.server import ModbusTcpServer
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusDeviceContext,
        ModbusServerContext,
    )
    from pymodbus.exceptions import ModbusIOException


    class SlaveBusySpikeContext(ModbusDeviceContext):
        def __init__(self, slavebusy_until: float, **kwargs):
            super().__init__(**kwargs)
            self.slavebusy_until = slavebusy_until
            self.write_count = 0

        async def async_setValues(self, fc, address, values):
            self.write_count += 1
            now = time.monotonic()
            in_window = now < self.slavebusy_until
            print(
                f"[{time.strftime('%H:%M:%S')}] write #{self.write_count} "
                f"fc={fc} addr={address} values={values[:3]}... "
                f"slavebusy_active={in_window}",
                flush=True,
            )
            if in_window:
                # Raise a ModbusIOException that pymodbus translates to exception 0x06
                raise ModbusIOException("SlaveBusy (0x06)", 0x06)
            return self.setValues(fc, address, values)


    async def main(port: int, duration_s: int):
        initial = [0] * 2000
        datablock = ModbusSequentialDataBlock(1, initial)
        slavebusy_until = time.monotonic() + duration_s
        print(f"SlaveBusy window: {duration_s}s starting now")
        ctx = SlaveBusySpikeContext(slavebusy_until, hr=datablock)
        server_ctx = ModbusServerContext(devices={126: ctx}, single=False)
        server = ModbusTcpServer(context=server_ctx, address=("0.0.0.0", port))
        print(f"Spike server listening on 0.0.0.0:{port}")
        print("Press Ctrl-C to stop")
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass


    if __name__ == "__main__":
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, default=5503,
                            help="Port to listen on (use 502 to masquerade as real proxy)")
        parser.add_argument("--slavebusy-duration", type=int, default=15,
                            help="Seconds to return SlaveBusy before normal behavior")
        args = parser.parse_args()
        try:
            asyncio.run(main(args.port, args.slavebusy_duration))
        except KeyboardInterrupt:
            pass
    ```

    Then execute the spike manually on the LXC and document the result.

    Procedure (to be run by the human via the checkpoint):
    ```
    # Terminal 1 on LXC
    ssh root@192.168.3.191
    systemctl stop pv-inverter-proxy.service
    cd /opt/pv-inverter-proxy
    .venv/bin/python scripts/venus_os_slavebusy_spike.py --port 502 --slavebusy-duration 15

    # Terminal 2 (dev machine): observe Venus OS UI and/or SSH to Venus OS
    ssh root@192.168.3.146 'dbus-monitor --system "sender=com.victronenergy.pvinverter.cgwacs_ttyUSB0" 2>&1 | head -50' \
      || echo "(no direct dbus access; observe Venus OS UI manually)"

    # After spike ends (~15s + whatever duration you run the server):
    # Terminal 1:
    Ctrl-C
    systemctl start pv-inverter-proxy.service
    ```

    **Document in 45-05-SUMMARY.md**:
    - Venus OS behavior during the SlaveBusy window: disconnected / logged errors / kept trying / silent retry
    - Venus OS behavior after the window ended: auto-reconnected within Xs / required manual refresh
    - Verdict: SlaveBusy is SAFE (use it) / SlaveBusy triggers disconnect (use silent-drop instead)
    - Screenshot or log excerpt as evidence
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -c "import ast; ast.parse(open('scripts/venus_os_slavebusy_spike.py').read()); print('syntax_ok')"</automated>
  </verify>
  <done>
    - Script exists and parses
    - Human has run it on LXC and documented the verdict
    - The verdict determines the implementation in Task 2 (SlaveBusy vs silent-drop)
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 1: Run the Venus OS SlaveBusy spike on LXC + record verdict</name>
  <what-built>
    scripts/venus_os_slavebusy_spike.py — standalone pymodbus server that returns SlaveBusy (0x06) for 15 seconds
  </what-built>
  <how-to-verify>
    1. Deploy: `./deploy.sh`
    2. SSH to LXC: `ssh root@192.168.3.191`
    3. Stop the real service: `systemctl stop pv-inverter-proxy.service`
    4. Start the spike: `cd /opt/pv-inverter-proxy && .venv/bin/python scripts/venus_os_slavebusy_spike.py --port 502 --slavebusy-duration 15`
    5. In another terminal, open the Venus OS web UI (http://192.168.3.146/) and navigate to the PV Inverter section
    6. Watch Venus OS for 15s (SlaveBusy window active) and then for another 30s (spike server now accepting writes normally)
    7. Record observations:
       (a) During the SlaveBusy window, does the Fronius device show "error" or "disconnected"?
       (b) Does Venus OS log any errors? Check via Venus OS remote console or journald
       (c) After the window ends, does Venus OS automatically resume control writes (Model 123) without intervention?
       (d) Is the device's PV production display still updated via read operations during the window? (Reads should NOT be affected by our maintenance mode, only writes.)
    8. Stop the spike (Ctrl-C in terminal 1)
    9. Restart the real service: `systemctl start pv-inverter-proxy.service`
    10. Verify the real service comes back cleanly: `systemctl is-active pv-inverter-proxy.service` returns "active"

    DECISION GATE:
    - If Venus OS tolerated SlaveBusy (device stayed visible, reads continued, no reconnect needed, writes resumed automatically): proceed with Task 2 using SlaveBusy strategy (return exception 0x06)
    - If Venus OS disconnected OR logged errors: proceed with Task 2 using "silent-drop" strategy (return success without forwarding the write during maintenance mode)
    - If Venus OS behavior was mixed (e.g., retries with backoff): document the timing and pick the strategy that minimizes UI disruption. Default to silent-drop if unclear.
  </how-to-verify>
  <resume-signal>Type "slavebusy" if Venus OS tolerated SlaveBusy, "silent-drop" if not. Attach observations to the resume message.</resume-signal>
  <files>(no files — human verification only)</files>
  <action>See &lt;how-to-verify&gt; — checkpoint tasks are human-driven.</action>
  <verify>
    <automated>echo "checkpoint — human verifies per how-to-verify block"</automated>
  </verify>
  <done>User types the resume-signal value.</done>

</task>

<task type="auto" tdd="true">
  <name>Task 2: updater/maintenance.py + AppContext flag + proxy.py write gate</name>
  <files>src/pv_inverter_proxy/updater/maintenance.py, src/pv_inverter_proxy/context.py, src/pv_inverter_proxy/proxy.py, tests/test_maintenance_mode.py</files>
  <behavior>
    API:
    - `@dataclass MaintenanceState: active: bool = False, entered_at: float | None = None, reason: str = ""`
    - `async def enter_maintenance_mode(app_ctx, reason: str = "update") -> None`:
        * Sets app_ctx.maintenance_mode = True
        * Records the entered_at timestamp
        * Logs structured event `maintenance_mode_entered`
    - `async def exit_maintenance_mode(app_ctx) -> None`:
        * Sets app_ctx.maintenance_mode = False
        * Logs `maintenance_mode_exited`
        * Called only on graceful recovery (e.g., trigger write failed, we re-enable writes)
    - `async def drain_inflight_modbus(app_ctx, timeout_s: float = 2.0) -> bool`:
        * RESTART-02: waits up to `timeout_s` for in-flight Modbus transactions to complete
        * Uses an asyncio.Event or counter on the slave_ctx
        * Returns True if drained cleanly, False if timeout
        * Implementation: the slave_ctx gains an `_inflight_count: int` and an `_inflight_drained: asyncio.Event`;
          async_setValues increments on entry and decrements + sets event on exit when count==0
    - `def is_modbus_write_allowed(app_ctx, address: int) -> bool`:
        * Returns True if `not app_ctx.maintenance_mode`
        * Returns False (reject write) during maintenance mode

    AppContext extension (context.py):
    - Add `maintenance_mode: bool = False`
    - Add `maintenance_entered_at: float | None = None`

    proxy.py changes (async_setValues gate):
    - At the TOP of async_setValues (after Venus OS detection, before the Model 123 handler):
      ```python
      if (
          self._app_ctx is not None
          and getattr(self._app_ctx, "maintenance_mode", False)
          and self._control is not None
          and self._control.is_model_123_address(abs_addr, len(values))
      ):
          # Maintenance mode: reject writes per configured strategy
          if MAINTENANCE_STRATEGY == "slavebusy":
              raise ModbusIOException("SlaveBusy (maintenance mode)", 0x06)
          else:  # silent_drop
              control_log.info("maintenance_mode_write_dropped", addr=abs_addr)
              return  # Return success without forwarding
      ```
    - Define `MAINTENANCE_STRATEGY = "slavebusy"` or `"silent_drop"` as a module-level constant
      — the value chosen is based on Task 1's verdict.
    - READS are not gated — reads continue from cache during maintenance mode (explicit in
      RESTART-01: "Reads weiter aus Cache").

    In-flight counter integration:
    - Modify `async_setValues` in StalenessAwareSlaveContext:
      ```python
      async def async_setValues(self, fc_as_hex, address, values):
          self._inflight_count += 1
          try:
              # ... existing write logic ...
          finally:
              self._inflight_count -= 1
              if self._inflight_count == 0 and self._inflight_drained is not None:
                  self._inflight_drained.set()
      ```
    - Add `_inflight_count: int = 0` and `_inflight_drained: asyncio.Event | None = None` attributes
    - Expose them on app_ctx so maintenance.drain_inflight_modbus can access them

    Test cases:
    - test_enter_maintenance_mode_sets_flag: app_ctx.maintenance_mode becomes True
    - test_exit_maintenance_mode_clears_flag: after exit, maintenance_mode is False
    - test_is_modbus_write_allowed_true_when_not_active: maintenance_mode=False -> True
    - test_is_modbus_write_allowed_false_when_active: maintenance_mode=True -> False
    - test_drain_inflight_no_requests_returns_immediately: _inflight_count=0 -> returns True immediately
    - test_drain_inflight_with_pending_waits: _inflight_count=1, schedule a task that decrements after 100ms -> drain returns True within 200ms
    - test_drain_inflight_timeout: _inflight_count=1, never decrements -> returns False after timeout_s
    - test_proxy_write_rejected_in_maintenance_slavebusy: mock async_setValues with maintenance_mode=True -> raises ModbusIOException (if MAINTENANCE_STRATEGY="slavebusy")
    - test_proxy_write_silent_drop_in_maintenance: same but MAINTENANCE_STRATEGY="silent_drop" -> returns silently, distributor NOT called
    - test_proxy_read_allowed_in_maintenance: getValues called during maintenance_mode -> returns cached value normally (reads are not gated)
  </behavior>
  <action>
    Step 1: Extend context.py with two new fields:
    ```python
    maintenance_mode: bool = False
    maintenance_entered_at: float | None = None
    ```

    Step 2: Create src/pv_inverter_proxy/updater/maintenance.py implementing the API above.

    Step 3: Modify proxy.py:
    (a) Add `MAINTENANCE_STRATEGY = "slavebusy"` or `"silent_drop"` (value chosen by Task 1
        verdict — the resume-signal in Task 1 tells us which).
    (b) Add `_inflight_count` + `_inflight_drained` attributes to StalenessAwareSlaveContext.__init__
    (c) Wrap async_setValues body in try/finally that increments/decrements the counter
    (d) Add the maintenance mode gate at the TOP of async_setValues (after existing Venus OS detection,
        before the Model 123 handler)

    Step 4: Create tests/test_maintenance_mode.py with all behavior cases. Use a minimal
    stub AppContext and a mock StalenessAwareSlaveContext where needed.

    NOTE on pymodbus ModbusIOException for 0x06: the exact method of raising SlaveBusy
    depends on the pymodbus version. If raising ModbusIOException(..., 0x06) does not
    propagate as exception code 0x06, fall back to:
    ```python
    from pymodbus.pdu import ExceptionResponse
    # return ExceptionResponse(...)
    ```
    Verify on the LXC with a test client during Task 5.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_maintenance_mode.py -x -v</automated>
  </verify>
  <done>
    - maintenance.py exists with the full API
    - context.py has the new fields
    - proxy.py has the maintenance gate + in-flight counter
    - All tests pass
    - MAINTENANCE_STRATEGY value matches Task 1 verdict
  </done>
</task>

<task type="auto">
  <name>Task 3: SO_REUSEADDR verification + patch on Modbus server bind (RESTART-06)</name>
  <files>src/pv_inverter_proxy/proxy.py</files>
  <action>
    Step 1: Verify whether pymodbus 3.8+ AsyncModbusTcpServer (actually ModbusTcpServer in this
    codebase) uses SO_REUSEADDR by default. Inspect the running pymodbus version:

    ```bash
    .venv/bin/python -c "
    import pymodbus
    print('pymodbus version:', pymodbus.__version__)
    from pymodbus.server import ModbusTcpServer
    import inspect
    # Check the source for SO_REUSEADDR references
    src = inspect.getsource(ModbusTcpServer)
    print('SO_REUSEADDR in source:', 'SO_REUSEADDR' in src or 'reuse_address' in src.lower())
    "
    ```

    Step 2: If SO_REUSEADDR is already set (pymodbus 3.8 uses asyncio's `reuse_address=True`
    on the server start by default), document the verification in a comment in proxy.py:

    ```python
    # RESTART-06: pymodbus 3.8+ passes reuse_address=True to asyncio's
    # loop.create_server() by default (verified in Plan 45-05). No patch needed.
    # If pymodbus is downgraded, this assumption breaks — TODO: re-verify on upgrades.
    ```

    Step 3: If SO_REUSEADDR is NOT set, patch the server construction in run_modbus_server:

    ```python
    server = ModbusTcpServer(
        context=server_ctx,
        address=(host, port),
    )
    # RESTART-06: verify / force SO_REUSEADDR so fast restarts after
    # maintenance mode don't fail with EADDRINUSE.
    # In pymodbus 3.x, the internal asyncio server can be configured via
    # the `allow_reuse_address` or by wrapping create_server. If not
    # natively supported, we patch the server's socket options post-bind
    # via a helper that runs on the server's _listener once it exists.
    try:
        # Option A: direct attribute if pymodbus exposes it
        if hasattr(server, "allow_reuse_address"):
            server.allow_reuse_address = True
        # Option B: monkey-patch the underlying start method to set SO_REUSEADDR
        import socket as _socket
        original_start = server.server_factory if hasattr(server, "server_factory") else None
        # If neither works, fall back to catching EADDRINUSE on restart
    except Exception as e:
        logger.warning("so_reuseaddr_patch_failed", error=str(e))
    ```

    Step 4: The more robust approach if pymodbus doesn't expose SO_REUSEADDR directly —
    wrap the listener socket with an options setter. Check pymodbus source for the
    exact hook point. If no clean hook: accept that restart may fail briefly with
    EADDRINUSE, mitigate by retry-with-backoff in __main__.py's graceful startup:

    ```python
    # In __main__.py, around run_modbus_server call:
    max_retries = 5
    for attempt in range(max_retries):
        try:
            cache, control_state, server, server_task, slave_ctx = await run_modbus_server(...)
            break
        except OSError as e:
            if e.errno == 98 and attempt < max_retries - 1:  # EADDRINUSE
                log.warning("modbus_bind_eaddrinuse_retrying", attempt=attempt)
                await asyncio.sleep(1.0)
                continue
            raise
    ```

    Document whichever approach works in a comment referencing RESTART-06.

    Step 5: On LXC, verify the SO_REUSEADDR is effective:
    ```
    ss -tlnp | grep :502
    # Start service, stop it, start it again within 1 second
    systemctl restart pv-inverter-proxy && sleep 1 && systemctl restart pv-inverter-proxy
    # No error in journal expected
    ```

    NOTE: This task has no dedicated unit test — it's an infrastructure verification.
    The end-to-end test in Task 5 will exercise the fast-restart path and catch any
    regression.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -c "
import pymodbus
print('pymodbus_version:', pymodbus.__version__)
from pv_inverter_proxy.proxy import run_modbus_server
print('run_modbus_server_importable: ok')
"</automated>
  </verify>
  <done>
    - proxy.py has a documented SO_REUSEADDR verification comment OR an explicit patch
    - If patched, EADDRINUSE retry fallback exists in __main__.py
    - Task 5 end-to-end test exercises fast-restart path
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: SAFETY-09 wiring — control.py save_state + __main__.py restore-on-boot</name>
  <files>src/pv_inverter_proxy/control.py, src/pv_inverter_proxy/__main__.py, tests/test_control_state_persistence.py</files>
  <behavior>
    Part A — control.py migration to state_file.save_state:

    - Replace the existing `_LAST_LIMIT_FILE` + `_load_last_limit`/`save_last_limit` JSON
      writes with calls to `state_file.save_state` and `state_file.load_state`.
    - On every power limit UPDATE in ControlState.update_wmaxlimpct (and night mode toggle
      if applicable), call save_state with the CURRENT PersistedState loaded + updated
      power_limit_pct and power_limit_set_at fields.
    - The old `_LAST_LIMIT_FILE` and `_UI_STATE_FILE` can coexist — Plan 45-05 only adds
      a new persistence path for SAFETY-09, it does NOT remove the existing UI state
      persistence. This minimizes blast radius.

    Part B — __main__.py restore-on-boot completion:

    - Replace the existing "Phase 43 stub" log with actual restoration:
      ```python
      try:
          from pv_inverter_proxy.state_file import load_state, is_power_limit_fresh, save_state
          persisted = load_state()
          if persisted.power_limit_pct is not None:
              fresh = is_power_limit_fresh(persisted, command_timeout_s=900.0)
              if fresh:
                  # Schedule re-issue after Modbus server is up (deferred into run_with_shutdown)
                  app_ctx._pending_restore_limit_pct = persisted.power_limit_pct
                  log.info(
                      "persisted_state_restore_scheduled",
                      power_limit_pct=persisted.power_limit_pct,
                      age_s=time.time() - persisted.power_limit_set_at,
                  )
              else:
                  log.info(
                      "persisted_state_stale_ignored",
                      power_limit_pct=persisted.power_limit_pct,
                      age_s=time.time() - persisted.power_limit_set_at,
                  )
      except Exception as e:
          log.warning("persisted_state_load_failed", error=str(e))
      ```
    - Then inside run_with_shutdown, AFTER the distributor is ready and BEFORE the
      shutdown_event wait:
      ```python
      # SAFETY-09 completion: re-issue the restored power limit
      restore_pct = getattr(app_ctx, "_pending_restore_limit_pct", None)
      if restore_pct is not None:
          log.info("restoring_power_limit_from_state", pct=restore_pct)
          # Write through the same path a Venus OS write would take, so readback
          # and distribution are consistent.
          try:
              control_state.update_wmaxlimpct(int(restore_pct))
              control_state.update_wmaxlim_ena(1)
              if app_ctx.distributor is not None:
                  await app_ctx.distributor.distribute(
                      control_state.wmaxlimpct_float, control_state.is_enabled,
                  )
              log.info("power_limit_restored", pct=restore_pct)
          except Exception as e:
              log.warning("power_limit_restore_failed", error=str(e))
      ```

    Part C — graceful shutdown sequence in run_with_shutdown:

    Currently `run_with_shutdown` just cancels tasks and stops the webapp. Plan 45-05 adds
    a maintenance sequence BEFORE the task cancellation, when the shutdown was triggered
    by an update (signal-based shutdowns like kill can skip this).

    Approach: the maintenance mode is entered from the webapp side (POST /api/update/start)
    BEFORE writing the trigger — so by the time SIGTERM arrives from `systemctl restart`,
    maintenance_mode is already True and writes have been draining for ~3-5 seconds.

    ```python
    # In webapp.py update_start_handler, BEFORE write_trigger:
    from pv_inverter_proxy.updater.maintenance import enter_maintenance_mode
    from pv_inverter_proxy.webapp import broadcast_update_in_progress  # new helper

    app_ctx = request.app["app_ctx"]
    try:
        await enter_maintenance_mode(app_ctx, reason="update_requested")
    except Exception as e:
        return web.json_response(
            {"error": f"maintenance_mode_failed: {e}"},
            status=500,
        )

    # Pre-shutdown WebSocket broadcast (RESTART-03)
    try:
        await broadcast_update_in_progress(request.app)
    except Exception as e:
        log.warning("ws_broadcast_update_in_progress_failed", error=str(e))

    # Fire-and-forget 3s drain (RESTART-02) — but we return 202 immediately.
    # The drain happens BEFORE the updater actually restarts the service.
    # Since the updater runs the full backup/extract/install flow (~30s+), the
    # 3s drain timeline is automatically satisfied. We log the timing for
    # confirmation.
    app_ctx.maintenance_entered_at = time.time()

    # Now write the trigger file as before
    write_trigger(payload)
    return web.json_response({"update_id": nonce, "status_url": "/api/update/status"}, status=202)
    ```

    Also add a SIGTERM handler path in __main__.py that, IF maintenance_mode is active,
    drains and broadcasts BEFORE cancelling tasks:

    ```python
    async def _graceful_shutdown_maintenance(ctx):
        """Called from run_with_shutdown after shutdown_event is set.

        If maintenance_mode was already True (set by the update handler), this
        is a no-op for entering — we just ensure a 3s grace + drain before
        task cancellation.
        """
        if ctx.maintenance_mode:
            from pv_inverter_proxy.updater.maintenance import drain_inflight_modbus
            log.info("maintenance_shutdown_draining")
            try:
                await asyncio.wait_for(drain_inflight_modbus(ctx, timeout_s=2.0), timeout=3.0)
            except asyncio.TimeoutError:
                log.warning("maintenance_drain_timeout")
            # Give Venus OS one poll cycle to see the maintenance response
            await asyncio.sleep(3.0)
        else:
            # Unplanned shutdown (SIGTERM from admin or crash) — skip drain
            log.info("unplanned_shutdown_no_drain")
    ```

    Wire this into run_with_shutdown AFTER `await app_ctx.shutdown_event.wait()`:
    ```python
    await app_ctx.shutdown_event.wait()
    await _graceful_shutdown_maintenance(app_ctx)
    log.info("graceful_shutdown_starting")
    # ... existing task cancellation ...
    ```

    Test cases (tests/test_control_state_persistence.py):
    - test_control_save_to_state_file: set power limit, assert /etc/pv-inverter-proxy/state.json has power_limit_pct (use tmp_path)
    - test_control_load_from_state_file: pre-populate state file, instantiate ControlState, assert fresh limit restored
    - test_control_load_stale_skipped: state file with power_limit_set_at 10 years ago -> NOT restored
    - test_save_state_preserves_unrelated_fields: pre-populate state.json with night_mode_active=True, save power limit, assert night_mode_active is still True
    - test_broadcast_update_in_progress_sends_ws: mock ws_clients, call broadcast, assert each client got the message
    - test_graceful_shutdown_maintenance_drain_called: mock drain_inflight_modbus as AsyncMock, ctx.maintenance_mode=True, call _graceful_shutdown_maintenance, assert drain called
    - test_graceful_shutdown_unplanned_skip: ctx.maintenance_mode=False, assert drain NOT called
  </behavior>
  <action>
    Step 1: Modify control.py:
    (a) Import state_file
    (b) In save_last_limit, ALSO call:
    ```python
    try:
        from pv_inverter_proxy import state_file
        cur = state_file.load_state()
        cur.power_limit_pct = float(self.wmaxlimpct_raw)
        cur.power_limit_set_at = time.time()
        state_file.save_state(cur)
    except Exception as e:
        logger.warning("state_file_save_failed: %s", e)
    ```
    Leave the existing _LAST_LIMIT_FILE write intact — belt and braces.

    Step 2: Modify __main__.py per Part B above.

    Step 3: Add `broadcast_update_in_progress` helper to webapp.py:
    ```python
    async def broadcast_update_in_progress(app: web.Application) -> None:
        """RESTART-03: pre-shutdown WS broadcast."""
        message = {
            "type": "update_in_progress",
            "message": "Update starting — reconnect in ~10s",
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        clients = app.get("ws_clients", [])
        for ws in list(clients):
            try:
                await ws.send_json(message)
            except Exception as e:
                log.warning("ws_broadcast_send_failed", error=str(e))
    ```
    (Use the existing logger and datetime imports in webapp.py.)

    Step 4: Modify update_start_handler to call enter_maintenance_mode and broadcast
    BEFORE write_trigger.

    Step 5: Wire _graceful_shutdown_maintenance into run_with_shutdown.

    Step 6: Create tests/test_control_state_persistence.py with the behavior cases.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_control_state_persistence.py tests/test_maintenance_mode.py -x -v</automated>
  </verify>
  <done>
    - control.py writes to state_file on limit update (belt and braces with existing _LAST_LIMIT_FILE)
    - __main__.py restores power limit on boot if fresh
    - update_start_handler enters maintenance mode + broadcasts WS before writing trigger
    - _graceful_shutdown_maintenance called after shutdown_event
    - All tests pass
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 5: Full LXC integration test — measure Venus OS disconnect duration during update</name>
  <what-built>
    - Maintenance mode + WS broadcast + drain sequence
    - SO_REUSEADDR verified / patched
    - SAFETY-09 complete: state.json restored on boot
    - Venus OS SlaveBusy strategy live (from Task 1 verdict)
  </what-built>
  <how-to-verify>
    This test compares Venus OS disconnect duration against the Plan 45-04 baseline.
    Success = Venus OS disconnect is <= 5 seconds (ideally under 3s), device reconnects
    cleanly, no manual intervention needed.

    1. Deploy + install: `./deploy.sh && ssh root@192.168.3.191 'cd /opt/pv-inverter-proxy && bash install.sh'`

    2. Start the update + Venus OS monitor in parallel. In terminal 1:
       ```
       ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy -u pv-inverter-proxy-updater -f'
       ```

    3. In terminal 2, start a Venus OS connectivity pinger (measures disconnect window):
       ```
       while true; do
         ts=$(date +%s.%N)
         if curl -s --max-time 1 http://192.168.3.191/api/health > /dev/null; then
           echo "$ts OK"
         else
           echo "$ts DOWN"
         fi
         sleep 0.5
       done
       ```

    4. In terminal 3, get current SHA and POST an update:
       ```
       SHA=$(ssh root@192.168.3.191 'cd /opt/pv-inverter-proxy && git rev-parse HEAD')
       curl -X POST http://192.168.3.191/api/update/start \
         -H 'Content-Type: application/json' \
         -d "{\"op\":\"update\",\"target_sha\":\"$SHA\"}"
       ```

    5. Watch terminal 1 for the journal sequence. Expected before the restart:
       - `maintenance_mode_entered` (new in Plan 45-05)
       - `ws_broadcast_update_in_progress` (if any clients connected)
       - Updater's standard phase progression from Plan 45-04
       - At restart: `graceful_shutdown_starting` then main service exit
       - After bind: fresh `starting` with maintenance_mode=False (new service)

    6. In terminal 2, count the DOWN entries — each is ~500ms. Calculate:
       `disconnect_duration_s = count(DOWN) * 0.5`

    7. Verify on Venus OS web UI:
       (a) Did the Fronius PV-Inverter-Master disappear from the device list?
       (b) If yes, for how long before it reappeared?
       (c) Did Venus OS log any errors in its journal?
       (d) After update, is the PV-Inverter-Master back with the current power reading?

    8. Test maintenance mode rejection directly — POST an update while maintenance
       mode is active (second POST within the window):
       ```
       # Start one update
       curl -X POST http://192.168.3.191/api/update/start -H 'Content-Type: application/json' \
         -d "{\"op\":\"update\",\"target_sha\":\"$SHA\"}"
       # Immediately issue a Modbus write via a test client to see the rejection
       # (Can use a small python script with pymodbus to write to Model 123)
       ```
       Expected: write fails with SlaveBusy or returns silently (per Task 1 verdict).
       Cache reads continue successfully.

    9. Verify state.json persistence via a restart:
       ```
       # On LXC, set a power limit via the webapp UI or direct Modbus write
       # Then trigger a restart and verify the limit is restored
       ssh root@192.168.3.191 'cat /etc/pv-inverter-proxy/state.json'
       # Should show power_limit_pct and power_limit_set_at
       ssh root@192.168.3.191 'systemctl restart pv-inverter-proxy'
       sleep 5
       ssh root@192.168.3.191 'journalctl -u pv-inverter-proxy -n 50 | grep -i "power_limit_restored\|persisted_state"'
       ```
       Expected: log shows `power_limit_restored` or `persisted_state_restore_scheduled`.

    10. Fast-restart bind test (SO_REUSEADDR verification):
       ```
       ssh root@192.168.3.191 'systemctl restart pv-inverter-proxy && sleep 1 && systemctl restart pv-inverter-proxy && sleep 2 && systemctl is-active pv-inverter-proxy'
       ```
       Expected: "active". No EADDRINUSE in journal.

    11. Pass criteria:
       (a) Venus OS disconnect duration <= 5s (improvement over Plan 45-04 baseline)
       (b) Venus OS UI shows no persistent errors post-update
       (c) Power limit state was persisted and restored correctly
       (d) Fast-restart test passes without bind failure
       (e) Maintenance mode rejected a write during the window (Task 8 above)
  </how-to-verify>
  <resume-signal>Report: (a) Venus OS disconnect duration in seconds, (b) whether all 5 pass criteria met, (c) any unexpected observations. If (a) is over 5s or (b) fails, investigate before approving.</resume-signal>
  <files>(no files — human verification only)</files>
  <action>See &lt;how-to-verify&gt; — checkpoint tasks are human-driven.</action>
  <verify>
    <automated>echo "checkpoint — human verifies per how-to-verify block"</automated>
  </verify>
  <done>User types the resume-signal value.</done>

</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Venus OS → Modbus writes during maintenance | Gated by app_ctx.maintenance_mode |
| webapp → state.json write | Atomic via state_file.save_state (Phase 43 pattern) |
| main service boot → state.json read | Defensive via state_file.load_state (never raises) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-45-05-01 | Tampering | Maintenance mode bypass | mitigate | The gate is in async_setValues at the Modbus protocol boundary. A direct memory write to app_ctx.maintenance_mode from a compromised main service process would disable the gate, but the attacker already has code-exec. Defense-in-depth: the updater owns the actual restart timing, maintenance mode is cosmetic for Venus OS UX. |
| T-45-05-02 | Denial of service | Maintenance mode stuck on | mitigate | enter_maintenance_mode is only called from update_start_handler, which is immediately followed by write_trigger. If trigger write fails, the handler currently does NOT call exit_maintenance_mode (because the shutdown is imminent). If the updater service never starts (path unit broken), maintenance mode persists until a manual `systemctl restart pv-inverter-proxy`. Acceptable risk — Phase 47 will add a helper heartbeat to detect this case. For Phase 45: any restart (manual or otherwise) clears maintenance mode because it's in-memory. |
| T-45-05-03 | Information disclosure | state.json contains power limit | accept | Power limit % is not sensitive; no PII or credentials. Mode 0644 is standard. |
| T-45-05-04 | Denial of service | Stale state.json restore causes wrong limit | mitigate | is_power_limit_fresh with command_timeout_s/2 gate. If power_limit_set_at is more than half the command timeout ago (default 450s for 900s timeout), the limit is NOT restored — SE30K would have reverted to default. Staleness check test_control_load_stale_skipped enforces. |
| T-45-05-05 | Race | Modbus write in-flight while shutting down | mitigate | RESTART-02: drain_inflight_modbus waits up to 2s for the inflight counter to reach zero before the service kill. Combined with the 3s post-drain sleep, any write initiated before maintenance mode was set gets to complete (or times out on the Venus OS side within the Modbus client timeout). |
| T-45-05-06 | Spoofing | update_in_progress WS broadcast | accept | Non-authenticated; any LAN client that hits the WS can also trigger an update via POST. No new risk. |
| T-45-05-07 | Denial of service | SO_REUSEADDR missing -> bind fails -> StartLimit exhaustion | mitigate | Task 3 verifies + patches + has retry fallback in __main__.py. Phase 43 unit hardening (StartLimitBurst=10) gives 10 attempts in 120s, enough for even a slow pymodbus bind. |
| T-45-05-08 | Tampering | control.py dual-write inconsistency | mitigate | The belt-and-braces approach keeps _LAST_LIMIT_FILE writes AND adds state.json writes. If state.json is corrupt, load_state returns empty and main service boots without restoration — the existing _LAST_LIMIT_FILE path still works for the UI. Test test_save_state_preserves_unrelated_fields ensures the new writes don't overwrite night_mode_active. |
</threat_model>

<verification>
## Validation Strategy

| REQ | Test Type | Evidence |
|-----|-----------|----------|
| RESTART-01 | Unit (test_proxy_write_rejected_in_maintenance_*) + LXC (Task 5 step 8) | Modbus writes rejected/dropped during maintenance |
| RESTART-02 | Unit (test_drain_inflight_*) + LXC (Task 5 step 6 disconnect duration) | Drain sequence + 3s grace |
| RESTART-03 | Unit (test_broadcast_update_in_progress_sends_ws) + LXC (Task 5 step 2 journal) | WS broadcast before shutdown |
| RESTART-06 | LXC (Task 5 step 10 fast-restart) | No EADDRINUSE |
| SAFETY-09 | Unit (test_control_save_to_state_file, test_control_load_from_state_file, test_control_load_stale_skipped) + LXC (Task 5 step 9) | End-to-end state persistence + restoration |

## Failure Rollback

1. **If Venus OS still disconnects longer than Plan 45-04 baseline:** The maintenance mode
   is not helping. Check:
   - Is maintenance_mode actually True when the SIGTERM arrives? (Add debug log)
   - Is the proxy.py gate firing? (Add debug log for each Modbus write during the window)
   - Did Task 1 verdict actually match Venus OS behavior? (Re-run spike)
   - If strategy was "silent_drop" but Venus OS still disconnects: switch to "slavebusy" (or vice versa) and redeploy

2. **If state.json restoration sets the wrong limit:** Check command_timeout_s value
   (currently hardcoded to 900.0 — should match the SE30K CommandTimeout register 0xF310).
   Phase 47 may expose this as config.

3. **If SO_REUSEADDR patch breaks the server bind entirely:** `git revert` the proxy.py
   changes for Task 3, rely on retry-with-backoff in __main__.py only.

4. **If update_start_handler latency regressed above 100ms because of enter_maintenance_mode:**
   Profile. The maintenance mode enter is an in-memory flag + structlog call + WS broadcast.
   The broadcast is the only async piece — if it's slow, move it to a background task
   (fire-and-forget) and let the handler return 202 immediately.

5. **General rollback:** `git revert HEAD` removes all Plan 45-05 changes. Phase 45 is still
   functional without maintenance mode — Plan 45-04 baseline works, just with a longer
   Venus OS disconnect.
</verification>

<success_criteria>
- Venus OS SlaveBusy spike executed and documented (Task 0, 1)
- MAINTENANCE_STRATEGY chosen based on empirical evidence
- Unit tests pass: test_maintenance_mode.py, test_control_state_persistence.py
- LXC integration test shows Venus OS disconnect <= 5s during a full update cycle
- state.json persistence + boot restoration confirmed in journal
- Fast-restart (systemctl restart twice in quick succession) succeeds without EADDRINUSE
- Both research flags from the orchestrator are now resolved and documented
- Phase 45 top-line success criterion 3 (maintenance mode + 3s drain + WS broadcast + SO_REUSEADDR) satisfied
- Phase 45 top-line success criterion 5 (deliberately broken release -> single rollback) is NOT yet tested here — that requires actually tagging a broken release, which is future manual work before shipping v8.0 to production. Document as "Plan 45-05 verified success path; broken-release rollback verified in v8.0 release gate test"
</success_criteria>

<output>
After completion, create `.planning/phases/45-privileged-updater-service/45-05-SUMMARY.md` capturing:

## Venus OS SlaveBusy Spike Result (Task 1)

- Spike duration: Xs
- Venus OS observed behavior during window: <descriptive>
- Venus OS observed behavior after window: <descriptive>
- Verdict: SlaveBusy|silent-drop
- MAINTENANCE_STRATEGY value chosen: <value>
- Evidence: <log excerpt or screenshot reference>

## Venus OS Disconnect Measurement (Task 5)

- Plan 45-04 baseline: Xs (from 45-04-SUMMARY.md)
- Plan 45-05 measured: Ys
- Improvement: (X-Y)s

## SAFETY-09 End-to-End (Task 5 step 9)

- state.json contents after limit set: <JSON>
- Journal line showing restoration on boot
- Command timeout value used: 900.0 (hardcoded, Phase 47 should expose)

## SO_REUSEADDR (Task 3)

- Approach taken: native/patched/retry-fallback
- pymodbus version: X.Y.Z
- Evidence of fast-restart success

## Research Flag Resolution

- Venus OS SlaveBusy: RESOLVED (strategy=<value>, evidence=<file reference>)
- /etc permissions per-file: RESOLVED in Plan 45-02

## Remaining work for Phase 46

- UI wiring (confirmation modal, progress view, rollback button)
- CSRF + rate limit on POST /api/update/start
- Release notes Markdown rendering (CHECK-04 completion)
- A "deliberately broken release" test must be run before shipping v8.0 (rollback path verification)

## Phase 45 Completion

All 28 requirements mapped to Plans 45-01..45-05 satisfied.
</output>
