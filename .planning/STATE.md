---
gsd_state_version: 1.0
milestone: v8.0
milestone_name: Auto-Update System
status: executing
stopped_at: Completed 44-01-updater-backend-PLAN.md
last_updated: "2026-04-10T16:18:38.147Z"
last_activity: 2026-04-10 — Completed 43-02 releases module (SAFETY-01/02/08 library landed)
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 7
  completed_plans: 5
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-10)

**Core value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen
**Current focus:** Milestone v8.0 — Auto-Update System (planning Phase 43)

## Current Position

Phase: 43 — Blue-Green Layout + Boot Recovery
Plan: 02 — Releases module (complete)
Status: Executing (2/4 plans complete)
Last activity: 2026-04-10 — Completed 43-02 releases module (SAFETY-01/02/08 library landed)

Progress: [#.........] 3% (0/5 phases, 0/64 requirements — 2 of 4 Phase-43 plans done)

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

### Blockers/Concerns

- None blocking — roadmap approved, Phase 43 ready for planning

## Session Continuity

Last session: 2026-04-10T16:18:38.144Z
Stopped at: Completed 44-01-updater-backend-PLAN.md
Resume point: Execute 43-03 systemd-hardening-recovery plan
