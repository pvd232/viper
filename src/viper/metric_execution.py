"""Launch one recomputed metric in a controlled child process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ids import InputName, StageId
from .protocol import (
    ArtifactName,
    BaseSpec,
    MetricExecutionReceipt,
    MetricSpec,
    ResolvedMetricDependency,
    RunSpec,
)
from .runtime import process_environment, select_cuda_device


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
    package_root = str(Path(__file__).resolve().parents[1])
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
        (sys.executable, "-m", "viper.metric_worker"),
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
