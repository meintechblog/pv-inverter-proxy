"""Phase 46 minimal ``UpdateConfig`` dataclass (D-04 / D-05 / D-06).

Phase 46 intentionally ships only three fields:

    github_repo: str           (default: ``"hulki/pv-inverter-proxy"``)
    check_interval_hours: int  (default: ``24``)
    auto_install: bool         (default: ``False``)

The full config schema (CFG-01) waits for Phase 47.

This module exposes:

* :class:`UpdateConfig` — the 3-field dataclass
* :data:`DEFAULT_UPDATE_CONFIG` — a pre-built defaults instance
* :data:`ALLOWED_UPDATE_CONFIG_KEYS` — the frozen set of valid keys
* :func:`load_update_config` — YAML read → typed dataclass (with
  per-field type coercion + fall-back to defaults on garbage)
* :func:`save_update_config` — YAML read-modify-write under the
  ``update:`` key, preserving **all** other top-level keys
  (``inverters:``, ``venus:``, ``proxy:``, …)
* :func:`validate_update_config_patch` — API allow-list + type
  validation used by the ``PATCH /api/update/config`` handler

The module does NOT import :mod:`pv_inverter_proxy.config` because that
module operates on a fully-typed :class:`~pv_inverter_proxy.config.Config`
dataclass (not a raw ``dict``). Saving the update sub-section through
``config.save_config`` would force us to roundtrip the entire dataclass
and risk clobbering sibling keys we don't know about. A direct YAML
read-modify-write is safer and keeps the update concern isolated.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, fields
from typing import Any

import yaml

#: Top-level YAML key under which the update config is persisted.
UPDATE_CONFIG_SECTION_KEY = "update"


@dataclass
class UpdateConfig:
    """Minimal 3-field config dataclass per D-04."""

    github_repo: str = "hulki/pv-inverter-proxy"
    check_interval_hours: int = 24
    auto_install: bool = False


#: Default instance used when the config file or section is missing.
DEFAULT_UPDATE_CONFIG = UpdateConfig()

#: Immutable allow-list of keys accepted by load/save/validate.
ALLOWED_UPDATE_CONFIG_KEYS = frozenset(
    f.name for f in fields(UpdateConfig)
)


def _coerce_loaded_section(section: Any) -> dict[str, Any]:
    """Filter a raw YAML sub-dict into per-field kwargs for UpdateConfig.

    Garbage values (wrong type, empty string, non-positive ints, ints that
    are actually bools) are silently dropped so the caller falls back to
    the dataclass default. Rationale: the config file is user-edited and
    we prefer "boot with defaults" over "crash on bad YAML".
    """
    if not isinstance(section, dict):
        return {}
    kwargs: dict[str, Any] = {}

    repo = section.get("github_repo")
    if isinstance(repo, str) and repo.strip():
        kwargs["github_repo"] = repo

    ci = section.get("check_interval_hours")
    # Reject bool (subclass of int in Python) and non-positive values.
    if isinstance(ci, int) and not isinstance(ci, bool) and ci > 0:
        kwargs["check_interval_hours"] = ci

    ai = section.get("auto_install")
    if isinstance(ai, bool):
        kwargs["auto_install"] = ai

    return kwargs


def load_update_config(config_path: str) -> UpdateConfig:
    """Read the ``update:`` sub-dict from ``config_path`` and return a typed
    :class:`UpdateConfig`. Missing file, missing section, or per-field
    garbage falls back to defaults.
    """
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return UpdateConfig()
    except Exception:  # pragma: no cover - defensive
        return UpdateConfig()

    if not isinstance(raw, dict):
        return UpdateConfig()

    section = raw.get(UPDATE_CONFIG_SECTION_KEY)
    return UpdateConfig(**_coerce_loaded_section(section))


def save_update_config(config_path: str, update_conf: UpdateConfig) -> None:
    """Persist ``update_conf`` into the ``update:`` sub-dict of
    ``config_path``, preserving every other top-level key untouched.

    Atomic write via ``tempfile.mkstemp`` + ``os.replace`` so a concurrent
    reader never observes a truncated file.
    """
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raw = {}
    except Exception:  # pragma: no cover - defensive
        raw = {}

    if not isinstance(raw, dict):
        raw = {}

    raw[UPDATE_CONFIG_SECTION_KEY] = {
        "github_repo": update_conf.github_repo,
        "check_interval_hours": update_conf.check_interval_hours,
        "auto_install": update_conf.auto_install,
    }

    abs_path = os.path.abspath(config_path)
    config_dir = os.path.dirname(abs_path) or "."
    os.makedirs(config_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=True)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def validate_update_config_patch(
    patch: Any,
) -> tuple[bool, str | None]:
    """Validate a PATCH payload against the D-04 allow-list.

    Returns ``(True, None)`` when the patch is acceptable (subset of the
    3 allowed keys, each with a correctly-typed value). Returns
    ``(False, error_code)`` with a machine-readable error string
    otherwise. The error code is intended to be returned verbatim in the
    ``detail`` field of the 422 JSON response.

    An **empty** patch is accepted (zero-key subset); callers decide
    whether to short-circuit the save in that case.
    """
    if not isinstance(patch, dict):
        return False, "patch_must_be_object"

    unknown = set(patch.keys()) - ALLOWED_UPDATE_CONFIG_KEYS
    if unknown:
        return (
            False,
            "unknown_keys:" + ",".join(sorted(unknown)),
        )

    if "github_repo" in patch:
        v = patch["github_repo"]
        if not isinstance(v, str) or not v.strip():
            return False, "github_repo_must_be_nonempty_string"

    if "check_interval_hours" in patch:
        v = patch["check_interval_hours"]
        # bool is a subclass of int → reject explicitly
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            return False, "check_interval_hours_must_be_positive_int"

    if "auto_install" in patch:
        v = patch["auto_install"]
        if not isinstance(v, bool):
            return False, "auto_install_must_be_bool"

    return True, None
