"""Define immutable storage and exact-file references."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from ._schema import SHA256, GitCommit, NonEmptyStr, ProtocolModel, RepoRelPath
from .ids import StageId


class GitSource(ProtocolModel):
    """A repository snapshot identified by an exact Git commit."""

    kind: Literal["git"] = "git"
    repository: HttpUrl
    commit: GitCommit


class GitFileRef(GitSource):
    """A file stored at an exact Git revision."""

    path: RepoRelPath


def _validate_pointer_path(path: RepoRelPath) -> None:
    """Require the canonical path for one promoted-input pointer."""
    parts = path.split("/")
    selection = parts[3].removesuffix(".pointer.yaml") if len(parts) == 4 else ""
    if (
        len(parts) != 4
        or parts[0] != "inputs"
        or parts[1] not in {"benchmarks", "datasets", "models", "priors"}
        or not parts[3].endswith(".pointer.yaml")
        or re.fullmatch(r"[a-z][a-z0-9_]*", parts[2]) is None
        or re.fullmatch(r"[a-z][a-z0-9_]*", selection) is None
    ):
        raise ValueError(
            "artifact pointer path must match "
            "inputs/<category>/<entity_id>/<selection_name>.pointer.yaml"
        )


class ArtifactPointerRef(GitFileRef):
    """A Git reference to the pointer selecting a promoted artifact."""

    @model_validator(mode="after")
    def validate_pointer_path(self) -> ArtifactPointerRef:
        """Enforce the canonical promoted-input pointer path."""
        _validate_pointer_path(self.path)
        return self


class HuggingFaceFileRef(ProtocolModel):
    """A file stored at an exact Hugging Face repository revision."""

    kind: Literal["huggingface"] = "huggingface"
    repository: NonEmptyStr
    commit: GitCommit
    path: RepoRelPath
    repo_type: Literal["model", "dataset", "space"]


class LocalFileRef(ProtocolModel):
    """A file in one immutable revision of a repository-local VIPER store."""

    kind: Literal["local"] = "local"
    store: RepoRelPath = ".viper/store"
    commit: SHA256
    path: RepoRelPath


class LocalStageResultSnapshotRef(ProtocolModel):
    """One immutable stage-result revision in a repository-local VIPER store."""

    kind: Literal["local"] = "local"
    store: RepoRelPath = ".viper/store"
    commit: SHA256


class StageResultSnapshotRef(ProtocolModel):
    """The immutable repository revision containing one completed stage."""

    kind: Literal["huggingface"] = "huggingface"
    repository: NonEmptyStr
    commit: GitCommit
    repo_type: Literal["model", "dataset", "space"]


StageResultSnapshot = Annotated[
    StageResultSnapshotRef | LocalStageResultSnapshotRef,
    Field(discriminator="kind"),
]

StorageModel = GitFileRef | HuggingFaceFileRef | LocalFileRef

StorageRef = Annotated[
    StorageModel,
    Field(discriminator="kind"),
]


class ResolvedFileRef(ProtocolModel):
    """Identify one hashed file and its immutable storage location."""

    sha256: SHA256
    bytes: int = Field(ge=0)
    stored_at: StorageRef


class SnapshotFileRef(ProtocolModel):
    """Identify one exact file within a stage-result snapshot."""

    path: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class ResolvedGitFileRef(ResolvedFileRef):
    """Identify an exact file stored at an immutable Git revision."""

    stored_at: GitFileRef  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedStageRef(ProtocolModel):
    """Binds one completed stage to its immutable stage-result snapshot."""

    stage_id: StageId
    snapshot: StageResultSnapshot
    resolved_spec: SnapshotFileRef


class ResolvedStageInvocationRef(ResolvedFileRef):
    """Identify one immutable stage-invocation receipt."""

    kind: Literal["stage_invocation"] = "stage_invocation"


class ResolvedArtifactPointerRef(ResolvedFileRef):
    """Identify an exact verified artifact-pointer file."""

    kind: Literal["artifact_pointer"] = "artifact_pointer"

    @model_validator(mode="after")
    def validate_pointer_path(self) -> ResolvedArtifactPointerRef:
        """Enforce the pointer path for every storage backend."""
        _validate_pointer_path(self.stored_at.path)
        return self


class ResolvedRunSpecRef(ResolvedFileRef):
    """Identify the exact run specification governing one run."""

    kind: Literal["run_spec"] = "run_spec"


class ResolvedRunRef(ResolvedFileRef):
    """Identify one terminal resolved-run document."""

    kind: Literal["resolved_run"] = "resolved_run"


class ResolvedBenchmarkSpecRef(ResolvedFileRef):
    """Identify the exact benchmark specification applied to a run."""

    kind: Literal["benchmark_spec"] = "benchmark_spec"


class ResolvedBenchmarkResultRef(ResolvedFileRef):
    """Identify one completed benchmark result."""

    kind: Literal["benchmark_result"] = "benchmark_result"


__all__ = [
    "ArtifactPointerRef",
    "GitFileRef",
    "GitSource",
    "HuggingFaceFileRef",
    "LocalFileRef",
    "LocalStageResultSnapshotRef",
    "ResolvedStageRef",
    "ResolvedStageInvocationRef",
    "ResolvedArtifactPointerRef",
    "ResolvedBenchmarkResultRef",
    "ResolvedBenchmarkSpecRef",
    "ResolvedFileRef",
    "ResolvedGitFileRef",
    "ResolvedRunRef",
    "ResolvedRunSpecRef",
    "SnapshotFileRef",
    "StageResultSnapshot",
    "StageResultSnapshotRef",
    "StorageModel",
    "StorageRef",
    "storage_file",
]


def storage_file(location: StorageModel, path: RepoRelPath) -> StorageModel:
    """Address another file in the same immutable revision."""
    values = location.model_dump()
    values["path"] = path
    return type(location).model_validate(values)


def resolve_snapshot_file_ref(
    snapshot: StageResultSnapshot,
    file: SnapshotFileRef,
) -> ResolvedFileRef:
    """Address one snapshot member without reading or republishing its bytes."""
    stored_at: StorageModel
    if isinstance(snapshot, LocalStageResultSnapshotRef):
        stored_at = LocalFileRef(
            store=snapshot.store,
            commit=snapshot.commit,
            path=file.path,
        )
    else:
        stored_at = HuggingFaceFileRef(
            repository=snapshot.repository,
            commit=snapshot.commit,
            path=file.path,
            repo_type=snapshot.repo_type,
        )
    return ResolvedFileRef(
        sha256=file.sha256,
        bytes=file.bytes,
        stored_at=stored_at,
    )
