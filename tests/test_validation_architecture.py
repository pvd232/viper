"""Tests for validation tiers and Python access boundaries."""

import ast
from pathlib import Path

import pytest

from tests.conftest import DOMAIN_BY_MODULE, TIER_BY_MODULE
from viper.project import PathError, resolve_path

ROOT = Path(__file__).parents[1]


def _redundant_private_modules(source_root: Path) -> list[Path]:
    """Find private modules nested beneath an already private package."""
    violations: list[Path] = []
    for path in source_root.rglob("_*.py"):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(source_root)
        if any(part.startswith("_") for part in relative.parts[:-1]):
            violations.append(relative)
    return sorted(violations)


def _shared_private_symbols(source_root: Path) -> list[tuple[Path, int, str]]:
    """Find single-underscore symbols imported across module boundaries."""
    violations: list[tuple[Path, int, str]] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for imported in node.names:
                if imported.name.startswith("_") and not imported.name.startswith("__"):
                    violations.append(
                        (path.relative_to(source_root), node.lineno, imported.name)
                    )
    return sorted(violations)


def test_every_test_module_has_one_tier_and_domain() -> None:
    """Require every collected test module to declare both classifications."""
    tests_root = Path(__file__).parent
    modules = {path.stem for path in tests_root.glob("test_*.py")}

    assert TIER_BY_MODULE.keys() == DOMAIN_BY_MODULE.keys()
    assert set(TIER_BY_MODULE) == modules
    assert set(TIER_BY_MODULE.values()) <= {
        "unit",
        "contract",
        "integration",
        "release",
    }


def test_source_tree_uses_one_private_boundary() -> None:
    """Accept the completed source tree under both access-boundary rules."""
    source_root = Path(__file__).parents[1] / "src" / "viper"

    assert _redundant_private_modules(source_root) == []
    assert _shared_private_symbols(source_root) == []


def test_private_package_rejects_an_underscored_module(tmp_path: Path) -> None:
    """Reject a second private marker beneath a private package."""
    source_root = tmp_path / "viper"
    module = source_root / "_runtime" / "_process.py"
    module.parent.mkdir(parents=True)
    module.write_text("def launch():\n    return None\n", encoding="utf-8")

    assert _redundant_private_modules(source_root) == [Path("_runtime/_process.py")]


def test_cross_module_import_rejects_an_underscored_symbol(tmp_path: Path) -> None:
    """Reject a private symbol imported by another module."""
    source_root = tmp_path / "viper"
    module = source_root / "execution" / "_run.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from ._attempt import _execute_attempt\n",
        encoding="utf-8",
    )

    assert _shared_private_symbols(source_root) == [
        (Path("execution/_run.py"), 1, "_execute_attempt")
    ]


def test_project_paths_reject_symlinks(tmp_path: Path) -> None:
    """Reject project paths containing traversal or descendant symlinks."""
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n", encoding="utf-8")
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "link.csv").symlink_to(outside)
    with pytest.raises(PathError, match="symlink"):
        resolve_path(root, "inputs/link.csv", operation="read")
    with pytest.raises(PathError, match="escapes"):
        resolve_path(root, "../outside.csv", operation="read")


def test_operations_resolve_project_root_once() -> None:
    """Resolve each selected project root once at its operation boundary."""
    source = ast.parse(
        (ROOT / "src/viper/_api/handlers.py").read_text(encoding="utf-8")
    )
    expected_calls = {
        "freeze_run": 1,
        "preflight": 1,
        "execute_stage": 1,
        "run_request": 1,
        "retry_request": 1,
        "execute_benchmark": 1,
        "plan_diff": 2,
        "verify_run": 1,
        "lineage": 1,
        "compare_runs": 2,
        "verify_benchmark": 1,
        "verify_pointer": 1,
    }
    functions = {
        node.name: node for node in source.body if isinstance(node, ast.FunctionDef)
    }
    for name, expected in expected_calls.items():
        calls = tuple(
            node
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_root"
        )
        assert len(calls) == expected, name
