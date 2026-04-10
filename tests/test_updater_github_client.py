"""Unit tests for pv_inverter_proxy.updater.github_client (CHECK-03, CHECK-06).

All tests are hermetic — zero real network traffic. aiohttp is mocked with
a hand-rolled ``_MockSession`` / ``_MockResponse`` pair so we don't add
``aioresponses`` as a test dependency.

Every test uses ``tmp_path`` for the ETag state file, so the real
``DEFAULT_STATE_FILE`` (``/etc/pv-inverter-proxy/update-state.json``) is
NEVER touched by the test suite.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pv_inverter_proxy.updater import github_client as gh_mod
from pv_inverter_proxy.updater.github_client import (
    ACCEPT,
    API_VERSION,
    GITHUB_API_URL,
    USER_AGENT,
    GithubReleaseClient,
    ReleaseInfo,
)


# ---------------------------------------------------------------------------
# Hand-rolled aiohttp mocks
# ---------------------------------------------------------------------------


class _MockResponse:
    """Minimal aiohttp.ClientResponse stand-in.

    Supports ``async with``, ``await resp.json()``, ``await resp.text()``,
    and ``resp.headers``. ``json_data=None`` makes ``.json()`` raise a
    ``JSONDecodeError`` — use that to exercise the parse-error path.
    """

    def __init__(
        self,
        status: int,
        json_data: Any | None = None,
        text_data: str = "",
        headers: dict[str, str] | None = None,
        raise_on_json: Exception | None = None,
    ) -> None:
        self.status = status
        self._json = json_data
        self._text = text_data
        self.headers = headers or {}
        self._raise_on_json = raise_on_json

    async def json(self) -> Any:
        if self._raise_on_json is not None:
            raise self._raise_on_json
        if self._json is None:
            raise json.JSONDecodeError("no json body", "", 0)
        return self._json

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_MockResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class _MockSession:
    """Drop-in stand-in for aiohttp.ClientSession with .get()."""

    def __init__(self, responses: list[_MockResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> Any:
        self.calls.append(
            {"url": url, "headers": dict(headers or {}), "timeout": timeout}
        )
        if not self._responses:
            raise AssertionError("No more mock responses queued")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            # Raise on __aenter__ by returning a context manager that raises
            return _RaisingContext(nxt)
        return nxt


class _RaisingContext:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def __aenter__(self) -> Any:
        raise self.exc

    async def __aexit__(self, *args: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _sample_release_json(prerelease: bool = False) -> dict[str, Any]:
    return {
        "tag_name": "v8.0.1",
        "published_at": "2026-04-10T12:00:00Z",
        "body": "## Changelog\n- fixed bug",
        "html_url": "https://github.com/meintechblog/pv-inverter-master/releases/tag/v8.0.1",
        "prerelease": prerelease,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_fetch_success_returns_release_info(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    resp = _MockResponse(
        status=200,
        json_data=_sample_release_json(),
        headers={"ETag": 'W/"abc123"'},
    )
    session = _MockSession([resp])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    release = await client.fetch_latest_release()

    assert release is not None
    assert isinstance(release, ReleaseInfo)
    assert release.tag_name == "v8.0.1"
    assert release.published_at == "2026-04-10T12:00:00Z"
    assert release.body == "## Changelog\n- fixed bug"
    assert release.html_url.endswith("/v8.0.1")
    assert release.prerelease is False
    # State file was written atomically
    assert state_file.exists()
    saved = json.loads(state_file.read_text())
    assert saved["etag"] == 'W/"abc123"'
    assert saved["release"]["tag_name"] == "v8.0.1"


async def test_fetch_sends_required_headers(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession(
        [_MockResponse(status=200, json_data=_sample_release_json())]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    await client.fetch_latest_release()

    assert session.calls, "client did not call session.get"
    headers = session.calls[0]["headers"]
    assert headers.get("User-Agent") == USER_AGENT
    assert headers.get("Accept") == ACCEPT
    assert headers.get("X-GitHub-Api-Version") == API_VERSION
    # No If-None-Match on first call (no prior ETag)
    assert "If-None-Match" not in headers
    # Correct URL
    assert session.calls[0]["url"] == GITHUB_API_URL


async def test_fetch_uses_10s_timeout(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession(
        [_MockResponse(status=200, json_data=_sample_release_json())]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    await client.fetch_latest_release()

    timeout = session.calls[0]["timeout"]
    assert timeout is not None
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total == 10.0


# ---------------------------------------------------------------------------
# ETag caching
# ---------------------------------------------------------------------------


async def test_fetch_persists_etag_and_sends_if_none_match_on_next_call(
    tmp_path: Path,
):
    state_file = tmp_path / "update-state.json"
    etag = 'W/"abc123"'
    # Call 1: 200 with ETag → persists
    # Call 2: 304 → should send If-None-Match
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                json_data=_sample_release_json(),
                headers={"ETag": etag},
            ),
            _MockResponse(status=304),
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    first = await client.fetch_latest_release()
    assert first is not None and first.tag_name == "v8.0.1"

    # Second call: a NEW client instance should also see the persisted ETag
    client2 = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    second = await client2.fetch_latest_release()
    # 304 with cache → returns the cached release
    assert second is not None
    assert second.tag_name == "v8.0.1"

    # Verify the If-None-Match header was sent on call 2
    assert len(session.calls) == 2
    assert session.calls[1]["headers"].get("If-None-Match") == etag


async def test_fetch_304_returns_cached_release(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    # Pre-prime the state file with a cached release + etag
    state_file.write_text(
        json.dumps(
            {
                "etag": 'W/"cached-tag"',
                "release": {
                    "tag_name": "v7.9.0",
                    "published_at": "2026-03-01T00:00:00Z",
                    "body": "prior",
                    "html_url": "https://example.com",
                    "prerelease": False,
                },
            }
        )
    )
    session = _MockSession([_MockResponse(status=304)])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    result = await client.fetch_latest_release()
    assert result is not None
    assert result.tag_name == "v7.9.0"
    # If-None-Match was sent
    assert session.calls[0]["headers"].get("If-None-Match") == 'W/"cached-tag"'


async def test_fetch_304_before_any_cache_returns_none(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([_MockResponse(status=304)])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]

    result = await client.fetch_latest_release()
    assert result is None


# ---------------------------------------------------------------------------
# Error paths — all return None, never raise
# ---------------------------------------------------------------------------


async def test_fetch_403_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession(
        [
            _MockResponse(
                status=403,
                text_data='{"message": "API rate limit exceeded"}',
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_429_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([_MockResponse(status=429)])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_fetch_5xx_returns_none_no_raise(tmp_path: Path, status: int):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([_MockResponse(status=status)])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_unexpected_status_returns_none(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([_MockResponse(status=418)])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_prerelease_returns_none(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                json_data=_sample_release_json(prerelease=True),
                headers={"ETag": 'W/"beta1"'},
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_timeout_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([asyncio.TimeoutError()])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_client_error_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession([aiohttp.ClientError("connection refused")])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_malformed_json_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                raise_on_json=json.JSONDecodeError("bad json", "", 0),
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


async def test_fetch_missing_key_returns_none_no_raise(tmp_path: Path):
    state_file = tmp_path / "update-state.json"
    # json is a non-dict — will trigger KeyError / ValueError on .get()
    session = _MockSession(
        [_MockResponse(status=200, json_data="not a dict")]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    # Should not raise; returns None
    result = await client.fetch_latest_release()
    assert result is None


async def test_fetch_unexpected_exception_returns_none(tmp_path: Path):
    """Even a totally unexpected error must not crash."""
    state_file = tmp_path / "update-state.json"
    session = _MockSession([RuntimeError("kaboom")])
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    assert await client.fetch_latest_release() is None


# ---------------------------------------------------------------------------
# State file resilience
# ---------------------------------------------------------------------------


async def test_state_file_injection_for_tests(tmp_path: Path):
    state_file = tmp_path / "subdir" / "state.json"
    state_file.parent.mkdir()
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                json_data=_sample_release_json(),
                headers={"ETag": 'W/"x"'},
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    release = await client.fetch_latest_release()
    assert release is not None
    assert state_file.exists()


async def test_state_file_write_failure_does_not_crash_fetch(tmp_path: Path):
    # State file path points into a non-existent directory → write will fail
    bogus = tmp_path / "does" / "not" / "exist" / "state.json"
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                json_data=_sample_release_json(),
                headers={"ETag": 'W/"x"'},
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=bogus)  # type: ignore[arg-type]
    # fetch must still succeed — save_state is best-effort
    release = await client.fetch_latest_release()
    assert release is not None
    assert release.tag_name == "v8.0.1"


async def test_corrupt_state_file_is_ignored_on_load(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{ this is not json")
    session = _MockSession(
        [
            _MockResponse(
                status=200,
                json_data=_sample_release_json(),
                headers={"ETag": 'W/"x"'},
            )
        ]
    )
    client = GithubReleaseClient(session, state_file=state_file)  # type: ignore[arg-type]
    # Should not raise during __init__
    release = await client.fetch_latest_release()
    assert release is not None
    # No prior ETag was loaded from the corrupt file
    assert "If-None-Match" not in session.calls[0]["headers"]


def test_default_state_file_constant():
    """Sanity: the production default path is the documented location."""
    assert str(gh_mod.DEFAULT_STATE_FILE) == "/etc/pv-inverter-proxy/update-state.json"
