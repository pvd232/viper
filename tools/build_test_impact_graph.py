"""Build VIPER's test graph through the independently installed source-impact."""

from __future__ import annotations

import argparse
from pathlib import Path

from source_impact import build

DEFAULT_ANALYZED_ROOTS = ("src", "tests", "tools")


def build_graph(
    *,
    repository: Path,
    codeql: Path,
    cache: Path,
    output: Path,
    analyzed_roots: tuple[str, ...] = DEFAULT_ANALYZED_ROOTS,
) -> None:
    """Apply VIPER's source-root defaults to the shared graph builder."""
    build.build_graph(
        repository=repository,
        codeql_executable=codeql,
        cache=cache,
        output=output,
        analyzed_roots=analyzed_roots,
    )


def main() -> int:
    """Build one current graph without checking out historical analyzer code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--codeql", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analyzed-root", action="append", dest="analyzed_roots")
    args = parser.parse_args()
    build_graph(
        repository=args.repository,
        codeql=args.codeql,
        cache=args.cache,
        output=args.output,
        analyzed_roots=tuple(args.analyzed_roots or DEFAULT_ANALYZED_ROOTS),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
