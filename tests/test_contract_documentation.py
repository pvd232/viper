"""Verify contract documents, PairBlocks, and checklist traceability."""

from __future__ import annotations

import ast
import hashlib
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import viper._contract_traceability as traceability
from tests._documentation import (
    CONTRACT_BASELINE_DATA,
    CONTRACT_BASELINE_MANIFEST,
    CONTRACTS_WITH_COMPLETE_EXAMPLES,
    IMPLEMENTATION_CONTRACTS,
    MASTER_EXECUTION_CHECKLIST,
    ROOT,
    class_bases,
    class_fields,
    class_methods,
    normalized,
    numbered_contract_section,
    python_blocks,
)
from tools.refresh_contract_baselines import rendered_manifest
from viper._contract_traceability import (
    ContractRequirement,
    ContractTarget,
    ContractTraceabilityGraph,
    DeclarationRef,
    PairBlock,
    RepoSymbolRef,
    RuleEdge,
    VerifierRule,
)

EXTERNAL_INPUT_ROOTS = ROOT / "docs/development/external-input-roots.md"

CONTRACT_TRACEABILITY = ROOT / "docs/development/contract-traceability.md"

MODULE_OWNERSHIP = ROOT / "docs/development/module-ownership.md"

SYSTEM_IMPACT_COMPILER = ROOT / "docs/development/system-impact-compiler.md"

RESEARCH_MEMORY = ROOT / "docs/development/research-memory-roadmap.md"

RESEARCH_MEMORY_PAIR_CODING = ROOT / "docs/development/research-memory-pair-coding.md"

MASTER_PHASE_ZERO_PAIR_CODING = ROOT / "docs/development/foundation-pair-coding.md"

FOUNDATION_CONTRACTS = IMPLEMENTATION_CONTRACTS[:4]

TRACEABILITY_MODELS = (
    DeclarationRef,
    RepoSymbolRef,
    ContractRequirement,
    VerifierRule,
    RuleEdge,
    ContractTarget,
    PairBlock,
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

_PHASE_HEADING = re.compile(r"^## \d+\. Master Phase (?P<phase>\d+)\b.*$", re.MULTILINE)

_SUBSECTION_HEADING = re.compile(
    r"^### (?P<section>\d+\.\d+)\s+.+$",
    re.MULTILINE,
)

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

_TRACEABILITY_MODEL_FENCE = re.compile(
    r"```python contract-target\n(?P<body>.*?)\n```",
    re.DOTALL,
)

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

_CONTENT_PAIR_BLOCK_MARKER = re.compile(
    r"<!-- pair-block: (?P<id>P[0-9]+-[A-Z]+-\d{2}) -->"
)

_PAIR_BLOCK_CONTRACT = re.compile(
    r"<!-- pair-block-contract: (?P<id>P[0-9]+-[A-Z]+-\d{2}) "
    r"contract=(?P<contract>[a-z0-9-]+\.md) -->"
)

_RULE_EDGE_STATE = re.compile(
    r"<!-- contract-(?:implementation|verification): "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) "
    r"rule=[a-z][a-z0-9_.]+ state=(?P<state>planned|implemented) "
)

_PAIR_BLOCK_DEFINITION = re.compile(
    r"<!-- pair-block-definition: (?P<id>P[0-9]+-[A-Z]+-\d{2}) -->\n"
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
        "evidence": "fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px",
        "implementation": "fill:#312e81,stroke:#a5b4fc,color:#ffffff,stroke-width:2px",
        "output": "fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px",
    },
)

SYSTEM_IMPACT_DAG_ROLES = (
    {
        "Contract": "current",
        "Edges": "evidence",
        "Blocks": "evidence",
        "Source": "evidence",
        "Gap": "gap",
    },
    {
        "Plan": "proposed",
        "Freeze": "proposed",
        "Identity": "proposed",
        "Baseline": "proposed",
        "Impact": "proposed",
        "Realized": "proposed",
        "Resolved": "proposed",
        "Target": "proposed",
        "Gates": "proposed",
        "Dependencies": "proposed",
        "Check": "proposed",
        "Commit": "proposed",
        "Acceptance": "proposed",
    },
    {
        "Requirement": "contract",
        "Target": "contract",
        "Rule": "contract",
        "CTG": "contract",
        "Block": "checklist",
        "CodeQL": "evidence",
        "G0": "evidence",
        "Gs": "evidence",
        "Impact": "evidence",
        "Execute": "implementation",
        "Freeze": "implementation",
        "Commit": "implementation",
        "Resolved": "output",
        "Gates": "implementation",
        "Dependencies": "output",
        "Check": "output",
        "Acceptance": "output",
    },
)

SYSTEM_IMPACT_DAG_EDGES = (
    {
        ("Contract", "Edges"),
        ("Blocks", "Source"),
        ("Edges", "Gap"),
        ("Source", "Gap"),
    },
    {
        ("Plan", "Freeze"),
        ("Plan", "Check"),
        ("Identity", "Baseline"),
        ("Baseline", "Impact"),
        ("Freeze", "Resolved"),
        ("Freeze", "Realized"),
        ("Identity", "Realized"),
        ("Baseline", "Resolved"),
        ("Resolved", "Impact"),
        ("Resolved", "Target"),
        ("Realized", "Target"),
        ("Impact", "Check"),
        ("Target", "Check"),
        ("Plan", "Gates"),
        ("Gates", "Check"),
        ("Baseline", "Dependencies"),
        ("Dependencies", "Check"),
        ("Freeze", "Commit"),
        ("Check", "Commit"),
        ("Commit", "Acceptance"),
        ("Check", "Acceptance"),
    },
    {
        ("Requirement", "Target"),
        ("Requirement", "Rule"),
        ("Target", "Block"),
        ("Rule", "Block"),
        ("Requirement", "CTG"),
        ("Target", "CTG"),
        ("Rule", "CTG"),
        ("Block", "CTG"),
        ("CodeQL", "G0"),
        ("CTG", "G0"),
        ("G0", "Impact"),
        ("Block", "Execute"),
        ("Execute", "Freeze"),
        ("CTG", "Freeze"),
        ("Freeze", "Gs"),
        ("Freeze", "Resolved"),
        ("CodeQL", "Gs"),
        ("Resolved", "Impact"),
        ("CTG", "Check"),
        ("Resolved", "Check"),
        ("G0", "Check"),
        ("Gs", "Check"),
        ("Impact", "Check"),
        ("Block", "Gates"),
        ("Gates", "Check"),
        ("G0", "Dependencies"),
        ("Dependencies", "Check"),
        ("Freeze", "Check"),
        ("Freeze", "Commit"),
        ("Check", "Commit"),
        ("Commit", "Acceptance"),
        ("Check", "Acceptance"),
    },
)


def _contract_classdefinitions() -> dict[str, list[tuple[Path, ast.ClassDef]]]:
    """Collect every top-level class shown by the active contracts."""
    classes: dict[str, list[tuple[Path, ast.ClassDef]]] = {}
    for contract in IMPLEMENTATION_CONTRACTS:
        for block in python_blocks(contract.read_text()):
            tree = ast.parse(block, filename=str(contract))
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    classes.setdefault(node.name, []).append((contract, node))
    return classes


def test_repeated_contract_classes_have_identical_declarations() -> None:
    """Reject two active contracts that assign different fields to one class."""
    definitions = _contract_classdefinitions()
    repeated = {name: values for name, values in definitions.items() if len(values) > 1}

    assert repeated
    mismatches = {}
    for name, values in sorted(repeated.items()):
        declarations = {
            (class_bases(node), class_fields(node), class_methods(node))
            for _, node in values
        }
        if len(declarations) > 1:
            mismatches[name] = {
                path.name: (
                    class_bases(node),
                    class_fields(node),
                    class_methods(node),
                )
                for path, node in values
            }

    assert mismatches == {}


def test_catalog_contract_exposes_every_promised_query_field() -> None:
    """Bind catalog questions to exact typed filters and result methods."""
    contract = ROOT / "docs/development/provenance-catalog-mcp.md"
    classes = {
        name: next(node for path, node in values if path == contract)
        for name, values in _contract_classdefinitions().items()
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
        name: {field for field, _, _ in class_fields(classes[name])}
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
        for block in python_blocks(contract.read_text())
    )
    classes = {
        name: next(node for path, node in values if path == contract)
        for name, values in _contract_classdefinitions().items()
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
        name: {field for field, _, _ in class_fields(classes[name])}
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
        "benchmarks",
        "knowledge",
    ]
    knowledge = next(
        node
        for node in contract_functions
        if node.name == "knowledge"
        and tuple(map(ast.unparse, node.decorator_list)) == ("property",)
    )
    assert tuple(map(ast.unparse, knowledge.decorator_list)) == ("property",)
    assert normalized(knowledge.returns) == "KnowledgeCatalog"

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
        for name, values in _contract_classdefinitions().items()
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
        name: {field for field, _, _ in class_fields(classes[name])}
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
        assert "python -m pytest " in str(manifest["gate"])
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


def test_pair_blocks_map_to_contract_sections_and_derived_status() -> None:
    """Map each content-changing block to one contract, section, and state."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    contract_names = {contract.name for contract in IMPLEMENTATION_CONTRACTS}
    headings = tuple(_SUBSECTION_HEADING.finditer(checklist))
    mappings: dict[str, tuple[str, str, bool]] = {}

    for checkbox in _CHECKBOX_BLOCK.finditer(checklist):
        markers = tuple(_CONTENT_PAIR_BLOCK_MARKER.finditer(checkbox.group(0)))
        if not markers:
            continue
        assert len(markers) == 1, checkbox.group(0).splitlines()[0]
        marker = markers[0]
        contract_markers = tuple(_PAIR_BLOCK_CONTRACT.finditer(checkbox.group(0)))
        assert len(contract_markers) == 1, checkbox.group(0).splitlines()[0]
        contract_marker = contract_markers[0]
        block_id = marker.group("id")
        assert contract_marker.group("id") == block_id
        contract = contract_marker.group("contract")
        assert block_id not in mappings
        assert contract in contract_names
        section = next(
            heading.group("section")
            for heading in reversed(headings)
            if heading.start() < checkbox.start()
        )
        mappings[block_id] = (
            contract,
            section,
            checkbox.group(0).startswith("- [x]"),
        )

    assert mappings
    statuses = {
        match.group("path"): match.group("status").casefold()
        for match in re.finditer(
            r"^\| \[[^]]+\]\((?P<path>[a-z0-9-]+\.md)\) "
            r"\| (?P<status>[^|]+?) \|",
            checklist,
            re.MULTILINE,
        )
    }
    for contract in {mapping[0] for mapping in mappings.values()}:
        completed = [
            complete
            for mapped_contract, _, complete in mappings.values()
            if mapped_contract == contract
        ]
        contract_path = ROOT / "docs" / "development" / contract
        requirement_ids = {
            match.group("requirement")
            for match in _CONTRACT_REQUIREMENT.finditer(
                contract_path.read_text(encoding="utf-8")
            )
        }
        requirement_states = {
            requirement: [
                match.group("state") == "implemented"
                for match in _RULE_EDGE_STATE.finditer(checklist)
                if match.group("requirement") == requirement
            ]
            for requirement in requirement_ids
        }
        requirements_complete = all(
            states and all(states) for states in requirement_states.values()
        )
        implementation_started = any(
            any(states) for states in requirement_states.values()
        )
        expected = (
            "complete"
            if all(completed) and requirements_complete
            else "in progress"
            if any(completed) or implementation_started
            else "planned"
        )
        assert statuses[contract].split(";", 1)[0] == expected


def test_contract_examples_are_complete() -> None:
    """Require every implementation contract to show and realize its delta."""
    failures: dict[str, str] = {}
    for contract in CONTRACTS_WITH_COMPLETE_EXAMPLES:
        try:
            traceability.validate_contract_example(contract)
        except traceability.ContractTraceabilityError as error:
            failures[contract.name] = str(error)

    assert failures == {}


def test_contracts_use_the_active_traceability_grammar() -> None:
    """Keep executable tests as the sole expected-outcome evidence grammar."""
    documents = (*IMPLEMENTATION_CONTRACTS, ROOT / "docs/README.md")

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "```toml contract-trace" not in text, document
        assert re.search(r"\bContractTrace\b", text) is None, document


def test_contract_traceability_dags_use_semantic_palette() -> None:
    """Keep each traceability DAG role bound to its declared color."""
    text = CONTRACT_TRACEABILITY.read_text()
    section = text.split("## 3. Current gap", maxsplit=1)[1].split(
        "## 4. Models", maxsplit=1
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
    current_gap = numbered_contract_section(MODULE_OWNERSHIP.read_text(), 3)
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
    current_gap = numbered_contract_section(
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


def test_system_impact_check_is_the_single_active_specification() -> None:
    """Keep the bounded check, PairBlocks, and gates in one document."""
    text = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    for required_section in (
        "## 1. Status",
        "## 7. Verification",
        "## 10. Implementation order",
    ):
        assert required_section in text
    for required_boundary in (
        "validated ContractTraceabilityGraph",
        "CodeQL baseline source graph",
        "CodeQL candidate source graph",
        "reject unplanned source changes",
    ):
        assert required_boundary in text


def test_contract_and_schedule_names_are_canonical() -> None:
    """Keep capability names separate from checklist-owned phase names."""
    expected_titles = {
        CONTRACT_TRACEABILITY: "# Contract Traceability",
        MASTER_PHASE_ZERO_PAIR_CODING: "# Foundation Pair-Coding Guide",
        MASTER_EXECUTION_CHECKLIST: "# VIPER Master Execution Checklist",
        SYSTEM_IMPACT_COMPILER: "# System Impact Check",
        RESEARCH_MEMORY: "# Research Memory and Agent Learning",
        RESEARCH_MEMORY_PAIR_CODING: "# Research Memory Pair-Coding Guide",
    }
    for path, title in expected_titles.items():
        assert path.read_text(encoding="utf-8").splitlines()[0] == title

    for path in (ROOT / "docs/development").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^### Phase \d+", text, re.MULTILINE) is None
        if path != MASTER_EXECUTION_CHECKLIST:
            assert re.search(r"^## \d+\. Master Phase \d+", text, re.MULTILINE) is None


def test_contract_traceability_owns_active_pair_blocks() -> None:
    """Keep each active CRT implementation block in its governing contract."""
    text = CONTRACT_TRACEABILITY.read_text(encoding="utf-8")
    definitions = tuple(_PAIR_BLOCK_DEFINITION.finditer(text))
    assert tuple(item.group("id") for item in definitions) == (
        "P0-CRT-06",
        "P0-CRT-07",
        "P0-PROOF-08",
        "P1-CRT-01",
    )

    for definition in definitions:
        manifest = tomllib.loads(definition.group("manifest"))
        assert manifest["id"] == definition.group("id")
        assert set(manifest) in (
            {
                "id",
                "requirements",
                "targets",
                "tests",
                "gate",
                "depends_on",
            },
            {
                "id",
                "requirements",
                "targets",
                "assets",
                "tests",
                "gate",
                "depends_on",
            },
        )
        assert manifest["requirements"]
        assert manifest["targets"]
        assert manifest["tests"]
        assert "python -m pytest " in str(manifest["gate"])
        assert definition.group("body").count("**Context:**") == 1

    assert text.count("class ContractTarget(ProtocolModel):") == 1
    assert text.count("class PairBlock(ProtocolModel):") == 1


def test_module_ownership_contract_owns_each_pair_block() -> None:
    """Require every MOD cycle to live in its governing contract."""
    text = MODULE_OWNERSHIP.read_text(encoding="utf-8")
    definitions = tuple(_PAIR_BLOCK_DEFINITION.finditer(text))
    expected_ids = (
        "P0-MOD-01",
        "P0-MOD-02",
        "P0-MOD-03",
        "P0-MOD-04",
    )
    assert tuple(item.group("id") for item in definitions) == expected_ids

    manifests: dict[str, dict[str, Any]] = {}
    order = {block_id: index for index, block_id in enumerate(expected_ids)}
    for definition in definitions:
        block_id = definition.group("id")
        manifest = tomllib.loads(definition.group("manifest"))
        assert manifest["id"] == block_id
        assert set(manifest) in (
            {
                "id",
                "requirements",
                "targets",
                "tests",
                "gate",
                "depends_on",
            },
            {
                "id",
                "requirements",
                "targets",
                "assets",
                "tests",
                "gate",
                "depends_on",
            },
        )
        assert manifest["requirements"] == ["MOD-01"]
        assert manifest["targets"]
        assert manifest["tests"]
        assert "python -m pytest " in str(manifest["gate"])

        body = definition.group("body")
        assert body.count("**Context:**") == 1, block_id
        edits = tuple(_TRACEABILITY_MODEL_FENCE.finditer(body))
        file_edits = tuple(
            re.finditer(
                r"`(?P<path>(?:src|tests)/[a-z0-9_/]+\.py)`\s*\n\s*"
                r"(?:<!-- contract-target: [^\n]+ -->\s*)+"
                r"```python contract-target\n(?P<code>.*?)\n```",
                body,
                re.DOTALL,
            )
        )
        assert edits, block_id
        assert len(file_edits) == len(edits), block_id
        assert len({edit.group("path") for edit in file_edits}) == len(edits)
        target_paths = {target.partition(":")[0] for target in manifest["targets"]}
        assert {edit.group("path") for edit in file_edits} <= target_paths, block_id
        symbols_by_path: dict[str, set[str]] = {}
        for edit in edits:
            assert _PAIR_PLACEHOLDER.search(edit.group("body")) is None, block_id
            ast.parse(
                edit.group("body"),
                filename=f"{MODULE_OWNERSHIP.name}:{block_id}",
            )
        for edit in file_edits:
            tree = ast.parse(edit.group("code"))
            symbols: set[str] = set()
            for node in tree.body:
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    symbols.add(node.name)
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        node.targets if isinstance(node, ast.Assign) else (node.target,)
                    )
                    symbols.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    symbols.update(
                        alias.asname or alias.name.rpartition(".")[2]
                        for alias in node.names
                    )
            symbols_by_path[edit.group("path")] = symbols
        for target in manifest["targets"]:
            path, _, symbol = target.partition(":")
            assert symbol in symbols_by_path[path], (block_id, target)
        manifests[block_id] = manifest

    for block_id, manifest in manifests.items():
        dependencies = manifest["depends_on"]
        assert len(dependencies) == len(set(dependencies)), block_id
        for dependency in dependencies:
            if dependency == "P0-CRT-06":
                continue
            assert dependency in manifests, (block_id, dependency)
            assert order[dependency] < order[block_id], (block_id, dependency)


def test_system_impact_consumes_the_closed_ctg_plan() -> None:
    """Keep plan authorship in CRT and source observation in System Impact."""
    contract = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    crt_contract = CONTRACT_TRACEABILITY.read_text(encoding="utf-8")

    assert "compile_contract_traceability() -> closed CTG plan" in contract
    assert "analyze_source(R0, K) -> G0 + receipt" in contract
    assert "check_plan(selected CTG, G0, G*) -> PlanCheck" in contract
    assert "accept(repository root, PlanCheck, revision) -> Acceptance" in contract
    assert "contract-only compilation" in crt_contract

    definition = next(
        item
        for item in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(contract)
        if item.group("id") == "P0-SIG-04"
    )
    manifest = tomllib.loads(definition.group("manifest"))
    assert manifest["depends_on"] == ["P0-SIG-03"]
    assert "src/viper/system_impact/check.py:check_plan" in manifest["targets"]
    assert "src/viper/system_impact/check.py:accept" in manifest["targets"]


def test_contract_target_declaration_has_one_meaning() -> None:
    """Keep one contract-owned meaning for the target payload boundary."""
    description = (
        "            "
        '"Exact contract-owned payload containing the desired declaration "\n'
        '            "for an add or update, or the removal marker for a removal."'
    )

    assert description in CONTRACT_TRACEABILITY.read_text(encoding="utf-8")
    assert CONTRACT_TRACEABILITY.read_text(encoding="utf-8").count(description) == 1


def test_external_input_contract_tests_have_owned_asserting_payloads() -> None:
    """Require each declared test to have one owned body and explicit oracle."""
    blocks, targets = traceability.compile_contract_plan(
        ROOT,
        (EXTERNAL_INPUT_ROOTS,),
    )
    lines = EXTERNAL_INPUT_ROOTS.read_text(encoding="utf-8").splitlines()
    for block in blocks:
        for test in block.tests:
            assert test in block.targets, (block.block_id, test)
            matching_targets = [
                target
                for target in targets
                if target.block_id == block.block_id and target.target == test
            ]
            assert len(matching_targets) == 1, (block.block_id, test)
            declaration = matching_targets[0].declaration
            fence = "\n".join(lines[declaration.start_line - 1 : declaration.end_line])
            payload_match = _TRACEABILITY_MODEL_FENCE.search(fence)
            assert payload_match is not None, (block.block_id, test)
            tree = ast.parse(payload_match.group("body"))
            function = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == test.symbol.rpartition(".")[2]
                ),
                None,
            )
            assert function is not None, (block.block_id, test)
            explicit_assertion = any(
                isinstance(node, ast.Assert) for node in ast.walk(function)
            )
            exception_assertion = any(
                isinstance(node, ast.With)
                and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and (
                        item.context_expr.func.attr == "raises"
                        or item.context_expr.func.attr.startswith("assertRaises")
                    )
                    for item in node.items
                )
                for node in ast.walk(function)
            )
            assert explicit_assertion or exception_assertion, (
                block.block_id,
                test,
            )


def test_system_impact_check_has_one_bounded_proof_obligation() -> None:
    """Keep the replacement centered on plan conformance, not plan synthesis."""
    contract = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")

    assert "G_0=\\operatorname{Analyze}_{K}(R_0)" in contract
    assert "G^*=\\operatorname{Analyze}_{K}(R^*)" in contract
    assert "C=\\operatorname{CheckPlan}(P,G_0,G^*)" in contract


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
    legacydefinitions = tuple(
        definition
        for definition in _PAIR_BLOCK_DEFINITION.finditer(reference)
        if not definition.group("id").startswith("P0-CRT-")
        and not definition.group("id").startswith("P0-MOD-")
        and definition.group("id")
        not in {"P0-PROOF-01", "P0-PROOF-02", "P0-PROOF-03", "P0-PROOF-04"}
        and not definition.group("id").startswith("P0-SIG-")
        and definition.group("id")
        not in {"P0-PROOF-09", "P0-PROOF-10", "P0-PROOF-11", "P0-PROOF-12"}
    )
    contract_reference = CONTRACT_TRACEABILITY.read_text(encoding="utf-8")
    contractdefinitions = tuple(
        definition
        for definition in _PAIR_BLOCK_DEFINITION.finditer(contract_reference)
        if definition.group("id").startswith("P0-")
    )
    module_reference = MODULE_OWNERSHIP.read_text(encoding="utf-8")
    moduledefinitions = tuple(
        definition for definition in _PAIR_BLOCK_DEFINITION.finditer(module_reference)
    )
    system_reference = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    systemdefinitions = tuple(
        definition
        for definition in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(system_reference)
        if definition.group("id").startswith("P0-")
    )
    rootdefinitions = tuple(
        definition
        for definition in legacydefinitions
        if definition.group("id").startswith("P0-PDR-")
    )
    downstreamdefinitions = tuple(
        definition
        for definition in legacydefinitions
        if not definition.group("id").startswith("P0-PDR-")
    )
    definitions = (
        rootdefinitions
        + contractdefinitions
        + moduledefinitions
        + downstreamdefinitions
        + systemdefinitions
    )
    definition_ids = [definition.group("id") for definition in definitions]
    assert len(definition_ids) == len(set(definition_ids))
    assert set(definition_ids) <= set(marker_ids)
    assert set(marker_ids) - implemented_ids <= set(definition_ids)

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
        assert set(manifest) in (
            {"id", "requirements", "targets", "tests", "gate", "depends_on"},
            {
                "id",
                "requirements",
                "targets",
                "assets",
                "tests",
                "gate",
                "depends_on",
            },
        )
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
        assert "python -m pytest " in str(manifest["gate"])

        body = definition.group("body")
        if block_id.startswith("P0-PDR-"):
            assert body.count("**Context:**") == 1, block_id
        edits = tuple(_PAIR_EDIT.finditer(body))
        contract_targets = "```python contract-target\n" in body
        edit_tree: ast.Module | None = None
        if (
            contract_targets
            or block_id.startswith("P0-SIG-")
            or block_id
            in {
                "P0-PROOF-08",
                "P0-PROOF-09",
                "P0-PROOF-10",
                "P0-PROOF-11",
                "P0-PROOF-12",
            }
        ):
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
                        filename=(f"{MASTER_PHASE_ZERO_PAIR_CODING.name}:{block_id}"),
                    )
                )
            edit_tree = ast.Module(
                body=[node for tree in trees for node in tree.body],
                type_ignores=[],
            )
        if (
            block_id not in implemented_ids
            and edits
            and not block_id.startswith("P0-CRT-")
        ):
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
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    declarations.update(
                        alias.asname or alias.name.rpartition(".")[2]
                        for alias in node.names
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
            if dependency in implemented_ids:
                continue
            assert dependency in manifests, (block_id, dependency)
            assert order[dependency] < order[block_id], (block_id, dependency)


def test_module_ownership_pair_blocks_cover_every_moved_definition() -> None:
    """Keep each realized owner equal to its reviewed PairBlock."""
    reference = MODULE_OWNERSHIP.read_text(encoding="utf-8")

    def exports(tree: ast.Module) -> tuple[str, ...]:
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        )
        assert isinstance(assignment.value, (ast.List, ast.Tuple))
        return tuple(
            value.value
            for value in assignment.value.elts
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )

    def planned_tree(block_id: str) -> ast.Module:
        definition = next(
            match
            for match in _PAIR_BLOCK_DEFINITION.finditer(reference)
            if match.group("id") == block_id
        )
        edit = _TRACEABILITY_MODEL_FENCE.search(definition.group("body"))
        assert edit is not None
        return ast.parse(edit.group("body"))

    model_target = planned_tree("P0-MOD-01")
    model_source = ast.parse(
        (ROOT / "src/viper/verification/models.py").read_text(encoding="utf-8")
    )
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
    target_models = {
        node.name: node
        for node in model_target.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    source_models = {
        node.name: node
        for node in model_source.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    assert source_models.keys() == target_models.keys()
    assert exports(model_source) == exports(model_target)

    verification_target = planned_tree("P0-MOD-02")
    verification_source = ast.parse(
        (ROOT / "src/viper/verification/__init__.py").read_text(encoding="utf-8")
    )
    target_operations = {
        node.name: node
        for node in verification_target.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    source_operations = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    assert target_operations.keys() <= source_operations.keys()
    assert set(exports(verification_target)) <= set(exports(verification_source))

    api_target = planned_tree("P0-MOD-03")
    api_source = ast.parse((ROOT / "src/viper/api.py").read_text(encoding="utf-8"))
    target_handlers = {
        node.name: node for node in api_target.body if isinstance(node, ast.FunctionDef)
    }
    source_handlers = {
        node.name: node
        for node in api_source.body
        if isinstance(node, ast.FunctionDef) and node.name in target_handlers
    }
    assert source_handlers.keys() == target_handlers.keys()


def test_phase_zero_system_impact_models_match_bounded_contract() -> None:
    """Keep the source-observation and plan-check records complete."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    for model in (
        "CodeQLIdentity",
        "CodeQLReceipt",
        "SourceNode",
        "SourceEdge",
        "SourceSnapshot",
        "SourceGraph",
        "Impact",
        "ResolvedContractTarget",
        "TargetCheck",
        "PlanCheck",
        "Acceptance",
    ):
        assert f"class {model}(ProtocolModel)" in specification
    for operation in ("imports", "calls", "constructs", "inherits", "reads", "writes"):
        assert f'"{operation}"' in specification
    for boundary in (
        "ChangeKind = Literal[",
        "policy_version: Literal[1]",
        "change_kind: ChangeKind",
        "start_col: int",
        "end_col: int",
        "def extract_declaration_bytes(",
        "def classify_target_change(",
        "IMPACT_EDGE_KINDS_V1",
        "block_id` appears in `PlanCheck.blocks`",
        "runs every frozen selected `PairBlock.gate`",
        "source digest and selected-plan digest from the",
        "### Guided work and strict closure",
        "### Autonomous work",
        "The default guided boundary is one contract session",
        "Every changed declaration receives one result",
        "test_acceptance_binds_commit_to_checked_source_and_plan",
    ):
        assert boundary in specification
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    assert "One contract session is the default guided boundary" in checklist
    assert "Autonomous work freezes the selected PairBlocks" in checklist
    assert "performs the final reconciliation" in checklist


def test_system_impact_uses_change_sensitive_one_hop_advice() -> None:
    """Keep impact typed, direct, advisory, and owned by P0-SIG-03."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")

    for claim in (
        "The operation stops after this direct",
        "complete only over",
        "impact-policy version 1",
        "typed one-hop impact report",
    ):
        assert claim in specification
    assert "classify its `ChangeKind`" in checklist

    definition = next(
        item
        for item in _SYSTEM_PAIR_BLOCK_DEFINITION.finditer(specification)
        if item.group("id") == "P0-SIG-03"
    )
    manifest = tomllib.loads(definition.group("manifest"))
    assert "src/viper/system_impact/models.py:ChangeKind" in manifest["targets"]
    assert (
        "src/viper/_system_impact/source.py:classify_target_change"
        in manifest["targets"]
    )
    assert {
        "tests/test_system_impact.py:test_change_classifier_distinguishes_interface_and_body_updates",
        "tests/test_system_impact.py:test_plan_reports_only_policy_selected_one_hop_dependents",
        "tests/test_system_impact.py:test_removed_target_reports_all_represented_direct_dependents",
        "tests/test_system_impact.py:test_unclassified_change_uses_conservative_one_hop_edges",
    } <= set(manifest["tests"])


def test_system_impact_delegates_pair_block_scheduling() -> None:
    """Keep scheduling in its governing contract instead of duplicating it."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    appendix = specification.split(
        "## Appendix A. PairBlock scheduling",
        maxsplit=1,
    )[1].split("## Sources", maxsplit=1)[0]
    normalized_appendix = " ".join(appendix.split())

    for boundary in (
        "[PairBlock scheduling](pair-block-scheduling.md)",
        "planned source materialization",
        "dependency projection",
        "write-conflict ordering",
        "SCC condensation",
        "deterministic execution waves",
    ):
        assert boundary in normalized_appendix
    for active_marker in (
        "contract-requirement:",
        "pair-block-definition:",
        "verifier-rule:",
    ):
        assert active_marker not in appendix


def test_system_impact_codeql_backend_is_end_to_end() -> None:
    """Keep one pinned CodeQL identity at both observation boundaries."""
    specification = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")

    for value in (
        "class CodeQLIdentity(ProtocolModel)",
        "class CodeQLReceipt(ProtocolModel)",
        "class SourceGraph(ProtocolModel)",
        "analyze_source(R0, K) -> G0 + receipt",
        "analyze_source(R*, K) -> G* + receipt",
        "tests/test_system_impact.py:test_analyze_source_binds_digests_identity_and_database_reuse",
    ):
        assert value in specification

    for rule in (
        "system.codeql.identity",
        "system.source.canonical",
        "system.plan.resolved",
        "system.plan.realized",
        "system.plan.closed",
        "system.fixture.replayed",
    ):
        assert f"rule={rule}" in checklist


def test_contract_traceability_model_block_matches_runtime() -> None:
    """Keep every documented traceability class and field aligned with Python."""
    text = CONTRACT_TRACEABILITY.read_text()
    section = text.split("## 4. Models", maxsplit=1)[1].split(
        "## 5. Execution", maxsplit=1
    )[0]
    block = _TRACEABILITY_MODEL_FENCE.search(section)
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
    assert CONTRACT_BASELINE_MANIFEST.read_bytes() == rendered_manifest(
        ROOT, CONTRACT_BASELINE_MANIFEST
    )
    baseline_records = CONTRACT_BASELINE_DATA["contracts"]
    assert tuple(record["path"] for record in baseline_records) == tuple(
        contract.relative_to(ROOT).as_posix() for contract in IMPLEMENTATION_CONTRACTS
    )
    baselines = {record["path"]: record for record in baseline_records}

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

    for contract in IMPLEMENTATION_CONTRACTS:
        relative_path = contract.relative_to(ROOT).as_posix()
        record = baselines[relative_path]
        assert hashlib.sha256(contract.read_bytes()).hexdigest() == record["sha256"]
        assert record["requirement_ids"] == sorted(
            match.group("requirement")
            for match in _CONTRACT_REQUIREMENT.finditer(contract.read_text())
        )

    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
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
        for guide in IMPLEMENTATION_CONTRACTS
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


def test_system_impact_rule_owners_match_the_bounded_check() -> None:
    """Keep verifier owners on the exact source-check operations."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    required_owners = {
        "src/viper/system_impact/models.py:SourceGraph",
        "src/viper/system_impact/models.py:CodeQLIdentity",
        "src/viper/system_impact/plan.py:inspect_plan",
        "src/viper/system_impact/check.py:check_plan",
        "src/viper/system_impact/check.py:accept",
        "tests/test_system_impact.py:test_committed_manifest_rename",
    }
    owners = set(
        re.findall(r"contract-implementation: [^>]+ owner=([^ ]+) -->", checklist)
    )
    assert required_owners <= owners


def test_system_impact_contract_covers_codeql_boundary() -> None:
    """Keep every CodeQL-owned implementation surface in its contract."""
    contract = SYSTEM_IMPACT_COMPILER.read_text(encoding="utf-8")
    for path in (
        "src/viper/_system_impact/codeql.py",
        "tests/test_system_impact.py",
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
    pair_guides = IMPLEMENTATION_CONTRACTS
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
