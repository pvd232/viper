"""Select unittest test names from a current VIPER source graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.select_impacted_tests import load_source_graph
from viper.test_impact import DeclarationId, TestRef, select_tests


def _unittest_ref(node: dict[str, Any]) -> str | None:
    """Convert one test declaration into an importable unittest name."""
    path = node["path"]
    symbol = node["symbol"]
    if not (
        isinstance(path, str)
        and path.startswith("tests/")
        and path.endswith(".py")
        and isinstance(symbol, str)
        and (symbol.startswith("test_") or ".test_" in symbol)
    ):
        return None
    module = path.removesuffix(".py").replace("/", ".")
    return f"{module}.{symbol}"


def select_unittest_tests(
    *,
    graph_path: Path,
    source_root: Path,
    declarations: tuple[str, ...],
    analyzed_roots: frozenset[str],
    fallback: str,
) -> dict[str, object]:
    """Return exact unittest names or one conservative fallback module."""
    if not declarations:
        raise ValueError("at least one changed declaration is required")
    nodes, edges = load_source_graph(
        graph_path,
        source_root.resolve(),
        analyzed_roots,
    )
    dependents: dict[DeclarationId, set[DeclarationId]] = {}
    for edge in edges:
        target = DeclarationId(str(edge["target"]))
        dependents.setdefault(target, set()).add(DeclarationId(str(edge["source"])))
    test_refs = {
        DeclarationId(declaration): TestRef(test)
        for declaration, node in nodes.items()
        if (test := _unittest_ref(node)) is not None
    }
    selection = select_tests(
        (DeclarationId(declaration) for declaration in declarations),
        dependents=dependents,
        observers={},
        test_refs_by_declaration=test_refs,
    )
    missing = {
        DeclarationId(declaration)
        for declaration in declarations
        if declaration not in nodes
    }
    unresolved = tuple(sorted(set(selection.unresolved) | missing))
    selected = tuple(selection.tests)
    arguments = (fallback,) if unresolved else selected
    return {
        "schema_version": 1,
        "mode": "fallback" if unresolved else "tests",
        "selected_tests": selected,
        "unresolved": unresolved,
        "unittest_args": arguments,
    }


def _parser() -> argparse.ArgumentParser:
    """Define the unittest adapter command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--declaration", action="append", required=True)
    parser.add_argument("--analyzed-root", action="append", required=True)
    parser.add_argument("--fallback", required=True)
    return parser


def main() -> int:
    """Print one deterministic unittest selection as JSON."""
    arguments = _parser().parse_args()
    result = select_unittest_tests(
        graph_path=arguments.graph,
        source_root=arguments.source_root,
        declarations=tuple(arguments.declaration),
        analyzed_roots=frozenset(arguments.analyzed_root),
        fallback=arguments.fallback,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
