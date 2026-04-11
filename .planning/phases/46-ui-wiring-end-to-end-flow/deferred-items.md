# Phase 46 — Deferred Items

## Pre-existing unrelated failures observed during Plan 46-04 execution

### tests/test_webapp.py::test_config_get_venus_defaults — pre-existing

- **Observed during:** Plan 46-04 Task 2 full-suite verification
- **Status:** Pre-existing at the Wave 1 merge base `2197ba8` (verified
  by `git stash` of 46-04 changes and re-running — still fails)
- **Root cause:** Test expects `data["venus"]` to equal
  `{"host": "", "port": 1883, "portal_id": ""}` verbatim, but the actual
  response now contains an additional `name: ""` field from a
  schema evolution that predates Phase 46
- **Scope decision:** Out of scope for Plan 46-04; the plan's `files_modified`
  contract covers `webapp.py` and `tests/test_updater_webapp_routes.py`
  only. Fixing a schema drift in Venus config serialization would
  touch unrelated surfaces. Log and continue per Rule 3 scope boundary.
- **Next owner:** A future config schema cleanup plan (candidate: Phase 47
  CFG-01 full schema) or a standalone tooling fix
