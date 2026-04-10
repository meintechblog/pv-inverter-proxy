# Feature Research — v8.0 Auto-Update System

**Domain:** In-webapp auto-update for self-hosted Python service on LXC
**Researched:** 2026-04-10
**Confidence:** HIGH (patterns well-established across Home Assistant, Nextcloud, UniFi, Pi-hole, OctoPrint)

## Scope

New features to add on top of the existing pv-inverter-proxy webapp (device-centric SPA, vanilla JS, WebSocket push, Venus-OS themed dark UI, systemd service, `/etc/pv-inverter-proxy/config.yaml` preserved across updates).

Research focus: how do mature self-hosted projects handle in-app updates, and which of those patterns should the Fronius Proxy adopt?

## Feature Landscape

### Table Stakes (Users Expect These)

Missing these and the update experience feels broken or amateurish. Every mature self-hosted project in the comparison set ships all of these.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Current version display | User must know what they run before deciding to update. Shown on every comparable project (Pi-hole admin footer, Nextcloud admin/Version, UniFi header). | LOW | Read from `pyproject.toml` / package metadata at startup, expose via `/api/version`. Display in sidebar footer and settings page. |
| Available version display | Core value of the feature — "what would I get if I clicked update?" | LOW | GitHub Releases API: `GET /repos/{owner}/{repo}/releases/latest`, cache 15 min to stay under 60 req/h unauthenticated rate limit. |
| "New version available" badge | Passive discovery — user shouldn't have to hunt for updates. HA, Nextcloud, UniFi, Pi-hole all show a persistent visual cue. | LOW | Small orange dot on a new "System" sidebar entry when `latest > current`. Disappears after update. |
| Update button with confirmation | Explicit consent before destructive operation. Single-click install without confirmation is universally rejected as unsafe. | LOW | Modal with version from→to, changelog, Cancel (default focus) + Install button. No "type to confirm" — too much friction for a routine operation. |
| Progress indicator during update | Updates take 30-90 s. Without feedback user assumes it hung and refreshes, mid-update → corruption. | MEDIUM | WebSocket-streamed status messages: "Downloading" → "Backing up" → "Installing" → "Restarting" → "Health check" → "Done". Existing WS infra already pushes snapshots; add `update_progress` message type. |
| Success / failure toast | Close-the-loop confirmation. Existing project already has toast stacking system (v2.1) — reuse it. | LOW | Green toast "Updated to vX.Y.Z", red toast "Update failed: reason" with link to log. |
| Config preservation during update | A proxy that forgets its inverters is useless. Every mature updater protects user data. | MEDIUM | `/etc/pv-inverter-proxy/config.yaml` lives outside the code tree — already decided in PROJECT.md. Updater must NEVER touch it. Test case: update with non-default config, verify survives. |
| Pre-update backup of code tree | Without a backup, rollback is impossible. Nextcloud creates `backups/nextcloud-CURRENTVERSION/`, greenboot uses btrfs snapshots. | MEDIUM | Copy `/opt/pv-inverter-proxy` to `/var/lib/pv-inverter-proxy/backups/v{current}-{timestamp}/` before `git pull`. Prune to last 3 to cap disk usage. |
| Post-update health check | If the new version crashes on boot, user is locked out. HA, greenboot, openSUSE health-checker all gate success on a post-restart probe. | MEDIUM | After `systemctl restart`, poll `/api/health` for up to 30 s. If it never returns 200 → rollback. |
| Automatic rollback on health check failure | The difference between "auto-update" and "auto-brick". Non-negotiable for a headless LXC where SSH is the recovery path. | MEDIUM | On failed health check: restore `/opt/pv-inverter-proxy` from backup dir, `systemctl restart`, log as rolled-back, show red toast on next page load. |
| Root-capable update helper | The `pv-proxy` systemd user has no sudo. `git pull` + `systemctl restart pv-inverter-proxy` must be performed as root. | MEDIUM | Separate oneshot systemd unit `pv-inverter-proxy-update.service` (run as root, triggered from the app). App writes an "update request" marker file, a `.path` unit picks it up, or simpler: app talks to a small root helper over a unix socket with `SocketMode=0660` and `SocketGroup=pv-proxy`. |

### Differentiators (Competitive Advantage)

Features that turn an OK updater into one that feels polished and trustworthy. Not strictly required for v8.0 but each has high perceived value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Inline changelog / release notes preview | User can read what changed before committing. Drives informed consent, not blind clicks. HA and UniFi both prominently show release notes in the update modal. | MEDIUM | GitHub API returns `body` as GitHub-flavored Markdown. Minimal vanilla JS renderer: handle headings, lists, bold, inline code, links (~80 LOC). Do NOT pull in `marked.js` — breaks zero-deps rule. Alternative: render as pre-formatted text and link "View full release on GitHub". |
| Update history log | "When did it last update, did it work, why did it roll back?" Builds trust after a bad update. | LOW | JSON file at `/var/lib/pv-inverter-proxy/update-history.json`, append-only, last 20 entries. Fields: timestamp, from_version, to_version, outcome (success / rolled-back / failed), duration_s, rollback_reason. Display in a System > Update History table. |
| Last-check timestamp visible in UI | Transparency about staleness. "Last checked: 12 min ago" is the difference between "is this thing alive" and "I trust this". | LOW | Store in-memory after every check, render as relative time near the version badge with a manual "Check now" button. |
| Background scheduler with user control | Auto-discovery of new releases without user babysitting, BUT always under user control. HA default is "notify only"; UniFi allows notify / auto. | MEDIUM | Three modes in config: `off` / `check_only` (default) / `check_and_notify`. NEVER auto-install silently. Interval: 24 h default, configurable. Implement as an asyncio task in the existing aiohttp app — no new systemd timer needed. |
| Pre-release / beta opt-in channel | Power users want to help test. Fits the "self-hosted tinkerer" audience. Pi-hole, HA, UniFi all offer release channels. | LOW | Toggle in System settings: "Include pre-releases". When on, use `GET /releases` and pick the first matching entry instead of `/releases/latest`. Off by default. |
| Cancel button during update | Escape hatch before the destructive step. Most mature updaters expose this at least during "downloading" phase. | MEDIUM | Cancel allowed only in phases before `git pull` commits. After that → cancel is disabled and shown as "Cannot cancel now". |
| Disk-space pre-check | Updates that die halfway through because `/opt` is full are the most painful class of failure. LXC containers with tight root disks are common. | LOW | `shutil.disk_usage()` on `/opt` and `/var/lib/pv-inverter-proxy/backups`. If <100 MB free → block update with a clear error. |
| Service status card after update | Post-update visibility: "All 4 devices reconnected, Venus OS still green, aggregation producing data". | MEDIUM | Reuse existing device connection dots. Show a green banner "Updated successfully — all devices healthy" once every device reconnects, with a 10 s timeout that shows a warning if any device is still down. |
| "Skip this version" option | User evaluates release notes, decides to wait. Without skip, badge nags forever. HA and many OS updaters offer this. | LOW | Button in the update modal: "Not now" (badge stays) vs "Skip v8.1.2" (badge hides until next release). Persist in config. |
| Download progress percent | Feels more responsive than a generic spinner, especially if git clone is slow over a rural uplink. | MEDIUM | `git pull` doesn't easily stream progress. Alternative: use the Release tarball (`tarball_url`) via aiohttp streaming + Content-Length → real percent. Tradeoff: switches from git-based updates to tarball-based updates. Probably NOT worth the architectural change. Keep spinner + phase text. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Silent auto-install on schedule | "Set and forget" — the dream of Watchtower-style automation | Breaks the Core Value. An auto-update that wedges the proxy during a solar-generation peak means unmonitored power, lost throttle commands, and a confused Venus OS. User-visible ops on a critical energy device MUST be consensual. HA explicitly made Supervisor auto-update opt-out-able for this reason, and most users disable it. | Scheduled **check** with a visible badge, manual install. "Check and notify" is the ceiling. |
| Forced updates on minor versions | "Users never update, make them" | This proxy is infrastructure, not a consumer app. Forcing a restart during solar production = real kWh lost. User runs their house. | Strong nudges (badge, optional email), never force. |
| Auto-reboot of the whole LXC | Some updates "feel cleaner" with a full reboot | Destroys MQTT session, disconnects Venus OS, triggers downstream reconnect storms. A `systemctl restart pv-inverter-proxy` is surgical and sufficient. | `systemctl restart` only. Document that a manual LXC reboot is never needed. |
| In-app package manager / dependency updates | "Update pymodbus too while you're at it" | Massive blast radius, not solving the user's actual problem (new features of *this* project). pip dependency conflicts are the #1 cause of broken Python self-hosted deployments. | Pin dependencies in `pyproject.toml`, update them in a normal code release, let the updater apply that release like any other. |
| Arbitrary-version downgrade via UI | "Roll back to v4.0 from v8.0" | Schema migrations, config drift, dropped fields — Nextcloud explicitly refuses this and documents "downgrades corrupt data". | Rollback is only to the one pre-update backup (N-1), and only within the health-check window. For older versions: git checkout manually. |
| "Update all devices" button that restarts inverters | Scope creep: conflating proxy update with firmware updates | Firmware is out of scope — the proxy is a translator, not a device manager. | Keep scope strictly to the proxy service itself. |
| Type-the-version-to-confirm dialog | "Extra safety" | Too much friction for a routine weekly operation; users develop copy-paste muscle memory that defeats it (NN/G finding: novel confirms only work when rare). The update is reversible via rollback, so it doesn't meet the "truly irreversible" bar where type-to-confirm earns its keep. | Normal modal with safe default focus on Cancel, clear from→to version, list of changes. |
| Patch notes delivered as an external link only | "Simpler, just link to GitHub" | Every click that leaves the app is a chance the user doesn't come back. Defeats the informed-consent goal. | Render inline. Link to GitHub as secondary "full release notes" link. |
| Opening a terminal / shell over the web | "Let me debug when an update fails" | Massive security and scope hole. Explicitly out of scope in PROJECT.md (no auth, LAN-only). | Surface logs via a read-only "View update log" link in the history entry. |

## Feature Dependencies

```
[Current version display]
    └──required by──> [Available version display]
                            └──required by──> [Update badge]
                                                   └──required by──> [Update button]
                                                                          └──required by──> [Confirmation modal w/ changelog]
                                                                                                 └──required by──> [Update flow]

[Root-capable update helper] ──required by──> [Update flow]
[Pre-update backup]          ──required by──> [Update flow] ──required by──> [Automatic rollback]
[Post-update health check]   ──required by──> [Automatic rollback]
[WebSocket progress stream]  ──required by──> [Progress indicator]

[Background scheduler] ──enhances──> [Update badge] (keeps it fresh)
[Update history log]   ──enhances──> [Update flow]  (post-hoc visibility)
[Last-check timestamp] ──enhances──> [Background scheduler]
[Pre-release channel]  ──enhances──> [Available version display]
[Skip this version]    ──enhances──> [Update badge]

[Silent auto-install] ──conflicts──> [Manual confirmation]  (philosophically incompatible)
```

### Dependency Notes

- **Root helper gates everything.** Until you can `git pull` and `systemctl restart` from the webapp's user context, no update flow works. This is the single biggest unknown in v8.0 and must land first.
- **Backup + health check + rollback are one cluster.** Shipping any one without the others gives false confidence. If health check is missing, a broken update silently succeeds. If backup is missing, rollback has nothing to restore. Treat as a single phase.
- **Changelog rendering is independent of update mechanics.** Can be built and shipped standalone (just fetches GitHub API, renders to modal). Good candidate for early UI work to de-risk the Markdown-in-vanilla-JS piece.
- **Background scheduler is pure polish on top of a working manual flow.** Not needed to validate the core value. Ship manual-check-only first, add scheduler last.

## MVP Definition

### Launch With (v8.0 — minimum useful updater)

- [x] Current + available version display — user can see where they stand
- [x] "Check for updates" button (manual trigger) — no scheduler yet
- [x] "New version available" badge on System sidebar entry — passive discovery
- [x] Update confirmation modal with version from→to and changelog preview — informed consent
- [x] Changelog rendering from GitHub API (minimal Markdown subset) — trust building
- [x] Root-capable update helper (systemd socket-activated or polled marker file) — the enabler
- [x] Pre-update backup of `/opt/pv-inverter-proxy` — rollback substrate
- [x] Disk-space pre-check — fail fast on LXC with tight root
- [x] WebSocket progress indicator with phase text — not-hung feedback
- [x] Post-update `/api/health` probe with 30 s timeout — correctness gate
- [x] Automatic rollback on health failure — safety net
- [x] Success / failure toast reusing existing toast system — closes the loop
- [x] Config preservation verified end-to-end — non-negotiable

### Add After Validation (v8.1)

- [ ] Update history log (last 20 entries, JSON on disk, table UI) — trigger: first rollback event in the wild
- [ ] Background scheduler (`check_only` default, 24 h interval, last-check timestamp) — trigger: users ask "how do I know if I'm behind?"
- [ ] "Skip this version" — trigger: persistent badge complaints
- [ ] Service-health banner after update (device reconnect confirmation) — trigger: silent post-update breakage reports

### Future Consideration (v8.2+)

- [ ] Pre-release / beta channel toggle — trigger: enough users to want a test group
- [ ] Email / MQTT notification of available update — trigger: user who runs proxy unattended for months
- [ ] Cancel-during-download — trigger: slow-network users complaining about commitment cost

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Root-capable update helper | HIGH | MEDIUM | P1 |
| Current/available version display | HIGH | LOW | P1 |
| Update button + confirmation modal | HIGH | LOW | P1 |
| Pre-update backup | HIGH | MEDIUM | P1 |
| Post-update health check | HIGH | MEDIUM | P1 |
| Automatic rollback | HIGH | MEDIUM | P1 |
| WebSocket progress indicator | HIGH | LOW | P1 (reuses existing WS infra) |
| Changelog preview in modal | HIGH | MEDIUM | P1 (vanilla MD renderer is the cost driver) |
| "New version available" badge | HIGH | LOW | P1 |
| Config preservation verification | HIGH | LOW | P1 |
| Disk-space pre-check | MEDIUM | LOW | P1 |
| Update history log | MEDIUM | LOW | P2 |
| Background scheduler | MEDIUM | MEDIUM | P2 |
| Last-check timestamp | MEDIUM | LOW | P2 |
| Service-health banner after update | MEDIUM | MEDIUM | P2 |
| Skip this version | LOW | LOW | P3 |
| Pre-release channel | LOW | LOW | P3 |
| Cancel during download | LOW | MEDIUM | P3 |

**Priority key:** P1 = must have for v8.0 launch. P2 = v8.1 polish. P3 = defer until user demand is clear.

## Competitor Feature Analysis

Named projects converged on a very similar pattern. Where they diverge, the self-hosted-infrastructure flavor (HA, Pi-hole) is the better template for this project than the SaaS flavor (Nextcloud, UniFi-cloud).

| Feature | Home Assistant | Pi-hole | Nextcloud | UniFi Controller | Our Approach |
|---------|----------------|---------|-----------|------------------|--------------|
| Version badge location | Sidebar + update center | Admin footer + banner | Admin > Overview top banner | Header icon + device table | Sidebar "System" entry with orange dot |
| Update trigger | Click in update center → modal | `pihole -up` CLI or Settings button | Run updater button → stepper UI | Update button per device | Single Install button in modal |
| Changelog shown inline? | Yes, truncated + "Read more" | No (linked) | Yes, full | Yes, in release notes pane | Yes, rendered GitHub Markdown (minimal subset) |
| Pre-update backup | Snapshot of whole HA config | No (relies on git) | Copy of code tree to `backups/` | Config backup file | Copy of `/opt/pv-inverter-proxy` to `backups/v{ver}-{ts}/` |
| Health check post-update | Core startup probe | None (bash script exits non-zero) | DB migration check | Device "provisioning" state | `/api/health` poll with 30 s timeout |
| Automatic rollback | Yes (snapshot restore) | No | No ("downgrade not supported") | Limited | Yes, from backup dir, within health window |
| Scheduled auto-check | Yes, configurable | Yes, via cron | Yes, cron hook | Yes, configurable | Optional, `check_only` default, 24 h |
| Silent auto-install | Opt-in per-component | Opt-out default (cron) | Opt-in | Opt-in | **Never** — explicit anti-feature |
| Release channel | Stable / beta / dev | Master / devel | Stable / beta / daily | LTS / Stable / RC | Stable only in v8.0, pre-release toggle in v8.2+ |
| Update history visible | Yes, in logbook | Hidden in `/var/log` | Partial (updater.log) | Yes | JSON file + table UI (P2) |
| Confirm strength | Single modal | CLI prompt (y/N) | Multi-step stepper | Single modal | Single modal, default focus on Cancel |

**Key takeaways for this project:**
1. **Inline changelog is now standard** — users expect it, skipping it feels cheap.
2. **Rollback is the dividing line** between "amateur" and "professional" self-hosted updaters. Pi-hole and Nextcloud are often criticized for not having it; HA gets praised for having it. We should be on the HA side.
3. **Auto-install is universally opt-in where it exists, and often disabled.** Defaulting to notify-only aligns with user expectations for infrastructure.
4. **No one does type-to-confirm for updates.** It's reserved for deletions. Don't invent friction users don't expect.
5. **A single modal with a default-Cancel focus** is the industry norm for confirming updates. Carbon, NN/G, and Shadcn all recommend it for reversible destructive actions.

## UX Recommendations (Concrete)

### Where the "new version" signal lives

**Recommendation:** New sidebar section "SYSTEM" below MQTT PUBLISH, with a "Software" entry. Orange `ve-dot` on that entry when `latest > current`. No persistent top banner — would clash with the existing Venus-OS auto-detect banner and MQTT gate overlay. No modal on page load — disruptive for a dashboard users leave open all day.

### Update page layout (`#system/software`)

```
+-- System: Software Updates ------------------------------+
|                                                          |
|  Current version:   v8.0.2                               |
|  Latest version:    v8.1.0   [New version available]    |
|  Last checked:      12 min ago       [Check now]        |
|                                                          |
|  +-- Release notes: v8.1.0 ----------------------+       |
|  | ## Added                                      |       |
|  | - Sungrow per-device aggregate toggle         |       |
|  | - Auto-update from the webapp                 |       |
|  | ## Fixed                                      |       |
|  | - Venus OS reconnect after MQTT restart       |       |
|  |                               [View on GitHub]|       |
|  +-----------------------------------------------+       |
|                                                          |
|                         [Cancel]  [Install v8.1.0]      |
|                                                          |
|  -------------------------------------------------       |
|                                                          |
|  Update History                                          |
|  v8.0.2 -> v8.0.1    2026-04-08 14:22   Rolled back     |
|  v8.0.1 -> v8.0.0    2026-04-07 09:10   Success (43s)   |
|  ...                                                     |
+----------------------------------------------------------+
```

### Confirmation modal content

- Title: `Install version X.Y.Z`
- Body: version from→to, full changelog (scrollable), disk-space-OK indicator, warning line "The proxy will restart. Venus OS will briefly show the inverter as offline (~10 s)."
- Buttons: `Cancel` (default focus, transparent) + `Install` (primary blue). No type-to-confirm.

### Progress modal (after Install clicked)

- Takes over the update page, not a blocking modal overlay (user can still navigate away and come back — WS state is server-side).
- Phase list with check marks as each completes:
  - [x] Disk space OK
  - [x] Backup created
  - [x] Code downloaded
  - [ ] Installing
  - [ ] Restarting
  - [ ] Health check
- Live phase text pulled from WS `update_progress` messages.
- On success: green toast + auto-redirect to the device dashboard.
- On failure with rollback: red toast + inline rollback card showing which phase failed.

### Markdown rendering (vanilla JS, zero deps)

Minimal subset sufficient for GitHub release notes:
- `#`, `##`, `###` → `<h3>` / `<h4>` / `<h5>` (don't use `h1` / `h2` — clashes with page title)
- `**bold**` → `<strong>`
- `` `code` `` → `<code>`
- `- item` / `* item` → `<ul><li>`
- `[text](url)` → `<a href target="_blank" rel="noopener">`
- Line breaks → `<br>` within paragraphs
- HTML-escape everything first to prevent XSS from a malicious release body
- Total: ~80 LOC, lives in `static/app.js` as `renderMarkdown(src)`

Everything else (tables, images, code blocks, nested lists) → render as plain text. Ship the "View on GitHub" link for users who want full fidelity.

## Open Questions for Roadmap

1. **Update helper transport:** unix socket with a tiny root daemon, polled marker file with a systemd `.path` unit, or a one-shot systemd unit triggered via D-Bus? Needs architecture research (ARCHITECTURE.md territory, not features).
2. **Git-based vs tarball-based updates:** git is simpler (user likely installed via `git clone`) but loses download progress. Tarball gives real percent but means shipping releases properly. Default assumption: git-based, matching existing curl-one-liner install.
3. **What exactly does `/api/health` check?** All devices connected? At least one device connected? Just "the event loop is alive"? Too strict and rollback fires on unrelated device issues; too loose and broken updates pass. Suggested: "event loop responds + config loads + at least the virtual device exists". Validate in phase planning.
4. **Where is the backup directory?** `/var/lib/pv-inverter-proxy/backups/` is the Debian-idiomatic choice, but requires the package to create it on install. Alternative: `/opt/pv-inverter-proxy/.backups/` (inside the tree), cleaner install but nests backups inside the thing being backed up, which is smelly. Recommend `/var/lib/`.

## Sources

- [Home Assistant Supervisor Releases](https://github.com/home-assistant/supervisor/releases) — update flow, release channels, opt-out auto-update
- [Home Assistant 2026.2 Release Notes](https://www.home-assistant.io/blog/2026/02/04/release-20262/) — Apps panel integration, update UX
- [Nextcloud Built-in Updater](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/upgrade.html) — maintenance mode, backup step, rollback policy ("not supported")
- [Nextcloud Updater GitHub](https://github.com/nextcloud/updater) — reference implementation of pre-update backup flow
- [Pi-hole Updating Docs](https://docs.pi-hole.net/main/update/) — CLI-first update model, no inline rollback
- [Pi-hole v6.3 Release](https://pi-hole.net/blog/2025/10/25/pi-hole-ftl-v6-3-web-v6-3-and-core-v6-2-released/) — current release cadence
- [Pi-hole Feature Request: Update Button in Webinterface](https://discourse.pi-hole.net/t/feature-request-reboot-and-update-button-in-webinterface/67623) — community demand for in-app updates
- [UniFi Updates Documentation](https://help.ui.com/hc/en-us/articles/7605005245975-UniFi-Updates) — release channel picker, auto-update opt-in
- [UniFi Advanced Updating Techniques](https://help.ui.com/hc/en-us/articles/204910064-UniFi-Advanced-Updating-Techniques) — rollback caveats
- [GitHub REST API — Releases](https://docs.github.com/en/rest/releases/releases) — endpoints, response shape (tag_name, name, body, published_at, html_url, prerelease), anonymous access for public repos
- [openSUSE health-checker](https://github.com/openSUSE/health-checker) — post-update health probe pattern, systemd integration
- [Fedora greenboot](https://github.com/fedora-iot/greenboot) — health-check → auto-rollback framework, the gold standard
- [Nielsen Norman Group: Confirmation Dialogs](https://www.nngroup.com/articles/confirmation-dialog/) — when to use normal confirms vs type-to-confirm, default focus guidance
- [Carbon Design System: Dialog Pattern](https://carbondesignsystem.com/patterns/dialog-pattern/) — modal UX for destructive actions
- [Appcues: UI Patterns for Product Updates](https://www.appcues.com/blog/choosing-the-right-ui-pattern-for-your-product-update) — modal vs banner vs tooltip tradeoffs
- [Twenty Feature Request: One-Click Auto-Update](https://github.com/twentyhq/twenty/issues/19091) — contemporary 2025 discussion of self-hosted update UX
- [Watchtower: Automatic Docker Container Updates](https://kx.cloudingenium.com/watchtower-automatic-docker-container-updates-notifications/) — cautionary tale on silent auto-updates

---
*Feature research for: v8.0 Auto-Update System, pv-inverter-proxy webapp*
*Researched: 2026-04-10*
