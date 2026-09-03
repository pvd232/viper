"""Verify contract declarations, rule edges, examples, and canonical graphs."""

import re
from pathlib import Path
from textwrap import dedent

import pytest

from viper._contract_traceability import (
    ContractTraceabilityError,
    _parse_contract_symbols,
    _parse_requirement_markers,
    _parse_rule_edges,
    _parse_verifier_rules,
    _python_symbols,
    compile_contract_traceability,
    serialize_contract_traceability,
    validate_contract_example,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER_CHECKLIST = ROOT / "docs/development/master-execution-checklist.md"
_CONTRACT_BASELINE = re.compile(
    r"<!-- contract-baseline: (?P<name>[a-z0-9-]+\.md) sha256=[0-9a-f]{64} -->"
)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Write one connected contract, checklist, source, and test fixture."""
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

            - [x] Compile the example contract.
              <!-- pair-block: P0-CRT-01 -->
              [IMPLEMENTATION]
              [VERIFICATION]
            """
        )
        .replace(
            "[IMPLEMENTATION]",
            "<!-- contract-"
            "implementation: requirement=CRT-01 rule=contract.rule "
            "state=implemented owner=src/owner.py:enforce -->",
        )
        .replace(
            "[VERIFICATION]",
            "<!-- contract-"
            "verification: requirement=CRT-01 rule=contract.rule "
            "state=implemented test=tests/test_owner.py:test_enforce -->",
        ),
        encoding="utf-8",
    )
    contract.write_text(
        dedent(
            """
            # Example contract

            ## 1. Status

            | Requirement | Claim |
            |---|---|
            [REQUIREMENT_ROW]

            ## 2. Required claim

            The compiler joins the rule to its owner and test.

            ## 3. Current gap

            ### Current DAG

            [MERMAID]
            flowchart LR
                A["Requirement"]
                B["Missing join"]
                A --> B
            [END]

            ### Proposed-change DAG

            [MERMAID]
            flowchart LR
                C["RuleEdge"]
                D["Resolved symbol"]
                C --> D
            [END]

            ### Integrated DAG

            [MERMAID]
            flowchart LR
                A["Requirement"]
                C["RuleEdge"]
                D["Resolved symbol"]
                A --> C
                C --> D
            [END]

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
            [RULE_ROW]

            ## 8. Propagation

            The source and test symbols enter the graph.

            ## 9. Acceptance case

            The accepted case compiles one implementation edge and one
            verification edge. The rejected case removes or corrupts one exact
            marker and requires ContractTraceabilityError in pytest.

            ## 10. Implementation order

            Parse declarations before edges.

            <!-- pair-block-definition: P0-CRT-01 -->
            [PAIR_BLOCK]
            id = "P0-CRT-01"
            requirements = ["CRT-01"]
            targets = ["src/owner.py:enforce"]
            tests = ["tests/test_owner.py:test_enforce"]
            gate = "python -m pytest tests/test_owner.py -q"
            depends_on = []
            [END]

            [TARGET_MARKER]
            [TARGET]
            def enforce() -> str:
                return "accepted"
            [END]
            """
        )
        .replace(
            "[PYTHON]",
            chr(96) * 3 + "python",
        )
        .replace(
            "[MERMAID]",
            chr(96) * 3 + "mermaid",
        )
        .replace(
            "[PAIR_BLOCK]",
            chr(96) * 3 + "toml pair-block",
        )
        .replace(
            "[TARGET]",
            chr(96) * 3 + "python contract-target",
        )
        .replace(
            "[TARGET_MARKER]",
            "<!-- contract-"
            "target: requirements=CRT-01 block=P0-CRT-01 "
            "action=update target=src/owner.py:enforce -->",
        )
        .replace(
            "[END]",
            chr(96) * 3,
        )
        .replace(
            "[REQUIREMENT_ROW]",
            "| CRT-01 <!-- contract-requirement: CRT-01 phase=0 "
            "test=tests/test_contract_traceability.py --> | Compile one exact rule. |",
        )
        .replace(
            "[RULE_ROW]",
            "| `contract.rule` <!-- verifier-rule: contract.rule "
            "requirement=CRT-01 --> | One owner and one test exist. |",
        ),
        encoding="utf-8",
    )
    return contract, checklist


def test_requirement_rows_and_rules_compile(tmp_path: Path) -> None:
    """Compile one requirement and its verifier rule."""
    contract, _ = _write_fixture(tmp_path)
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)

    assert [item.requirement.requirement_id for item in markers] == ["CRT-01"]
    assert [item.rule_id for item in rules] == ["contract.rule"]


def test_requirement_rows_reject_duplicate_and_orphan_ids(
    tmp_path: Path,
) -> None:
    """Reject duplicate requirements and rules owned by missing requirements."""
    contract, _ = _write_fixture(tmp_path)
    original = contract.read_text(encoding="utf-8")
    requirement_row = next(
        line
        for line in original.splitlines()
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


def test_rule_edges_resolve_one_owner_and_tests(tmp_path: Path) -> None:
    """Resolve one implementation edge and one verification edge."""
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
    empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert all(edge.declaration.sha256 != empty_sha256 for edge in edges)


def test_rule_edges_reject_missing_symbols(tmp_path: Path) -> None:
    """Reject an implemented edge whose target symbol does not exist."""
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


def test_python_symbols_include_module_assignments(tmp_path: Path) -> None:
    """Resolve module registries such as ``__all__`` as implementation owners."""
    source = tmp_path / "module.py"
    source.write_text(
        '__all__ = ["public"]\nVERSION: int = 1\n',
        encoding="utf-8",
    )

    assert {"__all__", "VERSION"} <= _python_symbols(source)


def test_contract_examples_reject_incomplete_structure(tmp_path: Path) -> None:
    """Reject a contract missing one required DAG heading."""
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
    """Reject an inventory entry that has no contract declaration."""
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8")
        .replace(
            '["ExampleRecord", "build_record"]',
            '["ExampleRecord", "build_record", "MissingRecord"]',
        )
        .replace(
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


def test_contract_symbols_compile_complete_inventory(tmp_path: Path) -> None:
    """Compile every Section 4 declaration and every example symbol."""
    contract, _ = _write_fixture(tmp_path)

    symbols = _parse_contract_symbols(tmp_path, contract)

    assert [(symbol.kind, symbol.name) for symbol in symbols] == [
        ("model", "ExampleRecord"),
        ("function", "build_record"),
    ]


def test_contract_symbols_reject_missing_section_model(tmp_path: Path) -> None:
    """Reject a Section 4 model omitted from the formal inventory."""
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
    """Reject an example symbol absent from the contract inventory."""
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


def test_contract_examples_reject_unused_inventory_symbol(tmp_path: Path) -> None:
    """Reject a declared inventory symbol omitted by the worked example."""
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


def test_contract_traceability_graph_is_canonical(tmp_path: Path) -> None:
    """Require stable graph bytes and source-evidenced declarations."""
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
        links = tuple(edge for edge in left.edges if edge.rule_id == rule.rule_id)
        assert sum(edge.kind == "implementation" for edge in links) == 1
        assert sum(edge.kind == "verification" for edge in links) >= 1
    assert [block.block_id for block in left.blocks] == ["P0-CRT-01"]
    assert [target.target.symbol for target in left.targets] == ["enforce"]

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
    """Reject one requirement compiled from more than one contract input."""
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


def test_contract_targets_require_exact_block_coverage(tmp_path: Path) -> None:
    """Reject a PairBlock target without one matching ContractTarget."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "<!-- contract-target: requirements=CRT-01 block=P0-CRT-01 "
            "action=update target=src/owner.py:enforce -->\n",
            "",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock target lacks ContractTarget",
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_rule_edges_match_pair_blocks(tmp_path: Path) -> None:
    """Reject a verification edge absent from its PairBlock tests."""
    contract, checklist = _write_fixture(tmp_path)
    checklist.write_text(
        checklist.read_text(encoding="utf-8").replace(
            "state=implemented test=tests/test_owner.py:test_enforce",
            "state=planned test=tests/test_owner.py:test_enforce",
        ),
        encoding="utf-8",
    )
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'tests = ["tests/test_owner.py:test_enforce"]',
            'tests = ["tests/test_owner.py:test_other"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="verification target is absent from PairBlock.tests",
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_pair_block_dependencies_are_acyclic(tmp_path: Path) -> None:
    """Reject a PairBlock dependency cycle."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "depends_on = []",
            'depends_on = ["P0-CRT-01"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock dependency cycle",
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_contract_traceability_graph_covers_migrated_contracts() -> None:
    """Compile every contract migrated to contract-owned PairBlocks."""
    contracts = (ROOT / "docs/development/contract-traceability.md",)
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
