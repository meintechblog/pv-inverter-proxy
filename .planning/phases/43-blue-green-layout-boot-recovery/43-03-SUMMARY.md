---
phase: 43-blue-green-layout-boot-recovery
plan: 03
subsystem: boot-recovery
tags: [safety, systemd, recovery, marker-contract, atomic-symlink]
requires:
  - "releases.py constants (RELEASES_ROOT, CURRENT_SYMLINK_NAME) from plan 43-02"
provides:
  - "Hardened main service unit (StartLimit, RuntimeDirectory, KillMode, TimeoutStopSec)"
  - "Boot-time recovery systemd unit (Type=oneshot, Before main service, root user)"
  - "recovery.py entry point with PENDING/SUCCESS marker logic"
  - "PENDING marker schema v1 contract (JSON, absolute-path validated)"
  - "Atomic symlink flip primitive (_atomic_symlink_flip via os.replace)"
  - "Public exports: main, recover_if_needed, load_pending_marker, clear_pending_marker, PendingMarker, PENDING_MARKER_PATH, LAST_BOOT_SUCCESS_PATH"
affects:
  - "Plan 43-04 (install migration) — deploys these unit files and wires healthy flag writer"
  - "Phase 45 (privileged updater) — writes PENDING marker before symlink flip; may reuse _atomic_symlink_flip"
tech-stack:
  added: []
  patterns:
    - "Defensive JSON schema validation (9 reject paths in load_pending_marker)"
    - "POSIX-atomic rename via os.replace for symlink flips"
    - "Always-exit-0 safety invariant for boot-path daemons"
    - "Stdlib-only recovery path (no config.yaml dependency, no subprocess)"
    - "Override-injected paths for unit-testing filesystem code without monkeypatching globals"
key-files:
  created:
    - "config/pv-inverter-proxy-recovery.service"
    - "src/pv_inverter_proxy/recovery.py"
    - "tests/test_recovery.py"
  modified:
    - "config/pv-inverter-proxy.service"
decisions:
  - "Recovery main() NEVER returns non-zero, even on unexpected exception. A failing recovery unit would block the main service (RequiredBy), costing the user the web UI needed to diagnose the failure — strictly worse than a no-op."
  - "PENDING marker is JSON (not a flag file) to carry previous_release + target_release + created_at + reason. Schema versioned to allow future evolution."
  - "Stale-marker detection via LAST_BOOT_SUCCESS mtime > marker.created_at. Equal mtimes are treated as NOT stale (defensive: proceed with rollback)."
  - "Two separate success markers: tmpfs /run/pv-inverter-proxy/healthy (boot-scoped freshness signal, cleared every boot) and persistent /var/lib/pv-inverter-proxy/last-boot-success.marker (cross-boot success signal, used by recovery on next boot)."
  - "Recovery runs as User=root in its own systemd unit — the main service runs as unprivileged pv-proxy and cannot touch the root-owned symlink at /opt/pv-inverter-proxy-releases/current. Splitting recovery into its own unit keeps the main service privilege-minimal."
  - "ReadWritePaths extended with /var/lib/pv-inverter-proxy in main unit so the main service can write LAST_BOOT_SUCCESS and clear PENDING after first successful poll (wiring lands in plan 43-04)."
metrics:
  duration: "~20 minutes"
  completed: "2026-04-10"
requirements: [SAFETY-04, SAFETY-05, SAFETY-06]
---

# Phase 43 Plan 03: Systemd Hardening + Boot-Time Recovery Summary

Lands the kernel of the v8.0 auto-update safety system — systemd crash-loop protection + a boot-time recovery oneshot that atomically flips the blue-green `current` symlink back to the previous release when the last boot's update did not reach a successful poll cycle, making bad updates self-healing without SSH.

## The PENDING Marker Contract (Phase 43 Edition)

Plan 43-03 defines the contract that the Phase 45 privileged updater will write and that the main service (plan 43-04) will clear. Writers and clearers do not exist yet in this plan — only the reader.

### Schema v1

```json
{
  "schema_version": 1,
  "previous_release": "/opt/pv-inverter-proxy-releases/v7.0-abc1234",
  "target_release":   "/opt/pv-inverter-proxy-releases/v8.0-def5678",
  "created_at":       1700000000.0,
  "reason":           "update"
}
```

| Field | Type | Validation |
|-------|------|------------|
| `schema_version` | int | Must equal `1` |
| `previous_release` | str | Must start with `/` (absolute) |
| `target_release` | str | Must start with `/` (absolute) |
| `created_at` | int\|float | Required, coerced to float |
| `reason` | str | Optional, defaults to `"update"` |

Any deviation → `load_pending_marker()` returns `None` with a warning log and `recover_if_needed()` takes the `no_pending` path. The recovery never trusts bad JSON.

### File Location & Ownership

| Marker | Path | Lifetime | Writer | Reader | Clearer |
|--------|------|----------|--------|--------|---------|
| PENDING | `/var/lib/pv-inverter-proxy/update-pending.marker` | Persistent, deleted on success | Phase 45 updater (as root, pre-flip) | recovery.py + main service | recovery.py (on rollback) + main service (on first successful poll) |
| LAST_BOOT_SUCCESS | `/var/lib/pv-inverter-proxy/last-boot-success.marker` | Persistent, mtime-touched per successful boot | Main service (Plan 43-04) | recovery.py (next boot) | — |
| HEALTHY | `/run/pv-inverter-proxy/healthy` | tmpfs, cleared per boot | Main service (Plan 43-04) | Web UI / systemctl status surfaces | systemd (tmpfs clear on shutdown) |

### Why Two Success Markers?

The distinction between `/run/.../healthy` (tmpfs) and `/var/lib/.../last-boot-success.marker` (persistent) is load-bearing:

- **`/run/pv-inverter-proxy/healthy` (tmpfs)** is a *boot-scoped freshness signal*. It is guaranteed absent at boot (RuntimeDirectory wipes it), so its presence proves "the main service is healthy THIS boot". It is the right thing to read from the web UI or `systemctl status` hooks.

- **`/var/lib/pv-inverter-proxy/last-boot-success.marker` (persistent)** is a *cross-boot success signal*. Its mtime records when the most recent successful poll completed. On the NEXT boot, recovery.py compares this mtime against the PENDING marker's `created_at` to decide whether the previous boot's update actually worked.

A single tmpfs marker would be useless on the next boot (wiped). A single persistent marker would be meaningless for THIS boot (stale from last boot). Both are needed.

## The "Recovery Never Blocks Boot" Invariant

The most important single line in `recovery.py`:

```python
def main() -> int:
    _configure_logging()
    try:
        outcome = recover_if_needed()
    except Exception as e:
        log.critical("recovery_unexpected_exception", error=str(e))
        outcome = "exception"
    log.info("recovery_complete", outcome=outcome)
    return 0  # ALWAYS
```

**Why:** `pv-inverter-proxy-recovery.service` declares `RequiredBy=pv-inverter-proxy.service` in `[Install]`. If recovery ever exited non-zero, systemd would mark it failed and refuse to start the main service. The user would then lose the web UI — which is exactly the tool they need to diagnose why their update failed. That is strictly worse than the alternative: log a CRITICAL message to journald, exit 0, and let the main service start against whatever `current` currently points at. If the CURRENT release is broken, the user still has the previous release on disk and can SSH in to roll back manually — but at least the next boot-with-a-fix will be able to serve the web UI.

This invariant is enforced in two layers:
1. `recover_if_needed()` uses a bounded decision tree that only returns strings — no raises on the main path.
2. `main()` wraps the call in a catch-all `except Exception` as a last-resort safety net.

Test coverage for the invariant: `test_main_returns_zero_no_pending`, `test_main_returns_zero_even_on_exception`, `test_main_returns_zero_on_target_missing`.

## Atomic Symlink Flip Primitive

```python
def _atomic_symlink_flip(current_link: Path, new_target: Path) -> None:
    tmp = current_link.with_name(current_link.name + ".new")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(new_target)
    os.replace(tmp, current_link)
```

This is the POSIX-atomic rename pattern: `os.replace()` guarantees the target path (`current`) either refers to the old symlink or the new one — never to nothing, never to a half-written file. If the process crashes between `symlink_to` and `os.replace`, the old `current` symlink is still valid; only the leftover `current.new` survives, and the next invocation cleans it (`if tmp.exists(): tmp.unlink()`).

**Phase 45 reuse:** The forward direction (updater flipping `current` to a new release) will use the exact same primitive. Phase 45 should `from pv_inverter_proxy.recovery import _atomic_symlink_flip` — or the primitive can be promoted to a public function if callers multiply. Consolidating the pattern in one place means there is one code path to audit for the POSIX atomicity guarantee.

Test coverage: `test_atomic_symlink_flip_direct` (happy path), `test_atomic_symlink_flip_cleans_stale_tmp` (crash recovery from a prior attempt).

## systemd Hardening Directives Landed

Mapping each directive to its PITFALLS.md entry:

| Directive | Section | Value | Mitigates |
|-----------|---------|-------|-----------|
| `StartLimitBurst=10` | `[Unit]` | 10 | C1 (crash-loop lockout) |
| `StartLimitIntervalSec=120` | `[Unit]` | 120s | C1 (crash-loop lockout) |
| `TimeoutStopSec=15` | `[Service]` | 15s | C1, C3, H3 (graceful shutdown window before SIGKILL) |
| `KillMode=mixed` | `[Service]` | mixed | C3 (asyncio shutdown hooks run on SIGTERM to main PID; SIGKILL to leftover children) |
| `RuntimeDirectory=pv-inverter-proxy` | `[Service]` | (name) | SAFETY-06 (tmpfs /run/pv-inverter-proxy/ for healthy marker) |
| `ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy` | `[Service]` | extended | SAFETY-04 (main service must write LAST_BOOT_SUCCESS and clear PENDING) |

**Preserved from original** (unchanged, verified via grep): `NoNewPrivileges=true`, `ProtectSystem=strict`, `User=pv-proxy`, `Group=pv-proxy`, `AmbientCapabilities=CAP_NET_BIND_SERVICE`, `Restart=on-failure`, `RestartSec=5`, `StandardOutput=journal`, `StandardError=journal`, `SyslogIdentifier=pv-inverter-proxy`, `WantedBy=multi-user.target`.

### Crash-Loop Math

With `Restart=on-failure`, `RestartSec=5`, `StartLimitBurst=10`, `StartLimitIntervalSec=120`:

- On a fast-crash bug, the service tries to restart every 5 seconds.
- systemd allows 10 starts per 120-second window before marking it failed.
- Translated: ~1 restart per 12 seconds on average. 10 restarts ≈ 50 seconds of restart attempts before the service is marked failed and stops restarting on its own.
- The recovery service runs once at boot, BEFORE the main service starts, so the 10-attempt budget does not apply to the rollback mechanism itself — recovery has unlimited time to decide during the single boot window.

This is intentionally generous: we want to tolerate transient failures (slow database, delayed network) without locking out the service.

## The Recovery Unit

`config/pv-inverter-proxy-recovery.service`:

```ini
[Unit]
Description=PV-Inverter-Proxy Boot-Time Recovery (SAFETY-04)
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

### Ordering Rationale

- `After=local-fs.target` — `/var/lib/` and `/opt/` must be mounted before we stat markers or flip symlinks.
- `Before=pv-inverter-proxy.service` — recovery runs to completion before the main service starts. If recovery flips the symlink, the main service starts against the rolled-back release.
- `RequiredBy=pv-inverter-proxy.service` in `[Install]` — `systemctl enable pv-inverter-proxy-recovery.service` is implicit when enabling the main service. The main service refuses to start if the recovery unit is masked: either the safety net is active or we don't boot. The install.sh script in plan 43-04 enables both explicitly as belt-and-braces.
- `User=root` — only root can modify `/opt/pv-inverter-proxy-releases/current`, which is root-owned after the v8.0 layout migration (plan 43-04). The main service runs as unprivileged `pv-proxy` and cannot touch the symlink — that's the whole point of splitting recovery into its own unit.

## Recovery Decision Flow

```
load_pending_marker()
    │
    ├─ None (no file or corrupt) ─→ "no_pending" (normal boot)
    │
    └─ valid PendingMarker
            │
            ├─ LAST_BOOT_SUCCESS.mtime > marker.created_at?
            │       └─ YES → "stale_pending_cleaned" (delete marker)
            │
            └─ NO (or marker absent)
                    │
                    ├─ previous_release.is_dir() ?
                    │       └─ NO → "target_missing" (log CRITICAL, KEEP marker for human)
                    │
                    └─ YES
                            │
                            ├─ _atomic_symlink_flip() raises OSError?
                            │       └─ YES → "flip_failed" (log CRITICAL, KEEP marker)
                            │
                            └─ NO → "rolled_back" (log WARNING, DELETE marker)
```

All 5 outcomes exit 0 at the `main()` layer. The 3 outcomes where the marker is KEPT (`target_missing`, `flip_failed`, plus a user-crafted bad marker) will re-trigger the same code path on the next boot; if the underlying condition has been fixed (release directory restored, permissions corrected), the rollback will proceed. If not, it will loop in a harmless no-op.

## Open Issues / Phase 45 TODO

1. **`previous_release` prefix validation.** Currently the check is `isinstance(prev, str) and prev.startswith("/") and previous.is_dir()`. An attacker with write access to the PENDING marker file could point at any readable directory on disk (e.g. `/etc`, `/home/user/repo`). The `is_dir()` check reduces this to "directories readable by root" which is not a new attack surface, but Phase 45 should tighten this to `prev.startswith(str(RELEASES_ROOT))` once Phase 45 becomes the authoritative marker writer. Noted in T-43-03-02 of the plan's threat register.

2. **Nonce cross-check with processed-nonces.json.** Phase 45's privileged updater will embed a nonce in the PENDING marker that cross-references the updater's signed update bundle. recovery.py should reject PENDING markers whose nonce is not present in processed-nonces.json. For Phase 43, the marker has no nonce field — we accept the T-43-03-09 defense-in-depth gap.

3. **Recovery unit deployment.** The unit files are NOT installed to `/etc/systemd/system/` in this plan — they live in `config/` in the source tree. Plan 43-04's `install.sh` will copy them into place, run `systemctl daemon-reload`, and enable both. Integration verification (`systemctl status pv-inverter-proxy-recovery.service` on the LXC) happens in plan 43-04.

4. **Healthy flag + LAST_BOOT_SUCCESS writer.** Plan 43-03 does NOT wire `__main__.py` to write the healthy flag or the last-boot-success marker. That's plan 43-04. Until then, the recovery service is callable but effectively dormant — any PENDING marker created manually would always result in `rolled_back` (because LAST_BOOT_SUCCESS is never present).

## Test Coverage

31 tests in `tests/test_recovery.py`, all passing in ~0.08s:

| Area | Tests | Coverage |
|------|-------|----------|
| `load_pending_marker` | 14 | missing file, corrupt JSON, array-not-dict, wrong schema_version, missing schema_version, missing previous, previous wrong type, previous not absolute, target not absolute, missing created_at, created_at wrong type, valid happy, reason defaults, int created_at coercion |
| `clear_pending_marker` | 3 | removes existing, missing-ok, swallows OSError |
| `recover_if_needed` | 9 | no_pending, corrupt→no_pending, stale_cleaned, target_missing (marker preserved), rolled_back (happy), rolled_back idempotent, flip_failed (marker preserved, symlink untouched), last_success older→rollback, last_success equal→rollback |
| `main` | 3 | returns 0 on no_pending, returns 0 on exception, returns 0 on target_missing |
| `_atomic_symlink_flip` | 2 | direct flip, cleans stale current.new from prior crash |

No test touches `/opt`, `/var`, or `/run` — all filesystem operations are tmp_path scoped. `_atomic_symlink_flip` is monkeypatched to raise OSError for the `flip_failed` case rather than relying on chmod permissions (which behave differently on macOS vs Linux).

## Deviations from Plan

### [Additive] Three extra tests beyond plan's ~22

- **Extra tests added:**
  - `test_load_pending_missing_schema_version` — explicit check for absent schema_version field (plan only covered wrong value)
  - `test_load_pending_previous_wrong_type` — previous_release as int instead of str
  - `test_load_pending_target_not_absolute` — symmetrical check for target path validation
  - `test_load_pending_created_at_wrong_type` — created_at as string
  - `test_load_pending_integer_created_at_ok` — explicit coverage of JSON int → Python float coercion path
  - `test_clear_pending_swallows_oserror` — monkeypatched OSError path (plan only covered missing file)
  - `test_recover_last_success_equal_to_marker_triggers_rollback` — equality edge case for stale detection (plan only had strict > case)
  - `test_main_returns_zero_on_target_missing` — explicit assertion that critical outcomes still exit 0
  - `test_atomic_symlink_flip_cleans_stale_tmp` — crash-recovery test for the tmp symlink cleanup branch
- **Reason:** Branch coverage — each defensive path in `load_pending_marker` deserves its own test so a future refactor that drops a check is immediately detected. The plan specified "~22 tests" and "9 parse error paths" for `load_pending_marker`; I ended up with 14 tests there. All are additive; no plan-specified test was removed or rewritten.
- **Files modified:** `tests/test_recovery.py` (test file) — no source changes triggered by this expansion.

No other deviations. Auto-fix rules 1-3 did not fire: no bugs found, no missing critical functionality, no blocking issues. The plan was executed exactly as specified for tasks 1, 2, and 3; task 4 was extended additively for branch coverage.

## Commits

| Hash | Type | Message |
|------|------|---------|
| `4b44297` | feat | `feat(43-03): harden systemd unit with StartLimit, RuntimeDirectory, KillMode` |
| `9b3c023` | feat | `feat(43-03): add boot-time recovery service` |
| `bca8bd6` | test | `test(43-03): add recovery unit tests` |

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Main unit has all 6 new directives | `grep -cE "StartLimitBurst=10\|StartLimitIntervalSec=120\|TimeoutStopSec=15\|KillMode=mixed\|RuntimeDirectory=pv-inverter-proxy\|ReadWritePaths=/etc/pv-inverter-proxy /var/lib/pv-inverter-proxy" config/pv-inverter-proxy.service` | 6 |
| Recovery unit exists | `test -f config/pv-inverter-proxy-recovery.service` | ok |
| Recovery unit directives | `grep -q "Type=oneshot\|Before=pv-inverter-proxy.service\|User=root\|pv_inverter_proxy.recovery\|RequiredBy=pv-inverter-proxy.service"` | all present |
| Module imports | `python -c "from pv_inverter_proxy.recovery import main, recover_if_needed, PENDING_MARKER_PATH, LAST_BOOT_SUCCESS_PATH, PendingMarker, load_pending_marker, clear_pending_marker; print('ok')"` | ok |
| Recovery tests | `.venv/bin/python -m pytest tests/test_recovery.py -q` | 31 passed in 0.08s |
| Full suite | `.venv/bin/python -m pytest tests/ -q` | 684 passed, 1 failed (pre-existing `test_config_get_venus_defaults` documented in `deferred-items.md` from plan 43-01, unrelated) |
| End-to-end main() | `.venv/bin/python -c "from pv_inverter_proxy.recovery import main; rc = main(); print(rc)"` | Emits JSON `no_pending_marker` + `recovery_complete outcome=no_pending` to stdout, exit 0 |

## Known Stubs

None. recovery.py is a complete, self-contained module with no TODO-in-code placeholders. The open issues listed above (prefix validation, nonce cross-check) are intentional Phase 45 extension points documented in this summary and in the plan's threat register (T-43-03-02, T-43-03-09) — not stubs in the code.

The healthy-flag writer in `__main__.py` and the PENDING marker writer in `install.sh` are explicit plan-43-04 scope, not stubs in this plan.

## Self-Check: PASSED

- `config/pv-inverter-proxy.service` modified (27 lines, all 6 directives verified present)
- `config/pv-inverter-proxy-recovery.service` created (18 lines, all required directives verified)
- `src/pv_inverter_proxy/recovery.py` created (245 lines ≥ 180 min required)
- `tests/test_recovery.py` created (453 lines ≥ 220 min required)
- All exported symbols present: `main`, `recover_if_needed`, `load_pending_marker`, `clear_pending_marker`, `PendingMarker`, `PENDING_MARKER_PATH`, `LAST_BOOT_SUCCESS_PATH`
- Commit `4b44297` present in git log (feat — systemd hardening)
- Commit `9b3c023` present in git log (feat — recovery service + module)
- Commit `bca8bd6` present in git log (test — recovery unit tests)
- 31/31 recovery tests passing
- 684/685 full suite passing (the 1 failure is pre-existing from plan 43-01, unrelated)
- End-to-end `main()` invocation on dev machine returns 0 and logs `no_pending`
- No deployment to LXC in this plan — that's plan 43-04 (as specified)
- Recovery script NEVER returns non-zero (verified by 3 dedicated tests)
