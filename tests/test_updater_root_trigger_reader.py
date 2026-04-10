"""Hermetic unit tests for updater_root.trigger_reader.

All file I/O targets ``tmp_path`` — never touches /etc, /var/lib.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pv_inverter_proxy.updater_root.trigger_reader import (
    DEFAULT_MAX_NONCES,
    NonceDedupStore,
    NonceReplayError,
    TriggerValidationError,
    ValidatedTrigger,
    read_and_validate_trigger,
    validate_tag_regex,
)

VALID_SHA = "a" * 40
VALID_SHA_2 = "b" * 40


def _write_trigger(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body))


def _good_body(nonce: str = "nonce-1") -> dict:
    return {
        "op": "update",
        "target_sha": VALID_SHA,
        "requested_at": "2026-04-10T14:22:00Z",
        "requested_by": "webapp",
        "nonce": nonce,
    }


# ---------- validate_tag_regex (SEC-06) ----------


def test_validate_tag_regex_accepts_valid():
    for tag in ("v8.0", "v8.0.1", "v10.20.30", "v1.2", "v0.0.1"):
        assert validate_tag_regex(tag), tag


def test_validate_tag_regex_rejects_invalid():
    for tag in (
        "8.0",
        "v8.0.0-rc1",
        "v8",
        "main",
        "latest",
        "v8.0.0.0",
        "v8.a",
        "va.b",
        "",
    ):
        assert not validate_tag_regex(tag), tag


def test_validate_tag_regex_rejects_non_string():
    assert not validate_tag_regex(None)  # type: ignore[arg-type]
    assert not validate_tag_regex(123)  # type: ignore[arg-type]


# ---------- read_and_validate_trigger — happy paths ----------


def test_read_valid_trigger(tmp_path: Path):
    trig = tmp_path / "trig.json"
    _write_trigger(trig, _good_body())
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    result = read_and_validate_trigger(trig, store)
    assert isinstance(result, ValidatedTrigger)
    assert result.op == "update"
    assert result.target_sha == VALID_SHA
    assert result.requested_by == "webapp"
    assert result.nonce == "nonce-1"


def test_read_rollback_previous_allowed(tmp_path: Path):
    trig = tmp_path / "trig.json"
    body = _good_body()
    body["op"] = "rollback"
    body["target_sha"] = "previous"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    result = read_and_validate_trigger(trig, store)
    assert result.op == "rollback"
    assert result.target_sha == "previous"


def test_read_rollback_sha_allowed(tmp_path: Path):
    trig = tmp_path / "trig.json"
    body = _good_body()
    body["op"] = "rollback"
    body["target_sha"] = VALID_SHA_2
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    result = read_and_validate_trigger(trig, store)
    assert result.target_sha == VALID_SHA_2


def test_read_stores_raw_body(tmp_path: Path):
    trig = tmp_path / "trig.json"
    body = _good_body()
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    result = read_and_validate_trigger(trig, store)
    assert result.raw_body == body


# ---------- read_and_validate_trigger — failures ----------


def test_read_missing_file(tmp_path: Path):
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="missing"):
        read_and_validate_trigger(tmp_path / "nope.json", store)


def test_read_corrupt_json(tmp_path: Path):
    trig = tmp_path / "trig.json"
    trig.write_text("{{not json")
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="not valid JSON"):
        read_and_validate_trigger(trig, store)


def test_read_not_dict(tmp_path: Path):
    trig = tmp_path / "trig.json"
    trig.write_text("[1,2,3]")
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="not a JSON object"):
        read_and_validate_trigger(trig, store)


def test_read_extra_keys_rejected(tmp_path: Path):
    body = _good_body()
    body["extra_field"] = "oops"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="schema mismatch"):
        read_and_validate_trigger(trig, store)


def test_read_missing_key(tmp_path: Path):
    body = _good_body()
    del body["nonce"]
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="schema mismatch"):
        read_and_validate_trigger(trig, store)


def test_read_bad_op(tmp_path: Path):
    body = _good_body()
    body["op"] = "hack"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="invalid op"):
        read_and_validate_trigger(trig, store)


def test_read_bad_sha_shape(tmp_path: Path):
    body = _good_body()
    body["target_sha"] = "xyz"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="40-char"):
        read_and_validate_trigger(trig, store)


def test_read_update_cannot_use_previous(tmp_path: Path):
    body = _good_body()
    body["target_sha"] = "previous"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="40-char"):
        read_and_validate_trigger(trig, store)


def test_read_bad_requested_at(tmp_path: Path):
    body = _good_body()
    body["requested_at"] = "yesterday"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="ISO-8601"):
        read_and_validate_trigger(trig, store)


def test_read_missing_z_suffix(tmp_path: Path):
    body = _good_body()
    body["requested_at"] = "2026-04-10T14:22:00"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="ISO-8601"):
        read_and_validate_trigger(trig, store)


def test_read_empty_requested_by(tmp_path: Path):
    body = _good_body()
    body["requested_by"] = ""
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="requested_by"):
        read_and_validate_trigger(trig, store)


def test_read_empty_nonce(tmp_path: Path):
    body = _good_body()
    body["nonce"] = ""
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError, match="nonce"):
        read_and_validate_trigger(trig, store)


# ---------- NonceDedupStore ----------


def test_nonce_dedup_first_time_ok(tmp_path: Path):
    trig = tmp_path / "trig.json"
    _write_trigger(trig, _good_body(nonce="abc"))
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    assert not store.has_seen("abc")
    read_and_validate_trigger(trig, store)
    assert store.has_seen("abc")


def test_nonce_dedup_replay_raises(tmp_path: Path):
    trig = tmp_path / "trig.json"
    _write_trigger(trig, _good_body(nonce="abc"))
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    read_and_validate_trigger(trig, store)
    with pytest.raises(NonceReplayError):
        read_and_validate_trigger(trig, store)


def test_nonce_dedup_persists_to_disk(tmp_path: Path):
    store_path = tmp_path / "dedup.json"
    store1 = NonceDedupStore(path=store_path)
    store1.mark_seen("nonce-a")
    store2 = NonceDedupStore(path=store_path)
    assert store2.has_seen("nonce-a")


def test_nonce_dedup_trims_to_max(tmp_path: Path):
    store_path = tmp_path / "dedup.json"
    store = NonceDedupStore(path=store_path, max_entries=DEFAULT_MAX_NONCES)
    for i in range(60):
        store.mark_seen(f"nonce-{i:03d}", now=1_700_000_000 + i)
    body = json.loads(store_path.read_text())
    assert len(body["nonces"]) == 50
    # Oldest dropped, newest retained
    assert not store.has_seen("nonce-000")
    assert not store.has_seen("nonce-009")
    assert store.has_seen("nonce-010")
    assert store.has_seen("nonce-059")


def test_nonce_dedup_corrupt_file_treated_as_empty(tmp_path: Path):
    store_path = tmp_path / "dedup.json"
    store_path.write_text("{{garbage")
    store = NonceDedupStore(path=store_path)
    assert not store.has_seen("anything")


def test_nonce_dedup_wrong_top_type_treated_as_empty(tmp_path: Path):
    store_path = tmp_path / "dedup.json"
    store_path.write_text("[1,2,3]")
    store = NonceDedupStore(path=store_path)
    assert not store.has_seen("anything")


def test_nonce_dedup_bad_nonces_field(tmp_path: Path):
    store_path = tmp_path / "dedup.json"
    store_path.write_text('{"nonces": "not a list"}')
    store = NonceDedupStore(path=store_path)
    assert not store.has_seen("anything")


def test_nonce_dedup_malformed_entries_filtered(tmp_path: Path):
    """Malformed entries are dropped but well-formed ones survive."""
    store_path = tmp_path / "dedup.json"
    body = {
        "nonces": [
            {"nonce": "good-1", "seen_at": 1.0},
            "not a dict",
            {"nonce": 123, "seen_at": 2.0},  # bad nonce type
            {"nonce": "good-2", "seen_at": "not-a-number"},  # bad seen_at
            {"nonce": "good-3", "seen_at": 3.0},
        ]
    }
    store_path.write_text(json.dumps(body))
    store = NonceDedupStore(path=store_path)
    assert store.has_seen("good-1")
    assert store.has_seen("good-3")
    assert not store.has_seen("good-2")


def test_nonce_dedup_mark_seen_idempotent(tmp_path: Path):
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    store.mark_seen("abc")
    store.mark_seen("abc")
    body = json.loads((tmp_path / "dedup.json").read_text())
    assert len(body["nonces"]) == 1


def test_nonce_dedup_replay_does_not_poison_store_on_failed_read(tmp_path: Path):
    """A malformed trigger must not add its nonce to the dedup store."""
    body = _good_body(nonce="poison")
    body["op"] = "bogus"
    trig = tmp_path / "trig.json"
    _write_trigger(trig, body)
    store = NonceDedupStore(path=tmp_path / "dedup.json")
    with pytest.raises(TriggerValidationError):
        read_and_validate_trigger(trig, store)
    assert not store.has_seen("poison")
