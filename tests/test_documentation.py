"""Verify public documentation against the executable package."""

from __future__ import annotations

import ast
import importlib
import re
import tomllib

from tests._documentation import (
    CONTRACTS_WITH_COMPLETE_EXAMPLES,
    IMPLEMENTATION_CONTRACTS,
    MASTER_EXECUTION_CHECKLIST,
    ROOT,
    class_bases,
    class_fields,
    decoded_local_link,
    definitions,
    dotted_name,
    github_anchors,
    local_links,
    normalized,
    python_blocks,
)
from viper.api import OPERATIONS

PROTOCOL = ROOT / "docs/reference/protocol.md"

API_REFERENCE = ROOT / "docs/reference/api.md"

AUTOMATIC_INPUT_RESOLUTION = ROOT / "docs/development/automatic-input-resolution.md"

TRAINING_GUIDES = (
    ROOT / "README.md",
    API_REFERENCE,
    ROOT / "docs/tutorials/getting-started.md",
    ROOT / "docs/explanation/how-viper-works.md",
)

EVAL_VOCABULARY_CONTRACTS = (
    ROOT / "docs/development/unified-metric-drafting.md",
    AUTOMATIC_INPUT_RESOLUTION,
    ROOT / "docs/development/stage-reuse.md",
)

_COMPLETE_AUTHORING_EXAMPLE = re.compile(
    r"<!-- complete-authoring-example: start -->"
    r"(?P<body>.*?)"
    r"<!-- complete-authoring-example: end -->",
    re.DOTALL,
)

_CONTRACT_WORKED_EXAMPLE = re.compile(
    r"<!-- contract-worked-example: start -->"
    r"(?P<body>.*?)"
    r"<!-- contract-worked-example: end -->",
    re.DOTALL,
)

_PYTHON_FENCE = re.compile(r"```python\n(?P<body>.*?)\n```", re.DOTALL)

_TRACEABILITY_MODEL_FENCE = re.compile(
    r"```python contract-target\n(?P<body>.*?)\n```",
    re.DOTALL,
)

_PAIR_BLOCK_MANIFEST_FENCE = re.compile(
    r"```toml pair-block\n.*?\n```",
    re.DOTALL,
)

_CONTRACT_TARGET_MARKER = re.compile(r"<!-- contract-target: [^\n]+ -->")

_IMPLEMENTED_EXAMPLE_MODULES = {"viper._contract_traceability"}

COMPLETE_EXAMPLE_PUBLIC_CALLS = {
    "artifact",
    "at_least",
    "at_most",
    "benchmark",
    "build",
    "catalog",
    "download",
    "embed",
    "eval",
    "execution.benchmark",
    "execution.run",
    "execution.run_many",
    "expand",
    "experiment",
    "factor",
    "freeze",
    "http",
    "input",
    "measure",
    "metric",
    "min",
    "plan",
    "replicate",
    "run_artifact",
    "stage",
    "train",
    "variant",
}

COMPLETE_EXAMPLE_PUBLIC_IMPORTS = {
    "viper.artifacts": {"artifact"},
    "viper.authoring": {
        "download",
        "expand",
        "experiment",
        "factor",
        "freeze",
        "input",
        "plan",
        "replicate",
        "run_artifact",
        "stage",
        "variant",
    },
    "viper.benchmark": {"at_least", "at_most", "benchmark"},
    "viper.catalog": {"MeasurementQuery", "catalog"},
    "viper.http": {"HttpContext", "HttpResult", "http"},
    "viper.metrics": {"measure", "metric", "min"},
    "viper.stages": {"Context", "build", "embed", "eval", "train"},
}

TARGET_EVAL_IDENTIFIERS = {
    "Eval",
    "EvalId",
    "EvalParams",
    "EvalSpec",
    "EvalSpecDraft",
    "EvalVariantStageParams",
    "ResolvedEvalSpec",
}

TARGET_PROJ_IDENTIFIERS = {
    "min_proj_norm",
    "proj_a",
    "proj_b",
    "proj_bias",
    "proj_norm",
}

TARGET_ENV_IDENTIFIERS = {
    "EnvSecretRef",
    "EnvSpec",
    "GCEEnvSpec",
    "LocalEnvSpec",
    "ProcessStartupReceipt",
    "PythonEnvSpec",
    "ResolvedEnv",
    "ResolvedGCEEnv",
    "ResolvedLocalEnv",
    "observe_python_env",
    "resolve_env",
}

COMPLETE_EXAMPLE_COMMENT_TOPICS = {
    "Repository identity",
    "Freezing records each loader",
    "custom HTTP function sends the request",
    "download() declares a runner-owned stage",
    "Live metrics receive values",
    "measure() supplies concrete parameters",
    "input() declares bytes",
    "build stage turns source data",
    "input handles become two FutureInputRef records",
    "decorated function owns model computation",
    "run_artifact() selects immutable outputs",
    "model handle is a same-run edge",
    "Source, environment, and reproducibility records",
    "benchmark enters the plan",
    "experiment owns reusable factors",
    "plan selects one variant",
    "Freezing compiles Python drafts",
}

PUBLIC_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "examples").rglob("*.md")),
    ROOT / "tests/README.md",
)

PROTOCOL_MODULES = (
    "_schema.py",
    "parameters.py",
    "references.py",
    "artifacts.py",
    "inputs.py",
    "stages.py",
    "runtime.py",
    "resume.py",
    "metrics.py",
    "experiments.py",
    "runs.py",
    "benchmark.py",
    "http.py",
)

PROTOCOL_ALIASES = {
    "ArtifactSpec",
    "AttemptFailureCode",
    "AttemptPurpose",
    "AttemptStatus",
    "ComputeBackendContext",
    "ComputeSpec",
    "DataRole",
    "EnvironmentSpec",
    "GeneratorFamily",
    "GCEProvisioningRef",
    "HostContext",
    "HttpImplementationSpec",
    "InputRef",
    "MetricKind",
    "MetricMode",
    "ParameterizedStageSpec",
    "ResolvedArtifact",
    "ResolvedEnvironment",
    "ResolvedInputRef",
    "ResolvedSpec",
    "Spec",
    "StageResultSnapshot",
    "StartupVariable",
    "StorageModel",
    "StorageRef",
    "VariantStageParams",
}


def _complete_authoring_blocks() -> tuple[str, ...]:
    """Return the marked end-to-end authoring and execution blocks."""
    match = _COMPLETE_AUTHORING_EXAMPLE.search(AUTOMATIC_INPUT_RESOLUTION.read_text())
    assert match is not None
    blocks = python_blocks(match.group("body"))
    assert blocks
    return blocks


def _protocoldefinitions() -> tuple[dict[str, ast.ClassDef], dict[str, ast.AST]]:
    """Collect the classes and aliases shown in the formal protocol."""
    classes: dict[str, ast.ClassDef] = {}
    aliases: dict[str, ast.AST] = {}
    for block in python_blocks(PROTOCOL.read_text()):
        tree = ast.parse(block, filename=str(PROTOCOL))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in classes:
                    raise AssertionError(f"duplicate protocol class: {node.name}")
                classes[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    aliases[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    aliases[node.target.id] = node.value
    return classes, aliases


def test_protocol_class_fields_match_their_defining_modules() -> None:
    """Require every repeated protocol class to show exact current fields."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    source_classes, _ = definitions(source_paths)
    protocol_classes, _ = _protocoldefinitions()
    repeated = source_classes.keys() & protocol_classes.keys()

    assert len(repeated) >= 45
    mismatches = {
        name: (
            (class_bases(source_classes[name]), class_fields(source_classes[name])),
            (
                class_bases(protocol_classes[name]),
                class_fields(protocol_classes[name]),
            ),
        )
        for name in sorted(repeated)
        if (
            class_bases(source_classes[name]),
            class_fields(source_classes[name]),
        )
        != (
            class_bases(protocol_classes[name]),
            class_fields(protocol_classes[name]),
        )
    }
    assert mismatches == {}


def test_protocol_type_aliases_match_their_defining_modules() -> None:
    """Require claim-bearing protocol unions to match their source aliases."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    _, source_aliases = definitions(source_paths)
    _, protocol_aliases = _protocoldefinitions()

    assert PROTOCOL_ALIASES <= source_aliases.keys()
    assert PROTOCOL_ALIASES <= protocol_aliases.keys()
    mismatches = {
        name: (normalized(source_aliases[name]), normalized(protocol_aliases[name]))
        for name in sorted(PROTOCOL_ALIASES)
        if normalized(source_aliases[name]) != normalized(protocol_aliases[name])
    }
    assert mismatches == {}


def test_protocol_uses_renderer_safe_math_fences() -> None:
    """Keep multiline protocol equations inside balanced GitHub math fences."""
    text = PROTOCOL.read_text()
    open_fence: str | None = None
    math_fences = 0
    for line in text.splitlines():
        if not line.startswith("```"):
            continue
        if open_fence is None:
            open_fence = line
            math_fences += line == "```math"
        else:
            assert line == "```"
            open_fence = None

    assert not re.search(r"^\$\$$", text, flags=re.MULTILINE)
    assert math_fences > 0
    assert open_fence is None


def test_public_python_examples_are_syntactically_valid() -> None:
    """Require every published Python fence to parse with supported syntax."""
    for document in PUBLIC_MARKDOWN:
        for block in python_blocks(document.read_text()):
            ast.parse(block, filename=str(document), feature_version=(3, 11))


def test_complete_authoring_example_covers_the_public_workflow() -> None:
    """Require every public constructor in the complete workflow example."""
    trees = tuple(
        ast.parse(block, filename=str(AUTOMATIC_INPUT_RESOLUTION))
        for block in _complete_authoring_blocks()
    )
    calls = {
        name
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := dotted_name(node.func)) is not None
    }

    assert COMPLETE_EXAMPLE_PUBLIC_CALLS - calls == set()

    imported_names = {
        node.module: {alias.name for alias in node.names}
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        if node.module in COMPLETE_EXAMPLE_PUBLIC_IMPORTS
    }
    for module, names in COMPLETE_EXAMPLE_PUBLIC_IMPORTS.items():
        assert names <= imported_names[module]


def test_target_contracts_use_env_identifiers() -> None:
    """Keep normative contract prose on `env` names before the rename executes."""
    full_contract_text = "\n".join(
        path.read_text() for path in IMPLEMENTATION_CONTRACTS
    )
    contract_text = "\n".join(
        _CONTRACT_TARGET_MARKER.sub(
            "",
            _PAIR_BLOCK_MANIFEST_FENCE.sub(
                "",
                _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()),
            ),
        )
        for path in IMPLEMENTATION_CONTRACTS
    )
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    target_identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", contract_text))

    assert TARGET_ENV_IDENTIFIERS - target_identifiers == set()
    assert 'kind: Literal["env"] = "env"' in full_contract_text
    assert 'kind: Literal["environment"] = "environment"' not in contract_text
    assert all(name in checklist for name in TARGET_ENV_IDENTIFIERS)


def test_target_contracts_use_eval_identifiers() -> None:
    """Keep the evaluation-stage contract on the `Eval` vocabulary."""
    full_contract_text = "\n".join(
        path.read_text() for path in EVAL_VOCABULARY_CONTRACTS
    )
    contract_text = "\n".join(
        _CONTRACT_TARGET_MARKER.sub(
            "",
            _PAIR_BLOCK_MANIFEST_FENCE.sub(
                "",
                _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()),
            ),
        )
        for path in EVAL_VOCABULARY_CONTRACTS
    )
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    target_identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", contract_text))

    assert TARGET_EVAL_IDENTIFIERS - target_identifiers == set()
    assert 'kind: Literal["eval"] = "eval"' in full_contract_text
    assert 'kind: Literal["evaluate"] = "evaluate"' not in contract_text
    assert 'DataRole = Literal["training", "validation", "eval", "benchmark"]' in (
        full_contract_text
    )
    assert 'data_role="evaluation"' not in contract_text
    assert "artifacts/evaluations/" not in contract_text
    assert "eval_id" in target_identifiers
    assert "evaluation_id" not in target_identifiers
    assert all(name in checklist for name in TARGET_EVAL_IDENTIFIERS)


def test_complete_authoring_example_uses_env_keywords() -> None:
    """Require the full example to use the target env API and fields."""
    trees = tuple(
        ast.parse(block, filename=str(AUTOMATIC_INPUT_RESOLUTION))
        for block in _complete_authoring_blocks()
    )
    calls = tuple(
        node for tree in trees for node in ast.walk(tree) if isinstance(node, ast.Call)
    )
    names = {name for node in calls if (name := dotted_name(node.func)) is not None}
    plan_calls = tuple(node for node in calls if dotted_name(node.func) == "plan")

    assert {"LocalEnvSpec", "observe_python_env"} <= names
    assert names & {"LocalEnvironmentSpec", "observe_python_environment"} == set()
    assert plan_calls
    assert all(
        "env" in {keyword.arg for keyword in node.keywords}
        and "environment" not in {keyword.arg for keyword in node.keywords}
        for node in plan_calls
    )


def test_complete_authoring_example_uses_proj_identifiers() -> None:
    """Keep projection-related Python names on the `proj` abbreviation."""
    trees = tuple(
        ast.parse(block, filename=str(AUTOMATIC_INPUT_RESOLUTION))
        for block in _complete_authoring_blocks()
    )
    identifiers = {
        name
        for tree in trees
        for node in ast.walk(tree)
        for name in (
            node.id if isinstance(node, ast.Name) else None,
            node.attr if isinstance(node, ast.Attribute) else None,
        )
        if name is not None
    }

    assert TARGET_PROJ_IDENTIFIERS <= identifiers
    assert {name for name in identifiers if "projection" in name.lower()} == set()


def test_complete_authoring_parameter_models_are_substantial_and_used() -> None:
    """Require five used fields in every project-owned parameter model."""
    trees = tuple(
        ast.parse(block, filename=str(AUTOMATIC_INPUT_RESOLUTION))
        for block in _complete_authoring_blocks()
    )
    parameter_classes = {
        node.name: tuple(
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        )
        for tree in trees
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        if any(
            (base_name := dotted_name(base)) is not None
            and base_name.startswith("params.")
            for base in node.bases
        )
    }
    parameter_accesses = {
        node.attr
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        if dotted_name(node.value) in {"params", "context.params"}
    }

    assert parameter_classes
    assert {
        name: fields for name, fields in parameter_classes.items() if len(fields) < 5
    } == {}
    assert {
        name: sorted(set(fields) - parameter_accesses)
        for name, fields in parameter_classes.items()
        if set(fields) - parameter_accesses
    } == {}


def test_complete_authoring_example_comments_explain_each_handoff() -> None:
    """Keep comments beside the public values and lifecycle boundaries."""
    comments = "\n".join(
        line.strip().removeprefix("#").strip()
        for block in _complete_authoring_blocks()
        for line in block.splitlines()
        if line.lstrip().startswith("#")
    )

    assert len(comments.splitlines()) >= 30
    assert {
        topic for topic in COMPLETE_EXAMPLE_COMMENT_TOPICS if topic not in comments
    } == set()


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


def _worked_example_runtime_failures(
    contract_name: str,
    example: str,
) -> list[str]:
    """Return every stale live import or model field in one worked example."""
    failures: list[str] = []
    blocks = tuple(match.group("body") for match in _PYTHON_FENCE.finditer(example))
    tree = ast.parse("\n\n".join(blocks), filename=contract_name)
    imported: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.module not in _IMPLEMENTED_EXAMPLE_MODULES:
            continue
        try:
            module = importlib.import_module(node.module)
        except ModuleNotFoundError:
            continue
        for name in node.names:
            if not hasattr(module, name.name):
                failures.append(f"{contract_name}: missing {node.module}.{name.name}")
                continue
            imported[name.asname or name.name] = getattr(module, name.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        model = imported.get(node.func.id)
        fields = getattr(model, "model_fields", None)
        if fields is None:
            continue
        unknown = sorted(
            keyword.arg
            for keyword in node.keywords
            if keyword.arg is not None and keyword.arg not in fields
        )
        if unknown:
            failures.append(
                f"{contract_name}: {node.func.id} has unknown fields {unknown}"
            )
    return failures


def test_worked_examples_resolve_live_imports_and_constructor_fields() -> None:
    """Reject stale runtime names and constructor fields in worked examples."""
    failures: list[str] = []
    for contract in CONTRACTS_WITH_COMPLETE_EXAMPLES:
        example_match = _CONTRACT_WORKED_EXAMPLE.search(
            contract.read_text(encoding="utf-8")
        )
        assert example_match is not None, contract.name
        failures.extend(
            _worked_example_runtime_failures(
                contract.name,
                example_match.group("body"),
            )
        )

    assert failures == []


def test_worked_example_runtime_check_rejects_unknown_models_and_fields() -> None:
    """Reject an unavailable model and a field outside the live schema."""
    example = """```python
from viper._contract_traceability import (
    ContractRequirement,
    UnknownRule,
)

ContractRequirement(
    requirement_id="CRT-01",
    contract="docs/development/example.md",
    unknown_field=0,
)
```"""

    assert _worked_example_runtime_failures("invalid-model.md", example) == [
        "invalid-model.md: missing viper._contract_traceability.UnknownRule",
        "invalid-model.md: ContractRequirement has unknown fields ['unknown_field']",
    ]


def test_api_operation_table_matches_python_and_cli_surfaces() -> None:
    """Keep every typed API operation beside its exact CLI command."""
    rows = re.findall(
        r"^\| `([a-z_]+)` \| `[^`]+` \| `[^`]+` \| `([a-z-]+)` \|$",
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
    assert tuple(documented) == OPERATIONS
    assert documented == expected


def test_changelog_starts_with_the_package_version() -> None:
    """Keep the first changelog release aligned with package metadata."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    first_release = re.search(r"^## ([^ ]+)", (ROOT / "CHANGELOG.md").read_text(), re.M)

    assert first_release is not None
    assert first_release.group(1) == package_version


def test_explanation_names_the_current_release() -> None:
    """Keep the explanatory guide linked to the package's current release report."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    explanation = (ROOT / "docs/explanation/how-viper-works.md").read_text()

    assert f"VIPER `{package_version}` is available from PyPI." in explanation
    assert f"[release report](../releases/{package_version}.md)" in explanation


def test_public_examples_distinguish_weights_from_the_artifact_key() -> None:
    """Keep tutorial vocabulary clear without changing the protocol artifact name."""
    public_text = "\n".join(
        _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()) for path in PUBLIC_MARKDOWN
    )

    assert 'weights_path = context.artifacts["parameters"]' in public_text
    assert "parameters_path" not in public_text


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
        assert "context.artifacts" in text
        assert all(call not in text for call in undefined_calls)


def test_public_guides_import_modules_owned_by_the_api_reference() -> None:
    """Require user-facing examples to import only documented public modules."""
    allowed_modules = set(
        re.findall(
            r"^\| `(viper\.[a-z_]+)` \|",
            API_REFERENCE.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )
    public_guides = (
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        *sorted((ROOT / "docs/reference").glob("*.md")),
        *sorted((ROOT / "docs/tutorials").rglob("*.md")),
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
    """Publish the Phase 11 workflow without retired authoring concepts."""
    documents = (
        ROOT / "README.md",
        ROOT / "docs/tutorials/getting-started.md",
        ROOT / "docs/explanation/how-viper-works.md",
        ROOT / "docs/reference/api.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    required = {
        "viper.authoring.plan",
        "viper.execution.run",
        "viper.execution.benchmark",
        "viper.execution.restore",
    }
    retired = {
        "freeze-run",
        "freeze_run_plan",
        "DownloadContext",
        "download_stage",
        "HttpSource",
    }

    assert required <= {name for name in required if name in text}
    assert retired.isdisjoint({name for name in retired if name in text})
