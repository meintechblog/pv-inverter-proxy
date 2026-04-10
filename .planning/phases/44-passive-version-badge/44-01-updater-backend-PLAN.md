---
phase: 44-passive-version-badge
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/pv_inverter_proxy/updater/__init__.py
  - src/pv_inverter_proxy/updater/version.py
  - src/pv_inverter_proxy/updater/github_client.py
  - src/pv_inverter_proxy/updater/scheduler.py
  - tests/test_updater_version.py
  - tests/test_updater_github_client.py
  - tests/test_updater_scheduler.py
autonomous: true
requirements:
  - CHECK-02
  - CHECK-03
  - CHECK-06
  - CHECK-07
must_haves:
  truths:
    - "Version NamedTuple parses vX.Y, vX.Y.Z, and rejects malformed strings"
    - "get_current_version() returns a string from importlib.metadata with fallbacks, never raises"
    - "GithubReleaseClient sends required User-Agent, Accept, X-GitHub-Api-Version headers on every call"
    - "GithubReleaseClient uses a 10s aiohttp timeout and returns None (not exception) on network errors, 5xx, and 403"
    - "GithubReleaseClient persists ETag to /etc/pv-inverter-proxy/update-state.json atomically and sends If-None-Match on subsequent calls"
    - "GithubReleaseClient filters out prereleases (prerelease=true in response)"
    - "UpdateCheckScheduler waits 60s initial delay before first check"
    - "UpdateCheckScheduler swallows all exceptions (except CancelledError), logs structlog warning, and continues looping"
    - "UpdateCheckScheduler defers check by 1h when has_active_websocket_client callback returns True"
    - "UpdateCheckScheduler is cancellable via asyncio.Task.cancel() and exits cleanly on CancelledError"
  artifacts:
    - path: "src/pv_inverter_proxy/updater/__init__.py"
      provides: "Package marker for updater subpackage"
    - path: "src/pv_inverter_proxy/updater/version.py"
      provides: "Version NamedTuple + parser + get_current_version()"
      exports: ["Version", "get_current_version", "get_commit_hash"]
      min_lines: 60
    - path: "src/pv_inverter_proxy/updater/github_client.py"
      provides: "GithubReleaseClient with aiohttp + ETag cache"
      exports: ["GithubReleaseClient", "ReleaseInfo"]
      min_lines: 150
    - path: "src/pv_inverter_proxy/updater/scheduler.py"
      provides: "UpdateCheckScheduler asyncio task loop"
      exports: ["UpdateCheckScheduler"]
      min_lines: 100
    - path: "tests/test_updater_version.py"
      provides: "Version parser tests"
      min_lines: 40
    - path: "tests/test_updater_github_client.py"
      provides: "GitHub client tests with mocked aiohttp"
      min_lines: 120
    - path: "tests/test_updater_scheduler.py"
      provides: "Scheduler tests: initial delay, error swallow, defer-on-active-user, cancellation"
      min_lines: 100
  key_links:
    - from: "src/pv_inverter_proxy/updater/scheduler.py"
      to: "src/pv_inverter_proxy/updater/github_client.py"
      via: "UpdateCheckScheduler holds a GithubReleaseClient instance and calls fetch_latest_release()"
      pattern: "GithubReleaseClient"
    - from: "src/pv_inverter_proxy/updater/github_client.py"
      to: "/etc/pv-inverter-proxy/update-state.json"
      via: "ETag persistence via tempfile + os.replace (mirrors state_file.py)"
      pattern: "os\\.replace"
    - from: "src/pv_inverter_proxy/updater/version.py"
      to: "importlib.metadata"
      via: "importlib.metadata.version('pv-inverter-master') with fallbacks"
      pattern: "importlib\\.metadata"
---

<objective>
Build the pure-backend updater subsystem: Version parsing, GitHub Releases API client with ETag caching, and the asyncio check scheduler. All three modules are testable in isolation, have zero wiring into the running service (Plan 44-02 handles that), and land with full unit test coverage.

Purpose: Deliver CHECK-02 (scheduler), CHECK-03 (aiohttp client with proper headers + ETag), CHECK-06 (fault tolerance), and CHECK-07 (defer on active user). CHECK-01, CHECK-04, CHECK-05 depend on this backend and land in Plans 44-02 and 44-03.

Output: Three new modules under `src/pv_inverter_proxy/updater/` plus three test files under `tests/`, all passing `pytest`. No changes to existing running code — Plan 44-02 wires these into `__main__.py` and `webapp.py`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/research/STACK.md
@.planning/research/ARCHITECTURE.md
@.planning/research/FEATURES.md
@CLAUDE.md

# Existing patterns to mirror
@src/pv_inverter_proxy/state_file.py
@src/pv_inverter_proxy/releases.py
@pyproject.toml

<interfaces>
<!-- Extracted interfaces the executor needs — do NOT re-explore the codebase -->

From src/pv_inverter_proxy/state_file.py (pattern to mirror for ETag persistence):
```python
# Atomic write pattern — tempfile sibling + os.replace + chmod 0o644
def save_state(state: PersistedState, path: Path | None = None) -> None:
    target = path or STATE_FILE_PATH
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(asdict(state), indent=2, sort_keys=True)
    try:
        tmp.write_text(payload)
        os.replace(tmp, target)
        os.chmod(target, 0o644)
    except FileNotFoundError:
        log.error("state_file_parent_missing", path=str(target))
        raise
    except OSError as e:
        log.error("state_file_write_failed", path=str(target), error=str(e))
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
```

From pyproject.toml (PACKAGE NAME and CURRENT VERSION):
```toml
[project]
name = "pv-inverter-master"   # ← use this exact string for importlib.metadata.version()
version = "6.0.0"              # ← note: NOT 8.0.0 yet; Plan 44-02 bumps this. For 44-01 tests, mock or accept whatever is returned.
```

From src/pv_inverter_proxy/releases.py (how install paths are resolved):
```python
RELEASES_ROOT: Path = Path("/opt/pv-inverter-proxy-releases")
INSTALL_ROOT: Path = Path("/opt/pv-inverter-proxy")
```

structlog usage pattern (every module):
```python
import structlog
log = structlog.get_logger(component="updater.<modulename>")
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: version.py — Version NamedTuple, parser, get_current_version, get_commit_hash</name>
  <files>
    src/pv_inverter_proxy/updater/__init__.py,
    src/pv_inverter_proxy/updater/version.py,
    tests/test_updater_version.py
  </files>
  <behavior>
    - Version.parse("v8.0") returns Version(8, 0, 0)
    - Version.parse("v8.0.1") returns Version(8, 0, 1)
    - Version.parse("8.0.1") returns Version(8, 0, 1) (leading v optional)
    - Version.parse("  v8.0.1  ") strips whitespace
    - Version.parse("8") raises ValueError
    - Version.parse("v8.0.1.2") raises ValueError
    - Version.parse("latest") raises ValueError
    - Version.parse("") raises ValueError
    - Version(8, 0, 1) &gt; Version(8, 0, 0) (tuple ordering)
    - Version(8, 1, 0) &gt; Version(8, 0, 99) (tuple ordering)
    - str(Version(8, 0, 1)) == "v8.0.1"
    - get_current_version() returns a non-empty string, never raises
    - get_current_version() prefers importlib.metadata.version("pv-inverter-master"); falls back to "unknown" if package is not installed (mock PackageNotFoundError to test)
    - get_commit_hash(install_dir) returns a 7-char short SHA on success
    - get_commit_hash returns None when .git is missing (use tmp_path with no .git)
    - get_commit_hash returns None when subprocess fails (mock subprocess.run to raise or return non-zero)
    - get_commit_hash never raises
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/__init__.py` as empty package marker (single-line docstring: `"""Update discovery subsystem (CHECK-xx requirements, Phase 44)."""`).

    Create `src/pv_inverter_proxy/updater/version.py` with:

    1. Module docstring referencing CHECK-01, STACK.md section 2, and stating "hand-rolled to avoid `packaging`/`semver` dependencies per stack research".
    2. Imports: `from __future__ import annotations`, `import re`, `import subprocess`, `from importlib import metadata`, `from pathlib import Path`, `from typing import NamedTuple`, `import structlog`.
    3. Module-level `log = structlog.get_logger(component="updater.version")`.
    4. `_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")`
    5. `PACKAGE_NAME = "pv-inverter-master"` constant (matches pyproject.toml [project].name).
    6. `class Version(NamedTuple)` with fields `major: int`, `minor: int`, `patch: int`.
       - `@classmethod def parse(cls, raw: str) -> "Version"` that strips, applies `_VERSION_RE`, raises `ValueError(f"Unparseable version: {raw!r}")` on no-match. Returns `cls(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))`.
       - `def __str__(self) -> str: return f"v{self.major}.{self.minor}.{self.patch}"`
    7. `def get_current_version() -> str:` — tries `metadata.version(PACKAGE_NAME)`, catches `metadata.PackageNotFoundError` and returns `"unknown"`, catches any other Exception and also returns `"unknown"` with a warning log. Never raises.
    8. `def get_commit_hash(install_dir: Path | None = None) -> str | None:` — runs `subprocess.run(["git", "-C", str(install_dir or Path("/opt/pv-inverter-proxy")), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False)`. If returncode == 0 and stdout is non-empty, returns `stdout.strip()[:7]`. On any FileNotFoundError, subprocess.TimeoutExpired, OSError, or non-zero returncode, logs debug and returns None. NEVER raises.

    Create `tests/test_updater_version.py`:
    - Write tests FIRST covering every bullet in &lt;behavior&gt;.
    - Use `pytest.raises(ValueError)` for malformed inputs.
    - For get_current_version fallback: `monkeypatch.setattr("pv_inverter_proxy.updater.version.metadata.version", lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError(name)))`.
    - For get_commit_hash tests: use `tmp_path` (no .git), assert None; mock subprocess.run via monkeypatch for the success path and for the exception-raising path.
    - All tests sync (no asyncio).

    Why: `importlib.metadata` is stdlib since 3.8; avoids adding `packaging`. Tuple ordering of NamedTuple gives free comparison operators. Fallback to "unknown" means an editable-install or broken pyproject never crashes the service.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -m pytest tests/test_updater_version.py -x -v</automated>
  </verify>
  <done>
    All tests pass. `from pv_inverter_proxy.updater.version import Version, get_current_version, get_commit_hash` succeeds. `Version.parse("v8.0")` returns `Version(8, 0, 0)`. `get_current_version()` returns a string in a clean checkout (either "6.0.0" or "unknown" depending on pip install state). `get_commit_hash(Path("/tmp"))` returns None.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: github_client.py — aiohttp GitHub Releases client with ETag cache</name>
  <files>
    src/pv_inverter_proxy/updater/github_client.py,
    tests/test_updater_github_client.py
  </files>
  <behavior>
    - fetch_latest_release() sends GET to https://api.github.com/repos/meintechblog/pv-inverter-master/releases/latest
    - Request includes User-Agent "pv-inverter-proxy/8.0 (github.com/meintechblog/pv-inverter-master)"
    - Request includes Accept "application/vnd.github+json"
    - Request includes X-GitHub-Api-Version "2022-11-28"
    - Uses aiohttp.ClientTimeout(total=10)
    - On 200 with valid JSON: returns ReleaseInfo dataclass with tag_name, published_at, body, html_url, prerelease
    - On 200 with prerelease=true: returns None (filters prereleases out)
    - On 304 Not Modified: returns cached ReleaseInfo (from previous call's cache file)
    - On 403 (rate limit): returns None, logs warning, does not raise
    - On 500/502/503: returns None, logs warning, does not raise
    - On asyncio.TimeoutError / aiohttp.ClientError: returns None, logs warning, does not raise
    - On JSON parse error: returns None, logs warning, does not raise
    - After a successful 200: persists {etag, release} to update-state.json atomically
    - On subsequent call: reads persisted etag from disk and sends If-None-Match header
    - Uses a caller-supplied aiohttp.ClientSession (does not create its own — for sharing with existing session)
    - State file path is injectable via constructor for testing
    - Filters prereleases: response with prerelease=true is treated as "no release available" and returns None
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/github_client.py` (~180 LOC).

    Module docstring: reference CHECK-03, CHECK-06, STACK.md section 1, ARCHITECTURE.md "Version Source of Truth" section.

    Imports:
    ```python
    from __future__ import annotations
    import asyncio
    import json
    import os
    from dataclasses import dataclass, asdict
    from pathlib import Path
    from typing import Optional
    import aiohttp
    import structlog
    ```

    Constants:
    ```python
    log = structlog.get_logger(component="updater.github_client")
    GITHUB_REPO = "meintechblog/pv-inverter-master"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    USER_AGENT = "pv-inverter-proxy/8.0 (github.com/meintechblog/pv-inverter-master)"
    ACCEPT = "application/vnd.github+json"
    API_VERSION = "2022-11-28"
    REQUEST_TIMEOUT_SECONDS = 10.0
    DEFAULT_STATE_FILE = Path("/etc/pv-inverter-proxy/update-state.json")
    ```

    `@dataclass(frozen=True)` `ReleaseInfo`:
    - `tag_name: str`
    - `published_at: str`
    - `body: str`
    - `html_url: str`
    - `prerelease: bool`

    `class GithubReleaseClient`:
    - `__init__(self, session: aiohttp.ClientSession, state_file: Path = DEFAULT_STATE_FILE)`: stores session, state_file. Reads any existing ETag from disk into `self._etag` (None on missing/corrupt). Reads any cached release into `self._cached_release`.
    - `_load_state(self) -> None`: reads state_file if exists, parses JSON, extracts `etag` (str or None) and `release` (dict that can reconstruct ReleaseInfo). Silent on missing/corrupt.
    - `_save_state(self, etag: str | None, release: ReleaseInfo | None) -> None`: atomic write via `tmp = state_file.with_suffix(".json.tmp")`, `tmp.write_text(json.dumps({"etag": etag, "release": asdict(release) if release else None}, indent=2, sort_keys=True))`, `os.replace(tmp, state_file)`, `os.chmod(state_file, 0o644)`. Wrap in try/except OSError — log warning on failure, do NOT raise (state file write failure must not crash the caller).
    - `async def fetch_latest_release(self) -> Optional[ReleaseInfo]`:
      1. Build headers dict with User-Agent, Accept, X-GitHub-Api-Version. If `self._etag`, add `If-None-Match: {etag}`.
      2. Try: `async with self._session.get(GITHUB_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:`
      3. If `resp.status == 304`: log info "github_release_not_modified", return `self._cached_release` (may be None if first call).
      4. If `resp.status == 403`: log warning "github_rate_limit_or_forbidden", return None. Try to read a short snippet of resp.text() for logging (best-effort).
      5. If `resp.status >= 500`: log warning "github_server_error" with status, return None.
      6. If `resp.status != 200`: log warning "github_unexpected_status" with status, return None.
      7. On 200: parse JSON via `await resp.json()`. Extract `tag_name`, `published_at`, `body`, `html_url`, `prerelease` with `.get()` fallbacks (empty strings, False). If `prerelease is True`: log info "github_release_is_prerelease_skipped", return None (still persist etag).
      8. Build `ReleaseInfo(...)`. Read `resp.headers.get("ETag")` into new_etag.
      9. Call `self._save_state(new_etag, release)` and update `self._etag`, `self._cached_release`.
      10. Return release.
    - Except `asyncio.TimeoutError`: log warning "github_request_timeout", return None.
    - Except `aiohttp.ClientError as e`: log warning "github_client_error", error=str(e), return None.
    - Except (json.JSONDecodeError, KeyError, ValueError) as e: log warning "github_parse_error", return None.
    - Except Exception (catch-all, last resort): log warning "github_unexpected_error", return None. This is the CHECK-06 guarantee.

    Create `tests/test_updater_github_client.py` (~200 LOC). Tests use `pytest-asyncio` (already available — see pyproject.toml dev deps). Use `aioresponses` if available, but fallback to a hand-rolled mock: patch `self._session.get` to return an async context manager.

    Implementation approach for mocking without adding a dep:
    ```python
    class _MockResponse:
        def __init__(self, status, json_data=None, text_data="", headers=None):
            self.status = status
            self._json = json_data
            self._text = text_data
            self.headers = headers or {}
        async def json(self):
            if self._json is None:
                raise json.JSONDecodeError("no json", "", 0)
            return self._json
        async def text(self):
            return self._text
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None

    class _MockSession:
        def __init__(self, response):
            self.response = response
            self.last_headers = None
            self.last_url = None
        def get(self, url, headers=None, timeout=None):
            self.last_headers = headers
            self.last_url = url
            return self.response
    ```

    Test cases (one test function each):
    1. `test_fetch_success_returns_release_info` — mock 200 with sample GitHub JSON, assert ReleaseInfo fields populated, assert state file written atomically.
    2. `test_fetch_sends_required_headers` — assert User-Agent, Accept, X-GitHub-Api-Version present.
    3. `test_fetch_persists_etag_and_sends_if_none_match_on_next_call` — first call gets ETag "W/\"abc123\"", second call should include `If-None-Match: W/\"abc123\"`.
    4. `test_fetch_304_returns_cached_release` — prime state file, mock 304, assert cached release returned.
    5. `test_fetch_304_before_any_cache_returns_none` — mock 304 with no prior cache, assert None.
    6. `test_fetch_403_returns_none_no_raise` — mock 403, assert None, no exception.
    7. `test_fetch_500_returns_none_no_raise` — mock 500, assert None.
    8. `test_fetch_prerelease_returns_none` — mock 200 with `"prerelease": true`, assert None.
    9. `test_fetch_timeout_returns_none_no_raise` — mock session.get to raise asyncio.TimeoutError on __aenter__, assert None.
    10. `test_fetch_client_error_returns_none_no_raise` — raise aiohttp.ClientError, assert None.
    11. `test_fetch_malformed_json_returns_none_no_raise` — mock 200 with `resp.json()` raising, assert None.
    12. `test_state_file_write_failure_does_not_crash_fetch` — pass a state_file path pointing to a non-writable location (e.g. /nonexistent/foo.json) via tmp_path with a read-only parent, mock 200, assert fetch still returns the ReleaseInfo.
    13. `test_state_file_injection_for_tests` — confirm `state_file=tmp_path/"state.json"` is honored.

    Use `tmp_path` fixture from pytest for all state file paths in tests. Real DEFAULT_STATE_FILE is NEVER touched by tests.

    Why the mocked session and not a real network call: unit tests must be hermetic. Plan 44-02 wires this into the webapp and a manual LXC smoke test in Plan 44-03 verifies the real network path.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -m pytest tests/test_updater_github_client.py -x -v</automated>
  </verify>
  <done>
    All 13 tests pass. `GithubReleaseClient` can be imported. All four error paths (timeout, client error, 5xx, 403) return None without raising. Prereleases are filtered. ETag caching round-trip works via tmp_path state file.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: scheduler.py — asyncio UpdateCheckScheduler with defer-on-active-user</name>
  <files>
    src/pv_inverter_proxy/updater/scheduler.py,
    tests/test_updater_scheduler.py
  </files>
  <behavior>
    - UpdateCheckScheduler constructor takes: github_client, on_update_available callback (sync or async, accepts ReleaseInfo|None), has_active_websocket_client callback (sync, returns bool), interval_seconds (default 3600), initial_delay_seconds (default 60)
    - start() creates and returns an asyncio.Task running the loop
    - Loop waits initial_delay_seconds before the first check
    - Each iteration: if has_active_websocket_client() returns True, skips the check and waits interval_seconds again (logs "update_check_deferred_user_active")
    - Each iteration that runs a check: calls github_client.fetch_latest_release(), then calls on_update_available(result), updates internal last_check_at and last_check_failed_at timestamps
    - On success (fetch returned ReleaseInfo or None cleanly): updates last_check_at = time.time(), clears last_check_failed_at
    - On exception during fetch or callback (any non-CancelledError): logs warning, sets last_check_failed_at = time.time(), continues loop (does not re-raise)
    - On CancelledError: re-raises (lets asyncio cancellation propagate cleanly)
    - Scheduler exposes last_check_at and last_check_failed_at as properties for the webapp to surface in UI
    - Task is cancellable: await task after cancel() returns cleanly without propagating CancelledError out
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater/scheduler.py`.

    Module docstring: reference CHECK-02, CHECK-06, CHECK-07, STACK.md section 7.

    Imports:
    ```python
    from __future__ import annotations
    import asyncio
    import inspect
    import time
    from typing import Awaitable, Callable, Optional
    import structlog
    from pv_inverter_proxy.updater.github_client import GithubReleaseClient, ReleaseInfo
    ```

    Constants:
    ```python
    log = structlog.get_logger(component="updater.scheduler")
    DEFAULT_INTERVAL_SECONDS = 3600      # CHECK-02: 1 hour default
    DEFAULT_INITIAL_DELAY_SECONDS = 60   # Avoid hammering GitHub on every restart
    ```

    Type aliases:
    ```python
    OnUpdateCallback = Callable[[Optional[ReleaseInfo]], Awaitable[None] | None]
    IsActiveCallback = Callable[[], bool]
    ```

    `class UpdateCheckScheduler`:
    - `__init__(self, github_client, on_update_available, has_active_websocket_client, interval_seconds=DEFAULT_INTERVAL_SECONDS, initial_delay_seconds=DEFAULT_INITIAL_DELAY_SECONDS)`:
      - Store all args as private attrs.
      - `self._last_check_at: Optional[float] = None`
      - `self._last_check_failed_at: Optional[float] = None`
      - `self._task: Optional[asyncio.Task] = None`
      - `self._stopped = asyncio.Event()`
    - `@property def last_check_at(self) -> Optional[float]: return self._last_check_at`
    - `@property def last_check_failed_at(self) -> Optional[float]: return self._last_check_failed_at`
    - `def start(self) -> asyncio.Task:` — creates `self._task = asyncio.create_task(self._run(), name="update_check_scheduler")`; returns task.
    - `async def stop(self) -> None:` — calls `self._task.cancel()` if running, awaits with `try/except CancelledError`.
    - `async def _run(self) -> None`:
      ```python
      log.info("update_scheduler_starting",
               initial_delay_s=self._initial_delay,
               interval_s=self._interval)
      try:
          await asyncio.sleep(self._initial_delay)
          while True:
              await self._run_one_iteration()
              await asyncio.sleep(self._interval)
      except asyncio.CancelledError:
          log.info("update_scheduler_cancelled")
          raise
      ```
    - `async def _run_one_iteration(self) -> None`:
      ```python
      # CHECK-07: defer when user is actively connected
      try:
          if self._has_active_client():
              log.info("update_check_deferred_user_active")
              return
      except Exception as e:
          log.warning("update_check_active_probe_failed", error=str(e))
          # Fall through and check anyway — probe failure should not block checks

      try:
          release = await self._client.fetch_latest_release()
          # fetch_latest_release returns None on any error — it already logs
          self._last_check_at = time.time()
          self._last_check_failed_at = None if release is not None else self._last_check_failed_at
          # Actually: if fetch returned cleanly (even None), the SCHEDULER succeeded.
          # But if we want CHECK-06 to distinguish "network failed" from "no update",
          # the client must communicate that. For Phase 44 we treat None-with-cached-or-no-update
          # the same as success. If the client's own logging already flagged the failure,
          # that's enough. Rationale: the UI surfaces the scheduler's last_check_failed_at
          # only for scheduler-level failures (exception during callback or probe).
          # Enhancement: if we want finer fault tolerance, change fetch_latest_release to
          # return a tuple (release, failed: bool). For Phase 44 keep the simpler contract.

          await self._invoke_callback(release)
      except asyncio.CancelledError:
          raise
      except Exception as e:
          log.warning("update_check_iteration_failed", error=str(e))
          self._last_check_failed_at = time.time()
      ```
    - `async def _invoke_callback(self, release: Optional[ReleaseInfo]) -> None`:
      ```python
      result = self._on_update(release)
      if inspect.isawaitable(result):
          await result
      ```

    **Important CHECK-06 nuance:** The simple design above sets `last_check_failed_at` only on exceptions bubbling OUT of fetch_latest_release or the callback. Since fetch_latest_release swallows its own errors (per Task 2), network failures show up as `release is None` and are indistinguishable from "no release exists yet." For Phase 44 this is acceptable — the scheduler's job is "did the iteration crash", and CHECK-06 language "Netzwerkfehler ... nur Log-Warnung" is satisfied by github_client's own warning logs plus the scheduler's crash protection.

    **Phase 47 enhancement note (do NOT implement in Phase 44):** a richer contract where fetch returns `FetchResult(release, error)` gives the scheduler visibility into network failures separately from "no release." For Phase 44, keep the simple None-means-unknown contract.

    Create `tests/test_updater_scheduler.py`:

    Test fixtures — use plain class fakes, not mocks:
    ```python
    class FakeClient:
        def __init__(self, results):
            self.results = list(results)  # list of ReleaseInfo | Exception
            self.calls = 0
        async def fetch_latest_release(self):
            self.calls += 1
            r = self.results[min(self.calls - 1, len(self.results) - 1)]
            if isinstance(r, Exception):
                raise r
            return r
    ```

    Tests (use `pytest.mark.asyncio` — auto mode is already on):
    1. `test_start_respects_initial_delay` — create scheduler with initial_delay=0.05, interval=0.05, fetch returns None, wait 0.2s, cancel, assert calls &gt;= 1.
    2. `test_interval_between_checks` — initial_delay=0.0, interval=0.1, fetch returns None, wait 0.35s, cancel, assert 3 &lt;= calls &lt;= 5.
    3. `test_defer_when_user_active` — has_active returning True always, wait 0.2s, cancel, assert client.calls == 0.
    4. `test_defer_then_run_when_user_disconnects` — has_active flips False after 2 calls; assert eventually calls &gt; 0.
    5. `test_exception_in_fetch_sets_failed_at_and_continues` — FakeClient that raises RuntimeError, wait long enough for 2 iterations, assert calls &gt;= 2 and last_check_failed_at is not None.
    6. `test_exception_in_callback_sets_failed_at_and_continues` — fetch returns ReleaseInfo; on_update_available raises; assert calls &gt;= 2 and last_check_failed_at is not None.
    7. `test_cancelled_error_propagates_cleanly` — start scheduler, cancel immediately, await task, assert task.cancelled() or CancelledError caught cleanly.
    8. `test_async_callback_is_awaited` — on_update_available is an `async def` that records its calls, fetch returns release, assert async callback was awaited.
    9. `test_sync_callback_is_called` — on_update_available is a plain `def` that records calls, assert it's called.
    10. `test_successful_check_updates_last_check_at` — fetch returns release, wait one iteration, assert scheduler.last_check_at is not None and close to time.time().
    11. `test_active_probe_exception_does_not_crash` — has_active_websocket_client raises RuntimeError; scheduler should log and fall through to check anyway; assert calls &gt;= 1 and scheduler still running.

    All tests must finish in &lt; 2 seconds total. Use small initial_delay and interval (0.0 - 0.1s). Always cancel the task and await in a try/except CancelledError to clean up.

    Provide a helper:
    ```python
    async def _run_scheduler_for(scheduler: UpdateCheckScheduler, duration_s: float) -> None:
        task = scheduler.start()
        try:
            await asyncio.sleep(duration_s)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    ```

    Why this design: using real asyncio.sleep with small durations keeps the test realistic without needing freezegun/time mocking. The fake client pattern avoids pytest-mock and keeps tests readable. Timing-based assertions use loose bounds (&gt;= 1, 3..5 range) to avoid flake.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -m pytest tests/test_updater_scheduler.py -x -v</automated>
  </verify>
  <done>
    All 11 tests pass within 2s. `UpdateCheckScheduler` can be imported. Exceptions in fetch or callback set `last_check_failed_at` but do not crash the loop. `has_active_websocket_client` returning True defers the check. Cancellation is clean. Async and sync callbacks both work.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| pv-proxy process ↔ GitHub API (public internet) | Untrusted remote: response body is parsed by the scheduler and displayed in UI |
| Scheduler ↔ filesystem (/etc/pv-inverter-proxy/update-state.json) | Local write; same uid as existing state.json — no new boundary |
| Version parser input ↔ caller | String input from GitHub API response or user config; must not panic on malformed input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-44-01 | S (Spoofing) | GithubReleaseClient | accept | TLS to api.github.com provides authenticity. No GPG in Phase 44 (SEC-05 is Phase 45). Compromise of GitHub account would install a bad tag, but Phase 44 is READ-ONLY — it shows a badge. Actual install requires Phase 45 trust-root check (SHA reachability from origin/main). |
| T-44-02 | T (Tampering) | GithubReleaseClient response parsing | mitigate | Use `.get()` with defaults on all fields. Wrap parsing in try/except (json.JSONDecodeError, KeyError, ValueError) → return None. Release `body` is rendered later in Phase 46 with HTML-escape; Phase 44 never interpolates body into HTML. |
| T-44-03 | R (Repudiation) | Scheduler actions | accept | structlog writes JSON lines to journal (SyslogIdentifier=pv-inverter-proxy). Full audit trail exists via `journalctl`. No additional action needed. |
| T-44-04 | I (Information Disclosure) | ETag cache file | accept | File contains only public GitHub release metadata — no secrets. Mode 0644 matches existing state.json pattern. |
| T-44-05 | D (Denial of Service) | GitHub API rate limit (60 req/h unauthenticated) | mitigate | 1 hour interval + ETag caching (304 still costs 1 req but tiny). Initial delay 60s after restart prevents restart-loop DoS against GitHub. Manual check (Phase 47) will be rate-limited at UI layer. |
| T-44-06 | D (DoS) | Malicious regex / version string (ReDoS) | mitigate | `_VERSION_RE` is anchored and has no nested quantifiers. Bounded linear time. Tested with Version.parse("") and extremely long strings. |
| T-44-07 | D (DoS) | GitHub unreachable crashes scheduler loop | mitigate | CHECK-06: github_client catches all aiohttp / asyncio / json exceptions and returns None. Scheduler wraps callback invocation in try/except so exceptions in on_update_available also do not crash the loop. |
| T-44-08 | E (Elevation) | Updater backend is READ-ONLY | accept | No file writes outside update-state.json (mode 0644). No subprocess calls except `git rev-parse --short HEAD` which is a read. No systemctl. Phase 45 introduces the privileged boundary. |
| T-44-09 | T (Tampering) | subprocess arg injection in get_commit_hash | mitigate | Explicit argv list (not shell=True). install_dir is a Path from module constants, not user input. |
</threat_model>

<validation_strategy>
## Nyquist Validation — Requirements → Tests

| Requirement | Validation Type | Test Location | What It Proves |
|-------------|----------------|---------------|----------------|
| CHECK-02 (scheduler as asyncio task, 1h default) | Unit + manual | test_updater_scheduler.py::test_interval_between_checks; manual LXC verify in Plan 44-03 | Loop runs at configured interval; default is DEFAULT_INTERVAL_SECONDS = 3600 |
| CHECK-03 (User-Agent, Accept, X-GitHub-Api-Version, 10s timeout, ETag cache) | Unit | test_updater_github_client.py::test_fetch_sends_required_headers, test_fetch_persists_etag_and_sends_if_none_match_on_next_call | Headers present; ETag round-trip works |
| CHECK-06 (fault tolerance: network/5xx/403 no crash, UI surfaces last_check_failed_at) | Unit | test_updater_github_client.py::test_fetch_{403,500,timeout,client_error,malformed_json}_returns_none_no_raise; test_updater_scheduler.py::test_exception_in_{fetch,callback}_sets_failed_at_and_continues | All error paths return None cleanly; scheduler last_check_failed_at field is set on exception |
| CHECK-07 (defer when WS client active) | Unit | test_updater_scheduler.py::test_defer_when_user_active, test_defer_then_run_when_user_disconnects, test_active_probe_exception_does_not_crash | Scheduler honors has_active_websocket_client callback; probe failure doesn't crash |

Per-task Nyquist: every &lt;verify&gt; block has an automated pytest invocation. No manual steps in Plan 44-01 — this is a pure backend plan with full unit coverage.
</validation_strategy>

<rollback_plan>
This plan is purely additive — new files under `src/pv_inverter_proxy/updater/` and `tests/`. Nothing existing is modified. To roll back: `git rm -r src/pv_inverter_proxy/updater tests/test_updater_*.py`. No systemd, no config, no runtime wiring. The running service is unaffected until Plan 44-02 integrates the scheduler into __main__.py.
</rollback_plan>

<verification>
- `python -m pytest tests/test_updater_version.py tests/test_updater_github_client.py tests/test_updater_scheduler.py -x -v` passes all tests
- `python -m pytest tests/ -x` (full suite) still passes — we have not touched existing modules
- `python -c "from pv_inverter_proxy.updater.version import Version; from pv_inverter_proxy.updater.github_client import GithubReleaseClient, ReleaseInfo; from pv_inverter_proxy.updater.scheduler import UpdateCheckScheduler; print('ok')"` prints `ok`
- No new runtime dependencies added (`grep -E "^(dependencies|install_requires)" pyproject.toml` unchanged)
- `ruff check src/pv_inverter_proxy/updater/` passes if ruff is configured (optional)
</verification>

<success_criteria>
Plan 44-01 is complete when:
- Three new modules exist under `src/pv_inverter_proxy/updater/` with the behaviors specified
- Three new test files pass with &gt;= 30 total test cases
- Full test suite still passes (no regressions)
- CHECK-02, CHECK-03, CHECK-06, CHECK-07 have unit-level coverage
- Zero new runtime dependencies introduced
- No existing production files have been modified
- Plan 44-02 can consume `GithubReleaseClient`, `UpdateCheckScheduler`, `get_current_version`, `get_commit_hash` by import
</success_criteria>

<output>
After completion, create `.planning/phases/44-passive-version-badge/44-01-SUMMARY.md` following the summary template, including:
- Frontmatter with `provides:` listing the four importable symbols
- `tech-stack.added: []` (zero new deps — reaffirm research decision)
- `key-decisions:` including "fetch_latest_release returns None on all error paths (no distinction between failure and no-release in Phase 44 — richer contract deferred to Phase 47)" and "scheduler's has_active_websocket_client callback probe failure does NOT block checks, only defers when True"
- `affects:` list Plan 44-02 ("wires scheduler into __main__.py startup") and Plan 44-03 ("reads last_check_failed_at for UI footer")
- Test count and pattern established for Plan 45+ updater modules
</output>