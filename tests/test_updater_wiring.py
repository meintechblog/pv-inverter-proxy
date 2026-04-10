"""Integration tests for the scheduler callback wiring in __main__.py.

Covers Plan 44-02 CHECK-01/02/07:

- ``_on_update_available(app_ctx, release)`` mutates AppContext correctly
  for every release/version combination (newer, same, older, unknown,
  unparseable, None).
- Stale ``available_update`` is preserved when a fetch fails (release is
  None), so a transient network error does not clear a previously
  advertised update.
- ``_has_active_ws_client(app_ctx)`` reports False when no webapp /
  ws_clients exist, True when the weakset has members.
- Broadcast is invoked exactly when the available_update dict changes
  and the webapp is attached.

These tests import the callback and probe directly from ``__main__`` so
the module-level refactor (closure -> top-level function) is exercised
end-to-end.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pv_inverter_proxy.__main__ import (
    _has_active_ws_client,
    _on_update_available,
)
from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.updater.github_client import ReleaseInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_release(
    tag: str = "v8.1.0",
    body: str = "notes",
    prerelease: bool = False,
) -> ReleaseInfo:
    return ReleaseInfo(
        tag_name=tag,
        published_at="2026-05-01T00:00:00Z",
        body=body,
        html_url=(
            f"https://github.com/meintechblog/pv-inverter-master/releases/tag/{tag}"
        ),
        prerelease=prerelease,
    )


def _ctx(current_version: str = "8.0.0") -> AppContext:
    ctx = AppContext()
    ctx.current_version = current_version
    ctx.current_commit = "abc123d"
    return ctx


# ---------------------------------------------------------------------------
# _on_update_available — version comparison + AppContext mutation
# ---------------------------------------------------------------------------


async def test_newer_release_sets_available_update():
    """When GitHub returns a newer release, available_update is populated."""
    ctx = _ctx("8.0.0")
    await _on_update_available(ctx, _make_release("v8.1.0"))
    assert ctx.available_update is not None
    assert ctx.available_update["latest_version"] == "v8.1.0"
    assert ctx.available_update["tag_name"] == "v8.1.0"
    assert ctx.available_update["release_notes"] == "notes"
    assert ctx.update_last_check_at is not None
    assert ctx.update_last_check_failed_at is None


async def test_same_version_clears_available_update():
    """Scheduler re-runs and the upstream is unchanged -> stale marker clears."""
    ctx = _ctx("8.0.0")
    ctx.available_update = {"latest_version": "v8.0.0"}  # stale
    await _on_update_available(ctx, _make_release("v8.0.0"))
    assert ctx.available_update is None
    assert ctx.update_last_check_at is not None


async def test_older_release_clears_available_update():
    """Running a dev build newer than upstream -> no upgrade offered."""
    ctx = _ctx("8.1.0")
    ctx.available_update = {"latest_version": "v8.0.0"}  # stale
    await _on_update_available(ctx, _make_release("v8.0.0"))
    assert ctx.available_update is None


async def test_none_release_leaves_state_unchanged():
    """Transient fetch error must NOT clear a previously advertised update.

    CHECK-06: the scheduler's own last_check_failed_at tracks the failure;
    the callback only bumps last_check_at and leaves available_update alone
    so the UI doesn't flicker between "update available" and "no update".
    """
    ctx = _ctx("8.0.0")
    ctx.available_update = {"latest_version": "v8.1.0"}
    await _on_update_available(ctx, None)
    assert ctx.available_update is not None
    assert ctx.available_update["latest_version"] == "v8.1.0"
    assert ctx.update_last_check_at is not None


async def test_unknown_current_version_shows_release_as_available():
    """If current version can't be resolved, defensively advertise the release."""
    ctx = _ctx("unknown")
    await _on_update_available(ctx, _make_release("v8.1.0"))
    assert ctx.available_update is not None
    assert ctx.available_update["latest_version"] == "v8.1.0"


async def test_malformed_tag_does_not_crash():
    """A non-version tag must NOT raise, and must clear any stale marker."""
    ctx = _ctx("8.0.0")
    ctx.available_update = {"latest_version": "v8.1.0"}
    await _on_update_available(ctx, _make_release("not-a-version"))
    assert ctx.available_update is None
    assert ctx.update_last_check_at is not None


async def test_unparseable_current_version_defensively_advertises():
    """Dev build with arbitrary version string -> always show release."""
    ctx = _ctx("dev-snapshot")
    await _on_update_available(ctx, _make_release("v8.1.0"))
    assert ctx.available_update is not None
    assert ctx.available_update["latest_version"] == "v8.1.0"


async def test_release_fields_persisted_verbatim():
    """All ReleaseInfo fields needed by the UI round-trip through the dict."""
    ctx = _ctx("8.0.0")
    rel = ReleaseInfo(
        tag_name="v9.0.0",
        published_at="2027-01-01T00:00:00Z",
        body="## Breaking\n- removed foo",
        html_url="https://github.com/meintechblog/pv-inverter-master/releases/tag/v9.0.0",
        prerelease=False,
    )
    await _on_update_available(ctx, rel)
    assert ctx.available_update == {
        "latest_version": "v9.0.0",
        "tag_name": "v9.0.0",
        "release_notes": "## Breaking\n- removed foo",
        "published_at": "2027-01-01T00:00:00Z",
        "html_url": "https://github.com/meintechblog/pv-inverter-master/releases/tag/v9.0.0",
    }


# ---------------------------------------------------------------------------
# _on_update_available — broadcast side-effect
# ---------------------------------------------------------------------------


async def test_broadcast_invoked_when_update_changes(monkeypatch):
    """When available_update transitions None -> dict, broadcast fires once."""
    ctx = _ctx("8.0.0")
    fake_app = MagicMock()
    ctx.webapp = fake_app
    broadcast = AsyncMock()
    monkeypatch.setattr(
        "pv_inverter_proxy.__main__.broadcast_available_update", broadcast
    )
    await _on_update_available(ctx, _make_release("v8.1.0"))
    broadcast.assert_awaited_once_with(fake_app)


async def test_broadcast_skipped_when_nothing_changes(monkeypatch):
    """Equal release on re-poll must not re-broadcast (coarse de-dup)."""
    ctx = _ctx("8.0.0")
    fake_app = MagicMock()
    ctx.webapp = fake_app
    existing = {
        "latest_version": "v8.1.0",
        "tag_name": "v8.1.0",
        "release_notes": "notes",
        "published_at": "2026-05-01T00:00:00Z",
        "html_url": (
            "https://github.com/meintechblog/pv-inverter-master/releases/tag/v8.1.0"
        ),
    }
    ctx.available_update = dict(existing)
    broadcast = AsyncMock()
    monkeypatch.setattr(
        "pv_inverter_proxy.__main__.broadcast_available_update", broadcast
    )
    await _on_update_available(ctx, _make_release("v8.1.0"))
    broadcast.assert_not_awaited()


async def test_broadcast_skipped_when_webapp_missing(monkeypatch):
    """During very early startup ``ctx.webapp`` is None -> no broadcast attempt."""
    ctx = _ctx("8.0.0")
    ctx.webapp = None
    broadcast = AsyncMock()
    monkeypatch.setattr(
        "pv_inverter_proxy.__main__.broadcast_available_update", broadcast
    )
    await _on_update_available(ctx, _make_release("v8.1.0"))
    broadcast.assert_not_awaited()
    # but state was still updated
    assert ctx.available_update is not None


# ---------------------------------------------------------------------------
# _has_active_ws_client (CHECK-07)
# ---------------------------------------------------------------------------


def test_has_active_ws_client_no_webapp():
    ctx = AppContext()
    ctx.webapp = None
    assert _has_active_ws_client(ctx) is False


def test_has_active_ws_client_empty_set():
    ctx = AppContext()
    fake_app = {"ws_clients": set()}
    ctx.webapp = fake_app
    assert _has_active_ws_client(ctx) is False


def test_has_active_ws_client_with_connected_client():
    ctx = AppContext()
    fake_app = {"ws_clients": {"ws1"}}
    ctx.webapp = fake_app
    assert _has_active_ws_client(ctx) is True


def test_has_active_ws_client_missing_key():
    """If the webapp dict lacks ws_clients entirely, report False gracefully."""
    ctx = AppContext()
    ctx.webapp = {}
    assert _has_active_ws_client(ctx) is False
