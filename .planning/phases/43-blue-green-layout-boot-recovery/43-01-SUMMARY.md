---
phase: 43-blue-green-layout-boot-recovery
plan: 01
subsystem: infra
tags: [state-persistence, atomic-write, safety-09, json, stdlib]

requires:
  - phase: 42
    provides: v7.0 service foundation, /etc/pv-inverter-proxy config directory convention
provides:
  - PersistedState schema (power_limit_pct, night_mode_active, timestamps, schema_version)
  - Atomic JSON read/write helpers (os.replace pattern)
  - CommandTimeout/2 staleness gate for boot-time power-limit restore
affects: [43-04-install-migration-wiring, 45-privileged-updater]

tech-stack:
  added: []
  patterns:
    - "Atomic file write via tempfile + os.replace (same directory for POSIX atomicity)"
    - "Defensive JSON load: all error paths return safe defaults, never raise"
    - "Unknown-key tolerance: dataclass(**{k:v for k,v in data.items() if k in __dataclass_fields__})"
    - "File mode 0o644 enforced via explicit os.chmod after os.replace"

key-files:
  created:
    - src/pv_inverter_proxy/state_file.py
    - tests/test_state_file.py
  modified: []

key-decisions:
  - "State file lives in /etc/pv-inverter-proxy/ (same as config.yaml) — single pv-proxy-owned directory"
  - "Parent-missing raises FileNotFoundError loudly — install bug, not runtime condition to swallow"
  - "File mode 0o644 (world-readable) — contents are not sensitive; enables root helper reads post-update"
  - "schema_version=1 gate rejects forward/backward incompatible files defensively"
  - "is_power_limit_fresh takes explicit now parameter for deterministic testing (no time.time mocking)"

patterns-established:
  - "Atomic write primitive (tempfile + os.replace + chmod) — reusable in Phase 45 for trigger.json/status.json"
  - "Defensive read with structlog warnings — all failure modes logged with component=state_file"

requirements-completed: [SAFETY-09]

duration: ~10min
completed: 2026-04-10
---

# Phase 43 Plan 01: State File Module Summary

**SAFETY-09 persistence primitive: PersistedState dataclass with atomic JSON write/defensive read helpers for SE30K power limit and night mode survival across process restarts, gated by CommandTimeout/2 staleness check.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-10T12:40Z
- **Completed:** 2026-04-10T12:50Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- `src/pv_inverter_proxy/state_file.py` (157 lines): self-contained persistence module with zero systemd/service coupling
- `tests/test_state_file.py` (138 lines): 13 unit tests, all passing, covering every documented behavior + error path
- Atomic-write primitive available for Phase 45 reuse (update-trigger.json, update-status.json)
- Staleness gate (`is_power_limit_fresh`) ready for Phase 45 boot-restore wiring

## Task Commits

1. **Task 1: state_file.py module** — `66d5420` (feat)
2. **Task 2: 13 unit tests** — `ac38f6a` (test)

## Files Created

- `src/pv_inverter_proxy/state_file.py` — PersistedState dataclass, load_state, save_state, is_power_limit_fresh, STATE_FILE_PATH
- `tests/test_state_file.py` — 13 pytest functions covering all documented behaviors

## API & Usage Pattern

```python
from pv_inverter_proxy.state_file import (
    PersistedState, load_state, save_state, is_power_limit_fresh, STATE_FILE_PATH,
)

# --- Write on state change ---
save_state(PersistedState(
    power_limit_pct=75.0,
    power_limit_set_at=time.time(),
))

# --- Read on boot, restore only if still fresh ---
state = load_state()  # never raises
if is_power_limit_fresh(state, command_timeout_s=900.0):
    # Re-issue the persisted limit to SE30K (Phase 45 work)
    modbus_client.write_wmaxlimpct(state.power_limit_pct)
```

**Public contract guarantees:**
- `load_state()` NEVER raises. All errors (missing, corrupt, wrong type, wrong schema, OSError) return `PersistedState()` defaults.
- `save_state()` is atomic: temp file in same directory + `os.replace`. No leftover `.tmp` on success.
- `save_state()` DOES raise `FileNotFoundError` if parent directory missing (install bug, not runtime condition).
- `save_state()` sets mode `0o644` via explicit `os.chmod` after rename.
- Unknown JSON keys are ignored — forward-compat for schema additions within v1.
- `schema_version != 1` triggers defaults return (rejects forward/backward breaking changes).

## Reuse Path for Phase 45

Phase 45 will need two more atomic JSON writers: `update-trigger.json` (pv-proxy → updater, mode 0664) and `update-status.json` (updater → pv-proxy, mode 0644). The pattern in `save_state` is trivially generalizable:

```python
def _atomic_write_json(path: Path, data: dict, mode: int) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, path)
    os.chmod(path, mode)
```

**Recommendation:** Extract this helper into `src/pv_inverter_proxy/atomic_io.py` only when the 3rd caller lands in Phase 45. Premature extraction would force churn on `state_file.py` now for a speculative reuse.

## Test Coverage

13 pytest functions, 0.05s runtime, stdlib-only, no mocks:

| # | Test | Covers |
|---|------|--------|
| 1 | `test_load_state_missing_file_returns_defaults` | Missing file path |
| 2 | `test_save_then_load_roundtrip` | Happy path I/O |
| 3 | `test_load_state_corrupt_json_returns_defaults` | `json.JSONDecodeError` |
| 4 | `test_load_state_json_array_returns_defaults` | JSON is not dict |
| 5 | `test_load_state_wrong_schema_version_returns_defaults` | schema_version != 1 |
| 6 | `test_load_state_ignores_unknown_keys` | Forward-compat |
| 7 | `test_save_state_file_mode_0644` | `os.chmod` effect |
| 8 | `test_save_state_parent_missing_raises` | `FileNotFoundError` surfaces |
| 9 | `test_save_state_no_leftover_tmp_file` | Atomic rename cleanup |
| 10 | `test_is_power_limit_fresh_within_window` | age=100s, timeout=900s → True |
| 11 | `test_is_power_limit_fresh_outside_window` | age=500s, timeout=900s → False |
| 12 | `test_is_power_limit_fresh_none_limit` | Missing pct → False |
| 13 | `test_load_state_empty_file_returns_defaults` | Zero-byte file |

## Known Limitations

1. **No concurrent-writer protection.** Only the main service writes; only root helper reads (Phase 45). File locking would add complexity with no benefit — the single-writer invariant is enforced by the deployment topology, not the code.
2. **Atomic helper not extracted.** `save_state` is the only atomic JSON writer today. Extraction to a generic `_atomic_write_json` is deferred until Phase 45 adds the 2nd and 3rd caller (trigger.json, status.json). See "Reuse Path for Phase 45" above.
3. **Boot-restore Modbus write-back not implemented.** SAFETY-09 is PARTIAL in this plan by design — the wiring that calls `is_power_limit_fresh` and re-issues the limit to SE30K lives in Phase 45 (privileged updater flow). This plan delivers only the persistence primitive.
4. **No integration test.** Unit tests cover the module in isolation. End-to-end verification (actual /etc/pv-inverter-proxy/state.json survives systemd restart) lands in Phase 43-04 where install.sh creates the directory.

## Decisions Made

- **Same-directory tempfile** — `.json.tmp` sibling of target, not `/tmp/*`. POSIX `rename(2)` is atomic only within the same filesystem; cross-device `os.replace` can fail or fall back to non-atomic copy.
- **Raise parent-missing, swallow everything else on load** — Asymmetric on purpose. Missing parent on write = install bug that must be fixed; corrupt state on read = runtime condition that must not crash the service on boot.
- **Explicit `now` parameter on `is_power_limit_fresh`** — Avoids `time.time()` mocking in tests. Deterministic, no `freezegun`/`unittest.mock.patch` needed.
- **structlog bound with `component="state_file"`** — Matches project convention; future journalctl queries can filter on `component`.

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed without auto-fixes, architectural questions, or scope changes.

## Issues Encountered

- **Pre-existing failure** in `tests/test_webapp.py::test_config_get_venus_defaults` surfaced during full-suite regression run. Unrelated to state_file (venus config defaults endpoint). Logged to `.planning/phases/43-blue-green-layout-boot-recovery/deferred-items.md`. Not fixed — out of scope per execution rules.
- **Local `python` not on PATH** on the executor machine, only `python3` / `.venv/bin/python`. Used `.venv/bin/python -m pytest` for all verification. Not a project issue — environmental.

## User Setup Required

None — this plan only adds a Python module and its tests. No config changes, no external services, no runtime behavior changes. `/etc/pv-inverter-proxy/state.json` is not created until Phase 45 wires the main service to call `save_state`.

## Next Phase Readiness

- **43-02 (releases module)** — Independent, unblocked. Already completed (pre-existing commit `a8ff18e`).
- **43-04 (install.sh + main service wiring)** — Unblocked. Can now import `state_file` and wire it into `context.py` / `control.py`.
- **Phase 45 (privileged updater)** — Unblocked for the SAFETY-09 restore path. The atomic-write primitive pattern is also ready for reuse in trigger.json/status.json helpers.

## Follow-Ups for Phase 45 Wiring

1. **control.py** — call `save_state(...)` on every power-limit set and every night-mode toggle. Include `set_at = time.time()` at the moment of the Modbus write.
2. **__main__.py or context init** — on startup, call `load_state()` and pass to DeviceRegistry; if `is_power_limit_fresh(state, CommandTimeout)` is True, re-issue `WMaxLimPct` to SE30K before accepting new commands.
3. **Read SE30K CommandTimeout at boot** — Phase 45 must read register 0xF100 (or equivalent) to get the real timeout, not hardcode 900s. Plan 45 should call this out in its plan body.
4. **install.sh** — ensure `/etc/pv-inverter-proxy/` exists with `pv-proxy` write access before the main service starts; otherwise `save_state` will raise `FileNotFoundError` on the first state change.

## Self-Check: PASSED

Verified files and commits exist:

- FOUND: `src/pv_inverter_proxy/state_file.py` (157 lines)
- FOUND: `tests/test_state_file.py` (138 lines, 13 tests passing)
- FOUND: commit `66d5420` (feat: state_file module)
- FOUND: commit `ac38f6a` (test: state_file tests)
- VERIFIED: `pytest tests/test_state_file.py` → 13 passed in 0.05s
- VERIFIED: `python -c "from pv_inverter_proxy.state_file import ..."` → ok

---
*Phase: 43-blue-green-layout-boot-recovery*
*Plan: 01*
*Completed: 2026-04-10*
