---
phase: 45-privileged-updater-service
plan: 03
subsystem: updater_root / privileged primitives
tags: [updater, updater_root, EXEC-02, EXEC-04, EXEC-05, EXEC-10, SEC-05, SEC-06, trust-boundary]
requires:
  - "Phase 43 releases.py (RELEASES_ROOT, select_releases_to_delete, check_disk_space)"
  - "Phase 43 recovery.py (PendingMarker schema, PENDING_MARKER_PATH)"
  - "Phase 45-02 updater/trigger.py (schema mirror source)"
provides:
  - "updater_root/__init__.py package marker with UPDATER_ROOT_SCHEMA_VERSION"
  - "updater_root/git_ops.py async subprocess wrappers (run_git, git_fetch, git_rev_parse, is_sha_on_main, git_clone_shared, git_checkout_detach, git_status_porcelain)"
  - "updater_root/backup.py create_backup + apply_backup_retention + apply_release_retention"
  - "updater_root/trigger_reader.py read_and_validate_trigger + NonceDedupStore + validate_tag_regex"
  - "updater_root/gpg_verify.py compute_sha256 + verify_sha256sums_file + verify_sha256sums_signature"
  - "tests/test_updater_trust_boundary.py AST-based boundary enforcement"
affects:
  - "Plan 45-04 orchestrator composes these primitives into the runner state machine"
  - "Plan 45-04 systemd .service + .path units will run against this code as root"
  - "Phase 47 SHA-256 git objectFormat upgrade will strengthen is_sha_on_main (EXEC-10)"
tech-stack:
  added: []
  patterns:
    - "Async subprocess wrappers via asyncio.create_subprocess_exec (never shell=True)"
    - "Explicit argv passing so ';touch file' stays a literal git arg"
    - "Atomic JSON writes via tempfile + os.replace (pattern reused from state_file.save_state)"
    - "Fail-open on dedup store corruption (reprocess one trigger > permanent lockout)"
    - "Independent schema mirror at trust boundary (trigger_reader does NOT import updater.trigger)"
    - "AST-based import enforcement for filesystem-level trust boundaries"
key-files:
  created:
    - "src/pv_inverter_proxy/updater_root/__init__.py"
    - "src/pv_inverter_proxy/updater_root/git_ops.py"
    - "src/pv_inverter_proxy/updater_root/backup.py"
    - "src/pv_inverter_proxy/updater_root/trigger_reader.py"
    - "src/pv_inverter_proxy/updater_root/gpg_verify.py"
    - "tests/test_updater_root_git_ops.py"
    - "tests/test_updater_root_backup.py"
    - "tests/test_updater_root_trigger_reader.py"
    - "tests/test_updater_root_gpg_verify.py"
    - "tests/test_updater_trust_boundary.py"
  modified: []
decisions:
  - "is_sha_on_main is the EXEC-04 security root of trust — uses 'git merge-base --is-ancestor' against refs/remotes/origin/main, any non-zero exit returns False (conservative)"
  - "NonceDedupStore fails open on corrupt file (returns has_seen=False) — reprocessing one trigger is strictly safer than permanent update lockout in a safety-critical system"
  - "mark_seen is only called AFTER full trigger validation passes, so a malformed trigger cannot poison the dedup store"
  - "Trigger schema is MIRRORED in trigger_reader.py (not imported from updater.trigger) — importing would cross the trust boundary"
  - "apply_release_retention is the FIRST place in the codebase that actually deletes release directories; releases.py stays read-only per Phase 43 decision"
  - "gpg_verify primitives ship fully tested but are DORMANT in Phase 45 runtime — Plan 45-04 uses git-based install so EXEC-10 integrity is delivered by git SHA content-hashing, not SHA256SUMS verification"
  - "SEC-05 default remains allow_unsigned=True for v8.0; v8.1 will flip it"
  - "Trust boundary enforced via AST walk (not grep) to avoid false positives from docstring mentions like 'updater_root/runner.py' in updater/status.py"
metrics:
  duration: "~50m"
  completed: "2026-04-10"
  tests_added: 84
  tests_passing: 84
  lines_of_code_src: 888
  lines_of_code_tests: 1337
---

# Phase 45 Plan 03: updater_root Privileged Primitives Summary

Shipped the `src/pv_inverter_proxy/updater_root/` package — four privileged primitive modules (git_ops, backup, trigger_reader, gpg_verify) plus a filesystem-enforced trust boundary. Nothing in the main service imports from this package, and the package itself only reaches into the narrow `releases / recovery / state_file` allowlist. Plan 45-04's orchestrator will compose these primitives into a runner state machine that runs as root under systemd.

Zero new dependencies (stdlib `asyncio`, `hashlib`, `tarfile`, `shutil`, `tempfile`, `pathlib`, `json`, `ast`, `re`, `dataclasses`). All 84 tests are hermetic: the only real subprocess they run is `git` against tmp_path repos (never network, never `/opt`, never `/var/lib`), and `gpg` is 100% monkey-patched.

## Requirements Coverage

| REQ | Evidence |
|-----|----------|
| EXEC-02 | `trigger_reader.read_and_validate_trigger` enforces strict key-set equality against `ALLOWED_KEYS` — extras AND missing fields both fail. Tests `test_read_extra_keys_rejected`, `test_read_missing_key`, plus nonce dedup via `NonceDedupStore` (persisted to `/var/lib/pv-inverter-proxy/processed-nonces.json`, trimmed to 50 newest). `test_nonce_dedup_replay_raises`, `test_nonce_dedup_trims_to_max`, `test_nonce_dedup_corrupt_file_treated_as_empty`. |
| EXEC-04 | `git_ops.is_sha_on_main` runs `git merge-base --is-ancestor <sha> refs/remotes/origin/main`. Tests `test_is_sha_on_main_true`, `test_is_sha_on_main_false_fabricated`, `test_is_sha_on_main_unrelated_chain` (orphan branch commit rejected). Security root of trust — conservative: any non-zero exit returns False. |
| EXEC-05 | `backup.create_backup` writes the three pre-update artifacts (venv-<ts>.tar.gz, config-<ts>.yaml, pyproject-<ts>.toml) with mode 0640. Tests `test_create_backup_produces_three_files`, `test_venv_tarball_roundtrip`, `test_file_modes_0640`, `test_timestamp_in_name`, `test_pyproject_missing_placeholder`. |
| EXEC-07 | Deferred to 45-04 (orchestrator will call `pip install --dry-run` via a helper). Not in scope for primitives plan. |
| EXEC-10 | `gpg_verify.compute_sha256` + `verify_sha256sums_file` parse the SHA256SUMS manifest and verify every listed file. Tests `test_verify_sha256sums_file_all_match`, `test_verify_sha256sums_file_mismatch`, `test_verify_sha256sums_file_binary_mode_prefix`, `test_verify_sha256sums_file_ignores_blank_and_comments`. **Runtime status:** Plan 45-04 uses a git-based install path (`git clone --shared` + `git checkout --detach` against origin/main), so EXEC-10 integrity is delivered by the git SHA content-hash (SHA-1 today, SHA-256 after Phase 47 `extensions.objectFormat` upgrade). These SHA256SUMS primitives are therefore DORMANT in the v8.0 runner, reserved for a potential Phase 47 tarball-alternative install path. They are still fully unit-tested so Phase 47 can enable them without re-plumbing. |
| SEC-05 | `gpg_verify.verify_sha256sums_signature` short-circuits when `GpgConfig.allow_unsigned=True` (the v8.0 default) — `test_allow_unsigned_skips_gpg` asserts zero subprocess invocations. When `allow_unsigned=False`, status output is parsed for GOODSIG/VALIDSIG/BADSIG/EXPSIG/EXPKEYSIG. Tests `test_gpg_verify_goodsig_validsig`, `test_gpg_verify_badsig`, `test_gpg_verify_expired`, `test_gpg_verify_keyring_injection`, `test_gpg_verify_timeout`, `test_gpg_verify_unexpected_status`. |
| SEC-06 | `trigger_reader.validate_tag_regex` enforces `^v\d+\.\d+(\.\d+)?$`. Tests accept `v8.0`, `v8.0.1`, `v10.20.30`; reject `8.0`, `v8.0.0-rc1`, `v8`, `main`, `latest`, `v8.0.0.0`. Exposed for Plan 45-04 orchestrator use when mapping a GitHub tag to a SHA. |
| Trust boundary | `tests/test_updater_trust_boundary.py` — AST-based enforcement (not grep). Walks `src/pv_inverter_proxy/` and parses every file via `ast.parse`, collects every `ast.Import` and `ast.ImportFrom`, asserts: (1) nothing outside `updater_root/` imports `pv_inverter_proxy.updater_root.*`; (2) `updater_root/**` only imports from `{releases, recovery, state_file}`; (3) `updater_root/**` never imports `pv_inverter_proxy.updater.*`. 4 tests, 0 violations. |

## Trust Boundary Verification

```
$ grep -rn "updater_root" src/pv_inverter_proxy/ | grep -v "src/pv_inverter_proxy/updater_root/"
src/pv_inverter_proxy/updater/status.py:12:    ``updater_root/runner.py`` (running as root, Plan 45-03/04). The
```

The single match outside `updater_root/` is a **docstring reference** in `updater/status.py` line 12 describing future architecture — not an import. The AST-based test correctly ignores it because no `ast.Import`/`ast.ImportFrom` node references `pv_inverter_proxy.updater_root`.

```
$ grep -rn "from pv_inverter_proxy\." src/pv_inverter_proxy/updater_root/
src/pv_inverter_proxy/updater_root/backup.py:23:from pv_inverter_proxy.releases import (
```

Exactly one allowlisted cross-import: `backup.py` imports `releases.DEFAULT_KEEP_RELEASES` and `releases.select_releases_to_delete`. All other `updater_root` modules are fully self-contained + stdlib + `structlog`.

The allowlist permits `releases`, `recovery`, and `state_file`; only `releases` is used by Plan 45-03. `recovery` and `state_file` are reserved for Plan 45-04.

## Test Results

```
$ .venv/bin/python -m pytest tests/test_updater_root_git_ops.py \
    tests/test_updater_root_backup.py \
    tests/test_updater_root_trigger_reader.py \
    tests/test_updater_root_gpg_verify.py \
    tests/test_updater_trust_boundary.py
tests/test_updater_root_git_ops.py         ...............        15 passed
tests/test_updater_root_backup.py          ................       16 passed
tests/test_updater_root_trigger_reader.py  .............................   29 passed
tests/test_updater_root_gpg_verify.py      ....................   20 passed
tests/test_updater_trust_boundary.py       ....                    4 passed
======================== 84 passed in 2.13s =========================
```

### Per-module breakdown

| Module | src LOC | test LOC | Tests |
|--------|--------:|---------:|------:|
| `updater_root/__init__.py` | 16 | — | — |
| `updater_root/git_ops.py` | 192 | 230 | 15 |
| `updater_root/backup.py` | 185 | 278 | 16 |
| `updater_root/trigger_reader.py` | 315 | 330 | 29 |
| `updater_root/gpg_verify.py` | 180 | 350 | 20 |
| `test_updater_trust_boundary.py` | — | 149 | 4 |
| **Total** | **888** | **1337** | **84** |

### Full-suite regression

```
$ .venv/bin/python -m pytest
1 failed, 939 passed, 531 warnings in 47.28s
```

The single failure is `tests/test_webapp.py::test_config_get_venus_defaults`, which is **pre-existing on main since Phase 45-01** and already logged in `deferred-items.md`. Verified unrelated to this plan — the failing test touches the `/api/config` GET path, not `/api/update/*`. All 938 previously-green tests remain green plus the 84 new tests from this plan.

## Key Design Decisions

1. **Independent schema mirror at the trust boundary.** `trigger_reader.py` re-implements trigger validation rather than importing `updater.trigger.TriggerPayload`. Importing would put main-service code in root's import path at runtime — exactly what the trust boundary forbids. The tradeoff is a duplicated `ALLOWED_KEYS` / `SHA_RE` / `TAG_RE` / `VALID_OPS` set, which is acceptable because the trigger schema is tiny and closed (5 fields, explicit evolution via `schema_version` bump).

2. **Fail-open on dedup store corruption.** If `/var/lib/pv-inverter-proxy/processed-nonces.json` is corrupted (partial write, filesystem error, manual tampering), `NonceDedupStore._load` returns an empty list with a warning. The alternative — fail-closed — would lock out all updates permanently after a single corrupt write, which is catastrophic for a remote-managed safety system. Re-processing one trigger is strictly safer. The replay window is still bounded by the operator monitoring the update-audit log.

3. **mark_seen only after full validation.** A malformed trigger (bad SHA, invalid op, extra keys) can never add its nonce to the dedup store. This prevents an attacker who can write the trigger file from "burning" specific nonces by submitting bogus triggers.

4. **Conservative `is_sha_on_main`.** Any non-zero exit from `git merge-base --is-ancestor` returns `False`, not just the "not an ancestor" exit code 1. This catches "bad object" (exit 128), "repository not initialized", and any other error shape as rejection. The cost is that a genuine git breakage produces "update refused" instead of a surfaced error, but the main service's health scheduler will catch a broken updater via `CHECK-06` / Phase 47's `HELPER-02` heartbeat.

5. **gpg_verify primitives are dormant but tested.** Plan 45-04's orchestrator delivers EXEC-10 via git SHA content-hashing (a SHA on `origin/main` is cryptographically guaranteed to contain the expected tree). SHA256SUMS+GPG is a separate mechanism for tarball distribution, which Phase 45 does not use. Keeping the primitives fully tested means Phase 47 can flip to tarball-based install (e.g. for offline LXCs that can't reach github.com) without re-plumbing verification logic.

6. **AST trust boundary (not grep).** A regex-based approach would have flagged the `updater_root/runner.py` docstring in `updater/status.py`. The AST walk inspects only `ast.Import` and `ast.ImportFrom` nodes, so text inside comments, docstrings, string literals, and identifier names cannot produce false positives. Future plans can safely mention `updater_root` in docs/comments without tripping the test.

## Known Stubs

None. All modules are fully implemented. The `gpg_verify` module is dormant in the v8.0 runtime path by design (documented in module docstring and EXEC-10 coverage above), not because of missing code.

## Deviations from Plan

### Rule-based auto-fixes

**1. [Rule 1 — Bug] `test_run_git_no_shell` initial assertion too strict**

- **Found during:** Task 1 test execution
- **Issue:** The plan suggested asserting that `"hacked"` does not appear in stdout/stderr of `run_git(";echo hacked")`. That fails because git echoes the invalid subcommand in its error message (`git: ';echo hacked' is not a git command`).
- **Fix:** Rewrote the test to use a marker file (`f";touch {tmp_path / 'pwned_marker'}"`) and assert the marker does NOT exist after the call. This is a more rigorous shell-invocation probe — if a shell actually ran, the marker would be created regardless of how git echoed the string.
- **Files modified:** `tests/test_updater_root_git_ops.py`
- **Committed as part of:** `aa4afc0` (initial git_ops commit)

### Plan literal deviation: plan suggested using `grep` for Task 5 enforcement

- **Plan text:** Task 5 suggested a regex like `re.compile(r"from pv_inverter_proxy\.updater_root|import pv_inverter_proxy\.updater_root")`.
- **Actual implementation:** Switched to AST walk (`ast.parse` + `ast.Import` / `ast.ImportFrom`) because the simpler regex would produce a false positive on `updater/status.py:12` (a docstring that mentions `updater_root/runner.py` as future code).
- **Impact:** The AST approach is strictly stronger — it catches the same import patterns with zero false positives. Added as a fourth test (`test_updater_root_package_exists_and_has_expected_modules`) as a sanity check that the package layout is what downstream tests assume.
- **Security impact:** None; the AST approach is more precise than grep, not less.

## Commits

| Commit | Message |
|--------|---------|
| `aa4afc0` | feat(45-03): add updater_root package marker + git_ops primitives |
| `3075002` | feat(45-03): add updater_root backup helpers |
| `aa86811` | feat(45-03): add updater_root trigger_reader with nonce dedup |
| `7f3c1e7` | feat(45-03): add updater_root gpg_verify primitives |
| `84c84c7` | test(45-03): enforce updater_root trust boundary via AST walk |

## Deferred Issues

None introduced by this plan. The pre-existing `test_config_get_venus_defaults` failure remains logged in `deferred-items.md` from Phase 45-01 — unrelated to any updater work.

## Self-Check: PASSED

- `src/pv_inverter_proxy/updater_root/__init__.py` FOUND (contains `UPDATER_ROOT_SCHEMA_VERSION`)
- `src/pv_inverter_proxy/updater_root/git_ops.py` FOUND (contains `async def is_sha_on_main`, `run_git`, `GitResult`, `GitTimeoutError`)
- `src/pv_inverter_proxy/updater_root/backup.py` FOUND (contains `create_backup`, `apply_backup_retention`, `apply_release_retention`, `BACKUP_FILE_MODE=0o640`)
- `src/pv_inverter_proxy/updater_root/trigger_reader.py` FOUND (contains `read_and_validate_trigger`, `NonceDedupStore`, `validate_tag_regex`, `NonceReplayError`)
- `src/pv_inverter_proxy/updater_root/gpg_verify.py` FOUND (contains `compute_sha256`, `verify_sha256sums_file`, `verify_sha256sums_signature`, `GpgConfig(allow_unsigned=True)`)
- `tests/test_updater_root_git_ops.py` FOUND (15 tests passing)
- `tests/test_updater_root_backup.py` FOUND (16 tests passing)
- `tests/test_updater_root_trigger_reader.py` FOUND (29 tests passing)
- `tests/test_updater_root_gpg_verify.py` FOUND (20 tests passing)
- `tests/test_updater_trust_boundary.py` FOUND (4 tests passing, 0 violations)
- Commits FOUND: `aa4afc0`, `3075002`, `aa86811`, `7f3c1e7`, `84c84c7`
- Trust boundary grep clean (only docstring reference in `updater/status.py`)
- No main-service code imports `updater_root` (AST-enforced)
- `updater_root` only imports `pv_inverter_proxy.releases` (1 import in backup.py)
- SEC-05 default `allow_unsigned=True` confirmed via `test_gpg_config_default_allow_unsigned`
- Full regression: 939 passed, 1 pre-existing unrelated failure (already deferred)
