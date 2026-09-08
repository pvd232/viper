"""Acceptance tests for PAC-05 ownership vocabulary."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import viper.http as http
import viper.repository as repository

PAIR_BLOCK_ID = "P2-PAC-05"
REQUIREMENT_ID = "PAC-05"
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
    """Reject project vocabulary except external Python and GCE standards."""
    src = ROOT / "src/viper"
    exemptions = {
        "google_project_id",
        "project_id",
        "pyproject.toml",
        "projects/",
        'parts[0] != "projects"',
        "project: nonemptystr",
        "project_value",
        "_gce_provisioning_id(kind: str, project: str",
        "quote(project",
        "project, name = parts[1]",
        'provisioning_id_get("boot_image", project',
        "project=project",
        "kind, project, name",
        'metadata_get("instance/attributes/viper-provisioning-project")',
        'metadata_get("project/project-id")',
    }
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            lowered = line.lower()
            if re.search(r"(?<![a-z])project(?![a-z])", lowered) is None:
                continue
            if any(exemption in lowered for exemption in exemptions):
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{line_number}:{line.strip()}")
    assert offenders == []
