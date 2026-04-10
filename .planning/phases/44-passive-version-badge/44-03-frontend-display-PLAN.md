---
phase: 44-passive-version-badge
plan: 03
type: execute
wave: 3
depends_on:
  - 44-02
files_modified:
  - src/pv_inverter_proxy/static/index.html
  - src/pv_inverter_proxy/static/app.js
  - src/pv_inverter_proxy/static/style.css
autonomous: false
requirements:
  - CHECK-01
  - CHECK-04
must_haves:
  truths:
    - "index.html has a footer element below the sidebar content that will hold the version string"
    - "app.js sets the footer text to 'v{current_version} ({current_commit})' when the available_update WS message arrives"
    - "app.js handles the available_update WS message type in the existing onmessage switch"
    - "app.js renders a SYSTEM sidebar group with a Software entry when available_update.available_update is non-null"
    - "The Software sidebar entry shows an orange ve-dot when an update is available"
    - "The Software sidebar entry shows a 'View on GitHub' link opening in a new tab"
    - "When last_check_failed_at is set and available_update is null, the version footer shows a small subtle indicator (dim dot or title tooltip)"
    - "Version footer uses existing --ve-text-dim token and existing font sizes — zero new hex colors"
    - "Frontend changes are additive: no existing classes removed, no existing DOM nodes restructured"
    - "Deploying the changes to the LXC 192.168.3.191 succeeds and the service restarts cleanly"
    - "Manual curl to /api/update/available on the LXC returns the expected JSON shape"
    - "Manual browser verification shows the version in the footer after hard refresh"
  artifacts:
    - path: "src/pv_inverter_proxy/static/index.html"
      provides: "Footer element #ve-version-footer below sidebar scroll area"
      contains: "ve-version-footer"
    - path: "src/pv_inverter_proxy/static/app.js"
      provides: "handleAvailableUpdate() + renderVersionFooter() + System sidebar group rendering"
      contains: "available_update"
    - path: "src/pv_inverter_proxy/static/style.css"
      provides: "Minimal additive styling for ve-version-footer (zero new colors)"
      contains: "ve-version-footer"
  key_links:
    - from: "src/pv_inverter_proxy/static/app.js onmessage handler"
      to: "handleAvailableUpdate"
      via: "case msg.type === 'available_update'"
      pattern: "available_update"
    - from: "renderSidebar"
      to: "SYSTEM group with Software entry"
      via: "New branch at end of renderSidebar when _availableUpdateState is set"
      pattern: "SYSTEM"
    - from: "WS initial push (webapp.py ws_handler)"
      to: "app.js on first connect"
      via: "ws.onmessage receives available_update message before any user interaction"
      pattern: "available_update"
---

<objective>
Deliver the frontend display for CHECK-01 (version in footer) and CHECK-04 (orange ve-dot on Sidebar-Eintrag 'System'). Deploy the full Phase 44 stack to the LXC and verify end-to-end: the version renders, the scheduler logs a fetch, and the curl endpoint returns expected JSON.

Purpose: This is the user-visible deliverable of Phase 44. After this plan ships, the user sees their current version when they open the webapp. When Claude Code tags a test release on GitHub, they see the orange badge + link within 1 hour (or immediately on next scheduler check, whichever comes first).

Output: Working webapp on http://192.168.3.191 showing version footer + (on demand) the badge. Full Phase 44 verification logged in SUMMARY.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/research/FEATURES.md
@.planning/phases/44-passive-version-badge/44-01-updater-backend-PLAN.md
@.planning/phases/44-passive-version-badge/44-02-webapp-integration-PLAN.md
@CLAUDE.md

@src/pv_inverter_proxy/static/index.html
@src/pv_inverter_proxy/static/app.js
@src/pv_inverter_proxy/static/style.css
@deploy.sh

<interfaces>
<!-- DOM + JS anchors the executor needs -->

**index.html existing sidebar structure:**
```html
<nav class="sidebar" id="sidebar">
  <div class="sidebar-header"> ... </div>
  <div id="device-sidebar"></div>         <!-- JS renders device groups here -->
  <div class="ve-sidebar-footer">          <!-- Export/Import buttons -->
    ...
  </div>
</nav>
```

The new version footer MUST be additive: a new `<div id="ve-version-footer">` element placed INSIDE the sidebar after `ve-sidebar-footer` (or as a new sibling within the sidebar), so it sits at the bottom and doesn't interfere with the config export/import row.

**app.js existing message dispatch (line ~323-340):**
```javascript
ws.onmessage = function(event) {
    try {
        var msg = JSON.parse(event.data);
        if (msg.type === 'snapshot') handleSnapshot(msg.data);
        if (msg.type === 'device_snapshot') handleDeviceSnapshot(msg);
        if (msg.type === 'virtual_snapshot') handleVirtualSnapshot(msg.data);
        if (msg.type === 'device_list') { ... renderSidebar(msg.data.devices); }
        // ← ADD: if (msg.type === 'available_update') handleAvailableUpdate(msg.data);
        ...
```

**app.js existing renderSidebar signature (line 87):**
```javascript
function renderSidebar(devices) {
    if (devices) _devices = devices;
    var container = document.getElementById('device-sidebar');
    if (!container) return;
    container.innerHTML = '';
    // ... builds INVERTERS, VENUS OS, MQTT PUBLISH groups ...
```

We'll add a new SYSTEM group at the end of renderSidebar when `_availableUpdateState` indicates an update is pending.

**app.js module-level state pattern:**
Near the top of app.js (before any functions) there are `var _devices = [];`, `var _activeDeviceId = null;`, etc. Add `var _availableUpdateState = null;` alongside them.

**createSidebarGroup(label, devices, showAddBtn) signature:**
Reuses for "SYSTEM" but the Software entry is not a device — use a direct HTML fragment or a minimal fake "device" object to pass through createSidebarDevice with type='system'. Simpler: write a small dedicated renderer `createSoftwareSidebarEntry(updateState)` that mirrors createSidebarDevice's structure but uses the badge dot color and adds a "View on GitHub" secondary element.

**CSS tokens (existing, MUST use, never hardcode hex):**
- `var(--ve-text-dim)` — footer text color
- `var(--ve-orange)` — update available badge
- `var(--ve-bg-surface)` — sidebar background (footer matches)
- `var(--ve-border)` — top border of footer
- `.ve-dot` class exists with 10px circle, default grey background; add inline `style="background:var(--ve-orange)"` to override for the badge

**deploy.sh** is the established deploy script to the LXC. `./deploy.sh` pushes current code to 192.168.3.191 and restarts the service. This is the auto-deploy target per user memory.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add version footer DOM + minimal CSS + JS handler</name>
  <files>
    src/pv_inverter_proxy/static/index.html,
    src/pv_inverter_proxy/static/style.css,
    src/pv_inverter_proxy/static/app.js
  </files>
  <action>
    **Step 1 — index.html:** Add a new div INSIDE `<nav class="sidebar">` AFTER the existing `<div class="ve-sidebar-footer">...</div>` block (around line 50, before `</nav>`):

    ```html
    <!-- Phase 44 CHECK-01: Version display -->
    <div id="ve-version-footer" class="ve-version-footer" title="">
      <span class="ve-version-footer-text">v—</span>
    </div>
    ```

    Placement rationale: the sidebar has `sidebar-header` at top, `device-sidebar` (dynamic), `ve-sidebar-footer` (export/import). The version footer sits below export/import so it's the last visible element in the sidebar, matching typical admin footer convention (Pi-hole, Nextcloud, HA all put version here).

    **Step 2 — style.css:** Append these rules at the END of the file (keep them grouped with a comment header to make them discoverable):

    ```css
    /* Phase 44: Version footer (CHECK-01) + System sidebar group (CHECK-04) */

    .ve-version-footer {
      padding: 8px 16px;
      font-size: 0.8rem;
      color: var(--ve-text-dim);
      border-top: 1px solid var(--ve-border);
      background: var(--ve-bg-surface);
      font-family: var(--ve-mono);
      text-align: center;
      user-select: text;
    }

    .ve-version-footer--failed {
      color: var(--ve-orange);
    }

    .ve-version-footer-text {
      display: inline-block;
    }

    /* System sidebar group (CHECK-04): reuses existing ve-sidebar-group + ve-sidebar-device
       but the Software entry has a badge dot instead of a power reading. */
    .ve-sidebar-device--system-with-update .ve-dot {
      background: var(--ve-orange);
    }

    .ve-sidebar-device-github-link {
      margin-left: auto;
      color: var(--ve-text-dim);
      font-size: 0.75rem;
      text-decoration: none;
      padding: 2px 6px;
      border-radius: 4px;
      transition: color var(--ve-duration-fast) var(--ve-easing-default),
                  background var(--ve-duration-fast) var(--ve-easing-default);
    }

    .ve-sidebar-device-github-link:hover {
      color: var(--ve-blue-light);
      background: rgba(115, 162, 211, 0.08);
    }
    ```

    Zero hardcoded hex colors except the rgba override for the hover background, which derives from --ve-blue-light (#73A2D3) — this is the one documented exception pattern for transparent overlays in the existing codebase (grep `.ve-btn--save:hover` and similar for precedent).

    **Correction:** Avoid the rgba exception. Use `background: var(--ve-bg)` or the existing `ve-sidebar-device:hover` background. Check existing hover patterns first and reuse. If the existing sidebar device hover already styles the container, the link can inherit that. Simplest: set link hover to `color: var(--ve-blue-light); text-decoration: underline;` with NO background change. Remove the rgba line.

    Final revised rule:
    ```css
    .ve-sidebar-device-github-link:hover {
      color: var(--ve-blue-light);
      text-decoration: underline;
    }
    ```

    **Step 3 — app.js:** Four edits.

    **3a.** Near the module-level state declarations (top of file, look for existing `var _devices = [];` around line 10-30), add:
    ```javascript
    // Phase 44 CHECK-01/04: version footer + update badge state
    var _availableUpdateState = null;  // {current_version, current_commit, available_update, last_check_at, last_check_failed_at}
    ```

    **3b.** Add a new handler function. Place it near `renderSidebar` (around line 85, before the sidebar section). This function updates BOTH the footer and triggers a re-render of the sidebar (so the System group can appear/disappear).

    ```javascript
    // ===== Phase 44: Available Update handler =====

    function handleAvailableUpdate(data) {
        _availableUpdateState = data || null;
        renderVersionFooter();
        // Re-render sidebar so the SYSTEM group can appear/disappear
        renderSidebar();
    }

    function renderVersionFooter() {
        var footer = document.getElementById('ve-version-footer');
        if (!footer) return;
        var textSpan = footer.querySelector('.ve-version-footer-text');
        if (!textSpan) return;

        if (!_availableUpdateState) {
            textSpan.textContent = 'v—';
            footer.title = '';
            footer.classList.remove('ve-version-footer--failed');
            return;
        }

        var v = _availableUpdateState.current_version || 'unknown';
        var c = _availableUpdateState.current_commit;
        var text = 'v' + v;
        if (c) {
            text += ' (' + c + ')';
        }
        textSpan.textContent = text;

        // CHECK-06 indicator: last_check_failed_at sets tooltip + orange color
        if (_availableUpdateState.last_check_failed_at) {
            var when = new Date(_availableUpdateState.last_check_failed_at * 1000);
            footer.title = 'Letzter Update-Check fehlgeschlagen: ' + when.toLocaleTimeString();
            footer.classList.add('ve-version-footer--failed');
        } else if (_availableUpdateState.last_check_at) {
            var whenOk = new Date(_availableUpdateState.last_check_at * 1000);
            footer.title = 'Letzter Update-Check: ' + whenOk.toLocaleTimeString();
            footer.classList.remove('ve-version-footer--failed');
        } else {
            footer.title = '';
            footer.classList.remove('ve-version-footer--failed');
        }
    }
    ```

    **3c.** At the end of `renderSidebar(devices)` function (after the MQTT PUBLISH group append, BEFORE `highlightActiveSidebar()`), add the SYSTEM group:

    ```javascript
        // Phase 44 CHECK-04: SYSTEM group with Software entry (only when update available)
        if (_availableUpdateState && _availableUpdateState.available_update) {
            container.appendChild(createSystemSidebarGroup(_availableUpdateState.available_update));
        }

        // Update active highlight
        highlightActiveSidebar();
    ```

    And add a new helper function near `createSidebarGroup`:

    ```javascript
    function createSystemSidebarGroup(availableUpdate) {
        var group = document.createElement('div');
        group.className = 've-sidebar-group';

        var header = document.createElement('div');
        header.className = 've-sidebar-group-header';
        header.innerHTML = '<span>SYSTEM</span><span class="ve-sidebar-header-right"><span class="ve-chevron">&#9660;</span></span>';
        header.addEventListener('click', function() {
            var items = group.querySelector('.ve-sidebar-group-items');
            var chevron = header.querySelector('.ve-chevron');
            if (items.classList.contains('ve-sidebar-group-items--collapsed')) {
                items.classList.remove('ve-sidebar-group-items--collapsed');
                chevron.classList.remove('ve-chevron--collapsed');
            } else {
                items.classList.add('ve-sidebar-group-items--collapsed');
                chevron.classList.add('ve-chevron--collapsed');
            }
        });
        group.appendChild(header);

        var itemsContainer = document.createElement('div');
        itemsContainer.className = 've-sidebar-group-items';
        itemsContainer.appendChild(createSoftwareSidebarEntry(availableUpdate));
        group.appendChild(itemsContainer);
        return group;
    }

    function createSoftwareSidebarEntry(availableUpdate) {
        var entry = document.createElement('div');
        entry.className = 've-sidebar-device ve-sidebar-device--system-with-update';

        var label = 'Software';
        var tagName = availableUpdate.tag_name || availableUpdate.latest_version || '';
        var title = 'Update available: ' + tagName;
        entry.title = title;

        // Badge dot (inline style uses existing token only)
        var dotHtml = '<span class="ve-dot" style="background:var(--ve-orange)"></span>';

        var linkHtml = '';
        if (availableUpdate.html_url) {
            linkHtml = '<a class="ve-sidebar-device-github-link" href="' + esc(availableUpdate.html_url) + '" target="_blank" rel="noopener">GitHub &rarr;</a>';
        }

        entry.innerHTML =
            dotHtml +
            '<span class="ve-sidebar-device-name">' + esc(label) + '</span>' +
            linkHtml;

        return entry;
    }
    ```

    **3d.** Add the message type to the WebSocket onmessage handler (around line 323-340). Find the `ws.onmessage = function(event) { ... }` block and add a new `if` branch alongside the others:

    ```javascript
    if (msg.type === 'available_update') handleAvailableUpdate(msg.data);
    ```

    Place this next to the `device_list` handler for locality.

    **Integration note on init:** When the page loads, the WebSocket reconnect logic already sends all snapshot messages on (re)connect. Because Plan 44-02 extended ws_handler to send `available_update` on connect, the footer will populate on the initial connection. No explicit "load version from REST" call needed, but as a defense-in-depth fallback, also add a one-shot fetch at page load:

    Near the end of app.js (or wherever `connectWebSocket()` is called during init), add:

    ```javascript
    // Phase 44: initial version fetch fallback — WS push is the primary path,
    // this only runs if WS hasn't delivered within 2 seconds of page load.
    setTimeout(function() {
        if (_availableUpdateState === null) {
            fetch('/api/update/available')
                .then(function(r) { return r.ok ? r.json() : null; })
                .then(function(data) {
                    if (data && _availableUpdateState === null) {
                        handleAvailableUpdate(data);
                    }
                })
                .catch(function() { /* silent */ });
        }
    }, 2000);
    ```

    Why: if the WS connects but the initial available_update push is missed or delayed, this fallback guarantees the footer populates within ~2 seconds of page load. Cost is one HTTP GET in the degenerate case.

    **Zero build step:** these are plain file edits, served by `static_handler` via `importlib.resources`. Changes take effect on service restart (see Task 2).
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy &amp;&amp; python -c "from pathlib import Path; html = Path('src/pv_inverter_proxy/static/index.html').read_text(); assert 've-version-footer' in html; css = Path('src/pv_inverter_proxy/static/style.css').read_text(); assert 've-version-footer' in css; assert 've-sidebar-device--system-with-update' in css; js = Path('src/pv_inverter_proxy/static/app.js').read_text(); assert 'handleAvailableUpdate' in js; assert 'createSoftwareSidebarEntry' in js; assert \"msg.type === 'available_update'\" in js; assert 'renderVersionFooter' in js; print('ok')"</automated>
  </verify>
  <done>
    index.html has `#ve-version-footer` div. style.css has `.ve-version-footer` and `.ve-sidebar-device--system-with-update` rules using only `var(--ve-*)` tokens. app.js has `handleAvailableUpdate`, `renderVersionFooter`, `createSystemSidebarGroup`, `createSoftwareSidebarEntry`, the onmessage case, and the fetch fallback. No hardcoded hex colors introduced.
  </done>
</task>

<task type="auto">
  <name>Task 2: Deploy to LXC 192.168.3.191 and automated smoke verification</name>
  <files>
    (no file changes; deploys existing)
  </files>
  <action>
    **Step 1 — run deploy.sh:**
    ```bash
    cd /Users/hulki/codex/pv-inverter-proxy && ./deploy.sh
    ```

    `deploy.sh` per project memory pushes to 192.168.3.191 and restarts the service. It's the established auto-deploy path. Confirm deploy completes without error.

    **Step 2 — pip reinstall so importlib.metadata picks up 8.0.0:**

    Because pyproject.toml was bumped in Plan 44-02, the editable install needs to re-read the metadata. The deploy script MAY already do this; if it does not, run:

    ```bash
    ssh root@192.168.3.191 "cd /opt/pv-inverter-proxy && .venv/bin/pip install -e . --quiet && systemctl restart pv-inverter-proxy"
    ```

    Under the blue-green layout from Phase 43, `/opt/pv-inverter-proxy` is a symlink to the current release dir. The `pip install -e .` re-reads pyproject and updates the installed metadata entry. After restart, `importlib.metadata.version("pv-inverter-master")` returns `8.0.0`.

    **Step 3 — wait for service to stabilize (≤ 10 seconds) and smoke-check logs:**

    ```bash
    ssh root@192.168.3.191 "journalctl -u pv-inverter-proxy -n 40 --no-pager" 2>&1 | tee /tmp/pv-log.txt
    ```

    Grep for the expected markers:
    ```bash
    grep -E "version_resolved|update_scheduler_started" /tmp/pv-log.txt
    ```

    Expected output (paraphrased):
    - `version_resolved version=8.0.0 commit=<7char>`
    - `update_scheduler_started`

    If `version_resolved` shows `version=unknown`, the pip reinstall did not take effect — rerun Step 2 and check for errors.
    If `update_scheduler_started` is absent, the scheduler wiring failed — check log for exceptions around the line that creates `update_scheduler_task`.

    **Step 4 — smoke-check the REST endpoint:**

    ```bash
    curl -sS http://192.168.3.191/api/update/available | python -m json.tool
    ```

    Expected JSON shape:
    ```json
    {
        "current_version": "8.0.0",
        "current_commit": "abc123d",
        "available_update": null,
        "last_check_at": null,
        "last_check_failed_at": null
    }
    ```

    (`last_check_at` may still be `null` if fewer than 60 seconds have passed since service start — the scheduler has an initial delay.)

    After 60+ seconds:
    ```bash
    sleep 70 && curl -sS http://192.168.3.191/api/update/available | python -m json.tool
    ```

    Expected: `last_check_at` is now a UNIX timestamp, `available_update` may be populated if a GitHub release newer than 8.0.0 exists. In a clean environment with no release yet, `available_update` stays null.

    **Step 5 — smoke-check that scheduler actually reached GitHub:**

    ```bash
    ssh root@192.168.3.191 "journalctl -u pv-inverter-proxy --since '2 minutes ago' --no-pager | grep -E 'github|update_check'"
    ```

    Expected: either `github_release_not_modified` (304, ETag cache hit) OR a successful fetch with `update_available` or no log (success + no newer version). Look for ABSENCE of `update_check_iteration_failed` — if present, investigate the error.

    If network to api.github.com is unreachable from the LXC, you may see `github_request_timeout` or `github_client_error` — that's CHECK-06 working as designed. Document the LXC's outbound network state in the SUMMARY.

    Why these steps: CHECK-01/02/06 need live verification because unit tests mock the network. The LXC is the real environment.
  </action>
  <verify>
    <automated>curl -sS http://192.168.3.191/api/update/available -o /tmp/upd.json &amp;&amp; python -c "import json; d=json.load(open('/tmp/upd.json')); assert d['current_version']=='8.0.0', f'got {d[\"current_version\"]}'; assert d['current_commit'] is not None and len(d['current_commit'])&gt;=7, f'got {d[\"current_commit\"]}'; assert 'available_update' in d; assert 'last_check_at' in d; assert 'last_check_failed_at' in d; print('endpoint ok:', d)"</automated>
  </verify>
  <done>
    Service deployed and restarted. Journal shows `version_resolved version=8.0.0`. `curl /api/update/available` returns JSON with current_version=8.0.0 and a real 7-char commit hash. After 60+ seconds, the scheduler has performed at least one check (success or graceful failure). No crashes.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Human verification of version footer and (optional) badge</name>
  <what-built>
    Fully deployed Phase 44:
    - Plan 44-01 backend modules (version parser, GitHub client, scheduler) + tests
    - Plan 44-02 webapp wiring (pyproject 8.0.0, AppContext fields, /api/update/available, WS broadcast)
    - Plan 44-03 frontend (version footer, SYSTEM group with badge, CSS)
  </what-built>
  <how-to-verify>
    1. Open http://192.168.3.191 in a fresh browser tab (hard-refresh: Cmd+Shift+R / Ctrl+Shift+R to bypass cached static assets).

    2. **CHECK-01 — Version footer:**
       - Scroll the sidebar to the bottom.
       - Expected: you see `v8.0.0 (abc123d)` in small monospace dim text below the Export/Import buttons.
       - Hover the footer: tooltip shows `Letzter Update-Check: HH:MM:SS` (after 60+ seconds since service start) OR empty before the first check.
       - The text uses the existing `--ve-text-dim` color (subtle grey), not bright white. Consistent with Venus OS theme.

    3. **CHECK-06 — Failed check indicator (optional, skip if network is fine):**
       - Temporarily block outbound to api.github.com on the LXC: `ssh root@192.168.3.191 "iptables -A OUTPUT -d 140.82.0.0/16 -j DROP"` (NOTE: github's IPs rotate; this is a best-effort block).
       - Wait for the next scheduler iteration (up to 1 hour by default — for faster testing, consider setting a shorter interval in `_run_with_shutdown` manually and restart).
       - Alternative: directly POST an error state for verification; not needed for Phase 44 sign-off.
       - Acceptance: if you CAN trigger a failure, the footer should turn orange (`--ve-orange` via `ve-version-footer--failed` class) and the tooltip should show `Letzter Update-Check fehlgeschlagen: HH:MM:SS`.
       - UNBLOCK when done: `ssh root@192.168.3.191 "iptables -D OUTPUT -d 140.82.0.0/16 -j DROP"`.
       - If this step is skipped, note in approval message.

    4. **CHECK-04 — Orange badge (optional live test):**
       - This requires tagging a release newer than v8.0.0 on the GitHub repo.
       - Two options:
         a) **Tag a test release:** On your dev machine, `git tag v8.0.1-test && git push origin v8.0.1-test`, then create a GitHub release from that tag via `gh release create v8.0.1-test --title "Phase 44 test" --notes "Badge verification"`. Wait up to 1 hour OR restart the service so the scheduler check runs within 60s. Expected: after the next check, the sidebar shows a new "SYSTEM" group with a "Software" entry, the entry has an orange dot (`ve-dot` with `--ve-orange` background), and a "GitHub →" link that opens the release page in a new tab. After verification, delete the test release + tag.
         b) **Skip the live badge test for Phase 44 approval** and rely on the unit/integration tests from 44-01/44-02 plus a manual browser inspection of the code paths. Phase 46 will have more comprehensive UI verification.

    5. **Regression checks:**
       - Existing sidebar groups (INVERTERS, VENUS OS, MQTT PUBLISH) still render correctly.
       - Existing device dots + power values still update.
       - Export/Import buttons still work.
       - Dashboard page loads and shows live data.
       - No JavaScript console errors (open DevTools > Console; should be clean).

    6. **Confirm the curl shape once more from the browser host:**
       ```bash
       curl -sS http://192.168.3.191/api/update/available | python -m json.tool
       ```
       Expected: current_version="8.0.0", current_commit is a 7-char string, available_update is null or a populated dict depending on step 4, last_check_at is a number, last_check_failed_at is null (unless step 3 was attempted).

    **Record in approval message:**
    - Screenshot or text description of the footer
    - Whether CHECK-04 was tested live (step 4a) or deferred (step 4b)
    - Any console errors observed
    - Any regressions in existing UI
  </how-to-verify>
  <resume-signal>
    Type "approved" to complete Phase 44, OR describe issues to fix. Mention whether the live badge test (step 4a) was performed or deferred.
  </resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser DOM ↔ release_notes string (rendered by JS) | Phase 44 does NOT render release_notes HTML — only uses tag_name and html_url in the sidebar entry. body is stored in AppContext but NEVER interpolated into HTML in Phase 44. Phase 46 will add the Markdown renderer with HTML escape. |
| Browser ↔ html_url from GitHub API | Link rendered via `<a href="..." target="_blank" rel="noopener">`; `esc()` applied to prevent attribute injection. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-44-16 | T (Tampering) | Malicious html_url in GitHub response rendered as link | mitigate | Pass through existing `esc()` function before interpolation into href. `target="_blank" rel="noopener"` prevents tabnabbing. GitHub's public API can be trusted to return HTTPS URLs under github.com, but defense-in-depth applies. |
| T-44-17 | I (Information Disclosure) | release_notes body NOT rendered in Phase 44 | accept | Phase 44 deliberately does NOT render `body` anywhere in the DOM. Only `tag_name` and `html_url` reach the browser view. Prevents XSS via malicious release notes until Phase 46's Markdown renderer handles escaping. |
| T-44-18 | D (DoS) | Frequent sidebar re-render from re-received available_update messages | accept | renderSidebar is idempotent and cheap (re-creates ~5 DOM nodes). Server broadcasts only on change (coarse-grained). Worst case: one re-render per minute. |
| T-44-19 | T (Tampering) | app.js fetch fallback could loop if API returns 200 with unexpected shape | mitigate | setTimeout runs once, not on an interval. If the response is malformed, `handleAvailableUpdate({})` sets `_availableUpdateState = {}` and renderVersionFooter shows `vunknown`. No loop. |
</threat_model>

<validation_strategy>
## Nyquist Validation — Requirements → Tests

| Requirement | Validation Type | Test Location | What It Proves |
|-------------|----------------|---------------|----------------|
| CHECK-01 (version in footer) | Static check + integration (LXC curl) + human verify | Task 1 automated grep + Task 2 curl + Task 3 browser | Footer shows "v8.0.0 (commit)" |
| CHECK-04 (orange ve-dot on System entry + release notes) | Code review + optional live tag test | Task 1 automated grep + Task 3 step 4 | SYSTEM sidebar group appears only when `_availableUpdateState.available_update` is non-null, orange dot via var(--ve-orange), GitHub link with rel="noopener". Release notes FULL rendering deferred to Phase 46 per phase scope. |

CHECK-04 is partially delivered in Phase 44: the badge and the GitHub link land here. Full inline Markdown rendering of release notes lands in Phase 46 (the confirmation modal). Phase 44 scope document explicitly defers this. Note in SUMMARY.

Per-task Nyquist: Task 1 has an automated grep verification for all expected tokens. Task 2 has an automated curl + JSON shape check. Task 3 is the checkpoint that cannot be automated (visual verification).
</validation_strategy>

<rollback_plan>
**Frontend-only rollback:** `git checkout src/pv_inverter_proxy/static/`. The backend (44-01/44-02) is already deployed and remains functional — the REST endpoint still works, scheduler still runs. The old frontend simply doesn't display the version footer but also doesn't crash.

**Full Phase 44 rollback:** Revert all three plans in reverse order (44-03 → 44-02 → 44-01):
```bash
git revert <44-03-commit> <44-02-commit> <44-01-commit>
./deploy.sh
ssh root@192.168.3.191 "cd /opt/pv-inverter-proxy && .venv/bin/pip install -e . --quiet && systemctl restart pv-inverter-proxy"
```

**Blue-green safety net:** Phase 43 installed the release layout. If the deploy corrupts the service, `ln -sfn /opt/pv-inverter-proxy-releases/<previous-release> /opt/pv-inverter-proxy-releases/current && systemctl restart pv-inverter-proxy` flips back instantly.

**State file cleanup (optional):** The scheduler persists ETag to `/etc/pv-inverter-proxy/update-state.json`. On rollback to pre-44 code, this file is harmless (no one reads it). Leave it or delete with `rm /etc/pv-inverter-proxy/update-state.json`.
</rollback_plan>

<verification>
- `curl -sS http://192.168.3.191/api/update/available` returns JSON with current_version="8.0.0" and a 7-char commit
- `journalctl -u pv-inverter-proxy -n 200` shows `version_resolved version=8.0.0`, `update_scheduler_started`, and within 120s at least one successful fetch attempt
- Browser at http://192.168.3.191 shows the version footer in the sidebar after hard refresh
- DevTools Console is free of JavaScript errors
- Existing dashboard, device groups, and config pages still function correctly
- `grep -c 've-version-footer' src/pv_inverter_proxy/static/app.js` returns ≥ 1
- No new npm dependencies (frontend is vanilla JS — hard rule)
- No hardcoded hex colors in the added CSS (only `var(--ve-*)` tokens)
</verification>

<success_criteria>
Plan 44-03 and Phase 44 are complete when:
- Version footer renders "v8.0.0 (commit)" in the sidebar on the live LXC
- SYSTEM sidebar group + Software entry + orange badge code paths exist and render conditionally (verified either live via test tag or via code review)
- Phase 44 scheduler has run at least one GitHub check on the live LXC without crashing
- Full backend + frontend deployed to 192.168.3.191
- No regressions in existing UI
- CHECK-01 and CHECK-04 (badge portion) are delivered; release notes Markdown rendering deferred to Phase 46 per phase scope
- Human verification approved in Task 3
- SUMMARY.md written with deployment log, screenshot reference, and phase-close notes
</success_criteria>

<output>
Create `.planning/phases/44-passive-version-badge/44-03-SUMMARY.md` with:
- Frontmatter: modified files (index.html, app.js, style.css), `provides: ["version footer rendering", "SYSTEM sidebar group with update badge", "client-side available_update state handler"]`
- `affects:` Phase 46 ("Will extend SYSTEM sidebar group Software entry with click handler → /system/software page; will render release_notes body via Markdown subset renderer; will add CHECK now button wired to a new POST /api/update/check endpoint")
- `key-decisions:`
  - "Release notes Markdown rendering deliberately deferred from Phase 44 to Phase 46 per phase scope document. Phase 44 shows only tag_name + GitHub link on the Software sidebar entry."
  - "Added 2s fetch fallback on page load in case the WS initial push is missed — single shot, no loop"
  - "Version footer uses --ve-mono font token to match register-viewer styling convention"
  - "CHECK-06 failed-check indicator: footer text turns orange via ve-version-footer--failed class, tooltip shows last failure timestamp"
- Deployment log: deploy.sh output summary + journalctl excerpts showing version_resolved + update_scheduler_started
- Live test outcome: was step 4a (test tag) performed? Did the badge appear? If deferred, note so.
- Phase 44 CLOSE checklist:
  - [ ] CHECK-01 version displayed in footer ✓/✗
  - [ ] CHECK-02 scheduler running as asyncio task ✓/✗
  - [ ] CHECK-03 GitHub client sends required headers + ETag ✓/✗ (unit + live log)
  - [ ] CHECK-04 badge renders (live OR code review) ✓/✗
  - [ ] CHECK-05 /api/update/available returns expected shape ✓/✗
  - [ ] CHECK-06 failed check tolerated, last_check_failed_at surfaced ✓/✗
  - [ ] CHECK-07 scheduler defers when WS client connected ✓/✗
</output>