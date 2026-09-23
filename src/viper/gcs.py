"""Store sealed VIPER revisions in Google Cloud Storage."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Literal
from urllib.parse import quote

from google.api_core.exceptions import GoogleAPIError, PreconditionFailed
from google.cloud import storage
from pydantic import Field, ValidationError, model_validator
from requests import RequestException

from ._cloud import (
    PublicationSource,
    RevisionManifest,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudProvider,
    canonical_json_bytes,
    manifest_revision,
    resolve_publication_source,
)
from ._schema import SHA256, ProtocolModel, RepoRelPath
from .ids import HumanId
from .references import (
    CloudFileRef,
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    SnapshotFileRef,
)

GCS_OPERATION_TIMEOUT_SECONDS: int = 300
GCS_MAX_WORKERS: int = 16
GCS_SLICED_FETCH_MIN_BYTES: int = 64 * 1024 * 1024
GCS_SLICED_FETCH_CHUNK_BYTES: int = 16 * 1024 * 1024
GCS_SLICED_FETCH_MAX_WORKERS: int = 4
GCS_SLICED_FETCH_PROGRESS_BYTES: int = 64 * 1024 * 1024
GCS_RANGE_FETCH_ATTEMPTS: int = 3
GCS_RANGE_FETCH_READ_TIMEOUT_SECONDS: int = 60

GcsProgressPhase = Literal[
    "manifest_cache_hit",
    "manifest_load_start",
    "manifest_load_done",
    "upload_start",
    "upload_done",
    "upload_reuse",
    "copy_start",
    "copy_done",
    "copy_reuse",
    "seal_start",
    "seal_done",
    "fetch_start",
    "fetch_done",
    "stream_fetch_start",
    "stream_fetch_sliced_start",
    "stream_fetch_range_start",
    "stream_fetch_range_done",
    "stream_fetch_range_retry",
    "stream_fetch_progress",
    "stream_fetch_sliced_done",
    "stream_fetch_python_start",
    "stream_fetch_python_done",
    "stream_fetch_done",
    "verify_start",
    "verify_done",
]


class GcsProgressEvent(ProtocolModel):
    """Describe one GCS operation boundary for publication and restore diagnostics."""

    phase: GcsProgressPhase = Field(description="GCS operation phase.")
    bucket: str = Field(description="GCS bucket used by the operation.")
    key: str = Field(description="GCS object key used by the operation.")
    owner: HumanId | None = Field(default=None, description="Logical Viper owner.")
    workspace: HumanId | None = Field(
        default=None,
        description="Logical Viper workspace.",
    )
    revision: SHA256 | None = Field(
        default=None,
        description="Content-derived Viper revision when known.",
    )
    path: RepoRelPath | None = Field(
        default=None,
        description="Repository-relative artifact path when known.",
    )
    source_key: str | None = Field(
        default=None,
        description="Source GCS object key for server-side copies.",
    )
    bytes: int | None = Field(default=None, description="Expected object byte count.")
    file_count: int | None = Field(
        default=None,
        description="Number of manifest members when the operation handles a seal.",
    )


GcsProgressSink = Callable[[GcsProgressEvent], None]


def format_gcs_progress_event(event: GcsProgressEvent) -> str:
    """Render one GCS progress event as a compact stderr line."""
    details = [
        f"phase={event.phase}",
        f"bucket={event.bucket}",
        f"key={event.key}",
    ]
    if event.path is not None:
        details.append(f"path={event.path}")
    if event.bytes is not None:
        details.append(f"bytes={event.bytes}")
    if event.file_count is not None:
        details.append(f"files={event.file_count}")
    if event.source_key is not None:
        details.append(f"source={event.source_key}")
    return "viper gcs " + " ".join(details)


def stderr_gcs_progress(event: GcsProgressEvent) -> None:
    """Write one GCS progress event to stderr without touching command stdout."""
    print(format_gcs_progress_event(event), file=sys.stderr, flush=True)


class _DigestWriter:
    """Count and hash chunks written by the GCS downloader."""

    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.bytes = 0

    def write(self, chunk: bytes) -> int:
        """Consume one downloaded chunk."""
        self.digest.update(chunk)
        self.bytes += len(chunk)
        return len(chunk)


class GcsStorageProbeReceipt(ProtocolModel):
    """Record one successful GCS publication and byte-for-byte restoration."""

    schema_version: Literal[1] = Field(
        default=1,
        description="GCS storage-probe receipt schema version.",
    )
    passed: Literal[True] = Field(
        default=True,
        description="Whether publication, restoration, and digest comparison passed.",
    )
    artifact_uri: str = Field(
        min_length=1,
        description="Immutable viper URI restored by the probe.",
    )
    sha256: SHA256 = Field(
        description="SHA-256 digest of the bytes published by the probe."
    )
    restored_sha256: SHA256 = Field(
        description="SHA-256 digest recomputed after restoring the cloud object."
    )

    @model_validator(mode="after")
    def require_matching_digests(self) -> GcsStorageProbeReceipt:
        """Reject a receipt whose restored bytes differ from its source."""
        if self.sha256 != self.restored_sha256:
            raise ValueError("GCS probe restored different bytes")
        return self


class GcsProvider(ViperCloudProvider):
    """Store sealed VIPER revisions in one Google Cloud Storage bucket."""

    def __init__(
        self,
        root: Path,
        bucket: str,
        *,
        prefix: str = "viper",
        client: storage.Client | None = None,
        operation_timeout: int = GCS_OPERATION_TIMEOUT_SECONDS,
        max_workers: int = GCS_MAX_WORKERS,
        sliced_fetch_min_bytes: int = GCS_SLICED_FETCH_MIN_BYTES,
        sliced_fetch_chunk_bytes: int = GCS_SLICED_FETCH_CHUNK_BYTES,
        sliced_fetch_max_workers: int = GCS_SLICED_FETCH_MAX_WORKERS,
        range_fetch_attempts: int = GCS_RANGE_FETCH_ATTEMPTS,
        range_fetch_read_timeout: int = GCS_RANGE_FETCH_READ_TIMEOUT_SECONDS,
        progress: GcsProgressSink | None = None,
    ) -> None:
        """Bind publication sources and object keys to one workspace and bucket."""
        super().__init__(root)
        if max_workers < 1:
            raise ValueError("GCS max_workers must be positive")
        if sliced_fetch_min_bytes < 0:
            raise ValueError("GCS sliced fetch threshold must be non-negative")
        if sliced_fetch_chunk_bytes < 1:
            raise ValueError("GCS sliced fetch chunk size must be positive")
        if sliced_fetch_max_workers < 1:
            raise ValueError("GCS sliced fetch max_workers must be positive")
        if range_fetch_attempts < 1:
            raise ValueError("GCS range fetch attempts must be positive")
        if range_fetch_read_timeout < 1:
            raise ValueError("GCS range fetch read timeout must be positive")
        prefix_path = PurePosixPath(prefix)
        if (
            prefix_path.is_absolute()
            or not prefix_path.parts
            or any(part in {"", ".", ".."} for part in prefix_path.parts)
        ):
            raise ValueError("GCS prefix must be a non-empty relative path")
        self.prefix = prefix_path.as_posix()
        self.client = client or storage.Client()
        self.bucket_name = bucket
        self.bucket = self.client.bucket(bucket)
        self.operation_timeout = operation_timeout
        self.max_workers = max_workers
        self.sliced_fetch_min_bytes = sliced_fetch_min_bytes
        self.sliced_fetch_chunk_bytes = sliced_fetch_chunk_bytes
        self.sliced_fetch_max_workers = sliced_fetch_max_workers
        self.range_fetch_attempts = range_fetch_attempts
        self.range_fetch_read_timeout = range_fetch_read_timeout
        self.progress = progress
        self._manifest_cache: dict[
            tuple[HumanId, HumanId, SHA256], RevisionManifest
        ] = {}

    def _emit_progress(
        self,
        phase: GcsProgressPhase,
        *,
        key: str,
        owner: HumanId | None = None,
        workspace: HumanId | None = None,
        revision: SHA256 | None = None,
        path: RepoRelPath | None = None,
        source_key: str | None = None,
        bytes: int | None = None,
        file_count: int | None = None,
    ) -> None:
        """Send one structured GCS progress event to the configured sink."""
        if self.progress is None:
            return
        self.progress(
            GcsProgressEvent(
                phase=phase,
                bucket=self.bucket_name,
                key=key,
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
                source_key=source_key,
                bytes=bytes,
                file_count=file_count,
            )
        )

    def _run_parallel(self, operations: list[Callable[[], None]]) -> None:
        """Run independent GCS operations with bounded parallelism."""
        if len(operations) <= 1 or self.max_workers == 1:
            for operation in operations:
                operation()
            return
        workers = min(self.max_workers, len(operations))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(lambda operation: operation(), operations))

    def _revision_prefix(
        self,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> str:
        """Return the prefix before an unchanged repository-relative file path."""
        return f"{self.prefix}/{owner}/{workspace}/{revision}"

    def _file_key(
        self,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
    ) -> str:
        """Return the object key for one exact workspace-relative path."""
        return f"{self._revision_prefix(owner, workspace, revision)}/{path}"

    def _manifest_key(
        self,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> str:
        """Return the seal object stored beside, rather than inside, the revision."""
        return f"{self._revision_prefix(owner, workspace, revision)}.manifest.json"

    def _upload_exact(
        self,
        key: str,
        source: PublicationSource,
        *,
        sha256: SHA256,
        size: int,
        owner: HumanId | None = None,
        workspace: HumanId | None = None,
        revision: SHA256 | None = None,
        path: RepoRelPath | None = None,
    ) -> None:
        """Create one object once and stream validated file-backed sources."""
        resolved = resolve_publication_source(self.root, source)
        if isinstance(resolved, bytes):
            observed_size = len(resolved)
            observed_sha256 = hashlib.sha256(resolved).hexdigest()
        else:
            observed_size = resolved.stat().st_size
            with resolved.open("rb") as stream:
                observed_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        if observed_size != size or observed_sha256 != sha256:
            raise ViperCloudError("GCS upload source identity changed")
        blob = self.bucket.blob(key)
        blob.metadata = {"sha256": sha256, "bytes": str(size)}
        self._emit_progress(
            "upload_start",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=size,
        )
        try:
            if isinstance(resolved, bytes):
                blob.upload_from_string(
                    resolved,
                    content_type="application/octet-stream",
                    if_generation_match=0,
                    checksum="auto",
                    timeout=self.operation_timeout,
                )
            else:
                blob.upload_from_filename(
                    str(resolved),
                    content_type="application/octet-stream",
                    if_generation_match=0,
                    checksum="auto",
                    timeout=self.operation_timeout,
                )
            self._emit_progress(
                "upload_done",
                key=key,
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
                bytes=size,
            )
        except PreconditionFailed:
            if not self._existing_object_has_identity(
                key,
                sha256=sha256,
                size=size,
            ):
                raise ViperCloudError(
                    "GCS object already contains different bytes"
                ) from None
            self._emit_progress(
                "upload_reuse",
                key=key,
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
                bytes=size,
            )

    def _existing_object_has_identity(
        self,
        key: str,
        *,
        sha256: SHA256,
        size: int,
    ) -> bool:
        """Check one already-written object by metadata and generation-locked bytes."""
        blob = self.bucket.blob(key)
        blob.reload(timeout=self.operation_timeout)
        metadata = blob.metadata or {}
        if metadata.get("sha256") != sha256 or metadata.get("bytes") != str(size):
            return False
        if blob.generation is None:
            raise ViperCloudError("GCS existing object has no immutable generation")
        observed = _DigestWriter()
        blob.download_to_file(
            observed,
            if_generation_match=blob.generation,
            checksum="auto",
            timeout=self.operation_timeout,
        )
        return observed.bytes == size and observed.digest.hexdigest() == sha256

    def _load_manifest(
        self,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> RevisionManifest:
        """Load and validate the seal before exposing any revision member."""
        cache_key = (owner, workspace, revision)
        cached = self._manifest_cache.get(cache_key)
        if cached is not None:
            self._emit_progress(
                "manifest_cache_hit",
                key=self._manifest_key(owner, workspace, revision),
                owner=owner,
                workspace=workspace,
                revision=revision,
            )
            return cached
        try:
            key = self._manifest_key(*cache_key)
            self._emit_progress(
                "manifest_load_start",
                key=key,
                owner=owner,
                workspace=workspace,
                revision=revision,
            )
            raw = self.bucket.blob(key).download_as_bytes(
                checksum="auto", timeout=self.operation_timeout
            )
            manifest = RevisionManifest.model_validate_json(raw)
        except (GoogleAPIError, KeyError, ValidationError) as error:
            raise ViperCloudError("GCS revision is not sealed") from error
        if (
            manifest.owner != owner
            or manifest.workspace != workspace
            or manifest.revision != revision
        ):
            raise ViperCloudError("GCS manifest names another revision")
        self._manifest_cache[cache_key] = manifest
        self._emit_progress(
            "manifest_load_done",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            bytes=len(raw),
        )
        return manifest

    def upload(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        source: PublicationSource,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Upload one immutable file while leaving its revision unsealed."""
        key = self._file_key(owner, workspace, revision, path)
        self._upload_exact(
            key,
            source,
            sha256=sha256,
            size=bytes,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
        )

    def copy(
        self,
        *,
        source: GcsFileRef,
        target: GcsFileRef,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Copy one sealed source object without downloading its payload."""
        source_files = {
            file.path: file
            for file in self._load_manifest(
                source.owner,
                source.workspace,
                source.revision,
            ).files
        }
        if source_files.get(source.path) != SnapshotFileRef(
            path=source.path,
            sha256=sha256,
            bytes=bytes,
        ):
            raise ViperCloudError("GCS copy source identity changed")
        source_blob = self.bucket.blob(
            self._file_key(
                source.owner,
                source.workspace,
                source.revision,
                source.path,
            )
        )
        source_blob.reload(timeout=self.operation_timeout)
        if source_blob.generation is None:
            raise ViperCloudError("GCS copy source has no generation")
        target_key = self._file_key(
            target.owner,
            target.workspace,
            target.revision,
            target.path,
        )
        self._emit_progress(
            "copy_start",
            key=target_key,
            owner=target.owner,
            workspace=target.workspace,
            revision=target.revision,
            path=target.path,
            source_key=source_blob.name,
            bytes=bytes,
        )
        try:
            self.bucket.copy_blob(
                source_blob,
                self.bucket,
                new_name=target_key,
                if_generation_match=0,
                if_source_generation_match=source_blob.generation,
                timeout=self.operation_timeout,
            )
            self._emit_progress(
                "copy_done",
                key=target_key,
                owner=target.owner,
                workspace=target.workspace,
                revision=target.revision,
                path=target.path,
                source_key=source_blob.name,
                bytes=bytes,
            )
        except PreconditionFailed:
            if not self._existing_object_has_identity(
                target_key,
                sha256=sha256,
                size=bytes,
            ):
                raise ViperCloudError(
                    "GCS copy target already contains different bytes"
                ) from None
            self._emit_progress(
                "copy_reuse",
                key=target_key,
                owner=target.owner,
                workspace=target.workspace,
                revision=target.revision,
                path=target.path,
                source_key=source_blob.name,
                bytes=bytes,
            )

    def seal(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        files: tuple[SnapshotFileRef, ...],
    ) -> None:
        """Publish an immutable manifest after every declared object is present."""
        manifest = RevisionManifest(
            owner=owner,
            workspace=workspace,
            revision=revision,
            files=tuple(sorted(files, key=lambda file: file.path)),
        )
        manifest_key = self._manifest_key(owner, workspace, revision)
        self._emit_progress(
            "seal_start",
            key=manifest_key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            file_count=len(manifest.files),
        )
        for file in manifest.files:
            blob = self.bucket.blob(
                self._file_key(owner, workspace, revision, file.path)
            )
            blob.reload(timeout=self.operation_timeout)
            metadata = blob.metadata or {}
            if metadata.get("sha256") != file.sha256 or metadata.get("bytes") != str(
                file.bytes
            ):
                raise ViperCloudError(
                    f"GCS file identity is missing or changed: {file.path}"
                )
        raw = canonical_json_bytes(manifest)
        self._upload_exact(
            manifest_key,
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            owner=owner,
            workspace=workspace,
            revision=revision,
        )
        self._manifest_cache[(owner, workspace, revision)] = manifest
        self._emit_progress(
            "seal_done",
            key=manifest_key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            bytes=len(raw),
            file_count=len(manifest.files),
        )

    def publish_revision(
        self,
        *,
        destination: ViperCloudDestination,
        revision: SHA256,
        sources: Mapping[RepoRelPath, PublicationSource],
        files: tuple[SnapshotFileRef, ...],
    ) -> GcsStageResultSnapshotRef:
        """Upload all revision members and expose them through one manifest."""
        identities = {file.path: file for file in files}
        upload_operations: list[Callable[[], None]] = []
        for path, source in sorted(sources.items()):
            identity = identities[path]
            upload_operations.append(
                lambda path=path, source=source, identity=identity: self.upload(
                    owner=destination.owner,
                    workspace=destination.workspace,
                    revision=revision,
                    path=path,
                    source=source,
                    sha256=identity.sha256,
                    bytes=identity.bytes,
                )
            )
        self._run_parallel(upload_operations)
        self.seal(
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
            files=files,
        )
        return GcsStageResultSnapshotRef(
            bucket=self.bucket_name,
            prefix=self.prefix,
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
        )

    def file_ref(
        self,
        snapshot: CloudStageResultSnapshotRef,
        path: RepoRelPath,
    ) -> GcsFileRef:
        """Address one canonical path in a GCS snapshot."""
        if not isinstance(snapshot, GcsStageResultSnapshotRef):
            raise TypeError("GcsProvider requires a GcsStageResultSnapshotRef")
        return GcsFileRef(
            bucket=snapshot.bucket,
            prefix=snapshot.prefix,
            owner=snapshot.owner,
            workspace=snapshot.workspace,
            revision=snapshot.revision,
            path=path,
        )

    def publish_reuse(
        self,
        *,
        destination: ViperCloudDestination,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: CloudStageResultSnapshotRef,
        files: Mapping[RepoRelPath, SnapshotFileRef],
        source_bytes: Mapping[RepoRelPath, bytes],
    ) -> GcsStageResultSnapshotRef:
        """Copy sealed GCS payloads server-side and upload only the new stage record."""
        del source_bytes
        if not isinstance(source_snapshot, GcsStageResultSnapshotRef):
            raise TypeError("GcsProvider requires a GcsStageResultSnapshotRef")
        self._load_manifest(
            source_snapshot.owner,
            source_snapshot.workspace,
            source_snapshot.revision,
        )
        stage_file = SnapshotFileRef(
            path=resolved_stage_path,
            sha256=hashlib.sha256(resolved_stage).hexdigest(),
            bytes=len(resolved_stage),
        )
        target_files = tuple(
            [stage_file]
            + [
                SnapshotFileRef(
                    path=target_path,
                    sha256=source_file.sha256,
                    bytes=source_file.bytes,
                )
                for target_path, source_file in sorted(files.items())
            ]
        )
        revision = manifest_revision(target_files)
        self.upload(
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
            path=resolved_stage_path,
            source=resolved_stage,
            sha256=stage_file.sha256,
            bytes=stage_file.bytes,
        )
        target_snapshot = GcsStageResultSnapshotRef(
            bucket=self.bucket_name,
            prefix=self.prefix,
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
        )
        copy_operations: list[Callable[[], None]] = []
        for target_path, source_file in sorted(files.items()):
            copy_operations.append(
                lambda target_path=target_path, source_file=source_file: self.copy(
                    source=self.file_ref(source_snapshot, source_file.path),
                    target=self.file_ref(target_snapshot, target_path),
                    sha256=source_file.sha256,
                    bytes=source_file.bytes,
                )
            )
        self._run_parallel(copy_operations)
        self.seal(
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
            files=target_files,
        )
        return target_snapshot

    def fetch(self, location: CloudFileRef) -> bytes:
        """Restore one sealed GCS file and verify its exact byte identity."""
        if not isinstance(location, GcsFileRef):
            raise TypeError("GcsProvider requires a GcsFileRef")
        return self._fetch(
            owner=location.owner,
            workspace=location.workspace,
            revision=location.revision,
            path=location.path,
        )

    def _fetch(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
    ) -> bytes:
        """Restore one sealed file and verify its exact byte identity."""
        files = {
            file.path: file
            for file in self._load_manifest(owner, workspace, revision).files
        }
        identity = files.get(path)
        if identity is None:
            raise ViperCloudError("GCS sealed revision has no requested file")
        key = self._file_key(owner, workspace, revision, path)
        self._emit_progress(
            "fetch_start",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=identity.bytes,
        )
        raw = self._download_object_to_bytes(
            key=key,
            expected=identity,
            owner=owner,
            workspace=workspace,
            revision=revision,
        )
        if (
            len(raw) != identity.bytes
            or hashlib.sha256(raw).hexdigest() != identity.sha256
        ):
            raise ViperCloudError("GCS restored file identity changed")
        self._emit_progress(
            "fetch_done",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=len(raw),
        )
        return raw

    def _download_object_to_bytes(
        self,
        *,
        key: str,
        expected: SnapshotFileRef,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> bytes:
        """Download one sealed object as bytes through the bounded restore path."""
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=".viper-fetch.",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            self._download_object_to_path(
                key=key,
                expected=expected,
                destination=temporary,
                owner=owner,
                workspace=workspace,
                revision=revision,
            )
            return temporary.read_bytes()
        finally:
            temporary.unlink(missing_ok=True)

    def fetch_to_path(
        self,
        location: CloudFileRef,
        identity: SnapshotFileRef,
        destination: Path,
    ) -> Path:
        """Stream one sealed GCS file to a verified local path."""
        if not isinstance(location, GcsFileRef):
            raise TypeError("GcsProvider requires a GcsFileRef")
        if identity.path != location.path:
            raise ViperCloudError("GCS materialization identity names another path")
        return self._fetch_to_path(
            owner=location.owner,
            workspace=location.workspace,
            revision=location.revision,
            path=location.path,
            expected=identity,
            destination=destination,
        )

    def _fetch_to_path(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        expected: SnapshotFileRef,
        destination: Path,
    ) -> Path:
        """Stream one sealed file to a new root-confined path and verify it."""
        files = {
            file.path: file
            for file in self._load_manifest(owner, workspace, revision).files
        }
        identity = files.get(path)
        if identity is None:
            raise ViperCloudError("GCS sealed revision has no requested file")
        if identity != expected:
            raise ViperCloudError("GCS file differs from its resolved reference")
        target = destination if destination.is_absolute() else self.root / destination
        target = target.resolve()
        if not target.is_relative_to(self.root):
            raise ViperCloudError("GCS restore destination escapes root")
        if target.exists():
            raise ViperCloudError("GCS restore destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        key = self._file_key(owner, workspace, revision, path)
        self._emit_progress(
            "stream_fetch_start",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=identity.bytes,
        )
        try:
            self._download_object_to_path(
                key=key,
                expected=identity,
                destination=temporary,
                owner=owner,
                workspace=workspace,
                revision=revision,
            )
            with temporary.open("rb") as stream:
                observed_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                temporary.stat().st_size != identity.bytes
                or observed_sha256 != identity.sha256
            ):
                raise ViperCloudError("GCS restored file identity changed")
            os.replace(temporary, target)
            self._emit_progress(
                "stream_fetch_done",
                key=key,
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
                bytes=identity.bytes,
            )
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _download_object_to_path(
        self,
        *,
        key: str,
        expected: SnapshotFileRef,
        destination: Path,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> None:
        """Download one sealed object using the fastest available verified path."""
        if expected.bytes < self.sliced_fetch_min_bytes:
            self._download_python_to_path(key=key, destination=destination)
            return
        self._emit_progress(
            "stream_fetch_sliced_start",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=expected.path,
            bytes=expected.bytes,
        )
        self._download_sliced_to_path(
            key=key,
            size=expected.bytes,
            destination=destination,
        )
        self._emit_progress(
            "stream_fetch_sliced_done",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=expected.path,
            bytes=expected.bytes,
        )

    def _download_python_to_path(self, *, key: str, destination: Path) -> None:
        """Download one small object through the GCS Python client."""
        self._emit_progress("stream_fetch_python_start", key=key)
        self.bucket.blob(key).download_to_filename(
            str(destination),
            checksum="auto",
            timeout=self.operation_timeout,
        )
        self._emit_progress("stream_fetch_python_done", key=key)

    def _download_sliced_to_path(
        self,
        *,
        key: str,
        size: int,
        destination: Path,
    ) -> None:
        """Restore one object through parallel byte-range reads."""
        ranges = tuple(
            (start, min(start + self.sliced_fetch_chunk_bytes, size))
            for start in range(0, size, self.sliced_fetch_chunk_bytes)
        )
        progress_lock = Lock()
        completed_bytes = 0
        next_progress_bytes = GCS_SLICED_FETCH_PROGRESS_BYTES

        def record_progress(chunk_bytes: int) -> None:
            nonlocal completed_bytes, next_progress_bytes
            with progress_lock:
                completed_bytes += chunk_bytes
                if completed_bytes < next_progress_bytes and completed_bytes < size:
                    return
                self._emit_progress(
                    "stream_fetch_progress",
                    key=key,
                    bytes=completed_bytes,
                )
                while next_progress_bytes <= completed_bytes:
                    next_progress_bytes += GCS_SLICED_FETCH_PROGRESS_BYTES

        def fetch_range(start: int, stop: int) -> int:
            return self._download_range_to_path(
                key=key,
                start=start,
                stop=stop,
                destination=destination,
                progress=record_progress,
            )

        try:
            with destination.open("wb") as output:
                output.truncate(size)
            restore_workers = min(self.sliced_fetch_max_workers, len(ranges))
            with ThreadPoolExecutor(max_workers=restore_workers) as executor:
                futures: dict[Future[int], tuple[int, int]] = {
                    executor.submit(fetch_range, start, stop): (start, stop)
                    for start, stop in ranges
                }
                for future in as_completed(futures):
                    start, stop = futures[future]
                    try:
                        written = future.result()
                    except (GoogleAPIError, RequestException) as error:
                        raise ViperCloudError(
                            f"GCS sliced restore failed for bytes {start}-{stop - 1}"
                        ) from error
                    if written != stop - start:
                        raise ViperCloudError("GCS restored file identity changed")
        except ViperCloudError:
            raise

    def _download_range_to_path(
        self,
        *,
        key: str,
        start: int,
        stop: int,
        destination: Path,
        progress: Callable[[int], None],
    ) -> int:
        """Read one half-open byte range from GCS into its destination offset."""
        for attempt in range(1, self.range_fetch_attempts + 1):
            try:
                return self._download_range_to_path_once(
                    key=key,
                    start=start,
                    stop=stop,
                    destination=destination,
                    progress=progress,
                )
            except (GoogleAPIError, RequestException):
                if attempt >= self.range_fetch_attempts:
                    raise
                self._emit_progress(
                    "stream_fetch_range_retry",
                    key=key,
                    bytes=stop - start,
                )
        raise ViperCloudError("GCS range restore exhausted retries")

    def _download_range_to_path_once(
        self,
        *,
        key: str,
        start: int,
        stop: int,
        destination: Path,
        progress: Callable[[int], None],
    ) -> int:
        """Stream one half-open GCS byte range into its destination offset."""
        session = getattr(self.client, "_http", None)
        self._emit_progress(
            "stream_fetch_range_start",
            key=key,
            bytes=stop - start,
        )
        if session is None:
            raw = self.bucket.blob(key).download_as_bytes(
                start=start,
                end=stop - 1,
                checksum=None,  # pyright: ignore[reportArgumentType]
                timeout=self.operation_timeout,
            )
            progress(len(raw))
            with destination.open("r+b") as output:
                output.seek(start)
                output.write(raw)
            self._emit_progress(
                "stream_fetch_range_done",
                key=key,
                bytes=len(raw),
            )
            return len(raw)
        object_name = quote(key, safe="")
        url = (
            f"https://storage.googleapis.com/download/storage/v1/b/"
            f"{self.bucket_name}/o/{object_name}?alt=media"
        )
        response = session.request(
            "GET",
            url,
            headers={"Range": f"bytes={start}-{stop - 1}"},
            stream=True,
            timeout=(self.operation_timeout, self.range_fetch_read_timeout),
        )
        if response.status_code != 206:
            raise ViperCloudError(
                f"GCS sliced restore expected HTTP 206, got {response.status_code}"
            )
        downloaded = 0
        with destination.open("r+b") as output:
            output.seek(start)
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                chunk_bytes = len(chunk)
                downloaded += chunk_bytes
                progress(chunk_bytes)
        self._emit_progress(
            "stream_fetch_range_done",
            key=key,
            bytes=downloaded,
        )
        return downloaded

    def list_files(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> tuple[SnapshotFileRef, ...]:
        """List the exact files exposed by one GCS snapshot."""
        if not isinstance(snapshot, GcsStageResultSnapshotRef):
            raise TypeError("GcsProvider requires a GcsStageResultSnapshotRef")
        return self._list_files(
            owner=snapshot.owner,
            workspace=snapshot.workspace,
            revision=snapshot.revision,
        )

    def _list_files(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> tuple[SnapshotFileRef, ...]:
        """List the exact files exposed by one sealed revision."""
        return self._load_manifest(owner, workspace, revision).files

    def verify_file(self, reference: CloudFileRef, identity: SnapshotFileRef) -> None:
        """Stream and hash one sealed GCS file without retaining a local copy."""
        if not isinstance(reference, GcsFileRef):
            raise TypeError("GcsProvider requires a GcsFileRef")
        self._verify_file(
            owner=reference.owner,
            workspace=reference.workspace,
            revision=reference.revision,
            path=reference.path,
            sha256=identity.sha256,
            bytes=identity.bytes,
        )

    def _verify_file(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Stream and hash one sealed object without creating a local copy."""
        expected = SnapshotFileRef(path=path, sha256=sha256, bytes=bytes)
        if expected not in self._load_manifest(owner, workspace, revision).files:
            raise ViperCloudError("GCS file differs from its sealed manifest")

        key = self._file_key(owner, workspace, revision, path)
        blob = self.bucket.blob(key)
        self._emit_progress(
            "verify_start",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=bytes,
        )
        try:
            blob.reload(timeout=self.operation_timeout)
            if blob.generation is None:
                raise ViperCloudError("GCS file has no immutable generation")
            observed = _DigestWriter()
            blob.download_to_file(
                observed,
                if_generation_match=blob.generation,
                checksum="auto",
                timeout=self.operation_timeout,
            )
        except GoogleAPIError as error:
            raise ViperCloudError("GCS file could not be verified") from error
        if observed.bytes != bytes or observed.digest.hexdigest() != sha256:
            raise ViperCloudError("GCS file identity changed")
        self._emit_progress(
            "verify_done",
            key=key,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
            bytes=observed.bytes,
        )


def probe_gcs_storage(
    root: Path,
    destination: ViperCloudDestination,
    provider: GcsProvider,
    receipt_path: Path,
    *,
    artifact_path: RepoRelPath = ".viper/probes/gcs-storage.bin",
) -> GcsStorageProbeReceipt:
    """Publish, restore, verify, and record one deterministic GCS probe."""
    payload = b"VIPER GCS storage probe\n"
    snapshot, identities = provider.publish(
        destination,
        {artifact_path: payload},
    )
    identity = identities[0]
    location = provider.file_ref(snapshot, artifact_path)
    restored = provider.fetch(location)
    restored_sha256 = hashlib.sha256(restored).hexdigest()
    receipt = GcsStorageProbeReceipt(
        artifact_uri=(
            f"viper://{location.owner}/{location.workspace}@"
            f"{location.revision}/{location.path}"
        ),
        sha256=identity.sha256,
        restored_sha256=restored_sha256,
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(receipt))
    temporary.replace(receipt_path)
    return receipt


__all__ = [
    "GcsProgressEvent",
    "GcsProgressPhase",
    "GcsProgressSink",
    "GcsStorageProbeReceipt",
    "GCS_OPERATION_TIMEOUT_SECONDS",
    "GcsProvider",
    "probe_gcs_storage",
]
