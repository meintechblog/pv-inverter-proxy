"""Tests for the UpdateRunner state machine.

All primitives are injected as fakes with recorded call sequences so the
test suite verifies ordering, branching, and exit codes without any
real subprocess, filesystem, or systemd activity. The only real
filesystem writes are through the real StatusFileWriter pointing at
tmp_path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pv_inverter_proxy.updater_root.healthcheck import HealthCheckOutcome
from pv_inverter_proxy.updater_root.runner import (
    EXIT_FAILURE,
    EXIT_ROLLBACK_DONE,
    EXIT_ROLLBACK_FAILED,
    EXIT_SUCCESS,
    UpdateRunner,
    UpdateRunnerConfig,
    UpdateRunnerPrimitives,
)
from pv_inverter_proxy.updater_root.status_writer import StatusFileWriter
from pv_inverter_proxy.updater_root.trigger_reader import (
    NonceReplayError,
    TriggerValidationError,
    ValidatedTrigger,
)


# ---------------------------------------------------------------------
# Fake primitives with call recording

@dataclass
class _Rec:
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

    def record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    @property
    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@dataclass
class _FakeOk:
    """Stand-in for a successful pip/git result with ``.ok``."""

    ok: bool = True
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class _FakeDisk:
    ok: bool = True
    message: str = ""
    opt_free_bytes: int = 10**10
    var_cache_free_bytes: int = 10**10


class _FakeHealthChecker:
    def __init__(self, outcome: HealthCheckOutcome) -> None:
        self._outcome = outcome

    async def wait_for_healthy(self) -> HealthCheckOutcome:
        return self._outcome


def _ok_outcome() -> HealthCheckOutcome:
    return HealthCheckOutcome(
        success=True,
        reason="stable_ok",
        last_response={"status": "ok"},
        probes=3,
        consecutive_ok=3,
    )


def _fail_outcome(reason: str = "timeout") -> HealthCheckOutcome:
    return HealthCheckOutcome(
        success=False,
        reason=reason,
        last_response=None,
        probes=5,
        consecutive_ok=0,
    )


def _make_config(tmp_path: Path) -> UpdateRunnerConfig:
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    current_release = releases_root / "current-abc1234"
    current_release.mkdir()
    current_link = releases_root / "current"
    current_link.symlink_to(current_release)
    backups = tmp_path / "backups"
    backups.mkdir()
    return UpdateRunnerConfig(
        releases_root=releases_root,
        install_root=tmp_path / "install",
        current_symlink=current_link,
        backups_root=backups,
        trigger_path=tmp_path / "trigger.json",
        status_path=tmp_path / "status.json",
        config_path=tmp_path / "config.yaml",
        dedup_path=tmp_path / "nonces.json",
        pending_marker_path=tmp_path / "pending.marker",
        main_service_unit="pv-inverter-proxy.service",
        keep_releases=3,
    )


def _make_primitives(
    rec: _Rec,
    *,
    trigger: ValidatedTrigger | Exception | None = None,
    sha_on_main: bool = True,
    disk_ok: bool = True,
    dryrun_ok: bool = True,
    install_ok: bool = True,
    compileall_ok: bool = True,
    smoke_ok: bool = True,
    config_dryrun_ok: bool = True,
    restart_ok: bool = True,
    health_outcome: HealthCheckOutcome | None = None,
    second_health_outcome: HealthCheckOutcome | None = None,
    symlink_flip_error: Exception | None = None,
    symlink_flip_error_on_rollback: Exception | None = None,
    fresh_status_writer: StatusFileWriter | None = None,
    config: UpdateRunnerConfig | None = None,
) -> UpdateRunnerPrimitives:
    if trigger is None:
        trigger = ValidatedTrigger(
            op="update",
            target_sha="a" * 40,
            requested_at="2026-04-10T12:00:00Z",
            requested_by="test",
            nonce="nonce-123",
            raw_body={},
        )

    async def fake_is_sha_on_main(repo: Path, sha: str) -> bool:
        rec.record("is_sha_on_main", repo, sha)
        return sha_on_main

    async def fake_git_rev_parse(repo: Path, ref: str) -> str:
        rec.record("git_rev_parse", repo, ref)
        return "c" * 40

    async def fake_git_clone(src: Path, dst: Path) -> Any:
        rec.record("git_clone_shared", src, dst)
        dst.mkdir(parents=True, exist_ok=True)
        return _FakeOk()

    async def fake_git_checkout(repo: Path, sha: str) -> Any:
        rec.record("git_checkout_detach", repo, sha)
        return _FakeOk()

    async def fake_git_fetch(repo: Path) -> Any:
        rec.record("git_fetch", repo)
        return _FakeOk()

    def fake_check_disk_space() -> Any:
        rec.record("check_disk_space")
        return _FakeDisk(ok=disk_ok, message="" if disk_ok else "low")

    def fake_create_backup(rel: Path, cfg: Path, backups: Path) -> Any:
        rec.record("create_backup", rel, cfg, backups)
        return object()

    def fake_apply_release_retention(**kwargs: Any) -> list[Path]:
        rec.record("apply_release_retention", **kwargs)
        return []

    def fake_apply_backup_retention(**kwargs: Any) -> list[Path]:
        rec.record("apply_backup_retention", **kwargs)
        return []

    async def fake_create_venv(venv: Path) -> Any:
        rec.record("create_venv", venv)
        return _FakeOk()

    async def fake_dryrun(py: Path, proj: Path) -> Any:
        rec.record("pip_install_dry_run", py, proj)
        return _FakeOk(ok=dryrun_ok, stderr="" if dryrun_ok else "boom")

    async def fake_install(py: Path, proj: Path) -> Any:
        rec.record("pip_install", py, proj)
        return _FakeOk(ok=install_ok, stderr="" if install_ok else "install_err")

    async def fake_compileall(py: Path, src: Path) -> Any:
        rec.record("compileall", py, src)
        return _FakeOk(ok=compileall_ok)

    async def fake_smoke(py: Path) -> Any:
        rec.record("smoke_import", py)
        return _FakeOk(ok=smoke_ok, stderr="" if smoke_ok else "ImportError")

    async def fake_cfg_dryrun(py: Path, cfg: Path) -> Any:
        rec.record("config_dryrun", py, cfg)
        return _FakeOk(ok=config_dryrun_ok)

    async def fake_restart(unit: str) -> bool:
        rec.record("systemctl_restart", unit)
        return restart_ok

    flip_calls = {"count": 0}

    def fake_flip(link: Path, target: Path) -> None:
        flip_calls["count"] += 1
        rec.record("atomic_symlink_flip", link, target)
        if flip_calls["count"] == 1 and symlink_flip_error is not None:
            raise symlink_flip_error
        if flip_calls["count"] == 2 and symlink_flip_error_on_rollback is not None:
            raise symlink_flip_error_on_rollback
        # Actually perform flip so _resolve_current_release would work
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)

    def fake_write_pending(
        path: Path,
        prev: Path,
        target: Path,
        created: float,
        reason: str = "update",
    ) -> None:
        rec.record("write_pending_marker", path, prev, target, created, reason)
        path.write_text("{}")

    def fake_clear_pending(path: Path) -> None:
        rec.record("clear_pending_marker", path)
        if path.exists():
            path.unlink()

    cfg = config
    status_writer = fresh_status_writer

    def fake_status_factory() -> StatusFileWriter:
        rec.record("status_writer_factory")
        return status_writer if status_writer is not None else StatusFileWriter(path=cfg.status_path if cfg else Path("/tmp/s.json"))

    def fake_read_trigger(path: Path, dedup: Any) -> ValidatedTrigger:
        rec.record("read_trigger", path)
        if isinstance(trigger, Exception):
            raise trigger
        return trigger

    def fake_make_dedup(path: Path) -> Any:
        rec.record("make_dedup_store", path)
        return object()

    hc_calls = {"count": 0}

    def fake_make_hc(**kwargs: Any) -> _FakeHealthChecker:
        hc_calls["count"] += 1
        rec.record("make_health_checker", **kwargs)
        if hc_calls["count"] == 1:
            return _FakeHealthChecker(health_outcome or _ok_outcome())
        return _FakeHealthChecker(second_health_outcome or _ok_outcome())

    return UpdateRunnerPrimitives(
        is_sha_on_main=fake_is_sha_on_main,
        git_rev_parse=fake_git_rev_parse,
        git_clone_shared=fake_git_clone,
        git_checkout_detach=fake_git_checkout,
        git_fetch=fake_git_fetch,
        check_disk_space=fake_check_disk_space,
        create_backup=fake_create_backup,
        apply_release_retention=fake_apply_release_retention,
        apply_backup_retention=fake_apply_backup_retention,
        create_venv=fake_create_venv,
        pip_install_dry_run=fake_dryrun,
        pip_install=fake_install,
        compileall=fake_compileall,
        smoke_import=fake_smoke,
        config_dryrun=fake_cfg_dryrun,
        systemctl_restart=fake_restart,
        atomic_symlink_flip=fake_flip,
        write_pending_marker=fake_write_pending,
        clear_pending_marker=fake_clear_pending,
        status_writer_factory=fake_status_factory,
        read_trigger=fake_read_trigger,
        make_dedup_store=fake_make_dedup,
        make_health_checker=fake_make_hc,
    )


def _make_runner(tmp_path: Path, **primitives_kwargs: Any) -> tuple[UpdateRunner, _Rec, UpdateRunnerConfig]:
    cfg = _make_config(tmp_path)
    rec = _Rec()
    writer = StatusFileWriter(path=cfg.status_path)
    prims = _make_primitives(
        rec, fresh_status_writer=writer, config=cfg, **primitives_kwargs
    )
    runner = UpdateRunner(cfg, prims)
    return runner, rec, cfg


# ---------------------------------------------------------------------
# Happy path

async def test_happy_path(tmp_path: Path) -> None:
    runner, rec, cfg = _make_runner(tmp_path)
    rc = await runner.run()
    assert rc == EXIT_SUCCESS

    # Verify all pre-flip steps ran in order
    assert "read_trigger" in rec.names
    assert "is_sha_on_main" in rec.names
    assert "check_disk_space" in rec.names
    assert "create_backup" in rec.names
    assert "git_clone_shared" in rec.names
    assert "git_checkout_detach" in rec.names
    assert "create_venv" in rec.names
    assert "pip_install_dry_run" in rec.names
    assert "pip_install" in rec.names
    assert "compileall" in rec.names
    assert "smoke_import" in rec.names
    assert "config_dryrun" in rec.names
    assert "write_pending_marker" in rec.names
    assert "atomic_symlink_flip" in rec.names
    assert "systemctl_restart" in rec.names
    assert "make_health_checker" in rec.names

    # Pending marker cleared on success
    assert rec.names.count("clear_pending_marker") == 1
    # Retention invoked on success
    assert "apply_release_retention" in rec.names
    assert "apply_backup_retention" in rec.names

    # Status file shows phase=done
    import json
    data = json.loads(cfg.status_path.read_text())
    assert data["current"]["phase"] == "done"


# ---------------------------------------------------------------------
# Sequence invariants

async def test_pending_marker_written_before_symlink_flip(
    tmp_path: Path,
) -> None:
    runner, rec, cfg = _make_runner(tmp_path)
    await runner.run()
    pending_idx = rec.names.index("write_pending_marker")
    flip_idx = rec.names.index("atomic_symlink_flip")
    assert pending_idx < flip_idx, (
        f"pending_marker_written ({pending_idx}) must come before "
        f"atomic_symlink_flip ({flip_idx}) in {rec.names}"
    )


async def test_smoke_import_before_symlink_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path)
    await runner.run()
    smoke_idx = rec.names.index("smoke_import")
    flip_idx = rec.names.index("atomic_symlink_flip")
    assert smoke_idx < flip_idx


async def test_config_dryrun_before_symlink_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path)
    await runner.run()
    cfg_idx = rec.names.index("config_dryrun")
    flip_idx = rec.names.index("atomic_symlink_flip")
    assert cfg_idx < flip_idx


# ---------------------------------------------------------------------
# Pre-flip failures

async def test_sha_not_on_main_aborts_early(tmp_path: Path) -> None:
    runner, rec, cfg = _make_runner(tmp_path, sha_on_main=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "create_backup" not in rec.names
    assert "atomic_symlink_flip" not in rec.names
    assert "write_pending_marker" not in rec.names


async def test_disk_space_preflight_aborts(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, disk_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "create_backup" not in rec.names
    assert "atomic_symlink_flip" not in rec.names


async def test_pip_dryrun_fail_no_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, dryrun_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "pip_install" not in rec.names  # real install not attempted
    assert "atomic_symlink_flip" not in rec.names
    assert "write_pending_marker" not in rec.names


async def test_pip_install_fail_no_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, install_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "atomic_symlink_flip" not in rec.names


async def test_compileall_fail_no_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, compileall_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "atomic_symlink_flip" not in rec.names


async def test_smoke_import_fail_no_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, smoke_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "atomic_symlink_flip" not in rec.names
    assert "write_pending_marker" not in rec.names


async def test_config_dryrun_fail_no_flip(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(tmp_path, config_dryrun_ok=False)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "atomic_symlink_flip" not in rec.names
    assert "write_pending_marker" not in rec.names


# ---------------------------------------------------------------------
# Trigger errors

async def test_nonce_replay_returns_failure(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(
        tmp_path, trigger=NonceReplayError("dup")
    )
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    assert "create_backup" not in rec.names


async def test_trigger_validation_error_returns_failure(tmp_path: Path) -> None:
    runner, rec, _ = _make_runner(
        tmp_path, trigger=TriggerValidationError("bad schema")
    )
    rc = await runner.run()
    assert rc == EXIT_FAILURE


# ---------------------------------------------------------------------
# Rollback paths (HEALTH-07, HEALTH-08)

async def test_healthcheck_fail_triggers_rollback(tmp_path: Path) -> None:
    runner, rec, cfg = _make_runner(
        tmp_path,
        health_outcome=_fail_outcome("no_healthy_flag"),
        second_health_outcome=_ok_outcome(),
    )
    rc = await runner.run()
    assert rc == EXIT_ROLLBACK_DONE
    # Two health checker instantiations
    assert rec.names.count("make_health_checker") == 2
    # Two symlink flips (forward + rollback)
    assert rec.names.count("atomic_symlink_flip") == 2
    # Two restarts
    assert rec.names.count("systemctl_restart") == 2
    # Status file shows rollback_done
    import json
    data = json.loads(cfg.status_path.read_text())
    assert data["current"]["phase"] == "rollback_done"


async def test_max_one_rollback(tmp_path: Path) -> None:
    """HEALTH-08: both health checks fail -> rollback_failed, not a 2nd rollback."""
    runner, rec, cfg = _make_runner(
        tmp_path,
        health_outcome=_fail_outcome("timeout"),
        second_health_outcome=_fail_outcome("timeout"),
    )
    rc = await runner.run()
    assert rc == EXIT_ROLLBACK_FAILED
    assert rec.names.count("make_health_checker") == 2
    # Forward flip + rollback flip = 2. NEVER a third.
    assert rec.names.count("atomic_symlink_flip") == 2
    import json
    data = json.loads(cfg.status_path.read_text())
    assert data["current"]["phase"] == "rollback_failed"


async def test_rollback_restart_failure_marks_rollback_failed(
    tmp_path: Path,
) -> None:
    """If systemctl_restart fails on the rollback leg, we abandon."""
    rec = _Rec()
    cfg = _make_config(tmp_path)
    writer = StatusFileWriter(path=cfg.status_path)
    # First restart succeeds, second fails — custom wiring
    restart_calls = {"count": 0}

    base = _make_primitives(
        rec,
        fresh_status_writer=writer,
        config=cfg,
        health_outcome=_fail_outcome("timeout"),
    )

    original_restart = base.systemctl_restart

    async def flaky_restart(unit: str) -> bool:
        restart_calls["count"] += 1
        rec.record("systemctl_restart", unit)
        return restart_calls["count"] == 1

    # Replace recorded systemctl_restart wrapper
    base = UpdateRunnerPrimitives(
        **{**base.__dict__, "systemctl_restart": flaky_restart}
    )
    runner = UpdateRunner(cfg, base)
    rc = await runner.run()
    assert rc == EXIT_ROLLBACK_FAILED
    import json
    data = json.loads(cfg.status_path.read_text())
    assert data["current"]["phase"] == "rollback_failed"


async def test_rollback_symlink_flip_failure(tmp_path: Path) -> None:
    runner, rec, cfg = _make_runner(
        tmp_path,
        health_outcome=_fail_outcome("timeout"),
        symlink_flip_error_on_rollback=OSError("broken symlink"),
    )
    rc = await runner.run()
    assert rc == EXIT_ROLLBACK_FAILED
    import json
    data = json.loads(cfg.status_path.read_text())
    assert data["current"]["phase"] == "rollback_failed"


async def test_initial_restart_failure_triggers_rollback(tmp_path: Path) -> None:
    runner, rec, cfg = _make_runner(
        tmp_path,
        restart_ok=False,
        second_health_outcome=_ok_outcome(),
    )
    rc = await runner.run()
    # Forward restart failed -> rollback attempted
    # Note: restart_ok=False makes ALL restarts fail, so rollback restart
    # also fails -> rollback_failed
    assert rc == EXIT_ROLLBACK_FAILED


# ---------------------------------------------------------------------
# Status file content assertions

async def test_status_history_contains_full_happy_sequence(
    tmp_path: Path,
) -> None:
    runner, _, cfg = _make_runner(tmp_path)
    await runner.run()
    import json
    data = json.loads(cfg.status_path.read_text())
    phases = [h["phase"] for h in data["history"]]
    # Ensure canonical order (subsequence check — runner may add entries)
    expected_order = [
        "trigger_received",
        "backup",
        "extract",
        "pip_install_dryrun",
        "pip_install",
        "compileall",
        "smoke_import",
        "config_dryrun",
        "pending_marker_written",
        "symlink_flipped",
        "restarting",
        "healthcheck",
        "done",
    ]
    # Every expected phase must appear in order
    idx = 0
    for want in expected_order:
        found_at = phases.index(want, idx)
        idx = found_at + 1


async def test_status_rollback_history(tmp_path: Path) -> None:
    runner, _, cfg = _make_runner(
        tmp_path,
        health_outcome=_fail_outcome("no_healthy_flag"),
        second_health_outcome=_ok_outcome(),
    )
    await runner.run()
    import json
    data = json.loads(cfg.status_path.read_text())
    phases = [h["phase"] for h in data["history"]]
    for want in [
        "rollback_starting",
        "rollback_symlink_flipped",
        "rollback_restarting",
        "rollback_healthcheck",
        "rollback_done",
    ]:
        assert want in phases, f"{want} missing from {phases}"


# ---------------------------------------------------------------------
# Missing current release

async def test_missing_current_symlink_aborts(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    # Remove the symlink to simulate first-run corruption
    cfg.current_symlink.unlink()
    rec = _Rec()
    writer = StatusFileWriter(path=cfg.status_path)
    prims = _make_primitives(rec, fresh_status_writer=writer, config=cfg)
    runner = UpdateRunner(cfg, prims)
    rc = await runner.run()
    assert rc == EXIT_FAILURE
    # No backup attempted
    assert "create_backup" not in rec.names
