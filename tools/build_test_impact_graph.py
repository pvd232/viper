"""Build the declaration graph with VIPER's retained CodeQL/AST analyzer."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ANALYZER_REVISION = "4840ee9875b5382d547595b2bee62b8f16365611"
ANALYZER_ROOT = Path(__file__).parents[1]
DEFAULT_ANALYZED_ROOTS = ("src", "tests", "tools")


class GraphBuildError(RuntimeError):
    """Report failure to materialize or run the retained analyzer."""


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    """Run one graph-build command and retain its terminal output."""
    completed = subprocess.run(command, cwd=cwd, check=False, env=env)
    if completed.returncode != 0:
        raise GraphBuildError(
            f"command failed with exit {completed.returncode}: {command}"
        )


def build_graph(
    *,
    repository: Path,
    codeql: Path,
    cache: Path,
    output: Path,
    analyzed_roots: tuple[str, ...] = DEFAULT_ANALYZED_ROOTS,
) -> None:
    """Run the pinned analyzer plus its current-source compatibility patch."""
    root = repository.resolve()
    analyzer_root = ANALYZER_ROOT.resolve()
    patch = analyzer_root / "tools/codeql/test-impact-compat.patch"
    if not patch.is_file():
        raise GraphBuildError(f"compatibility patch is absent: {patch}")
    if not analyzed_roots or any(
        not item or Path(item).parts != (item,) or item in {".", ".."}
        for item in analyzed_roots
    ):
        raise GraphBuildError("analyzed roots must be top-level directory names")

    with tempfile.TemporaryDirectory(prefix="viper-test-impact.") as directory:
        worktree = Path(directory) / "analyzer"
        _run(
            (
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                ANALYZER_REVISION,
            ),
            cwd=analyzer_root,
        )
        try:
            _run(("git", "apply", "--unidiff-zero", str(patch)), cwd=worktree)
            shutil.copyfile(
                analyzer_root / "tools/codeql/historical_test_impact_worker.py.txt",
                worktree / "tools/_historical_test_impact_worker.py",
            )
            root_arguments = tuple(
                argument
                for analyzed_root in analyzed_roots
                for argument in ("--analyzed-root", analyzed_root)
            )
            _run(
                (
                    sys.executable,
                    "tools/_historical_test_impact_worker.py",
                    "--repository",
                    str(root),
                    "--codeql",
                    str(codeql.resolve()),
                    "--cache",
                    str(cache.resolve()),
                    "--output",
                    str(output.resolve()),
                    *root_arguments,
                ),
                cwd=worktree,
                env={**os.environ, "PYTHONPATH": str(worktree / "src")},
            )
        finally:
            _run(
                ("git", "worktree", "remove", "--force", str(worktree)),
                cwd=analyzer_root,
            )


def _parser() -> argparse.ArgumentParser:
    """Define the pinned analyzer command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--codeql", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analyzed-root", action="append", dest="analyzed_roots")
    return parser


def main() -> int:
    """Build one graph or return a nonzero process result."""
    arguments = _parser().parse_args()
    build_graph(
        repository=arguments.repository,
        codeql=arguments.codeql,
        cache=arguments.cache,
        output=arguments.output,
        analyzed_roots=tuple(arguments.analyzed_roots or DEFAULT_ANALYZED_ROOTS),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
