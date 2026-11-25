"""Promote a verified local run graph to configured cloud storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .._cloud import PublicationSource, manifest_revision
from .._graph import RunGraphReader
from .._source import RunFetcher
from ..cloud import ViperCloud
from ..evidence import VerificationPolicy
from ..inputs import DownloadSourceClosureReceipt
from ..references import (
    ArtifactPointerRef,
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
    ViperCloudStageResultSnapshotRef,
)
from ..reuse import ResolvedStageReuseRef, StageReuseReceipt, stage_spec_sha256
from ..runs import ResolvedRun, RunSpec
from ..serialization import parse_yaml_bytes, serialize_document
from ..stages import InternalSpec, ResolvedSpec, Spec
from ..storage import (
    LocalArtifactStore,
    ViperCloudDestination,
    load_storage_settings,
    local_artifact_store,
)
from ..verification import verify_run_result
from ._promotion_journal import PublicationJournal
from ._promotion_transfer import TransferSpace
from ._restore import resolve_run_reference
from .errors import RunPromotionError

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)
_DocumentDecoder = Callable[[object], BaseModel]
_SourceSnapshotRef = StageResultSnapshotRef | GitSource
_SNAPSHOT_ADAPTER = TypeAdapter(_SourceSnapshotRef)


class RunGraphPromoter(RunGraphReader):
    """Rewrite one verified local reference DAG from its leaves upward."""

    def __init__(
        self,
        root: Path,
        cloud: ViperCloud,
        destination: ViperCloudDestination,
        *,
        fetcher: RunFetcher,
        journal: PublicationJournal | None = None,
        space: TransferSpace | None = None,
    ) -> None:
        """Use the shared graph reader and the supplied publication destination."""
        super().__init__(root, fetcher=fetcher, error_type=RunPromotionError)
        self.cloud = cloud
        self.destination = destination
        self.journal = journal
        self.space = space
        self._read_budget = space
        if space is not None:
            if journal is None:
                raise RunPromotionError("bounded copies require a publication journal")
            journal.space = space
            space.configure_cloud(cloud)
        self.files: dict[StorageModel, ResolvedFileRef] = {}
        self.snapshots: dict[_SourceSnapshotRef, CloudStageResultSnapshotRef] = {}
        self.snapshot_files: dict[_SourceSnapshotRef, tuple[SnapshotFileRef, ...]] = {}
        self.promoting: set[_SourceSnapshotRef] = set()
        self.receipt_hashes: dict[str, str] = {}

    def promote_reference(self, reference: ResolvedFileRef) -> ResolvedFileRef:
        """Publish a file after updating the documents it depends on."""
        location = reference.stored_at
        snapshot = self.snapshot_for(location)
        if self.inventory is None and not isinstance(location, LocalFileRef):
            return reference
        if isinstance(location, GitFileRef) and location.path not in self.documents.get(
            snapshot, {}
        ):
            return reference
        remembered = self.files.get(location)
        if remembered is not None:
            return remembered
        promoted_snapshot = self.promote_snapshot(snapshot)
        identity = next(
            (
                file
                for file in self.snapshot_files[snapshot]
                if file.path == location.path
            ),
            None,
        )
        if identity is None:
            raise RunPromotionError("source run graph is unavailable")
        promoted = ResolvedFileRef(
            sha256=identity.sha256,
            bytes=identity.bytes,
            stored_at=self.cloud.file_ref(promoted_snapshot, identity.path),
        )
        self.files[location] = promoted
        return promoted

    def promote_snapshot(
        self, snapshot: _SourceSnapshotRef
    ) -> CloudStageResultSnapshotRef:
        """Publish a complete snapshot after updating its saved references."""
        remembered = self.snapshots.get(snapshot)
        if remembered is not None:
            return remembered
        if snapshot in self.promoting:
            raise RunPromotionError("storage cycle")
        self.promoting.add(snapshot)
        try:
            self.discover_snapshot(snapshot)
            for child in sorted(
                self.dependencies.get(snapshot, ()),
                key=lambda item: item.model_dump_json(),
            ):
                if not isinstance(child, GitSource) or child in self.documents:
                    self.promote_snapshot(child)
            if isinstance(snapshot, GitSource):
                locations = tuple(
                    file
                    for file in self.source_files
                    if self.snapshot_for(file) == snapshot
                    and file.path in self.documents[snapshot]
                )
            else:
                locations = self.source_members[snapshot]
            if self.space is not None:
                sizes = [self.source_files[file][0] for file in locations]
                self.space.check(sum(sizes), max(sizes, default=0))
            original: dict[str, PublicationSource] = {}
            identities = []
            for location in locations:
                size, digest = self.source_files[location]
                if isinstance(location, LocalFileRef):
                    source = local_artifact_store(location).path(location)
                    identity = self.source_identity(location.path, source)
                    self._record_file(location, identity.bytes, identity.sha256)
                else:
                    if digest is None:
                        raise RunPromotionError("source file hash is missing")
                    identity = SnapshotFileRef(
                        path=location.path, bytes=size, sha256=digest
                    )
                    reference = ResolvedFileRef(
                        stored_at=location, bytes=size, sha256=digest
                    )
                    source = self.fetcher.path(reference)
                original[location.path] = source
                identities.append(identity)
            if (
                isinstance(snapshot, LocalStageResultSnapshotRef)
                and manifest_revision(tuple(identities)) != snapshot.commit
            ):
                raise RunPromotionError("source snapshot files changed")
            sources = self.rewrite_snapshot_documents(snapshot, original)
            promoted, files = self._publish_sources(
                sources, snapshot=snapshot, source_files=tuple(identities)
            )
            self.snapshots[snapshot] = promoted
            self.snapshot_files[snapshot] = files
            if self.space is not None:
                self.space.check()
                self.space.release(self.fetcher)
            return promoted
        except RunPromotionError:
            raise
        except Exception as error:
            raise RunPromotionError("source run graph is unavailable") from error
        finally:
            self.promoting.remove(snapshot)

    def _publish_sources(
        self,
        sources: dict[str, PublicationSource],
        *,
        snapshot: _SourceSnapshotRef,
        source_files: tuple[SnapshotFileRef, ...],
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Stage verified neighboring-store files within the publication root."""
        staging_root = (
            self.space.root / "staging"
            if self.space is not None
            else self.root / ".viper" / "promotion"
        )
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
            confined: dict[str, PublicationSource] = {}
            for path, source in sources.items():
                if isinstance(source, bytes) or source.is_relative_to(self.root):
                    confined[path] = source
                    continue
                staged = Path(temporary) / str(len(confined))
                try:
                    os.link(source, staged)
                except OSError:
                    shutil.copyfile(source, staged)
                confined[path] = staged
            if self.space is not None:
                self.space.check()
            if self.journal is not None:
                children = [
                    (
                        child.model_dump(mode="json"),
                        self.snapshots[child].model_dump(mode="json"),
                    )
                    for child in sorted(
                        self.dependencies.get(snapshot, ()),
                        key=lambda item: item.model_dump_json(),
                    )
                    if child in self.snapshots
                ]
                digest = hashlib.sha256(
                    json.dumps(children, sort_keys=True).encode()
                ).hexdigest()
                return self.journal.publish(snapshot, source_files, confined, digest)
            return self.cloud.publish(self.destination, confined)

    def rewrite_snapshot_documents(
        self,
        snapshot: _SourceSnapshotRef,
        original: dict[str, PublicationSource],
    ) -> dict[str, PublicationSource]:
        """Rewrite referenced documents and propagate changed stage identities."""
        sources = dict(original)
        documents = self.documents.get(snapshot, {})
        ordered = sorted(
            documents.items(),
            key=lambda item: (isinstance(item[1], RunSpec), item[0]),
        )
        for path, document in ordered:
            rewritten = self.rewrite_typed(document)
            if isinstance(rewritten, RunSpec):
                stages = tuple(
                    stage.model_copy(
                        update={
                            "sha256": identity.sha256,
                            "bytes": identity.bytes,
                        }
                    )
                    for stage in rewritten.stages
                    for identity in (
                        self.source_identity(stage.spec, sources[stage.spec]),
                    )
                )
                rewritten = rewritten.model_copy(update={"stages": stages})
            if _contains_local_reference(rewritten):
                raise RunPromotionError("promoted run graph retains local storage")
            if rewritten != document:
                sources[path] = serialize_document(rewritten)

        return sources

    def promote_stage_reference(self, value: ResolvedStageRef) -> ResolvedStageRef:
        """Promote one stage snapshot and bind its rewritten resolved record."""
        if self.inventory is None and not isinstance(
            value.snapshot, LocalStageResultSnapshotRef
        ):
            return value
        promoted_snapshot = self.promote_snapshot(value.snapshot)
        matches = tuple(
            file
            for file in self.snapshot_files[value.snapshot]
            if file.path == value.resolved_spec.path
        )
        if len(matches) != 1:
            raise RunPromotionError("source run graph is unavailable")
        self.receipt_hashes[value.resolved_spec.sha256] = matches[0].sha256
        return ResolvedStageRef(
            stage_id=value.stage_id,
            snapshot=promoted_snapshot,
            resolved_spec=matches[0],
        )

    def _rewrite_source_node_id(self, node_id: str) -> str:
        """Replace only receipt hashes in canonical source-graph identities."""
        if node_id.startswith(("pointer:", "reuse:")):
            kind, digest = node_id.split(":", 1)
            return f"{kind}:{self.receipt_hashes.get(digest, digest)}"
        prefix, separator, suffix = node_id.partition("/receipt:")
        if not separator:
            return node_id
        digest, slash, direction = suffix.partition("/")
        return (
            f"{prefix}{separator}{self.receipt_hashes.get(digest, digest)}"
            f"{slash}{direction}"
        )

    def _rewrite_source_closure(
        self, value: DownloadSourceClosureReceipt
    ) -> DownloadSourceClosureReceipt:
        """Keep source-graph links aligned with promoted immutable receipts."""
        roots = {
            name: tuple(
                sorted(
                    (self.rewrite_typed(root) for root in selected),
                    key=lambda root: (
                        root.run_id,
                        root.attempt_id,
                        root.stage_id,
                        root.input_name,
                        root.stage_receipt.resolved_spec.sha256,
                    ),
                )
            )
            for name, selected in value.roots.items()
        }
        nodes = {
            rewritten: node.model_copy(update={"node_id": rewritten})
            for node in value.nodes
            for rewritten in (self._rewrite_source_node_id(node.node_id),)
        }
        edges = {
            (source, target, edge.relation): edge.model_copy(
                update={"source": source, "target": target}
            )
            for edge in value.edges
            for source, target in (
                (
                    self._rewrite_source_node_id(edge.source),
                    self._rewrite_source_node_id(edge.target),
                ),
            )
        }
        return DownloadSourceClosureReceipt(
            roots=roots,
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            edges=tuple(edges[key] for key in sorted(edges)),
        )

    def rewrite_typed(self, value: Any) -> Any:
        """Promote storage references while preserving protocol model types."""
        if isinstance(value, ArtifactPointerRef) and self.inventory is not None:
            size, digest = self.source_files[value]
            if digest is None:
                raise RunPromotionError("source file hash is missing")
            original = ResolvedArtifactPointerRef(
                stored_at=value, bytes=size, sha256=digest
            )
            rewritten = self.promote_reference(original)
            self.receipt_hashes[digest] = rewritten.sha256
            return ResolvedArtifactPointerRef(**rewritten.model_dump())
        if isinstance(value, StageReuseReceipt):
            return self._rewrite_reuse_receipt(value)
        if isinstance(value, ResolvedStageRef):
            return self.promote_stage_reference(value)
        if isinstance(value, ResolvedFileRef):
            promoted = self.promote_reference(value)
            if isinstance(value, (ResolvedArtifactPointerRef, ResolvedStageReuseRef)):
                self.receipt_hashes[value.sha256] = promoted.sha256
            payload = value.model_dump(mode="python")
            payload.update(promoted.model_dump(mode="python"))
            return type(value).model_validate(payload)
        if isinstance(value, LocalStageResultSnapshotRef):
            return self.promote_snapshot(value)
        if self.inventory is not None and isinstance(
            value,
            (
                GcsStageResultSnapshotRef,
                HuggingFaceStageResultSnapshotRef,
                ViperCloudStageResultSnapshotRef,
            ),
        ):
            return self.promote_snapshot(value)
        if isinstance(value, DownloadSourceClosureReceipt):
            return self._rewrite_source_closure(value)
        if isinstance(value, BaseModel):
            updates = {
                name: self.rewrite_typed(getattr(value, name))
                for name in type(value).model_fields
            }
            updates.update(
                {
                    name: self.rewrite_typed(item)
                    for name, item in (value.model_extra or {}).items()
                }
            )
            return value.model_copy(update=updates)
        if isinstance(value, tuple):
            return tuple(self.rewrite_typed(item) for item in value)
        if isinstance(value, list):
            return [self.rewrite_typed(item) for item in value]
        if isinstance(value, dict):
            return {key: self.rewrite_typed(item) for key, item in value.items()}
        return value

    def _rewrite_reuse_receipt(self, value: StageReuseReceipt) -> StageReuseReceipt:
        """Bind the reuse key to its promoted source stage's pointer identities."""
        source = value.source_stage
        if self.inventory is None and not isinstance(
            source.snapshot, LocalStageResultSnapshotRef
        ):
            return value
        original = self.documents[source.snapshot][source.resolved_spec.path]
        rewritten_source = self.rewrite_typed(original)
        spec = getattr(rewritten_source, "spec", None)
        if not isinstance(spec, InternalSpec):
            raise RunPromotionError("reuse source is not an internal stage")
        updates = {
            name: self.rewrite_typed(getattr(value, name))
            for name in type(value).model_fields
            if name != "key"
        }
        updates["key"] = value.key.model_copy(
            update={"stage_sha256": stage_spec_sha256(spec)}
        )
        return value.model_copy(update=updates)


def _source_repository(root: Path, run: ResolvedRun) -> str:
    """Read the source repository from a local run's immutable plan."""
    location = run.spec.stored_at
    if isinstance(location, GitFileRef):
        return str(location.repository)
    if isinstance(location, LocalFileRef):
        raw = local_artifact_store(location).fetch(location)
    else:
        raw = RunFetcher(root, LocalArtifactStore(root), "")(location)
    return str(RunSpec.model_validate(parse_yaml_bytes(raw)).source.repository)


def _contains_local_reference(value: Any) -> bool:
    """Return whether a typed protocol graph still names local storage."""
    if isinstance(value, (LocalFileRef, LocalStageResultSnapshotRef)):
        return True
    if isinstance(value, BaseModel):
        return any(
            _contains_local_reference(item)
            for item in (
                *value.__dict__.values(),
                *(value.model_extra or {}).values(),
            )
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_local_reference(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_local_reference(item) for item in value.values())
    return False


def promote_run_to_cloud(
    repository_root: Path,
    source: Path | ResolvedRunRef,
    destination: ViperCloudDestination,
) -> ResolvedRunRef:
    """Verify and promote one local run graph to the required destination."""
    root = repository_root.resolve(strict=True)
    reference = resolve_run_reference(root, source)
    if not isinstance(reference.stored_at, LocalFileRef):
        raise RunPromotionError("source run graph is unavailable")
    try:
        raw = local_artifact_store(reference.stored_at).fetch(reference.stored_at)
        record = ResolvedRun.model_validate(parse_yaml_bytes(raw))
        source_repository = _source_repository(root, record)
        fetcher = RunFetcher(root, LocalArtifactStore(root), source_repository)
        verify_run_result(
            record,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({source_repository})
            ),
            fetcher=fetcher,
        )
    except Exception as error:
        raise RunPromotionError("source run graph is unavailable") from error
    settings = load_storage_settings(root)
    if settings.repository is None:
        raise RunPromotionError("cloud destination is not configured")
    promoter = RunGraphPromoter(
        root,
        ViperCloud(root, settings.repository),
        destination,
        fetcher=fetcher,
    )
    promoter.discover_reference(reference, ResolvedRun.model_validate)
    promoted = promoter.promote_reference(reference)
    result = ResolvedRunRef.model_validate(promoted.model_dump(mode="python"))
    if not isinstance(result.stored_at, (GcsFileRef, HuggingFaceFileRef)):
        raise RunPromotionError("promoted run graph is not cloud-backed")
    try:
        promoted_raw = promoter.cloud.fetch(result.stored_at)
        if (
            len(promoted_raw) != result.bytes
            or hashlib.sha256(promoted_raw).hexdigest() != result.sha256
        ):
            raise RunPromotionError("promoted run reference identity changed")
        promoted_record = ResolvedRun.model_validate(parse_yaml_bytes(promoted_raw))
        verify_run_result(
            promoted_record,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({source_repository})
            ),
            fetcher=RunFetcher(
                root,
                LocalArtifactStore(root),
                source_repository,
            ),
        )
    except Exception as error:
        raise RunPromotionError("promoted run graph failed verification") from error
    return result


__all__ = ["promote_run_to_cloud"]
