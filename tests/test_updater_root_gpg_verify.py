"""Hermetic unit tests for updater_root.gpg_verify.

GPG subprocess calls are monkey-patched — these tests never invoke real gpg.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from pv_inverter_proxy.updater_root import gpg_verify as gv
from pv_inverter_proxy.updater_root.gpg_verify import (
    GpgConfig,
    GpgResult,
    compute_sha256,
    verify_sha256sums_file,
    verify_sha256sums_signature,
)


# ---------- compute_sha256 ----------


def test_compute_sha256_known_value(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello\n")
    # sha256("hello\n") precomputed
    expected = hashlib.sha256(b"hello\n").hexdigest()
    assert compute_sha256(f) == expected


def test_compute_sha256_empty_file(tmp_path: Path):
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert compute_sha256(f) == (
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )


def test_compute_sha256_large_streaming(tmp_path: Path):
    """Verify the 64 KiB streaming buffer produces the same hash."""
    f = tmp_path / "large"
    payload = b"A" * (200 * 1024)  # > 3 chunks
    f.write_bytes(payload)
    assert compute_sha256(f) == hashlib.sha256(payload).hexdigest()


# ---------- verify_sha256sums_file ----------


def _write_sums(sums_path: Path, entries: list[tuple[str, str]]) -> None:
    """Each entry is ``(hex_hash, filename)`` in standard sha256sum format."""
    lines = [f"{h}  {name}" for h, name in entries]
    sums_path.write_text("\n".join(lines) + "\n")


def test_verify_sha256sums_file_all_match(tmp_path: Path):
    (tmp_path / "a.bin").write_bytes(b"A")
    (tmp_path / "b.bin").write_bytes(b"B")
    sums = tmp_path / "SHA256SUMS"
    _write_sums(
        sums,
        [
            (hashlib.sha256(b"A").hexdigest(), "a.bin"),
            (hashlib.sha256(b"B").hexdigest(), "b.bin"),
        ],
    )
    results = verify_sha256sums_file(sums, tmp_path)
    assert len(results) == 2
    assert all(match for _, match, _ in results)


def test_verify_sha256sums_file_mismatch(tmp_path: Path):
    (tmp_path / "a.bin").write_bytes(b"A")
    (tmp_path / "b.bin").write_bytes(b"B")
    sums = tmp_path / "SHA256SUMS"
    _write_sums(
        sums,
        [
            (hashlib.sha256(b"A").hexdigest(), "a.bin"),
            (hashlib.sha256(b"B").hexdigest(), "b.bin"),
        ],
    )
    # Mutate b.bin after the sums were written
    (tmp_path / "b.bin").write_bytes(b"CHANGED")
    results = verify_sha256sums_file(sums, tmp_path)
    by_name = {n: (m, h) for n, m, h in results}
    assert by_name["a.bin"][0] is True
    assert by_name["b.bin"][0] is False


def test_verify_sha256sums_file_missing_file(tmp_path: Path):
    sums = tmp_path / "SHA256SUMS"
    _write_sums(sums, [("0" * 64, "ghost.bin")])
    results = verify_sha256sums_file(sums, tmp_path)
    assert results == [("ghost.bin", False, "0" * 64)]


def test_verify_sha256sums_file_ignores_blank_and_comments(tmp_path: Path):
    (tmp_path / "a.bin").write_bytes(b"A")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        f"""# header comment
# another

{hashlib.sha256(b"A").hexdigest()}  a.bin

# trailing
"""
    )
    results = verify_sha256sums_file(sums, tmp_path)
    assert len(results) == 1
    assert results[0] == ("a.bin", True, hashlib.sha256(b"A").hexdigest())


def test_verify_sha256sums_file_malformed_line_skipped(tmp_path: Path):
    (tmp_path / "a.bin").write_bytes(b"A")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        f"""{hashlib.sha256(b"A").hexdigest()}  a.bin
just-one-token
"""
    )
    results = verify_sha256sums_file(sums, tmp_path)
    assert len(results) == 1


def test_verify_sha256sums_file_binary_mode_prefix(tmp_path: Path):
    """The '*' binary mode marker is stripped from filenames."""
    (tmp_path / "a.bin").write_bytes(b"A")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(b'A').hexdigest()} *a.bin\n")
    results = verify_sha256sums_file(sums, tmp_path)
    assert results == [("a.bin", True, hashlib.sha256(b"A").hexdigest())]


# ---------- verify_sha256sums_signature ----------


async def test_allow_unsigned_skips_gpg(tmp_path: Path, monkeypatch):
    """allow_unsigned=True must not invoke gpg at all."""
    invoked = False

    async def no_subprocess(*a, **kw):  # pragma: no cover - should not run
        nonlocal invoked
        invoked = True
        raise AssertionError("subprocess should not be invoked")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)
    result = await verify_sha256sums_signature(
        tmp_path / "SHA256SUMS",  # doesn't need to exist
        tmp_path / "SHA256SUMS.asc",  # doesn't need to exist
        GpgConfig(allow_unsigned=True),
    )
    assert result.ok is True
    assert result.reason == "unsigned_allowed"
    assert invoked is False


async def test_signature_required_but_missing(tmp_path: Path):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("deadbeef  ignored\n")
    sig = tmp_path / "SHA256SUMS.asc"
    # sig intentionally missing
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason == "signature_file_missing"


class _FakeProc:
    """Async-context-friendly stand-in for an asyncio subprocess."""

    def __init__(self, stdout_text: str, stderr_text: str = ""):
        self._stdout = stdout_text.encode()
        self._stderr = stderr_text.encode()

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:  # pragma: no cover - not needed here
        pass

    async def wait(self) -> int:  # pragma: no cover - not needed here
        return 0


def _patch_subprocess(monkeypatch, stdout_text: str) -> list[list[str]]:
    """Patch asyncio.create_subprocess_exec to return a fake proc.

    Captures the argv of every call into the returned list.
    """
    calls: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        calls.append(list(args))
        return _FakeProc(stdout_text)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


async def test_gpg_verify_goodsig_validsig(tmp_path: Path, monkeypatch):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    calls = _patch_subprocess(
        monkeypatch,
        "[GNUPG:] GOODSIG ABC123 Test Key\n[GNUPG:] VALIDSIG ABC123\n",
    )
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is True
    assert result.reason == "valid_signature"
    # gpg argv shape
    assert calls[0][0] == "gpg"
    assert "--verify" in calls[0]
    assert str(sig) in calls[0]


async def test_gpg_verify_badsig(tmp_path: Path, monkeypatch):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    _patch_subprocess(monkeypatch, "[GNUPG:] BADSIG ABC123\n")
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason == "bad_signature"


async def test_gpg_verify_expired(tmp_path: Path, monkeypatch):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    _patch_subprocess(monkeypatch, "[GNUPG:] EXPSIG ABC123\n")
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason == "expired_signature"


async def test_gpg_verify_expkeysig(tmp_path: Path, monkeypatch):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    _patch_subprocess(monkeypatch, "[GNUPG:] EXPKEYSIG ABC123\n")
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason == "expired_signature"


async def test_gpg_verify_unexpected_status(tmp_path: Path, monkeypatch):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    _patch_subprocess(monkeypatch, "[GNUPG:] NODATA 1\n")
    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason.startswith("unexpected_status:")


async def test_gpg_verify_keyring_injection(tmp_path: Path, monkeypatch):
    """keyring_path causes --no-default-keyring --keyring to be prepended."""
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")
    keyring = tmp_path / "maintainer.gpg"
    keyring.write_bytes(b"fake-keyring")
    calls = _patch_subprocess(
        monkeypatch,
        "[GNUPG:] GOODSIG X\n[GNUPG:] VALIDSIG X\n",
    )
    result = await verify_sha256sums_signature(
        sums,
        sig,
        GpgConfig(allow_unsigned=False, keyring_path=keyring),
    )
    assert result.ok is True
    argv = calls[0]
    assert "--no-default-keyring" in argv
    assert "--keyring" in argv
    assert str(keyring) in argv


async def test_gpg_verify_timeout(tmp_path: Path, monkeypatch):
    """Timeout -> ok=False, reason='gpg_timeout', subprocess killed."""
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x")
    sig = tmp_path / "SHA256SUMS.asc"
    sig.write_text("x")

    killed = {"count": 0}

    class _HangingProc:
        async def communicate(self):
            # We won't actually reach here because wait_for is patched.
            await asyncio.sleep(3600)
            return b"", b""

        def kill(self):
            killed["count"] += 1

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        return _HangingProc()

    async def fake_wait_for(coro, timeout):
        # Close coroutine to silence warnings
        if hasattr(coro, "close"):
            coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await verify_sha256sums_signature(
        sums, sig, GpgConfig(allow_unsigned=False)
    )
    assert result.ok is False
    assert result.reason == "gpg_timeout"
    assert killed["count"] == 1


def test_gpg_result_shape():
    r = GpgResult(ok=True, reason="ok")
    assert r.verified_uid is None


def test_gpg_config_default_allow_unsigned():
    assert GpgConfig().allow_unsigned is True
