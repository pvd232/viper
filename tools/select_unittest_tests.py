"""Apply portable graph selection to importable unittest references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_impact import codeql, testing


def select_unittest_tests(
    *,
    graph_path: Path,
    source_root: Path,
    declarations: tuple[str, ...],
    analyzed_roots: frozenset[str],
    fallback: str,
) -> dict[str, object]:
    """Union known tests with the supplied fallback and retain every graph gap."""
    graph = codeql.load_source_graph(graph_path, source_root.resolve(), analyzed_roots)
    selection = testing.select_graph_tests(
        graph,
        source_root=source_root,
        framework="unittest",
        declarations=declarations,
        fallback_tests=(fallback,),
    )
    return {
        "schema_version": 1,
        "mode": "fallback" if not selection.complete else "tests_and_fallback",
        "selected_tests": selection.known_tests,
        "unresolved": selection.unresolved,
        "analysis_unknowns": selection.analysis_unknowns,
        "fallback_tests": selection.fallback_tests,
        "complete": selection.complete,
        "requires_manual_selection": selection.requires_manual_selection,
        "unittest_args": selection.tests,
    }


def _parser() -> argparse.ArgumentParser:
    """Define the existing unittest adapter command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--declaration", action="append", required=True)
    parser.add_argument("--analyzed-root", action="append", required=True)
    parser.add_argument("--fallback", required=True)
    return parser


def main() -> int:
    """Print a deterministic selection without hiding unknown relationships."""
    arguments = _parser().parse_args()
    result = select_unittest_tests(
        graph_path=arguments.graph,
        source_root=arguments.source_root,
        declarations=tuple(arguments.declaration),
        analyzed_roots=frozenset(arguments.analyzed_root),
        fallback=arguments.fallback,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 1 if result["requires_manual_selection"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
