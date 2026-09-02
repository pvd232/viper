# Contract Traceability Pair-Coding Guide

This is the implementation authority for contract-requirement traceability.
The [contract](contract-traceability.md) defines what must become
true. The [master checklist](master-execution-checklist.md#72-contract-traceability)
owns order and completion. This guide supplies the exact edit for each pair
cycle.

The identifier for this subsystem is `CRT`.

## 1. Status and boundary

**Guide status:** implemented through `P0-CRT-05`; the draft `CRT-06`
extension remains unimplemented and pending review.

The compiler operations exist in `src/viper/_contract_traceability.py`, their
focused tests exist in `tests/test_contract_traceability.py`, and every
implementation contract passes the shared DAG, symbol-inventory, and worked-
example gate. Each `python pair-edit` fence retains the approved code for its
named pair cycle.

This guide changes only contract traceability during Master Phase 0:

```text
existing ContractRequirement, VerifierRule, and RuleEdge models
-> parse authored contract and checklist declarations
-> compile exact source targets and PairBlocks
-> validate requirement-rule joins and concrete examples
-> compile ContractTraceabilityGraph
-> serialize canonical JSON bytes
```

Every compiled requirement, rule, edge, and symbol retains the exact source
path, line span, and digest of its authored declaration. The System Impact
Check can then consume the CTG without reparsing Markdown.

Project-root work precedes `P0-CRT-01` because the compiler accepts one
resolved project root. System Impact follows `P0-CRT-07` because it consumes
the closed target and PairBlock plan.

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
                    |
                    v
              P0-CRT-06
                    |
                    v
              P0-CRT-07 -> P0-PROOF-08
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

**Context:** Contract requirements and verifier rules are still Markdown text.
These parsers turn them into typed, source-anchored records and reject duplicate
IDs, mismatched labels, orphan rules, and requirements with no rule.

Add the imports, error, private row type, patterns, and both complete parsers
after `ContractTraceabilityGraph`.

`src/viper/_contract_traceability.py`

```python pair-edit
import hashlib
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
    requirement_ids = {
        marker.requirement.requirement_id for marker in requirements
    }
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

**Context:** A rule does not identify the code that enforces it or the test that
observes it. This parser joins checklist markers to exact Python symbols and
rejects missing, duplicate, or inconsistent links.

Add the checklist edge parser after the declaration parsers.

`src/viper/_contract_traceability.py`

```python pair-edit
import ast
from typing import cast


_PHASE_HEADING = re.compile(
    r"^## \d+\. Master Phase (?P<phase>\d+)\b", re.MULTILINE
)
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
            declaration_start = phase_match.end() + match.start()
            declaration_end = phase_match.end() + match.end()
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
requirements = ["CRT-03", "CRT-05"]
targets = ["src/viper/_contract_traceability.py:_parse_contract_symbols", "src/viper/_contract_traceability.py:validate_contract_example"]
tests = ["tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure", "tests/test_contract_traceability.py:test_contract_symbols_compile_complete_inventory", "tests/test_contract_traceability.py:test_contract_symbols_reject_missing_section_model", "tests/test_contract_traceability.py:test_contract_examples_require_registered_symbols"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_examples -q"
depends_on = ["P0-CRT-02"]
```

**Context:** The documentation test checks selected worked-example symbols but
does not inventory every Section 4 declaration. This block adds the complete
contract inventory, requires example symbols to be a subset, and keeps the DAG
and worked-example checks in one reusable compiler boundary.

Move the existing model-construction and Mermaid checks from the documentation
oracle into this production operation. Keep the oracle until parity passes.

`src/viper/_contract_traceability.py`

```python pair-edit
import ast
from typing import cast


_PYTHON_FENCE = re.compile(r"\`\`\`python\n(?P<body>.*?)\n\`\`\`", re.DOTALL)
_CONTRACT_EXAMPLE_SYMBOLS = re.compile(
    r"<!-- contract-example-symbols:\s*(?P<body>\[.*?\])\s*-->",
    re.DOTALL,
)
_CONTRACT_SYMBOLS = re.compile(
    r"<!-- contract-symbols:\s*(?P<body>\{.*?\})\s*-->",
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


def _python_declarations(text: str, filename: str) -> dict[str, set[str]]:
    declarations = {"models": set(), "aliases": set(), "functions": set()}
    declarations["imports"] = set()
    for match in _PYTHON_FENCE.finditer(text):
        tree = ast.parse(match.group("body"), filename=filename)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                declarations["models"].add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                declarations["functions"].add(node.name)
            elif isinstance(node, ast.Assign):
                declarations["aliases"].update(
                    target.id
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Name
            ):
                declarations["aliases"].add(node.target.id)
            elif isinstance(node, ast.Import):
                declarations["imports"].update(
                    alias.asname or alias.name.split(".", maxsplit=1)[0]
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                declarations["imports"].update(
                    alias.asname or alias.name for alias in node.names
                )
    return declarations


def _load_symbol_inventory(contract: Path) -> dict[str, tuple[str, ...]]:
    text = contract.read_text(encoding="utf-8")
    markers = tuple(_CONTRACT_SYMBOLS.finditer(text))
    if len(markers) != 1:
        raise ContractTraceabilityError(
            f"{contract.name} requires one contract-symbols inventory"
        )
    try:
        loaded = json.loads(markers[0].group("body"))
    except json.JSONDecodeError as error:
        raise ContractTraceabilityError(
            f"{contract.name} has an invalid contract-symbols inventory"
        ) from error
    keys = ("models", "aliases", "functions")
    if not isinstance(loaded, dict) or set(loaded) != set(keys):
        raise ContractTraceabilityError(
            f"{contract.name} contract-symbols requires models, aliases, and functions"
        )
    inventory: dict[str, tuple[str, ...]] = {}
    for key in keys:
        values = loaded[key]
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str) or not value.isidentifier()
                for value in values
            )
            or values != sorted(set(values))
        ):
            raise ContractTraceabilityError(
                f"{contract.name} contract-symbols {key} must be sorted unique "
                "Python identifiers"
            )
        inventory[key] = tuple(values)
    all_names = [name for values in inventory.values() for name in values]
    if not all_names or len(all_names) != len(set(all_names)):
        raise ContractTraceabilityError(
            f"{contract.name} contract-symbols must inventory each symbol once"
        )
    return inventory


def _parse_contract_symbols(
    root: Path,
    contract: Path,
) -> tuple[ContractSymbol, ...]:
    text = contract.read_text(encoding="utf-8")
    inventory = _load_symbol_inventory(contract)
    marker = next(_CONTRACT_SYMBOLS.finditer(text))
    marker_ref = _declaration_ref(
        root,
        contract,
        text,
        marker.start(),
        marker.end(),
    )

    available = _python_declarations(text, str(contract))
    available_names = set().union(*available.values())
    inventoried_names = set().union(
        *(set(values) for values in inventory.values())
    )
    missing = sorted(inventoried_names - available_names)
    if missing:
        raise ContractTraceabilityError(
            f"{contract.name} contract-symbols names undeclared symbols: {missing}"
        )

    models = _section(text, 4)
    example = _CONTRACT_WORKED_EXAMPLE.search(models)
    if example is not None:
        models = models[: example.start()] + models[example.end() :]
    required = _python_declarations(models, f"{contract}:section-4")
    for key in ("models", "aliases", "functions"):
        omitted = sorted(required[key] - set(inventory[key]))
        if omitted:
            raise ContractTraceabilityError(
                f"{contract.name} contract-symbols omits Section 4 {key}: "
                f"{omitted}"
            )

    kinds = {"models": "model", "aliases": "alias", "functions": "function"}
    contract_path = contract.relative_to(root).as_posix()
    return tuple(
        ContractSymbol(
            kind=cast(ContractSymbolKind, kinds[key]),
            name=name,
            contract=contract_path,
            declaration=marker_ref,
        )
        for key in ("models", "aliases", "functions")
        for name in inventory[key]
    )


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
    contract_symbols = set().union(*_load_symbol_inventory(contract).values())
    uncovered_symbols = sorted(symbols - contract_symbols)
    if uncovered_symbols:
        raise ContractTraceabilityError(
            f"{contract.name} example symbols absent from contract-symbols: "
            f"{uncovered_symbols}"
        )

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
```

<!-- pair-block-definition: P0-CRT-04 -->
```toml pair-block
id = "P0-CRT-04"
requirements = ["CRT-03"]
targets = ["tests/test_documentation.py:CONTRACTS_WITH_COMPLETE_EXAMPLES"]
tests = ["tests/test_documentation.py:test_contract_examples_are_complete"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_examples_are_complete -q"
depends_on = ["P0-CRT-03"]
```

**Context:** Only migrated contracts can enter the compiled traceability graph.
This block adds each contract after its diagrams, explicit example-symbol
inventory, and worked example satisfy the shared contract structure.

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
11. `research-memory-roadmap.md`

For each contract, add its verifier-rule rows, current DAG, proposed-change
DAG, integrated DAG, explicit example-symbol inventory, and marked worked
example before adding its path to the validated tuple. The inventory names the
contract surface that the example must exercise independently of document
position. The contract-gap skill defines the required contents; this
block controls only their repository-wide migration and acceptance gate.

`tests/test_documentation.py`

```python pair-edit
CONTRACTS_WITH_COMPLETE_EXAMPLES = IMPLEMENTATION_CONTRACTS
```

<!-- pair-block-definition: P0-CRT-05 -->
```toml pair-block
id = "P0-CRT-05"
requirements = ["CRT-04", "CRT-05"]
targets = ["src/viper/_contract_traceability.py:compile_contract_traceability", "src/viper/_contract_traceability.py:serialize_contract_traceability"]
tests = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_traceability_graph -q"
depends_on = ["P0-CRT-03", "P0-CRT-04"]
```

**Context:** Parsed requirements, rules, and edges remain separate collections
until one operation joins and orders them. This block creates the complete graph
and emits stable bytes for later comparison and verification.

Compile the joined records and serialize their canonical representation.

`src/viper/_contract_traceability.py`

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
    symbols = tuple(
        symbol
        for contract in contracts
        for symbol in _parse_contract_symbols(root, contract)
    )
    for contract in contracts:
        validate_contract_example(contract)
    graph = ContractTraceabilityGraph(
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=edges,
        symbols=tuple(
            sorted(
                symbols,
                key=lambda item: (item.contract, item.kind, item.name),
            )
        ),
    )
    serialize_contract_traceability(graph)
    return graph
```

<!-- pair-block-definition: P0-CRT-06 -->
```toml pair-block
id = "P0-CRT-06"
requirements = ["CRT-06"]
targets = ["src/viper/_contract_traceability.py:ContractTarget", "src/viper/_contract_traceability.py:PairBlock", "src/viper/_contract_traceability.py:RuleEdge", "src/viper/_contract_traceability.py:ContractTraceabilityGraph", "src/viper/_contract_traceability.py:_validate_plan"]
tests = ["tests/test_contract_traceability.py:test_contract_targets_require_exact_block_coverage", "tests/test_contract_traceability.py:test_rule_edges_match_pair_blocks", "tests/test_contract_traceability.py:test_pair_block_dependencies_are_acyclic"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k 'contract_targets or rule_edges_match_pair_blocks or pair_block_dependencies' -q"
depends_on = ["P0-CRT-05"]
```

**Context:** The current graph proves rule ownership but leaves the exact edits
and their execution blocks outside the graph. This block adds that join. A
target says which symbol changes, whether it is added, updated, or removed, and
which exact PairBlock declaration specifies the desired code.

Replace the current symbol-inventory models and add the plan parser and closure
validator.

`src/viper/_contract_traceability.py`

```python pair-edit
PairBlockId = Annotated[
    str,
    Field(pattern=r"^P[0-9]+-[A-Z]{3}-[0-9]{2}$"),
]
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
            "Authored PairBlock payload containing the desired declaration for "
            "an add or update, or the exact removal marker for a removal."
        )
    )


class PairBlock(ProtocolModel):
    """Store one bounded, dependency-ordered implementation step."""

    block_id: PairBlockId = Field(
        description="Stable identifier used by checklist and target records."
    )
    requirements: tuple[RequirementId, ...] = Field(
        min_length=1,
        description="Contract requirements implemented by this block."
    )
    targets: tuple[RepoSymbolRef, ...] = Field(
        min_length=1,
        description="Repository symbols this block changes."
    )
    tests: tuple[RepoSymbolRef, ...] = Field(
        min_length=1,
        description="Exact pytest functions that observe this block."
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
    phase: int = Field(
        ge=0,
        description="Checklist phase that schedules this relationship."
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
    """Store the complete ordered contract and implementation plan."""

    schema_version: Literal[5] = Field(
        default=5,
        description="Format version of the serialized traceability graph."
    )
    requirements: tuple[ContractRequirement, ...] = Field(
        min_length=1,
        description="Ordered contract requirements represented by the graph."
    )
    rules: tuple[VerifierRule, ...] = Field(
        min_length=1,
        description="Ordered verifier rules represented by the graph."
    )
    edges: tuple[RuleEdge, ...] = Field(
        min_length=1,
        description="Ordered implementation and verification relationships."
    )
    targets: tuple[ContractTarget, ...] = Field(
        min_length=1,
        description="Ordered source changes required by the contracts."
    )
    blocks: tuple[PairBlock, ...] = Field(
        min_length=1,
        description="Ordered implementation blocks that apply the source changes."
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
            raise ContractTraceabilityError("ContractTarget requirement is absent from PairBlock")
        if target.target not in block.targets:
            raise ContractTraceabilityError("ContractTarget is absent from PairBlock.targets")

    for block in blocks:
        for target in block.targets:
            if (block.block_id, target) not in target_keys:
                raise ContractTraceabilityError("PairBlock target lacks ContractTarget")
        for dependency in block.depends_on:
            if dependency not in block_by_id:
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
            visit(dependency)
        visiting.remove(block_id)
        visited.add(block_id)

    for block_id in block_by_id:
        visit(block_id)

    for edge in edges:
        rule = rule_by_id[edge.rule_id]
        block = block_by_id.get(edge.block_id)
        if block is None:
            raise ContractTraceabilityError("RuleEdge names unknown PairBlock")
        if rule.requirement_id not in block.requirements:
            raise ContractTraceabilityError("RuleEdge requirement is absent from PairBlock")
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
```

Stop after the models and closure validator import cleanly. The next block owns
marker parsing and repository-wide migration.

<!-- pair-block-definition: P0-CRT-07 -->
```toml pair-block
id = "P0-CRT-07"
requirements = ["CRT-06"]
targets = ["src/viper/_contract_traceability.py:_parse_pair_blocks", "src/viper/_contract_traceability.py:_parse_rule_edges", "src/viper/_contract_traceability.py:compile_contract_traceability"]
tests = ["tests/test_contract_traceability.py:test_contract_targets_require_exact_block_coverage"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py tests/test_documentation.py -k 'contract_target or pair_block' -q"
depends_on = ["P0-CRT-06"]
```

**Context:** Strict closure can start only after every existing target has an
action and declaration. Migrate one PairBlock at a time, then remove the three
obsolete symbol and export inventories after exact target parity.

`src/viper/_contract_traceability.py`

```python pair-edit
import tomllib
from typing import Any


_PAIR_BLOCK = re.compile(
    r"<!-- pair-" r"block-definition: (?P<id>P[0-9]+-[A-Z]{3}-[0-9]{2}) -->\\n"
    r"```toml pair-block\\n(?P<manifest>.*?)\\n```(?P<body>.*?)"
    r"(?=<!-- pair-" r"block-definition: |\\Z)",
    re.DOTALL,
)
_TARGET_MARKER = re.compile(
    r"<!-- contract-target: requirements=(?P<requirements>[^ ]+) "
    r"action=(?P<action>add|update|remove) "
    r"target=(?P<target>[^ ]+) -->"
)
_PAIR_EDIT_FENCE = re.compile(
    r"```python pair-edit\\n(?P<body>.*?)\\n```",
    re.DOTALL,
)
_REMOVE_MARKER = re.compile(r"<!-- contract-remove -->")
_CHECKBOX = re.compile(
    r"^- \\[[ xX]\\] .*?(?=^- \\[[ xX]\\] |^### |^## |\\Z)",
    re.MULTILINE | re.DOTALL,
)
_PAIR_BLOCK_MARKER = re.compile(
    r"<!-- pair-block: (?P<id>P[0-9]+-[A-Z]{3}-[0-9]{2}) -->"
)


def _parse_pair_blocks(
    root: Path,
    guides: tuple[Path, ...],
) -> tuple[tuple[PairBlock, ...], tuple[ContractTarget, ...]]:
    """Compile PairBlocks and their exact target declarations."""
    blocks: list[PairBlock] = []
    targets: list[ContractTarget] = []
    for guide in guides:
        text = guide.read_text(encoding="utf-8")
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
                tests=tuple(
                    _parse_repo_symbol(value) for value in manifest["tests"]
                ),
                gate=manifest["gate"],
                depends_on=tuple(manifest["depends_on"]),
                declaration=_declaration_ref(
                    root,
                    guide,
                    text,
                    match.start("manifest"),
                    match.end("manifest"),
                ),
            )
            body = match.group("body")
            target_markers = tuple(_TARGET_MARKER.finditer(body))
            for target_marker in target_markers:
                action = target_marker.group("action")
                if action == "remove":
                    declaration = _REMOVE_MARKER.search(body, target_marker.end())
                    if declaration is None:
                        raise ContractTraceabilityError(
                            "removed ContractTarget lacks contract-remove"
                        )
                else:
                    declaration = _PAIR_EDIT_FENCE.search(body, target_marker.end())
                    if declaration is None:
                        raise ContractTraceabilityError(
                            "ContractTarget lacks its following pair-edit declaration"
                        )
                target = _parse_repo_symbol(target_marker.group("target"))
                target_requirements = tuple(
                    target_marker.group("requirements").split(",")
                )
                if not set(target_requirements) <= set(requirements):
                    raise ContractTraceabilityError(
                        "ContractTarget requirement is absent from PairBlock"
                    )
                if target not in block_targets:
                    raise ContractTraceabilityError(
                        "ContractTarget is absent from PairBlock.targets"
                    )
                declaration_start = match.start("body") + declaration.start()
                declaration_end = match.start("body") + declaration.end()
                targets.append(
                    ContractTarget(
                        requirements=target_requirements,
                        block_id=block.block_id,
                        action=action,
                        target=target,
                        declaration=_declaration_ref(
                            root,
                            guide,
                            text,
                            declaration_start,
                            declaration_end,
                        ),
                    )
                )
            blocks.append(block)
    if _duplicates([block.block_id for block in blocks]):
        raise ContractTraceabilityError("PairBlock ID belongs to several guides")
    return (
        tuple(sorted(blocks, key=lambda item: item.block_id)),
        tuple(
            sorted(
                targets,
                key=lambda item: (
                    item.block_id,
                    item.target.path,
                    item.target.symbol,
                ),
            )
        ),
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
    requirement_by_id = {
        item.requirement.requirement_id: item for item in requirements
    }
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
                        phase=phase,
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


def compile_contract_traceability(
    root: Path,
    checklist: Path,
    contracts: tuple[Path, ...],
    guides: tuple[Path, ...],
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
                if marker.requirement.contract
                == contract.relative_to(root).as_posix()
            ),
        )
    )
    if _duplicates([item.rule_id for item in rules]):
        raise ContractTraceabilityError("verifier-rule ID belongs to several contracts")
    blocks, targets = _parse_pair_blocks(root, guides)
    edges = _parse_rule_edges(root, checklist, markers, rules)
    _validate_plan(requirements, rules, edges, targets, blocks)
    graph = ContractTraceabilityGraph(
        requirements=tuple(
            sorted(requirements, key=lambda item: item.requirement_id)
        ),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=edges,
        targets=targets,
        blocks=blocks,
    )
    serialize_contract_traceability(graph)
    return graph
```

Add one `contract-target` marker per PairBlock target during this cycle. Place
the marker before the `python pair-edit` fence that owns the target. A removal
uses `contract-remove` instead. Delete the obsolete symbol and export markers
only after the compiler reports exact target parity across every guide.

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

**Context:** The declaration parsers need one connected repository fixture and
both acceptance and rejection evidence. These tests prove valid rows compile
and duplicate or orphan IDs fail at the declaration boundary.

Create `tests/test_contract_traceability.py`. This first block owns the one
connected fixture used by every later proof.

`tests/test_contract_traceability.py`

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
            ## 7. Master Phase 0

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

            <!-- contract-symbols:
            {"models":["ExampleRecord"],"aliases":[],"functions":["build_record"]}
            -->

            <!-- contract-example-symbols: ["ExampleRecord", "build_record"] -->
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

            The accepted case compiles one implementation edge and one
            verification edge. The rejected case removes or corrupts one exact
            marker and requires ContractTraceabilityError in pytest.

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

**Context:** Parsed checklist edges must reach one real implementation and at
least one real test. These cases prove valid joins resolve and missing symbols
or owners fail before graph construction.

Extend the imports in `tests/test_contract_traceability.py`, then add both
tests below the requirement-row tests.

`tests/test_contract_traceability.py`

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

**Stop:** both edge tests pass. Contract-example validation begins next.

<!-- pair-block-definition: P0-PROOF-03 -->
```toml pair-block
id = "P0-PROOF-03"
requirements = ["CRT-03", "CRT-05"]
targets = ["tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure", "tests/test_contract_traceability.py:test_contract_examples_reject_undeclared_inventory_symbol", "tests/test_contract_traceability.py:test_contract_examples_reject_unused_inventory_symbol", "tests/test_contract_traceability.py:test_contract_symbols_compile_complete_inventory", "tests/test_contract_traceability.py:test_contract_symbols_reject_missing_section_model", "tests/test_contract_traceability.py:test_contract_examples_require_registered_symbols"]
tests = ["tests/test_contract_traceability.py:test_contract_examples_reject_incomplete_structure", "tests/test_contract_traceability.py:test_contract_examples_reject_undeclared_inventory_symbol", "tests/test_contract_traceability.py:test_contract_examples_reject_unused_inventory_symbol", "tests/test_contract_traceability.py:test_contract_symbols_compile_complete_inventory", "tests/test_contract_traceability.py:test_contract_symbols_reject_missing_section_model", "tests/test_contract_traceability.py:test_contract_examples_require_registered_symbols"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_examples -q"
depends_on = ["P0-CRT-03", "P0-PROOF-02"]
```

**Context:** A contract can declare rules while omitting a required DAG or an
inventoried symbol from its worked example. These tests reject the exact
structural omission before the contract enters the compiled graph.

Extend the imports, then add these tests.

`tests/test_contract_traceability.py`

```python pair-edit
from viper._contract_traceability import (
    _parse_contract_symbols,
    validate_contract_example,
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


def test_contract_examples_reject_undeclared_inventory_symbol(
    tmp_path: Path,
) -> None:
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            '["ExampleRecord", "build_record"]',
            '["ExampleRecord", "build_record", "MissingRecord"]',
        ).replace(
            '"models":["ExampleRecord"]',
            '"models":["ExampleRecord","MissingRecord"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="inventory names undeclared symbols: \\['MissingRecord'\\]",
    ):
        validate_contract_example(contract)


def test_contract_examples_reject_unused_inventory_symbol(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "built = build_record(declared.value)",
            "built = declared",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="operations=\\['build_record'\\]",
    ):
        validate_contract_example(contract)


def test_contract_symbols_compile_complete_inventory(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)

    symbols = _parse_contract_symbols(tmp_path, contract)

    assert [(symbol.kind, symbol.name) for symbol in symbols] == [
        ("model", "ExampleRecord"),
        ("function", "build_record"),
    ]


def test_contract_symbols_reject_missing_section_model(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            '"models":["ExampleRecord"]',
            '"models":[]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="omits Section 4 models: \\['ExampleRecord'\\]",
    ):
        _parse_contract_symbols(tmp_path, contract)


def test_contract_examples_require_registered_symbols(tmp_path: Path) -> None:
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            ',"functions":["build_record"]',
            ',"functions":[]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="example symbols absent from contract-symbols: \\['build_record'\\]",
    ):
        validate_contract_example(contract)
```

**Stop:** all three contract-example rejections pass. Complete graph compilation
begins next.

<!-- pair-block-definition: P0-PROOF-04 -->
```toml pair-block
id = "P0-PROOF-04"
requirements = ["CRT-04"]
targets = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids", "tests/test_contract_traceability.py:test_contract_traceability_graph_covers_all_implementation_contracts"]
tests = ["tests/test_contract_traceability.py:test_contract_traceability_graph_is_canonical", "tests/test_contract_traceability.py:test_contract_traceability_graph_rejects_duplicate_ids", "tests/test_contract_traceability.py:test_contract_traceability_graph_covers_all_implementation_contracts"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k contract_traceability_graph -q"
depends_on = ["P0-CRT-05", "P0-PROOF-03"]
```

**Context:** The final compiler must produce the same bytes for the same
repository, reject identities that would make graph joins ambiguous, and
compile every baselined implementation contract with its checklist edges.

Extend the imports, then add the final compiler tests.

`tests/test_contract_traceability.py`

```python pair-edit
import re

from viper._contract_traceability import (
    compile_contract_traceability,
    serialize_contract_traceability,
)


ROOT = Path(__file__).resolve().parents[1]
MASTER_CHECKLIST = ROOT / "docs/development/master-execution-checklist.md"
_CONTRACT_BASELINE = re.compile(
    r"<!-- contract-baseline: (?P<name>[a-z0-9-]+\.md) sha256=[0-9a-f]{64} -->"
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

    declaration = left.requirements[0].declaration
    assert declaration.path == "docs/development/example.md"
    assert declaration.start_line == declaration.end_line
    original_sha256 = declaration.sha256
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "test=tests/test_contract_traceability.py",
            "test=tests/test_changed.py",
            1,
        ),
        encoding="utf-8",
    )
    changed = compile_contract_traceability(
        tmp_path,
        checklist,
        contracts,
    )
    assert changed.requirements[0].declaration.sha256 != original_sha256


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


def test_contract_traceability_graph_covers_all_implementation_contracts() -> None:
    contract_names = tuple(
        match.group("name")
        for match in _CONTRACT_BASELINE.finditer(
            MASTER_CHECKLIST.read_text(encoding="utf-8")
        )
    )
    contracts = tuple(ROOT / "docs/development" / name for name in contract_names)

    graph = compile_contract_traceability(
        ROOT,
        MASTER_CHECKLIST,
        contracts,
    )

    assert {requirement.contract for requirement in graph.requirements} == {
        contract.relative_to(ROOT).as_posix() for contract in contracts
    }
    assert all(
        any(edge.rule_id == rule.rule_id for edge in graph.edges)
        for rule in graph.rules
    )
```

**Stop:** all graph tests pass. Repeated fixture compilation is byte-identical,
duplicate IDs fail, and every baselined contract joins to its planned or
implemented owner and test edges.

<!-- pair-block-definition: P0-PROOF-08 -->
```toml pair-block
id = "P0-PROOF-08"
requirements = ["CRT-06"]
targets = ["tests/test_contract_traceability.py:test_contract_targets_require_exact_block_coverage", "tests/test_contract_traceability.py:test_rule_edges_match_pair_blocks", "tests/test_contract_traceability.py:test_pair_block_dependencies_are_acyclic"]
tests = ["tests/test_contract_traceability.py:test_contract_targets_require_exact_block_coverage", "tests/test_contract_traceability.py:test_rule_edges_match_pair_blocks", "tests/test_contract_traceability.py:test_pair_block_dependencies_are_acyclic"]
gate = "conda run -n mantra python -m pytest tests/test_contract_traceability.py -k 'contract_targets or rule_edges_match_pair_blocks or pair_block_dependencies' -q"
depends_on = ["P0-CRT-07"]
```

**Context:** These tests prove the CTG is closed before System Impact consumes
it. Each rejection changes one join: target-to-block, rule-edge-to-block, or
block-to-predecessor.

`tests/test_contract_traceability.py`

```python pair-edit
def test_contract_targets_require_exact_block_coverage(tmp_path: Path) -> None:
    """Reject missing, duplicate, and requirement-mismatched target ownership."""
    root, checklist, contracts, guides = _write_plan_fixture(tmp_path)
    graph = compile_contract_traceability(root, checklist, contracts, guides)
    assert graph.targets[0].target in graph.blocks[0].targets

    _replace(guides[0], 'target="src/owner.py:enforce"', 'target="src/owner.py:other"')
    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock target lacks ContractTarget",
    ):
        compile_contract_traceability(root, checklist, contracts, guides)


def test_rule_edges_match_pair_blocks(tmp_path: Path) -> None:
    """Reject an implementation or verification edge outside its owning block."""
    root, checklist, contracts, guides = _write_plan_fixture(tmp_path)
    _replace(checklist, "pair-block: P0-CRT-06", "pair-block: P0-CRT-99")
    with pytest.raises(
        ContractTraceabilityError,
        match="RuleEdge names unknown PairBlock",
    ):
        compile_contract_traceability(root, checklist, contracts, guides)


def test_pair_block_dependencies_are_acyclic(tmp_path: Path) -> None:
    """Reject a cycle in the complete PairBlock dependency relation."""
    root, checklist, contracts, guides = _write_plan_fixture(tmp_path)
    _replace(guides[0], "depends_on = []", 'depends_on = ["P0-CRT-06"]')
    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock dependency cycle",
    ):
        compile_contract_traceability(root, checklist, contracts, guides)
```

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
DAGs, its example-symbol inventory, its complete worked example, and
verifier-rule markers. Run the focused gate after each contract.

## 6. Guide gate

After all twelve PairBlocks pass, run:

```bash
conda run -n mantra python -m pytest tests/test_documentation.py -q
```

Then run the focused System Impact consumer boundary:

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k 'contract_traceability or system_impact_consumes_the_closed_ctg_plan' -q
```

The contract-traceability work in Master Phase 0 closes only when:

- every CRT checklist box is checked;
- every CRT implementation and verification marker has
  `state=implemented`;
- repeated compilation produces byte-identical JSON;
- the complete documentation boundary passes;
- the System Impact consumer boundary passes; and
- the review-cycle commit is synchronized with its upstream.

## 7. System Impact handoff

After `CRT-06`, `compile_contract_traceability()` returns the complete plan:

```text
ContractTraceabilityGraph.requirements
ContractTraceabilityGraph.rules
ContractTraceabilityGraph.edges
ContractTraceabilityGraph.targets
ContractTraceabilityGraph.blocks
```

Contract Traceability owns plan syntax and closure. The System Impact Check
accepts the closed CTG without reparsing contracts, checklists, or PairBlock
guides.
It uses CodeQL only to observe baseline dependencies and the realized source
delta:

```text
R0 + CodeQLIdentity -> SourceGraph G0
(CTG, G0) -> Impact
execute CTG.blocks -> R1
R1 + same CodeQLIdentity -> SourceGraph G1
(CTG, G0, G1) -> PlanCheck
```

System Impact reports reverse dependencies and rejects unplanned realized
changes. It does not generate `ContractChange`, `ContractDelta`, new
PairBlocks, SCC work units, or target constraints.
