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
    """Schema for /etc/pv-inverter-proxy/state.json.

    Fields:
        power_limit_pct: Last-set SE30K WMaxLimPct (0-100). None = not set / enabled.
        power_limit_set_at: UNIX timestamp when limit was set. Used for staleness.
        night_mode_active: Whether night mode is currently on.
        night_mode_set_at: UNIX timestamp when night mode was last toggled.
        schema_version: For future migrations. Current schema = 1.
    """
    power_limit_pct: float | None = None
    power_limit_set_at: float | None = None
    night_mode_active: bool = False
    night_mode_set_at: float | None = None
    schema_version: int = 1


def load_state(path: Path | None = None) -> PersistedState:
    """Load persisted state from disk. Never raises.

    Returns PersistedState() on any error path:
    - missing file
    - unreadable file (OSError)
    - corrupt JSON
    - JSON that is not a top-level dict
    - schema_version missing or not 1

    Unknown fields in the JSON are ignored (forward-compat with future
    schema additions in the same major version).
    """
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
        log.warning(
            "state_file_wrong_type",
            path=str(target),
            type=type(data).__name__,
        )
        return PersistedState()

    schema = data.get("schema_version")
    if schema != 1:
        log.warning(
            "state_file_unsupported_schema",
            path=str(target),
            schema=schema,
        )
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
    """Atomically write state to disk via tempfile + os.replace.

    Temp file lives in the same directory as the target (required for
    atomicity on POSIX — cross-device rename is not atomic). On success,
    file mode is set to 0o644 (world-readable, owner-writable).

    Raises:
        FileNotFoundError: if parent directory does not exist (install bug).
        OSError: on any other write failure (EACCES, ENOSPC, ...).

    The caller decides whether to swallow or propagate these; this module
    re-raises intentionally so silent install/permission bugs surface
    loudly rather than being masked as runtime state loss.
    """
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
    """SAFETY-09 staleness gate used at boot.

    Returns True iff a power limit is recorded AND its age is strictly
    less than command_timeout_s / 2. The half-window gives the boot
    restore path enough headroom to re-issue the limit before the SE30K
    reverts to default naturally.

    Args:
        state: The loaded PersistedState.
        command_timeout_s: The SE30K CommandTimeout register value in seconds.
        now: Optional override for time.time(); used for deterministic tests.
    """
    if state.power_limit_pct is None or state.power_limit_set_at is None:
        return False
    current = now if now is not None else time.time()
    age = current - state.power_limit_set_at
    return age < (command_timeout_s / 2.0)
