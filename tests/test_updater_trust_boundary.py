"""Trust-boundary enforcement: main service ↔ updater_root isolation.

Rules enforced by this test:

1. NO file inside ``src/pv_inverter_proxy/`` (except ``updater_root/**``)
   may import ``pv_inverter_proxy.updater_root``.
2. Files inside ``src/pv_inverter_proxy/updater_root/**`` may import ONLY
   from an allowlist of main-package modules: ``releases``, ``recovery``,
   ``state_file``. Any other ``from pv_inverter_proxy.<x>`` or
   ``import pv_inverter_proxy.<x>`` is a violation.

Detection is based on a real Python AST walk (``ast.parse`` +
``ast.Import`` / ``ast.ImportFrom``) so string matches inside comments,
docstrings, or identifier names cannot produce false positives.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pv_inverter_proxy"
UPDATER_ROOT = SRC / "updater_root"

#: The ONLY main-package modules updater_root may import from.
ALLOWED_MAIN_MODULES: frozenset[str] = frozenset(
    {"releases", "recovery", "state_file"}
)


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        # Skip __pycache__ and editable install artifacts defensively.
        if "__pycache__" in p.parts:
            continue
        yield p


def _collect_imports(py_file: Path) -> list[tuple[int, str]]:
    """Return [(lineno, fully-qualified-module-name)] for every import in ``py_file``."""
    try:
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
    except SyntaxError as e:  # pragma: no cover - defensive
        raise AssertionError(f"failed to parse {py_file}: {e}") from e
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) never reference pv_inverter_proxy.*
            # from the outside, so we only care about absolute imports here.
            if node.level == 0 and node.module:
                results.append((node.lineno, node.module))
    return results


def test_no_main_service_file_imports_updater_root():
    """Any file in src/pv_inverter_proxy/ OUTSIDE updater_root must not import it."""
    violations: list[str] = []
    for py in _iter_py_files(SRC):
        # Skip updater_root itself
        try:
            py.relative_to(UPDATER_ROOT)
            continue
        except ValueError:
            pass
        for lineno, modname in _collect_imports(py):
            if (
                modname == "pv_inverter_proxy.updater_root"
                or modname.startswith("pv_inverter_proxy.updater_root.")
            ):
                violations.append(
                    f"{py.relative_to(SRC.parent.parent)}:{lineno}: import {modname}"
                )
    assert not violations, (
        "TRUST BOUNDARY VIOLATION: main service files must never import "
        "pv_inverter_proxy.updater_root\n" + "\n".join(violations)
    )


def test_updater_root_only_imports_allowlisted_main_modules():
    """updater_root may only import releases, recovery, state_file from the main package."""
    assert UPDATER_ROOT.is_dir(), f"updater_root missing at {UPDATER_ROOT}"
    violations: list[str] = []
    for py in _iter_py_files(UPDATER_ROOT):
        for lineno, modname in _collect_imports(py):
            if not modname.startswith("pv_inverter_proxy"):
                continue  # stdlib + third-party is fine
            # Allow updater_root self-imports
            if (
                modname == "pv_inverter_proxy.updater_root"
                or modname.startswith("pv_inverter_proxy.updater_root.")
            ):
                continue
            # Strip the leading "pv_inverter_proxy." to get the top-level main module name
            if modname == "pv_inverter_proxy":
                # Bare package import is also forbidden — force explicit submodule
                violations.append(
                    f"{py.relative_to(SRC.parent.parent)}:{lineno}: "
                    f"import {modname} (forbidden: use explicit submodule)"
                )
                continue
            assert modname.startswith("pv_inverter_proxy.")
            tail = modname[len("pv_inverter_proxy."):]
            top = tail.split(".", 1)[0]
            if top not in ALLOWED_MAIN_MODULES:
                violations.append(
                    f"{py.relative_to(SRC.parent.parent)}:{lineno}: "
                    f"import {modname} (top-level '{top}' not in allowlist "
                    f"{sorted(ALLOWED_MAIN_MODULES)})"
                )
    assert not violations, (
        "TRUST BOUNDARY VIOLATION: updater_root imported a non-allowlisted "
        "main-package module\n" + "\n".join(violations)
    )


def test_updater_root_does_not_import_updater_package():
    """Explicit regression test: updater_root must NEVER import updater.* (schema must be mirrored)."""
    violations: list[str] = []
    for py in _iter_py_files(UPDATER_ROOT):
        for lineno, modname in _collect_imports(py):
            if (
                modname == "pv_inverter_proxy.updater"
                or modname.startswith("pv_inverter_proxy.updater.")
            ):
                violations.append(
                    f"{py.relative_to(SRC.parent.parent)}:{lineno}: import {modname}"
                )
    assert not violations, (
        "TRUST BOUNDARY VIOLATION: updater_root must never import "
        "pv_inverter_proxy.updater.* — schema must be mirrored independently\n"
        + "\n".join(violations)
    )


def test_updater_root_package_exists_and_has_expected_modules():
    """Sanity: the package layout is what downstream tests assume."""
    assert UPDATER_ROOT.is_dir()
    expected = {
        "__init__.py",
        "git_ops.py",
        "backup.py",
        "trigger_reader.py",
        "gpg_verify.py",
    }
    actual = {p.name for p in UPDATER_ROOT.iterdir() if p.is_file()}
    missing = expected - actual
    assert not missing, f"updater_root missing modules: {missing}"
