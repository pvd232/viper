"""Launch one recomputed metric in a controlled child process."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

import viper._subprocess as subprocess

from .._schema import ArtifactName
from ..artifacts import ResolvedArtifact, ResolvedSingleFileArtifact
from ..experiments import ExperimentSpec
from ..ids import InputName, StageId
from ..inputs import (
    FutureInputRef,
    ResolvedExternalInputRef,
    ResolvedFutureInputRef,
    ResolvedStoredInputRef,
)
from ..metrics import (
    FloatComparator,
    MeasurementSink,
    MetricExecutionReceipt,
    MetricSpec,
    MetricVerificationReceipt,
    ResolvedMetricDependency,
    compare_metric_values,
    is_recomputed_metric,
)
from ..references import (
    ResolvedFileRef,
    ResolvedStageRef,
    SnapshotFileRef,
    resolve_snapshot_file_ref,
)
from ..runs import RunSpec
from ..runtime import process_environment, select_cuda_device
from ..serialization import serialize_document
from ..stages import BaseSpec, InternalSpec, ResolvedBaseSpec, ResolvedInternalSpec
from ._publication import write_synchronized
from .errors import RunError


class MetricExecutionError(RuntimeError):
    """Report a failed or malformed metric worker invocation."""


class MetricWorkerContext(BaseModel):
    """Supply one exact metric invocation to the controlled child."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_root: Path
    run: RunSpec
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    stage: BaseSpec
    metric: MetricSpec
    purpose: Literal["measurement", "verification"]
    input_paths: dict[InputName, Path]
    artifact_paths: dict[ArtifactName, Path]
    dependencies: tuple[ResolvedMetricDependency, ...]
    result_path: Path


class MetricWorkerResult(BaseModel):
    """Return one successful receipt or one bounded worker error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: MetricExecutionReceipt | None = None
    error: str | None = None


@dataclass(frozen=True)
class MetricProcessResult:
    """Return the worker receipt and captured process output."""

    receipt: MetricExecutionReceipt
    stdout: bytes
    stderr: bytes


def execute_metric_process(
    repository_root: Path,
    run: RunSpec,
    stage_id: StageId,
    stage: BaseSpec,
    metric: MetricSpec,
    *,
    attempt_id: int = 1,
    purpose: Literal["measurement", "verification"],
    input_paths: dict[InputName, Path],
    artifact_paths: dict[ArtifactName, Path],
    dependencies: tuple[ResolvedMetricDependency, ...],
    timeout_seconds: float | None = None,
) -> MetricProcessResult:
    """Apply startup controls and execute one frozen metric callable."""
    root = repository_root.resolve()
    if not is_recomputed_metric(metric):
        raise MetricExecutionError("metric worker requires a recomputed metric")
    if metric.metric_id not in stage.metric_ids:
        raise MetricExecutionError("stage does not select the metric")
    expected_dependencies = tuple(metric.dependencies)
    if tuple(value.dependency for value in dependencies) != expected_dependencies:
        raise MetricExecutionError(
            "resolved metric dependencies differ from MetricSpec"
        )

    effective_environment = stage.env or run.env
    compute = effective_environment.compute
    cuda_ordinal = select_cuda_device(compute.model) if compute.kind == "cuda" else None
    env = os.environ.copy()
    env.update(
        {
            str(key): value
            for key, value in process_environment(
                run.seed,
                run.reproducibility,
                compute,
                cuda_ordinal=cuda_ordinal,
            ).items()
        }
    )
    package_root = str(Path(__file__).resolve().parents[2])
    existing_python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        package_root
        if existing_python_path is None
        else f"{package_root}{os.pathsep}{existing_python_path}"
    )

    runtime_root = root / ".viper" / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    prefix = f"{run.run_id}.{attempt_id}.{stage_id}.{metric.metric_id}.{purpose}"
    context_path = runtime_root / f"{prefix}.context.json"
    result_path = runtime_root / f"{prefix}.result.json"
    result_path.unlink(missing_ok=True)
    context = MetricWorkerContext(
        repository_root=root,
        run=run,
        attempt_id=attempt_id,
        stage_id=stage_id,
        stage=stage,
        metric=metric,
        purpose=purpose,
        input_paths=input_paths,
        artifact_paths=artifact_paths,
        dependencies=dependencies,
        result_path=result_path,
    )
    context_path.write_text(context.model_dump_json(), encoding="utf-8")
    env["VIPER_METRIC_CONTEXT_PATH"] = str(context_path)

    completed = subprocess.run(
        (sys.executable, "-m", "viper._workers.metrics"),
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if not result_path.is_file():
        raise MetricExecutionError(
            f"metric worker exited with status {completed.returncode} without a result"
        )
    try:
        worker_result = MetricWorkerResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise MetricExecutionError("metric worker wrote an invalid result") from exc
    if completed.returncode != 0 or worker_result.error is not None:
        detail = worker_result.error or completed.stderr.decode(errors="replace")
        raise MetricExecutionError(
            f"metric worker exited with status {completed.returncode}: {detail.strip()}"
        )
    if worker_result.receipt is None:
        raise MetricExecutionError("successful metric worker omitted its receipt")
    return MetricProcessResult(
        receipt=worker_result.receipt,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _artifact_paths(root: Path, stage: BaseSpec) -> dict[str, Path]:
    """Return the materialized path of each artifact declared by one stage."""
    return {name: root / artifact.path for name, artifact in stage.artifacts.items()}


def _artifact_files(artifact: ResolvedArtifact) -> tuple[SnapshotFileRef, ...]:
    """Return every snapshot member represented by one resolved artifact."""
    if isinstance(artifact, ResolvedSingleFileArtifact):
        return (artifact.file,)
    return tuple(member.file for member in artifact.members)


def _resolve_metric_dependencies(
    stage: InternalSpec,
    resolved_stage: ResolvedInternalSpec,
    current_stage: ResolvedStageRef,
    completed_results: Mapping[StageId, ResolvedBaseSpec],
    metric: MetricSpec,
    stored_inputs: Mapping[InputName, tuple[ResolvedFileRef, ...]],
) -> tuple[ResolvedMetricDependency, ...]:
    """Reuse the immutable snapshot references selected by each dependency."""
    resolved: list[ResolvedMetricDependency] = []
    for dependency in metric.dependencies:
        if dependency.source == "artifact":
            files = tuple(
                resolve_snapshot_file_ref(current_stage.snapshot, file)
                for file in _artifact_files(resolved_stage.artifacts[dependency.name])
            )
        else:
            declared = stage.inputs[dependency.name]
            realized = resolved_stage.inputs[dependency.name]
            if isinstance(realized, ResolvedExternalInputRef):
                files = (
                    resolve_snapshot_file_ref(
                        current_stage.snapshot,
                        realized.file,
                    ),
                )
            elif isinstance(realized, ResolvedFutureInputRef):
                assert isinstance(declared, FutureInputRef)
                producer = completed_results[declared.producer_stage_id]
                files = tuple(
                    resolve_snapshot_file_ref(realized.producer.snapshot, file)
                    for file in _artifact_files(producer.artifacts[declared.name])
                )
            elif isinstance(realized, ResolvedStoredInputRef):
                files = stored_inputs[dependency.name]
            else:
                raise TypeError(
                    f"unsupported resolved input: {type(realized).__name__}"
                )
        resolved.append(
            ResolvedMetricDependency(
                dependency=dependency,
                files=files,
            )
        )
    return tuple(resolved)


def run_after_stage_metrics(
    root: Path,
    run: RunSpec,
    stage_id: StageId,
    stage: InternalSpec,
    resolved_stage: ResolvedInternalSpec,
    current_stage: ResolvedStageRef,
    completed_results: Mapping[StageId, ResolvedBaseSpec],
    stored_inputs: Mapping[InputName, tuple[ResolvedFileRef, ...]],
    experiment: ExperimentSpec,
    input_paths: Mapping[str, Path],
    measurement_paths: list[Path],
    metric_verification_paths: list[Path],
    timeout_seconds: float | None,
    attempt_id: int,
) -> None:
    """Invoke selected recomputed metrics with existing immutable references."""
    metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for metric_id in stage.metric_ids:
        metric = metrics[metric_id]
        if not is_recomputed_metric(metric):
            continue
        dependencies = _resolve_metric_dependencies(
            stage,
            resolved_stage,
            current_stage,
            completed_results,
            metric,
            stored_inputs,
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
            production = execute_metric_process(
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
        ).append(production.receipt.value)
        measurement_paths.append(path)
        try:
            recomputation = execute_metric_process(
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
            recomputation.receipt.value,
            comparator,
        )
        receipt = MetricVerificationReceipt(
            metric_id=metric_id,
            stage_id=stage_id,
            measurement=measurement,
            production=production.receipt,
            recomputation=recomputation.receipt,
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
        write_synchronized(receipt_path, serialize_document(receipt))
        metric_verification_paths.append(receipt_path)
        if not passed:
            raise RunError(f"metric {metric_id!r} failed independent recomputation")
