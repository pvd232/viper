"""Guard the pinned CodeQL/AST graph-builder boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.build_test_impact_graph import (
    ANALYZER_REVISION,
    GraphBuildError,
    build_graph,
)
from viper._subprocess import run as run_subprocess


def test_compatibility_patch_applies_to_the_pinned_analyzer(tmp_path: Path) -> None:
    """Reject drift between the retained revision and its compatibility patch."""
    root = Path(__file__).parents[1]
    worktree = tmp_path / "analyzer"
    run_subprocess(
        ("git", "worktree", "add", "--detach", str(worktree), ANALYZER_REVISION),
        cwd=root,
        check=True,
        capture_output=True,
    )
    try:
        run_subprocess(
            (
                "git",
                "apply",
                "--check",
                "--unidiff-zero",
                str(root / "tools/codeql/test-impact-compat.patch"),
            ),
            cwd=worktree,
            check=True,
            capture_output=True,
        )
    finally:
        run_subprocess(
            ("git", "worktree", "remove", "--force", str(worktree)),
            cwd=root,
            check=True,
            capture_output=True,
        )


def test_graph_builder_removes_worktree_after_worker_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the detached analyzer checkout when graph construction fails."""
    root = tmp_path / "repository"
    patch = root / "tools/codeql/test-impact-compat.patch"
    worker = root / "tools/codeql/historical_test_impact_worker.py.txt"
    patch.parent.mkdir(parents=True)
    patch.write_text("patch", encoding="utf-8")
    worker.write_text("worker", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        del cwd, env
        commands.append(command)
        if command[0].endswith("python"):
            raise GraphBuildError("worker failed")

    monkeypatch.setattr("tools.build_test_impact_graph._run", fake_run)
    monkeypatch.setattr(
        "tools.build_test_impact_graph.shutil.copyfile",
        lambda *_: None,
    )

    with pytest.raises(GraphBuildError, match="worker failed"):
        build_graph(
            repository=root,
            codeql=tmp_path / "codeql",
            cache=tmp_path / "cache",
            output=tmp_path / "graph.json",
        )

    assert commands[-1][0:4] == ("git", "worktree", "remove", "--force")
