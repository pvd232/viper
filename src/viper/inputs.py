"""Input model classes."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from ._schema import DataRole, ProtocolModel, RepoRelPath, repo_file_paths_overlap
from .http import HttpRequestSpec
from .ids import InputName, OutputName, RunId, StageId
from .references import (
    ArtifactPointerRef,
    ResolvedArtifactPointerRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StorageModel,
)


class StoredInputMaterialization(StrEnum):
    """Select where a verified prior-run artifact is materialized."""

    DECLARED_PATH = "declared_path"
    ATTEMPT_WORKSPACE = "attempt_workspace"


class LocalSource(ProtocolModel):
    """Identify one repository-local file selected by the user."""

    kind: Literal["local"] = "local"
    path: RepoRelPath


class ExternalInputRef(ProtocolModel):
    """Declare one repository-local value supplied to a stage."""

    kind: Literal["external"] = "external"
    source: LocalSource
    data_role: DataRole


class ResolvedExternalInputRef(ProtocolModel):
    """Record one local input captured in its consuming stage snapshot."""

    kind: Literal["external"] = "external"
    source: LocalSource
    file: SnapshotFileRef
    data_role: DataRole


PointerRef = ArtifactPointerRef | ResolvedArtifactPointerRef


def validate_stored_input_path(path: RepoRelPath) -> RepoRelPath:
    """Return a stored-input path rooted beneath the consumer's inputs directory."""
    if not str(path).startswith("inputs/"):
        raise ValueError("stored input path must be beneath inputs/")
    return path


def pointer_location(pointer: PointerRef) -> StorageModel:
    """Return the immutable storage location of one artifact pointer."""
    if isinstance(pointer, ResolvedArtifactPointerRef):
        return pointer.stored_at
    return pointer


def pointer_location_matches(pointer: PointerRef, location: StorageModel) -> bool:
    """Compare pointer locations without requiring identical model subclasses."""
    return pointer_location(pointer).model_dump(mode="json") == location.model_dump(
        mode="json"
    )


def pointer_path(pointer: PointerRef) -> RepoRelPath:
    """Return the path containing one artifact pointer."""
    return pointer_location(pointer).path


class StoredInputRef(ProtocolModel):
    """Select a prior run's artifact through its stored pointer."""

    kind: Literal["stored"] = "stored"
    pointer: PointerRef
    path: RepoRelPath
    data_role: DataRole
    materialization: StoredInputMaterialization = (
        StoredInputMaterialization.DECLARED_PATH
    )

    _validate_input_root = field_validator("path")(validate_stored_input_path)

    @model_validator(mode="after")
    def validate_materialization_path(self) -> StoredInputRef:
        """Require the consumer path and pointer path to occupy separate roots."""
        selected_pointer_path = pointer_path(self.pointer)
        if repo_file_paths_overlap(
            self.path, selected_pointer_path
        ) or self.path.endswith(".pointer.yaml"):
            raise ValueError(
                "stored input path must not use or overlap a pointer-file path"
            )
        return self


class FutureInputRef(ProtocolModel):
    """One named artifact produced by an earlier stage in the same run."""

    kind: Literal["future"] = "future"
    producer_stage_id: StageId
    name: OutputName


InputRef = Annotated[
    ExternalInputRef | StoredInputRef | FutureInputRef,
    Field(discriminator="kind"),
]


class ResolvedStoredInputRef(ProtocolModel):
    """Bind a stored stage input to its verified pointer file."""

    kind: Literal["stored"] = "stored"
    pointer: ResolvedArtifactPointerRef


class ResolvedFutureInputRef(ProtocolModel):
    """Bind a future input to its completed producer stage."""

    kind: Literal["future"] = "future"
    producer: ResolvedStageRef


class VerifiedDownloadSource(ProtocolModel):
    """Identify one immutable Download receipt at a provenance graph root."""

    run_id: RunId = Field(description="Run that executed the root download stage.")
    attempt_id: int = Field(
        ge=1,
        description="Attempt that executed the root download stage.",
    )
    stage_id: StageId = Field(description="Download stage that produced the bytes.")
    stage_receipt: ResolvedStageRef = Field(
        description="Exact immutable resolved-stage receipt for the Download root."
    )
    input_name: InputName = Field(
        description="Named HTTP request and same-named download output."
    )
    request: HttpRequestSpec = Field(
        description="Frozen HTTP request whose promised body was verified."
    )
    body: SnapshotFileRef = Field(
        description="Immutable body reference retained by the Download receipt."
    )

    @model_validator(mode="after")
    def validate_stage_receipt(self) -> VerifiedDownloadSource:
        """Bind the semantic stage ID to the exact retained stage receipt."""
        if self.stage_receipt.stage_id != self.stage_id:
            raise ValueError("download root stage receipt and stage ID differ")
        return self


class DownloadSourceNode(ProtocolModel):
    """Identify one record visited while walking toward Download roots."""

    node_id: str = Field(
        min_length=1,
        description="Canonical identity of the visited input, output, or receipt.",
    )
    kind: Literal["stage_input", "stage_output", "pointer", "reuse"] = Field(
        description="Protocol role of the visited record."
    )


class DownloadSourceEdge(ProtocolModel):
    """Record one directed provenance relationship followed by the verifier."""

    source: str = Field(
        min_length=1,
        description="Canonical identity of the consuming-side record.",
    )
    target: str = Field(
        min_length=1,
        description="Canonical identity of the source-side record.",
    )
    relation: Literal["future", "stored", "selects", "produced_from", "reuse"] = Field(
        description="Relationship followed from source to target."
    )


class DownloadSourceClosureReceipt(ProtocolModel):
    """Record the verified Download roots reachable from each consumer input."""

    schema_version: Literal[1] = Field(
        default=1,
        description="Schema used to decode this source-closure receipt.",
    )
    roots: dict[InputName, tuple[VerifiedDownloadSource, ...]] = Field(
        min_length=1,
        description="Verified terminal Download roots grouped by consumer input.",
    )
    nodes: tuple[DownloadSourceNode, ...] = Field(
        min_length=1,
        description="Every provenance record visited by the closure walk.",
    )
    edges: tuple[DownloadSourceEdge, ...] = Field(
        min_length=1,
        description="Every provenance relationship followed by the closure walk.",
    )

    @model_validator(mode="after")
    def validate_roots(self) -> DownloadSourceClosureReceipt:
        """Require every consumer input to reach unique, ordered roots."""
        for input_name, roots in self.roots.items():
            if not roots:
                raise ValueError(
                    f"download source roots for input {input_name!r} cannot be empty"
                )
            identities = tuple(
                (
                    root.run_id,
                    root.attempt_id,
                    root.stage_id,
                    root.input_name,
                    root.stage_receipt.resolved_spec.sha256,
                )
                for root in roots
            )
            if identities != tuple(sorted(set(identities))):
                raise ValueError("download source roots must be unique and sorted")
        node_ids = tuple(node.node_id for node in self.nodes)
        if node_ids != tuple(sorted(set(node_ids))):
            raise ValueError("download source nodes must be unique and sorted")
        edge_ids = tuple(
            (edge.source, edge.target, edge.relation) for edge in self.edges
        )
        if edge_ids != tuple(sorted(set(edge_ids))):
            raise ValueError("download source edges must be unique and sorted")
        known = set(node_ids)
        if any(
            edge.source not in known or edge.target not in known for edge in self.edges
        ):
            raise ValueError("download source edge references an absent node")
        return self


ResolvedInputRef = Annotated[
    ResolvedStoredInputRef | ResolvedFutureInputRef | ResolvedExternalInputRef,
    Field(discriminator="kind"),
]
