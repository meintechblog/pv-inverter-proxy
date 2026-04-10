# Pitfalls Research — v8.0 Auto-Update System

**Confidence:** HIGH
**Date:** 2026-04-10

## Severity Legend

- **BLOCKING** — must be solved before v8.0 ships; failure = lockout or data corruption
- **HIGH** — should solve in v8.0; real reliability issue
- **MEDIUM** — handle opportunistically or defer to v8.1
- **LOW** — document only

## Phase Tag Legend

- P1-Layout, P2-Helper, P3-Pipeline, P4-Restart, P5-UI, P6-Safety

---

## BLOCKING

### C1. Bad Commit Lockout via systemd StartLimit

**Phase:** P1-Layout, P4-Restart

**What goes wrong:** systemd default is `StartLimitBurst=5` in `StartLimitIntervalSec=10s`. A bad update crashing on import will be restarted 5 times, then systemd marks unit `failed`. Webapp gone = user locked out (no SSH = physical access needed).

**Prevention:**
1. **Blue-green directory layout** — never mutate running code tree:
   ```
   /opt/pv-inverter-proxy/             # symlink → releases/current
   /opt/pv-inverter-proxy-releases/
     ├── v7.0-abc1234/                 # full checkout + .venv
     ├── v8.0-def5678/                 # full checkout + .venv
     └── current -> v8.0-def5678       # atomic symlink swap
   ```
   Rollback = symlink flip + restart. Zero git operations at rollback time.
2. **Out-of-process watchdog** — updater helper survives main service restart and decides rollback, not the webapp itself.
3. **Unit hardening:** `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15`.
4. **Boot-time recovery hook** — separate `pv-proxy-recovery.service` (Type=oneshot, before main service) reads PENDING marker; if last boot ended without SUCCESS marker, flips symlink back.

### C2. Privileged Helper Single Point of Failure

**Phase:** P2-Helper, P6-Safety

**What goes wrong:** If helper crashes, is masked, or is stopped, the webapp silently can't update. Users click "Update" forever seeing "in progress" that never completes.

**Prevention:**
1. **Dedicated root helper: `pv-inverter-proxy-updater.service`** (Type=oneshot, RemainAfterExit=no) triggered via `.path` unit watching `/etc/pv-inverter-proxy/update-trigger.json`.
2. **Helper heartbeat endpoint** — main service writes `ping` trigger every 60s; helper responds. If no response in 3min, UI shows red banner: "Auto-Update helper not responding — SSH required."
3. **Install-time smoke test** — installer runs helper with `--self-test` to confirm end-to-end plumbing before enabling.
4. **Never use sudo, polkit, or runtime capabilities** — see ARCHITECTURE.md for rationale (polkit requires logind session which nologin pv-proxy user doesn't have).

### C3. Modbus Write In-Flight During Restart

**Phase:** P4-Restart, P6-Safety

**What goes wrong:** Venus OS polls every ~2s, issues writes (power limit, EDPC refresh every 30s). Killing mid-write → TCP reset → Venus OS logs "override failed". Worse: SolarEdge may hold stale limit past CommandTimeout, violating user intent.

**Prevention:**
1. **Pre-shutdown maintenance mode:**
   - Set `app_ctx.maintenance_mode = True`
   - Modbus server returns `SlaveBusy` (exception 0x06) for writes; reads continue from cache
   - Wait 3s (> one Venus OS poll cycle, < user patience)
   - Stop poller, drain in-flight pymodbus transactions (`asyncio.wait_for(drain(), 2.0)`)
   - THEN trigger restart
2. **Preserve SE30K last-set limit across restart** — write `{limit_pct, set_at}` to `/etc/pv-inverter-proxy/state.json`. On boot, restore if `now - set_at < CommandTimeout/2`.
3. **`KillMode=mixed, TimeoutStopSec=15`** — SIGTERM first, asyncio shutdown hooks run, SIGKILL only if needed.

### C4. Dependency Install Failure Leaves Half-Updated System

**Phase:** P3-Pipeline, P4-Restart

**What goes wrong:** v8.0 adds new dep; pip download fails mid-install (network, disk, missing libffi-dev). New code in place importing uninstalled lib. Restart → ImportError → StartLimit → lockout.

**Prevention:**
1. **Isolated .venv per release dir** — new venv installed while old venv still serves traffic. Failure doesn't touch the running system.
2. **Pre-flight `pip install --dry-run`** — verify all deps obtainable BEFORE touching real venv.
3. **Post-install smoke import** — `new_venv/bin/python -c "import pv_inverter_proxy; startup_selfcheck()"` before restart. Failure → abort, don't restart, don't swap symlink.
4. **NEVER run `pip install` against currently-running venv.**

### C5. LAN Webapp = Arbitrary Code Execution Surface

**Phase:** P2-Helper, P5-UI, P6-Safety

**What goes wrong:** No auth today. Adding "Update to latest from GitHub" button means any LAN device can install arbitrary code. Attack vectors:
1. Compromised IoT device (TV, printer, vulnerable inverter firmware) POSTs to `/api/update`
2. GitHub account compromise → malicious release pulled worldwide
3. CSRF from browser tab on malicious site
4. MITM on git fetch

**Prevention:**
1. **Pin updates to tagged GitHub Releases, not `main`** — scheduler polls `/repos/.../releases/latest`, only annotated tags count. Main branch auto-install explicitly rejected.
2. **Verify release asset checksum** — each release uploads `SHA256SUMS`, helper verifies before extract.
3. **Optional GPG verification** — `SHA256SUMS.asc` signed by maintainer key. Config `updates.allow_unsigned: false` (default).
4. **Rate limit** — max 1 update per 60s.
5. **CSRF token on update endpoint** — defeats drive-by browser attacks.
6. **Audit log** — every update request logged with requesting IP, UA, timestamp.
7. **Never auto-install unreleased commits** — manual SHA-install flow requires confirmation token typed from SSH/journal.

---

## HIGH

### H1. File Permission Drift on Re-Install

**Phase:** P2-Helper, P3-Pipeline

**Prevention:**
1. Helper runs as root but wraps file-touching commands: `sudo -u pv-proxy -- git ...`, `sudo -u pv-proxy -- pip ...`. Only `systemctl restart` and symlink swap run as root.
2. After extraction, explicit `chown -R pv-proxy:pv-proxy <release_dir>`.
3. Pre-compile pyc at install time: `python -m compileall -q <release_dir>/src`. Eliminates runtime pyc writes (which `ProtectSystem=strict` blocks anyway).
4. Post-install assertion: walk `.venv/`, fail if any file not owned by pv-proxy.

### H2. Partial Download / Network Failure Corrupts Tree

**Phase:** P2-GitOps, P3-Pipeline

**Prevention:**
1. **Download-to-temp, verify, then move:**
   ```
   /tmp/pv-updater-<uuid>/release.tar.gz
   /tmp/pv-updater-<uuid>/SHA256SUMS
   sha256sum -c SHA256SUMS
   tar xzf release.tar.gz -C /opt/pv-inverter-proxy-releases/v8.0-def5678/
   ```
2. **Explicit `Content-Length` check** against downloaded bytes.
3. **GitHub API defensive parsing** — verify `tag_name`, `tarball_url`, `assets` fields present; reject if `message` field set (GitHub error envelope).
4. **Don't use `git fetch` at update time** — only initial install uses git. Updates use Releases tarballs. Eliminates git-state corruption class.
5. Optional GitHub PAT for 5000/hr rate limit (vs 60/hr unauth).

### H3. Python Cache / Socket Reuse / Async Shutdown

**Phase:** P4-Restart

**Prevention:**
1. Isolated `__pycache__/` per release dir (blue-green solves automatically).
2. Rollback explicitly: `find <old_release>/src -name '__pycache__' -exec rm -rf {} +`, then recompile.
3. Verify pymodbus server binds with `SO_REUSEADDR` (grep codebase, add if missing).
4. SIGTERM handler → `asyncio.get_event_loop().create_task(graceful_shutdown())`.
5. `TimeoutStopSec=15` gives asyncio time to drain.

### H4. Config Schema Forward/Backward Compatibility — CRITICAL PREREQ

**Phase:** P6-Safety, P4-Restart

**What goes wrong:** v8.0 adds `updates:` section. User enables auto-updates. v8.0 bug → rollback to v7.1. v7.1's strict dataclass loader raises `TypeError: unexpected keyword argument 'updates'`. Service won't start. **Rollback itself triggers lockout.**

**Prevention:**
1. **Config loader MUST tolerate unknown keys.** Verify `src/pv_inverter_proxy/config.py` — if it crashes on unknown keys, ship **v7.1.x compat prep release** BEFORE v8.0 that adds tolerance. Users must upgrade to v7.1.x before v8.0. This is effectively a v8.0 prerequisite.
2. **`config_version: N` field** at top of config.yaml. Loader warns if > supported, errors if < min.
3. **Config auto-backup on update** — `config-<version>-<timestamp>.yaml.bak`. Rollback restores matching backup.
4. **Config migrations in code** — forward migration on startup. Inverse migration or backup restore on rollback.
5. **Rule:** never REMOVE a config field without 2 releases deprecation. Never REQUIRE a new field without a default.

### H5. Health Check Must Cover Modbus Layer

**Phase:** P4-Restart

**What goes wrong:** Tempting: `/api/health` returns 200 if webapp is up. But poller crash doesn't crash webapp → health returns ok → helper declares success → broken update stays. Silent bad update.

**Prevention:**
1. **Rich `/api/health`:**
   ```json
   {
     "webapp": "ok",
     "version": "8.0.0",
     "commit": "def5678",
     "modbus_server": "ok",
     "devices": {"se30k": "ok"},
     "venus_os": "ok",
     "uptime_s": 42
   }
   ```
   Any component ≠ "ok" → degraded → helper counts as failure.
2. **Distinguish startup vs steady-state** — first 30s returns `starting`, not failure. Helper timeout 90s for full startup.
3. **N successful reads before declaring success** — 3 consecutive ok over 15s.
4. **Rollback on any single failed** — better false-positive than leaving broken release.
5. Include `version` + `commit` so helper asserts it's reading the NEW process.

### H6. Scheduler Races User-Initiated Update

**Phase:** P5-UI, P6-Safety

**Prevention:**
1. **Singleton lock file** — `flock(LOCK_EX|LOCK_NB)` on `/run/pv-inverter-proxy-updater/lock`. Second attempt returns `update_in_progress`.
2. **Webapp state machine** — states: `idle|checking|downloading|installing|restarting|verifying|success|failed|rolled_back`. UI disables buttons when state ≠ idle.
3. **Scheduler defers when user is active** — if WebSocket client connected, postpone auto-check by 1h.
4. **Auto-install default OFF** — scheduler only surfaces badge, user clicks Install. Opt-in toggle `updates.auto_install: false`.

### H7. Git Working Tree Dirty on First Upgrade

**Phase:** P1-Layout

**What goes wrong:** User edited a file in `/opt/pv-inverter-proxy/` on LXC. Next update `git reset --hard` silently obliterates it, or `git pull` fails with conflict.

**Prevention:**
1. **One-time migration on first v8.0 run** — detect old layout (no symlink), check `git status --porcelain`. If dirty, refuse migration with clear banner showing diff. Otherwise copy tree to release dir, create symlink, verify, remove old dir.
2. Document migration in v8.0 release notes.

### H8. Disk Space Exhaustion Mid-Install

**Phase:** P6-Safety

**Prevention:**
1. **Pre-flight `df`** — verify ≥500 MB free on /opt and /var/cache before download.
2. **Retention policy** — keep max 3 release dirs (configurable `updates.keep_releases: 3`). On successful update, delete Nth-oldest (not current, not previous).
3. **`PIP_CACHE_DIR=/var/cache/pv-proxy/pip`** — outside venv, shared across releases.
4. **Emergency cleanup mode** — if < 200MB free, offer to delete all non-current releases + pip cache as pre-update recovery.

---

## MEDIUM

### M1. Rollback Infinite Loop

**Phase:** P4-Restart

**What goes wrong:** v8.0 fails health → rollback to v7.1 → v7.1 also fails (shared dep broken by manual install, or H4 config issue) → loop.

**Prevention:**
1. **Max 1 rollback per update attempt.** If rolled-back version fails health, helper writes CRITICAL state, stops, keeps rolled-back symlink. Red banner in webapp: "Multiple health check failures — manual intervention required."
2. Never auto-rollback further than 1 release. Multi-hop is manual only.

### M2. Clock Skew Breaks TLS

**Phase:** P3-Pipeline

**Prevention:**
1. Pre-flight time check — call `https://api.github.com/zen`, compare `Date:` header to local clock. Skew > 60s → warning, > 1h → refuse update.
2. Install step installs `systemd-timesyncd` if missing.
3. Log NTP sync status in `/api/health`.

### M3. Journal Log Pollution

**Phase:** P5-UI, P6-Safety

**Prevention:**
1. `SyslogIdentifier=pv-inverter-proxy-updater` distinct from main service.
2. Structured logging — one JSON line per attempt with `{attempt_id, from, to, outcome, duration_ms}`.
3. `LogRateLimitIntervalSec=30 LogRateLimitBurst=10` on helper unit.

### M4. Update During Night Mode State Transition

**Phase:** P4-Restart

**Prevention:**
1. Persist night-mode state in `/etc/pv-inverter-proxy/state.json`. Restore on boot.
2. Delay auto-updates to quiet hours by default (`updates.auto_install_window: "03:00-04:00"`).

### M5. Version Source-of-Truth Drift

**Phase:** P3-Pipeline, P5-UI

**Prevention:**
1. **Single source of truth:** git tag. Build step writes `src/pv_inverter_proxy/_version.py` using `git describe --tags --always`.
2. CI check that tag matches `pyproject.toml version`.
3. Footer shows BOTH version string AND short commit hash.

### M6. Helper Trigger File Injection

**Phase:** P2-Helper, P6-Safety

**Prevention:**
1. tmpfiles.d creates `/run/pv-inverter-proxy-updater/` with mode 0750, owner `pv-proxy:root`.
2. Strict JSON schema validation — reject extra fields. `release_tag` regex `^v\d+\.\d+\.\d+$`.
3. Helper validates `sha256` BEFORE downloading — webapp must prove it got hash from release manifest, pass in trigger.

---

## LOW

- **L1. Browser tab stale after update** — WS reconnect polls `/api/version`; force `location.reload()` if changed.
- **L2. importlib.resources caching** — document: updates ALWAYS require full process restart. No hot-reload.
- **L3. GitHub API schema drift** — defensive parsing, warn in `/api/health` if parse fails.
- **L4. Timezone in update log** — log in UTC, render in browser-local time.

---

## Severity-Ranked Summary

| # | Pitfall | Severity | Phase |
|---|---------|----------|-------|
| C1 | Bad commit lockout / StartLimit | BLOCKING | P1, P4 |
| C2 | Privileged helper SPOF | BLOCKING | P2, P6 |
| C3 | Modbus in-flight writes | BLOCKING | P4, P6 |
| C4 | Dep install failure | BLOCKING | P3, P4 |
| C5 | LAN webapp ACE surface | BLOCKING | P2, P5, P6 |
| H1 | Permission drift | HIGH | P2, P3 |
| H2 | Partial download | HIGH | P2, P3 |
| H3 | Python cache / sockets | HIGH | P4 |
| H4 | Config compat (v7.1.x prereq) | HIGH | P4, P6 |
| H5 | Rich health check | HIGH | P4 |
| H6 | Scheduler race | HIGH | P5, P6 |
| H7 | Dirty git tree on first upgrade | HIGH | P1 |
| H8 | Disk space | HIGH | P6 |
| M1 | Rollback infinite loop | MEDIUM | P4 |
| M2 | Clock skew TLS | MEDIUM | P3 |
| M3 | Journal pollution | MEDIUM | P5, P6 |
| M4 | Night mode restart | MEDIUM | P4 |
| M5 | Version drift | MEDIUM | P3, P5 |
| M6 | Trigger injection | MEDIUM | P2, P6 |
| L1-L4 | Misc | LOW | P5 |

---

## Must-Have Requirements Emerging From Pitfalls

These should land in REQUIREMENTS.md:

1. **Blue-green release layout with atomic symlink swap** (C1, C4, H1, H3)
2. **Dedicated root helper via trigger file, NOT sudo/polkit** (C2, C5, M6)
3. **Rich `/api/health` covering webapp + Modbus + devices + Venus OS** (H5, C1)
4. **Out-of-process watchdog for health check + auto-rollback** (C1, H5, M1)
5. **Modbus SlaveBusy maintenance mode with ≥3s drain before restart** (C3)
6. **Persistent state file for power limit + night mode across restart** (C3, M4)
7. **Tarball + SHA256SUMS from GitHub Releases — no main branch auto-install** (C5, H2)
8. **Pre-flight checks: disk, clock skew, permissions, config compat** (H4, H8, M2)
9. **Config loader tolerates unknown keys (v7.1.x compat prereq release)** (H4)
10. **CSRF token + rate limit on update endpoints** (C5)
11. **Boot-time recovery service** (C1)
12. **Helper heartbeat surfaced in webapp UI** (C2)
13. **systemd unit: StartLimitBurst=10, TimeoutStopSec=15, KillMode=mixed** (C1, H3)

## Open Questions for Roadmap

1. **Does Venus OS tolerate SlaveBusy responses without errors?** Needs empirical verification on live LXC. Early prototype spike recommended.
2. **GPG signing optional or required?** Recommendation: optional in v8.0, required in v8.1.
3. **Retention default:** 3 releases.
4. **Auto-install default:** OFF.
5. **Maximum auto-rollback distance:** 1 release.

## Sources

- systemd.service(5), systemd.exec(5) — training data, stable across versions
- pymodbus Modbus exception 0x06 SlaveBusy semantics
- GitHub Releases API, rate limits May 2025 changelog
- Project files reviewed: PROJECT.md, config/pv-inverter-proxy.service, install.sh, deploy.sh, CLAUDE.md
