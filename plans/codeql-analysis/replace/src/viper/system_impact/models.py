"""Define public records for System Impact checks."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .._contract_traceability import (
    ContractTarget,
    PairBlockId,
    RepoSymbolRef,
)
from .._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath

CommitId = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
NodeId = NonEmptyStr
EdgeKind = Literal["imports", "calls", "constructs", "inherits", "reads", "writes"]
SourceNodeKind = Literal["function", "method", "class", "assignment", "import"]
ChangeKind = Literal[
    "satisfied",
    "added",
    "removed",
    "callable_interface_changed",
    "type_interface_changed",
    "implementation_changed",
    "unclassified",
]
CheckState = Literal["passed", "failed"]


def _hash_parts(parts: tuple[bytes, ...]) -> str:
    """Hash a sequence without allowing adjacent values to blur together."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    """Serialize a stage input for a stable cache key."""
    model_dump = getattr(value, "model_dump", None)
    payload = model_dump(mode="json") if model_dump is not None else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def stage_key(*values: object) -> str:
    """Hash the exact inputs consumed by one analysis stage."""
    return _hash_parts(tuple(_canonical_bytes(value) for value in values))


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


class CodeQLExtractionSpec(ProtocolModel):
    """Identify the CodeQL installation and extraction mode."""

    version: NonEmptyStr = Field(description="CodeQL CLI version.")
    platform: NonEmptyStr = Field(description="CodeQL bundle platform.")
    executable_sha256: SHA256 = Field(description="Digest of the CodeQL executable.")
    extractor_sha256: SHA256 = Field(description="Digest of the Python extractor tree.")
    language: Literal["python"] = Field(
        default="python",
        description="Language extracted into the database.",
    )
    build_mode: Literal["none"] = Field(
        default="none",
        description="CodeQL database build mode.",
    )


class CodeQLQuerySpec(ProtocolModel):
    """Identify the query pack and suite executed against a database."""

    pack: NonEmptyStr = Field(description="Query-pack name and version.")
    pack_sha256: SHA256 = Field(description="Digest of the query-pack tree.")
    suite: NonEmptyStr = Field(description="Query suite selected from the pack.")


class SourceGraphFormat(ProtocolModel):
    """Identify the graph schema and CodeQL-row conversion rules."""

    schema_version: int = Field(
        ge=1,
        description="Serialized SourceGraph format version.",
    )
    lowering_sha256: SHA256 = Field(
        description=(
            "Digest of the explicit path-and-byte manifest for graph lowering."
        ),
    )


class DatabaseReceipt(ProtocolModel):
    """Record one completed source extraction."""

    snapshot: SourceSnapshot = Field(description="Source extracted by CodeQL.")
    extraction: CodeQLExtractionSpec = Field(description="Extraction settings used.")
    key: SHA256 = Field(description="Digest of the snapshot and extraction settings.")
    sha256: SHA256 = Field(description="Digest of the extracted database facts.")
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Commands executed to create the database.",
    )
    exit_code: Literal[0] = Field(
        default=0,
        description="Successful database-creation process exit code.",
    )
    stderr_sha256: SHA256 = Field(description="Digest of captured standard error.")

    @model_validator(mode="after")
    def validate_key(self) -> DatabaseReceipt:
        """Require the key derived from this receipt's stage inputs."""
        if self.key != stage_key(self.snapshot, self.extraction):
            raise ValueError("DatabaseReceipt key differs from its stage inputs")
        return self


class QueryReceipt(ProtocolModel):
    """Record one completed query-suite execution."""

    database_key: SHA256 = Field(description="Key of the database queried.")
    database_sha256: SHA256 = Field(description="Digest of that database's facts.")
    query: CodeQLQuerySpec = Field(description="Query pack and suite executed.")
    key: SHA256 = Field(description="Digest of the database and query specification.")
    sha256: SHA256 = Field(description="Digest of the suite's BQRS files.")
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Commands executed to produce the query results.",
    )
    exit_code: Literal[0] = Field(
        default=0,
        description="Successful query process exit code.",
    )
    stderr_sha256: SHA256 = Field(description="Digest of captured standard error.")

    @model_validator(mode="after")
    def validate_key(self) -> QueryReceipt:
        """Require the key derived from this receipt's stage inputs."""
        if self.key != stage_key(
            self.database_key,
            self.database_sha256,
            self.query,
        ):
            raise ValueError("QueryReceipt key differs from its stage inputs")
        return self


class GraphReceipt(ProtocolModel):
    """Record the conversion of query results into a source graph."""

    query_key: SHA256 = Field(description="Key of the query results converted.")
    query_sha256: SHA256 = Field(description="Digest of the suite's BQRS files.")
    format: SourceGraphFormat = Field(
        description="Graph schema and conversion rules used."
    )
    key: SHA256 = Field(description="Digest of the query results and graph format.")
    sha256: SHA256 = Field(
        description="Digest of the canonical SourceGraph nodes and edges."
    )
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Commands used to decode the query results.",
    )
    exit_code: Literal[0] = Field(
        default=0,
        description="Successful graph-conversion process exit code.",
    )
    stderr_sha256: SHA256 = Field(description="Digest of captured standard error.")

    @model_validator(mode="after")
    def validate_key(self) -> GraphReceipt:
        """Require the key derived from this receipt's stage inputs."""
        if self.key != stage_key(self.query_key, self.query_sha256, self.format):
            raise ValueError("GraphReceipt key differs from its stage inputs")
        return self


class CodeQLAnalysisReceipt(ProtocolModel):
    """Join the receipts for one complete CodeQL analysis."""

    database: DatabaseReceipt = Field(description="Database extraction evidence.")
    query: QueryReceipt = Field(description="Query execution evidence.")
    graph: GraphReceipt = Field(description="Graph conversion evidence.")

    @model_validator(mode="after")
    def validate_chain(self) -> CodeQLAnalysisReceipt:
        """Require each stage to consume the preceding stage's exact result."""
        if (
            self.query.database_key != self.database.key
            or self.query.database_sha256 != self.database.sha256
        ):
            raise ValueError("QueryReceipt does not consume DatabaseReceipt")
        if (
            self.graph.query_key != self.query.key
            or self.graph.query_sha256 != self.query.sha256
        ):
            raise ValueError("GraphReceipt does not consume QueryReceipt")
        return self


class SourceNode(ProtocolModel):
    """Identify one Python declaration observed in one source snapshot."""

    node_id: NodeId = Field(
        description="Stable path-and-symbol key assigned after uniqueness is proved."
    )
    path: RepoRelPath = Field(description="Repository-relative Python source path.")
    symbol: NonEmptyStr = Field(description="Qualified Python symbol name.")
    kind: SourceNodeKind = Field(description="Observed Python declaration kind.")
    binding_start_line: int = Field(
        ge=1,
        description="First line of the AST occurrence located by CodeQL.",
    )
    binding_start_col: int = Field(
        ge=0,
        description="UTF-8 byte offset of that occurrence on its first line.",
    )
    binding_end_line: int = Field(
        ge=1,
        description="Final line of the located AST occurrence.",
    )
    binding_end_col: int = Field(
        ge=0,
        description="UTF-8 byte offset after the located AST occurrence.",
    )
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

    @model_validator(mode="after")
    def validate_spans(self) -> SourceNode:
        """Require a nonempty binding inside its declaration."""
        binding_start = (self.binding_start_line, self.binding_start_col)
        binding_end = (self.binding_end_line, self.binding_end_col)
        declaration_start = (self.start_line, self.start_col)
        declaration_end = (self.end_line, self.end_col)

        if not (declaration_start <= binding_start < binding_end <= declaration_end):
            raise ValueError("SourceNode binding must lie inside its declaration")

        return self


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

    schema_version: Literal[3] = Field(
        default=3,
        description="Source-graph format version.",
    )
    snapshot: SourceSnapshot = Field(
        description="Immutable source snapshot represented by the graph."
    )
    nodes: tuple[SourceNode, ...] = Field(
        description="Nodes sorted by stable identifier."
    )
    edges: tuple[SourceEdge, ...] = Field(
        description="Edges sorted by stable identifier."
    )
    receipt: CodeQLAnalysisReceipt = Field(
        description="Evidence for extraction, query execution, and graph conversion."
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

    @model_validator(mode="after")
    def validate_graph(self) -> SourceGraph:
        """Reject duplicate identities, dangling edges, and receipt drift."""
        node_ids = tuple(node.node_id for node in self.nodes)
        target_keys = tuple((node.path, node.symbol) for node in self.nodes)
        occurrences = tuple(
            (
                node.path,
                node.binding_start_line,
                node.binding_start_col,
                node.binding_end_line,
                node.binding_end_col,
            )
            for node in self.nodes
        )
        edge_ids = tuple(edge.edge_id for edge in self.edges)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("SourceGraph contains duplicate node IDs")
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("SourceGraph contains an ambiguous source target")
        if len(occurrences) != len(set(occurrences)):
            raise ValueError("SourceGraph contains a duplicate binding occurrence")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("SourceGraph contains duplicate edge IDs")
        known = set(node_ids)
        if any(
            edge.source not in known or edge.target not in known for edge in self.edges
        ):
            raise ValueError("SourceGraph contains an edge with an unknown endpoint")
        database = self.receipt.database
        query = self.receipt.query
        graph = self.receipt.graph
        if database.snapshot != self.snapshot:
            raise ValueError(
                "DatabaseReceipt snapshot differs from SourceGraph snapshot"
            )
        if query.database_key != database.key:
            raise ValueError("QueryReceipt database key differs from DatabaseReceipt")
        if query.database_sha256 != database.sha256:
            raise ValueError(
                "QueryReceipt database digest differs from DatabaseReceipt"
            )
        if graph.query_key != query.key:
            raise ValueError("GraphReceipt query key differs from QueryReceipt")
        if graph.query_sha256 != query.sha256:
            raise ValueError("GraphReceipt query digest differs from QueryReceipt")
        if graph.format.schema_version != self.schema_version:
            raise ValueError(
                "SourceGraphFormat schema version differs from SourceGraph"
            )
        result_payload = json.dumps(
            {
                "nodes": [node.model_dump(mode="json") for node in self.nodes],
                "edges": [edge.model_dump(mode="json") for edge in self.edges],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if hashlib.sha256(result_payload).hexdigest() != graph.sha256:
            raise ValueError("GraphReceipt digest differs from SourceGraph rows")
        return self


class Impact(ProtocolModel):
    """Report direct baseline dependents selected by policy version 1."""

    policy_version: Literal[1] = Field(
        default=1,
        description="Change-kind-to-edge-kind policy version used for this report.",
    )
    baseline: SourceSnapshot = Field(
        description="Baseline source snapshot whose direct edges were inspected."
    )
    targets: tuple[NodeId, ...] = Field(
        description="Existing baseline nodes resolved from the selected targets."
    )
    affected: tuple[NodeId, ...] = Field(
        description="Unique direct dependents selected by the impact policy."
    )
    edges: tuple[SHA256, ...] = Field(
        description="SourceEdge identifiers that support the affected-node report."
    )


class ResolvedContractTarget(ProtocolModel):
    """Bind one authored target to baseline and expected declaration bytes."""

    target: ContractTarget = Field(description="Selected CTG target being resolved.")
    baseline_node: NodeId | None = Field(
        description="Resolved baseline node identifier, or absent for an addition."
    )
    baseline_sha256: SHA256 | None = Field(
        description="Baseline declaration digest, or absent for an addition."
    )
    expected_sha256: SHA256 | None = Field(
        description="Authored declaration digest, or absent for a removal."
    )
    change_kind: ChangeKind = Field(
        description="Planned transition used to select direct dependency edges."
    )


class TargetCheck(ProtocolModel):
    """Record whether one realized declaration matches its authored target."""

    resolved: ResolvedContractTarget = Field(
        description="Authored target resolved against the baseline source graph."
    )
    after_sha256: SHA256 | None = Field(
        description=(
            "Realized declaration digest, or absent when no declaration remains."
        )
    )
    state: CheckState = Field(
        description="Whether the realized declaration has the required target state."
    )
    message: NonEmptyStr = Field(description="Specific reason for the target result.")


class GateCheck(ProtocolModel):
    """Record one selected PairBlock gate invocation."""

    block_id: PairBlockId = Field(
        description="Selected PairBlock whose frozen gate was executed."
    )
    command: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Exact argument vector executed without a command shell.",
    )
    exit_code: int = Field(description="Terminal process exit code.")
    stdout_sha256: SHA256 = Field(
        description="Digest of the gate's captured standard output bytes."
    )
    stderr_sha256: SHA256 = Field(
        description="Digest of the gate's captured standard error bytes."
    )


class OneHop(ProtocolModel):
    """Store the CodeQL edge delta around the selected targets."""

    targets: tuple[NodeId, ...] = Field(
        description="Selected target nodes present in either graph."
    )
    neighbors: tuple[NodeId, ...] = Field(
        description="Direct dependents found before or after the planned change."
    )
    changed: tuple[NodeId, ...] = Field(
        description="Direct dependents whose declaration state changed."
    )
    before: tuple[SHA256, ...] = Field(
        description="Policy-selected incoming edge IDs in the baseline graph."
    )
    after: tuple[SHA256, ...] = Field(
        description="Incoming edge IDs derived from the materialized PairBlocks."
    )
    removed: tuple[SHA256, ...] = Field(
        description="Baseline edge IDs absent after materialization."
    )
    added: tuple[SHA256, ...] = Field(
        description="Materialized edge IDs absent from the baseline."
    )

    @model_validator(mode="after")
    def validate_delta(self) -> OneHop:
        """Require added and removed edges to equal the graph difference."""
        before = set(self.before)
        after = set(self.after)
        if self.removed != tuple(sorted(before - after)):
            raise ValueError("OneHop.removed differs from before - after")
        if self.added != tuple(sorted(after - before)):
            raise ValueError("OneHop.added differs from after - before")
        return self


class PlanCheck(ProtocolModel):
    """Record the complete result of checking selected PairBlocks."""

    schema_version: Literal[3] = Field(
        default=3,
        description="Plan-check record format version.",
    )
    baseline: SourceSnapshot = Field(
        description="Source state inspected before the selected PairBlocks ran."
    )
    realized: SourceSnapshot = Field(
        description=(
            "Candidate source state inspected after the selected PairBlocks ran."
        )
    )
    blocks: tuple[PairBlockId, ...] = Field(
        min_length=1,
        description="Selected PairBlocks covered by this check.",
    )
    contracts: tuple[RepoRelPath, ...] = Field(
        min_length=1,
        description="Contract files needed to reconstruct the selected plan.",
    )
    baseline_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state already exists in the baseline."
        ),
    )
    unsatisfied_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state is absent from the baseline."
        ),
    )
    plan_sha256: SHA256 = Field(
        description=(
            "Digest of the selected PairBlock and ContractTarget records plus "
            "the selected asset paths and bytes."
        )
    )
    impact: Impact = Field(
        description="Direct advisory dependency report for the selected targets."
    )
    one_hop: OneHop = Field(
        description="CodeQL edge delta derived from the baseline and planned source."
    )
    targets: tuple[TargetCheck, ...] = Field(
        description="One realized result for every selected ContractTarget."
    )
    unexpected: tuple[RepoSymbolRef, ...] = Field(
        description="Changed declarations that no selected ContractTarget owns."
    )
    gates: tuple[GateCheck, ...] = Field(
        description="One gate result for every selected PairBlock."
    )
    receipts_valid: bool = Field(
        description=(
            "Whether both graphs have valid receipts and matching stage specifications."
        )
    )
    plan_valid: bool = Field(
        description=(
            "Whether the post-gate contract files retain the checked plan digest."
        )
    )
    source_valid: bool = Field(
        description="Whether both source roots retain their checked source digests."
    )
    passed: bool = Field(
        description=(
            "Whether every target, dependency, gate, source, plan, and receipt check "
            "passed."
        )
    )


class Acceptance(ProtocolModel):
    """Bind a passing plan check to its exact committed source and plan."""

    check: SHA256 = Field(
        description="Digest of the exact passing PlanCheck accepted for reuse."
    )
    revision: CommitId = Field(
        description="Commit whose Python source and selected plan match the PlanCheck."
    )


class PlanInspection(ProtocolModel):
    """Return resolved selected targets and their direct advisory impact."""

    targets: tuple[ResolvedContractTarget, ...] = Field(
        description="Selected targets resolved against their baseline declarations."
    )
    impact: Impact = Field(
        description="Direct advisory impact derived from the resolved targets."
    )


__all__ = [
    "Acceptance",
    "ChangeKind",
    "CheckState",
    "CodeQLAnalysisReceipt",
    "CodeQLExtractionSpec",
    "CodeQLQuerySpec",
    "CommitId",
    "DatabaseReceipt",
    "EdgeKind",
    "GateCheck",
    "GraphReceipt",
    "Impact",
    "NodeId",
    "OneHop",
    "PlanCheck",
    "PlanInspection",
    "QueryReceipt",
    "ResolvedContractTarget",
    "SourceEdge",
    "SourceGraph",
    "SourceGraphFormat",
    "SourceNode",
    "SourceNodeKind",
    "SourceSnapshot",
    "TargetCheck",
    "stage_key",
]
