---
phase: 46-ui-wiring-end-to-end-flow
plan: 05
type: execute
wave: 3
depends_on: [46-03, 46-04]
files_modified:
  - src/pv_inverter_proxy/updater/config.py
  - src/pv_inverter_proxy/webapp.py
  - src/pv_inverter_proxy/static/software_page.js
  - tests/test_updater_config.py
autonomous: false
requirements: [UI-01, UI-02, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09, CFG-02]
threat_refs: []
decisions_implemented: [D-04, D-05, D-06, D-42]

must_haves:
  truths:
    - "UpdateConfig dataclass has EXACTLY 3 fields: github_repo (str), check_interval_hours (int), auto_install (bool)"
    - "load_update_config reads from config.yaml under the 'update:' key and returns defaults when missing"
    - "save_update_config writes only the 3 fields back to config.yaml and preserves all other keys"
    - "GET /api/update/config returns {github_repo, check_interval_hours, auto_install}"
    - "PATCH /api/update/config accepts a subset of the 3 keys and rejects unknown keys with 422"
    - "PATCH /api/update/config validates types: github_repo non-empty string, check_interval_hours positive int, auto_install bool"
    - "software_page.js update-config panel uses the existing dirty-tracking ve-cfg-save-pair pattern"
    - "Save button POSTs PATCH /api/update/config with CSRF header and updates originals on success"
    - "After all plans verified, code is auto-deployed to LXC 192.168.3.191 (D-42)"
    - "Human verifies the full end-to-end flow on the LXC (modal, progress checklist, rollback, config save)"
  artifacts:
    - path: "src/pv_inverter_proxy/updater/config.py"
      provides: "@dataclass UpdateConfig + load_update_config + save_update_config"
      min_lines: 80
    - path: "tests/test_updater_config.py"
      provides: "CFG-02 dataclass + API tests"
      min_lines: 150
  key_links:
    - from: "updater/config.py::save_update_config"
      to: "existing config.save_config (preserves sibling keys)"
      via: "read-modify-write of the 'update' sub-dict"
      pattern: "from pv_inverter_proxy.config import"
    - from: "webapp.py::update_config_patch_handler"
      to: "updater.config.save_update_config"
      via: "validated key allow-list"
      pattern: "save_update_config"
    - from: "software_page.js::update-config form"
      to: "PATCH /api/update/config"
      via: "existing ve-cfg-save-pair dirty-tracking wiring"
      pattern: "ve-cfg-save-pair"
---

<objective>
Ship the minimal `UpdateConfig` dataclass (3 fields only per D-04), expose it via GET/PATCH /api/update/config, wire it into the software_page.js update-config panel using the existing dirty-tracking Save/Cancel pattern, and auto-deploy the full Phase 46 feature set to the LXC (D-42).

Purpose: CFG-02 is the final Phase 46 requirement. Plan 46-03 left the config panel as a skeleton; this plan populates it with three real fields and wires Save/Cancel. The auto-deploy + human-verify checkpoint at the end is the phase gate.

Output: A minimal config module (deliberately NOT the full CFG-01 schema — that waits for Phase 47), two new API routes, ~60 lines of wiring in software_page.js, an auto-deploy to 192.168.3.191, and a human-verify checkpoint covering the full end-to-end flow.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-RESEARCH.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-03-frontend-software-page-PLAN.md
@.planning/phases/46-ui-wiring-end-to-end-flow/46-04-update-api-routes-PLAN.md
@src/pv_inverter_proxy/config.py
@src/pv_inverter_proxy/webapp.py
@src/pv_inverter_proxy/static/software_page.js

<interfaces>
<!-- Contracts consumed from prior plans. -->

From existing config.py (Phase 43+):
```python
def load_config(path: Path) -> dict: ...
def save_config(path: Path, config: dict) -> None: ...
# The config.yaml is a dict with arbitrary top-level keys; "update" is a new sub-dict added here.
```

From app.js existing dirty-tracking pattern (lines 1149-1320):
```javascript
// Pattern:
// 1. Render panel with ve-panel-header + ve-btn-pair ve-cfg-save-pair (hidden)
// 2. Store originals dict
// 3. Query all inputs, bind 'input'/'change' -> checkDirty
// 4. checkDirty: compare each input to originals, toggle ve-input--dirty + savePair visibility
// 5. Cancel: restore originals, call checkDirty
// 6. Save: POST, on success reset originals to new values, call checkDirty
```
Plan 46-05 reuses these class names (ve-panel, ve-panel-header, ve-btn-pair, ve-cfg-save-pair, ve-input, ve-input--dirty) without creating new ones.

Required new exports from updater/config.py:
```python
@dataclass
class UpdateConfig:
    github_repo: str = "hulki/pv-inverter-proxy"
    check_interval_hours: int = 24
    auto_install: bool = False

DEFAULT_UPDATE_CONFIG = UpdateConfig()
ALLOWED_UPDATE_CONFIG_KEYS = {"github_repo", "check_interval_hours", "auto_install"}

def load_update_config(config_path: Path) -> UpdateConfig: ...
def save_update_config(config_path: Path, update_conf: UpdateConfig) -> None: ...
def validate_update_config_patch(patch: dict) -> tuple[bool, str | None]: ...  # (valid, error_message)
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement updater/config.py dataclass + load/save/validate helpers with tests</name>
  <files>src/pv_inverter_proxy/updater/config.py, tests/test_updater_config.py</files>
  <read_first>
    - src/pv_inverter_proxy/config.py (existing load_config + save_config signature and YAML handling)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-04, D-05, D-06
    - tests/test_config.py, tests/test_config_save.py (existing YAML test patterns)
  </read_first>
  <behavior>
    Test file defines the full contract for the 3-field dataclass and the validation helper. Every test must be concrete and runnable.

    Required test functions:
    - test_default_values_match_d04 (github_repo="hulki/pv-inverter-proxy", check_interval_hours=24, auto_install=False)
    - test_dataclass_has_exactly_three_fields (assert len(dataclasses.fields(UpdateConfig)) == 3)
    - test_load_update_config_missing_section_returns_defaults
    - test_load_update_config_partial_section_fills_defaults
    - test_load_update_config_full_section_roundtrip
    - test_save_update_config_preserves_other_top_level_keys (inverter:, venus:, etc. unchanged)
    - test_save_update_config_writes_exactly_three_keys
    - test_validate_patch_accepts_subset_of_three_keys
    - test_validate_patch_rejects_unknown_key
    - test_validate_patch_rejects_empty_github_repo
    - test_validate_patch_rejects_negative_check_interval
    - test_validate_patch_rejects_zero_check_interval
    - test_validate_patch_rejects_non_int_check_interval
    - test_validate_patch_rejects_non_bool_auto_install
    - test_validate_patch_rejects_non_string_github_repo
  </behavior>
  <action>
    **(A)** Create `tests/test_updater_config.py` with the 15 test functions above. Use `tmp_path` for config file fixtures, write small YAML files with the existing `save_config`/`load_config`, and assert round-trips.

    **(B)** Create `src/pv_inverter_proxy/updater/config.py`:
    ```python
    """Phase 46 update config: minimal 3-field dataclass (D-04). CFG-01 full schema stays in Phase 47."""
    from __future__ import annotations

    from dataclasses import dataclass, fields, asdict
    from pathlib import Path
    from typing import Any

    from pv_inverter_proxy.config import load_config, save_config

    UPDATE_CONFIG_SECTION_KEY = "update"

    @dataclass
    class UpdateConfig:
        github_repo: str = "hulki/pv-inverter-proxy"
        check_interval_hours: int = 24
        auto_install: bool = False

    DEFAULT_UPDATE_CONFIG = UpdateConfig()
    ALLOWED_UPDATE_CONFIG_KEYS = frozenset({"github_repo", "check_interval_hours", "auto_install"})

    def load_update_config(config_path: Path) -> UpdateConfig:
        try:
            full = load_config(config_path)
        except Exception:
            return UpdateConfig()
        section = (full or {}).get(UPDATE_CONFIG_SECTION_KEY) or {}
        kwargs: dict[str, Any] = {}
        if isinstance(section, dict):
            if isinstance(section.get("github_repo"), str) and section["github_repo"]:
                kwargs["github_repo"] = section["github_repo"]
            ci = section.get("check_interval_hours")
            if isinstance(ci, int) and not isinstance(ci, bool) and ci > 0:
                kwargs["check_interval_hours"] = ci
            ai = section.get("auto_install")
            if isinstance(ai, bool):
                kwargs["auto_install"] = ai
        return UpdateConfig(**kwargs)

    def save_update_config(config_path: Path, update_conf: UpdateConfig) -> None:
        try:
            full = load_config(config_path) or {}
        except Exception:
            full = {}
        if not isinstance(full, dict):
            full = {}
        full[UPDATE_CONFIG_SECTION_KEY] = {
            "github_repo": update_conf.github_repo,
            "check_interval_hours": update_conf.check_interval_hours,
            "auto_install": update_conf.auto_install,
        }
        save_config(config_path, full)

    def validate_update_config_patch(patch: dict) -> tuple[bool, str | None]:
        if not isinstance(patch, dict):
            return False, "patch_must_be_object"
        unknown = set(patch.keys()) - ALLOWED_UPDATE_CONFIG_KEYS
        if unknown:
            return False, f"unknown_keys:{','.join(sorted(unknown))}"
        if "github_repo" in patch:
            v = patch["github_repo"]
            if not isinstance(v, str) or not v.strip():
                return False, "github_repo_must_be_nonempty_string"
        if "check_interval_hours" in patch:
            v = patch["check_interval_hours"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                return False, "check_interval_hours_must_be_positive_int"
        if "auto_install" in patch:
            v = patch["auto_install"]
            if not isinstance(v, bool):
                return False, "auto_install_must_be_bool"
        return True, None
    ```

    Run `pytest tests/test_updater_config.py -x -q` — all 15 tests must pass.
  </action>
  <acceptance_criteria>
    - `src/pv_inverter_proxy/updater/config.py` exists
    - `grep -q "class UpdateConfig" src/pv_inverter_proxy/updater/config.py`
    - `grep -q 'github_repo: str = "hulki/pv-inverter-proxy"' src/pv_inverter_proxy/updater/config.py`
    - `grep -q 'check_interval_hours: int = 24' src/pv_inverter_proxy/updater/config.py`
    - `grep -q 'auto_install: bool = False' src/pv_inverter_proxy/updater/config.py`
    - `grep -q "ALLOWED_UPDATE_CONFIG_KEYS" src/pv_inverter_proxy/updater/config.py`
    - `grep -q "def load_update_config" src/pv_inverter_proxy/updater/config.py`
    - `grep -q "def save_update_config" src/pv_inverter_proxy/updater/config.py`
    - `grep -q "def validate_update_config_patch" src/pv_inverter_proxy/updater/config.py`
    - `python -c "from pv_inverter_proxy.updater.config import UpdateConfig; import dataclasses; assert len(dataclasses.fields(UpdateConfig)) == 3"` exits 0
    - `pytest tests/test_updater_config.py -x -q` exits 0 with all 15 tests green
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_config.py -x -q</automated>
  </verify>
  <done>UpdateConfig dataclass with exactly 3 fields per D-04; load/save/validate helpers with 15 passing tests; no coupling to webapp.py.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add GET/PATCH /api/update/config routes to webapp.py + frontend wiring in software_page.js</name>
  <files>src/pv_inverter_proxy/webapp.py, src/pv_inverter_proxy/static/software_page.js, tests/test_updater_webapp_routes.py</files>
  <read_first>
    - src/pv_inverter_proxy/webapp.py lines 558-720 (existing config_get_handler + config_save_handler as reference pattern)
    - src/pv_inverter_proxy/static/app.js lines 1149-1320 (existing dirty-tracking Save/Cancel pattern)
    - src/pv_inverter_proxy/updater/config.py (Task 1 output)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-04, D-05, D-06
  </read_first>
  <behavior>
    Add the backend endpoints, wire the frontend form into the existing dirty-tracking pattern, verify via pytest, and add two more test cases for the new routes in the existing test file.
  </behavior>
  <action>
    **(A) Backend: webapp.py edits**

    Add import near other updater imports:
    ```python
    from pv_inverter_proxy.updater.config import (
        UpdateConfig,
        load_update_config,
        save_update_config,
        validate_update_config_patch,
    )
    from dataclasses import asdict as _asdict
    ```

    Add two handlers:
    ```python
    async def update_config_get_handler(request: web.Request) -> web.Response:
        cfg_path = request.app["config_path"]
        try:
            uc = load_update_config(cfg_path)
        except Exception:
            uc = UpdateConfig()
        return web.json_response(_asdict(uc))

    async def update_config_patch_handler(request: web.Request) -> web.Response:
        try:
            patch = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        valid, err = validate_update_config_patch(patch)
        if not valid:
            return web.json_response({"error": "validation_failed", "detail": err}, status=422)
        cfg_path = request.app["config_path"]
        current = load_update_config(cfg_path)
        merged = UpdateConfig(
            github_repo=patch.get("github_repo", current.github_repo),
            check_interval_hours=patch.get("check_interval_hours", current.check_interval_hours),
            auto_install=patch.get("auto_install", current.auto_install),
        )
        try:
            save_update_config(cfg_path, merged)
        except Exception as exc:
            return web.json_response({"error": "save_failed", "detail": str(exc)}, status=500)
        return web.json_response(_asdict(merged), status=200)
    ```

    Register routes in create_webapp (near the other /api/update/* routes added by Plan 46-04):
    ```python
    app.router.add_get("/api/update/config", update_config_get_handler)
    app.router.add_patch("/api/update/config", update_config_patch_handler)
    ```

    NOTE: Plan 46-01's csrf_middleware enforces CSRF on PATCH since path starts with `/api/update/`. Confirm by re-reading the middleware's method allow-list — it must include PATCH (per Plan 46-01 Task 2 step 4: `request.method in ("POST", "PUT", "PATCH", "DELETE")`).

    **(B) Test additions in tests/test_updater_webapp_routes.py** (append, do not replace):
    Add test functions:
    - test_update_config_get_returns_three_fields
    - test_update_config_patch_requires_csrf
    - test_update_config_patch_accepts_single_field
    - test_update_config_patch_rejects_unknown_key_with_422
    - test_update_config_patch_rejects_invalid_type_with_422
    - test_update_config_patch_preserves_other_config_keys
    - test_update_config_get_does_not_require_csrf

    Run `pytest tests/test_updater_webapp_routes.py -x -q` — all new + existing pass.

    **(C) Frontend wiring in software_page.js**

    Locate the skeleton update-config card built by Plan 46-03 (class `ve-software-card` or similar container). Replace the skeleton form with a real one modeled on the existing dirty-tracking pattern. Add a new function `buildUpdateConfigForm(container)` that:

    1. Fetches current values:
    ```javascript
    function loadUpdateConfig(cb) {
      fetch('/api/update/config', {credentials: 'same-origin'})
        .then(function(res) { return res.json(); })
        .then(cb)
        .catch(function() { cb({github_repo: '', check_interval_hours: 24, auto_install: false}); });
    }
    ```

    2. Builds the form DOM via createElement (no innerHTML):
    ```javascript
    function buildUpdateConfigForm(container, values) {
      container.textContent = '';
      var originals = {
        github_repo: values.github_repo || '',
        check_interval_hours: values.check_interval_hours || 24,
        auto_install: !!values.auto_install,
      };
      // Panel header with save/cancel pair (existing pattern)
      var header = document.createElement('div');
      header.className = 've-panel-header';
      var title = document.createElement('h3');
      title.className = 've-software-card-title';
      title.textContent = 'Update-Einstellungen';
      header.appendChild(title);
      var savePair = document.createElement('span');
      savePair.className = 've-btn-pair ve-cfg-save-pair';
      savePair.style.display = 'none';
      var saveBtn = document.createElement('button');
      saveBtn.type = 'button';
      saveBtn.className = 've-btn ve-btn--sm ve-btn--save ve-update-action';
      saveBtn.textContent = 'Speichern';
      var cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 've-btn ve-btn--sm ve-btn--cancel';
      cancelBtn.textContent = 'Abbrechen';
      savePair.appendChild(saveBtn);
      savePair.appendChild(cancelBtn);
      header.appendChild(savePair);
      container.appendChild(header);

      // Three form fields
      var grid = document.createElement('div');
      grid.className = 've-software-config-grid';
      var repoGroup = makeGroup('GitHub Repository', 'text', 'github_repo', originals.github_repo);
      var intervalGroup = makeGroup('Check-Intervall (Stunden)', 'number', 'check_interval_hours', originals.check_interval_hours);
      var autoGroup = makeGroup('Auto-Install', 'checkbox', 'auto_install', originals.auto_install);
      grid.appendChild(repoGroup);
      grid.appendChild(intervalGroup);
      grid.appendChild(autoGroup);
      container.appendChild(grid);

      function makeGroup(label, type, name, value) {
        var g = document.createElement('div');
        g.className = 've-form-group';
        var lab = document.createElement('label');
        lab.textContent = label;
        var input = document.createElement('input');
        input.type = type;
        input.className = 've-input';
        input.dataset.field = name;
        if (type === 'checkbox') input.checked = !!value;
        else input.value = value;
        input.addEventListener('input', checkDirty);
        input.addEventListener('change', checkDirty);
        g.appendChild(lab);
        g.appendChild(input);
        return g;
      }

      function readValues() {
        return {
          github_repo: repoGroup.querySelector('input').value,
          check_interval_hours: parseInt(intervalGroup.querySelector('input').value, 10),
          auto_install: autoGroup.querySelector('input').checked,
        };
      }

      function checkDirty() {
        var cur = readValues();
        var dirty = false;
        [repoGroup, intervalGroup, autoGroup].forEach(function(g) {
          var input = g.querySelector('input');
          var f = input.dataset.field;
          var isDirty;
          if (input.type === 'checkbox') isDirty = input.checked !== originals[f];
          else if (input.type === 'number') isDirty = parseInt(input.value, 10) !== originals[f];
          else isDirty = input.value !== originals[f];
          input.classList.toggle('ve-input--dirty', isDirty);
          if (isDirty) dirty = true;
        });
        savePair.style.display = dirty ? '' : 'none';
      }

      cancelBtn.addEventListener('click', function() {
        repoGroup.querySelector('input').value = originals.github_repo;
        intervalGroup.querySelector('input').value = originals.check_interval_hours;
        autoGroup.querySelector('input').checked = originals.auto_install;
        checkDirty();
      });

      saveBtn.addEventListener('click', function() {
        var patch = readValues();
        fetch('/api/update/config', {
          method: 'PATCH',
          headers: csrfHeaders(),
          credentials: 'same-origin',
          body: JSON.stringify(patch),
        }).then(function(res) {
          if (res.status === 200) {
            return res.json().then(function(data) {
              originals.github_repo = data.github_repo;
              originals.check_interval_hours = data.check_interval_hours;
              originals.auto_install = data.auto_install;
              checkDirty();
              window.showToast('Einstellungen gespeichert', 'success');
            });
          } else if (res.status === 422) {
            return res.json().then(function(data) {
              window.showToast('Ungültige Eingabe: ' + (data.detail || 'unbekannt'), 'error');
            });
          } else {
            window.showToast('Speichern fehlgeschlagen: HTTP ' + res.status, 'error');
          }
        }).catch(function(e) {
          window.showToast('Netzwerkfehler: ' + e.message, 'error');
        });
      });
    }
    ```

    3. Call `loadUpdateConfig(function(values) { buildUpdateConfigForm(configCardBody, values); })` during `init()` after the card skeleton is mounted.
  </action>
  <acceptance_criteria>
    - `grep -q "from pv_inverter_proxy.updater.config import" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def update_config_get_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q "async def update_config_patch_handler" src/pv_inverter_proxy/webapp.py`
    - `grep -q '"/api/update/config"' src/pv_inverter_proxy/webapp.py`
    - `grep -q "add_patch.*update/config\|add_get.*update/config" src/pv_inverter_proxy/webapp.py`
    - `grep -q "validate_update_config_patch" src/pv_inverter_proxy/webapp.py`
    - `grep -q "test_update_config_patch_rejects_unknown_key_with_422" tests/test_updater_webapp_routes.py`
    - `grep -q "test_update_config_patch_preserves_other_config_keys" tests/test_updater_webapp_routes.py`
    - `grep -q "buildUpdateConfigForm\|loadUpdateConfig" src/pv_inverter_proxy/static/software_page.js`
    - `grep -q "ve-cfg-save-pair" src/pv_inverter_proxy/static/software_page.js`
    - `grep -q "ve-input--dirty" src/pv_inverter_proxy/static/software_page.js`
    - `grep -q "PATCH.*update/config\|'/api/update/config'" src/pv_inverter_proxy/static/software_page.js`
    - `grep -q "Speichern\|Einstellungen gespeichert" src/pv_inverter_proxy/static/software_page.js`
    - `pytest tests/test_updater_webapp_routes.py tests/test_updater_config.py tests/test_updater_security.py tests/test_updater_progress.py -x -q` exits 0
    - `pytest tests/test_updater_start_endpoint.py -x -q` exits 0 (Phase 45 regression)
  </acceptance_criteria>
  <verify>
    <automated>pytest tests/test_updater_webapp_routes.py tests/test_updater_config.py tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_start_endpoint.py -x -q</automated>
  </verify>
  <done>CFG-02 endpoints exist with validation; frontend form reuses existing dirty-tracking pattern; all tests green; CSRF enforced on PATCH.</done>
</task>

<task type="auto">
  <name>Task 3: Full phase test suite + auto-deploy to LXC 192.168.3.191</name>
  <files>deployed: /opt/pv-inverter-proxy on 192.168.3.191</files>
  <read_first>
    - CLAUDE.md (auto-deploy feedback_auto_deploy: deploy to 192.168.3.191 after code changes)
    - scripts/deploy.sh (if it exists — use the project's deploy helper, do NOT invent a new one)
    - .planning/phases/46-ui-wiring-end-to-end-flow/46-CONTEXT.md D-42
  </read_first>
  <action>
    1. Run the full Phase 46 test slice (all new + regression):
    ```bash
    pytest tests/test_updater_security.py tests/test_updater_progress.py tests/test_updater_webapp_routes.py tests/test_updater_config.py tests/test_updater_start_endpoint.py tests/test_updater_status.py tests/test_updater_trigger.py -x -q
    ```
    Must exit 0.

    2. Run the full project test suite:
    ```bash
    pytest -x -q
    ```
    Must exit 0 (no regression across ~57 test files).

    3. Lint/import sanity:
    ```bash
    python -c "import pv_inverter_proxy.webapp; import pv_inverter_proxy.updater.security; import pv_inverter_proxy.updater.progress; import pv_inverter_proxy.updater.config"
    ```

    4. Deploy to LXC 192.168.3.191 using the project's deploy helper. If `scripts/deploy.sh` exists, run it. Otherwise use the pattern documented in Phase 44 / Phase 45 SUMMARYs (rsync + systemctl restart via SSH). Executor must read scripts/deploy.sh or the latest Phase 45 SUMMARY for the exact invocation.

    5. Post-deploy smoke check (via SSH to 192.168.3.191):
    ```bash
    curl -s http://192.168.3.191:8080/api/version | python -m json.tool
    curl -s http://192.168.3.191:8080/api/update/status | python -m json.tool
    curl -s http://192.168.3.191:8080/api/update/config | python -m json.tool
    ```
    All three should return valid JSON. The version endpoint should show the new build commit SHA.

    6. Check systemd journal for any Phase 46 startup errors:
    ```bash
    ssh root@192.168.3.191 "journalctl -u pv-inverter-proxy -n 50 --no-pager"
    ```
    No tracebacks, no CSRF warnings, progress broadcaster task started.
  </action>
  <acceptance_criteria>
    - `pytest -x -q` exits 0 (full suite, no regressions)
    - `curl -s -o /dev/null -w '%{http_code}' http://192.168.3.191:8080/api/version` returns `200`
    - `curl -s http://192.168.3.191:8080/api/version` returns JSON with `version` and `commit` keys
    - `curl -s -o /dev/null -w '%{http_code}' http://192.168.3.191:8080/api/update/config` returns `200`
    - `curl -s http://192.168.3.191:8080/api/update/config | python -c "import sys,json; d=json.load(sys.stdin); assert 'github_repo' in d and 'check_interval_hours' in d and 'auto_install' in d"` exits 0
    - `ssh root@192.168.3.191 "journalctl -u pv-inverter-proxy -n 100 --no-pager" | grep -iE "traceback|error.*csrf|error.*progress_broadcaster"` returns no output
    - `ssh root@192.168.3.191 "journalctl -u pv-inverter-proxy -n 200 --no-pager"` contains "progress_broadcaster" or equivalent startup log line
  </acceptance_criteria>
  <verify>
    <automated>bash -c 'pytest -x -q && curl -sf http://192.168.3.191:8080/api/version && curl -sf http://192.168.3.191:8080/api/update/config | python -c "import sys,json; d=json.load(sys.stdin); assert set(d.keys())>={\"github_repo\",\"check_interval_hours\",\"auto_install\"}"'</automated>
  </verify>
  <done>Full test suite green, code deployed to 192.168.3.191, smoke endpoints return 200, no startup errors in journal, progress broadcaster task started.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: Human end-to-end verification on LXC 192.168.3.191</name>
  <what-built>
    All of Phase 46:
    - New #system/software page with version card, release-notes card, update-config card, rollback card
    - Install confirmation modal (native <dialog>) with Cancel autofocus, ESC close, German wording
    - 17-phase progress checklist driven by WS update_progress messages
    - CSRF middleware + rate limit + concurrent guard + audit log on /api/update/start and /api/update/rollback
    - /api/version, /api/update/status, /api/update/rollback, /api/update/check, /api/update/config (GET+PATCH) endpoints
    - Rollback button visible for 1 hour after a successful update
    - Update-config panel with dirty-tracking Save/Cancel
    - Auto-deployed to LXC 192.168.3.191
  </what-built>
  <how-to-verify>
    1. Open http://192.168.3.191:8080/ in a browser.
    2. Confirm the sidebar shows SYSTEM > Software. Click it. URL should change to `.../#system/software`.
    3. Version card: confirm it shows a current version string and a commit hash.
    4. Update-config panel: edit the "Check-Intervall (Stunden)" field — a green border should appear on the dirty input; Save/Cancel buttons should appear. Click Cancel — field reverts. Edit again, click Save — a success toast should appear.
    5. DevTools: verify that `document.cookie` contains `pvim_csrf=<base64 token>` and that `SameSite=Strict` is set.
    6. Click "Check now". A toast should appear (either "Neue Version verfügbar" or "Keine neue Version").
    7. (If a release is available) Click Install. Modal opens. Verify:
       a. Title: "Update installieren?"
       b. Cancel button has keyboard focus (visible focus ring)
       c. Press ESC — modal closes
       d. Press Install again, click Cancel — modal closes
       e. Press Install again, click "Installieren" — dialog closes, toast "Update gestartet" appears, all update buttons dim via ve-update-busy
    8. Watch the 17-phase checklist animate as the update progresses (requires a real update target; if none available, trigger a test update with the same SHA).
    9. After "done" phase: success toast appears, rollback button becomes visible.
    10. Verify /api/version reload: after the restart, the tab should reload automatically (check that the footer version badge shows the new commit).
    11. SSH check: `ssh root@192.168.3.191 "cat /var/lib/pv-inverter-proxy/update-audit.log | tail -5"` — should show JSONL entries with ts/ip/ua/outcome fields.
    12. Rapid-click protection: click Install twice within 5 seconds. Second attempt should show "Bitte 60s warten" toast (429 response) OR "Update läuft bereits" (409).
    13. CSRF test: in DevTools, delete the pvim_csrf cookie, then try to click Install. Should get "Sicherheitstoken abgelaufen" toast + page reload after 1.5s.
    14. Rollback test (within 1h of the successful update): click Rollback, confirm the native confirm dialog, watch the progress checklist run through rollback_* phases.
    15. Wait ~65 minutes (or simulate by setting `sessionStorage.lastUpdateSuccessAt` to an old timestamp): rollback button should hide.
  </how-to-verify>
  <resume-signal>Type "approved" if all 15 checks pass, or describe which step failed with a screenshot/log excerpt.</resume-signal>
</task>

</tasks>

<verification>
- `pytest -x -q` — full suite green
- LXC smoke endpoints return 200 with expected JSON shapes
- Journal shows no Phase 46 startup errors
- Human verifies 15-step end-to-end checklist passes
</verification>

<success_criteria>
CFG-02: UpdateConfig dataclass with 3 fields, load/save/validate helpers, GET/PATCH endpoints, frontend dirty-tracking form.
D-42: Auto-deployed to 192.168.3.191.
Phase 46 complete: all 14 REQ-IDs (UI-01..UI-09, SEC-01..SEC-04, CFG-02) verified end-to-end on the LXC.
</success_criteria>

<output>
After completion, create `.planning/phases/46-ui-wiring-end-to-end-flow/46-05-SUMMARY.md` using `@$HOME/.claude/get-shit-done/templates/summary.md`.
Also create `.planning/phases/46-ui-wiring-end-to-end-flow/46-HUMAN-VERIFY.md` capturing the approved state of the Task 4 checklist for the v8.0 release gate.
</output>
