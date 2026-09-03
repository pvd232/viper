"""Publish verified HTTP bodies as declared download artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .._schema import SHA256, RepoRelPath
from ..references import SnapshotFileRef
from .errors import RunError


def publish_download_body(
    *,
    repository_root: Path,
    source: Path,
    destination: RepoRelPath,
    expected_sha256: SHA256,
    expected_bytes: int,
) -> SnapshotFileRef:
    """Copy one verified HTTP body atomically into its declared artifact path."""
    root = repository_root.resolve(strict=True)
    source_path = source.resolve(strict=True)
    if source.is_symlink() or not source_path.is_file():
        raise RunError("HTTP result body must be a regular nonsymlink file")

    target = root / destination
    if not target.resolve(strict=False).is_relative_to(root):
        raise RunError("download artifact path escapes the repository root")
    if target.is_symlink():
        raise RunError("download artifact path must not be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with (
            source_path.open("rb") as source_file,
            os.fdopen(descriptor, "wb") as target_file,
        ):
            while chunk := source_file.read(1024 * 1024):
                target_file.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
            target_file.flush()
            os.fsync(target_file.fileno())

        observed_sha256 = digest.hexdigest()
        if byte_count != expected_bytes:
            raise RunError("download body byte count changed before publication")
        if observed_sha256 != expected_sha256:
            raise RunError("download body SHA-256 changed before publication")

        os.replace(temporary, target)
        return SnapshotFileRef(
            path=destination,
            sha256=observed_sha256,
            bytes=byte_count,
        )
    finally:
        temporary.unlink(missing_ok=True)
