"""Define contract-requirement traceability records."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self, cast

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
    """Connect one verifier rule to an implementation or test."""

    kind: RuleEdgeKind = Field(
        description="Relationship from the rule to an implementation or test."
    )
    rule_id: VerifierRuleId = Field(
        description="Verifier rule at the source of this edge."
    )
    phase: int = Field(
        ge=0,
        description="Checklist phase that schedules this relationship.",
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


class ContractTraceabilityGraph(ProtocolModel):
    """Store the complete ordered traceability graph."""

    schema_version: Literal[3] = Field(
        default=3,
        description="Format version of the serialized traceability graph.",
    )
    requirements: tuple[ContractRequirement, ...] = Field(
        min_length=1,
        description="Ordered contract requirements represented by the graph.",
    )
    rules: tuple[VerifierRule, ...] = Field(
        min_length=1,
        description="Ordered verifier rules represented by the graph.",
    )
    edges: tuple[RuleEdge, ...] = Field(
        min_length=1,
        description="Ordered implementation and verification relationships.",
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


_PYTHON_FENCE = re.compile(r"\`\`\`python\n(?P<body>.*?)\n\`\`\`", re.DOTALL)
_CONTRACT_EXAMPLE_SYMBOLS = re.compile(
    r"<!-- contract-example-symbols:\s*(?P<body>\[.*?\])\s*-->",
    re.DOTALL,
)
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
_PLACEHOLDER = re.compile(
    r"(?:^\s*\.\.\.\s*$|=\s*\.\.\.\s*$|"
    r"\bTBD\b|\bTODO\b|<[^>]+>)",
    re.MULTILINE,
)


class ContractTraceabilityError(ValueError):
    """Report an invalid or incomplete traceability declaration."""


@dataclass(frozen=True)
class _RequirementMarker:
    requirement: ContractRequirement
    phase: int
    test_path: str


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
    text = checklist.read_text(encoding="utf-8")
    phases = tuple(_PHASE_HEADING.finditer(text))
    requirement_by_id = {item.requirement.requirement_id: item for item in requirements}
    rule_by_id = {rule.rule_id: rule for rule in rules}
    edges: list[RuleEdge] = []
    for index, phase_match in enumerate(phases):
        phase = int(phase_match.group("phase"))
        end = phases[index + 1].start() if index + 1 < len(phases) else len(text)
        section = text[phase_match.end() : end]
        for match in _RULE_EDGE.finditer(section):
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
            declaration_start = phase_match.end() + match.start()
            declaration_end = phase_match.end() + match.start()
            edges.append(
                RuleEdge(
                    kind=kind,
                    rule_id=rule_id,
                    phase=phase,
                    declaration=_declaration_ref(
                        root,
                        checklist,
                        text,
                        declaration_start,
                        declaration_end,
                    ),
                    state=state,
                    target=target,
                )
            )
    keys = [(edge.kind, edge.rule_id, edge.target) for edge in edges]
    if len(keys) != len(set(keys)):
        raise ContractTraceabilityError("duplicate rule edge")
    for rule_id in rule_by_id:
        implementation_count = sum(
            edge.kind == "implementation" for edge in edges if edge.rule_id == rule_id
        )
        verification_count = sum(
            edge.kind == "verification" for edge in edges if edge.rule_id == rule_id
        )
        if implementation_count != 1:
            raise ContractTraceabilityError(
                f"{rule_id} requires exactly one implementation edge"
            )
        if verification_count < 1:
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

    _section(text, 4)
    inventories = tuple(_CONTRACT_EXAMPLE_SYMBOLS.finditer(text))
    if len(inventories) != 1:
        raise ContractTraceabilityError(
            f"{contract.name} requires one contract-example-symbols inventory"
        )
    try:
        loaded_symbols = json.loads(inventories[0].group("body"))
    except json.JSONDecodeError as error:
        raise ContractTraceabilityError(
            f"{contract.name} has an invalid contract-example-symbols inventory"
        ) from error
    if (
        not isinstance(loaded_symbols, list)
        or not loaded_symbols
        or any(
            not isinstance(symbol, str) or not symbol.isidentifier()
            for symbol in loaded_symbols
        )
        or len(loaded_symbols) != len(set(loaded_symbols))
    ):
        raise ContractTraceabilityError(
            f"{contract.name} contract-example-symbols must be a non-empty "
            "array of unique Python identifiers"
        )
    symbols = set(loaded_symbols)

    examples = tuple(_CONTRACT_WORKED_EXAMPLE.finditer(text))
    if len(examples) != 1:
        raise ContractTraceabilityError(
            f"{contract.name} requires one marked worked example"
        )

    declarations = text
    declaration_trees = tuple(
        ast.parse(match.group("body"), filename=str(contract))
        for match in _PYTHON_FENCE.finditer(declarations)
    )
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
    declared_aliases.update(
        node.target.id
        for tree in declaration_trees
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    )
    declared_imports = {
        alias.asname or alias.name.split(".", maxsplit=1)[0]
        for tree in declaration_trees
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    declared_imports.update(
        alias.asname or alias.name
        for tree in declaration_trees
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )

    example_blocks = tuple(
        match.group("body")
        for match in _PYTHON_FENCE.finditer(examples[0].group("body"))
    )
    if not example_blocks:
        raise ContractTraceabilityError(f"{contract.name} worked example has no Python")
    example_tree = ast.parse(
        "\n\n".join(example_blocks),
        filename=f"{contract}:worked-example",
    )
    calls = {
        node.func.id
        for node in ast.walk(example_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    used_names = {
        node.id
        for node in ast.walk(example_tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    declared_symbols = (
        declared_classes | declared_functions | declared_aliases | declared_imports
    )
    undeclared_symbols = sorted(symbols - declared_symbols)
    if undeclared_symbols:
        raise ContractTraceabilityError(
            f"{contract.name} inventory names undeclared symbols: "
            f"{undeclared_symbols}"
        )

    missing_classes = sorted((symbols & declared_classes) - calls)
    missing_functions = sorted((symbols & declared_functions) - calls)
    referenced_symbols = declared_aliases | declared_imports
    missing_aliases = sorted(
        (symbols & referenced_symbols)
        - declared_classes
        - declared_functions
        - used_names
    )
    if missing_classes or missing_functions or missing_aliases:
        raise ContractTraceabilityError(
            f"{contract.name} incomplete worked example: "
            f"models={missing_classes}, operations={missing_functions}, "
            f"aliases={missing_aliases}"
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
    edges = _parse_rule_edges(root, checklist, markers, rules)
    for contract in contracts:
        validate_contract_example(contract)
    graph = ContractTraceabilityGraph(
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=edges,
    )
    serialize_contract_traceability(graph)
    return graph
