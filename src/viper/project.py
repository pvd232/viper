"""Discover and validate the root of a Git-backed VIPER project."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from ._schema import ProtocolModel


class ProjectSettings(ProtocolModel):
    """Represent the ``[project]`` table stored in ``viper.toml``."""

    schema_version: Literal[1] = Field(
        description="Version of the project-marker schema."
    )


class ProjectRootError(ValueError):
    """Report failure to discover or validate a VIPER project root."""


def find_project_root(start: Path) -> Path:
    """Return the nearest ancestor of ``start`` that contains ``viper.toml``."""
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "viper.toml").is_file():
            return directory
    raise ProjectRootError(f"no viper.toml found from {start}")


def _require_git_work_tree(root: Path) -> None:
    """Require ``root`` to equal the top level of its Git work tree."""
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProjectRootError(f"project root is not in a Git work tree: {root}")
    if Path(completed.stdout.strip()).resolve() != root:
        raise ProjectRootError(f"viper.toml must be a Git work-tree root: {root}")


def resolve_project_root(root: Path | None = None) -> Path:
    """Return a project root with a valid marker at its Git work-tree boundary."""
    resolved = find_project_root(root if root is not None else Path.cwd())
    marker = resolved / "viper.toml"
    try:
        data = tomllib.loads(marker.read_text(encoding="utf-8"))
        ProjectSettings.model_validate(data.get("project", {}))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ProjectRootError(f"invalid project marker: {marker}") from error

    _require_git_work_tree(resolved)
    return resolved
