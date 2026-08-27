"""Publish and retrieve immutable files through the local VIPER store."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ._schema import RepoRelPath
from .references import (
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StorageModel,
)


class LocalStoreError(RuntimeError):
    """Report an unsafe path or inconsistent immutable-store revision."""


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

    def __init__(self, repository_root: Path, store: RepoRelPath = ".viper/store"):
        """Bind the store to one repository and validate its configured root."""
        self.repository_root = repository_root.resolve()
        self.store = store
        self.store_root = (self.repository_root / store).resolve()
        if not self.store_root.is_relative_to(self.repository_root):
            raise LocalStoreError("local store escapes the repository root")

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


def snapshot_file(path: RepoRelPath, raw: bytes) -> SnapshotFileRef:
    """Describe one exact file included in a local stage snapshot."""
    return SnapshotFileRef(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
