---
phase: 16-install-script-readme
plan: 01
subsystem: docs
tags: [bash, installer, readme, yaml, documentation]

# Dependency graph
requires:
  - phase: 13-venus-os-mqtt
    provides: VenusConfig dataclass and MQTT integration
  - phase: 14-venus-config-ui
    provides: Config page with connection bobbles and MQTT setup guide
  - phase: 15-venus-os-auto-detect
    provides: Venus OS auto-detect banner
provides:
  - Fixed install.sh with correct YAML template (inverter: + venus: sections)
  - Pre-flight checks (port 502, old config migration warning)
  - Secure curl flags (-fsSL)
  - Updated README with full v3.0 setup flow
  - config.example.yaml with venus section
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Install script YAML template must match config.py dataclass field names"
    - "Single source of truth: config.example.yaml -> install.sh template -> README example"

key-files:
  created: []
  modified:
    - install.sh
    - config/config.example.yaml
    - README.md

key-decisions:
  - "Migration warning (not auto-migration) for old solaredge: config key"
  - "Port 502 check is warning not hard fail (previous install may hold port)"

patterns-established:
  - "curl -fsSL (with --fail) for all pipe-to-bash install commands"

requirements-completed: [DOCS-01, DOCS-02]

# Metrics
duration: 5min
completed: 2026-03-19
---

# Phase 16 Plan 01: Install Script & README Summary

**Fixed install script YAML mismatch (solaredge: -> inverter:), added venus: config section, pre-flight checks, and rewrote README with full v3.0 setup flow including Venus OS MQTT instructions**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-19T21:13:17Z
- **Completed:** 2026-03-19T21:18:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Install script generates correct YAML matching config.py dataclasses (inverter: key, venus: section)
- Pre-flight checks: port 502 warning, old solaredge: config migration warning, secure -fsSL curl flags
- README rewritten with Prerequisites (Venus OS >= 3.7), Setup Flow (4-step onboarding), updated config example, network diagram with MQTT, all v3.0 features documented
- config.example.yaml updated with venus section for consistency

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix install script YAML template and add pre-flight checks** - `650a225` (feat)
2. **Task 2: Rewrite README with full v3.0 setup flow** - `6c6bc76` (feat)

## Files Created/Modified
- `install.sh` - Fixed YAML template (inverter: + venus:), port 502 check, migration warning, secure curl flags
- `config/config.example.yaml` - Added venus: section with host, port, portal_id
- `README.md` - Full rewrite: Prerequisites, Setup Flow, correct config, network diagram, v3.0 features, paho-mqtt in tech stack

## Decisions Made
- Migration warning instead of auto-migration for old solaredge: config key (sed on YAML is fragile)
- Port 502 pre-flight check is a warning, not a hard fail (previous install of same service may hold the port)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- This is the final phase of v3.0 milestone (Setup & Onboarding)
- All documentation and install artifacts are now aligned with the codebase
- The blocker "Install script YAML key mismatch" documented in STATE.md is resolved

---
*Phase: 16-install-script-readme*
*Completed: 2026-03-19*
