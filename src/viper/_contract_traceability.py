"""Define contract-requirement traceability records."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, model_validator

from ._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath

RequirementId = Annotated[
    str,
    Field(pattern=r"^[A-Z]{3}-[0-9]{2}$"),
]
VerifierRuleId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"),
]
RuleEdgeKind = Literal["implementation", "verification"]
TraceState = Literal["planned", "implemented"]
PairBlockId = Annotated[
    str,
    Field(pattern=r"^P[0-9]+-[A-Z]+-[0-9]{2}$"),
]


class DeclarationRef(ProtocolModel):
    """Locate and identify one authored traceability declaration."""

    path: RepoRelPath = Field(
        description="Repository-relative document containing the declaration."
    )
    start_line: int = Field(
        ge=1,
        description="One-based first line occupied by the declaration.",
    )
    end_line: int = Field(
        ge=1,
        description="One-based final line occupied by the declaration.",
    )
    sha256: SHA256 = Field(
        description="SHA-256 digest of the exact UTF-8 declaration bytes."
    )

    @model_validator(mode="after")
    def validate_line_order(self) -> Self:
        """Require the final line to include or follow the first line."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class RepoSymbolRef(ProtocolModel):
    """Reference one qualified symbol in one repository file."""

    path: RepoRelPath = Field(
        description="Repository-relative source file containing the symbol."
    )
    symbol: NonEmptyStr = Field(
        description="Qualified symbol name resolved inside the source file."
    )


class ContractRequirement(ProtocolModel):
    """Identify one requirement declared by one contract."""

    requirement_id: RequirementId = Field(
        description="Stable identifier declared by the owning contract."
    )
    contract: RepoRelPath = Field(
        description="Repository-relative contract that declares the requirement."
    )
    declaration: DeclarationRef = Field(
        description="Exact authored requirement marker used to reconstruct this record."
    )


class VerifierRule(ProtocolModel):
    """Declare one testable rule required by a contract."""

    rule_id: VerifierRuleId = Field(
        description="Stable identifier of the executable invariant."
    )
    requirement_id: RequirementId = Field(
        description="Contract requirement that owns the verifier rule."
    )
    contract: RepoRelPath = Field(
        description="Repository-relative contract that declares the rule."
    )
    statement: NonEmptyStr = Field(
        description="Testable invariant enforced by the rule."
    )
    declaration: DeclarationRef = Field(
        description=(
            "Exact authored verifier-rule marker used to reconstruct this record."
        )
    )


class RuleEdge(ProtocolModel):
    """Connect one verifier rule to its implementation block or test block."""

    kind: RuleEdgeKind = Field(
        description="Relationship from the rule to an implementation or test."
    )
    rule_id: VerifierRuleId = Field(
        description="Verifier rule at the source of this edge."
    )
    block_id: PairBlockId = Field(
        description="PairBlock that owns the target of this relationship."
    )
    declaration: DeclarationRef = Field(
        description="Exact checklist marker that declares this relationship."
    )
    state: TraceState = Field(
        description="Whether the referenced symbol is planned or implemented."
    )
    target: RepoSymbolRef = Field(
        description="Repository symbol reached by this relationship."
    )


TargetAction = Literal["add", "update", "remove"]


class ContractTarget(ProtocolModel):
    """Bind one required source change to one implementation block."""

    requirements: tuple[RequirementId, ...] = Field(
        min_length=1,
        description="Contract requirements that need this source change.",
    )
    block_id: PairBlockId = Field(
        description="PairBlock that applies this source change."
    )
    action: TargetAction = Field(
        description="Whether the PairBlock adds, updates, or removes the target."
    )
    target: RepoSymbolRef = Field(
        description="Repository symbol changed by the PairBlock."
    )
    declaration: DeclarationRef = Field(
        description=(
            "Exact contract-owned payload containing the desired declaration "
            "for an add or update, or the removal marker for a removal."
        )
    )


class PairBlock(ProtocolModel):
    """Store one bounded, dependency-ordered implementation step."""

    block_id: PairBlockId = Field(
        description="Stable identifier used by checklist and target records."
    )
    requirements: tuple[RequirementId, ...] = Field(
        min_length=1, description="Contract requirements implemented by this block."
    )
    targets: tuple[RepoSymbolRef, ...] = Field(
        min_length=1, description="Repository symbols this block changes."
    )
    tests: tuple[RepoSymbolRef, ...] = Field(
        min_length=1, description="Exact pytest functions that observe this block."
    )
    gate: NonEmptyStr = Field(
        description="Focused command that must pass before the block closes."
    )
    depends_on: tuple[PairBlockId, ...] = Field(
        description="Blocks whose completed results this block consumes."
    )
    declaration: DeclarationRef = Field(
        description="Exact pair-block manifest used to reconstruct this record."
    )


class ContractTraceabilityGraph(ProtocolModel):
    """Store the complete ordered contract and implementation plan."""

    schema_version: Literal[5] = Field(
        default=5, description="Format version of the serialized traceability graph."
    )
    requirements: tuple[ContractRequirement, ...] = Field(
        min_length=1,
        description="Ordered contract requirements represented by the graph.",
    )
    rules: tuple[VerifierRule, ...] = Field(
        min_length=1, description="Ordered verifier rules represented by the graph."
    )
    edges: tuple[RuleEdge, ...] = Field(
        min_length=1,
        description="Ordered implementation and verification relationships.",
    )
    targets: tuple[ContractTarget, ...] = Field(
        min_length=1, description="Ordered source changes required by the contracts."
    )
    blocks: tuple[PairBlock, ...] = Field(
        min_length=1,
        description="Ordered implementation blocks that apply the source changes.",
    )


_REQUIREMENT_ROW = re.compile(
    r"^\| (?P<label>[A-Z]{3}-\d{2}) "
    r"<!-- contract-requirement: (?P<requirement>[A-Z]{3}-\d{2}) "
    r"phase=(?P<phase>\d+) test=(?P<test>tests/[a-z0-9_/]+\.py) -->",
    re.MULTILINE,
)
_VERIFIER_RULE_ROW = re.compile(
    r"^\| `(?P<label>[a-z][a-z0-9_.]+)` "
    r"<!-- verifier-rule: (?P<rule>[a-z][a-z0-9_.]+) "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) --> "
    r"\| (?P<statement>.+?) \|$",
    re.MULTILINE,
)

_PHASE_HEADING = re.compile(r"^## \d+\. Master Phase (?P<phase>\d+)\b", re.MULTILINE)
_RULE_EDGE = re.compile(
    r"<!-- contract-(?P<kind>implementation|verification): "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) "
    r"rule=(?P<rule>[a-z][a-z0-9_.]+) "
    r"state=(?P<state>planned|implemented) "
    r"(?P<label>owner|test)=(?P<target>[^ ]+) -->"
)
_PAIR_BLOCK = re.compile(
    r"<!-- pair-"
    r"block-definition: (?P<id>P[0-9]+-[A-Z]+-[0-9]{2}) -->\n"
    r"```toml pair-block\n(?P<manifest>.*?)\n```(?P<body>.*?)"
    r"(?=<!-- pair-"
    r"block-definition: |\Z)",
    re.DOTALL,
)
_TARGET_MARKER = re.compile(
    r"<!-- contract-target: requirements=(?P<requirements>[^ ]+) "
    r"block=(?P<block>P[0-9]+-[A-Z]+-[0-9]{2}) "
    r"action=(?P<action>add|update|remove) "
    r"target=(?P<target>[^ ]+) -->"
)
_TARGET_FENCE = re.compile(
    r"```python contract-target\n(?P<body>.*?)\n```",
    re.DOTALL,
)
_REMOVE_MARKER = re.compile(r"<!-- contract-remove -->")
_CHECKBOX = re.compile(
    r"^- \[[ xX]\] .*?(?=^- \[[ xX]\] |^### |^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_PAIR_BLOCK_MARKER = re.compile(r"<!-- pair-block: (?P<id>P[0-9]+-[A-Z]+-[0-9]{2}) -->")


_PYTHON_FENCE = re.compile(r"\`\`\`python\n(?P<body>.*?)\n\`\`\`", re.DOTALL)
_CONTRACT_WORKED_EXAMPLE = re.compile(
    r"<!-- contract-worked-example: start -->"
    r"(?P<body>.*?)"
    r"<!-- contract-worked-example: end -->",
    re.DOTALL,
)
_MERMAID_FENCE = re.compile(
    r"\`\`\`mermaid\n(?P<body>.*?)\n\`\`\`",
    re.DOTALL,
)
_MERMAID_EDGE = re.compile(
    r"^\s*(?P<source>[A-Za-z][A-Za-z0-9_]*)\s+-->"
    r"(?:\|[^|]+\|)?\s*(?P<target>[A-Za-z][A-Za-z0-9_]*)"
)


class ContractTraceabilityError(ValueError):
    """Report an invalid or incomplete traceability declaration."""


@dataclass(frozen=True)
class _RequirementMarker:
    requirement: ContractRequirement
    phase: int
    test_path: str


def _parse_pair_blocks(
    root: Path,
    contracts: tuple[Path, ...],
) -> tuple[PairBlock, ...]:
    """Compile the implementation blocks declared by the contracts."""
    blocks: list[PairBlock] = []
    for contract in contracts:
        text = contract.read_text(encoding="utf-8")
        for match in _PAIR_BLOCK.finditer(text):
            manifest: dict[str, Any] = tomllib.loads(match.group("manifest"))
            block_id = match.group("id")
            if manifest.get("id") != block_id:
                raise ContractTraceabilityError("PairBlock marker and manifest differ")
            requirements = tuple(manifest["requirements"])
            block_targets = tuple(
                _parse_repo_symbol(value) for value in manifest["targets"]
            )
            block = PairBlock(
                block_id=block_id,
                requirements=requirements,
                targets=block_targets,
                tests=tuple(_parse_repo_symbol(value) for value in manifest["tests"]),
                gate=manifest["gate"],
                depends_on=tuple(manifest["depends_on"]),
                declaration=_declaration_ref(
                    root,
                    contract,
                    text,
                    match.start("manifest"),
                    match.end("manifest"),
                ),
            )
            blocks.append(block)
    if _duplicates([block.block_id for block in blocks]):
        raise ContractTraceabilityError("PairBlock ID belongs to several contracts")
    return tuple(sorted(blocks, key=lambda item: item.block_id))


def _parse_contract_targets(
    root: Path,
    contracts: tuple[Path, ...],
) -> tuple[ContractTarget, ...]:
    """Compile each contract-owned source transition."""
    targets: list[ContractTarget] = []
    for contract in contracts:
        text = contract.read_text(encoding="utf-8")
        markers = tuple(_TARGET_MARKER.finditer(text))
        for marker in markers:
            action = cast(TargetAction, marker.group("action"))
            payload_pattern = _REMOVE_MARKER if action == "remove" else _TARGET_FENCE
            payload = payload_pattern.search(text, marker.end())

            if payload is None:
                raise ContractTraceabilityError(
                    "ContractTarget lacks its contract-owned declaration"
                )

            between = text[marker.end() : payload.start()]
            if _TARGET_MARKER.sub("", between).strip():
                raise ContractTraceabilityError(
                    "ContractTarget is not immediately followed by its declaration"
                )

            targets.append(
                ContractTarget(
                    requirements=tuple(marker.group("requirements").split(",")),
                    block_id=marker.group("block"),
                    action=action,
                    target=_parse_repo_symbol(marker.group("target")),
                    declaration=_declaration_ref(
                        root,
                        contract,
                        text,
                        payload.start(),
                        payload.end(),
                    ),
                )
            )
    return tuple(
        sorted(
            targets,
            key=lambda item: (
                item.block_id,
                item.target.path,
                item.target.symbol,
            ),
        )
    )


def _validate_plan(
    requirements: tuple[ContractRequirement, ...],
    rules: tuple[VerifierRule, ...],
    edges: tuple[RuleEdge, ...],
    targets: tuple[ContractTarget, ...],
    blocks: tuple[PairBlock, ...],
) -> None:
    requirement_ids = {item.requirement_id for item in requirements}
    rule_by_id = {item.rule_id: item for item in rules}
    block_by_id = {item.block_id: item for item in blocks}
    completed_blocks = {edge.block_id for edge in edges if edge.state == "implemented"}

    target_keys = [(item.block_id, item.target) for item in targets]
    if len(target_keys) != len(set(target_keys)):
        raise ContractTraceabilityError("PairBlock target has several ContractTargets")

    for target in targets:
        if not set(target.requirements) <= requirement_ids:
            raise ContractTraceabilityError("ContractTarget names unknown requirement")
        block = block_by_id.get(target.block_id)
        if block is None:
            raise ContractTraceabilityError("ContractTarget names unknown PairBlock")
        if not set(target.requirements) <= set(block.requirements):
            raise ContractTraceabilityError(
                "ContractTarget requirement is absent from PairBlock"
            )
        if target.target not in block.targets:
            raise ContractTraceabilityError(
                "ContractTarget is absent from PairBlock.targets"
            )

    for block in blocks:
        for target in block.targets:
            if (block.block_id, target) not in target_keys:
                raise ContractTraceabilityError("PairBlock target lacks ContractTarget")
        for dependency in block.depends_on:
            if dependency not in block_by_id and dependency not in completed_blocks:
                raise ContractTraceabilityError("PairBlock names unknown dependency")

    visiting: set[PairBlockId] = set()
    visited: set[PairBlockId] = set()

    def visit(block_id: PairBlockId) -> None:
        if block_id in visiting:
            raise ContractTraceabilityError("PairBlock dependency cycle")
        if block_id in visited:
            return
        visiting.add(block_id)
        for dependency in block_by_id[block_id].depends_on:
            if dependency in block_by_id:
                visit(dependency)
        visiting.remove(block_id)
        visited.add(block_id)

    for block_id in block_by_id:
        visit(block_id)

    for edge in edges:
        rule = rule_by_id[edge.rule_id]
        if edge.state == "implemented":
            continue
        block = block_by_id.get(edge.block_id)
        if block is None:
            raise ContractTraceabilityError("RuleEdge names unknown PairBlock")
        if rule.requirement_id not in block.requirements:
            raise ContractTraceabilityError(
                "RuleEdge requirement is absent from PairBlock"
            )
        if edge.kind == "implementation":
            if not any(
                item.block_id == block.block_id
                and rule.requirement_id in item.requirements
                for item in targets
            ):
                raise ContractTraceabilityError(
                    "implementation block lacks a target for the rule requirement"
                )
        elif edge.target not in block.tests:
            raise ContractTraceabilityError(
                "verification target is absent from PairBlock.tests"
            )


def _declaration_ref(
    root: Path,
    path: Path,
    text: str,
    start: int,
    end: int,
) -> DeclarationRef:
    raw = text[start:end].encode("utf-8")
    return DeclarationRef(
        path=path.relative_to(root).as_posix(),
        start_line=text.count("\n", 0, start) + 1,
        end_line=text.count("\n", 0, end) + 1,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _duplicates(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(value for value in set(values) if values.count(value) > 1))


def _parse_requirement_markers(
    root: Path,
    contract: Path,
) -> tuple[_RequirementMarker, ...]:
    contract_path = contract.relative_to(root).as_posix()
    text = contract.read_text(encoding="utf-8")
    markers: list[_RequirementMarker] = []
    for match in _REQUIREMENT_ROW.finditer(text):
        label = match.group("label")
        requirement_id = match.group("requirement")
        if label != requirement_id:
            raise ContractTraceabilityError(
                f"requirement label {label} does not match {requirement_id}"
            )
        markers.append(
            _RequirementMarker(
                requirement=ContractRequirement(
                    requirement_id=requirement_id,
                    contract=contract_path,
                    declaration=_declaration_ref(
                        root,
                        contract,
                        text,
                        match.start(),
                        match.end(),
                    ),
                ),
                phase=int(match.group("phase")),
                test_path=match.group("test"),
            )
        )
    if not markers:
        raise ContractTraceabilityError(
            f"{contract_path} declares no contract requirements"
        )
    duplicate_ids = _duplicates(
        [marker.requirement.requirement_id for marker in markers]
    )
    if duplicate_ids:
        raise ContractTraceabilityError(
            f"duplicate requirements in {contract_path}: {duplicate_ids}"
        )
    return tuple(sorted(markers, key=lambda item: item.requirement.requirement_id))


def _parse_verifier_rules(
    root: Path,
    contract: Path,
    requirements: tuple[_RequirementMarker, ...],
) -> tuple[VerifierRule, ...]:
    contract_path = contract.relative_to(root).as_posix()
    text = contract.read_text(encoding="utf-8")
    requirement_ids = {marker.requirement.requirement_id for marker in requirements}
    rules: list[VerifierRule] = []
    for match in _VERIFIER_RULE_ROW.finditer(text):
        label = match.group("label")
        rule_id = match.group("rule")
        requirement_id = match.group("requirement")
        if label != rule_id:
            raise ContractTraceabilityError(
                f"verifier-rule label {label} does not match {rule_id}"
            )
        if requirement_id not in requirement_ids:
            raise ContractTraceabilityError(
                f"{rule_id} names unknown requirement {requirement_id}"
            )
        rules.append(
            VerifierRule(
                rule_id=rule_id,
                requirement_id=requirement_id,
                contract=contract_path,
                statement=match.group("statement"),
                declaration=_declaration_ref(
                    root,
                    contract,
                    text,
                    match.start(),
                    match.end(),
                ),
            )
        )
    duplicate_ids = _duplicates([rule.rule_id for rule in rules])
    if duplicate_ids:
        raise ContractTraceabilityError(
            f"duplicate verifier rules in {contract_path}: {duplicate_ids}"
        )
    uncovered = requirement_ids - {rule.requirement_id for rule in rules}
    if uncovered:
        raise ContractTraceabilityError(
            f"requirements w/o verifier rules in {contract_path}: {sorted(uncovered)}"
        )
    return tuple(sorted(rules, key=lambda item: item.rule_id))


def _parse_repo_symbol(value: str) -> RepoSymbolRef:
    path, separator, symbol = value.partition(":")
    if not separator or not path or not symbol:
        raise ContractTraceabilityError()

    return RepoSymbolRef(path=path, symbol=symbol)


def _python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            symbols.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(f"{node.name}.{member.name}")
    return symbols


def _require_python_symbol(root: Path, target: RepoSymbolRef) -> None:
    path = root / target.path
    if not path.is_file():
        raise ContractTraceabilityError(f"source file is missing: {target.path}")
    if target.symbol not in _python_symbols(path):
        raise ContractTraceabilityError(
            f"source symbol is missing: {target.path}:{target.symbol}"
        )


def _parse_rule_edges(
    root: Path,
    checklist: Path,
    requirements: tuple[_RequirementMarker, ...],
    rules: tuple[VerifierRule, ...],
) -> tuple[RuleEdge, ...]:
    """Compile rule edges and the PairBlock owning each edge target."""
    text = checklist.read_text(encoding="utf-8")
    phases = tuple(_PHASE_HEADING.finditer(text))
    requirement_by_id = {item.requirement.requirement_id: item for item in requirements}
    rule_by_id = {rule.rule_id: rule for rule in rules}
    edges: list[RuleEdge] = []
    for index, phase_match in enumerate(phases):
        phase = int(phase_match.group("phase"))
        end = phases[index + 1].start() if index + 1 < len(phases) else len(text)
        section_start = phase_match.end()
        section = text[section_start:end]
        for checkbox in _CHECKBOX.finditer(section):
            block_markers = tuple(_PAIR_BLOCK_MARKER.finditer(checkbox.group(0)))
            edge_markers = tuple(_RULE_EDGE.finditer(checkbox.group(0)))
            if edge_markers and len(block_markers) != 1:
                raise ContractTraceabilityError(
                    "rule-bearing checklist task requires one PairBlock"
                )
            for match in edge_markers:
                requirement_id = match.group("requirement")
                rule_id = match.group("rule")
                kind = cast(RuleEdgeKind, match.group("kind"))
                expected_label = "owner" if kind == "implementation" else "test"
                if match.group("label") != expected_label:
                    raise ContractTraceabilityError(
                        f"{kind} edge requires {expected_label}= target"
                    )
                requirement_marker = requirement_by_id.get(requirement_id)
                rule = rule_by_id.get(rule_id)
                if requirement_marker is None and rule is None:
                    continue
                if requirement_marker is None or rule is None:
                    raise ContractTraceabilityError(
                        f"unknown requirement-rule edge: {requirement_id}:{rule_id}"
                    )
                if rule.requirement_id != requirement_id:
                    raise ContractTraceabilityError(
                        f"{rule_id} does not belong to {requirement_id}"
                    )
                if requirement_marker.phase != phase:
                    raise ContractTraceabilityError(
                        f"{requirement_id} belongs to phase "
                        f"{requirement_marker.phase}, not {phase}"
                    )
                target = _parse_repo_symbol(match.group("target"))
                state = cast(TraceState, match.group("state"))
                if state == "implemented":
                    _require_python_symbol(root=root, target=target)
                marker_start = section_start + checkbox.start() + match.start()
                marker_end = section_start + checkbox.start() + match.end()
                edges.append(
                    RuleEdge(
                        kind=kind,
                        rule_id=rule_id,
                        block_id=block_markers[0].group("id"),
                        declaration=_declaration_ref(
                            root,
                            checklist,
                            text,
                            marker_start,
                            marker_end,
                        ),
                        state=state,
                        target=target,
                    )
                )
    keys = [(edge.kind, edge.rule_id, edge.target) for edge in edges]
    if len(keys) != len(set(keys)):
        raise ContractTraceabilityError("duplicate rule edge")
    for rule_id in rule_by_id:
        links = tuple(edge for edge in edges if edge.rule_id == rule_id)
        if sum(edge.kind == "implementation" for edge in links) != 1:
            raise ContractTraceabilityError(
                f"{rule_id} requires exactly one implementation edge"
            )
        if sum(edge.kind == "verification" for edge in links) < 1:
            raise ContractTraceabilityError(
                f"{rule_id} requires at least one verification edge"
            )
    order = {"implementation": 0, "verification": 1}
    return tuple(
        sorted(
            edges,
            key=lambda edge: (
                edge.rule_id,
                order[edge.kind],
                edge.target.path,
                edge.target.symbol,
            ),
        )
    )


def _section(text: str, number: int) -> str:
    match = re.search(
        rf"^## {number}\. [^\n]+\n(?P<body>.*?)(?=^## \d+\. |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ContractTraceabilityError(
            f"contract is missing numbered section {number}"
        )
    return match.group("body")


def _assert_dag(diagram: str, contract: Path, index: int) -> None:
    if not diagram.lstrip().startswith("flowchart"):
        raise ContractTraceabilityError(
            f"{contract.name} diagram {index} is not a Mermaid flowchart"
        )
    adjacency: dict[str, set[str]] = {}
    for line in diagram.splitlines():
        edge = _MERMAID_EDGE.match(line)
        if edge is not None:
            adjacency.setdefault(edge.group("source"), set()).add(edge.group("target"))
    if not adjacency:
        raise ContractTraceabilityError(
            f"{contract.name} diagram {index} has no directed edges"
        )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractTraceabilityError(
                f"{contract.name} diagram {index} contains a cycle"
            )
        if node in visited:
            return
        visiting.add(node)
        for target in adjacency.get(node, set()):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        visit(node)


def validate_contract_example(contract: Path) -> None:
    text = contract.read_text(encoding="utf-8")
    retired_markers = (
        "<!-- contract-symbols:",
        "<!-- contract-example-symbols:",
        "```python contract-exports",
    )
    if any(marker in text for marker in retired_markers):
        raise ContractTraceabilityError(
            f"{contract.name} contains a retired symbol inventory"
        )
    current_gap = _section(text, 3)
    positions = tuple(
        current_gap.find(heading)
        for heading in (
            "### Current DAG",
            "### Proposed-change DAG",
            "### Integrated DAG",
        )
    )
    if -1 in positions or positions != tuple(sorted(positions)):
        raise ContractTraceabilityError(
            f"{contract.name} requires ordered current, proposed-change, "
            "and integrated DAG headings"
        )

    diagrams = tuple(
        match.group("body") for match in _MERMAID_FENCE.finditer(current_gap)
    )
    if len(diagrams) != 3:
        raise ContractTraceabilityError(
            f"{contract.name} requires exactly three Mermaid DAGs"
        )
    for index, diagram in enumerate(diagrams, start=1):
        _assert_dag(diagram, contract, index)

    examples = tuple(_CONTRACT_WORKED_EXAMPLE.finditer(text))
    if len(examples) != 1:
        raise ContractTraceabilityError(
            f"{contract.name} requires one marked worked example"
        )

    example_blocks = tuple(
        match.group("body")
        for match in _PYTHON_FENCE.finditer(examples[0].group("body"))
    )
    if not example_blocks:
        raise ContractTraceabilityError(f"{contract.name} worked example has no Python")
    ast.parse(
        "\n\n".join(example_blocks),
        filename=f"{contract}:worked-example",
    )


def serialize_contract_traceability(graph: ContractTraceabilityGraph) -> bytes:
    return json.dumps(
        graph.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compile_contract_traceability(
    root: Path,
    checklist: Path,
    contracts: tuple[Path, ...],
) -> ContractTraceabilityGraph:
    """Compile and validate the complete contract implementation plan."""
    markers = tuple(
        marker
        for contract in contracts
        for marker in _parse_requirement_markers(root, contract)
    )
    requirements = tuple(marker.requirement for marker in markers)
    if _duplicates([item.requirement_id for item in requirements]):
        raise ContractTraceabilityError("requirement ID belongs to several contracts")
    rules = tuple(
        rule
        for contract in contracts
        for rule in _parse_verifier_rules(
            root,
            contract,
            tuple(
                marker
                for marker in markers
                if marker.requirement.contract == contract.relative_to(root).as_posix()
            ),
        )
    )
    if _duplicates([item.rule_id for item in rules]):
        raise ContractTraceabilityError("verifier-rule ID belongs to several contracts")
    blocks = _parse_pair_blocks(root, contracts)
    targets = _parse_contract_targets(root, contracts)
    edges = _parse_rule_edges(root, checklist, markers, rules)
    _validate_plan(requirements, rules, edges, targets, blocks)
    graph = ContractTraceabilityGraph(
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=edges,
        targets=targets,
        blocks=blocks,
    )
    serialize_contract_traceability(graph)
    return graph
