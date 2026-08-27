"""Define artifact declarations, identities, pointers, and resolved values."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._schema import (
    SHA256,
    ArtifactName,
    DataRole,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
    RepoRelPath,
    repo_file_paths_overlap,
)
from .ids import StageId
from .references import (
    ResolvedBenchmarkResultRef,
    ResolvedRunRef,
    SnapshotFileRef,
)


class StageArtifactRef(ProtocolModel):
    """Select one named artifact produced by one stage."""

    stage_id: StageId
    artifact_name: ArtifactName


class ArtifactPointer(ProtocolModel):
    """Select one artifact accepted as a reusable input."""

    schema_version: Literal[1] = 1
    run: ResolvedRunRef
    artifact: StageArtifactRef
    benchmark_result: ResolvedBenchmarkResultRef | None = None


class ArtifactLoaderRef(ProtocolModel):
    """Identify one project-owned artifact loader by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol = "load"
    sha256: SHA256
    bytes: int = Field(gt=0)


class SingleFileArtifactSpec(ProtocolModel):
    """Declare one named artifact written as one file."""

    kind: Literal["file"] = "file"
    path: RepoRelPath
    loader: ArtifactLoaderRef
    data_role: DataRole


class BundleArtifactSpec(ProtocolModel):
    """Declare one named artifact written beneath one directory root."""

    kind: Literal["bundle"] = "bundle"
    path: RepoRelPath
    loader: ArtifactLoaderRef
    data_role: DataRole


ArtifactSpec = Annotated[
    SingleFileArtifactSpec | BundleArtifactSpec,
    Field(discriminator="kind"),
]


class ResolvedSingleFileArtifact(ProtocolModel):
    """Record the exact file representing one artifact."""

    kind: Literal["file"] = "file"
    file: SnapshotFileRef


class ResolvedBundleMember(ProtocolModel):
    """Record one exact file beneath a bundle artifact's directory root."""

    relative_path: RepoRelPath
    file: SnapshotFileRef


class ResolvedBundleArtifact(ProtocolModel):
    """Record every exact file representing one bundle artifact."""

    kind: Literal["bundle"] = "bundle"
    members: tuple[ResolvedBundleMember, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_member_paths(self) -> ResolvedBundleArtifact:
        """Require unique, ordered, and nonoverlapping bundle member paths."""
        relative_paths = tuple(member.relative_path for member in self.members)
        if len(set(relative_paths)) != len(relative_paths):
            raise ValueError("bundle member paths must be unique")
        if relative_paths != tuple(sorted(relative_paths)):
            raise ValueError("bundle members must use canonical path order")

        for index, relative_path in enumerate(relative_paths):
            for prior_path in relative_paths[:index]:
                if repo_file_paths_overlap(relative_path, prior_path):
                    raise ValueError("bundle member paths must not overlap")

        return self


ResolvedArtifact = Annotated[
    ResolvedSingleFileArtifact | ResolvedBundleArtifact,
    Field(discriminator="kind"),
]


__all__ = [
    "ArtifactLoaderRef",
    "ArtifactPointer",
    "ArtifactSpec",
    "BundleArtifactSpec",
    "ResolvedArtifact",
    "ResolvedBundleArtifact",
    "ResolvedBundleMember",
    "ResolvedSingleFileArtifact",
    "SingleFileArtifactSpec",
    "StageArtifactRef",
]
