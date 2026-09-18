"""Retrieve exact source and immutable output bytes for run execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

import viper._subprocess as subprocess

from .._schema import RepoRelPath
from .._verification.storage import fetch_git_file_bytes, verify_resolved_file_bytes
from ..cloud import ViperCloud
from ..evidence import VerificationError, VerificationPolicy, VerifiedProducerRun
from ..references import (
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunRef,
    StageResultSnapshot,
    StorageModel,
)
from ..storage import LocalArtifactStore, local_artifact_store
from ._verified_cache import VerifiedObjectCache
from .errors import RunError

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
        raise RunError("local Git evidence could not be read") from exc


class RunFetcher:
    """Retrieve frozen Git source and repository-local immutable outputs."""

    _verify_local_content = True

    def __init__(
        self,
        repository_root: Path,
        store: LocalArtifactStore,
        source_repository: str,
    ) -> None:
        """Bind retrieval to one local Git checkout and output store.

        Immutable references determine when a previously verified local path may
        be reused. Callers cannot weaken that rule with a trust switch.
        """
        self.repository_root = repository_root.resolve()
        self.store = store
        self.source_repository = source_repository
        self._external_git_files: dict[GitFileRef, bytes] = {}
        self._external_git_cache_bytes = 0
        self._external_git_checkout_root = (
            self.repository_root / ".viper/cache/git-checkouts"
        )
        self._verified_objects = VerifiedObjectCache(
            self.repository_root / ".viper/cache/verified-objects"
        )
        self._verified_paths: dict[ResolvedFileRef, Path] = {}
        self._verified_producers: dict[
            tuple[ResolvedRunRef, VerificationPolicy],
            VerifiedProducerRun,
        ] = {}

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
        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            return ViperCloud.for_reference(self.repository_root, location).fetch(
                location
            )
        if isinstance(location, LocalFileRef):
            return local_artifact_store(location).fetch(location)
        return self.store.fetch(location)

    def read_verified(self, reference: ResolvedFileRef) -> bytes:
        """Reuse exact bytes across executions without trusting cache contents."""
        cacheable = not isinstance(reference.stored_at, LocalFileRef) and not (
            isinstance(reference.stored_at, GitFileRef)
            and str(reference.stored_at.repository) == self.source_repository
        )
        if cacheable:
            cached = self._verified_objects.read(reference)
            if cached is not None:
                return cached
        raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
        if cacheable:
            self._verified_objects.write(reference, raw)
        return raw

    def read_verified_path(self, reference: ResolvedFileRef) -> Path:
        """Return one path-backed verified object."""
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
            if self._verify_local_content:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != reference.sha256:
                    raise VerificationError(
                        f"SHA-256 mismatch: expected {reference.sha256}, "
                        f"received {digest}"
                    )
            self._verified_paths[reference] = path
            return path

        if not isinstance(reference.stored_at, (GcsFileRef, HuggingFaceFileRef)):
            raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
            self._verified_objects.write(reference, raw)
            path = self._verified_objects.path(reference)
            self._verified_paths[reference] = path
            return path

        cached = self._verified_objects.trusted_path(reference)
        if cached is not None:
            self._verified_paths[reference] = cached
            return cached

        temporary = self._verified_objects.temporary_path(reference)
        try:
            restored = ViperCloud.for_reference(
                self.repository_root,
                reference.stored_at,
            ).fetch_to_path(reference, temporary)
            cached = self._verified_objects.adopt_verified_path(reference, restored)
        finally:
            temporary.unlink(missing_ok=True)

        self._verified_paths[reference] = cached
        return cached

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

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshot,
    ) -> tuple[RepoRelPath, ...]:
        """List every regular file in one immutable stage snapshot."""
        if isinstance(
            snapshot,
            (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef),
        ):
            return tuple(
                file.path
                for file in ViperCloud.for_snapshot(
                    self.repository_root,
                    snapshot,
                ).list_files(snapshot)
            )
        return local_artifact_store(snapshot).list_snapshot_files(snapshot)


class ExecutionRunFetcher(RunFetcher):
    """Trust locally sealed store payloads only inside one active execution."""

    _verify_local_content = False


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
