"""Verify the pre-pairing plan command."""

from pathlib import Path

from tools.plan import check


def test_ruff_does_not_rewrite_planned_source() -> None:
    """Reject unformatted code without changing the planned candidate."""
    python = Path(".venv/bin/python")
    target = "src/viper/example.py"

    commands = dict(check._ruff(python, (target,)))

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
