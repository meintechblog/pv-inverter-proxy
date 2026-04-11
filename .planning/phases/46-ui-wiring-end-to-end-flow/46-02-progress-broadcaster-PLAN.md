---
phase: 46-ui-wiring-end-to-end-flow
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/updater/progress.py
  - tests/test_updater_progress.py
autonomous: true
requirements: [UI-02]
threat_refs: []
decisions_implemented: [D-22, D-23, D-24, D-25, D-26, D-40]

must_haves:
  truths:
    - "A single module-level asyncio.Task polls update-status.json every 500ms while current_phase not in IDLE_PHASES"
    - "Task backs off to 5s idle polling when phase is in IDLE_PHASES"
    - "Each new history[] entry emits exactly one {type: 'update_progress', data: {...}} WS message"
    - "Dedupe uses the monotonic `sequence` field on history entries — no entry is broadcast twice"
    - "Broadcaster survives a missing or malformed status file without crashing the task"
    - "Broadcaster has a clean start/stop API wired into app startup/shutdown"
  artifacts:
    - path: "src/pv_inverter_proxy/updater/progress.py"
      provides: "ProgressBroadcaster class, start(app), stop(app)"
      min_lines: 150
    - path: "tests/test_updater_progress.py"
      provides: "UI-02 progress broadcaster unit tests"
      min_lines: 200
  key_links:
    - from: "progress.py::ProgressBroadcaster._poll_loop"
      to: "updater.status.load_status + current_phase"
      via: "direct function call every 500ms (active) / 5s (idle)"
      pattern: "from pv_inverter_proxy.updater.status import (load_status|current_phase)"
    - from: "progress.py::ProgressBroadcaster._emit"
      to: "app['ws_clients'] broadcast"
      via: "json.dumps envelope with type=update_progress + data=history_entry"
      pattern: "\"type\": \"update_progress\""
---

<objective>
Build the status-file poller that drives the client's 17-phase progress checklist.

Purpose: Phase 45 already writes `update-status.json` with a `history[]` list of phase transitions. Phase 46 needs a WebSocket push so the browser can render progress live without polling a REST endpoint every 500ms. UI-02 (progress checklist) is the direct consumer.

Output: A self-contained `updater/progress.py` module with no webapp.py coupling (it imports app/ws_clients via the aiohttp `app` dict contract established in Phase 44). Wired into `create_webapp` startup in Plan 46-04.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md
@src/pv_inverter_proxy/updater/status.py
@src/pv_inverter_proxy/updater_root/status_writer.py

<interfaces>
<!-- Existing Phase 45 contracts this plan depends on. -->

From src/pv_inverter_proxy/updater/status.py:
```python
def load_status(path: Path | None = None) -> UpdateStatus: ...
def current_phase(status: UpdateStatus) -> str: ...
```

The UpdateStatus object exposes (existing Phase 45 contract — verify in status.py before coding):
- `current`: dict | None — the currently running phase entry
- `history`: list[dict] — list of past phase entries with at least {"phase": str, "at": str, "sequence": int, "error": str | None}

From src/pv_inverter_proxy/webapp.py (existing Phase 44 pattern):
```python
# app["ws_clients"]: set[web.WebSocketResponse]
# Broadcast pattern from webapp.py:1288-1315 broadcast_available_update
async def broadcast_update_progress(app, entry: dict) -> None:
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({"type": "update_progress", "data": entry})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)
```

Required new exports from updater/progress.py:
```python
ACTIVE_POLL_INTERVAL_S: float = 0.5  # D-22
IDLE_POLL_INTERVAL_S: float = 5.0
IDLE_PHASES: frozenset[str] = frozenset({"idle", "done", "rollback_done", "rollback_failed"})  # D-10 reuse

class ProgressBroadcaster:
    def __init__(self, app, *, status_path: Path | None = None,
                 active_interval: float = ACTIVE_POLL_INTERVAL_S,
                 idle_interval: float = IDLE_POLL_INTERVAL_S) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def _poll_once(self) -> None: ...  # exposed for unit tests

async def start_broadcaster(app) -> None: ...  # on_startup hook
async def stop_broadcaster(app) -> None: ...   # on_cleanup hook
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Wave 0 test scaffold — tests/test_updater_progress.py</name>
  <files>tests/test_updater_progress.py</files>
  <read_first>
    - src/pv_inverter_proxy/updater/status.py (for UpdateStatus shape + load_status signature)
    - src/pv_inverter_proxy/updater_root/status_writer.py (for PHASES frozenset + history entry schema)
    - tests/test_updater_status.py (for monkeypatching load_status in tests)
    - tests/test_websocket.py (for ws_clients fake / broadcast test patterns)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-22..D-26
  </read_first>
  <behavior>
    The test file defines (initially failing) tests for every acceptance criterion in Task 2. Tests use a fake `load_status` that the test controls via a mutable object, and a fake `app["ws_clients"]` that is a set of `FakeWs` objects recording `send_str` payloads.

    Required test functions (exact names):
    - test_poll_once_emits_one_message_per_new_history_entry
    - test_poll_once_dedupes_via_sequence_field
    - test_poll_once_with_missing_status_file_is_noop
    - test_poll_once_with_malformed_status_is_noop
    - test_poll_once_with_empty_history_emits_nothing
    - test_poll_once_envelope_has_type_update_progress
    - test_poll_once_envelope_data_includes_phase_at_sequence_error
    - test_broadcaster_uses_500ms_interval_when_phase_running
    - test_broadcaster_uses_5s_interval_when_phase_idle
    - test_broadcaster_transitions_from_idle_to_running_picks_up_within_one_interval
    - test_broadcaster_start_and_stop_cleanly_cancels_task
    - test_broadcaster_survives_load_status_exception (patched to raise)
    - test_broadcaster_survives_ws_send_exception (one ws raises ConnectionError, other succeeds)
    - test_dead_ws_clients_are_discarded_from_set
    - test_sequence_tracking_is_per_broadcaster_instance (two instances start from independent cursors)

    FakeWs class:
    ```python
    class FakeWs:
        def __init__(self, raise_on_send=False):
            self.sent: list[str] = []
            self.raise_on_send = raise_on_send
        async def send_str(self, payload: str) -> None:
            if self.raise_on_send:
                raise ConnectionResetError("fake")
            self.sent.append(payload)
    ```
  </behavior>
  <action>
    Create `tests/test_updater_progress.py` with all 15 test functions listed above as concrete runnable pytest cases using `@pytest.mark.asyncio`. Tests must fail at import time before Task 2 creates the module (RED state).

    Every test constructs a fake `app` dict: `app = {"ws_clients": {FakeWs(), FakeWs()}}`.

    For monkeypatching load_status, set the attribute at module scope:
    ```python
    monkeypatch.setattr(
        "pv_inverter_proxy.updater.progress.load_status",
        lambda *args, **kwargs: fake_status,
    )
    ```
    Where `fake_status` is a simple namespace object with `.current` and `.history` attributes (matches what the real `load_status` returns — executor should adjust if the real type is a TypedDict or dataclass).

    For `test_poll_once_dedupes_via_sequence_field`, create a fake_status with history=[{seq=1}, {seq=2}]. Call `_poll_once()` — expect 2 sends. Then append {seq=3} and call again — expect only 1 new send (total 3). Then call again with no change — expect 0 new sends. This MUST be the dedupe contract (per D-24).

    For the interval timing tests, instrument the interval selection method:
    ```python
    def test_broadcaster_uses_500ms_interval_when_phase_running(monkeypatch):
        # running phase
        b = ProgressBroadcaster(app={})
        assert b._next_interval("pip_install") == ACTIVE_POLL_INTERVAL_S
        assert b._next_interval("restarting") == ACTIVE_POLL_INTERVAL_S

    def test_broadcaster_uses_5s_interval_when_phase_idle():
        b = ProgressBroadcaster(app={})
        assert b._next_interval("idle") == IDLE_POLL_INTERVAL_S
        assert b._next_interval("done") == IDLE_POLL_INTERVAL_S
        assert b._next_interval("rollback_done") == IDLE_POLL_INTERVAL_S
        assert b._next_interval("rollback_failed") == IDLE_POLL_INTERVAL_S
    ```
    This pins the D-22 contract: 500ms active / 5s idle.

    For start/stop tests, start the broadcaster, sleep briefly, call stop, assert the task is done. Use `asyncio.wait_for(..., timeout=1.0)` to prevent hangs.
  </action>
  <acceptance_criteria>
    - File `tests/test_updater_progress.py` exists
    - `grep -c "^async def test_\|^def test_" tests/test_updater_progress.py` >= 15
    - `grep -q "test_poll_once_dedupes_via_sequence_field" tests/test_updater_progress.py`
    - `grep -q "test_broadcaster_uses_500ms_interval_when_phase_running" tests/test_updater_progress.py`
    - `grep -q "test_broadcaster_uses_5s_interval_when_phase_idle" tests/test_updater_progress.py`
    - `grep -q "FakeWs" tests/test_updater_progress.py`
    - `grep -q "update_progress" tests/test_updater_progress.py`
    - `pytest tests/test_updater_progress.py --collect-only 2>&1 | grep -qE "(ImportError|ModuleNotFoundError).*updater.progress"`
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_progress.py --collect-only 2>&1 | grep -qE "(ImportError|ModuleNotFoundError).*updater.progress"</automated>
  </verify>
  <done>Test file committed in failing RED state; only reason for failure is missing `updater.progress` module.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement updater/progress.py — polling broadcaster with sequence-based dedupe</name>
  <files>src/pv_inverter_proxy/updater/progress.py</files>
  <read_first>
    - src/pv_inverter_proxy/updater/status.py (full file — need UpdateStatus shape)
    - src/pv_inverter_proxy/webapp.py lines 1288-1315 (existing broadcast_available_update pattern)
    - tests/test_updater_progress.py (the red tests from Task 1 are the contract)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-22..D-26
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md Pattern 4 + Pitfall 4 + Pitfall 6
  </read_first>
  <behavior>
    Implement the broadcaster to satisfy all 15 tests from Task 1. No extra features, no webapp.py imports.
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/progress.py` with the following shape.

    1. Module docstring: "Phase 46 progress broadcaster: polls update-status.json and pushes update_progress WS messages. Per 46-CONTEXT.md D-22..D-26."

    2. Imports:
    ```python
    from __future__ import annotations
    import asyncio
    import json
    from pathlib import Path
    from typing import Any

    import structlog
    from aiohttp import web

    from pv_inverter_proxy.updater.status import load_status, current_phase
    ```

    3. Constants (per D-22):
    ```python
    ACTIVE_POLL_INTERVAL_S: float = 0.5
    IDLE_POLL_INTERVAL_S: float = 5.0
    IDLE_PHASES: frozenset[str] = frozenset({"idle", "done", "rollback_done", "rollback_failed"})
    _logger = structlog.get_logger(__name__)
    WS_MESSAGE_TYPE = "update_progress"
    APP_KEY = "progress_broadcaster"
    ```

    4. `ProgressBroadcaster` class (per D-23, D-24, D-25):
    ```python
    class ProgressBroadcaster:
        def __init__(
            self,
            app: web.Application | dict,
            *,
            status_path: Path | None = None,
            active_interval: float = ACTIVE_POLL_INTERVAL_S,
            idle_interval: float = IDLE_POLL_INTERVAL_S,
        ) -> None:
            self._app = app
            self._status_path = status_path
            self._active = active_interval
            self._idle = idle_interval
            self._last_sequence: int = -1
            self._task: asyncio.Task | None = None
            self._stop = asyncio.Event()

        def _next_interval(self, phase: str) -> float:
            return self._idle if phase in IDLE_PHASES else self._active

        async def _poll_once(self) -> str:
            """Poll status file once, emit new history entries, return current phase.

            Returns "unknown" on any load error. Never raises.
            """
            try:
                status = (
                    load_status(self._status_path)
                    if self._status_path is not None
                    else load_status()
                )
            except Exception:
                _logger.warning("progress_load_status_failed")
                return "unknown"

            # Extract history list defensively — the real UpdateStatus type may be
            # a dataclass or dict; handle both.
            history = getattr(status, "history", None)
            if history is None and isinstance(status, dict):
                history = status.get("history")
            if not history:
                return current_phase(status)

            new_entries = []
            for entry in history:
                seq = entry.get("sequence") if isinstance(entry, dict) else getattr(entry, "sequence", None)
                if seq is None:
                    continue
                if seq > self._last_sequence:
                    new_entries.append((seq, entry))

            if new_entries:
                new_entries.sort(key=lambda t: t[0])
                for seq, entry in new_entries:
                    payload = self._envelope(entry)
                    await self._broadcast(payload)
                    self._last_sequence = seq

            return current_phase(status)

        def _envelope(self, entry: Any) -> str:
            data = dict(entry) if isinstance(entry, dict) else {
                "phase": getattr(entry, "phase", None),
                "at": getattr(entry, "at", None),
                "sequence": getattr(entry, "sequence", None),
                "error": getattr(entry, "error", None),
            }
            return json.dumps({"type": WS_MESSAGE_TYPE, "data": data}, separators=(",", ":"))

        async def _broadcast(self, payload: str) -> None:
            clients = self._app.get("ws_clients") if hasattr(self._app, "get") else None
            if not clients:
                return
            dead = []
            for ws in list(clients):
                try:
                    await ws.send_str(payload)
                except (ConnectionError, RuntimeError, ConnectionResetError):
                    dead.append(ws)
            for ws in dead:
                try:
                    clients.discard(ws)
                except AttributeError:
                    pass

        async def _loop(self) -> None:
            while not self._stop.is_set():
                phase = await self._poll_once()
                interval = self._next_interval(phase)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    continue
                else:
                    break

        async def start(self) -> None:
            if self._task is not None:
                return
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="progress_broadcaster")

        async def stop(self) -> None:
            if self._task is None:
                return
            self._stop.set()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
    ```

    5. App lifecycle helpers (for Plan 46-04 wiring):
    ```python
    async def start_broadcaster(app: web.Application) -> None:
        b = ProgressBroadcaster(app)
        app[APP_KEY] = b
        await b.start()

    async def stop_broadcaster(app: web.Application) -> None:
        b = app.get(APP_KEY)
        if b is not None:
            await b.stop()
    ```

    Run `pytest tests/test_updater_progress.py -x -q` — all 15 tests must pass.
  </action>
  <acceptance_criteria>
    - `src/pv_inverter_proxy/updater/progress.py` exists
    - `grep -q "ACTIVE_POLL_INTERVAL_S: float = 0.5" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "IDLE_POLL_INTERVAL_S: float = 5.0" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "class ProgressBroadcaster" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "WS_MESSAGE_TYPE = \"update_progress\"" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "from pv_inverter_proxy.updater.status import load_status, current_phase" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "_last_sequence" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "async def start_broadcaster" src/pv_inverter_proxy/updater/progress.py`
    - `grep -q "async def stop_broadcaster" src/pv_inverter_proxy/updater/progress.py`
    - `! grep -q "from pv_inverter_proxy import webapp\|from pv_inverter_proxy.webapp" src/pv_inverter_proxy/updater/progress.py` (no webapp coupling)
    - `pytest tests/test_updater_progress.py -x -q` exits 0 with all 15 tests green
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_progress.py -x -q</automated>
  </verify>
  <done>All 15 progress broadcaster tests pass. Module is self-contained. Ready for Plan 46-04 to call `start_broadcaster(app)` in create_webapp and `stop_broadcaster(app)` on cleanup.</done>
</task>

</tasks>

<verification>
- `pytest tests/test_updater_progress.py -x -q` — 15/15 green
- `python -c "from pv_inverter_proxy.updater.progress import ProgressBroadcaster, start_broadcaster, stop_broadcaster, ACTIVE_POLL_INTERVAL_S, IDLE_POLL_INTERVAL_S, WS_MESSAGE_TYPE; assert ACTIVE_POLL_INTERVAL_S == 0.5; assert IDLE_POLL_INTERVAL_S == 5.0; assert WS_MESSAGE_TYPE == 'update_progress'"` exits 0
- Zero coupling to webapp.py
</verification>

<success_criteria>
UI-02 progress broadcaster backend is complete: polls at 500ms when active, 5s when idle, dedupes via monotonic `sequence` field, emits one `{type: 'update_progress', data: {phase, at, sequence, error}}` WS message per new history entry, starts/stops cleanly, survives all defensive paths (missing file, malformed status, dead WS clients).
</success_criteria>

<output>
After completion, create `.planning/phases/46-ui-wiring-end-to-end-flow/46-02-SUMMARY.md` using `@$HOME/.claude/get-shit-done/templates/summary.md`.
</output>
