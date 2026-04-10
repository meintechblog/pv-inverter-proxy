"""Hermetic tests for updater_root.pip_ops.

All tests monkeypatch ``asyncio.create_subprocess_exec`` — no real pip,
no real venv, no network. The tests verify:

- Explicit argv (no shell interpolation)
- Timeout wrapping via ``PipTimeoutError``
- Return codes surfaced in ``PipResult``
- Exact arguments for EXEC-07 (dry-run), EXEC-08 (smoke + config dryrun),
  EXEC-09 (compileall)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pv_inverter_proxy.updater_root import pip_ops
from pv_inverter_proxy.updater_root.pip_ops import (
    PipResult,
    PipTimeoutError,
    compileall,
    config_dryrun,
    create_venv,
    pip_install,
    pip_install_dry_run,
    smoke_import,
)


class _FakeProc:
    """Mimics the subset of asyncio.subprocess.Process used by pip_ops."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)  # will be cancelled by wait_for
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _install_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    hang: bool = False,
) -> list[tuple[Any, ...]]:
    """Patch create_subprocess_exec, capture all invocations."""
    calls: list[tuple[Any, ...]] = []

    async def fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:  # noqa: ANN401
        calls.append(args)
        return _FakeProc(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            hang=hang,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


# ---------------------------------------------------------------------
# pip_install_dry_run (EXEC-07)

@pytest.mark.asyncio
async def test_pip_install_dry_run_passes_correct_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0, stdout=b"ok")
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    project_dir = tmp_path / "release"
    result = await pip_install_dry_run(venv_python, project_dir)
    assert result.ok
    assert result.returncode == 0
    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == str(venv_python)
    assert "-m" in argv
    assert "pip" in argv
    assert "install" in argv
    assert "--dry-run" in argv
    assert "-e" in argv
    assert str(project_dir) in argv


@pytest.mark.asyncio
async def test_pip_install_dry_run_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, returncode=1, stderr=b"ResolutionImpossible")
    result = await pip_install_dry_run(
        tmp_path / ".venv" / "bin" / "python3", tmp_path / "release"
    )
    assert not result.ok
    assert result.returncode == 1
    assert "ResolutionImpossible" in result.stderr


@pytest.mark.asyncio
async def test_pip_install_dry_run_wraps_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, hang=True)
    # Force a tiny timeout so the test finishes fast
    monkeypatch.setattr(pip_ops, "PIP_DRY_RUN_TIMEOUT_S", 0.05)
    with pytest.raises(PipTimeoutError):
        await pip_install_dry_run(
            tmp_path / ".venv" / "bin" / "python3", tmp_path / "release"
        )


# ---------------------------------------------------------------------
# pip_install (real install)

@pytest.mark.asyncio
async def test_pip_install_passes_correct_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0)
    await pip_install(tmp_path / ".venv" / "bin" / "python3", tmp_path / "release")
    argv = calls[0]
    assert "--dry-run" not in argv  # Must NOT be dry-run here
    assert "install" in argv
    assert "-e" in argv
    assert str(tmp_path / "release") in argv


# ---------------------------------------------------------------------
# create_venv

@pytest.mark.asyncio
async def test_create_venv_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0)
    venv_dir = tmp_path / ".venv"
    result = await create_venv(venv_dir)
    assert result.ok
    argv = calls[0]
    assert argv[0] == "python3"
    assert "-m" in argv
    assert "venv" in argv
    assert str(venv_dir) in argv


# ---------------------------------------------------------------------
# compileall (EXEC-09)

@pytest.mark.asyncio
async def test_compileall_invokes_compileall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0)
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    src_dir = tmp_path / "release" / "src"
    await compileall(venv_python, src_dir)
    argv = calls[0]
    assert argv[0] == str(venv_python)
    assert "-m" in argv
    assert "compileall" in argv
    assert "-q" in argv
    assert str(src_dir) in argv


# ---------------------------------------------------------------------
# smoke_import (EXEC-08 part 1)

@pytest.mark.asyncio
async def test_smoke_import_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0, stdout=b"ok\n")
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    result = await smoke_import(venv_python)
    assert result.ok
    argv = calls[0]
    assert argv[0] == str(venv_python)
    assert "-c" in argv
    # Last element is the python script
    script = argv[-1]
    assert "import pv_inverter_proxy" in script


@pytest.mark.asyncio
async def test_smoke_import_failure_surfaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, returncode=1, stderr=b"ImportError: ...")
    result = await smoke_import(tmp_path / ".venv" / "bin" / "python3")
    assert not result.ok
    assert "ImportError" in result.stderr


# ---------------------------------------------------------------------
# config_dryrun (EXEC-08 part 2)

@pytest.mark.asyncio
async def test_config_dryrun_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, returncode=0)
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    config_path = tmp_path / "etc" / "config.yaml"
    await config_dryrun(venv_python, config_path)
    argv = calls[0]
    assert argv[0] == str(venv_python)
    assert "-c" in argv
    script = argv[-1]
    assert "load_config" in script
    assert str(config_path) in script


@pytest.mark.asyncio
async def test_config_dryrun_path_with_spaces_not_interpolated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Config path with spaces must be passed as-is inside the script string,
    not split or shell-interpreted."""
    calls = _install_fake(monkeypatch, returncode=0)
    weird_cfg = tmp_path / "has spaces" / "config.yaml"
    await config_dryrun(tmp_path / ".venv" / "bin" / "python3", weird_cfg)
    argv = calls[0]
    # argv is a tuple — the script is one single positional arg.
    script = argv[-1]
    assert str(weird_cfg) in script
    # Verify the script is passed as a single argv element (not split)
    assert sum(1 for a in argv if "load_config" in str(a)) == 1


@pytest.mark.asyncio
async def test_config_dryrun_failure_surfaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, returncode=1, stderr=b"KeyError: 'required'")
    result = await config_dryrun(
        tmp_path / ".venv" / "bin" / "python3",
        tmp_path / "config.yaml",
    )
    assert not result.ok


# ---------------------------------------------------------------------
# Security: no shell=True anywhere

@pytest.mark.asyncio
async def test_all_use_exec_not_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Snapshot test: every helper uses create_subprocess_exec, never
    create_subprocess_shell. Enforced by the fake: if any helper reaches
    for subprocess_shell, the call won't be captured and the test will
    fail with AttributeError on the missing attribute."""
    # Block shell variant entirely
    async def blocked_shell(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        raise AssertionError("shell subprocess forbidden")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", blocked_shell)
    _install_fake(monkeypatch, returncode=0)

    venv_python = tmp_path / ".venv" / "bin" / "python3"
    release = tmp_path / "release"
    cfg = tmp_path / "config.yaml"

    await create_venv(tmp_path / ".venv")
    await pip_install_dry_run(venv_python, release)
    await pip_install(venv_python, release)
    await compileall(venv_python, release / "src")
    await smoke_import(venv_python)
    await config_dryrun(venv_python, cfg)


@pytest.mark.asyncio
async def test_pip_result_ok_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, returncode=0)
    r = await pip_install_dry_run(tmp_path / "p", tmp_path / "r")
    assert isinstance(r, PipResult)
    assert r.ok is True
    _install_fake(monkeypatch, returncode=2)
    r2 = await pip_install_dry_run(tmp_path / "p", tmp_path / "r")
    assert r2.ok is False
