"""Unit tests for pv_inverter_proxy.updater.version (CHECK-01, Phase 44).

Covers:
- Version.parse success cases (with/without leading v, 2- and 3-field)
- Version.parse failure cases (malformed strings)
- Version ordering via tuple comparison
- Version.__str__ canonical form
- get_current_version() happy path + PackageNotFoundError fallback
- get_commit_hash() success, missing .git, subprocess failure
- Neither get_current_version nor get_commit_hash ever raise
"""
from __future__ import annotations

import subprocess
from importlib import metadata
from pathlib import Path

import pytest

from pv_inverter_proxy.updater import version as version_mod
from pv_inverter_proxy.updater.version import (
    Version,
    get_commit_hash,
    get_current_version,
)


# ---------------------------------------------------------------------------
# Version.parse — success cases
# ---------------------------------------------------------------------------


def test_parse_two_field_with_v_prefix():
    assert Version.parse("v8.0") == Version(8, 0, 0)


def test_parse_three_field_with_v_prefix():
    assert Version.parse("v8.0.1") == Version(8, 0, 1)


def test_parse_three_field_without_v_prefix():
    assert Version.parse("8.0.1") == Version(8, 0, 1)


def test_parse_two_field_without_v_prefix():
    assert Version.parse("8.0") == Version(8, 0, 0)


def test_parse_strips_whitespace():
    assert Version.parse("  v8.0.1  ") == Version(8, 0, 1)
    assert Version.parse("\tv7.1\n") == Version(7, 1, 0)


def test_parse_large_numbers():
    assert Version.parse("v999.888.777") == Version(999, 888, 777)


def test_parse_zero_patch():
    assert Version.parse("v8.0.0") == Version(8, 0, 0)


# ---------------------------------------------------------------------------
# Version.parse — failure cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "8",
        "v8",
        "v8.0.1.2",
        "latest",
        "",
        "v",
        "v.8.0",
        "v8..0",
        "v8.0.",
        "abc",
        "v8.0.1-beta",
        "8.0.1+meta",
        "  ",
        "v8,0,1",
    ],
)
def test_parse_rejects_malformed(bad: str):
    with pytest.raises(ValueError):
        Version.parse(bad)


# ---------------------------------------------------------------------------
# Version ordering (free tuple comparison)
# ---------------------------------------------------------------------------


def test_ordering_patch():
    assert Version(8, 0, 1) > Version(8, 0, 0)


def test_ordering_minor_beats_patch():
    assert Version(8, 1, 0) > Version(8, 0, 99)


def test_ordering_major_beats_minor():
    assert Version(9, 0, 0) > Version(8, 99, 99)


def test_ordering_equality():
    assert Version(8, 0, 1) == Version(8, 0, 1)


def test_ordering_less_than():
    assert Version(8, 0, 0) < Version(8, 0, 1)
    assert Version(8, 0, 0) <= Version(8, 0, 0)


# ---------------------------------------------------------------------------
# Version.__str__
# ---------------------------------------------------------------------------


def test_str_canonical_form():
    assert str(Version(8, 0, 1)) == "v8.0.1"
    assert str(Version(8, 0, 0)) == "v8.0.0"
    assert str(Version(10, 2, 3)) == "v10.2.3"


def test_str_roundtrip_with_parse():
    for raw in ("v8.0.1", "v1.2.3", "v0.0.0"):
        assert str(Version.parse(raw)) == raw


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------


def test_get_current_version_returns_non_empty_string():
    result = get_current_version()
    assert isinstance(result, str)
    assert result  # non-empty


def test_get_current_version_package_not_found(monkeypatch: pytest.MonkeyPatch):
    def _raise(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version_mod.metadata, "version", _raise)
    assert get_current_version() == "unknown"


def test_get_current_version_generic_error(monkeypatch: pytest.MonkeyPatch):
    def _raise(name: str) -> str:
        raise RuntimeError("metadata backend broken")

    monkeypatch.setattr(version_mod.metadata, "version", _raise)
    # Must not raise, must return fallback
    assert get_current_version() == "unknown"


def test_get_current_version_happy_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(version_mod.metadata, "version", lambda name: "8.0.1")
    assert get_current_version() == "8.0.1"


# ---------------------------------------------------------------------------
# get_commit_hash
# ---------------------------------------------------------------------------


def test_get_commit_hash_no_git_dir_returns_none(tmp_path: Path):
    # tmp_path has no .git, so git rev-parse should fail
    result = get_commit_hash(tmp_path)
    assert result is None


def test_get_commit_hash_subprocess_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("git binary not installed")

    monkeypatch.setattr(version_mod.subprocess, "run", _raise)
    assert get_commit_hash(tmp_path) is None


def test_get_commit_hash_subprocess_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(version_mod.subprocess, "run", _raise)
    assert get_commit_hash(tmp_path) is None


def test_get_commit_hash_os_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _raise(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(version_mod.subprocess, "run", _raise)
    assert get_commit_hash(tmp_path) is None


def test_get_commit_hash_non_zero_returncode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class _FakeCompleted:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    monkeypatch.setattr(
        version_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted()
    )
    assert get_commit_hash(tmp_path) is None


def test_get_commit_hash_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    class _FakeCompleted:
        returncode = 0
        stdout = "abc1234\n"
        stderr = ""

    monkeypatch.setattr(
        version_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted()
    )
    assert get_commit_hash(tmp_path) == "abc1234"


def test_get_commit_hash_success_trims_to_seven(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class _FakeCompleted:
        returncode = 0
        stdout = "abcdef1234567890\n"
        stderr = ""

    monkeypatch.setattr(
        version_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted()
    )
    # Even if git returned more, we cap at 7 for display consistency
    assert get_commit_hash(tmp_path) == "abcdef1"


def test_get_commit_hash_empty_stdout_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        version_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted()
    )
    assert get_commit_hash(tmp_path) is None


def test_get_commit_hash_default_install_dir_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
):
    """No install_dir argument should still not raise even if /opt path missing."""
    # On dev machines /opt/pv-inverter-proxy usually doesn't exist.
    # This should never raise.
    result = get_commit_hash()
    assert result is None or isinstance(result, str)
