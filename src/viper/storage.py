"""Save and read files through the local Viper store or cloud storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import (
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ._cloud import (
    LocalSource,
    PublicationSource,
    SnapshotCopy,
    SnapshotInventory,
    SnapshotSources,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudRepository,
    canonical_json_bytes,
    manifest_revision,
    resolve_publication_source,
    source_file,
    validate_snapshot_copy,
)
from ._git_proof import GIT_PROOF_PREFIX, GitFileProof, proof_member_path
from ._offload import (
    PublicationError,
    PublicationSession,
    current_session,
    read_publication_copies,
    read_publication_receipt,
    read_publication_status,
    session_scope,
)
from ._offload import (
    retry_publication as _retry_publication,
)
from ._schema import ProtocolModel, RepoRelPath
from ._storage_locks import PayloadLocks, WorkflowReaders
from ._storage_registry import StorageRegistry
from ._verified_cache import VerifiedObjectCache
from .artifacts import ResolvedSingleFileArtifact
from .cloud import PublicationReceipt, PublicationTarget, ViperCloud
from .evidence import VerificationError
from .gcs import GcsProgressSink, stderr_gcs_progress
from .huggingface import HuggingFaceProvider
from .ids import RunId
from .references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from .repository import PathError, resolve_path
from .serialization import document_digest, write_synchronized

_CloudSource = ViperCloud | Callable[[], ViperCloud]


class LocalStoreError(RuntimeError):
    """Report an unsafe path or missing or inconsistent stored files."""


class StorageConfigurationError(ViperCloudError):
    """Report invalid storage settings or a changed run destination."""


class LocalStorageDestination(ProtocolModel):
    """Save published files in the local Viper store."""

    kind: Literal["local"] = Field(
        default="local",
        description="Discriminator selecting ROOT/.viper/store publication.",
    )


StorageDestination = Annotated[
    LocalStorageDestination | ViperCloudDestination,
    Field(discriminator="kind"),
]


class StorageSettings(ProtocolModel):
    """Choose where to publish files and whether to keep local copies."""

    destination: StorageDestination = Field(
        default_factory=LocalStorageDestination,
        description="Destination used for every immutable publication in one run.",
    )
    repository: ViperCloudRepository | None = Field(
        default=None,
        description="Cloud repository used when destination selects ViperCloud.",
    )
    offload: bool = Field(
        default=False,
        strict=True,
        description=(
            "Automatically remove managed local copies after successful workflow "
            "completion, verified cloud backing, and completion of their readers."
        ),
    )

    @model_validator(mode="after")
    def require_matching_repository(self) -> StorageSettings:
        """Require the cloud settings needed for the selected operation."""
        uses_cloud = isinstance(self.destination, ViperCloudDestination)

        if uses_cloud and self.repository is None:
            raise ValueError("viper_cloud repository is required for cloud destination")

        return self


class PublicationStatus(ProtocolModel):
    """Report background publication separately from experiment results."""

    operation_path: Path
    status: Literal["pending", "complete", "failed"]
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    error: str | None = None


class RunPromotionPolicy(ProtocolModel):
    """Choose cloud destinations for a complete run."""

    hosts: tuple[ViperCloudRepository, ...] = Field(
        min_length=1,
        description="Destination cloud repositories for graph publication.",
    )


class TransferLimits(ProtocolModel):
    """Limit disk use and simultaneous cloud connections."""

    staging_bytes: int = Field(
        gt=0, strict=True, description="Maximum bytes in the copy's working directory."
    )
    cache_bytes: int = Field(
        gt=0,
        strict=True,
        description="Maximum bytes kept in the copy's download cache.",
    )
    connections: int = Field(
        gt=0,
        strict=True,
        description="Maximum active connections used by a transfer client.",
    )


class SnapshotPublisher(Protocol):
    """Save a completed stage record and its files."""

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> tuple[StageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Save stage files and return their snapshot reference and hashes."""
        ...

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshotRef,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, PublicationSource],
    ) -> StageResultSnapshotRef:
        """Save a new stage record with files reused from an earlier snapshot."""
        ...


def content_revision(
    files: Mapping[RepoRelPath, bytes] | tuple[SnapshotFileRef, ...],
) -> str:
    """Compute a snapshot ID from file paths, byte counts and SHA-256 hashes."""
    if isinstance(files, Mapping):
        files = tuple(snapshot_file(path, raw) for path, raw in files.items())
    return manifest_revision(files)


class LocalArtifactStore:
    """Save snapshot file lists and find the files in local or cloud storage."""

    def __init__(
        self,
        repository_root: Path,
        store: RepoRelPath = ".viper/store",
        *,
        cache_root: Path | None = None,
        targets: tuple[PublicationTarget, ...] = (),
    ) -> None:
        """Choose the store and an optional separate cache for transfer work."""
        self.repository_root = repository_root.resolve(strict=True)
        self.store = store
        self.targets = targets
        try:
            self.store_root = resolve_path(
                self.repository_root, store, operation="write"
            )
        except PathError as error:
            raise LocalStoreError("local store escapes the workspace root") from error

        self.registry = StorageRegistry(self.repository_root, self.store)
        self._objects = VerifiedObjectCache(self.store_root / "objects")
        self.task_owned_cache = cache_root is not None
        download_root = (
            self._objects.root if cache_root is None else cache_root.resolve()
        )

        if not download_root.is_relative_to(self.repository_root):
            raise LocalStoreError("file cache must be inside the workspace")
        self.downloads = VerifiedObjectCache(download_root)

    def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
        """Save the files and return their snapshot ID."""
        commit, _ = self._publish(files)
        return commit

    def _publish(
        self,
        files: Mapping[RepoRelPath, PublicationSource],
        *,
        path_custody: Literal["output", "cache", "external"] | None = None,
    ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
        """Store supplied bytes and register completed files at their existing paths.

        Path callers must finish writing and give up further writes before capture.
        """
        if not files:
            raise LocalStoreError("an immutable revision requires at least one file")
        sources = {
            name: resolve_publication_source(self.repository_root, source)
            for name, source in sorted(files.items())
        }
        if path_custody is None and any(
            isinstance(source, Path) for source in sources.values()
        ):
            raise LocalStoreError(
                "registering existing files requires explicit ownership"
            )
        identities = tuple(
            source_file(self.repository_root, name, source)
            for name, source in sources.items()
        )
        commit = content_revision(identities)
        snapshot = LocalStageResultSnapshotRef(
            workspace=self.repository_root, store=self.store, commit=commit
        )
        locations: dict[RepoRelPath, tuple[LocalSource, ...]] = {}
        for member in identities:
            reference = resolve_snapshot_file_ref(snapshot, member)
            self.hold(reference)
            source = sources[member.path]
            if isinstance(source, bytes):
                path = self._objects.verified_path(reference)
                if path is None:
                    self._objects.write(reference, source)
                    path = self._objects.path(reference)
                custody: Literal["output", "cache", "external"] = "cache"
            else:
                path = source
                assert path_custody is not None
                previous = self.registry.binding(
                    reference, path.relative_to(self.repository_root).as_posix()
                )
                custody = path_custody if previous is None else previous.custody
            self._synchronize_parent(path)
            locations[member.path] = (self._observe(path, custody=custody),)
        inventory = SnapshotInventory(source=snapshot, source_files=identities)
        self.registry.register_snapshot(
            SnapshotSources(inventory=inventory, locations=locations)
        )
        session = current_session()
        if session is not None and session.root == self.repository_root:
            session.admit(inventory, locations=locations)
        return commit, identities

    def hold(self, reference: ResolvedFileRef) -> None:
        """Protect this store's file until the active workflow finishes."""
        session = current_session()
        if session is not None:
            session.hold(
                reference, repository_root=self.repository_root, store=self.store
            )

    def record_path(self, reference: ResolvedFileRef, path: Path) -> None:
        """Record a checked local copy for the workflow's later cleanup."""
        session = current_session()
        if session is not None and not self.task_owned_cache:
            session.record_path(
                reference, path, repository_root=self.repository_root, store=self.store
            )

    @staticmethod
    def _synchronize_parent(path: Path) -> None:
        """Save the directory entry before admitting durable publication work."""
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def adopt_verified_reference(
        self, reference: ResolvedFileRef, source_path: Path
    ) -> Path:
        """Keep a verified foreign file here without changing its reference."""
        self.hold(reference)
        location = reference.stored_at
        if isinstance(location, GitFileRef):
            raise TypeError("Git source retrieval remains with its Git reader")
        source = TypeAdapter(StageResultSnapshotRef).validate_python(
            location.model_dump(exclude={"path"})
        )
        record = self.registry.snapshot(source)
        if record is None:
            if isinstance(source, LocalStageResultSnapshotRef):
                original = local_artifact_store(source)
                original.hold(reference)
                record = original._local_snapshot(source)
            else:
                record = self._snapshot_record(source)
            self.registry.register_snapshot(SnapshotSources(inventory=record.inventory))
        member = SnapshotFileRef(
            path=location.path, sha256=reference.sha256, bytes=reference.bytes
        )
        if member not in record.inventory.source_files:
            raise VerificationError("adopted file differs from its snapshot inventory")
        candidate = (
            source_path
            if source_path.is_absolute()
            else self.repository_root / source_path
        )
        if candidate.is_symlink():
            raise LocalStoreError("adopted file is a symlink")
        original_path = candidate.resolve(strict=True)
        VerifiedObjectCache.verify_path(reference, original_path)
        if original_path.is_relative_to(self.repository_root):
            relative = original_path.relative_to(self.repository_root).as_posix()
            if any(
                alias.path == relative and not alias.retired
                for alias in record.locations.get(member.path, ())
            ):
                self.record_path(reference, original_path)
                return original_path
        installed = self._objects.verified_path(reference)
        if installed is None:
            temporary = self._objects.temporary_path(reference)
            try:
                try:
                    os.link(original_path, temporary)
                except OSError:
                    shutil.copyfile(original_path, temporary)
                    VerifiedObjectCache.verify_path(reference, temporary)
                installed = self._objects.adopt_verified_path(reference, temporary)
            finally:
                temporary.unlink(missing_ok=True)
            if isinstance(source, LocalStageResultSnapshotRef) and (
                original_path.is_relative_to(source.workspace)
                and source.workspace != self.repository_root
            ):
                origin = local_artifact_store(source)
                origin_record = origin.registry.snapshot(source)
                relative = original_path.relative_to(source.workspace).as_posix()
                if origin_record is not None:
                    for alias in origin_record.locations.get(member.path, ()):
                        if alias.path == relative and not alias.retired:
                            origin.registry.record_materialization(
                                source, member, original_path, custody=alias.custody
                            )
                            break
        self._synchronize_parent(installed)
        self.registry.record_materialization(source, member, installed, custody="cache")
        self.record_path(reference, installed)
        return installed

    def _observe(
        self,
        path: Path,
        *,
        custody: Literal["output", "cache", "external"],
    ) -> LocalSource:
        """Record the path and file-system details of a file already checked."""
        status = path.stat()
        return LocalSource(
            path=path.relative_to(self.repository_root).as_posix(),
            observed_stat=(
                status.st_dev,
                status.st_ino,
                status.st_mtime_ns,
                status.st_ctime_ns,
            ),
            custody=custody,
        )

    def snapshot(
        self,
        files: Mapping[RepoRelPath, bytes],
    ) -> LocalStageResultSnapshotRef:
        """Save the files and return their snapshot reference."""
        return LocalStageResultSnapshotRef(
            workspace=self.repository_root,
            store=self.store,
            commit=self.publish(files),
        )

    def resolved_files(
        self,
        files: Mapping[RepoRelPath, bytes],
    ) -> tuple[ResolvedFileRef, ...]:
        """Save the files and return a reference for each one."""
        commit, identities = self._publish(files)
        snapshot = LocalStageResultSnapshotRef(
            workspace=self.repository_root, store=self.store, commit=commit
        )
        return tuple(
            resolve_snapshot_file_ref(snapshot, member) for member in identities
        )

    def _local_snapshot(
        self,
        source: LocalStageResultSnapshotRef,
    ) -> SnapshotSources:
        """Read the saved file list or register files from the older store layout."""
        registered = self.registry.snapshot(source)
        if registered is not None:
            return registered

        if source.workspace != self.repository_root or source.store != self.store:
            raise LocalStoreError("local snapshot belongs to a different store")

        directory = resolve_path(
            self.repository_root,
            f"{self.store}/{source.commit}",
            operation="write",
        )
        if not directory.is_dir():
            raise LocalStoreError("local snapshot revision is missing")

        members = []
        locations = {}
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise LocalStoreError("local snapshot contains a symlink")
            if path.is_file():
                member_path = path.relative_to(directory).as_posix()
                member = source_file(self.repository_root, member_path, path)
                members.append(member)
                locations[member_path] = (self._observe(path, custody="cache"),)

        try:
            inventory = SnapshotInventory(
                source=source,
                source_files=tuple(sorted(members, key=lambda member: member.path)),
            )
        except ValueError as error:
            raise LocalStoreError(
                "local snapshot inventory differs from its revision"
            ) from error

        record = SnapshotSources(
            inventory=inventory,
            locations=locations,
        )
        return self._register_snapshot(record)

    def _register_snapshot(self, record: SnapshotSources) -> SnapshotSources:
        """Save the snapshot's file list and look up its known local copies."""
        self.registry.register_snapshot(record)
        registered = self.registry.snapshot(record.inventory.source)
        if registered is None:
            raise LocalStoreError("registered snapshot is unavailable")
        return registered

    def _snapshot_record(
        self, source: StageResultSnapshotRef, *, cloud: _CloudSource | None = None
    ) -> SnapshotSources:
        """Get the complete snapshot file list from the registry or cloud storage."""
        if isinstance(source, LocalStageResultSnapshotRef):
            return self._local_snapshot(source)
        registered = None if self.task_owned_cache else self.registry.snapshot(source)
        if registered is not None:
            return registered
        service = self._cloud(source, cloud)
        record = SnapshotSources(
            inventory=SnapshotInventory(
                source=source, source_files=service.list_files(source)
            )
        )
        if not self.task_owned_cache:
            return self._register_snapshot(record)
        return record

    def snapshot_files(
        self,
        snapshot: StageResultSnapshotRef,
        *,
        cloud: _CloudSource | None = None,
    ) -> tuple[SnapshotFileRef, ...]:
        """List every recorded file with its byte count and SHA-256."""
        return self._snapshot_record(snapshot, cloud=cloud).inventory.source_files

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshotRef,
        *,
        cloud: _CloudSource | None = None,
    ) -> tuple[RepoRelPath, ...]:
        """Return the complete recorded file list, including files absent locally."""
        return tuple(
            member.path for member in self.snapshot_files(snapshot, cloud=cloud)
        )

    def _reference(
        self, location: StorageModel, *, cloud: _CloudSource | None = None
    ) -> ResolvedFileRef:
        """Look up the file's recorded size and SHA-256 hash."""
        if isinstance(location, GitFileRef):
            raise TypeError("Git source retrieval remains with its Git reader")
        source = TypeAdapter(StageResultSnapshotRef).validate_python(
            location.model_dump(exclude={"path"})
        )
        for member in self._snapshot_record(source, cloud=cloud).inventory.source_files:
            if member.path == location.path:
                reference = resolve_snapshot_file_ref(source, member)
                self.hold(reference)
                return reference
        raise LocalStoreError("immutable file is outside the snapshot inventory")

    def reference(
        self, location: StorageModel, *, cloud: _CloudSource | None = None
    ) -> ResolvedFileRef:
        """Read a file's expected identity from its complete snapshot inventory."""
        return self._reference(location, cloud=cloud)

    def fetch(
        self, location: StorageModel, *, cloud: _CloudSource | None = None
    ) -> bytes:
        """Read and check the file at the recorded address."""
        return self.read(self._reference(location, cloud=cloud), cloud=cloud)

    def path(self, location: StorageModel) -> Path:
        """Find the file's current local path and check its bytes."""
        return self.resolve(self._reference(location))

    def resolve(
        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
    ) -> Path:
        """Find and check a registered original or stored copy of the file."""
        resolved = self._resolve(reference, as_bytes=False, cloud=cloud)
        assert isinstance(resolved, Path)
        return resolved

    def read(
        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
    ) -> bytes:
        """Read the file once and check its byte count and SHA-256."""
        return self.read_resolved(reference, cloud=cloud)[0]

    def read_resolved(
        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
    ) -> tuple[bytes, Path]:
        """Read and check the file, returning its bytes and local path."""
        resolved = self._resolve(reference, as_bytes=True, cloud=cloud)
        assert isinstance(resolved, tuple)
        return resolved

    def _check_git_reference(self, reference: ResolvedFileRef) -> None:
        """Require a proven commit/path binding before reusing bytes by content hash."""
        if not isinstance(reference.stored_at, GitFileRef):
            return
        proof = self.registry.git_file_proof(reference.stored_at)
        if proof is None:
            raise VerificationError(
                "Git source has no verified commit and path binding"
            )
        if (proof.reference.sha256, proof.reference.bytes) != (
            reference.sha256,
            reference.bytes,
        ):
            raise VerificationError(
                "Git source identity differs from its commit and path"
            )

    def cached_read(self, reference: ResolvedFileRef) -> tuple[bytes, Path] | None:
        """Read cached bytes if their byte count and SHA-256 match the reference."""
        self.hold(reference)
        self._check_git_reference(reference)
        raw = self.downloads.read(reference)
        if raw is None:
            return None
        path = self.downloads.path(reference)
        self.record_path(reference, path)
        return raw, path

    def cache_verified_bytes(self, reference: ResolvedFileRef, raw: bytes) -> Path:
        """Store bytes that the caller has already checked against the reference."""
        self.hold(reference)
        self.downloads.write(reference, raw)
        path = self.downloads.path(reference)
        self.record_path(reference, path)
        return path

    def _download(
        self,
        reference: ResolvedFileRef,
        remote: ResolvedFileRef,
        cloud: ViperCloud,
        cache: VerifiedObjectCache,
    ) -> Path:
        """Download, verify and install one file, retaining its exact cloud proof."""
        self.hold(reference)
        temporary = cache.temporary_path(reference)
        try:
            if isinstance(cloud.provider, HuggingFaceProvider):
                cloud.provider.stream_files = True
            restored = cloud.fetch_to_path(remote, temporary)
            installed = cache.adopt_verified_path(reference, restored)
        finally:
            temporary.unlink(missing_ok=True)
        self._synchronize_parent(installed)
        if not self.task_owned_cache and isinstance(
            remote.stored_at, (GcsFileRef, HuggingFaceFileRef)
        ):
            self.registry.register_verified_file(remote)
        return installed

    def _resolve(
        self,
        reference: ResolvedFileRef,
        *,
        as_bytes: bool,
        cloud: _CloudSource | None,
        local_only: bool = False,
    ) -> tuple[bytes, Path] | Path:
        """Check local bytes or restore them from an already verified cloud copy."""
        self.hold(reference)
        self._check_git_reference(reference)
        location = reference.stored_at
        git_source = isinstance(location, GitFileRef)
        source: StageResultSnapshotRef | GitSource
        if isinstance(location, GitFileRef):
            source = GitSource.model_validate(location.model_dump(exclude={"path"}))
            record = None
        else:
            source = TypeAdapter(StageResultSnapshotRef).validate_python(
                location.model_dump(exclude={"path"})
            )
            record = (
                self._snapshot_record(source, cloud=cloud)
                if isinstance(source, LocalStageResultSnapshotRef)
                else self.registry.snapshot(source)
            )
        member = SnapshotFileRef(
            path=location.path, sha256=reference.sha256, bytes=reference.bytes
        )
        failure: VerificationError | None = None
        if record is not None and member not in record.inventory.source_files:
            raise VerificationError("resolved file differs from its snapshot inventory")
        aliases = sorted(
            ()
            if self.task_owned_cache
            and not isinstance(source, (LocalStageResultSnapshotRef, GitSource))
            else self.registry.locations(reference)
            if record is None
            else record.locations.get(member.path, ()),
            key=lambda alias: alias.custody == "cache",
        )
        for alias in aliases:
            if alias.retired:
                continue
            try:
                path = resolve_path(self.repository_root, alias.path, operation="read")
                status = path.stat()
                if (status.st_dev, status.st_ino) != alias.observed_stat[:2]:
                    continue
                observed = (
                    status.st_dev,
                    status.st_ino,
                    status.st_mtime_ns,
                    status.st_ctime_ns,
                )
                if as_bytes:
                    raw = VerifiedObjectCache.read_path(reference, path)
                    if observed != alias.observed_stat and record is not None:
                        self.registry.record_materialization(
                            source, member, path, custody=alias.custody
                        )
                    self.record_path(reference, path)
                    return raw, path
                checked = VerifiedObjectCache.verify_path(reference, path)
                if observed != alias.observed_stat and record is not None:
                    self.registry.record_materialization(
                        source, member, checked, custody=alias.custody
                    )
                self.record_path(reference, checked)
                return checked
            except (FileNotFoundError, PathError):
                continue
            except VerificationError as error:
                if alias.custody != "cache":
                    raise
                failure = error
        cache = (
            self._objects
            if isinstance(source, LocalStageResultSnapshotRef)
            and not self.task_owned_cache
            else self.downloads
        )
        cached = cache.read(reference) if as_bytes else cache.verified_path(reference)
        if cached is not None:
            if not self.task_owned_cache and record is not None:
                self.registry.record_materialization(
                    source, member, cache.path(reference), custody="cache"
                )
            self.record_path(reference, cache.path(reference))
            if isinstance(cached, bytes):
                return cached, cache.path(reference)
            return cached
        if isinstance(source, LocalStageResultSnapshotRef) and (
            source.workspace != self.repository_root or source.store != self.store
        ):
            try:
                original = local_artifact_store(source, targets=self.targets)
                original.hold(reference)
                return original._resolve(
                    reference, as_bytes=as_bytes, cloud=None, local_only=True
                )
            except (OSError, LocalStoreError):
                pass
        if local_only:
            if failure is not None:
                raise failure
            raise LocalStoreError("registered local payload is unavailable")
        candidates: list[
            tuple[
                ResolvedFileRef,
                StageResultSnapshotRef | GitSource | None,
                SnapshotFileRef,
            ]
        ] = []
        original_cloud = not isinstance(
            source, (LocalStageResultSnapshotRef, GitSource)
        )
        if original_cloud and record is not None:
            candidates.append((reference, source, member))
        bind_original = record is not None and not git_source
        backings = (
            self.registry.backings(source, identity=reference)
            if not self.task_owned_cache
            or isinstance(source, (LocalStageResultSnapshotRef, GitSource))
            else ()
        )
        for copy in backings:
            if copy.published is None:
                continue
            for remote_member in copy.expected.files:
                if (remote_member.sha256, remote_member.bytes) == (
                    reference.sha256,
                    reference.bytes,
                ):
                    candidates.append(
                        (
                            resolve_snapshot_file_ref(copy.published, remote_member),
                            source if bind_original else copy.source,
                            member if bind_original else remote_member,
                        )
                    )
                    break
        for remote in self.registry.file_backings(reference):
            remote_member = SnapshotFileRef(
                path=remote.stored_at.path, sha256=remote.sha256, bytes=remote.bytes
            )
            candidates.append(
                (
                    remote,
                    source if bind_original else None,
                    member if bind_original else remote_member,
                )
            )
        if original_cloud and record is None:
            candidates.append((reference, source, member))
        if not candidates:
            if failure is not None:
                raise failure
            raise LocalStoreError("registered local payload is unavailable")
        restore_error: Exception | None = None
        for download, binding_source, binding_member in candidates:
            try:
                if (
                    record is None
                    and binding_source == source
                    and not isinstance(source, GitSource)
                ):
                    record = self._snapshot_record(source, cloud=cloud)
                    if member not in record.inventory.source_files:
                        raise VerificationError(
                            "resolved file differs from its snapshot inventory"
                        )
                service = self._cloud(
                    download.stored_at, cloud if download == reference else None
                )
                installed = self._download(reference, download, service, cache)
            except (OSError, ViperCloudError, VerificationError) as error:
                restore_error = error
                continue
            if not self.task_owned_cache:
                if binding_source is None:
                    binding_source = TypeAdapter(
                        StageResultSnapshotRef
                    ).validate_python(download.stored_at.model_dump(exclude={"path"}))
                    self._snapshot_record(binding_source, cloud=service)
                self.registry.record_materialization(
                    binding_source, binding_member, installed, custody="cache"
                )
            self.record_path(reference, installed)
            return (installed.read_bytes(), installed) if as_bytes else installed
        assert restore_error is not None
        raise restore_error

    def _cloud(
        self,
        location: StorageModel | CloudStageResultSnapshotRef,
        cloud: _CloudSource | None = None,
    ) -> ViperCloud:
        """Create or reuse a cloud service after local lookup fails."""
        if cloud is not None:
            return cloud() if callable(cloud) else cloud
        if isinstance(location, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)):
            return viper_cloud(self.repository_root)
        if not isinstance(
            location,
            (
                GcsFileRef,
                HuggingFaceFileRef,
                GcsStageResultSnapshotRef,
                HuggingFaceStageResultSnapshotRef,
            ),
        ):
            raise TypeError("reference is not cloud-backed")
        session = current_session()
        targets = self.targets or (() if session is None else session.targets)
        repository = ViperCloud._repository_for(location)
        for target in targets:
            if target.repository == repository:
                return ViperCloud.for_target(self.repository_root, target)
        if isinstance(location, (GcsFileRef, GcsStageResultSnapshotRef)) and any(
            target.gcp_service_account is not None for target in targets
        ):
            raise StorageConfigurationError(
                "cloud source has no matching attached target"
            )
        if isinstance(
            location, (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef)
        ):
            return ViperCloud.for_snapshot(self.repository_root, location)
        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            return ViperCloud.for_reference(self.repository_root, location)
        raise TypeError("reference is not cloud-backed")


def local_artifact_store(
    location: LocalFileRef | LocalStageResultSnapshotRef,
    *,
    targets: tuple[PublicationTarget, ...] = (),
) -> LocalArtifactStore:
    """Open the store named in the original local reference."""
    return LocalArtifactStore(location.workspace, location.store, targets=targets)


class LocalSnapshotPublisher:
    """Save stage records and their files in the local store."""

    def __init__(self, root: Path):
        """Choose the workspace and its local store."""
        self.root = root.resolve(strict=True)
        self.store = LocalArtifactStore(self.root)

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> tuple[LocalStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Save a stage snapshot, retaining original files inside a workflow."""
        session = current_session()
        if session is not None and session.root == self.root:
            commit, members = self.store._publish(
                {resolved_stage_path: resolved_stage, **files}, path_custody="output"
            )
        else:
            payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
            for path, source in files.items():
                payload[path] = read_publication_source(self.root, source)
            commit, members = self.store._publish(payload)
        snapshot = LocalStageResultSnapshotRef(
            workspace=self.store.repository_root,
            store=self.store.store,
            commit=commit,
        )
        return snapshot, members

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshotRef,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, PublicationSource],
    ) -> LocalStageResultSnapshotRef:
        """Reuse checked local files while preserving their existing ownership."""
        session = current_session()
        managed = session is not None and session.root == self.root
        payload: dict[RepoRelPath, PublicationSource] = {
            resolved_stage_path: resolved_stage
        }
        for target_path, member in files.items():
            if target_path == resolved_stage_path:
                raise StorageConfigurationError("reused file replaces resolved stage")
            source = source_bytes[target_path]
            actual = source_file(self.root, member.path, source)
            if (actual.sha256, actual.bytes) != (member.sha256, member.bytes):
                raise StorageConfigurationError("reused snapshot file identity changed")
            payload[target_path] = (
                source if managed else read_publication_source(self.root, source)
            )
        commit, _ = self.store._publish(
            payload, path_custody="cache" if managed else None
        )
        return LocalStageResultSnapshotRef(
            workspace=self.store.repository_root, store=self.store.store, commit=commit
        )


def _parse_storage_destination(value: object) -> StorageDestination:
    """Read the configured storage destination."""
    if value == "local":
        return LocalStorageDestination()
    if not isinstance(value, str) or not value.startswith("viper://"):
        raise StorageConfigurationError("storage destination is invalid")
    address = value.removeprefix("viper://")
    if any(token in address for token in ("?", "#")):
        raise StorageConfigurationError("storage destination is invalid")
    parts = address.split("/")
    if len(parts) != 2 or not all(parts):
        raise StorageConfigurationError("storage destination is invalid")
    owner, workspace = (part.replace("-", "_") for part in parts)
    try:
        return ViperCloudDestination(owner=owner, workspace=workspace)
    except ValidationError as error:
        raise StorageConfigurationError("storage destination is invalid") from error


def load_storage_settings(root: Path) -> StorageSettings:
    """Read storage settings from viper.toml."""
    try:
        marker = resolve_path(root, "viper.toml", operation="read")
        document = tomllib.loads(marker.read_text(encoding="utf-8"))
        storage = document.get("storage", {})
        if not isinstance(storage, dict):
            raise StorageConfigurationError("storage table is invalid")
        payload = dict(storage)
        payload["destination"] = _parse_storage_destination(
            payload.get("destination", "local")
        )
        repository = document.get("viper_cloud")
        if repository is not None and not isinstance(repository, dict):
            raise StorageConfigurationError("viper_cloud table is invalid")
        payload["repository"] = repository
        return StorageSettings.model_validate(payload)
    except (OSError, PathError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise StorageConfigurationError("storage settings are invalid") from error


@contextmanager
def workflow(
    repository_root: Path,
    *,
    session: PublicationSession | None = None,
    targets: tuple[PublicationTarget, ...] | None = None,
) -> Generator[PublicationSession, None, None]:
    """Keep related work together and queue publication without waiting for uploads."""
    root = repository_root.resolve(strict=True)
    owner = session or current_session()
    if targets is not None and owner is not None and targets != owner.targets:
        raise PublicationError("nested workflow changes publication destinations")
    if targets is None:
        if owner is not None:
            targets = owner.targets
        else:
            settings = load_storage_settings(root)
            targets = ()
            if isinstance(settings.destination, ViperCloudDestination):
                assert settings.repository is not None
                targets = (
                    PublicationTarget(
                        repository=settings.repository, destination=settings.destination
                    ),
                )
    with session_scope(root, targets=targets, session=session) as selected:
        if selected.before_close is None:
            selected.before_close = lambda: _publish_git_sources(root, selected)
        yield selected


def _publish_git_sources(root: Path, session: PublicationSession) -> None:
    """Queue verified source files and Git metadata through the existing publisher."""
    if not session.targets:
        return
    store = LocalArtifactStore(root, session.store, targets=session.targets)
    groups: dict[GitSource, dict[RepoRelPath, PublicationSource]] = {}
    for reference in session.used_files():
        location = reference.stored_at
        if not isinstance(location, GitFileRef):
            continue
        proof = store.registry.git_file_proof(location)
        if proof is None or (proof.reference.sha256, proof.reference.bytes) != (
            reference.sha256,
            reference.bytes,
        ):
            continue
        path = store._objects.verified_path(reference)
        if path is None:
            raise VerificationError(
                "verified Git source disappeared before publication"
            )
        source = GitSource.model_validate(location.model_dump(exclude={"path"}))
        files = groups.setdefault(source, {})
        files[location.path] = path
        files[proof_member_path(proof.reference)] = canonical_json_bytes(proof)
    for files in groups.values():
        store._publish(files, path_custody="cache")


def publication_status(
    operation_path: Path,
    *,
    wait: bool = False,
    timeout_seconds: float | None = None,
) -> PublicationStatus:
    """Read background publication status, optionally waiting for it to finish."""
    return PublicationStatus.model_validate(
        read_publication_status(
            operation_path, wait=wait, timeout_seconds=timeout_seconds
        )
    )


def retry_publication(operation_path: Path) -> None:
    """Retry failed uploads from saved work without rerunning the experiment."""
    _retry_publication(operation_path)


def publication_copies(
    operation_path: Path,
    source: StageResultSnapshotRef,
    *,
    wait: bool = False,
    timeout_seconds: float | None = None,
) -> tuple[SnapshotCopy, ...]:
    """Observe verified copies of one snapshot while the workflow is still open."""
    return read_publication_copies(
        operation_path, source, wait=wait, timeout_seconds=timeout_seconds
    )


def publication_receipt(operation_path: Path) -> PublicationReceipt:
    """Return the portable receipt after every cloud destination is verified."""
    return PublicationReceipt.model_validate(read_publication_receipt(operation_path))


@contextmanager
def _restore_holds(
    root: Path, references: tuple[ResolvedFileRef, ...]
) -> Generator[None, None, None]:
    """Protect every imported file until its local records have been saved."""
    session = current_session()
    if session is not None:
        for reference in references:
            session.hold(reference, repository_root=root)
        yield
    else:
        with WorkflowReaders(PayloadLocks(root)) as readers:
            for reference in references:
                readers.hold(reference)
            yield


def import_publication_copies(
    repository_root: Path,
    copies: Sequence[SnapshotCopy | Mapping[str, object]],
    *,
    targets: tuple[PublicationTarget, ...] = (),
) -> None:
    """Restore complete portable cloud copies and retain their original references.

    A new copy's full inventory and bytes are checked before its cloud proof is
    registered. Downloaded files remain in the shared cache. Identical proofs
    already verified here are reused. Importing does not complete a workflow.
    """
    root = repository_root.resolve(strict=True)
    normalized = tuple(
        validate_snapshot_copy(SnapshotCopy.model_validate(value)) for value in copies
    )
    references = tuple(
        resolve_snapshot_file_ref(copy.source, member)
        for copy in normalized
        for member in copy.source_files
    )
    with _restore_holds(root, references):
        store = LocalArtifactStore(root, targets=targets)
        registry = store.registry
        for copy in normalized:
            published = copy.published
            if published is None:
                raise VerificationError(
                    "portable cloud copy has not completed publication"
                )
            repository = ViperCloud._repository_for(published)
            matched = next(
                (
                    target
                    for target in targets
                    if target.repository == repository
                    and target.destination.owner == copy.expected.owner
                    and target.destination.workspace == copy.expected.workspace
                ),
                None,
            )
            if targets and matched is None:
                raise StorageConfigurationError(
                    "publication target does not match cloud copy"
                )
            if copy in registry.backings(copy.source):
                _import_git_file_proofs(store, copy)
                continue
            cloud = (
                ViperCloud.for_target(root, matched)
                if matched is not None
                else ViperCloud.for_snapshot(root, published)
            )
            if isinstance(cloud.provider, HuggingFaceProvider):
                if cloud.provider.read_manifest(published) != copy.expected:
                    raise VerificationError(
                        "cloud inventory differs from its saved proof"
                    )
            elif cloud.list_files(published) != copy.expected.files:
                raise VerificationError("cloud inventory differs from its saved proof")
            locations: dict[RepoRelPath, tuple[LocalSource, ...]] = {}
            for member in copy.source_files:
                original = resolve_snapshot_file_ref(copy.source, member)
                installed = store._download(
                    original,
                    resolve_snapshot_file_ref(published, member),
                    cloud,
                    store._objects,
                )
                locations[member.path] = (store._observe(installed, custody="cache"),)
            registry.register_snapshot(
                SnapshotSources(
                    inventory=SnapshotInventory(
                        source=copy.source, source_files=copy.source_files
                    ),
                    locations=locations,
                )
            )
            proof = f".viper/store/proofs/{document_digest(copy)}.json"
            path = resolve_path(root, proof, operation="write")
            write_synchronized(path, canonical_json_bytes(copy))
            registry.register_backing(copy, proof)
            _import_git_file_proofs(store, copy)
            for member in copy.source_files:
                original = resolve_snapshot_file_ref(copy.source, member)
                store.record_path(original, store._objects.path(original))


def _import_git_file_proofs(store: LocalArtifactStore, copy: SnapshotCopy) -> None:
    """Check Git metadata against imported code before recording its source address."""
    assert copy.published is not None
    for member in copy.source_files:
        if not member.path.startswith(GIT_PROOF_PREFIX):
            continue
        key = "git:" + member.path.removeprefix(GIT_PROOF_PREFIX).removesuffix(".json")
        proof = store.registry.git_file_proof_by_key(key)
        known = (
            proof is not None
            and snapshot_file(member.path, canonical_json_bytes(proof)) == member
        )
        if not known:
            metadata = store.resolve(resolve_snapshot_file_ref(copy.published, member))
            proof = GitFileProof.model_validate_json(metadata.read_bytes())
        assert proof is not None
        if proof_member_path(proof.reference) != member.path:
            raise VerificationError("Git proof metadata has the wrong source address")
        code = next(
            (
                file
                for file in copy.source_files
                if (file.sha256, file.bytes)
                == (proof.reference.sha256, proof.reference.bytes)
            ),
            None,
        )
        if code is None:
            raise VerificationError(
                "Git proof has no matching source file in its snapshot"
            )
        if not known:
            path = store.resolve(resolve_snapshot_file_ref(copy.published, code))
            store.registry.register_git_file(proof, path.read_bytes())


def import_publication_receipt(
    repository_root: Path,
    receipt: PublicationReceipt | Mapping[str, object],
    *,
    targets: tuple[PublicationTarget, ...] = (),
) -> None:
    """Restore receipt copies and inventories while keeping original references."""
    parsed = PublicationReceipt.model_validate(receipt)
    references = (
        *parsed.used,
        *parsed.file_copies,
        *(
            resolve_snapshot_file_ref(copy.source, member)
            for copy in parsed.copies
            for member in copy.source_files
        ),
    )
    with _restore_holds(repository_root.resolve(strict=True), references):
        import_publication_copies(repository_root, parsed.copies, targets=targets)
        store = LocalArtifactStore(repository_root)
        for inventory in parsed.inventories:
            store.registry.register_snapshot(SnapshotSources(inventory=inventory))
        for reference in parsed.file_copies:
            known = reference in store.registry.file_backings(reference)
            location = reference.stored_at
            if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
                raise VerificationError("portable file needs an exact cloud address")
            repository = ViperCloud._repository_for(location)
            matched = next(
                (
                    target
                    for target in targets
                    if target.repository == repository
                    and (
                        not isinstance(location, GcsFileRef)
                        or (
                            target.destination.owner == location.owner
                            and target.destination.workspace == location.workspace
                        )
                    )
                ),
                None,
            )
            if targets and matched is None:
                raise StorageConfigurationError(
                    "publication target does not match cloud file"
                )
            if known and (isinstance(location, GcsFileRef) or not targets):
                continue
            cloud = (
                ViperCloud.for_target(store.repository_root, matched)
                if matched is not None
                else ViperCloud.for_reference(store.repository_root, location)
            )
            source = TypeAdapter(CloudStageResultSnapshotRef).validate_python(
                location.model_dump(exclude={"path"})
            )
            if matched is not None and isinstance(cloud.provider, HuggingFaceProvider):
                manifest = cloud.provider.read_manifest(source)
                if (manifest.owner, manifest.workspace) != (
                    matched.destination.owner,
                    matched.destination.workspace,
                ):
                    raise VerificationError("cloud file belongs to another destination")
            if known:
                continue
            record = store._snapshot_record(source, cloud=cloud)
            member = SnapshotFileRef(
                path=location.path, sha256=reference.sha256, bytes=reference.bytes
            )
            if member not in record.inventory.source_files:
                raise VerificationError(
                    "cloud file differs from its snapshot inventory"
                )
            installed = store._download(reference, reference, cloud, store._objects)
            store.registry.record_materialization(
                source, member, installed, custody="cache"
            )
            store.record_path(reference, installed)


def read_publication_source(root: Path, source: PublicationSource) -> bytes:
    """Read source bytes from memory or a file inside the workspace."""
    resolved = resolve_publication_source(root, source)
    return resolved if isinstance(resolved, bytes) else resolved.read_bytes()


def _verify_reuse_source(source: SnapshotFileRef, raw: bytes) -> None:
    """Reject bytes that differ from the recorded byte count or SHA-256."""
    if len(raw) != source.bytes or hashlib.sha256(raw).hexdigest() != source.sha256:
        raise StorageConfigurationError("reused snapshot file identity changed")


def viper_cloud(root: Path) -> ViperCloud:
    """Create the cloud service configured for this workspace."""
    settings = load_storage_settings(root)
    if settings.repository is None:
        raise StorageConfigurationError("viper_cloud repository is required")
    return ViperCloud(root, settings.repository, progress=_gcs_progress_sink())


def _gcs_progress_sink() -> GcsProgressSink | None:
    """Choose whether to report GCS transfer progress."""
    if os.environ.get("VIPER_GCS_PROGRESS") == "0":
        return None
    return stderr_gcs_progress


class ViperCloudSnapshotPublisher:
    """Publish stage records and files to the configured cloud destination."""

    def __init__(
        self,
        root: Path,
        destination: ViperCloudDestination,
    ) -> None:
        """Choose the workspace and cloud destination."""
        self.root = root.resolve(strict=True)
        self.destination = destination
        self.cloud = viper_cloud(self.root)

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Upload stage files and return the snapshot reference and file hashes."""
        return self.cloud.publish(
            self.destination,
            {resolved_stage_path: resolved_stage, **files},
        )

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshotRef,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, PublicationSource],
    ) -> CloudStageResultSnapshotRef:
        """Publish checked files reused from an earlier cloud snapshot."""
        if not isinstance(
            source_snapshot,
            (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef),
        ):
            raise StorageConfigurationError("cloud reuse requires a cloud snapshot")
        if resolved_stage_path in files:
            raise StorageConfigurationError("reused file replaces resolved stage")
        return self.cloud.publish_reuse(
            destination=self.destination,
            resolved_stage_path=resolved_stage_path,
            resolved_stage=resolved_stage,
            source_snapshot=source_snapshot,
            files=files,
            source_bytes={
                name: read_publication_source(self.root, source)
                for name, source in source_bytes.items()
            },
        )


def create_snapshot_publisher(
    root: Path,
    destination: StorageDestination,
) -> SnapshotPublisher:
    """Choose local capture in a workflow or the configured synchronous publisher."""
    session = current_session()
    if isinstance(destination, LocalStorageDestination) or (
        session is not None and session.root == root.resolve(strict=True)
    ):
        return LocalSnapshotPublisher(root)
    return ViperCloudSnapshotPublisher(root, destination)


def publish_resolved_files(
    root: Path,
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> dict[RepoRelPath, ResolvedFileRef]:
    """Save raw file references and queue cloud publication inside a workflow."""
    session = current_session()
    managed = session is not None and session.root == root.resolve(strict=True)
    store = LocalArtifactStore(root)
    if isinstance(destination, LocalStorageDestination) or managed:
        if managed:
            commit, members = store._publish(files, path_custody="output")
            snapshot = LocalStageResultSnapshotRef(
                workspace=store.repository_root, store=store.store, commit=commit
            )
            references = {
                member.path: resolve_snapshot_file_ref(snapshot, member)
                for member in members
            }
        else:
            payload = {
                path: read_publication_source(root, source)
                for path, source in files.items()
            }
            references = {
                reference.stored_at.path: reference
                for reference in store.resolved_files(payload)
                if isinstance(reference.stored_at, LocalFileRef)
            }
    else:
        references = viper_cloud(root).resolved_files(destination, files)
    first = next(iter(references.values()))
    snapshot = TypeAdapter(StageResultSnapshotRef).validate_python(
        first.stored_at.model_dump(exclude={"path"})
    )
    members = tuple(
        SnapshotFileRef(path=name, sha256=reference.sha256, bytes=reference.bytes)
        for name, reference in sorted(references.items())
    )
    store.registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=snapshot, source_files=members)
        )
    )
    for member in members:
        store.registry.register_artifact(
            snapshot,
            member.path,
            ResolvedSingleFileArtifact(relative_path=member.path, file=member),
        )
    return references


def bind_run_destination(
    root: Path,
    run_id: RunId,
    destination: StorageDestination,
) -> StorageDestination:
    """Save the run's destination and reject a later change."""
    relative = f".viper/workspaces/{run_id}/storage-destination.json"
    try:
        target = resolve_path(root, relative, operation="write")
    except PathError as error:
        raise StorageConfigurationError(
            "storage destination path is invalid"
        ) from error
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            destination.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(raw)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)

    try:
        stored = TypeAdapter(StorageDestination).validate_json(target.read_bytes())
    except (OSError, ValidationError) as error:
        raise StorageConfigurationError("stored run destination is invalid") from error
    if stored != destination:
        raise StorageConfigurationError("storage_destination_changed")
    return stored


def snapshot_file(path: RepoRelPath, raw: bytes) -> SnapshotFileRef:
    """Record a file's path, byte count and SHA-256."""
    return SnapshotFileRef(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
