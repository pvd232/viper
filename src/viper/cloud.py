"""Expose provider-neutral ViperCloud publication and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from google.auth.compute_engine import Credentials
from google.cloud import storage as gcs_storage
from pydantic import Field, model_validator

from ._cloud import (
    GcsRepository,
    HuggingFaceRepository,
    PublicationSource,
    SnapshotCopy,
    SnapshotInventory,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudProvider,
    ViperCloudRepository,
    validate_snapshot_copy,
)
from ._schema import ProtocolModel, RepoRelPath
from .gcs import GcsProgressSink, GcsProvider
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
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
    resolve_snapshot_file_ref,
)

CloudReference = CloudFileRef | CloudStageResultSnapshotRef


class PublicationTarget(ProtocolModel):
    """Select a cloud destination and any required attached GCP identity."""

    repository: ViperCloudRepository = Field(
        description="Cloud repository to publish to."
    )
    destination: ViperCloudDestination = Field(
        description="Logical publication workspace."
    )
    google_project_id: str | None = Field(
        default=None, description="Google Cloud quota identifier."
    )
    gcp_service_account: str | None = Field(
        default=None, description="Required attached GCP service-account email."
    )

    @model_validator(mode="after")
    def require_attached_identity_configuration(self) -> PublicationTarget:
        """Require the GCP configuration needed by attached credentials."""
        if self.gcp_service_account is not None and (
            not self.google_project_id or not isinstance(self.repository, GcsRepository)
        ):
            raise ValueError(
                "attached GCP identity requires a GCS repository and project_id"
            )
        return self


class PublicationReceipt(ProtocolModel):
    """Keep the verified copies needed to restore unchanged artifact references."""

    operation_id: str = Field(description="Identifier of the publication operation.")
    targets: tuple[PublicationTarget, ...] = Field(description="Required destinations.")
    science_succeeded: bool = Field(description="Whether the whole workflow succeeded.")
    used: tuple[ResolvedFileRef, ...] = Field(
        description="Original references used or produced."
    )
    copies: tuple[SnapshotCopy, ...] = Field(
        description="Verified copies of original snapshots."
    )

    file_copies: tuple[ResolvedFileRef, ...] = Field(
        default=(),
        description="Cloud files verified individually while restoring shared bytes.",
    )
    inventories: tuple[SnapshotInventory, ...] = Field(
        default=(),
        description="Original inventories whose shared bytes use another copy's proof.",
    )

    @model_validator(mode="after")
    def require_verified_copies(self) -> PublicationReceipt:
        """Validate copy identities without claiming fresh remote verification."""
        inventories = {inventory.source: inventory for inventory in self.inventories}
        for copy in self.copies:
            validate_snapshot_copy(copy)
            if copy.published is None:
                raise ValueError("publication receipt contains an unfinished copy")
            inventory = SnapshotInventory(
                source=copy.source, source_files=copy.source_files
            )
            previous = inventories.setdefault(copy.source, inventory)
            if previous != inventory:
                raise ValueError("publication receipt contains conflicting inventories")
        if any(
            not isinstance(reference.stored_at, (GcsFileRef, HuggingFaceFileRef))
            for reference in self.file_copies
        ):
            raise ValueError(
                "verified file copies need self-describing cloud addresses"
            )
        return self


class ViperCloud:
    """Publish and retrieve artifacts without exposing provider implementations."""

    def __init__(
        self,
        root: Path,
        repository: ViperCloudRepository,
        *,
        provider: ViperCloudProvider | None = None,
        progress: GcsProgressSink | None = None,
    ) -> None:
        """Bind one workspace to its configured cloud repository."""
        self.root = root.resolve(strict=True)
        self.repository = repository
        self.progress = progress
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
                progress=self.progress,
            )
        if isinstance(repository, HuggingFaceRepository):
            return HuggingFaceProvider(
                self.root,
                repository.repository,
                repository.repo_type,
            )
        raise ViperCloudError("unsupported ViperCloud repository")

    @staticmethod
    def _repository_for(reference: CloudReference) -> ViperCloudRepository:
        """Recover the repository encoded by one self-describing reference."""
        if isinstance(reference, GcsFileRef):
            return GcsRepository(
                bucket=reference.bucket,
                prefix=reference.prefix,
            )
        if isinstance(reference, GcsStageResultSnapshotRef):
            return GcsRepository(
                bucket=reference.bucket,
                prefix=reference.prefix,
            )
        if isinstance(reference, HuggingFaceFileRef):
            return HuggingFaceRepository(
                repository=reference.repository,
                repo_type=reference.repo_type,
            )
        if isinstance(reference, HuggingFaceStageResultSnapshotRef):
            return HuggingFaceRepository(
                repository=reference.repository,
                repo_type=reference.repo_type,
            )
        if isinstance(
            reference,
            (ViperCloudFileRef, ViperCloudStageResultSnapshotRef),
        ):
            raise ViperCloudError(
                "provider-neutral references require the workspace repository"
            )
        raise TypeError("reference is not cloud-backed")

    @classmethod
    def for_target(cls, root: Path, target: PublicationTarget) -> ViperCloud:
        """Use an explicitly attached GCP identity when the target requires it."""
        repository = target.repository
        if target.gcp_service_account is not None:
            if not isinstance(repository, GcsRepository):
                raise ViperCloudError("attached credentials require GCS")
            credentials = Credentials(service_account_email=target.gcp_service_account)
            client = gcs_storage.Client(
                project=target.google_project_id, credentials=credentials
            )
            provider = GcsProvider(
                root, repository.bucket, prefix=repository.prefix, client=client
            )
            return cls(root, repository, provider=provider)
        return cls(root, repository)

    @classmethod
    def for_reference(cls, root: Path, reference: CloudFileRef) -> ViperCloud:
        """Construct the service that owns one self-describing cloud reference."""
        if isinstance(reference, ViperCloudFileRef):
            raise ViperCloudError(
                "provider-neutral references require the workspace repository"
            )
        return cls(root, cls._repository_for(reference))

    @classmethod
    def for_snapshot(
        cls,
        root: Path,
        snapshot: CloudStageResultSnapshotRef,
    ) -> ViperCloud:
        """Construct the service that owns one self-describing cloud snapshot."""
        if isinstance(snapshot, ViperCloudStageResultSnapshotRef):
            raise ViperCloudError(
                "provider-neutral snapshots require the workspace repository"
            )
        return cls(root, cls._repository_for(snapshot))

    def _file_location(self, location: CloudFileRef) -> CloudFileRef:
        """Resolve an older provider-neutral file through this repository."""
        if not isinstance(location, ViperCloudFileRef):
            return location
        if isinstance(self.repository, GcsRepository):
            return GcsFileRef(
                bucket=self.repository.bucket,
                prefix=self.repository.prefix,
                owner=location.owner,
                workspace=location.workspace,
                revision=location.revision,
                path=location.path,
            )
        raise ViperCloudError(
            "provider-neutral revisions cannot identify a Hugging Face commit"
        )

    def _snapshot_location(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> CloudStageResultSnapshotRef:
        """Resolve an older provider-neutral snapshot through this repository."""
        if not isinstance(snapshot, ViperCloudStageResultSnapshotRef):
            return snapshot
        if isinstance(self.repository, GcsRepository):
            return GcsStageResultSnapshotRef(
                bucket=self.repository.bucket,
                prefix=self.repository.prefix,
                owner=snapshot.owner,
                workspace=snapshot.workspace,
                revision=snapshot.revision,
            )
        raise ViperCloudError(
            "provider-neutral revisions cannot identify a Hugging Face commit"
        )

    def publish(
        self,
        destination: ViperCloudDestination,
        sources: Mapping[RepoRelPath, PublicationSource],
        *,
        attempts: int = 3,
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Publish a snapshot with the requested number of attempts."""
        return self.provider.publish(destination, sources, attempts=attempts)

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
        service = self._service_for(source_snapshot)
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
        service = self._service_for(location)
        return service.provider.fetch(service._file_location(location))

    def fetch_to_path(self, reference: ResolvedFileRef, destination: Path) -> Path:
        """Materialize a verified reference at one local workspace path."""
        location = reference.stored_at
        if not isinstance(
            location,
            (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
        ):
            raise TypeError("resolved file is not cloud-backed")
        service = self._service_for(location)
        concrete = service._file_location(location)
        return service.provider.fetch_to_path(
            concrete,
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
        service = self._service_for(snapshot)
        return service.provider.list_files(service._snapshot_location(snapshot))

    def file_ref(
        self,
        snapshot: CloudStageResultSnapshotRef,
        path: RepoRelPath,
    ) -> CloudFileRef:
        """Return the provider-specific file reference inside one snapshot."""
        service = self._service_for(snapshot)
        return service.provider.file_ref(snapshot, path)

    def verify_file(self, reference: ResolvedFileRef) -> None:
        """Verify one cloud file without changing its artifact identity."""
        location = reference.stored_at
        if not isinstance(
            location,
            (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
        ):
            raise TypeError("resolved file is not cloud-backed")
        service = self._service_for(location)
        concrete = service._file_location(location)
        service.provider.verify_file(
            concrete,
            SnapshotFileRef(
                path=location.path,
                sha256=reference.sha256,
                bytes=reference.bytes,
            ),
        )

    def verify_copy(self, value: object) -> SnapshotCopy:
        """Validate an exact snapshot copy and independently verify its cloud bytes."""
        copy = validate_snapshot_copy(SnapshotCopy.model_validate(value))
        if copy.published is None:
            raise ViperCloudError("snapshot copy is not published")
        snapshot = self._snapshot_location(copy.published)
        if self._repository_for(snapshot) != self.repository:
            raise ViperCloudError("snapshot copy belongs to another repository")
        if isinstance(self.provider, HuggingFaceProvider):
            if self.provider.read_manifest(snapshot) != copy.expected:
                raise ViperCloudError("snapshot copy manifest differs")
        elif self.list_files(snapshot) != copy.expected.files:
            raise ViperCloudError("snapshot copy file inventory differs")
        for member in copy.expected.files:
            self.verify_file(resolve_snapshot_file_ref(snapshot, member))
        return copy

    def _service_for(self, reference: CloudReference) -> ViperCloud:
        """Reuse this service or construct the service named by a reference."""
        if isinstance(
            reference,
            (ViperCloudFileRef, ViperCloudStageResultSnapshotRef),
        ):
            return self
        if self.repository == self._repository_for(reference):
            return self
        return type(self)(
            self.root,
            self._repository_for(reference),
            progress=self.progress,
        )


__all__ = ["PublicationReceipt", "PublicationTarget", "ViperCloud"]
