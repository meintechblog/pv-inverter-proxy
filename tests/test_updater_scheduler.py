"""Unit tests for pv_inverter_proxy.updater.scheduler (CHECK-02, 06, 07).

Tests use real asyncio.sleep with small delays (<= 0.3s) to exercise the
actual loop timing. Fakes rather than mocks keep the tests readable.

Every test finishes in well under 2 seconds total. Each test cancels the
scheduler task cleanly in a finally block so there are no leaked tasks.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pv_inverter_proxy.updater.github_client import ReleaseInfo
from pv_inverter_proxy.updater.scheduler import UpdateCheckScheduler


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Stand-in for GithubReleaseClient.

    Feed it a list of results (ReleaseInfo | None | Exception). Each call to
    fetch_latest_release() consumes one element; if the list is empty the
    last element is returned repeatedly. Exceptions are raised.
    """

    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.calls = 0

    async def fetch_latest_release(self) -> Any:
        self.calls += 1
        if not self.results:
            return None
        idx = min(self.calls - 1, len(self.results) - 1)
        nxt = self.results[idx]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _sample_release() -> ReleaseInfo:
    return ReleaseInfo(
        tag_name="v8.0.1",
        published_at="2026-04-10T12:00:00Z",
        body="body",
        html_url="https://example.com",
        prerelease=False,
    )


async def _run_scheduler_for(
    scheduler: UpdateCheckScheduler, duration_s: float
) -> None:
    """Start the scheduler, let it run for duration_s, then cancel cleanly."""
    task = scheduler.start()
    try:
        await asyncio.sleep(duration_s)
    finally:
        await scheduler.stop()
        # Belt-and-braces — make sure the task is fully done
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


async def test_start_respects_initial_delay():
    client = FakeClient([None])
    updates: list[Any] = []
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: updates.append(r),
        has_active_websocket_client=lambda: False,
        interval_seconds=1.0,
        initial_delay_seconds=0.1,
    )

    task = scheduler.start()
    try:
        # Before initial_delay elapses: zero calls
        await asyncio.sleep(0.03)
        assert client.calls == 0
        # After initial_delay: at least one call
        await asyncio.sleep(0.15)
        assert client.calls >= 1
    finally:
        await scheduler.stop()


async def test_interval_between_checks():
    client = FakeClient([None])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.1,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.35)
    # Expect ~3-5 calls in 0.35s with 0.1s interval
    assert 2 <= client.calls <= 6, f"got {client.calls} calls"


# ---------------------------------------------------------------------------
# Defer on active user (CHECK-07)
# ---------------------------------------------------------------------------


async def test_defer_when_user_active():
    client = FakeClient([None])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: True,  # always active
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.2)
    assert client.calls == 0, "scheduler should have deferred every check"


async def test_defer_then_run_when_user_disconnects():
    client = FakeClient([None])
    state = {"active": True}
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: state["active"],
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    task = scheduler.start()
    try:
        # Active for the first 0.15s — no fetches
        await asyncio.sleep(0.15)
        assert client.calls == 0
        # Disconnect, give it time to fire
        state["active"] = False
        await asyncio.sleep(0.2)
        assert client.calls >= 1
    finally:
        await scheduler.stop()


async def test_active_probe_exception_does_not_crash():
    client = FakeClient([None])

    def _raising() -> bool:
        raise RuntimeError("ws state broken")

    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=_raising,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.2)
    # Probe failure should fall through → fetch still runs
    assert client.calls >= 1


# ---------------------------------------------------------------------------
# Exception handling (CHECK-06)
# ---------------------------------------------------------------------------


async def test_exception_in_fetch_sets_failed_at_and_continues():
    client = FakeClient([RuntimeError("boom"), RuntimeError("boom2")])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.2)

    assert client.calls >= 2, "loop should continue after exception"
    assert scheduler.last_check_failed_at is not None


async def test_exception_in_callback_sets_failed_at_and_continues():
    client = FakeClient([_sample_release()])

    def _bad_cb(_: Any) -> None:
        raise RuntimeError("callback broken")

    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=_bad_cb,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.2)
    assert client.calls >= 2
    assert scheduler.last_check_failed_at is not None


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancelled_error_propagates_cleanly():
    client = FakeClient([None])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=10.0,  # long — we cancel before it fires
        initial_delay_seconds=10.0,
    )

    task = scheduler.start()
    # Let the task start up
    await asyncio.sleep(0.01)
    await scheduler.stop()

    # Task should be done / cancelled, and awaiting should not raise
    assert task.done()


async def test_stop_is_idempotent():
    client = FakeClient([None])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.1,
        initial_delay_seconds=0.0,
    )

    scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()
    # Second stop must not raise
    await scheduler.stop()


# ---------------------------------------------------------------------------
# Callback variants
# ---------------------------------------------------------------------------


async def test_async_callback_is_awaited():
    client = FakeClient([_sample_release()])
    received: list[Any] = []

    async def _async_cb(release: Any) -> None:
        received.append(release)

    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=_async_cb,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.15)
    assert len(received) >= 1
    assert received[0].tag_name == "v8.0.1"


async def test_sync_callback_is_called():
    client = FakeClient([_sample_release()])
    received: list[Any] = []

    def _sync_cb(release: Any) -> None:
        received.append(release)

    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=_sync_cb,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.15)
    assert len(received) >= 1
    assert received[0].tag_name == "v8.0.1"


# ---------------------------------------------------------------------------
# last_check_at
# ---------------------------------------------------------------------------


async def test_successful_check_updates_last_check_at():
    client = FakeClient([_sample_release()])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    assert scheduler.last_check_at is None

    await _run_scheduler_for(scheduler, 0.15)

    assert scheduler.last_check_at is not None
    import time

    # last_check_at should be within the last second
    assert time.time() - scheduler.last_check_at < 1.5


async def test_none_release_still_updates_last_check_at():
    """Plan 44 contract: None return = 'no update', still counts as success."""
    client = FakeClient([None])
    scheduler = UpdateCheckScheduler(
        github_client=client,
        on_update_available=lambda r: None,
        has_active_websocket_client=lambda: False,
        interval_seconds=0.05,
        initial_delay_seconds=0.0,
    )

    await _run_scheduler_for(scheduler, 0.15)
    assert scheduler.last_check_at is not None
