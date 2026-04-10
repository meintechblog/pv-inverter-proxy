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

## Phase 43-04 Deploy Follow-ups (for Phase 45)

### deploy.sh should create /var/lib/pv-inverter-proxy before systemctl restart

- **Discovered during:** 43-04 Task 6 LXC deploy
- **Status:** Known gap in deploy.sh, not a blocker but caused a 5-minute diagnostic detour
- **Details:** Phase 43-03 hardened unit file has
  `ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy`. systemd
  refuses to start the service (`status=226/NAMESPACE`) if the
  ReadWritePaths directory does not exist. deploy.sh copies the unit file
  and restarts the service but does not create the state dir; install.sh
  creates it but deploy.sh does not run install.sh. For the LXC verification
  run, I manually created the dir via ssh before the restart succeeded.
- **Proposed fix (Phase 45):** Add these two lines to the post-sync INSTALL
  block in deploy.sh, immediately before the daemon-reload:
  ```bash
  install -d -o root -g pv-proxy -m 2775 /var/lib/pv-inverter-proxy
  install -d -o root -g pv-proxy -m 2775 /var/lib/pv-inverter-proxy/backups
  ```
  Alternatively: have deploy.sh refuse to run if it detects a pre-migration
  flat layout, forcing users through install.sh exactly once. Cleaner.
- **Scope:** Defer to Phase 45 or earlier if a fresh LXC deploy is needed.

### 15-second graceful-stop timeout hit during every restart

- **Discovered during:** 43-04 Task 6 LXC deploy
- **Status:** Pre-existing latency issue surfaced by the new TimeoutStopSec=15
- **Details:** Journal shows `graceful_shutdown_starting` at T+0, then
  `mqtt_publisher_stopped` at T+0.0s, then nothing until `TimeoutStopSec=15`
  forces SIGKILL at T+15s. The 15-second gap is unexplained teardown work.
  Prior unit file had TimeoutStopSec=90, so the issue was always there but
  hidden by the larger ceiling. The new 15s ceiling is now consistently hit.
- **Impact:** Adds ~15 seconds to every service restart, including Phase 45
  updates. This is the biggest single contributor to Venus OS disconnect
  window during updates. Phase 45 should reduce this to <5s or fall back
  to SIGKILL-before-flip.
- **Proposed investigation (Phase 45):** Add structlog events around each
  teardown step in `run_with_shutdown`: after `heartbeat_task` cancel, after
  `runner.cleanup()`, after `registry.stop_all()`, after `server_task` cancel.
  The gap will point at the blocking await.
- **Scope:** Phase 45 restart-safety work.

### LXC release dir cosmetically named v0.0-nosha

- **Discovered during:** 43-04 Task 6 LXC deploy
- **Status:** Cosmetic — functionally correct, just wrong name
- **Details:** The migration was run from a worktree deploy where the `.git`
  pointer file was shipped (pre-fix for commit db4cd8a). git commands on
  the LXC failed with "not a git repository" because the pointer target
  path doesn't exist on the LXC. install.sh migration fell through to
  defensive fallbacks: `v0.0-nosha`. The release dir works fine; only the
  name is wrong.
- **Fix:** The next deploy+migration from a clean main checkout (after
  Phase 43 merges to main) will create a properly-named release dir
  (`v7.0-<sha>` or similar). The stale `v0.0-nosha` dir will be naturally
  pruned by the Phase 45 retention logic (`select_releases_to_delete` with
  `keep=3`) after enough releases accumulate.
- **Scope:** No action needed. Will self-heal after the next real deploy.

### chown -R pv-proxy:pv-proxy on LXC /opt/pv-inverter-proxy root directory

- **Discovered during:** 43-04 Task 6 pre-check
- **Status:** Pre-existing — the LXC's /opt/pv-inverter-proxy/ was owned
  501:staff (rsync preservation of local dev user) instead of root:root
  or pv-proxy:pv-proxy. git complained about "dubious ownership".
- **Fix:** Corrected during migration — the migrated release dir is now
  owned pv-proxy:pv-proxy. No future action needed.
- **Scope:** Self-healed.
