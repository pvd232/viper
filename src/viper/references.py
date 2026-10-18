"""Define immutable storage and exact-file references."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from ._schema import (
    SHA256,
    AbsolutePath,
    GitCommit,
    NonEmptyStr,
    ProtocolModel,
    RepoRelPath,
)
from .ids import HumanId, LocalStoreId, OutputName, StageId


class GitSource(ProtocolModel):
    """A repository snapshot identified by an exact Git commit."""

    kind: Literal["git"] = "git"
    repository: HttpUrl
    commit: GitCommit


class GitFileRef(GitSource):
    """A file stored at an exact Git revision."""

    path: RepoRelPath


def _validate_pointer_path(path: RepoRelPath) -> None:
    """Require the canonical path for one run-output pointer."""
    parts = path.split("/")
    selection = parts[4].removesuffix(".pointer.yaml") if len(parts) == 5 else ""
    if (
        len(parts) != 5
        or parts[0] != ".viper"
        or parts[1] != "pointers"
        or re.fullmatch(r"[0-9a-f]{64}", parts[2]) is None
        or re.fullmatch(r"[a-z][a-z0-9_]*", parts[3]) is None
        or not parts[4].endswith(".pointer.yaml")
        or re.fullmatch(r"[a-z][a-z0-9_]*", selection) is None
    ):
        raise ValueError(
            "output pointer path must match "
            ".viper/pointers/<run_digest>/<stage_id>/<output_name>.pointer.yaml"
        )


def output_pointer_path(
    *,
    run_digest: SHA256,
    producer_stage_id: StageId,
    output_name: OutputName,
) -> RepoRelPath:
    """Generate the pointer path for one completed run output."""
    path = (
        f".viper/pointers/{run_digest}/{producer_stage_id}/{output_name}.pointer.yaml"
    )
    _validate_pointer_path(path)
    return path


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
    """Reference to the file at ``workspace / store / commit / path``."""

    kind: Literal["local"] = "local"
    workspace: AbsolutePath = Field(
        description="Absolute root of the workspace that owns the local store."
    )
    store: RepoRelPath = ".viper/store"
    store_id: LocalStoreId = Field(
        description="Store identity saved in workspace / store / '.identity'."
    )
    commit: SHA256
    path: RepoRelPath


class LocalStageResultSnapshotRef(ProtocolModel):
    """Reference to a saved file collection at ``workspace / store / commit``.

    ``commit`` names the directory derived from file paths, sizes, and hashes.
    A ``LocalFileRef`` adds ``path`` to select one file within that directory.
    The store's persisted identity must match ``store_id``.
    """

    kind: Literal["local"] = Field(
        default="local", description="Select the repository-local storage backend."
    )
    workspace: AbsolutePath = Field(
        description="Absolute workspace directory beneath which store is located."
    )
    store: RepoRelPath = Field(
        default=".viper/store", description="Store directory relative to workspace."
    )
    store_id: LocalStoreId = Field(
        description="Random store identity saved in workspace / store / '.identity'."
    )
    commit: SHA256 = Field(
        description="Revision directory derived from file paths, sizes, and hashes."
    )


class HuggingFaceStageResultSnapshotRef(ProtocolModel):
    """Reference to a saved file collection at one Hugging Face repository commit.

    ``repository`` and ``repo_type`` select the repository; ``commit`` fixes its
    version. A ``HuggingFaceFileRef`` adds a repository-relative ``path`` to select
    one file. The revision manifest lists the collection's members.
    """

    kind: Literal["huggingface"] = Field(
        default="huggingface", description="Select the Hugging Face storage backend."
    )
    repository: NonEmptyStr = Field(description="Hub repository ID as owner/name.")
    commit: GitCommit = Field(
        description="Exact Git commit containing the saved file collection."
    )
    repo_type: Literal["model", "dataset", "space"] = Field(
        description="Hub repository category used with repository to locate the files."
    )


class GcsFileRef(ProtocolModel):
    """A file in one sealed Google Cloud Storage revision."""

    kind: Literal["gcs"] = "gcs"
    bucket: NonEmptyStr
    prefix: RepoRelPath = "viper"
    owner: HumanId
    workspace: HumanId
    revision: SHA256
    path: RepoRelPath


class ViperCloudFileRef(ProtocolModel):
    """A file in a provider-neutral ViperCloud revision."""

    kind: Literal["viper_cloud"] = "viper_cloud"
    owner: HumanId
    workspace: HumanId
    revision: SHA256
    path: RepoRelPath


class GcsStageResultSnapshotRef(ProtocolModel):
    """Reference to a saved file collection in Google Cloud Storage.

    Files live under ``gs://{bucket}/{prefix}/{owner}/{workspace}/{revision}/``.
    A ``GcsFileRef`` adds ``path`` beneath that prefix to select one object.
    """

    kind: Literal["gcs"] = Field(
        default="gcs", description="Select the Google Cloud Storage backend."
    )
    bucket: NonEmptyStr = Field(description="GCS bucket containing the collection.")
    prefix: RepoRelPath = Field(
        default="viper", description="Object-key prefix preceding owner/workspace."
    )
    owner: HumanId = Field(description="Owner namespace beneath prefix.")
    workspace: HumanId = Field(description="Logical workspace name beneath owner.")
    revision: SHA256 = Field(
        description="Content-derived revision beneath owner/workspace."
    )


class ViperCloudStageResultSnapshotRef(ProtocolModel):
    """Legacy collection reference requiring a configured GCS repository.

    Configuration supplies bucket and prefix for
    ``gs://{bucket}/{prefix}/{owner}/{workspace}/{revision}/``.
    A ``ViperCloudFileRef`` adds ``path`` to select one member.
    """

    kind: Literal["viper_cloud"] = Field(
        default="viper_cloud",
        description="Select legacy cloud addressing through repository configuration.",
    )
    owner: HumanId = Field(description="Owner namespace beneath the configured prefix.")
    workspace: HumanId = Field(description="Logical workspace name beneath owner.")
    revision: SHA256 = Field(
        description="Content-derived revision beneath owner/workspace."
    )


StageResultSnapshotRef = Annotated[
    GcsStageResultSnapshotRef
    | HuggingFaceStageResultSnapshotRef
    | LocalStageResultSnapshotRef
    | ViperCloudStageResultSnapshotRef,
    Field(discriminator="kind"),
]

CloudFileRef = GcsFileRef | HuggingFaceFileRef | ViperCloudFileRef
CloudStageResultSnapshotRef = (
    GcsStageResultSnapshotRef
    | HuggingFaceStageResultSnapshotRef
    | ViperCloudStageResultSnapshotRef
)

StorageModel = (
    GitFileRef | GcsFileRef | HuggingFaceFileRef | LocalFileRef | ViperCloudFileRef
)

StorageRef = Annotated[
    StorageModel,
    Field(discriminator="kind"),
]


class FileIdentity(ProtocolModel):
    """Identify one exact byte sequence independently of its location."""

    sha256: SHA256 = Field(description="SHA-256 digest of the file bytes.")
    bytes: int = Field(ge=0, description="Number of bytes in the file.")


class ResolvedFileRef(FileIdentity):
    """Identify one hashed file and its immutable storage location."""

    stored_at: StorageRef


class SnapshotFileRef(FileIdentity):
    """Relative path, expected size, and SHA-256 of one file in a snapshot.

    Pair this with a ``StageResultSnapshotRef`` to locate and verify the file.
    The snapshot supplies the storage address; ``path`` selects its member.
    """

    path: RepoRelPath = Field(
        description="Member path appended to the containing snapshot's root address."
    )


class ResolvedGitFileRef(ResolvedFileRef):
    """Identify an exact file stored at an immutable Git revision."""

    stored_at: GitFileRef  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedStageRef(ProtocolModel):
    """Binds one completed stage to its immutable stage-result snapshot."""

    stage_id: StageId
    snapshot: StageResultSnapshotRef
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
    "CloudFileRef",
    "CloudStageResultSnapshotRef",
    "FileIdentity",
    "GcsFileRef",
    "GcsStageResultSnapshotRef",
    "GitFileRef",
    "GitSource",
    "HuggingFaceFileRef",
    "HuggingFaceStageResultSnapshotRef",
    "LocalFileRef",
    "LocalStageResultSnapshotRef",
    "ResolvedArtifactPointerRef",
    "ResolvedBenchmarkResultRef",
    "ResolvedBenchmarkSpecRef",
    "ResolvedFileRef",
    "ResolvedGitFileRef",
    "ResolvedRunRef",
    "ResolvedRunSpecRef",
    "ResolvedStageInvocationRef",
    "ResolvedStageRef",
    "SnapshotFileRef",
    "StageResultSnapshotRef",
    "StorageModel",
    "StorageRef",
    "ViperCloudFileRef",
    "ViperCloudStageResultSnapshotRef",
    "storage_file",
]


def storage_file(location: StorageModel, path: RepoRelPath) -> StorageModel:
    """Address another file in the same immutable revision."""
    values = location.model_dump()
    values["path"] = path
    return type(location).model_validate(values)


def resolve_snapshot_file_ref(
    snapshot: StageResultSnapshotRef,
    file: SnapshotFileRef,
) -> ResolvedFileRef:
    """Address one snapshot member without reading or republishing its bytes."""
    stored_at: StorageModel
    if isinstance(snapshot, LocalStageResultSnapshotRef):
        stored_at = LocalFileRef(
            workspace=snapshot.workspace,
            store=snapshot.store,
            store_id=snapshot.store_id,
            commit=snapshot.commit,
            path=file.path,
        )
    elif isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
        stored_at = HuggingFaceFileRef(
            repository=snapshot.repository,
            commit=snapshot.commit,
            path=file.path,
            repo_type=snapshot.repo_type,
        )
    elif isinstance(snapshot, GcsStageResultSnapshotRef):
        stored_at = GcsFileRef(
            bucket=snapshot.bucket,
            prefix=snapshot.prefix,
            owner=snapshot.owner,
            workspace=snapshot.workspace,
            revision=snapshot.revision,
            path=file.path,
        )
    else:
        stored_at = ViperCloudFileRef(
            owner=snapshot.owner,
            workspace=snapshot.workspace,
            revision=snapshot.revision,
            path=file.path,
        )
    return ResolvedFileRef(
        sha256=file.sha256,
        bytes=file.bytes,
        stored_at=stored_at,
    )
