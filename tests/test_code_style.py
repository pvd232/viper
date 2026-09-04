"""Enforce repository-wide source conventions that linters cannot express."""

from __future__ import annotations

import tokenize
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYTHON_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "tools")


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
