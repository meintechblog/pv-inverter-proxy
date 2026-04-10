"""Hermetic unit tests for updater_root.git_ops.

Uses tmp_path to create ephemeral git repos. No network access. No real
origin remote. All merge-base / rev-parse assertions are against locally
constructed commit chains.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pv_inverter_proxy.updater_root.git_ops import (
    GitResult,
    GitTimeoutError,
    git_checkout_detach,
    git_clone_shared,
    git_fetch,
    git_rev_parse,
    git_status_porcelain,
    is_sha_on_main,
    run_git,
)


async def _init_repo(path: Path, commits: int = 1) -> list[str]:
    """Init a git repo at ``path`` with ``commits`` commits on branch main.

    Returns list of SHAs oldest-first.
    """
    path.mkdir(parents=True, exist_ok=True)
    r = await run_git("init", "--quiet", "-b", "main", cwd=path)
    assert r.ok, f"git init failed: {r.stderr}"
    await run_git("config", "user.email", "t@t.test", cwd=path)
    await run_git("config", "user.name", "tester", cwd=path)
    await run_git("config", "commit.gpgsign", "false", cwd=path)
    shas: list[str] = []
    for i in range(commits):
        (path / f"f{i}").write_text(str(i))
        await run_git("add", f"f{i}", cwd=path)
        await run_git("commit", "--quiet", "-m", f"c{i}", cwd=path)
        sha = await git_rev_parse(path, "HEAD")
        assert sha is not None
        shas.append(sha)
    return shas


# ---------- run_git basics ----------


async def test_run_git_basic(tmp_path: Path):
    r = await run_git("--version", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout.startswith("git version ")


async def test_run_git_nonzero_exit(tmp_path: Path):
    r = await run_git("nonexistent-subcommand", cwd=tmp_path)
    assert r.returncode != 0
    # must NOT raise


async def test_run_git_timeout(monkeypatch, tmp_path: Path):
    """Simulate a hanging git by monkeypatching asyncio.wait_for."""

    async def fake_wait_for(coro, timeout):
        # close the coroutine to avoid "coroutine was never awaited" warning
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(GitTimeoutError):
        await run_git("--version", cwd=tmp_path, timeout_s=0.01)


async def test_run_git_no_shell(tmp_path: Path):
    """Malicious arg is passed literally, not interpreted by a shell.

    If a shell were involved, ``;touch /tmp/pwned_<marker>`` would create
    the sentinel file. We assert the marker file does NOT exist and git
    exited non-zero (git complains that it isn't a known subcommand).
    """
    marker = tmp_path / "pwned_marker"
    malicious = f";touch {marker}"
    r = await run_git(malicious, cwd=tmp_path)
    assert r.returncode != 0
    assert not marker.exists(), (
        "Shell interpretation detected: marker file was created"
    )


# ---------- git_fetch ----------


async def test_git_fetch_local(tmp_path: Path):
    """Local bare repo + clone + fetch round-trip."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    r = await run_git("init", "--bare", "--quiet", "-b", "main", cwd=bare)
    assert r.ok

    # Create an upstream working repo and push into the bare
    upstream = tmp_path / "upstream"
    await _init_repo(upstream, commits=2)
    await run_git("remote", "add", "origin", str(bare), cwd=upstream)
    r = await run_git("push", "--quiet", "origin", "main", cwd=upstream)
    assert r.ok, r.stderr

    # Clone the bare to a working dir
    work = tmp_path / "work"
    r = await run_git("clone", "--quiet", str(bare), str(work), cwd=tmp_path)
    assert r.ok

    # Add a new commit in upstream, push it, then fetch in work
    (upstream / "new").write_text("x")
    await run_git("add", "new", cwd=upstream)
    await run_git("commit", "--quiet", "-m", "c2", cwd=upstream)
    await run_git("push", "--quiet", "origin", "main", cwd=upstream)

    r = await git_fetch(work, "origin")
    assert r.ok, r.stderr


# ---------- git_rev_parse ----------


async def test_git_rev_parse_head(tmp_path: Path):
    await _init_repo(tmp_path, commits=1)
    sha = await git_rev_parse(tmp_path, "HEAD")
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


async def test_git_rev_parse_bad_ref(tmp_path: Path):
    await _init_repo(tmp_path, commits=1)
    sha = await git_rev_parse(tmp_path, "refs/heads/does-not-exist")
    assert sha is None


# ---------- is_sha_on_main ----------


async def test_is_sha_on_main_true(tmp_path: Path):
    """Middle commit of a 3-commit linear history is ancestor of HEAD."""
    shas = await _init_repo(tmp_path, commits=3)
    middle = shas[1]
    # "refs/heads/main" stands in for the origin/main ref in a local-only repo
    assert await is_sha_on_main(tmp_path, middle, main_ref="refs/heads/main")


async def test_is_sha_on_main_false_fabricated(tmp_path: Path):
    await _init_repo(tmp_path, commits=1)
    fake = "0" * 40
    assert not await is_sha_on_main(tmp_path, fake, main_ref="refs/heads/main")


async def test_is_sha_on_main_unrelated_chain(tmp_path: Path):
    """A commit on a disjoint branch is NOT an ancestor of main."""
    shas_main = await _init_repo(tmp_path, commits=2)
    # Create an orphan branch with its own commit
    r = await run_git("checkout", "--orphan", "other", cwd=tmp_path)
    assert r.ok
    # Remove index so orphan starts clean
    await run_git("rm", "-rf", "--quiet", ".", cwd=tmp_path)
    (tmp_path / "orphan.txt").write_text("o")
    await run_git("add", "orphan.txt", cwd=tmp_path)
    await run_git("commit", "--quiet", "-m", "orphan", cwd=tmp_path)
    orphan_sha = await git_rev_parse(tmp_path, "HEAD")
    assert orphan_sha is not None

    # main still contains shas_main[-1]; orphan_sha is NOT an ancestor of main
    assert not await is_sha_on_main(
        tmp_path, orphan_sha, main_ref="refs/heads/main"
    )
    # Sanity: shas_main[-1] IS ancestor of main
    assert await is_sha_on_main(
        tmp_path, shas_main[-1], main_ref="refs/heads/main"
    )


# ---------- git_clone_shared ----------


async def test_git_clone_shared(tmp_path: Path):
    source = tmp_path / "source"
    await _init_repo(source, commits=1)
    dest = tmp_path / "dest"
    r = await git_clone_shared(source, dest)
    assert r.ok, r.stderr
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    assert alternates.exists(), "--shared should create objects/info/alternates"


# ---------- git_checkout_detach ----------


async def test_git_checkout_detach(tmp_path: Path):
    shas = await _init_repo(tmp_path, commits=3)
    first = shas[0]
    r = await git_checkout_detach(tmp_path, first)
    assert r.ok, r.stderr
    head = await git_rev_parse(tmp_path, "HEAD")
    assert head == first


# ---------- git_status_porcelain ----------


async def test_git_status_porcelain_clean(tmp_path: Path):
    await _init_repo(tmp_path, commits=1)
    out = await git_status_porcelain(tmp_path)
    assert out == ""


async def test_git_status_porcelain_dirty(tmp_path: Path):
    await _init_repo(tmp_path, commits=1)
    (tmp_path / "new-untracked").write_text("x")
    out = await git_status_porcelain(tmp_path)
    assert "new-untracked" in out


# ---------- shape sanity ----------


def test_git_result_ok_property():
    assert GitResult(returncode=0, stdout="", stderr="").ok
    assert not GitResult(returncode=1, stdout="", stderr="").ok
