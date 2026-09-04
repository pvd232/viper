"""Verify contract declarations, rule edges, examples, and canonical graphs."""

from pathlib import Path
from textwrap import dedent

import pytest

from viper._contract_traceability import (
    ContractTraceabilityError,
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

            ## 4. Models

            [PYTHON]
            class ExampleRecord:
                def __init__(self, value: str) -> None:
                    self.value = value


            def build_record(value: str) -> ExampleRecord:
                return ExampleRecord(value)
            [END]

            [WORKED_START]
            [PYTHON]
            declared = ExampleRecord("declared")
            built = build_record(declared.value)
            assert built.value == "declared"
            [END]
            [WORKED_END]

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
            "[WORKED_START]",
            "<!-- contract-worked-example: start -->",
        )
        .replace(
            "[WORKED_END]",
            "<!-- contract-worked-example: end -->",
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


def test_requirement_requires_a_verifier_rule(tmp_path: Path) -> None:
    """Reject a requirement omitted from the contract's verifier rules."""
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "| `contract.rule` <!-- verifier-rule: contract.rule "
            "requirement=CRT-01 --> | One owner and one test exist. |",
            "",
        ),
        encoding="utf-8",
    )
    markers = _parse_requirement_markers(tmp_path, contract)

    with pytest.raises(
        ContractTraceabilityError,
        match="requirements w/o verifier rules",
    ):
        _parse_verifier_rules(tmp_path, contract, markers)


def test_verifier_rule_requires_a_verification_edge(tmp_path: Path) -> None:
    """Reject a verifier rule omitted from the checklist's test edges."""
    contract, checklist = _write_fixture(tmp_path)
    checklist.write_text(
        "\n".join(
            line
            for line in checklist.read_text(encoding="utf-8").splitlines()
            if "contract-verification:" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)

    with pytest.raises(
        ContractTraceabilityError,
        match="requires at least one verification edge",
    ):
        _parse_rule_edges(tmp_path, checklist, markers, rules)


def test_verifier_rule_requires_one_implementation_edge(tmp_path: Path) -> None:
    """Reject a verifier rule omitted from the checklist's owner edges."""
    contract, checklist = _write_fixture(tmp_path)
    checklist.write_text(
        "\n".join(
            line
            for line in checklist.read_text(encoding="utf-8").splitlines()
            if "contract-implementation:" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    markers = _parse_requirement_markers(tmp_path, contract)
    rules = _parse_verifier_rules(tmp_path, contract, markers)

    with pytest.raises(
        ContractTraceabilityError,
        match="requires exactly one implementation edge",
    ):
        _parse_rule_edges(tmp_path, checklist, markers, rules)


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


def test_contract_examples_reject_retired_symbol_inventories(
    tmp_path: Path,
) -> None:
    """Reject the obsolete inventory that ContractTarget replaced."""
    contract, _ = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "<!-- contract-worked-example: start -->",
            "<!-- contract-symbols: {} -->\n<!-- contract-worked-example: start -->",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="contains a retired symbol inventory",
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
    assert left.schema_version == 6
    for rule in left.rules:
        links = tuple(edge for edge in left.edges if edge.rule_id == rule.rule_id)
        assert sum(edge.kind == "implementation" for edge in links) == 1
        assert sum(edge.kind == "verification" for edge in links) >= 1
    assert [block.block_id for block in left.blocks] == ["P0-CRT-01"]
    assert left.blocks[0].assets == ()
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


def test_contract_traceability_compiles_selected_requirement_slice(
    tmp_path: Path,
) -> None:
    """Compile one closed requirement without requiring a later contract phase."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8")
        .replace(
            "| CRT-01 <!-- contract-requirement:",
            "| CRT-02 <!-- contract-requirement: CRT-02 phase=1 "
            "test=tests/test_owner.py --> | Later requirement. |\n"
            "| CRT-01 <!-- contract-requirement:",
        )
        .replace(
            "| `contract.rule` <!-- verifier-rule:",
            "| `contract.later` <!-- verifier-rule: contract.later "
            "requirement=CRT-02 --> | Later rule. |\n"
            "| `contract.rule` <!-- verifier-rule:",
        ),
        encoding="utf-8",
    )

    graph = compile_contract_traceability(
        tmp_path,
        checklist,
        (contract,),
        requirement_ids=("CRT-01",),
    )

    assert [item.requirement_id for item in graph.requirements] == ["CRT-01"]
    assert [item.rule_id for item in graph.rules] == ["contract.rule"]
    assert [item.block_id for item in graph.blocks] == ["P0-CRT-01"]


def test_contract_traceability_rejects_requirement_slice_that_splits_block(
    tmp_path: Path,
) -> None:
    """Reject selection that omits a requirement owned by the same PairBlock."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8")
        .replace(
            "| CRT-01 <!-- contract-requirement:",
            "| CRT-02 <!-- contract-requirement: CRT-02 phase=1 "
            "test=tests/test_owner.py --> | Coupled requirement. |\n"
            "| CRT-01 <!-- contract-requirement:",
        )
        .replace(
            "| `contract.rule` <!-- verifier-rule:",
            "| `contract.later` <!-- verifier-rule: contract.later "
            "requirement=CRT-02 --> | Coupled rule. |\n"
            "| `contract.rule` <!-- verifier-rule:",
        )
        .replace(
            'requirements = ["CRT-01"]',
            'requirements = ["CRT-01", "CRT-02"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="selected requirements split a PairBlock",
    ):
        compile_contract_traceability(
            tmp_path,
            checklist,
            (contract,),
            requirement_ids=("CRT-01",),
        )


def test_contract_traceability_includes_dependency_evidence_for_selected_slice(
    tmp_path: Path,
) -> None:
    """Retain one omitted dependency block so its baseline target can be checked."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8")
        .replace(
            "| CRT-01 <!-- contract-requirement:",
            "| CRT-02 <!-- contract-requirement: CRT-02 phase=1 "
            "test=tests/test_owner.py --> | Later requirement. |\n"
            "| CRT-01 <!-- contract-requirement:",
        )
        .replace(
            "| `contract.rule` <!-- verifier-rule:",
            "| `contract.later` <!-- verifier-rule: contract.later "
            "requirement=CRT-02 --> | Later rule. |\n"
            "| `contract.rule` <!-- verifier-rule:",
        )
        + dedent(
            """

            <!-- pair-block-definition: P1-CRT-01 -->
            ```toml pair-block
            id = "P1-CRT-01"
            requirements = ["CRT-02"]
            targets = ["src/owner.py:later"]
            tests = ["tests/test_owner.py:test_enforce"]
            gate = "python -m pytest tests/test_owner.py -q"
            depends_on = ["P0-CRT-01"]
            ```

            [TARGET]
            ```python contract-target
            def later() -> str:
                return "later"
            ```
            """
        ).replace(
            "[TARGET]",
            "<!-- contract-target: requirements=CRT-02 block=P1-CRT-01 "
            "action=add target=src/owner.py:later -->",
        ),
        encoding="utf-8",
    )
    checklist.write_text(
        checklist.read_text(encoding="utf-8")
        + dedent(
            """

            ## 8. Master Phase 1

            - [ ] Compile the selected requirement.
              <!-- pair-block: P1-CRT-01 -->
              [IMPLEMENTATION]
              [VERIFICATION]
            """
        )
        .replace(
            "[IMPLEMENTATION]",
            "<!-- contract-implementation: requirement=CRT-02 "
            "rule=contract.later state=planned owner=src/owner.py:later -->",
        )
        .replace(
            "[VERIFICATION]",
            "<!-- contract-verification: requirement=CRT-02 "
            "rule=contract.later state=planned "
            "test=tests/test_owner.py:test_enforce -->",
        ),
        encoding="utf-8",
    )

    graph = compile_contract_traceability(
        tmp_path,
        checklist,
        (contract,),
        requirement_ids=("CRT-02",),
    )

    assert [item.requirement_id for item in graph.requirements] == [
        "CRT-01",
        "CRT-02",
    ]
    assert [item.block_id for item in graph.blocks] == [
        "P0-CRT-01",
        "P1-CRT-01",
    ]


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


def test_pair_block_assets_compile_when_implemented_files_exist(
    tmp_path: Path,
) -> None:
    """Compile one optional non-Python asset owned by an implemented block."""
    contract, checklist = _write_fixture(tmp_path)
    asset = tmp_path / "tools/codeql/example/Declarations.ql"
    asset.parent.mkdir(parents=True)
    asset.write_text("select 1\n", encoding="utf-8")
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'targets = ["src/owner.py:enforce"]',
            'targets = ["src/owner.py:enforce"]\n'
            'assets = ["tools/codeql/example/Declarations.ql"]',
        ),
        encoding="utf-8",
    )

    graph = compile_contract_traceability(tmp_path, checklist, (contract,))

    assert graph.blocks[0].assets == ("tools/codeql/example/Declarations.ql",)


def test_pair_block_assets_reject_duplicates(tmp_path: Path) -> None:
    """Reject one asset path repeated inside the same PairBlock."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'targets = ["src/owner.py:enforce"]',
            'targets = ["src/owner.py:enforce"]\n'
            'assets = ["tools/query.ql", "tools/query.ql"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock asset has several owners",
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_pair_block_assets_reject_python_source(tmp_path: Path) -> None:
    """Keep Python declaration changes in ContractTarget records."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'targets = ["src/owner.py:enforce"]',
            'targets = ["src/owner.py:enforce"]\nassets = ["src/owner.py"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ContractTraceabilityError,
        match="PairBlock assets must not name Python source",
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_pair_block_assets_require_files_only_after_implementation(
    tmp_path: Path,
) -> None:
    """Permit a planned asset and reject it once its block is implemented."""
    contract, checklist = _write_fixture(tmp_path)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            'targets = ["src/owner.py:enforce"]',
            'targets = ["src/owner.py:enforce"]\n'
            'assets = ["tools/codeql/example/Declarations.ql"]',
        ),
        encoding="utf-8",
    )
    implemented_checklist = checklist.read_text(encoding="utf-8")
    checklist.write_text(
        implemented_checklist.replace("state=implemented", "state=planned"),
        encoding="utf-8",
    )

    graph = compile_contract_traceability(tmp_path, checklist, (contract,))
    assert graph.blocks[0].assets == ("tools/codeql/example/Declarations.ql",)

    checklist.write_text(implemented_checklist, encoding="utf-8")
    with pytest.raises(
        ContractTraceabilityError,
        match=(
            "implemented PairBlock asset is missing: "
            "tools/codeql/example/Declarations.ql"
        ),
    ):
        compile_contract_traceability(tmp_path, checklist, (contract,))


def test_contract_traceability_graph_covers_migrated_contracts() -> None:
    """Compile every contract migrated to contract-owned PairBlocks."""
    contracts = (
        ROOT / "docs/development/contract-traceability.md",
        ROOT / "docs/development/module-ownership.md",
    )
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
