"""Verify canonical System Impact source-analysis records."""

from viper.system_impact import (
    CodeQLIdentity,
    CodeQLReceipt,
    SourceEdge,
    SourceGraph,
    SourceNode,
    SourceSnapshot,
)


def test_source_graph_is_canonical() -> None:
    """Canonicalize row order into byte-identical source-graph JSON."""
    revision = "1" * 40
    snapshot = SourceSnapshot(
        base_revision=revision,
        source_sha256="2" * 64,
        revision=revision,
    )
    identity = CodeQLIdentity(
        version="2.26.4",
        platform="osx64",
        bundle_sha256="3" * 64,
        pack="viper/python-impact@1.0.0",
        pack_sha256="4" * 64,
    )
    receipt = CodeQLReceipt(
        snapshot=snapshot,
        command=("codeql", "query", "run"),
        exit_code=0,
        database_sha256="5" * 64,
        result_sha256="6" * 64,
        stderr_sha256="7" * 64,
    )
    dependency = SourceNode(
        node_id="src/viper/models.py:ArtifactRef",
        path="src/viper/models.py",
        symbol="ArtifactRef",
        kind="class",
        start_line=4,
        start_col=0,
        end_line=6,
        end_col=14,
        sha256="8" * 64,
    )
    dependent = SourceNode(
        node_id="src/viper/storage.py:LocalArtifactStore.load",
        path="src/viper/storage.py",
        symbol="LocalArtifactStore.load",
        kind="method",
        start_line=4,
        start_col=4,
        end_line=5,
        end_col=36,
        sha256="9" * 64,
    )
    reads = SourceEdge(
        edge_id="a" * 64,
        source=dependent.node_id,
        target=dependency.node_id,
        kind="reads",
        query="viper/python-impact/reads",
        path=dependent.path,
        line=5,
    )
    constructs = SourceEdge(
        edge_id="b" * 64,
        source=dependent.node_id,
        target=dependency.node_id,
        kind="constructs",
        query="viper/python-impact/constructs",
        path=dependent.path,
        line=5,
    )

    forward = SourceGraph(
        snapshot=snapshot,
        identity=identity,
        nodes=(dependency, dependent),
        edges=(reads, constructs),
        receipt=receipt,
    )
    reversed_rows = SourceGraph(
        snapshot=snapshot,
        identity=identity,
        nodes=(dependent, dependency),
        edges=(constructs, reads),
        receipt=receipt,
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
