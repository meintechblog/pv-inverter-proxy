# Stack Research — v8.0 Auto-Update System

**Confidence:** HIGH
**Date:** 2026-04-10

## Executive Verdict

**Zero new Python dependencies required.** Build entirely with existing stack (`aiohttp`, `PyYAML`, `structlog`, `asyncio`) plus stdlib (`subprocess`, `pathlib`, `tempfile`, `shutil`, `hashlib`, `json`, `re`, `tomllib`, `importlib.metadata`).

**Critical decision:** Use **polkit JavaScript rule** (Debian 13 trixie) for privilege escalation. NOT sudoers. NOT a root daemon.

## 1. GitHub Releases API Client

**Library:** `aiohttp.ClientSession` (already present).
**Endpoint:** `https://api.github.com/repos/meintechblog/pv-inverter-master/releases/latest`

**Rate limits:** 60 req/hour unauthenticated per IP. Hourly scheduler + manual clicks will never hit limit.

**Required headers:**
```python
headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "pv-inverter-proxy/8.0 (github.com/meintechblog/pv-inverter-master)",
}
```
`User-Agent` is **required** — missing returns 403.

**ETag caching:** Worth implementing for bandwidth, but 304 still costs 1 req for unauthenticated. Cache to `/etc/pv-inverter-proxy/update-state.json`.

**Timeout:** `aiohttp.ClientTimeout(total=10)`. On failure, log + return None, never crash. UI must stay responsive when GitHub is unreachable.

## 2. Version Comparison

**Decision:** Hand-rolled 15-line `Version(NamedTuple)` parser. Do NOT add `packaging` or `semver`.

**Rationale:**
- Project tags are simple (`v1.0`, `v2.1`, `v8.0`). PEP 440/semver features unused.
- `packaging` is NOT stdlib; transitive-via-pip presence is a silent time-bomb.
- `semver` requires strict 2.0.0 format → would force re-tagging.

**Reference:**
```python
# src/pv_inverter_proxy/updater/version.py
import re
from typing import NamedTuple

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")

class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "Version":
        m = _VERSION_RE.match(raw.strip())
        if not m:
            raise ValueError(f"Unparseable version: {raw!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"
```

Tuple ordering gives `>`, `<`, `==` for free.

**Current version lookup:** `importlib.metadata.version("pv-inverter-master")` — stdlib since 3.8.

## 3. Git Operations: subprocess vs GitPython

**Decision:** `asyncio.create_subprocess_exec` with explicit argv. Do NOT add GitPython.

| Criterion | subprocess | GitPython |
|---|---|---|
| New dep | None | +350KB + gitdb + smmap |
| CVE history | n/a | Multiple (path traversal etc.) |
| Async | Native via asyncio | Blocking; needs to_thread |
| Debuggability | Copy-paste from logs | Opaque wrappers |

**Commands needed:**
```
git -C /opt/pv-inverter-proxy fetch --tags --quiet origin
git -C /opt/pv-inverter-proxy rev-parse HEAD            # save for rollback
git -C /opt/pv-inverter-proxy checkout --quiet tags/v8.1.0
git -C /opt/pv-inverter-proxy checkout --quiet <saved_sha>  # rollback
```

**Safety guards:**
- Always explicit argv, never `shell=True`
- Use `-C $INSTALL_DIR` not `cwd=`
- Before fetch: check `git status --porcelain` is clean; refuse update if local mods detected
- Use `checkout tags/vX.Y` not `git pull` — deterministic, no merge conflicts possible

## 4. Privilege Escalation — CRITICAL

**Decision:** polkit JavaScript rule (Debian 13 trixie) scoped to the specific unit.

**Why newly viable:** Debian 12 shipped old polkit (`.pkla` files, no per-unit filtering). **Debian 13 trixie ships modern polkit with JS `.rules` files** that support per-unit scoping. This removes the historical blocker that forced projects to sudoers.

**Rule:**
```javascript
// /etc/polkit-1/rules.d/50-pv-inverter-proxy.rules
polkit.addRule(function(action, subject) {
    if (subject.user !== "pv-proxy") return polkit.Result.NOT_HANDLED;
    var unit = action.lookup("unit");
    if (unit !== "pv-inverter-proxy.service") return polkit.Result.NOT_HANDLED;
    if (action.id === "org.freedesktop.systemd1.manage-units") {
        return polkit.Result.YES;
    }
    return polkit.Result.NOT_HANDLED;
});
```

Grants `pv-proxy` the ability to `systemctl restart pv-inverter-proxy.service` without password or sudo. polkit logs every authorization decision to journal — fully auditable.

**Trade-off table:**

| Option | Security | Install | Verdict |
|---|---|---|---|
| **polkit JS rule** | Excellent — unit-scoped, user-scoped | Drop 1 file, reload polkit | **CHOSEN** |
| sudoers NOPASSWD | Good if scoped via Cmnd_Alias | Drop 1 file | Fallback for Debian 12 |
| Privileged sidecar daemon | Poor — larger attack surface | Second systemd unit + IPC | Rejected |
| Run proxy as root | Terrible | Undoes existing hardening | Rejected |

**Sudoers fallback (Debian 12 detection):**
```
pv-proxy ALL=(root) NOPASSWD: /bin/systemctl restart pv-inverter-proxy.service
pv-proxy ALL=(root) NOPASSWD: /bin/systemctl is-active pv-inverter-proxy.service
Defaults!/bin/systemctl !requiretty
```

**systemd hardening note:** Existing unit has `NoNewPrivileges=true`. This is fine for polkit (invoked via D-Bus IPC, not setuid fork) but would block direct sudo fork — another reason to prefer polkit.

## 5. Self-Restart Pattern

**Problem:** Calling `systemctl restart` from inside the service kills the caller mid-operation.

**Solution:** `systemd-run --on-active=2s` transient unit fires restart from outside the dying cgroup.

```python
await asyncio.create_subprocess_exec(
    "systemd-run", "--on-active=2s",
    "--unit=pv-inverter-proxy-restart",
    "/bin/systemctl", "restart", "pv-inverter-proxy.service",
)
# Respond HTTP 202 immediately, let the client poll
```

Same polkit rule covers the systemd-run invocation. No extra package needed.

## 6. Health Check Mechanism

**Decision:** Client-browser-polled health endpoint + server-side watchdog oneshot. NOT self-reporting from inside the new version.

**Why not self-report:** If new version crashes on startup, it can't report failure.

**Flow:**
1. UI POST `/api/update/apply` → server does git checkout + pip install + saves old_sha + queues systemd-run restart → responds HTTP 202 `{ state: "restarting", old_sha, deadline_ts }`
2. Server dies, systemd restarts with new code
3. Client polls `GET /api/update/status` every 2s
4. New version on boot: runs self-checks, writes `state: "healthy"` to `/etc/pv-inverter-proxy/update-state.json`
5. Client sees healthy → success toast
6. If deadline reached (60s) without healthy → client calls `POST /api/update/rollback`

**Server-side watchdog (for catastrophic failure where webapp doesn't come up):**
```
systemd-run --on-active=90s --unit=pv-inverter-proxy-healthcheck \
    /opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy.updater.healthcheck
```

Healthcheck module (~80 LOC): curls `http://localhost/api/health`, on failure does `git checkout <old_sha>` + restart.

**Health signals:**
- REQUIRED: process up, Modbus server bound, ≥1 device producing frames
- OPTIONAL (warn-only): MQTT connected (may take longer to reconnect)

## 7. Background Scheduler

**Decision:** `asyncio.create_task` loop in existing event loop. NOT a systemd timer.

**Rationale:** Event loop already exists, matches prior art (EDPC refresh, MQTT reconnect, device polling), ~60 LOC.

```python
class UpdateCheckScheduler:
    async def _loop(self):
        await asyncio.sleep(60)  # Initial delay
        while True:
            try:
                await self._checker.check_and_cache()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("update_check_failed", error=str(exc))
            await asyncio.sleep(self._interval)
```

**Config (defaults):**
```yaml
update:
  auto_check_enabled: true
  check_interval_seconds: 3600
  github_repo: "meintechblog/pv-inverter-master"
```

**Hot-reload:** Follow existing VenusConfig pattern — cancel old task, start new loop on config change.

## 8. Summary: Dependency Impact

**New runtime dependencies: ZERO.**

| Need | Solution | Source |
|---|---|---|
| HTTP to GitHub | `aiohttp.ClientSession` | existing |
| JSON | `json` | stdlib |
| Version compare | `NamedTuple` (~15 LOC) | new code, zero deps |
| Git ops | `asyncio.create_subprocess_exec` | stdlib |
| Privilege | polkit JS rule + `systemctl` via `systemd-run` | system config |
| Restart-self | `systemd-run --on-active=2s` | system tool |
| Scheduler | `asyncio.create_task` | stdlib |
| State persistence | `json` → update-state.json | stdlib |
| Version lookup | `importlib.metadata.version` | stdlib |
| Config | existing `PyYAML` | existing |
| Logging | existing `structlog` | existing |
| Healthcheck client (standalone) | `urllib.request` | stdlib |

**Explicitly rejected:**
- GitPython (350KB, CVEs, blocking)
- packaging (not stdlib, transitive time-bomb)
- semver (strict format incompatible with project tags)
- httpx/requests (aiohttp already present)
- APScheduler (asyncio task replaces)
- Privileged sidecar daemon (IPC complexity, attack surface)

## 9. Files to Add (v8.0 scope)

```
src/pv_inverter_proxy/updater/
    __init__.py
    github_client.py       # aiohttp wrapper + ETag cache (~80 LOC)
    version.py             # NamedTuple parser (~30 LOC)
    git_ops.py             # async subprocess wrappers (~100 LOC)
    scheduler.py           # asyncio task loop (~60 LOC)
    orchestrator.py        # update flow state machine (~150 LOC)
    healthcheck.py         # standalone rollback watchdog script (~80 LOC)
    state.py               # update-state.json read/write (~40 LOC)

# Webapp route additions in webapp.py: /api/update/* (~120 LOC)

# System config:
config/polkit/50-pv-inverter-proxy.rules  # new file

# Modifications:
install.sh                 # + polkit rule install step
pyproject.toml             # no change — zero new deps
config/pv-inverter-proxy.service  # no change
```

**Estimated total:** ~660 LOC Python + 1 polkit rules file.

## 10. Integration Points

- **Scheduler task** joins existing task group in `__main__.py run()` alongside device_polling, modbus_server, webapp, mqtt_loop
- **Version cache** at `/etc/pv-inverter-proxy/update-state.json` — same dir as existing writable paths (`ReadWritePaths=/etc/pv-inverter-proxy`). No systemd unit changes.
- **Webapp routes** in `webapp.py` following existing REST patterns
- **structlog events:** `update_check_started`, `update_available`, `update_apply_initiated`, `git_checkout_complete`, `restart_queued`, `health_check_passed`, `rollback_initiated`
- **WebSocket snapshot extension:** add `available_update: { version, published_at, release_notes_url } | null` to existing snapshot (matches "extend snapshot, not protocol" decision)

## 11. Open Questions for REQUIREMENTS.md

1. **Health definition:** Process up + Modbus bound + ≥1 device producing = required. MQTT = warn-only. Confirm.
2. **Tag selection:** v8.0 UI shows only `latest` release, but internal API accepts any tag for manual pinning. Confirm.
3. **pip install failure mode:** timeout + capture output + immediate rollback before restart.
4. **Config migration:** Continue existing pattern (code tolerates missing fields with defaults). Updater never touches config.yaml.
5. **Power-limit race:** During restart, EDPC refresh pauses → SolarEdge CommandTimeout auto-reverts to full power. Document as "brief return to full power during updates, typically <10s".

## Sources

- GitHub: Rate limits for the REST API (docs.github.com)
- GitHub Changelog: Updated rate limits for unauthenticated requests (May 2025)
- polkit(8) / polkitd — Debian trixie manpage
- PolicyKit — Debian Wiki
- Polkit — ArchWiki (JS rule reference)
- packaging library — PyPA docs
