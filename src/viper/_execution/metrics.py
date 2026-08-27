"""Produce and verify metrics selected by one completed stage."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ..experiments import ExperimentSpec
from ..ids import StageId
from ..local_store import LocalArtifactStore
from ..metric_execution import MetricExecutionError, execute_metric_process
from ..metrics import (
    FloatComparator,
    MeasurementSink,
    MetricSpec,
    MetricVerificationReceipt,
    ResolvedMetricDependency,
    compare_metric_values,
)
from ..references import ResolvedFileRef
from ..runs import RunSpec
from ..serialization import serialize_document
from ..stages import BaseSpec
from .errors import RunError
from .publication import _write_synchronized


def _artifact_paths(root: Path, stage: BaseSpec) -> dict[str, Path]:
    """Return the materialized path of each artifact declared by one stage."""
    return {name: root / artifact.path for name, artifact in stage.artifacts.items()}


def _publish_metric_dependency(
    root: Path,
    path: Path,
    store: LocalArtifactStore,
) -> tuple[ResolvedFileRef, ...]:
    """Publish every regular file represented by one metric dependency path."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RunError("metric dependency path escapes the repository root")
    if resolved.is_symlink():
        raise RunError("metric dependencies must not be symbolic links")
    if resolved.is_file():
        relative = resolved.relative_to(root).as_posix()
        return store.resolved_files({relative: resolved.read_bytes()})
    if not resolved.is_dir():
        raise RunError("metric dependency path is absent")
    files: dict[str, bytes] = {}
    for member in sorted(resolved.rglob("*")):
        if member.is_symlink():
            raise RunError("metric dependency bundles must not contain symlinks")
        if member.is_file():
            files[member.relative_to(root).as_posix()] = member.read_bytes()
    if not files:
        raise RunError("metric dependency bundle contains no regular files")
    return store.resolved_files(files)


def _resolve_metric_dependencies(
    root: Path,
    stage: BaseSpec,
    metric: MetricSpec,
    input_paths: Mapping[str, Path],
    store: LocalArtifactStore,
) -> tuple[ResolvedMetricDependency, ...]:
    """Bind each declared metric dependency to immutable file references."""
    artifact_paths = _artifact_paths(root, stage)
    resolved: list[ResolvedMetricDependency] = []
    for dependency in metric.dependencies:
        selected = (
            input_paths[dependency.name]
            if dependency.source == "input"
            else artifact_paths[dependency.name]
        )
        resolved.append(
            ResolvedMetricDependency(
                dependency=dependency,
                files=_publish_metric_dependency(root, selected, store),
            )
        )
    return tuple(resolved)


def _run_after_stage_metrics(
    root: Path,
    run: RunSpec,
    stage_id: StageId,
    stage: BaseSpec,
    experiment: ExperimentSpec,
    input_paths: Mapping[str, Path],
    measurement_paths: list[Path],
    metric_verification_paths: list[Path],
    store: LocalArtifactStore,
    timeout_seconds: float | None,
    attempt_id: int,
) -> None:
    """Invoke each selected recomputed metric in a controlled child process."""
    metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for metric_id in stage.metric_ids:
        metric = metrics[metric_id]
        if metric.mode != "recompute":
            continue
        dependencies = _resolve_metric_dependencies(
            root,
            stage,
            metric,
            input_paths,
            store,
        )
        available_artifacts = _artifact_paths(root, stage)
        metric_inputs = {
            dependency.name: input_paths[dependency.name]
            for dependency in metric.dependencies
            if dependency.source == "input"
        }
        metric_artifacts = {
            dependency.name: available_artifacts[dependency.name]
            for dependency in metric.dependencies
            if dependency.source == "artifact"
        }
        try:
            process = execute_metric_process(
                root,
                run,
                stage_id,
                stage,
                metric,
                purpose="measurement",
                attempt_id=attempt_id,
                input_paths=metric_inputs,
                artifact_paths=metric_artifacts,
                dependencies=dependencies,
                timeout_seconds=timeout_seconds,
            )
        except MetricExecutionError as exc:
            raise RunError(f"metric {metric_id!r} invocation failed") from exc
        path = (
            root
            / f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
            / f"attempts/{attempt_id}/measurements"
            / f"{stage_id}.{metric_id}.jsonl"
        )
        measurement = MeasurementSink(
            path,
            run_id=run.run_id,
            attempt_id=attempt_id,
            stage_id=stage_id,
            metric_id=metric_id,
        ).append(process.receipt.value)
        measurement_paths.append(path)
        try:
            verification = execute_metric_process(
                root,
                run,
                stage_id,
                stage,
                metric,
                purpose="verification",
                attempt_id=attempt_id,
                input_paths=metric_inputs,
                artifact_paths=metric_artifacts,
                dependencies=dependencies,
                timeout_seconds=timeout_seconds,
            )
        except MetricExecutionError as exc:
            raise RunError(f"metric {metric_id!r} verification failed") from exc
        comparator = cast(FloatComparator, metric.comparator)
        passed = compare_metric_values(
            measurement.value,
            verification.receipt.value,
            comparator,
        )
        receipt = MetricVerificationReceipt(
            metric_id=metric_id,
            stage_id=stage_id,
            measurement=measurement,
            production=process.receipt,
            recomputation=verification.receipt,
            comparator=comparator,
            passed=passed,
            completed_at=datetime.now(UTC),
        )
        receipt_path = (
            root
            / f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
            / f"attempts/{attempt_id}/metric_verification"
            / f"{stage_id}.{metric_id}.yaml"
        )
        _write_synchronized(receipt_path, serialize_document(receipt))
        metric_verification_paths.append(receipt_path)
        if not passed:
            raise RunError(f"metric {metric_id!r} failed independent recomputation")
