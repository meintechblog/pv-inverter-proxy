---
gsd_state_version: 1.0
milestone: v8.0
milestone_name: Auto-Update System
status: executing
stopped_at: Completed 44-03-frontend-display-PLAN.md code work; Task 3 human-verify checkpoint pending
last_updated: "2026-04-10T16:44:00Z"
last_activity: 2026-04-10 — Completed 44-03 frontend display code + LXC deploy (v8.0.0 79be2a0 live); CHECK-04 badge code-complete, visual verification pending
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 7
  completed_plans: 7
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-10)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Milestone v8.0 — Auto-Update System (Phase 44 code-complete, pending human visual verification)

## Current Position

Phase: 44 — Passive Version Badge
Plan: 03 — Frontend display (code-complete, human checkpoint pending)
Status: Awaiting human-verify checkpoint on Task 3
Last activity: 2026-04-10 — Completed 44-03 frontend code + LXC deploy; v8.0.0 (79be2a0) live at 192.168.3.191

Progress: [##########] 100% code (1/5 phases, 7/7 plans — Phase 44 awaiting visual approval)

## Performance Metrics

**Prior milestones:**

- v1.0: 4 phases, 9 plans
- v2.0: 4 phases, 7 plans
- v2.1: 4 phases, 7 plans
- v3.0: 4 phases, 6 plans
- v3.1: 4 phases, 7 plans
- v4.0: 4 phases, 8 plans
- v5.0: 3 phases, 6 plans
- v6.0: 10 phases, 12 plans
- v7.0: 5 phases (38-42), shipped 2026-04-10
- v8.0: 5 phases (43-47), planned

## Accumulated Context

### Decisions

- [v6.0]: Profile-based Gen1/Gen2 abstraction (dict, not class hierarchy)
- [v6.0]: Scoring formula: proportional base=7, binary base=3, with response/cooldown/startup penalties
- [v6.0->post]: Higher score = throttled first (fastest responders handle throttling)
- [v7.0]: Per-device aggregate toggle independent of throttle_enabled — display + aggregation respect it, throttle distributor stays independent
- [v8.0-research]: config.py already tolerates unknown keys (verified) — NO v7.1.x compat prep release needed
- [v8.0-research]: Privilege model is path-unit + root helper, NOT polkit (systemd #22055 blocks polkit for nologin system users)
- [v8.0-research]: Blue-green release layout with atomic symlink swap is the safety foundation — must land before any update-triggering phase
- [v8.0-research]: Auto-install default OFF — scheduler only checks + shows badge, user clicks bewusst on Install
- [v8.0-research]: Rollback distance is N-1 only (one release back); multi-hop via manual git checkout
- [v8.0-research]: GPG signing is optional in v8.0 (`updates.allow_unsigned: true` default), required in v8.1
- [43-02]: Retention union semantics: `retained = top-N newest ∪ current ∪ protect set`. Protected dirs outside the top-N window retain in ADDITION to top-N (can exceed `keep`). "Never delete current or previous" takes precedence over exact retention count.
- [43-02]: `releases.py` is strictly read-only — no rmtree, no symlink writes. Phase 45 updater owns all mutations. Module is safe to import in unprivileged pv-proxy context.
- [43-02]: Layout anchor constants (`RELEASES_ROOT`, `INSTALL_ROOT`, `DEFAULT_KEEP_RELEASES=3`, `MIN_FREE_BYTES=500MB`) now live in `releases.py` as the single source of truth for the entire v8.0 update system.
- [Phase 44]: Plan 44-01: fetch_latest_release returns None on ALL error paths (no network/no-release distinction in Phase 44; richer contract deferred to Phase 47)
- [Phase 44]: Plan 44-01: active-user probe exceptions fall through to run the check anyway — broken probe must not permanently lock out update checks
- [Phase 44]: Plan 44-02: refactored scheduler callback from closure to module-level _on_update_available(app_ctx, release) so tests import directly from __main__
- [Phase 44]: Plan 44-02: shared aiohttp.ClientSession created once in run_with_shutdown, passed to GithubReleaseClient — no per-request sessions
- [Phase 44]: Plan 44-02: release=None preserves stale available_update (transient fetch errors must not clear a previously advertised update)
- [Phase 44]: Plan 44-03: release_notes body rendering deferred to Phase 46 — Phase 44 shows only tag_name + GitHub link in the SYSTEM sidebar entry (T-44-17 avoidance until Markdown escape renderer lands)
- [Phase 44]: Plan 44-03: deploy.sh now writes transient src/pv_inverter_proxy/COMMIT file before rsync (removed via EXIT trap); version.py falls back to reading it when git is unavailable — required because LXC rsync excludes .git/ and CHECK-01 mandates the commit hash in the footer
- [Phase 44]: Plan 44-03: 2s REST fallback to /api/update/available on page load in case the WS initial push is missed — single-shot, never polls, guards against race with WS handler

### Sungrow Reference

- Live device: SG8.0RT at 192.168.2.151:502 via WiNet-S Dongle
- Register map verified: wire 5002-5037 covers all essential data
- U32 values: high word at lower address, low word always 0
- 3-phase inverter (3P4L), rated 8kW

### v8.0 Auto-Update Context

- Service runs as `pv-proxy` user (no sudo) under systemd on Debian 13 LXC
- Code at /opt/pv-inverter-proxy, installed via `pip install -e .`
- Config at /etc/pv-inverter-proxy/config.yaml (must be preserved across updates)
- GitHub repo: github.com:meintechblog/pv-inverter-master
- Target LXC: 192.168.3.191
- Two-process trust boundary: main service (unprivileged) writes trigger file → path-unit activates root oneshot updater
- Blue-green layout: `/opt/pv-inverter-proxy-releases/<version>-<sha>/` behind `current` symlink; rollback = symlink flip + restart
- Health definition: webapp=ok, modbus_server=ok, >=1 device=ok required; MQTT/Venus OS warn-only

### Research Flags (resolve during phase planning)

- Phase 45: Venus OS tolerance of pymodbus exception 0x06 (`SlaveBusy`) during maintenance mode — needs empirical spike on live LXC before implementation
- Phase 45: `/etc/pv-inverter-proxy/` per-file permissions — trigger file needs pv-proxy writable, status file needs root-only writable
- Phase 47: GPG key distribution strategy — maintainer key publication, Debian toolchain, install.sh integration

### Phase Summary (v8.0)

| Phase | Name | Reqs | Depends On |
|-------|------|------|------------|
| 43 | Blue-Green Layout + Boot Recovery | 9 (SAFETY-01..09) | Phase 42 |
| 44 | Passive Version Badge | 7 (CHECK-01..07) | Phase 43 |
| 45 | Privileged Updater Service | 28 (EXEC/RESTART/HEALTH/SEC-05..07) | Phase 43 |
| 46 | UI Wiring & End-to-End Flow | 14 (UI/SEC-01..04/CFG-02) | Phase 45 |
| 47 | Polish, Scheduler UI & Hardening | 12 (HELPER/HIST/CFG-01/CFG-03) | Phase 46 |
| Phase 44 P01 | ~45min | 3 tasks | 7 files |
| Phase 44 P02 | 25 min | 3 tasks | 6 files |
| Phase 44 P03 | ~7 min | 2 tasks + human-verify | 6 files |

### Blockers/Concerns

- None blocking — roadmap approved, Phase 43 ready for planning

## Session Continuity

Last session: 2026-04-10T16:33:17.711Z
Stopped at: Completed 44-02-webapp-integration-PLAN.md
Resume point: Execute 43-03 systemd-hardening-recovery plan
