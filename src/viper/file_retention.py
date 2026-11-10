"""Apply retention to closed files after verifying their immutable cloud copies."""

from __future__ import annotations

import fcntl
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from ._schema import ProtocolModel, RepoRelPath
from .cloud import ViperCloud
from .references import GcsFileRef, HuggingFaceFileRef, ResolvedFileRef, SnapshotFileRef
from .repository import PathError, resolve_path


class FileEvictionError(RuntimeError):
    """Report evidence that prevents safe removal of an explicitly selected file."""


class FileEviction(ProtocolModel):
    """Record closed local files removed after verifying their immutable cloud bytes."""

    artifacts: tuple[SnapshotFileRef, ...] = Field(
        description="Cloud-verified local artifact identities removed by this call."
    )
    bytes_released: int = Field(
        ge=0, description="Total regular-file payload bytes removed by this call."
    )


def _local_file_identity(root: Path, identity: SnapshotFileRef) -> Path | None:
    """Resolve a confined regular file and require its recorded size and digest."""
    try:
        local = resolve_path(root, identity.path, operation="write")
        if not local.exists():
            return None
        if not local.is_file():
            raise FileEvictionError("local artifact is not a regular file")
        with local.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if local.stat().st_size != identity.bytes or digest != identity.sha256:
            raise FileEvictionError("local artifact identity changed")
        return local
    except (OSError, PathError) as error:
        raise FileEvictionError("local artifact path is unsafe") from error


def evict_cloud_backed_files(
    repository_root: Path,
    references: tuple[ResolvedFileRef, ...],
    *,
    cloud: ViperCloud | None = None,
    not_before: datetime | None = None,
    minimum_bytes: int = 0,
) -> FileEviction:
    """Release caller-selected closed files with immutable cloud references.

    The caller closes the producer before requesting eviction. VIPER enforces the
    retention time and size threshold, checks all local and remote identities,
    checks local bytes again, and then removes the eligible files. Retention
    calls share a workspace lock. Exact duplicates and already absent files are
    harmless; conflicting references, unsafe paths and changed bytes are refused.
    """
    root = repository_root.resolve(strict=True)
    if type(minimum_bytes) is not int or minimum_bytes < 0:
        raise ValueError("minimum_bytes must be a nonnegative integer")
    if not_before is not None and not_before.utcoffset() is not None:
        if datetime.now(UTC) < not_before:
            return FileEviction(artifacts=(), bytes_released=0)
    elif not_before is not None:
        raise ValueError("not_before must contain an explicit timezone")
    by_path: dict[RepoRelPath, ResolvedFileRef] = {}
    for reference in references:
        location = reference.stored_at
        if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            raise FileEvictionError("artifact is not stored in Viper Cloud")
        previous = by_path.setdefault(location.path, reference)
        if previous != reference:
            raise FileEvictionError("artifact path has conflicting cloud identities")
    lock_path = resolve_path(root, ".viper/retention.lock", operation="write")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        verified: list[SnapshotFileRef] = []
        for path, reference in sorted(by_path.items()):
            if reference.bytes < minimum_bytes:
                continue
            identity = SnapshotFileRef(
                path=path, bytes=reference.bytes, sha256=reference.sha256
            )
            if _local_file_identity(root, identity) is None:
                continue
            try:
                location = reference.stored_at
                assert isinstance(location, (GcsFileRef, HuggingFaceFileRef))
                service = cloud or ViperCloud.for_reference(root, location)
                service.verify_file(reference)
            except Exception as error:
                raise FileEvictionError("cloud artifact identity changed") from error
            verified.append(identity)
        for identity in verified:
            if _local_file_identity(root, identity) is None:
                raise FileEvictionError(
                    "local artifact disappeared during verification"
                )
        for identity in verified:
            local = resolve_path(root, identity.path, operation="write")
            local.unlink()
    return FileEviction(
        artifacts=tuple(verified),
        bytes_released=sum(identity.bytes for identity in verified),
    )


__all__ = ["FileEviction", "FileEvictionError", "evict_cloud_backed_files"]
