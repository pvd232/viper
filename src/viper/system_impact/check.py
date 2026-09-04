"""Check one selected PairBlock plan and bind it to an accepted commit."""

from __future__ import annotations

import ast
import hashlib
import json
import shlex
import tempfile
from pathlib import Path

import viper._subprocess as subprocess

from .._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlock,
    PairBlockId,
    RepoSymbolRef,
    compile_contract_plan,
)
from .._system_impact.codeql import IGNORED_PARTS, source_digest
from .._system_impact.source import (
    SourceDeclarationError,
    declaration_payload,
    extract_declaration_bytes,
    import_binding,
)
from .models import (
    Acceptance,
    CommitId,
    GateCheck,
    OneHop,
    PlanCheck,
    ResolvedContractTarget,
    SourceGraph,
    SourceNode,
    TargetCheck,
)
from .plan import IMPACT_EDGE_KINDS_V1, inspect_plan


class SystemImpactCheckError(ValueError):
    """Report malformed check inputs or a failed acceptance binding."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _node_index(graph: SourceGraph) -> dict[tuple[str, str], SourceNode]:
    index: dict[tuple[str, str], SourceNode] = {}
    for node in graph.nodes:
        key = (node.path, node.symbol)
        if key in index:
            raise SystemImpactCheckError(
                f"SourceGraph contains duplicate declaration identity: {key!r}"
            )
        index[key] = node
    return index


def _target_key(target: ContractTarget) -> tuple[str, str]:
    return target.target.path, target.target.symbol


def _selected_records(
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
) -> tuple[tuple[PairBlock, ...], tuple[ContractTarget, ...]]:
    if not block_ids:
        raise SystemImpactCheckError("check_plan requires at least one PairBlock")
    if len(block_ids) != len(set(block_ids)):
        raise SystemImpactCheckError("check_plan received a duplicate PairBlock ID")

    block_by_id = {block.block_id: block for block in traceability.blocks}
    missing = sorted(set(block_ids) - block_by_id.keys())
    if missing:
        raise SystemImpactCheckError(
            f"selected PairBlock is absent from traceability: {missing}"
        )

    selected = set(block_ids)
    blocks = tuple(
        sorted((block_by_id[item] for item in selected), key=lambda x: x.block_id)
    )
    targets = tuple(
        sorted(
            (target for target in traceability.targets if target.block_id in selected),
            key=lambda target: (
                target.block_id,
                target.target.path,
                target.target.symbol,
            ),
        )
    )
    for block in blocks:
        owned = {
            _target_key(target)
            for target in targets
            if target.block_id == block.block_id
        }
        declared = {(target.path, target.symbol) for target in block.targets}
        if declared != owned:
            raise SystemImpactCheckError(
                f"PairBlock target closure failed: {block.block_id}"
            )
    return blocks, targets


def _plan_sha256(
    blocks: tuple[PairBlock, ...],
    targets: tuple[ContractTarget, ...],
    asset_manifest_sha256: str,
) -> str:
    payload = {
        "schema_version": 1,
        "blocks": [block.model_dump(mode="json") for block in blocks],
        "targets": [target.model_dump(mode="json") for target in targets],
        "asset_manifest_sha256": asset_manifest_sha256,
    }
    return _sha256(_canonical_json(payload))


def _asset_manifest_sha256(
    *,
    root: Path,
    blocks: tuple[PairBlock, ...],
    revision: CommitId | None = None,
) -> str:
    rows: list[dict[str, str]] = []
    assets = sorted({str(asset) for block in blocks for asset in block.assets})
    for relative in assets:
        if revision is None:
            try:
                content = (root / relative).read_bytes()
            except OSError as error:
                raise SystemImpactCheckError(
                    f"cannot read selected PairBlock asset: {relative}"
                ) from error
        else:
            content = _git(root, ("show", f"{revision}:{relative}"))
        rows.append({"path": relative, "sha256": _sha256(content)})
    return _sha256(_canonical_json(rows))


def _one_hop(
    *,
    targets: tuple[ResolvedContractTarget, ...],
    baseline: SourceGraph,
    realized: SourceGraph,
) -> OneHop:
    """Record direct dependents selected by the existing impact policy."""
    baseline_nodes = {node.node_id: node for node in baseline.nodes}
    realized_nodes = {node.node_id: node for node in realized.nodes}
    indexes = (_node_index(baseline), _node_index(realized))
    node_kinds: dict[str, set[str]] = {}
    for target in targets:
        key = _target_key(target.target)
        kinds = IMPACT_EDGE_KINDS_V1[target.change_kind]

        # Adds exist only afterward and removals only beforehand, so each target
        # must be resolved in both graphs.
        for index in indexes:
            node = index.get(key)
            if node is not None:
                node_kinds.setdefault(node.node_id, set()).update(kinds)

    before = tuple(
        sorted(
            edge.edge_id
            for edge in baseline.edges
            if edge.target in node_kinds and edge.kind in node_kinds[edge.target]
        )
    )
    after = tuple(
        sorted(
            edge.edge_id
            for edge in realized.edges
            if edge.target in node_kinds and edge.kind in node_kinds[edge.target]
        )
    )
    before_ids = set(before)
    after_ids = set(after)
    selected_ids = before_ids | after_ids
    selected_edges = tuple(
        edge
        for edge in (*baseline.edges, *realized.edges)
        if edge.edge_id in selected_ids
    )
    neighbors = tuple(sorted({edge.source for edge in selected_edges}))
    changed = tuple(
        node_id
        for node_id in neighbors
        if baseline_nodes.get(node_id) is None
        or realized_nodes.get(node_id) is None
        or baseline_nodes[node_id].sha256 != realized_nodes[node_id].sha256
    )
    return OneHop(
        targets=tuple(sorted(node_kinds)),
        neighbors=neighbors,
        changed=changed,
        before=before,
        after=after,
        removed=tuple(sorted(before_ids - after_ids)),
        added=tuple(sorted(after_ids - before_ids)),
    )


def _declaration_payload(root: Path, target: ContractTarget) -> bytes | None:
    try:
        return declaration_payload(root, target)
    except SourceDeclarationError as error:
        raise SystemImpactCheckError(str(error)) from error


def _target_is_satisfied(
    *,
    root: Path,
    target: ContractTarget,
    nodes: dict[tuple[str, str], SourceNode],
) -> bool:
    node = nodes.get(_target_key(target))
    if target.action == "remove":
        return node is None
    expected = _declaration_payload(root, target)
    assert expected is not None
    if node is not None and node.kind == "import":
        realized = (root / target.target.path).read_bytes()
        return import_binding(expected, target.target.symbol) == import_binding(
            realized,
            target.target.symbol,
        )
    return node is not None and node.sha256 == _sha256(expected)


def _dependency_results(
    *,
    root: Path,
    traceability: ContractTraceabilityGraph,
    blocks: tuple[PairBlock, ...],
    selected: set[PairBlockId],
    baseline_nodes: dict[tuple[str, str], SourceNode],
) -> tuple[tuple[PairBlockId, ...], tuple[PairBlockId, ...]]:
    block_by_id = {block.block_id: block for block in traceability.blocks}
    targets_by_block: dict[PairBlockId, list[ContractTarget]] = {}
    for target in traceability.targets:
        targets_by_block.setdefault(target.block_id, []).append(target)

    baseline_satisfied: set[PairBlockId] = set()
    unsatisfied: set[PairBlockId] = set()
    for block in blocks:
        for dependency in block.depends_on:
            if dependency in selected:
                continue
            dependency_block = block_by_id.get(dependency)
            dependency_targets = targets_by_block.get(dependency, [])
            if (
                dependency_block is not None
                and dependency_targets
                and all(
                    _target_is_satisfied(
                        root=root,
                        target=target,
                        nodes=baseline_nodes,
                    )
                    for target in dependency_targets
                )
            ):
                baseline_satisfied.add(dependency)
            else:
                unsatisfied.add(dependency)
    return tuple(sorted(baseline_satisfied)), tuple(sorted(unsatisfied))


def _run_gate(
    *,
    root: Path,
    block: PairBlock,
    timeout_seconds: float,
) -> GateCheck:
    try:
        command = tuple(shlex.split(block.gate, posix=True))
    except ValueError as error:
        return GateCheck(
            block_id=block.block_id,
            command=(block.gate,),
            exit_code=2,
            stdout_sha256=_sha256(b""),
            stderr_sha256=_sha256(str(error).encode("utf-8")),
        )
    if not command:
        return GateCheck(
            block_id=block.block_id,
            command=(block.gate,),
            exit_code=2,
            stdout_sha256=_sha256(b""),
            stderr_sha256=_sha256(b"empty gate command"),
        )

    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        return GateCheck(
            block_id=block.block_id,
            command=command,
            exit_code=124,
            stdout_sha256=_sha256(stdout),
            stderr_sha256=_sha256(stderr),
        )
    except OSError as error:
        return GateCheck(
            block_id=block.block_id,
            command=command,
            exit_code=127,
            stdout_sha256=_sha256(b""),
            stderr_sha256=_sha256(str(error).encode("utf-8")),
        )

    return GateCheck(
        block_id=block.block_id,
        command=command,
        exit_code=completed.returncode,
        stdout_sha256=_sha256(completed.stdout),
        stderr_sha256=_sha256(completed.stderr),
    )


def _receipt_pair_is_valid(baseline: SourceGraph, realized: SourceGraph) -> bool:
    def result_sha256(graph: SourceGraph) -> str:
        return _sha256(
            _canonical_json(
                {
                    "nodes": [node.model_dump(mode="json") for node in graph.nodes],
                    "edges": [edge.model_dump(mode="json") for edge in graph.edges],
                }
            )
        )

    return (
        baseline.receipt.snapshot == baseline.snapshot
        and realized.receipt.snapshot == realized.snapshot
        and baseline.receipt.exit_code == 0
        and realized.receipt.exit_code == 0
        and baseline.receipt.result_sha256 == result_sha256(baseline)
        and realized.receipt.result_sha256 == result_sha256(realized)
        and baseline.identity == realized.identity
        and baseline.snapshot.revision is not None
        and realized.snapshot.base_revision == baseline.snapshot.revision
    )


def _target_checks(
    *,
    root: Path,
    resolved_targets: tuple[ResolvedContractTarget, ...],
    realized_nodes: dict[tuple[str, str], SourceNode],
) -> tuple[TargetCheck, ...]:
    checks: list[TargetCheck] = []
    for resolved in resolved_targets:
        target = resolved.target
        after = realized_nodes.get(_target_key(target))
        if target.action == "remove":
            passed = after is None
            message = (
                "target declaration is absent"
                if passed
                else "removed target declaration remains present"
            )
        else:
            expected = _declaration_payload(root, target)
            if after is not None and after.kind == "import" and expected is not None:
                realized = (root / target.target.path).read_bytes()
                passed = import_binding(
                    expected,
                    target.target.symbol,
                ) == import_binding(realized, target.target.symbol)
            else:
                passed = after is not None and after.sha256 == resolved.expected_sha256
            if after is None:
                message = "required target declaration is absent"
            elif passed:
                message = (
                    "target import matches the authored binding"
                    if after.kind == "import"
                    else "target declaration matches the authored bytes"
                )
            else:
                message = "target declaration differs from the authored bytes"
        checks.append(
            TargetCheck(
                resolved=resolved,
                after_sha256=None if after is None else after.sha256,
                state="passed" if passed else "failed",
                message=message,
            )
        )
    return tuple(checks)


def _unexpected_changes(
    *,
    baseline_root: Path,
    realized_root: Path,
    baseline_nodes: dict[tuple[str, str], SourceNode],
    realized_nodes: dict[tuple[str, str], SourceNode],
    targets: tuple[ContractTarget, ...],
) -> tuple[RepoSymbolRef, ...]:
    changed: set[tuple[str, str]] = set()
    for key in baseline_nodes.keys() | realized_nodes.keys():
        before = baseline_nodes.get(key)
        after = realized_nodes.get(key)
        if before is None or after is None:
            changed.add(key)
            continue
        if before.sha256 == after.sha256:
            continue
        if before.kind == after.kind == "import":
            baseline_source = (baseline_root / before.path).read_bytes()
            realized_source = (realized_root / after.path).read_bytes()
            if import_binding(baseline_source, before.symbol) == import_binding(
                realized_source,
                after.symbol,
            ):
                continue
        try:
            baseline_declaration = extract_declaration_bytes(
                (baseline_root / before.path).read_bytes(),
                before.symbol,
            )
            realized_declaration = extract_declaration_bytes(
                (realized_root / after.path).read_bytes(),
                after.symbol,
            )
            baseline_tree = ast.parse(baseline_declaration, type_comments=True)
            realized_tree = ast.parse(realized_declaration, type_comments=True)
            if ast.dump(baseline_tree, include_attributes=False) == ast.dump(
                realized_tree,
                include_attributes=False,
            ):
                continue
        except (OSError, SyntaxError, SourceDeclarationError):
            pass
        changed.add(key)
    all_nodes = {**baseline_nodes, **realized_nodes}
    planned: set[tuple[str, str]] = set()
    import_spans: set[tuple[str, int, int, int, int]] = set()
    for target in targets:
        target_key = _target_key(target)
        planned.add(target_key)
        target_node = all_nodes.get(target_key)
        for node in (baseline_nodes.get(target_key), realized_nodes.get(target_key)):
            if node is not None and node.kind == "import":
                import_spans.add(
                    (
                        node.path,
                        node.start_line,
                        node.start_col,
                        node.end_line,
                        node.end_col,
                    )
                )
        for key, node in all_nodes.items():
            if key[0] != target_key[0]:
                continue
            target_contains_node = (
                target_node is not None
                and target_node.kind == "class"
                and node.symbol.startswith(f"{target_key[1]}.")
            )
            node_contains_target = node.kind == "class" and target_key[1].startswith(
                f"{node.symbol}."
            )
            if target_contains_node or node_contains_target:
                planned.add(key)
    for key, node in all_nodes.items():
        span = (
            node.path,
            node.start_line,
            node.start_col,
            node.end_line,
            node.end_col,
        )
        if node.kind == "import" and span in import_spans:
            # One import target owns the whole statement; Ruff may regroup its names.
            planned.add(key)
    return tuple(
        RepoSymbolRef(path=path, symbol=symbol)
        for path, symbol in sorted(changed - planned)
    )


def check_plan(
    *,
    root: Path,
    baseline_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
    realized: SourceGraph,
    gate_timeout_seconds: float = 900.0,
) -> PlanCheck:
    """Check selected PairBlocks against independently observed source graphs."""
    root = root.resolve()
    baseline_root = baseline_root.resolve()
    if gate_timeout_seconds <= 0:
        raise SystemImpactCheckError("gate timeout must be greater than zero")

    blocks, targets = _selected_records(traceability, block_ids)
    baseline_nodes = _node_index(baseline)
    realized_nodes = _node_index(realized)
    inspection = inspect_plan(
        plan_root=root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=tuple(block.block_id for block in blocks),
        baseline=baseline,
    )
    target_checks = _target_checks(
        root=root,
        resolved_targets=inspection.targets,
        realized_nodes=realized_nodes,
    )
    one_hop = _one_hop(
        targets=inspection.targets,
        baseline=baseline,
        realized=realized,
    )
    unexpected = _unexpected_changes(
        baseline_root=baseline_root,
        realized_root=root,
        baseline_nodes=baseline_nodes,
        realized_nodes=realized_nodes,
        targets=targets,
    )
    baseline_dependencies, unsatisfied_dependencies = _dependency_results(
        root=root,
        traceability=traceability,
        blocks=blocks,
        selected={block.block_id for block in blocks},
        baseline_nodes=baseline_nodes,
    )
    plan_sha256 = _plan_sha256(
        blocks,
        targets,
        _asset_manifest_sha256(root=root, blocks=blocks),
    )
    contracts = tuple(sorted({item.declaration.path for item in (*blocks, *targets)}))
    gates = tuple(
        _run_gate(
            root=root,
            block=block,
            timeout_seconds=gate_timeout_seconds,
        )
        for block in blocks
    )
    receipt_valid = _receipt_pair_is_valid(baseline, realized)
    try:
        plan_valid = (
            _current_plan_sha256(
                root=root,
                contracts=contracts,
                block_ids=tuple(block.block_id for block in blocks),
            )
            == plan_sha256
        )
    except SystemImpactCheckError:
        plan_valid = False
    source_valid = (
        source_digest(baseline_root) == baseline.snapshot.source_sha256
        and source_digest(root) == realized.snapshot.source_sha256
    )
    passed = (
        receipt_valid
        and plan_valid
        and source_valid
        and all(target.state == "passed" for target in target_checks)
        and not unexpected
        and not unsatisfied_dependencies
        and all(gate.exit_code == 0 for gate in gates)
    )
    return PlanCheck(
        baseline=baseline.snapshot,
        realized=realized.snapshot,
        blocks=tuple(block.block_id for block in blocks),
        contracts=contracts,
        baseline_dependencies=baseline_dependencies,
        unsatisfied_dependencies=unsatisfied_dependencies,
        plan_sha256=plan_sha256,
        impact=inspection.impact,
        one_hop=one_hop,
        targets=target_checks,
        unexpected=unexpected,
        gates=gates,
        receipts_valid=receipt_valid,
        plan_valid=plan_valid,
        source_valid=source_valid,
        passed=passed,
    )


def _git(
    root: Path,
    arguments: tuple[str, ...],
    *,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        input=input_bytes,
        check=False,
        capture_output=True,
        shell=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SystemImpactCheckError(f"Git operation failed: {message}")
    return completed.stdout


def _snapshot_source_sha256(root: Path, revision: CommitId | None) -> str:
    if revision is None:
        return source_digest(root)
    raw_paths = _git(
        root,
        ("ls-tree", "-r", "-z", "--name-only", revision),
    )
    paths = sorted(
        path.decode("utf-8")
        for path in raw_paths.split(b"\0")
        if path
        and path.endswith(b".py")
        and not any(part in IGNORED_PARTS for part in Path(path.decode("utf-8")).parts)
    )
    rows: list[dict[str, str]] = []
    for path in paths:
        content = _git(root, ("show", f"{revision}:{path}"))
        rows.append({"path": path, "sha256": _sha256(content)})
    return _sha256(_canonical_json(rows))


def _current_plan_sha256(
    *,
    root: Path,
    contracts: tuple[str, ...],
    block_ids: tuple[PairBlockId, ...],
) -> str:
    contract_paths = tuple(root / relative for relative in contracts)
    parsed_blocks, parsed_targets = compile_contract_plan(root, contract_paths)
    selected = set(block_ids)
    blocks = tuple(block for block in parsed_blocks if block.block_id in selected)
    targets = tuple(target for target in parsed_targets if target.block_id in selected)
    if {block.block_id for block in blocks} != selected:
        raise SystemImpactCheckError(
            "working tree does not contain every selected PairBlock"
        )
    return _plan_sha256(
        blocks,
        targets,
        _asset_manifest_sha256(root=root, blocks=blocks),
    )


def _committed_plan(
    *,
    root: Path,
    revision: CommitId,
    contracts: tuple[str, ...],
    block_ids: tuple[PairBlockId, ...],
) -> tuple[str, tuple[ContractTarget, ...]]:
    with tempfile.TemporaryDirectory(prefix="viper-system-impact-") as directory:
        temporary_root = Path(directory)
        contract_paths: list[Path] = []
        for relative in contracts:
            destination = temporary_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(_git(root, ("show", f"{revision}:{relative}")))
            contract_paths.append(destination)
        parsed_blocks, parsed_targets = compile_contract_plan(
            temporary_root,
            tuple(contract_paths),
        )

    selected = set(block_ids)
    blocks = tuple(block for block in parsed_blocks if block.block_id in selected)
    targets = tuple(target for target in parsed_targets if target.block_id in selected)
    if {block.block_id for block in blocks} != selected:
        raise SystemImpactCheckError(
            "accepted commit does not contain every selected PairBlock"
        )
    return (
        _plan_sha256(
            blocks,
            targets,
            _asset_manifest_sha256(
                root=root,
                blocks=blocks,
                revision=revision,
            ),
        ),
        targets,
    )


def accept(
    *,
    root: Path,
    check: PlanCheck,
    revision: CommitId,
) -> Acceptance:
    """Bind one passing check to identical committed source and plan bytes."""
    root = root.resolve()
    check_is_passing = (
        check.passed
        and check.receipts_valid
        and check.plan_valid
        and check.source_valid
        and all(target.state == "passed" for target in check.targets)
        and not check.unexpected
        and not check.unsatisfied_dependencies
        and all(gate.exit_code == 0 for gate in check.gates)
        and tuple(sorted(gate.block_id for gate in check.gates)) == check.blocks
    )
    if not check_is_passing:
        raise SystemImpactCheckError("cannot accept a failed PlanCheck")
    if check.realized.revision is not None and check.realized.revision != revision:
        raise SystemImpactCheckError(
            "accepted commit differs from the committed realized snapshot"
        )
    resolved_revision = (
        _git(
            root,
            ("rev-parse", "--verify", f"{revision}^{{commit}}"),
        )
        .decode("ascii")
        .strip()
    )
    if resolved_revision != revision:
        raise SystemImpactCheckError("accept requires one exact full commit ID")
    ancestry = subprocess.run(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            check.baseline.revision or check.baseline.base_revision,
            revision,
        ),
        cwd=root,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestry.returncode != 0:
        raise SystemImpactCheckError(
            "accepted commit does not descend from the checked baseline"
        )

    source_sha256 = _snapshot_source_sha256(root, revision)
    if source_sha256 != check.realized.source_sha256:
        raise SystemImpactCheckError(
            "accepted commit source differs from the checked candidate"
        )
    plan_sha256, committed_targets = _committed_plan(
        root=root,
        revision=revision,
        contracts=check.contracts,
        block_ids=check.blocks,
    )
    if plan_sha256 != check.plan_sha256:
        raise SystemImpactCheckError(
            "accepted commit plan differs from the checked PairBlocks"
        )
    checked_targets = tuple(
        sorted(
            (
                target.resolved.target.block_id,
                target.resolved.target.target.path,
                target.resolved.target.target.symbol,
            )
            for target in check.targets
        )
    )
    expected_targets = tuple(
        sorted(
            (target.block_id, target.target.path, target.target.symbol)
            for target in committed_targets
        )
    )
    if checked_targets != expected_targets:
        raise SystemImpactCheckError(
            "accepted PlanCheck does not cover every committed ContractTarget"
        )

    check_sha256 = _sha256(_canonical_json(check.model_dump(mode="json")))
    return Acceptance(check=check_sha256, revision=revision)


__all__ = ["SystemImpactCheckError", "accept", "check_plan"]
