"""Verify public documentation against the executable package."""

from __future__ import annotations

import ast
import json
import re
import tomllib

import pytest

from tests._documentation import (
    ROOT,
    decoded_local_link,
    github_anchors,
    local_links,
    python_blocks,
)
from viper.api import OPERATIONS
from viper.cli import build_parser

PROTOCOL = ROOT / "docs/reference/protocol.md"

API_REFERENCE = ROOT / "docs/reference/api.md"

TRAINING_GUIDES = (
    ROOT / "README.md",
    API_REFERENCE,
    ROOT / "docs/tutorials/getting-started.md",
    ROOT / "docs/explanation/how-viper-works.md",
)

_TRACEABILITY_MODEL_FENCE = re.compile(
    r"```python contract-target\n(?P<body>.*?)\n```",
    re.DOTALL,
)

PUBLIC_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "examples").rglob("*.md")),
    ROOT / "tests/README.md",
)


def test_public_authoring_config_gate_precedes_documentation_migration() -> None:
    """Keep PAC-01 executable before PAC-07 owns the documentation migration."""
    checklist = json.loads(
        (
            ROOT / "docs/development/v0.1.0a3-public-authoring-contract.checklist.json"
        ).read_text(encoding="utf-8")
    )
    requirements = {item["requirement_id"]: item for item in checklist["requirements"]}

    assert "documentation" not in requirements["PAC-01"]["gate"]["target"]
    assert "documentation" in requirements["PAC-07"]["gate"]["target"]


def test_protocol_uses_live_schemas_instead_of_repeated_source_models() -> None:
    """Keep exact protocol fields owned by the installed schema registry."""
    text = PROTOCOL.read_text(encoding="utf-8")

    assert "viper --json schema RunSpec" in text
    assert "viper --json capabilities" in text
    assert not python_blocks(text)


def test_protocol_reference_does_not_repeat_the_walkthrough_or_guarantees() -> None:
    """Keep the protocol page focused on record lookup and distinctions."""
    text = PROTOCOL.read_text(encoding="utf-8")

    assert "## Record map" in text
    assert "## Terms that mark different lifecycle states" in text
    assert "| Record | Purpose |" in text
    assert "| Record | Scope | Purpose |" not in text
    assert "| `ResolvedSpec` | Records the artifacts" in text
    assert "## What happens during a run" not in text
    assert "## Core acceptance relation" not in text


def test_public_python_examples_are_syntactically_valid() -> None:
    """Require every published Python fence to parse with supported syntax."""
    for document in PUBLIC_MARKDOWN:
        for block in python_blocks(document.read_text()):
            ast.parse(block, filename=str(document), feature_version=(3, 11))


def test_public_markdown_links_resolve() -> None:
    """Require every repository-relative documentation link to resolve."""
    failures: list[str] = []
    for document in PUBLIC_MARKDOWN:
        text = document.read_text()
        for raw_target in local_links(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("https://", "http://", "mailto:")):
                continue

            path_text, anchor = decoded_local_link(target)
            linked_path = document if not path_text else document.parent / path_text
            linked_path = linked_path.resolve()
            if not linked_path.exists():
                failures.append(
                    f"{document.relative_to(ROOT)} -> {target}: missing file"
                )
                continue
            if anchor is not None and linked_path.suffix == ".md":
                anchors = github_anchors(linked_path.read_text())
                if anchor not in anchors:
                    failures.append(
                        f"{document.relative_to(ROOT)} -> {target}: missing anchor"
                    )

    assert failures == []


def test_api_operation_table_matches_python_and_cli_surfaces() -> None:
    """Keep every typed API operation beside its exact CLI command."""
    rows = re.findall(
        r"^\| `([a-z_]+)` \| `[^`]+` \| `[^`]+` \| `([a-z_ -]+)` \|$",
        API_REFERENCE.read_text(),
        flags=re.MULTILINE,
    )
    documented = dict(rows)

    cli_tree = ast.parse((ROOT / "src/viper/cli.py").read_text())
    cli_mapping: dict[str, str] | None = None
    for node in ast.walk(cli_tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "mapping":
            continue
        if isinstance(node.value, ast.Dict):
            cli_mapping = {
                ast.literal_eval(key): ast.literal_eval(value)
                for key, value in zip(node.value.keys, node.value.values, strict=True)
                if key is not None
            }
            break

    assert cli_mapping is not None
    expected = {operation: command for command, operation in cli_mapping.items()}
    for operation in expected:
        if operation == "knowledge_refresh":
            expected[operation] = "knowledge refresh"
        elif operation.startswith("publish_"):
            expected[operation] = f"knowledge publish {operation}"
        elif expected[operation].startswith("search-") and operation not in {
            "search_runs",
            "search_artifacts",
            "search_measurements",
            "search_benchmarks",
        }:
            expected[operation] = f"knowledge search {operation}"
    assert tuple(documented) == OPERATIONS
    assert documented == expected

    parser = build_parser()
    for command in documented.values():
        with pytest.raises(SystemExit) as exited:
            parser.parse_args([*command.split(), "--help"])
        assert exited.value.code == 0, command


def test_changelog_names_the_package_version_after_unreleased() -> None:
    """Keep active work above the current released package entry."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    headings = re.findall(r"^## ([^\n]+)", (ROOT / "CHANGELOG.md").read_text(), re.M)

    assert headings[0] == "Unreleased"
    assert headings[1].startswith(package_version)


def test_explanation_names_the_current_release() -> None:
    """Keep the explanatory guide linked to the package's current release report."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    explanation = (ROOT / "docs/explanation/how-viper-works.md").read_text()

    assert f"VIPER `{package_version}` is the current release candidate." in explanation
    assert f"[release report](../releases/{package_version}.md)" in explanation


def test_public_examples_distinguish_weights_from_the_artifact_key() -> None:
    """Keep the example's model path tied to its declared artifact key."""
    public_text = "\n".join(
        _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()) for path in PUBLIC_MARKDOWN
    )

    assert 'model = context.outputs["model"]' in public_text
    assert 'context.outputs["weights"]' not in public_text


def test_training_examples_name_the_project_owned_training_function() -> None:
    """Keep project computation inside one decorated project stage."""
    undefined_calls = (
        "run_training(",
        "model = fit(",
        "update_model(",
        "save_weights(",
    )

    for path in TRAINING_GUIDES:
        text = path.read_text()
        assert "@train(" in text
        assert "context.outputs" in text
        assert all(call not in text for call in undefined_calls)


def test_public_guides_import_modules_owned_by_the_api_reference() -> None:
    """Require user-facing examples to import only documented public modules."""
    allowed_modules = set(
        re.findall(
            r"^\| `(viper\.[a-z_.]+)` \|",
            API_REFERENCE.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )
    public_guides = (
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        *sorted((ROOT / "docs/reference").glob("*.md")),
        *sorted((ROOT / "docs/tutorials").rglob("*.md")),
        *sorted((ROOT / "docs/how-to").rglob("*.md")),
        *sorted((ROOT / "docs/explanation").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.md")),
        ROOT / "tests/README.md",
    )

    imported_modules: set[str] = set()
    for document in public_guides:
        for block in python_blocks(document.read_text(encoding="utf-8")):
            tree = ast.parse(block, filename=str(document))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module is not None:
                    module = node.module
                    if module.startswith("viper."):
                        imported_modules.add(".".join(module.split(".")[:2]))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("viper."):
                            imported_modules.add(".".join(alias.name.split(".")[:2]))

    assert imported_modules <= allowed_modules


def test_current_docs_import_public_functions_from_defining_modules() -> None:
    """Reject package-root names owned by a public submodule."""
    current_guides = tuple(
        path
        for path in PUBLIC_MARKDOWN
        if path.name not in {"CHANGELOG.md", "0.1.0a1.md", "system-impact-compiler.md"}
    )
    text = "\n".join(path.read_text() for path in current_guides)
    rooted_names = (
        "Artifact",
        "DownloadSpecDraft",
        "MeasurementQuery",
        "MetricContext",
        "StatefulMetric",
        "artifact",
        "at_least",
        "at_most",
        "build",
        "download",
        "embed",
        "eval",
        "experiment",
        "expand",
        "factor",
        "freeze",
        "input",
        "max",
        "measure",
        "metric",
        "min",
        "plan",
        "replicate",
        "run_artifact",
        "stage",
        "train",
        "variant",
    )

    for name in rooted_names:
        assert re.search(rf"\bviper\.{name}\b", text) is None
    for name in ("benchmark", "catalog", "http", "knowledge"):
        assert re.search(rf"\bviper\.{name}\(", text) is None
        assert re.search(rf"@viper\.{name}(?!\.)\b", text) is None


def test_public_workflow_uses_target_api() -> None:
    """Document execution from Python drafts and saved plans with current APIs."""
    documents = (
        ROOT / "README.md",
        ROOT / "docs/tutorials/getting-started.md",
        ROOT / "docs/explanation/how-viper-works.md",
        ROOT / "docs/reference/api.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    required = {
        "viper.authoring.plan",
        "freeze_run_plan",
        "viper.execution.run",
        "viper.execution.benchmark",
        "viper.execution.restore",
    }
    retired = {
        "DownloadContext",
        "download_stage",
        "HttpSource",
    }

    assert required <= {name for name in required if name in text}
    assert retired.isdisjoint({name for name in retired if name in text})


def test_documentation_navigation_separates_reader_and_internal_routes() -> None:
    """Keep one complete public path and one explicit internal doorway."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    home = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    tutorial = (ROOT / "docs/tutorials/getting-started.md").read_text(encoding="utf-8")
    explanation = (ROOT / "docs/explanation/how-viper-works.md").read_text(
        encoding="utf-8"
    )

    assert "[documentation home](docs/README.md)" in readme
    for heading in (
        "## Tutorial",
        "## How-to guides",
        "## Explanation",
        "## Reference",
        "## Contributing and internal engineering",
    ):
        assert home.count(heading) == 1

    required_routes = (
        "tutorials/getting-started.md",
        "how-to/inputs.md",
        "how-to/metrics-and-benchmarks.md",
        "how-to/variants-and-replicates.md",
        "how-to/retry-restore-compare.md",
        "how-to/catalog-knowledge-mcp.md",
        "how-to/troubleshooting.md",
        "explanation/how-viper-works.md",
        "explanation/guarantees.md",
        "reference/README.md",
        "internal/README.md",
    )
    assert all(home.count(route) == 1 for route in required_routes)

    internal_contracts = (
        "automatic-input-resolution.md",
        "remote-storage.md",
        "system-impact-compiler.md",
        "unified-metric-drafting.md",
    )
    assert all(contract not in home for contract in internal_contracts)

    workflow = tutorial + explanation
    assert workflow.count("../../examples/cpu_quickstart.py") >= 2
    assert "execution.run()" in workflow
    assert "viper.parameters" not in workflow
    assert "viper.api.run" not in workflow
