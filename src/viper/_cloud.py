"""Define provider-neutral cloud publication contracts and shared behavior."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath
from .ids import HumanId
from .references import (
    CloudFileRef,
    CloudStageResultSnapshotRef,
    SnapshotFileRef,
)
from .repository import PathError, resolve_path

PublicationSource = bytes | Path


class ViperCloudError(RuntimeError):
    """Report invalid configuration or a failed cloud-storage operation."""


class ViperCloudDestination(ProtocolModel):
    """Select one logical ViperCloud workspace for immutable publication."""

    kind: Literal["viper_cloud"] = Field(
        default="viper_cloud",
        description="Discriminator selecting ViperCloud publication.",
    )
    owner: HumanId = Field(description="Account owning the logical workspace.")
    workspace: HumanId = Field(description="Logical workspace receiving the files.")


class GcsRepository(ProtocolModel):
    """Select one Google Cloud Storage repository."""

    provider: Literal["gcs"] = "gcs"
    bucket: NonEmptyStr
    prefix: RepoRelPath = "viper"


class HuggingFaceRepository(ProtocolModel):
    """Select one Hugging Face repository."""

    provider: Literal["huggingface"] = "huggingface"
    repository: NonEmptyStr
    repo_type: Literal["model", "dataset", "space"]


ViperCloudRepository = Annotated[
    GcsRepository | HuggingFaceRepository,
    Field(discriminator="provider"),
]


class RevisionManifest(ProtocolModel):
    """Bind one sealed revision to its exact sorted file identities."""

    schema_version: Literal[1] = 1
    owner: HumanId
    workspace: HumanId
    revision: SHA256
    files: tuple[SnapshotFileRef, ...]

    @model_validator(mode="after")
    def require_revision_identity(self) -> RevisionManifest:
        """Require unique sorted paths and the content-derived revision."""
        paths = tuple(file.path for file in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("cloud manifest files must have unique sorted paths")
        if manifest_revision(self.files) != self.revision:
            raise ValueError("cloud manifest content does not match its revision")
        return self


def manifest_revision(files: tuple[SnapshotFileRef, ...]) -> SHA256:
    """Derive one revision identity from sorted paths and file identities."""
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda item: item.path):
        encoded_path = str(file.path).encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(file.bytes.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file.sha256))
    return digest.hexdigest()


def canonical_json_bytes(record: ProtocolModel) -> bytes:
    """Serialize one cloud protocol record into stable UTF-8 JSON bytes."""
    return (
        json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def resolve_publication_source(root: Path, source: PublicationSource) -> bytes | Path:
    """Return in-memory bytes or one validated root-confined source path."""
    if isinstance(source, bytes):
        return source
    repository_root = root.resolve(strict=True)
    candidate = source if source.is_absolute() else repository_root / source
    try:
        relative = candidate.relative_to(repository_root).as_posix()
        return resolve_path(repository_root, relative, operation="read")
    except (OSError, ValueError, PathError) as error:
        raise ViperCloudError("cloud publication source is invalid") from error


def source_file(
    root: Path,
    path: RepoRelPath,
    source: PublicationSource,
) -> SnapshotFileRef:
    """Hash one source without loading a path-backed payload into memory."""
    resolved = resolve_publication_source(root, source)
    if isinstance(resolved, bytes):
        digest = hashlib.sha256(resolved).hexdigest()
        size = len(resolved)
    else:
        with resolved.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = resolved.stat().st_size
    return SnapshotFileRef(path=path, sha256=digest, bytes=size)


class ViperCloudProvider(ABC):
    """Implement shared immutable publication for one cloud repository kind."""

    def __init__(self, root: Path) -> None:
        """Bind publication and materialization to one workspace root."""
        self.root = root.resolve(strict=True)

    def publish(
        self,
        destination: ViperCloudDestination,
        sources: Mapping[RepoRelPath, PublicationSource],
        *,
        attempts: int = 3,
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Publish and seal one deterministic revision with bounded retries."""
        if attempts < 1:
            raise ValueError("attempts must be positive")
        if not sources:
            raise ViperCloudError("cloud revision requires at least one file")
        files = tuple(
            source_file(self.root, path, source)
            for path, source in sorted(sources.items())
        )
        revision = manifest_revision(files)
        for attempt in range(attempts):
            try:
                snapshot = self.publish_revision(
                    destination=destination,
                    revision=revision,
                    sources=sources,
                    files=files,
                )
                return snapshot, files
            except Exception as error:
                if attempt + 1 == attempts:
                    raise ViperCloudError("cloud publication failed") from error
        raise AssertionError("unreachable cloud publication retry state")

    @abstractmethod
    def publish_revision(
        self,
        *,
        destination: ViperCloudDestination,
        revision: SHA256,
        sources: Mapping[RepoRelPath, PublicationSource],
        files: tuple[SnapshotFileRef, ...],
    ) -> CloudStageResultSnapshotRef:
        """Atomically expose one fully identified revision."""

    @abstractmethod
    def file_ref(
        self,
        snapshot: CloudStageResultSnapshotRef,
        path: RepoRelPath,
    ) -> CloudFileRef:
        """Address one canonical path inside a provider snapshot."""

    @abstractmethod
    def fetch(self, location: CloudFileRef) -> bytes:
        """Return verified bytes from one immutable reference."""

    @abstractmethod
    def fetch_to_path(
        self,
        location: CloudFileRef,
        identity: SnapshotFileRef,
        destination: Path,
    ) -> Path:
        """Materialize verified bytes atomically at a workspace path."""

    @abstractmethod
    def list_files(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> tuple[SnapshotFileRef, ...]:
        """Return the exact members named by a sealed snapshot."""

    def verify_file(self, reference: CloudFileRef, identity: SnapshotFileRef) -> None:
        """Verify one referenced file against its declared identity."""
        raw = self.fetch(reference)
        if (
            len(raw) != identity.bytes
            or hashlib.sha256(raw).hexdigest() != identity.sha256
        ):
            raise ViperCloudError("cloud file identity changed")

    def publish_reuse(
        self,
        *,
        destination: ViperCloudDestination,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: CloudStageResultSnapshotRef,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> CloudStageResultSnapshotRef:
        """Publish remapped verified files, with providers free to avoid downloads."""
        del source_snapshot
        sources: dict[RepoRelPath, PublicationSource] = {
            resolved_stage_path: resolved_stage
        }
        for target_path, source_file_ref in files.items():
            raw = source_bytes[target_path]
            if (
                len(raw) != source_file_ref.bytes
                or hashlib.sha256(raw).hexdigest() != source_file_ref.sha256
            ):
                raise ViperCloudError("reused snapshot file identity changed")
            sources[target_path] = raw
        snapshot, _ = self.publish(destination, sources)
        return snapshot


__all__ = [
    "GcsRepository",
    "HuggingFaceRepository",
    "PublicationSource",
    "RevisionManifest",
    "ViperCloudDestination",
    "ViperCloudError",
    "ViperCloudProvider",
    "ViperCloudRepository",
    "canonical_json_bytes",
    "manifest_revision",
    "resolve_publication_source",
    "source_file",
]
