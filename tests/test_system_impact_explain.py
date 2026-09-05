"""Verify agent-readable joins over one-hop System Impact evidence."""

from __future__ import annotations

import pytest

from viper.system_impact.explain import explain_one_hop, explain_plan_check
from viper.system_impact.models import (
    OneHop,
    PlanCheck,
    SourceEdge,
    SourceGraph,
    SourceNode,
    SourceSnapshot,
)


def _node(path: str, symbol: str, *, sha256: str = "1" * 64) -> SourceNode:
    """Build one declaration for an explanation fixture."""
    return SourceNode(
        node_id=f"{path}:{symbol}",
        path=path,
        symbol=symbol,
        kind="function",
        binding_start_line=1,
        binding_start_col=0,
        binding_end_line=1,
        binding_end_col=1,
        start_line=1,
        start_col=0,
        end_line=1,
        end_col=1,
        sha256=sha256,
    )


def _edge(
    edge_id: str,
    *,
    source: SourceNode,
    target: SourceNode,
    line: int,
) -> SourceEdge:
    """Build one call occurrence for an explanation fixture."""
    return SourceEdge(
        edge_id=edge_id,
        source=source.node_id,
        target=target.node_id,
        kind="calls",
        query="viper/python-impact/dependencies",
        path=source.path,
        line=line,
    )


def _graph(
    nodes: tuple[SourceNode, ...],
    edges: tuple[SourceEdge, ...],
) -> SourceGraph:
    """Build the graph surface consumed by the pure explanation operation."""
    return SourceGraph.model_construct(nodes=nodes, edges=edges)


def test_explain_one_hop_joins_dependencies_and_source_locations() -> None:
    """Return readable unchanged, removed, and added dependency evidence."""
    target_before = _node("src/api.py", "parse", sha256="1" * 64)
    target_after = _node("src/api.py", "parse", sha256="2" * 64)
    stable = _node("src/command.py", "run")
    removed = _node("src/legacy.py", "load")
    added = _node("src/adapter.py", "adapt")
    unchanged_edge = _edge(
        "1" * 64,
        source=stable,
        target=target_before,
        line=14,
    )
    removed_edge = _edge(
        "2" * 64,
        source=removed,
        target=target_before,
        line=7,
    )
    added_edge = _edge(
        "3" * 64,
        source=added,
        target=target_after,
        line=9,
    )
    baseline = _graph(
        (target_before, stable, removed),
        (unchanged_edge, removed_edge),
    )
    realized = _graph(
        (target_after, stable, added),
        (unchanged_edge, added_edge),
    )
    one_hop = OneHop(
        targets=(target_before.node_id,),
        neighbors=(added.node_id, removed.node_id, stable.node_id),
        changed=(added.node_id, removed.node_id),
        before=(unchanged_edge.edge_id, removed_edge.edge_id),
        after=(unchanged_edge.edge_id, added_edge.edge_id),
        removed=(removed_edge.edge_id,),
        added=(added_edge.edge_id,),
    )

    result = explain_one_hop(
        baseline=baseline,
        realized=realized,
        one_hop=one_hop,
    )

    assert [item.dependent.symbol for item in result] == ["adapt", "run", "load"]
    assert [item.state for item in result] == ["added", "unchanged", "removed"]
    assert [item.dependent_changed for item in result] == [True, False, True]
    assert result[0].target.path == "src/api.py"
    assert result[0].kind == "calls"
    assert result[0].use_path == "src/adapter.py"
    assert result[0].use_line == 9


def test_explain_one_hop_rejects_an_absent_edge() -> None:
    """Reject a one-hop identifier that cannot be joined to its source graph."""
    one_hop = OneHop.model_construct(
        targets=(),
        neighbors=(),
        changed=(),
        before=("f" * 64,),
        after=(),
        removed=("f" * 64,),
        added=(),
    )

    with pytest.raises(ValueError, match="absent SourceEdges"):
        explain_one_hop(
            baseline=_graph((), ()),
            realized=_graph((), ()),
            one_hop=one_hop,
        )


def test_explain_one_hop_rejects_an_absent_target() -> None:
    """Reject a selected target that neither source graph identifies."""
    one_hop = OneHop(
        targets=("src/missing.py:target",),
        neighbors=(),
        changed=(),
        before=(),
        after=(),
        removed=(),
        added=(),
    )

    with pytest.raises(ValueError, match="absent target declarations"):
        explain_one_hop(
            baseline=_graph((), ()),
            realized=_graph((), ()),
            one_hop=one_hop,
        )


def test_explain_plan_check_binds_graphs_and_filters_targets() -> None:
    """Return requested evidence only after matching both checked snapshots."""
    baseline_snapshot = SourceSnapshot(
        base_revision="1" * 40,
        source_sha256="2" * 64,
        revision="1" * 40,
    )
    realized_snapshot = SourceSnapshot(
        base_revision="1" * 40,
        source_sha256="3" * 64,
        revision=None,
    )
    first_target = _node("src/api.py", "parse")
    second_target = _node("src/api.py", "render")
    first_dependent = _node("src/command.py", "run")
    second_dependent = _node("src/view.py", "show")
    first_edge = _edge(
        "4" * 64,
        source=first_dependent,
        target=first_target,
        line=12,
    )
    second_edge = _edge(
        "5" * 64,
        source=second_dependent,
        target=second_target,
        line=18,
    )
    baseline = SourceGraph.model_construct(
        snapshot=baseline_snapshot,
        nodes=(first_target, second_target, first_dependent, second_dependent),
        edges=(first_edge, second_edge),
    )
    realized = SourceGraph.model_construct(
        snapshot=realized_snapshot,
        nodes=(first_target, second_target, first_dependent, second_dependent),
        edges=(first_edge, second_edge),
    )
    one_hop = OneHop(
        targets=(first_target.node_id, second_target.node_id),
        neighbors=(first_dependent.node_id, second_dependent.node_id),
        changed=(),
        before=(first_edge.edge_id, second_edge.edge_id),
        after=(first_edge.edge_id, second_edge.edge_id),
        removed=(),
        added=(),
    )
    check = PlanCheck.model_construct(
        baseline=baseline_snapshot,
        realized=realized_snapshot,
        one_hop=one_hop,
        receipts_valid=True,
    )

    result = explain_plan_check(
        check=check,
        baseline=baseline,
        realized=realized,
        targets=(first_target.node_id,),
    )

    assert len(result) == 1
    assert result[0].target.symbol == "parse"
    assert result[0].dependent.symbol == "run"


def test_explain_plan_check_rejects_unverified_receipts() -> None:
    """Reject graph evidence when PlanCheck does not attest its receipts."""
    check = PlanCheck.model_construct(receipts_valid=False)

    with pytest.raises(ValueError, match="does not attest valid"):
        explain_plan_check(
            check=check,
            baseline=_graph((), ()),
            realized=_graph((), ()),
        )
