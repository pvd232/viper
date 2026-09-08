"""Acceptance tests for the PAC-07 final public inventory."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import viper._schema as schema
import viper.config as config
import viper.outputs as outputs
import viper.repository as repository
import viper.stages as stages
from tests._documentation import dotted_name, python_blocks
from viper import _subprocess as subprocess

PAIR_BLOCK_ID = "P3-PAC-07"
REQUIREMENT_ID = "PAC-07"
ROOT = Path(__file__).resolve().parents[1]
RETIRED_AUTHORING_TERMS = (
    "ParameterSet",
    "ParameterModelRef",
    "parameter_model",
    "stage_params",
    "context.params",
    "ProjectHttpImplementationSpec",
    "init_project",
)
DISCOURAGED_DOC_IMPORTS = (
    "from viper import config",
    "config.BuildConfig",
    "config.DiagnosticConfig",
    "config.EmbedConfig",
    "config.EvalConfig",
    "config.HttpConfig",
    "config.MetricConfig",
    "config.TrainConfig",
)


def test_public_modules_expose_the_approved_authoring_vocabulary() -> None:
    """Present config, output, diagnostic, workspace, and repository names."""
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
        for block in python_blocks(text):
            for node in ast.walk(ast.parse(block)):
                if not isinstance(node, ast.Call):
                    continue
                name = dotted_name(node.func)
                if name is None or name.rsplit(".", 1)[-1] not in {"stage", "download"}:
                    continue
                if any(keyword.arg == "artifacts" for keyword in node.keywords):
                    offenders.append(f"{path.relative_to(ROOT)}:{name}(artifacts=)")
    assert offenders == []


def test_public_documents_import_config_classes_directly() -> None:
    """Teach direct imports from each symbol's public owner module."""
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
            for path in sorted(directory.rglob("*.md"))
        ),
    ]
    offenders = [
        f"{path.relative_to(ROOT)}:{pattern}"
        for path in paths
        for pattern in DISCOURAGED_DOC_IMPORTS
        if pattern in path.read_text()
    ]
    assert offenders == []


def test_package_imports_are_declared_at_module_scope() -> None:
    """Reject function-local and conditional imports in package source."""
    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "viper").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset != 0:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_builtin_output_names_have_one_definition() -> None:
    """Keep canonical stage names in viper.keys rather than the shared schema."""
    assert not any(
        hasattr(schema, name)
        for name in (
            "MODEL",
            "MODEL_INPUT",
            "PARAMETERS",
            "PARAMETERS_INPUT",
            "PREDICTIONS",
            "RESUME_STATE",
            "RESUME_STATE_INPUT",
        )
    )


def test_public_examples_use_direct_owner_module_imports() -> None:
    """Keep public examples concise without hiding symbol ownership."""
    readme = (ROOT / "README.md").read_text()
    assert "from viper.stages import" in readme
    assert "from viper.outputs import" in readme
    assert "@viper.stages." not in readme
    assert "viper.outputs.TrainOutputs" not in readme


def test_generated_workspace_uses_final_public_names(tmp_path: Path) -> None:
    """Generate examples with the same vocabulary users read in the docs."""
    repository.init_workspace(tmp_path)
    generated = "\n".join(path.read_text() for path in sorted(tmp_path.rglob("*.py")))
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
