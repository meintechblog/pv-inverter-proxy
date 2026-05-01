# Roadmap: Venus OS Fronius Proxy

## Milestones

- v1.0 MVP -- Phases 1-4 (shipped 2026-03-18)
- v2.0 Dashboard & Power Control -- Phases 5-8 (shipped 2026-03-18)
- v2.1 Dashboard Redesign & Polish -- Phases 9-12 (shipped 2026-03-18)
- v3.0 Setup & Onboarding -- Phases 13-16 (shipped 2026-03-19)
- v3.1 Auto-Discovery & Inverter Management -- Phases 17-20 (shipped 2026-03-20)
- v4.0 Multi-Source Virtual Inverter -- Phases 21-24 (shipped 2026-03-21)
- v5.0 MQTT Data Publishing -- Phases 25-27 (shipped 2026-03-22)
- v6.0 Shelly Plugin -- Phases 28-37 (shipped 2026-03-25)
- v7.0 Sungrow SG-RT Plugin -- Phases 38-42 (shipped 2026-04-10)
- v8.0 Auto-Update System -- Phases 43-47 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-4) -- SHIPPED 2026-03-18</summary>

- [x] Phase 1: Protocol Research & Validation (2/2 plans)
- [x] Phase 2: Core Proxy / Read Path (2/2 plans)
- [x] Phase 3: Control Path & Production Hardening (3/3 plans)
- [x] Phase 4: Configuration Webapp (2/2 plans)

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>v2.0 Dashboard & Power Control (Phases 5-8) -- SHIPPED 2026-03-18</summary>

- [x] Phase 5: Data Pipeline & Theme Foundation (2/2 plans)
- [x] Phase 6: Live Dashboard (2/2 plans)
- [x] Phase 7: Power Control (2/2 plans)
- [x] Phase 8: Inverter Details & Polish (1/1 plan)

Full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

<details>
<summary>v2.1 Dashboard Redesign & Polish (Phases 9-12) -- SHIPPED 2026-03-18</summary>

- [x] Phase 9: CSS Animations & Toast System (2/2 plans)
- [x] Phase 10: Peak Statistics & Smart Notifications (2/2 plans)
- [x] Phase 11: Venus OS Widget & Lock Toggle (2/2 plans)
- [x] Phase 12: Unified Dashboard Layout (1/1 plan)

Full details: `.planning/milestones/v2.1-ROADMAP.md`

</details>

<details>
<summary>v3.0 Setup & Onboarding (Phases 13-16) -- SHIPPED 2026-03-19</summary>

- [x] Phase 13: MQTT Config Backend (2/2 plans)
- [x] Phase 14: Config Page & Dashboard UX (2/2 plans)
- [x] Phase 15: Venus OS Auto-Detect (1/1 plan)
- [x] Phase 16: Install Script & README (1/1 plan)

Full details: `.planning/milestones/v3.0-ROADMAP.md`

</details>

<details>
<summary>v3.1 Auto-Discovery & Inverter Management (Phases 17-20) -- SHIPPED 2026-03-20</summary>

- [x] Phase 17: Discovery Engine (2/2 plans)
- [x] Phase 18: Multi-Inverter Config (2/2 plans)
- [x] Phase 19: Inverter Management UI (1/1 plan)
- [x] Phase 20: Discovery UI & Onboarding (2/2 plans)

Full details: `.planning/milestones/v3.1-ROADMAP.md`

</details>

<details>
<summary>v4.0 Multi-Source Virtual Inverter (Phases 21-24) -- SHIPPED 2026-03-21</summary>

- [x] Phase 21: Data Model & OpenDTU Plugin (2/2 plans)
- [x] Phase 22: Device Registry & Aggregation (2/2 plans)
- [x] Phase 23: Power Limit Distribution (2/2 plans)
- [x] Phase 24: Device-Centric API & Frontend (2/2 plans)

Full details: `.planning/milestones/v4.0-ROADMAP.md`

</details>

<details>
<summary>v5.0 MQTT Data Publishing (Phases 25-27) -- SHIPPED 2026-03-22</summary>

- [x] Phase 25: Publisher Infrastructure & Broker Connectivity (2/2 plans)
- [x] Phase 26: Telemetry Publishing & Home Assistant Discovery (2/2 plans)
- [x] Phase 27: Webapp Config & Status UI (2/2 plans)

Full details: `.planning/milestones/v5.0-ROADMAP.md`

</details>

<details>
<summary>v6.0 Shelly Plugin (Phases 28-37) -- SHIPPED 2026-03-25</summary>

- [x] Phase 28: Plugin Core & Profiles (1/1 plan)
- [x] Phase 29: Switch Control & Config Wiring (1/1 plan)
- [x] Phase 30: Add-Device Flow & Discovery (2/2 plans)
- [x] Phase 31: Device Dashboard & Connection Card (1/1 plan)
- [x] Phase 32: Aggregation Integration (1/1 plan)
- [x] Phase 33: Device Throttle Capabilities & Scoring (2/2 plans)
- [x] Phase 34: Binary Throttle Engine with Hysteresis (1/1 plan)
- [x] Phase 35: Smart Auto-Throttle Algorithm (2/2 plans)
- [x] Phase 36: Auto-Throttle UI & Live Tuning (2/2 plans)
- [x] Phase 37: Distributor Wiring & DC Average Fix (1/1 plan)

Full details: `.planning/milestones/v6.0-ROADMAP.md`

</details>

<details>
<summary>v7.0 Sungrow SG-RT Plugin (Phases 38-42) -- SHIPPED 2026-04-10</summary>

- [x] Phase 38: Plugin Core (2/2 plans)
- [x] Phase 39: Dashboard
- [x] Phase 40: Add Device & Discovery
- [x] Phase 41: Power Control
- [x] Phase 42: Integration

Full details: `.planning/milestones/v7.0-ROADMAP.md`

</details>

### v8.0 Auto-Update System (In Progress)

**Milestone Goal:** Professionelle In-Webapp Update-Experience — User kann neue Versionen aus dem GitHub-Repo direkt aus der Webapp installieren, ohne SSH-Zugriff, mit automatischer Verfuegbarkeits-Pruefung, Backup, Health-Check und Rollback-Sicherheit.

- [ ] **Phase 43: Blue-Green Layout + Boot Recovery** - Safety foundation: release directories, symlink layout, boot-time recovery hook, systemd hardening (no user-visible changes)
- [ ] **Phase 44: Passive Version Badge** - First user-visible feature: GitHub API polling, version display, orange badge on "System" entry when update available
- [x] **Phase 45: Privileged Updater Service** - Root helper via path-unit + oneshot: trigger file protocol, git ops, backup, health check, rollback (CLI-only, no UI wiring) (completed 2026-04-10)
- [x] **Phase 46: UI Wiring & End-to-End Flow** - Confirmation modal, progress view, WebSocket update stream, CSRF, rate limit, rollback button -- connects backend to browser (completed 2026-04-11)
- [ ] **Phase 47: Polish, Scheduler UI & Hardening** - Helper heartbeat banner, update history, scheduler settings UI, optional GPG verification, structured logging

## Phase Details

### Phase 43: Blue-Green Layout + Boot Recovery
**Goal**: The service runs from a versioned release directory behind an atomic symlink and can automatically recover from a bad boot, with zero user-visible UI changes — the safety foundation every subsequent update depends on
**Depends on**: Phase 42 (v7.0 complete)
**Requirements**: SAFETY-01, SAFETY-02, SAFETY-03, SAFETY-04, SAFETY-05, SAFETY-06, SAFETY-07, SAFETY-08, SAFETY-09
**Success Criteria** (what must be TRUE):
  1. The running service loads code from `/opt/pv-inverter-proxy-releases/<version>-<sha>/` via a `current` symlink; `/opt/pv-inverter-proxy` points at `releases/current`, and the first-boot migration has moved the existing flat tree into this layout without dirty-tree data loss
  2. A dedicated `pv-inverter-proxy-recovery.service` runs as a oneshot before the main service on every boot, reads a PENDING marker, and flips the symlink back to the previous release if the last boot ended without a SUCCESS marker
  3. The main systemd unit is hardened with `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15`, `KillMode=mixed`, and a `RuntimeDirectory=pv-inverter-proxy` tmpfs for the `/run/pv-inverter-proxy/healthy` flag
  4. The `/var/lib/pv-inverter-proxy/backups/` directory exists with mode 2775 root:pv-proxy, a pre-flight disk-space check refuses updates below 500 MB free on `/opt` or `/var/cache`, and retention of at most 3 release directories is enforceable
  5. The SE30K power-limit and night-mode state persist to `/etc/pv-inverter-proxy/state.json` across restarts and are restored on boot when still within `CommandTimeout/2`
**Plans**: TBD

### Phase 44: Passive Version Badge
**Goal**: The webapp discovers new releases on GitHub on a schedule and shows the user a non-actionable badge plus the current version, validating the entire version-check pipeline before any update can be triggered
**Depends on**: Phase 43
**Requirements**: CHECK-01, CHECK-02, CHECK-03, CHECK-04, CHECK-05, CHECK-06, CHECK-07
**Success Criteria** (what must be TRUE):
  1. The webapp footer displays the current version and short commit hash sourced from `importlib.metadata.version`
  2. Within one hour of a new GitHub Release being tagged, the sidebar "System" entry shows an orange `ve-dot` and `GET /api/update/available` returns the new `{current_version, latest_version, release_notes, published_at, tag_name}` payload
  3. The background scheduler runs as an asyncio task in the main event loop, uses aiohttp with the required `User-Agent` and `Accept: application/vnd.github+json` headers, honors ETag caching, and defers checks by one hour when a WebSocket client is connected
  4. GitHub unreachable, 5xx responses, and network errors never crash the scheduler — the UI surfaces a `last_check_failed_at` timestamp and logs a warning only
**Plans**: TBD
**UI hint**: yes

### Phase 45: Privileged Updater Service
**Goal**: A CLI-only end-to-end update works: writing a trigger file causes a privileged helper to back up, extract a new release into its own venv, run health checks, and either mark success or automatically roll back — with the Modbus server entering maintenance mode before restart
**Depends on**: Phase 43
**Requirements**: EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06, EXEC-07, EXEC-08, EXEC-09, EXEC-10, RESTART-01, RESTART-02, RESTART-03, RESTART-04, RESTART-05, RESTART-06, HEALTH-01, HEALTH-02, HEALTH-03, HEALTH-04, HEALTH-05, HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09, SEC-05, SEC-06, SEC-07
**Success Criteria** (what must be TRUE):
  1. Manually writing a valid trigger file to `/etc/pv-inverter-proxy/update-trigger.json` (atomic via `os.replace`) causes the `pv-inverter-proxy-updater.path`/`.service` pair to activate, the updater validates the target SHA is reachable from `origin/main`, matches `^v\d+\.\d+(\.\d+)?$`, and rejects any other input
  2. A full successful update extracts the new release into a fresh `/opt/pv-inverter-proxy-releases/<version>-<sha>/` directory with its own isolated `.venv/`, runs `pip install --dry-run` preflight and real install, verifies SHA256SUMS, compiles bytecode, runs a smoke import plus config dry-run against the new code, and flips the symlink atomically before `systemctl restart`
  3. Before every restart the main service enters maintenance mode — Modbus writes return exception 0x06 (`SlaveBusy`), in-flight transactions drain with a 3s grace, a `update_in_progress` WebSocket broadcast is sent, and the pymodbus server re-binds cleanly via `SO_REUSEADDR`
  4. `GET /api/health` reports per-component status (webapp, modbus_server, devices, venus_os) and the updater requires three consecutive healthy probes over 15 seconds plus the `/run/pv-inverter-proxy/healthy` tmpfs flag before marking `phase=done`
  5. A deliberately broken release triggers a single automatic rollback (symlink flip to previous release + restart + health re-check); a second failure is captured as `phase=rollback_failed` CRITICAL with the status file updated and the symlink left untouched for manual SSH recovery
**Plans**: 5 plans
- [x] 45-01-rich-health-endpoint-PLAN.md — Extend /api/health with per-component schema (HEALTH-01..04)
- [x] 45-02-trigger-status-contracts-PLAN.md — updater/trigger.py + status.py + POST /api/update/start + install.sh file perms (EXEC-01, EXEC-02, SEC-07) ✓ 2026-04-10
- [x] 45-03-updater-root-primitives-PLAN.md — updater_root package: git_ops, backup, gpg_verify, trigger_reader (EXEC-04, EXEC-05, EXEC-07, EXEC-10, SEC-05, SEC-06)
- [x] 45-04-updater-orchestrator-systemd-PLAN.md — runner state machine + healthcheck + systemd path/service units (EXEC-03, EXEC-06, EXEC-08, EXEC-09, RESTART-04, RESTART-05, HEALTH-05..09)
- [x] 45-05-maintenance-mode-integration-PLAN.md — Venus OS SlaveBusy spike + maintenance mode + SO_REUSEADDR + SAFETY-09 wiring (RESTART-01, RESTART-02, RESTART-03, RESTART-06)

### Phase 46: UI Wiring & End-to-End Flow
**Goal**: A user with no SSH access can click "Install" in the webapp, watch live phase-by-phase progress, and see a success or failure toast — with CSRF protection, rate limiting, and concurrent-update guards in place
**Depends on**: Phase 45
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09, SEC-01, SEC-02, SEC-03, SEC-04, CFG-02
**Success Criteria** (what must be TRUE):
  1. A new `#system/software` page shows current version + commit, last-check timestamp, a "Check now" button, and when an update is available a prominent card with release notes (rendered via a minimal Markdown subset) and an Install button
  2. Clicking Install opens a confirmation modal (Cancel is default focus, no type-to-confirm), and confirming calls `POST /api/update/start` with a CSRF token — the endpoint returns HTTP 202 in under 100 ms, atomically writes the trigger file, and broadcasts WebSocket `update_progress` messages for every phase transition rendered as a checklist
  3. The progress view drives a state machine that disables all update buttons while running, a success or failure toast reuses the existing v2.1 toast stacking system, and after a successful update the browser forces a reload when `/api/version` changes on WebSocket reconnect
  4. Concurrent update attempts get HTTP 409, the second attempt within 60 seconds gets HTTP 429 with `Retry-After`, every request (accepted or rejected) is written to `/var/lib/pv-inverter-proxy/update-audit.log` with timestamp, source IP, user-agent, and outcome
  5. A rollback button is visible for a bounded window after a successful update and from any history entry, triggers `POST /api/update/rollback`, and all update-related config fields are editable via the webapp with dirty-tracking Save/Cancel
**Plans**: TBD
**UI hint**: yes

### Phase 47: Polish, Scheduler UI & Hardening
**Goal**: The v8.0 feature set is complete — update history is visible, a silent helper is loudly surfaced, scheduler and update config are hot-reloadable from the UI, and medium-severity hardening items land behind the working core flow
**Depends on**: Phase 46
**Requirements**: HELPER-01, HELPER-02, HELPER-03, HELPER-04, HELPER-05, HELPER-06, HIST-01, HIST-02, HIST-03, HIST-04, CFG-01, CFG-03
**Success Criteria** (what must be TRUE):
  1. The `#system/software` page displays a history table of the last 20 updates with outcome badges (success/rolled_back/failed), expandable details, and rollback reason — backed by `/var/lib/pv-inverter-proxy/update-history.json` and `GET /api/update/history`
  2. A helper heartbeat runs every 60 seconds and a red "Auto-Update helper not responding — SSH required" banner appears when the last heartbeat reply is older than 3 minutes; `install.sh` runs a `self-test` trigger at install time and fails loudly on plumbing problems
  3. A new `update:` config section with documented defaults (`enabled: true`, `auto_install: false`, `check_interval_hours: 1`, `github_repo: ...`, `keep_releases: 3`, `allow_unsigned: true`) exists and changes take effect without a service restart via the same hot-reload pattern as VenusConfig
  4. The updater emits one structured JSON log line per attempt with `{attempt_id, from_version, to_version, outcome, duration_ms, error?}` under `SyslogIdentifier=pv-inverter-proxy-updater`, and systemd rate-limits the helper journal at `LogRateLimitIntervalSec=30`, `LogRateLimitBurst=10`
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 43 -> 44 -> 45 -> 46 -> 47
(Note: Phase 44 depends only on Phase 43 and could run in parallel with Phase 45, but sequential execution is cleaner and safer.)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 43. Blue-Green Layout + Boot Recovery | 0/? | Not started | - |
| 44. Passive Version Badge | 3/3 | Code-complete, pending human-verify | 2026-04-10 |
| 45. Privileged Updater Service | 5/5 | Complete   | 2026-04-10 |
| 46. UI Wiring & End-to-End Flow | 5/5 | Complete   | 2026-04-12 |
| 47. Polish, Scheduler UI & Hardening | 0/? | Not started | - |
