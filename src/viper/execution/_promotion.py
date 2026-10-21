"""Promote a verified local run graph to configured cloud storage."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from .._cloud import GcsRepository, PublicationSource, manifest_revision
from .._schema import ProtocolModel
from .._source import RunFetcher
from ..artifacts import ArtifactPointer
from ..benchmark import BenchmarkResult, BenchmarkSpec
from ..cloud import ViperCloud
from ..evidence import VerificationPolicy
from ..experiments import ExperimentSpec, VariantSpec
from ..inputs import DownloadSourceClosureReceipt
from ..metrics import MetricVerificationReceipt
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
    ResolvedBenchmarkResultRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from ..reuse import ResolvedStageReuseRef, StageReuseReceipt, stage_spec_sha256
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt, RunSpec
from ..serialization import parse_yaml_bytes, serialize_document
from ..stages import InternalSpec, ResolvedSpec, Spec
from ..storage import (
    LocalArtifactStore,
    ViperCloudDestination,
    load_storage_settings,
    local_artifact_store,
)
from ..verification import verify_run_result
from ._restore import resolve_run_reference
from .errors import RunPromotionError

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)
_DocumentDecoder = Callable[[object], BaseModel]
_SourceSnapshot = StageResultSnapshot | GitSource
_SNAPSHOT_ADAPTER = TypeAdapter(_SourceSnapshot)


class PromotionInventory(ProtocolModel):
    """Name the runs and files that an additional publication must contain."""

    schema_version: Literal[1] = Field(
        default=1, description="Inventory format version."
    )
    roots: tuple[ResolvedRunRef, ...] = Field(
        min_length=1, description="Runs to publish."
    )
    required_files: dict[str, ResolvedFileRef] = Field(
        description="Expected files, keyed by their role in the application."
    )


class _RunGraphPromoter:
    """Rewrite one verified local reference DAG from its leaves upward."""

    def __init__(
        self,
        root: Path,
        cloud: ViperCloud,
        destination: ViperCloudDestination,
        *,
        fetcher: RunFetcher,
    ) -> None:
        """Use the supplied fetcher for source documents."""
        self.root = root
        self.cloud = cloud
        self.destination = destination
        self.fetcher = fetcher
        self.files: dict[StorageModel, ResolvedFileRef] = {}
        self.snapshots: dict[
            _SourceSnapshot,
            CloudStageResultSnapshotRef,
        ] = {}
        self.snapshot_files: dict[
            _SourceSnapshot,
            tuple[SnapshotFileRef, ...],
        ] = {}
        self.documents: dict[
            _SourceSnapshot,
            dict[str, BaseModel],
        ] = {}
        self.promoting: set[_SourceSnapshot] = set()
        self.receipt_hashes: dict[str, str] = {}
        self.inventory: PromotionInventory | None = None
        self.source_files: dict[StorageModel, tuple[int, str | None]] = {}
        self.source_members: dict[_SourceSnapshot, tuple[StorageModel, ...]] = {}
        self.dependencies: dict[_SourceSnapshot, set[_SourceSnapshot]] = {}
        self._reading: list[StorageModel] = []

    @staticmethod
    def snapshot_for(location: StorageModel) -> _SourceSnapshot:
        """Return the snapshot containing a file."""
        return _SNAPSHOT_ADAPTER.validate_python(location.model_dump(exclude={"path"}))

    @staticmethod
    def file_in_snapshot(
        snapshot: _SourceSnapshot, file: SnapshotFileRef
    ) -> ResolvedFileRef:
        """Combine a file's size and hash with its snapshot address."""
        if isinstance(snapshot, GitSource):
            location = GitFileRef(**snapshot.model_dump(), path=file.path)
            return ResolvedFileRef(
                stored_at=location, sha256=file.sha256, bytes=file.bytes
            )
        return resolve_snapshot_file_ref(snapshot, file)

    def _record_file(
        self, location: StorageModel, size: int, digest: str | None
    ) -> None:
        """Record a file once and reject conflicting sizes or hashes."""
        previous = self.source_files.get(location)
        if previous is not None:
            if previous[0] != size or (
                previous[1] and digest and previous[1] != digest
            ):
                raise RunPromotionError("conflicting source identity")
            digest = digest or previous[1]
        self.source_files[location] = (size, digest)

    def discover_snapshot(self, snapshot: _SourceSnapshot) -> None:
        """List a snapshot's files before reading any artifact bodies."""
        if snapshot in self.source_members or isinstance(snapshot, GitSource):
            return
        if isinstance(snapshot, LocalStageResultSnapshotRef):
            store = local_artifact_store(snapshot)
            locations = []
            for path in store.list_snapshot_files(snapshot):
                location = LocalFileRef(
                    **snapshot.model_dump(exclude={"kind"}), path=path
                )
                self._record_file(location, store.path(location).stat().st_size, None)
                locations.append(location)
        else:
            locations = []
            for member in self.fetcher.snapshot_files(snapshot):
                reference = resolve_snapshot_file_ref(snapshot, member)
                self._record_file(reference.stored_at, member.bytes, member.sha256)
                locations.append(reference.stored_at)
        self.source_members[snapshot] = tuple(locations)

    def discover_inventory(
        self, inventory: PromotionInventory
    ) -> tuple[_SourceSnapshot, ...]:
        """List the required files and return snapshots in dependency order."""
        self.inventory = inventory
        for reference in inventory.roots:
            self.discover_reference(reference, ResolvedRun.model_validate)
        for role, reference in inventory.required_files.items():
            actual = self.source_files.get(reference.stored_at)
            if actual is None:
                raise RunPromotionError(f"inventory item is unreachable: {role}")
            self._record_file(reference.stored_at, reference.bytes, reference.sha256)
        ordered: list[_SourceSnapshot] = []
        active: set[_SourceSnapshot] = set()
        complete: set[_SourceSnapshot] = set()

        def visit(snapshot: _SourceSnapshot) -> None:
            """Place each dependency before the snapshot that uses it."""
            if snapshot in active:
                raise RunPromotionError("storage cycle")
            if snapshot in complete:
                return
            active.add(snapshot)
            for child in sorted(
                self.dependencies.get(snapshot, ()), key=lambda x: x.model_dump_json()
            ):
                visit(child)
            active.remove(snapshot)
            complete.add(snapshot)
            ordered.append(snapshot)

        for snapshot in self.source_members:
            visit(snapshot)
        return tuple(ordered)

    def read_document(self, reference: ResolvedFileRef) -> bytes:
        """Read a run document through the supplied fetcher."""
        try:
            return self.fetcher.read(reference)
        except Exception as err:
            raise RunPromotionError("source run graph is unavailable") from err

    @staticmethod
    def source_identity(path: str, source: PublicationSource) -> SnapshotFileRef:
        """Identify one publication source without retaining its payload."""
        if isinstance(source, bytes):
            return SnapshotFileRef(
                path=path,
                sha256=hashlib.sha256(source).hexdigest(),
                bytes=len(source),
            )
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return SnapshotFileRef(path=path, sha256=digest.hexdigest(), bytes=size)

    @staticmethod
    def document_decoder(reference: ResolvedFileRef) -> _DocumentDecoder | None:
        """Select a document schema from the reference's protocol role."""
        if isinstance(reference, ResolvedRunRef):
            return ResolvedRun.model_validate
        if isinstance(reference, ResolvedRunSpecRef):
            return RunSpec.model_validate
        if isinstance(reference, ResolvedAttemptRef):
            return RunAttempt.model_validate
        if isinstance(reference, ResolvedArtifactPointerRef):
            return ArtifactPointer.model_validate
        if isinstance(reference, ResolvedStageReuseRef):
            return StageReuseReceipt.model_validate
        if isinstance(reference, ResolvedBenchmarkSpecRef):
            return BenchmarkSpec.model_validate
        if isinstance(reference, ResolvedBenchmarkResultRef):
            return BenchmarkResult.model_validate
        return None

    def discover_reference(
        self,
        reference: ResolvedFileRef,
        decoder: _DocumentDecoder | None = None,
    ) -> None:
        """Record a file and follow the links in its saved document."""
        location = reference.stored_at
        if self.inventory is None and not isinstance(location, LocalFileRef):
            return
        if isinstance(location, ViperCloudFileRef):
            if not isinstance(
                load_storage_settings(self.root).repository, GcsRepository
            ):
                raise RunPromotionError("legacy source binding is required")
        self._record_file(location, reference.bytes, reference.sha256)
        snapshot = self.snapshot_for(location)
        if self.inventory is not None:
            self.discover_snapshot(snapshot)
            if self._reading:
                parent = self.snapshot_for(self._reading[-1])
                if parent != snapshot:
                    self.dependencies.setdefault(parent, set()).add(snapshot)
        selected_decoder = decoder or self.document_decoder(reference)
        if selected_decoder is None:
            return
        if location in self._reading:
            raise RunPromotionError("storage cycle")
        documents = self.documents.setdefault(snapshot, {})
        if location.path in documents:
            return
        self._reading.append(location)
        try:
            document = selected_decoder(parse_yaml_bytes(self.read_document(reference)))
            documents[location.path] = document
            if isinstance(document, RunSpec):
                self.discover_plan_members(snapshot, document)
            if isinstance(document, RunAttempt):
                for metric in document.metric_verification_files:
                    self.discover_reference(
                        metric, MetricVerificationReceipt.model_validate
                    )
            if isinstance(document, BenchmarkResult):
                for metric in document.metrics:
                    self.discover_reference(
                        metric.candidate_verification,
                        MetricVerificationReceipt.model_validate,
                    )
                    self.discover_reference(
                        metric.confirmation_verification,
                        MetricVerificationReceipt.model_validate,
                    )
            if isinstance(document, StageReuseReceipt):
                for metric in document.metrics:
                    if metric.verification is not None:
                        self.discover_reference(
                            metric.verification,
                            MetricVerificationReceipt.model_validate,
                        )
            self.discover_typed(document)
        except RunPromotionError:
            raise
        except Exception as error:
            raise RunPromotionError("source run graph is unavailable") from error
        finally:
            self._reading.pop()

    def discover_snapshot_document(
        self,
        snapshot: _SourceSnapshot,
        identity: SnapshotFileRef,
        decoder: _DocumentDecoder,
    ) -> None:
        """Follow a document using its snapshot, path, size, and hash."""
        self.discover_reference(self.file_in_snapshot(snapshot, identity), decoder)

    def discover_plan_document(
        self,
        snapshot: _SourceSnapshot,
        path: str,
        decoder: _DocumentDecoder,
    ) -> None:
        """Read a saved plan file and follow its references."""
        if isinstance(snapshot, (LocalStageResultSnapshotRef, GitSource)):
            placeholder = SnapshotFileRef(path=path, bytes=0, sha256="0" * 64)
            location = self.file_in_snapshot(snapshot, placeholder).stored_at
            raw = self.fetcher(location)
            identity = SnapshotFileRef(
                path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
            )
        else:
            identity = next(
                (
                    file
                    for file in self.fetcher.snapshot_files(snapshot)
                    if file.path == path
                ),
                None,
            )
            if identity is None:
                raise RunPromotionError("plan document is missing from snapshot")
        self.discover_snapshot_document(snapshot, identity, decoder)

    def discover_plan_members(
        self,
        snapshot: _SourceSnapshot,
        run: RunSpec,
    ) -> None:
        """Register every typed document selected by one frozen run plan."""
        if self.inventory is not None:
            self.discover_plan_document(
                snapshot,
                f"experiments/{run.experiment_id}/spec.yaml",
                ExperimentSpec.model_validate,
            )
            self.discover_plan_document(
                snapshot,
                f"experiments/{run.experiment_id}/variants/{run.variant_id}.spec.yaml",
                VariantSpec.model_validate,
            )
        for stage in run.stages:
            self.discover_snapshot_document(
                snapshot,
                SnapshotFileRef(
                    path=stage.spec,
                    sha256=stage.sha256,
                    bytes=stage.bytes,
                ),
                _SPEC_ADAPTER.validate_python,
            )
        if run.benchmark_id is not None:
            self.discover_plan_document(
                snapshot,
                f"benchmarks/{run.benchmark_id}.spec.yaml",
                BenchmarkSpec.model_validate,
            )

    def discover_stage_reference(self, reference: ResolvedStageRef) -> None:
        """Register the resolved stage document selected by a stage reference."""
        if self.inventory is not None or isinstance(
            reference.snapshot, LocalStageResultSnapshotRef
        ):
            self.discover_snapshot_document(
                reference.snapshot,
                reference.resolved_spec,
                _RESOLVED_SPEC_ADAPTER.validate_python,
            )

    def discover_typed(self, value: Any) -> None:
        """Walk typed objects and register every referenced protocol document."""
        if isinstance(value, ArtifactPointerRef) and self.inventory is not None:
            raw = self.fetcher(value)
            reference = ResolvedArtifactPointerRef(
                stored_at=value, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
            )
            self.discover_reference(reference)
            return
        if isinstance(value, SnapshotFileRef) and self._reading:
            snapshot = self.snapshot_for(self._reading[-1])
            reference = self.file_in_snapshot(snapshot, value)
            if reference.stored_at in self.source_files:
                self._record_file(reference.stored_at, value.bytes, value.sha256)
            return
        if isinstance(value, ResolvedStageRef):
            self.discover_stage_reference(value)
            return
        if isinstance(value, ResolvedFileRef):
            self.discover_reference(value)
            return
        if isinstance(value, BaseModel):
            for item in value.__dict__.values():
                self.discover_typed(item)
            for item in (value.model_extra or {}).values():
                self.discover_typed(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                self.discover_typed(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self.discover_typed(item)

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
        self, snapshot: _SourceSnapshot
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
            if isinstance(snapshot, GitSource):
                locations = tuple(
                    file
                    for file in self.source_files
                    if self.snapshot_for(file) == snapshot
                    and file.path in self.documents[snapshot]
                )
            else:
                locations = self.source_members[snapshot]
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
            promoted, files = self._publish_sources(sources)
            self.snapshots[snapshot] = promoted
            self.snapshot_files[snapshot] = files
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
    ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
        """Stage verified neighboring-store files within the publication root."""
        staging_root = self.root / ".viper" / "promotion"
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
            return self.cloud.publish(self.destination, confined)

    def rewrite_snapshot_documents(
        self,
        snapshot: _SourceSnapshot,
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
    promoter = _RunGraphPromoter(
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
