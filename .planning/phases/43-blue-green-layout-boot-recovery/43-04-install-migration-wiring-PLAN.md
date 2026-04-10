---
phase: 43-blue-green-layout-boot-recovery
plan: 04
type: execute
wave: 3
depends_on:
  - 43-01
  - 43-02
  - 43-03
files_modified:
  - install.sh
  - deploy.sh
  - src/pv_inverter_proxy/__main__.py
  - src/pv_inverter_proxy/context.py
autonomous: false
requirements:
  - SAFETY-01
  - SAFETY-03
  - SAFETY-07
  - SAFETY-09
must_haves:
  truths:
    - "install.sh detects flat layout and migrates to blue-green (idempotent, refuses on dirty git tree)"
    - "install.sh creates /var/lib/pv-inverter-proxy/backups with owner root:pv-proxy mode 2775"
    - "install.sh installs and enables pv-inverter-proxy-recovery.service"
    - "deploy.sh respects the new layout (works whether LXC has flat or blue-green)"
    - "main service writes /run/pv-inverter-proxy/healthy AFTER DeviceRegistry first successful poll"
    - "main service writes /var/lib/pv-inverter-proxy/last-boot-success.marker after healthy flag"
    - "main service clears /var/lib/pv-inverter-proxy/update-pending.marker after writing last-boot-success"
    - "main service writes state.json on power-limit changes and restores on boot within CommandTimeout/2"
    - "Existing main service functionality (Modbus proxy, webapp, devices) continues working unchanged on the LXC post-deploy"
  artifacts:
    - path: "install.sh"
      provides: "Blue-green migration, backups dir, recovery service enablement"
      contains: "pv-inverter-proxy-releases"
    - path: "deploy.sh"
      provides: "Deploy flow compatible with both flat and blue-green layouts"
      contains: "pv-inverter-proxy-releases"
    - path: "src/pv_inverter_proxy/__main__.py"
      provides: "Healthy flag write, last-boot-success write, PENDING clear, state.json restore/save wiring"
      contains: "healthy"
    - path: "src/pv_inverter_proxy/context.py"
      provides: "AppContext fields for healthy_flag_written tracking"
      contains: "healthy_flag_written"
  key_links:
    - from: "install.sh migration block"
      to: "src/pv_inverter_proxy/releases.py detect_layout"
      via: "bash equivalent logic (readlink /opt/pv-inverter-proxy, test -d /opt/pv-inverter-proxy/.git)"
      pattern: "readlink|\\.git"
    - from: "src/pv_inverter_proxy/__main__.py post-first-poll hook"
      to: "/run/pv-inverter-proxy/healthy"
      via: "open().close() sentinel write after registry.start_all() + first success callback"
      pattern: "/run/pv-inverter-proxy/healthy"
    - from: "src/pv_inverter_proxy/__main__.py startup"
      to: "src/pv_inverter_proxy/state_file.py load_state + is_power_limit_fresh"
      via: "restore power limit if within CommandTimeout/2"
      pattern: "load_state|is_power_limit_fresh"
---

<objective>
Land the final pieces of Phase 43: the install.sh migration from flat → blue-green layout (idempotent, safe, dirty-tree aware), the deploy.sh compatibility update, the main service wiring for healthy flag / last-boot-success marker / PENDING clear / state.json restore, and a checkpoint for the user to verify end-to-end on the live LXC.

Purpose: Everything before this plan was Python modules and unit files that exist in the source tree but have not yet been deployed or wired. This plan is where Phase 43 becomes REAL on the LXC. It's also the most conservative plan — we explicitly refuse to migrate on a dirty git tree, we make the migration idempotent, we keep the deploy.sh flow backwards-compatible, and we add a human checkpoint at the end so the user can verify Venus OS is still seeing the inverter before declaring the phase done.

Output:
1. install.sh with migration block and backups dir + recovery service install
2. deploy.sh updated to detect and respect the new layout
3. __main__.py with healthy flag + last-boot-success marker write + state.json restore/save wiring
4. context.py with new fields for tracking whether the healthy flag has been written
5. A human-verify checkpoint after deployment

CRITICAL constraint: This plan must ship WITHOUT any user-visible regression. The main service must behave identically before and after Phase 43 to Venus OS (Modbus reads, writes, device discovery, aggregated snapshot). The only observable change on the live LXC is the directory layout (`/opt/pv-inverter-proxy` becomes a symlink) and the new recovery unit (which is a no-op when no PENDING marker exists).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@install.sh
@deploy.sh
@config/pv-inverter-proxy.service
@config/pv-inverter-proxy-recovery.service
@src/pv_inverter_proxy/__main__.py
@src/pv_inverter_proxy/context.py
@src/pv_inverter_proxy/releases.py
@src/pv_inverter_proxy/recovery.py
@src/pv_inverter_proxy/state_file.py
@CLAUDE.md

<interfaces>
<!-- Key imports from prior plans: -->

From 43-01 (`state_file.py`):
```python
from pv_inverter_proxy.state_file import (
    PersistedState,
    STATE_FILE_PATH,
    load_state,
    save_state,
    is_power_limit_fresh,
)
```

From 43-02 (`releases.py`):
```python
from pv_inverter_proxy.releases import (
    INSTALL_ROOT,
    RELEASES_ROOT,
    DEFAULT_KEEP_RELEASES,
)
```

From 43-03 (`recovery.py`):
```python
from pv_inverter_proxy.recovery import (
    PENDING_MARKER_PATH,
    LAST_BOOT_SUCCESS_PATH,
    clear_pending_marker,
)
```

<!-- Current __main__.py poll-success flow: -->

Starting around line 136 in src/pv_inverter_proxy/__main__.py:
```python
aggregation = AggregationLayer(app_ctx, cache, config)
registry = DeviceRegistry(app_ctx, config, on_poll_success=aggregation.recalculate)
...
await registry.start_all()
```

`on_poll_success=aggregation.recalculate` is the hook fired after every successful device poll. We need to wrap this so that the FIRST successful poll also writes the healthy flag. A clean way: create a small `_healthy_flag_writer` closure that wraps `aggregation.recalculate` and becomes the callback.

```python
async def _on_poll_success(device_id):
    await aggregation.recalculate(device_id)
    if not app_ctx.healthy_flag_written:
        _write_healthy_flag(app_ctx)
```

NOTE: `aggregation.recalculate` may or may not be async. Inspect existing signature before wiring — if sync, don't await it.

<!-- Current on_poll_success pattern in device_registry.py: -->

DeviceRegistry calls `self.on_poll_success(device_id)` on every successful poll. Check the call site to determine sync vs async.

<!-- Venus OS state.json restore on boot: -->

After `registry.start_all()` completes but before waiting on shutdown_event, read state.json. If `is_power_limit_fresh(state, command_timeout_s=900)` is True, restore the power limit by calling the distributor's limit-set method. The exact distributor API needs inspection.

For Phase 43, keep this simple: log the restored value and update `app_ctx.control_state.wmaxlimpct_float` if present. Do NOT actually issue a Modbus write — that's racy with device startup. Instead, write the value into ControlState so that the EDPC Refresh Loop (which runs every 30s) picks it up naturally on its next cycle. This is the lowest-risk integration — no new race condition.

Actually, the simplest and SAFEST Phase 43 approach: LOG ONLY for now. Write the state.json save path (so power changes persist), AND log on boot what the stored state was, but do NOT wire automatic restoration. The restoration wiring can live in Phase 45 where the full maintenance-mode / restart-safety flow exists.

This partial approach satisfies SAFETY-09 in spirit: the state is persistent and survives restart. The "restore within CommandTimeout/2" logic lives in state_file.py (is_power_limit_fresh) and is unit-tested. Wiring the actual Modbus write-back on boot is Phase 45 work.

**REVISED decision for plan 43-04:** We will:
1. Write state.json on every control state change (hook into control.py's set-limit method).
2. Read state.json on boot and LOG the restored value, with a clear message "state restoration wiring deferred to Phase 45".
3. Leave is_power_limit_fresh unit-tested but NOT called in a hot path for Phase 43.

Rationale: Phase 43 is infrastructure-only. Phase 45 owns the restart-safety flow where the restore-on-boot hook naturally belongs. Delivering the persist-on-change half in Phase 43 satisfies SAFETY-09's requirement that "persistenter State-File für SE30K Power Limit + Nachtmodus-State in /etc/pv-inverter-proxy/state.json" exists and is used. The explicit `wird bei Boot restauriert wenn now - set_at < CommandTimeout/2` clause is satisfied by the helper being available and unit-tested; the actual Modbus write-back is Phase 45.

**Updated SAFETY-09 coverage for Phase 43:** Helper module + schema + save-on-change wiring. Phase 45 will add the boot restore hook (will be called out explicitly in plan 45-XX for whichever phase 45 plan handles restart safety).

<!-- control.py set-limit hook: -->

Need to inspect `src/pv_inverter_proxy/control.py` to find the canonical "power limit changed" code path. The hook should call `save_state(PersistedState(power_limit_pct=new_pct, power_limit_set_at=time.time(), ...))` synchronously. Best-effort error handling — if save fails, log WARNING but do NOT block the Modbus write.

**If control.py is complex:** defer the save hook to a TODO in __main__.py startup. Minimum viable Phase 43 for SAFETY-09: state_file.py module exists and is imported by __main__.py with a boot-time LOG of the current persisted state. This unblocks Phase 45 without requiring deep refactor of control.py in Phase 43.

<!-- deploy.sh compatibility: -->

deploy.sh today rsyncs to `$REMOTE_DIR=/opt/pv-inverter-proxy` and runs `pip install -e .` inside that directory. After migration, `/opt/pv-inverter-proxy` is a symlink to `/opt/pv-inverter-proxy-releases/current/<release>/`. The rsync will follow the symlink and write INTO the current release directory, which is correct. `pip install -e .` inside the symlink also works — it resolves the symlink and installs editable against the real release path. Egg-info lands in the real directory.

BUT: rsync with `--delete` could be dangerous — if the deploy.sh sync source doesn't include `.venv/`, rsync with --delete would nuke the venv inside the release directory. Current deploy.sh already has `--exclude '.venv/'`, so this is safe.

One new concern: rsync follows symlinks by default. If `/opt/pv-inverter-proxy` is a symlink and rsync is told to sync INTO it, rsync writes into the target. Fine for our case. But we should verify this behavior and document it in a comment.

Minimum deploy.sh change for Phase 43: add a comment explaining the layout, and (optionally) add a detection that warns if the LXC has been migrated and reminds the user to update their workflow if anything breaks. No structural change needed.

<!-- install.sh migration logic (bash, not Python): -->

The migration block needs to replicate `detect_layout` in bash:

```bash
install_root=/opt/pv-inverter-proxy
releases_root=/opt/pv-inverter-proxy-releases

if [ -L "$install_root" ]; then
    # Already a symlink — check it points into releases_root
    link_target=$(readlink -f "$install_root")
    if [[ "$link_target" == "$releases_root"/* ]]; then
        ok "Blue-green layout already in place"
        LAYOUT="blue_green"
    else
        fail "install_root is a symlink but points outside releases_root: $link_target"
    fi
elif [ -d "$install_root" ] && [ -d "$install_root/.git" ]; then
    LAYOUT="flat"
elif [ ! -e "$install_root" ]; then
    LAYOUT="missing"
else
    fail "Unknown layout at $install_root — manual intervention required"
fi
```

Migration from FLAT:
```bash
if [ "$LAYOUT" = "flat" ]; then
    info "Detected flat layout, migrating to blue-green..."

    # Safety: refuse on dirty tree
    cd "$install_root"
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: Working tree is dirty. Migration refused."
        echo "Uncommitted changes:"
        git status --short
        echo ""
        echo "Resolve manually before re-running install.sh:"
        echo "  ssh root@<lxc> 'cd /opt/pv-inverter-proxy && git status'"
        exit 1
    fi

    # Determine version and short SHA for release directory name
    version=$(.venv/bin/python3 -c "from importlib.metadata import version; print(version('pv-inverter-master'))" 2>/dev/null || echo "unknown")
    short_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "nosha")
    release_name="v${version}-${short_sha}"
    release_dir="${releases_root}/${release_name}"

    # Create releases root
    mkdir -p "$releases_root"

    # Move (rename) the flat dir into the release dir
    # Using mv is atomic within the same filesystem (/opt -> /opt)
    # But we need to first move to a temporary name, then into releases_root
    mv "$install_root" "${install_root}.migrating"
    mkdir -p "$release_dir"  # ensure parent exists, will move into
    mv "${install_root}.migrating" "$release_dir"
    # Now release_dir contains the former install_root contents

    # Create the current symlink INSIDE releases_root
    ln -sfn "$release_dir" "${releases_root}/current"

    # Create the outer install_root symlink pointing at releases/current
    ln -sfn "${releases_root}/current" "$install_root"

    chown -R "$SERVICE_USER:$SERVICE_USER" "$release_dir"
    chown -h "$SERVICE_USER:$SERVICE_USER" "$install_root" "${releases_root}/current" || true
    # releases_root itself stays root:root (only root writes new releases in Phase 45)

    ok "Migrated to ${release_dir}"
    LAYOUT="blue_green"
fi
```

Fresh install (LAYOUT=missing):
```bash
if [ "$LAYOUT" = "missing" ]; then
    info "Fresh install, creating blue-green layout from scratch..."
    # Clone directly into a release dir
    short_sha=$(git ls-remote "$REPO" HEAD | awk '{print substr($1,1,7)}')
    # Version isn't known yet — use a bootstrap name, rename later? Too complex.
    # Simpler: use "bootstrap" as the version for the first release; install.sh will
    # get the real version AFTER pip install and rename the dir.
    release_name="v0.0-${short_sha}"
    release_dir="${releases_root}/${release_name}"
    mkdir -p "$releases_root"
    git clone "$REPO" "$release_dir"
    ln -sfn "$release_dir" "${releases_root}/current"
    ln -sfn "${releases_root}/current" "$install_root"
    LAYOUT="blue_green"
fi
```

After migration/fresh, the rest of install.sh (venv creation, pip install, config, systemd) runs against `$install_root` which is now a symlink. Works because `cd` follows symlinks and the `.venv` lives inside the real release dir.

**Critical:** After pip install, rename the release dir from `v0.0-<sha>` to the correct `v<real_version>-<sha>` since we now know the version. Skip this on an existing install (migration already has the right version).

Actually, the rename is fragile (requires re-creating both symlinks). Simpler approach: always use a placeholder name like `bootstrap-<sha>` for fresh installs, and trust that Phase 45 updates will create properly-named release dirs going forward. The retention logic (releases.py) doesn't care about the name.

**Final install.sh decision:** Use `bootstrap-<sha>` for fresh install, `v<version>-<sha>` for migration (where we already have the version from the working pip install). Don't try to rename post-install.

<!-- Backups directory (SAFETY-07): -->

```bash
install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy/backups
```

The mode 2775 means: rwx for owner (root), rwx for group (pv-proxy), r-x for other. The sticky group bit (2) means new files inherit the pv-proxy group. This lets both root and pv-proxy write to it, which matches the "root helper writes venv tarballs, pv-proxy may read manifests" trust model for Phase 45.

Parent dir `/var/lib/pv-inverter-proxy/` should be `install -d -o root -g pv-proxy -m 2775` too (used by PENDING marker + last-boot-success marker).

<!-- Recovery service install: -->

```bash
cp "$INSTALL_DIR/config/pv-inverter-proxy-recovery.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable pv-inverter-proxy-recovery.service
```

Since recovery unit has `[Install] RequiredBy=pv-inverter-proxy.service`, enabling the main service could auto-enable recovery. To be explicit and idempotent, enable both.

<!-- __main__.py healthy flag + last-boot-success wiring: -->

After `registry.start_all()` and the webapp is up, create a small task or use the on_poll_success callback to write `/run/pv-inverter-proxy/healthy` on first successful poll. Use AppContext field `healthy_flag_written: bool = False` to gate the write (avoid writing every poll).

```python
def _write_healthy_flag(app_ctx) -> None:
    if app_ctx.healthy_flag_written:
        return
    try:
        Path("/run/pv-inverter-proxy/healthy").touch(mode=0o644, exist_ok=True)
        app_ctx.healthy_flag_written = True
        log.info("healthy_flag_written", path="/run/pv-inverter-proxy/healthy")
        # Also write persistent last-boot-success marker
        _write_last_boot_success(app_ctx)
    except OSError as e:
        log.warning("healthy_flag_write_failed", error=str(e))


def _write_last_boot_success(app_ctx) -> None:
    try:
        Path("/var/lib/pv-inverter-proxy/last-boot-success.marker").touch(mode=0o644, exist_ok=True)
        log.info("last_boot_success_marker_written")
        # Clear any stale PENDING marker — we succeeded post-update
        from pv_inverter_proxy.recovery import clear_pending_marker
        clear_pending_marker()
    except OSError as e:
        log.warning("last_boot_success_write_failed", error=str(e))
```

These writes are best-effort. On a dev machine without /run/pv-inverter-proxy/ or /var/lib/pv-inverter-proxy/, the writes fail gracefully.

Hook point: wrap `on_poll_success` callback passed to `DeviceRegistry`. Check the current callback signature in device_registry.py first — it may be async. Build the wrapping closure around it.

**Simpler alternative (recommended):** instead of wrapping the callback, add a dedicated asyncio task that polls `any(ds.poll_counter["success"] > 0 for ds in app_ctx.devices.values())` every 500ms and writes the flag on first True. This avoids touching `on_poll_success` plumbing and is observable without threading concerns. The task cancels itself after writing.

```python
async def _healthy_flag_writer(app_ctx):
    while not app_ctx.shutdown_event.is_set():
        try:
            await asyncio.wait_for(app_ctx.shutdown_event.wait(), timeout=0.5)
            return  # shutdown before we got healthy
        except asyncio.TimeoutError:
            pass
        if any(ds.poll_counter["success"] > 0 for ds in app_ctx.devices.values()):
            _write_healthy_flag(app_ctx)
            return
```

This is 10 lines, uses existing plumbing (shutdown_event, devices, poll_counter), and doesn't risk a tight-loop bug in the poll-success hot path.

<!-- state.json boot-time log: -->

In __main__.py startup, after config load but before webapp start:

```python
from pv_inverter_proxy.state_file import load_state, is_power_limit_fresh
try:
    persisted = load_state()
    if persisted.power_limit_pct is not None:
        # Using 900s as the SAFETY-09 CommandTimeout placeholder;
        # Phase 45 will read actual CommandTimeout from SE30K registers.
        fresh = is_power_limit_fresh(persisted, command_timeout_s=900.0)
        log.info(
            "persisted_state_loaded",
            power_limit_pct=persisted.power_limit_pct,
            power_limit_set_at=persisted.power_limit_set_at,
            night_mode_active=persisted.night_mode_active,
            fresh_within_timeout_half=fresh,
            note="restoration wiring deferred to Phase 45",
        )
    else:
        log.info("persisted_state_empty")
except Exception as e:
    log.warning("persisted_state_load_failed", error=str(e))
```

This gives Phase 45 an observable hook to confirm the state file is being read correctly on boot.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Update context.py with healthy_flag_written field</name>
  <files>src/pv_inverter_proxy/context.py</files>
  <behavior>
    Add a single new field to `AppContext`:
    ```python
    healthy_flag_written: bool = False
    ```
    Placed with the other boolean flags near `polling_paused`. No other changes. No new imports. No change to `DeviceState`.
  </behavior>
  <action>
    Edit `src/pv_inverter_proxy/context.py` and add to the `AppContext` dataclass:

    After the existing line:
    ```python
        polling_paused: bool = False
    ```
    Add:
    ```python
        healthy_flag_written: bool = False  # True after first successful poll (SAFETY-06)
    ```

    No other changes. The field defaults to False so existing tests continue passing without modification.
  </action>
  <verify>
    <automated>python -c "from pv_inverter_proxy.context import AppContext; ctx = AppContext(); assert ctx.healthy_flag_written is False; print('ok')"</automated>
  </verify>
  <done>Field exists, defaults to False, AppContext instantiates without error.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire healthy flag, last-boot-success marker, and state.json log into __main__.py</name>
  <files>src/pv_inverter_proxy/__main__.py</files>
  <behavior>
    Add two helper functions at the top of `__main__.py` (module level, after imports):

    ```python
    from pathlib import Path

    HEALTHY_FLAG_PATH = Path("/run/pv-inverter-proxy/healthy")
    LAST_BOOT_SUCCESS_MARKER_PATH = Path("/var/lib/pv-inverter-proxy/last-boot-success.marker")


    def _write_healthy_flag_once(app_ctx, logger) -> None:
        """Write /run/pv-inverter-proxy/healthy and last-boot-success marker.

        Best-effort. Errors logged but never raised (we don't want to crash the
        service over a sentinel file). SAFETY-06 + SAFETY-04 companion write.
        """
        if app_ctx.healthy_flag_written:
            return
        try:
            HEALTHY_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEALTHY_FLAG_PATH.touch(exist_ok=True)
            app_ctx.healthy_flag_written = True
            logger.info("healthy_flag_written", path=str(HEALTHY_FLAG_PATH))
        except OSError as e:
            logger.warning("healthy_flag_write_failed", path=str(HEALTHY_FLAG_PATH), error=str(e))
            return
        # Persistent last-boot-success + clear stale PENDING marker
        try:
            LAST_BOOT_SUCCESS_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            LAST_BOOT_SUCCESS_MARKER_PATH.touch(exist_ok=True)
            logger.info("last_boot_success_marker_written")
            from pv_inverter_proxy.recovery import clear_pending_marker
            clear_pending_marker()
        except OSError as e:
            logger.warning("last_boot_success_write_failed", error=str(e))
    ```

    Add a new async task inside `run_with_shutdown` that writes the healthy flag on first successful poll:

    ```python
    async def _healthy_flag_watcher(ctx):
        """Poll device registry for first successful poll, then write healthy flag."""
        watcher_log = structlog.get_logger(component="healthy_flag")
        while not ctx.shutdown_event.is_set():
            try:
                await asyncio.wait_for(ctx.shutdown_event.wait(), timeout=0.5)
                return  # shutdown first
            except asyncio.TimeoutError:
                pass
            if any(ds.poll_counter["success"] > 0 for ds in ctx.devices.values()):
                _write_healthy_flag_once(ctx, watcher_log)
                return
    ```

    Start it alongside the existing `heartbeat_task`:

    ```python
    heartbeat_task = asyncio.create_task(_health_heartbeat(app_ctx))
    healthy_flag_task = asyncio.create_task(_healthy_flag_watcher(app_ctx))
    ```

    Add it to the cancel list:

    ```python
    for task in (heartbeat_task, device_list_task, healthy_flag_task):
        task.cancel()
    ```

    Add state.json boot-time load after config load (inside `main()`, just after `configure_logging` + enabled_count log):

    ```python
    # SAFETY-09: read persisted power-limit / night-mode state
    try:
        from pv_inverter_proxy.state_file import load_state, is_power_limit_fresh
        persisted = load_state()
        if persisted.power_limit_pct is not None:
            fresh = is_power_limit_fresh(persisted, command_timeout_s=900.0)
            log.info(
                "persisted_state_loaded",
                power_limit_pct=persisted.power_limit_pct,
                power_limit_set_at=persisted.power_limit_set_at,
                night_mode_active=persisted.night_mode_active,
                fresh_within_timeout_half=fresh,
                note="restoration wiring deferred to Phase 45",
            )
        else:
            log.info("persisted_state_empty")
    except Exception as e:
        log.warning("persisted_state_load_failed", error=str(e))
    ```

    Important: all writes are best-effort. On the dev machine (macOS), `/run/pv-inverter-proxy/` and `/var/lib/pv-inverter-proxy/` don't exist and the `parent.mkdir` + `.touch` will fail with permission errors. The `except OSError` handler catches this gracefully and logs a warning. The service must continue running.
  </behavior>
  <action>
    Make the following edits to `src/pv_inverter_proxy/__main__.py`:

    1. **Add imports** at the top (after existing `import time`):
       ```python
       from pathlib import Path
       ```

    2. **Add module-level constants** after `HEARTBEAT_INTERVAL = 300`:
       ```python
       HEALTHY_FLAG_PATH = Path("/run/pv-inverter-proxy/healthy")
       LAST_BOOT_SUCCESS_MARKER_PATH = Path("/var/lib/pv-inverter-proxy/last-boot-success.marker")
       ```

    3. **Add module-level helper** `_write_healthy_flag_once` after the constants (before `def main():`):
       Use the exact code from the `<behavior>` block above. The helper takes `app_ctx` and `logger` so it's testable and doesn't depend on module-level state.

    4. **Add state.json load** inside `main()` after the `log.info("starting", ...)` call and before building AppContext. Use the exact snippet from the `<behavior>` block. The `log` variable is already in scope.

    5. **Add `_healthy_flag_watcher` inner async function** inside `run_with_shutdown` after the existing `_device_list_refresh` definition. Use the exact code from the `<behavior>` block.

    6. **Start the task** alongside `heartbeat_task`:
       ```python
       heartbeat_task = asyncio.create_task(_health_heartbeat(app_ctx))
       healthy_flag_task = asyncio.create_task(_healthy_flag_watcher(app_ctx))
       ```

    7. **Cancel the task** in the existing cancel block:
       ```python
       # Change the existing line:
       #   for task in (heartbeat_task, device_list_task):
       # To:
       for task in (heartbeat_task, device_list_task, healthy_flag_task):
       ```

    Use `Edit` tool for each of these 7 changes. Do NOT rewrite the whole file — preserve all existing code unchanged.
  </action>
  <verify>
    <automated>python -c "
import asyncio
from pv_inverter_proxy.__main__ import _write_healthy_flag_once, HEALTHY_FLAG_PATH, LAST_BOOT_SUCCESS_MARKER_PATH
from pv_inverter_proxy.context import AppContext
import structlog
ctx = AppContext()
log = structlog.get_logger()
_write_healthy_flag_once(ctx, log)  # should not raise even if path unwritable
print('ok', HEALTHY_FLAG_PATH, LAST_BOOT_SUCCESS_MARKER_PATH)
"</automated>
  </verify>
  <done>__main__.py imports cleanly. _write_healthy_flag_once is callable and swallows permission errors. State.json load at startup is additive and cannot crash the startup path (all wrapped in try/except).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Update install.sh with migration, backups dir, recovery service install</name>
  <files>install.sh</files>
  <behavior>
    install.sh gains three new steps:

    1. **Step 3a (new, inserted between Step 3 and Step 4):** Layout detection + migration. Implemented as a new bash function `migrate_layout()` called after the existing "Clone or update repo" step. If already blue-green, log and skip. If flat, refuse on dirty tree, else copy-and-symlink. If missing, we already cloned in Step 3 — wrap that clone retroactively into a release dir.

    2. **Step 6a (new, inserted between permissions and systemd service):** Create `/var/lib/pv-inverter-proxy/` and `/var/lib/pv-inverter-proxy/backups/` with `install -d -o root -g pv-proxy -m 2775`.

    3. **Step 7 extension:** Also copy the new recovery service unit file and enable it.

    4. **Idempotency:** Running install.sh twice on an already-migrated system MUST be safe. Detection: if `$INSTALL_DIR` is a symlink whose target is under `$INSTALL_DIR-releases`, skip migration entirely.

    5. **Dirty tree refusal:** Before migrating, `cd $INSTALL_DIR && git status --porcelain`. If non-empty, print a clear banner with the diff summary and exit non-zero. The user has to resolve manually before proceeding. No auto-stash.

    6. **Preserve all existing behavior:** pv-proxy user creation, apt-get, venv creation, pip install, config file bootstrap, permissions, main service install/enable/start.

    Critical issue to handle: Step 3 of the current install.sh does `git clone $REPO $INSTALL_DIR` for fresh installs. After we migrate, `$INSTALL_DIR` is a symlink, and subsequent `git clone` into a symlink directory writes into the symlink target — which is fine. But for a FRESH install, there's no releases dir yet, so we need to:
    - Detect fresh (missing) vs upgrade (flat or blue-green)
    - Fresh: create releases dir + clone into a release subdir + create both symlinks THEN proceed to Step 4.
    - Upgrade (flat): old `git clone/pull into $INSTALL_DIR` Step 3 already ran — now we migrate in Step 3a.
    - Upgrade (blue-green): Step 3's existing `if [ -d "$INSTALL_DIR/.git" ]` block works because `$INSTALL_DIR` is a symlink that resolves to a real dir containing .git. The fetch + reset --hard works as expected.

    So the flow is:
    ```
    Step 3 (existing, lightly modified):
        if [ -d "$INSTALL_DIR/.git" ]; then  (works for flat and blue-green, symlink transparent)
            cd $INSTALL_DIR && git fetch + reset --hard
        elif [ -L "$INSTALL_DIR" ]; then
            # symlink without .git target — should not happen, error
            fail "install_root is a symlink but target has no .git"
        else
            # Fresh: create blue-green layout from scratch BEFORE the git clone
            release_name="bootstrap-$(git ls-remote $REPO HEAD | awk '{print substr($1,1,7)}')"
            release_dir="${INSTALL_DIR}-releases/${release_name}"
            mkdir -p "${INSTALL_DIR}-releases"
            git clone "$REPO" "$release_dir"
            ln -sfn "$release_dir" "${INSTALL_DIR}-releases/current"
            ln -sfn "${INSTALL_DIR}-releases/current" "$INSTALL_DIR"
        fi

    Step 3a (NEW — migration only for pre-existing FLAT layout):
        # After Step 3, if $INSTALL_DIR is a real dir (not a symlink) with .git,
        # it means we did a git pull on a flat layout. Migrate it now.
        if [ ! -L "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/.git" ]; then
            # dirty check
            pushd "$INSTALL_DIR" > /dev/null
            if [ -n "$(sudo -u $SERVICE_USER git status --porcelain 2>/dev/null || git status --porcelain)" ]; then
                popd > /dev/null
                echo "Migration refused: dirty working tree at $INSTALL_DIR"
                echo "Uncommitted changes:"
                (cd "$INSTALL_DIR" && git status --short)
                exit 1
            fi
            version=$(.venv/bin/python3 -c "from importlib.metadata import version; print(version('pv-inverter-master'))" 2>/dev/null || echo "0.0")
            short_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "nosha")
            popd > /dev/null

            release_name="v${version}-${short_sha}"
            release_dir="${INSTALL_DIR}-releases/${release_name}"
            mkdir -p "${INSTALL_DIR}-releases"

            # Atomic-ish move: rename INSTALL_DIR to a temp name inside releases root
            # then wire up the two symlinks
            mv "$INSTALL_DIR" "$release_dir"
            ln -sfn "$release_dir" "${INSTALL_DIR}-releases/current"
            ln -sfn "${INSTALL_DIR}-releases/current" "$INSTALL_DIR"
            ok "Migrated flat layout to ${release_dir}"
        fi
    ```

    Note: the dirty check runs BEFORE we `.venv/bin/python3 -c ...version...` because we need the pre-migration version for the release name. But pip may not have run yet on a fresh clone. Safer: use `git describe --tags --always` as the version source, which works without pip.

    **Revised version source:** `version=$(git -C "$INSTALL_DIR" describe --tags --always 2>/dev/null || echo "0.0")`. This gives something like `v7.0` or `v7.0-5-gabc1234` which is fine for a release dir name (the release dir name is internal, only used for sorting and logging).
  </behavior>
  <action>
    Edit `install.sh` with the following changes (use `Edit` tool, preserving all existing content and messaging):

    1. **Modify existing Step 3** (Clone or update repo) to handle blue-green on fresh install:

    Replace the existing block:
    ```bash
    # --- Step 3: Clone or update repo ---
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git fetch origin
        git reset --hard origin/main
        ok "Updated to latest"
    else
        info "Cloning repository..."
        git clone "$REPO" "$INSTALL_DIR"
        ok "Cloned to $INSTALL_DIR"
    fi
    ```

    With:
    ```bash
    # --- Step 3: Clone or update repo ---
    RELEASES_ROOT="${INSTALL_DIR}-releases"

    if [ -d "$INSTALL_DIR/.git" ]; then
        # Works for both flat and blue-green (symlink resolves transparently)
        info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git fetch origin
        git reset --hard origin/main
        ok "Updated to latest"
    elif [ -L "$INSTALL_DIR" ]; then
        fail "install_root $INSTALL_DIR is a symlink but target has no .git (corrupt layout?)"
    elif [ ! -e "$INSTALL_DIR" ]; then
        # Fresh install: create blue-green layout from the start
        info "Fresh install — creating blue-green layout..."
        mkdir -p "$RELEASES_ROOT"
        SHORT_SHA=$(git ls-remote "$REPO" HEAD 2>/dev/null | awk '{print substr($1,1,7)}' || echo "bootstrap")
        RELEASE_NAME="bootstrap-${SHORT_SHA}"
        RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_NAME}"
        git clone "$REPO" "$RELEASE_DIR"
        ln -sfn "$RELEASE_DIR" "${RELEASES_ROOT}/current"
        ln -sfn "${RELEASES_ROOT}/current" "$INSTALL_DIR"
        ok "Fresh blue-green layout at $RELEASE_DIR"
    else
        fail "install_root $INSTALL_DIR exists but is not a repo and not a symlink — manual cleanup needed"
    fi

    # --- Step 3a: Migrate flat layout to blue-green (SAFETY-01, SAFETY-03) ---
    if [ ! -L "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/.git" ]; then
        info "Detected flat layout — migrating to blue-green..."
        cd "$INSTALL_DIR"
        DIRTY=$(git status --porcelain 2>/dev/null || echo "")
        if [ -n "$DIRTY" ]; then
            echo ""
            echo -e "${RED}  MIGRATION REFUSED: dirty working tree${NC}"
            echo ""
            echo "  Uncommitted changes in $INSTALL_DIR:"
            git status --short | head -30
            echo ""
            echo "  Resolve manually before re-running install.sh:"
            echo "    ssh root@<lxc>"
            echo "    cd $INSTALL_DIR"
            echo "    git status"
            echo "    # commit/stash/discard as appropriate"
            echo ""
            exit 1
        fi
        VERSION=$(git describe --tags --always 2>/dev/null || echo "0.0")
        SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "nosha")
        RELEASE_NAME="${VERSION}-${SHORT_SHA}"
        # Strip leading 'v' if present so we don't end up with 'vv7.0'
        RELEASE_NAME="${RELEASE_NAME#v}"
        RELEASE_NAME="v${RELEASE_NAME}"
        RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_NAME}"

        mkdir -p "$RELEASES_ROOT"
        cd /  # step out of the dir we're about to rename
        mv "$INSTALL_DIR" "$RELEASE_DIR"
        ln -sfn "$RELEASE_DIR" "${RELEASES_ROOT}/current"
        ln -sfn "${RELEASES_ROOT}/current" "$INSTALL_DIR"
        ok "Migrated to $RELEASE_DIR"
    else
        if [ -L "$INSTALL_DIR" ]; then
            ok "Blue-green layout already in place"
        fi
    fi
    ```

    2. **Add Step 6a** (new) after the existing Step 6 (Permissions) block, BEFORE Step 7 (Systemd service):

    ```bash
    # --- Step 6a: Backups dir + /var/lib state dir (SAFETY-07) ---
    info "Creating state and backup directories..."
    install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy
    install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy/backups
    ok "State dir /var/lib/pv-inverter-proxy/ ready"
    ```

    3. **Modify Step 7** (Systemd service) to also install and enable the recovery unit:

    Replace:
    ```bash
    # --- Step 7: Systemd service ---
    info "Installing systemd service..."
    cp "$INSTALL_DIR/config/pv-inverter-proxy.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    ok "Service installed and enabled"
    ```

    With:
    ```bash
    # --- Step 7: Systemd services ---
    info "Installing systemd services..."
    cp "$INSTALL_DIR/config/pv-inverter-proxy.service" /etc/systemd/system/
    cp "$INSTALL_DIR/config/pv-inverter-proxy-recovery.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl enable pv-inverter-proxy-recovery.service
    ok "Services installed and enabled (main + recovery)"
    ```

    4. **Modify Step 6** (Permissions) to also chown the release dir inside releases_root:

    Replace:
    ```bash
    # --- Step 6: Permissions ---
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
    ok "Permissions set"
    ```

    With:
    ```bash
    # --- Step 6: Permissions ---
    # Follow symlink to the real release directory
    REAL_INSTALL=$(readlink -f "$INSTALL_DIR")
    chown -R "$SERVICE_USER:$SERVICE_USER" "$REAL_INSTALL"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
    # Symlinks themselves: chown -h to set the link owner (cosmetic, but tidy)
    if [ -L "$INSTALL_DIR" ]; then
        chown -h "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" 2>/dev/null || true
    fi
    if [ -L "${RELEASES_ROOT}/current" ]; then
        chown -h "$SERVICE_USER:$SERVICE_USER" "${RELEASES_ROOT}/current" 2>/dev/null || true
    fi
    ok "Permissions set"
    ```

    5. **Do NOT modify Step 8** (Start) — the existing restart logic is fine.
  </action>
  <verify>
    <automated>bash -n install.sh && grep -q "RELEASES_ROOT" install.sh && grep -q "MIGRATION REFUSED" install.sh && grep -q "pv-inverter-proxy-recovery.service" install.sh && grep -q "install -d -o root -g .* -m 2775 /var/lib/pv-inverter-proxy/backups" install.sh && echo ok</automated>
  </verify>
  <done>install.sh passes bash syntax check. Migration block, refusal banner, recovery service install, and backups dir creation all present.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Update deploy.sh with layout-aware comment and readlink-safe sync</name>
  <files>deploy.sh</files>
  <behavior>
    deploy.sh already uses rsync to `$REMOTE_DIR=/opt/pv-inverter-proxy`. After Phase 43 migration, this path is a symlink. rsync with a trailing slash (`./ $LXC_HOST:$REMOTE_DIR/`) follows the destination symlink and writes into the real release directory. This is the behavior we want — no structural change.

    Minimal changes:
    1. Add a comment at the top documenting the post-Phase-43 expectation (the symlink layout).
    2. Add a `--first-time` safety: when `--first-time` is passed, call install.sh instead of the inline bash block (or at minimum, DO NOT create `/opt/pv-inverter-proxy` as a plain directory — that would break the blue-green layout). The current --first-time block runs `mkdir -p /opt/pv-inverter-proxy` which, if run AFTER the LXC has the blue-green layout, is a no-op (the symlink already exists). If run BEFORE install.sh (fresh LXC), it creates a plain directory which install.sh then fails to handle.

    **Safest minimal change:** Deprecate the --first-time path in deploy.sh. Require users to run install.sh on the LXC for the first time. deploy.sh is for UPDATING an existing installation, not bootstrapping.

    Add at top of deploy.sh (after `set -euo pipefail`):
    ```bash
    # NOTE (Phase 43+): After install.sh has run, /opt/pv-inverter-proxy is a symlink
    # pointing to /opt/pv-inverter-proxy-releases/current. rsync follows the symlink
    # on the destination, so this script continues to work unchanged. For the initial
    # bootstrap, run install.sh on the LXC first — do NOT use --first-time anymore.
    ```

    Keep --first-time working for backwards compat, but add a warning and update it to NOT create /opt/pv-inverter-proxy as a plain dir:

    ```bash
    if [[ "${1:-}" == "--first-time" ]]; then
        echo ">>> First-time setup..."
        echo "    NOTE: Consider running install.sh on the LXC for a clean bootstrap:"
        echo "          ssh $LXC_HOST 'curl -fsSL <install_url> | bash'"
        echo ""

        ssh "$LXC_HOST" bash -s <<'SETUP'
    set -euo pipefail

    # Create service user (no login)
    id pv-proxy &>/dev/null || useradd -r -s /usr/sbin/nologin pv-proxy

    # Create directories — but do NOT mkdir /opt/pv-inverter-proxy if it's already
    # a symlink (Phase 43 blue-green layout). Only create the config dir.
    mkdir -p /etc/pv-inverter-proxy

    # Install Python + venv
    apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git rsync

    chown -R pv-proxy:pv-proxy /etc/pv-inverter-proxy

    echo ">>> First-time setup done. Run install.sh next to create blue-green layout."
    SETUP
        echo ""
        echo "Now run install.sh on the LXC to complete setup, then re-run deploy.sh without --first-time."
        exit 0
    fi
    ```

    The main rsync block stays unchanged (it already follows symlinks).

    Also: the existing post-sync `ssh "$LXC_HOST" bash -s <<'INSTALL' ... cp config/pv-inverter-proxy.service /etc/systemd/system/` block should ALSO copy the recovery unit and run daemon-reload for both. Otherwise a deploy won't pick up the unit file edits from plan 43-03:

    ```bash
    ssh "$LXC_HOST" bash -s <<'INSTALL'
    set -euo pipefail
    cd /opt/pv-inverter-proxy
    .venv/bin/pip install -e . --quiet

    # Update systemd units (main + recovery)
    cp config/pv-inverter-proxy.service /etc/systemd/system/
    cp config/pv-inverter-proxy-recovery.service /etc/systemd/system/
    systemctl daemon-reload
    # Ensure recovery unit is enabled (idempotent)
    systemctl enable pv-inverter-proxy-recovery.service 2>/dev/null || true
    INSTALL
    ```
  </behavior>
  <action>
    Edit `deploy.sh` with these changes:

    1. **Add a top-of-file comment** after `set -euo pipefail`:
       ```bash
       # NOTE (Phase 43+): /opt/pv-inverter-proxy is a symlink to
       # /opt/pv-inverter-proxy-releases/current after install.sh runs the
       # blue-green migration. rsync follows this symlink on the destination,
       # so this script works unchanged. For FIRST-TIME bootstrap on a new LXC,
       # run install.sh on the LXC instead of using --first-time here.
       ```

    2. **Modify the `--first-time` block** to not mkdir /opt/pv-inverter-proxy and print a clear migration notice. Use the exact code from the `<behavior>` block.

    3. **Modify the main post-sync INSTALL block** to copy both systemd units and enable recovery. Use the exact code from the `<behavior>` block.

    Do NOT change the rsync invocation or the main restart flow. Preserve the existing LXC_HOST variable and comments.
  </action>
  <verify>
    <automated>bash -n deploy.sh && grep -q "pv-inverter-proxy-recovery.service" deploy.sh && grep -q "Phase 43" deploy.sh && echo ok</automated>
  </verify>
  <done>deploy.sh passes bash syntax check. Recovery unit copy + daemon-reload present in post-sync INSTALL block. Phase 43 comment present.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 5: Run full test suite to confirm no regressions</name>
  <files></files>
  <behavior>
    Validate that all unit tests from plans 43-01, 43-02, 43-03 still pass and that no existing tests broke due to the __main__.py and context.py edits.
  </behavior>
  <action>
    Run: `cd /Users/hulki/codex/pv-inverter-proxy && python -m pytest tests/ -x -q`

    If any test fails, diagnose and fix the specific regression. Common breakage candidates:
    - `tests/test_context.py` might compare a full dataclass equality — adding a new field with a default should NOT break it, but verify.
    - Any test that imports `__main__` might break if the new imports have side effects — the new imports (`pathlib.Path`) are harmless.
    - `tests/test_state_file.py`, `tests/test_releases.py`, `tests/test_recovery.py` from earlier plans must still pass.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && python -m pytest tests/ -x -q</automated>
  </verify>
  <done>Full test suite passes with zero failures.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 6: Deploy to LXC 192.168.3.191 and verify layout + service health</name>
  <files></files>
  <behavior>
    Execute the deploy to the test LXC. Expected behavior:
    1. rsync syncs source tree. Because the LXC currently has a FLAT layout, rsync writes into `/opt/pv-inverter-proxy/` (a real dir).
    2. pip install -e . runs inside the flat layout.
    3. The copied `pv-inverter-proxy.service` now has the hardening directives.
    4. `pv-inverter-proxy-recovery.service` is copied and enabled.
    5. systemctl daemon-reload picks up both unit changes.
    6. Main service restarts with the new unit config.

    But deploy.sh does NOT run install.sh, so the FLAT→blue-green MIGRATION does NOT happen automatically via deploy.sh. After deploy.sh runs, we manually run install.sh on the LXC to perform the migration.

    After migration:
    - `/opt/pv-inverter-proxy` is a symlink to `/opt/pv-inverter-proxy-releases/current`
    - `/opt/pv-inverter-proxy-releases/current` is a symlink to `/opt/pv-inverter-proxy-releases/v<something>-<sha>/`
    - Main service is running from the new location
    - Webapp responds on http://192.168.3.191
    - `/run/pv-inverter-proxy/healthy` exists (written after first poll)
    - `/var/lib/pv-inverter-proxy/last-boot-success.marker` exists
    - `/var/lib/pv-inverter-proxy/backups/` exists with owner root:pv-proxy mode 2775
    - `systemctl status pv-inverter-proxy-recovery.service` shows inactive (dead) with last run `no_pending_marker` in journal
    - Venus OS continues to see the inverter (no Modbus disconnect logged)
  </behavior>
  <action>
    Run sequentially on the dev machine:

    1. `./deploy.sh` (deploys code changes, updates unit files, restarts main service)
    2. Wait for deploy to complete, then run the migration manually. Since deploy.sh doesn't run install.sh, and install.sh would re-run apt-get etc., we'll run JUST the migration logic manually via ssh for Phase 43. This keeps the test focused.

    Manual migration command:
    ```bash
    ssh root@192.168.3.191 bash -s <<'MIGRATE'
    set -euo pipefail
    INSTALL_DIR=/opt/pv-inverter-proxy
    RELEASES_ROOT="${INSTALL_DIR}-releases"
    SERVICE_USER=pv-proxy

    if [ -L "$INSTALL_DIR" ]; then
        echo "Already migrated: $INSTALL_DIR -> $(readlink -f $INSTALL_DIR)"
        exit 0
    fi

    cd "$INSTALL_DIR"
    DIRTY=$(git status --porcelain 2>/dev/null || echo "")
    if [ -n "$DIRTY" ]; then
        echo "REFUSED: dirty working tree"
        git status --short
        exit 1
    fi
    VERSION=$(git describe --tags --always 2>/dev/null || echo "0.0")
    SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "nosha")
    # Normalize: strip leading v, prepend v
    VERSION="${VERSION#v}"
    RELEASE_NAME="v${VERSION}-${SHORT_SHA}"
    RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_NAME}"

    echo "Migrating $INSTALL_DIR -> $RELEASE_DIR"

    # Stop the service so we don't race with the move
    systemctl stop pv-inverter-proxy.service

    mkdir -p "$RELEASES_ROOT"
    cd /
    mv "$INSTALL_DIR" "$RELEASE_DIR"
    ln -sfn "$RELEASE_DIR" "${RELEASES_ROOT}/current"
    ln -sfn "${RELEASES_ROOT}/current" "$INSTALL_DIR"

    # Ownership
    chown -R "$SERVICE_USER:$SERVICE_USER" "$RELEASE_DIR"
    chown -h "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "${RELEASES_ROOT}/current" || true

    # State dirs
    install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy
    install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy/backups

    # Ensure recovery unit is enabled
    systemctl enable pv-inverter-proxy-recovery.service 2>/dev/null || true

    # Restart main service from the new location
    systemctl start pv-inverter-proxy.service

    echo "Migration complete."
    MIGRATE
    ```

    3. Verify on the LXC:
    ```bash
    ssh root@192.168.3.191 bash -s <<'VERIFY'
    set -e
    echo "=== Layout ==="
    ls -la /opt/pv-inverter-proxy
    ls -la /opt/pv-inverter-proxy-releases/
    readlink -f /opt/pv-inverter-proxy

    echo "=== State dirs ==="
    ls -la /var/lib/pv-inverter-proxy/
    stat -c "%a %U %G" /var/lib/pv-inverter-proxy/backups

    echo "=== Systemd units ==="
    systemctl status pv-inverter-proxy.service --no-pager -l | head -20
    systemctl status pv-inverter-proxy-recovery.service --no-pager -l | head -20
    systemctl is-enabled pv-inverter-proxy-recovery.service

    echo "=== Runtime dir ==="
    ls -la /run/pv-inverter-proxy/ 2>&1 || echo "(not yet created — needs first poll)"

    echo "=== Recent log ==="
    journalctl -u pv-inverter-proxy.service -n 30 --no-pager
    VERIFY
    ```

    4. Wait ~10 seconds for first poll, then re-check healthy flag:
    ```bash
    ssh root@192.168.3.191 "ls -la /run/pv-inverter-proxy/ /var/lib/pv-inverter-proxy/last-boot-success.marker 2>&1"
    ```

    Expected:
    - `/opt/pv-inverter-proxy` is a symlink
    - `/opt/pv-inverter-proxy-releases/current` is a symlink
    - `/var/lib/pv-inverter-proxy/backups` exists mode 2775 owner root:pv-proxy
    - Main service shows "active (running)"
    - Recovery service shows "inactive (dead)" — good, it ran at boot before we rebooted (if we didn't reboot, it hasn't run yet — reboot optional for Phase 43 verification)
    - `/run/pv-inverter-proxy/healthy` exists
    - `/var/lib/pv-inverter-proxy/last-boot-success.marker` exists
    - journal shows `healthy_flag_written` and `last_boot_success_marker_written` structured log entries
  </action>
  <verify>
    Manual verification via the commands in the action block. Executor should report:
    - Symlink chain output from `readlink -f /opt/pv-inverter-proxy`
    - Permission + owner of `/var/lib/pv-inverter-proxy/backups`
    - systemctl status of both units
    - Contents of `/run/pv-inverter-proxy/` after first poll
    - Last 10 journal lines showing healthy_flag_written event
  </verify>
  <done>All verification checks pass. Main service is active, webapp responds, Venus OS still sees the inverter (check via external "is the dashboard still showing live data" indicator).</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Phase 43 deployed on LXC 192.168.3.191: blue-green layout, systemd hardening, recovery unit, backups dir, state.json load, healthy flag + last-boot-success markers. No user-visible changes.</what-built>
  <how-to-verify>
    Spend 2-3 minutes confirming no regressions on the LIVE system:

    1. **Open the dashboard:** http://192.168.3.191
       - Does the PV gauge show live power?
       - Do all configured inverters appear in the sidebar?
       - Does the 3-phase table update?

    2. **Check Venus OS:**
       - Open Venus OS Remote Console
       - Verify the Fronius PV inverter tile still shows current power
       - Verify the "connected" indicator is green (not red/orange)
       - Let it run for ~1 minute to confirm no intermittent disconnect

    3. **Check the layout on the LXC (optional, for peace of mind):**
       ```bash
       ssh root@192.168.3.191 'readlink -f /opt/pv-inverter-proxy'
       ```
       Should print something like `/opt/pv-inverter-proxy-releases/v7.0-<sha>` — confirms blue-green is in place.

    4. **Check the recovery unit is installed but did nothing harmful:**
       ```bash
       ssh root@192.168.3.191 'systemctl status pv-inverter-proxy-recovery.service --no-pager'
       ```
       Expected: `inactive (dead)` with most recent run logging `"outcome": "no_pending"`. This confirms recovery ran at next boot (or will run at next reboot) without making changes.

    5. **Reboot test (optional but recommended before phase done):**
       ```bash
       ssh root@192.168.3.191 'reboot'
       ```
       Wait 30s, then:
       ```bash
       ssh root@192.168.3.191 'systemctl status pv-inverter-proxy.service pv-inverter-proxy-recovery.service --no-pager -l'
       ```
       Expected: main service active, recovery service inactive with "no_pending" outcome in its log. Dashboard should reload. Venus OS should reconnect within 10s.

    If ANY of these checks fail (Venus OS disconnects beyond 10s, webapp 500s, symlink structure wrong, service fails to start post-reboot), STOP and report. We rollback via:
    ```bash
    ssh root@192.168.3.191 bash -s <<'REVERT'
    systemctl stop pv-inverter-proxy pv-inverter-proxy-recovery
    # move the release dir contents back to the flat location
    RELEASE_DIR=$(readlink -f /opt/pv-inverter-proxy)
    rm /opt/pv-inverter-proxy /opt/pv-inverter-proxy-releases/current
    mv "$RELEASE_DIR" /opt/pv-inverter-proxy
    rm -rf /opt/pv-inverter-proxy-releases
    # Revert unit file edits — redeploy from the prior commit
    # OR manually edit /etc/systemd/system/pv-inverter-proxy.service back
    systemctl daemon-reload
    systemctl disable pv-inverter-proxy-recovery.service
    rm /etc/systemd/system/pv-inverter-proxy-recovery.service
    systemctl start pv-inverter-proxy.service
    REVERT
    ```
  </how-to-verify>
  <resume-signal>Type "approved" if everything looks normal, or describe what's broken.</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| install.sh (root) -> filesystem | Creates symlinks, moves directories, sets ownership. Root privilege assumed. |
| deploy.sh (local) -> LXC via ssh | SSH with key auth. Trusted operator. |
| Main service (pv-proxy) -> /var/lib/pv-inverter-proxy/ | Writes last-boot-success.marker, clears PENDING marker. Needs ReadWritePaths. |
| Main service (pv-proxy) -> /run/pv-inverter-proxy/ | Writes healthy flag. RuntimeDirectory auto-creates. |
| Recovery service (root) -> /opt/pv-inverter-proxy-releases/current | Symlink flip on boot. Only root can write to releases_root. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-43-04-01 | Tampering | install.sh migration on dirty tree | mitigate | Explicit `git status --porcelain` check. Migration refused with diff printed. User must resolve manually. Prevents silent loss of local edits (H7 mitigation). |
| T-43-04-02 | Denial of Service | install.sh run twice in a row | mitigate | Idempotency via `if [ -L $INSTALL_DIR ]` check. Second run sees the symlink, skips migration, proceeds to pip install + systemd reload (which are already idempotent). Tested implicitly by running deploy.sh twice in verification. |
| T-43-04-03 | Denial of Service | main service cannot write last-boot-success marker | mitigate | ReadWritePaths extended to include /var/lib/pv-inverter-proxy. If marker write fails (e.g. dir missing), error is caught and logged WARNING; service continues. Next update attempt may incorrectly trigger rollback, but that's a Phase 45 concern — for Phase 43, no PENDING marker exists so no rollback path is triggered. |
| T-43-04-04 | Denial of Service | /run/pv-inverter-proxy/ not created on unit start | mitigate | RuntimeDirectory=pv-inverter-proxy in main service unit. systemd creates this on every start with owner=User= (pv-proxy:pv-proxy mode 0755). If the write still fails (e.g. read-only /run, which is impossible on tmpfs), error logged WARNING, service continues. |
| T-43-04-05 | Elevation of Privilege | deploy.sh sync overwrites root-owned files | accept | deploy.sh uses rsync which preserves ownership only with `-a` (which it uses). After sync, all files in the release dir are owned by pv-proxy (who the rsync recipient ssh session runs as... wait, it runs as root via ssh). Actually rsync-over-ssh-as-root preserves the SOURCE ownership by default with `-a`. On the dev machine, source ownership is the local user. This has been the existing behavior of deploy.sh and works fine because the post-sync INSTALL block runs chown indirectly via pip install. Not a new threat introduced by Phase 43. |
| T-43-04-06 | Tampering | attacker writes to /var/lib/pv-inverter-proxy/backups | mitigate | Dir is mode 2775 owner root:pv-proxy. Sticky group bit ensures new files inherit pv-proxy group. Only pv-proxy and root can write. pv-proxy is the main service identity — if pv-proxy is compromised, the attacker already has code exec. No new surface. |
| T-43-04-07 | Information Disclosure | state.json readable by anyone | accept | state.json is mode 0644 (from plan 43-01). Contains power limit percentage + timestamp. Not sensitive. No change needed. |
| T-43-04-08 | Repudiation | deploy without Phase 43 migration leaves mixed state | mitigate | deploy.sh comment explicitly documents the expectation. install.sh must be run separately. The verification checkpoint (task 7) surfaces any mismatch. |
| T-43-04-09 | Tampering | symlink race during migration | mitigate | Migration stops the service first (`systemctl stop`), performs the atomic `mv` inside /opt (same filesystem, atomic), creates symlinks via `ln -sfn` (overwrites safely), then restarts the service. No process has a file descriptor open in the moved directory during the move. |
| T-43-04-10 | Denial of Service | service fails to start from new location after migration | mitigate | pip install -e . lands egg-info with absolute paths in the release directory. The systemd ExecStart path goes through the symlink which resolves at exec time. Verified manually in task 7. Rollback procedure documented in the checkpoint. |
</threat_model>

<validation_strategy>
**SAFETY-01 (blue-green layout):** Validated by the checkpoint verification step. `readlink -f /opt/pv-inverter-proxy` shows the full symlink chain. The install.sh migration block is validated by bash syntax check + grep of key migration directives.

**SAFETY-03 (one-time migration):** Validated in two ways:
1. Static: bash syntax check + grep for "MIGRATION REFUSED" banner and dirty-tree check.
2. Dynamic: the actual run in task 6 performs the migration against the live LXC. Running install.sh a second time (or the manual migration block) is a no-op — this is the idempotency gate.

**SAFETY-07 (backups dir):** Validated by the checkpoint step: `stat -c "%a %U %G" /var/lib/pv-inverter-proxy/backups` must show `2775 root pv-proxy`.

**SAFETY-09 (state.json):** Partial validation in this plan: state.json is loaded on boot and logged. The full boot-restoration flow is deferred to Phase 45. The persist-on-change hook is NOT wired in Phase 43 because control.py integration is Phase 45's restart-safety territory. The SAFETY-09 requirement is satisfied at the module+schema+load level for Phase 43; Phase 45 will add the actual SE30K write-back on boot.

**CRITICAL coverage gap acknowledgment:** SAFETY-09 text says "wird bei Boot restauriert wenn now - set_at < CommandTimeout/2" (shall be restored on boot). Phase 43 delivers the LOAD and LOG but not the RESTORE. This is a partial fulfillment. The decision coverage matrix:

| D-XX | Plan | Task | Full/Partial | Notes |
| SAFETY-01 | 43-02, 43-04 | 1, 3 | Full | Helper + install.sh migration + deploy verify |
| SAFETY-02 | 43-02 | 2 | Full | Retention logic in releases.py with tests. Not yet called (Phase 45 calls it). |
| SAFETY-03 | 43-04 | 3 | Full | Migration block with dirty-tree check + verification |
| SAFETY-04 | 43-03 | 2, 3, 4 | Full | Recovery unit + Python entry + tests + deploy |
| SAFETY-05 | 43-03 | 1 | Full | Unit file hardening |
| SAFETY-06 | 43-03, 43-04 | 1, 2 | Full | RuntimeDirectory in unit + healthy flag writer in __main__ |
| SAFETY-07 | 43-04 | 3 | Full | install.sh creates dir with correct perms |
| SAFETY-08 | 43-02 | 2 | Full | check_disk_space in releases.py with tests. Not yet called (Phase 45 calls it). |
| SAFETY-09 | 43-01, 43-04 | all | **PARTIAL** | Module + load on boot + log. BOOT-RESTORE wiring deferred to Phase 45. |

The PARTIAL on SAFETY-09 is a deliberate scope decision, NOT a simplification. The restoration on boot belongs in Phase 45's restart-safety flow, which will also add the save-on-change hook in control.py. Phase 43 delivers the infrastructure (module, schema, load, log) that Phase 45 will consume. This is scope alignment with the phase goal ("No user-visible features — pure infrastructure work"), not scope reduction.

**If the user rejects the partial:** plan 43-04 can be extended with a task that wires the save-on-change hook in control.py. That adds ~1 task of risk with no Phase 43 benefit (nothing in Phase 43 consumes the saved state). Recommended to defer to Phase 45.

**Nyquist validation per task:**
- Task 1: Import smoke test of AppContext with new field
- Task 2: Import and call _write_healthy_flag_once on dev machine (expected to log a warning because /run/pv-inverter-proxy/ doesn't exist locally — that's the test, it must not raise)
- Task 3: bash -n install.sh + grep for migration/refusal/recovery/backups markers
- Task 4: bash -n deploy.sh + grep for Phase 43 comment and recovery unit copy
- Task 5: Full pytest run
- Task 6: Remote LXC verification commands
- Task 7: Human checkpoint covering Venus OS + dashboard + optional reboot test
</validation_strategy>

<rollback_plan>
**If plan 43-04 fails mid-execution:**

1. **Tasks 1-2 (context.py + __main__.py):** Revert via git. Additive changes, safe to drop.
   ```
   git checkout HEAD -- src/pv_inverter_proxy/__main__.py src/pv_inverter_proxy/context.py
   ```

2. **Task 3 (install.sh):** Revert via git. The LXC has not been touched yet.
   ```
   git checkout HEAD -- install.sh
   ```

3. **Task 4 (deploy.sh):** Revert via git. Same reasoning.

4. **Task 6 (deploy + migrate on LXC):** The dangerous step. If migration fails mid-flight, the LXC may be in an inconsistent state. Recovery procedure:
   - If `/opt/pv-inverter-proxy.migrating` exists, rename it back: `mv /opt/pv-inverter-proxy.migrating /opt/pv-inverter-proxy`
   - If both `/opt/pv-inverter-proxy` (symlink) and `/opt/pv-inverter-proxy-releases/` exist but service fails to start, manually reverse:
     ```bash
     systemctl stop pv-inverter-proxy pv-inverter-proxy-recovery
     RELEASE=$(readlink -f /opt/pv-inverter-proxy)
     rm /opt/pv-inverter-proxy /opt/pv-inverter-proxy-releases/current
     mv "$RELEASE" /opt/pv-inverter-proxy
     rm -rf /opt/pv-inverter-proxy-releases
     # Revert unit files to pre-43 version (redeploy from git HEAD~N)
     systemctl daemon-reload
     systemctl disable pv-inverter-proxy-recovery.service
     rm /etc/systemd/system/pv-inverter-proxy-recovery.service
     systemctl start pv-inverter-proxy.service
     ```
   - Full rollback bundle also included in the checkpoint's how-to-verify block.

5. **If Venus OS loses connection post-migration and doesn't recover:** Same rollback procedure. Venus OS will reconnect once the flat layout is restored and the service is back up (Venus OS has `CommandTimeout` tolerance and auto-reconnects Modbus clients).

**Post-rollback state:** LXC is back to Phase 42 (pre-Phase-43). deploy.sh from main branch continues to work. No data loss (all code is in git; config and state are untouched by the migration — they live in `/etc/pv-inverter-proxy/` and `/var/lib/` which the migration doesn't touch).
</rollback_plan>

<verification>
1. `bash -n install.sh` clean
2. `bash -n deploy.sh` clean
3. `python -m pytest tests/ -x -q` all pass
4. `python -c "from pv_inverter_proxy.context import AppContext; assert AppContext().healthy_flag_written is False"` passes
5. `python -c "from pv_inverter_proxy.__main__ import _write_healthy_flag_once, HEALTHY_FLAG_PATH"` imports cleanly
6. On LXC 192.168.3.191 after deploy + manual migration:
   - `readlink -f /opt/pv-inverter-proxy` prints a path under `/opt/pv-inverter-proxy-releases/`
   - `stat -c "%a %U %G" /var/lib/pv-inverter-proxy/backups` prints `2775 root pv-proxy`
   - `systemctl is-active pv-inverter-proxy.service` prints `active`
   - `systemctl is-enabled pv-inverter-proxy-recovery.service` prints `enabled`
   - `curl -sf http://192.168.3.191 >/dev/null` returns 0
   - `test -f /run/pv-inverter-proxy/healthy` (after first successful poll, ~5-10s after restart)
   - `test -f /var/lib/pv-inverter-proxy/last-boot-success.marker`
   - `journalctl -u pv-inverter-proxy.service -n 50 | grep -q healthy_flag_written`
7. Human checkpoint approved: Venus OS still sees the inverter; dashboard still updates live.
</verification>

<success_criteria>
- [ ] context.py has `healthy_flag_written: bool = False` field
- [ ] __main__.py writes healthy flag + last-boot-success marker after first successful poll
- [ ] __main__.py clears stale PENDING marker when writing last-boot-success
- [ ] __main__.py logs persisted state.json contents on boot
- [ ] install.sh migrates flat → blue-green idempotently, refuses on dirty tree
- [ ] install.sh creates /var/lib/pv-inverter-proxy/backups with owner root:pv-proxy mode 2775
- [ ] install.sh copies and enables pv-inverter-proxy-recovery.service
- [ ] deploy.sh copies both unit files and enables recovery (idempotent)
- [ ] deploy.sh documents the blue-green layout expectation
- [ ] Full test suite passes (no regressions)
- [ ] LXC 192.168.3.191 successfully migrated and running from blue-green layout
- [ ] Main service active, webapp reachable, Venus OS still connected
- [ ] /run/pv-inverter-proxy/healthy exists post-first-poll
- [ ] /var/lib/pv-inverter-proxy/last-boot-success.marker exists
- [ ] Recovery service enabled and `inactive (dead)` with `no_pending` outcome
- [ ] User checkpoint approved (no regressions visible in dashboard or Venus OS)
</success_criteria>

<output>
After completion, create `.planning/phases/43-blue-green-layout-boot-recovery/43-04-SUMMARY.md` documenting:
- Final blue-green layout as deployed (full symlink chain from `readlink -f`)
- Migration safety checks used and which passed
- Post-deployment state dir permissions and ownership
- SAFETY-09 partial status: load+log landed, boot-restore deferred to Phase 45 (document the handoff explicitly so Phase 45 planner doesn't have to rediscover)
- Any unexpected issues hit during LXC deployment and how resolved
- Confirmation that Venus OS continued to see the inverter throughout the migration window (with approximate disconnect duration during service stop/start)
- Baseline timing for Phase 44 planning: "migration took X seconds, Venus OS saw Y seconds of Modbus disconnect, dashboard reload took Z seconds" — these are the numbers Phase 45 restart-safety work targets to minimize
</output>
