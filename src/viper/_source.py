"""Read the source and saved output files needed to execute a run."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from pathlib import Path
from threading import RLock
from types import TracebackType
from typing import Self
from weakref import finalize

import viper._subprocess as subprocess

from ._git_proof import capture_git_file_proof, verify_git_file_proof
from ._offload import current_session
from ._schema import RepoRelPath
from ._storage_locks import PayloadLocks, WorkflowReaders
from ._verification.storage import fetch_git_file_bytes
from ._verified_cache import VerifiedObjectCache, verify_resolved_file_bytes
from .cloud import CloudReference, ViperCloud
from .evidence import VerificationError, VerificationPolicy, VerifiedProducerRun
from .huggingface import HuggingFaceProvider
from .references import (
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
from .repository import read_source
from .serialization import document_digest
from .storage import (
    LocalArtifactStore,
    LocalStoreError,
    local_artifact_store,
    viper_cloud,
)

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
        self._local_git_roots: set[Path] = set()
        self._git_objects: dict[tuple[Path, str, str], bytes] = {}
        self._external_git_cache_bytes = 0
        self._external_git_checkout_root = self.cache_root / "git-checkouts"
        if self.cache_root != self.repository_root / ".viper/cache":
            self.store = LocalArtifactStore(
                store.repository_root,
                store.store,
                cache_root=self.cache_root / "verified-objects",
                targets=store.targets,
            )
        self._verified_paths: dict[ResolvedFileRef, Path] = {}
        self._verified_producers: dict[
            tuple[ResolvedRunRef, VerificationPolicy],
            VerifiedProducerRun,
        ] = {}
        self._cloud_services: dict[tuple[str, ...], ViperCloud] = {}
        self._reader_stack = ExitStack()
        self._reader_holds: dict[tuple[Path, RepoRelPath], WorkflowReaders] = {}
        self._reader_mutex = RLock()
        self._reader_closed = False
        self._reader_finalizer = finalize(self, self._reader_stack.close)

    def close(self) -> None:
        """Release standalone reader protection when this fetcher is no longer used."""
        with self._reader_mutex:
            self._reader_closed = True
            self._reader_finalizer()
            self._reader_holds.clear()

    def __enter__(self) -> Self:
        """Use this fetcher until the surrounding verification finishes."""
        if self._reader_closed:
            raise RuntimeError("run fetcher is already closed")
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Release this fetcher's standalone reader holds."""
        self.close()

    def _reader_hold(
        self, reference: ResolvedFileRef, root: Path, store: RepoRelPath
    ) -> None:
        """Protect the file until its workflow or standalone fetcher closes."""
        with self._reader_mutex:
            if self._reader_closed:
                raise RuntimeError("run fetcher is already closed")
            session = current_session()
            if session is not None:
                session.hold(reference, repository_root=root, store=store)
                return
            key = (root, store)
            readers = self._reader_holds.get(key)
            if readers is None:
                readers = self._reader_stack.enter_context(
                    WorkflowReaders(PayloadLocks(root, store))
                )
                self._reader_holds[key] = readers
            readers.hold(reference)

    @property
    def _verified_objects(self) -> VerifiedObjectCache:
        """Return the store cache used by existing transfer code."""
        return self.store.downloads

    def _cloud_service(self, reference: CloudReference) -> ViperCloud:
        """Reuse a cloud client while honoring any explicitly attached identity."""
        if isinstance(reference, (GcsFileRef, GcsStageResultSnapshotRef)):
            key: tuple[str, ...] = ("gcs", reference.bucket, reference.prefix)
        elif isinstance(
            reference, (HuggingFaceFileRef, HuggingFaceStageResultSnapshotRef)
        ):
            key = ("hf", reference.repository, reference.repo_type)
        else:
            key = ("configured", "", "")
        target = None
        session = current_session()
        targets = self.store.targets or (() if session is None else session.targets)
        if targets and not isinstance(
            reference, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)
        ):
            repository = ViperCloud._repository_for(reference)
            target = next(
                (selected for selected in targets if selected.repository == repository),
                None,
            )
            if target is not None:
                key = (*key, document_digest(target))
        if (
            target is None
            and isinstance(reference, (GcsFileRef, GcsStageResultSnapshotRef))
            and any(selected.gcp_service_account is not None for selected in targets)
        ):
            raise ValueError("cloud source has no matching attached target")
        remembered = self._cloud_services.get(key)
        if remembered is not None:
            return remembered
        if target is not None:
            cloud = ViperCloud.for_target(self.repository_root, target)
        elif isinstance(
            reference, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)
        ):
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
        return local_artifact_store(location=location, targets=self.store.targets)

    def _hold(self, reference: ResolvedFileRef) -> None:
        """Protect a file before returning a remembered or newly resolved path."""
        self._reader_hold(reference, self.store.repository_root, self.store.store)
        location = reference.stored_at
        if (
            isinstance(location, LocalFileRef)
            and (
                location.workspace != self.store.repository_root
                or location.store != self.store.store
            )
            and location.workspace.is_dir()
        ):
            self._reader_hold(reference, location.workspace, location.store)

    def _record_path(self, reference: ResolvedFileRef, path: Path) -> None:
        """Record the checked physical file and its original source workspace."""
        if isinstance(reference.stored_at, LocalFileRef):
            self._local_git_roots.add(reference.stored_at.workspace)
        if current_session() is None:
            return
        if path.is_relative_to(self.store.repository_root):
            self.store.record_path(reference, path)
        elif isinstance(reference.stored_at, LocalFileRef):
            local_artifact_store(reference.stored_at).record_path(reference, path)

    def _local_git_file(self, location: GitFileRef) -> tuple[Path, bytes]:
        """Try this checkout and matching original producer checkouts."""
        roots = (
            [self.repository_root]
            if str(location.repository) == self.source_repository
            else []
        )
        roots.extend(sorted(self._local_git_roots - {self.repository_root}))
        for root in roots:
            try:
                if root != self.repository_root and (
                    read_source(root).repository != location.repository
                ):
                    continue
                return root, run_git(root, "show", f"{location.commit}:{location.path}")
            except (OSError, ValueError):
                continue
        raise VerificationError("local Git evidence could not be read")

    def _actual_git_file(self, location: GitFileRef) -> tuple[Path, bytes]:
        """Read Git itself before accepting an unproved file coordinate."""
        try:
            return self._local_git_file(location)
        except VerificationError:
            if str(location.repository) == self.source_repository:
                raise
        checkout_identity = hashlib.sha256(
            f"{location.repository}\0{location.commit}".encode()
        ).hexdigest()
        checkout = self._external_git_checkout_root / checkout_identity
        return checkout, fetch_git_file_bytes(location, checkout=checkout)

    def _git_object(self, root: Path, kind: str, oid: str) -> bytes:
        """Reuse the immutable commit and tree objects read during this execution."""
        key = (root, kind, oid)
        if key not in self._git_objects:
            self._git_objects[key] = run_git(root, "cat-file", kind, oid)
        return self._git_objects[key]

    def _git_file(self, location: GitFileRef) -> tuple[bytes, Path]:
        """Resolve only bytes proved to belong to this pinned Git address."""
        try:
            proof = self.store.registry.git_file_proof(location)
            if proof is None:
                root, raw = self._actual_git_file(location)
                reference = ResolvedGitFileRef(
                    stored_at=location,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                )
                proof = capture_git_file_proof(
                    reference, lambda kind, oid: self._git_object(root, kind, oid)
                )
                self.store.registry.register_git_file(proof, raw)
                self._hold(reference)
                path = self.store.cache_verified_bytes(reference, raw)
            else:
                reference = proof.reference
                self._hold(reference)
                remembered = self._external_git_files.get(location)
                cached = (
                    self.store.cached_read(reference) if remembered is None else None
                )
                if remembered is not None:
                    raw = remembered
                    path = self.store.downloads.verified_path(reference)
                    if path is None:
                        path = self.store.cache_verified_bytes(reference, raw)
                elif cached is not None:
                    raw, path = cached
                else:
                    try:
                        raw, path = self.store.read_resolved(reference)
                    except LocalStoreError:
                        _, raw = self._actual_git_file(location)
                        verify_git_file_proof(proof, raw)
                        path = self.store.cache_verified_bytes(reference, raw)
                verify_git_file_proof(proof, raw)
        except VerificationError:
            raise
        except (OSError, ValueError) as error:
            raise VerificationError(
                "Git file address or membership proof is invalid"
            ) from error
        if (
            location not in self._external_git_files
            and self._external_git_cache_bytes + len(raw)
            <= _MAX_EXTERNAL_GIT_CACHE_BYTES
        ):
            self._external_git_files[location] = raw
            self._external_git_cache_bytes += len(raw)
        self._record_path(reference, path)
        self._verified_paths[reference] = path
        return raw, path

    def __call__(self, location: StorageModel) -> bytes:
        """Read a file from the location recorded in its reference."""
        if isinstance(location, GitFileRef):
            return self._git_file(location)[0]
        store = (
            self._local_store(location)
            if isinstance(location, LocalFileRef)
            else self.store
        )
        cloud = (
            None
            if isinstance(location, LocalFileRef)
            else lambda: self._cloud_service(location)
        )
        return self.read(store.reference(location, cloud=cloud))

    def read(self, reference: ResolvedFileRef) -> bytes:
        """Read the file and check its byte count and SHA-256 on first use."""
        if isinstance(reference.stored_at, GitFileRef):
            raw, path = self._git_file(reference.stored_at)
            raw = verify_resolved_file_bytes(reference, raw)
            self._verified_paths[reference] = path
            return raw
        self._hold(reference)
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            raw = remembered.read_bytes()
            self._record_path(reference, remembered)
            return raw
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
        self._record_path(reference, path)
        self._verified_paths[reference] = path
        return raw

    def path(self, reference: ResolvedFileRef) -> Path:
        """Return a local path after checking the file on first use."""
        if isinstance(reference.stored_at, GitFileRef):
            self.read(reference)
            return self._verified_paths[reference]
        self._hold(reference)
        remembered = self._verified_paths.get(reference)
        if remembered is not None:
            self._record_path(reference, remembered)
            return remembered
        if isinstance(reference.stored_at, LocalFileRef):
            path = self._local_store(reference.stored_at).resolve(reference)
        else:
            path = self.store.resolve(
                reference, cloud=lambda: self._cloud_service(reference.stored_at)
            )
        self._record_path(reference, path)
        self._verified_paths[reference] = path
        return path

    def remember_path(self, reference: ResolvedFileRef, path: Path) -> None:
        """Remember a file whose byte count and SHA-256 were checked during publication.

        The caller must pass the published file or its unchanged upload source.
        Its bytes must still match the reference.
        """
        if isinstance(reference.stored_at, GitFileRef):
            self.read(reference)
            return
        self._hold(reference)
        if path.stat().st_size != reference.bytes:
            raise VerificationError(
                f"byte-count mismatch: expected {reference.bytes}, "
                f"received {path.stat().st_size}"
            )
        self._record_path(reference, path)
        self._verified_paths[reference] = path

    def read_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
    ) -> VerifiedProducerRun | None:
        """Return a producer run already verified during this execution."""
        self._hold(reference)
        return self._verified_producers.get((reference, policy))

    def remember_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
        producer: VerifiedProducerRun,
    ) -> None:
        """Remember a verified producer run for later reads in this execution."""
        self._hold(reference)
        self._verified_producers[(reference, policy)] = producer

    def snapshot_files(
        self, snapshot: StageResultSnapshotRef
    ) -> tuple[SnapshotFileRef, ...]:
        """List every snapshot file with its byte count and SHA-256."""
        if isinstance(snapshot, LocalStageResultSnapshotRef):
            return self._local_store(snapshot).snapshot_files(snapshot)
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
