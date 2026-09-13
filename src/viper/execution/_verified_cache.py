"""Persist immutable bytes after validating their recorded content identity."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..evidence import VerificationError
from ..references import ResolvedFileRef


@dataclass(frozen=True)
class VerifiedObjectCache:
    """Store files by SHA-256 and revalidate every cache hit."""

    root: Path

    def read(self, reference: ResolvedFileRef) -> bytes | None:
        """Return cached bytes only when both recorded identity fields match."""
        path = self._path(reference.sha256)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        if self._matches(reference, raw):
            return raw
        return None

    def write(self, reference: ResolvedFileRef, raw: bytes) -> None:
        """Atomically publish bytes after validating their recorded identity."""
        if not self._matches(reference, raw):
            raise VerificationError(
                "retrieved bytes differ from their resolved reference"
            )
        path = self._path(reference.sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(raw)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def _path(self, sha256: str) -> Path:
        """Shard one digest beneath the cache root."""
        return self.root / sha256[:2] / sha256

    @staticmethod
    def _matches(reference: ResolvedFileRef, raw: bytes) -> bool:
        """Compare bytes with the complete recorded content identity."""
        return len(raw) == reference.bytes and (
            hashlib.sha256(raw).hexdigest() == reference.sha256
        )
