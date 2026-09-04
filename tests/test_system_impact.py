"""Verify canonical System Impact source analysis and plan inspection."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import cast

import pytest

import viper.scheduling as scheduling
from viper._contract_traceability import (
    ContractRequirement,
    ContractTarget,
    ContractTraceabilityGraph,
    DeclarationRef,
    PairBlock,
    RepoSymbolRef,
    RuleEdge,
    TargetAction,
    VerifierRule,
    compile_contract_plan,
)
from viper._subprocess import run as run_subprocess
from viper._system_impact.check import SystemImpactCheckError, _unexpected_changes
from viper._system_impact.codeql import (
    CodeQLAnalysisError,
    _node_span,
    _qualified_declarations,
    _tree_digest,
    analyze_source,
    source_digest,
)
from viper._system_impact.source import (
    SourceDeclarationError,
    classify_target_change,
    extract_declaration_bytes,
)
from viper.system_impact import (
    CodeQLIdentity,
    CodeQLReceipt,
    EdgeKind,
    SourceEdge,
    SourceGraph,
    SourceNode,
    SourceNodeKind,
    SourceSnapshot,
    accept,
    check_plan,
    inspect_plan,
)

_BLOCK_ID = "P0-SIG-03"
_REQUIREMENT_ID = "SIG-02"
_REVISION = "1" * 40


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_source_digest_ignores_viper_worktrees(tmp_path: Path) -> None:
    """Keep generated plan candidates outside the reusable source identity."""
    source = tmp_path / "src/example.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    expected = source_digest(tmp_path)

    generated = tmp_path / ".viper/checks/candidate/example.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("VALUE = 2\n")

    assert source_digest(tmp_path) == expected


def _declaration_ref(
    *,
    path: str = "docs/plan.md",
    start_line: int = 1,
    end_line: int = 1,
    sha256: str = "0" * 64,
) -> DeclarationRef:
    return DeclarationRef(
        path=path,
        start_line=start_line,
        end_line=end_line,
        sha256=sha256,
    )


def _write_target_fence(plan_root: Path, body: bytes) -> DeclarationRef:
    relative_path = "docs/plan.md"
    payload = b"```python contract-target\n" + body + b"\n```"
    target_path = plan_root / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(payload + b"\n")
    return _declaration_ref(
        path=relative_path,
        start_line=1,
        end_line=payload.count(b"\n") + 1,
        sha256=_sha256(payload),
    )


def test_final_targets_compose_ordered_revisions() -> None:
    """Use the last explicitly ordered declaration as the terminal target."""
    first = "P0-TST-01"
    second = "P0-TST-02"
    declaration = _declaration_ref()
    final_declaration = declaration.model_copy(update={"sha256": "1" * 64})
    target = RepoSymbolRef(path="module.py", symbol="load")
    targets = (
        ContractTarget.model_construct(
            requirements=("SCH-01",),
            block_id=first,
            action="update",
            target=target,
            declaration=declaration,
        ),
        ContractTarget.model_construct(
            requirements=("SCH-01",),
            block_id=second,
            action="update",
            target=target,
            declaration=final_declaration,
        ),
    )
    blocks = (
        PairBlock.model_construct(
            block_id=first,
            requirements=("SCH-01",),
            targets=(target,),
            assets=(),
            tests=(),
            gate="true",
            depends_on=(),
            declaration=declaration,
        ),
        PairBlock.model_construct(
            block_id=second,
            requirements=("SCH-01",),
            targets=(target,),
            assets=(),
            tests=(),
            gate="true",
            depends_on=(first,),
            declaration=declaration,
        ),
    )
    traceability = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=targets,
        blocks=blocks,
    )
    baseline = _source_graph(
        nodes=(_node(path="module.py", symbol="load", kind="function"),)
    )

    resolved = scheduling.final_targets(traceability, (first, second), baseline)

    assert len(resolved) == 1
    assert resolved[0].block_id == second
    assert resolved[0].action == "update"
    assert resolved[0].declaration == final_declaration

    unordered = traceability.model_copy(
        update={
            "blocks": (
                blocks[0],
                blocks[1].model_copy(update={"depends_on": ()}),
            )
        }
    )
    with pytest.raises(scheduling.ScheduleError, match="explicit dependency path"):
        scheduling.final_targets(unordered, (first, second), baseline)


def test_materialize_plan_applies_exact_declarations(tmp_path: Path) -> None:
    """Apply one update, removal, and top-level addition to an isolated tree."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"def old():\n    return 1\n\ndef removed():\n    return 2\n"
    (baseline_root / "module.py").write_bytes(source)
    plan_root = tmp_path / "plan"
    updated = b"def old():\n    return 3"
    added = b"def added():\n    return old()"
    update_ref = _write_target_fence(plan_root, updated + b"\n\n" + added)
    remove_ref = DeclarationRef(
        path="contract.md",
        start_line=1,
        end_line=1,
        sha256=hashlib.sha256(b"<!-- contract-remove -->").hexdigest(),
    )
    graph = _source_graph(
        nodes=(
            SourceNode(
                node_id="module.py:old",
                path="module.py",
                symbol="old",
                kind="function",
                start_line=1,
                start_col=0,
                end_line=2,
                end_col=12,
                sha256=hashlib.sha256(b"def old():\n    return 1").hexdigest(),
            ),
            SourceNode(
                node_id="module.py:removed",
                path="module.py",
                symbol="removed",
                kind="function",
                start_line=4,
                start_col=0,
                end_line=5,
                end_col=12,
                sha256=hashlib.sha256(b"def removed():\n    return 2").hexdigest(),
            ),
        ),
    )
    traceability = _traceability(
        targets=(
            _target(
                action="add",
                path="module.py",
                symbol="added",
                declaration=update_ref,
            ),
            _target(
                action="update",
                path="module.py",
                symbol="old",
                declaration=update_ref,
            ),
            _target(
                action="remove",
                path="module.py",
                symbol="removed",
                declaration=remove_ref,
            ),
        ),
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_text() == (
        "def added():\n    return old()\n\ndef old():\n    return 3\n\n\n"
    )
    assert (baseline_root / "module.py").read_bytes() == source


def test_materialize_plan_coalesces_one_shared_declaration_removal(
    tmp_path: Path,
) -> None:
    """Remove one import declaration named by several ContractTargets once."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"from package import First, Second\n"
    (baseline_root / "module.py").write_bytes(source)
    plan_root = tmp_path / "plan"
    remove_ref = DeclarationRef(
        path="contract.md",
        start_line=1,
        end_line=1,
        sha256=hashlib.sha256(b"<!-- contract-remove -->").hexdigest(),
    )
    declaration_end = len(source.rstrip(b"\n"))
    graph = _source_graph(
        nodes=tuple(
            SourceNode(
                node_id=f"module.py:{symbol}",
                path="module.py",
                symbol=symbol,
                kind="import",
                start_line=1,
                start_col=0,
                end_line=1,
                end_col=declaration_end,
                sha256=hashlib.sha256(source.rstrip(b"\n")).hexdigest(),
            )
            for symbol in ("First", "Second")
        ),
    )
    traceability = _traceability(
        targets=tuple(
            _target(
                action="remove",
                path="module.py",
                symbol=symbol,
                declaration=remove_ref,
            )
            for symbol in ("First", "Second")
        )
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_bytes() == b"\n"


def test_materialize_plan_composes_one_import_across_targets(tmp_path: Path) -> None:
    """Let a later import payload replace the earlier form of that import."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"from package import First\n\nVALUE = First\n"
    (baseline_root / "module.py").write_bytes(source)

    plan_root = tmp_path / "plan"
    fence = b"`" * 3
    old_payload = fence + b"python contract-target\nfrom package import First\n" + fence
    new_payload = (
        fence + b"python contract-target\nfrom package import First, Second\n" + fence
    )
    old_path = plan_root / "docs/old.md"
    new_path = plan_root / "docs/new.md"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(old_payload + b"\n")
    new_path.write_bytes(new_payload + b"\n")
    old_ref = _declaration_ref(
        path="docs/old.md",
        start_line=1,
        end_line=3,
        sha256=_sha256(old_payload),
    )
    new_ref = _declaration_ref(
        path="docs/new.md",
        start_line=1,
        end_line=3,
        sha256=_sha256(new_payload),
    )
    declaration_end = len(b"from package import First")
    graph = _source_graph(
        nodes=(
            SourceNode(
                node_id="module.py:First",
                path="module.py",
                symbol="First",
                kind="import",
                start_line=1,
                start_col=0,
                end_line=1,
                end_col=declaration_end,
                sha256=_sha256(b"from package import First"),
            ),
        ),
    )
    traceability = _traceability(
        targets=(
            _target(
                action="update",
                path="module.py",
                symbol="First",
                declaration=old_ref,
            ),
            _target(
                action="add",
                path="module.py",
                symbol="Second",
                declaration=new_ref,
            ),
        )
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_bytes() == (
        b"from package import First, Second\n\nVALUE = First\n"
    )


def test_pre_pairing_modules_document_every_operation() -> None:
    """Require docstrings on public, private, and nested pre-pairing operations."""
    missing: list[str] = []
    for relative_path in ("src/viper/scheduling.py", "tools/check_plan.py"):
        tree = ast.parse(Path(relative_path).read_text(), filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is None:
                    missing.append(f"{relative_path}:{node.name}")

    assert missing == []


def test_pre_pairing_command_loads() -> None:
    """Load the pre-pairing command without relying on prior package imports."""
    checked = run_subprocess(
        (sys.executable, "tools/check_plan.py", "--help"),
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert checked.returncode == 0, checked.stderr


def _schedule_fixture() -> tuple[ContractTraceabilityGraph, SourceGraph, SourceGraph]:
    """Build four blocks with one dependency and one shared-file conflict."""
    declaration = _declaration_ref()
    definitions = (
        ("P0-TST-01", "src/parse.py", "parse", ()),
        ("P0-TST-02", "src/load.py", "load", ("P0-TST-01",)),
        ("P0-TST-03", "src/shared.py", "left", ()),
        ("P0-TST-04", "src/shared.py", "right", ()),
    )
    targets = tuple(
        ContractTarget.model_construct(
            requirements=("SCH-02",),
            block_id=block_id,
            action="update",
            target=RepoSymbolRef(path=path, symbol=symbol),
            declaration=declaration,
        )
        for block_id, path, symbol, _dependencies in definitions
    )
    blocks = tuple(
        PairBlock.model_construct(
            block_id=block_id,
            requirements=("SCH-02",),
            targets=(RepoSymbolRef(path=path, symbol=symbol),),
            assets=(),
            tests=(
                RepoSymbolRef(
                    path="tests/test_system_impact.py",
                    symbol="test_schedule_blocks_returns_dependency_safe_waves",
                ),
            ),
            gate="python -m pytest tests/test_system_impact.py",
            depends_on=dependencies,
            declaration=declaration,
        )
        for block_id, path, symbol, dependencies in definitions
    )
    traceability = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=targets,
        blocks=blocks,
    )
    parse = _node(path="src/parse.py", symbol="parse", kind="function")
    load = _node(path="src/load.py", symbol="load", kind="function")
    left = _node(path="src/shared.py", symbol="left", kind="function")
    right = _node(path="src/shared.py", symbol="right", kind="function")
    baseline = _source_graph(nodes=(parse, load, left, right))
    planned = _source_graph(
        nodes=(parse, load, left, right),
        edges=(_edge(index=1, source=load, target=parse, kind="calls"),),
        source_sha256="8" * 64,
        revision=None,
    )
    return traceability, baseline, planned


def test_block_graph_combines_dependencies_and_write_conflicts() -> None:
    """Project explicit, source, and same-file relations onto PairBlocks."""
    traceability, baseline, planned = _schedule_fixture()

    graph = scheduling.build_block_graph(
        traceability,
        ("P0-TST-02", "P0-TST-03", "P0-TST-04"),
        baseline,
        planned,
    )

    relations = {(edge.prerequisite, edge.consumer, edge.kind) for edge in graph.edges}
    assert ("P0-TST-01", "P0-TST-02", "declared") in relations
    assert ("P0-TST-01", "P0-TST-02", "source") in relations
    assert ("P0-TST-03", "P0-TST-04", "write_conflict") in relations
    assert ("P0-TST-04", "P0-TST-03", "write_conflict") not in relations


def test_block_graph_rejects_unselected_endpoint() -> None:
    """Reject an edge whose consumer is absent from the selected blocks."""
    with pytest.raises(ValueError, match="unselected PairBlock"):
        scheduling.BlockGraph(
            blocks=("P0-TST-01",),
            edges=(
                scheduling.ScheduleEdge(
                    prerequisite="P0-TST-01",
                    consumer="P0-TST-02",
                    kind="declared",
                    evidence="P0-TST-01",
                ),
            ),
        )


def test_schedule_blocks_returns_dependency_safe_waves() -> None:
    """Place independent groups together and their consumer in the next wave."""
    traceability, baseline, planned = _schedule_fixture()
    graph = scheduling.build_block_graph(
        traceability,
        ("P0-TST-02", "P0-TST-03", "P0-TST-04"),
        baseline,
        planned,
    )

    schedule = scheduling.schedule_blocks(graph)
    groups = {group.group_id: group.blocks for group in schedule.groups}
    waves = tuple(
        tuple(groups[group_id] for group_id in wave.groups) for wave in schedule.waves
    )

    assert set(waves[0]) == {("P0-TST-01",), ("P0-TST-03",)}
    assert set(waves[1]) == {("P0-TST-02",), ("P0-TST-04",)}


def test_schedule_blocks_keeps_cycle_in_one_group() -> None:
    """Keep mutually dependent blocks together in one execution group."""
    graph = scheduling.BlockGraph(
        blocks=("P0-TST-01", "P0-TST-02"),
        edges=(
            scheduling.ScheduleEdge(
                prerequisite="P0-TST-01",
                consumer="P0-TST-02",
                kind="source",
                evidence="edge-1",
            ),
            scheduling.ScheduleEdge(
                prerequisite="P0-TST-02",
                consumer="P0-TST-01",
                kind="source",
                evidence="edge-2",
            ),
        ),
    )

    schedule = scheduling.schedule_blocks(graph)

    assert tuple(group.blocks for group in schedule.groups) == (
        ("P0-TST-01", "P0-TST-02"),
    )
    assert len(schedule.waves) == 1


def _traceability(
    *,
    targets: tuple[ContractTarget, ...],
) -> ContractTraceabilityGraph:
    target_refs = tuple(target.target for target in targets)
    declaration = _declaration_ref()
    return ContractTraceabilityGraph(
        requirements=(
            ContractRequirement(
                requirement_id=_REQUIREMENT_ID,
                contract="docs/plan.md",
                declaration=declaration,
            ),
        ),
        rules=(
            VerifierRule(
                rule_id="system_impact.plan_target",
                requirement_id=_REQUIREMENT_ID,
                contract="docs/plan.md",
                statement="Selected source targets match their authored declarations.",
                declaration=declaration,
            ),
        ),
        edges=(
            RuleEdge(
                kind="implementation",
                rule_id="system_impact.plan_target",
                block_id=_BLOCK_ID,
                declaration=declaration,
                state="planned",
                target=target_refs[0],
            ),
        ),
        targets=targets,
        blocks=(
            PairBlock(
                block_id=_BLOCK_ID,
                requirements=(_REQUIREMENT_ID,),
                targets=target_refs,
                tests=(
                    RepoSymbolRef(
                        path="tests/test_system_impact.py",
                        symbol=(
                            "test_plan_reports_only_policy_selected_one_hop_dependents"
                        ),
                    ),
                ),
                gate="python -m pytest tests/test_system_impact.py",
                depends_on=(),
                declaration=declaration,
            ),
        ),
    )


def _target(
    *,
    action: TargetAction,
    path: str,
    symbol: str,
    declaration: DeclarationRef,
) -> ContractTarget:
    return ContractTarget(
        requirements=(_REQUIREMENT_ID,),
        block_id=_BLOCK_ID,
        action=action,
        target=RepoSymbolRef(path=path, symbol=symbol),
        declaration=declaration,
    )


def _node(
    *,
    path: str,
    symbol: str,
    kind: SourceNodeKind,
    declaration: bytes | None = None,
) -> SourceNode:
    return SourceNode(
        node_id=f"{path}:{symbol}",
        path=path,
        symbol=symbol,
        kind=kind,
        start_line=1,
        start_col=0,
        end_line=1,
        end_col=1,
        sha256=_sha256(declaration) if declaration is not None else "f" * 64,
    )


def _edge(
    *,
    index: int,
    source: SourceNode,
    target: SourceNode,
    kind: EdgeKind,
) -> SourceEdge:
    return SourceEdge(
        edge_id=f"{index:064x}",
        source=source.node_id,
        target=target.node_id,
        kind=kind,
        query=f"viper/python-impact/{kind}",
        path=source.path,
        line=1,
    )


def _source_graph(
    *,
    nodes: tuple[SourceNode, ...],
    edges: tuple[SourceEdge, ...] = (),
    source_sha256: str = "2" * 64,
    base_revision: str = _REVISION,
    revision: str | None = _REVISION,
    identity: CodeQLIdentity | None = None,
    exit_code: int = 0,
) -> SourceGraph:
    canonical_nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
    canonical_edges = tuple(sorted(edges, key=lambda edge: edge.edge_id))
    result_payload = json.dumps(
        {
            "nodes": [node.model_dump(mode="json") for node in canonical_nodes],
            "edges": [edge.model_dump(mode="json") for edge in canonical_edges],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    snapshot = SourceSnapshot(
        base_revision=base_revision,
        source_sha256=source_sha256,
        revision=revision,
    )
    if identity is None:
        identity = CodeQLIdentity(
            version="2.26.4",
            platform="osx64",
            executable_sha256="3" * 64,
            pack="viper/python-impact@1.0.0",
            pack_sha256="4" * 64,
        )
    receipt = CodeQLReceipt(
        snapshot=snapshot,
        identity=identity,
        commands=(("codeql", "query", "run"),),
        exit_code=exit_code,
        database_sha256="5" * 64,
        result_sha256=_sha256(result_payload),
        stderr_sha256="7" * 64,
    )
    return SourceGraph(
        snapshot=snapshot,
        identity=identity,
        nodes=canonical_nodes,
        edges=canonical_edges,
        receipt=receipt,
    )


def _observed_graph(
    root: Path,
    *,
    base_revision: str = _REVISION,
    revision: str | None = None,
    identity: CodeQLIdentity | None = None,
) -> SourceGraph:
    """Build canonical declaration facts from one small Python fixture tree."""
    nodes: list[SourceNode] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        source = path.read_bytes()
        tree = ast.parse(source.decode("utf-8"), type_comments=True)
        for symbol, declaration, kind in _qualified_declarations(tree):
            start_line, start_col, end_line, end_col, exact = _node_span(
                declaration,
                source,
            )
            nodes.append(
                SourceNode(
                    node_id=f"{relative}:{symbol}",
                    path=relative,
                    symbol=symbol,
                    kind=cast(SourceNodeKind, kind),
                    start_line=start_line,
                    start_col=start_col,
                    end_line=end_line,
                    end_col=end_col,
                    sha256=_sha256(exact),
                )
            )
    return _source_graph(
        nodes=tuple(nodes),
        source_sha256=source_digest(root),
        base_revision=base_revision,
        revision=revision,
        identity=identity,
    )


def _write_check_contract(
    root: Path,
    *,
    gate: str,
    dependency: bool = False,
    asset: bool = False,
) -> ContractTraceabilityGraph:
    """Write and compile the PairBlocks used by strict-closure tests."""
    dependency_block = ""
    dependency_target = ""
    dependencies = '["P0-SIG-02"]' if dependency else "[]"
    assets = '["tools/rule.ql"]' if asset else "[]"
    if dependency:
        dependency_block = """<!-- pair-block-definition: P0-SIG-02 -->
```toml pair-block
id = "P0-SIG-02"
requirements = ["SIG-02"]
targets = ["src/example.py:dependency"]
tests = ["tests/test_system_impact.py:test_dependency"]
gate = "python -c pass"
depends_on = []
```
"""
        dependency_target = (
            "<!-- contract-target: requirements=SIG-02 block=P0-SIG-02 "
            "action=add target=src/example.py:dependency -->\n"
            "```python contract-target\n"
            "def dependency() -> int:\n"
            "    return 1\n"
            "```\n"
        )

    contract = root / "docs/plan.md"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        dependency_block
        + f"""<!-- pair-block-definition: P0-SIG-04 -->
```toml pair-block
id = "P0-SIG-04"
requirements = ["SIG-03"]
targets = ["src/example.py:target"]
assets = {assets}
tests = ["tests/test_system_impact.py:test_plan"]
gate = {json.dumps(gate)}
depends_on = {dependencies}
```
{dependency_target}"""
        + "<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 "
        "action=update target=src/example.py:target -->\n"
        "```python contract-target\n"
        "def target(value: int) -> int:\n"
        "    return value + 1\n"
        "```\n",
        encoding="utf-8",
    )
    blocks, targets = compile_contract_plan(root, (contract,))
    declaration = blocks[-1].declaration
    requirements = tuple(
        ContractRequirement(
            requirement_id=requirement_id,
            contract="docs/plan.md",
            declaration=declaration,
        )
        for requirement_id in (("SIG-02", "SIG-03") if dependency else ("SIG-03",))
    )
    return ContractTraceabilityGraph(
        requirements=requirements,
        rules=(
            VerifierRule(
                rule_id="system.plan.closed",
                requirement_id="SIG-03",
                contract="docs/plan.md",
                statement="The selected source plan closes exactly.",
                declaration=declaration,
            ),
        ),
        edges=(
            RuleEdge(
                kind="implementation",
                rule_id="system.plan.closed",
                block_id="P0-SIG-04",
                declaration=declaration,
                state="planned",
                target=RepoSymbolRef(path="src/example.py", symbol="target"),
            ),
        ),
        targets=targets,
        blocks=blocks,
    )


def _write_check_source(
    root: Path,
    *,
    target_increment: int,
    dependency: bool = False,
    unexpected: bool = False,
) -> None:
    """Write one source state for a strict-closure test."""
    declarations = []
    if dependency:
        declarations.append("def dependency() -> int:\n    return 1")
    declarations.append(
        f"def target(value: int) -> int:\n    return value + {target_increment}"
    )
    if unexpected:
        declarations.append("def unplanned() -> int:\n    return 3")
    path = root / "src/example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(declarations) + "\n", encoding="utf-8")


def test_source_graph_is_canonical() -> None:
    """Canonicalize row order into byte-identical source-graph JSON."""
    dependency = _node(
        path="src/viper/models.py",
        symbol="ArtifactRef",
        kind="class",
    )
    dependent = _node(
        path="src/viper/storage.py",
        symbol="LocalArtifactStore.load",
        kind="method",
    )
    reads = _edge(index=10, source=dependent, target=dependency, kind="reads")
    constructs = _edge(
        index=11,
        source=dependent,
        target=dependency,
        kind="constructs",
    )

    forward = _source_graph(
        nodes=(dependency, dependent),
        edges=(reads, constructs),
    )
    reversed_rows = _source_graph(
        nodes=(dependent, dependency),
        edges=(constructs, reads),
    )

    assert forward == reversed_rows
    assert forward.model_dump_json() == reversed_rows.model_dump_json()
    assert tuple(node.node_id for node in forward.nodes) == tuple(
        sorted((dependency.node_id, dependent.node_id))
    )
    assert tuple(edge.edge_id for edge in forward.edges) == (
        reads.edge_id,
        constructs.edge_id,
    )


def test_declaration_extraction_preserves_exact_decorated_bytes() -> None:
    """Include decorators and preserve the original UTF-8 and CRLF bytes."""
    source = (
        b"class Service:\r\n"
        b"    @first\r\n"
        b'    @named("\xce\xbb")\r\n'
        b"    async def run(self, value: int) -> int:\r\n"
        b"        return value + 1\r\n"
        b"\r\n"
        b"unrelated = True\r\n"
    )
    expected = (
        b"@first\r\n"
        b'    @named("\xce\xbb")\r\n'
        b"    async def run(self, value: int) -> int:\r\n"
        b"        return value + 1"
    )

    assert extract_declaration_bytes(source, "Service.run") == expected


def test_declaration_extraction_resolves_shared_import_fence(
    tmp_path: Path,
) -> None:
    """Resolve two import bindings from one shared authored declaration fence."""
    plan_root = tmp_path / "plan"
    baseline_root = tmp_path / "baseline"
    baseline_path = baseline_root / "src/bindings.py"
    baseline_path.parent.mkdir(parents=True)
    before = b"from old_package import Alpha, Beta as B\n"
    after = b"from new_package import Alpha, Beta as B\n"
    baseline_path.write_bytes(before)
    declaration = _write_target_fence(plan_root, after.rstrip(b"\n"))
    targets = tuple(
        _target(
            action="update",
            path="src/bindings.py",
            symbol=symbol,
            declaration=declaration,
        )
        for symbol in ("Alpha", "B")
    )
    baseline_declaration = before.rstrip(b"\n")
    graph = _source_graph(
        nodes=tuple(
            _node(
                path="src/bindings.py",
                symbol=symbol,
                kind="import",
                declaration=baseline_declaration,
            )
            for symbol in ("Alpha", "B")
        )
    )

    result = inspect_plan(
        plan_root=plan_root,
        baseline_root=baseline_root,
        traceability=_traceability(targets=targets),
        block_ids=(_BLOCK_ID,),
        baseline=graph,
    )

    assert extract_declaration_bytes(after, "Alpha") == after.rstrip(b"\n")
    assert extract_declaration_bytes(after, "B") == after.rstrip(b"\n")
    assert extract_declaration_bytes(b"import package.module\n", "package") == (
        b"import package.module"
    )
    assert tuple(target.change_kind for target in result.targets) == (
        "unclassified",
        "unclassified",
    )
    assert len({target.expected_sha256 for target in result.targets}) == 1


@pytest.mark.parametrize(
    ("baseline", "expected", "change_kind"),
    (
        (
            b"def run(value: int) -> int:\n    return value",
            b"def run(value: str) -> int:\n    return len(value)",
            "callable_interface_changed",
        ),
        (
            b"def run(value: int) -> int:\n    return value",
            b"def run(value: int) -> int:\n    return value + 1",
            "implementation_changed",
        ),
        (
            b"class Item(Base):\n    value: int",
            b"class Item(Other):\n    value: int",
            "type_interface_changed",
        ),
        (b"value: int = 1", b"value: str = '1'", "type_interface_changed"),
        (b"from old import Item", b"from new import Item", "unclassified"),
        (b"def Item():\n    pass", b"class Item:\n    pass", "unclassified"),
    ),
)
def test_change_classifier_distinguishes_interface_and_body_updates(
    baseline: bytes,
    expected: bytes,
    change_kind: str,
) -> None:
    """Separate represented interface changes from body-only and unknown changes."""
    assert (
        classify_target_change(
            action="update",
            baseline=baseline,
            expected=expected,
        )
        == change_kind
    )


@pytest.mark.parametrize(
    ("action", "baseline", "expected"),
    (
        ("add", b"value = 1", b"value = 2"),
        ("add", None, None),
        ("remove", None, None),
        ("remove", b"value = 1", b"value = 2"),
        ("update", None, b"value = 2"),
        ("update", b"value = 1", None),
        ("update", b"value = 1", b"value = 1"),
    ),
)
def test_change_classifier_rejects_impossible_actions(
    action: TargetAction,
    baseline: bytes | None,
    expected: bytes | None,
) -> None:
    """Reject action declarations that contradict source presence or bytes."""
    with pytest.raises(SourceDeclarationError):
        classify_target_change(
            action=action,
            baseline=baseline,
            expected=expected,
        )


def test_plan_reports_only_policy_selected_one_hop_dependents(
    tmp_path: Path,
) -> None:
    """Use separate roots and stop callable-interface impact after one hop."""
    plan_root = tmp_path / "plan"
    baseline_root = tmp_path / "baseline"
    baseline_path = baseline_root / "src/target.py"
    baseline_path.parent.mkdir(parents=True)
    before = b"def target(value: int) -> int:\n    return value\n"
    after = (
        b"def target(value: int, *, strict: bool = False) -> int:\n    return value\n"
    )
    baseline_path.write_bytes(before)
    misleading_path = plan_root / "src/target.py"
    misleading_path.parent.mkdir(parents=True)
    misleading_path.write_bytes(b"def target():\n    raise RuntimeError\n")
    declaration = _write_target_fence(plan_root, after.rstrip(b"\n"))
    target = _node(
        path="src/target.py",
        symbol="target",
        kind="function",
        declaration=before.rstrip(b"\n"),
    )
    direct = _node(path="src/direct.py", symbol="direct", kind="function")
    transitive = _node(
        path="src/transitive.py",
        symbol="transitive",
        kind="function",
    )
    importer = _node(path="src/importer.py", symbol="target", kind="import")
    direct_call = _edge(index=1, source=direct, target=target, kind="calls")
    transitive_call = _edge(
        index=2,
        source=transitive,
        target=direct,
        kind="calls",
    )
    direct_import = _edge(
        index=3,
        source=importer,
        target=target,
        kind="imports",
    )
    graph = _source_graph(
        nodes=(target, direct, transitive, importer),
        edges=(direct_call, transitive_call, direct_import),
    )
    contract_target = _target(
        action="update",
        path=target.path,
        symbol=target.symbol,
        declaration=declaration,
    )

    result = inspect_plan(
        plan_root=plan_root,
        baseline_root=baseline_root,
        traceability=_traceability(targets=(contract_target,)),
        block_ids=(_BLOCK_ID,),
        baseline=graph,
    )

    assert result.targets[0].change_kind == "callable_interface_changed"
    assert result.impact.targets == (target.node_id,)
    assert result.impact.affected == (direct.node_id,)
    assert result.impact.edges == (direct_call.edge_id,)


def test_removed_target_reports_all_represented_direct_dependents(
    tmp_path: Path,
) -> None:
    """Report every represented incoming edge when a declaration is removed."""
    baseline_root = tmp_path / "baseline"
    baseline_path = baseline_root / "src/target.py"
    baseline_path.parent.mkdir(parents=True)
    before = b"class Target:\n    pass\n"
    baseline_path.write_bytes(before)
    target = _node(
        path="src/target.py",
        symbol="Target",
        kind="class",
        declaration=before.rstrip(b"\n"),
    )
    kinds = ("imports", "calls", "constructs", "inherits", "reads", "writes")
    dependents = tuple(
        _node(path=f"src/dependent_{index}.py", symbol="use", kind="function")
        for index, _ in enumerate(kinds, start=1)
    )
    edges = tuple(
        _edge(index=index, source=dependent, target=target, kind=kind)
        for index, (dependent, kind) in enumerate(
            zip(dependents, kinds, strict=True),
            start=10,
        )
    )
    contract_target = _target(
        action="remove",
        path=target.path,
        symbol=target.symbol,
        declaration=_declaration_ref(),
    )

    result = inspect_plan(
        plan_root=tmp_path / "plan",
        baseline_root=baseline_root,
        traceability=_traceability(targets=(contract_target,)),
        block_ids=(_BLOCK_ID,),
        baseline=_source_graph(nodes=(target, *dependents), edges=edges),
    )

    assert result.targets[0].change_kind == "removed"
    assert result.impact.affected == tuple(
        sorted(dependent.node_id for dependent in dependents)
    )
    assert result.impact.edges == tuple(sorted(edge.edge_id for edge in edges))


def test_unclassified_change_uses_conservative_one_hop_edges(
    tmp_path: Path,
) -> None:
    """Retain every represented incoming edge for an unclassified update."""
    plan_root = tmp_path / "plan"
    baseline_root = tmp_path / "baseline"
    baseline_path = baseline_root / "src/bindings.py"
    baseline_path.parent.mkdir(parents=True)
    before = b"from old_package import Item\n"
    after = b"from new_package import Item\n"
    baseline_path.write_bytes(before)
    declaration = _write_target_fence(plan_root, after.rstrip(b"\n"))
    target = _node(
        path="src/bindings.py",
        symbol="Item",
        kind="import",
        declaration=before.rstrip(b"\n"),
    )
    dependent = _node(path="src/consumer.py", symbol="consume", kind="function")
    kinds = ("imports", "calls", "constructs", "inherits", "reads", "writes")
    edges = tuple(
        _edge(index=index, source=dependent, target=target, kind=kind)
        for index, kind in enumerate(kinds, start=20)
    )
    contract_target = _target(
        action="update",
        path=target.path,
        symbol=target.symbol,
        declaration=declaration,
    )

    result = inspect_plan(
        plan_root=plan_root,
        baseline_root=baseline_root,
        traceability=_traceability(targets=(contract_target,)),
        block_ids=(_BLOCK_ID,),
        baseline=_source_graph(nodes=(target, dependent), edges=edges),
    )

    assert result.targets[0].change_kind == "unclassified"
    assert result.impact.affected == (dependent.node_id,)
    assert result.impact.edges == tuple(sorted(edge.edge_id for edge in edges))


# SIG-01 and SIG-02 source-analysis checks


def test_source_graph_rejects_receipt_drift_duplicates_and_dangling_edges() -> None:
    """Reject every identity defect that would make a graph receipt ambiguous."""
    dependency = _node(
        path="src/dependency.py",
        symbol="dependency",
        kind="function",
    )
    dependent = _node(
        path="src/dependent.py",
        symbol="dependent",
        kind="function",
    )
    edge = _edge(index=40, source=dependent, target=dependency, kind="calls")
    graph = _source_graph(nodes=(dependency, dependent), edges=(edge,))
    changed_snapshot = graph.snapshot.model_copy(update={"source_sha256": "a" * 64})
    changed_identity = graph.identity.model_copy(update={"version": "2.27.0"})

    with pytest.raises(ValueError, match="snapshot differs"):
        SourceGraph(
            snapshot=changed_snapshot,
            identity=graph.identity,
            nodes=graph.nodes,
            edges=graph.edges,
            receipt=graph.receipt,
        )
    with pytest.raises(ValueError, match="identity differs"):
        SourceGraph(
            snapshot=graph.snapshot,
            identity=changed_identity,
            nodes=graph.nodes,
            edges=graph.edges,
            receipt=graph.receipt,
        )
    with pytest.raises(ValueError, match="duplicate node IDs"):
        SourceGraph(
            snapshot=graph.snapshot,
            identity=graph.identity,
            nodes=(dependency, dependency),
            edges=(),
            receipt=graph.receipt,
        )
    with pytest.raises(ValueError, match="duplicate edge IDs"):
        SourceGraph(
            snapshot=graph.snapshot,
            identity=graph.identity,
            nodes=graph.nodes,
            edges=(edge, edge),
            receipt=graph.receipt,
        )
    with pytest.raises(ValueError, match="unknown endpoint"):
        SourceGraph(
            snapshot=graph.snapshot,
            identity=graph.identity,
            nodes=graph.nodes,
            edges=(edge.model_copy(update={"target": "src/missing.py:missing"}),),
            receipt=graph.receipt,
        )


def _write_fake_codeql(path: Path) -> Path:
    """Write a process-compatible CodeQL stand-in with fixed BQRS rows."""
    source = f"""#!{sys.executable}
import json
import sys
from pathlib import Path

args = sys.argv[1:]

def option(prefix: str) -> str:
    return next(value.split("=", 1)[1] for value in args if value.startswith(prefix))

if args[0] == "version":
    print(json.dumps({{"version": "2.26.4"}}))
elif args[:2] == ["database", "create"]:
    Path(args[2]).mkdir(parents=True, exist_ok=True)
elif args[:2] == ["query", "run"]:
    Path(option("--output=")).write_text(Path(args[2]).stem, encoding="utf-8")
elif args[:2] == ["bqrs", "decode"]:
    query = Path(args[2]).read_text(encoding="utf-8")
    if query == "Declarations":
        rows = [
            ["src/example.py", "dependency", "function", 1, 1, 2, 12],
            ["src/example.py", "dependent", "function", 4, 1, 5, 23],
        ]
    else:
        rows = [["src/example.py", 4, 1, "src/example.py", 1, 1,
                 "calls", "src/example.py", 5]]
    Path(option("--output=")).write_text(
        json.dumps({{"#select": {{"tuples": rows}}}}),
        encoding="utf-8",
    )
else:
    raise SystemExit(2)
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def _sig02_source_fixture(root: Path) -> None:
    """Write two declarations joined by one statically resolved call."""
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def dependency() -> int:\n"
        "    return 1\n"
        "\n"
        "def dependent() -> int:\n"
        "    return dependency()\n",
        encoding="utf-8",
    )


def _sig02_identity(query_pack: Path, executable: Path) -> CodeQLIdentity:
    """Bind the fake analyzer and exact checked-in query-pack tree."""
    return CodeQLIdentity(
        version="2.26.4",
        platform="osx64",
        executable_sha256=_sha256(executable.read_bytes()),
        pack="viper/python-impact@1.0.0",
        pack_sha256=_tree_digest(query_pack),
    )


def test_analyze_source_binds_digests_identity_and_database_reuse(
    tmp_path: Path,
) -> None:
    """Bind canonical rows to source and analyzer identity and reuse one database."""
    root = tmp_path / "source"
    _sig02_source_fixture(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    executable = _write_fake_codeql(tmp_path / "codeql")
    identity = _sig02_identity(query_pack, executable)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    cache = tmp_path / "cache"

    first = analyze_source(
        root,
        snapshot=snapshot,
        identity=identity,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=cache,
        artifact_root=tmp_path / "artifacts-first",
    )
    second = analyze_source(
        root,
        snapshot=snapshot,
        identity=identity,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=cache,
        artifact_root=tmp_path / "artifacts-second",
    )

    assert first.snapshot == snapshot
    assert first.identity == identity
    assert first.receipt.identity == identity
    assert first.receipt.snapshot == snapshot
    assert first.receipt.database_sha256 == second.receipt.database_sha256
    assert first.receipt.result_sha256 == second.receipt.result_sha256
    assert first.nodes == second.nodes
    assert first.edges == second.edges
    assert any(
        command[1:3] == ("database", "create") for command in first.receipt.commands
    )
    assert all(
        command[1:3] != ("database", "create") for command in second.receipt.commands
    )
    assert tuple(node.symbol for node in first.nodes) == (
        "dependency",
        "dependent",
    )
    assert len(first.edges) == 1
    assert first.edges[0].kind == "calls"
    assert first.edges[0].source == "src/example.py:dependent"
    assert first.edges[0].target == "src/example.py:dependency"


def test_analyze_source_rebuilds_tampered_cache_manifest(tmp_path: Path) -> None:
    """Refuse cache reuse when its manifest or database bytes are altered."""
    root = tmp_path / "source"
    _sig02_source_fixture(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    executable = _write_fake_codeql(tmp_path / "codeql")
    identity = _sig02_identity(query_pack, executable)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    cache = tmp_path / "cache"
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "identity": identity,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": cache,
    }
    analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-first",
    )
    manifest = next(cache.glob("*/viper-database.json"))
    manifest.write_text('{"key":"tampered"}', encoding="utf-8")

    rebuilt = analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-rebuilt",
    )

    assert any(
        command[1:3] == ("database", "create") for command in rebuilt.receipt.commands
    )
    assert json.loads(manifest.read_text(encoding="utf-8")) != {"key": "tampered"}

    database = manifest.parent / "database"
    (database / "tampered").write_text("changed", encoding="utf-8")
    rebuilt_again = analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-rebuilt-again",
    )

    assert any(
        command[1:3] == ("database", "create")
        for command in rebuilt_again.receipt.commands
    )
    assert not (database / "tampered").exists()


def test_analyze_source_rejects_source_pack_and_cli_identity_drift(
    tmp_path: Path,
) -> None:
    """Reject source, query-pack, and executable identities that differ."""
    root = tmp_path / "source"
    _sig02_source_fixture(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    executable = _write_fake_codeql(tmp_path / "codeql")
    identity = _sig02_identity(query_pack, executable)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "identity": identity,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
        "artifact_root": tmp_path / "artifacts",
    }

    with pytest.raises(CodeQLAnalysisError, match="source bytes"):
        analyze_source(
            **{
                **arguments,
                "snapshot": snapshot.model_copy(update={"source_sha256": "0" * 64}),
            }
        )
    with pytest.raises(CodeQLAnalysisError, match="query-pack bytes"):
        analyze_source(
            **{
                **arguments,
                "identity": identity.model_copy(update={"pack_sha256": "0" * 64}),
            }
        )
    with pytest.raises(CodeQLAnalysisError, match="executable version"):
        analyze_source(
            **{
                **arguments,
                "identity": identity.model_copy(update={"version": "2.27.0"}),
            }
        )
    with pytest.raises(CodeQLAnalysisError, match="executable digest"):
        analyze_source(
            **{
                **arguments,
                "identity": identity.model_copy(update={"executable_sha256": "0" * 64}),
            }
        )


@pytest.mark.integration
def test_checked_in_codeql_pack_analyzes_tiny_repository(tmp_path: Path) -> None:
    """Compile the checked-in QL pack and verify call and write dependencies."""
    if os.environ.get("VIPER_RUN_CODEQL_TESTS") != "1":
        pytest.skip("set VIPER_RUN_CODEQL_TESTS=1 to run the real CodeQL check")

    configured = os.environ.get("VIPER_CODEQL")
    executable_value = configured or shutil.which("codeql")
    assert executable_value is not None, "CodeQL is unavailable"
    executable = Path(executable_value).resolve()

    checked_in_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    query_pack = tmp_path / "query-pack"
    shutil.copytree(checked_in_pack, query_pack)

    installed = run_subprocess(
        (str(executable), "pack", "install", str(query_pack)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    version = run_subprocess(
        (str(executable), "version", "--format=json"),
        check=True,
        capture_output=True,
        text=True,
    )

    root = tmp_path / "source"
    _sig02_source_fixture(root)
    (root / "src/writes.py").write_text(
        "state = 0\n"
        "\n"
        "def update_state(value: int) -> None:\n"
        "    global state\n"
        "    state = value\n"
        "\n"
        "class Counter:\n"
        "    value = 0\n"
        "\n"
        "    def update(self, value: int) -> None:\n"
        "        self.value = value\n",
        encoding="utf-8",
    )

    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    identity = CodeQLIdentity(
        version=json.loads(version.stdout)["version"],
        platform=sys.platform,
        executable_sha256=_sha256(executable.read_bytes()),
        pack="viper/python-impact@1.0.0",
        pack_sha256=_tree_digest(query_pack),
    )

    graph = analyze_source(
        root,
        snapshot=snapshot,
        identity=identity,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=tmp_path / "cache",
        artifact_root=tmp_path / "artifacts",
    )

    assert {node.symbol for node in graph.nodes} >= {
        "dependency",
        "dependent",
        "state",
        "update_state",
        "Counter",
        "Counter.value",
        "Counter.update",
    }
    assert any(
        edge.source == "src/example.py:dependent"
        and edge.target == "src/example.py:dependency"
        and edge.kind == "calls"
        for edge in graph.edges
    )

    write_edges = {
        (edge.source, edge.target): (edge.path, edge.line)
        for edge in graph.edges
        if edge.kind == "writes"
    }
    assert write_edges[("src/writes.py:update_state", "src/writes.py:state")] == (
        "src/writes.py",
        5,
    )
    assert write_edges[
        ("src/writes.py:Counter.update", "src/writes.py:Counter.value")
    ] == ("src/writes.py", 11)


# SIG-04 strict closure and commit acceptance


def test_plan_check_rejects_unplanned_source_change(tmp_path: Path) -> None:
    """Reject a candidate that changes a declaration absent from the plan."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0)
    _write_check_source(realized_root, target_increment=1, unexpected=True)
    traceability = _write_check_contract(
        realized_root,
        gate=f"{sys.executable} -c pass",
    )

    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=_observed_graph(
            baseline_root,
            revision=_REVISION,
        ),
        realized=_observed_graph(realized_root),
    )

    assert result.targets[0].state == "passed"
    assert result.unexpected == (
        RepoSymbolRef(path="src/example.py", symbol="unplanned"),
    )
    assert not result.passed


def test_class_target_owns_nested_declaration_changes() -> None:
    """Treat class-container and nested declaration digests as one planned edit."""
    path = "src/example.py"
    baseline_class = _node(
        path=path,
        symbol="Example",
        kind="class",
        declaration=b"class Example:\n    value = 1",
    )
    baseline_field = _node(
        path=path,
        symbol="Example.value",
        kind="assignment",
        declaration=b"value = 1",
    )
    realized_class = baseline_class.model_copy(
        update={"sha256": _sha256(b"class Example:\n    value = 2")}
    )
    realized_field = baseline_field.model_copy(update={"sha256": _sha256(b"value = 2")})
    target = ContractTarget(
        requirements=(_REQUIREMENT_ID,),
        block_id=_BLOCK_ID,
        action="update",
        target=RepoSymbolRef(path=path, symbol="Example"),
        declaration=_declaration_ref(),
    )

    unexpected = _unexpected_changes(
        baseline_nodes={
            (path, "Example"): baseline_class,
            (path, "Example.value"): baseline_field,
        },
        realized_nodes={
            (path, "Example"): realized_class,
            (path, "Example.value"): realized_field,
        },
        targets=(target,),
    )

    assert unexpected == ()


def test_plan_check_runs_gates_and_validates_dependencies(tmp_path: Path) -> None:
    """Run each gate and distinguish satisfied and missing prior block output."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0, dependency=True)
    _write_check_source(realized_root, target_increment=1, dependency=True)
    traceability = _write_check_contract(
        realized_root,
        gate=f"{sys.executable} -c pass",
        dependency=True,
    )

    passed = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=_observed_graph(baseline_root, revision=_REVISION),
        realized=_observed_graph(realized_root),
    )

    assert passed.baseline_dependencies == ("P0-SIG-02",)
    assert passed.unsatisfied_dependencies == ()
    assert tuple(gate.block_id for gate in passed.gates) == ("P0-SIG-04",)
    assert passed.gates[0].exit_code == 0
    assert passed.passed

    missing_root = tmp_path / "missing-baseline"
    failed_root = tmp_path / "failed-realized"
    _write_check_source(missing_root, target_increment=0)
    _write_check_source(failed_root, target_increment=1)
    failed_traceability = _write_check_contract(
        failed_root,
        gate=f"{sys.executable} -c 'raise SystemExit(9)'",
        dependency=True,
    )
    failed = check_plan(
        root=failed_root,
        baseline_root=missing_root,
        traceability=failed_traceability,
        block_ids=("P0-SIG-04",),
        baseline=_observed_graph(missing_root, revision=_REVISION),
        realized=_observed_graph(failed_root),
    )

    assert failed.baseline_dependencies == ()
    assert failed.unsatisfied_dependencies == ("P0-SIG-02",)
    assert failed.gates[0].exit_code == 9
    assert not failed.passed


def test_plan_check_rejects_asset_changed_by_gate(tmp_path: Path) -> None:
    """Invalidate the frozen plan when its gate changes an owned asset."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0)
    _write_check_source(realized_root, target_increment=1)
    asset = realized_root / "tools/rule.ql"
    asset.parent.mkdir(parents=True)
    asset.write_text("original\n", encoding="utf-8")
    gate = (
        f'{sys.executable} -c "from pathlib import Path; '
        "Path('tools/rule.ql').write_text('changed')\""
    )
    traceability = _write_check_contract(
        realized_root,
        gate=gate,
        asset=True,
    )

    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=_observed_graph(baseline_root, revision=_REVISION),
        realized=_observed_graph(realized_root),
    )

    assert result.gates[0].exit_code == 0
    assert not result.plan_valid
    assert not result.passed


def test_plan_check_rejects_wrong_target_and_receipt_identity(
    tmp_path: Path,
) -> None:
    """Reject an incorrect declaration and a candidate from another analyzer."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0)
    _write_check_source(realized_root, target_increment=2)
    traceability = _write_check_contract(
        realized_root,
        gate=f"{sys.executable} -c pass",
    )
    baseline = _observed_graph(baseline_root, revision=_REVISION)
    other_identity = baseline.identity.model_copy(update={"version": "2.27.0"})

    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=baseline,
        realized=_observed_graph(realized_root, identity=other_identity),
    )

    assert result.targets[0].state == "failed"
    assert not result.receipts_valid
    assert not result.passed


def _git(root: Path, *arguments: str) -> str:
    """Run one successful Git command in an isolated acceptance repository."""
    return run_subprocess(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_acceptance_binds_commit_to_checked_source_and_plan(tmp_path: Path) -> None:
    """Accept exact committed bytes and reject later source or plan drift."""
    root = tmp_path / "repository"
    baseline_root = tmp_path / "baseline"
    root.mkdir()
    _write_check_source(root, target_increment=0)
    _write_check_source(baseline_root, target_increment=0)
    traceability = _write_check_contract(
        root,
        gate=f"{sys.executable} -c pass",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "system-impact@example.invalid")
    _git(root, "config", "user.name", "System Impact Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    baseline_revision = _git(root, "rev-parse", "HEAD")
    baseline = _observed_graph(
        baseline_root,
        base_revision=baseline_revision,
        revision=baseline_revision,
    )

    _write_check_source(root, target_increment=1)
    realized = _observed_graph(root, base_revision=baseline_revision)
    checked = check_plan(
        root=root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=baseline,
        realized=realized,
    )
    _git(root, "add", "src/example.py")
    _git(root, "commit", "-qm", "realized")
    realized_revision = _git(root, "rev-parse", "HEAD")

    acceptance = accept(root=root, check=checked, revision=realized_revision)

    assert acceptance.revision == realized_revision
    assert len(acceptance.check) == 64

    contract = root / "docs/plan.md"
    accepted_contract = contract.read_bytes()
    contract.write_bytes(accepted_contract.replace(b"-c pass", b"-c 'pass'"))
    _git(root, "add", "docs/plan.md")
    _git(root, "commit", "-qm", "drift plan")
    plan_drift_revision = _git(root, "rev-parse", "HEAD")
    with pytest.raises(SystemImpactCheckError, match="plan differs"):
        accept(root=root, check=checked, revision=plan_drift_revision)

    contract.write_bytes(accepted_contract)
    (root / "extra.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "drift source")
    source_drift_revision = _git(root, "rev-parse", "HEAD")
    with pytest.raises(SystemImpactCheckError, match="source differs"):
        accept(root=root, check=checked, revision=source_drift_revision)


# SIG-05 portable historical replay


def _fixture_source_path(root: Path, path: str, suffix: str) -> Path:
    """Resolve a historical source path, including pytest-safe fixture suffixes."""
    direct = root / path
    return direct if direct.is_file() else Path(f"{direct}{suffix}")


def _fixture_declarations(source: bytes) -> dict[str, str]:
    """Return exact declaration digests from one historical Python file."""
    tree = ast.parse(source.decode("utf-8"), type_comments=True)
    return {
        symbol: _sha256(_node_span(declaration, source)[-1])
        for symbol, declaration, _ in _qualified_declarations(tree)
    }


def _assert_historical_fixture(
    fixture_id: str,
    baseline_revision: str,
    realized_revision: str,
    tmp_path: Path,
) -> None:
    """Run the strict plan check over one reviewed historical transition."""
    fixture_root = Path(__file__).parent / "data/system_impact" / fixture_id
    metadata = json.loads((fixture_root / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["baseline_revision"] == baseline_revision
    assert metadata["realized_revision"] == realized_revision
    suffix = metadata["test_source_suffix"]
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    before: dict[tuple[str, str], str] = {}
    after: dict[tuple[str, str], str] = {}
    realized_sources: dict[str, bytes] = {}
    for record in metadata["source_files"]:
        path = record["path"]
        baseline_source = _fixture_source_path(fixture_root / "baseline", path, suffix)
        realized_source = _fixture_source_path(fixture_root / "realized", path, suffix)
        baseline_bytes = baseline_source.read_bytes()
        realized_bytes = realized_source.read_bytes()
        assert _sha256(baseline_bytes) == record["baseline_sha256"]
        assert _sha256(realized_bytes) == record["realized_sha256"]
        realized_sources[path] = realized_bytes
        for destination_root, content in (
            (baseline_root, baseline_bytes),
            (realized_root, realized_bytes),
        ):
            destination = destination_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        before.update(
            ((path, symbol), digest)
            for symbol, digest in _fixture_declarations(baseline_bytes).items()
        )
        after.update(
            ((path, symbol), digest)
            for symbol, digest in _fixture_declarations(realized_bytes).items()
        )

    observed = {
        (
            path,
            symbol,
            "add" if key not in before else "remove" if key not in after else "update",
        )
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
        for path, symbol in (key,)
    }
    expected = {
        (record["path"], record["symbol"], record["action"])
        for record in metadata["expected_changed_declarations"]
    }
    assert observed == expected
    for record in metadata["expected_changed_declarations"]:
        key = (record["path"], record["symbol"])
        assert before.get(key) == record["baseline_sha256"]
        assert after.get(key) == record["realized_sha256"]

    expected_records = metadata["expected_changed_declarations"]
    target_values = [
        f"{record['path']}:{record['symbol']}" for record in expected_records
    ]
    plan_parts = [
        "<!-- pair-block-definition: P0-SIG-05 -->\n",
        "```toml pair-block\n",
        'id = "P0-SIG-05"\n',
        'requirements = ["SIG-04"]\n',
        f"targets = {json.dumps(target_values)}\n",
        'tests = ["tests/test_system_impact.py:test_committed_manifest_rename"]\n',
        f"gate = {json.dumps(f'{sys.executable} -c pass')}\n",
        "depends_on = []\n",
        "```\n",
    ]
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for record in expected_records:
        key = (record["path"], record["symbol"].split(".", maxsplit=1)[0])
        groups.setdefault(key, []).append(record)
    for (path, top_level_symbol), records in groups.items():
        for record in records:
            plan_parts.append(
                "<!-- contract-target: requirements=SIG-04 block=P0-SIG-05 "
                f"action={record['action']} target={path}:{record['symbol']} -->\n"
            )
        if all(record["action"] == "remove" for record in records):
            plan_parts.append("<!-- contract-remove -->\n")
        else:
            declaration = extract_declaration_bytes(
                realized_sources[path],
                top_level_symbol,
            ).decode("utf-8")
            plan_parts.extend(("```python contract-target\n", declaration, "\n```\n"))

    plan_path = realized_root / "docs/plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("".join(plan_parts), encoding="utf-8")
    blocks, targets = compile_contract_plan(realized_root, (plan_path,))
    declaration = blocks[0].declaration
    traceability = ContractTraceabilityGraph(
        requirements=(
            ContractRequirement(
                requirement_id="SIG-04",
                contract="docs/plan.md",
                declaration=declaration,
            ),
        ),
        rules=(
            VerifierRule(
                rule_id="system.fixture.replayed",
                requirement_id="SIG-04",
                contract="docs/plan.md",
                statement="The historical source transition matches its exact plan.",
                declaration=declaration,
            ),
        ),
        edges=(
            RuleEdge(
                kind="implementation",
                rule_id="system.fixture.replayed",
                block_id="P0-SIG-05",
                declaration=declaration,
                state="planned",
                target=targets[0].target,
            ),
        ),
        targets=targets,
        blocks=blocks,
    )
    baseline_graph = _observed_graph(
        baseline_root,
        base_revision=baseline_revision,
        revision=baseline_revision,
    )
    realized_graph = _observed_graph(
        realized_root,
        base_revision=baseline_revision,
    )
    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-05",),
        baseline=baseline_graph,
        realized=realized_graph,
    )

    assert result.passed, result.model_dump(mode="json")
    assert result.unexpected == ()
    assert all(target.state == "passed" for target in result.targets)
    assert {
        (
            target.resolved.target.target.path,
            target.resolved.target.target.symbol,
            target.resolved.target.action,
        )
        for target in result.targets
    } == expected


def test_committed_manifest_rename(tmp_path: Path) -> None:
    """Replay the global skills manifest-field migration fixture."""
    _assert_historical_fixture(
        "agents_manifest_migration",
        "6eb74b8e8bba2ddf2f2f9fa3822e11c5d9a3d06b",
        "18083057eeb92c755ead031122afd48e8a77d653",
        tmp_path,
    )


def test_completed_viper_pair_block(tmp_path: Path) -> None:
    """Replay the accepted VIPER P0-PROOF-05 fixture."""
    _assert_historical_fixture(
        "viper_p0_proof_05",
        "1e33d9a7bd12327702397c0e7aaf96e490dec46e",
        "5c78ff5d33bdfa9c7b92b7bb9ff5c0fefdc7eef8",
        tmp_path,
    )


def test_one_hop_records_baseline_and_candidate_neighbors(tmp_path: Path) -> None:
    """Record direct dependents found before and after a selected update."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0)
    _write_check_source(realized_root, target_increment=1)
    traceability = _write_check_contract(
        realized_root,
        gate=f"{sys.executable} -c pass",
    )
    baseline_target = _node(
        path="src/example.py",
        symbol="target",
        kind="function",
        declaration=b"def target(value: int) -> int:\n    return value + 0",
    )
    realized_target = _node(
        path="src/example.py",
        symbol="target",
        kind="function",
        declaration=b"def target(value: int) -> int:\n    return value + 1",
    )
    caller = _node(path="src/caller.py", symbol="caller", kind="function")
    adapter = _node(path="src/adapter.py", symbol="adapter", kind="function")
    before = _edge(index=21, source=caller, target=baseline_target, kind="calls")
    after = _edge(index=22, source=adapter, target=realized_target, kind="calls")

    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=_source_graph(
            nodes=(baseline_target, caller),
            edges=(before,),
            source_sha256=source_digest(baseline_root),
        ),
        realized=_source_graph(
            nodes=(realized_target, adapter),
            edges=(after,),
            source_sha256=source_digest(realized_root),
            revision=None,
        ),
    )

    assert result.one_hop.targets == (baseline_target.node_id,)
    assert result.one_hop.neighbors == (adapter.node_id, caller.node_id)
    assert result.one_hop.changed == (adapter.node_id, caller.node_id)
    assert result.one_hop.before == (before.edge_id,)
    assert result.one_hop.after == (after.edge_id,)
    assert result.one_hop.removed == (before.edge_id,)
    assert result.one_hop.added == (after.edge_id,)


def test_pre_pairing_pyright_rejects_stale_caller(tmp_path: Path) -> None:
    """Reject a caller that omits a new required parameter."""
    root = tmp_path / "candidate"
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def save(path: str, overwrite: bool) -> None:\n"
        "    pass\n"
        "\n"
        "def publish() -> None:\n"
        "    save('artifact')\n",
        encoding="utf-8",
    )
    (root / "pyrightconfig.json").write_text(
        json.dumps({"include": ["src"], "typeCheckingMode": "standard"}),
        encoding="utf-8",
    )

    checked = run_subprocess(
        (
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(root / "pyrightconfig.json"),
            "--pythonpath",
            sys.executable,
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert checked.returncode != 0
    assert "overwrite" in checked.stdout
