"""Initialize project files and establish global root discovery ."""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ._schema import ProtocolModel


class ProjectSettings(ProtocolModel):
    """Validate settings ."""
    schema_version: Literal[1]


class ProjectRootError(ValueError):
    """Report a missing, invalid, or incompatible project root ."""


def find_project_root(start: Path) -> Path:
    """Greedily searches tree for <ROOT>/viper.toml until failure ."""
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    # *(Iterator) unpacks it
    for directory in (candidate, *candidate.parents):
        if (directory / "viper.toml").is_file():
            return directory
    raise ProjectRootError(f"no viper.toml found from {start}")


def _require_git_work_tree(root: Path) -> None:
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
    """Validate the user has a valid viper.toml then return the resolved root path ."""
    resolved = find_project_root(root if root is not None else Path.cwd())
    marker = resolved / "viper.toml"
    try:
        data = tomllib.loads(marker.read_text(encoding="utf-8"))
        ProjectSettings.model_validate(data.get("project", {}))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ProjectRootError(f"invalid project marker: {marker}") from error

    _require_git_work_tree(resolved)
    return resolved


def _resolve_operation_root(root: Path | None) -> Path:
    return resolve_project_root(root)
