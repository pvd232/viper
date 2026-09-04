"""Verify the pre-pairing plan command."""

from pathlib import Path

from tools.plan import check


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
