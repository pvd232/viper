"""Check one selected PairBlock plan and bind it to an accepted commit."""

from __future__ import annotations

import hashlib
import json
import shlex
import tempfile
from pathlib import Path

from .. import _subprocess as subprocess
from .._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlock,
    PairBlockId,
    RepoSymbolRef,
    compile_contract_plan,
)
from ..system_impact import (
    Acceptance,
    CommitId,
    GateCheck,
    PlanCheck,
    ResolvedContractTarget,
    SourceGraph,
    SourceNode,
    TargetCheck,
    inspect_plan,
)
from .codeql import IGNORED_PARTS, source_digest
from .source import SourceDeclarationError, extract_declaration_bytes


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


def _declaration_payload(root: Path, target: ContractTarget) -> bytes | None:
    if target.action == "remove":
        return None

    path = root / target.declaration.path
    try:
        source = path.read_bytes()
    except OSError as error:
        raise SystemImpactCheckError(
            f"cannot read ContractTarget declaration: {target.declaration.path}"
        ) from error

    opening = b"```python contract-target\n"
    closing = b"\n```"
    candidates: list[bytes] = []
    position = 0
    while True:
        start = source.find(opening, position)
        if start < 0:
            break
        end = source.find(closing, start + len(opening))
        if end < 0:
            break
        declaration_end = end + len(closing)
        declaration = source[start:declaration_end]
        start_line = source.count(b"\n", 0, start) + 1
        end_line = source.count(b"\n", 0, declaration_end) + 1
        if (
            start_line == target.declaration.start_line
            and end_line == target.declaration.end_line
            and _sha256(declaration) == target.declaration.sha256
        ):
            candidates.append(source[start + len(opening) : end])
        position = declaration_end

    if len(candidates) != 1:
        raise SystemImpactCheckError(
            "ContractTarget declaration cannot be reconstructed exactly: "
            f"{target.block_id} {target.target.path}:{target.target.symbol}"
        )
    try:
        return extract_declaration_bytes(candidates[0], target.target.symbol)
    except SourceDeclarationError as error:
        raise SystemImpactCheckError(
            "ContractTarget payload does not resolve its declared symbol: "
            f"{target.target.path}:{target.target.symbol}"
        ) from error


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
        completed = subprocess.run(  # noqa: S603
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
            passed = after is not None and after.sha256 == resolved.expected_sha256
            if after is None:
                message = "required target declaration is absent"
            elif passed:
                message = "target declaration matches the authored bytes"
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
    baseline_nodes: dict[tuple[str, str], SourceNode],
    realized_nodes: dict[tuple[str, str], SourceNode],
    targets: tuple[ContractTarget, ...],
) -> tuple[RepoSymbolRef, ...]:
    changed = {
        key
        for key in baseline_nodes.keys() | realized_nodes.keys()
        if (
            baseline_nodes.get(key) is None
            or realized_nodes.get(key) is None
            or baseline_nodes[key].sha256 != realized_nodes[key].sha256
        )
    }
    all_nodes = {**baseline_nodes, **realized_nodes}
    planned: set[tuple[str, str]] = set()
    for target in targets:
        target_key = _target_key(target)
        planned.add(target_key)
        target_node = all_nodes.get(target_key)
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
        resolved_targets=inspection.targets,
        realized_nodes=realized_nodes,
    )
    unexpected = _unexpected_changes(
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
    completed = subprocess.run(  # noqa: S603
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
    ancestry = subprocess.run(  # noqa: S603
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
