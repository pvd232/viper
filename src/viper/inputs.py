"""Input model classes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._schema import (
    ArtifactName,
    DataRole,
    ProtocolModel,
    RepoRelPath,
    repo_file_paths_overlap,
)
from .ids import StageId
from .references import (
    ArtifactPointerRef,
    ResolvedArtifactPointerRef,
    ResolvedStageRef,
    SnapshotFileRef,
)

# ----- Provenance graph boundary ----- #


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


# ----- Provenance graph boundary ----- #


class StoredInputRef(ProtocolModel):
    """A promoted artifact selected before the run begins."""

    kind: Literal["stored"] = "stored"
    pointer: ArtifactPointerRef
    path: RepoRelPath
    data_role: DataRole

    @model_validator(mode="after")
    def validate_materialization_path(self) -> StoredInputRef:
        """Keep materialized input bytes within their promoted-input scope."""
        pointer_scope = self.pointer.path.split("/")[:3]
        materialization_parts = self.path.split("/")
        if (
            len(materialization_parts) < 3
            or materialization_parts[:3] != pointer_scope
            or repo_file_paths_overlap(self.path, self.pointer.path)
            or materialization_parts[-1].endswith(".pointer.yaml")
        ):
            raise ValueError(
                "stored input path must use the pointer's category and entity ID "
                "and must not use or overlap a pointer-file path"
            )
        return self


class FutureInputRef(ProtocolModel):
    """One named artifact produced by an earlier stage in the same run."""

    kind: Literal["future"] = "future"
    producer_stage_id: StageId
    name: ArtifactName


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


ResolvedInputRef = Annotated[
    ResolvedStoredInputRef | ResolvedFutureInputRef | ResolvedExternalInputRef,
    Field(discriminator="kind"),
]
