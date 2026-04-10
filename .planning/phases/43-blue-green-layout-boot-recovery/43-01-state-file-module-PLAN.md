---
phase: 43-blue-green-layout-boot-recovery
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/state_file.py
  - tests/test_state_file.py
autonomous: true
requirements:
  - SAFETY-09
must_haves:
  truths:
    - "State persistence helper can atomically write JSON to disk"
    - "State file reads return safe defaults on missing/corrupt files without crashing"
    - "Power limit and night mode state survives a process restart within CommandTimeout/2"
  artifacts:
    - path: "src/pv_inverter_proxy/state_file.py"
      provides: "State file schema, atomic read/write helpers"
      min_lines: 120
      exports: ["PersistedState", "load_state", "save_state", "STATE_FILE_PATH"]
    - path: "tests/test_state_file.py"
      provides: "Unit tests for state file round-trip, corruption handling, schema validation"
      min_lines: 140
  key_links:
    - from: "src/pv_inverter_proxy/state_file.py"
      to: "stdlib json + os.replace"
      via: "atomic write pattern (tempfile + os.replace)"
      pattern: "os\\.replace"
---

<objective>
Create a self-contained, unit-testable state persistence module that the main service can use to write the SE30K power limit and night mode state to `/etc/pv-inverter-proxy/state.json` on every relevant state change, and read it back on boot for restoration if the timestamp is still within the SE30K `CommandTimeout/2` window.

Purpose: This is the atomic building block for SAFETY-09 and the smallest piece of Phase 43. It has zero systemd coupling, zero filesystem-layout coupling, and can be fully validated with stdlib-only unit tests. Landing this first de-risks the rest of the phase and gives a clean foundation for Phase 45 (which will add update-trigger.json and update-status.json helpers that reuse the same atomic-write primitive).

Output: One new source module (`state_file.py`), one new test file, no modifications to main service wiring yet (wiring happens in plan 43-04 where install.sh creates the required directory permissions).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@CLAUDE.md

<interfaces>
<!-- Relevant existing code the executor needs. -->

From src/pv_inverter_proxy/config.py (top):
```python
DEFAULT_CONFIG_PATH = "/etc/pv-inverter-proxy/config.yaml"
```
Note: `/etc/pv-inverter-proxy/` is already the canonical config directory owned by pv-proxy — `state.json` lives in the same directory.

Pattern reference (from ARCHITECTURE.md Pattern 1 — atomic trigger file write):
```python
def write_trigger(payload: dict) -> None:
    target = Path("/etc/pv-inverter-proxy/update-trigger.json")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, target)  # atomic on POSIX
```
Use the same pattern for state.json — write to `state.json.tmp` in the same directory, then `os.replace`.

Existing test pattern (from tests/test_config.py and tests/test_context.py): tests are plain `pytest` functions, import target module, use `tmp_path` fixture for filesystem isolation, assert on return values.

SE30K CommandTimeout reference (from requirements SAFETY-09):
The SE30K Modbus register `CommandTimeout` (reg 0xF100 typical) specifies how long the inverter holds a set power limit before reverting to default. Typical value is 900s. On boot, state.json is only trusted if `now - set_at < CommandTimeout/2` (i.e. we still have at least half the timeout left to re-issue). If older, ignore the persisted limit; the inverter has already reverted naturally.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create state_file.py module with schema, atomic write, defensive read</name>
  <files>src/pv_inverter_proxy/state_file.py</files>
  <behavior>
    The module exports:

    1. `STATE_FILE_PATH: Path = Path("/etc/pv-inverter-proxy/state.json")` — module-level constant, but all public functions MUST accept an optional `path: Path | None = None` argument that overrides it (so tests can point at `tmp_path`).

    2. `@dataclass PersistedState`:
       - `power_limit_pct: float | None = None` — last-set SE30K WMaxLimPct (0-100). None = not set / enabled.
       - `power_limit_set_at: float | None = None` — UNIX timestamp (`time.time()`) when limit was set. Used for staleness check.
       - `night_mode_active: bool = False` — whether night mode is currently on.
       - `night_mode_set_at: float | None = None` — UNIX timestamp when night mode was last toggled.
       - `schema_version: int = 1` — for future migrations.

    3. `def load_state(path: Path | None = None) -> PersistedState`:
       - If file does not exist → return `PersistedState()` (all defaults).
       - If file exists but JSON parse fails → log a warning via `structlog.get_logger(component="state_file")` with the filename and error, return `PersistedState()`.
       - If JSON parses but top-level is not a dict → warn, return `PersistedState()`.
       - If `schema_version` is missing or not 1 → warn "unsupported schema", return `PersistedState()`.
       - Otherwise construct `PersistedState(**{k: v for k, v in data.items() if k in PersistedState.__dataclass_fields__})` — mirror the config.py pattern of ignoring unknown keys.
       - Any unexpected `Exception` → log error, return `PersistedState()`. Must NEVER raise.

    4. `def save_state(state: PersistedState, path: Path | None = None) -> None`:
       - Serialize `dataclasses.asdict(state)` to JSON (indent=2, sort_keys=True for deterministic output).
       - Write to `path.with_suffix(".json.tmp")` (same directory — required so rename is atomic on POSIX; cross-device rename is not atomic).
       - Call `os.replace(tmp, path)` for atomic swap.
       - If parent directory does not exist → log error with a hint about running install.sh, re-raise `FileNotFoundError` (this is a real install bug, not a runtime condition to swallow).
       - Any other `OSError` (EACCES, ENOSPC) → log error with context, re-raise. The caller decides whether to crash.
       - File mode: explicitly `0o644` via `os.chmod(path, 0o644)` AFTER replace (world-readable, owner-writable — matches the "root helper reads state to restore post-update" flow).

    5. `def is_power_limit_fresh(state: PersistedState, command_timeout_s: float, now: float | None = None) -> bool`:
       - Return `True` iff `state.power_limit_pct is not None and state.power_limit_set_at is not None and (now or time.time()) - state.power_limit_set_at < command_timeout_s / 2`.
       - Return `False` on any missing field or if stale.
       - This is the SAFETY-09 staleness gate used at boot.

    Test expectations (all must pass in task 2):
    - Test 1: `load_state` on non-existent path returns `PersistedState()` with all defaults.
    - Test 2: Save then load round-trips a populated state exactly.
    - Test 3: `load_state` on corrupt JSON returns defaults without raising.
    - Test 4: `load_state` on JSON array (not dict) returns defaults without raising.
    - Test 5: `load_state` on JSON dict with wrong schema_version returns defaults.
    - Test 6: `load_state` on JSON with unknown extra keys ignores them and loads known ones.
    - Test 7: `save_state` produces file with mode 0644 (check via `os.stat`).
    - Test 8: `save_state` to non-existent parent directory raises `FileNotFoundError`.
    - Test 9: `save_state` is atomic — simulated by asserting the `.tmp` file does NOT exist after a successful save.
    - Test 10: `is_power_limit_fresh` returns True when `set_at = now - 100` and `command_timeout = 900` (stale = 450s threshold).
    - Test 11: `is_power_limit_fresh` returns False when `set_at = now - 500` and `command_timeout = 900`.
    - Test 12: `is_power_limit_fresh` returns False when `power_limit_pct is None`.
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/state_file.py`:

    ```python
    """Persistent state file for power limit + night mode (SAFETY-09).

    Writes to /etc/pv-inverter-proxy/state.json atomically via os.replace.
    Reads are defensive: missing, corrupt, or wrong-schema files return
    safe defaults, never raise. The main service writes on state changes,
    reads on boot and restores if the timestamp is still within
    CommandTimeout/2 (i.e. we still have headroom to re-issue the limit
    before the SE30K reverts naturally).
    """
    from __future__ import annotations

    import json
    import os
    import time
    from dataclasses import asdict, dataclass
    from pathlib import Path

    import structlog

    log = structlog.get_logger(component="state_file")

    STATE_FILE_PATH: Path = Path("/etc/pv-inverter-proxy/state.json")


    @dataclass
    class PersistedState:
        power_limit_pct: float | None = None
        power_limit_set_at: float | None = None
        night_mode_active: bool = False
        night_mode_set_at: float | None = None
        schema_version: int = 1


    def load_state(path: Path | None = None) -> PersistedState:
        target = path or STATE_FILE_PATH
        if not target.exists():
            return PersistedState()
        try:
            raw = target.read_text()
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("state_file_corrupt", path=str(target), error=str(e))
            return PersistedState()
        except OSError as e:
            log.warning("state_file_read_error", path=str(target), error=str(e))
            return PersistedState()
        if not isinstance(data, dict):
            log.warning("state_file_wrong_type", path=str(target), type=type(data).__name__)
            return PersistedState()
        schema = data.get("schema_version")
        if schema != 1:
            log.warning("state_file_unsupported_schema", path=str(target), schema=schema)
            return PersistedState()
        try:
            return PersistedState(**{
                k: v for k, v in data.items()
                if k in PersistedState.__dataclass_fields__
            })
        except Exception as e:  # pragma: no cover - defensive
            log.error("state_file_construct_failed", path=str(target), error=str(e))
            return PersistedState()


    def save_state(state: PersistedState, path: Path | None = None) -> None:
        target = path or STATE_FILE_PATH
        tmp = target.with_suffix(".json.tmp")
        payload = json.dumps(asdict(state), indent=2, sort_keys=True)
        try:
            tmp.write_text(payload)
            os.replace(tmp, target)
            os.chmod(target, 0o644)
        except FileNotFoundError:
            log.error(
                "state_file_parent_missing",
                path=str(target),
                hint="run install.sh to create /etc/pv-inverter-proxy",
            )
            raise
        except OSError as e:
            log.error("state_file_write_failed", path=str(target), error=str(e))
            # best-effort cleanup of the .tmp if it exists
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise


    def is_power_limit_fresh(
        state: PersistedState,
        command_timeout_s: float,
        now: float | None = None,
    ) -> bool:
        if state.power_limit_pct is None or state.power_limit_set_at is None:
            return False
        current = now if now is not None else time.time()
        age = current - state.power_limit_set_at
        return age < (command_timeout_s / 2.0)
    ```
  </action>
  <verify>
    <automated>python -c "from pv_inverter_proxy.state_file import PersistedState, load_state, save_state, is_power_limit_fresh, STATE_FILE_PATH; print('ok')"</automated>
  </verify>
  <done>Module file exists, imports cleanly, exports the documented symbols.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Write unit tests for state_file.py</name>
  <files>tests/test_state_file.py</files>
  <behavior>
    12 pytest test functions covering all the behaviors documented in Task 1. All use the `tmp_path` fixture for isolation. No mocks needed except `time.time()` via an explicit `now` parameter.
  </behavior>
  <action>
    Create `tests/test_state_file.py`:

    ```python
    """Unit tests for state_file.py (SAFETY-09)."""
    from __future__ import annotations

    import json
    import os
    import stat
    from pathlib import Path

    import pytest

    from pv_inverter_proxy.state_file import (
        PersistedState,
        is_power_limit_fresh,
        load_state,
        save_state,
    )


    def test_load_state_missing_file_returns_defaults(tmp_path: Path):
        state = load_state(tmp_path / "state.json")
        assert state == PersistedState()
        assert state.power_limit_pct is None
        assert state.night_mode_active is False
        assert state.schema_version == 1


    def test_save_then_load_roundtrip(tmp_path: Path):
        path = tmp_path / "state.json"
        original = PersistedState(
            power_limit_pct=42.5,
            power_limit_set_at=1700000000.0,
            night_mode_active=True,
            night_mode_set_at=1700000100.0,
        )
        save_state(original, path)
        loaded = load_state(path)
        assert loaded == original


    def test_load_state_corrupt_json_returns_defaults(tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text("{not valid json")
        state = load_state(path)
        assert state == PersistedState()


    def test_load_state_json_array_returns_defaults(tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text('[1, 2, 3]')
        state = load_state(path)
        assert state == PersistedState()


    def test_load_state_wrong_schema_version_returns_defaults(tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({
            "schema_version": 99,
            "power_limit_pct": 50.0,
        }))
        state = load_state(path)
        assert state == PersistedState()


    def test_load_state_ignores_unknown_keys(tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "power_limit_pct": 75.0,
            "power_limit_set_at": 1700000000.0,
            "unknown_future_field": "whatever",
            "another_one": 123,
        }))
        state = load_state(path)
        assert state.power_limit_pct == 75.0
        assert state.power_limit_set_at == 1700000000.0


    def test_save_state_file_mode_0644(tmp_path: Path):
        path = tmp_path / "state.json"
        save_state(PersistedState(power_limit_pct=10.0), path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o644


    def test_save_state_parent_missing_raises(tmp_path: Path):
        path = tmp_path / "nonexistent_dir" / "state.json"
        with pytest.raises(FileNotFoundError):
            save_state(PersistedState(), path)


    def test_save_state_no_leftover_tmp_file(tmp_path: Path):
        path = tmp_path / "state.json"
        save_state(PersistedState(power_limit_pct=33.3), path)
        assert path.exists()
        assert not (tmp_path / "state.json.tmp").exists()


    def test_is_power_limit_fresh_within_window():
        state = PersistedState(
            power_limit_pct=50.0,
            power_limit_set_at=1_000_000.0,
        )
        # command_timeout = 900s, half = 450s, age = 100s -> fresh
        assert is_power_limit_fresh(state, 900.0, now=1_000_100.0) is True


    def test_is_power_limit_fresh_outside_window():
        state = PersistedState(
            power_limit_pct=50.0,
            power_limit_set_at=1_000_000.0,
        )
        # age = 500s > 450s -> stale
        assert is_power_limit_fresh(state, 900.0, now=1_000_500.0) is False


    def test_is_power_limit_fresh_none_limit():
        state = PersistedState(power_limit_set_at=1_000_000.0)  # pct missing
        assert is_power_limit_fresh(state, 900.0, now=1_000_001.0) is False


    def test_load_state_empty_file_returns_defaults(tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text("")
        state = load_state(path)
        assert state == PersistedState()
    ```
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && python -m pytest tests/test_state_file.py -x -q</automated>
  </verify>
  <done>All 13 tests pass. No warnings about unclosed files. Test file self-contained (no fixtures beyond `tmp_path`).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| main-service -> state.json | Main service (pv-proxy user) writes its own state file; no external input. |
| state.json -> main-service on boot | JSON parse of a file owned by pv-proxy; attacker with write access already has code execution. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-43-01-01 | Tampering | state.json | accept | File is inside pv-proxy-owned /etc/pv-inverter-proxy; attacker with write access has already achieved code execution via config.yaml. No new attack surface. |
| T-43-01-02 | Denial of Service | load_state | mitigate | All parse errors (corrupt JSON, wrong type, wrong schema, unknown keys) caught and logged; function returns defaults, never raises. Prevents a corrupt state.json from crashing service on boot. |
| T-43-01-03 | Denial of Service | save_state cross-device rename | mitigate | Temp file is written in same directory as target (`.json.tmp` suffix), not `/tmp`, so `os.replace` is guaranteed atomic. |
| T-43-01-04 | Information Disclosure | state.json permissions | accept | File mode 0644 (world-readable). Contents are power limit percentage and timestamp — not sensitive. Explicitly documented. |
| T-43-01-05 | Repudiation | state write without audit | accept | State changes are logged by main-service callers (control.py, etc.) via structlog; this module is a primitive. |
| T-43-01-06 | Spoofing | wrong owner writes state.json | mitigate | Parent directory is pv-proxy-owned. Only root and pv-proxy can write. Out-of-scope for this module to enforce — install.sh sets directory permissions (plan 43-04). |
</threat_model>

<validation_strategy>
**SAFETY-09 validation:** Fully unit-tested in `tests/test_state_file.py` (13 tests). No integration test needed for this plan — the wiring into main service (restoring limit on boot) lands in plan 43-04. The atomic-write guarantee (`os.replace`) is a POSIX kernel guarantee; we verify the high-level behavior (no leftover tmp file, file exists after save).

**Nyquist validation per task:**
- Task 1 verify: Import-time smoke test (`python -c "from ... import ..."`). Catches syntax errors, missing exports, import cycles.
- Task 2 verify: Full pytest run against the 13 test cases. Each case is an executable assertion of a documented behavior from Task 1's `<behavior>` block.

**Why this plan is unit-testable in isolation:** Zero dependencies on systemd, zero dependencies on filesystem layout beyond a writable directory (`tmp_path`), zero dependencies on the main service. Pure function module.
</validation_strategy>

<rollback_plan>
If this plan's execution fails or introduces regressions:

1. **Source files are additive only** — deleting `src/pv_inverter_proxy/state_file.py` and `tests/test_state_file.py` fully reverts the plan. No existing files are modified.
2. **Git operation:** `git rm src/pv_inverter_proxy/state_file.py tests/test_state_file.py && git commit -m "revert(43-01): remove state_file module"`
3. **Service impact:** Zero. Nothing imports `state_file.py` yet — that wiring lands in plan 43-04. A failed 43-01 blocks nothing downstream in this plan set except 43-04.
4. **Re-attempt:** Fix the specific failing test, commit, re-run `pytest tests/test_state_file.py`.
</rollback_plan>

<verification>
1. `python -m pytest tests/test_state_file.py -x -q` passes (13/13 tests)
2. `python -c "from pv_inverter_proxy.state_file import PersistedState, load_state, save_state, is_power_limit_fresh, STATE_FILE_PATH"` succeeds
3. `python -m py_compile src/pv_inverter_proxy/state_file.py` has no syntax errors
4. Existing test suite still passes: `python -m pytest tests/ -x -q` (no regressions — plan only adds new files)
</verification>

<success_criteria>
- [ ] `src/pv_inverter_proxy/state_file.py` exists with `PersistedState`, `load_state`, `save_state`, `is_power_limit_fresh`, `STATE_FILE_PATH` exports
- [ ] `tests/test_state_file.py` exists with 13 tests, all passing
- [ ] No modifications to any existing file (fully additive)
- [ ] Module is importable without side effects (no filesystem access at import time)
- [ ] `save_state` is atomic via `os.replace` pattern, leaves no `.tmp` file on success
- [ ] `load_state` is defensive: returns `PersistedState()` on all error paths (missing / corrupt / wrong type / wrong schema / OSError), never raises
- [ ] Full test suite passes after this plan (no regressions)
</success_criteria>

<output>
After completion, create `.planning/phases/43-blue-green-layout-boot-recovery/43-01-SUMMARY.md` documenting:
- Module API and usage pattern for Phase 45 to reuse (trigger.json, status.json will use the same atomic-write primitive)
- Test count and coverage areas
- Known limitations (no concurrent-writer protection — intentional; only main service writes, only root helper reads; file locking would add complexity without benefit)
- Whether the atomic-write helper should be extracted into a generic `_atomic_write_json` function in a future refactor if 3+ callers emerge
</output>
