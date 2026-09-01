# Contract traceability Phase 0 pair-coding guide

This is the implementation authority for contract-requirement traceability.
The [contract](contract-requirement-traceability.md) defines what must become
true. The [master checklist](master-execution-checklist.md#71-contract-requirement-traceability)
owns order and completion. This guide supplies the exact edit for each pair
cycle.

The identifier for this subsystem is `CRT`.

## 1. Status and boundary

**Guide status:** proposed implementation, reviewed against `main` at commit
`1821b8c`.

The records in `src/viper/_contract_traceability.py` already exist. The
parsers, compiler operations, and focused acceptance tests remain proposed.
Each `python pair-edit` fence contains code for the user to apply during its
named pair cycle. Repository implementation begins when the user applies that
edit.

This phase changes only contract traceability:

```text
existing ContractRequirement, VerifierRule, RuleEdge, and ContractTrace models
-> parse authored contract and checklist declarations
-> validate their joins and concrete examples
-> compile ContractTraceabilityGraph
-> serialize canonical JSON bytes
```

Project-root work precedes `P0-CRT-01` because the compiler accepts one
resolved project root. SystemGraph work follows `P0-CRT-05` because it
consumes the compiled traceability graph.

## 2. Pair-cycle contract

Every block contains:

- one stable block ID and its governing contract requirements;
- exact prerequisite blocks;
- exact target symbols;
- the complete proposed edit for that cycle;
- exact observing tests and one focused command; and
- a stop condition stated beside the edit.

The user applies one block. Codex inspects the saved result. The user runs its
focused gate. The pair advances only from the observed output.

The dependency path is:

```text
P0-PDR-05
    |
    v
P0-CRT-01 -> P0-PROOF-01
    |
    v
P0-CRT-02 -> P0-PROOF-02
    |
    v
P0-CRT-03 -> P0-PROOF-03
    |
    +----------> P0-CRT-04
                    |
                    v
              P0-CRT-05 -> P0-PROOF-04
```

## 3. Production PairBlocks

<!-- pair-block-definition: P0-CRT-01 -->
```toml pair-block
id = "P0-CRT-01"
requirements = ["CRT-01"]
targets = ["src/viper/_contract_traceability.py:_parse_requirement_markers", "src/viper/_contract_traceability.py:_parse_verifier_rules"]
tests = ["tests/test_contract_traceability.py:test_requirement_rows_and_rules_compile", "tests/test_contract_traceability.py:test_requirement_rows_reject_duplicate_and_orphan_ids"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k requirement_rows -q"
depends_on = ["P0-PDR-05"]
```

Add the imports, error, private row type, patterns, and both complete parsers
after `ContractTraceabilityGraph`.

```python pair-edit
import re
from dataclasses import dataclass
from pathlib import Path


class ContractTraceabilityError(ValueError):
    """Report an invalid or incomplete traceability declaration."""


@dataclass(frozen=True)
class _RequirementMarker:
    requirement: ContractRequirement
    phase: int
    test_path: str


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


def _duplicates(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(value for value in set(values) if values.count(value) > 1))


def _parse_requirement_markers(
    root: Path,
    contract: Path,
) -> tuple[_RequirementMarker, ...]:
    contract_path = contract.relative_to(root).as_posix()
    markers: list[_RequirementMarker] = []
    for match in _REQUIREMENT_ROW.finditer(contract.read_text(encoding="utf-8")):
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
    requirement_ids = {
        marker.requirement.requirement_id for marker in requirements
    }
    rules: list[VerifierRule] = []
    for match in _VERIFIER_RULE_ROW.finditer(contract.read_text(encoding="utf-8")):
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
            f"requirements without verifier rules in {contract_path}: {sorted(uncovered)}"
        )
    return tuple(sorted(rules, key=lambda item: item.rule_id))
```

<!-- pair-block-definition: P0-CRT-02 -->
```toml pair-block
id = "P0-CRT-02"
requirements = ["CRT-02"]
targets = ["src/viper/_contract_traceability.py:_parse_rule_edges"]
tests = ["tests/test_contract_traceability.py:test_rule_edges_resolve_one_owner_and_tests", "tests/test_contract_traceability.py:test_rule_edges_reject_missing_symbols"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k rule_edges -q"
depends_on = ["P0-CRT-01"]
```

Add the checklist edge parser after the declaration parsers.

```python pair-edit
import ast


_PHASE_HEADING = re.compile(r"^## \d+\. Phase (?P<phase>\d+)\b", re.MULTILINE)
_RULE_EDGE = re.compile(
    r"<!-- contract-(?P<kind>implementation|verification): "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) "
    r"rule=(?P<rule>[a-z][a-z0-9_.]+) "
    r"state=(?P<state>planned|implemented) "
    r"(?P<label>owner|test)=(?P<target>[^ ]+) -->"
)


def _parse_repo_symbol(value: str) -> RepoSymbolRef:
    path, separator, symbol = value.partition(":")
    if not separator or not path or not symbol:
        raise ContractTraceabilityError(
            f"source reference must use path:symbol: {value}"
        )
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
    requirement_by_id = {
        item.requirement.requirement_id: item for item in requirements
    }
    rule_by_id = {rule.rule_id: rule for rule in rules}
    edges: list[RuleEdge] = []
    for index, phase_match in enumerate(phases):
        phase = int(phase_match.group("phase"))
        end = phases[index + 1].start() if index + 1 < len(phases) else len(text)
        section = text[phase_match.end():end]
        for match in _RULE_EDGE.finditer(section):
            requirement_id = match.group("requirement")
            rule_id = match.group("rule")
            kind = match.group("kind")
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
            state = match.group("state")
            if state == "implemented":
                _require_python_symbol(root, target)
            edges.append(
                RuleEdge(
                    kind=kind,
                    rule_id=rule_id,
                    phase=phase,
                    checklist_line=text.count("\n", 0, phase_match.end() + match.start()) + 1,
                    state=state,
                    target=target,
                )
            )
    keys = [(edge.kind, edge.rule_id, edge.target) for edge in edges]
    if len(keys) != len(set(keys)):
        raise ContractTraceabilityError("duplicate rule edge")
    for rule_id in rule_by_id:
        implementation_count = sum(
            edge.kind == "implementation"
            for edge in edges
            if edge.rule_id == rule_id
        )
        verification_count = sum(
            edge.kind == "verification"
            for edge in edges
            if edge.rule_id == rule_id
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
```

<!-- pair-block-definition: P0-CRT-03 -->
```toml pair-block
id = "P0-CRT-03"
requirements = ["CRT-03"]
targets = ["src/viper/_contract_traceability.py:parse_contract_traces", "src/viper/_contract_traceability.py:validate_contract_example"]
tests = ["tests/test_contract_traceability.py:test_contract_traces_compile", "tests/test_contract_traceability.py:test_contract_traces_reject_incomplete_evidence", "tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k 'contract_traces or contract_examples' -q"
depends_on = ["P0-CRT-02"]
```

Move the existing trace-fence, model-construction, and Mermaid checks from the
documentation oracle into these production operations. Keep the oracle until
parity passes.

```python pair-edit
import ast
import tomllib
from collections.abc import Mapping


_TRACE_FENCE = re.compile(
    r"(?P<fence>\`{3,4})toml contract-trace\n"
    r"(?P<body>.*?)\n(?P=fence)",
    re.DOTALL,
)
_PYTHON_FENCE = re.compile(r"\`\`\`python\n(?P<body>.*?)\n\`\`\`", re.DOTALL)
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


def _trace_mapping(raw: Mapping[str, object]) -> dict[str, object]:
    value = dict(raw)
    value["implementation"] = _parse_repo_symbol(str(value["implementation"]))
    value["test"] = _parse_repo_symbol(str(value["test"]))
    outcome = dict(value["outcome"])
    if outcome.get("kind") == "rejected":
        outcome["rejected_at"] = _parse_repo_symbol(str(outcome["rejected_at"]))
    value["outcome"] = outcome
    return value


def parse_contract_traces(
    root: Path,
    contract: Path,
    requirements: tuple[ContractRequirement, ...],
    rules: tuple[VerifierRule, ...],
    edges: tuple[RuleEdge, ...],
) -> tuple[ContractTrace, ...]:
    contract_ref = contract.relative_to(root).as_posix()
    requirement_ids = {
        item.requirement_id
        for item in requirements
        if item.contract == contract_ref
    }
    rule_by_id = {
        item.rule_id: item
        for item in rules
        if item.contract == contract_ref
    }
    edges_by_rule = {
        rule_id: tuple(edge for edge in edges if edge.rule_id == rule_id)
        for rule_id in rule_by_id
    }

    traces: list[ContractTrace] = []
    for match in _TRACE_FENCE.finditer(contract.read_text(encoding="utf-8")):
        body = match.group("body")
        if _PLACEHOLDER.search(body):
            raise ContractTraceabilityError(
                f"trace contains a placeholder: {contract_ref}"
            )
        trace = ContractTrace.model_validate(
            _trace_mapping(tomllib.loads(body))
        )
        rule = rule_by_id.get(trace.rule_id)
        if trace.requirement_id not in requirement_ids:
            raise ContractTraceabilityError(
                f"{trace.trace_id} names unknown requirement "
                f"{trace.requirement_id}"
            )
        if rule is None or rule.requirement_id != trace.requirement_id:
            raise ContractTraceabilityError(
                f"{trace.trace_id} has an invalid requirement-rule join"
            )

        rule_edges = edges_by_rule[trace.rule_id]
        owners = {
            (edge.target.path, edge.target.symbol)
            for edge in rule_edges
            if edge.kind == "implementation"
        }
        tests = {
            (edge.target.path, edge.target.symbol)
            for edge in rule_edges
            if edge.kind == "verification"
        }
        implementation = (
            trace.implementation.path,
            trace.implementation.symbol,
        )
        test = (trace.test.path, trace.test.symbol)
        if implementation not in owners:
            raise ContractTraceabilityError(
                f"{trace.trace_id} names an unowned implementation"
            )
        if test not in tests:
            raise ContractTraceabilityError(
                f"{trace.trace_id} names an unlinked test"
            )
        if trace.state == "implemented":
            _require_python_symbol(root, trace.implementation)
            _require_python_symbol(root, trace.test)
            if trace.outcome.kind == "rejected":
                _require_python_symbol(root, trace.outcome.rejected_at)
        traces.append(trace)

    duplicate_ids = _duplicates([trace.trace_id for trace in traces])
    if duplicate_ids:
        raise ContractTraceabilityError(
            f"duplicate trace IDs in {contract_ref}: {duplicate_ids}"
        )
    kinds = {trace.outcome.kind for trace in traces}
    if kinds != {"accepted", "rejected"}:
        raise ContractTraceabilityError(
            f"{contract_ref} requires accepted and rejected traces"
        )
    return tuple(sorted(traces, key=lambda item: item.trace_id))


def _assert_dag(diagram: str, contract: Path, index: int) -> None:
    if not diagram.lstrip().startswith("flowchart"):
        raise ContractTraceabilityError(
            f"{contract.name} diagram {index} is not a Mermaid flowchart"
        )
    adjacency: dict[str, set[str]] = {}
    for line in diagram.splitlines():
        edge = _MERMAID_EDGE.match(line)
        if edge is not None:
            adjacency.setdefault(edge.group("source"), set()).add(
                edge.group("target")
            )
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

    models = _section(text, 4)
    examples = tuple(
        re.finditer(
            r"<!-- contract-worked-example: start -->"
            r"(?P<body>.*?)"
            r"<!-- contract-worked-example: end -->",
            models,
            re.DOTALL,
        )
    )
    if len(examples) != 1:
        raise ContractTraceabilityError(
            f"{contract.name} requires one marked worked example"
        )

    declarations = models[: examples[0].start()]
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

    example_blocks = tuple(
        match.group("body")
        for match in _PYTHON_FENCE.finditer(examples[0].group("body"))
    )
    if not example_blocks:
        raise ContractTraceabilityError(
            f"{contract.name} worked example has no Python"
        )
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
        if isinstance(node, ast.Name)
    }

    missing_classes = sorted(declared_classes - calls)
    missing_functions = sorted(declared_functions - calls)
    missing_aliases = sorted(declared_aliases - used_names)
    if missing_classes or missing_functions or missing_aliases:
        raise ContractTraceabilityError(
            f"{contract.name} incomplete worked example: "
            f"models={missing_classes}, operations={missing_functions}, "
            f"aliases={missing_aliases}"
        )
```

<!-- pair-block-definition: P0-CRT-04 -->
```toml pair-block
id = "P0-CRT-04"
requirements = ["CRT-03"]
targets = ["tests/test_documentation.py:CONTRACTS_WITH_COMPLETE_EXAMPLES"]
tests = ["tests/test_documentation.py:test_phase_zero_contracts_show_three_dags_and_instantiate_models"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k phase_zero_contracts_show_three_dags_and_instantiate_models -q"
depends_on = ["P0-CRT-03"]
```

Expand the validated contract set only after every contract has the required
three diagrams and complete worked example.

Migrate these contracts one at a time, in checklist order:

1. `download-retrieval-artifacts.md`
2. `external-input-roots.md`
3. `unified-metric-drafting.md`
4. `automatic-input-resolution.md`
5. `frozen-plan-git-identity.md`
6. `remote-storage.md`
7. `experiment-expansion.md`
8. `provenance-catalog-mcp.md`
9. `stage-reuse.md`
10. `experiment-knowledge-primitives.md`

For each contract, add its verifier-rule rows, current DAG, proposed-change
DAG, integrated DAG, complete Section 4 declarations, marked worked example,
accepted trace, and rejected trace before adding its path to the validated
tuple. The contract-gap skill defines the required contents of those sections;
this block controls only their repository-wide migration and acceptance gate.

```python pair-edit
CONTRACTS_WITH_COMPLETE_EXAMPLES = IMPLEMENTATION_CONTRACTS
```

<!-- pair-block-definition: P0-CRT-05 -->
```toml pair-block
id = "P0-CRT-05"
requirements = ["CRT-04"]
targets = ["src/viper/_contract_traceability.py:compile_contract_traceability", "src/viper/_contract_traceability.py:serialize_contract_traceability"]
tests = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_traceability_graph -q"
depends_on = ["P0-CRT-03", "P0-CRT-04"]
```

Compile the joined records and serialize their canonical representation.

```python pair-edit
import json


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
    traces = tuple(
        trace
        for contract in contracts
        for trace in parse_contract_traces(
            root,
            contract,
            requirements,
            rules,
            edges,
        )
    )
    if _duplicates([item.trace_id for item in traces]):
        raise ContractTraceabilityError("trace ID belongs to several contracts")
    graph = ContractTraceabilityGraph(
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=edges,
        traces=tuple(sorted(traces, key=lambda item: item.trace_id)),
    )
    serialize_contract_traceability(graph)
    return graph
```

## 4. Acceptance PairBlocks

Use one connected temporary repository across rejection tests. Each test
changes only the declaration or symbol named by the failure case.

<!-- pair-block-definition: P0-PROOF-01 -->
```toml pair-block
id = "P0-PROOF-01"
requirements = ["CRT-01"]
targets = ["tests/test_contract_traceability.py:_write_fixture", "tests/test_contract_traceability.py:test_requirement_rows_and_rules_compile", "tests/test_contract_traceability.py:test_requirement_rows_reject_duplicate_and_orphan_ids"]
tests = ["tests/test_contract_traceability.py:test_requirement_rows_and_rules_compile", "tests/test_contract_traceability.py:test_requirement_rows_reject_duplicate_and_orphan_ids"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k requirement_rows -q"
depends_on = ["P0-CRT-01"]
```

Create `tests/test_contract_traceability.py`. This first block owns the one
connected fixture used by every later proof.

```python pair-edit
from pathlib import Path
from textwrap import dedent

import pytest

from viper._contract_traceability import (
    ContractTraceabilityError,
    _parse_requirement_markers,
    _parse_verifier_rules,
)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    contract = tmp_path / "docs/development/example.md"
    checklist = tmp_path / "docs/development/master-execution-checklist.md"
    source = tmp_path / "src/owner.py"
    test = tmp_path / "tests/test_owner.py"
    for path in (contract, checklist, source, test):
        path.parent.mkdir(parents=True, exist_ok=True)

    source.write_text(
        "def enforce() -> str:\n    return 'accepted'\n",
        encoding="utf-8",
    )
    test.write_text(
        "def test_enforce() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    checklist.write_text(
        dedent(
            """
            ## 7. Phase 0

            <!-- contract-implementation: requirement=CRT-01
            rule=contract.rule state=implemented
            owner=src/owner.py:enforce -->
            <!-- contract-verification: requirement=CRT-01
            rule=contract.rule state=implemented
            test=tests/test_owner.py:test_enforce -->
            """
        ).replace("\nrule=", " rule=").replace("\nowner=", " owner=")
        .replace("\ntest=", " test="),
        encoding="utf-8",
    )
    contract.write_text(
        dedent(
            """
            # Example contract

            ## 1. Status

            | Requirement | Claim |
            |---|---|
            | CRT-01 <!-- contract-requirement: CRT-01 phase=0 test=tests/test_contract_traceability.py --> | Compile one exact rule. |

            ## 2. Required claim

            The compiler joins the rule to its owner and test.

            ## 3. Current gap

            ### Current DAG

            ```mermaid
            flowchart LR
                A["Requirement"]
                B["Missing join"]
                A --> B
            ```

            ### Proposed-change DAG

            ```mermaid
            flowchart LR
                C["RuleEdge"]
                D["Resolved symbol"]
                C --> D
            ```

            ### Integrated DAG

            ```mermaid
            flowchart LR
                A["Requirement"]
                C["RuleEdge"]
                D["Resolved symbol"]
                A --> C
                C --> D
            ```

            ## 4. Contract models

            [PYTHON]
            class ExampleRecord:
                def __init__(self, value: str) -> None:
                    self.value = value


            def build_record(value: str) -> ExampleRecord:
                return ExampleRecord(value)
            [END]

            <!-- contract-worked-example: start -->
            [PYTHON]
            declared = ExampleRecord("declared")
            built = build_record(declared.value)
            assert built.value == "declared"
            [END]
            <!-- contract-worked-example: end -->

            ## 5. Execution

            The compiler parses the rule.

            ## 6. Persisted evidence

            Canonical graph bytes retain the join.

            ## 7. Verification

            | Rule | Statement |
            |---|---|
            | `contract.rule` <!-- verifier-rule: contract.rule requirement=CRT-01 --> | One owner and one test exist. |

            ## 8. Propagation

            The source and test symbols enter the graph.

            ## 9. Acceptance case

            ```toml contract-trace
            trace_id = "accepted-rule"
            requirement_id = "CRT-01"
            rule_id = "contract.rule"
            state = "implemented"
            scenario = "The compiler accepts one complete rule."
            setup = "The contract and checklist contain matching markers."
            input = "contract.rule"
            invocation = "compile_contract_traceability(root, checklist, contracts)"
            implementation = "src/owner.py:enforce"
            test = "tests/test_owner.py:test_enforce"

            [outcome]
            kind = "accepted"
            result = "The graph contains the rule, owner, and test."
            evidence = [".viper/system/contracts/traceability.json"]
            ```

            ```toml contract-trace
            trace_id = "rejected-rule"
            requirement_id = "CRT-01"
            rule_id = "contract.rule"
            state = "implemented"
            scenario = "The compiler rejects a missing rule owner."
            setup = "The rule lacks a matching implementation marker."
            input = "contract.rule"
            invocation = "compile_contract_traceability(root, checklist, contracts)"
            implementation = "src/owner.py:enforce"
            test = "tests/test_owner.py:test_enforce"

            [outcome]
            kind = "rejected"
            rejected_at = "src/owner.py:enforce"
            error_type = "ContractTraceabilityError"
            message_match = "requires exactly one implementation edge"
            ```

            ## 10. Implementation order

            Parse declarations before edges.
            """
        ).replace(
            "[PYTHON]",
            chr(96) * 3 + "python",
        ).replace(
            "[END]",
            chr(96) * 3,
        ),
        encoding="utf-8",
    )
    return contract, checklist


def test_requirement_rows_and_rules_compile(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)

    assert [item.requirement.requirement_id for item in markers] == ["CRT-01"]
    assert [item.rule_id for item in rules] == ["contract.rule"]


def test_requirement_rows_reject_duplicate_and_orphan_ids(
    tmp_path: Path,
) -> None:
    contract, _ = _write_fixture(tmp_path)
    original = contract.read_text(encoding="utf-8")
    requirement_row = next(
        line for line in original.splitlines()
        if line.startswith("| CRT-01 <!-- contract-requirement:")
    )
    contract.write_text(
        f"{original}\n{requirement_row}\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ContractTraceabilityError,
        match="duplicate requirements",
    ):
        _parse_requirement_markers(tmp_path, contract)

    contract.write_text(
        original.replace(
            "verifier-rule: contract.rule requirement=CRT-01",
            "verifier-rule: contract.rule requirement=CRT-99",
            1,
        ),
        encoding="utf-8",
    )
    markers = _parse_requirement_markers(tmp_path, contract)
    with pytest.raises(
        ContractTraceabilityError,
        match="names unknown requirement CRT-99",
    ):
        _parse_verifier_rules(tmp_path, contract, markers)
```

**Stop:** both requirement-row tests pass. Edge parsing begins in the next
cycle.

<!-- pair-block-definition: P0-PROOF-02 -->
```toml pair-block
id = "P0-PROOF-02"
requirements = ["CRT-02"]
targets = ["tests/test_contract_traceability.py:test_rule_edges_resolve_one_owner_and_tests", "tests/test_contract_traceability.py:test_rule_edges_reject_missing_symbols"]
tests = ["tests/test_contract_traceability.py:test_rule_edges_resolve_one_owner_and_tests", "tests/test_contract_traceability.py:test_rule_edges_reject_missing_symbols"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k rule_edges -q"
depends_on = ["P0-CRT-02", "P0-PROOF-01"]
```

Extend the imports in `tests/test_contract_traceability.py`, then add both
tests below the requirement-row tests.

```python pair-edit
from viper._contract_traceability import (
    _parse_rule_edges,
)


def test_rule_edges_resolve_one_owner_and_tests(tmp_path: Path) -> None:
    contract, checklist = _write_fixture(tmp_path)
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)
    edges = _parse_rule_edges(
        tmp_path,
        checklist,
        markers,
        rules,
    )

    assert [(edge.kind, edge.target.symbol) for edge in edges] == [
        ("implementation", "enforce"),
        ("verification", "test_enforce"),
    ]


def test_rule_edges_reject_missing_symbols(tmp_path: Path) -> None:
    contract, checklist = _write_fixture(tmp_path)
    checklist.write_text(
        checklist.read_text(encoding="utf-8").replace(
            "src/owner.py:enforce",
            "src/owner.py:absent",
        ),
        encoding="utf-8",
    )
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)

    with pytest.raises(
        ContractTraceabilityError,
        match="source symbol is missing: src/owner.py:absent",
    ):
        _parse_rule_edges(tmp_path, checklist, markers, rules)
```

**Stop:** both edge tests pass. Trace parsing begins in the next cycle.

<!-- pair-block-definition: P0-PROOF-03 -->
```toml pair-block
id = "P0-PROOF-03"
requirements = ["CRT-03"]
targets = ["tests/test_contract_traceability.py:test_contract_traces_compile", "tests/test_contract_traceability.py:test_contract_traces_reject_incomplete_evidence", "tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure"]
tests = ["tests/test_contract_traceability.py:test_contract_traces_compile", "tests/test_contract_traceability.py:test_contract_traces_reject_incomplete_evidence", "tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k 'contract_traces or contract_examples' -q"
depends_on = ["P0-CRT-03", "P0-PROOF-02"]
```

Extend the imports, then add these tests.

```python pair-edit
from viper._contract_traceability import (
    parse_contract_traces,
    validate_contract_example,
)


def _fixture_graph_parts(
    root: Path,
    contract: Path,
    checklist: Path,
):
    markers = _parse_requirement_markers(root, contract)
    requirements = tuple(marker.requirement for marker in markers)
    rules = _parse_verifier_rules(root, contract, markers)
    edges = _parse_rule_edges(root, checklist, markers, rules)
    return requirements, rules, edges


def test_contract_traces_compile(tmp_path: Path) -> None:
    contract, checklist = _write_fixture(tmp_path)
    requirements, rules, edges = _fixture_graph_parts(
        tmp_path,
        contract,
        checklist,
    )

    traces = parse_contract_traces(
        tmp_path,
        contract,
        requirements,
        rules,
        edges,
    )
    validate_contract_example(contract)

    assert {trace.outcome.kind for trace in traces} == {
        "accepted",
        "rejected",
    }


def test_contract_traces_reject_incomplete_evidence(tmp_path: Path) -> None:
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'scenario = "The compiler accepts one complete rule."',
            'scenario = "' + "TO" + 'DO"',
        ),
        encoding="utf-8",
    )
    requirements, rules, edges = _fixture_graph_parts(
        tmp_path,
        contract,
        checklist,
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="trace contains a placeholder",
    ):
        parse_contract_traces(
            tmp_path,
            contract,
            requirements,
            rules,
            edges,
        )


def test_contract_examples_reject_incomplete_structure(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "### Integrated DAG",
            "### Merged graph",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="requires ordered current, proposed-change, and integrated",
    ):
        validate_contract_example(contract)
```

**Stop:** the accepted trace and both targeted rejections pass. Complete graph
compilation begins in the next cycle.

<!-- pair-block-definition: P0-PROOF-04 -->
```toml pair-block
id = "P0-PROOF-04"
requirements = ["CRT-04"]
targets = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids"]
tests = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_traceability_graph -q"
depends_on = ["P0-CRT-05", "P0-PROOF-03"]
```

Extend the imports, then add the final compiler tests.

```python pair-edit
from viper._contract_traceability import (
    compile_contract_traceability,
    serialize_contract_traceability,
)


def test_contract_traceability_graph_is_canonical(tmp_path: Path) -> None:
    contract, checklist = _write_fixture(tmp_path)
    contracts = (contract,)

    left = compile_contract_traceability(
        tmp_path,
        checklist,
        contracts,
    )
    right = compile_contract_traceability(
        tmp_path,
        checklist,
        contracts,
    )

    assert left == right
    assert serialize_contract_traceability(left) == (
        serialize_contract_traceability(right)
    )
    for rule in left.rules:
        links = tuple(
            edge for edge in left.edges if edge.rule_id == rule.rule_id
        )
        assert sum(edge.kind == "implementation" for edge in links) == 1
        assert sum(edge.kind == "verification" for edge in links) >= 1


def test_contract_traceability_graph_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    contract, checklist = _write_fixture(tmp_path)

    with pytest.raises(
        ContractTraceabilityError,
        match="requirement ID belongs to several contracts",
    ):
        compile_contract_traceability(
            tmp_path,
            checklist,
            (contract, contract),
        )
```

**Stop:** both graph tests pass with byte-identical repeated compilation.

## 5. Pair execution

For one block:

```text
Codex inspects the current target and its direct consumers
-> Codex gives this block's one bounded edit
-> user applies the edit
-> Codex inspects the saved file
-> user runs the block's focused gate
-> pair diagnoses the exact output
-> commit and push only when the block is independently valid
```

A failed gate keeps the pair in the current block. A code block may include a
small mechanical propagation when separating it would leave the module unable
to import. The block stays within its current behavior and test.

Cycle `P0-CRT-04` is the only repeated migration. Add one contract to
`CONTRACTS_WITH_COMPLETE_EXAMPLES` after that contract receives all three
DAGs, its complete worked example, verifier-rule markers, and accepted and
rejected traces. Run the focused gate after each contract.

## 6. Phase gate

After all nine PairBlocks pass, run:

```bash
conda run -n mantra python -m pytest tests/test_documentation.py -q
```

Then run the focused SystemGraph consumer boundary:

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k 'contract_compiler or system_graph_preserves_contract_traceability' -q
```

Phase 0 contract traceability closes only when:

- every CRT checklist box is checked;
- every CRT implementation and verification marker has
  `state=implemented`;
- repeated compilation produces byte-identical JSON;
- the complete documentation boundary passes;
- the SystemGraph consumer boundary passes; and
- the review-cycle commit is synchronized with its upstream.

## 7. SystemGraph handoff

`compile_contract_traceability()` returns the only traceability input accepted
by `compile_contract_delta()`:

```text
ContractTraceabilityGraph.requirements
ContractTraceabilityGraph.rules
ContractTraceabilityGraph.edges
ContractTraceabilityGraph.traces
```

Contract traceability owns declaration parsing, joins, cardinality, worked
examples, and canonical bytes. SystemGraph owns dependency lowering, impact
traversal, propagation coverage, and target constraints.
