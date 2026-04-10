---
phase: 43-blue-green-layout-boot-recovery
plan: 03
type: execute
wave: 2
depends_on:
  - 43-02
files_modified:
  - config/pv-inverter-proxy.service
  - config/pv-inverter-proxy-recovery.service
  - src/pv_inverter_proxy/recovery.py
  - tests/test_recovery.py
autonomous: true
requirements:
  - SAFETY-04
  - SAFETY-05
  - SAFETY-06
must_haves:
  truths:
    - "Main service unit has StartLimitBurst=10, StartLimitIntervalSec=120, TimeoutStopSec=15, KillMode=mixed"
    - "Main service unit creates /run/pv-inverter-proxy/ tmpfs via RuntimeDirectory=pv-inverter-proxy"
    - "A new pv-inverter-proxy-recovery.service unit runs Before=pv-inverter-proxy.service as Type=oneshot"
    - "recovery.py is the entry point that reads the PENDING marker and flips symlink back if the last boot had no SUCCESS marker"
    - "Recovery is idempotent: running it twice without a PENDING marker is a no-op"
    - "Recovery is atomic: if it crashes mid-flip the system still boots (it never deletes before successfully creating the replacement symlink)"
  artifacts:
    - path: "config/pv-inverter-proxy.service"
      provides: "Hardened main service unit with RuntimeDirectory"
      contains: "RuntimeDirectory=pv-inverter-proxy"
    - path: "config/pv-inverter-proxy-recovery.service"
      provides: "Boot-time recovery oneshot unit"
      contains: "Type=oneshot"
    - path: "src/pv_inverter_proxy/recovery.py"
      provides: "Recovery entry point with PENDING/SUCCESS marker logic"
      min_lines: 180
      exports: ["main", "PENDING_MARKER_PATH", "recover_if_needed"]
    - path: "tests/test_recovery.py"
      provides: "Unit tests covering marker read/write and symlink flip logic"
      min_lines: 220
  key_links:
    - from: "config/pv-inverter-proxy-recovery.service"
      to: "pv-inverter-proxy.service"
      via: "Before= directive in [Unit]"
      pattern: "Before=pv-inverter-proxy.service"
    - from: "src/pv_inverter_proxy/recovery.py"
      to: "src/pv_inverter_proxy/releases.py"
      via: "import for layout anchors (RELEASES_ROOT, CURRENT_SYMLINK_NAME)"
      pattern: "from pv_inverter_proxy.releases import"
    - from: "config/pv-inverter-proxy-recovery.service ExecStart"
      to: "recovery.py main"
      via: "python -m pv_inverter_proxy.recovery"
      pattern: "python.*-m pv_inverter_proxy\\.recovery"
---

<objective>
Harden the main service systemd unit, add the boot-time recovery unit + Python entry point, and wire the PENDING/SUCCESS marker contract that makes bad updates automatically recoverable without SSH.

Purpose: This plan lands the kernel of the safety system — the mechanism that makes a bricked update self-healing. The recovery service runs Before=pv-inverter-proxy.service on every boot; if it sees a PENDING marker without a corresponding SUCCESS marker, it flips the `current` symlink back to the previous release path recorded in the marker. The main service writes the SUCCESS marker after the first successful DeviceRegistry poll cycle (that hook-up is plan 43-04).

Three deliverables:
1. Updated `config/pv-inverter-proxy.service` with StartLimit tuning, RuntimeDirectory, KillMode=mixed, TimeoutStopSec=15.
2. New `config/pv-inverter-proxy-recovery.service` oneshot unit that runs before the main service.
3. New `src/pv_inverter_proxy/recovery.py` module with the PENDING-check + symlink-flip logic, plus a `tests/test_recovery.py` unit test file.

Output: Two systemd unit files (one modified, one new), one Python module, one test file. Unit files are NOT deployed to /etc/systemd/system/ in this plan — install.sh handles that in plan 43-04. This plan verifies the content is correct and the Python logic works on dev machine.

CRITICAL safety property: The recovery script must NEVER make things worse. If it cannot determine what to do, it logs CRITICAL and exits 0 (letting systemd start the main service with the current symlink). Only when it has HIGH confidence in the rollback target does it touch the symlink.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@config/pv-inverter-proxy.service
@src/pv_inverter_proxy/releases.py
@CLAUDE.md

<interfaces>
<!-- Current main service unit (to be modified): -->

`config/pv-inverter-proxy.service`:
```ini
[Unit]
Description=PV-Inverter-Master (Multi-Source Solar Aggregator for Venus OS)
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy
Restart=on-failure
RestartSec=5
User=pv-proxy
Group=pv-proxy
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/etc/pv-inverter-proxy
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pv-inverter-proxy

[Install]
WantedBy=multi-user.target
```

<!-- Anchors from plan 43-02 (releases.py): -->

```python
RELEASES_ROOT: Path = Path("/opt/pv-inverter-proxy-releases")
INSTALL_ROOT: Path = Path("/opt/pv-inverter-proxy")
CURRENT_SYMLINK_NAME: str = "current"
```

The `current` symlink lives at `RELEASES_ROOT / "current"` (i.e. `/opt/pv-inverter-proxy-releases/current`), NOT at `INSTALL_ROOT`. `INSTALL_ROOT` is a separate symlink (`/opt/pv-inverter-proxy`) that points at `RELEASES_ROOT / "current"`. The recovery script only touches the inner `current` symlink — the outer `INSTALL_ROOT` symlink stays put.

<!-- Marker contract (new — defined here, consumed in plan 43-04 and plan 45): -->

PENDING marker: `/var/lib/pv-inverter-proxy/update-pending.marker`
- JSON format (uses same stdlib primitives as state_file.py)
- Schema:
  ```json
  {
    "schema_version": 1,
    "previous_release": "/opt/pv-inverter-proxy-releases/v7.0-abc1234",
    "target_release": "/opt/pv-inverter-proxy-releases/v8.0-def5678",
    "created_at": 1700000000.0,
    "reason": "update" | "manual"
  }
  ```
- Written by: the privileged updater (Phase 45) BEFORE flipping the symlink to the new release.
- Deleted by: the main service after writing the SUCCESS marker (plan 43-04 wiring). Also deleted by recovery.py after a successful rollback (to avoid a loop on next boot).

SUCCESS marker: `/run/pv-inverter-proxy/healthy`
- Empty file, `RuntimeDirectory` tmpfs — automatically cleared on every boot.
- Written by: main service after DeviceRegistry completes first successful poll cycle.
- Read by: recovery.py — if PENDING exists and SUCCESS does NOT (wait, SUCCESS is in tmpfs which is cleared on boot, so it's ALWAYS absent at boot time) ... see note below.

**Important semantic correction:** The SUCCESS marker in `/run/pv-inverter-proxy/healthy` is tmpfs-cleared on every boot. So "SUCCESS existed last boot" cannot be detected via `/run/`. Instead, we use a PERSISTENT success marker:

PERSISTENT SUCCESS marker: `/var/lib/pv-inverter-proxy/last-boot-success.marker`
- Empty file, disk-persistent
- Written by: main service AFTER DeviceRegistry first successful poll AND after PENDING marker is cleared. This is the "we definitely succeeded this boot" signal.
- Read by: recovery.py on the NEXT boot.

Recovery logic flow:
```
On boot (before main service starts):
  if PENDING marker exists:
    # Something was updated. Did it complete successfully last boot?
    if LAST_BOOT_SUCCESS marker is newer than PENDING marker:
      # The update that wrote PENDING succeeded last boot. This is a stale marker.
      # This can happen if main service forgot to clear PENDING. Clean up.
      delete PENDING marker
      log "stale pending marker cleaned"
      exit 0
    else:
      # PENDING exists and either LAST_BOOT_SUCCESS is older or missing.
      # The previous boot did NOT reach "success" after the update.
      # ROLLBACK: flip current symlink to previous_release from PENDING.
      flip symlink
      delete PENDING marker (to avoid loop)
      log "recovery: rolled back to {previous_release}"
      exit 0
  else:
    # No pending update, normal boot.
    exit 0
```

Note that "last boot success" is a slightly fuzzy signal — if the user manually restarts the service within the same boot, LAST_BOOT_SUCCESS is already present from the boot. That's fine: PENDING is only written by the privileged updater, and the updater deletes stale PENDING before writing a new one. A fresh PENDING marker always has `created_at > last-boot-success.mtime` because the updater writes it mid-boot.

Extra safety: recovery.py also checks `created_at` against `last-boot-success.marker` mtime to detect the race: if PENDING was created AFTER the last success marker (even within the same boot), it's a genuine in-progress update; if LAST_BOOT_SUCCESS mtime is newer, the marker is stale.

<!-- Test patterns (tests/test_config.py, tests/test_context.py): -->

Unit tests can fully fake the filesystem via `tmp_path`. `recover_if_needed()` MUST accept override paths for every file it touches so tests can exercise it without touching real /var/lib/ or /opt/.

<!-- systemd.path and systemd.service doc references (no need to fetch): -->

systemd unit directives used in this plan (all in man systemd.service(5) / systemd.exec(5)):
- `Type=oneshot` — runs to completion then exits; do not need explicit main PID
- `RemainAfterExit=no` (default) — after exit, unit is inactive (correct for recovery)
- `Before=pv-inverter-proxy.service` — ordering, ensures we run before main service
- `Requires=` vs `Wants=` — use `RequiredBy=pv-inverter-proxy.service` in [Install] so it's pulled in automatically
- `RuntimeDirectory=NAME` — systemd creates /run/NAME on ExecStart and removes on ExecStop (mode 0755 by default; ownership matches User=). For pv-proxy user, this gives `/run/pv-inverter-proxy/` owned by pv-proxy:pv-proxy.
- `KillMode=mixed` — SIGTERM to main, SIGKILL to remaining children
- `TimeoutStopSec=15` — how long to wait between SIGTERM and SIGKILL
- `StartLimitBurst=10`, `StartLimitIntervalSec=120` — allow 10 restarts within 2 minutes before marking failed
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Harden main service unit with StartLimit, RuntimeDirectory, KillMode</name>
  <files>config/pv-inverter-proxy.service</files>
  <behavior>
    Modified `config/pv-inverter-proxy.service`:
    - Adds `StartLimitBurst=10` and `StartLimitIntervalSec=120` to `[Unit]` section (these are Unit-level directives, not Service).
    - Adds `TimeoutStopSec=15` and `KillMode=mixed` to `[Service]` section.
    - Adds `RuntimeDirectory=pv-inverter-proxy` to `[Service]` section (creates /run/pv-inverter-proxy/ tmpfs owned by pv-proxy:pv-proxy).
    - Adds `ReadWritePaths=/var/lib/pv-inverter-proxy` to `[Service]` section — the main service needs to write `last-boot-success.marker` and clear the PENDING marker (both in /var/lib). The ProtectSystem=strict blocks this by default.
    - Leaves everything else unchanged: User=pv-proxy, NoNewPrivileges=true, ProtectSystem=strict, CAP_NET_BIND_SERVICE, ExecStart, Restart=on-failure, RestartSec=5.
    - ExecStart stays as `/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy`. Note: /opt/pv-inverter-proxy is a symlink after migration but that's transparent to systemd — it resolves at exec time.

    The file must still parse as valid systemd unit syntax (`systemd-analyze verify` would pass).
  </behavior>
  <action>
    Rewrite `config/pv-inverter-proxy.service` to this exact content:

    ```ini
    [Unit]
    Description=PV-Inverter-Master (Multi-Source Solar Aggregator for Venus OS)
    After=network-online.target
    Wants=network-online.target
    StartLimitBurst=10
    StartLimitIntervalSec=120

    [Service]
    Type=exec
    ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy
    Restart=on-failure
    RestartSec=5
    TimeoutStopSec=15
    KillMode=mixed
    User=pv-proxy
    Group=pv-proxy
    AmbientCapabilities=CAP_NET_BIND_SERVICE
    NoNewPrivileges=true
    ProtectSystem=strict
    ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy
    RuntimeDirectory=pv-inverter-proxy
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier=pv-inverter-proxy

    [Install]
    WantedBy=multi-user.target
    ```

    Key changes vs original:
    1. `[Unit]`: add `StartLimitBurst=10`, `StartLimitIntervalSec=120` (C1 mitigation)
    2. `[Service]`: add `TimeoutStopSec=15` (C1, C3, H3 — graceful shutdown window)
    3. `[Service]`: add `KillMode=mixed` (C3 — asyncio shutdown hooks run on SIGTERM)
    4. `[Service]`: add `RuntimeDirectory=pv-inverter-proxy` (SAFETY-06 — healthy flag tmpfs)
    5. `[Service]`: extend `ReadWritePaths` with `/var/lib/pv-inverter-proxy` (needed for LAST_BOOT_SUCCESS marker write and PENDING marker clear)
  </action>
  <verify>
    <automated>grep -E "StartLimitBurst=10|StartLimitIntervalSec=120|TimeoutStopSec=15|KillMode=mixed|RuntimeDirectory=pv-inverter-proxy|ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy" config/pv-inverter-proxy.service | wc -l | tr -d ' ' | grep -q '^6$' && echo ok</automated>
  </verify>
  <done>All 6 directives present. File parses as ini. No directives removed from original.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Create recovery systemd unit</name>
  <files>config/pv-inverter-proxy-recovery.service</files>
  <behavior>
    New file `config/pv-inverter-proxy-recovery.service`:
    - `Type=oneshot` (runs to completion, exits)
    - `User=root` — recovery touches /opt/pv-inverter-proxy-releases/current symlink which is root-owned
    - `ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy.recovery`
    - `Before=pv-inverter-proxy.service` — runs before main service
    - `DefaultDependencies=yes` — use default boot ordering (we just need to run before the main service, no special requirements)
    - `After=local-fs.target` — filesystems must be mounted before we try to read /var/lib/ and /opt/
    - `[Install] RequiredBy=pv-inverter-proxy.service` — pulled in whenever main service is enabled; disabling it requires explicit action
    - `SyslogIdentifier=pv-inverter-proxy-recovery` — distinct from main service for journal filtering
    - `StandardOutput=journal`, `StandardError=journal`
    - NO `Restart=` (oneshot does not restart on failure)
    - NO `TimeoutStartSec` — default is 90s which is plenty for a symlink flip
  </behavior>
  <action>
    Create `config/pv-inverter-proxy-recovery.service`:

    ```ini
    [Unit]
    Description=PV-Inverter-Proxy Boot-Time Recovery (SAFETY-04)
    Documentation=https://github.com/meintechblog/pv-inverter-proxy
    DefaultDependencies=yes
    After=local-fs.target
    Before=pv-inverter-proxy.service

    [Service]
    Type=oneshot
    User=root
    Group=root
    ExecStart=/opt/pv-inverter-proxy/.venv/bin/python3 -m pv_inverter_proxy.recovery
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier=pv-inverter-proxy-recovery

    [Install]
    RequiredBy=pv-inverter-proxy.service
    ```

    Design notes:
    - `User=root` is required to modify /opt/pv-inverter-proxy-releases/current (which is root-owned after migration). The main service runs as pv-proxy and cannot touch this symlink — that's the whole point of splitting recovery into its own unit.
    - `Before=pv-inverter-proxy.service` ensures recovery runs to completion before main service even starts. If recovery decides to flip the symlink, main service will start against the rolled-back release.
    - `RequiredBy=pv-inverter-proxy.service` in [Install] means `systemctl enable pv-inverter-proxy-recovery.service` happens implicitly via `systemctl enable pv-inverter-proxy.service` (or via install.sh enabling both explicitly). If the recovery unit is masked, the main unit will fail to start — which is what we want: either recovery works, or we don't boot.
    - `Type=oneshot` + no `RemainAfterExit=yes` means the unit is inactive after running. That's fine — its job is to fire once per boot.
  </action>
  <verify>
    <automated>test -f config/pv-inverter-proxy-recovery.service && grep -q "Type=oneshot" config/pv-inverter-proxy-recovery.service && grep -q "Before=pv-inverter-proxy.service" config/pv-inverter-proxy-recovery.service && grep -q "User=root" config/pv-inverter-proxy-recovery.service && grep -q "pv_inverter_proxy.recovery" config/pv-inverter-proxy-recovery.service && grep -q "RequiredBy=pv-inverter-proxy.service" config/pv-inverter-proxy-recovery.service && echo ok</automated>
  </verify>
  <done>Unit file exists with all required directives. Valid ini syntax.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Create recovery.py entry point with marker logic and safe symlink flip</name>
  <files>src/pv_inverter_proxy/recovery.py</files>
  <behavior>
    New module `src/pv_inverter_proxy/recovery.py` exposing:

    1. Constants:
       - `PENDING_MARKER_PATH: Path = Path("/var/lib/pv-inverter-proxy/update-pending.marker")`
       - `LAST_BOOT_SUCCESS_PATH: Path = Path("/var/lib/pv-inverter-proxy/last-boot-success.marker")`

    2. `@dataclass class PendingMarker`:
       - `schema_version: int = 1`
       - `previous_release: str`  # absolute path (str not Path for JSON)
       - `target_release: str`
       - `created_at: float`
       - `reason: str = "update"`

    3. `def load_pending_marker(path: Path | None = None) -> PendingMarker | None`:
       - Returns None if file does not exist
       - Returns None and logs on any parse/schema error (never raises)
       - Validates `schema_version == 1`
       - Validates `previous_release` and `target_release` look like absolute paths (`startswith("/")`)
       - Returns populated dataclass on success

    4. `def clear_pending_marker(path: Path | None = None) -> None`:
       - Unlinks PENDING marker if it exists
       - Silently succeeds if missing
       - Logs warning on OSError but does not raise

    5. `def recover_if_needed(
           pending_path: Path | None = None,
           last_success_path: Path | None = None,
           releases_root: Path | None = None,
       ) -> str`:
       - Returns a short outcome string: `"no_pending"`, `"stale_pending_cleaned"`, `"rolled_back"`, `"no_recovery_target"`, `"flip_failed"`, `"target_missing"`
       - Uses `pv_inverter_proxy.releases` constants as defaults (RELEASES_ROOT).
       - Logic:
         a. Load PENDING marker. If absent → return `"no_pending"` (normal boot).
         b. Check `last_success_path`. If it exists AND its mtime > `marker.created_at` → STALE. Delete PENDING, return `"stale_pending_cleaned"`.
         c. Otherwise, attempt rollback:
            - Validate `marker.previous_release` exists as a directory. If not → log CRITICAL, return `"target_missing"`. Do NOT clear marker (user needs to investigate).
            - Atomic symlink flip: `ln -sfn <previous_release> <releases_root>/current.new; mv -T <releases_root>/current.new <releases_root>/current`. In Python:
              ```python
              tmp = releases_root / "current.new"
              if tmp.exists() or tmp.is_symlink():
                  tmp.unlink()
              tmp.symlink_to(previous_release)  # creates tmp pointing at prev
              os.replace(tmp, releases_root / "current")  # atomic swap
              ```
            - On success, clear PENDING marker, return `"rolled_back"`.
            - On OSError during flip, log CRITICAL, return `"flip_failed"`. Do NOT clear marker.

    6. `def main() -> int`:
       - Entry point for `python -m pv_inverter_proxy.recovery`
       - Configures minimal structlog (stdout, JSON, no config file needed — recovery runs before config loading).
       - Calls `recover_if_needed()` with defaults.
       - Logs the outcome.
       - Returns exit code:
         - 0 for `"no_pending"`, `"stale_pending_cleaned"`, `"rolled_back"` (all "success from systemd's POV, let main service start")
         - 0 for `"no_recovery_target"` and `"flip_failed"` too — we exit 0 to let main service attempt to start anyway. The CRITICAL log will surface in journalctl. Exiting non-zero would make recovery.service fail and block main service, which is strictly worse (user loses web UI to diagnose).
       - CRITICAL design rule: recovery.py NEVER returns a non-zero exit code. Its job is to help, not to block boot. If it cannot help, it logs and gets out of the way.

    7. `if __name__ == "__main__": sys.exit(main())`

    Logging format for recovery.py: use `structlog.get_logger(component="recovery")`. Minimal configuration — do NOT import `logging_config` (which expects config.yaml to exist). Use a bare structlog setup:

    ```python
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    ```
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/recovery.py`:

    ```python
    """Boot-time recovery hook (SAFETY-04).

    Runs as root via pv-inverter-proxy-recovery.service BEFORE the main service
    on every boot. If a PENDING update marker is found WITHOUT a corresponding
    post-update LAST_BOOT_SUCCESS, the previous release symlink is restored.

    Critical design rules:
    1. NEVER exit non-zero. If recovery cannot help, it logs CRITICAL and exits 0
       so the main service still attempts to start. A failing recovery unit
       would block boot, which is strictly worse than a no-op.
    2. Only flip the symlink when we have a VALID previous_release directory.
       Bogus markers are ignored with a CRITICAL log, not acted upon.
    3. The symlink flip is atomic via os.replace — if we crash mid-flip the
       old symlink is still intact.
    4. Once we successfully flip, delete the PENDING marker so we don't loop
       on the next boot.
    """
    from __future__ import annotations

    import json
    import os
    import sys
    from dataclasses import dataclass
    from pathlib import Path

    import structlog

    from pv_inverter_proxy.releases import (
        CURRENT_SYMLINK_NAME,
        RELEASES_ROOT,
    )

    PENDING_MARKER_PATH: Path = Path("/var/lib/pv-inverter-proxy/update-pending.marker")
    LAST_BOOT_SUCCESS_PATH: Path = Path("/var/lib/pv-inverter-proxy/last-boot-success.marker")


    def _configure_logging() -> None:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.PrintLoggerFactory(),
        )


    log = structlog.get_logger(component="recovery")


    @dataclass
    class PendingMarker:
        previous_release: str
        target_release: str
        created_at: float
        reason: str = "update"
        schema_version: int = 1


    def load_pending_marker(path: Path | None = None) -> PendingMarker | None:
        target = path or PENDING_MARKER_PATH
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("pending_marker_unreadable", path=str(target), error=str(e))
            return None
        if not isinstance(data, dict):
            log.warning("pending_marker_wrong_type", path=str(target))
            return None
        if data.get("schema_version") != 1:
            log.warning("pending_marker_unsupported_schema", schema=data.get("schema_version"))
            return None
        prev = data.get("previous_release")
        tgt = data.get("target_release")
        created = data.get("created_at")
        if not isinstance(prev, str) or not prev.startswith("/"):
            log.warning("pending_marker_bad_previous", previous=prev)
            return None
        if not isinstance(tgt, str) or not tgt.startswith("/"):
            log.warning("pending_marker_bad_target", target=tgt)
            return None
        if not isinstance(created, (int, float)):
            log.warning("pending_marker_bad_created_at", created_at=created)
            return None
        return PendingMarker(
            previous_release=prev,
            target_release=tgt,
            created_at=float(created),
            reason=str(data.get("reason", "update")),
        )


    def clear_pending_marker(path: Path | None = None) -> None:
        target = path or PENDING_MARKER_PATH
        try:
            target.unlink(missing_ok=True)
        except OSError as e:
            log.warning("pending_marker_unlink_failed", path=str(target), error=str(e))


    def _atomic_symlink_flip(current_link: Path, new_target: Path) -> None:
        """Atomic replacement of `current_link` to point at `new_target`.

        Uses the standard ln -sfn + mv -T pattern via os.replace.
        Raises OSError on failure.
        """
        tmp = current_link.with_name(current_link.name + ".new")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(new_target)
        os.replace(tmp, current_link)


    def recover_if_needed(
        pending_path: Path | None = None,
        last_success_path: Path | None = None,
        releases_root: Path | None = None,
    ) -> str:
        p_path = pending_path or PENDING_MARKER_PATH
        s_path = last_success_path or LAST_BOOT_SUCCESS_PATH
        rr = releases_root or RELEASES_ROOT

        marker = load_pending_marker(p_path)
        if marker is None:
            log.info("no_pending_marker")
            return "no_pending"

        log.info(
            "pending_marker_found",
            previous=marker.previous_release,
            target=marker.target_release,
            created_at=marker.created_at,
        )

        # Stale marker check: last_success newer than marker = previous boot
        # completed successfully post-update. Marker was orphaned.
        if s_path.exists():
            try:
                last_success_mtime = s_path.stat().st_mtime
            except OSError as e:
                log.warning("last_success_stat_failed", error=str(e))
                last_success_mtime = 0.0
            if last_success_mtime > marker.created_at:
                log.info(
                    "stale_pending_marker_cleaning",
                    last_success_mtime=last_success_mtime,
                    marker_created_at=marker.created_at,
                )
                clear_pending_marker(p_path)
                return "stale_pending_cleaned"

        # Genuine rollback needed.
        previous = Path(marker.previous_release)
        if not previous.is_dir():
            log.critical(
                "recovery_target_missing",
                previous_release=marker.previous_release,
                hint="manual SSH intervention required",
            )
            return "target_missing"

        current_link = rr / CURRENT_SYMLINK_NAME
        try:
            _atomic_symlink_flip(current_link, previous)
        except OSError as e:
            log.critical(
                "recovery_symlink_flip_failed",
                error=str(e),
                current_link=str(current_link),
                target=str(previous),
                hint="manual SSH intervention required",
            )
            return "flip_failed"

        log.warning(
            "recovery_rolled_back",
            previous_release=marker.previous_release,
            failed_target=marker.target_release,
        )
        clear_pending_marker(p_path)
        return "rolled_back"


    def main() -> int:
        _configure_logging()
        try:
            outcome = recover_if_needed()
        except Exception as e:  # pragma: no cover - last-resort safety net
            log.critical("recovery_unexpected_exception", error=str(e))
            outcome = "exception"
        log.info("recovery_complete", outcome=outcome)
        # Always exit 0 — recovery should never block boot.
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    ```
  </action>
  <verify>
    <automated>python -c "from pv_inverter_proxy.recovery import main, recover_if_needed, PENDING_MARKER_PATH, LAST_BOOT_SUCCESS_PATH, PendingMarker, load_pending_marker, clear_pending_marker; print('ok')"</automated>
  </verify>
  <done>Module imports cleanly, all exports present.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Write unit tests for recovery.py</name>
  <files>tests/test_recovery.py</files>
  <behavior>
    pytest tests using `tmp_path` for all filesystem operations. No mocks.

    Test coverage:

    **load_pending_marker:**
    - Returns None when file does not exist
    - Returns None on corrupt JSON
    - Returns None on JSON array (wrong type)
    - Returns None on wrong schema_version
    - Returns None on missing previous_release
    - Returns None when previous_release is not absolute path
    - Returns None on missing created_at
    - Returns populated dataclass on valid input
    - Reason defaults to "update" if missing

    **clear_pending_marker:**
    - Unlinks existing file
    - Silently succeeds on missing file
    - Does not raise on unlinkable file (simulated by already-removed path)

    **recover_if_needed:**
    - `no_pending` when marker file does not exist
    - `no_pending` when marker file is corrupt (load returns None)
    - `stale_pending_cleaned` when last_success.mtime > marker.created_at
      - Verify PENDING marker is deleted after cleanup
    - `target_missing` when previous_release does not exist
      - Verify PENDING marker is NOT deleted (user intervention needed)
      - Verify current symlink NOT touched
    - `rolled_back` happy path:
      - Set up: releases_root with v1/ and v2/ dirs, current symlink pointing at v2
      - Create PENDING marker with previous_release=v1, target_release=v2, no last_success
      - Call recover_if_needed
      - Assert: current symlink now resolves to v1
      - Assert: PENDING marker deleted
      - Assert: return value is "rolled_back"
    - `flip_failed` when symlink flip raises OSError
      - Create releases_root as a read-only dir (chmod 0555)
      - Create marker pointing at a valid previous_release
      - Assert return value is "flip_failed"
      - Assert PENDING marker NOT deleted
      - (Skip this test on macOS if root-only fs ops behave differently; use monkeypatch to force OSError from _atomic_symlink_flip instead)

    **main:**
    - Returns 0 on no_pending
    - Returns 0 on target_missing (critical logged, but exit 0)
    - Returns 0 even if recover_if_needed raises (safety net)

    **Integration-ish (still with tmp_path):**
    - Full lifecycle: create releases with v1, v2; set current -> v2; write PENDING(prev=v1, target=v2); call recover_if_needed; confirm symlink flipped and marker gone. Then call recover_if_needed AGAIN — should return "no_pending" (marker was cleared).
  </behavior>
  <action>
    Create `tests/test_recovery.py`:

    ```python
    """Unit tests for recovery.py (SAFETY-04)."""
    from __future__ import annotations

    import json
    import os
    import time
    from pathlib import Path

    import pytest

    from pv_inverter_proxy import recovery
    from pv_inverter_proxy.recovery import (
        PendingMarker,
        clear_pending_marker,
        load_pending_marker,
        recover_if_needed,
    )


    # -------- Fixtures --------

    def _write_marker(path: Path, **kwargs) -> None:
        data = {
            "schema_version": 1,
            "previous_release": "/opt/pv-inverter-proxy-releases/v7.0-abc1234",
            "target_release": "/opt/pv-inverter-proxy-releases/v8.0-def5678",
            "created_at": 1_700_000_000.0,
            "reason": "update",
        }
        data.update(kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))


    def _setup_releases(tmp_path: Path) -> tuple[Path, Path, Path]:
        """Return (releases_root, v1_dir, v2_dir) with current -> v2."""
        releases_root = tmp_path / "releases"
        releases_root.mkdir()
        v1 = releases_root / "v7.0-abc1234"
        v1.mkdir()
        (v1 / "pyproject.toml").write_text("[project]\nname='x'\n")
        v2 = releases_root / "v8.0-def5678"
        v2.mkdir()
        (v2 / "pyproject.toml").write_text("[project]\nname='x'\n")
        (releases_root / "current").symlink_to(v2)
        return releases_root, v1, v2


    # -------- load_pending_marker --------

    def test_load_pending_missing(tmp_path: Path):
        assert load_pending_marker(tmp_path / "nope.marker") is None


    def test_load_pending_corrupt_json(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text("{bad json")
        assert load_pending_marker(path) is None


    def test_load_pending_array_not_dict(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text("[1,2,3]")
        assert load_pending_marker(path) is None


    def test_load_pending_wrong_schema(tmp_path: Path):
        path = tmp_path / "marker"
        _write_marker(path, schema_version=99)
        assert load_pending_marker(path) is None


    def test_load_pending_missing_previous(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text(json.dumps({
            "schema_version": 1,
            "target_release": "/opt/x",
            "created_at": 1.0,
        }))
        assert load_pending_marker(path) is None


    def test_load_pending_previous_not_absolute(tmp_path: Path):
        path = tmp_path / "marker"
        _write_marker(path, previous_release="relative/path")
        assert load_pending_marker(path) is None


    def test_load_pending_missing_created_at(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text(json.dumps({
            "schema_version": 1,
            "previous_release": "/opt/x",
            "target_release": "/opt/y",
        }))
        assert load_pending_marker(path) is None


    def test_load_pending_valid(tmp_path: Path):
        path = tmp_path / "marker"
        _write_marker(path)
        m = load_pending_marker(path)
        assert m is not None
        assert m.previous_release == "/opt/pv-inverter-proxy-releases/v7.0-abc1234"
        assert m.target_release == "/opt/pv-inverter-proxy-releases/v8.0-def5678"
        assert m.created_at == 1_700_000_000.0
        assert m.reason == "update"


    def test_load_pending_reason_defaults(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text(json.dumps({
            "schema_version": 1,
            "previous_release": "/opt/x",
            "target_release": "/opt/y",
            "created_at": 1.0,
        }))
        m = load_pending_marker(path)
        assert m is not None
        assert m.reason == "update"


    # -------- clear_pending_marker --------

    def test_clear_pending_removes_file(tmp_path: Path):
        path = tmp_path / "marker"
        path.write_text("hi")
        clear_pending_marker(path)
        assert not path.exists()


    def test_clear_pending_missing_ok(tmp_path: Path):
        clear_pending_marker(tmp_path / "nope")  # should not raise


    # -------- recover_if_needed --------

    def test_recover_no_pending(tmp_path: Path):
        releases_root, _, _ = _setup_releases(tmp_path)
        outcome = recover_if_needed(
            pending_path=tmp_path / "no_marker",
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome == "no_pending"


    def test_recover_no_pending_on_corrupt(tmp_path: Path):
        releases_root, _, _ = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        marker.write_text("{garbage")
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome == "no_pending"


    def test_recover_stale_cleaned(tmp_path: Path):
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(
            marker,
            previous_release=str(v1),
            target_release=str(v2),
            created_at=1_000_000.0,
        )
        success = tmp_path / "last-success"
        success.write_text("")
        os.utime(success, (2_000_000.0, 2_000_000.0))  # newer than marker
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=success,
            releases_root=releases_root,
        )
        assert outcome == "stale_pending_cleaned"
        assert not marker.exists()
        # current symlink unchanged
        assert (releases_root / "current").resolve() == v2.resolve()


    def test_recover_target_missing(tmp_path: Path):
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(
            marker,
            previous_release=str(tmp_path / "nonexistent"),
            target_release=str(v2),
        )
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome == "target_missing"
        assert marker.exists()  # NOT cleared
        assert (releases_root / "current").resolve() == v2.resolve()  # untouched


    def test_recover_rolled_back(tmp_path: Path):
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(
            marker,
            previous_release=str(v1),
            target_release=str(v2),
            created_at=time.time(),
        )
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome == "rolled_back"
        assert not marker.exists()
        assert (releases_root / "current").resolve() == v1.resolve()


    def test_recover_rolled_back_idempotent(tmp_path: Path):
        """Second call after rollback returns no_pending."""
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(marker, previous_release=str(v1), target_release=str(v2))
        outcome1 = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome1 == "rolled_back"
        outcome2 = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome2 == "no_pending"


    def test_recover_flip_failed(tmp_path: Path, monkeypatch):
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(marker, previous_release=str(v1), target_release=str(v2))

        def raising_flip(current_link, new_target):
            raise OSError("simulated EPERM")

        monkeypatch.setattr(recovery, "_atomic_symlink_flip", raising_flip)
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=tmp_path / "no_success",
            releases_root=releases_root,
        )
        assert outcome == "flip_failed"
        assert marker.exists()  # NOT cleared — user intervention needed
        assert (releases_root / "current").resolve() == v2.resolve()  # untouched


    def test_recover_last_success_older_than_marker_triggers_rollback(tmp_path: Path):
        """If last_success exists but is OLDER than the marker, rollback proceeds."""
        releases_root, v1, v2 = _setup_releases(tmp_path)
        marker = tmp_path / "marker"
        _write_marker(
            marker,
            previous_release=str(v1),
            target_release=str(v2),
            created_at=5_000_000.0,
        )
        success = tmp_path / "last-success"
        success.write_text("")
        os.utime(success, (1_000_000.0, 1_000_000.0))  # OLDER than marker
        outcome = recover_if_needed(
            pending_path=marker,
            last_success_path=success,
            releases_root=releases_root,
        )
        assert outcome == "rolled_back"


    # -------- main --------

    def test_main_returns_zero_no_pending(tmp_path: Path, monkeypatch):
        monkeypatch.setattr(recovery, "PENDING_MARKER_PATH", tmp_path / "nope")
        monkeypatch.setattr(recovery, "LAST_BOOT_SUCCESS_PATH", tmp_path / "nope2")
        assert recovery.main() == 0


    def test_main_returns_zero_even_on_exception(tmp_path: Path, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(recovery, "recover_if_needed", boom)
        assert recovery.main() == 0


    def test_atomic_symlink_flip_direct(tmp_path: Path):
        releases_root = tmp_path / "releases"
        releases_root.mkdir()
        v1 = releases_root / "v1"
        v1.mkdir()
        v2 = releases_root / "v2"
        v2.mkdir()
        current = releases_root / "current"
        current.symlink_to(v2)
        recovery._atomic_symlink_flip(current, v1)
        assert current.resolve() == v1.resolve()
        # Leftover .new should not exist
        assert not (releases_root / "current.new").exists()
    ```
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && python -m pytest tests/test_recovery.py -x -q</automated>
  </verify>
  <done>All ~22 tests pass. No test touches /opt, /var, or /run — everything is tmp_path scoped.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| recovery.py (runs as root) -> /opt/pv-inverter-proxy-releases/current | The ONLY place where root modifies the current symlink on boot. |
| PENDING marker (pv-proxy writes? or root writes?) -> recovery.py | **Phase 45** privileged updater writes PENDING as root. For Phase 43, nobody writes it yet — tests fake it. The marker path is in /var/lib/pv-inverter-proxy/ which is root:pv-proxy mode 2775. |
| recovery.py -> systemd exit code | Always exit 0 — never block boot. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-43-03-01 | Tampering | PENDING marker from untrusted writer | mitigate | Marker lives in /var/lib/pv-inverter-proxy/ (root:pv-proxy mode 2775 — set by install.sh in plan 43-04). Only pv-proxy and root can write. Attacker with pv-proxy write access already has code execution on the main service. Schema validation in load_pending_marker rejects anything that doesn't match the strict contract (absolute paths required, schema_version=1). |
| T-43-03-02 | Tampering | PENDING marker points at an attacker-chosen directory | mitigate | `previous_release` is validated as `is_dir()` before acting. An attacker could only redirect to a directory that actually exists. The attack surface is reduced to "directories readable by root on /opt/" which is not a new surface. Future hardening (Phase 45+): validate that `previous_release` starts with `RELEASES_ROOT` string. **TODO for Phase 45:** Add this check in plan 43-03 recovery.py since Phase 43 creates the marker contract. |
| T-43-03-03 | Elevation of Privilege | recovery.py as root in boot path | mitigate | Minimal code path: only stdlib + releases.py constant import. No shell invocation, no subprocess, no network, no user input other than a JSON file with strict schema. Imports from pv_inverter_proxy.releases which itself imports only stdlib. |
| T-43-03-04 | Denial of Service | recovery.py blocks boot | mitigate | `main()` catches all exceptions and returns 0. The unit is Type=oneshot with a 90s default timeout. The recovery logic is bounded (one symlink read, one mtime stat, one symlink flip — all O(1) syscalls). |
| T-43-03-05 | Denial of Service | corrupt PENDING marker causes crash loop | mitigate | `load_pending_marker` is fully defensive — 9 parse error paths tested. Returns None on any failure, which leads to `no_pending` outcome. |
| T-43-03-06 | Denial of Service | symlink flip leaves system in inconsistent state | mitigate | Atomic via `os.replace(tmp_symlink, current_symlink)` — POSIX guarantees either old or new symlink, never absent. On OSError, old symlink remains; recovery reports `flip_failed` and marker is preserved for human inspection. |
| T-43-03-07 | Repudiation | recovery action not logged | mitigate | Every outcome logs via structlog (JSONRenderer to stdout → journald). Outcome string is deterministic and parseable. `recovery_rolled_back` logged at WARNING, `recovery_target_missing` / `recovery_symlink_flip_failed` logged at CRITICAL. |
| T-43-03-08 | Information Disclosure | recovery.py logs paths | accept | Paths are deterministic (/opt/pv-inverter-proxy-releases/v*-*) and not sensitive. |
| T-43-03-09 | Tampering | LAST_BOOT_SUCCESS marker backdate to skip rollback | mitigate | LAST_BOOT_SUCCESS is in /var/lib/pv-inverter-proxy/ (same ACL as PENDING). Attacker with write access could `touch` it to be newer than PENDING, suppressing rollback. Mitigation: the marker is written only after DeviceRegistry completes first poll — an attacker in control of pv-proxy already controls the main service. Defense-in-depth: Phase 45 will cross-check the PENDING marker's nonce against processed-nonces.json. For Phase 43, accept. |

**TODO noted in-code (task 3 action section):** Add `previous_release.startswith(str(RELEASES_ROOT))` validation in a follow-up. For Phase 43, the validation accepts any absolute path under a directory; the `is_dir()` check is the main gate.
</threat_model>

<validation_strategy>
**SAFETY-04 (boot-time recovery):** Validated in 3 layers:
1. **Unit layer (this plan):** `tests/test_recovery.py` exercises all 6 outcomes plus main() entry point. Uses fake filesystem via tmp_path. No systemd, no root.
2. **Integration layer (plan 43-04 deploy):** After install.sh deploys the recovery unit and migrates the layout, verify `systemctl status pv-inverter-proxy-recovery.service` shows `inactive (dead)` with a clean journal entry `no_pending_marker` on the next boot.
3. **Manual LXC verification (post-plan 43-04):** Manually create a PENDING marker pointing at a non-current release, reboot, verify current symlink flipped and marker cleared.

**SAFETY-05 (systemd hardening):** Validated by grep of the unit file (task 1 verify). Integration validation in plan 43-04 via `systemd-analyze verify /etc/systemd/system/pv-inverter-proxy.service`.

**SAFETY-06 (RuntimeDirectory):** Validated by grep of the unit file. Integration validation in plan 43-04 after deploy: verify `/run/pv-inverter-proxy/` exists and is owned by pv-proxy:pv-proxy after `systemctl start pv-inverter-proxy.service`.

**Nyquist validation per task:**
- Task 1 verify: grep assertion that all 6 hardening directives are present (StartLimitBurst=10, StartLimitIntervalSec=120, TimeoutStopSec=15, KillMode=mixed, RuntimeDirectory=pv-inverter-proxy, ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy).
- Task 2 verify: grep assertion that recovery.service has Type=oneshot, User=root, Before=pv-inverter-proxy.service, RequiredBy in install, ExecStart invokes the module.
- Task 3 verify: Import smoke test of the recovery module.
- Task 4 verify: Full pytest run against ~22 test cases covering all outcomes.

**Why systemd units cannot be unit-tested:** They are configuration files consumed by systemd. We verify by static grep and rely on `systemd-analyze verify` in the plan 43-04 deploy verification step on the LXC.
</validation_strategy>

<rollback_plan>
1. **Main service unit (task 1):** Original content is saved in git history. Revert via `git checkout HEAD~N -- config/pv-inverter-proxy.service` and redeploy. The service already ran fine before these directives, so reverting is safe. WARNING: if a PENDING marker exists at rollback time and the recovery unit is installed but the main service unit no longer has ReadWritePaths=/var/lib/pv-inverter-proxy, the main service may fail to clear the PENDING marker — but Phase 43 does not yet wire the marker-writing code, so this is not a real risk until plan 45 lands.
2. **Recovery unit (task 2):** New file — `git rm config/pv-inverter-proxy-recovery.service` to revert. Must also remove it from /etc/systemd/system/ on the LXC: `systemctl disable pv-inverter-proxy-recovery.service; rm /etc/systemd/system/pv-inverter-proxy-recovery.service; systemctl daemon-reload`. Plan 43-04 installs it; this plan only creates the source file.
3. **recovery.py (task 3):** New file — `git rm src/pv_inverter_proxy/recovery.py` to revert. No importers yet.
4. **test_recovery.py (task 4):** New file — `git rm tests/test_recovery.py` to revert.
5. **Service impact if this plan is reverted mid-flight:** None, because plan 43-03 does not deploy anything to the LXC. The deploy happens in plan 43-04 install.sh. Reverting plan 43-03 is pure source-tree revert.
</rollback_plan>

<verification>
1. `grep -c '^StartLimitBurst=10$\|^StartLimitIntervalSec=120$' config/pv-inverter-proxy.service` returns 2
2. `grep -c '^TimeoutStopSec=15$\|^KillMode=mixed$\|^RuntimeDirectory=pv-inverter-proxy$' config/pv-inverter-proxy.service` returns 3
3. `grep -q 'ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy' config/pv-inverter-proxy.service`
4. `test -f config/pv-inverter-proxy-recovery.service`
5. `grep -q 'Before=pv-inverter-proxy.service' config/pv-inverter-proxy-recovery.service`
6. `grep -q 'RequiredBy=pv-inverter-proxy.service' config/pv-inverter-proxy-recovery.service`
7. `python -m pytest tests/test_recovery.py -x -q` — all pass
8. `python -m pytest tests/ -x -q` — full suite passes, no regressions
9. `python -c "from pv_inverter_proxy.recovery import main; print(main())"` prints a log line and returns 0 (no PENDING marker on dev machine, graceful no_pending path). Note: will print JSON log to stdout — expected.
</verification>

<success_criteria>
- [ ] `config/pv-inverter-proxy.service` has StartLimitBurst=10, StartLimitIntervalSec=120 in [Unit]
- [ ] `config/pv-inverter-proxy.service` has TimeoutStopSec=15, KillMode=mixed, RuntimeDirectory=pv-inverter-proxy in [Service]
- [ ] `config/pv-inverter-proxy.service` has ReadWritePaths extended to include /var/lib/pv-inverter-proxy
- [ ] `config/pv-inverter-proxy-recovery.service` exists with Type=oneshot, User=root, Before=pv-inverter-proxy.service, ExecStart invoking pv_inverter_proxy.recovery module, RequiredBy=pv-inverter-proxy.service in [Install]
- [ ] `src/pv_inverter_proxy/recovery.py` exists, exports main/recover_if_needed/PendingMarker/load_pending_marker/clear_pending_marker/PENDING_MARKER_PATH/LAST_BOOT_SUCCESS_PATH
- [ ] recovery.py NEVER returns non-zero from main() even on unexpected exception
- [ ] recovery.py uses the atomic os.replace pattern for symlink flip
- [ ] recovery.py only clears PENDING marker on successful rollback or confirmed staleness
- [ ] `tests/test_recovery.py` has 20+ tests, all passing
- [ ] Full test suite passes (no regressions)
- [ ] No deployment to LXC in this plan — that's plan 43-04
</success_criteria>

<output>
After completion, create `.planning/phases/43-blue-green-layout-boot-recovery/43-03-SUMMARY.md` documenting:
- The PENDING marker contract (schema, writer, reader, clearer) as it stands in Phase 43
- The "recovery never blocks boot" invariant and why it's enforced
- The atomic symlink flip primitive and how Phase 45 will reuse it for the forward direction
- Open issue: previous_release path validation should eventually require startswith(RELEASES_ROOT) — note for Phase 45 when Phase 45 becomes the marker writer
- The tmpfs `/run/pv-inverter-proxy/healthy` vs persistent `/var/lib/pv-inverter-proxy/last-boot-success.marker` distinction — why we need both (tmpfs is boot-scoped freshness signal, persistent is cross-boot success signal)
- systemd unit directives landed and their C1/C3/H3 mitigation mapping
</output>
