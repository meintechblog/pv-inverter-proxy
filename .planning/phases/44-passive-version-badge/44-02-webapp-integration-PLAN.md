---
phase: 44-passive-version-badge
plan: 02
type: execute
wave: 2
depends_on:
  - 44-01
files_modified:
  - pyproject.toml
  - src/pv_inverter_proxy/context.py
  - src/pv_inverter_proxy/__main__.py
  - src/pv_inverter_proxy/webapp.py
  - tests/test_updater_webapp_routes.py
  - tests/test_updater_wiring.py
autonomous: true
requirements:
  - CHECK-01
  - CHECK-02
  - CHECK-05
  - CHECK-06
  - CHECK-07
must_haves:
  truths:
    - "pyproject.toml [project].version is 8.0.0 so importlib.metadata.version('pv-inverter-master') returns 8.0.0 after reinstall"
    - "AppContext has available_update, current_version, current_commit, update_last_check_at, update_last_check_failed_at fields (all default None)"
    - "__main__.py creates a single shared aiohttp.ClientSession and passes it to the GithubReleaseClient"
    - "__main__.py resolves current_version and current_commit ONCE at startup (cached on AppContext)"
    - "__main__.py starts UpdateCheckScheduler as asyncio task alongside heartbeat, device_list_refresh, healthy_flag"
    - "__main__.py cancels the scheduler task in the graceful_shutdown section alongside other periodic tasks"
    - "webapp.py registers GET /api/update/available route"
    - "GET /api/update/available returns {current_version, current_commit, latest_version, release_notes, published_at, tag_name, html_url, last_check_at, last_check_failed_at} when AppContext.available_update is set"
    - "GET /api/update/available returns {current_version, current_commit, available_update: null, last_check_at, last_check_failed_at} when no update is available"
    - "webapp ws_handler sends available_update snapshot on client connect"
    - "broadcast_available_update(app) is called by the scheduler callback whenever available_update changes"
    - "has_active_websocket_client helper reads len(app['ws_clients']) > 0"
    - "Scheduler callback compares Version(current) < Version(latest); sets available_update only when latest > current"
  artifacts:
    - path: "pyproject.toml"
      provides: "Version bump 6.0.0 → 8.0.0"
      contains: 'version = "8.0.0"'
    - path: "src/pv_inverter_proxy/context.py"
      provides: "AppContext update fields"
      contains: "available_update"
    - path: "src/pv_inverter_proxy/__main__.py"
      provides: "Scheduler wiring in run_with_shutdown()"
      contains: "UpdateCheckScheduler"
    - path: "src/pv_inverter_proxy/webapp.py"
      provides: "GET /api/update/available route + WS snapshot extension + broadcast helper"
      contains: "/api/update/available"
    - path: "tests/test_updater_webapp_routes.py"
      provides: "Route response shape tests"
      min_lines: 80
    - path: "tests/test_updater_wiring.py"
      provides: "Scheduler callback integration test"
      min_lines: 60
  key_links:
    - from: "src/pv_inverter_proxy/__main__.py"
      to: "src/pv_inverter_proxy/updater/scheduler.py"
      via: "UpdateCheckScheduler instantiated with http_session, on_update_available callback, has_active_websocket_client callback"
      pattern: "UpdateCheckScheduler"
    - from: "src/pv_inverter_proxy/webapp.py"
      to: "src/pv_inverter_proxy/context.py AppContext.available_update"
      via: "update_available_handler reads app_ctx.available_update"
      pattern: "app_ctx\\.available_update"
    - from: "scheduler on_update_available callback"
      to: "broadcast_available_update in webapp.py"
      via: "callback pushes update info into AppContext and broadcasts via ws_clients"
      pattern: "broadcast_available_update"
---

<objective>
Wire the backend modules from Plan 44-01 into the running service: bump the version, extend AppContext, start the scheduler in __main__.py, add the /api/update/available route, extend the WebSocket snapshot, and build the scheduler-to-webapp callback that publishes `available_update` updates to connected clients.

Purpose: Deliver CHECK-01 (version in footer — requires real 8.0.0 in pyproject), CHECK-05 (REST endpoint), and complete the CHECK-02/06/07 wiring started in 44-01. Prepare the integration point Plan 44-03 will consume from the frontend.

Output: Running service exposes the version + any available update at `GET /api/update/available`, the scheduler fires hourly, and the WebSocket snapshot broadcasts update events. No frontend changes yet (Plan 44-03).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/research/STACK.md
@.planning/research/ARCHITECTURE.md
@.planning/phases/44-passive-version-badge/44-01-updater-backend-PLAN.md
@CLAUDE.md

@pyproject.toml
@src/pv_inverter_proxy/context.py
@src/pv_inverter_proxy/__main__.py
@src/pv_inverter_proxy/webapp.py

<interfaces>
<!-- Key integration anchors the executor MUST use verbatim -->

**Imports available from Plan 44-01 (MUST use, do not re-implement):**
```python
from pv_inverter_proxy.updater.version import Version, get_current_version, get_commit_hash
from pv_inverter_proxy.updater.github_client import GithubReleaseClient, ReleaseInfo
from pv_inverter_proxy.updater.scheduler import UpdateCheckScheduler
```

**pyproject.toml current state:**
```toml
[project]
name = "pv-inverter-master"
version = "6.0.0"   # ← BUMP TO "8.0.0"
```
After change, run `pip install -e .` on the LXC during deploy for importlib.metadata to pick it up.

**context.py existing AppContext (excerpt):**
```python
@dataclass
class AppContext:
    ...
    webapp: object = None          # aiohttp web.Application
    polling_paused: bool = False
    healthy_flag_written: bool = False
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    ...
```
Add NEW fields (all defaulting to None) WITHOUT touching existing ones.

**__main__.py existing task creation pattern (line ~289-315):**
```python
device_list_task = asyncio.create_task(_device_list_refresh(app_ctx))
...
healthy_flag_task = asyncio.create_task(_healthy_flag_watcher(app_ctx))
heartbeat_task = asyncio.create_task(_health_heartbeat(app_ctx))
```

**__main__.py existing shutdown pattern (line ~322-328):**
```python
# Cancel periodic tasks
for task in (heartbeat_task, device_list_task, healthy_flag_task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

**webapp.py route registration (line ~2009-2048):**
```python
app.router.add_get("/api/status", status_handler)
app.router.add_get("/api/health", health_handler)
...
# ← Add app.router.add_get("/api/update/available", update_available_handler) here
```

**webapp.py WS client set (line 2007):**
```python
app["ws_clients"] = weakref.WeakSet()
```
Read via `len(app.get("ws_clients") or ())` for CHECK-07 has_active check.

**webapp.py existing broadcast pattern (line 959 broadcast_device_list):**
```python
async def broadcast_device_list(app: web.Application) -> None:
    clients = app.get("ws_clients")
    if not clients:
        return
    ...
    payload = json.dumps({"type": "device_list", "data": {...}})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)
```
Mirror this for `broadcast_available_update`.

**webapp.py ws_handler initial push (line ~600-670):**
The handler sends `device_snapshot`, `snapshot`, `virtual_snapshot`, `device_list` on connect. Add ONE more send for `available_update` after `device_list`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Bump pyproject version and extend AppContext with update fields</name>
  <files>
    pyproject.toml,
    src/pv_inverter_proxy/context.py
  </files>
  <action>
    **Step 1 — pyproject.toml:**
    Change `version = "6.0.0"` to `version = "8.0.0"` on line 3. Nothing else changes. The milestone goal is v8.0 and CHECK-01 requires `importlib.metadata.version("pv-inverter-master")` to return the real version; 6.0.0 would be user-visibly wrong and would fail the ship test.

    **Step 2 — context.py:**
    Add five new fields to the AppContext dataclass, all with default None, placed AFTER the existing MQTT Publisher stats block (around line 69) and BEFORE any closing brace. Preserve existing formatting and comments.

    ```python
    # Phase 44: Passive Version Badge (CHECK-01, CHECK-05, CHECK-06)
    current_version: str | None = None         # From importlib.metadata at startup
    current_commit: str | None = None          # From git rev-parse --short HEAD at startup
    available_update: dict | None = None       # Parsed GitHub release info when latest > current
    update_last_check_at: float | None = None  # UNIX timestamp of last successful scheduler iteration
    update_last_check_failed_at: float | None = None  # UNIX timestamp of last failed iteration
    ```

    Do NOT import anything new in context.py — the fields are primitive types.

    Why: AppContext is the single shared mutable state bag. The scheduler callback and the webapp handlers must read/write the same fields; storing them here (instead of a new UpdateState class) matches the existing convention used for mqtt_pub_*, venus_*, etc.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -c "from pv_inverter_proxy.context import AppContext; ctx = AppContext(); assert hasattr(ctx, 'current_version'); assert hasattr(ctx, 'current_commit'); assert hasattr(ctx, 'available_update'); assert hasattr(ctx, 'update_last_check_at'); assert hasattr(ctx, 'update_last_check_failed_at'); assert ctx.current_version is None; print('ok')" &amp;&amp; grep -q 'version = "8.0.0"' pyproject.toml &amp;&amp; echo "pyproject ok"</automated>
  </verify>
  <done>
    pyproject.toml line 3 reads `version = "8.0.0"`. AppContext has five new fields all defaulting to None. Existing tests still pass: `python -m pytest tests/test_context.py -x`.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add REST endpoint + WS snapshot extension + broadcast helper to webapp.py</name>
  <files>
    src/pv_inverter_proxy/webapp.py,
    tests/test_updater_webapp_routes.py
  </files>
  <action>
    Modify `src/pv_inverter_proxy/webapp.py` with four additive changes. Do NOT touch any other code paths.

    **Change 1 — Add module-level imports at the top alongside existing updater-adjacent imports (after `from pv_inverter_proxy.venus_reader import venus_mqtt_loop` or similar; if no such line, add after the Config import):**

    ```python
    # Phase 44: Passive Version Badge
    from pv_inverter_proxy.updater.version import Version
    ```

    (GithubReleaseClient and UpdateCheckScheduler are NOT imported here — they live in __main__.py. webapp.py only needs the Version parser for the scheduler callback helper and the route handler.)

    **Change 2 — Add `update_available_handler` function. Place it in the route-handler section, near `health_handler` (around line 236). Exact location: immediately after `health_handler` and before `config_get_handler`.**

    ```python
    async def update_available_handler(request: web.Request) -> web.Response:
        """GET /api/update/available — CHECK-05.

        Returns the current version, commit, and (if available) the latest GitHub
        release info. CHECK-06: also surfaces last_check_at and last_check_failed_at
        so the UI can show a stale/failed indicator.

        Response shape:
            {
              "current_version": "8.0.0",
              "current_commit": "abc123d",
              "available_update": {
                 "latest_version": "v8.1.0",
                 "tag_name": "v8.1.0",
                 "release_notes": "...",
                 "published_at": "2026-04-10T...",
                 "html_url": "https://github.com/..."
              } | null,
              "last_check_at": 1712755200.0 | null,
              "last_check_failed_at": null | 1712755200.0
            }
        """
        app_ctx = request.app["app_ctx"]
        return web.json_response({
            "current_version": app_ctx.current_version,
            "current_commit": app_ctx.current_commit,
            "available_update": app_ctx.available_update,
            "last_check_at": app_ctx.update_last_check_at,
            "last_check_failed_at": app_ctx.update_last_check_failed_at,
        })
    ```

    **Change 3 — Register the route in `create_webapp()`. Add after `app.router.add_get("/api/health", health_handler)` (around line 2012):**

    ```python
    app.router.add_get("/api/update/available", update_available_handler)
    ```

    **Change 4 — Add `broadcast_available_update` helper. Place it near `broadcast_device_list` (around line 959), mirroring its pattern exactly.**

    ```python
    async def broadcast_available_update(app: web.Application) -> None:
        """Push updated available_update + version info to all WS clients.

        Called by the scheduler callback whenever AppContext.available_update or
        the last_check_{at,failed_at} fields change. Mirrors broadcast_device_list
        to reuse its pruning pattern for dead clients.
        """
        clients = app.get("ws_clients")
        if not clients:
            return
        app_ctx = app.get("app_ctx")
        if app_ctx is None:
            return
        payload = json.dumps({
            "type": "available_update",
            "data": {
                "current_version": app_ctx.current_version,
                "current_commit": app_ctx.current_commit,
                "available_update": app_ctx.available_update,
                "last_check_at": app_ctx.update_last_check_at,
                "last_check_failed_at": app_ctx.update_last_check_failed_at,
            },
        })
        for ws in set(clients):
            try:
                await ws.send_str(payload)
            except (ConnectionError, RuntimeError, ConnectionResetError):
                clients.discard(ws)
    ```

    **Change 5 — Extend `ws_handler` initial push. In the block where it sends `device_list` (around line 667-668), add one more send after:**

    ```python
    # Send initial device list so client knows connection states (MQTT etc.)
    devices = _build_device_list(ws_app_ctx, config)
    await ws.send_json({"type": "device_list", "data": {"devices": devices}})

    # Phase 44: send initial available_update state so fresh clients know the current version
    await ws.send_json({
        "type": "available_update",
        "data": {
            "current_version": ws_app_ctx.current_version,
            "current_commit": ws_app_ctx.current_commit,
            "available_update": ws_app_ctx.available_update,
            "last_check_at": ws_app_ctx.update_last_check_at,
            "last_check_failed_at": ws_app_ctx.update_last_check_failed_at,
        },
    })
    ```

    **Create `tests/test_updater_webapp_routes.py`:**

    ```python
    """Tests for GET /api/update/available route."""
    import pytest
    from aiohttp import web
    from pv_inverter_proxy.context import AppContext
    from pv_inverter_proxy.webapp import update_available_handler, broadcast_available_update


    def _make_request(app_ctx: AppContext) -> web.Request:
        app = web.Application()
        app["app_ctx"] = app_ctx
        return _make_request_for(app)


    def _make_request_for(app):
        return web.Request(
            message=...,  # use aiohttp test utilities instead
            payload=...,
        )
    ```

    **Actually** — because constructing aiohttp Request objects by hand is awkward, use `aiohttp.test_utils.make_mocked_request`:

    ```python
    import json
    import pytest
    from aiohttp.test_utils import make_mocked_request
    from aiohttp import web
    from pv_inverter_proxy.context import AppContext
    from pv_inverter_proxy.webapp import update_available_handler


    @pytest.fixture
    def app_with_ctx():
        ctx = AppContext()
        ctx.current_version = "8.0.0"
        ctx.current_commit = "abc123d"
        ctx.available_update = None
        ctx.update_last_check_at = 1712755200.0
        ctx.update_last_check_failed_at = None
        app = web.Application()
        app["app_ctx"] = ctx
        return app, ctx


    async def test_update_available_no_update(app_with_ctx):
        app, ctx = app_with_ctx
        req = make_mocked_request("GET", "/api/update/available", app=app)
        resp = await update_available_handler(req)
        data = json.loads(resp.body.decode())
        assert data["current_version"] == "8.0.0"
        assert data["current_commit"] == "abc123d"
        assert data["available_update"] is None
        assert data["last_check_at"] == 1712755200.0
        assert data["last_check_failed_at"] is None


    async def test_update_available_with_update(app_with_ctx):
        app, ctx = app_with_ctx
        ctx.available_update = {
            "latest_version": "v8.1.0",
            "tag_name": "v8.1.0",
            "release_notes": "## Added\n- feature",
            "published_at": "2026-05-01T00:00:00Z",
            "html_url": "https://github.com/meintechblog/pv-inverter-master/releases/tag/v8.1.0",
        }
        req = make_mocked_request("GET", "/api/update/available", app=app)
        resp = await update_available_handler(req)
        data = json.loads(resp.body.decode())
        assert data["available_update"]["latest_version"] == "v8.1.0"
        assert data["available_update"]["tag_name"] == "v8.1.0"
        assert "feature" in data["available_update"]["release_notes"]


    async def test_update_available_unknown_version(app_with_ctx):
        app, ctx = app_with_ctx
        ctx.current_version = "unknown"
        ctx.current_commit = None
        req = make_mocked_request("GET", "/api/update/available", app=app)
        resp = await update_available_handler(req)
        data = json.loads(resp.body.decode())
        assert data["current_version"] == "unknown"
        assert data["current_commit"] is None


    async def test_update_available_failed_check(app_with_ctx):
        app, ctx = app_with_ctx
        ctx.update_last_check_failed_at = 1712755500.0
        req = make_mocked_request("GET", "/api/update/available", app=app)
        resp = await update_available_handler(req)
        data = json.loads(resp.body.decode())
        assert data["last_check_failed_at"] == 1712755500.0
    ```

    Four tests, all use `aiohttp.test_utils.make_mocked_request` which is officially supported and works without spinning up a TCP server.

    Why this split: the broadcast helper is integration-tested in Task 4 via an end-to-end scheduler callback test in test_updater_wiring.py — no need to double-test at the broadcast layer here.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -m pytest tests/test_updater_webapp_routes.py -x -v &amp;&amp; python -c "from pv_inverter_proxy.webapp import update_available_handler, broadcast_available_update; print('ok')"</automated>
  </verify>
  <done>
    4 tests pass. `update_available_handler` and `broadcast_available_update` are importable from webapp. ws_handler sends `available_update` on connect. Full test suite still passes (no existing tests broken).
  </done>
</task>

<task type="auto">
  <name>Task 3: Wire UpdateCheckScheduler into __main__.py run_with_shutdown() with shared aiohttp session</name>
  <files>
    src/pv_inverter_proxy/__main__.py,
    tests/test_updater_wiring.py
  </files>
  <action>
    Modify `src/pv_inverter_proxy/__main__.py` with additive changes. Do NOT touch existing task lifecycle, just add alongside.

    **Step 1 — imports.** Add after existing `from pv_inverter_proxy.webapp import create_webapp` (around line 28):

    ```python
    # Phase 44: Passive Version Badge
    from pv_inverter_proxy.updater.version import get_current_version, get_commit_hash
    from pv_inverter_proxy.updater.github_client import GithubReleaseClient, ReleaseInfo
    from pv_inverter_proxy.updater.scheduler import UpdateCheckScheduler
    from pv_inverter_proxy.releases import INSTALL_ROOT
    import aiohttp
    ```

    **Step 2 — resolve current version and commit ONCE early in `run_with_shutdown` before any long-running task starts. Add immediately after `for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, handle_signal, sig)` (around line 199):**

    ```python
    # Phase 44 CHECK-01: Resolve current version + commit once at startup and
    # cache on AppContext. subprocess is run once here to avoid repeated forks.
    try:
        app_ctx.current_version = get_current_version()
        app_ctx.current_commit = get_commit_hash(INSTALL_ROOT)
        log.info(
            "version_resolved",
            version=app_ctx.current_version,
            commit=app_ctx.current_commit or "unknown",
        )
    except Exception as e:
        log.warning("version_resolution_failed", error=str(e))
        app_ctx.current_version = "unknown"
        app_ctx.current_commit = None
    ```

    **Step 3 — after webapp startup but before MQTT publisher startup (around line 237, immediately after `log.info("webapp_started", port=config.webapp.port)`), create the shared aiohttp.ClientSession and scheduler. Place it after webapp creation so the `app_ctx.webapp` reference is available for the callback.**

    ```python
    # Phase 44 CHECK-02/03/07: Start GitHub update check scheduler
    # Single shared aiohttp.ClientSession — do not create one per request.
    update_http_session = aiohttp.ClientSession(
        headers={"User-Agent": "pv-inverter-proxy/8.0 (github.com/meintechblog/pv-inverter-master)"}
    )
    update_github_client = GithubReleaseClient(session=update_http_session)

    async def _on_update_available(release: "ReleaseInfo | None") -> None:
        """Scheduler callback: compare versions and update AppContext + broadcast.

        CHECK-06: any exception here is caught by the scheduler (see Plan 44-01).
        The scheduler also updates last_check_at / last_check_failed_at.
        """
        from pv_inverter_proxy.updater.version import Version
        from pv_inverter_proxy.webapp import broadcast_available_update

        import time as _time
        app_ctx.update_last_check_at = _time.time()

        previous = app_ctx.available_update

        if release is None:
            # Either no release yet, network error (already logged by client),
            # or prerelease filtered out. Clear any stale "available" marker
            # ONLY on the successful-but-empty path by checking last_check_failed_at;
            # if the scheduler sets failed_at on its next iteration we'll know.
            # For simplicity: leave existing available_update in place; it will
            # refresh on the next successful fetch.
            pass
        else:
            try:
                latest = Version.parse(release.tag_name)
                current_str = app_ctx.current_version or "unknown"
                if current_str == "unknown":
                    # Cannot compare; show as available defensively
                    is_newer = True
                else:
                    current = Version.parse(current_str)
                    is_newer = latest > current
            except ValueError as e:
                log.warning(
                    "update_version_parse_failed",
                    current=app_ctx.current_version,
                    latest=release.tag_name,
                    error=str(e),
                )
                is_newer = False

            if is_newer:
                app_ctx.available_update = {
                    "latest_version": release.tag_name,
                    "tag_name": release.tag_name,
                    "release_notes": release.body,
                    "published_at": release.published_at,
                    "html_url": release.html_url,
                }
                log.info(
                    "update_available",
                    current=app_ctx.current_version,
                    latest=release.tag_name,
                )
            else:
                app_ctx.available_update = None

        # Broadcast only if anything changed (coarse-grained)
        if app_ctx.available_update != previous and app_ctx.webapp is not None:
            await broadcast_available_update(app_ctx.webapp)

    def _has_active_ws_client() -> bool:
        """CHECK-07: return True iff at least one WebSocket client is connected."""
        app = app_ctx.webapp
        if app is None:
            return False
        clients = app.get("ws_clients")
        return bool(clients) and len(clients) > 0

    update_scheduler = UpdateCheckScheduler(
        github_client=update_github_client,
        on_update_available=_on_update_available,
        has_active_websocket_client=_has_active_ws_client,
    )
    update_scheduler_task = update_scheduler.start()
    log.info("update_scheduler_started")
    ```

    **Step 4 — extend the graceful shutdown. Modify the cancel loop (around line 323):**

    Before:
    ```python
    # Cancel periodic tasks
    for task in (heartbeat_task, device_list_task, healthy_flag_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    ```

    After:
    ```python
    # Cancel periodic tasks
    for task in (heartbeat_task, device_list_task, healthy_flag_task, update_scheduler_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Close shared HTTP session used by update scheduler
    try:
        await update_http_session.close()
    except Exception as e:
        log.warning("update_http_session_close_failed", error=str(e))
    ```

    **Step 5 — Create `tests/test_updater_wiring.py`:**

    ```python
    """Integration tests for the scheduler callback: version comparison + AppContext mutation.

    These tests exercise the _on_update_available callback logic without booting
    the full service. The callback is defined inside run_with_shutdown() so we
    build an equivalent standalone for testing the version comparison + mutation
    rules. If the callback is refactored into a module-level function in the
    future, replace this test with direct imports.
    """
    import pytest
    from unittest.mock import AsyncMock, MagicMock
    from pv_inverter_proxy.context import AppContext
    from pv_inverter_proxy.updater.github_client import ReleaseInfo
    from pv_inverter_proxy.updater.version import Version


    def _make_release(tag="v8.1.0", body="notes", prerelease=False):
        return ReleaseInfo(
            tag_name=tag,
            published_at="2026-05-01T00:00:00Z",
            body=body,
            html_url=f"https://github.com/meintechblog/pv-inverter-master/releases/tag/{tag}",
            prerelease=prerelease,
        )


    async def _on_update_available_pure(app_ctx: AppContext, release):
        """Pure version of the callback suitable for testing.

        Must stay byte-identical to the logic inside __main__._on_update_available
        (minus the structlog + broadcast wiring). If __main__ logic changes, this
        helper MUST change too — kept as a guard so drift is caught by the tests.
        """
        import time as _time
        app_ctx.update_last_check_at = _time.time()
        if release is None:
            return
        try:
            latest = Version.parse(release.tag_name)
            current_str = app_ctx.current_version or "unknown"
            if current_str == "unknown":
                is_newer = True
            else:
                current = Version.parse(current_str)
                is_newer = latest > current
        except ValueError:
            is_newer = False
        if is_newer:
            app_ctx.available_update = {
                "latest_version": release.tag_name,
                "tag_name": release.tag_name,
                "release_notes": release.body,
                "published_at": release.published_at,
                "html_url": release.html_url,
            }
        else:
            app_ctx.available_update = None


    async def test_newer_release_sets_available_update():
        ctx = AppContext()
        ctx.current_version = "8.0.0"
        await _on_update_available_pure(ctx, _make_release("v8.1.0"))
        assert ctx.available_update is not None
        assert ctx.available_update["latest_version"] == "v8.1.0"
        assert ctx.update_last_check_at is not None


    async def test_same_version_clears_available_update():
        ctx = AppContext()
        ctx.current_version = "8.0.0"
        ctx.available_update = {"latest_version": "v8.0.0"}  # stale
        await _on_update_available_pure(ctx, _make_release("v8.0.0"))
        assert ctx.available_update is None


    async def test_older_release_clears_available_update():
        ctx = AppContext()
        ctx.current_version = "8.1.0"
        await _on_update_available_pure(ctx, _make_release("v8.0.0"))
        assert ctx.available_update is None


    async def test_none_release_leaves_state_unchanged():
        ctx = AppContext()
        ctx.current_version = "8.0.0"
        ctx.available_update = {"latest_version": "v8.1.0"}
        await _on_update_available_pure(ctx, None)
        assert ctx.available_update is not None  # unchanged
        assert ctx.update_last_check_at is not None


    async def test_unknown_current_version_shows_release_as_available():
        ctx = AppContext()
        ctx.current_version = "unknown"
        await _on_update_available_pure(ctx, _make_release("v8.1.0"))
        assert ctx.available_update is not None
        assert ctx.available_update["latest_version"] == "v8.1.0"


    async def test_malformed_tag_does_not_crash():
        ctx = AppContext()
        ctx.current_version = "8.0.0"
        await _on_update_available_pure(ctx, _make_release("not-a-version"))
        assert ctx.available_update is None
    ```

    Why a "pure" helper instead of importing from __main__: __main__.py defines the callback inside `run_with_shutdown` as a closure (using `app_ctx` from the enclosing scope), which is not directly importable without refactoring. The tests validate the LOGIC; if __main__'s closure diverges, these tests fail by staleness and a comment in the test file flags the drift risk. The alternative (refactoring the callback to a module-level function taking `app_ctx` + `release`) is cleaner — **do that refactor** if time permits: move `_on_update_available` and `_has_active_ws_client` out of `run_with_shutdown` into module-level functions that take `app_ctx` as a parameter. Then the test can import `_on_update_available` directly.

    **Recommended refactor (cleaner):** Move `_on_update_available` to module-level:

    ```python
    # At module level in __main__.py, below main() definition
    async def _on_update_available(app_ctx, release):
        """Scheduler callback: version-compare and update AppContext."""
        import time as _time
        from pv_inverter_proxy.updater.version import Version
        from pv_inverter_proxy.webapp import broadcast_available_update

        app_ctx.update_last_check_at = _time.time()
        previous = app_ctx.available_update

        if release is None:
            return

        try:
            latest = Version.parse(release.tag_name)
            current_str = app_ctx.current_version or "unknown"
            if current_str == "unknown":
                is_newer = True
            else:
                current = Version.parse(current_str)
                is_newer = latest > current
        except ValueError:
            is_newer = False

        if is_newer:
            app_ctx.available_update = {
                "latest_version": release.tag_name,
                "tag_name": release.tag_name,
                "release_notes": release.body,
                "published_at": release.published_at,
                "html_url": release.html_url,
            }
        else:
            app_ctx.available_update = None

        if app_ctx.available_update != previous and app_ctx.webapp is not None:
            await broadcast_available_update(app_ctx.webapp)
    ```

    Then inside `run_with_shutdown`, wrap the callback to bind app_ctx:

    ```python
    async def _callback(release):
        await _on_update_available(app_ctx, release)

    update_scheduler = UpdateCheckScheduler(
        github_client=update_github_client,
        on_update_available=_callback,
        has_active_websocket_client=_has_active_ws_client,
    )
    ```

    And update `tests/test_updater_wiring.py` to directly import:
    ```python
    from pv_inverter_proxy.__main__ import _on_update_available
    ```
    (remove the _on_update_available_pure helper).

    Use the refactored layout. It's cleaner and makes tests direct.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -m pytest tests/test_updater_wiring.py -x -v &amp;&amp; python -c "from pv_inverter_proxy.__main__ import _on_update_available; print('callback importable')" &amp;&amp; python -m pytest tests/ -x --ignore=tests/test_updater_wiring.py --ignore=tests/test_updater_version.py --ignore=tests/test_updater_github_client.py --ignore=tests/test_updater_scheduler.py --ignore=tests/test_updater_webapp_routes.py -q 2>&amp;1 | tail -20</automated>
  </verify>
  <done>
    6 new tests pass in test_updater_wiring.py. `_on_update_available` is importable from `pv_inverter_proxy.__main__`. Full existing test suite still passes (no regressions). Service starts successfully on LXC (verified via Plan 44-03 deploy).
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| pv-proxy process ↔ GitHub API | Already covered in Plan 44-01 threat model; this plan adds no new boundary |
| HTTP client ↔ webapp clients | Existing — same trust level as all /api/* routes; no auth today, LAN-only per PROJECT.md |
| Scheduler callback ↔ AppContext mutation | Single-writer: only the scheduler task mutates update_* fields; webapp handlers only READ |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-44-10 | T (Tampering) | Race between scheduler write and WS broadcast read | accept | Python asyncio single-threaded event loop — no cross-thread mutation possible. Callback awaits broadcast before returning, so readers during the broadcast window see consistent state. |
| T-44-11 | I (Information Disclosure) | /api/update/available returns version + commit + notes | accept | All data is already public (GitHub release API is public, version is in pyproject on the repo). No secrets exposed. |
| T-44-12 | D (DoS) | Unbounded available_update dict size | mitigate | GitHub API body is capped server-side (typically &lt; 100KB). We store as-is but don't re-transmit without limits. Phase 46 will truncate for the modal render. |
| T-44-13 | D (DoS) | aiohttp.ClientSession leak | mitigate | Shutdown handler closes `update_http_session` in a try/except. If close fails, systemd kill eventually reaps the process. |
| T-44-14 | D (DoS) | has_active_websocket_client returns False when app is still starting up | accept | During early startup the webapp reference may be None for a brief window; the helper handles this (returns False) and scheduler proceeds normally. |
| T-44-15 | E (Elevation) | Wiring remains READ-ONLY | accept | Plan 44-02 adds no privileged operations. No file writes outside what 44-01 already established. |
</threat_model>

<validation_strategy>
## Nyquist Validation — Requirements → Tests

| Requirement | Validation Type | Test Location | What It Proves |
|-------------|----------------|---------------|----------------|
| CHECK-01 (version in footer from importlib.metadata) | Unit (pyproject present) + integration (manual on LXC in Plan 44-03) | test_updater_version.py (44-01) + manual verify in 44-03 | pyproject.toml version bumped, get_current_version returns "8.0.0" after `pip install -e .` |
| CHECK-02 (scheduler as asyncio task) | Integration | test_updater_wiring.py + manual LXC log inspection in 44-03 | __main__.py creates `update_scheduler_task`, task registered in shutdown cancel list |
| CHECK-05 (GET /api/update/available response shape) | Unit | test_updater_webapp_routes.py (all 4 test cases) | Route returns correct JSON in both update-available and no-update states |
| CHECK-06 (fault tolerance last_check_failed_at surfaced in UI) | Unit | test_updater_webapp_routes.py::test_update_available_failed_check | Route returns last_check_failed_at field populated |
| CHECK-07 (defer when WS client connected) | Unit | test_updater_wiring tests in 44-01 + integration manual test in 44-03 | _has_active_ws_client reads app["ws_clients"] length |

No threat model gaps. Route shape verified structurally via mocked request; end-to-end HTTP verified in Plan 44-03 via `curl` on the LXC.
</validation_strategy>

<rollback_plan>
Changes are additive:
- Revert `pyproject.toml` version change: `git checkout pyproject.toml` (one-line diff)
- Revert AppContext changes: `git checkout src/pv_inverter_proxy/context.py`
- Revert webapp changes: `git checkout src/pv_inverter_proxy/webapp.py`
- Revert __main__.py changes: `git checkout src/pv_inverter_proxy/__main__.py`
- Delete new tests: `rm tests/test_updater_webapp_routes.py tests/test_updater_wiring.py`

If the scheduler causes issues on the LXC but version bump is fine, a one-line revert removes the scheduler task creation + shutdown cancel entry; no data migration, no config changes. The blue-green rollback from Phase 43 also provides a whole-service safety net.

If `pip install -e .` on the LXC fails due to version bump (shouldn't — only a string change), the old release dir in the blue-green layout is still available via symlink flip.
</rollback_plan>

<verification>
**Unit verification (runs in sandbox):**
- `python -m pytest tests/test_updater_webapp_routes.py tests/test_updater_wiring.py -x -v` passes
- `python -m pytest tests/ -x` full suite passes (no regressions)
- `python -c "from pv_inverter_proxy.__main__ import _on_update_available; from pv_inverter_proxy.webapp import update_available_handler, broadcast_available_update; print('ok')"`

**Integration verification (Plan 44-03 handles LXC deploy and runtime checks):**
- Service starts without errors: `journalctl -u pv-inverter-proxy -n 50`
- Log shows `version_resolved version=8.0.0 commit=<7char>`
- Log shows `update_scheduler_started`
- After 60s initial delay, log shows a fetch attempt (success or failure)
- `curl http://192.168.3.191/api/update/available` returns JSON with `current_version: "8.0.0"` and `current_commit` populated
- Shutdown is clean: `systemctl restart pv-inverter-proxy` followed by `journalctl -u pv-inverter-proxy -n 20` shows `update_scheduler_cancelled`
</verification>

<success_criteria>
Plan 44-02 is complete when:
- pyproject.toml version is 8.0.0
- AppContext has five new fields
- __main__.py creates shared aiohttp.ClientSession, GithubReleaseClient, UpdateCheckScheduler and starts the task
- __main__.py exposes `_on_update_available(app_ctx, release)` at module level
- __main__.py graceful shutdown cancels `update_scheduler_task` and closes `update_http_session`
- webapp.py has `update_available_handler` registered at `GET /api/update/available`
- webapp.py has `broadcast_available_update` helper mirroring broadcast_device_list
- ws_handler sends `available_update` message on client connect
- 10+ new test cases pass (4 route + 6 wiring)
- Full existing test suite still passes
- Service boots successfully on LXC (verified in Plan 44-03)
- CHECK-01, CHECK-02, CHECK-05, CHECK-06, CHECK-07 wiring complete; frontend display is Plan 44-03
</success_criteria>

<output>
Create `.planning/phases/44-passive-version-badge/44-02-SUMMARY.md` with:
- Frontmatter listing modified files (pyproject.toml, context.py, __main__.py, webapp.py) and created tests
- `provides:` list including "module-level `_on_update_available(app_ctx, release)` for testability" and "`broadcast_available_update(app)` webapp helper"
- `key-decisions:`
  - "Refactored scheduler callback from closure to module-level function in __main__.py so tests can import it directly"
  - "Shared aiohttp.ClientSession created once in run_with_shutdown, not per-request — matches STACK.md recommendation"
  - "Version bumped 6.0.0 → 8.0.0 (required for CHECK-01 to return the real version via importlib.metadata)"
  - "_on_update_available leaves app_ctx.available_update unchanged when release is None (network failure or no release yet), refreshes only on successful fetch with a comparable version"
- `affects:` Plan 44-03 ("consumes /api/update/available and WS available_update messages"), Phase 45 ("reuses shared aiohttp.ClientSession pattern; extends broadcast_available_update with update_in_progress")
</output>