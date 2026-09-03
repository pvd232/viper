"""Acceptance tests for the installed project scaffold operation."""

from __future__ import annotations

import subprocess
import sys
from os import environ
from pathlib import Path

from viper.api import (
    InitProjectRequest,
    ViperFailure,
    dispatch,
    init_project,
)
from viper.project import find_root, init, resolve_root


def test_init_generates_importable_five_stage_project(
    tmp_path: Path,
) -> None:
    """Generate the project and execute its focused tests without editing it."""
    target = tmp_path / "starter"
    environment = environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())

    result = init_project(InitProjectRequest(path=target, package="sample_project"))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=target,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.project_root == target
    assert len(result.files) == 22
    assert target / "viper.toml" in result.files
    assert target / "inputs" / ".gitkeep" in result.files
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_init_rejects_occupied_target_without_mutation(
    tmp_path: Path,
) -> None:
    """Preserve every existing file when the target directory is occupied."""
    target = tmp_path / "occupied"
    target.mkdir()
    existing = target / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    result = dispatch(
        "init_project",
        {"path": target, "package": "sample_project"},
    )

    assert isinstance(result, ViperFailure)
    assert result.code == "write_conflict"
    assert existing.read_text(encoding="utf-8") == "keep"
    assert tuple(target.iterdir()) == (existing,)


def test_init_rejects_invalid_package_before_writing(
    tmp_path: Path,
) -> None:
    """Reject an invalid import name at the request-validation boundary."""
    target = tmp_path / "starter"

    result = dispatch(
        "init_project",
        {"path": target, "package": "Bad-Package"},
    )

    assert isinstance(result, ViperFailure)
    assert result.origin == "request"
    assert result.code == "invalid_request"
    assert not target.exists()


def test_init_establishes_discoverable_root(tmp_path: Path) -> None:
    """Guarantee that project root discovery and resolution == project init path ."""
    target = tmp_path / "outside" / "starter"
    init(target, "sample_project")
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    child = target / "src" / "sample_project"
    assert find_root(child) == target.resolve()
    assert resolve_root(child) == target.resolve()
    required = {
        "viper.toml",
        "inputs",
        "benchmarks",
        "experiments",
        ".gitignore",
        "pyproject.toml",
    }
    assert required <= {path.name for path in target.iterdir()}
