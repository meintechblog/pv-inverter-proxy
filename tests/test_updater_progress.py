"""Unit tests for pv_inverter_proxy.updater.progress (UI-02, Phase 46).

Hermetic — every test builds a fake app dict with a set of FakeWs clients
and monkeypatches `load_status` to return a controlled UpdateStatus-like
object. No real status file is read.

Contract under test (per 46-CONTEXT.md D-22..D-26):
  * A single asyncio.Task polls `update-status.json` every 500ms while
    current_phase() is not in IDLE_PHASES, and backs off to 5s when idle.
  * Each new history[] entry emits exactly one
    `{"type": "update_progress", "data": {...}}` WS message.
  * Dedupe via the monotonic `sequence` field on history entries (Phase
    45 does not currently write this field, so the broadcaster falls back
    to the entry's index in history[] per RESEARCH.md Pattern 4).
  * Missing file / malformed status / dead WS clients must not crash the
    task.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from pv_inverter_proxy.updater.progress import (
    ACTIVE_POLL_INTERVAL_S,
    IDLE_POLL_INTERVAL_S,
    IDLE_PHASES,
    ProgressBroadcaster,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeWs:
    """Minimal stand-in for aiohttp.web.WebSocketResponse used in broadcasts."""

    def __init__(self, raise_on_send: bool = False) -> None:
        self.sent: list[str] = []
        self.raise_on_send = raise_on_send

    async def send_str(self, payload: str) -> None:
        if self.raise_on_send:
            raise ConnectionResetError("fake")
        self.sent.append(payload)


@dataclass
class FakeStatus:
    """Stand-in for updater.status.UpdateStatus."""

    current: dict | None = None
    history: list[dict] = field(default_factory=list)
    schema_version: int = 1


def _patch_status(monkeypatch: pytest.MonkeyPatch, status: Any) -> None:
    """Monkeypatch `load_status` used inside progress.py to return `status`.

    If `status` is callable, each call to load_status() invokes it fresh —
    useful for tests that mutate history over multiple polls.
    """
    def _fake_load_status(*args: Any, **kwargs: Any) -> Any:
        if callable(status):
            return status()
        return status

    monkeypatch.setattr(
        "pv_inverter_proxy.updater.progress.load_status",
        _fake_load_status,
    )


def _patch_current_phase(monkeypatch: pytest.MonkeyPatch, phase: Any) -> None:
    """Monkeypatch `current_phase` to return a deterministic value."""
    def _fake_current_phase(status: Any) -> str:
        if callable(phase):
            return phase(status)
        return phase

    monkeypatch.setattr(
        "pv_inverter_proxy.updater.progress.current_phase",
        _fake_current_phase,
    )


def _make_app(num_clients: int = 2) -> dict:
    return {"ws_clients": {FakeWs() for _ in range(num_clients)}}


def _all_sent_payloads(app: dict) -> list[dict]:
    """Merge sent payloads from every FakeWs client, decode JSON, sort by sequence."""
    payloads: list[dict] = []
    for ws in app["ws_clients"]:
        for raw in ws.sent:
            payloads.append(json.loads(raw))
    return payloads


# ---------------------------------------------------------------------------
# Core poll-once emission contract (D-23, D-24)
# ---------------------------------------------------------------------------


async def test_poll_once_emits_one_message_per_new_history_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = FakeStatus(
        current={"phase": "pip_install"},
        history=[
            {"phase": "trigger_received", "at": "2026-04-11T12:00:00Z", "sequence": 0},
            {"phase": "backup", "at": "2026-04-11T12:00:05Z", "sequence": 1},
            {"phase": "pip_install", "at": "2026-04-11T12:00:10Z", "sequence": 2},
        ],
    )
    _patch_status(monkeypatch, status)
    _patch_current_phase(monkeypatch, "pip_install")

    app = _make_app(num_clients=2)
    b = ProgressBroadcaster(app)
    await b._poll_once()

    # Each of the 2 clients received exactly 3 messages.
    for ws in app["ws_clients"]:
        assert len(ws.sent) == 3
    # Payload for the first message should be the trigger_received entry.
    first = json.loads(next(iter(app["ws_clients"])).sent[0])
    assert first["type"] == "update_progress"
    assert first["data"]["phase"] == "trigger_received"


async def test_poll_once_dedupes_via_sequence_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history: list[dict] = [
        {"phase": "trigger_received", "at": "t0", "sequence": 0},
        {"phase": "backup", "at": "t1", "sequence": 1},
    ]
    status = FakeStatus(current={"phase": "backup"}, history=history)
    _patch_status(monkeypatch, lambda: FakeStatus(
        current=status.current, history=list(history)
    ))
    _patch_current_phase(monkeypatch, "backup")

    app = _make_app(num_clients=1)
    b = ProgressBroadcaster(app)

    # First poll: 2 entries → 2 messages
    await b._poll_once()
    only_ws = next(iter(app["ws_clients"]))
    assert len(only_ws.sent) == 2

    # Append a new entry and poll again: only the new entry should be sent
    history.append({"phase": "extract", "at": "t2", "sequence": 2})
    await b._poll_once()
    assert len(only_ws.sent) == 3
    last = json.loads(only_ws.sent[-1])
    assert last["data"]["phase"] == "extract"

    # Poll once more with no change: nothing new sent
    await b._poll_once()
    assert len(only_ws.sent) == 3


async def test_poll_once_with_missing_status_file_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # load_status already returns an empty UpdateStatus on missing file;
    # model that here with an empty FakeStatus.
    _patch_status(monkeypatch, FakeStatus())
    _patch_current_phase(monkeypatch, "idle")

    app = _make_app()
    b = ProgressBroadcaster(app)
    await b._poll_once()  # must not raise

    for ws in app["ws_clients"]:
        assert ws.sent == []


async def test_poll_once_with_malformed_status_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated malformed status")

    monkeypatch.setattr(
        "pv_inverter_proxy.updater.progress.load_status", _raise
    )

    app = _make_app()
    b = ProgressBroadcaster(app)
    await b._poll_once()  # must swallow the exception

    for ws in app["ws_clients"]:
        assert ws.sent == []


async def test_poll_once_with_empty_history_emits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(monkeypatch, FakeStatus(current=None, history=[]))
    _patch_current_phase(monkeypatch, "idle")

    app = _make_app()
    b = ProgressBroadcaster(app)
    await b._poll_once()

    for ws in app["ws_clients"]:
        assert ws.sent == []


async def test_poll_once_envelope_has_type_update_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(
        monkeypatch,
        FakeStatus(
            current={"phase": "backup"},
            history=[{"phase": "backup", "at": "t0", "sequence": 0}],
        ),
    )
    _patch_current_phase(monkeypatch, "backup")

    app = _make_app(num_clients=1)
    b = ProgressBroadcaster(app)
    await b._poll_once()

    payloads = _all_sent_payloads(app)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "update_progress"


async def test_poll_once_envelope_data_includes_phase_at_sequence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = {
        "phase": "healthcheck",
        "at": "2026-04-11T12:01:00Z",
        "sequence": 7,
        "error": None,
    }
    _patch_status(
        monkeypatch,
        FakeStatus(current={"phase": "healthcheck"}, history=[entry]),
    )
    _patch_current_phase(monkeypatch, "healthcheck")

    app = _make_app(num_clients=1)
    b = ProgressBroadcaster(app)
    await b._poll_once()

    payloads = _all_sent_payloads(app)
    assert len(payloads) == 1
    data = payloads[0]["data"]
    assert data["phase"] == "healthcheck"
    assert data["at"] == "2026-04-11T12:01:00Z"
    assert data["sequence"] == 7
    assert "error" in data
    assert data["error"] is None


# ---------------------------------------------------------------------------
# Interval selection (D-22)
# ---------------------------------------------------------------------------


def test_broadcaster_uses_500ms_interval_when_phase_running() -> None:
    b = ProgressBroadcaster({})
    assert b._next_interval("pip_install") == ACTIVE_POLL_INTERVAL_S
    assert b._next_interval("restarting") == ACTIVE_POLL_INTERVAL_S
    assert b._next_interval("healthcheck") == ACTIVE_POLL_INTERVAL_S


def test_broadcaster_uses_5s_interval_when_phase_idle() -> None:
    b = ProgressBroadcaster({})
    assert b._next_interval("idle") == IDLE_POLL_INTERVAL_S
    assert b._next_interval("done") == IDLE_POLL_INTERVAL_S
    assert b._next_interval("rollback_done") == IDLE_POLL_INTERVAL_S
    assert b._next_interval("rollback_failed") == IDLE_POLL_INTERVAL_S
    # Sanity: IDLE_PHASES contains exactly the four terminal phases.
    assert IDLE_PHASES == frozenset(
        {"idle", "done", "rollback_done", "rollback_failed"}
    )


async def test_broadcaster_transitions_from_idle_to_running_picks_up_within_one_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict = {"phase": "idle", "history": []}

    def _load() -> FakeStatus:
        return FakeStatus(
            current=None if state["phase"] == "idle" else {"phase": state["phase"]},
            history=list(state["history"]),
        )

    _patch_status(monkeypatch, _load)
    _patch_current_phase(monkeypatch, lambda status: state["phase"])

    app = _make_app(num_clients=1)
    # Shrink intervals so the test is fast but still exercises the loop.
    b = ProgressBroadcaster(
        app, active_interval=0.01, idle_interval=0.01
    )
    await b.start()

    # Flip from idle → running with a history entry.
    state["phase"] = "backup"
    state["history"] = [{"phase": "backup", "at": "t0", "sequence": 0}]

    # Give the loop a couple of ticks to notice.
    for _ in range(20):
        await asyncio.sleep(0.01)
        only_ws = next(iter(app["ws_clients"]))
        if only_ws.sent:
            break

    await b.stop()

    only_ws = next(iter(app["ws_clients"]))
    assert len(only_ws.sent) >= 1
    first = json.loads(only_ws.sent[0])
    assert first["data"]["phase"] == "backup"


# ---------------------------------------------------------------------------
# Lifecycle (D-40)
# ---------------------------------------------------------------------------


async def test_broadcaster_start_and_stop_cleanly_cancels_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(monkeypatch, FakeStatus())
    _patch_current_phase(monkeypatch, "idle")

    app = _make_app(num_clients=0)
    b = ProgressBroadcaster(app, active_interval=0.01, idle_interval=0.01)
    await b.start()
    # Let one iteration run.
    await asyncio.sleep(0.02)
    await asyncio.wait_for(b.stop(), timeout=1.0)
    assert b._task is None


async def test_broadcaster_survives_load_status_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    def _sometimes_raise(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("boom")
        return FakeStatus()

    monkeypatch.setattr(
        "pv_inverter_proxy.updater.progress.load_status", _sometimes_raise
    )
    _patch_current_phase(monkeypatch, "idle")

    app = _make_app()
    b = ProgressBroadcaster(app, active_interval=0.01, idle_interval=0.01)
    await b.start()
    await asyncio.sleep(0.05)
    await asyncio.wait_for(b.stop(), timeout=1.0)
    # Task must have completed at least 2 polls (one raised, one succeeded).
    assert call_count["n"] >= 2


async def test_broadcaster_survives_ws_send_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(
        monkeypatch,
        FakeStatus(
            current={"phase": "backup"},
            history=[{"phase": "backup", "at": "t0", "sequence": 0}],
        ),
    )
    _patch_current_phase(monkeypatch, "backup")

    bad_ws = FakeWs(raise_on_send=True)
    good_ws = FakeWs()
    app: dict = {"ws_clients": {bad_ws, good_ws}}

    b = ProgressBroadcaster(app)
    await b._poll_once()  # must not raise

    # Good client got the message.
    assert len(good_ws.sent) == 1
    # Bad client is discarded from the set.
    assert bad_ws not in app["ws_clients"]


async def test_dead_ws_clients_are_discarded_from_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(
        monkeypatch,
        FakeStatus(
            current={"phase": "backup"},
            history=[{"phase": "backup", "at": "t0", "sequence": 0}],
        ),
    )
    _patch_current_phase(monkeypatch, "backup")

    dead1 = FakeWs(raise_on_send=True)
    dead2 = FakeWs(raise_on_send=True)
    alive = FakeWs()
    app: dict = {"ws_clients": {dead1, dead2, alive}}

    b = ProgressBroadcaster(app)
    await b._poll_once()

    # Both dead clients evicted; alive still present.
    assert dead1 not in app["ws_clients"]
    assert dead2 not in app["ws_clients"]
    assert alive in app["ws_clients"]
    assert len(alive.sent) == 1


async def test_sequence_tracking_is_per_broadcaster_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = FakeStatus(
        current={"phase": "backup"},
        history=[
            {"phase": "trigger_received", "at": "t0", "sequence": 0},
            {"phase": "backup", "at": "t1", "sequence": 1},
        ],
    )
    _patch_status(monkeypatch, status)
    _patch_current_phase(monkeypatch, "backup")

    app_a = _make_app(num_clients=1)
    app_b = _make_app(num_clients=1)
    b_a = ProgressBroadcaster(app_a)
    b_b = ProgressBroadcaster(app_b)

    await b_a._poll_once()
    await b_b._poll_once()

    ws_a = next(iter(app_a["ws_clients"]))
    ws_b = next(iter(app_b["ws_clients"]))
    assert len(ws_a.sent) == 2
    assert len(ws_b.sent) == 2
    # Polling again should dedupe per-instance (no new sends).
    await b_a._poll_once()
    await b_b._poll_once()
    assert len(ws_a.sent) == 2
    assert len(ws_b.sent) == 2
