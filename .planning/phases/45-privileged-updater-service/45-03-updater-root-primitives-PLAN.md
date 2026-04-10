---
phase: 45-privileged-updater-service
plan: 03
type: execute
wave: 3
depends_on:
  - "45-02"
files_modified:
  - src/pv_inverter_proxy/updater_root/__init__.py
  - src/pv_inverter_proxy/updater_root/git_ops.py
  - src/pv_inverter_proxy/updater_root/backup.py
  - src/pv_inverter_proxy/updater_root/gpg_verify.py
  - src/pv_inverter_proxy/updater_root/trigger_reader.py
  - tests/test_updater_root_git_ops.py
  - tests/test_updater_root_backup.py
  - tests/test_updater_root_trigger_reader.py
  - tests/test_updater_root_gpg_verify.py
autonomous: true
requirements:
  - EXEC-02
  - EXEC-04
  - EXEC-05
  - EXEC-07
  - EXEC-10
  - SEC-05
  - SEC-06
must_haves:
  truths:
    - "updater_root is a brand-new package isolated from the main service code (no main-service code imports it)"
    - "git_ops provides async wrappers for: fetch origin, clone --shared, checkout --detach, rev-parse, merge-base --is-ancestor"
    - "backup creates a venv tarball and config.yaml snapshot into /var/lib/pv-inverter-proxy/backups/ and uses releases.select_releases_to_delete for retention"
    - "trigger_reader loads and validates the trigger file, enforces SHA format, tag regex (SEC-06), and nonce deduplication against /var/lib/pv-inverter-proxy/processed-nonces.json (last 50)"
    - "gpg_verify implements optional SHA256SUMS.asc verification; when updates.allow_unsigned=true the verifier is a no-op that returns True"
    - "The trust boundary is grep-verifiable: `grep -r 'updater_root' src/pv_inverter_proxy/updater/ src/pv_inverter_proxy/webapp.py src/pv_inverter_proxy/__main__.py` returns ZERO matches"
    - "Every module has hermetic unit tests using fakes for subprocess and filesystem"
  artifacts:
    - path: "src/pv_inverter_proxy/updater_root/__init__.py"
      provides: "Package marker with version constant"
      min_lines: 5
    - path: "src/pv_inverter_proxy/updater_root/git_ops.py"
      provides: "async git subprocess wrappers"
      contains: "async def is_sha_on_main"
    - path: "src/pv_inverter_proxy/updater_root/backup.py"
      provides: "create_backup, apply_retention"
      contains: "def create_backup"
    - path: "src/pv_inverter_proxy/updater_root/gpg_verify.py"
      provides: "verify_sha256sums_signature (no-op when unsigned allowed)"
      contains: "def verify_sha256sums_signature"
    - path: "src/pv_inverter_proxy/updater_root/trigger_reader.py"
      provides: "read_and_validate_trigger, NonceDedupStore"
      contains: "class NonceDedupStore"
  key_links:
    - from: "src/pv_inverter_proxy/updater_root/trigger_reader.py"
      to: "updater/trigger.py TriggerPayload schema (v1)"
      via: "schema mirror — independent decode + re-validate"
      pattern: "op.*target_sha.*nonce"
    - from: "src/pv_inverter_proxy/updater_root/backup.py"
      to: "pv_inverter_proxy.releases.select_releases_to_delete"
      via: "direct import (releases is read-only, safe to import from root context)"
      pattern: "from pv_inverter_proxy.releases import"
    - from: "src/pv_inverter_proxy/updater_root/git_ops.py"
      to: "asyncio.create_subprocess_exec"
      via: "stdlib only, no GitPython"
      pattern: "create_subprocess_exec"
---

<objective>
Create the `updater_root/` Python package containing the privileged primitives: git subprocess wrappers, backup manager, GPG verifier, trigger reader with nonce dedup. NO orchestrator yet (Plan 45-04), NO systemd units yet (Plan 45-04). Pure code + unit tests, all hermetic, all runnable on any dev machine without root.

Purpose: Establish the trust boundary and ship the primitives in isolation so the orchestrator in Plan 45-04 is a thin state machine over tested building blocks. This plan is the one that crosses the trust boundary — everything here runs as root in production.

Output: A new `src/pv_inverter_proxy/updater_root/` package (not imported anywhere by the main service), 4 primitive modules, 4 test files, and a grep-verifiable trust boundary.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@.planning/research/STACK.md
@src/pv_inverter_proxy/releases.py
@src/pv_inverter_proxy/recovery.py
@src/pv_inverter_proxy/updater/trigger.py

<interfaces>
<!-- Schema mirror: updater_root/trigger_reader.py re-implements validation
     independently of updater/trigger.py. The trust boundary forbids importing
     updater code from updater_root. -->

From updater/trigger.py schema (mirror, do NOT import):
```python
{
  "op": "update" | "rollback",
  "target_sha": "<40-char hex>" | "previous",
  "requested_at": "<ISO-8601 Z>",
  "requested_by": "<string>",
  "nonce": "<uuid4>"
}
```

From releases.py (safe to import — read-only, no side effects):
```python
RELEASES_ROOT: Path = Path("/opt/pv-inverter-proxy-releases")
INSTALL_ROOT: Path = Path("/opt/pv-inverter-proxy")
DEFAULT_KEEP_RELEASES: int = 3
MIN_FREE_BYTES: int = 500 * 1024 * 1024

def current_release_dir(releases_root: Path | None = None) -> Path | None: ...
def list_release_dirs(releases_root: Path | None = None) -> list[Path]: ...
def select_releases_to_delete(
    releases_root: Path | None = None,
    keep: int = DEFAULT_KEEP_RELEASES,
    protect: set[Path] | None = None,
) -> list[Path]: ...
def check_disk_space(min_free_bytes=MIN_FREE_BYTES, ...) -> DiskSpaceReport: ...
```

From recovery.py (safe to import — schema and constants):
```python
PENDING_MARKER_PATH: Path = Path("/var/lib/pv-inverter-proxy/update-pending.marker")

@dataclass
class PendingMarker:
    previous_release: str
    target_release: str
    created_at: float
    reason: str = "update"
    schema_version: int = 1
```
</interfaces>

## Trust boundary — CRITICAL

`src/pv_inverter_proxy/updater_root/` is root-only code. The main service NEVER imports from this package. The only allowed cross-imports are the OTHER direction (updater_root importing narrow read-only helpers from the main package):

ALLOWED imports from main package:
- `pv_inverter_proxy.releases` — read-only layout helpers, constants, disk check
- `pv_inverter_proxy.recovery` — PendingMarker schema and path constants ONLY
- `pv_inverter_proxy.state_file` — NOT imported in Plan 45-03 (reserved for Plan 45-04)

FORBIDDEN imports:
- `pv_inverter_proxy.webapp` — NEVER
- `pv_inverter_proxy.__main__` — NEVER
- `pv_inverter_proxy.context` — NEVER
- `pv_inverter_proxy.proxy` — NEVER
- `pv_inverter_proxy.distributor` — NEVER
- `pv_inverter_proxy.control` — NEVER
- `pv_inverter_proxy.updater.*` — NEVER (schema must be mirrored independently)

Task 5 below is a grep-verified enforcement step.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: updater_root/git_ops.py — async subprocess wrappers</name>
  <files>src/pv_inverter_proxy/updater_root/__init__.py, src/pv_inverter_proxy/updater_root/git_ops.py, tests/test_updater_root_git_ops.py</files>
  <behavior>
    API:
    - `async def run_git(*args, cwd: Path, timeout_s: float = 60.0) -> GitResult`:
        * Wraps asyncio.create_subprocess_exec("git", *args, cwd=str(cwd), stdout=PIPE, stderr=PIPE)
        * Returns GitResult(returncode, stdout, stderr)
        * Never uses shell=True
        * Raises GitTimeoutError on timeout
        * Does NOT raise on non-zero exit (caller decides)
    - `async def git_fetch(repo_dir: Path, remote: str = "origin") -> GitResult`
    - `async def git_rev_parse(repo_dir: Path, ref: str) -> str | None`:
        * Returns stripped stdout on returncode==0, None otherwise
    - `async def is_sha_on_main(repo_dir: Path, sha: str, main_ref: str = "refs/remotes/origin/main") -> bool`:
        * EXEC-04: runs `git merge-base --is-ancestor <sha> <main_ref>`
        * Returns True iff returncode==0
        * Security root of trust — rejects any SHA not reachable from origin/main
    - `async def git_clone_shared(source: Path, dest: Path) -> GitResult`:
        * `git clone --shared --no-checkout <source> <dest>`
        * --shared reuses the object store from the existing release (saves bandwidth, ~10x faster)
    - `async def git_checkout_detach(repo_dir: Path, sha: str) -> GitResult`:
        * `git -C <repo_dir> checkout --detach <sha>`
        * Detached head avoids branch state on the new release dir

    Exceptions:
    - `class GitTimeoutError(Exception)`
    - `class GitOpsError(Exception)` — for unexpected shapes

    Test cases (hermetic — use a temp git repo, no network):
    - test_run_git_basic: run `git --version` -> returncode 0, stdout starts with "git version "
    - test_run_git_nonzero_exit: run `git nonexistent-cmd` -> returncode != 0, NO raise
    - test_run_git_timeout: monkeypatch asyncio.wait_for to raise TimeoutError -> GitTimeoutError
    - test_git_fetch_local: create a bare repo, clone it, add a commit to the bare, fetch from clone -> 0
    - test_git_rev_parse_head: returns 40-char hex
    - test_git_rev_parse_bad_ref: returns None
    - test_is_sha_on_main_true: create a 3-commit linear history, check the middle commit is ancestor of HEAD -> True
    - test_is_sha_on_main_false: check a fabricated SHA "0000..." -> False (returncode != 0)
    - test_is_sha_on_main_unrelated: create two separate commit chains, check ancestry between them -> False
    - test_git_clone_shared: clone a local repo with --shared, verify dest has .git/objects/info/alternates
    - test_git_checkout_detach: checkout a specific SHA -> returncode 0, HEAD points at the SHA
    - test_run_git_no_shell: verify that a malicious arg like `"; rm -rf /"` is passed literally, not interpreted
      (assert subprocess.PIPE, not shell=True — inspect the create_subprocess_exec call via monkeypatch)

    Note on tests: Use `pytest-asyncio` (already in deps or add it). Use `tmp_path` and create
    ephemeral git repos. NEVER hit the network. If pytest-asyncio is missing, use
    `asyncio.run(test_coro())` inline.
  </behavior>
  <action>
    Step 1: Create `src/pv_inverter_proxy/updater_root/__init__.py`:

    ```python
    """Root-only privileged updater package (Phase 45).

    This package is imported ONLY from the pv-inverter-proxy-updater.service
    systemd unit, which runs as root. The main service (pv-inverter-proxy.service,
    User=pv-proxy) MUST NEVER import from this package. The trust boundary is
    filesystem-enforced and grep-verifiable.

    Allowed imports from pv_inverter_proxy.*:
        - releases     (read-only constants + layout helpers)
        - recovery     (PendingMarker schema + path constants)
        - state_file   (Plan 45-04 only)

    Forbidden:
        - webapp, __main__, context, proxy, distributor, control, updater.*
    """
    UPDATER_ROOT_SCHEMA_VERSION = 1
    ```

    Step 2: Create `src/pv_inverter_proxy/updater_root/git_ops.py`:

    ```python
    """Async git subprocess wrappers (stdlib only, no GitPython).

    Security: every call uses explicit argv with create_subprocess_exec.
    shell=True is never used. All refs are passed as positional arguments,
    never interpolated into a command string.
    """
    from __future__ import annotations

    import asyncio
    from dataclasses import dataclass
    from pathlib import Path

    import structlog

    log = structlog.get_logger(component="updater_root.git_ops")

    GIT_DEFAULT_TIMEOUT_S = 60.0
    GIT_FETCH_TIMEOUT_S = 120.0


    class GitTimeoutError(Exception):
        pass


    class GitOpsError(Exception):
        pass


    @dataclass
    class GitResult:
        returncode: int
        stdout: str
        stderr: str

        @property
        def ok(self) -> bool:
            return self.returncode == 0


    async def run_git(
        *args: str,
        cwd: Path,
        timeout_s: float = GIT_DEFAULT_TIMEOUT_S,
    ) -> GitResult:
        log.info("git_exec", args=args, cwd=str(cwd))
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s,
            )
        except asyncio.TimeoutError as e:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise GitTimeoutError(
                f"git {' '.join(args)} timed out after {timeout_s}s"
            ) from e
        return GitResult(
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )


    async def git_fetch(repo_dir: Path, remote: str = "origin") -> GitResult:
        return await run_git(
            "-C", str(repo_dir),
            "fetch", "--tags", "--quiet", remote,
            cwd=repo_dir,
            timeout_s=GIT_FETCH_TIMEOUT_S,
        )


    async def git_rev_parse(repo_dir: Path, ref: str) -> str | None:
        r = await run_git("-C", str(repo_dir), "rev-parse", ref, cwd=repo_dir)
        if not r.ok:
            return None
        return r.stdout.strip() or None


    async def is_sha_on_main(
        repo_dir: Path,
        sha: str,
        main_ref: str = "refs/remotes/origin/main",
    ) -> bool:
        """EXEC-04: security root of trust.

        Returns True iff `sha` is an ancestor of `main_ref`. This is what
        prevents a compromised pv-proxy from requesting arbitrary SHAs.
        Only SHAs already in origin/main's history are accepted.
        """
        r = await run_git(
            "-C", str(repo_dir),
            "merge-base", "--is-ancestor", sha, main_ref,
            cwd=repo_dir,
        )
        return r.ok


    async def git_clone_shared(source: Path, dest: Path) -> GitResult:
        dest.parent.mkdir(parents=True, exist_ok=True)
        return await run_git(
            "clone", "--shared", "--no-checkout",
            str(source), str(dest),
            cwd=source.parent,
            timeout_s=GIT_FETCH_TIMEOUT_S,
        )


    async def git_checkout_detach(repo_dir: Path, sha: str) -> GitResult:
        return await run_git(
            "-C", str(repo_dir),
            "checkout", "--detach", "--quiet", sha,
            cwd=repo_dir,
        )
    ```

    Step 3: Create `tests/test_updater_root_git_ops.py` with all behavior cases.

    For the ephemeral git repo, use pytest's `tmp_path` + a helper:

    ```python
    async def _init_repo(path: Path, commits: int = 1) -> list[str]:
        """Init a git repo with N commits, return list of SHAs oldest-first."""
        await run_git("init", "--quiet", cwd=path)
        # Need user.email + user.name for commits to work
        await run_git("config", "user.email", "t@t", cwd=path)
        await run_git("config", "user.name", "t", cwd=path)
        shas = []
        for i in range(commits):
            (path / f"f{i}").write_text(str(i))
            await run_git("add", f"f{i}", cwd=path)
            await run_git("commit", "--quiet", "-m", f"c{i}", cwd=path)
            sha = await git_rev_parse(path, "HEAD")
            shas.append(sha)
        return shas
    ```

    For the `is_sha_on_main` test, set up:
    - repo with 3 commits on "main" (use `git branch -M main` after init)
    - An unrelated commit chain via a detached checkout + commit with --orphan
    - Verify middle commit is ancestor of HEAD
    - Verify unrelated commit is NOT ancestor

    For the `test_run_git_no_shell` test, just assert that passing `";echo hacked"` as
    an argument to `run_git` results in a non-zero returncode (because git doesn't know
    that "command") but NO stdout contains "hacked" (proving the shell wasn't invoked).
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_git_ops.py -x -v</automated>
  </verify>
  <done>
    - updater_root/__init__.py and git_ops.py exist
    - All git_ops tests pass
    - No network calls in tests (verify via hostile DNS or just trust tmp_path usage)
    - run_git never uses shell=True (grep-verified: `grep -n 'shell=True' src/pv_inverter_proxy/updater_root/git_ops.py` returns nothing)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: updater_root/backup.py — venv tarball + config snapshot + retention</name>
  <files>src/pv_inverter_proxy/updater_root/backup.py, tests/test_updater_root_backup.py</files>
  <behavior>
    API:
    - `@dataclass BackupResult: venv_tarball: Path, config_copy: Path, pyproject_copy: Path, created_at: float`
    - `def create_backup(release_dir: Path, config_path: Path, backups_root: Path, now: float | None = None) -> BackupResult`:
        * EXEC-05: creates
            - `<backups_root>/venv-<ts>.tar.gz` (tarball of release_dir/.venv)
            - `<backups_root>/config-<ts>.yaml` (copy of config.yaml)
            - `<backups_root>/pyproject-<ts>.toml` (copy of release_dir/pyproject.toml)
        * Timestamp = `time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))`
        * Uses `tarfile.open(..., "w:gz")` + add(recursive=True)
        * Sets file mode 0640 on all outputs (root-owned, group-readable)
        * Returns BackupResult with paths
    - `def apply_backup_retention(backups_root: Path, keep: int = 3) -> list[Path]`:
        * Scans for `venv-*.tar.gz` files, sorts by mtime newest-first
        * Keeps the `keep` newest SETS (venv+config+pyproject for each timestamp)
        * Deletes the rest
        * Returns the list of deleted files
    - `def apply_release_retention(releases_root: Path, keep: int = 3, protect: set[Path] | None = None) -> list[Path]`:
        * Thin wrapper over `releases.select_releases_to_delete` that ACTUALLY deletes
        * Uses `shutil.rmtree(path, ignore_errors=False)`
        * Returns list of deleted paths
        * NOTE: This is the first place in the codebase that ACTUALLY deletes release
          directories (releases.py is read-only per Phase 43 decision).

    Test cases (hermetic, all in tmp_path):
    - test_create_backup_produces_three_files: create fake release_dir with .venv/, run create_backup, assert 3 outputs exist
    - test_venv_tarball_roundtrip: create a .venv with a known file, tarball, extract to new dir, assert file content preserved
    - test_config_snapshot_literal_copy: config.yaml with "inverter:\n  host: 1.2.3.4\n" -> snapshot has exact same bytes
    - test_pyproject_snapshot: similar
    - test_file_modes_0640: os.stat each output -> mode & 0o777 == 0o640
    - test_timestamp_in_name: now=1712755200.0 -> names contain "20240410T122000Z" (or equivalent gmtime)
    - test_apply_backup_retention_keeps_newest: create 5 sets, keep=3, assert 2 oldest sets deleted (6 files total)
    - test_apply_backup_retention_keep_all_if_under: 2 sets, keep=3, assert nothing deleted
    - test_apply_release_retention_calls_rmtree: create 5 release dirs with a current symlink to the newest;
      assert select_releases_to_delete result is rmtree'd, current is preserved
    - test_apply_release_retention_protects_previous: pass protect={prev_release}, assert prev_release is NOT deleted
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/backup.py`:

    ```python
    """Pre-update backup management (EXEC-05) + retention (SAFETY-02).

    Creates a venv tarball + config + pyproject snapshot before every update,
    and enforces retention to prevent /var/lib filling up. The retention helper
    is the FIRST place that actually deletes release directories — releases.py
    is read-only per Phase 43 decision.
    """
    from __future__ import annotations

    import os
    import shutil
    import tarfile
    import time
    from dataclasses import dataclass
    from pathlib import Path

    import structlog

    from pv_inverter_proxy.releases import (
        DEFAULT_KEEP_RELEASES,
        select_releases_to_delete,
    )

    log = structlog.get_logger(component="updater_root.backup")

    BACKUPS_ROOT_DEFAULT: Path = Path("/var/lib/pv-inverter-proxy/backups")
    BACKUP_FILE_MODE: int = 0o640


    @dataclass
    class BackupResult:
        venv_tarball: Path
        config_copy: Path
        pyproject_copy: Path
        created_at: float
        timestamp_str: str


    def _ts_str(now: float) -> str:
        return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


    def create_backup(
        release_dir: Path,
        config_path: Path,
        backups_root: Path | None = None,
        now: float | None = None,
    ) -> BackupResult:
        root = backups_root or BACKUPS_ROOT_DEFAULT
        root.mkdir(parents=True, exist_ok=True)
        t = now if now is not None else time.time()
        ts = _ts_str(t)

        venv_src = release_dir / ".venv"
        venv_dst = root / f"venv-{ts}.tar.gz"
        config_dst = root / f"config-{ts}.yaml"
        pyproject_src = release_dir / "pyproject.toml"
        pyproject_dst = root / f"pyproject-{ts}.toml"

        log.info("backup_starting", ts=ts, release=str(release_dir))
        with tarfile.open(venv_dst, "w:gz") as tar:
            if venv_src.exists():
                tar.add(str(venv_src), arcname=".venv")
            else:
                log.warning("venv_missing_skipping", path=str(venv_src))
        os.chmod(venv_dst, BACKUP_FILE_MODE)

        shutil.copy2(config_path, config_dst)
        os.chmod(config_dst, BACKUP_FILE_MODE)

        if pyproject_src.exists():
            shutil.copy2(pyproject_src, pyproject_dst)
            os.chmod(pyproject_dst, BACKUP_FILE_MODE)
        else:
            pyproject_dst.write_text("# pyproject.toml missing at backup time\n")
            os.chmod(pyproject_dst, BACKUP_FILE_MODE)

        log.info(
            "backup_complete",
            ts=ts,
            venv=str(venv_dst),
            config=str(config_dst),
            pyproject=str(pyproject_dst),
        )
        return BackupResult(
            venv_tarball=venv_dst,
            config_copy=config_dst,
            pyproject_copy=pyproject_dst,
            created_at=t,
            timestamp_str=ts,
        )


    def apply_backup_retention(
        backups_root: Path | None = None,
        keep: int = 3,
    ) -> list[Path]:
        root = backups_root or BACKUPS_ROOT_DEFAULT
        if not root.exists():
            return []
        # Group by timestamp extracted from filename
        venvs = sorted(
            root.glob("venv-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        effective_keep = max(1, keep)
        to_delete_venvs = venvs[effective_keep:]
        deleted: list[Path] = []
        for v in to_delete_venvs:
            ts = v.name[len("venv-"):-len(".tar.gz")]
            for sibling in (
                v,
                root / f"config-{ts}.yaml",
                root / f"pyproject-{ts}.toml",
            ):
                try:
                    sibling.unlink(missing_ok=True)
                    deleted.append(sibling)
                except OSError as e:
                    log.warning("backup_delete_failed", path=str(sibling), error=str(e))
        return deleted


    def apply_release_retention(
        releases_root: Path | None = None,
        keep: int = DEFAULT_KEEP_RELEASES,
        protect: set[Path] | None = None,
    ) -> list[Path]:
        to_delete = select_releases_to_delete(
            releases_root=releases_root, keep=keep, protect=protect,
        )
        deleted: list[Path] = []
        for d in to_delete:
            try:
                shutil.rmtree(d)
                deleted.append(d)
                log.info("release_deleted", path=str(d))
            except OSError as e:
                log.warning("release_delete_failed", path=str(d), error=str(e))
        return deleted
    ```

    Create tests/test_updater_root_backup.py covering all behavior cases.
    For the release retention test, manually create a fake releases root with numbered
    dirs and a symlink; do NOT depend on the real /opt/pv-inverter-proxy-releases.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_backup.py -x -v</automated>
  </verify>
  <done>
    - backup.py exists with all three public functions
    - All tests pass
    - No writes to /var/lib/pv-inverter-proxy during tests
    - apply_release_retention uses shutil.rmtree (grep-verified)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: updater_root/trigger_reader.py — schema + nonce dedup + SEC-06 tag regex</name>
  <files>src/pv_inverter_proxy/updater_root/trigger_reader.py, tests/test_updater_root_trigger_reader.py</files>
  <behavior>
    API:
    - `@dataclass ValidatedTrigger: op, target_sha, requested_at, requested_by, nonce, raw_body`
    - `class TriggerValidationError(Exception)` with subclass `NonceReplayError`
    - `def read_and_validate_trigger(path: Path, dedup_store: NonceDedupStore, target_sha_must_match_tag_regex: bool = False) -> ValidatedTrigger`:
        * Reads path.read_text()
        * json.loads; must be dict
        * Rejects extra keys NOT in the allowed set (strict mode — EXEC-02 is "exactly these 5 fields")
        * Re-validates op, target_sha shape (40-char hex or "previous")
        * Validates requested_at is a parseable ISO-8601 UTC string
        * Validates nonce is a non-empty string
        * Checks dedup_store.has_seen(nonce) — raises NonceReplayError if seen
        * On success: dedup_store.mark_seen(nonce) + return ValidatedTrigger

    - `class NonceDedupStore`:
        * `__init__(self, path: Path, max_entries: int = 50)`
        * `has_seen(self, nonce: str) -> bool`: loads the JSON, checks membership
        * `mark_seen(self, nonce: str) -> None`: loads, appends, trims to `max_entries` newest, atomic write
        * File schema: `{"nonces": [{"nonce": "...", "seen_at": <float>}, ...]}`
        * Missing file is empty-list
        * Corrupt JSON triggers a warning + treats as empty-list (safer to reprocess than to lock out)
        * Atomic write via tempfile + os.replace (same pattern as state_file.save_state)

    - `def validate_tag_regex(tag: str) -> bool`:
        * SEC-06: returns True iff tag matches `^v\d+\.\d+(\.\d+)?$`
        * NOTE: Plan 45-03 does not wire this into the trigger flow (the trigger carries a SHA, not a tag).
          It's exposed here so Plan 45-04's orchestrator can validate the tag after looking it up from
          the GitHub API response that led to the trigger.

    Test cases (hermetic):
    - test_read_valid_trigger: write a good JSON, read it -> ValidatedTrigger populated
    - test_read_missing_file: raises TriggerValidationError (not FileNotFoundError)
    - test_read_corrupt_json: raises TriggerValidationError
    - test_read_not_dict: json body is a list -> raises
    - test_read_extra_keys_rejected: JSON has {op, target_sha, requested_at, requested_by, nonce, EXTRA} -> raises
    - test_read_missing_key: missing "nonce" -> raises
    - test_read_bad_sha_shape: target_sha="xyz" -> raises
    - test_read_rollback_previous_allowed: op=rollback, target_sha="previous" -> ok
    - test_nonce_dedup_first_time_ok: fresh dedup_store + valid trigger -> ok; store now contains nonce
    - test_nonce_dedup_replay_raises: read same trigger twice -> second raises NonceReplayError
    - test_nonce_dedup_persists_to_disk: create store, mark_seen("abc"), instantiate a new store with same path, has_seen("abc") -> True
    - test_nonce_dedup_trims_to_max: mark_seen 60 distinct nonces, store file has exactly 50 most recent
    - test_nonce_dedup_corrupt_file: write garbage to dedup file, has_seen("x") -> False (permissive to avoid lockout)
    - test_validate_tag_regex_accepts: "v8.0", "v8.0.1", "v10.20.30" -> True
    - test_validate_tag_regex_rejects: "8.0", "v8.0.0-rc1", "v8", "main", "latest" -> False
    - test_read_stores_raw_body: ValidatedTrigger.raw_body == original parsed dict
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/trigger_reader.py`. Mirror the schema from
    updater/trigger.py INDEPENDENTLY — do not import from updater/. The schema mirror
    comment must explicitly name the boundary.

    Use module-level constants:
    ```python
    ALLOWED_KEYS = frozenset({"op", "target_sha", "requested_at", "requested_by", "nonce"})
    VALID_OPS = frozenset({"update", "rollback"})
    SHA_RE = re.compile(r"^[0-9a-f]{40}$")
    TAG_RE = re.compile(r"^v\d+\.\d+(\.\d+)?$")
    PROCESSED_NONCES_PATH = Path("/var/lib/pv-inverter-proxy/processed-nonces.json")
    DEFAULT_MAX_NONCES = 50
    ```

    Implement NonceDedupStore with atomic write. Important detail: the dedup store writes to
    /var/lib/pv-inverter-proxy/ which Phase 43 created as mode 2775 root:pv-proxy. The updater
    runs as root, so writes succeed.

    For `read_and_validate_trigger`, strict validation:
    ```python
    def read_and_validate_trigger(path: Path, dedup_store: NonceDedupStore) -> ValidatedTrigger:
        if not path.exists():
            raise TriggerValidationError(f"trigger file missing: {path}")
        try:
            raw = path.read_text()
            body = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            raise TriggerValidationError(f"trigger unreadable: {e}") from e
        if not isinstance(body, dict):
            raise TriggerValidationError("trigger not a JSON object")
        keys = set(body.keys())
        if keys != ALLOWED_KEYS:
            extra = keys - ALLOWED_KEYS
            missing = ALLOWED_KEYS - keys
            raise TriggerValidationError(
                f"trigger schema mismatch: extra={extra}, missing={missing}"
            )
        # ... validate each field, then check dedup ...
    ```

    Create tests/test_updater_root_trigger_reader.py with all cases. For the dedup persistence
    test, two independent NonceDedupStore instances against the same tmp_path file.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_trigger_reader.py -x -v</automated>
  </verify>
  <done>
    - trigger_reader.py exists with the full API
    - All tests pass including dedup persistence and trim-to-max
    - No import of pv_inverter_proxy.updater.trigger (grep-verified)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: updater_root/gpg_verify.py — optional SHA256SUMS.asc verification</name>
  <files>src/pv_inverter_proxy/updater_root/gpg_verify.py, tests/test_updater_root_gpg_verify.py</files>
  <behavior>
    API:
    - `@dataclass GpgConfig: allow_unsigned: bool, keyring_path: Path | None = None`
    - `@dataclass GpgResult: ok: bool, reason: str, verified_uid: str | None = None`
    - `async def verify_sha256sums_signature(sums_path: Path, sig_path: Path, config: GpgConfig) -> GpgResult`:
        * SEC-05: if config.allow_unsigned=True (v8.0 default), return GpgResult(ok=True, reason="unsigned_allowed") WITHOUT running gpg
        * Otherwise: run `gpg --status-fd 1 --verify <sig_path> <sums_path>`
        * Parse status output for `GOODSIG` / `VALIDSIG` / `EXPSIG` / `BADSIG`
        * Returns ok=True on GOODSIG + VALIDSIG
        * Returns ok=False with a descriptive reason otherwise
    - `def compute_sha256(path: Path) -> str`: hashlib.sha256 hex digest (needed for EXEC-10)
    - `def verify_sha256sums_file(sums_path: Path, files_dir: Path) -> list[tuple[str, bool, str]]`:
        * Parses SHA256SUMS format: each line is `<hex>  <filename>`
        * Computes sha256 of each `files_dir / filename`
        * Returns list of (filename, matches, expected_hash)
        * Used by Plan 45-04 to verify tarball integrity BEFORE GPG (EXEC-10)

    Test cases (hermetic):
    - test_allow_unsigned_skips_gpg: config.allow_unsigned=True, sig_path=nonexistent -> ok=True (no subprocess)
    - test_compute_sha256_known_value: write "hello\n" to tmp, verify hash == "5891b5b522d5..." (known)
    - test_verify_sha256sums_file_match: create 2 files with known hashes + sums file, verify all match=True
    - test_verify_sha256sums_file_mismatch: alter one file after sums written -> match=False for that entry
    - test_verify_sha256sums_file_missing_file: sums entry points at nonexistent file -> match=False, expected_hash populated
    - test_verify_sha256sums_file_malformed_line: blank line, comment "#...", missing hash -> skipped silently
    - test_gpg_verify_no_sig_file_but_required: allow_unsigned=False, sig_path missing -> ok=False, reason="signature_file_missing"
    - test_gpg_verify_subprocess_shape: allow_unsigned=False, monkeypatch asyncio.create_subprocess_exec to return a fake with stdout containing "GOODSIG"+"VALIDSIG" -> ok=True
    - test_gpg_verify_badsig: monkeypatched stdout with "BADSIG" -> ok=False
    - test_gpg_verify_expired: monkeypatched stdout with "EXPSIG" -> ok=False, reason mentions expired

    NOTE on Phase 45 scope: gpg_verify is fully implemented but the DEFAULT config is allow_unsigned=True.
    Plan 45-04's orchestrator will NOT enforce GPG by default. Phase 47+ may flip the default. For Phase 45,
    the verifier exists, is tested, and is wired into the plan BUT is a no-op in production.
  </behavior>
  <action>
    Create `src/pv_inverter_proxy/updater_root/gpg_verify.py`:

    ```python
    """Optional GPG SHA256SUMS.asc verification (SEC-05) + SHA256SUMS file check (EXEC-10).

    In v8.0 the default is ``allow_unsigned=True`` — the GPG verifier is a
    no-op and every release is accepted as long as its SHA256SUMS file
    matches the computed hashes. v8.1 will flip the default and require a
    maintainer key on the LXC.
    """
    from __future__ import annotations

    import asyncio
    import hashlib
    from dataclasses import dataclass
    from pathlib import Path

    import structlog

    log = structlog.get_logger(component="updater_root.gpg_verify")

    GPG_VERIFY_TIMEOUT_S = 15.0


    @dataclass
    class GpgConfig:
        allow_unsigned: bool = True
        keyring_path: Path | None = None


    @dataclass
    class GpgResult:
        ok: bool
        reason: str
        verified_uid: str | None = None


    def compute_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


    def verify_sha256sums_file(
        sums_path: Path,
        files_dir: Path,
    ) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []
        for line in sums_path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            expected_hash = parts[0].lower()
            filename = " ".join(parts[1:]).lstrip("*")  # "*" prefix = binary mode
            target = files_dir / filename
            if not target.exists():
                results.append((filename, False, expected_hash))
                continue
            actual = compute_sha256(target)
            results.append((filename, actual == expected_hash, expected_hash))
        return results


    async def verify_sha256sums_signature(
        sums_path: Path,
        sig_path: Path,
        config: GpgConfig,
    ) -> GpgResult:
        if config.allow_unsigned:
            log.info("gpg_verify_skipped", reason="allow_unsigned")
            return GpgResult(ok=True, reason="unsigned_allowed")
        if not sig_path.exists():
            return GpgResult(ok=False, reason="signature_file_missing")
        args = ["gpg", "--status-fd", "1", "--verify", str(sig_path), str(sums_path)]
        if config.keyring_path is not None:
            args = ["gpg", "--no-default-keyring", "--keyring", str(config.keyring_path),
                    "--status-fd", "1", "--verify", str(sig_path), str(sums_path)]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=GPG_VERIFY_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return GpgResult(ok=False, reason="gpg_timeout")

        status = stdout.decode("utf-8", errors="replace")
        if "BADSIG" in status:
            return GpgResult(ok=False, reason="bad_signature")
        if "EXPSIG" in status or "EXPKEYSIG" in status:
            return GpgResult(ok=False, reason="expired_signature")
        if "GOODSIG" in status and "VALIDSIG" in status:
            return GpgResult(ok=True, reason="valid_signature")
        return GpgResult(ok=False, reason=f"unexpected_status: {status[:200]}")
    ```

    Create tests/test_updater_root_gpg_verify.py with the cases above.
    Use monkeypatch.setattr(asyncio, "create_subprocess_exec", ...) for subprocess fakes.
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_root_gpg_verify.py -x -v</automated>
  </verify>
  <done>
    - gpg_verify.py exists
    - All tests pass
    - Default allow_unsigned=True path runs without subprocess (verified in test)
  </done>
</task>

<task type="auto">
  <name>Task 5: Trust boundary grep enforcement</name>
  <files>tests/test_updater_trust_boundary.py</files>
  <action>
    Create a trust boundary enforcement test that hard-fails if the main service ever
    imports from updater_root. This is the filesystem-enforced security boundary — a
    test ensures a future refactor cannot silently cross it.

    ```python
    """Trust boundary enforcement: main service must never import updater_root."""
    from __future__ import annotations

    import re
    from pathlib import Path

    SRC = Path(__file__).parent.parent / "src" / "pv_inverter_proxy"
    FORBIDDEN_IMPORT = re.compile(r"from pv_inverter_proxy\.updater_root|import pv_inverter_proxy\.updater_root")

    MAIN_SERVICE_MODULES = [
        "webapp.py",
        "__main__.py",
        "context.py",
        "proxy.py",
        "distributor.py",
        "control.py",
        "device_registry.py",
        "aggregation.py",
        "dashboard.py",
        "mqtt_publisher.py",
        "venus_reader.py",
    ]

    MAIN_SERVICE_PACKAGES = ["updater", "plugins"]


    def test_no_main_service_file_imports_updater_root():
        violations = []
        for name in MAIN_SERVICE_MODULES:
            path = SRC / name
            if not path.exists():
                continue
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if FORBIDDEN_IMPORT.search(line):
                    violations.append(f"{path}:{lineno}: {line.strip()}")
        assert not violations, (
            "TRUST BOUNDARY VIOLATION: main service must never import updater_root\n"
            + "\n".join(violations)
        )


    def test_no_main_service_package_imports_updater_root():
        violations = []
        for pkg in MAIN_SERVICE_PACKAGES:
            pkg_dir = SRC / pkg
            if not pkg_dir.is_dir():
                continue
            for py in pkg_dir.rglob("*.py"):
                text = py.read_text()
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if FORBIDDEN_IMPORT.search(line):
                        violations.append(f"{py}:{lineno}: {line.strip()}")
        assert not violations, (
            "TRUST BOUNDARY VIOLATION: main service packages must never import updater_root\n"
            + "\n".join(violations)
        )


    def test_updater_root_only_imports_allowlisted_main_modules():
        """updater_root may ONLY import releases, recovery, state_file from the main package."""
        updater_root = SRC / "updater_root"
        allowed = {"releases", "recovery", "state_file"}
        import_re = re.compile(r"from pv_inverter_proxy\.(\w+)")
        violations = []
        for py in updater_root.rglob("*.py"):
            text = py.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = import_re.search(line)
                if m and m.group(1) not in allowed and not m.group(1).startswith("updater_root"):
                    violations.append(f"{py}:{lineno}: {line.strip()}")
        assert not violations, (
            "TRUST BOUNDARY VIOLATION: updater_root imported a non-allowlisted main module\n"
            + "\n".join(violations)
        )
    ```
  </action>
  <verify>
    <automated>cd /Users/hulki/codex/pv-inverter-proxy && .venv/bin/python -m pytest tests/test_updater_trust_boundary.py -x -v</automated>
  </verify>
  <done>
    - Test file exists and passes
    - Grep confirms no updater_root imports in main service files: `grep -rn "updater_root" src/pv_inverter_proxy/ | grep -v "updater_root/"` returns nothing
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| pv-proxy code → updater_root code | FORBIDDEN — filesystem + import-test enforced |
| updater_root → subprocess (git, gpg) | Explicit argv only, never shell=True |
| updater_root → /var/lib/pv-inverter-proxy/ | Root-owned writes for dedup + backups |
| updater_root → trigger file | Read-only consumer; validates every field |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-45-03-01 | Elevation of privilege | Command injection via git args | mitigate | run_git uses create_subprocess_exec with explicit argv; no shell. Test test_run_git_no_shell proves a malicious arg is passed literally. |
| T-45-03-02 | Tampering | Trigger file schema injection | mitigate | trigger_reader uses strict key-set equality (ALLOWED_KEYS != body keys -> raise). Extra fields are rejected, not silently ignored. |
| T-45-03-03 | Elevation of privilege | Arbitrary SHA install | mitigate | is_sha_on_main uses `git merge-base --is-ancestor` — EXEC-04 security root of trust. Only SHAs reachable from origin/main are accepted. The git repo has origin remote pinned in install.sh. |
| T-45-03-04 | Replay | Nonce replay | mitigate | NonceDedupStore persists last 50 nonces to /var/lib; has_seen check before execute. Test test_nonce_dedup_replay_raises proves the mechanism. |
| T-45-03-05 | Denial of service | Dedup store corruption lockout | mitigate | Corrupt dedup file is treated as empty (test_nonce_dedup_corrupt_file). Failure mode is "reprocess", not "lockout forever". The opposite choice (fail closed) would be worse for a safety system. |
| T-45-03-06 | Tampering | Tarball substitution | mitigate | compute_sha256 + verify_sha256sums_file (EXEC-10) check every extracted tarball against the SHA256SUMS manifest. Plan 45-04 calls this before extraction. |
| T-45-03-07 | Tampering | SHA256SUMS itself substituted | partial | EXEC-10 only verifies files against SHA256SUMS, not SHA256SUMS itself. Full mitigation is SEC-05 GPG. v8.0 leaves this partially mitigated by design (allow_unsigned=true default). The underlying trust is TLS to api.github.com + the git origin remote URL. Documented risk: a MitM on github.com with a forged TLS cert could substitute both the tarball AND SHA256SUMS. Mitigation: pin to origin/main via is_sha_on_main, so the SHA must also be in the locally-stored origin/main history. Attacker would need to compromise the git fetch AND the releases API simultaneously. |
| T-45-03-08 | Spoofing | Tag regex bypass | mitigate | SEC-06: validate_tag_regex enforces `^v\d+\.\d+(\.\d+)?$`. Plan 45-04 calls it before accepting any tag-to-SHA mapping from the GitHub API. |
| T-45-03-09 | Information disclosure | Backup file world-readable | mitigate | BACKUP_FILE_MODE=0640 (root:root). A config.yaml copy may contain secrets (though current schema has no secrets). Mode 0640 limits exposure. |
| T-45-03-10 | Trust boundary violation | Main service imports updater_root | mitigate | Task 5 grep-enforced test. Any future refactor that crosses the boundary fails CI. |
| T-45-03-11 | Denial of service | git fetch timeout hangs updater | mitigate | GIT_FETCH_TIMEOUT_S=120s. On timeout, GitTimeoutError + process killed. Plan 45-04 orchestrator treats timeout as a terminal error and writes status=failed. |
</threat_model>

<verification>
## Validation Strategy

| REQ | Test Type | Evidence |
|-----|-----------|----------|
| EXEC-02 | Unit (trigger_reader tests) | Strict key-set validation |
| EXEC-04 | Unit (git_ops::test_is_sha_on_main_*) | merge-base --is-ancestor semantics |
| EXEC-05 | Unit (backup::test_create_backup_*) | Three files created, modes 0640 |
| EXEC-07 | Deferred to 45-04 | Plan 45-04 calls `pip install --dry-run` via subprocess helper |
| EXEC-10 | Unit (gpg_verify::test_verify_sha256sums_file_*) | Hash match/mismatch detection |
| SEC-05 | Unit (gpg_verify::test_allow_unsigned_skips_gpg) | No-op when config.allow_unsigned=True |
| SEC-06 | Unit (trigger_reader::test_validate_tag_regex_*) | Regex accepts v8.0, v8.0.1; rejects main/latest/v8.0.0-rc1 |
| Trust boundary | Unit (test_updater_trust_boundary.py) | Grep-enforced import isolation |

## Failure Rollback

Plan 45-03 is pure code + tests, no runtime deployment. On failure:
1. `git revert HEAD` — package deletion is clean
2. Plan 45-04 cannot proceed without 45-03
3. No LXC state to clean up (no install.sh changes, no services installed)
</verification>

<success_criteria>
- updater_root/ package exists with 4 modules + __init__
- 4 test files pass, plus trust_boundary test
- Zero imports of updater_root from main service (grep + test enforced)
- Zero network or privileged operations during test runs (all hermetic)
- Plan 45-04 can now compose these primitives into the runner state machine
</success_criteria>

<output>
After completion, create `.planning/phases/45-privileged-updater-service/45-03-SUMMARY.md` capturing:
- Final module file list + line counts
- Test counts per module
- Output of `grep -rn "updater_root" src/pv_inverter_proxy/ | grep -v "src/pv_inverter_proxy/updater_root/"` (should be empty)
- Output of `grep -rn "from pv_inverter_proxy\." src/pv_inverter_proxy/updater_root/` (should only list releases, recovery)
- Confirmation that SEC-05 default is allow_unsigned=True and GPG path is test-covered but runtime-inactive in Phase 45
</output>
