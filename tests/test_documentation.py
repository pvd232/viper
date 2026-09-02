"""Keep the published documentation aligned with the executable package."""

from __future__ import annotations

import ast
import hashlib
import importlib
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

import viper._contract_traceability as traceability
from viper._contract_traceability import (
    ContractRequirement,
    ContractTraceabilityGraph,
    DeclarationRef,
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
CONTRACT_TRACEABILITY = ROOT / "docs/development/contract-traceability.md"
MODULE_OWNERSHIP = ROOT / "docs/development/module-ownership.md"
SYSTEM_IMPACT_COMPILER = ROOT / "docs/development/system-impact-compiler.md"
RESEARCH_MEMORY = ROOT / "docs/development/research-memory-roadmap.md"
RESEARCH_MEMORY_PAIR_CODING = ROOT / "docs/development/research-memory-pair-coding.md"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
WORKFLOWS = tuple(sorted((ROOT / ".github/workflows").glob("*.yml")))
RETIRED_SYSTEM_IMPACT_DOCUMENTS = (
    ROOT / "docs/development/system-impact-graph.md",
    ROOT / "docs/development/system-impact-phase-0-1-pair-coding.md",
    ROOT / "docs/development/system-impact-specification-review.md",
    ROOT / "docs/development/proof/graph_transformation/core-proof.md",
    ROOT / "docs/development/proof/graph_transformation/appendix-a-foundations.md",
)
MASTER_PHASE_ZERO_PAIR_CODING = ROOT / "docs/development/foundation-pair-coding.md"
CONTRACT_TRACEABILITY_PAIR_CODING = (
    ROOT / "docs/development/contract-traceability-pair-coding.md"
)
IMPLEMENTATION_CONTRACTS = (
    ROOT / "docs/development/contract-traceability.md",
    ROOT / "docs/development/project-data-root.md",
    MODULE_OWNERSHIP,
    SYSTEM_IMPACT_COMPILER,
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
    RESEARCH_MEMORY,
)

FOUNDATION_CONTRACTS = IMPLEMENTATION_CONTRACTS[:4]
CONTRACTS_WITH_COMPLETE_EXAMPLES = IMPLEMENTATION_CONTRACTS
TRACEABILITY_MODELS = (
    DeclarationRef,
    RepoSymbolRef,
    ContractRequirement,
    VerifierRule,
    RuleEdge,
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
_PHASE_HEADING = re.compile(r"^## \d+\. Master Phase (?P<phase>\d+)\b.*$", re.MULTILINE)
_PHASE_CAPABILITY = re.compile(
    r"<!-- phase-(?P<role>produces|consumes): "
    r"(?P<symbols>[A-Za-z0-9_., ]+) -->"
)
_CHECKBOX_BLOCK = re.compile(
    r"^- \[[ xX]\] .*?(?=^- \[[ xX]\] |^### |^## |\Z)",
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
_MASTER_PHASE_ZERO_SECTION = re.compile(
    r"^## 7\. Master Phase 0\b(?P<body>.*?)(?=^## 8\. Master Phase 1\b)",
    re.MULTILINE | re.DOTALL,
)
_MASTER_PHASE_ZERO_CHECKBOX = re.compile(
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
_FILE_PAIR_EDIT = re.compile(
    r"`(?P<path>(?:src|tests)/[a-z0-9_/]+\.py)`\s*\n\s*"
    r"```python pair-edit\n(?P<code>.*?)\n```",
    re.DOTALL,
)
_SYSTEM_PAIR_BLOCK_DEFINITION = re.compile(
    r"<!-- pair-block-definition: "
    r"(?P<id>P[01]-SIG-\d{2}|P0-PROOF-(?:09|10|11|12)) -->\n"
    r"```toml pair-block\n(?P<manifest>.*?)\n```\n"
    r"(?P<body>.*?)(?=<!-- pair-block-definition: |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_RESEARCH_PAIR_BLOCK_DEFINITION = re.compile(
    r"```toml pair-block\n"
    r'(?P<manifest>id = "P(?:18|19|20)-RML-\d{2}".*?\n)'
    r"```",
    re.DOTALL,
)
_RESEARCH_PAIR_BLOCK_MARKER = re.compile(
    r"<!-- pair-block: (?P<id>P(?:18|19|20)-RML-\d{2}) -->"
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
        "Compiler": "input",
        "Context": "input",
        "Traceability": "input",
        "Change": "input",
        "Bootstrap": "input",
        "Inventory": "proposed",
        "Database": "proposed",
        "Queries": "proposed",
        "Facts": "proposed",
        "Sites": "proposed",
        "Graph": "proposed",
        "ContractCompiler": "proposed",
        "Delta": "proposed",
        "Overlay": "proposed",
        "Support": "proposed",
        "GraphQueries": "proposed",
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
        "R0": "input",
        "K": "input",
        "X": "input",
        "Q0": "input",
        "W0": "input",
        "Q1": "input",
        "W1": "input",
        "Change": "input",
        "Decisions": "input",
        "DB0": "evidence",
        "Queries0": "evidence",
        "F0": "evidence",
        "DB1": "evidence",
        "Queries1": "evidence",
        "F1": "evidence",
        "CompileBase": "consumer",
        "CompileChange": "consumer",
        "GraphQueries": "consumer",
        "CompileWork": "consumer",
        "Execute": "consumer",
        "Observe": "consumer",
        "CheckTarget": "consumer",
        "Review": "consumer",
        "G0": "evidence",
        "PairBlocks": "evidence",
        "R1": "evidence",
        "G1": "evidence",
        "Delta": "output",
        "Impact": "output",
        "Closure": "output",
        "SCC": "output",
        "Tests": "output",
        "Coverage": "output",
        "Plan": "output",
        "Target": "output",
        "Repairs": "output",
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
        ("Baseline", "Database"),
        ("Compiler", "Database"),
        ("Database", "Queries"),
        ("Compiler", "Queries"),
        ("Queries", "Facts"),
        ("Queries", "Sites"),
        ("Sites", "Graph"),
        ("Facts", "Graph"),
        ("Inventory", "Graph"),
        ("Context", "Graph"),
        ("Traceability", "Graph"),
        ("Bootstrap", "Graph"),
        ("Change", "ContractCompiler"),
        ("Graph", "ContractCompiler"),
        ("ContractCompiler", "Delta"),
        ("Graph", "Overlay"),
        ("Delta", "Overlay"),
        ("Delta", "Support"),
        ("Overlay", "GraphQueries"),
        ("Support", "GraphQueries"),
        ("GraphQueries", "Closure"),
        ("GraphQueries", "SCC"),
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
        ("R0", "DB0"),
        ("K", "DB0"),
        ("DB0", "Queries0"),
        ("K", "Queries0"),
        ("Queries0", "F0"),
        ("F0", "CompileBase"),
        ("K", "CompileBase"),
        ("X", "CompileBase"),
        ("Q0", "CompileBase"),
        ("W0", "CompileBase"),
        ("CompileBase", "G0"),
        ("Change", "CompileChange"),
        ("G0", "CompileChange"),
        ("CompileChange", "Delta"),
        ("G0", "Impact"),
        ("Delta", "Impact"),
        ("Impact", "GraphQueries"),
        ("K", "GraphQueries"),
        ("GraphQueries", "Closure"),
        ("GraphQueries", "SCC"),
        ("Closure", "Tests"),
        ("Tests", "Coverage"),
        ("Closure", "Plan"),
        ("Decisions", "Plan"),
        ("G0", "Target"),
        ("Delta", "Target"),
        ("Plan", "Target"),
        ("SCC", "Repairs"),
        ("Target", "Repairs"),
        ("Repairs", "CompileWork"),
        ("Target", "CompileWork"),
        ("CompileWork", "PairBlocks"),
        ("PairBlocks", "Execute"),
        ("Execute", "R1"),
        ("R1", "DB1"),
        ("K", "DB1"),
        ("DB1", "Queries1"),
        ("K", "Queries1"),
        ("Queries1", "F1"),
        ("F1", "Observe"),
        ("X", "Observe"),
        ("K", "Observe"),
        ("Q1", "Observe"),
        ("W1", "Observe"),
        ("Observe", "G1"),
        ("G1", "CheckTarget"),
        ("Target", "CheckTarget"),
        ("CheckTarget", "Conformance"),
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
    trees = tuple(
        ast.parse(block, filename=str(contract))
        for block in _python_blocks(contract.read_text())
    )
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

    contract_functions = tuple(
        node
        for tree in trees
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    )
    refresh = next(
        node
        for node in contract_functions
        if node.name == "refresh"
        and any(argument.arg == "knowledge" for argument in node.args.kwonlyargs)
    )
    assert [argument.arg for argument in refresh.args.kwonlyargs] == [
        "runs",
        "knowledge",
    ]
    knowledge = next(
        node
        for node in contract_functions
        if node.name == "knowledge"
        and tuple(map(ast.unparse, node.decorator_list)) == ("property",)
    )
    assert tuple(map(ast.unparse, knowledge.decorator_list)) == ("property",)
    assert _normalized(knowledge.returns) == "KnowledgeCatalog"

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


def test_research_contract_preserves_learning_and_promotion_boundaries() -> None:
    """Bind the research loop to exact persisted decision and gate records."""
    classes = {
        name: next(node for path, node in values if path == RESEARCH_MEMORY)
        for name, values in _contract_class_definitions().items()
        if any(path == RESEARCH_MEMORY for path, _ in values)
    }
    expected_fields = {
        "ResearchObjective": {
            "schema_version",
            "objective_id",
            "question",
            "target_metrics",
            "admissible_evidence",
            "constraints",
            "created_by",
            "created_at",
        },
        "AnalysisPlan": {
            "estimand",
            "comparison",
            "metric_id",
            "direction",
            "minimum_effect",
            "interval_method",
            "confidence",
            "stopping_rule",
            "maximum_looks",
            "multiplicity_family",
            "multiplicity_rule",
        },
        "ExperimentSelection": {
            "schema_version",
            "objective",
            "hypothesis",
            "candidates",
            "scores",
            "selected",
            "policy",
            "evidence_snapshot",
            "budget",
            "random_seed",
            "selected_at",
        },
        "ResearchConstraint": {
            "constraint_id",
            "kind",
            "statement",
            "enforcement",
            "verifier_rule",
            "evidence",
        },
        "ResourceLimit": {"resource", "maximum", "unit"},
        "ResourceBudget": {
            "maximum_runs",
            "maximum_wall_seconds",
            "maximum_cost_usd",
            "maximum_gpu_seconds",
            "resource_limits",
        },
        "ExperimentCandidate": {
            "schema_version",
            "candidate_id",
            "hypothesis",
            "plan",
            "parent_plan",
            "expected_information_gain",
            "expected_utility",
            "expected_cost_usd",
            "constraint_ids",
            "supporting_evidence",
            "system_change_report",
        },
        "ResearchEpisode": {
            "schema_version",
            "episode_id",
            "objective",
            "hypothesis",
            "selection",
            "agent_policy",
            "model_invocations",
            "tool_invocations",
            "pair_blocks",
            "observations",
            "total_cost_usd",
            "total_wall_seconds",
            "review",
            "started_at",
            "ended_at",
        },
        "LearningDatasetManifest": {
            "schema_version",
            "dataset_id",
            "version",
            "target",
            "ontology",
            "catalog_snapshot",
            "cutoff_at",
            "splits",
            "leakage_checks",
            "origin_counts",
            "examples_sha256",
        },
        "DatasetMember": {"example", "group_id"},
        "DatasetSplit": {"name", "members"},
        "PolicyPromotionDecision": {
            "schema_version",
            "baseline_policy",
            "challenger_policy",
            "evaluation",
            "decision",
            "rollback_policy",
            "decided_by",
            "decided_at",
        },
        "AgentPolicyIdentity": {
            "schema_version",
            "policy_id",
            "version",
            "model",
            "system_prompt_sha256",
            "workflow_sha256",
            "retrieval_policy_sha256",
            "tool_schema_sha256",
            "memory_manifest",
            "policy_bundle",
            "implementation_commit",
        },
        "AgentToolInvocationReceipt": {
            "schema_version",
            "server",
            "server_version",
            "operation",
            "tool_schema_sha256",
            "request_sha256",
            "result_sha256",
            "task_id",
            "started_at",
            "ended_at",
            "terminal_status",
            "evidence",
        },
        "LiteratureClaim": {
            "schema_version",
            "work_version",
            "claim",
            "claim_kind",
            "anchors",
            "method_primitives",
            "extraction_origin",
            "extraction_policy",
            "review_status",
            "reviewed_by",
            "reviewed_at",
        },
        "LiteratureWork": {
            "schema_version",
            "work_id",
            "title",
            "authors",
            "venue",
            "doi",
            "primary_url",
        },
        "LiteratureVersion": {
            "schema_version",
            "work",
            "version_label",
            "publication_state",
            "retrieved_at",
            "content_sha256",
            "content",
            "prior_version",
        },
    }

    assert {
        name: {field for field, _, _ in _class_fields(classes[name])}
        for name in expected_fields
    } == expected_fields

    text = RESEARCH_MEMORY.read_text(encoding="utf-8")
    for feature in (
        "Discovery",
        "Resources",
        "Prompts",
        "Tools",
        "MRTR elicitation",
        "Tasks extension",
        "Subscriptions",
    ):
        assert f'["{feature}"]' in text
    assert "provider-backed model invocation" in text
    assert "--access learn" in RESEARCH_MEMORY_PAIR_CODING.read_text(encoding="utf-8")


def test_research_pair_guide_has_executable_ordered_blocks() -> None:
    """Bind every research PairBlock to exact targets, tests, inputs, and gate."""
    text = RESEARCH_MEMORY_PAIR_CODING.read_text(encoding="utf-8")
    manifests = tuple(
        tomllib.loads(match.group("manifest"))
        for match in _RESEARCH_PAIR_BLOCK_DEFINITION.finditer(text)
    )
    expected_ids = (
        "P18-RML-01",
        "P18-RML-02",
        "P18-RML-03",
        "P18-RML-04",
        "P18-RML-05",
        "P18-RML-06",
        "P19-RML-01",
        "P19-RML-02",
        "P19-RML-03",
        "P20-RML-01",
        "P20-RML-02",
        "P20-RML-03",
        "P20-RML-04",
    )
    assert tuple(manifest["id"] for manifest in manifests) == expected_ids

    prior_ids: set[str] = set()
    covered_requirements: set[str] = set()
    target_pattern = re.compile(
        r"^(?:src|tests)/[a-z0-9_/]+\.py:[A-Za-z_][A-Za-z0-9_.]*$"
    )
    planned_paths = {
        value.partition(":")[0]
        for manifest in manifests
        for value in manifest["targets"]
    }
    for manifest in manifests:
        block_id = manifest["id"]
        assert set(manifest) == {
            "id",
            "requirements",
            "depends_on",
            "targets",
            "tests",
            "gate",
        }
        assert manifest["requirements"]
        assert manifest["targets"]
        assert manifest["tests"]
        assert manifest["gate"].startswith("conda run -n mantra python -m pytest ")
        assert all(target_pattern.fullmatch(target) for target in manifest["targets"])
        assert all(target_pattern.fullmatch(test) for test in manifest["tests"])
        assert len(manifest["targets"]) == len(set(manifest["targets"]))
        assert len(manifest["tests"]) == len(set(manifest["tests"]))
        assert len(manifest["depends_on"]) == len(set(manifest["depends_on"]))
        for target in manifest["targets"]:
            target_path = target.partition(":")[0]
            assert (ROOT / target_path).is_file() or target_path in planned_paths
        for test in manifest["tests"]:
            test_path = test.partition(":")[0]
            assert (ROOT / test_path).is_file() or test_path in planned_paths
            assert test_path in manifest["gate"]
        for dependency in manifest["depends_on"]:
            assert dependency in prior_ids
        prior_ids.add(block_id)
        covered_requirements.update(manifest["requirements"])

    assert covered_requirements == {
        "RML-01",
        "RML-02",
        "RML-03",
        "RML-04",
        "RML-05",
        "RML-06",
        "PCM-06",
        "PCM-07",
    }
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    assert "owns the `P18-RML`, `P19-RML`, and" in checklist
    for phase in (18, 19, 20):
        assert f"Master Phase {phase} " in checklist


def test_research_checklist_tasks_resolve_to_pair_blocks() -> None:
    """Give every research PairBlock one checklist-owned task."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    research_sections = checklist.split("## 25. Master Phase 18", 1)[1].split(
        "## 28. Master Phase 21",
        1,
    )[0]
    marker_ids = [
        match.group("id")
        for match in _RESEARCH_PAIR_BLOCK_MARKER.finditer(research_sections)
    ]
    definition_ids = [
        tomllib.loads(match.group("manifest"))["id"]
        for match in _RESEARCH_PAIR_BLOCK_DEFINITION.finditer(
            RESEARCH_MEMORY_PAIR_CODING.read_text(encoding="utf-8")
        )
    ]

    assert marker_ids == definition_ids
    assert len(marker_ids) == len(set(marker_ids))
    for checkbox in _CHECKBOX_BLOCK.finditer(research_sections):
        markers = tuple(_RESEARCH_PAIR_BLOCK_MARKER.finditer(checkbox.group(0)))
        assert len(markers) <= 1, checkbox.group(0).splitlines()[0]


def test_contract_statuses_match_the_master_checklist() -> None:
    """Keep each governing contract's approval state in one vocabulary."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    rows = {
        match.group("path"): match.group("status")
        for match in re.finditer(
            r"^\| \[[^]]+\]\((?P<path>[a-z0-9-]+\.md)\) "
            r"\| (?P<status>[^|]+?) \|",
            checklist,
            re.MULTILINE,
        )
    }

    assert set(rows) >= {contract.name for contract in IMPLEMENTATION_CONTRACTS}
    for contract in IMPLEMENTATION_CONTRACTS:
        status = re.search(
            r"^\*\*Contract status:\*\* (?P<status>.+)$",
            contract.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert status is not None, contract
        documented = status.group("status").removesuffix(".").casefold()
        assert documented == rows[contract.name].casefold()


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


def test_contract_examples_are_complete() -> None:
    """Require every implementation contract to show and realize its delta."""
    failures: dict[str, str] = {}
    for contract in CONTRACTS_WITH_COMPLETE_EXAMPLES:
        try:
            traceability.validate_contract_example(contract)
        except traceability.ContractTraceabilityError as error:
            failures[contract.name] = str(error)

    assert failures == {}


def test_contracts_exclude_retired_trace_records() -> None:
    """Keep executable tests as the sole expected-outcome evidence."""
    documents = (*IMPLEMENTATION_CONTRACTS, ROOT / "docs/README.md")

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "```toml contract-trace" not in text, document
        assert re.search(r"\bContractTrace\b", text) is None, document

    assert "concrete trace" not in (ROOT / "docs/README.md").read_text(
        encoding="utf-8"
    )


def test_contract_traceability_dags_use_semantic_palette() -> None:
    """Keep each traceability DAG role bound to its declared color."""
    text = CONTRACT_TRACEABILITY.read_text()
    section = text.split("## 3. Current gap", maxsplit=1)[1].split(
        "## 4. Contract models", maxsplit=1
    )[0]
    diagrams = tuple(match.group("body") for match in _MERMAID_FENCE.finditer(section))

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
        SYSTEM_IMPACT_COMPILER.read_text(),
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


def test_system_impact_compiler_is_the_single_active_specification() -> None:
    """Keep the contract, proof, PairBlocks, and gates in one document."""
    text = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    opening = text.split("## 1. Status", 1)[0]
    pipeline = _MERMAID_FENCE.search(opening)

    assert pipeline is not None
    assert "flowchart TB" in pipeline.group("body")
    assert 'F0["CodeQLSourceFacts F0"]' in pipeline.group("body")
    assert 'F1["CodeQLSourceFacts F1"]' in pipeline.group("body")
    assert 'Check["evaluate_target_conformance()"]' in pipeline.group("body")
    assert all(not path.exists() for path in RETIRED_SYSTEM_IMPACT_DOCUMENTS)
    for required_section in (
        "## 1. Status",
        "## 7. Verification",
        "## 12. Core proof",
        "## 13. Detailed graph-transformation foundations",
        "## 14. Implementation plan and verification gates",
        "## 15. Research program",
    ):
        assert required_section in text

    documentation = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "docs").rglob("*.md")
    )
    for retired in RETIRED_SYSTEM_IMPACT_DOCUMENTS:
        assert retired.name not in documentation


def test_contract_and_schedule_names_are_canonical() -> None:
    """Keep capability names separate from checklist-owned phase names."""
    expected_titles = {
        CONTRACT_TRACEABILITY: "# Contract Traceability",
        CONTRACT_TRACEABILITY_PAIR_CODING: (
            "# Contract Traceability Pair-Coding Guide"
        ),
        MASTER_PHASE_ZERO_PAIR_CODING: "# Foundation Pair-Coding Guide",
        MASTER_EXECUTION_CHECKLIST: "# VIPER Master Execution Checklist",
        SYSTEM_IMPACT_COMPILER: "# System Impact Compiler",
        RESEARCH_MEMORY: "# Research Memory and Agent Learning",
        RESEARCH_MEMORY_PAIR_CODING: "# Research Memory Pair-Coding Guide",
    }
    for path, title in expected_titles.items():
        assert path.read_text(encoding="utf-8").splitlines()[0] == title

    retired_names = (
        ROOT / "docs/development/contract-requirement-traceability.md",
        ROOT / "docs/development/contract-traceability-phase-0-pair-coding.md",
        ROOT / "docs/development/phase-0-pair-coding.md",
    )
    assert not any(path.exists() for path in retired_names)

    for path in (ROOT / "docs/development").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^### Phase \d+", text, re.MULTILINE) is None
        if path != MASTER_EXECUTION_CHECKLIST:
            assert re.search(r"^## \d+\. Master Phase \d+", text, re.MULTILINE) is None


def test_contract_traceability_pair_guide_covers_each_cycle() -> None:
    """Require every CRT cycle to carry one exact parseable edit and gate."""
    text = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    headings = (
        "## 1. Status and boundary",
        "## 2. Pair-cycle contract",
        "## 3. Production PairBlocks",
        "## 4. Acceptance PairBlocks",
        "## 5. Pair execution",
        "## 6. Guide gate",
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

    manifests: dict[str, dict[str, Any]] = {}
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

        body = definition.group("body")
        assert body.count("**Context:**") == 1, block_id

        edits = tuple(_PAIR_EDIT.finditer(body))
        assert len(edits) == 1, block_id
        file_edits = tuple(_FILE_PAIR_EDIT.finditer(body))
        assert len(file_edits) == len(edits), block_id
        target_paths = {
            target.partition(":")[0] for target in manifest["targets"]
        }
        assert {edit.group("path") for edit in file_edits} <= target_paths, block_id
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
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
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
        target for manifest in manifests.values() for target in manifest["targets"]
    }
    order = {block_id: index for index, block_id in enumerate(expected_ids)}
    for block_id, manifest in manifests.items():
        assert all(target_pattern.fullmatch(target) for target in manifest["targets"])
        for target in manifest["targets"]:
            assert target.partition(":")[2] in declarations[block_id], (
                block_id,
                target,
            )
        for test in manifest["tests"]:
            test_path = test.partition(":")[0]
            assert (ROOT / test_path).is_file() or any(
                target.partition(":")[0] == test_path for target in all_targets
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

    pending_contracts = {contract.name for contract in IMPLEMENTATION_CONTRACTS[4:]}
    assert pending_contracts == {
        name for name in pending_contracts if f"`{name}`" in text
    }


def test_system_graph_stages_traceability_before_contract_change() -> None:
    """Keep CRT lowering inside G0 compilation and change compilation after G0."""
    proof = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    crt_guide = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    system_guide = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")

    assert "Q_0=\\operatorname{CompileTraceability}(R_0)" in proof
    assert "\\operatorname{CompileContractChange}(c_\\Delta,G_0)" in proof
    assert "R0 + K -> analyze_source_with_codeql() -> F0" in crt_guide
    assert "(F0, K, X, Q0, W0) -> compile_system() -> G0" in crt_guide
    assert "(ContractChange, G0)" in crt_guide
    assert "only traceability input accepted" not in crt_guide

    definition = next(
        item
        for item in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(system_guide)
        if item.group("id") == "P0-SIG-04"
    )
    manifest = tomllib.loads(definition.group("manifest"))
    assert manifest["depends_on"] == ["P0-CRT-05", "P0-SIG-03"]
    assert "ingest_contract_traceability" in " ".join(manifest["targets"])
    assert "compile_contract_change" in " ".join(manifest["targets"])
    body = " ".join(definition.group("body").split())
    assert "Derive `ContractTraceabilityGraph`" not in body
    assert body.index("Consume the `ContractTraceabilityGraph`") < (
        body.index("After `G0` exists")
    )


def test_system_impact_proof_uses_complete_compiler_boundary() -> None:
    """Keep every proof compiler step explicit and every subsection numbered."""
    proof = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    research = proof.split("## 15. Research program", 1)[1]
    core = proof.split("## 12. Core proof", 1)[1].split(
        "## 13. Detailed graph-transformation foundations",
        1,
    )[0]

    baseline = "R_0&\\xrightarrow{\\operatorname{AnalyzeCodeQL}_K}F_0"
    baseline_lowering = "(F_0,Q_0,W_0)&\\xrightarrow{\\mathcal C_{X,K}}G_0"
    observed = "R_1\\xrightarrow{\\operatorname{AnalyzeCodeQL}_K}F_1"
    observed_lowering = "(F_1,Q_1,W_1)&\\xrightarrow{\\mathcal C_{X,K}}G_1"
    assert research.count(baseline) == 2
    assert research.count(baseline_lowering) == 2
    assert research.count(observed) == 2
    assert research.count(observed_lowering) == 2
    assert baseline in core
    assert baseline_lowering in core
    assert observed.replace("R_1", "R_1&", 1) in core
    assert observed_lowering in core
    assert "\\longrightarrow(Q_0,W_0)\\longrightarrow G_0" not in proof
    assert "\\longrightarrow(Q_1,W_1)\\longrightarrow G_1" not in proof

    subsection_numbers = re.findall(r"^### (12\.\d+) ", core, re.MULTILINE)
    assert subsection_numbers == [f"12.{number}" for number in range(1, 14)]


def test_contract_traceability_pair_guide_executes_as_one_workflow(
    tmp_path: Path,
) -> None:
    """Execute the proposed CRT code and every focused acceptance case."""
    text = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    definitions: dict[str, str] = {}
    for definition in _PAIR_BLOCK_DEFINITION.finditer(text):
        edit = _PAIR_EDIT.search(definition.group("body"))
        assert edit is not None
        definitions[definition.group("id")] = edit.group("code")

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
        "test_contract_examples_reject_incomplete_structure",
        "test_contract_examples_reject_undeclared_inventory_symbol",
        "test_contract_examples_reject_unused_inventory_symbol",
        "test_contract_traceability_graph_is_canonical",
        "test_contract_traceability_graph_rejects_duplicate_ids",
    )
    for index, test_name in enumerate(tests):
        case_root = tmp_path / str(index)
        case_root.mkdir()
        namespace[test_name](case_root)


def test_phase_zero_checkboxes_have_complete_ordered_pair_blocks() -> None:
    """Bind every Master Phase 0 task to one parseable ordered edit."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    phase_match = _MASTER_PHASE_ZERO_SECTION.search(checklist)
    assert phase_match is not None
    checkboxes = tuple(_MASTER_PHASE_ZERO_CHECKBOX.finditer(phase_match.group("body")))
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

    reference = MASTER_PHASE_ZERO_PAIR_CODING.read_text(encoding="utf-8")
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
    contract_reference = CONTRACT_TRACEABILITY_PAIR_CODING.read_text(encoding="utf-8")
    contract_definitions = tuple(
        definition for definition in _PAIR_BLOCK_DEFINITION.finditer(contract_reference)
    )
    system_reference = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
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
        for contract in FOUNDATION_CONTRACTS
        for match in _CONTRACT_REQUIREMENT.finditer(
            contract.read_text(encoding="utf-8")
        )
    }
    manifests: dict[str, dict[str, Any]] = {}
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

        body = definition.group("body")
        if block_id.startswith("P0-PDR-"):
            assert body.count("**Context:**") == 1, block_id
        edits = tuple(_PAIR_EDIT.finditer(body))
        edit_tree: ast.Module | None = None
        if block_id.startswith("P0-SIG-") or block_id in {
            "P0-PROOF-09",
            "P0-PROOF-10",
            "P0-PROOF-11",
            "P0-PROOF-12",
        }:
            assert not edits, block_id
            assert _PAIR_PLACEHOLDER.search(definition.group("body")) is None
        else:
            assert edits, block_id
            if len(edits) > 1:
                file_edits = tuple(_FILE_PAIR_EDIT.finditer(body))
                assert len(file_edits) == len(edits), block_id
                edit_paths = [edit.group("path") for edit in file_edits]
                assert len(edit_paths) == len(set(edit_paths)), block_id
                target_paths = {
                    target.partition(":")[0] for target in manifest["targets"]
                }
                assert set(edit_paths) <= target_paths, block_id

            trees: list[ast.Module] = []
            for edit in edits:
                code = edit.group("code")
                assert _PAIR_PLACEHOLDER.search(code) is None, block_id
                trees.append(
                    ast.parse(
                        code,
                        filename=(
                            f"{MASTER_PHASE_ZERO_PAIR_CODING.name}:{block_id}"
                        ),
                    )
                )
            edit_tree = ast.Module(
                body=[node for tree in trees for node in tree.body],
                type_ignores=[],
            )
        if block_id not in implemented_ids and edits:
            assert edit_tree is not None
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
                        node.targets if isinstance(node, ast.Assign) else (node.target,)
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
    """Bind each high-return Master Phase 1 task to one ordered block."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    section = checklist.split("### 8.0 System Impact hardening", 1)[1].split(
        "### 8.1 Local publication interface",
        1,
    )[0]
    marker_ids = re.findall(r"<!-- pair-block: (P1-SIG-\d{2}) -->", section)
    assert marker_ids == ["P1-SIG-01", "P1-SIG-02", "P1-SIG-03", "P1-SIG-04"]

    reference = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    definitions = {
        match.group("id"): tomllib.loads(match.group("manifest"))
        for match in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(reference)
        if match.group("id").startswith("P1-SIG-")
    }
    assert set(definitions) == set(marker_ids)
    available = {
        match.group("id") for match in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(reference)
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
    reference = MASTER_PHASE_ZERO_PAIR_CODING.read_text(encoding="utf-8")

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
    assert {name: _normalized(node) for name, node in source_operations.items()} == {
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
        node.name: node for node in api_source.body if isinstance(node, ast.FunctionDef)
    }
    target_handlers = {
        node.name: node for node in api_target.body if isinstance(node, ast.FunctionDef)
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
    added_helpers = {"_root", "_local_fetcher"}
    assert target_handlers.keys() == source_handlers.keys() | added_helpers
    unchanged = source_handlers.keys() - root_migration
    assert {name: _normalized(source_handlers[name]) for name in unchanged} == {
        name: _normalized(target_handlers[name]) for name in unchanged
    }


def test_phase_zero_system_models_match_contract() -> None:
    """Keep the unified SystemGraph vocabulary complete and internally equal."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
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
        assert f'"{value}"' in specification
    assert "source depends on the target" in specification
    assert "source depends on target" in specification
    assert 'ContractCompiler -->|"PairBlocks"| Plan' not in specification
    assert "PairReference" not in specification
    assert 'GraphQueries -->|"mutual reachability"| SCC' in specification
    assert 'Target -->|"hard constraints"| Repairs' in specification
    assert "compile_work()" in specification
    assert 'Execute -->|"writes"| R1' in specification


def test_system_impact_codeql_backend_is_end_to_end() -> None:
    """Keep the pinned CodeQL backend at both compiler boundaries."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")

    for value in (
        'cli_version: Literal["2.26.4"]',
        "class CodeQLSourceFacts(ProtocolModel)",
        "class CodeQLAnalysisReceipt(ProtocolModel)",
        "source_analysis: CodeQLAnalysisReceipt",
        "def analyze_source_with_codeql(",
        "F_0=\\operatorname{AnalyzeCodeQL}_K(R_0)",
        "F_1=\\operatorname{AnalyzeCodeQL}_K(R_1)",
        "reject every unsupported or unresolved dependency site",
        "tests/test_system_graph_codeql.py:test_codeql_source_fact_oracle_parity",
    ):
        assert value in specification

    for rule in (
        "system.codeql.identity",
        "system.codeql.database",
        "system.codeql.queries",
        "system.codeql.facts",
        "system.codeql.parity",
    ):
        assert f"rule={rule}" in checklist

    assert "Production extraction owns\nthe parser" not in checklist
    assert "reject every\n      unsupported or unresolved dependency site" in checklist


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
        ("retired-model.md: missing viper._contract_traceability.RuleImplementation"),
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
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
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
    assert len(phase_matches) == 22
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

    assert set(phase_text) == set(range(0, 22))

    declared = set(declarations)
    assert set(mappings["implements"]) == declared
    assert set(mappings["verifies"]) == declared

    planned_test_paths = {
        value.partition(":")[0]
        for guide in (CONTRACT_TRACEABILITY_PAIR_CODING, SYSTEM_IMPACT_COMPILER)
        for definition in _PAIR_BLOCK_DEFINITION.finditer(
            guide.read_text(encoding="utf-8")
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


def test_contracts_retain_propagation_sections() -> None:
    """Require every governing contract to retain its propagation section."""
    for contract in IMPLEMENTATION_CONTRACTS:
        text = contract.read_text()
        match = re.search(
            r"^## \d+\. Propagation[^\n]*\n(?P<body>.*?)(?=^## |\Z)",
            text,
            re.M | re.S,
        )
        assert match is not None, contract.name
        assert match.group("body").strip(), contract.name


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
    assert int(phases[-1].group("phase")) == 21
    terminal = checklist[phases[-1].start() :]
    earlier = checklist[: phases[-1].start()]

    for command in ("make check", "make check-integration", "make check-release"):
        assert command in terminal
        assert command not in earlier
    assert (
        "Install the wheel with the `mcp`, `knowledge`, and `research` extras"
        in terminal
    )


def test_release_workflow_copies_only_existing_acceptance_inputs() -> None:
    """Require every copied release-acceptance input to exist in the repository."""
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    copy_commands = re.findall(
        r'^\s*cp -R (?P<sources>.+?) "\$ACCEPTANCE_ROOT/"$',
        workflow,
        flags=re.MULTILINE,
    )

    assert copy_commands
    for sources in copy_commands:
        for source in sources.split():
            assert (ROOT / source).exists(), source


def test_workflows_pin_actions_to_full_commit_shas() -> None:
    """Require immutable full-length commit references for external actions."""
    references = tuple(
        (match.group("action"), match.group("revision"))
        for workflow in WORKFLOWS
        for match in re.finditer(
            r"uses:\s+(?P<action>[^\s@]+)@(?P<revision>[^\s#]+)",
            workflow.read_text(encoding="utf-8"),
        )
    )

    assert references
    for action, revision in references:
        assert re.fullmatch(r"[0-9a-f]{40}", revision), action


def test_workflows_limit_token_and_checkout_credentials() -> None:
    """Keep workflow tokens read-only and remove unused checkout credentials."""
    checkout = re.compile(
        r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n"
        r"\s+with:\n"
        r"\s+persist-credentials: false"
    )

    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert re.search(r"^permissions:\n  contents: read$", text, re.MULTILINE)
        assert len(checkout.findall(text)) == text.count("uses: actions/checkout@")


def test_wheel_smoke_gates_use_the_public_module_contract() -> None:
    """Run the installed-package inventory instead of expecting root exports."""
    workflows = "\n".join(
        workflow.read_text(encoding="utf-8") for workflow in WORKFLOWS
    )

    assert "viper.__all__" not in workflows
    assert workflows.count("python -I -m pytest tests/test_public_api.py -q") >= 4


def test_system_impact_status_matches_the_master_checklist() -> None:
    """Keep the approved design state distinct from pending implementation."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")

    assert (
        "**Contract status:** approved design; implementation pending." in specification
    )
    assert (
        "| [System Impact Compiler](system-impact-compiler.md) "
        "| Approved design; implementation pending |" in checklist
    )


def test_system_impact_rule_owners_use_pair_block_nomenclature() -> None:
    """Keep verifier owners on the exact planned implementation symbols."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    required_owners = {
        "src/viper/system_graph.py:condense_affected_graph",
        "src/viper/system_graph.py:compile_propagation_plan",
        "src/viper/system_graph.py:compile_system_change",
    }
    retired_owners = {
        "src/viper/system_graph.py:condense_system_graph",
        "src/viper/system_graph.py:verify_propagation",
        "src/viper/system_graph.py:compare_observed_graph",
    }

    owners = set(
        re.findall(r"contract-implementation: [^>]+ owner=([^ ]+) -->", checklist)
    )
    assert required_owners <= owners
    assert retired_owners.isdisjoint(owners)


def test_system_impact_contract_covers_codeql_boundary() -> None:
    """Keep every CodeQL-owned implementation surface in its contract."""
    contract = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    for path in (
        "src/viper/_system_graph/codeql.py",
        "tools/codeql/viper-system-graph/",
        "tests/test_system_graph_codeql.py",
    ):
        assert f"`{path}`" in contract


def test_master_checklist_names_existing_test_modules() -> None:
    """Require each named test module to exist or have one exact PairBlock."""
    named_tests = set(
        re.findall(
            r"tests/[a-z0-9_/]+\.py",
            MASTER_EXECUTION_CHECKLIST.read_text(),
        )
    )
    pair_guides = (
        MASTER_PHASE_ZERO_PAIR_CODING,
        CONTRACT_TRACEABILITY_PAIR_CODING,
        SYSTEM_IMPACT_COMPILER,
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


def test_explanation_names_the_current_release() -> None:
    """Keep the explanatory guide linked to the package's current release report."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    explanation = (ROOT / "docs/explanation/how-viper-works.md").read_text()

    assert f"VIPER `{package_version}` is available from PyPI." in explanation
    assert f"[release report](../releases/{package_version}.md)" in explanation


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
        if path.name not in {"CHANGELOG.md", "0.1.0a1.md", "system-impact-compiler.md"}
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
