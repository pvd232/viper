"""Planned acceptance tests for PAC-05 ownership vocabulary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import viper.repository as repository

import viper.http as http

PAIR_BLOCK_ID = "P2-PAC-05"
REQUIREMENT_ID = "PAC-05"
PLANNED_DESTINATION = "tests/test_workspace_vocabulary.py"

ROOT = Path(__file__).resolve().parents[1]


def test_repository_module_owns_root_operations() -> None:
    """Name Git and filesystem-root operations after their actual boundary."""
    assert hasattr(repository, "RepositorySettings")
    assert hasattr(repository, "find_root")
    assert hasattr(repository, "init_workspace")
    assert importlib.util.find_spec("viper.project") is None


def test_workspace_http_implementation_uses_workspace_owner() -> None:
    """Name user-authored HTTP code and config after the workspace."""
    assert hasattr(http, "WorkspaceHttpImplementationSpec")
    assert not hasattr(http, "ProjectHttpImplementationSpec")


def test_viper_settings_use_workspace_marker() -> None:
    """Store the versioned VIPER marker under the workspace table."""
    settings = repository.RepositorySettings.model_validate({"schema_version": 2})
    assert settings.schema_version == 2


def test_viper_owned_python_identifiers_do_not_use_project() -> None:
    """Reject project vocabulary in VIPER-owned public Python identifiers."""
    src = ROOT / "src/viper"
    exemptions = {
        "google_project_id",
        "project_id",  # Google Cloud provider field.
    }
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            lowered = line.lower()
            if "project" not in lowered:
                continue
            if any(exemption in lowered for exemption in exemptions):
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{line_number}:{line.strip()}")
    assert offenders == []
