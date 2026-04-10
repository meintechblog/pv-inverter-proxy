# Phase 45 — Deferred Items

Out-of-scope discoveries logged during plan execution. Do NOT auto-fix; address
in a dedicated debug/fix workflow.

## Pre-existing test failures on main

- **tests/test_webapp.py::test_config_get_venus_defaults** — Fails on clean
  `main` (commit `523618a`) before any Plan 45-01 changes. Failure is in the
  `/api/config` GET path, unrelated to `/api/health`. Confirmed via
  `git stash -u -- <plan-touched-files>` run against the baseline.
  - Discovered during: Plan 45-01 Task 1 regression sweep
  - Scope: Unrelated to HEALTH-01..04
  - Action: Triage in a separate `/gsd:debug` run.
