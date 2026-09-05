"""Present one-hop source dependencies as joined, agent-readable evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from viper._contract_traceability import RepoSymbolRef
from viper._schema import SHA256, NonEmptyStr, ProtocolModel

from .models import EdgeKind, OneHop, PlanCheck, SourceEdge, SourceGraph

DependencyState = Literal["unchanged", "added", "removed"]


class DependencyEvidence(ProtocolModel):
    """Describe one direct dependency occurrence across two source graphs."""

    edge_id: SHA256 = Field(
        description="SourceEdge identifier supporting this dependency occurrence."
    )
    target: RepoSymbolRef = Field(
        description="Declaration consumed by the dependent declaration."
    )
    dependent: RepoSymbolRef = Field(
        description="Declaration that contains the dependency occurrence."
    )
    kind: EdgeKind = Field(description="Operation connecting dependent to target.")
    use_path: NonEmptyStr = Field(
        description="Repository-relative source path containing the operation."
    )
    use_line: int = Field(
        ge=1,
        description="One-based source line containing the operation.",
    )
    query: NonEmptyStr = Field(
        description="CodeQL query that observed the dependency occurrence."
    )
    state: DependencyState = Field(
        description="Whether the occurrence is unchanged, added, or removed."
    )
    dependent_changed: bool = Field(
        description="Whether the dependent declaration changed between the graphs."
    )


def _edge_index(graph: SourceGraph) -> dict[str, SourceEdge]:
    """Index one validated graph's edges by identifier."""
    return {edge.edge_id: edge for edge in graph.edges}


def _node_refs(
    baseline: SourceGraph,
    realized: SourceGraph,
) -> dict[str, RepoSymbolRef]:
    """Join stable node identifiers to path-and-symbol references."""
    refs: dict[str, RepoSymbolRef] = {}
    for graph in (baseline, realized):
        for node in graph.nodes:
            ref = RepoSymbolRef(path=node.path, symbol=node.symbol)
            existing = refs.get(node.node_id)
            if existing is not None and existing != ref:
                raise ValueError(
                    f"node ID identifies different declarations: {node.node_id!r}"
                )
            refs[node.node_id] = ref
    return refs


def _changed_nodes(
    baseline: SourceGraph,
    realized: SourceGraph,
    neighbors: set[str],
) -> set[str]:
    """Derive changed neighbor IDs from declaration presence and digests."""
    before = {node.node_id: node for node in baseline.nodes}
    after = {node.node_id: node for node in realized.nodes}
    return {
        node_id
        for node_id in neighbors
        if before.get(node_id) is None
        or after.get(node_id) is None
        or before[node_id].sha256 != after[node_id].sha256
    }


def explain_one_hop(
    *,
    baseline: SourceGraph,
    realized: SourceGraph,
    one_hop: OneHop,
) -> tuple[DependencyEvidence, ...]:
    """Join a one-hop delta to declarations, operations, and source locations."""
    before = _edge_index(baseline)
    after = _edge_index(realized)
    before_ids = set(one_hop.before)
    after_ids = set(one_hop.after)
    missing_before = before_ids - before.keys()
    missing_after = after_ids - after.keys()
    if missing_before or missing_after:
        raise ValueError(
            "OneHop references absent SourceEdges: "
            f"before={sorted(missing_before)!r}, after={sorted(missing_after)!r}"
        )
    if set(one_hop.removed) != before_ids - after_ids:
        raise ValueError("OneHop.removed differs from before - after")
    if set(one_hop.added) != after_ids - before_ids:
        raise ValueError("OneHop.added differs from after - before")

    refs = _node_refs(baseline, realized)
    selected_edges: dict[str, SourceEdge] = {}
    for edge_id in sorted(before_ids | after_ids):
        baseline_edge = before.get(edge_id)
        realized_edge = after.get(edge_id)
        if (
            baseline_edge is not None
            and realized_edge is not None
            and baseline_edge != realized_edge
        ):
            raise ValueError(f"edge ID identifies different edges: {edge_id!r}")
        if realized_edge is not None:
            selected_edges[edge_id] = realized_edge
        elif baseline_edge is not None:
            selected_edges[edge_id] = baseline_edge
        else:
            raise ValueError(f"selected edge is absent from both graphs: {edge_id!r}")

    targets = set(one_hop.targets)
    neighbors = set(one_hop.neighbors)
    missing_targets = targets - refs.keys()
    if missing_targets:
        raise ValueError(
            f"OneHop references absent target declarations: {sorted(missing_targets)!r}"
        )
    if any(edge.target not in targets for edge in selected_edges.values()):
        raise ValueError("OneHop contains an edge outside its target declarations")
    derived_neighbors = {edge.source for edge in selected_edges.values()}
    if neighbors != derived_neighbors:
        raise ValueError("OneHop.neighbors differs from its selected SourceEdges")
    if set(one_hop.changed) != _changed_nodes(baseline, realized, neighbors):
        raise ValueError("OneHop.changed differs from its source declarations")

    evidence: list[DependencyEvidence] = []
    for edge_id, edge in selected_edges.items():
        try:
            target = refs[edge.target]
            dependent = refs[edge.source]
        except KeyError as error:
            raise ValueError(
                f"SourceEdge references an absent declaration: {error.args[0]!r}"
            ) from error
        state: DependencyState
        if edge_id in before_ids and edge_id in after_ids:
            state = "unchanged"
        elif edge_id in after_ids:
            state = "added"
        else:
            state = "removed"
        evidence.append(
            DependencyEvidence(
                edge_id=edge_id,
                target=target,
                dependent=dependent,
                kind=edge.kind,
                use_path=edge.path,
                use_line=edge.line,
                query=edge.query,
                state=state,
                dependent_changed=edge.source in one_hop.changed,
            )
        )

    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.dependent.path,
                item.dependent.symbol,
                item.target.path,
                item.target.symbol,
                item.kind,
                item.use_path,
                item.use_line,
                item.state,
                item.edge_id,
            ),
        )
    )


def explain_plan_check(
    *,
    check: PlanCheck,
    baseline: SourceGraph,
    realized: SourceGraph,
    targets: tuple[str, ...] = (),
) -> tuple[DependencyEvidence, ...]:
    """Return verified one-hop evidence from one persisted plan check."""
    if not check.receipts_valid:
        raise ValueError("PlanCheck does not attest valid source-graph receipts")
    if baseline.snapshot != check.baseline:
        raise ValueError("baseline SourceGraph snapshot differs from PlanCheck")
    if realized.snapshot != check.realized:
        raise ValueError("realized SourceGraph snapshot differs from PlanCheck")

    requested = set(targets)
    if len(requested) != len(targets):
        raise ValueError("requested targets contain duplicates")
    selected = set(check.one_hop.targets)
    missing = requested - selected
    if missing:
        raise ValueError(
            f"requested targets are absent from PlanCheck.one_hop: {sorted(missing)!r}"
        )

    evidence = explain_one_hop(
        baseline=baseline,
        realized=realized,
        one_hop=check.one_hop,
    )
    if not requested:
        return evidence
    return tuple(
        item
        for item in evidence
        if f"{item.target.path}:{item.target.symbol}" in requested
    )


__all__ = [
    "DependencyEvidence",
    "DependencyState",
    "explain_one_hop",
    "explain_plan_check",
]
