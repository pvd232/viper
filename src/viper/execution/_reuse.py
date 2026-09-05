from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml

from .._schema import ArtifactName, RepoRelPath
from .._verification.storage import read_snapshot_file
from ..artifacts import (
    ResolvedArtifact,
    ResolvedBundleArtifact,
    ResolvedBundleMember,
    ResolvedSingleFileArtifact,
)
from ..catalog import Catalog
from ..ids import InputName, MetricId, StageId
from ..inputs import ResolvedInputRef
from ..metrics import Measurement, MetricSpec
from ..references import (
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
)
from ..reuse import (
    ExecutedStageCompletion,
    ResolvedStageReuseRef,
    ReusedMetricEvidence,
    ReusedStageCompletion,
    ReusedStageFile,
    StageReuseKey,
    StageReuseReceipt,
    catalog_reuse_candidates,
)
from ..runs import ResolvedRun
from ..serialization import parse_yaml_bytes, serialize_document
from ..stages import (
    ParameterizedSpec,
    ResolvedBuildSpec,
    ResolvedEmbedSpec,
    ResolvedEvalSpec,
    ResolvedInternalSpec,
    ResolvedParameterizedSpec,
    ResolvedTrainSpec,
)
from ..storage import (
    SnapshotPublisher,
    StorageDestination,
    ViperCloudClient,
    publish_resolved_files,
    snapshot_file,
)
from ..verification import verify_run_result
from ..verification.models import StorageFetcher, VerificationPolicy


@dataclass(frozen=True)
class ReuseStageResult:
    """Return the resolved target stage and its source-file mapping."""

    resolved: ResolvedInternalSpec
    snapshot: StageResultSnapshot
    files: dict[RepoRelPath, SnapshotFileRef]


def _remap_artifacts(
    source: ResolvedParameterizedSpec,
    target: ParameterizedSpec,
) -> tuple[
    dict[ArtifactName, ResolvedArtifact],
    tuple[ReusedStageFile, ...],
    dict[RepoRelPath, SnapshotFileRef],
]:
    """Map source artifact bytes onto the target run's declared paths."""
    if set(source.artifacts) != set(target.artifacts):
        raise ValueError("reuse source artifact names differ from the target")
    artifacts: dict[ArtifactName, ResolvedArtifact] = {}
    receipt_files = []
    publication_files: dict[RepoRelPath, SnapshotFileRef] = {}
    for name, source_artifact in source.artifacts.items():
        target_spec = target.artifacts[name]
        if source_artifact.kind != target_spec.kind:
            raise ValueError("reuse source artifact kind differs from the target")
        if isinstance(source_artifact, ResolvedSingleFileArtifact):
            target_file = source_artifact.file.model_copy(
                update={"path": target_spec.path}
            )
            artifacts[name] = ResolvedSingleFileArtifact(file=target_file)
            receipt_files.append(
                ReusedStageFile(
                    artifact_name=name,
                    source=source_artifact.file,
                    target=target_file,
                )
            )
            publication_files[target_file.path] = source_artifact.file
            continue
        if not isinstance(source_artifact, ResolvedBundleArtifact):
            raise ValueError("reuse source artifact is unsupported")
        members = []
        for member in source_artifact.members:
            target_file = member.file.model_copy(
                update={"path": f"{target_spec.path}/{member.relative_path}"}
            )
            members.append(
                ResolvedBundleMember(
                    relative_path=member.relative_path,
                    file=target_file,
                )
            )
            receipt_files.append(
                ReusedStageFile(
                    artifact_name=name,
                    source=member.file,
                    target=target_file,
                )
            )
            publication_files[target_file.path] = member.file
        artifacts[name] = ResolvedBundleArtifact(members=tuple(members))
    return artifacts, tuple(receipt_files), publication_files


def _metric_evidence(
    stage_id: StageId,
    metrics: dict[MetricId, MetricSpec],
    measurement_files: tuple[ResolvedFileRef, ...],
    verification_files: tuple[ResolvedFileRef, ...],
    fetcher: StorageFetcher,
) -> tuple[ReusedMetricEvidence, ...]:
    """Link each selected source metric to the file containing its measurement."""
    found: dict[MetricId, ResolvedFileRef] = {}
    for reference in measurement_files:
        raw = fetcher(cast(StorageModel, reference.stored_at))
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            measurement = Measurement.model_validate(json.loads(line))
            if measurement.stage_id == stage_id and measurement.metric_id in metrics:
                found.setdefault(measurement.metric_id, reference)
    missing = set(metrics) - set(found)
    if missing:
        raise ValueError("reuse source is missing selected metric evidence")
    verifications: dict[MetricId, ResolvedFileRef] = {}
    prefix = f"/metric_verification/{stage_id}."
    for reference in verification_files:
        path = str(reference.stored_at.path)
        if prefix in path and path.endswith(".yaml"):
            metric_id = path.split(prefix, 1)[1].removesuffix(".yaml")
            if metric_id in metrics:
                verifications[metric_id] = reference
    if any(
        metric.mode == "recompute" and metric_id not in verifications
        for metric_id, metric in metrics.items()
    ):
        raise ValueError("reuse source is missing metric verification evidence")
    return tuple(
        ReusedMetricEvidence(
            metric_id=metric_id,
            measurement=found[metric_id],
            verification=(
                verifications.get(metric_id)
                if metrics[metric_id].mode == "recompute"
                else None
            ),
        )
        for metric_id in metrics
    )


def _resolved_stage(
    stage: ParameterizedSpec,
    *,
    completion: ReusedStageCompletion,
    artifacts: dict[ArtifactName, ResolvedArtifact],
    inputs: dict[InputName, ResolvedInputRef],
    completed_at: datetime,
) -> ResolvedInternalSpec:
    """Construct the resolved subtype selected by the target stage kind."""
    values = {
        "spec": stage,
        "completion": completion,
        "artifacts": artifacts,
        "inputs": inputs,
        "completed_at": completed_at,
    }
    if stage.kind == "build":
        return ResolvedBuildSpec(**values)
    if stage.kind == "embed":
        return ResolvedEmbedSpec(**values)
    if stage.kind == "train":
        return ResolvedTrainSpec(**values)
    return ResolvedEvalSpec(**values)


def reuse_stage(
    *,
    root: Path,
    catalog: Catalog,
    key: StageReuseKey,
    stage: ParameterizedSpec,
    inputs: dict[InputName, ResolvedInputRef],
    captured_inputs: dict[InputName, SnapshotFileRef],
    resolved_stage_path: str,
    fetcher: StorageFetcher,
    policy: VerificationPolicy,
    publisher: SnapshotPublisher,
    destination: StorageDestination,
    cloud_client: ViperCloudClient | None,
    metrics: dict[MetricId, MetricSpec],
) -> ReuseStageResult | None:
    """Verify one catalog hit and materialize it without running a worker."""
    candidate = catalog.reuse_candidate(key)
    if candidate is None:
        return None
    try:
        raw = fetcher(cast(StorageModel, candidate.source_run.stored_at))
        source_run = ResolvedRun.model_validate(parse_yaml_bytes(raw))
        verified = verify_run_result(source_run, policy=policy, fetcher=fetcher)
        rebuilt = next(
            (
                item
                for item in catalog_reuse_candidates(candidate.source_run, verified)
                if item.source_stage == candidate.source_stage
            ),
            None,
        )
        if rebuilt is None or rebuilt.key != key:
            return None
        source = verified.resolved_stages.get(key.stage_id)
        if not isinstance(source, ResolvedParameterizedSpec):
            return None
        if not isinstance(source.completion, ExecutedStageCompletion):
            return None
        artifacts, receipt_files, publication_files = _remap_artifacts(source, stage)
        attempt = next(
            item
            for item in verified.attempts
            if item.attempt_id == candidate.attempt_id
        )
        metric_evidence = _metric_evidence(
            key.stage_id,
            {metric_id: metrics[metric_id] for metric_id in stage.metric_ids},
            attempt.measurement_files,
            attempt.metric_verification_files,
            fetcher,
        )
        source_bytes = {
            target_path: read_snapshot_file(
                candidate.source_stage.snapshot,
                source_file,
                fetcher=fetcher,
            )
            for target_path, source_file in publication_files.items()
        }
        for captured in captured_inputs.values():
            if captured.path in publication_files:
                raise ValueError("captured input conflicts with a reused artifact")
            raw = (root / captured.path).read_bytes()
            if snapshot_file(captured.path, raw) != captured:
                raise ValueError("captured input changed before reuse publication")
            publication_files[captured.path] = captured
            source_bytes[captured.path] = raw
    except (
        KeyError,
        OSError,
        StopIteration,
        UnicodeDecodeError,
        ValueError,
        yaml.YAMLError,
    ):
        return None
    completed_at = datetime.now(UTC)
    receipt = StageReuseReceipt(
        stage_id=key.stage_id,
        key=key,
        source_run=candidate.source_run,
        source_attempt=candidate.source_attempt,
        source_stage=candidate.source_stage,
        files=receipt_files,
        metrics=metric_evidence,
        completed_at=completed_at,
    )
    receipt_path = resolved_stage_path.replace("resolved.yaml", "reuse.yaml")
    published = publish_resolved_files(
        root,
        destination,
        {receipt_path: serialize_document(receipt)},
        cloud_client=cloud_client,
    )[receipt_path]
    receipt_reference = ResolvedStageReuseRef.model_validate(
        published.model_dump(mode="json")
    )
    resolved = _resolved_stage(
        stage,
        completion=ReusedStageCompletion(receipt=receipt_reference),
        artifacts=artifacts,
        inputs=inputs,
        completed_at=completed_at,
    )
    snapshot = publisher.publish_reuse(
        resolved_stage_path=resolved_stage_path,
        resolved_stage=serialize_document(resolved),
        source_snapshot=candidate.source_stage.snapshot,
        files=publication_files,
        source_bytes=source_bytes,
    )
    return ReuseStageResult(
        resolved=resolved,
        snapshot=snapshot,
        files=publication_files,
    )
