"""Check file bytes and save checked files in the local cache."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .evidence import VerificationError
from .references import ResolvedFileRef


@dataclass(frozen=True)
class VerifiedObjectCache:
    """Store files by SHA-256 and check their bytes before reuse."""

    root: Path

    @staticmethod
    def read_path(reference: ResolvedFileRef, path: Path) -> bytes:
        """Read the file once and check its byte count and SHA-256."""
        raw = path.read_bytes()
        if len(raw) != reference.bytes:
            raise VerificationError(
                f"byte-count mismatch: expected {reference.bytes}, received {len(raw)}"
            )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != reference.sha256:
            raise VerificationError(
                f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
            )
        return raw

    @staticmethod
    def verify_path(reference: ResolvedFileRef, path: Path) -> Path:
        """Read the file in chunks to check its byte count and SHA-256."""
        size = path.stat().st_size
        if size != reference.bytes:
            raise VerificationError(
                f"byte-count mismatch: expected {reference.bytes}, received {size}"
            )
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != reference.sha256:
            raise VerificationError(
                f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
            )
        return path

    def read(self, reference: ResolvedFileRef) -> bytes | None:
        """Return cached bytes if their byte count and SHA-256 match the reference."""
        try:
            return self.read_path(reference, self._path(reference.sha256))
        except (FileNotFoundError, VerificationError):
            return None

    def verified_path(self, reference: ResolvedFileRef) -> Path | None:
        """Return the cached path if its file matches the reference."""
        try:
            return self.verify_path(reference, self._path(reference.sha256))
        except (OSError, VerificationError):
            return None

    def adopt_verified_path(self, reference: ResolvedFileRef, source: Path) -> Path:
        """Install checked bytes without replacing an existing valid shared file."""
        if source.stat().st_size != reference.bytes:
            raise VerificationError(
                "retrieved file size differs from its resolved reference"
            )
        path = self._path(reference.sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, path)
        except FileExistsError:
            if self.verified_path(reference) is None:
                os.replace(source, path)
        return path

    def temporary_path(self, reference: ResolvedFileRef) -> Path:
        """Choose a temporary download path on the same filesystem as the cache."""
        parent = self._path(reference.sha256).parent
        parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        temporary.unlink()
        return temporary

    def path(self, reference: ResolvedFileRef) -> Path:
        """Build the cache path from the recorded SHA-256."""
        return self._path(reference.sha256)

    def write(self, reference: ResolvedFileRef, raw: bytes) -> None:
        """Save checked bytes, reusing matching content already in the cache."""
        path = self._path(reference.sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(raw)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            self.adopt_verified_path(reference, Path(temporary_name))
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def _path(self, sha256: str) -> Path:
        """Build the cache filename from the SHA-256 hash."""
        path = self.root / sha256[:2] / sha256
        if any(part.is_symlink() for part in (self.root, path.parent, path)):
            raise VerificationError("verified payload path contains a symlink")
        return path
