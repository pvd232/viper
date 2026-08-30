"""Keep the published documentation aligned with the executable package."""

from __future__ import annotations

import ast
import hashlib
import re
import tomllib
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from viper.api import OPERATIONS

ROOT = Path(__file__).parents[1]
PROTOCOL = ROOT / "docs/reference/protocol.md"
API_REFERENCE = ROOT / "docs/reference/api.md"
AUTOMATIC_INPUT_RESOLUTION = ROOT / "docs/development/automatic-input-resolution.md"
TRAINING_GUIDES = (
    ROOT / "README.md",
    API_REFERENCE,
    ROOT / "docs/tutorials/getting-started.md",
    ROOT / "docs/explanation/how-viper-works.md",
)

MASTER_EXECUTION_CHECKLIST = ROOT / "docs/development/master-execution-checklist.md"
IMPLEMENTATION_CONTRACTS = (
    ROOT / "docs/development/contract-requirement-traceability.md",
    ROOT / "docs/development/project-data-root.md",
    ROOT / "docs/development/system-impact-graph.md",
    ROOT / "docs/development/download-retrieval-artifacts.md",
    ROOT / "docs/development/external-input-roots.md",
    ROOT / "docs/development/unified-metric-drafting.md",
    AUTOMATIC_INPUT_RESOLUTION,
    ROOT / "docs/development/frozen-plan-git-identity.md",
    ROOT / "docs/development/remote-storage.md",
    ROOT / "docs/development/experiment-expansion.md",
    ROOT / "docs/development/provenance-catalog-mcp.md",
    ROOT / "docs/development/stage-reuse.md",
    ROOT / "docs/development/experiment-knowledge-primitives.md",
)

PHASE_ZERO_CONTRACTS = (
    ROOT / "docs/development/contract-requirement-traceability.md",
    ROOT / "docs/development/project-data-root.md",
    ROOT / "docs/development/system-impact-graph.md",
)

_CONTRACT_REQUIREMENT = re.compile(
    r"^\| (?P<label>[A-Z]{3}-\d{2}) "
    r"<!-- contract-requirement: (?P<requirement>[A-Z]{3}-\d{2}) "
    r"phase=(?P<phase>\d+) test=(?P<test>tests/[a-z0-9_/]+\.py) -->",
    re.MULTILINE,
)
_CHECKLIST_MAPPING = re.compile(
    r"<!-- (?P<role>implements|verifies): (?P<requirements>[A-Z0-9, -]+) -->"
)
_CONTRACT_BASELINE = re.compile(
    r"<!-- contract-baseline: (?P<name>[a-z0-9-]+\.md) "
    r"sha256=(?P<sha256>[0-9a-f]{64}) -->"
)
_PHASE_HEADING = re.compile(r"^## \d+\. Phase (?P<phase>\d+)\b.*$", re.MULTILINE)
_PHASE_CAPABILITY = re.compile(
    r"<!-- phase-(?P<role>produces|consumes): "
    r"(?P<symbols>[A-Za-z0-9_., ]+) -->"
)
_CHECKBOX_BLOCK = re.compile(
    r"^- \[ \] .*?(?=^- \[ \] |^### |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_ORDERED_CAPABILITIES = {
    "KnowledgeVector",
    "RetrievalJudgment",
    "StageReuseKey",
    "viper.catalog",
    "viper.execution.run_many",
    "viper.expand",
}
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
_CONTRACT_TRACE_FENCE = re.compile(
    r"```toml contract-trace\n(?P<body>.*?)\n```",
    re.DOTALL,
)
_PYTHON_FENCE = re.compile(r"```python\n(?P<body>.*?)\n```", re.DOTALL)
_MERMAID_FENCE = re.compile(r"```mermaid\n(?P<body>.*?)\n```", re.DOTALL)
_MERMAID_EDGE = re.compile(
    r"^\s*(?P<source>[A-Za-z][A-Za-z0-9_]*)\s+-->"
    r'(?:\|"[^"]+"\|)?\s*(?P<target>[A-Za-z][A-Za-z0-9_]*)\s*$'
)

COMPLETE_EXAMPLE_PUBLIC_CALLS = {
    "viper.at_least",
    "viper.at_most",
    "viper.benchmark",
    "viper.build",
    "viper.download",
    "viper.embed",
    "viper.eval",
    "viper.execution.benchmark",
    "viper.execution.run",
    "viper.execution.run_many",
    "viper.expand",
    "viper.experiment",
    "viper.factor",
    "viper.artifact",
    "viper.input",
    "viper.freeze",
    "viper.http",
    "viper.measure",
    "viper.metric",
    "viper.min",
    "viper.plan",
    "viper.replicate",
    "viper.run_artifact",
    "viper.stage",
    "viper.train",
    "viper.variant",
    "viper.catalog",
}

RETIRED_COMPLETE_EXAMPLE_PUBLIC_CALLS = {
    "viper.file_artifact",
    "viper.file_input",
    "viper.http_transport",
    "viper.transport",
    "viper.evaluate",
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

RETIRED_TARGET_EVAL_IDENTIFIERS = {
    "Evaluate",
    "EvaluateParams",
    "EvaluateSpec",
    "EvaluateSpecDraft",
    "EvaluateVariantStageParams",
    "EvaluationId",
    "ResolvedEvaluateSpec",
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

RETIRED_TARGET_ENV_IDENTIFIERS = {
    "EnvironmentSecretRef",
    "EnvironmentSpec",
    "GCEEnvironmentSpec",
    "LocalEnvironmentSpec",
    "PythonEnvironmentSpec",
    "ResolvedEnvironment",
    "ResolvedGCEEnvironment",
    "ResolvedLocalEnvironment",
    "observe_python_environment",
    "resolve_environment",
}

COMPLETE_EXAMPLE_COMMENT_TOPICS = {
    "Repository identity",
    "Freezing records each loader",
    "custom HTTP function sends the request",
    "viper.download() declares a runner-owned stage",
    "Live metrics receive values",
    "viper.measure() supplies concrete parameters",
    "viper.input() declares bytes",
    "build stage turns source data",
    "input handles become two FutureInputRef records",
    "decorated function owns model computation",
    "viper.run_artifact() selects immutable outputs",
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
    "HttpTransportSpec",
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


def _python_blocks(markdown: str) -> tuple[str, ...]:
    """Return every complete Python fence from one Markdown document."""
    return tuple(re.findall(r"```python\n(.*?)\n```", markdown, flags=re.DOTALL))


def _dotted_name(node: ast.AST) -> str | None:
    """Return one dotted Python name without evaluating it."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def _complete_authoring_blocks() -> tuple[str, ...]:
    """Return the marked end-to-end authoring and execution blocks."""
    match = _COMPLETE_AUTHORING_EXAMPLE.search(AUTOMATIC_INPUT_RESOLUTION.read_text())
    assert match is not None
    blocks = _python_blocks(match.group("body"))
    assert blocks
    return blocks


def _normalized(node: ast.AST | None) -> str | None:
    """Render one declaration while ignoring qualified package prefixes."""
    if node is None:
        return None
    return ast.unparse(node).replace("viper.", "")


def _class_fields(node: ast.ClassDef) -> tuple[tuple[str, str | None, str | None], ...]:
    """Describe fields declared directly by one class."""
    fields = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        fields.append(
            (
                statement.target.id,
                _normalized(statement.annotation),
                _normalized(statement.value),
            )
        )
    return tuple(fields)


def _class_bases(node: ast.ClassDef) -> tuple[str | None, ...]:
    """Describe the declared bases of one class."""
    return tuple(_normalized(base) for base in node.bases)


def _class_methods(
    node: ast.ClassDef,
) -> tuple[tuple[str, str, str | None, tuple[str, ...]], ...]:
    """Describe methods declared directly by one contract class."""
    return tuple(
        (
            statement.name,
            ast.unparse(statement.args).replace("viper.", ""),
            _normalized(statement.returns),
            tuple(
                ast.unparse(decorator).replace("viper.", "")
                for decorator in statement.decorator_list
            ),
        )
        for statement in node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _definitions(
    paths: tuple[Path, ...],
) -> tuple[dict[str, ast.ClassDef], dict[str, ast.AST]]:
    """Collect top-level classes and type aliases from Python source files."""
    classes: dict[str, ast.ClassDef] = {}
    aliases: dict[str, ast.AST] = {}
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    aliases[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    aliases[node.target.id] = node.value
    return classes, aliases


def _protocol_definitions() -> tuple[dict[str, ast.ClassDef], dict[str, ast.AST]]:
    """Collect the classes and aliases shown in the formal protocol."""
    classes: dict[str, ast.ClassDef] = {}
    aliases: dict[str, ast.AST] = {}
    for block in _python_blocks(PROTOCOL.read_text()):
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


def _contract_class_definitions() -> dict[str, list[tuple[Path, ast.ClassDef]]]:
    """Collect every top-level class shown by the active contracts."""
    classes: dict[str, list[tuple[Path, ast.ClassDef]]] = {}
    for contract in IMPLEMENTATION_CONTRACTS:
        for block in _python_blocks(contract.read_text()):
            tree = ast.parse(block, filename=str(contract))
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    classes.setdefault(node.name, []).append((contract, node))
    return classes


def _github_anchors(markdown: str) -> set[str]:
    """Derive the GitHub-style anchor for every Markdown heading."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE):
        plain = re.sub(r"<[^>]+>", "", heading)
        plain = plain.replace("`", "").strip().lower()
        slug = re.sub(r"[^\w\- ]", "", plain, flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", slug)
        occurrence = counts.get(slug, 0)
        counts[slug] = occurrence + 1
        anchors.add(slug if occurrence == 0 else f"{slug}-{occurrence}")
    return anchors


def _local_links(markdown: str) -> tuple[str, ...]:
    """Return local Markdown link targets while excluding image sources."""
    return tuple(re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", markdown))


def test_protocol_class_fields_match_their_defining_modules() -> None:
    """Require every repeated protocol class to show exact current fields."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    source_classes, _ = _definitions(source_paths)
    protocol_classes, _ = _protocol_definitions()
    repeated = source_classes.keys() & protocol_classes.keys()

    assert len(repeated) >= 45
    mismatches = {
        name: (
            (_class_bases(source_classes[name]), _class_fields(source_classes[name])),
            (
                _class_bases(protocol_classes[name]),
                _class_fields(protocol_classes[name]),
            ),
        )
        for name in sorted(repeated)
        if (
            _class_bases(source_classes[name]),
            _class_fields(source_classes[name]),
        )
        != (
            _class_bases(protocol_classes[name]),
            _class_fields(protocol_classes[name]),
        )
    }
    assert mismatches == {}


def test_protocol_type_aliases_match_their_defining_modules() -> None:
    """Require claim-bearing protocol unions to match their source aliases."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    _, source_aliases = _definitions(source_paths)
    _, protocol_aliases = _protocol_definitions()

    assert PROTOCOL_ALIASES <= source_aliases.keys()
    assert PROTOCOL_ALIASES <= protocol_aliases.keys()
    mismatches = {
        name: (_normalized(source_aliases[name]), _normalized(protocol_aliases[name]))
        for name in sorted(PROTOCOL_ALIASES)
        if _normalized(source_aliases[name]) != _normalized(protocol_aliases[name])
    }
    assert mismatches == {}


def test_repeated_contract_classes_have_identical_declarations() -> None:
    """Reject two active contracts that assign different fields to one class."""
    definitions = _contract_class_definitions()
    repeated = {name: values for name, values in definitions.items() if len(values) > 1}

    assert len(repeated) >= 25
    mismatches = {}
    for name, values in sorted(repeated.items()):
        declarations = {
            (_class_bases(node), _class_fields(node), _class_methods(node))
            for _, node in values
        }
        if len(declarations) > 1:
            mismatches[name] = {
                path.name: (
                    _class_bases(node),
                    _class_fields(node),
                    _class_methods(node),
                )
                for path, node in values
            }

    assert mismatches == {}


def test_catalog_contract_exposes_every_promised_query_field() -> None:
    """Bind catalog questions to exact typed filters and result methods."""
    contract = ROOT / "docs/development/provenance-catalog-mcp.md"
    classes = {
        name: next(node for path, node in values if path == contract)
        for name, values in _contract_class_definitions().items()
        if any(path == contract for path, _ in values)
    }
    expected_fields = {
        "RunQuery": {
            "experiment_id",
            "variant_ids",
            "replicate_ids",
            "statuses",
            "source_commit",
            "env_sha256",
            "reproducibility_sha256",
            "benchmark_id",
            "input_sha256",
            "artifact_sha256",
            "limit",
            "cursor",
        },
        "ArtifactQuery": {
            "experiment_id",
            "variant_ids",
            "stage_ids",
            "artifact_names",
            "data_roles",
            "sha256",
            "source_commit",
            "limit",
            "cursor",
        },
        "MeasurementQuery": {
            "experiment_id",
            "variant_ids",
            "stage_ids",
            "metric_ids",
            "input_sha256",
            "env_sha256",
            "minimum",
            "maximum",
            "origins",
            "limit",
            "cursor",
        },
        "BenchmarkQuery": {
            "experiment_id",
            "variant_ids",
            "benchmark_ids",
            "statuses",
            "metric_ids",
            "source_commit",
            "env_sha256",
            "input_sha256",
            "artifact_sha256",
            "limit",
            "cursor",
        },
    }

    assert {
        name: {field for field, _, _ in _class_fields(classes[name])}
        for name in expected_fields
    } == expected_fields

    catalog_methods = {
        node.name
        for node in classes["Catalog"].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "refresh",
        "runs",
        "artifacts",
        "measurements",
        "benchmarks",
        "lineage",
    } <= catalog_methods

    text = contract.read_text()
    assert "search_benchmarks" in text
    assert "catalog_refresh` belongs to execution access" in text


def test_knowledge_contract_exposes_exact_queries_and_tool_sets() -> None:
    """Bind scientific searches and agent tools to exact public models."""
    contract = ROOT / "docs/development/experiment-knowledge-primitives.md"
    classes = {
        name: next(node for path, node in values if path == contract)
        for name, values in _contract_class_definitions().items()
        if any(path == contract for path, _ in values)
    }
    expected_fields = {
        "PrimitiveQuery": {
            "ontology_id",
            "ontology_versions",
            "dimensions",
            "primitive_ids",
            "labels",
            "limit",
            "cursor",
        },
        "AssignmentQuery": {
            "run",
            "stage_ids",
            "origins",
            "primitive_ids",
            "decisions",
            "effective_only",
            "limit",
            "cursor",
        },
        "ModulationQuery": {
            "baseline_runs",
            "candidate_runs",
            "dimensions",
            "primitive_ids",
            "context_sha256",
            "limit",
            "cursor",
        },
        "EffectQuery": {
            "metric_ids",
            "directions",
            "primitive_ids",
            "context_sha256",
            "minimum_improvement",
            "maximum_improvement",
            "limit",
            "cursor",
        },
        "ImpactQuery": {
            "metric_ids",
            "impacts",
            "policy_ids",
            "context_sha256",
            "limit",
            "cursor",
        },
        "DiagnosticQuery": {
            "runs",
            "stage_ids",
            "metric_ids",
            "limit",
            "cursor",
        },
        "AssertionQuery": {
            "kinds",
            "statuses",
            "evidence_kinds",
            "primitive_ids",
            "limit",
            "cursor",
        },
        "RetrievalJudgmentQuery": {
            "view_ids",
            "aspects",
            "minimum_relevance",
            "reviewers",
            "limit",
            "cursor",
        },
        "SimilarityQuery": {
            "view_id",
            "view_version",
            "values",
            "primitive_ids",
            "metric_ids",
            "assertion_statuses",
            "limit",
        },
    }

    assert {
        name: {field for field, _, _ in _class_fields(classes[name])}
        for name in expected_fields
    } == expected_fields

    methods = {
        node.name
        for node in classes["KnowledgeCatalog"].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {
        "primitives",
        "assignments",
        "modulations",
        "effects",
        "impacts",
        "diagnostics",
        "assertions",
        "retrieval_judgments",
        "similar",
    }

    text = contract.read_text()
    read_block = re.search(
        r"MCP read mode adds these tools in name order:\n\n```text\n(.*?)\n```",
        text,
        re.S,
    )
    execute_block = re.search(
        r"MCP execute mode adds:\n\n```text\n(.*?)\n```",
        text,
        re.S,
    )
    assert read_block is not None
    assert execute_block is not None
    assert read_block.group(1).splitlines() == sorted(read_block.group(1).splitlines())
    assert execute_block.group(1).splitlines() == sorted(
        execute_block.group(1).splitlines()
    )


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
        for block in _python_blocks(document.read_text()):
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
        if (name := _dotted_name(node.func)) is not None
    }

    assert COMPLETE_EXAMPLE_PUBLIC_CALLS - calls == set()
    assert calls & RETIRED_COMPLETE_EXAMPLE_PUBLIC_CALLS == set()

    imported_modules = {
        node.module
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "viper.http" not in imported_modules


def test_target_contracts_use_env_identifiers() -> None:
    """Keep target contracts and their implementation plan on `env` names."""
    contract_text = "\n".join(path.read_text() for path in IMPLEMENTATION_CONTRACTS)
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    target_identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", contract_text))

    assert TARGET_ENV_IDENTIFIERS - target_identifiers == set()
    assert target_identifiers & RETIRED_TARGET_ENV_IDENTIFIERS == set()
    assert 'kind: Literal["env"] = "env"' in contract_text
    assert 'kind: Literal["environment"] = "environment"' not in contract_text
    assert all(name in checklist for name in TARGET_ENV_IDENTIFIERS)
    assert all(name in checklist for name in RETIRED_TARGET_ENV_IDENTIFIERS)


def test_target_contracts_use_eval_identifiers() -> None:
    """Keep the evaluation-stage contract on the `Eval` vocabulary."""
    contract_text = "\n".join(path.read_text() for path in IMPLEMENTATION_CONTRACTS)
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    target_identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", contract_text))

    assert TARGET_EVAL_IDENTIFIERS - target_identifiers == set()
    assert target_identifiers & RETIRED_TARGET_EVAL_IDENTIFIERS == set()
    assert 'kind: Literal["eval"] = "eval"' in contract_text
    assert 'kind: Literal["evaluate"] = "evaluate"' not in contract_text
    assert 'DataRole = Literal["training", "validation", "eval", "benchmark"]' in (
        contract_text
    )
    assert 'data_role="evaluation"' not in contract_text
    assert "artifacts/evaluations/" not in contract_text
    assert "eval_id" in target_identifiers
    assert "evaluation_id" not in target_identifiers
    assert all(name in checklist for name in TARGET_EVAL_IDENTIFIERS)
    assert all(name in checklist for name in RETIRED_TARGET_EVAL_IDENTIFIERS)


def test_complete_authoring_example_uses_env_keywords() -> None:
    """Require the full example to use the target env API and fields."""
    trees = tuple(
        ast.parse(block, filename=str(AUTOMATIC_INPUT_RESOLUTION))
        for block in _complete_authoring_blocks()
    )
    calls = tuple(
        node for tree in trees for node in ast.walk(tree) if isinstance(node, ast.Call)
    )
    names = {name for node in calls if (name := _dotted_name(node.func)) is not None}
    plan_calls = tuple(
        node for node in calls if _dotted_name(node.func) == "viper.plan"
    )

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
            (base_name := _dotted_name(base)) is not None
            and base_name.startswith("viper.params.")
            for base in node.bases
        )
    }
    parameter_accesses = {
        node.attr
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        if _dotted_name(node.value) in {"params", "context.params"}
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
        for raw_target in _local_links(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("https://", "http://", "mailto:")):
                continue

            path_text, separator, anchor = target.partition("#")
            linked_path = (
                document if not path_text else document.parent / unquote(path_text)
            )
            linked_path = linked_path.resolve()
            if not linked_path.exists():
                failures.append(
                    f"{document.relative_to(ROOT)} -> {target}: missing file"
                )
                continue
            if separator and linked_path.suffix == ".md":
                anchors = _github_anchors(linked_path.read_text())
                if unquote(anchor) not in anchors:
                    failures.append(
                        f"{document.relative_to(ROOT)} -> {target}: missing anchor"
                    )

    assert failures == []


def _numbered_contract_section(text: str, number: int) -> str:
    """Return one numbered top-level section from a development contract."""
    match = re.search(
        rf"^## {number}\. [^\n]+\n(?P<body>.*?)(?=^## \d+\. |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, number
    return match.group("body")


def test_phase_zero_contracts_show_three_dags_and_instantiate_models() -> None:
    """Require each foundational contract to show and realize its full delta."""
    failures: dict[str, list[str]] = {}

    for contract in PHASE_ZERO_CONTRACTS:
        text = contract.read_text()
        current_gap = _numbered_contract_section(text, 3)
        contract_models = _numbered_contract_section(text, 4)
        errors: list[str] = []

        for heading in (
            "### Current DAG",
            "### Proposed-change DAG",
            "### Integrated DAG",
        ):
            if heading not in current_gap:
                errors.append(f"missing {heading}")

        diagrams = tuple(_MERMAID_FENCE.finditer(current_gap))
        if len(diagrams) != 3:
            errors.append(f"expected 3 Mermaid DAGs; found {len(diagrams)}")
        for index, diagram in enumerate(diagrams, start=1):
            diagram_body = diagram.group("body")
            if not diagram_body.lstrip().startswith("flowchart"):
                errors.append(f"diagram {index} is not a Mermaid flowchart")
                continue

            adjacency: dict[str, set[str]] = {}
            for line in diagram_body.splitlines():
                edge = _MERMAID_EDGE.match(line)
                if edge is None:
                    continue
                adjacency.setdefault(edge.group("source"), set()).add(
                    edge.group("target")
                )
            if not adjacency:
                errors.append(f"diagram {index} has no parsed directed edges")
                continue

            visiting: set[str] = set()
            visited: set[str] = set()

            def visit(node: str) -> bool:
                if node in visiting:
                    return False
                if node in visited:
                    return True
                visiting.add(node)
                for target in adjacency.get(node, set()):
                    if not visit(target):
                        return False
                visiting.remove(node)
                visited.add(node)
                return True

            if not all(visit(node) for node in adjacency):
                errors.append(f"diagram {index} contains a directed cycle")

        examples = tuple(_CONTRACT_WORKED_EXAMPLE.finditer(contract_models))
        if len(examples) != 1:
            errors.append(f"expected 1 marked worked example; found {len(examples)}")
            failures[contract.name] = errors
            continue

        declarations_text = contract_models[: examples[0].start()]
        declaration_trees = [
            ast.parse(match.group("body"))
            for match in _PYTHON_FENCE.finditer(declarations_text)
        ]
        declared_classes = {
            node.name
            for tree in declaration_trees
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        declared_functions = {
            node.name
            for tree in declaration_trees
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        declared_aliases = {
            target.id
            for tree in declaration_trees
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        example_blocks = tuple(
            match.group("body")
            for match in _PYTHON_FENCE.finditer(examples[0].group("body"))
        )
        if not example_blocks:
            errors.append("worked example has no Python block")
            failures[contract.name] = errors
            continue

        example_tree = ast.parse("\n\n".join(example_blocks))
        calls = {
            node.func.id
            for node in ast.walk(example_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        used_names = {
            node.id for node in ast.walk(example_tree) if isinstance(node, ast.Name)
        }
        missing_classes = sorted(declared_classes - calls)
        missing_functions = sorted(declared_functions - calls)
        missing_aliases = sorted(declared_aliases - used_names)
        if missing_classes:
            errors.append(f"models never constructed: {missing_classes}")
        if missing_functions:
            errors.append(f"operations never called: {missing_functions}")
        if missing_aliases:
            errors.append(f"aliases never realized: {missing_aliases}")

        if errors:
            failures[contract.name] = errors

    assert failures == {}


def test_phase_zero_contract_traces_use_typed_outcomes() -> None:
    """Require concrete setup plus distinct accepted and rejected outcomes."""
    common_fields = {
        "trace_id",
        "requirement_id",
        "rule_id",
        "state",
        "scenario",
        "setup",
        "declaration",
        "runtime",
        "implementation",
        "test",
        "outcome",
    }
    retired_fields = {"input", "persisted_evidence", "verifier", "expected"}

    for contract in PHASE_ZERO_CONTRACTS:
        traces = tuple(
            tomllib.loads(match.group("body"))
            for match in _CONTRACT_TRACE_FENCE.finditer(contract.read_text())
        )
        assert len(traces) == 2, contract.name
        assert {trace["outcome"]["kind"] for trace in traces} == {
            "accepted",
            "rejected",
        }

        for trace in traces:
            assert set(trace) == common_fields, (contract.name, trace["trace_id"])
            assert retired_fields.isdisjoint(trace)
            assert all(
                isinstance(trace[field], str) and trace[field].strip()
                for field in common_fields - {"outcome"}
            )

            outcome = trace["outcome"]
            if outcome["kind"] == "accepted":
                assert set(outcome) == {"kind", "result", "persisted_evidence"}
                assert outcome["result"].strip()
                assert outcome["persisted_evidence"]
            else:
                assert set(outcome) == {
                    "kind",
                    "rejected_at",
                    "error_type",
                    "message_match",
                }
                assert all(
                    isinstance(outcome[field], str) and outcome[field].strip()
                    for field in outcome
                    if field != "kind"
                )


def test_contract_requirements_map_to_plan_tasks_and_tests() -> None:
    """Bind every pending contract requirement to one plan phase and test."""
    declarations: dict[str, tuple[Path, int, Path]] = {}
    declaration_counts: Counter[str] = Counter()
    for contract in IMPLEMENTATION_CONTRACTS:
        matches = tuple(_CONTRACT_REQUIREMENT.finditer(contract.read_text()))
        assert matches, f"{contract.relative_to(ROOT)} declares no requirements"
        for match in matches:
            requirement = match.group("requirement")
            assert match.group("label") == requirement
            test_path = ROOT / match.group("test")
            declaration_counts[requirement] += 1
            declarations[requirement] = (
                contract,
                int(match.group("phase")),
                test_path,
            )

    assert all(count == 1 for count in declaration_counts.values())

    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    baselines = {
        match.group("name"): match.group("sha256")
        for match in _CONTRACT_BASELINE.finditer(checklist)
    }
    assert set(baselines) == {contract.name for contract in IMPLEMENTATION_CONTRACTS}
    for contract in IMPLEMENTATION_CONTRACTS:
        assert (
            hashlib.sha256(contract.read_bytes()).hexdigest()
            == baselines[contract.name]
        )

    phase_matches = tuple(_PHASE_HEADING.finditer(checklist))
    assert len(phase_matches) == 19
    mappings: dict[str, dict[str, list[tuple[int, str]]]] = {
        "implements": {},
        "verifies": {},
    }
    phase_text: dict[int, str] = {}
    for index, phase_match in enumerate(phase_matches):
        phase = int(phase_match.group("phase"))
        end = (
            phase_matches[index + 1].start()
            if index + 1 < len(phase_matches)
            else len(checklist)
        )
        section = checklist[phase_match.start() : end]
        phase_text[phase] = section
        for checkbox in _CHECKBOX_BLOCK.finditer(section):
            block = checkbox.group(0)
            for marker in _CHECKLIST_MAPPING.finditer(block):
                role = marker.group("role")
                requirements = tuple(
                    value.strip() for value in marker.group("requirements").split(",")
                )
                for requirement in requirements:
                    mappings[role].setdefault(requirement, []).append((phase, block))

    assert set(phase_text) == set(range(0, 19))

    declared = set(declarations)
    assert set(mappings["implements"]) == declared
    assert set(mappings["verifies"]) == declared

    for requirement, (contract, expected_phase, test_path) in declarations.items():
        implementation = mappings["implements"][requirement]
        verification = mappings["verifies"][requirement]
        assert len(implementation) == 1, requirement
        assert len(verification) == 1, requirement
        assert implementation[0][0] == expected_phase, requirement
        assert verification[0][0] == expected_phase, requirement
        assert test_path.is_file(), test_path.relative_to(ROOT)
        assert test_path.relative_to(ROOT).as_posix() in verification[0][1], requirement

        owner_section = phase_text[expected_phase]
        assert (
            re.search(
                rf"\({re.escape(contract.name)}(?:#[^)]+)?\)",
                owner_section,
            )
            or "**Contracts:** All." in owner_section
        ), requirement


def test_contract_propagation_paths_enter_the_code_change_ledger() -> None:
    """Require every concrete propagation owner in the authoritative ledger."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    missing: dict[str, list[str]] = {}
    for contract in IMPLEMENTATION_CONTRACTS:
        text = contract.read_text()
        match = re.search(
            r"^## \d+\. Propagation[^\n]*\n(?P<body>.*?)(?=^## |\Z)",
            text,
            re.M | re.S,
        )
        assert match is not None, contract.name
        paths = {
            value
            for value in re.findall(r"`([^`]+)`", match.group("body"))
            if value.startswith(("src/", "tests/")) or value == "pyproject.toml"
        }
        absent = sorted(path for path in paths if f"`{path}`" not in checklist)
        if absent:
            missing[contract.name] = absent

    assert missing == {}


def test_master_checklist_orders_capability_producers_before_consumers() -> None:
    """Reject a phase that consumes a named capability before it exists."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    phases = tuple(_PHASE_HEADING.finditer(checklist))
    events: dict[str, dict[str, list[tuple[int, int]]]] = {
        "produces": {},
        "consumes": {},
    }

    for index, phase_match in enumerate(phases):
        phase = int(phase_match.group("phase"))
        end = phases[index + 1].start() if index + 1 < len(phases) else len(checklist)
        section = checklist[phase_match.start() : end]
        for checkbox in _CHECKBOX_BLOCK.finditer(section):
            for marker in _PHASE_CAPABILITY.finditer(checkbox.group(0)):
                position = phase_match.start() + checkbox.start() + marker.start()
                for symbol in marker.group("symbols").split(","):
                    events[marker.group("role")].setdefault(symbol.strip(), []).append(
                        (phase, position)
                    )

    assert _ORDERED_CAPABILITIES <= events["produces"].keys()
    assert _ORDERED_CAPABILITIES <= events["consumes"].keys()

    for symbol, consumers in events["consumes"].items():
        producers = events["produces"].get(symbol, [])
        assert len(producers) == 1, symbol
        producer_phase, producer_position = producers[0]
        for consumer_phase, consumer_position in consumers:
            assert producer_phase <= consumer_phase, symbol
            assert producer_position < consumer_position, symbol


def test_terminal_release_gate_follows_every_implementation_phase() -> None:
    """Keep full repository and wheel validation after the last build phase."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    phases = tuple(_PHASE_HEADING.finditer(checklist))
    assert phases
    assert int(phases[-1].group("phase")) == 18
    terminal = checklist[phases[-1].start() :]
    earlier = checklist[: phases[-1].start()]

    for command in ("make check", "make check-integration", "make check-release"):
        assert command in terminal
        assert command not in earlier
    assert "Install the wheel with the `mcp` and `knowledge` extras" in terminal


def test_master_checklist_names_existing_test_modules() -> None:
    """Require every test module named by the implementation plan to exist."""
    named_tests = set(
        re.findall(
            r"tests/[a-z0-9_/]+\.py",
            MASTER_EXECUTION_CHECKLIST.read_text(),
        )
    )

    assert named_tests
    assert {name for name in named_tests if not (ROOT / name).is_file()} == set()


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


def test_public_examples_distinguish_weights_from_the_artifact_key() -> None:
    """Keep tutorial vocabulary clear without changing the protocol artifact name."""
    public_text = "\n".join(path.read_text() for path in PUBLIC_MARKDOWN)

    assert 'weights_path = context.artifacts["parameters"]' in public_text
    assert "parameters_path" not in public_text


def test_training_examples_name_the_project_owned_training_function() -> None:
    """Keep project computation separate from VIPER's stage context."""
    undefined_calls = (
        "run_training(",
        "model = fit(",
        "update_model(",
        "save_weights(",
    )

    for path in TRAINING_GUIDES:
        text = path.read_text()
        assert "from my_project.training import train_model" in text
        assert "train_model(" in text
        assert all(call not in text for call in undefined_calls)


def test_current_docs_do_not_reference_retired_public_modules() -> None:
    """Keep current guides on the single-owner public module layout."""
    current_guides = tuple(
        path
        for path in PUBLIC_MARKDOWN
        if path.name not in {"CHANGELOG.md", "0.1.0a1.md"}
    )
    text = "\n".join(path.read_text() for path in current_guides)

    assert "viper.protocol" not in text
    assert "viper.runner" not in text
    assert "viper.verifier" not in text
    assert "viper.file_artifact" not in text
    assert "viper.file_input" not in text
    assert "FileInputDraft" not in text
    assert "docs/contracts" not in text
    assert "PUBLICATION_TODO" not in text
