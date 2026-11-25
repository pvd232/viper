"""Read the source and saved output files needed to execute a run."""

from __future__ import annotations

import hashlib
from pathlib import Path

import viper._subprocess as subprocess

from ._schema import RepoRelPath
from ._verification.storage import fetch_git_file_bytes, verify_resolved_file_bytes
from ._verified_cache import VerifiedObjectCache
from .cloud import CloudReference, ViperCloud
from .evidence import VerificationError, VerificationPolicy, VerifiedProducerRun
from .huggingface import HuggingFaceProvider
from .references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from .storage import LocalArtifactStore, local_artifact_store, viper_cloud

_MAX_EXTERNAL_GIT_CACHE_BYTES = 64 * 1024**2


def run_git(repository_root: Path, *arguments: str) -> bytes:
    """Read Git data from the selected repository."""
    try:
        return subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=True,
            capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise VerificationError("local Git evidence could not be read") from exc


class RunFetcher:
    """Read files and remember checks already completed during this execution."""

    def __init__(
        self,
        repository_root: Path,
        store: LocalArtifactStore,
        source_repository: str,
        *,
        cache_root: Path | None = None,
    ) -> None:
        """Set up file access for one execution.

        cache_root keeps temporary transfer files separate from shared storage.
        Files used by this fetcher must stay unchanged until the execution ends.
        A new fetcher checks existing files again.
        """
        self.repository_root = repository_root.resolve()
        self.store = store
        self.source_repository = source_repository
        self.cache_root = (
            cache_root or self.repository_root / ".viper/cache"
        ).resolve()
        if not self.cache_root.is_relative_to(self.repository_root):
            raise ValueError("file cache must be inside the workspace")
        self._external_git_files: dict[GitFileRef, bytes] = {}
        self._external_git_cache_bytes = 0
        self._external_git_checkout_root = self.cache_root / "git-checkouts"
        if self.cache_root != self.repository_root / ".viper/cache":
            self.store = LocalArtifactStore(
                store.repository_root,
                store.store,
                cache_root=self.cache_root / "verified-objects",
            )
        self._verified_paths: dict[ResolvedFileRef, Path] = {}
        self._verified_producers: dict[
            tuple[ResolvedRunRef, VerificationPolicy],
            VerifiedProducerRun,
        ] = {}
        self._cloud_services: dict[tuple[str, str, str], ViperCloud] = {}

    @property
    def _verified_objects(self) -> VerifiedObjectCache:
        """Return the store cache used by existing transfer code."""
        return self.store.downloads

    def _cloud_service(self, reference: CloudReference) -> ViperCloud:
        """Reuse a cloud service and its checked file lists during this execution."""
        if isinstance(reference, (GcsFileRef, GcsStageResultSnapshotRef)):
            key = ("gcs", reference.bucket, reference.prefix)
        elif isinstance(
            reference, (HuggingFaceFileRef, HuggingFaceStageResultSnapshotRef)
        ):
            key = ("hf", reference.repository, reference.repo_type)
        else:
            key = ("configured", "", "")
        remembered = self._cloud_services.get(key)
        if remembered is not None:
            return remembered
        if isinstance(reference, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)):
            cloud = viper_cloud(self.repository_root)
        elif isinstance(reference, (GcsFileRef, HuggingFaceFileRef)):
            cloud = ViperCloud.for_reference(self.repository_root, reference)
        else:
            cloud = ViperCloud.for_snapshot(self.repository_root, reference)
        if self.cache_root != self.repository_root / ".viper/cache" and isinstance(
            cloud.provider, HuggingFaceProvider
        ):
            cloud.provider.cache_dir = self.cache_root / "hub"
        self._cloud_services[key] = cloud
        return cloud

    def _local_store(
        self, location: LocalFileRef | LocalStageResultSnapshotRef
    ) -> LocalArtifactStore:
        """Check this workspace, then the workspace saved in the reference."""
        if (
            location.workspace == self.store.repository_root
            and location.store == self.store.store
        ):
            return self.store
        source = LocalStageResultSnapshotRef.model_validate(
            location.model_dump(exclude={"path"})
            if isinstance(location, LocalFileRef)
            else location
        )
        if self.store.registry.snapshot(source) is not None:
            return self.store
        return local_artifact_store(location=location)

    def __call__(self, location: StorageModel) -> bytes:
        """Read a file from the location recorded in its reference."""
        if isinstance(location, GitFileRef):
            if str(location.repository) != self.source_repository:
                try:
                    return self._external_git_files[location]
                except KeyError:
                    checkout_identity = hashlib.sha256(
                        f"{location.repository}\0{location.commit}".encode()
                    ).hexdigest()
                    checkout = self._external_git_checkout_root / checkout_identity
                    raw = fetch_git_file_bytes(location, checkout=checkout)
                    if (
                        self._external_git_cache_bytes + len(raw)
                        <= _MAX_EXTERNAL_GIT_CACHE_BYTES
                    ):
                        self._external_git_files[location] = raw
                        self._external_git_cache_bytes += len(raw)
                    return raw
            return run_git(
                self.repository_root,
                "show",
                f"{location.commit}:{location.path}",
            )
        if isinstance(
            location,
            (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
        ):
            return self.store.fetch(
                location, cloud=lambda: self._cloud_service(location)
            )

        if isinstance(location, LocalFileRef):
            return self._local_store(location).fetch(location)
        return self.store.fetch(location)

    def read(self, reference: ResolvedFileRef) -> bytes:
        """Read the file and check its byte count and SHA-256 on first use."""
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            return remembered.read_bytes()
        if isinstance(reference.stored_at, GitFileRef):
            cached = self.store.cached_read(reference)
            if cached is not None:
                raw, path = cached
            else:
                raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
                path = self.store.cache_verified_bytes(reference, raw)
        else:
            store = (
                self._local_store(reference.stored_at)
                if isinstance(reference.stored_at, LocalFileRef)
                else self.store
            )
            cloud = (
                None
                if isinstance(reference.stored_at, LocalFileRef)
                else lambda: self._cloud_service(reference.stored_at)
            )
            raw, path = store.read_resolved(reference, cloud=cloud)
        self._verified_paths[reference] = path
        return raw

    def path(self, reference: ResolvedFileRef) -> Path:
        """Return a local path after checking the file on first use."""
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            return remembered

        if isinstance(reference.stored_at, GitFileRef):
            self.read(reference)
            return self._verified_paths[reference]

        if isinstance(reference.stored_at, LocalFileRef):
            path = self._local_store(reference.stored_at).resolve(reference)
        else:
            path = self.store.resolve(
                reference, cloud=lambda: self._cloud_service(reference.stored_at)
            )
        self._verified_paths[reference] = path
        return path

    def remember_path(self, reference: ResolvedFileRef, path: Path) -> None:
        """Remember a file whose byte count and SHA-256 were checked during publication.

        The caller must pass the published file or its unchanged upload source.
        Its bytes must still match the reference.
        """
        if path.stat().st_size != reference.bytes:
            raise VerificationError(
                f"byte-count mismatch: expected {reference.bytes}, "
                f"received {path.stat().st_size}"
            )
        self._verified_paths[reference] = path

    def read_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
    ) -> VerifiedProducerRun | None:
        """Return a producer run already verified during this execution."""
        return self._verified_producers.get((reference, policy))

    def remember_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
        producer: VerifiedProducerRun,
    ) -> None:
        """Remember a verified producer run for later reads in this execution."""
        self._verified_producers[(reference, policy)] = producer

    def snapshot_files(
        self, snapshot: CloudStageResultSnapshotRef
    ) -> tuple[SnapshotFileRef, ...]:
        """List every file in a cloud snapshot with its byte count and SHA-256."""
        return self.store.snapshot_files(
            snapshot, cloud=lambda: self._cloud_service(snapshot)
        )

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """Return the snapshot's complete list of file paths."""
        if isinstance(
            snapshot,
            (
                GcsStageResultSnapshotRef,
                HuggingFaceStageResultSnapshotRef,
                ViperCloudStageResultSnapshotRef,
            ),
        ):
            return tuple(file.path for file in self.snapshot_files(snapshot))
        return self._local_store(snapshot).list_snapshot_files(snapshot)


def resolve_git_file(
    fetcher: RunFetcher,
    location: GitFileRef,
) -> ResolvedGitFileRef:
    """Read a file at a fixed Git commit and record its byte count and SHA-256."""
    raw = fetcher(location)
    return ResolvedGitFileRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=location,
    )
