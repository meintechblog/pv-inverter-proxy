# Architecture Research — v8.0 Auto-Update System

**Confidence:** HIGH
**Date:** 2026-04-10

## Executive Summary

**Two-process pattern with path-unit-triggered root helper.**

- Main service (`pv-inverter-proxy.service`, user `pv-proxy`) handles UI, version checks, scheduler, status broadcasting — never gains privileges.
- New privileged helper (`pv-inverter-proxy-updater.service`, root, `Type=oneshot`) performs git/pip/restart — triggered via systemd path unit watching a trigger file.
- Trust boundary is explicit in the filesystem: `updater/` package is pv-proxy code; `updater_root_impl/` package is root-only code. Nothing in main service imports from `updater_root_impl/`.

**Critical decision: polkit is NOT viable.** The stack research's polkit recommendation is blocked by systemd issue #22055: polkit's `org.freedesktop.systemd1.manage-units` requires an active logind session, which `pv-proxy` (a `useradd -r -s /usr/sbin/nologin` system user) never has. Path-unit + root helper is the correct pattern.

## Privilege Model — Path-Unit Triggered Root Helper

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ User Browser → HTTP + WebSocket (port 80)                           │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ pv-inverter-proxy.service  [User=pv-proxy, NoNewPrivileges=true]    │
│                                                                       │
│  aiohttp webapp                                                      │
│   ├─ /api/update/available   (reads AppContext.update_available)    │
│   ├─ /api/update/start       (POST → trigger.write() → 202)         │
│   ├─ /api/update/status      (reads update-status.json)             │
│   └─ /api/health             ({version, status, components})       │
│                                                                       │
│  Background asyncio tasks                                            │
│   └─ update_scheduler               [polls GitHub every 1h]          │
│                                                                       │
│  AppContext (extended)                                               │
│   ├─ update_available: {tag, sha, body, published_at}               │
│   └─ update_status:    {phase, progress, started_at, target}        │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ atomic file write
                       ▼
      /etc/pv-inverter-proxy/update-trigger.json
                       │ (PathModified=)
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ pv-inverter-proxy-updater.path  (watches trigger file)              │
│              │ activates                                             │
│              ▼                                                       │
│ pv-inverter-proxy-updater.service  [Type=oneshot, User=root]        │
│                                                                       │
│  1. Read trigger JSON, validate nonce/SHA reachability              │
│  2. Backup: tarball .venv, copy config.yaml                         │
│  3. git fetch origin; verify target SHA is ancestor of origin/main  │
│  4. git reset --hard <target_sha>                                   │
│  5. .venv/bin/pip install -e .                                      │
│  6. Dry-run config load against new code                           │
│  7. systemctl restart pv-inverter-proxy.service                    │
│  8. Poll /api/health + /run/pv-inverter-proxy/healthy (60s max)    │
│  9. On failure: git reset --hard <old_sha>, restore venv, restart  │
│ 10. Write phase=done (or rollback_done/failed) to status file       │
└─────────────────────────────────────────────────────────────────────┘
```

### Why This Beats Polkit

| Option | Verdict | Why |
|---|---|---|
| Polkit JS rule | **REJECTED** | `pv-proxy` is nologin → no session → polkit always denies. Verified: systemd issue #22055. |
| Sudoers NOPASSWD | Fallback only | Conflicts with `NoNewPrivileges=true`; entangles Python with sudo quoting; argv-based state passing is messy. |
| Path-unit + root helper | **CHOSEN** | Zero polkit headaches. Main service writes a JSON file → separate root service picks it up. Survives main-service restart. Clean audit trail via `journalctl -u pv-inverter-proxy-updater`. |
| Main service as root | Rejected | Undoes existing `NoNewPrivileges=true` + `ProtectSystem=strict` hardening. |

### Trigger File Contract (v1)

```json
{
  "op": "update" | "rollback",
  "target_sha": "abc123...",
  "requested_at": "2026-04-10T14:22:00Z",
  "requested_by": "webapp",
  "nonce": "uuid4"
}
```

- `nonce` enables idempotency — updater persists processed nonces in `/var/lib/pv-inverter-proxy/processed-nonces.json` (last 50)
- Main service writes atomically: `tempfile.NamedTemporaryFile` + `os.replace`
- Updater validates: schema, nonce unseen, `target_sha` reachable from `refs/remotes/origin/main` via `git merge-base --is-ancestor`
- **Security root of trust:** only SHAs reachable from origin/main are acceptable. Prevents compromised pv-proxy from installing arbitrary code.

### systemd Units

```ini
# /etc/systemd/system/pv-inverter-proxy-updater.path
[Unit]
Description=Watch for pv-inverter-proxy update triggers

[Path]
PathModified=/etc/pv-inverter-proxy/update-trigger.json
Unit=pv-inverter-proxy-updater.service

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/pv-inverter-proxy-updater.service
[Unit]
Description=PV-Inverter-Proxy Privileged Updater
After=network-online.target

[Service]
Type=oneshot
User=root
Group=root
ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy.updater_root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pv-inverter-proxy-updater
```

## Self-Restart Without Deadlock

**Pattern: Fire-and-forget + async status polling.**

1. `POST /api/update/start` → write trigger file → respond HTTP 202 with `{update_id, status_url}` (~50ms, user sees no failure)
2. `systemctl restart` issued by the **updater**, not the main service — no deadlock
3. Main service dies via SIGTERM like normal; systemd restarts new code
4. Frontend polls `/api/update/status` every 1s — state is in a file, not in-memory, so reconnect works

**Rejected alternatives:**
- `systemd-run --on-active=5s` from main service — requires privilege, defeats the point
- Detached subprocess inside main service — orphaned child when parent dies

## Health Check After Restart

**Both mechanisms combined.** Updater is authoritative for rollback decisions.

### Sequence

```
t=0s    updater: systemctl restart pv-inverter-proxy.service
t=0-3s  updater: systemctl is-active --wait (max 30s)
t=3s    updater: poll http://127.0.0.1:80/api/health every 1s
t=Xs    main service startup: DeviceRegistry completes ≥1 poll
                               → write /run/pv-inverter-proxy/healthy (tmpfs)
                               → /api/health returns {status: "ok", version: "8.0.0"}
t=X+1s  updater sees 200 + correct version
        verifies 3 consecutive ok polls over 5s (stability)
t=X+6s  updater writes phase=done
```

### Rollback Triggers

- **Hard timeout: 60s** without confirmed healthy → rollback
- `systemctl is-active` returns `failed` → immediate rollback
- Version mismatch in `/api/health` → rollback (catches partial install)
- 5xx or unreachable for > 45s → rollback
- No `/run/pv-inverter-proxy/healthy` after 45s → rollback

### Health Endpoint Schema

```json
{
  "status": "ok" | "starting" | "degraded",
  "version": "8.0.0",
  "commit": "def5678",
  "uptime_seconds": 12,
  "webapp": "ok",
  "modbus_server": "ok",
  "devices": {"se30k": "ok"},
  "venus_os": "ok" | "disabled"
}
```

**Use `/run/pv-inverter-proxy/` (tmpfs)**, not `/var/run/`. Add `RuntimeDirectory=pv-inverter-proxy` to main service unit — systemd creates the dir on every start with correct ownership.

## Rollback Mechanism — Git SHA + Tarball (Belt & Braces)

**Before update:**
1. Record `git rev-parse HEAD` → saved in update-status.json
2. Snapshot `.venv/` → `/var/lib/pv-inverter-proxy/backups/venv-<timestamp>.tar.gz`
3. Snapshot `pyproject.toml` for integrity check

**On rollback:**
1. `git reset --hard <old_sha>`
2. `pip install -e .` (re-pin to old pyproject.toml)
3. `systemctl restart`
4. Health-check the rolled-back version
5. If rollback itself fails → write phase=`rollback_failed`, loud journal error, user must SSH

**Retention:** Keep last 3 snapshots (~1-5 MB each). Store in `/var/lib/pv-inverter-proxy/backups/` — **NOT** in `/opt/pv-inverter-proxy` (would be wiped by git reset).

## Module Layout

```
src/pv_inverter_proxy/updater/              # pv-proxy code
    __init__.py
    github_client.py       # aiohttp wrapper + ETag cache
    version.py             # Version parsing + current lookup
    trigger.py             # Atomic trigger file write
    status.py              # Read/watch update-status.json
    scheduler.py           # asyncio background check
    webapp_routes.py       # REST + WebSocket routes

src/pv_inverter_proxy/updater_root.py        # Root entry point
src/pv_inverter_proxy/updater_root_impl/     # Root-only package
    __init__.py
    runner.py              # Orchestrator state machine
    git_ops.py             # git subprocess wrappers
    backup.py              # Tarball snapshots + retention
    healthcheck.py         # /api/health poller + rollback
```

**Trust boundary is filesystem-enforced:** nothing in `webapp.py` or `updater/` imports from `updater_root_impl/`. A reviewer can grep to verify.

## Modified Existing Files

| File | Change |
|---|---|
| `webapp.py` | Register update routes; extend `/api/health` with version field; pre-shutdown "reconnect_soon" WS broadcast |
| `__main__.py` | Add `updater_task = asyncio.create_task(run_update_scheduler(app_ctx))` in startup; cancel in shutdown |
| `context.py` | Add `update_available`, `update_status`, `update_check_task`, `healthy_flag_written` fields |
| `pyproject.toml` | Bump version to `"8.0.0"` |
| `config/pv-inverter-proxy.service` | Add `RuntimeDirectory=pv-inverter-proxy`; raise `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15` |
| `install.sh` | Install new `.service` + `.path` units; create `/var/lib/pv-inverter-proxy/backups` |

## Version Source of Truth

**Primary:** `importlib.metadata.version("pv-inverter-master")` — reads from installed package metadata (via pyproject.toml).
**Augmented:** `git rev-parse --short HEAD` appended for display (`"8.0.0 (def5678)"`).
**Updates:** reported via `/api/health`, `/api/status`, `/api/update/version`.

**GitHub side:** `GET https://api.github.com/repos/meintechblog/pv-inverter-master/releases/latest` → parse `tag_name`. ETag caching, unauthenticated, 60 req/hr plenty for hourly checks.

## State During Update — Graceful Shutdown Pattern

Rely on existing `__main__.py` SIGTERM handling — do not invent new shutdown path. Add:

1. **Pre-shutdown WebSocket broadcast:** "reconnect_soon" message so browser dashboards show "Update in progress — reconnecting in ~10s" banner instead of raw disconnect.
2. **Modbus writes handled by existing EDPC Refresh Loop:** after restart, Venus OS re-issues power limit within 30s. The 3-5s gap is invisible to user because Venus OS tolerates momentary disconnects (CommandTimeout exists for this).
3. **Polling pause flag:** set `app_ctx.polling_paused = True` for 500ms before trigger write to let in-flight polls complete.

## Config Schema Evolution

**Critical prerequisite:** v7.x config loader must tolerate unknown keys. Verify `src/pv_inverter_proxy/config.py` — if it crashes on unknown keys, ship **v7.1.x compat prep release** BEFORE v8.0 that adds tolerance. This unblocks rollback from v8.0 to v7.1.

**Rules:**
1. Forward-only additive changes in v8.0 — no renames, no removals
2. New fields default to sensible values when absent
3. Pre-update dry-run: updater runs `python -c "from pv_inverter_proxy.config import load_config; load_config(...)"` against the NEW code before restarting. If fails, abort before restart.
4. Backup config.yaml to `/var/lib/pv-inverter-proxy/backups/config-<timestamp>.yaml` before every update

## Build Order — 4 Phases (MVP = Phases 1-3)

### Phase 1: Passive Version Badge (no actual updates)

**Goal:** User sees "Update 8.1.0 available" badge in UI. Clicking does nothing yet.

- `updater/version.py`, `updater/github_client.py`, `updater/scheduler.py`
- Add `version` field to `/api/health`
- New endpoint `GET /api/update/available`
- WebSocket broadcast on update available
- Frontend: version in footer, sidebar badge
- Config: `updater: { enabled, check_interval_hours, channel }`

**Dependencies:** None — fully reversible, no privilege escalation.
**Ship test:** Tag a v8.0.1 release → webapp shows badge within 1h.

### Phase 2: Privileged Updater Service (no UI wiring)

**Goal:** CLI test — writing trigger file triggers git pull + restart.

- New `.service` + `.path` units
- `updater_root.py` + `updater_root_impl/runner.py`
- `git_ops.py` with SHA reachability validation
- `backup.py` (venv tarball + config copy + retention)
- `healthcheck.py` poller
- Add `RuntimeDirectory=pv-inverter-proxy` to main unit; write healthy flag
- `install.sh`: install units, create backup dir

**Ship test:** Manually write trigger file → service updates itself → verify success. Then corrupt code, trigger rollback, verify recovery.

### Phase 3: UI Wiring + End-to-End Flow

**Goal:** User clicks "Update" in webapp, completes successfully.

- `updater/trigger.py`, `updater/status.py`, `updater/webapp_routes.py`
- 4 new REST routes: `/api/update/start`, `/status`, `/rollback`, `/history`
- WebSocket phase-transition broadcasts
- Pre-shutdown "reconnect_soon"
- Frontend: `#update` page with check/install/progress/rollback/history
- Pre-update config compat dry-run

**Ship test:** End-to-end update from 8.0.0-rc1 → 8.0.0-rc2, observe no HTTP error, restart transparent to Venus OS.

### Phase 4: Polish + Hardening

- Scheduler UI toggle + interval config
- Pre-release/beta channel support (filter by prerelease flag)
- Failed-update diagnostics page (journal tail for updater service)
- Rate limiting (max 1 update per 5min)
- Concurrent update guard (HTTP 409 if already in progress)
- Optional GPG signature verification on tags

## Critical Integration Points

1. **`__main__.py` line 216:** register `update_scheduler` asyncio task alongside `_health_heartbeat`. Existing "Cancel periodic tasks" block handles cancellation.
2. **`webapp.py` line 2039:** add `register_update_routes(app)` call before `return runner`.
3. **`webapp.py` health_handler:** extend response with version + component status. Write `/run/pv-inverter-proxy/healthy` first time all conditions met.
4. **`context.py`:** 4 new AppContext fields, all default to None/False.
5. **`config/pv-inverter-proxy.service`:** single line addition `RuntimeDirectory=pv-inverter-proxy` + StartLimit tuning.
6. **`install.sh`:** install updater unit files + create `/var/lib/pv-inverter-proxy/backups` with `install -d -o root -g pv-proxy -m 2775`.

## Key Patterns

### Pattern 1: Atomic Trigger File Write

```python
def write_trigger(payload: dict) -> None:
    target = Path("/etc/pv-inverter-proxy/update-trigger.json")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, target)  # atomic on POSIX
```

### Pattern 2: Phase-Based Status with Monotonic Progression

```json
{
  "current": {
    "nonce": "abc-123",
    "phase": "healthcheck",
    "target_sha": "def456",
    "old_sha": "abc123",
    "started_at": "2026-04-10T14:22:00Z"
  },
  "history": [
    {"phase": "trigger_received", "at": "..."},
    {"phase": "backup", "at": "..."},
    {"phase": "git_reset", "at": "..."},
    {"phase": "pip_install", "at": "..."},
    {"phase": "config_dryrun", "at": "..."},
    {"phase": "restarting", "at": "..."},
    {"phase": "healthcheck", "at": "..."}
  ]
}
```

### Pattern 3: Readable-by-Main, Writable-by-Root-Only

- Status file: mode 0644 (world-readable, root-writable)
- Trigger file: mode 0664, owned by `root:pv-proxy`
- One-way trust channel: pv-proxy requests, only root reports

## Anti-Patterns to Avoid

1. **`subprocess.Popen(["sudo", ...])` from main service** — conflicts with NoNewPrivileges, messy, no audit trail. Use file trigger instead.
2. **`os.execv()` or SIGTERM self-restart** — new process inherits old state (env, open fds, references to upgraded packages in memory). Let systemd restart.
3. **Keeping HTTP connection open during restart** — user sees connection lost = interpreted as failure. Return 202 immediately, poll status separately.
4. **Rolling back by re-running installer** — non-deterministic (network, package mirrors). Rollback must succeed even if network is down. Local git + local tarball only.
5. **Trusting GitHub API response as authoritative for what to install** — DNS hijack / compromised account vector. Validate target_sha against `refs/remotes/origin/main` locally. Main branch history is the trust root.

## Open Questions for Roadmapper

1. **Update channel:** `prerelease` flag on GitHub Releases? Phase 4 work.
2. **Trigger file ownership race:** `/etc/pv-inverter-proxy/` is pv-proxy-owned. Update-status.json should be root-writable only — needs file-specific chmod/chown.
3. **Restart of updater itself:** if path unit fires twice while updater still running, `Type=oneshot + RemainAfterExit=no` queues correctly. Document in phase 2 ship test.

## Sources

- systemd issue #22055 — polkit requires active session (BLOCKS polkit approach)
- freedesktop.org: systemd.path(5) manual
- ArchWiki: Polkit rule syntax for systemctl
- Existing codebase: `__main__.py`, `context.py`, `webapp.py`, `config/pv-inverter-proxy.service`, `install.sh`, `pyproject.toml`
