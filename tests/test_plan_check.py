"""Verify the pre-pairing plan command."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.plan import check


def test_baseline_analysis_uses_clean_candidate_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep checkout caches and environments out of the baseline database."""
    root = tmp_path / "repository"
    root.mkdir()
    results = tmp_path / "results"
    candidate = results / "candidate"
    block = SimpleNamespace(block_id="P1-TST-01", requirements=("TST-01",))
    baseline = object()
    events: list[tuple[str, Path]] = []

    monkeypatch.setattr(check, "_git_revision", lambda _root: "1" * 40)
    monkeypatch.setattr(check, "_contracts", lambda _root: ())
    monkeypatch.setattr(check, "compile_contract_plan", lambda *_args: ((block,), ()))
    monkeypatch.setattr(check, "_implemented_pair_blocks", lambda _path: frozenset())
    monkeypatch.setattr(
        check,
        "select_blocks",
        lambda *_args, **_kwargs: ("P1-TST-01",),
    )
    monkeypatch.setattr(
        check,
        "compile_contract_traceability",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(check, "_specs", lambda *_args: (object(), object(), object()))

    def checkout(_root: Path, _revision: str, destination: Path) -> None:
        events.append(("checkout", destination))
        destination.mkdir(parents=True)

    def analyze(analyzed_root: Path, **_kwargs: object) -> object:
        events.append(("analyze", analyzed_root))
        return baseline

    def stop_after_analysis(*args: object, **_kwargs: object) -> None:
        applied_candidate = args[0]
        assert isinstance(applied_candidate, Path)
        events.append(("apply", applied_candidate))
        assert args[1] == root
        assert args[4] is baseline
        raise check.ScheduleError("stop after baseline analysis")

    monkeypatch.setattr(check, "_checkout_candidate", checkout)
    monkeypatch.setattr(check, "_analyze", analyze)
    monkeypatch.setattr(check, "apply_plan", stop_after_analysis)

    result = check.validate(
        root=root,
        blocks=("P1-TST-01",),
        codeql=Path("codeql"),
        query_pack=Path("query-pack"),
        python=Path("python"),
        cache=tmp_path / "cache",
        results=results,
    )

    assert result["stage"] == "materialize"
    assert events == [
        ("checkout", candidate),
        ("analyze", candidate),
        ("apply", candidate),
    ]


def test_ruff_formats_only_candidate_copy() -> None:
    """Format only the final copy, then keep every Ruff check read-only."""
    python = Path(".venv/bin/python")
    target = "src/viper/example.py"

    formatting = dict(check._format(python, (target,)))
    commands = dict(check._ruff(python, (target,)))

    assert formatting["ruff-format"] == (
        str(python),
        "-m",
        "ruff",
        "format",
        target,
    )
    assert "--fix" in formatting["ruff-imports"]

    assert commands["ruff-format"] == (
        str(python),
        "-m",
        "ruff",
        "format",
        "--check",
        target,
    )
    assert commands["ruff-imports"] == (
        str(python),
        "-m",
        "ruff",
        "check",
        "--select",
        "I001",
        target,
    )
    assert all("--fix" not in command for command in commands.values())
