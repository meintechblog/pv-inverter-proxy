"""Integration tests for POST /api/update/start (EXEC-01, EXEC-02).

Uses an in-process aiohttp Application with just the one route wired up.
The trigger-file path is monkeypatched to a tmp_path so tests never touch
/etc/pv-inverter-proxy/.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pv_inverter_proxy.updater import trigger as trigger_mod
from pv_inverter_proxy.webapp import update_start_handler

FULL_SHA = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trigger_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TRIGGER_FILE_PATH to a tmp file for the duration of the test."""
    p = tmp_path / "update-trigger.json"
    monkeypatch.setattr(trigger_mod, "TRIGGER_FILE_PATH", p)
    return p


@pytest.fixture
async def client(trigger_path: Path):
    """In-process aiohttp client with only /api/update/start registered."""
    app = web.Application()
    app.router.add_post("/api/update/start", update_start_handler)
    async with TestClient(TestServer(app)) as c:
        yield c


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_update_start_accepts_valid_update(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
    )
    assert resp.status == 202
    data = await resp.json()
    assert set(data.keys()) == {"update_id", "status_url"}
    assert data["status_url"] == "/api/update/status"
    # update_id is a UUID4
    assert len(data["update_id"]) == 36
    assert data["update_id"].count("-") == 4

    # Trigger file landed on disk with full schema.
    assert trigger_path.exists()
    written = json.loads(trigger_path.read_text())
    assert written["op"] == "update"
    assert written["target_sha"] == FULL_SHA
    assert written["nonce"] == data["update_id"]
    assert written["requested_by"] == "webapp"
    assert written["requested_at"].endswith("Z")


async def test_update_start_accepts_rollback_previous(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        json={"op": "rollback", "target_sha": "previous"},
    )
    assert resp.status == 202
    data = json.loads((trigger_path).read_text())
    assert data["op"] == "rollback"
    assert data["target_sha"] == "previous"


async def test_update_start_op_defaults_to_update(client, trigger_path: Path):
    """Missing `op` defaults to 'update' per handler spec."""
    resp = await client.post(
        "/api/update/start",
        json={"target_sha": FULL_SHA},
    )
    assert resp.status == 202
    written = json.loads(trigger_path.read_text())
    assert written["op"] == "update"


# ---------------------------------------------------------------------------
# 400 — malformed input
# ---------------------------------------------------------------------------


async def test_update_start_rejects_short_sha(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": "abc"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "invalid_payload" in data["error"]
    assert not trigger_path.exists()


async def test_update_start_rejects_bad_op(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        json={"op": "delete", "target_sha": FULL_SHA},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "invalid_payload" in data["error"]
    assert not trigger_path.exists()


async def test_update_start_rejects_missing_target_sha(client, trigger_path: Path):
    resp = await client.post("/api/update/start", json={"op": "update"})
    assert resp.status == 400
    data = await resp.json()
    assert "target_sha" in data["error"]
    assert not trigger_path.exists()


async def test_update_start_rejects_non_dict_body(client, trigger_path: Path):
    resp = await client.post("/api/update/start", json=["not", "an", "object"])
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "body_must_be_json_object"


async def test_update_start_rejects_non_json_body(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        data=b"this is not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "invalid_json" in data["error"]


async def test_update_start_rejects_numeric_target_sha(client, trigger_path: Path):
    resp = await client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": 12345},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "strings" in data["error"]


# ---------------------------------------------------------------------------
# 500 — write failure
# ---------------------------------------------------------------------------


async def test_update_start_returns_500_on_write_error(
    client,
    trigger_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Simulate a disk-level failure in write_trigger."""
    from pv_inverter_proxy.updater import trigger as trig

    def boom(payload, path=None):
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(trig, "write_trigger", boom)

    resp = await client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
    )
    assert resp.status == 500
    data = await resp.json()
    assert "trigger_write_failed" in data["error"]
    assert "simulated ENOSPC" in data["error"]


# ---------------------------------------------------------------------------
# EXEC-01 latency budget (<100ms)
# ---------------------------------------------------------------------------


async def test_update_start_under_100ms(client, trigger_path: Path):
    """The handler must complete in under 100ms (EXEC-01)."""
    # Warm up (first request pays import / aiohttp setup costs)
    await client.post(
        "/api/update/start",
        json={"op": "update", "target_sha": FULL_SHA},
    )

    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = await client.post(
            "/api/update/start",
            json={"op": "update", "target_sha": FULL_SHA},
        )
        t1 = time.perf_counter()
        assert resp.status == 202
        samples.append((t1 - t0) * 1000)  # ms

    # Use the median so a single CI hiccup does not flake the test.
    samples.sort()
    median_ms = samples[len(samples) // 2]
    assert median_ms < 100.0, (
        f"median latency {median_ms:.2f}ms exceeds 100ms budget; "
        f"all samples: {samples}"
    )


# ---------------------------------------------------------------------------
# Nonce uniqueness (consecutive calls)
# ---------------------------------------------------------------------------


async def test_update_start_generates_unique_nonces(client, trigger_path: Path):
    nonces = set()
    for _ in range(10):
        resp = await client.post(
            "/api/update/start",
            json={"op": "update", "target_sha": FULL_SHA},
        )
        assert resp.status == 202
        data = await resp.json()
        nonces.add(data["update_id"])
    assert len(nonces) == 10
