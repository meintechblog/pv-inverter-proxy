"""Version parsing + current-version resolution for the updater subsystem.

Requirements:
    CHECK-01 (Phase 44): Determine the running build's version and expose it
    as a comparable tuple.

References:
    - .planning/research/STACK.md section 2 ("Version source of truth")
    - pyproject.toml [project].name / version

Design notes:
    This module is intentionally hand-rolled to avoid pulling in `packaging`
    or `semver` as new dependencies. The version grammar we need is narrow:
    two- or three-field dotted integers with an optional leading `v`. A
    single anchored regex is enough and gives us a free ReDoS-safe parser.

    `Version` is a NamedTuple, so ordering/equality are free via tuple
    comparison — we never need a separate `<`/`>` implementation.

    `get_current_version()` reads from `importlib.metadata` (stdlib since
    3.8) rather than importing any project module, so it keeps working in
    an editable install and never crashes if the package metadata is
    missing — it just returns `"unknown"`.
"""
from __future__ import annotations

import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

import structlog

log = structlog.get_logger(component="updater.version")

#: Name as it appears in pyproject.toml's ``[project].name``. Keep in sync.
PACKAGE_NAME = "pv-inverter-master"

#: Default install directory used by get_commit_hash when caller passes None.
DEFAULT_INSTALL_DIR = Path("/opt/pv-inverter-proxy")

#: Anchored, no nested quantifiers → bounded linear time, ReDoS-safe.
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class Version(NamedTuple):
    """Semver-ish triple (major, minor, patch).

    Tuple comparison gives free <, <=, ==, >=, > ordering. Use :meth:`parse`
    to build one from a string; use :meth:`__str__` to get the canonical
    ``vX.Y.Z`` form back.
    """

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "Version":
        """Parse ``vX.Y`` or ``vX.Y.Z`` (leading ``v`` optional).

        Whitespace is stripped. Missing patch defaults to 0. Anything else
        (single-field, 4-field, pre-release suffix, empty, etc.) raises
        :class:`ValueError`.

        Args:
            raw: The version string to parse.

        Returns:
            A :class:`Version` tuple.

        Raises:
            ValueError: If ``raw`` is not a recognizable version string.
        """
        if not isinstance(raw, str):
            raise ValueError(f"Unparseable version: {raw!r}")
        stripped = raw.strip()
        match = _VERSION_RE.match(stripped)
        if match is None:
            raise ValueError(f"Unparseable version: {raw!r}")
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3) or 0),
        )

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


def get_current_version() -> str:
    """Return the running build's version string, or ``"unknown"``.

    Reads ``importlib.metadata.version(PACKAGE_NAME)``. Catches
    ``PackageNotFoundError`` (editable install / broken pyproject) and any
    other exception defensively. **Never raises.**

    The returned string may or may not be parseable by :meth:`Version.parse`
    — callers that need a structured comparison must wrap the call in a
    try/except.
    """
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        log.debug("package_metadata_not_found", package=PACKAGE_NAME)
        return "unknown"
    except Exception as exc:  # pragma: no cover - defensive
        log.warning(
            "package_metadata_unexpected_error",
            package=PACKAGE_NAME,
            error=str(exc),
        )
        return "unknown"


def get_commit_hash(install_dir: Path | None = None) -> str | None:
    """Return the 7-char short SHA of ``install_dir``'s current HEAD.

    Shells out to ``git -C <install_dir> rev-parse --short HEAD``. Uses an
    explicit argv list (never ``shell=True``) so there is no injection
    surface. Returns ``None`` on every failure mode — git missing, path
    missing, .git missing, non-zero exit, timeout, permission error —
    **never raises**.

    Args:
        install_dir: Repository path. Defaults to ``/opt/pv-inverter-proxy``
            when ``None``.

    Returns:
        Lowercase hex short SHA (max 7 chars) or ``None``.
    """
    target = install_dir if install_dir is not None else DEFAULT_INSTALL_DIR
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        log.debug("git_binary_missing", install_dir=str(target))
        return None
    except subprocess.TimeoutExpired:
        log.debug("git_rev_parse_timeout", install_dir=str(target))
        return None
    except OSError as exc:
        log.debug(
            "git_rev_parse_os_error", install_dir=str(target), error=str(exc)
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive catch-all
        log.debug(
            "git_rev_parse_unexpected",
            install_dir=str(target),
            error=str(exc),
        )
        return None

    if result.returncode != 0:
        log.debug(
            "git_rev_parse_nonzero",
            install_dir=str(target),
            returncode=result.returncode,
            stderr=(result.stderr or "").strip()[:200],
        )
        return None

    sha = (result.stdout or "").strip()
    if not sha:
        return None
    return sha[:7]
