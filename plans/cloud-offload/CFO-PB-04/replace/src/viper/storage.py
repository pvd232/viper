"""Save and read files through the local Viper store or cloud storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Callable, Mapping
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
    SnapshotInventory,
    SnapshotSources,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudRepository,
    manifest_revision,
    resolve_publication_source,
    source_file,
)
from ._schema import ProtocolModel, RepoRelPath
from ._storage_registry import StorageRegistry
from ._verified_cache import VerifiedObjectCache
from .cloud import ViperCloud
from .evidence import VerificationError
from .gcs import GcsProgressSink, stderr_gcs_progress
from .huggingface import HuggingFaceProvider
from .ids import RunId
from .references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
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
        source_bytes: Mapping[RepoRelPath, bytes],
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
    ) -> None:
        """Choose the store and an optional separate cache for transfer work."""
        self.repository_root = repository_root.resolve(strict=True)
        self.store = store
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
        self, files: Mapping[RepoRelPath, bytes]
    ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
        """Store each distinct file by hash and save the complete snapshot file list."""
        if not files:
            raise LocalStoreError("an immutable revision requires at least one file")
        identities = tuple(
            snapshot_file(path, raw) for path, raw in sorted(files.items())
        )
        commit = content_revision(identities)
        snapshot = LocalStageResultSnapshotRef(
            workspace=self.repository_root, store=self.store, commit=commit
        )
        locations = {}
        for member in identities:
            reference = resolve_snapshot_file_ref(snapshot, member)
            path = self._objects.verified_path(reference)
            if path is None:
                self._objects.write(reference, files[member.path])
                path = self._objects.path(reference)
            locations[member.path] = (self._observe(path, custody="cache"),)
        self.registry.register_snapshot(
            SnapshotSources(
                inventory=SnapshotInventory(source=snapshot, source_files=identities),
                locations=locations,
            )
        )
        return commit, identities

    def _observe(
        self, path: Path, *, custody: Literal["output", "cache", "external"]
    ) -> LocalSource:
        """Record the path and file-system details of a file already checked."""
        status = path.stat()
        return LocalSource(
            path=path.relative_to(self.repository_root).as_posix(),
            observed_stat=(
                status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns
            ),
            custody=custody,
        )

    def snapshot(
        self, files: Mapping[RepoRelPath, bytes]
    ) -> LocalStageResultSnapshotRef:
        """Save the files and return their snapshot reference."""
        return LocalStageResultSnapshotRef(
            workspace=self.repository_root, store=self.store, commit=self.publish(files)
        )

    def resolved_files(
        self, files: Mapping[RepoRelPath, bytes]
    ) -> tuple[ResolvedFileRef, ...]:
        """Save the files and return a reference for each one."""
        commit, identities = self._publish(files)
        snapshot = LocalStageResultSnapshotRef(
            workspace=self.repository_root, store=self.store, commit=commit
        )
        return tuple(
            resolve_snapshot_file_ref(snapshot, member) for member in identities
        )

    def _local_snapshot(self, source: LocalStageResultSnapshotRef) -> SnapshotSources:
        """Read the saved file list or register files from the older store layout."""
        registered = self.registry.snapshot(source)
        if registered is not None:
            return registered
        if source.workspace != self.repository_root or source.store != self.store:
            raise LocalStoreError("local snapshot belongs to a different store")
        directory = resolve_path(
            self.repository_root, f"{self.store}/{source.commit}", operation="write"
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
        record = SnapshotSources(inventory=inventory, locations=locations)
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
                return resolve_snapshot_file_ref(source, member)
        raise LocalStoreError("immutable file is outside the snapshot inventory")

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

    def cached_read(self, reference: ResolvedFileRef) -> tuple[bytes, Path] | None:
        """Read cached bytes if their byte count and SHA-256 match the reference."""
        raw = self.downloads.read(reference)
        return None if raw is None else (raw, self.downloads.path(reference))

    def cache_verified_bytes(self, reference: ResolvedFileRef, raw: bytes) -> Path:
        """Store bytes that the caller has already checked against the reference."""
        self.downloads.write(reference, raw)
        return self.downloads.path(reference)

    def _resolve(
        self,
        reference: ResolvedFileRef,
        *,
        as_bytes: bool,
        cloud: _CloudSource | None,
    ) -> tuple[bytes, Path] | Path:
        """Check a registered local copy or restore a missing cloud file."""
        location = reference.stored_at
        if isinstance(location, GitFileRef):
            raise TypeError("Git source retrieval remains with its Git reader")
        source = TypeAdapter(StageResultSnapshotRef).validate_python(
            location.model_dump(exclude={"path"})
        )
        record = self._snapshot_record(source, cloud=cloud)
        member = SnapshotFileRef(
            path=location.path, sha256=reference.sha256, bytes=reference.bytes
        )
        failure: VerificationError | None = None
        if member not in record.inventory.source_files:
            raise VerificationError(
                "resolved file differs from its snapshot inventory"
            )
        aliases = sorted(
            record.locations.get(member.path, ()),
            key=lambda alias: alias.custody == "cache",
        )
        for alias in aliases:
            if alias.retired:
                continue
            try:
                path = resolve_path(
                    self.repository_root, alias.path, operation="read"
                )
                status = path.stat()
                if (status.st_dev, status.st_ino) != alias.observed_stat[:2]:
                    continue
                if as_bytes:
                    return VerifiedObjectCache.read_path(reference, path), path
                return VerifiedObjectCache.verify_path(reference, path)
            except (FileNotFoundError, PathError):
                continue
            except VerificationError as error:
                if alias.custody != "cache":
                    raise
                failure = error
        cache = (
            self._objects
            if isinstance(source, LocalStageResultSnapshotRef)
            else self.downloads
        )
        cached = cache.read(reference) if as_bytes else cache.verified_path(reference)
        if cached is not None:
            if not self.task_owned_cache:
                self.registry.record_materialization(
                    source, member, cache.path(reference), custody="cache"
                )
            if isinstance(cached, bytes):
                return cached, cache.path(reference)
            return cached
        if isinstance(source, LocalStageResultSnapshotRef):
            if failure is not None:
                raise failure
            raise LocalStoreError("registered local payload is unavailable")
        service = self._cloud(location, cloud)
        if isinstance(service.provider, HuggingFaceProvider):
            service.provider.stream_files = True
        temporary = cache.temporary_path(reference)
        try:
            restored = service.fetch_to_path(reference, temporary)
            installed = cache.adopt_verified_path(reference, restored)
        finally:
            temporary.unlink(missing_ok=True)
        if not self.task_owned_cache:
            self.registry.record_materialization(
                source, member, installed, custody="cache"
            )
        return (installed.read_bytes(), installed) if as_bytes else installed

    def _cloud(
        self,
        location: StorageModel | CloudStageResultSnapshotRef,
        cloud: _CloudSource | None = None,
    ) -> ViperCloud:
        """Create or reuse a cloud service after local lookup fails."""
        if cloud is not None:
            return cloud() if callable(cloud) else cloud
        if isinstance(
            location, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)
        ):
            return viper_cloud(self.repository_root)
        if isinstance(
            location, (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef)
        ):
            return ViperCloud.for_snapshot(self.repository_root, location)
        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            return ViperCloud.for_reference(self.repository_root, location)
        raise TypeError("reference is not cloud-backed")

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



def local_artifact_store(
    location: LocalFileRef | LocalStageResultSnapshotRef,
) -> LocalArtifactStore:
    """Open the store named in the original local reference."""
    return LocalArtifactStore(location.workspace, location.store)


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
        """Save local stage files and return their references and hashes."""
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
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> LocalStageResultSnapshotRef:
        """Save a stage record with checked files from an earlier snapshot."""
        payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
        for target_path, member in files.items():
            if target_path == resolved_stage_path:
                raise StorageConfigurationError("reused file replaces resolved stage")
            raw = source_bytes[target_path]
            _verify_reuse_source(member, raw)
            payload[target_path] = raw
        return self.store.snapshot(payload)


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
        source_bytes: Mapping[RepoRelPath, bytes],
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
            source_bytes=source_bytes,
        )


def create_snapshot_publisher(
    root: Path,
    destination: StorageDestination,
) -> SnapshotPublisher:
    """Choose the local or cloud publisher from the storage settings."""
    if isinstance(destination, LocalStorageDestination):
        return LocalSnapshotPublisher(root)
    return ViperCloudSnapshotPublisher(root, destination)


def publish_resolved_files(
    root: Path,
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> dict[RepoRelPath, ResolvedFileRef]:
    """Save files and return their exact references keyed by file path."""
    if isinstance(destination, LocalStorageDestination):
        payload = {
            path: read_publication_source(root, source)
            for path, source in files.items()
        }
        references = LocalArtifactStore(root).resolved_files(payload)
        return {
            reference.stored_at.path: reference
            for reference in references
            if isinstance(reference.stored_at, LocalFileRef)
        }
    return viper_cloud(root).resolved_files(destination, files)


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
