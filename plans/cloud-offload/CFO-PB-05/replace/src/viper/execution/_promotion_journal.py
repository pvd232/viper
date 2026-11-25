"""Save publication progress so an interrupted copy can resume."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from pydantic import Field

from .._cloud import (
    GcsRepository,
    PublicationSource,
    RevisionManifest,
    SnapshotCopy,
    SnapshotInventory,
    canonical_json_bytes,
    manifest_revision,
    source_file,
)
from .._schema import SHA256, ProtocolModel
from ..cloud import ViperCloud
from ..huggingface import HuggingFaceProvider
from ..references import (
    CloudStageResultSnapshotRef,
    GcsStageResultSnapshotRef,
    GitSource,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from ..serialization import document_digest, parse_yaml_bytes
from ..storage import ViperCloudDestination
from ._promotion_transfer import TransferSpace
from ._publication import replace_synchronized
from .errors import RunPromotionError


def validate_exact_snapshot_copy(copy: SnapshotCopy) -> SnapshotCopy:
    """Require a destination to preserve a validated original inventory."""
    try:
        original = SnapshotInventory(
            source=copy.source,
            source_files=tuple(sorted(copy.source_files, key=lambda file: file.path)),
        )
    except ValueError as error:
        raise RunPromotionError("original snapshot inventory differs") from error

    if copy.expected.files != original.source_files:
        raise RunPromotionError(
            "destination inventory differs from the original snapshot"
        )

    return copy


class _Progress(ProtocolModel):
    """Bind saved copies to one publication request."""

    schema_version: Literal[1] = Field(default=1, description="Progress file format.")
    operation_sha256: SHA256 = Field(
        description="Hash of the inventory, policy, and destination."
    )
    copies: dict[str, SnapshotCopy] = Field(
        default_factory=dict,
        description="Expected and completed copies, keyed by source snapshot.",
    )


class PublicationJournal:
    """Keep one writer and reuse verified copies after a restart."""

    def __init__(
        self,
        path: Path,
        operation_sha256: SHA256,
        cloud: ViperCloud,
        destination: ViperCloudDestination,
    ) -> None:
        """Select the progress file and publication destination."""
        self.path = path
        self.cloud = cloud
        self.destination = destination
        self.progress = _Progress(operation_sha256=operation_sha256)
        self._lock: int | None = None
        self.space: TransferSpace | None = None

    def __enter__(self) -> Self:
        """Lock the progress file and check the request it describes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = os.open(
            self.path.with_suffix(".lock"),
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self._lock)
            self._lock = None
            raise RunPromotionError("publication journal is locked") from error
        try:
            if self.path.is_symlink():
                raise ValueError("progress file is a symlink")
            if self.path.exists():
                saved = _Progress.model_validate(
                    parse_yaml_bytes(self.path.read_bytes())
                )
                if saved.operation_sha256 != self.progress.operation_sha256:
                    raise ValueError("publication request changed")
                if any(
                    key != document_digest(copy.source)
                    for key, copy in saved.copies.items()
                ):
                    raise ValueError("source key changed")
                self.progress = saved
            return self
        except Exception as error:
            self.__exit__(None, None, None)
            raise RunPromotionError("publication journal differs") from error

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Release the writer lock and keep the saved progress."""
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    def _save(self) -> None:
        """Replace the progress file while holding its writer lock."""
        if self._lock is None:
            raise RunPromotionError("publication journal is not locked")
        replace_synchronized(self.path, canonical_json_bytes(self.progress))
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def publish(
        self,
        source: StageResultSnapshotRef | GitSource,
        source_files: tuple[SnapshotFileRef, ...],
        sources: dict[str, PublicationSource],
        dependencies_sha256: SHA256,
        *,
        exact_bytes: bool = False,
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Upload files with saved progress and verify them before returning."""
        if self._lock is None:
            raise RunPromotionError("publication journal is not locked")
        if not sources:
            raise RunPromotionError("cloud revision requires at least one file")
        original_files = tuple(sorted(source_files, key=lambda file: file.path))
        files = tuple(
            source_file(self.cloud.root, name, data)
            for name, data in sorted(sources.items())
        )
        expected = RevisionManifest(
            owner=self.destination.owner,
            workspace=self.destination.workspace,
            revision=manifest_revision(files),
            files=files,
        )
        candidate = SnapshotCopy(
            source=source,
            source_files=original_files,
            expected=expected,
            dependencies_sha256=dependencies_sha256,
            previous_head=None,
        )
        if exact_bytes:
            validate_exact_snapshot_copy(candidate)
        key = document_digest(source)
        saved = self.progress.copies.get(key)
        published: CloudStageResultSnapshotRef | None = None
        if saved is not None:
            if (
                saved.source != source
                or saved.source_files != original_files
                or saved.expected != expected
                or saved.dependencies_sha256 != dependencies_sha256
            ):
                raise RunPromotionError("publication journal differs")
            published = saved.published
            if published is None:
                if not exact_bytes:
                    published = self._recover(saved)
                elif isinstance(self.cloud.provider, HuggingFaceProvider):
                    if saved.previous_head is None:
                        raise RunPromotionError("publication journal differs")
                    published = self.cloud.provider.find_publication(
                        expected, saved.previous_head
                    )
                elif not isinstance(self.cloud.repository, GcsRepository):
                    raise RunPromotionError("publication provider cannot resume")
        else:
            previous = None
            if isinstance(self.cloud.provider, HuggingFaceProvider):
                previous = self.cloud.provider.publication_head()
            saved = candidate.model_copy(update={"previous_head": previous})
            self.progress.copies[key] = saved
            self._save()
        if published is None:
            try:
                published = self.cloud.provider.publish_revision(
                    destination=self.destination,
                    revision=expected.revision,
                    sources=sources,
                    files=files,
                )
            except Exception as error:
                raise RunPromotionError(
                    "remote publication outcome is unresolved"
                ) from error
        self._verify(published, expected)
        self.progress.copies[key] = saved.model_copy(update={"published": published})
        self._save()
        return published, files

    def _recover(self, saved: SnapshotCopy) -> CloudStageResultSnapshotRef:
        """Find the cloud location to check after an interrupted upload."""
        provider = self.cloud.provider
        if isinstance(provider, HuggingFaceProvider):
            if saved.previous_head is None:
                raise RunPromotionError("publication journal differs")
            published = provider.find_publication(saved.expected, saved.previous_head)
            if published is not None:
                return published
        else:
            repository = self.cloud.repository
            if isinstance(repository, GcsRepository):
                return GcsStageResultSnapshotRef(
                    bucket=repository.bucket,
                    prefix=repository.prefix,
                    owner=saved.expected.owner,
                    workspace=saved.expected.workspace,
                    revision=saved.expected.revision,
                )
        raise RunPromotionError("remote publication outcome is unresolved")

    def verify_destination(
        self,
        snapshot: CloudStageResultSnapshotRef,
        expected: RevisionManifest,
    ) -> None:
        """Verify an address and manifest without downloading payloads."""
        if ViperCloud._repository_for(snapshot) != self.cloud.repository:
            raise RunPromotionError("destination repository differs")
        if isinstance(snapshot, GcsStageResultSnapshotRef) and (
            snapshot.owner != expected.owner
            or snapshot.workspace != expected.workspace
            or snapshot.revision != expected.revision
        ):
            raise RunPromotionError("destination snapshot differs")
        if isinstance(self.cloud.provider, HuggingFaceProvider):
            if self.cloud.provider.read_manifest(snapshot) != expected:
                raise RunPromotionError("destination snapshot differs")
        elif self.cloud.list_files(snapshot) != expected.files:
            raise RunPromotionError("destination snapshot differs")

    def _verify(
        self,
        snapshot: CloudStageResultSnapshotRef,
        expected: RevisionManifest,
    ) -> None:
        """Read every destination file and check its saved size and hash."""
        self.verify_destination(snapshot, expected)
        if self.space is not None:
            self.space.check(
                largest_file=max((file.bytes for file in expected.files), default=0)
            )
            directory = self.space.root / "verification"
        else:
            directory = self.cloud.root / ".viper/promotion/verification"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as scratch:
            for member in expected.files:
                target = Path(scratch) / "file"
                self.cloud.fetch_to_path(
                    resolve_snapshot_file_ref(snapshot, member), target
                )
                if self.space is not None:
                    self.space.check()
                target.unlink()


def publish_captured_snapshot(
    journal: PublicationJournal,
    inventory: SnapshotInventory,
    sources: dict[str, PublicationSource],
) -> SnapshotCopy:
    """Upload the snapshot's files or reuse its verified cloud publication.

    This call waits for upload and verification.
    """
    if journal._lock is None:
        raise RunPromotionError("publication journal is not locked")
    key = document_digest(inventory.source)
    dependencies = hashlib.sha256(b"[]").hexdigest()
    saved = journal.progress.copies.get(key)
    if saved is not None:
        validate_exact_snapshot_copy(saved)
        if (
            saved.source != inventory.source
            or saved.source_files != inventory.source_files
            or saved.expected.owner != journal.destination.owner
            or saved.expected.workspace != journal.destination.workspace
            or saved.dependencies_sha256 != dependencies
        ):
            raise RunPromotionError("captured snapshot binding differs")
        if saved.published is not None:
            journal.verify_destination(saved.published, saved.expected)
            return saved
    journal.publish(
        inventory.source,
        inventory.source_files,
        sources,
        dependencies,
        exact_bytes=True,
    )
    return validate_exact_snapshot_copy(journal.progress.copies[key])
