"""Expose provider-neutral ViperCloud publication and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ._cloud import (
    GcsRepository,
    HuggingFaceRepository,
    PublicationSource,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudProvider,
    ViperCloudRepository,
)
from ._schema import RepoRelPath
from .gcs import GcsProvider
from .huggingface import HuggingFaceProvider
from .references import (
    CloudFileRef,
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
)


class ViperCloud:
    """Publish and retrieve artifacts without exposing provider implementations."""

    def __init__(
        self,
        root: Path,
        repository: ViperCloudRepository,
        *,
        provider: ViperCloudProvider | None = None,
    ) -> None:
        """Bind one workspace to its configured cloud repository."""
        self.root = root.resolve(strict=True)
        self.repository = repository
        self.provider = provider or self._create_provider(repository)

    def _create_provider(
        self,
        repository: ViperCloudRepository,
    ) -> ViperCloudProvider:
        """Construct the provider selected by validated workspace settings."""
        if isinstance(repository, GcsRepository):
            return GcsProvider(
                self.root,
                repository.bucket,
                prefix=repository.prefix,
            )
        if isinstance(repository, HuggingFaceRepository):
            return HuggingFaceProvider(
                self.root,
                repository.repository,
                repository.repo_type,
            )
        raise ViperCloudError("unsupported ViperCloud repository")

    @classmethod
    def for_reference(cls, root: Path, reference: CloudFileRef) -> ViperCloud:
        """Construct the service that owns one self-describing cloud reference."""
        if isinstance(reference, GcsFileRef):
            repository: ViperCloudRepository = GcsRepository(
                bucket=reference.bucket,
                prefix=reference.prefix,
            )
        elif isinstance(reference, HuggingFaceFileRef):
            repository = HuggingFaceRepository(
                repository=reference.repository,
                repo_type=reference.repo_type,
            )
        else:
            raise TypeError("reference is not cloud-backed")
        return cls(root, repository)

    @classmethod
    def for_snapshot(
        cls,
        root: Path,
        snapshot: CloudStageResultSnapshotRef,
    ) -> ViperCloud:
        """Construct the service that owns one self-describing cloud snapshot."""
        if isinstance(snapshot, GcsStageResultSnapshotRef):
            repository: ViperCloudRepository = GcsRepository(
                bucket=snapshot.bucket,
                prefix=snapshot.prefix,
            )
        elif isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
            repository = HuggingFaceRepository(
                repository=snapshot.repository,
                repo_type=snapshot.repo_type,
            )
        else:
            raise TypeError("snapshot is not cloud-backed")
        return cls(root, repository)

    def publish(
        self,
        destination: ViperCloudDestination,
        sources: Mapping[RepoRelPath, PublicationSource],
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Publish one sealed revision through the selected provider."""
        return self.provider.publish(destination, sources)

    def resolved_files(
        self,
        destination: ViperCloudDestination,
        sources: Mapping[RepoRelPath, PublicationSource],
    ) -> dict[RepoRelPath, ResolvedFileRef]:
        """Publish related files and return exact references by canonical path."""
        snapshot, files = self.publish(destination, sources)
        return {
            identity.path: ResolvedFileRef(
                sha256=identity.sha256,
                bytes=identity.bytes,
                stored_at=self.provider.file_ref(snapshot, identity.path),
            )
            for identity in files
        }

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
        """Publish remapped files through the provider's optimized path."""
        service = self._service_for_snapshot(source_snapshot)
        return service.provider.publish_reuse(
            destination=destination,
            resolved_stage_path=resolved_stage_path,
            resolved_stage=resolved_stage,
            source_snapshot=source_snapshot,
            files=files,
            source_bytes=source_bytes,
        )

    def fetch(self, location: CloudFileRef) -> bytes:
        """Return verified bytes from the provider named by the reference."""
        service = self._service_for_file(location)
        return service.provider.fetch(location)

    def fetch_to_path(self, reference: ResolvedFileRef, destination: Path) -> Path:
        """Materialize a verified reference at one local workspace path."""
        location = reference.stored_at
        if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            raise TypeError("resolved file is not cloud-backed")
        service = self._service_for_file(location)
        return service.provider.fetch_to_path(
            location,
            SnapshotFileRef(
                path=location.path,
                sha256=reference.sha256,
                bytes=reference.bytes,
            ),
            destination,
        )

    def list_files(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> tuple[SnapshotFileRef, ...]:
        """Return the exact members of one sealed provider snapshot."""
        service = self._service_for_snapshot(snapshot)
        return service.provider.list_files(snapshot)

    def file_ref(
        self,
        snapshot: CloudStageResultSnapshotRef,
        path: RepoRelPath,
    ) -> CloudFileRef:
        """Return the provider-specific file reference inside one snapshot."""
        service = self._service_for_snapshot(snapshot)
        return service.provider.file_ref(snapshot, path)

    def verify_file(self, reference: ResolvedFileRef) -> None:
        """Verify one cloud file without changing its artifact identity."""
        location = reference.stored_at
        if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            raise TypeError("resolved file is not cloud-backed")
        service = self._service_for_file(location)
        service.provider.verify_file(
            location,
            SnapshotFileRef(
                path=location.path,
                sha256=reference.sha256,
                bytes=reference.bytes,
            ),
        )

    def _service_for_file(self, reference: CloudFileRef) -> ViperCloud:
        """Reuse this service or construct the provider named by a file ref."""
        if self._provider_matches_file(reference):
            return self
        return self.for_reference(self.root, reference)

    def _service_for_snapshot(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> ViperCloud:
        """Reuse this service or construct the provider named by a snapshot ref."""
        if self._provider_matches_snapshot(snapshot):
            return self
        return self.for_snapshot(self.root, snapshot)

    def _provider_matches_file(self, reference: CloudFileRef) -> bool:
        """Return whether the configured provider owns a file reference."""
        return (
            isinstance(self.repository, GcsRepository)
            and isinstance(reference, GcsFileRef)
            and self.repository.bucket == reference.bucket
            and self.repository.prefix == reference.prefix
        ) or (
            isinstance(self.repository, HuggingFaceRepository)
            and isinstance(reference, HuggingFaceFileRef)
            and self.repository.repository == reference.repository
            and self.repository.repo_type == reference.repo_type
        )

    def _provider_matches_snapshot(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> bool:
        """Return whether the configured provider owns a snapshot reference."""
        return (
            isinstance(self.repository, GcsRepository)
            and isinstance(snapshot, GcsStageResultSnapshotRef)
            and self.repository.bucket == snapshot.bucket
            and self.repository.prefix == snapshot.prefix
        ) or (
            isinstance(self.repository, HuggingFaceRepository)
            and isinstance(snapshot, HuggingFaceStageResultSnapshotRef)
            and self.repository.repository == snapshot.repository
            and self.repository.repo_type == snapshot.repo_type
        )


__all__ = ["ViperCloud"]
