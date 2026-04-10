# Project Research Summary

**Project:** pv-inverter-proxy — v8.0 Auto-Update System
**Domain:** In-webapp self-update for self-hosted Python service on LXC/systemd
**Researched:** 2026-04-10
**Confidence:** HIGH

---

## Executive Summary

The v8.0 Auto-Update System turns the Fronius Proxy into a self-maintaining service: users will see a version badge when a new release is available, click "Install", watch a phase-by-phase progress view, and land on the dashboard with the new version running — all without SSH. The safety model mirrors Home Assistant Supervisor and Fedora greenboot: blue-green release directories, an out-of-process root helper, a rich `/api/health` probe covering Modbus and devices, and automatic rollback if health fails. Everything is reversible.

The central architectural decision is the **path-unit-triggered root helper**. The `pv-proxy` system user runs with `NoNewPrivileges=true` and has no logind session, which means polkit's `org.freedesktop.systemd1.manage-units` action is permanently blocked (systemd issue #22055). The STACK.md polkit recommendation is therefore superseded: the correct pattern is an atomic trigger file written by the main service, a `.path` unit watching it, and a `Type=oneshot User=root` helper service that performs git operations and `systemctl restart`. This two-process split makes the trust boundary explicit, survives main-service restarts, and leaves a clean journal audit trail under `pv-inverter-proxy-updater`.

The key execution risk is the **blue-green directory layout**. A naive in-place `git reset` on the running code tree causes the StartLimit lockout pattern (C1) that makes a bad update unrecoverable without SSH. Every other safety mechanism — rollback, health check, boot-time recovery — depends on the blue-green layout being in place before the first update is attempted. This must land first. With that foundation correct, the remaining work is largely additive and low-risk.

**Milestone shape in five bullets:**
- Blue-green release layout with atomic symlink swap (`/opt/pv-inverter-proxy-releases/current` symlink) and boot-time recovery hook
- Root helper via `.path` + `Type=oneshot` systemd unit pair — polkit explicitly rejected
- Rich `/api/health` covering webapp, Modbus server, devices, Venus OS + out-of-process watchdog driving auto-rollback
- Version badge and one-click update UI reusing existing WebSocket infrastructure and toast system
- Opt-in background scheduler (`check_only` default, 1h interval); auto-install default OFF

---

## Key Findings

### Stack Decisions (condensed)

Zero new Python runtime dependencies. The full update system is buildable from the existing stack plus stdlib only.

| Need | Solution | Status |
|------|----------|--------|
| GitHub Releases API | `aiohttp.ClientSession` + ETag caching | existing |
| Version comparison | Hand-rolled `Version(NamedTuple)` (~15 LOC) | new code, zero deps |
| Git operations | `asyncio.create_subprocess_exec` with explicit argv | stdlib |
| Privilege escalation | Path-unit + root helper (NOT polkit, NOT sudo) | system config |
| Self-restart | Root helper calls `systemctl restart` — never main service | system config |
| Background scheduler | `asyncio.create_task` loop in existing event loop | stdlib |
| State persistence | `json` to `/etc/pv-inverter-proxy/update-state.json` | stdlib |
| Version source of truth | `importlib.metadata.version("pv-inverter-master")` | stdlib |

**Explicitly rejected:**
- `polkit JS rule` — blocked by systemd issue #22055 (`pv-proxy` is nologin, no session)
- `systemd-run --on-active=Ns` from main service — requires privilege, defeats the point
- `GitPython` — 350KB, CVEs, blocking I/O
- `packaging` / `semver` — not stdlib; project tags are simple `vX.Y.Z`
- `APScheduler` — asyncio task is sufficient
- Hot-reload / `os.execv` — unsafe; `importlib.resources` caches are process-bound

**GitHub API rate limits:** 60 req/hr unauthenticated. Hourly scheduler plus manual checks will never hit the limit. User-Agent header is required (missing returns 403).

### Feature Table Stakes

Every mature self-hosted updater in the comparison set (Home Assistant, Pi-hole, Nextcloud, UniFi, OctoPrint) ships all of these. Missing any one makes the update experience feel broken or untrustworthy.

| Feature | Why It Matters |
|---------|----------------|
| Current version display | User must know what they run before deciding to update |
| Available version display + badge | Passive discovery; orange dot on sidebar "System" entry |
| Confirmation modal (from-to, changelog, Cancel default) | Explicit informed consent before destructive op |
| Inline changelog from GitHub API body | HA and UniFi show this; skipping feels cheap |
| WebSocket progress indicator (phase text) | 30-90s without feedback = user assumes hang = mid-update refresh = corruption |
| Post-update health check with timeout | Gates success on a real probe, not "did systemd say active" |
| Automatic rollback on health failure | The line between "self-updating" and "self-bricking" |
| Success / failure toast | Close the loop; reuse existing toast stacking system (v2.1) |
| Config preservation (`/etc/pv-inverter-proxy/config.yaml`) | Non-negotiable; file lives outside code tree already |
| Pre-update backup of code tree | Rollback substrate; without it rollback is impossible |

### Feature Differentiators

| Feature | Value | When to Ship |
|---------|-------|--------------|
| Update history log (JSON, last 20, table UI) | Trust after a bad update; "when did it last work?" | v8.1 — trigger: first rollback in the wild |
| Background scheduler with last-check timestamp | Auto-discovery without babysitting | v8.1 — trigger: users ask "how do I know if I'm behind?" |
| "Skip this version" | Stops badge nagging when user consciously defers | v8.1 — trigger: badge complaints |
| Service-health banner after update (device reconnect) | Post-update visibility; all devices back | v8.1 |
| Pre-release / beta channel toggle | Power-user opt-in; fits self-hosted tinkerer audience | v8.2+ |
| GPG signature verification on releases | Hardens against compromised GitHub account | v8.1 optional, v8.2 required |
| Persistent state file for power limit across restart | SE30K limit survives update; no brief full-power event | v8.0 — safety, not polish |

### Anti-Features (explicit OUT)

| Feature | Why Out |
|---------|---------|
| Silent auto-install on schedule | A proxy update during solar peak = unmonitored power, lost throttle, confused Venus OS. User consent is non-negotiable for infrastructure. |
| Main-branch auto-pull | Non-deterministic; commit history is not release-tested. Updates pin to tagged GitHub Releases only. |
| Type-to-confirm dialog | Defeats informed-consent goal (users copy-paste). Update is reversible via rollback; does not meet the "truly irreversible" bar. |
| Hot-reload without restart | `importlib.resources` caches are process-bound. Updates ALWAYS require full `systemctl restart`. |
| Forced updates on minor versions | This proxy is infrastructure. Forcing a restart during solar production = real kWh lost. |
| Arbitrary multi-version downgrade | Rollback is N-1 only, within health-check window. Older versions require manual git checkout. |
| In-app package manager for dependencies | Dependency conflicts are the #1 cause of broken Python self-hosted deployments. Pin in pyproject.toml, ship in a release. |

### Architecture (condensed)

Two-process model with an explicit trust boundary. The main service (`pv-proxy` user) never gains privileges; all privileged operations happen in a separate root oneshot.

```
+---------------------------------------------------------------------+
| User Browser -> HTTP + WebSocket (port 80)                          |
+----------------------+----------------------------------------------+
                       |
                       v
+---------------------------------------------------------------------+
| pv-inverter-proxy.service  [User=pv-proxy, NoNewPrivileges=true]    |
|                                                                     |
|  aiohttp webapp                                                     |
|   +- /api/update/available   (reads AppContext.update_available)    |
|   +- /api/update/start       (POST -> trigger.write() -> 202)      |
|   +- /api/update/status      (reads update-status.json)            |
|   +- /api/health             ({version, status, components})       |
|                                                                     |
|  Background asyncio tasks                                           |
|   +- update_scheduler               [polls GitHub every 1h]        |
|                                                                     |
|  AppContext (extended)                                              |
|   +- update_available: {tag, sha, body, published_at}              |
|   +- update_status:    {phase, progress, started_at, target}       |
+----------------------+----------------------------------------------+
                       | atomic file write
                       v
      /etc/pv-inverter-proxy/update-trigger.json
                       | (PathModified=)
                       v
+---------------------------------------------------------------------+
| pv-inverter-proxy-updater.path  (watches trigger file)              |
|              | activates                                            |
|              v                                                      |
| pv-inverter-proxy-updater.service  [Type=oneshot, User=root]        |
|                                                                     |
|  1. Read trigger JSON, validate nonce/SHA reachability             |
|  2. Backup: tarball .venv, copy config.yaml                        |
|  3. git fetch origin; verify target SHA ancestor of origin/main    |
|  4. git reset --hard <target_sha>                                  |
|  5. .venv/bin/pip install -e .                                     |
|  6. Dry-run config load against new code                           |
|  7. systemctl restart pv-inverter-proxy.service                    |
|  8. Poll /api/health + /run/pv-inverter-proxy/healthy (60s max)    |
|  9. On failure: git reset --hard <old_sha>, restore venv, restart  |
| 10. Write phase=done (or rollback_done/failed) to status file      |
+---------------------------------------------------------------------+
```

**Blue-green layout:**
```
/opt/pv-inverter-proxy-releases/
  +-- v7.0-abc1234/    # full checkout + .venv
  +-- v8.0-def5678/    # full checkout + .venv
  +-- current -> v8.0-def5678   # atomic symlink swap
/opt/pv-inverter-proxy -> /opt/pv-inverter-proxy-releases/current
```

Rollback is a symlink flip and restart — zero git operations at rollback time.

**Key patterns:**
- Atomic trigger file write: `NamedTemporaryFile` + `os.replace` (POSIX atomic)
- Phase-based status file: monotonic progression; frontend polls `/api/update/status`
- File ownership: trigger 0664 root:pv-proxy, status 0644; one-way trust channel
- Security root of trust: only SHAs reachable from `refs/remotes/origin/main` are acceptable
- Nonce deduplication: processed nonces persisted to prevent double-execution

**New modules:**
```
src/pv_inverter_proxy/updater/          # pv-proxy code (unprivileged)
    github_client.py, version.py, trigger.py,
    status.py, scheduler.py, webapp_routes.py

src/pv_inverter_proxy/updater_root_impl/  # root-only code
    runner.py, git_ops.py, backup.py, healthcheck.py
```

**Modified existing files:** `webapp.py`, `__main__.py`, `context.py`, `pyproject.toml`, `config/pv-inverter-proxy.service`, `install.sh`

### Top 5 Blocking Pitfalls and Mitigations

**C1 — Bad commit lockout via systemd StartLimit**
A bad update crashing on import exhausts `StartLimitBurst=5` in 10s, systemd marks unit `failed`, webapp gone. On headless LXC without SSH habit = physical access.
Mitigation: Blue-green layout (rollback = symlink flip, not git ops). Tune unit: `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15`. Boot-time recovery hook: `pv-proxy-recovery.service` reads PENDING marker before main service starts, flips symlink back if last boot ended without SUCCESS marker.

**C2 — Privileged helper is a single point of failure**
If the updater service is masked/stopped/crashed, the main webapp silently cannot update. User clicks "Install" and sees "in progress" forever.
Mitigation: Helper heartbeat surfaced in UI (red banner after 3min silence). Install-time smoke test (`--self-test` flag). Never use sudo/polkit — those add additional failure modes. `journalctl -u pv-inverter-proxy-updater` is the primary diagnostic surface.

**C3 — Modbus write in-flight during restart**
Venus OS polls every ~2s and issues power-limit writes via EDPC refresh every 30s. Killing mid-write causes TCP reset, Venus OS logs "override failed", SE30K may hold stale limit past CommandTimeout.
Mitigation: Pre-shutdown maintenance mode: set `app_ctx.maintenance_mode = True`, Modbus server returns `SlaveBusy` (exception 0x06) for writes, drain in-flight transactions, wait 3s (> one Venus OS poll cycle), THEN trigger restart. Persist last-set power limit to `/etc/pv-inverter-proxy/state.json`; restore on boot if `now - set_at < CommandTimeout/2`. `KillMode=mixed`, `TimeoutStopSec=15`.

**C4 — Dependency install failure leaves half-updated system**
New dep in v8.0; pip download fails mid-install (network, disk, missing libffi-dev). New code in place importing uninstalled lib. Restart -> ImportError -> StartLimit -> lockout.
Mitigation: Isolated `.venv` per release directory — install into new venv while old venv still serves traffic. Pre-flight `pip install --dry-run` before touching real venv. Post-install smoke import in new venv before restart. NEVER run `pip install` against the currently-running venv.

**C5 — LAN webapp = arbitrary code execution surface**
No auth today. An "Install from GitHub" button means any compromised LAN device can trigger an install. GitHub account compromise would propagate to all instances worldwide.
Mitigation: Pin updates to tagged GitHub Releases only (never `main` branch). SHA256SUMS asset verification before extract. CSRF token on update endpoints. Rate limit (max 1 update per 60s). Optional GPG signature verification. Audit log of all update requests (IP, UA, timestamp).

---

## v7.1.x Compat Prep Release — RESOLVED: NOT NEEDED

PITFALLS.md and ARCHITECTURE.md both flag the config loader as a critical prerequisite: if v7.x crashes on unknown keys, rollback from v8.0 (which adds an `update:` section) triggers lockout.

**Verification result: config.py already tolerates unknown keys.** The module docstring states "Unknown keys are ignored." The implementation confirms this — every dataclass is constructed with a dict comprehension filtered to `__dataclass_fields__`:

```python
ProxyConfig(**{k: v for k, v in data.get("proxy", {}).items()
               if k in ProxyConfig.__dataclass_fields__})
```

This pattern is consistent across all top-level config sections (`ProxyConfig`, `NightModeConfig`, `WebappConfig`, `VenusConfig`, `ScannerConfig`, `MqttPublishConfig`, `VirtualInverterConfig`). Unknown keys at both the top level (unrecognized section names like `update:`) and within known sections are silently ignored. A config.yaml containing `update: {auto_check: true}` will load cleanly under v7.x.

**Conclusion:** No compat prep release required. v8.0 can add the `update:` section and rollback to v7.x will not cause a config parse failure. Cross this prerequisite off the blocking list.

---

## Implications for Roadmap

### Recommended Phase Breakdown (5 phases)

The Features agent suggested 4 phases (Passive Badge, Privileged Helper, UI Wiring, Polish). The Pitfalls agent suggested 7 phases keyed to its P1-P6 tags. This synthesis recommends **5 phases** that front-load all safety foundations before any user-facing update action is possible. The principle: phases 1-2 must be shippable and safe in production before phase 3 (the first phase that can trigger a real update) is built.

---

**Phase 1: Blue-Green Layout + Boot Recovery**

Rationale: This is the prerequisite for everything else. Without the blue-green directory structure, a bad update causes unrecoverable lockout. This phase has zero user-visible features but is the safety foundation the entire milestone rests on.

Delivers:
- `/opt/pv-inverter-proxy-releases/` directory structure with `current` symlink
- One-time migration script: detects old flat layout, checks `git status --porcelain`, copies tree to releases dir, creates symlink
- Boot-time recovery hook (`pv-proxy-recovery.service`, oneshot, before main service): reads PENDING marker; if found without SUCCESS, flips symlink back to previous release
- systemd unit hardening: `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15`, `KillMode=mixed`
- `RuntimeDirectory=pv-inverter-proxy` added to main service unit (creates tmpfs dir for healthy flag)
- `/var/lib/pv-inverter-proxy/backups/` directory created in install.sh

Addresses: C1 (lockout), H7 (dirty git tree on first upgrade)
Research flag: Standard systemd patterns — skip research phase.

---

**Phase 2: Passive Version Badge (no updates yet)**

Rationale: Delivers the first user-visible feature while remaining fully reversible. No privilege escalation, no actual update capability. Validates that GitHub API polling works on the live LXC (rate limits, User-Agent header, ETag caching) before depending on it for update triggers.

Delivers:
- `updater/version.py` (Version NamedTuple, ~15 LOC)
- `updater/github_client.py` (aiohttp wrapper, ETag cache, timeout handling, ~80 LOC)
- `updater/scheduler.py` (asyncio task, 1h interval, initial 60s delay, ~60 LOC)
- `/api/update/available` GET endpoint
- `/api/health` extended with `version` and `commit` fields
- WebSocket snapshot extended with `available_update` field
- Frontend: version display in sidebar footer, orange `ve-dot` on "System" entry when update available
- Config: `update: {enabled, check_interval_hours, github_repo}` with defaults

Ship test: Tag a v8.0.1 release -> webapp shows badge within 1h.
Addresses: Table stakes (version display, badge)
Research flag: Standard patterns — skip research phase.

---

**Phase 3: Privileged Updater Service (CLI-only, no UI wiring)**

Rationale: The hardest and most novel piece. Must be validated in isolation before connecting to the UI. End-to-end test is: manually write trigger file -> service performs update -> verify success. Then deliberately corrupt code, trigger rollback, verify recovery. Validates the entire safety chain before users can trigger it.

Delivers:
- `pv-inverter-proxy-updater.path` + `pv-inverter-proxy-updater.service` systemd units
- `updater_root.py` entry point + `updater_root_impl/runner.py` state machine
- `updater_root_impl/git_ops.py` (fetch, SHA reachability validation, reset, ~100 LOC)
- `updater_root_impl/backup.py` (venv tarball + config copy, retention to 3, ~80 LOC)
- `updater_root_impl/healthcheck.py` (poll `/api/health`, version assertion, 3 consecutive ok over 15s, 60s timeout, rollback on failure, ~80 LOC)
- Trigger file contract (JSON schema, nonce dedup, atomic write pattern)
- `/run/pv-inverter-proxy/healthy` flag written by main service on first stable health
- Phase-based status file written by root helper
- Modbus maintenance mode (`SlaveBusy` responses, 3s drain, polling pause flag)
- Persistent power-limit state file (`/etc/pv-inverter-proxy/state.json`)
- Install-time `--self-test` smoke test for updater
- install.sh updates: unit installation, backup dir, file permissions (0664/0644)

Ship test: Manual trigger -> observe full update cycle and rollback in journal.
Addresses: C1, C2, C3, C4, C5 (all blocking pitfalls), H1 (permissions), H2 (partial download), H3 (sockets), H5 (rich health check)
Research flag: Needs deeper research during planning — trigger file ownership race; Venus OS SlaveBusy empirical test spike recommended before this phase begins.

---

**Phase 4: UI Wiring and End-to-End Flow**

Rationale: Connects the working backend (Phase 3) to the browser. At this point the safety foundations are solid; this phase is primarily additive frontend work plus the WebSocket progress stream.

Delivers:
- `updater/trigger.py` (atomic trigger file write from main service, ~30 LOC)
- `updater/status.py` (read/watch update-status.json, ~40 LOC)
- `updater/webapp_routes.py` (REST + WebSocket routes, ~120 LOC):
  - `POST /api/update/start` -> write trigger -> 202
  - `GET /api/update/status`
  - `POST /api/update/rollback`
  - `GET /api/update/history`
- WebSocket `update_progress` message type for phase transitions
- Pre-shutdown `reconnect_soon` WebSocket broadcast
- CSRF token on update endpoints
- Rate limit: max 1 update per 60s; HTTP 409 on concurrent attempt
- Pre-update config compat dry-run (new code loads config before restart)
- Disk-space pre-check (`shutil.disk_usage`, 500MB threshold)
- Frontend `#system/software` page:
  - Version from/to display, last-check timestamp, "Check now" button
  - Inline changelog (minimal Markdown renderer, ~80 LOC vanilla JS)
  - Confirmation modal (Cancel default focus, no type-to-confirm)
  - Progress view with phase checklist driven by WebSocket
  - Success/failure toast reusing existing toast system
- SHA256SUMS asset verification

Ship test: End-to-end update from 8.0.0-rc1 -> 8.0.0-rc2, Venus OS stays green throughout.
Addresses: Table stakes (progress, modal, toast, changelog), C5 (CSRF, rate limit)
Research flag: Standard patterns for this codebase — skip research phase.

---

**Phase 5: Polish, Scheduler UI, and Hardening**

Rationale: Completes the v8.0 feature set and addresses the remaining medium-severity pitfalls. All items are independent and can be ordered internally by priority.

Delivers:
- Background scheduler UI toggle + configurable interval in System settings
- `check_only` default (never auto-install silently)
- Update history log: `update-history.json`, last 20 entries, table UI in `#system/software`
- Helper heartbeat surfaced in UI (red banner if helper silent > 3min) — C2 mitigation
- Clock skew pre-flight check against GitHub API `Date:` header (M2)
- Concurrent update guard (H6)
- Rate limiting on scheduler when user is active on WebSocket (defer auto-check by 1h)
- Optional GPG signature verification (`updates.allow_unsigned: false` config flag)
- Rollback infinite loop guard: max 1 rollback per update attempt; CRITICAL state on second failure (M1)
- Journal log surfaced in UI for failed update entries (read-only "View update log" link)
- Browser tab stale-version reload (poll `/api/version` on WS reconnect, force reload if changed) (L1)
- Structured logging for updater: one JSON line per attempt (M3)

Ship test: Trigger update, kill network mid-download, verify graceful failure and clean state. Trigger update, let health check fail, verify single rollback and CRITICAL state on second failure.
Research flag: GPG verification implementation needs research during planning (key distribution, Debian tooling).

---

### Phase Ordering Rationale

- **Safety before UI:** Phases 1-3 ship the entire safety stack (blue-green, helper, health check, rollback) before any user can trigger an update. A broken Phase 3 implementation is caught in CLI testing, not by a user clicking a button.
- **Reversibility gate:** Each phase is fully reversible without affecting users. Phase 1 changes the directory layout but leaves the service running. Phase 2 adds polling but no action. Phase 3 adds a new service that only fires when a trigger file appears.
- **Dependency order:** Phase 4 (UI) depends on Phase 3 (helper). Phase 2 (version badge) depends on neither and can be built in parallel with Phase 3 if needed.
- **Merge of research agents:** Features agent P1-P4 and Pitfalls agent P1-P6 tags are reconciled as follows: Pitfalls P1-Layout and P4-Restart concerns land in Phase 1. Pitfalls P2-Helper and P3-Pipeline concerns are Phase 3. Pitfalls P5-UI concerns are Phase 4. Pitfalls P6-Safety hardening is spread across Phases 3 and 5.

### Research Flags

Needs deeper research during planning:
- **Phase 3:** Trigger file ownership race (root writes status, pv-proxy writes trigger; verify `/etc/pv-inverter-proxy/` permissions survive install.sh). Empirical spike: does Venus OS accept `SlaveBusy` (exception 0x06) without logging errors or disconnecting? This is the Modbus maintenance mode assumption and should be verified on the live LXC before Phase 3 begins.
- **Phase 5:** GPG key distribution strategy — where is the maintainer key published, how does the helper fetch and trust it, what is the Debian toolchain for this?

Standard patterns, skip research phase:
- **Phase 1:** systemd unit tuning and symlink-based deployment are well-documented patterns.
- **Phase 2:** GitHub Releases API is fully documented; aiohttp ETag caching is standard.
- **Phase 4:** WebSocket progress patterns match existing codebase conventions exactly.

---

## Open Questions for Requirements and Roadmap

1. **Auto-install default:** Research consensus is OFF. Confirm this is the product decision. Config key: `update.auto_install: false`.

2. **GPG signing:** Optional in v8.0 (Phase 5 config flag `updates.allow_unsigned: false` defaults to `true` = unsigned allowed), required in v8.1? Or defer entirely to v8.2? The value is real but implementation adds complexity.

3. **Retention count:** Research recommends 3 release directories. Each is roughly 50-200MB depending on venv size. Confirm this is acceptable for LXC root disk sizing.

4. **Health definition — final call:** REQUIRED = webapp responds + Modbus server bound + >=1 device producing frames. OPTIONAL (warn-only) = MQTT/Venus OS connected. This needs product sign-off as it affects rollback false-positive rate.

5. **Rollback distance:** Max 1 (N-1 only). For older versions, manual git checkout. Confirm this is the intended UX.

6. **Update channel in v8.0:** Stable only (tagged releases via `/releases/latest`). Pre-release toggle deferred to v8.2+. Confirm.

7. **Venus OS SlaveBusy behavior:** Does pymodbus Modbus TCP server returning exception 0x06 during maintenance mode cause Venus OS to log errors, retry, or disconnect? Needs empirical verification before Phase 3 ships.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new deps confirmed; polkit block verified via systemd issue #22055; all library choices match existing codebase patterns |
| Features | HIGH | Industry consensus from HA/Pi-hole/Nextcloud/UniFi is strong; table stakes and anti-features are well-established |
| Architecture | HIGH | Two-process path-unit pattern is well-documented in systemd.path(5); existing codebase integration points are specific and reviewed |
| Pitfalls | HIGH | All blocking pitfalls have concrete mitigations; config.py compat verified by direct code inspection |

**Overall confidence: HIGH**

### Gaps to Address

- **Venus OS SlaveBusy tolerance:** Unverified assumption. If it fails, the Modbus maintenance mode strategy changes. Spike in Phase 3 planning.
- **LXC disk headroom:** Blue-green layout plus 3 retained releases adds ~150-600MB. Unknown if typical LXC root disk has this headroom. Should be surfaced in Phase 1 planning.
- **`/etc/pv-inverter-proxy/` per-file permissions:** Status file needs root-writable but pv-proxy-readable. Trigger file needs pv-proxy-writable. Current directory is pv-proxy-owned. Needs explicit `chown`/`chmod` per-file in install.sh, not directory-level. Resolve in Phase 3.

---

## Sources

### Primary (HIGH confidence)

- `src/pv_inverter_proxy/config.py` — Direct code inspection confirms unknown-key tolerance via `__dataclass_fields__` filtering; compat prep release not needed
- `config/pv-inverter-proxy.service` — Existing unit hardening baseline for StartLimit tuning
- `__main__.py`, `context.py`, `webapp.py` — Integration points verified against specific line numbers in ARCHITECTURE.md
- systemd issue #22055 — Polkit session requirement blocks pv-proxy (nologin user); path-unit pattern chosen
- freedesktop.org systemd.path(5) — Path unit semantics for trigger file watching
- GitHub REST API docs — Rate limits, User-Agent requirement, ETag semantics, releases endpoint schema

### Secondary (MEDIUM confidence)

- Home Assistant Supervisor — Update flow, health check gating, rollback via snapshot
- Fedora greenboot — Post-update health probe + auto-rollback gold standard
- Nextcloud built-in updater — Pre-update backup flow, "downgrade not supported" policy
- Pi-hole updating docs — CLI-first model, no inline rollback (cautionary)
- UniFi updates docs — Release channel picker, auto-update opt-in UX
- Nielsen Norman Group: Confirmation Dialogs — Default focus on Cancel, when type-to-confirm earns its keep

### Tertiary (LOW confidence — needs empirical validation)

- pymodbus exception 0x06 SlaveBusy semantics — Venus OS behavior under SlaveBusy is assumed but not empirically tested on live hardware

---
*Research completed: 2026-04-10*
*Ready for roadmap: yes*
