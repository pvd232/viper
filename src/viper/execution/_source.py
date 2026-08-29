"""Retrieve exact source and immutable output bytes for run execution."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .._schema import RepoRelPath
from ..references import (
    GitFileRef,
    HuggingFaceFileRef,
    LocalStageResultSnapshotRef,
    ResolvedGitFileRef,
    StageResultSnapshotRef,
    StorageModel,
)
from ..storage import LocalArtifactStore
from ..verification import (
    fetch_git_file_bytes,
    fetch_huggingface_file_bytes,
    list_huggingface_snapshot_files,
)
from .errors import RunError


def run_git(repository_root: Path, *arguments: str) -> bytes:
    """Run one bounded Git query against the selected repository."""
    try:
        return subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=True,
            capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RunError("local Git evidence could not be read") from exc


class RunFetcher:
    """Retrieve frozen Git source and repository-local immutable outputs."""

    def __init__(
        self,
        repository_root: Path,
        store: LocalArtifactStore,
        source_repository: str,
    ) -> None:
        """Bind retrieval to one local Git checkout and output store."""
        self.repository_root = repository_root.resolve()
        self.store = store
        self.source_repository = source_repository

    def __call__(self, location: StorageModel) -> bytes:
        """Retrieve one file from its declared immutable backend."""
        if isinstance(location, GitFileRef):
            if str(location.repository) != self.source_repository:
                return fetch_git_file_bytes(location)
            return run_git(
                self.repository_root,
                "show",
                f"{location.commit}:{location.path}",
            )
        if isinstance(location, HuggingFaceFileRef):
            return fetch_huggingface_file_bytes(location)
        return self.store.fetch(location)

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable stage snapshot."""
        if isinstance(snapshot, StageResultSnapshotRef):
            return list_huggingface_snapshot_files(snapshot)
        return self.store.list_snapshot_files(snapshot)


def resolve_git_file(
    fetcher: RunFetcher,
    location: GitFileRef,
) -> ResolvedGitFileRef:
    """Retrieve and identify one exact file in the local Git checkout."""
    raw = fetcher(location)
    return ResolvedGitFileRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=location,
    )
