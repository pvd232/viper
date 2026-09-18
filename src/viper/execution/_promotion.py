"""Promote a verified local run graph to configured cloud storage."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from ..artifacts import ArtifactPointer
from ..benchmark import BenchmarkResult, BenchmarkSpec
from ..cloud import ViperCloud
from ..evidence import VerificationPolicy
from ..metrics import MetricVerificationReceipt
from ..references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GitFileRef,
    HuggingFaceFileRef,
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
)
from ..reuse import ResolvedStageReuseRef, StageReuseReceipt
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt, RunSpec
from ..serialization import parse_yaml_bytes, serialize_document
from ..stages import ResolvedSpec, Spec
from ..storage import (
    LocalArtifactStore,
    ViperCloudDestination,
    content_revision,
    load_storage_settings,
    local_artifact_store,
)
from ..verification import verify_run_result
from ._restore import resolve_run_reference
from ._source import RunFetcher
from .errors import RunPromotionError

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)
_DocumentDecoder = Callable[[object], BaseModel]


class _RunGraphPromoter:
    """Rewrite one verified local reference DAG from its leaves upward."""

    def __init__(
        self,
        root: Path,
        cloud: ViperCloud,
        destination: ViperCloudDestination,
    ) -> None:
        self.root = root
        self.cloud = cloud
        self.destination = destination
        self.files: dict[LocalFileRef, ResolvedFileRef] = {}
        self.snapshots: dict[
            LocalStageResultSnapshotRef,
            CloudStageResultSnapshotRef,
        ] = {}
        self.snapshot_files: dict[
            LocalStageResultSnapshotRef,
            tuple[SnapshotFileRef, ...],
        ] = {}
        self.documents: dict[
            LocalStageResultSnapshotRef,
            dict[str, BaseModel],
        ] = {}
        self.local_bytes: dict[LocalFileRef, bytes] = {}
        self.promoting: set[LocalStageResultSnapshotRef] = set()

    @staticmethod
    def snapshot_for(location: LocalFileRef) -> LocalStageResultSnapshotRef:
        """Return the local snapshot containing one local file."""
        return LocalStageResultSnapshotRef(
            workspace=location.workspace,
            store=location.store,
            store_id=location.store_id,
            commit=location.commit,
        )

    def read_local(self, reference: ResolvedFileRef) -> bytes:
        """Read and verify one immutable local file once."""
        location = reference.stored_at
        if not isinstance(location, LocalFileRef):
            raise RunPromotionError("source run graph is unavailable")
        remembered = self.local_bytes.get(location)
        if remembered is not None:
            return remembered
        try:
            raw = local_artifact_store(location).fetch(location)
        except (OSError, RuntimeError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        if (
            len(raw) != reference.bytes
            or hashlib.sha256(raw).hexdigest() != reference.sha256
        ):
            raise RunPromotionError("source run graph is unavailable")
        self.local_bytes[location] = raw
        return raw

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
        """Register the typed document selected by one immutable reference."""
        location = reference.stored_at
        if not isinstance(location, LocalFileRef):
            return
        selected_decoder = decoder or self.document_decoder(reference)
        if selected_decoder is None:
            return
        snapshot = self.snapshot_for(location)
        documents = self.documents.setdefault(snapshot, {})
        if location.path in documents:
            return
        raw = self.read_local(reference)
        try:
            document = selected_decoder(parse_yaml_bytes(raw))
        except (UnicodeDecodeError, ValueError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
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

    def discover_snapshot_document(
        self,
        snapshot: LocalStageResultSnapshotRef,
        identity: SnapshotFileRef,
        decoder: _DocumentDecoder,
    ) -> None:
        """Register a typed member selected inside one immutable snapshot."""
        reference = ResolvedFileRef(
            sha256=identity.sha256,
            bytes=identity.bytes,
            stored_at=LocalFileRef(
                workspace=snapshot.workspace,
                store=snapshot.store,
                store_id=snapshot.store_id,
                commit=snapshot.commit,
                path=identity.path,
            ),
        )
        self.discover_reference(reference, decoder)

    def discover_plan_document(
        self,
        snapshot: LocalStageResultSnapshotRef,
        path: str,
        decoder: _DocumentDecoder,
    ) -> None:
        """Register a canonical plan member sealed by the plan snapshot."""
        location = LocalFileRef(
            workspace=snapshot.workspace,
            store=snapshot.store,
            store_id=snapshot.store_id,
            commit=snapshot.commit,
            path=path,
        )
        try:
            raw = local_artifact_store(location).fetch(location)
        except (OSError, RuntimeError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        reference = ResolvedFileRef(
            sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
            stored_at=location,
        )
        self.discover_reference(reference, decoder)

    def discover_plan_members(
        self,
        snapshot: LocalStageResultSnapshotRef,
        run: RunSpec,
    ) -> None:
        """Register every typed document selected by one frozen run plan."""
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
        if isinstance(reference.snapshot, LocalStageResultSnapshotRef):
            self.discover_snapshot_document(
                reference.snapshot,
                reference.resolved_spec,
                _RESOLVED_SPEC_ADAPTER.validate_python,
            )

    def discover_typed(self, value: Any) -> None:
        """Walk typed objects and register every referenced protocol document."""
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
        """Promote one local file after rewriting its referenced descendants."""
        location = reference.stored_at
        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            return reference
        if not isinstance(location, LocalFileRef):
            return reference
        remembered = self.files.get(location)
        if remembered is not None:
            return remembered
        self.read_local(reference)
        snapshot = self.snapshot_for(location)
        promoted_snapshot = self.promote_snapshot(snapshot)
        matches = tuple(
            file for file in self.snapshot_files[snapshot] if file.path == location.path
        )
        if len(matches) != 1:
            raise RunPromotionError("source run graph is unavailable")
        identity = matches[0]
        promoted = ResolvedFileRef(
            sha256=identity.sha256,
            bytes=identity.bytes,
            stored_at=self.cloud.file_ref(promoted_snapshot, identity.path),
        )
        self.files[location] = promoted
        return promoted

    def promote_snapshot(
        self,
        snapshot: LocalStageResultSnapshotRef,
    ) -> CloudStageResultSnapshotRef:
        """Promote every member of one local snapshot as a sealed unit."""
        remembered = self.snapshots.get(snapshot)
        if remembered is not None:
            return remembered
        if snapshot in self.promoting:
            raise RunPromotionError("source run graph contains a storage cycle")
        self.promoting.add(snapshot)
        store = local_artifact_store(snapshot)
        try:
            paths = store.list_snapshot_files(snapshot)
            original = {
                path: store.fetch(
                    LocalFileRef(
                        workspace=snapshot.workspace,
                        store=snapshot.store,
                        store_id=snapshot.store_id,
                        commit=snapshot.commit,
                        path=path,
                    )
                )
                for path in paths
            }
            if content_revision(original) != snapshot.commit:
                raise RunPromotionError("source run graph is unavailable")
            sources = dict(original)
            for path, document in self.documents.get(snapshot, {}).items():
                rewritten = self.rewrite_typed(document)
                if _contains_local_reference(rewritten):
                    raise RunPromotionError("promoted run graph retains local storage")
                sources[path] = serialize_document(rewritten)
        except (OSError, RuntimeError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        finally:
            self.promoting.remove(snapshot)
        promoted, files = self.cloud.publish(self.destination, sources)
        self.snapshots[snapshot] = promoted
        self.snapshot_files[snapshot] = files
        return promoted

    def promote_stage_reference(self, value: ResolvedStageRef) -> ResolvedStageRef:
        """Promote one stage snapshot and bind its rewritten resolved record."""
        if not isinstance(value.snapshot, LocalStageResultSnapshotRef):
            return value
        promoted_snapshot = self.promote_snapshot(value.snapshot)
        matches = tuple(
            file
            for file in self.snapshot_files[value.snapshot]
            if file.path == value.resolved_spec.path
        )
        if len(matches) != 1:
            raise RunPromotionError("source run graph is unavailable")
        return ResolvedStageRef(
            stage_id=value.stage_id,
            snapshot=promoted_snapshot,
            resolved_spec=matches[0],
        )

    def rewrite_typed(self, value: Any) -> Any:
        """Promote storage references while preserving protocol model types."""
        if isinstance(value, ResolvedStageRef):
            return self.promote_stage_reference(value)
        if isinstance(value, ResolvedFileRef):
            promoted = self.promote_reference(value)
            payload = value.model_dump(mode="python")
            payload.update(promoted.model_dump(mode="python"))
            return type(value).model_validate(payload)
        if isinstance(value, LocalStageResultSnapshotRef):
            return self.promote_snapshot(value)
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
    )
    promoter.discover_reference(reference, ResolvedRun.model_validate)
    promoted = promoter.promote_reference(reference)
    result = ResolvedRunRef.model_validate(promoted.model_dump(mode="python"))
    if not isinstance(result.stored_at, (GcsFileRef, HuggingFaceFileRef)):
        raise RunPromotionError("promoted run graph is not cloud-backed")
    return result


__all__ = ["promote_run_to_cloud"]
