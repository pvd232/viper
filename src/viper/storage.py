"""Publish and retrieve immutable files through the local VIPER store."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from ._cloud import (
    PublicationSource,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudRepository,
    resolve_publication_source,
)
from ._schema import ProtocolModel, RepoRelPath
from .cloud import ViperCloud
from .ids import LocalStoreId, RunId
from .references import (
    CloudStageResultSnapshotRef,
    GcsStageResultSnapshotRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
)
from .repository import PathError, resolve_path


class LocalStoreError(RuntimeError):
    """Report an unsafe path or inconsistent immutable-store revision."""


class StorageConfigurationError(ViperCloudError):
    """Report invalid storage configuration or a changed run destination."""


class LocalStorageDestination(ProtocolModel):
    """Select repository-local immutable publication."""

    kind: Literal["local"] = Field(
        default="local",
        description="Discriminator selecting ROOT/.viper/store publication.",
    )


StorageDestination = Annotated[
    LocalStorageDestination | ViperCloudDestination,
    Field(discriminator="kind"),
]


class StorageSettings(ProtocolModel):
    """Store the immutable-publication settings parsed from viper.toml."""

    destination: StorageDestination = Field(
        default_factory=LocalStorageDestination,
        description="Destination used for every immutable publication in one run.",
    )
    repository: ViperCloudRepository | None = Field(
        default=None,
        description="Cloud repository used when destination selects ViperCloud.",
    )

    @model_validator(mode="after")
    def require_matching_repository(self) -> StorageSettings:
        """Require a repository when publication selects ViperCloud."""
        if (
            isinstance(self.destination, ViperCloudDestination)
            and self.repository is None
        ):
            raise ValueError("viper_cloud repository is required for cloud destination")
        return self


class SnapshotPublisher(Protocol):
    """Publish one completed stage snapshot to a selected destination."""

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> StageResultSnapshot:
        """Publish one resolved stage document and its existing member files."""
        ...

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshot,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> StageResultSnapshot:
        """Publish a target stage document and remapped source snapshot files."""
        ...


def content_revision(files: Mapping[RepoRelPath, bytes]) -> str:
    """Derive one revision identity from ordered paths and file identities."""
    digest = hashlib.sha256()
    for path, raw in sorted(files.items()):
        encoded_path = str(path).encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(hashlib.sha256(raw).digest())
    return digest.hexdigest()


class LocalArtifactStore:
    """Manage content-addressed output revisions beneath one repository root."""

    def __init__(self, repository_root: Path, store: RepoRelPath = ".viper/store"):
        """Bind the immutable store beneath one canonical workspace root."""
        self.repository_root = repository_root.resolve(strict=True)
        self.store = store
        try:
            self.store_root = resolve_path(
                self.repository_root, store, operation="write"
            )
        except PathError as error:
            raise LocalStoreError("local store escapes the workspace root") from error
        self.identity_path = self.store_root / ".identity"

    def _read_identity(self) -> LocalStoreId:
        """Read and validate this local store's durable identity."""
        try:
            value = self.identity_path.read_text(encoding="ascii").strip()
            return TypeAdapter(LocalStoreId).validate_python(value)
        except (OSError, UnicodeError, ValidationError) as error:
            raise LocalStoreError("local store identity is invalid") from error

    def _create_identity(self) -> LocalStoreId:
        """Create this local store's identity without replacing a peer writer's ID."""
        self.store_root.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(16)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.store_root,
                prefix=".identity.",
                delete=False,
                mode="w",
                encoding="ascii",
            ) as stream:
                temporary = Path(stream.name)
                stream.write(f"{value}\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.identity_path)
            except FileExistsError:
                pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self._read_identity()

    @property
    def store_id(self) -> LocalStoreId:
        """Return this store's durable identity, creating it when absent."""
        if self.identity_path.exists():
            return self._read_identity()
        return self._create_identity()

    def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
        """Write one immutable revision and return its content-derived identity."""
        if not files:
            raise LocalStoreError("an immutable revision requires at least one file")
        _ = self.store_id
        commit = content_revision(files)
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
        return commit

    def snapshot(
        self,
        files: Mapping[RepoRelPath, bytes],
    ) -> LocalStageResultSnapshotRef:
        """Publish one stage snapshot and return its immutable location."""
        return LocalStageResultSnapshotRef(
            workspace=self.repository_root,
            store=self.store,
            store_id=self.store_id,
            commit=self.publish(files),
        )

    def resolved_files(
        self,
        files: Mapping[RepoRelPath, bytes],
    ) -> tuple[ResolvedFileRef, ...]:
        """Publish related files and return exact references to each file."""
        commit = self.publish(files)
        return tuple(
            ResolvedFileRef(
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
                stored_at=LocalFileRef(
                    workspace=self.repository_root,
                    store=self.store,
                    store_id=self.store_id,
                    commit=commit,
                    path=path,
                ),
            )
            for path, raw in sorted(files.items())
        )

    def fetch(self, location: StorageModel) -> bytes:
        """Retrieve one local-store file after validating its revision path."""
        return self.path(location).read_bytes()

    def path(self, location: StorageModel) -> Path:
        """Resolve one local-store file directly from its immutable reference."""
        if not isinstance(location, LocalFileRef):
            raise TypeError("LocalArtifactStore can resolve only LocalFileRef")

        if location.workspace != self.repository_root or location.store != self.store:
            raise LocalStoreError("local file belongs to a different store")
        if location.store_id != self.store_id:
            raise LocalStoreError("local file belongs to a different store instance")

        revision_root = (self.store_root / location.commit).resolve()
        target = (revision_root / location.path).resolve()
        if not target.is_relative_to(revision_root) or not target.is_file():
            raise LocalStoreError("local immutable file is missing")
        return target

    def list_snapshot_files(
        self,
        snapshot: LocalStageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable local snapshot."""
        if snapshot.workspace != self.repository_root or snapshot.store != self.store:
            raise LocalStoreError("local snapshot belongs to a different store")
        if snapshot.store_id != self.store_id:
            raise LocalStoreError(
                "local snapshot belongs to a different store instance"
            )

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
    """Open the local store named by one serialized local reference."""
    return LocalArtifactStore(location.workspace, location.store)


class LocalSnapshotPublisher:
    """Publish stage snapshots through one repository-local artifact store."""

    def __init__(self, root: Path):
        """Bind publication to the selected workspace root."""
        self.root = root.resolve(strict=True)
        self.store = LocalArtifactStore(self.root)

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> LocalStageResultSnapshotRef:
        """Read validated member paths and publish one local stage snapshot."""
        payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
        for path, source in files.items():
            payload[path] = read_publication_source(self.root, source)
        return self.store.snapshot(payload)

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshot,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> LocalStageResultSnapshotRef:
        """Publish verified local snapshot files under their target paths."""
        payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
        for target_path, source_file in files.items():
            if target_path == resolved_stage_path:
                raise StorageConfigurationError("reused file replaces resolved stage")
            raw = source_bytes[target_path]
            _verify_reuse_source(source_file, raw)
            payload[target_path] = raw
        return self.store.snapshot(payload)


def _parse_storage_destination(value: object) -> StorageDestination:
    """Parse one public storage destination string into its protocol model."""
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
    try:
        return ViperCloudDestination(owner=parts[0], workspace=parts[1])
    except ValidationError as error:
        raise StorageConfigurationError("storage destination is invalid") from error


def load_storage_settings(root: Path) -> StorageSettings:
    """Load storage destination and cloud repository from ``viper.toml``."""
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
    """Return bytes from one in-memory or root-confined publication source."""
    resolved = resolve_publication_source(root, source)
    return resolved if isinstance(resolved, bytes) else resolved.read_bytes()


def _verify_reuse_source(source: SnapshotFileRef, raw: bytes) -> None:
    """Reject source bytes that do not match their snapshot identity."""
    if len(raw) != source.bytes or hashlib.sha256(raw).hexdigest() != source.sha256:
        raise StorageConfigurationError("reused snapshot file identity changed")


def viper_cloud(root: Path) -> ViperCloud:
    """Construct the cloud service selected by workspace configuration."""
    settings = load_storage_settings(root)
    if settings.repository is None:
        raise StorageConfigurationError("viper_cloud repository is required")
    return ViperCloud(root, settings.repository)


class ViperCloudSnapshotPublisher:
    """Publish stage snapshots through the workspace ViperCloud service."""

    def __init__(
        self,
        root: Path,
        destination: ViperCloudDestination,
    ) -> None:
        """Bind publication to one root and logical cloud destination."""
        self.root = root.resolve(strict=True)
        self.destination = destination
        self.cloud = viper_cloud(self.root)

    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> CloudStageResultSnapshotRef:
        """Publish one stage and return its sealed provider snapshot."""
        snapshot, _ = self.cloud.publish(
            self.destination,
            {resolved_stage_path: resolved_stage, **files},
        )
        return snapshot

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshot,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> CloudStageResultSnapshotRef:
        """Publish verified reused payloads under their target paths."""
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
    """Create the stage publisher selected by workspace configuration."""
    if isinstance(destination, LocalStorageDestination):
        return LocalSnapshotPublisher(root)
    return ViperCloudSnapshotPublisher(root, destination)


def publish_resolved_files(
    root: Path,
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> dict[RepoRelPath, ResolvedFileRef]:
    """Publish standalone files and return references by canonical path."""
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
    """Create or validate the immutable publication destination for one run."""
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
    """Describe one exact file included in a local stage snapshot."""
    return SnapshotFileRef(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
