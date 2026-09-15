"""Store sealed VIPER revisions in Google Cloud Storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from google.api_core.exceptions import GoogleAPIError, PreconditionFailed
from google.cloud import storage
from pydantic import Field, ValidationError, model_validator

from ._schema import SHA256, ProtocolModel, RepoRelPath
from .ids import HumanId
from .references import SnapshotFileRef, ViperCloudFileRef
from .storage import (
    PublicationSource,
    StorageConfigurationError,
    ViperCloudClient,
    ViperCloudDestination,
    manifest_revision,
    publish_resolved_files,
    resolve_publication_source,
)


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


class _GcsRevisionManifest(ProtocolModel):
    """Describe every file exposed by one sealed cloud revision."""

    schema_version: Literal[1] = Field(
        default=1,
        description="GCS revision-manifest schema version.",
    )
    owner: HumanId = Field(description="Account owning the cloud revision.")
    workspace: HumanId = Field(description="Workspace owning the cloud revision.")
    revision: SHA256 = Field(description="Content-derived revision identifier.")
    files: tuple[SnapshotFileRef, ...] = Field(
        description="Files exposed by the sealed revision in path order."
    )

    @model_validator(mode="after")
    def require_revision_identity(self) -> _GcsRevisionManifest:
        """Bind the manifest revision to its sorted, unique file identities."""
        paths = tuple(file.path for file in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("GCS manifest files must have unique sorted paths")
        if manifest_revision(self.files) != self.revision:
            raise ValueError("GCS manifest content does not match its revision")
        return self


def _canonical_json(record: ProtocolModel) -> bytes:
    """Serialize one protocol record into stable UTF-8 JSON bytes."""
    return (
        json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


class GcsViperCloudClient(ViperCloudClient):
    """Implement VIPER's immutable cloud protocol in one GCS bucket."""

    def __init__(
        self,
        root: Path,
        bucket: str,
        *,
        prefix: str = "viper",
        client: storage.Client | None = None,
    ) -> None:
        """Bind publication sources and object keys to one workspace and bucket."""
        self.root = root.resolve(strict=True)
        prefix_path = PurePosixPath(prefix)
        if (
            prefix_path.is_absolute()
            or not prefix_path.parts
            or any(part in {"", ".", ".."} for part in prefix_path.parts)
        ):
            raise ValueError("GCS prefix must be a non-empty relative path")
        self.prefix = prefix_path.as_posix()
        self.client = client or storage.Client()
        self.bucket = self.client.bucket(bucket)

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
            raise StorageConfigurationError("GCS upload source identity changed")
        blob = self.bucket.blob(key)
        blob.metadata = {"sha256": sha256, "bytes": str(size)}
        try:
            if isinstance(resolved, bytes):
                blob.upload_from_string(
                    resolved,
                    content_type="application/octet-stream",
                    if_generation_match=0,
                    checksum="auto",
                )
            else:
                blob.upload_from_filename(
                    str(resolved),
                    content_type="application/octet-stream",
                    if_generation_match=0,
                    checksum="auto",
                )
        except PreconditionFailed:
            existing = blob.download_as_bytes(checksum="auto")
            if len(existing) != size or hashlib.sha256(existing).hexdigest() != sha256:
                raise StorageConfigurationError(
                    "GCS object already contains different bytes"
                ) from None

    def _load_manifest(
        self,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> _GcsRevisionManifest:
        """Load and validate the seal before exposing any revision member."""
        try:
            raw = self.bucket.blob(
                self._manifest_key(owner, workspace, revision)
            ).download_as_bytes(checksum="auto")
            manifest = _GcsRevisionManifest.model_validate_json(raw)
        except (GoogleAPIError, KeyError, ValidationError) as error:
            raise StorageConfigurationError("GCS revision is not sealed") from error
        if (
            manifest.owner != owner
            or manifest.workspace != workspace
            or manifest.revision != revision
        ):
            raise StorageConfigurationError("GCS manifest names another revision")
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
        self._upload_exact(
            self._file_key(owner, workspace, revision, path),
            source,
            sha256=sha256,
            size=bytes,
        )

    def copy(
        self,
        *,
        source: ViperCloudFileRef,
        target: ViperCloudFileRef,
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
            raise StorageConfigurationError("GCS copy source identity changed")
        source_blob = self.bucket.blob(
            self._file_key(
                source.owner,
                source.workspace,
                source.revision,
                source.path,
            )
        )
        source_blob.reload()
        if source_blob.generation is None:
            raise StorageConfigurationError("GCS copy source has no generation")
        target_key = self._file_key(
            target.owner,
            target.workspace,
            target.revision,
            target.path,
        )
        try:
            self.bucket.copy_blob(
                source_blob,
                self.bucket,
                new_name=target_key,
                if_generation_match=0,
                if_source_generation_match=source_blob.generation,
            )
        except PreconditionFailed:
            existing = self.bucket.blob(target_key).download_as_bytes(checksum="auto")
            if len(existing) != bytes or hashlib.sha256(existing).hexdigest() != sha256:
                raise StorageConfigurationError(
                    "GCS copy target already contains different bytes"
                ) from None

    def seal(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        files: tuple[SnapshotFileRef, ...],
    ) -> None:
        """Publish an immutable manifest after every declared object is present."""
        manifest = _GcsRevisionManifest(
            owner=owner,
            workspace=workspace,
            revision=revision,
            files=tuple(sorted(files, key=lambda file: file.path)),
        )
        for file in manifest.files:
            blob = self.bucket.blob(
                self._file_key(owner, workspace, revision, file.path)
            )
            blob.reload()
            metadata = blob.metadata or {}
            if metadata.get("sha256") != file.sha256 or metadata.get("bytes") != str(
                file.bytes
            ):
                raise StorageConfigurationError(
                    f"GCS file identity is missing or changed: {file.path}"
                )
        raw = _canonical_json(manifest)
        self._upload_exact(
            self._manifest_key(owner, workspace, revision),
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
        )

    def fetch(
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
            raise StorageConfigurationError("GCS sealed revision has no requested file")
        raw = self.bucket.blob(
            self._file_key(owner, workspace, revision, path)
        ).download_as_bytes(checksum="auto")
        if (
            len(raw) != identity.bytes
            or hashlib.sha256(raw).hexdigest() != identity.sha256
        ):
            raise StorageConfigurationError("GCS restored file identity changed")
        return raw

    def fetch_to_path(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        destination: Path,
    ) -> Path:
        """Stream one sealed file to a new root-confined path and verify it."""
        files = {
            file.path: file
            for file in self._load_manifest(owner, workspace, revision).files
        }
        identity = files.get(path)
        if identity is None:
            raise StorageConfigurationError("GCS sealed revision has no requested file")
        target = destination if destination.is_absolute() else self.root / destination
        target = target.resolve()
        if not target.is_relative_to(self.root):
            raise StorageConfigurationError("GCS restore destination escapes root")
        if target.exists():
            raise StorageConfigurationError("GCS restore destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            self.bucket.blob(
                self._file_key(owner, workspace, revision, path)
            ).download_to_filename(str(temporary), checksum="auto")
            with temporary.open("rb") as stream:
                observed_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                temporary.stat().st_size != identity.bytes
                or observed_sha256 != identity.sha256
            ):
                raise StorageConfigurationError("GCS restored file identity changed")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def list_files(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> tuple[SnapshotFileRef, ...]:
        """List the exact files exposed by one sealed revision."""
        return self._load_manifest(owner, workspace, revision).files


def probe_gcs_storage(
    root: Path,
    destination: ViperCloudDestination,
    client: GcsViperCloudClient,
    receipt_path: Path,
    *,
    artifact_path: RepoRelPath = ".viper/probes/gcs-storage.bin",
) -> GcsStorageProbeReceipt:
    """Publish, restore, verify, and record one deterministic GCS probe."""
    payload = b"VIPER GCS storage probe\n"
    references = publish_resolved_files(
        root,
        destination,
        {artifact_path: payload},
        cloud_client=client,
    )
    reference = references[artifact_path]
    location = reference.stored_at
    if not isinstance(location, ViperCloudFileRef):
        raise StorageConfigurationError("GCS probe produced a non-cloud reference")
    restored = client.fetch(
        owner=location.owner,
        workspace=location.workspace,
        revision=location.revision,
        path=location.path,
    )
    restored_sha256 = hashlib.sha256(restored).hexdigest()
    receipt = GcsStorageProbeReceipt(
        artifact_uri=(
            f"viper://{location.owner}/{location.workspace}@"
            f"{location.revision}/{location.path}"
        ),
        sha256=reference.sha256,
        restored_sha256=restored_sha256,
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_bytes(_canonical_json(receipt))
    temporary.replace(receipt_path)
    return receipt


__all__ = [
    "GcsStorageProbeReceipt",
    "GcsViperCloudClient",
    "probe_gcs_storage",
]
