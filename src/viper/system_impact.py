"""Define public source-analysis records for System Impact checks."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from ._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath

CommitId = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
NodeId = NonEmptyStr
EdgeKind = Literal["imports", "calls", "constructs", "inherits", "reads", "writes"]


class CodeQLIdentity(ProtocolModel):
    """Fix the analyzer and query pack used for both source snapshots."""

    version: NonEmptyStr = Field(description="Required CodeQL CLI version.")
    platform: NonEmptyStr = Field(description="CodeQL bundle platform identifier.")
    bundle_sha256: SHA256 = Field(description="Digest of the installed CodeQL bundle.")
    pack: NonEmptyStr = Field(description="Name and version of the VIPER query pack.")
    pack_sha256: SHA256 = Field(description="Digest of the exact query-pack bytes.")


class SourceSnapshot(ProtocolModel):
    """Identify one immutable repository source tree."""

    base_revision: CommitId = Field(
        description="Committed baseline from which this source was derived."
    )
    source_sha256: SHA256 = Field(
        description="Digest of the complete analyzed source-file set and bytes."
    )
    revision: CommitId | None = Field(
        description="Exact commit when the snapshot is committed; otherwise absent."
    )


class CodeQLReceipt(ProtocolModel):
    """Record one completed source-analysis invocation."""

    snapshot: SourceSnapshot = Field(
        description="Immutable source snapshot analyzed by CodeQL."
    )
    command: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Exact analyzer argument vector.",
    )
    exit_code: int = Field(description="Terminal process exit code.")
    database_sha256: SHA256 = Field(
        description="Digest identifying the CodeQL database."
    )
    result_sha256: SHA256 = Field(description="Digest of the decoded canonical rows.")
    stderr_sha256: SHA256 = Field(
        description="Digest of captured standard error bytes."
    )


class SourceNode(ProtocolModel):
    """Identify one Python declaration observed in one source snapshot."""

    node_id: NodeId = Field(description="Stable path-and-symbol node identifier.")
    path: RepoRelPath = Field(description="Repository-relative Python source path.")
    symbol: NonEmptyStr = Field(description="Qualified Python symbol name.")
    kind: NonEmptyStr = Field(description="Observed Python declaration kind.")
    start_line: int = Field(
        ge=1,
        description="First source line of the declaration.",
    )
    start_col: int = Field(
        ge=0,
        description="UTF-8 byte offset on the first line.",
    )
    end_line: int = Field(
        ge=1,
        description="Final source line of the declaration.",
    )
    end_col: int = Field(
        ge=0,
        description="UTF-8 byte offset after the declaration.",
    )
    sha256: SHA256 = Field(description="Digest of the exact declaration bytes.")


class SourceEdge(ProtocolModel):
    """Record one source declaration's dependency on another declaration."""

    edge_id: SHA256 = Field(description="Digest of the complete edge identity.")
    source: NodeId = Field(description="Declaration that depends on the target.")
    target: NodeId = Field(description="Declaration consumed by the source.")
    kind: EdgeKind = Field(description="Observed dependency operation.")
    query: NonEmptyStr = Field(description="CodeQL query that emitted the edge.")
    path: NonEmptyStr = Field(
        description="Repository-relative path containing the use."
    )
    line: int = Field(
        ge=1,
        description="One-based source line containing the use.",
    )


class SourceGraph(ProtocolModel):
    """Store one canonical CodeQL observation of a source snapshot."""

    schema_version: Literal[1] = Field(
        default=1,
        description="Source-graph format version.",
    )
    snapshot: SourceSnapshot = Field(
        description="Immutable source snapshot represented by the graph."
    )
    identity: CodeQLIdentity = Field(
        description="Analyzer identity used for this graph."
    )
    nodes: tuple[SourceNode, ...] = Field(
        description="Nodes sorted by stable identifier."
    )
    edges: tuple[SourceEdge, ...] = Field(
        description="Edges sorted by stable identifier."
    )
    receipt: CodeQLReceipt = Field(
        description="Evidence for the completed analysis run."
    )

    @field_validator("nodes")
    @classmethod
    def order_nodes(cls, nodes: tuple[SourceNode, ...]) -> tuple[SourceNode, ...]:
        """Order nodes by their stable identifiers before serialization."""
        return tuple(sorted(nodes, key=lambda node: node.node_id))

    @field_validator("edges")
    @classmethod
    def order_edges(cls, edges: tuple[SourceEdge, ...]) -> tuple[SourceEdge, ...]:
        """Order edges by their stable identifiers before serialization."""
        return tuple(sorted(edges, key=lambda edge: edge.edge_id))


__all__ = [
    "CodeQLIdentity",
    "CodeQLReceipt",
    "CommitId",
    "EdgeKind",
    "NodeId",
    "SourceEdge",
    "SourceGraph",
    "SourceNode",
    "SourceSnapshot",
]
