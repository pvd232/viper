"""Planned acceptance tests for the PAC-07 final public inventory."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

PAIR_BLOCK_ID = "P3-PAC-07"
REQUIREMENT_ID = "PAC-07"
PLANNED_DESTINATION = "tests/test_public_inventory.py"

ROOT = Path(__file__).resolve().parents[1]
RETIRED_AUTHORING_TERMS = (
    "ParameterSet",
    "ParameterModelRef",
    "parameter_model",
    "stage_params",
    "artifacts=",
    "context.params",
    "context.artifacts",
    "ProjectHttpImplementationSpec",
    "init_project",
)


def test_public_modules_expose_the_approved_authoring_vocabulary() -> None:
    """Present config, output, diagnostic, workspace, and repository names."""
    config = importlib.import_module("viper.config")
    outputs = importlib.import_module("viper.outputs")
    stages = importlib.import_module("viper.stages")
    repository = importlib.import_module("viper.repository")
    assert hasattr(config, "TrainConfig")
    assert hasattr(outputs, "TrainOutputs")
    assert hasattr(stages, "diagnostic")
    assert hasattr(repository, "init_workspace")


def test_public_documents_do_not_teach_retired_authoring_terms() -> None:
    """Remove retired names from public prose and executable examples."""
    public_directories = (
        ROOT / "docs/tutorials",
        ROOT / "docs/how-to",
        ROOT / "docs/explanation",
        ROOT / "docs/reference",
    )
    paths = [
        ROOT / "README.md",
        *(
            path
            for directory in public_directories
            if directory.exists()
            for path in sorted(directory.rglob("*.md"))
        ),
    ]
    offenders: list[str] = []
    for path in paths:
        text = path.read_text()
        for term in RETIRED_AUTHORING_TERMS:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}:{term}")
    assert offenders == []


def test_generated_workspace_uses_final_public_names(tmp_path: Path) -> None:
    """Generate examples with the same vocabulary users read in the docs."""
    repository = importlib.import_module("viper.repository")
    repository.init_workspace(tmp_path)
    generated = "\n".join(
        path.read_text() for path in sorted(tmp_path.rglob("*.py"))
    )
    assert "TrainConfig" in generated
    assert "TrainOutputs" in generated
    assert "config=" in generated
    assert "outputs=" in generated
    assert not any(term in generated for term in RETIRED_AUTHORING_TERMS)


def test_capabilities_include_diagnostic_and_config_vocabulary() -> None:
    """Keep machine-readable discovery aligned with the Python API."""
    completed = subprocess.run(
        [sys.executable, "-m", "viper.cli", "--json", "capabilities"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    rendered = json.dumps(payload, sort_keys=True)
    assert "diagnostic" in rendered
    assert "config" in rendered
    assert "parameter_model" not in rendered
    assert "stage_params" not in rendered


def test_checked_in_schemas_use_version_two_authoring_names() -> None:
    """Keep generated schema documents synchronized with the final protocol."""
    offenders: list[str] = []
    for path in sorted((ROOT / "schemas").rglob("*.json")):
        text = path.read_text()
        if '"schema_version"' in text and '"const": 2' not in text:
            offenders.append(f"{path.relative_to(ROOT)}:schema_version")
        for term in ("parameter_model", "stage_params"):
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}:{term}")
    assert offenders == []
