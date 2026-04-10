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

## install.sh re-run fails on blue-green deployed hosts

- **Symptom:** `./deploy.sh` pushes via rsync (which excludes `.git/`), so the
  resolved target of `/opt/pv-inverter-proxy -> releases/current/<release>/`
  has no `.git`. Running `install.sh` on such a host trips the guard at
  install.sh:86:

      install_root /opt/pv-inverter-proxy is a symlink but target has no .git (corrupt layout?)

  This makes it impossible to run the full installer on a deployed LXC to
  pick up new install.sh changes (like Plan 45-02's Step 6b file perms).
  - Discovered during: Plan 45-02 Task 4 LXC smoke test
  - Workaround used: Applied Step 6b block manually via `ssh root@lxc bash -s`
  - Scope: install.sh early-exit guard is too strict for rsync-deployed hosts
  - Action: Either (a) relax the guard to accept `.git`-less release dirs, or
    (b) have `deploy.sh` write a marker file that install.sh treats as
    equivalent to `.git`. Handle in a dedicated `/gsd:debug` or phase-45
    follow-up plan — NOT in 45-02.

## Trigger file ownership drifts to pv-proxy:pv-proxy after first write

- **Symptom:** install.sh Step 6b creates `update-trigger.json` with owner
  `root:pv-proxy` mode 0664. After the first successful POST /api/update/start,
  `os.replace` swaps in a tempfile that pv-proxy just wrote, so the resulting
  inode is `pv-proxy:pv-proxy` (mode 0664 is preserved by our chmod).
  - Discovered during: Plan 45-02 Task 4 LXC smoke test
  - Security impact: None. The SEC-07 intent ("pv-proxy can write, root can
    read") still holds — root bypasses ownership entirely, and pv-proxy is
    the owner so it can keep writing. The threat model T-45-02-06 already
    accepts that pv-proxy compromise implies trigger write access.
  - Deviation from literal SEC-07 text: SEC-07 says "owner `root:pv-proxy`".
    That can only be the install-time state; atomic os.replace inherently
    transfers ownership to the writer's uid.
  - Action: Document in 45-02 SUMMARY.md. Phase 45-03 consumer MUST NOT rely
    on `stat().st_uid == 0`; it only matters that the file is readable by
    root (which it always is). No code change needed for 45-02.
