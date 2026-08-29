"""Provide Git repository operations shared by execution acceptance tests."""

import subprocess
from pathlib import Path

REPOSITORY = "https://github.com/example/viper-local-project"


def run_git(root: Path, *arguments: str) -> str:
    """Run one successful Git command in an acceptance repository."""
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
