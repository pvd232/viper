"""Resolve authored ContractTargets against a baseline source graph."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlockId,
)
from .._system_impact.source import classify_target_change, extract_declaration_bytes
from .models import (
    EdgeKind,
    Impact,
    PlanInspection,
    ResolvedContractTarget,
    SourceGraph,
    SourceNode,
)

IMPACT_EDGE_KINDS_V1: dict[str, frozenset[EdgeKind]] = {
    "satisfied": frozenset(),
    "added": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
    "removed": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
    "callable_interface_changed": frozenset({"calls", "constructs"}),
    "type_interface_changed": frozenset({"constructs", "inherits", "reads", "writes"}),
    "implementation_changed": frozenset({"calls", "reads"}),
    "unclassified": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
}


class PlanInspectionError(ValueError):
    """Report an absent, duplicate, stale, or impossible selected target."""


def _node_index(graph: SourceGraph) -> dict[tuple[str, str], SourceNode]:
    index: dict[tuple[str, str], SourceNode] = {}
    for node in graph.nodes:
        key = (node.path, node.symbol)
        if key in index:
            raise PlanInspectionError(f"duplicate source declaration: {key!r}")
        index[key] = node
    return index


def _payload(plan_root: Path, target: ContractTarget) -> bytes | None:
    if target.action == "remove":
        return None
    path = plan_root / target.declaration.path
    source = path.read_bytes()
    opening = b"```python contract-target\n"
    closing = b"\n```"
    candidates: list[bytes] = []
    cursor = 0
    while True:
        start = source.find(opening, cursor)
        if start < 0:
            break
        end = source.find(closing, start + len(opening))
        if end < 0:
            break
        fence_end = end + len(closing)
        fence = source[start:fence_end]
        if (
            source.count(b"\n", 0, start) + 1 == target.declaration.start_line
            and source.count(b"\n", 0, fence_end) + 1 == target.declaration.end_line
            and hashlib.sha256(fence).hexdigest() == target.declaration.sha256
        ):
            candidates.append(source[start + len(opening) : end])
        cursor = fence_end
    if len(candidates) != 1:
        raise PlanInspectionError(
            "cannot reconstruct target payload for "
            f"{target.target.path}:{target.target.symbol}"
        )
    return extract_declaration_bytes(candidates[0], target.target.symbol)


def inspect_plan(
    *,
    plan_root: Path,
    baseline_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
) -> PlanInspection:
    """Resolve selected targets and return policy-selected incoming edges."""
    if not block_ids or len(block_ids) != len(set(block_ids)):
        raise PlanInspectionError("block_ids must contain unique selected PairBlocks")
    known_blocks = {block.block_id for block in traceability.blocks}
    missing = sorted(set(block_ids) - known_blocks)
    if missing:
        raise PlanInspectionError(f"selected PairBlocks are absent: {missing}")

    selected = set(block_ids)
    targets = tuple(
        sorted(
            (target for target in traceability.targets if target.block_id in selected),
            key=lambda item: (item.block_id, item.target.path, item.target.symbol),
        )
    )
    nodes = _node_index(baseline)
    resolved: list[ResolvedContractTarget] = []
    impacted_edges = {}
    target_ids: set[str] = set()
    for target in targets:
        key = (target.target.path, target.target.symbol)
        baseline_node = nodes.get(key)
        before = None
        if baseline_node is not None:
            source = (baseline_root / baseline_node.path).read_bytes()
            before = extract_declaration_bytes(source, baseline_node.symbol)
            if hashlib.sha256(before).hexdigest() != baseline_node.sha256:
                raise PlanInspectionError(f"baseline digest is stale for {key!r}")
        expected = _payload(plan_root, target)
        change_kind = classify_target_change(
            action=target.action,
            baseline=before,
            expected=expected,
        )
        item = ResolvedContractTarget(
            target=target,
            baseline_node=None if baseline_node is None else baseline_node.node_id,
            baseline_sha256=None if baseline_node is None else baseline_node.sha256,
            expected_sha256=None
            if expected is None
            else hashlib.sha256(expected).hexdigest(),
            change_kind=change_kind,
        )
        resolved.append(item)
        if baseline_node is None:
            continue
        target_ids.add(baseline_node.node_id)
        permitted = IMPACT_EDGE_KINDS_V1[change_kind]
        for edge in baseline.edges:
            if edge.target == baseline_node.node_id and edge.kind in permitted:
                impacted_edges[edge.edge_id] = edge

    edges = tuple(sorted(impacted_edges.values(), key=lambda edge: edge.edge_id))
    return PlanInspection(
        targets=tuple(resolved),
        impact=Impact(
            baseline=baseline.snapshot,
            targets=tuple(sorted(target_ids)),
            affected=tuple(sorted({edge.source for edge in edges})),
            edges=tuple(edge.edge_id for edge in edges),
        ),
    )


__all__ = ["IMPACT_EDGE_KINDS_V1", "PlanInspectionError", "inspect_plan"]
