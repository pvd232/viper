"""Retrieve exact source and immutable output bytes for run execution."""

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
    """Run one bounded Git query against the selected repository."""
    try:
        return subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=True,
            capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise VerificationError("local Git evidence could not be read") from exc


class RunFetcher:
    """Read run files and reuse their content checks within one execution."""

    def __init__(
        self,
        repository_root: Path,
        store: LocalArtifactStore,
        source_repository: str,
        *,
        cache_root: Path | None = None,
    ) -> None:
        """Bind retrieval and its per-file cache to one execution.

        cache_root selects a task-owned cache beneath the workspace.
        Files must remain unchanged for the lifetime of the fetcher. A new
        execution creates a new fetcher and checks pre-existing files again.
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
        self._verified_objects = VerifiedObjectCache(
            self.cache_root / "verified-objects"
        )
        self._verified_paths: dict[ResolvedFileRef, Path] = {}
        self._verified_producers: dict[
            tuple[ResolvedRunRef, VerificationPolicy],
            VerifiedProducerRun,
        ] = {}
        self._cloud_services: dict[tuple[str, str, str], ViperCloud] = {}

    def _cloud_service(self, reference: CloudReference) -> ViperCloud:
        """Keep a provider's sealed-manifest cache for this fetcher's lifetime."""
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
            cloud.provider.stream_files = True
        self._cloud_services[key] = cloud
        return cloud

    def __call__(self, location: StorageModel) -> bytes:
        """Retrieve one file from its declared immutable backend."""
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
            cloud = self._cloud_service(location)
            return cloud.fetch(location)
        if isinstance(location, LocalFileRef):
            return local_artifact_store(location).fetch(location)
        return self.store.fetch(location)

    def read(self, reference: ResolvedFileRef) -> bytes:
        """Read bytes, checking size and SHA-256 on first use in this execution."""
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            return remembered.read_bytes()
        cacheable = not isinstance(reference.stored_at, LocalFileRef)
        if cacheable:
            cached = self._verified_objects.read(reference)
            if cached is not None:
                self._verified_paths[reference] = self._verified_objects.path(reference)
                return cached
        raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
        if cacheable:
            self._verified_objects.write(reference, raw)
            path = self._verified_objects.path(reference)
        else:
            assert isinstance(reference.stored_at, LocalFileRef)
            path = local_artifact_store(reference.stored_at).path(reference.stored_at)
        self._verified_paths[reference] = path
        return raw

    def path(self, reference: ResolvedFileRef) -> Path:
        """Return a local path after its first size and SHA-256 check per execution."""
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            return remembered

        if isinstance(reference.stored_at, LocalFileRef):
            path = local_artifact_store(reference.stored_at).path(reference.stored_at)
            if path.stat().st_size != reference.bytes:
                raise VerificationError(
                    f"byte-count mismatch: expected {reference.bytes}, "
                    f"received {path.stat().st_size}"
                )
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != reference.sha256:
                raise VerificationError(
                    f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
                )
            self._verified_paths[reference] = path
            return path

        if not isinstance(
            reference.stored_at,
            (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
        ):
            self.read(reference)
            return self._verified_paths[reference]

        cached = self._verified_objects.verified_path(reference)
        if cached is not None:
            self._verified_paths[reference] = cached
            return cached

        temporary = self._verified_objects.temporary_path(reference)
        try:
            cloud = self._cloud_service(reference.stored_at)
            restored = cloud.fetch_to_path(reference, temporary)
            cached = self._verified_objects.adopt_verified_path(reference, restored)
        finally:
            temporary.unlink(missing_ok=True)

        self._verified_paths[reference] = cached
        return cached

    def remember_path(self, reference: ResolvedFileRef, path: Path) -> None:
        """Cache a file using the size and hash returned by successful publication.

        The caller must pass the published file or its unchanged upload source.
        Publication must establish the reference's SHA-256 before registration.
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
        """Return producer structure verified earlier in this execution."""
        return self._verified_producers.get((reference, policy))

    def remember_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
        producer: VerifiedProducerRun,
    ) -> None:
        """Reuse one immutable producer proof without retaining artifact bytes."""
        self._verified_producers[(reference, policy)] = producer

    def snapshot_files(
        self, snapshot: CloudStageResultSnapshotRef
    ) -> tuple[SnapshotFileRef, ...]:
        """Return each file's path, size, and SHA-256 hash from a cloud snapshot."""
        return self._cloud_service(snapshot).list_files(snapshot)

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshotRef,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable stage snapshot."""
        if isinstance(
            snapshot,
            (
                GcsStageResultSnapshotRef,
                HuggingFaceStageResultSnapshotRef,
                ViperCloudStageResultSnapshotRef,
            ),
        ):
            return tuple(file.path for file in self.snapshot_files(snapshot))
        return local_artifact_store(snapshot).list_snapshot_files(snapshot)


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
