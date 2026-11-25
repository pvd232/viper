"""Save and read files through the local Viper store or cloud storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import (
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ._cloud import (
    PublicationSource,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudRepository,
    manifest_revision,
    resolve_publication_source,
)
from ._schema import ProtocolModel, RepoRelPath
from .cloud import ViperCloud
from .gcs import GcsProgressSink, stderr_gcs_progress
from .ids import RunId
from .references import (
    CloudStageResultSnapshotRef,
    GcsStageResultSnapshotRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
)
from .repository import PathError, resolve_path


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

        if self.offload and not uses_cloud:
            raise ValueError("storage.offload requires a viper_cloud destination")

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
    """Save snapshot files and find their local paths."""

    def __init__(self, repository_root: Path, store: RepoRelPath = ".viper/store"):
        """Choose the workspace and local store."""
        self.repository_root = repository_root.resolve(strict=True)
        self.store = store
        try:
            self.store_root = resolve_path(
                self.repository_root, store, operation="write"
            )
        except PathError as error:
            raise LocalStoreError("local store escapes the workspace root") from error

    def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
        """Save the files and return their snapshot ID."""
        commit, _ = self._publish(files)
        return commit

    def _publish(
        self, files: Mapping[RepoRelPath, bytes]
    ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
        """Save the files and return their snapshot ID and file hashes."""
        if not files:
            raise LocalStoreError("an immutable revision requires at least one file")
        identities = tuple(
            snapshot_file(path, raw) for path, raw in sorted(files.items())
        )
        commit = content_revision(identities)
        revision_root = self.store_root / commit
        for relative_path, raw in sorted(files.items()):
            target = (revision_root / relative_path).resolve()
            if not target.is_relative_to(revision_root):
                raise LocalStoreError("published file escapes its immutable revision")
            if target.exists():
                if not target.is_file() or target.read_bytes() != raw:
                    raise LocalStoreError("immutable revision contains different bytes")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
            )
            try:
                with os.fdopen(file_descriptor, "wb") as temporary_file:
                    temporary_file.write(raw)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_name, target)
            finally:
                temporary_path = Path(temporary_name)
                if temporary_path.exists():
                    temporary_path.unlink()
        return commit, identities

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
        return tuple(
            ResolvedFileRef(
                sha256=identity.sha256,
                bytes=identity.bytes,
                stored_at=LocalFileRef(
                    workspace=self.repository_root,
                    store=self.store,
                    commit=commit,
                    path=identity.path,
                ),
            )
            for identity in identities
        )

    def fetch(self, location: StorageModel) -> bytes:
        """Read and check the file at the recorded address."""
        return self.path(location).read_bytes()

    def path(self, location: StorageModel) -> Path:
        """Find the file at its recorded local store path."""
        if not isinstance(location, LocalFileRef):
            raise TypeError("LocalArtifactStore can resolve only LocalFileRef")

        if location.workspace != self.repository_root or location.store != self.store:
            raise LocalStoreError("local file belongs to a different store")

        revision_root = (self.store_root / location.commit).resolve()
        target = (revision_root / location.path).resolve()
        if not target.is_relative_to(revision_root) or not target.is_file():
            raise LocalStoreError("local immutable file is missing")
        return target

    def list_snapshot_files(
        self,
        snapshot: LocalStageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """Return the complete recorded file list, including files absent locally."""
        if snapshot.workspace != self.repository_root or snapshot.store != self.store:
            raise LocalStoreError("local snapshot belongs to a different store")

        revision_root = (self.store_root / snapshot.commit).resolve()
        if not revision_root.is_dir():
            raise LocalStoreError("local snapshot revision is missing")

        paths: list[RepoRelPath] = []
        for path in sorted(revision_root.rglob("*")):
            if path.is_symlink():
                raise LocalStoreError("local snapshot contains a symlink")
            if path.is_file():
                paths.append(path.relative_to(revision_root).as_posix())
        return tuple(paths)


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
        for target_path, source_file in files.items():
            if target_path == resolved_stage_path:
                raise StorageConfigurationError("reused file replaces resolved stage")
            raw = source_bytes[target_path]
            _verify_reuse_source(source_file, raw)
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
