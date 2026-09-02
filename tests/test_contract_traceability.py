"""Verify contract declarations, rule edges, examples, and canonical graphs."""

from pathlib import Path
from textwrap import dedent

import pytest

from viper._contract_traceability import (
    ContractTraceabilityError,
    _parse_requirement_markers,
    _parse_rule_edges,
    _parse_verifier_rules,
    compile_contract_traceability,
    serialize_contract_traceability,
    validate_contract_example,
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
            [REQUIREMENT_ROW]

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
            [RULE_ROW]

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
        ).replace(
            "[REQUIREMENT_ROW]",
            "| CRT-01 <!-- contract-requirement: CRT-01 phase=0 "
            "test=tests/test_contract_traceability.py --> | Compile one exact rule. |",
        ).replace(
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
