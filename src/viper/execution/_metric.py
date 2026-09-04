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
from ..experiments import ExperimentSpec
from ..ids import InputName, StageId
from ..metrics import (
    FloatComparator,
    MeasurementSink,
    MetricExecutionReceipt,
    MetricSpec,
    MetricVerificationReceipt,
    ResolvedMetricDependency,
    compare_metric_values,
)
from ..references import ResolvedFileRef
from ..runs import RunSpec
from ..runtime import process_environment, select_cuda_device
from ..serialization import serialize_document
from ..stages import BaseSpec
from ..storage import LocalArtifactStore
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
    if metric.mode != "recompute":
        raise MetricExecutionError("metric worker requires recompute mode")
    if metric.metric_id not in stage.metric_ids:
        raise MetricExecutionError("stage does not select the metric")
    expected_dependencies = tuple(metric.dependencies)
    if tuple(value.dependency for value in dependencies) != expected_dependencies:
        raise MetricExecutionError(
            "resolved metric dependencies differ from MetricSpec"
        )

    effective_environment = stage.environment or run.environment
    compute = effective_environment.compute
    cuda_ordinal = select_cuda_device(compute.model) if compute.kind == "cuda" else None
    environment = os.environ.copy()
    environment.update(
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
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
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
    environment["VIPER_METRIC_CONTEXT_PATH"] = str(context_path)

    completed = subprocess.run(
        (sys.executable, "-m", "viper._workers.metrics"),
        cwd=root,
        env=environment,
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


def run_after_stage_metrics(
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
        write_synchronized(receipt_path, serialize_document(receipt))
        metric_verification_paths.append(receipt_path)
        if not passed:
            raise RunError(f"metric {metric_id!r} failed independent recomputation")
