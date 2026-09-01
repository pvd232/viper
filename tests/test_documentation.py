"""Keep the published documentation aligned with the executable package."""

from __future__ import annotations

import ast
import hashlib
import importlib
import re
import tomllib
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import pytest

import viper._contract_traceability as traceability
from viper._contract_traceability import (
    AcceptedTraceOutcome,
    ContractRequirement,
    ContractTrace,
    ContractTraceabilityGraph,
    DeclarationRef,
    RejectedTraceOutcome,
    RepoSymbolRef,
    RuleEdge,
    VerifierRule,
)
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
CONTRACT_TRACEABILITY = (
    ROOT / "docs/development/contract-requirement-traceability.md"
)
MODULE_OWNERSHIP = ROOT / "docs/development/module-ownership.md"
SYSTEM_IMPACT_GRAPH = ROOT / "docs/development/system-impact-graph.md"
SYSTEM_IMPACT_CORE_PROOF = (
    ROOT / "docs/development/proof/graph_transformation/core-proof.md"
)
PHASE_ZERO_PAIR_CODING = ROOT / "docs/development/phase-0-pair-coding.md"
CONTRACT_TRACEABILITY_PAIR_CODING = (
    ROOT / "docs/development/contract-traceability-phase-0-pair-coding.md"
)
SYSTEM_IMPACT_PAIR_CODING = (
    ROOT / "docs/development/system-impact-phase-0-1-pair-coding.md"
)
IMPLEMENTATION_CONTRACTS = (
    ROOT / "docs/development/contract-requirement-traceability.md",
    ROOT / "docs/development/project-data-root.md",
    MODULE_OWNERSHIP,
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
    MODULE_OWNERSHIP,
    ROOT / "docs/development/system-impact-graph.md",
)
TRACEABILITY_MODELS = (
    DeclarationRef,
    RepoSymbolRef,
    ContractRequirement,
    VerifierRule,
    RuleEdge,
    AcceptedTraceOutcome,
    RejectedTraceOutcome,
    ContractTrace,
    ContractTraceabilityGraph,
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
    "viper.authoring.expand",
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
_MERMAID_CLASS_DEF = re.compile(
    r"^\s*classDef (?P<role>[a-z]+) (?P<style>.+)$",
    re.MULTILINE,
)
_MERMAID_CLASS_ASSIGNMENT = re.compile(
    r"^\s*class (?P<nodes>[A-Za-z0-9_,]+) (?P<role>[a-z]+)$",
    re.MULTILINE,
)
_PHASE_ZERO_SECTION = re.compile(
    r"^## 7\. Phase 0\b(?P<body>.*?)(?=^## 8\. Phase 1\b)",
    re.MULTILINE | re.DOTALL,
)
_PHASE_ZERO_CHECKBOX = re.compile(
    r"^- \[[ x]\] .*?(?=^- \[[ x]\] |^### |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_PAIR_BLOCK_MARKER = re.compile(r"<!-- pair-block: (?P<id>P0-[A-Z]+-\d{2}) -->")
_PAIR_BLOCK_DEFINITION = re.compile(
    r"<!-- pair-block-definition: (?P<id>P0-[A-Z]+-\d{2}) -->\n"
    r"```toml pair-block\n(?P<manifest>.*?)\n```\n"
    r"(?P<body>.*?)(?=<!-- pair-block-definition: |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_PAIR_EDIT = re.compile(r"```python pair-edit\n(?P<code>.*?)\n```", re.DOTALL)
_SYSTEM_PAIR_BLOCK_DEFINITION = re.compile(
    r"<!-- pair-block-definition: "
    r"(?P<id>P[01]-SIG-\d{2}|P0-PROOF-(?:09|10|11|12)) -->\n"
    r"```toml pair-block\n(?P<manifest>.*?)\n```\n"
    r"(?P<body>.*?)(?=<!-- pair-block-definition: |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_PAIR_PLACEHOLDER = re.compile(
    r"(?:\bTBD\b|\bTODO\b|^\s*\.\.\.\s*$|=\s*\.\.\.\s*$)",
    re.MULTILINE,
)
_IMPLEMENTED_EXAMPLE_MODULES = {"viper._contract_traceability"}

TRACEABILITY_DAG_PALETTES = (
    {
        "current": "fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px",
        "evidence": "fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px",
        "gap": "fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px",
    },
    {
        "proposed": "fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px",
    },
    {
        "contract": "fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px",
        "checklist": "fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px",
        "implementation": "fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px",
        "output": "fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px",
    },
)
TRACEABILITY_LINK_STYLE = "linkStyle default stroke:#94a3b8,stroke-width:2px"
MODULE_OWNERSHIP_DAG_EDGES = (
    {
        ("ApiTypes", "Handlers"),
        ("Handlers", "Wrappers"),
        ("VerificationTypes", "PrivateVerification"),
        ("PrivateVerification", "LateImports"),
        ("VerificationTypes", "LateImports"),
    },
    {
        ("Models", "Verification"),
        ("Private", "Verification"),
        ("Api", "Verification"),
        ("Api", "Tests"),
        ("Verification", "Tests"),
        ("Models", "Tests"),
    },
    {
        ("Contract", "ModelsTask"),
        ("ModelsTask", "Models"),
        ("Models", "VerificationTask"),
        ("VerificationTask", "Verification"),
        ("Verification", "ApiTask"),
        ("ApiTask", "Api"),
        ("Models", "Test"),
        ("Verification", "Test"),
        ("Api", "Test"),
        ("Test", "System"),
    },
)
MODULE_OWNERSHIP_DAG_PALETTES = TRACEABILITY_DAG_PALETTES
SYSTEM_IMPACT_DAG_PALETTES = (
    {
        "input": "fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px",
        "current": "fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px",
        "evidence": "fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px",
        "gap": "fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px",
    },
    {
        "input": "fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px",
        "proposed": "fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px",
    },
    {
        "input": "fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px",
        "evidence": "fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px",
        "output": "fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px",
        "consumer": "fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px",
    },
)
SYSTEM_IMPACT_DAG_ROLES = (
    {
        "Python": "input",
        "Contracts": "input",
        "Plans": "input",
        "Runs": "input",
        "Architecture": "current",
        "Documentation": "current",
        "PlanDiff": "current",
        "Lineage": "current",
        "LocalA": "evidence",
        "LocalB": "evidence",
        "LocalC": "evidence",
        "LocalD": "evidence",
        "Gap": "gap",
    },
    {
        "Baseline": "input",
        "Context": "input",
        "Traceability": "input",
        "DeltaDocs": "input",
        "Bootstrap": "input",
        "Inventory": "proposed",
        "Analyze": "proposed",
        "Sites": "proposed",
        "Graph": "proposed",
        "ContractCompiler": "proposed",
        "Delta": "proposed",
        "Overlay": "proposed",
        "Support": "proposed",
        "Closure": "proposed",
        "SCC": "proposed",
        "DAG": "proposed",
        "Select": "proposed",
        "Coverage": "proposed",
        "Plan": "proposed",
        "Target": "proposed",
        "Work": "proposed",
    },
    {
        "Baseline": "input",
        "Context": "input",
        "Traceability": "input",
        "DeltaDocs": "input",
        "Bootstrap": "input",
        "Decisions": "input",
        "CompileBase": "consumer",
        "CompileContract": "consumer",
        "CompileWork": "consumer",
        "Implementation": "consumer",
        "CompileObserved": "consumer",
        "Review": "consumer",
        "BaseGraph": "evidence",
        "PairBlocks": "evidence",
        "Candidate": "evidence",
        "CandidateGraph": "evidence",
        "Delta": "output",
        "Impact": "output",
        "Condensation": "output",
        "Tests": "output",
        "Coverage": "output",
        "Plan": "output",
        "Target": "output",
        "Conformance": "output",
    },
)
SYSTEM_IMPACT_DAG_EDGES = (
    {
        ("Python", "Architecture"),
        ("Contracts", "Documentation"),
        ("Plans", "PlanDiff"),
        ("Runs", "Lineage"),
        ("Architecture", "LocalA"),
        ("Documentation", "LocalB"),
        ("PlanDiff", "LocalC"),
        ("Lineage", "LocalD"),
        ("LocalA", "Gap"),
        ("LocalB", "Gap"),
        ("LocalC", "Gap"),
        ("LocalD", "Gap"),
    },
    {
        ("Baseline", "Inventory"),
        ("Context", "Analyze"),
        ("Inventory", "Analyze"),
        ("Analyze", "Sites"),
        ("Analyze", "Graph"),
        ("Sites", "Graph"),
        ("Traceability", "Graph"),
        ("Bootstrap", "Graph"),
        ("DeltaDocs", "ContractCompiler"),
        ("Graph", "ContractCompiler"),
        ("ContractCompiler", "Delta"),
        ("Graph", "Overlay"),
        ("Delta", "Overlay"),
        ("Delta", "Support"),
        ("Overlay", "Closure"),
        ("Support", "Closure"),
        ("Closure", "SCC"),
        ("SCC", "DAG"),
        ("Closure", "Select"),
        ("Select", "Coverage"),
        ("Closure", "Plan"),
        ("Graph", "Target"),
        ("Delta", "Target"),
        ("Plan", "Target"),
        ("Target", "Work"),
        ("DAG", "Work"),
    },
    {
        ("Baseline", "CompileBase"),
        ("Context", "CompileBase"),
        ("Traceability", "CompileBase"),
        ("Bootstrap", "CompileBase"),
        ("CompileBase", "BaseGraph"),
        ("DeltaDocs", "CompileContract"),
        ("BaseGraph", "CompileContract"),
        ("CompileContract", "Delta"),
        ("BaseGraph", "Impact"),
        ("Delta", "Impact"),
        ("Impact", "Condensation"),
        ("Impact", "Tests"),
        ("Tests", "Coverage"),
        ("Impact", "Plan"),
        ("Decisions", "Plan"),
        ("BaseGraph", "Target"),
        ("Delta", "Target"),
        ("Plan", "Target"),
        ("Target", "CompileWork"),
        ("Condensation", "CompileWork"),
        ("CompileWork", "PairBlocks"),
        ("PairBlocks", "Implementation"),
        ("Implementation", "Candidate"),
        ("Candidate", "CompileObserved"),
        ("Context", "CompileObserved"),
        ("CompileObserved", "CandidateGraph"),
        ("CandidateGraph", "Conformance"),
        ("Target", "Conformance"),
        ("Coverage", "Review"),
        ("Conformance", "Review"),
    },
)

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
    plan_calls = tuple(node for node in calls if _dotted_name(node.func) == "plan")

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
            and base_name.startswith("params.")
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


def test_contract_traceability_dags_use_semantic_palette() -> None:
    """Keep each traceability DAG role bound to its declared color."""
    text = CONTRACT_TRACEABILITY.read_text()
    section = text.split("## 3. Current gap", maxsplit=1)[1].split(
        "## 4. Contract models", maxsplit=1
    )[0]
    diagrams = tuple(
        match.group("body") for match in _MERMAID_FENCE.finditer(section)
    )

    assert len(diagrams) == len(TRACEABILITY_DAG_PALETTES)
    for diagram, expected_palette in zip(
        diagrams,
        TRACEABILITY_DAG_PALETTES,
        strict=True,
    ):
        actual_palette = {
            match.group("role"): match.group("style")
            for match in _MERMAID_CLASS_DEF.finditer(diagram)
        }
        assert actual_palette == expected_palette
        assert TRACEABILITY_LINK_STYLE in diagram


def test_module_ownership_dags_preserve_semantic_topology() -> None:
    """Keep the module refactor diagrams aligned with the scheduled moves."""
    current_gap = _numbered_contract_section(MODULE_OWNERSHIP.read_text(), 3)
    diagrams = tuple(
        match.group("body") for match in _MERMAID_FENCE.finditer(current_gap)
    )

    assert len(diagrams) == 3
    for diagram, expected_edges, expected_palette in zip(
        diagrams,
        MODULE_OWNERSHIP_DAG_EDGES,
        MODULE_OWNERSHIP_DAG_PALETTES,
        strict=True,
    ):
        actual_edges = {
            (edge.group("source"), edge.group("target"))
            for line in diagram.splitlines()
            if (edge := _MERMAID_EDGE.match(line)) is not None
        }
        actual_palette = {
            match.group("role"): match.group("style")
            for match in _MERMAID_CLASS_DEF.finditer(diagram)
        }

        assert actual_edges == expected_edges
        assert actual_palette == expected_palette
        assert TRACEABILITY_LINK_STYLE in diagram


def test_system_impact_dags_preserve_semantic_topology() -> None:
    """Keep each system-impact DAG edge and role aligned with its contract."""
    current_gap = _numbered_contract_section(
        SYSTEM_IMPACT_GRAPH.read_text(),
        3,
    )
    diagrams = tuple(
        match.group("body") for match in _MERMAID_FENCE.finditer(current_gap)
    )

    assert len(diagrams) == 3
    for diagram, expected_edges, expected_roles, expected_palette in zip(
        diagrams,
        SYSTEM_IMPACT_DAG_EDGES,
        SYSTEM_IMPACT_DAG_ROLES,
        SYSTEM_IMPACT_DAG_PALETTES,
        strict=True,
    ):
        actual_edges: set[tuple[str, str]] = set()
        for line in diagram.splitlines():
            edge = _MERMAID_EDGE.match(line)
            if edge is not None:
                actual_edges.add((edge.group("source"), edge.group("target")))
        actual_roles = {
            node: assignment.group("role")
            for assignment in _MERMAID_CLASS_ASSIGNMENT.finditer(diagram)
            for node in assignment.group("nodes").split(",")
        }
        actual_palette = {
            match.group("role"): match.group("style")
            for match in _MERMAID_CLASS_DEF.finditer(diagram)
        }

        assert actual_edges == expected_edges
        assert actual_roles == expected_roles
        assert actual_palette == expected_palette
        assert TRACEABILITY_LINK_STYLE in diagram


def test_contract_traceability_pair_guide_covers_each_cycle() -> None:
    """Require every CRT cycle to carry one exact parseable edit and gate."""
    text = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    headings = (
        "## 1. Status and boundary",
        "## 2. Pair-cycle contract",
        "## 3. Production PairBlocks",
        "## 4. Acceptance PairBlocks",
        "## 5. Pair execution",
        "## 6. Phase gate",
        "## 7. SystemGraph handoff",
    )
    positions = tuple(text.index(heading) for heading in headings)
    assert positions == tuple(sorted(positions))

    definitions = tuple(_PAIR_BLOCK_DEFINITION.finditer(text))
    expected_ids = (
        "P0-CRT-01",
        "P0-CRT-02",
        "P0-CRT-03",
        "P0-CRT-04",
        "P0-CRT-05",
        "P0-PROOF-01",
        "P0-PROOF-02",
        "P0-PROOF-03",
        "P0-PROOF-04",
    )
    assert tuple(item.group("id") for item in definitions) == expected_ids

    manifests: dict[str, dict[str, object]] = {}
    declarations: dict[str, set[str]] = {}
    for definition in definitions:
        block_id = definition.group("id")
        manifest = tomllib.loads(definition.group("manifest"))
        assert manifest["id"] == block_id
        assert set(manifest) == {
            "id",
            "requirements",
            "targets",
            "tests",
            "gate",
            "depends_on",
        }
        assert manifest["requirements"]
        assert manifest["targets"]
        assert manifest["tests"]
        assert str(manifest["gate"]).startswith("conda run -n mantra ")

        edits = tuple(_PAIR_EDIT.finditer(definition.group("body")))
        assert len(edits) == 1, block_id
        code = edits[0].group("code")
        assert _PAIR_PLACEHOLDER.search(code) is None, block_id
        tree = ast.parse(
            code,
            filename=f"{CONTRACT_TRACEABILITY_PAIR_CODING.name}:{block_id}",
        )
        names: set[str] = set()
        for node in tree.body:
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                names.add(node.name)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else (node.target,)
                )
                names.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
        declarations[block_id] = names
        manifests[block_id] = manifest

    target_pattern = re.compile(
        r"^(?:src|tests)/[a-z0-9_/]+\.py:[A-Za-z_][A-Za-z0-9_.]*$"
    )
    all_targets = {
        target
        for manifest in manifests.values()
        for target in manifest["targets"]
    }
    order = {block_id: index for index, block_id in enumerate(expected_ids)}
    for block_id, manifest in manifests.items():
        assert all(
            target_pattern.fullmatch(target) for target in manifest["targets"]
        )
        for target in manifest["targets"]:
            assert target.partition(":")[2] in declarations[block_id], (
                block_id,
                target,
            )
        for test in manifest["tests"]:
            test_path = test.partition(":")[0]
            assert (ROOT / test_path).is_file() or any(
                target.partition(":")[0] == test_path
                for target in all_targets
            )

        dependencies = manifest["depends_on"]
        assert len(dependencies) == len(set(dependencies)), block_id
        for dependency in dependencies:
            if dependency == "P0-PDR-05":
                continue
            assert dependency in manifests, (block_id, dependency)
            assert order[dependency] < order[block_id], (
                block_id,
                dependency,
            )

    pending_contracts = {
        contract.name for contract in IMPLEMENTATION_CONTRACTS[4:]
    }
    assert pending_contracts == {
        name
        for name in pending_contracts
        if f"`{name}`" in text
    }


def test_system_graph_stages_traceability_before_contract_delta() -> None:
    """Keep CRT lowering inside G0 compilation and delta compilation after G0."""
    proof = SYSTEM_IMPACT_CORE_PROOF.read_text(encoding="utf-8")
    crt_guide = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    system_guide = SYSTEM_IMPACT_PAIR_CODING.read_text(encoding="utf-8")

    assert "Q_0=\\operatorname{CompileTraceability}(R_0)" in proof
    assert (
        "\\operatorname{CompileContractDelta}(d_\\Delta,G_0)"
        in proof
    )
    assert "Q0 -> compile_system() -> G0" in crt_guide
    assert "(contract-delta declaration, G0)" in crt_guide
    assert "only traceability input accepted" not in crt_guide

    definition = next(
        item
        for item in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(system_guide)
        if item.group("id") == "P0-SIG-04"
    )
    manifest = tomllib.loads(definition.group("manifest"))
    assert manifest["depends_on"] == ["P0-CRT-05", "P0-SIG-03"]
    assert "ingest_contract_traceability" in " ".join(manifest["targets"])
    assert "compile_contract_delta" in " ".join(manifest["targets"])
    body = " ".join(definition.group("body").split())
    assert "Derive `ContractTraceabilityGraph`" not in body
    assert body.index("Consume the canonical `ContractTraceabilityGraph`") < (
        body.index("After `G0` exists")
    )


def test_contract_traceability_pair_guide_executes_as_one_workflow(
    tmp_path: Path,
) -> None:
    """Execute the proposed CRT code and every focused acceptance case."""
    text = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    definitions = {
        definition.group("id"): _PAIR_EDIT.search(
            definition.group("body")
        ).group("code")
        for definition in _PAIR_BLOCK_DEFINITION.finditer(text)
    }

    namespace = dict(vars(traceability))
    for block_id in (
        "P0-CRT-01",
        "P0-CRT-02",
        "P0-CRT-03",
        "P0-CRT-05",
    ):
        exec(
            compile(definitions[block_id], f"<{block_id}>", "exec"),
            namespace,
        )

    documentation_namespace = {
        "IMPLEMENTATION_CONTRACTS": IMPLEMENTATION_CONTRACTS,
    }
    exec(
        compile(definitions["P0-CRT-04"], "<P0-CRT-04>", "exec"),
        documentation_namespace,
    )
    assert documentation_namespace["CONTRACTS_WITH_COMPLETE_EXAMPLES"] == (
        IMPLEMENTATION_CONTRACTS
    )

    for block_id in (
        "P0-PROOF-01",
        "P0-PROOF-02",
        "P0-PROOF-03",
        "P0-PROOF-04",
    ):
        tree = ast.parse(definitions[block_id], filename=f"<{block_id}>")
        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.ImportFrom)
                and node.module == "viper._contract_traceability"
            )
        ]
        exec(compile(tree, f"<{block_id}>", "exec"), namespace)

    tests = (
        "test_requirement_rows_and_rules_compile",
        "test_requirement_rows_reject_duplicate_and_orphan_ids",
        "test_rule_edges_resolve_one_owner_and_tests",
        "test_rule_edges_reject_missing_symbols",
        "test_contract_traces_compile",
        "test_contract_traces_reject_incomplete_evidence",
        "test_contract_examples_reject_incomplete_structure",
        "test_contract_traceability_graph_is_canonical",
        "test_contract_traceability_graph_rejects_duplicate_ids",
    )
    for index, test_name in enumerate(tests):
        case_root = tmp_path / str(index)
        case_root.mkdir()
        namespace[test_name](case_root)

def test_phase_zero_checkboxes_have_complete_ordered_pair_blocks() -> None:
    """Bind every Phase 0 task to one parseable dependency-ordered edit."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    phase_match = _PHASE_ZERO_SECTION.search(checklist)
    assert phase_match is not None
    checkboxes = tuple(_PHASE_ZERO_CHECKBOX.finditer(phase_match.group("body")))
    marker_ids: list[str] = []
    implemented_ids: set[str] = set()
    for checkbox in checkboxes:
        markers = tuple(_PAIR_BLOCK_MARKER.finditer(checkbox.group(0)))
        assert len(markers) == 1, checkbox.group(0).splitlines()[0]
        block_id = markers[0].group("id")
        marker_ids.append(block_id)
        if checkbox.group(0).startswith("- [x]"):
            implemented_ids.add(block_id)
    assert len(marker_ids) == len(set(marker_ids))

    reference = PHASE_ZERO_PAIR_CODING.read_text(encoding="utf-8")
    legacy_definitions = tuple(
        definition
        for definition in _PAIR_BLOCK_DEFINITION.finditer(reference)
        if not definition.group("id").startswith("P0-CRT-")
        and definition.group("id")
        not in {"P0-PROOF-01", "P0-PROOF-02", "P0-PROOF-03", "P0-PROOF-04"}
        and not definition.group("id").startswith("P0-SIG-")
        and definition.group("id")
        not in {"P0-PROOF-09", "P0-PROOF-10", "P0-PROOF-11", "P0-PROOF-12"}
    )
    contract_reference = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(
        encoding="utf-8"
    )
    contract_definitions = tuple(
        definition
        for definition in _PAIR_BLOCK_DEFINITION.finditer(contract_reference)
    )
    system_reference = SYSTEM_IMPACT_PAIR_CODING.read_text(encoding="utf-8")
    system_definitions = tuple(
        definition
        for definition in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(system_reference)
        if definition.group("id").startswith("P0-")
    )
    root_definitions = tuple(
        definition
        for definition in legacy_definitions
        if definition.group("id").startswith("P0-PDR-")
    )
    downstream_definitions = tuple(
        definition
        for definition in legacy_definitions
        if not definition.group("id").startswith("P0-PDR-")
    )
    definitions = (
        root_definitions
        + contract_definitions
        + downstream_definitions
        + system_definitions
    )
    definition_ids = [definition.group("id") for definition in definitions]
    assert len(definition_ids) == len(set(definition_ids))
    assert set(definition_ids) == set(marker_ids)

    requirement_ids = {
        match.group("requirement")
        for contract in PHASE_ZERO_CONTRACTS
        for match in _CONTRACT_REQUIREMENT.finditer(
            contract.read_text(encoding="utf-8")
        )
    }
    manifests: dict[str, dict[str, object]] = {}
    order: dict[str, int] = {}
    planned_target_paths = {
        value.partition(":")[0]
        for definition in definitions
        for value in tomllib.loads(definition.group("manifest"))["targets"]
    }
    target_pattern = re.compile(
        r"^(?:src|tests)/[a-z0-9_/]+\.py:[A-Za-z_][A-Za-z0-9_.]*$"
    )
    for index, definition in enumerate(definitions):
        block_id = definition.group("id")
        manifest = tomllib.loads(definition.group("manifest"))
        assert manifest["id"] == block_id
        assert set(manifest) == {
            "id",
            "requirements",
            "targets",
            "tests",
            "gate",
            "depends_on",
        }
        assert manifest["requirements"]
        assert set(manifest["requirements"]) <= requirement_ids
        assert manifest["targets"]
        assert manifest["tests"]
        assert all(target_pattern.fullmatch(value) for value in manifest["targets"])
        assert all(target_pattern.fullmatch(value) for value in manifest["tests"])
        assert all(
            (ROOT / value.partition(":")[0]).is_file()
            or value.partition(":")[0] in planned_target_paths
            for value in manifest["tests"]
        )
        assert str(manifest["gate"]).startswith("conda run -n mantra ")

        edits = tuple(_PAIR_EDIT.finditer(definition.group("body")))
        if block_id.startswith("P0-SIG-") or block_id in {
            "P0-PROOF-09",
            "P0-PROOF-10",
            "P0-PROOF-11",
            "P0-PROOF-12",
        }:
            assert not edits, block_id
            assert _PAIR_PLACEHOLDER.search(definition.group("body")) is None
        else:
            assert len(edits) == 1, block_id
            code = edits[0].group("code")
            assert _PAIR_PLACEHOLDER.search(code) is None, block_id
            edit_tree = ast.parse(
                code,
                filename=f"{PHASE_ZERO_PAIR_CODING.name}:{block_id}",
            )
        if block_id not in implemented_ids and edits:
            declarations: set[str] = set()
            for node in edit_tree.body:
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    declarations.add(node.name)
                if isinstance(node, ast.ClassDef):
                    declarations.update(
                        f"{node.name}.{member.name}"
                        for member in node.body
                        if isinstance(
                            member,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    )
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else (node.target,)
                    )
                    declarations.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )
            for target in manifest["targets"]:
                symbol = target.partition(":")[2]
                assert symbol in declarations, (block_id, target)
        manifests[block_id] = manifest
        order[block_id] = index

    for block_id, manifest in manifests.items():
        dependencies = manifest["depends_on"]
        assert isinstance(dependencies, list)
        assert len(dependencies) == len(set(dependencies)), block_id
        for dependency in dependencies:
            assert dependency in manifests, (block_id, dependency)
            assert order[dependency] < order[block_id], (block_id, dependency)


def test_system_graph_phase_one_tasks_have_pair_blocks() -> None:
    """Bind each high-return Phase 1 SystemGraph task to one ordered block."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    section = checklist.split("### 8.0 SystemGraph Phase 1 hardening", 1)[1].split(
        "### 8.1 Local publication interface",
        1,
    )[0]
    marker_ids = re.findall(r"<!-- pair-block: (P1-SIG-\d{2}) -->", section)
    assert marker_ids == ["P1-SIG-01", "P1-SIG-02", "P1-SIG-03", "P1-SIG-04"]

    reference = SYSTEM_IMPACT_PAIR_CODING.read_text(encoding="utf-8")
    definitions = {
        match.group("id"): tomllib.loads(match.group("manifest"))
        for match in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(reference)
        if match.group("id").startswith("P1-SIG-")
    }
    assert set(definitions) == set(marker_ids)
    available = {
        match.group("id")
        for match in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(reference)
    }
    for block_id in marker_ids:
        manifest = definitions[block_id]
        assert manifest["id"] == block_id
        assert manifest["requirements"]
        assert manifest["targets"]
        assert manifest["tests"]
        assert str(manifest["gate"]).startswith("conda run -n mantra ")
        assert set(manifest["depends_on"]) <= available


def test_module_ownership_pair_blocks_cover_every_moved_definition() -> None:
    """Keep each planned move equal to the complete current definition set."""
    reference = PHASE_ZERO_PAIR_CODING.read_text(encoding="utf-8")

    def planned_tree(block_id: str) -> ast.Module:
        definition = next(
            match
            for match in _PAIR_BLOCK_DEFINITION.finditer(reference)
            if match.group("id") == block_id
        )
        edit = _PAIR_EDIT.search(definition.group("body"))
        assert edit is not None
        return ast.parse(edit.group("code"))

    verification_source = ast.parse(
        (ROOT / "src/viper/verification.py").read_text(encoding="utf-8")
    )
    verification_target = planned_tree("P0-MOD-02")
    source_operations = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    target_operations = {
        node.name: node
        for node in verification_target.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    assert source_operations.keys() == target_operations.keys()
    assert {
        name: _normalized(node) for name, node in source_operations.items()
    } == {
        name: _normalized(node) for name, node in target_operations.items()
    }

    model_names = {
        "VerificationError",
        "VerificationPolicy",
        "VerifiedSnapshotFile",
        "VerifiedArtifact",
        "VerifiedInput",
        "VerifiedRunPlan",
        "VerifiedRunResult",
        "VerifiedBenchmarkResult",
    }
    model_target = planned_tree("P0-MOD-01")
    source_models = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    target_models = {
        node.name: node
        for node in model_target.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    assert source_models.keys() == target_models.keys()
    assert {name: _normalized(node) for name, node in source_models.items()} == {
        name: _normalized(node) for name, node in target_models.items()
    }

    api_source = ast.parse(
        (ROOT / "src/viper/_api/handlers.py").read_text(encoding="utf-8")
    )
    api_target = planned_tree("P0-MOD-03")
    source_handlers = {
        node.name: node
        for node in api_source.body
        if isinstance(node, ast.FunctionDef)
    }
    target_handlers = {
        node.name: node
        for node in api_target.body
        if isinstance(node, ast.FunctionDef)
    }
    root_migration = {
        "freeze_run",
        "preflight",
        "execute_stage",
        "run_request",
        "retry_request",
        "execute_benchmark",
        "plan_diff",
        "verify_run",
        "lineage",
        "compare_runs",
        "verify_benchmark",
        "verify_pointer",
    }
    added_helpers = {"_project_root", "_local_fetcher"}
    assert target_handlers.keys() == source_handlers.keys() | added_helpers
    unchanged = source_handlers.keys() - root_migration
    assert {
        name: _normalized(source_handlers[name]) for name in unchanged
    } == {
        name: _normalized(target_handlers[name]) for name in unchanged
    }


def test_phase_zero_system_models_match_contract() -> None:
    """Keep the canonical SystemGraph vocabulary equal in both active guides."""
    contract = SYSTEM_IMPACT_GRAPH.read_text(encoding="utf-8")
    guide = SYSTEM_IMPACT_PAIR_CODING.read_text(encoding="utf-8")
    node_kinds = {
        "repository_file",
        "python_symbol",
        "document_anchor",
        "external_symbol",
    }
    edge_kinds = {
        "contained_by",
        "imports_module",
        "imports_symbol",
        "calls",
        "constructs",
        "inherits_from",
        "uses_type",
        "reads_symbol",
        "writes_symbol",
        "decorated_by",
        "registers_with",
        "exports_symbol",
        "declared_by",
        "implements_rule",
        "verifies_rule",
        "scheduled_by",
        "targets",
        "gated_by",
        "block_depends_on",
        "reads_context",
        "launches",
    }
    fact_kinds = {"node_identity", "node_roles", "python_signature", "edge"}
    constraint_kinds = {"presence", "absence", "preservation"}
    for value in node_kinds | edge_kinds | fact_kinds | constraint_kinds:
        assert f'"{value}"' in contract
        assert value in guide
    assert "source depends on the target" in contract
    assert "source depends on target" in guide
    assert "ContractCompiler -->|\"PairBlocks\"| Plan" not in contract
    assert "PairReference" not in contract
    assert 'CompileWork -->|"ordered work"| PairBlocks' in contract
    assert 'PairBlocks -->|"bounded work"| Implementation' in contract


def _worked_example_runtime_failures(
    contract_name: str,
    example: str,
) -> list[str]:
    """Return every stale live import or model field in one worked example."""
    failures: list[str] = []
    blocks = tuple(
        match.group("body") for match in _PYTHON_FENCE.finditer(example)
    )
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
                failures.append(
                    f"{contract_name}: missing {node.module}.{name.name}"
                )
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
    for contract in PHASE_ZERO_CONTRACTS:
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


def test_worked_example_runtime_check_rejects_retired_models_and_fields() -> None:
    """Preserve the stale traceability-model defect as a rejected fixture."""
    example = """```python
from viper._contract_traceability import (
    ContractRequirement,
    RuleImplementation,
)

ContractRequirement(
    requirement_id="CRT-01",
    contract="docs/development/example.md",
    phase=0,
)
```"""

    assert _worked_example_runtime_failures("retired-model.md", example) == [
        (
            "retired-model.md: missing "
            "viper._contract_traceability.RuleImplementation"
        ),
        "retired-model.md: ContractRequirement has unknown fields ['phase']",
    ]


def test_contract_traceability_model_block_matches_runtime() -> None:
    """Keep every documented traceability class and field aligned with Python."""
    text = CONTRACT_TRACEABILITY.read_text()
    section = text.split("## 4. Contract models", maxsplit=1)[1].split(
        "## 5. Execution", maxsplit=1
    )[0]
    block = _PYTHON_FENCE.search(section)
    assert block is not None

    tree = ast.parse(block.group("body"))
    documented = {
        node.name: tuple(
            child.target.id
            for child in node.body
            if isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    implemented = {
        model.__name__: tuple(model.model_fields) for model in TRACEABILITY_MODELS
    }

    assert documented == implemented


def test_contract_traceability_schema_describes_every_field() -> None:
    """Require each traceability field to explain its persisted role."""
    missing: dict[str, list[str]] = {}

    for model in TRACEABILITY_MODELS:
        properties = model.model_json_schema().get("properties", {})
        undescribed = sorted(
            field_name
            for field_name, field_schema in properties.items()
            if not field_schema.get("description", "").strip()
        )
        if undescribed:
            missing[model.__name__] = undescribed

    assert missing == {}


def test_traceability_declaration_ref_rejects_reversed_span() -> None:
    """Reject declaration evidence whose final line precedes its first line."""
    with pytest.raises(ValueError, match="end_line must be greater"):
        DeclarationRef(
            path="docs/development/example.md",
            start_line=2,
            end_line=1,
            sha256="0" * 64,
        )


def test_phase_zero_contract_traces_use_typed_outcomes() -> None:
    """Require concrete setup plus distinct accepted and rejected outcomes."""
    common_fields = {
        "trace_id",
        "requirement_id",
        "rule_id",
        "state",
        "scenario",
        "setup",
        "input",
        "invocation",
        "implementation",
        "test",
        "outcome",
    }
    retired_fields = {
        "declaration",
        "runtime",
        "persisted_evidence",
        "verifier",
        "expected",
    }

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
                assert set(outcome) == {"kind", "result", "evidence"}
                assert outcome["result"].strip()
                assert outcome["evidence"]
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

    planned_test_paths = {
        value.partition(":")[0]
        for definition in _PAIR_BLOCK_DEFINITION.finditer(
            CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
        )
        for value in tomllib.loads(definition.group("manifest"))["targets"]
        if value.startswith("tests/")
    }
    for requirement, (contract, expected_phase, test_path) in declarations.items():
        implementation = mappings["implements"][requirement]
        verification = mappings["verifies"][requirement]
        assert len(implementation) == 1, requirement
        assert len(verification) == 1, requirement
        assert implementation[0][0] == expected_phase, requirement
        assert verification[0][0] == expected_phase, requirement
        assert test_path.is_file() or (
            test_path.relative_to(ROOT).as_posix() in planned_test_paths
        ), test_path.relative_to(ROOT)
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
    """Require each named test module to exist or have one exact PairBlock."""
    named_tests = set(
        re.findall(
            r"tests/[a-z0-9_/]+\.py",
            MASTER_EXECUTION_CHECKLIST.read_text(),
        )
    )
    pair_guides = (
        PHASE_ZERO_PAIR_CODING,
        CONTRACT_TRACEABILITY_PAIR_CODING,
        SYSTEM_IMPACT_PAIR_CODING,
    )
    planned_tests = {
        value.partition(":")[0]
        for guide in pair_guides
        for definition in _PAIR_BLOCK_DEFINITION.finditer(
            guide.read_text(encoding="utf-8")
        )
        for value in tomllib.loads(definition.group("manifest"))["targets"]
        if value.startswith("tests/")
    }

    assert named_tests
    assert {
        name
        for name in named_tests
        if not (ROOT / name).is_file() and name not in planned_tests
    } == set()


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
        if path.name
        not in {"CHANGELOG.md", "0.1.0a1.md", "system-impact-compiler.md"}
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


def test_current_docs_import_public_functions_from_defining_modules() -> None:
    """Reject package-root names owned by a public submodule."""
    current_guides = tuple(
        path
        for path in PUBLIC_MARKDOWN
        if path.name
        not in {"CHANGELOG.md", "0.1.0a1.md", "system-impact-compiler.md"}
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
