---
phase: 46-ui-wiring-end-to-end-flow
plan: 02
subsystem: updater
tags: [progress-broadcaster, websocket, asyncio, ui-02]
requires:
  - updater.status.load_status (Phase 45)
  - updater.status.current_phase (Phase 45)
  - app["ws_clients"] aiohttp dict contract (Phase 44)
provides:
  - pv_inverter_proxy.updater.progress.ProgressBroadcaster
  - pv_inverter_proxy.updater.progress.start_broadcaster
  - pv_inverter_proxy.updater.progress.stop_broadcaster
  - pv_inverter_proxy.updater.progress.ACTIVE_POLL_INTERVAL_S
  - pv_inverter_proxy.updater.progress.IDLE_POLL_INTERVAL_S
  - pv_inverter_proxy.updater.progress.IDLE_PHASES
  - pv_inverter_proxy.updater.progress.WS_MESSAGE_TYPE
affects:
  - Plan 46-04 (wires start/stop_broadcaster into create_webapp lifecycle)
  - Plan 46-03 (frontend consumes `update_progress` WS messages)
tech_stack:
  added: []
  patterns:
    - asyncio.Task + asyncio.Event stop-signal polling loop
    - JSON envelope broadcast via app["ws_clients"] set (Phase 44 pattern)
    - Monotonic sequence dedupe with history-index fallback
key_files:
  created:
    - src/pv_inverter_proxy/updater/progress.py (302 lines)
    - tests/test_updater_progress.py (496 lines, 16 tests)
  modified: []
decisions:
  - D-22: 500ms active / 5s idle polling intervals
  - D-23: Envelope {type: update_progress, data: {phase, at, sequence, error}}
  - D-24: Dedupe via monotonic sequence (with history-index fallback)
  - D-25: Per-instance last_sequence cursor (enables replay on reconnect)
  - D-26: 17-phase vocabulary consumed from updater_root.status_writer.PHASES
  - D-40: New module under pv_inverter_proxy.updater.progress
requirements: [UI-02]
metrics:
  duration: ~45m
  completed: 2026-04-11
  tasks: 2
  files_created: 2
  tests_added: 16
  tests_passing: 16
---

# Phase 46 Plan 02: Progress Broadcaster Summary

Status-file polling WebSocket broadcaster with monotonic sequence dedupe that pushes `update_progress` messages to every connected browser client while the Phase 45 update engine runs.

## Overview

Phase 45 writes `/etc/pv-inverter-proxy/update-status.json` with a `history[]` list of phase transitions (17-phase vocabulary from `updater_root/status_writer.py::PHASES`). Phase 46 needs a WebSocket push so the UI's progress checklist renders live without fetching a REST endpoint every 500ms.

This plan delivers a zero-dependency, self-contained broadcaster module in `pv_inverter_proxy.updater.progress` with no coupling to `webapp.py`. It talks to the aiohttp `app` dict contract (`app["ws_clients"]`) established in Phase 44 and exposes `start_broadcaster(app)` / `stop_broadcaster(app)` hooks for Plan 46-04 to wire into `create_webapp` lifecycle.

## What Was Built

### `src/pv_inverter_proxy/updater/progress.py`

**Constants (D-22, D-23):**
- `ACTIVE_POLL_INTERVAL_S = 0.5` — 500ms poll while update running
- `IDLE_POLL_INTERVAL_S = 5.0` — 5s poll when idle
- `IDLE_PHASES = frozenset({"idle", "done", "rollback_done", "rollback_failed"})` — D-10 reuse
- `WS_MESSAGE_TYPE = "update_progress"`
- `APP_KEY = "progress_broadcaster"` — aiohttp app dict key

**`ProgressBroadcaster` class:**
- `__init__(app, *, status_path=None, active_interval, idle_interval)` — injected app dict + overridable intervals for tests
- `_next_interval(phase) -> float` — active/idle selector gated on `IDLE_PHASES`
- `_poll_once() -> str` — reads status file, emits new entries, returns observed phase. Never raises.
- `_extract_history(status)` — defensive history extractor (dataclass or dict)
- `_emit_new_entries(history)` — iterates with `enumerate`, compares sequence to `_last_sequence`, broadcasts in order, advances cursor
- `_entry_sequence(entry, fallback_index)` — prefers explicit `sequence` field, falls back to `history[]` index, rejects `bool`/non-int values
- `_envelope(entry, sequence)` — builds JSON envelope, backfills missing `sequence`/`error` fields
- `_broadcast(payload)` — mirrors Phase 44 `broadcast_available_update` pattern: send to every client, evict dead ones on `ConnectionError`/`RuntimeError`/`ConnectionResetError`
- `_loop()` — polls forever, sleeps on `asyncio.wait_for(stop_event.wait(), timeout=interval)` so stop is instant
- `start()` / `stop()` — idempotent lifecycle with `asyncio.Event` signalling and 2s cancel fallback

**Module helpers:**
- `start_broadcaster(app)` — on_startup hook: instantiate + store in `app[APP_KEY]` + start
- `stop_broadcaster(app)` — on_cleanup hook: stop the singleton if present

### `tests/test_updater_progress.py` (16 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_poll_once_emits_one_message_per_new_history_entry` | 3-entry history → 3 messages per client |
| 2 | `test_poll_once_dedupes_via_sequence_field` | D-24 dedupe contract over 3 sequential polls |
| 3 | `test_poll_once_with_missing_status_file_is_noop` | Empty UpdateStatus → 0 sends |
| 4 | `test_poll_once_with_malformed_status_is_noop` | `load_status` raises → no crash, 0 sends |
| 5 | `test_poll_once_with_empty_history_emits_nothing` | `history=[]` → 0 sends |
| 6 | `test_poll_once_envelope_has_type_update_progress` | Envelope type field (D-23) |
| 7 | `test_poll_once_envelope_data_includes_phase_at_sequence_error` | Envelope data fields (D-23) |
| 8 | `test_broadcaster_uses_500ms_interval_when_phase_running` | D-22 active interval |
| 9 | `test_broadcaster_uses_5s_interval_when_phase_idle` | D-22 idle interval + IDLE_PHASES set |
| 10 | `test_broadcaster_transitions_from_idle_to_running_picks_up_within_one_interval` | Live loop picks up state change |
| 11 | `test_broadcaster_start_and_stop_cleanly_cancels_task` | Lifecycle — `_task is None` after stop |
| 12 | `test_broadcaster_survives_load_status_exception` | Task survives `OSError` from loader |
| 13 | `test_broadcaster_survives_ws_send_exception` | Bad client evicted, good client still receives |
| 14 | `test_dead_ws_clients_are_discarded_from_set` | Multiple dead clients all evicted |
| 15 | `test_poll_once_falls_back_to_index_when_sequence_field_missing` | **Phase 45 compat** (deviation fix) |
| 16 | `test_sequence_tracking_is_per_broadcaster_instance` | Two instances track cursors independently |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sequence-field dedupe was incompatible with Phase 45's status writer**
- **Found during:** Task 2 (reading `updater_root/status_writer.py` to verify history entry shape)
- **Issue:** Plan Task 2 prescribed:
  ```python
  seq = entry.get("sequence") if isinstance(entry, dict) else getattr(entry, "sequence", None)
  if seq is None:
      continue
  ```
  Phase 45's `status_writer.py::write_phase` (lines 112-130) writes history entries as `{"phase": ..., "at": ..., "error"?: ...}` — **no `sequence` field**. With the plan's code, every real Phase 45 entry would be silently skipped and the UI checklist would never update.
- **Fix:** Broadcaster now uses `enumerate(history)` and falls back to the entry's index in `history[]` as the sequence when the explicit field is missing. This matches RESEARCH.md Pattern 4 line 239: *"`sequence` is the index of the entry in `history[]`"*. The envelope always carries a numeric `sequence` so client-side dedupe contract stays intact.
- **Test coverage:** Added `test_poll_once_falls_back_to_index_when_sequence_field_missing` to pin the fallback contract. The other 15 tests continue to use explicit sequences, proving both paths work.
- **Files modified:** `src/pv_inverter_proxy/updater/progress.py`, `tests/test_updater_progress.py`
- **Commit:** `ef62a35`

**2. [Rule 2 - Missing critical functionality] Task loop exception safety**
- **Found during:** Task 2 implementation review
- **Issue:** The plan's `_loop` had no exception handler around `_poll_once`. A downed broadcaster task would silently stop without any UI error signal — the 17-phase checklist would freeze and the user would have no way to detect it.
- **Fix:** Added a defensive `try/except Exception` around `_poll_once` in `_loop`. Transient failures log `progress_poll_loop_error` and fall through to the idle interval without breaking the loop. Also added defensive `try/except` in `_broadcast` for unexpected `Exception` so a single pathological client can't take the broadcaster down.
- **Files modified:** `src/pv_inverter_proxy/updater/progress.py`
- **Commit:** `ef62a35`

## Commits

- `17bcadd` — test(46-02): add failing tests for progress broadcaster (Task 1, RED)
- `ef62a35` — feat(46-02): implement progress broadcaster for UI-02 (Task 2, GREEN + fallback test)

## Verification Results

```
$ PYTHONPATH=src pytest tests/test_updater_progress.py -x -q
................                                                         [100%]
16 passed in 0.42s

$ python -c "from pv_inverter_proxy.updater.progress import ProgressBroadcaster, start_broadcaster, stop_broadcaster, ACTIVE_POLL_INTERVAL_S, IDLE_POLL_INTERVAL_S, WS_MESSAGE_TYPE; assert ACTIVE_POLL_INTERVAL_S == 0.5; assert IDLE_POLL_INTERVAL_S == 5.0; assert WS_MESSAGE_TYPE == 'update_progress'"
# exit 0
```

All plan acceptance criteria pass:
- File `src/pv_inverter_proxy/updater/progress.py` exists (302 lines)
- All 8 required grep patterns present (`ACTIVE_POLL_INTERVAL_S: float = 0.5`, `IDLE_POLL_INTERVAL_S: float = 5.0`, `class ProgressBroadcaster`, `WS_MESSAGE_TYPE = "update_progress"`, `from pv_inverter_proxy.updater.status import current_phase, load_status`, `_last_sequence`, `async def start_broadcaster`, `async def stop_broadcaster`)
- Zero coupling to `webapp.py` (`grep webapp` returns nothing)
- 16/16 tests green (plan required ≥15)

## Handoff Notes

**For Plan 46-04 (create_webapp wiring):**

```python
from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster

app.on_startup.append(start_broadcaster)
app.on_cleanup.append(stop_broadcaster)
```

The singleton is stored under `app["progress_broadcaster"]` if any other code needs a handle.

**For Plan 46-03 (frontend):**

Client handler for `{type: "update_progress", data: {phase, at, sequence, error}}`:
- Dedupe via `data.sequence` — monotonic per update run
- On WS reconnect, fetch `/api/update/status`, replay every `history[]` entry with `sequence > last_seen`, then resume live WS (D-25)
- `data.phase` values map to the 17-phase checklist in `updater_root.status_writer.PHASES`

**Sequence semantics note:** Until Phase 45 is bumped to write an explicit `sequence` field, the broadcaster synthesizes sequence from the history index. The client should treat `sequence` as opaque and monotonic per update run, not as a globally unique identifier.

## Known Stubs

None. All code paths wired to real (or test-faked) data.

## Self-Check: PASSED

- [x] `src/pv_inverter_proxy/updater/progress.py` exists (302 lines)
- [x] `tests/test_updater_progress.py` exists (496 lines, 16 tests)
- [x] Commit `17bcadd` present in `git log --oneline`
- [x] Commit `ef62a35` present in `git log --oneline`
- [x] `pytest tests/test_updater_progress.py` green (16/16)
- [x] No `webapp` imports in `progress.py`
