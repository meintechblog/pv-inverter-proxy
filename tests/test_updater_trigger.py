"""Unit tests for pv_inverter_proxy.updater.trigger (EXEC-01, EXEC-02, SEC-07).

Hermetic — every test writes to pytest's tmp_path fixture. No touching
/etc/pv-inverter-proxy/ under any circumstance.

Covers:
- Schema round-trip (write → read → same dict)
- Schema key set exactly matches {op, target_sha, requested_at, requested_by, nonce}
- File mode is 0o664 after write
- No `.json.tmp` leftover after successful write
- `.json.tmp` cleaned up when os.replace raises
- TriggerPayload.validate rejects short SHA / bad op / missing nonce / non-Z timestamp
- TriggerPayload.validate accepts rollback with "previous" sentinel
- generate_nonce returns UUID4 shape
- Atomic replace under concurrent reader thread — reader never observes a
  partial JSON write
"""
from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest

from pv_inverter_proxy.updater import trigger as trigger_mod
from pv_inverter_proxy.updater.trigger import (
    TriggerPayload,
    generate_nonce,
    now_iso_utc,
    write_trigger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


FULL_SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"


def _make_payload(**overrides) -> TriggerPayload:
    base = {
        "op": "update",
        "target_sha": FULL_SHA,
        "requested_at": "2026-04-10T14:22:00Z",
        "requested_by": "webapp",
        "nonce": "11111111-2222-4333-8444-555555555555",
    }
    base.update(overrides)
    return TriggerPayload(**base)


# ---------------------------------------------------------------------------
# write_trigger — happy path
# ---------------------------------------------------------------------------


def test_write_trigger_atomic_replace(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    payload = _make_payload()
    write_trigger(payload, path=target)

    assert target.exists()
    data = json.loads(target.read_text())
    assert data == {
        "op": "update",
        "target_sha": FULL_SHA,
        "requested_at": "2026-04-10T14:22:00Z",
        "requested_by": "webapp",
        "nonce": "11111111-2222-4333-8444-555555555555",
    }


def test_write_trigger_correct_schema_keys(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    write_trigger(_make_payload(), path=target)
    data = json.loads(target.read_text())
    assert sorted(data.keys()) == [
        "nonce",
        "op",
        "requested_at",
        "requested_by",
        "target_sha",
    ]


def test_write_trigger_mode_0664(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    write_trigger(_make_payload(), path=target)
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o664, f"expected 0o664, got {oct(mode)}"


def test_write_trigger_no_tmp_leftover(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    write_trigger(_make_payload(), path=target)
    tmp = target.with_suffix(".json.tmp")
    assert not tmp.exists()


def test_write_trigger_sorted_pretty_printed(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    write_trigger(_make_payload(), path=target)
    raw = target.read_text()
    # indent=2 → contains newlines
    assert "\n" in raw
    # sort_keys=True → nonce comes before op alphabetically
    nonce_idx = raw.find('"nonce"')
    op_idx = raw.find('"op"')
    assert 0 < nonce_idx < op_idx


def test_write_trigger_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "update-trigger.json"
    write_trigger(_make_payload(), path=target)
    write_trigger(_make_payload(target_sha=OTHER_SHA), path=target)
    data = json.loads(target.read_text())
    assert data["target_sha"] == OTHER_SHA


# ---------------------------------------------------------------------------
# write_trigger — failure paths
# ---------------------------------------------------------------------------


def test_write_trigger_tmp_cleanup_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "update-trigger.json"

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_trigger(_make_payload(), path=target)

    # tempfile must be cleaned up even though replace failed
    tmp = target.with_suffix(".json.tmp")
    assert not tmp.exists(), "tmp leaked after failed replace"
    assert not target.exists(), "target must not exist if replace failed"


def test_write_trigger_rejects_invalid_payload_before_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "update-trigger.json"
    bad = _make_payload(op="delete")
    with pytest.raises(ValueError):
        write_trigger(bad, path=target)
    # Nothing written
    assert not target.exists()
    assert not target.with_suffix(".json.tmp").exists()


# ---------------------------------------------------------------------------
# TriggerPayload.validate
# ---------------------------------------------------------------------------


def test_validate_accepts_canonical_update() -> None:
    _make_payload().validate()  # no raise


def test_validate_accepts_rollback_previous() -> None:
    _make_payload(op="rollback", target_sha="previous").validate()


def test_validate_accepts_rollback_with_sha() -> None:
    _make_payload(op="rollback", target_sha=OTHER_SHA).validate()


def test_validate_rejects_short_sha() -> None:
    with pytest.raises(ValueError, match="40-char"):
        _make_payload(target_sha="abc123").validate()


def test_validate_rejects_uppercase_sha() -> None:
    with pytest.raises(ValueError):
        _make_payload(target_sha=FULL_SHA.upper()).validate()


def test_validate_rejects_bad_op() -> None:
    with pytest.raises(ValueError, match="invalid op"):
        _make_payload(op="delete").validate()


def test_validate_rejects_empty_op() -> None:
    with pytest.raises(ValueError):
        _make_payload(op="").validate()


def test_validate_rejects_empty_nonce() -> None:
    with pytest.raises(ValueError, match="nonce"):
        _make_payload(nonce="").validate()


def test_validate_rejects_non_z_timestamp() -> None:
    with pytest.raises(ValueError, match="Z"):
        _make_payload(requested_at="2026-04-10T14:22:00+00:00").validate()


def test_validate_rejects_empty_requested_by() -> None:
    with pytest.raises(ValueError, match="requested_by"):
        _make_payload(requested_by="").validate()


def test_validate_rejects_rollback_garbage_target() -> None:
    with pytest.raises(ValueError):
        _make_payload(op="rollback", target_sha="latest").validate()


# ---------------------------------------------------------------------------
# generate_nonce / now_iso_utc
# ---------------------------------------------------------------------------


def test_generate_nonce_uuid4_shape() -> None:
    nonce = generate_nonce()
    assert isinstance(nonce, str)
    assert len(nonce) == 36
    assert nonce.count("-") == 4
    # UUID4 variant bit: 14th char is "4", 19th char is one of 8,9,a,b
    assert nonce[14] == "4"
    assert nonce[19] in "89ab"


def test_generate_nonce_unique() -> None:
    nonces = {generate_nonce() for _ in range(100)}
    assert len(nonces) == 100


def test_now_iso_utc_shape() -> None:
    ts = now_iso_utc()
    assert ts.endswith("Z")
    assert len(ts) == 20  # "YYYY-MM-DDTHH:MM:SSZ"
    # parseable as ISO
    assert ts[4] == "-"
    assert ts[10] == "T"
    assert ts[13] == ":"


# ---------------------------------------------------------------------------
# Concurrency — reader never sees partial content
# ---------------------------------------------------------------------------


def test_write_trigger_atomic_under_concurrent_reader(tmp_path: Path) -> None:
    """Prove os.replace atomicity from a reader's point of view.

    A background thread continuously reads the target file. The main thread
    rewrites it 100 times. Every successful read must parse as JSON — never
    a truncated or half-written blob.
    """
    target = tmp_path / "update-trigger.json"
    # Seed with a first valid write so the reader has something to read.
    write_trigger(_make_payload(), path=target)

    stop = threading.Event()
    errors: list[str] = []
    reads = [0]

    def reader() -> None:
        while not stop.is_set():
            try:
                raw = target.read_text()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            if not raw:
                # Can legitimately happen only if a non-atomic writer truncated;
                # our writer uses os.replace so this is a regression signal.
                errors.append("empty read")
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"partial json: {e}")
                continue
            if sorted(data.keys()) != [
                "nonce",
                "op",
                "requested_at",
                "requested_by",
                "target_sha",
            ]:
                errors.append(f"wrong keys: {sorted(data.keys())}")
            reads[0] += 1

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        for i in range(100):
            payload = _make_payload(
                target_sha=FULL_SHA if i % 2 == 0 else OTHER_SHA,
                nonce=f"00000000-0000-4000-8000-{i:012d}",
            )
            write_trigger(payload, path=target)
    finally:
        stop.set()
        t.join(timeout=2)

    assert errors == [], f"reader observed inconsistent state: {errors[:5]}"
    assert reads[0] > 0, "reader did not run — test is vacuous"


# ---------------------------------------------------------------------------
# Constants / module sanity
# ---------------------------------------------------------------------------


def test_module_constants_match_spec() -> None:
    assert trigger_mod.TRIGGER_FILE_PATH == Path(
        "/etc/pv-inverter-proxy/update-trigger.json"
    )
    assert trigger_mod.TRIGGER_FILE_MODE == 0o664
