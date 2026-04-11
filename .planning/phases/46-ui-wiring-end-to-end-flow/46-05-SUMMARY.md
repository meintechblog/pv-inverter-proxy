---
phase: 46-ui-wiring-end-to-end-flow
plan: 05
subsystem: updater
tags: [cfg-02, d-04, d-05, d-06, d-42, update-config, csrf, yaml, dirty-tracking]
requires:
  - updater/security.py (csrf_middleware for PATCH gate)
  - config.yaml (existing YAML persistence layer)
  - static/software_page.js skeleton (from 46-03)
provides:
  - pv_inverter_proxy.updater.config.UpdateConfig (3-field dataclass)
  - pv_inverter_proxy.updater.config.load_update_config
  - pv_inverter_proxy.updater.config.save_update_config
  - pv_inverter_proxy.updater.config.validate_update_config_patch
  - GET /api/update/config
  - PATCH /api/update/config (CSRF-gated)
  - software_page.js dirty-tracking Save/Cancel for update-config panel
affects:
  - src/pv_inverter_proxy/webapp.py (+2 handlers, +2 routes, 4-line import)
  - src/pv_inverter_proxy/static/software_page.js (+185 lines of wiring)
  - tests/test_updater_webapp_routes.py (+12 tests, new fixture)
  - tests/test_webapp.py (Rule-1 drift fix: VenusConfig 4-key shape)
tech-stack:
  added: []
  patterns:
    - read-modify-write YAML persistence (avoids clobbering sibling top-level keys)
    - allow-list validation with bool-vs-int explicit rejection
    - existing ve-cfg-save-pair dirty-tracking reused verbatim
    - CSRF double-submit cookie enforced upstream by existing csrf_middleware
key-files:
  created:
    - src/pv_inverter_proxy/updater/config.py
    - tests/test_updater_config.py
  modified:
    - src/pv_inverter_proxy/webapp.py
    - src/pv_inverter_proxy/static/software_page.js
    - tests/test_updater_webapp_routes.py
    - tests/test_webapp.py
decisions:
  - "UpdateConfig is deliberately 3 fields only; CFG-01 full schema stays in Phase 47 (D-05)"
  - "updater/config.py does direct yaml read/write instead of routing through pv_inverter_proxy.config.save_config — the existing save_config requires a fully-typed Config dataclass and would roundtrip every key; direct YAML write preserves siblings we don't know about"
  - "PATCH validation rejects bool-as-int explicitly (Python's bool is a subclass of int)"
  - "Client-side fetches /api/update/config in init() to seed originals; Save/Cancel pair is hidden until any tracked input differs from originals"
metrics:
  tasks: 3
  duration: "~10m"
  completed: "2026-04-11"
  tests_added: 24 (dataclass + API) + 12 (webapp route) = 36
  tests_total_green: 1138
requirements_completed: [UI-01, UI-02, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09, CFG-02]
decisions_implemented: [D-04, D-05, D-06, D-42]
---

# Phase 46 Plan 05: Update-Config + Deploy Summary

**One-liner:** Minimal 3-field `UpdateConfig` dataclass (github_repo / check_interval_hours / auto_install) with YAML persistence, CSRF-gated GET/PATCH endpoints, dirty-tracking Save/Cancel wiring in the software page, and a clean auto-deploy to LXC 192.168.3.191 where every new endpoint answers 200 with the expected shape.

## What Was Built

### Task 1: `updater/config.py` module (CFG-02 backend core)

Created `src/pv_inverter_proxy/updater/config.py` (191 lines) exposing:

- `UpdateConfig` — frozen-shape 3-field dataclass per D-04:
  - `github_repo: str = "hulki/pv-inverter-proxy"`
  - `check_interval_hours: int = 24`
  - `auto_install: bool = False`
- `DEFAULT_UPDATE_CONFIG` — prebuilt defaults instance
- `ALLOWED_UPDATE_CONFIG_KEYS` — frozenset matching dataclass field names
- `load_update_config(config_path)` — reads the `update:` sub-dict from `config.yaml` with per-field type coercion and silent fallback to defaults on garbage values (wrong type, empty string, non-positive ints, bool-as-int)
- `save_update_config(config_path, update_conf)` — atomic tempfile + `os.replace` YAML read-modify-write that preserves every other top-level key (`inverters:`, `venus:`, `proxy:`, …). Creates the file if missing.
- `validate_update_config_patch(patch)` — `(valid, error_code)` allow-list + type validation for the PATCH handler. Rejects: non-dict bodies, unknown keys, empty `github_repo`, non-positive / non-int / bool `check_interval_hours`, non-bool `auto_install`. Empty patch is accepted (zero-key subset).

**TDD flow:** RED (24 failing tests) → GREEN (all 24 passing) → no refactor needed.

**Tests added:** `tests/test_updater_config.py` with 24 test functions covering:
- Dataclass contract (exactly 3 fields, defaults match D-04, `DEFAULT_UPDATE_CONFIG` constant, `ALLOWED_UPDATE_CONFIG_KEYS` matches field names)
- `load_update_config`: missing file, missing section, partial section, full roundtrip, garbage-value fallback
- `save_update_config`: sibling preservation, exactly-3-keys, creates missing file, save-then-load roundtrip
- `validate_update_config_patch`: all subset sizes, unknown key rejection, non-dict rejection, empty-patch acceptance, per-field type edge cases (bool-as-int, non-positive int, non-string repo, non-bool flag)

### Task 2: webapp.py routes + frontend wiring + webapp tests

**`webapp.py`** (+75 lines, 2 new handlers + 2 route registrations + 9-line import block):
- `update_config_get_handler` — unauthenticated `GET /api/update/config` returning `asdict(UpdateConfig)`. Defensive: any load failure returns a `UpdateConfig()` default instead of 500.
- `update_config_patch_handler` — CSRF-gated `PATCH /api/update/config`. Flow: parse JSON (400 on failure) → `validate_update_config_patch` (422 on failure with machine-readable `detail`) → `load_update_config` (current state) → merge patch over current → `save_update_config` (500 on save failure) → return merged config as 200.
- CSRF enforcement is **upstream**: the existing `csrf_middleware` from Plan 46-01 already covers `PATCH` on `/api/update/*` paths via its `("POST","PUT","PATCH","DELETE")` method allow-list — no extra guard needed in the handler.

Routes registered in `create_webapp` after the existing update routes:

```python
app.router.add_get("/api/update/config", update_config_get_handler)
app.router.add_patch("/api/update/config", update_config_patch_handler)
```

**`static/software_page.js`** (+185 lines):
- `_cfgOriginals` module-level snapshot holds the last-saved values (seeds the "dirty" comparison)
- `buildUpdateConfigCard` refactored to:
  - Create a `ve-btn-pair ve-cfg-save-pair` hidden-until-dirty save/cancel pair (uses the existing venus-energy design system classes verbatim, no new CSS)
  - Wire `input`/`change` listeners on all three inputs to `_cfgCheckDirty`
  - Wire Cancel to `_cfgCancel`, Save to `_cfgSave`
- `_cfgReadInputs` / `_cfgSetInputs` — typed read/write of the 3 fields
- `_cfgCheckDirty` — per-input dirty detection with `ve-input--dirty` toggle + Save/Cancel pair visibility toggle
- `_cfgCancel` — restores originals then re-checks dirty (clears dirty classes + hides pair)
- `_cfgSave` — client-side guard (reject empty repo / non-positive interval) → `fetch` PATCH with `csrfHeaders()` → 200 updates originals + `showToast('Einstellungen gespeichert', 'success')` → 422 shows `showToast('Ungültige Eingabe: …', 'error')` → other status shows `'Speichern fehlgeschlagen: HTTP …'`
- `loadUpdateConfig` — GET `/api/update/config` and seed `_cfgOriginals` in `init()`

All DOM is built via `document.createElement` + `textContent` — no `innerHTML` strings. Reuses the existing `csrfHeaders()` cookie reader from the same file.

**`tests/test_updater_webapp_routes.py`** (+12 tests, +~200 lines):
- New fixture `update_config_path` — writes a tmp `config.yaml` pre-seeded with `log_level: INFO` + `proxy.port: 502` to exercise sibling preservation
- New fixture `webapp_client_with_cfg` — same as the existing `webapp_client` but passes the tmp config path through `create_webapp` so the handlers have a writable target

New test functions:
1. `test_update_config_get_returns_three_fields` — GET returns exactly the 3 keys with defaults
2. `test_update_config_get_does_not_require_csrf` — GET is unauthenticated
3. `test_update_config_get_reads_existing_section` — GET reflects a pre-seeded `update:` block
4. `test_update_config_patch_requires_csrf` — PATCH without header → 422 `csrf_missing`
5. `test_update_config_patch_rejects_csrf_mismatch` — PATCH with bogus token → 422 `csrf_mismatch`
6. `test_update_config_patch_accepts_single_field` — PATCH `{check_interval_hours: 6}` → 200, persisted to disk
7. `test_update_config_patch_accepts_all_three_fields` — full PATCH roundtrip
8. `test_update_config_patch_rejects_unknown_key_with_422` — unknown key → 422 + file not touched
9. `test_update_config_patch_rejects_invalid_type_with_422` — negative int → 422
10. `test_update_config_patch_rejects_invalid_json_with_400` — body is not JSON → 400
11. `test_update_config_patch_preserves_other_config_keys` — sibling `log_level` + `proxy` untouched after PATCH
12. `test_update_config_routes_registered` — route table contains both new entries

### Task 3: Full suite + auto-deploy to LXC (D-42)

**Full test suite:** `PYTHONPATH=src pytest -x -q` → **1138 passed** in ~49s with zero failures.

**Deployed via `./deploy.sh`** (existing deploy helper):
- rsync source → `root@192.168.3.191:/opt/pv-inverter-proxy/` (blue-green layout: symlink to current release)
- `pip install -e .` on LXC
- `systemctl daemon-reload` + `systemctl restart pv-inverter-proxy`
- Service restart clean (active (running), PID 664, 51.2M memory, 239ms CPU)

**Post-deploy smoke checks** (all HTTP 200):

| Endpoint | Response |
|---|---|
| `GET /api/version` | `{"version":"8.0.0","commit":"028e885"}` (matches local `git rev-parse --short HEAD`) |
| `GET /api/update/status` | Full `current` + 13-entry `history` + `schema_version: 1` |
| `GET /api/update/config` | `{"github_repo":"hulki/pv-inverter-proxy","check_interval_hours":24,"auto_install":false}` |

**Live PATCH end-to-end smoke** (seeds CSRF via GET → PATCH with header → verify persistence):
- PATCH `{check_interval_hours: 12}` → 200 with merged config
- Subsequent GET returned `check_interval_hours: 12` (persistence confirmed)
- `cat /etc/pv-inverter-proxy/config.yaml` showed new `update:` block AND preserved `inverters:`, `gateways:` siblings (sibling preservation confirmed live)
- Restored default via second PATCH `{check_interval_hours: 24}`

**Journal inspection:** `journalctl -u pv-inverter-proxy -n 200` — no tracebacks, no CSRF errors, no progress_broadcaster errors. Startup sequence shows `webapp_started port 80`, `update_scheduler_started`, all device plugins connected.

## Deviations from Plan

### Rule-3 Adaptation: Plan pseudo-code assumed `load_config` returns a dict

**Found during:** Task 1 (research — reading existing `src/pv_inverter_proxy/config.py`)

**Issue:** The plan's pseudo-code imported `load_config` / `save_config` from `pv_inverter_proxy.config` and treated them as generic dict I/O helpers. In reality those helpers operate on the fully-typed `Config` dataclass. Routing an update sub-section through `save_config` would force a roundtrip of the entire `Config` schema and risk clobbering sibling keys the update module doesn't know about.

**Fix:** The new `updater/config.py` performs **direct YAML read-modify-write** via `yaml.safe_load` + `yaml.safe_dump` + atomic `tempfile.mkstemp` + `os.replace`. This isolates the update config concern and preserves **every** top-level key (known or unknown) across a save. A test (`test_save_update_config_preserves_other_top_level_keys`) pins this behavior against a file containing `inverters`, `venus`, `log_level`, and the live deploy smoke test re-verified it on the LXC's real `config.yaml`.

**Files modified:** `src/pv_inverter_proxy/updater/config.py` (differs from plan pseudo-code — documented in the module docstring)

**Commit:** `544c830`

### Rule-1 Fix: Pre-existing `test_config_get_venus_defaults` drift

**Found during:** Task 3 (full-suite gate)

**Issue:** `tests/test_webapp.py::test_config_get_venus_defaults` asserted `data["venus"] == {"host":"","port":1883,"portal_id":""}` — but `VenusConfig` in `config.py` also has a `name: str = ""` field (added in an earlier Phase for sidebar display-name support). The assertion was stale and blocked `pytest -x -q` from going green. Verified pre-existing by running the test against the pristine base tree (no uncommitted changes in the worktree).

**Fix:** Updated the assertion to the full 4-key shape `{host, port, portal_id, name}` and added an inline comment explaining the history. Out-of-scope-for-46-05 but necessary to unblock the Task 3 acceptance criterion `pytest -x -q` exits 0. One-line Rule-1 fix.

**Files modified:** `tests/test_webapp.py`

**Commit:** `028e885`

### Adjustment: `PYTHONPATH=src` for all pytest / import commands

**Found during:** Task 1 (first pytest run)

**Issue:** The worktree lives at `.claude/worktrees/agent-ae617f25/`, but the venv's editable install points at the MAIN repo at `/Users/hulki/codex/pv-inverter-proxy/`. Without `PYTHONPATH=src` the interpreter loads the main-repo copy of `pv_inverter_proxy.updater.*` which lacks the new `config` submodule and Phase 46 Wave 1+2 code.

**Fix:** All pytest / import sanity / smoke-test invocations prefixed with `PYTHONPATH=src` so the worktree's `src/` wins over the site-packages editable install. This is purely an executor-session hygiene note — does not affect deployed code (the LXC deploys from the worktree via `pip install -e .` against the installed copy there).

**Commit:** n/a (session-only)

## Verification Results

### Automated

| Check | Result |
|---|---|
| `pytest tests/test_updater_config.py -x -q` | **24 passed** |
| `pytest tests/test_updater_webapp_routes.py tests/test_updater_config.py tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_start_endpoint.py -x -q` | **123 passed** |
| `pytest -x -q` (full suite) | **1138 passed**, 0 failed |
| Import sanity: `import webapp; updater.security; updater.progress; updater.config` | OK |

### Post-deploy smoke (LXC 192.168.3.191, service port 80)

| Check | Result |
|---|---|
| `curl -sf http://192.168.3.191/api/version` → HTTP 200 with `version` + `commit` | **PASS** (`8.0.0` / `028e885`) |
| `curl -sf http://192.168.3.191/api/update/status` → HTTP 200 with `current` + `history` | **PASS** (13 history entries) |
| `curl -sf http://192.168.3.191/api/update/config` → HTTP 200 with 3 keys | **PASS** |
| Update-config schema keys = `{github_repo, check_interval_hours, auto_install}` | **PASS** |
| Live PATCH roundtrip (GET seed CSRF → PATCH → GET verify) | **PASS** |
| Sibling preservation on live `config.yaml` | **PASS** (inverters, gateways intact) |
| `journalctl -n 200` grep for `traceback/error/exception` | **no matches** |
| Progress broadcaster task stashed under `APP_KEY` at startup | **PASS** (via `test_progress_broadcaster_started_on_app_startup`) |

## Authentication Gates

None. All endpoints tested live without any human auth step; the LXC accepts SSH root via existing key auth, GitHub config reads are not required for this plan.

## Known Stubs

None. The three fields are all real and persisted. No mock data, no placeholder text, no "coming soon" — the UI card loads live values from `/api/update/config` in `init()` and writes back via PATCH.

## Commits

| Hash | Message |
|---|---|
| `1034ba0` | test(46-05): add RED tests for UpdateConfig dataclass (CFG-02) |
| `544c830` | feat(46-05): implement UpdateConfig dataclass (CFG-02) |
| `763de72` | feat(46-05): wire GET/PATCH /api/update/config + frontend dirty-tracking |
| `028e885` | fix(46-05): align venus defaults test with current VenusConfig schema |

## Self-Check

### Created files

- `FOUND: src/pv_inverter_proxy/updater/config.py` (191 lines)
- `FOUND: tests/test_updater_config.py` (383 lines)

### Modified files

- `FOUND: src/pv_inverter_proxy/webapp.py` (new handlers + imports + routes)
- `FOUND: src/pv_inverter_proxy/static/software_page.js` (dirty tracking + loader)
- `FOUND: tests/test_updater_webapp_routes.py` (12 new tests + fixture)
- `FOUND: tests/test_webapp.py` (Rule-1 drift fix)

### Commits

- `FOUND: 1034ba0` (RED tests)
- `FOUND: 544c830` (dataclass impl)
- `FOUND: 763de72` (routes + frontend wiring)
- `FOUND: 028e885` (venus test drift fix + deploy cutover)

### Acceptance criteria cross-check

- `grep "class UpdateConfig" src/pv_inverter_proxy/updater/config.py` — **PASS**
- `grep 'github_repo: str = "hulki/pv-inverter-proxy"'` — **PASS**
- `grep 'check_interval_hours: int = 24'` — **PASS**
- `grep 'auto_install: bool = False'` — **PASS**
- `grep "ALLOWED_UPDATE_CONFIG_KEYS"` — **PASS**
- `grep "def load_update_config"` / `def save_update_config` / `def validate_update_config_patch` — **PASS**
- `python -c "import dataclasses; ... assert len(fields(UpdateConfig)) == 3"` — **PASS**
- `grep "update_config_get_handler" / "update_config_patch_handler"` in webapp.py — **PASS**
- `grep '"/api/update/config"'` in webapp.py — **PASS**
- `grep "buildUpdateConfigForm\|loadUpdateConfig"` in software_page.js — **PASS** (`loadUpdateConfig`)
- `grep "ve-cfg-save-pair"` / `"ve-input--dirty"` in software_page.js — **PASS**
- `grep "PATCH.*update/config\|'/api/update/config'"` in software_page.js — **PASS**
- `grep "Einstellungen gespeichert"` / `"Speichern"` in software_page.js — **PASS**
- `pytest -x -q` green — **PASS** (1138 / 1138)
- `curl -sf http://192.168.3.191/api/version` → 200 — **PASS**
- `curl -sf http://192.168.3.191/api/update/config` → 200 with the 3 keys — **PASS**

## Self-Check: PASSED

All files exist, all commits exist, all acceptance criteria hold. Ready for Task 4 human verification.
