"""Present one-hop source dependencies as joined, agent-readable evidence."""

from __future__ import annotations

import heapq
import math
from typing import Literal

from pydantic import Field

from viper._contract_traceability import RepoSymbolRef
from viper._schema import SHA256, NonEmptyStr, ProtocolModel

from .models import EdgeKind, OneHop, PlanCheck, SourceEdge, SourceGraph

DependencyState = Literal["unchanged", "added", "removed"]

_EDGE_WEIGHTS: dict[EdgeKind, float] = {
    "calls": 6.0,
    "constructs": 6.0,
    "inherits": 5.0,
    "writes": 5.0,
    "reads": 4.0,
    "imports": 3.0,
}


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


class ImpactPathStep(ProtocolModel):
    """Describe one dependency edge traversed from a target to its dependent."""

    edge_id: SHA256 = Field(description="SourceEdge supporting this path step.")
    target: RepoSymbolRef = Field(description="Declaration consumed at this path step.")
    dependent: RepoSymbolRef = Field(
        description="Declaration reached by following the dependency backward."
    )
    kind: EdgeKind = Field(description="Operation connecting both declarations.")
    use_path: NonEmptyStr = Field(
        description="Repository-relative source path containing the operation."
    )
    use_line: int = Field(
        ge=1,
        description="One-based source line containing the operation.",
    )
    query: NonEmptyStr = Field(
        description="CodeQL query that observed the dependency operation."
    )


class RankedImpactPath(ProtocolModel):
    """Rank one candidate declaration by its dependency path from a target."""

    candidate: RepoSymbolRef = Field(
        description="Declaration selected for agent inspection."
    )
    score: float = Field(
        description="Deterministic advisory relevance score for this path."
    )
    depth: int = Field(
        ge=1,
        description="Number of dependency edges from the target to the candidate.",
    )
    candidate_is_test: bool = Field(
        description="Whether the candidate lies beneath a test directory."
    )
    steps: tuple[ImpactPathStep, ...] = Field(
        min_length=1,
        description="Ordered dependency edges from the target to the candidate.",
    )
    reason: NonEmptyStr = Field(
        description="Compact explanation of the score-bearing path properties."
    )


class ImpactPathSearch(ProtocolModel):
    """Report one bounded ranked traversal over a baseline source graph."""

    targets: tuple[RepoSymbolRef, ...] = Field(
        description="Baseline declarations used as traversal seeds."
    )
    unranked_targets: tuple[NonEmptyStr, ...] = Field(
        description="Requested declarations absent from the baseline graph."
    )
    max_depth: int = Field(
        ge=1, description="Maximum dependency edges allowed in one returned path."
    )
    limit: int = Field(
        ge=1, description="Maximum ranked candidate paths returned to the caller."
    )
    expansion_budget: int = Field(
        ge=1, description="Maximum partial paths removed from the search frontier."
    )
    expansions: int = Field(
        ge=0, description="Partial paths removed from the frontier during this search."
    )
    truncated: bool = Field(
        description="Whether the expansion budget or result limit omitted candidates."
    )
    paths: tuple[RankedImpactPath, ...] = Field(
        description="Highest-ranked candidate paths in deterministic order."
    )


def _is_test_path(path: str) -> bool:
    """Return whether a repository path lies beneath its root test directory."""
    parts = path.split("/")
    return parts[0] in {"test", "tests"}


def _candidate_role_bonus(path: str) -> float:
    """Prioritize primary source, then root tests, over auxiliary Python trees."""
    if path.startswith("src/"):
        return 2.0
    if _is_test_path(path):
        return 0.5
    return 0.0


def _rank_score(
    edges: tuple[SourceEdge, ...],
    *,
    nodes: dict[str, RepoSymbolRef],
    incoming_counts: dict[str, int],
) -> float:
    """Score one path by edge strength, depth, fanout, and test evidence."""
    edge_score = sum(
        _EDGE_WEIGHTS[edge.kind] / (2**index) for index, edge in enumerate(edges)
    )
    depth_penalty = 4.0 * (len(edges) - 1)
    fanout_penalty = sum(
        math.log2(1 + incoming_counts.get(edge.source, 0)) / (2**index)
        for index, edge in enumerate(edges[:-1], start=1)
    )
    candidate = nodes[edges[-1].source]
    role_bonus = _candidate_role_bonus(candidate.path)
    return round(edge_score - depth_penalty - fanout_penalty + role_bonus, 6)


def _path_reason(edges: tuple[SourceEdge, ...], *, candidate_is_test: bool) -> str:
    """Explain the visible properties used to rank one dependency path."""
    kinds = " -> ".join(edge.kind for edge in edges)
    candidate = edges[-1].source
    suffix = "; test candidate" if candidate_is_test else ""
    if candidate.startswith("src/"):
        suffix = "; primary source candidate"
    return f"{len(edges)}-hop {kinds} path{suffix}"


def _ranked_path(
    edges: tuple[SourceEdge, ...],
    *,
    nodes: dict[str, RepoSymbolRef],
    incoming_counts: dict[str, int],
) -> RankedImpactPath:
    """Convert one internal edge path into agent-readable evidence."""
    candidate = nodes[edges[-1].source]
    candidate_is_test = _is_test_path(candidate.path)
    return RankedImpactPath(
        candidate=candidate,
        score=_rank_score(edges, nodes=nodes, incoming_counts=incoming_counts),
        depth=len(edges),
        candidate_is_test=candidate_is_test,
        steps=tuple(
            ImpactPathStep(
                edge_id=edge.edge_id,
                target=nodes[edge.target],
                dependent=nodes[edge.source],
                kind=edge.kind,
                use_path=edge.path,
                use_line=edge.line,
                query=edge.query,
            )
            for edge in edges
        ),
        reason=_path_reason(edges, candidate_is_test=candidate_is_test),
    )


def rank_impact_paths(
    *,
    graph: SourceGraph,
    targets: tuple[str, ...],
    max_depth: int = 3,
    limit: int = 12,
    expansion_budget: int = 500,
) -> ImpactPathSearch:
    """Rank bounded reverse-dependency paths from baseline declarations."""
    if not targets or len(targets) != len(set(targets)):
        raise ValueError("targets must contain unique source declarations")
    if not 1 <= max_depth <= 5:
        raise ValueError("max_depth must be between 1 and 5")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if not 1 <= expansion_budget <= 5000:
        raise ValueError("expansion_budget must be between 1 and 5000")

    nodes = {
        node.node_id: RepoSymbolRef(path=node.path, symbol=node.symbol)
        for node in graph.nodes
    }
    resolved_ids = tuple(sorted(set(targets) & nodes.keys()))
    unranked = tuple(sorted(set(targets) - nodes.keys()))
    incoming: dict[str, list[SourceEdge]] = {}
    for edge in graph.edges:
        incoming.setdefault(edge.target, []).append(edge)
    for edges in incoming.values():
        edges.sort(key=lambda edge: edge.edge_id)
    incoming_counts = {node_id: len(edges) for node_id, edges in incoming.items()}

    frontier: list[
        tuple[float, int, tuple[str, ...], tuple[SourceEdge, ...], tuple[str, ...]]
    ] = []
    for target in resolved_ids:
        for edge in incoming.get(target, ()):
            path = (edge,)
            score = _rank_score(path, nodes=nodes, incoming_counts=incoming_counts)
            heapq.heappush(
                frontier,
                (-score, 1, (edge.edge_id,), path, (target, edge.source)),
            )

    best: dict[str, RankedImpactPath] = {}
    expansions = 0
    while frontier and expansions < expansion_budget:
        _priority, depth, edge_ids, edges, path_nodes = heapq.heappop(frontier)
        expansions += 1
        ranked = _ranked_path(edges, nodes=nodes, incoming_counts=incoming_counts)
        candidate_id = edges[-1].source
        current = best.get(candidate_id)
        if current is None or (-ranked.score, edge_ids) < (
            -current.score,
            tuple(step.edge_id for step in current.steps),
        ):
            best[candidate_id] = ranked
        if depth == max_depth:
            continue
        for edge in incoming.get(candidate_id, ()):
            if edge.source in path_nodes:
                continue
            next_edges = (*edges, edge)
            next_ids = (*edge_ids, edge.edge_id)
            score = _rank_score(
                next_edges,
                nodes=nodes,
                incoming_counts=incoming_counts,
            )
            heapq.heappush(
                frontier,
                (
                    -score,
                    depth + 1,
                    next_ids,
                    next_edges,
                    (*path_nodes, edge.source),
                ),
            )

    ordered = tuple(
        sorted(
            best.values(),
            key=lambda item: (
                -item.score,
                item.depth,
                item.candidate.path,
                item.candidate.symbol,
                tuple(step.edge_id for step in item.steps),
            ),
        )
    )
    return ImpactPathSearch(
        targets=tuple(nodes[target] for target in resolved_ids),
        unranked_targets=unranked,
        max_depth=max_depth,
        limit=limit,
        expansion_budget=expansion_budget,
        expansions=expansions,
        truncated=bool(frontier) or len(ordered) > limit,
        paths=ordered[:limit],
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


def explain_source_comparison(
    *,
    baseline: SourceGraph,
    realized: SourceGraph,
    targets: tuple[str, ...],
) -> tuple[DependencyEvidence, ...]:
    """Return every direct dependency around explicit source targets."""
    requested = set(targets)
    if not targets or len(requested) != len(targets):
        raise ValueError("targets must contain unique source declarations")
    if baseline.snapshot.revision is None:
        raise ValueError("baseline SourceGraph must identify an exact revision")
    if realized.snapshot.base_revision != baseline.snapshot.revision:
        raise ValueError("realized SourceGraph does not derive from the baseline")
    if baseline.receipt.database.extraction != realized.receipt.database.extraction:
        raise ValueError("source graphs use different CodeQL extraction settings")
    if baseline.receipt.query.query != realized.receipt.query.query:
        raise ValueError("source graphs use different CodeQL query settings")
    if baseline.receipt.graph.format != realized.receipt.graph.format:
        raise ValueError("source graphs use different lowering formats")

    known = {node.node_id for graph in (baseline, realized) for node in graph.nodes}
    missing = requested - known
    if missing:
        raise ValueError(f"requested targets are absent: {sorted(missing)!r}")

    before = tuple(
        sorted(edge.edge_id for edge in baseline.edges if edge.target in requested)
    )
    after = tuple(
        sorted(edge.edge_id for edge in realized.edges if edge.target in requested)
    )
    before_ids = set(before)
    after_ids = set(after)
    selected = before_ids | after_ids
    edges = {
        edge.edge_id: edge
        for graph in (baseline, realized)
        for edge in graph.edges
        if edge.edge_id in selected
    }
    neighbors = tuple(sorted({edge.source for edge in edges.values()}))
    one_hop = OneHop(
        targets=tuple(sorted(requested)),
        neighbors=neighbors,
        changed=tuple(sorted(_changed_nodes(baseline, realized, set(neighbors)))),
        before=before,
        after=after,
        removed=tuple(sorted(before_ids - after_ids)),
        added=tuple(sorted(after_ids - before_ids)),
    )
    return explain_one_hop(
        baseline=baseline,
        realized=realized,
        one_hop=one_hop,
    )


__all__ = [
    "DependencyEvidence",
    "DependencyState",
    "ImpactPathSearch",
    "ImpactPathStep",
    "RankedImpactPath",
    "explain_one_hop",
    "explain_plan_check",
    "explain_source_comparison",
    "rank_impact_paths",
]
