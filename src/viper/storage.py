"""Publish and retrieve immutable files through the local VIPER store."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, TypeAdapter, ValidationError

from ._schema import ProtocolModel, RepoRelPath
from .ids import HumanId, RunId
from .project import PathError, resolve_path
from .references import (
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
)


class LocalStoreError(RuntimeError):
    """Report an unsafe path or inconsistent immutable-store revision."""


class StorageConfigurationError(RuntimeError):
    """Report invalid storage configuration or a changed run destination."""


class LocalStorageDestination(ProtocolModel):
    """Select repository-local immutable publication."""

    kind: Literal["local"] = Field(
        default="local",
        description="Discriminator selecting ROOT/.viper/store publication.",
    )


class ViperCloudDestination(ProtocolModel):
    """Select one Viper Cloud project for immutable publication."""

    kind: Literal["viper_cloud"] = Field(
        default="viper_cloud",
        description="Discriminator selecting Viper Cloud publication.",
    )
    owner: HumanId = Field(description="Viper Cloud account owning the project.")
    project: HumanId = Field(description="Viper Cloud project receiving the files.")


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


PublicationSource = bytes | Path


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


def _content_commit(files: Mapping[RepoRelPath, bytes]) -> str:
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

    def __init__(self, project_root: Path, store: RepoRelPath = ".viper/store"):
        """Bind the immutable store beneath one canonical project root."""
        self.project_root = project_root.resolve(strict=True)
        self.store = store
        try:
            self.store_root = resolve_path(self.project_root, store, operation="write")
        except PathError as error:
            raise LocalStoreError("local store escapes the project root") from error

    def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
        """Write one immutable revision and return its content-derived identity."""
        if not files:
            raise LocalStoreError("an immutable revision requires at least one file")
        commit = _content_commit(files)
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
            store=self.store,
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
                    store=self.store,
                    commit=commit,
                    path=path,
                ),
            )
            for path, raw in sorted(files.items())
        )

    def fetch(self, location: StorageModel) -> bytes:
        """Retrieve one local-store file after validating its revision path."""
        if not isinstance(location, LocalFileRef):
            raise TypeError("LocalArtifactStore can retrieve only LocalFileRef")

        if location.store != self.store:
            raise LocalStoreError("local file belongs to a different store")

        revision_root = (self.store_root / location.commit).resolve()
        target = (revision_root / location.path).resolve()
        if not target.is_relative_to(revision_root) or not target.is_file():
            raise LocalStoreError("local immutable file is missing")

        return target.read_bytes()

    def list_snapshot_files(
        self,
        snapshot: LocalStageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable local snapshot."""
        if snapshot.store != self.store:
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


class LocalSnapshotPublisher:
    """Publish stage snapshots through one repository-local artifact store."""

    def __init__(self, root: Path):
        """Bind publication to the selected project root."""
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
            payload[path] = _read_publication_source(self.root, source)
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
        return ViperCloudDestination(owner=parts[0], project=parts[1])
    except ValidationError as error:
        raise StorageConfigurationError("storage destination is invalid") from error


def load_storage_settings(root: Path) -> StorageSettings:
    """Load the storage table from the selected project's viper.toml file."""
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
        return StorageSettings.model_validate(payload)
    except (OSError, PathError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise StorageConfigurationError("storage settings are invalid") from error


def _read_publication_source(root: Path, source: PublicationSource) -> bytes:
    """Return bytes from one in-memory or root-confined publication source."""
    if isinstance(source, bytes):
        return source
    project_root = root.resolve(strict=True)
    candidate = source if source.is_absolute() else project_root / source
    try:
        relative = candidate.relative_to(project_root).as_posix()
        validated = resolve_path(project_root, relative, operation="read")
    except (OSError, ValueError, PathError) as error:
        raise StorageConfigurationError(
            "storage publication source is invalid"
        ) from error
    return validated.read_bytes()


def create_snapshot_publisher(
    root: Path,
    destination: StorageDestination,
) -> SnapshotPublisher:
    """Create the stage publisher for one implemented storage destination."""
    if isinstance(destination, LocalStorageDestination):
        return LocalSnapshotPublisher(root)
    raise StorageConfigurationError("viper_cloud publication is not implemented")


def publish_resolved_files(
    root: Path,
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> dict[RepoRelPath, ResolvedFileRef]:
    """Publish standalone files and return references keyed by requested path."""
    if not isinstance(destination, LocalStorageDestination):
        raise StorageConfigurationError("viper_cloud publication is not implemented")
    payload = {
        path: _read_publication_source(root, source) for path, source in files.items()
    }
    references = LocalArtifactStore(root).resolved_files(payload)
    return {
        reference.stored_at.path: reference
        for reference in references
        if isinstance(reference.stored_at, LocalFileRef)
    }


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
