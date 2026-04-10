# Phase 43 — Deferred Items

Out-of-scope issues discovered during plan execution. Not caused by the
current phase's changes; logged here for later triage.

## Pre-existing test failures

### test_webapp.py::test_config_get_venus_defaults

- **Discovered during:** 43-01 full-suite regression check
- **Status:** Pre-existing — unrelated to state_file module
- **Details:** `AssertionError` in webapp Venus config defaults endpoint.
  The test exercises `/api/config/venus/defaults` which has nothing to do
  with the state_file module being added in 43-01.
- **Scope:** Do not fix in Phase 43. Belongs in a webapp-focused phase or
  a separate bugfix plan.
