"""Retrieve exact source and immutable output bytes for run execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

import viper._subprocess as subprocess

from .._schema import RepoRelPath
from .._verification.storage import (
    fetch_git_file_bytes,
    fetch_huggingface_file_bytes,
    list_huggingface_snapshot_files,
)
from ..references import (
    GitFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedGitFileRef,
    StageResultSnapshot,
    StorageModel,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from ..storage import LocalArtifactStore, ViperCloudClient
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
        cloud_client: ViperCloudClient | None = None,
    ) -> None:
        """Bind retrieval to one local Git checkout and output store."""
        self.repository_root = repository_root.resolve()
        self.store = store
        self.source_repository = source_repository
        self.cloud_client = cloud_client

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
        if isinstance(location, ViperCloudFileRef):
            if self.cloud_client is None:
                raise RunError("Viper Cloud retrieval requires a client")
            return self.cloud_client.fetch(
                owner=location.owner,
                project=location.project,
                revision=location.revision,
                path=location.path,
            )
        return self.store.fetch(location)

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshot,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable stage snapshot."""
        if isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
            return list_huggingface_snapshot_files(snapshot)
        if isinstance(snapshot, ViperCloudStageResultSnapshotRef):
            if self.cloud_client is None:
                raise RunError("Viper Cloud snapshot listing requires a client")
            return tuple(
                file.path
                for file in self.cloud_client.list_files(
                    owner=snapshot.owner,
                    project=snapshot.project,
                    revision=snapshot.revision,
                )
            )
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
