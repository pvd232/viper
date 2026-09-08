"""Enforce repository-wide source conventions that linters cannot express."""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYTHON_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "tools", ROOT / "plans")


def test_python_imports_are_declared_at_module_scope() -> None:
    """Keep imports visible at the top of each repository-owned module."""
    violations: list[str] = []

    for source_root in PYTHON_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(tree):
                parents.update(
                    (child, parent) for child in ast.iter_child_nodes(parent)
                )

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    parent = parents.get(node)
                    while parent is not None:
                        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            violations.append(
                                f"{path.relative_to(ROOT)}:{node.lineno}:nested import"
                            )
                            break
                        parent = parents.get(parent)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                ):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}:dynamic import"
                    )

    assert violations == []


def test_repository_has_no_inline_lint_suppressions() -> None:
    """Require code and contracts to fix lint failures instead of hiding them."""
    directive = "no" + "qa"
    occurrences: list[str] = []

    for source_root in PYTHON_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            with path.open("rb") as source:
                comments = (
                    token
                    for token in tokenize.tokenize(source.readline)
                    if token.type == tokenize.COMMENT
                )
                occurrences.extend(
                    f"{path.relative_to(ROOT)}:{token.start[0]}"
                    for token in comments
                    if directive in token.string.lower()
                )

    for path in sorted((ROOT / "docs").rglob("*.md")):
        occurrences.extend(
            f"{path.relative_to(ROOT)}:{line_number}"
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            )
            if directive in line.lower()
        )

    assert occurrences == []
