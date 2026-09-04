"""Verify metric recomputation evidence for completed stages."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import cast

import yaml

from ..ids import InputName, MetricId, StageId
from ..metrics import (
    FloatComparator,
    Measurement,
    MetricExecutionReceipt,
    MetricVerificationReceipt,
    ResolvedMetricDependency,
    compare_metric_values,
)
from ..references import HuggingFaceFileRef, LocalFileRef
from ..runs import RunAttempt, RunSpec
from ..runtime import (
    CUDABackendContext,
    GCEEnvironmentSpec,
    GCEHostContext,
    process_environment,
)
from ..serialization import parse_yaml_bytes
from ..stages import BaseSpec, ResolvedBaseSpec
from ..verification.models import (
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedInput,
    VerifiedRunPlan,
)
from .paths import run_root
from .storage import StorageFetcher, read_resolved_file, verify_snapshot_artifact


def _verify_metric_worker_runtime(
    run: RunSpec,
    stage: BaseSpec,
    receipt: MetricExecutionReceipt,
) -> None:
    """Match one metric worker's startup and runtime facts to the run plan."""
    startup = receipt.startup
    if startup.reproducibility != run.reproducibility:
        raise VerificationError("metric worker reproducibility controls differ")
    compute = (stage.environment or run.environment).compute
    recorded_cuda = startup.environment.get("CUDA_VISIBLE_DEVICES")
    if compute.kind == "cuda":
        if recorded_cuda is None or not recorded_cuda.isdigit():
            raise VerificationError("metric worker omitted its selected CUDA device")
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
            cuda_ordinal=int(recorded_cuda),
        )
    else:
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
        )
    if startup.environment != expected_environment:
        raise VerificationError("metric worker startup environment differs")
    if any(generator.seed != run.seed for generator in startup.generators):
        raise VerificationError("metric worker generator seed differs")
    family_counts = Counter(generator.family for generator in startup.generators)
    if family_counts["python"] != 1 or family_counts["torch_cpu"] != 1:
        raise VerificationError("metric worker generator receipts are incomplete")
    expected_numpy_names = set(run.reproducibility.numpy_randomness.generators)
    received_numpy_names = {
        generator.name
        for generator in startup.generators
        if generator.family == "numpy_generator"
    }
    if received_numpy_names != expected_numpy_names:
        raise VerificationError("metric worker NumPy generators differ")
    context = receipt.execution_context
    effective_environment = stage.environment or run.environment
    if receipt.python_environment != effective_environment.python_environment:
        raise VerificationError("metric worker Python environment differs")
    if context.host.provider != effective_environment.kind:
        raise VerificationError("metric worker host provider differs")
    if isinstance(effective_environment, GCEEnvironmentSpec):
        if not isinstance(context.host, GCEHostContext):
            raise VerificationError("metric worker omitted its GCE host context")
        if context.host.machine_type != effective_environment.machine_type:
            raise VerificationError("metric worker machine type differs")
    if context.backend.kind != compute.kind:
        raise VerificationError("metric worker compute backend differs")
    if compute.kind == "cuda":
        if not isinstance(context.backend, CUDABackendContext):
            raise VerificationError("metric worker omitted its CUDA context")
        if len(context.backend.gpu_devices) != compute.count:
            raise VerificationError("metric worker CUDA device count differs")
        if any(device.model != compute.model for device in context.backend.gpu_devices):
            raise VerificationError("metric worker CUDA model differs")


def verify_metric_dependency_references(
    received: ResolvedMetricDependency,
    expected: ResolvedMetricDependency,
    metric_id: MetricId,
) -> None:
    """Require one metric dependency to retain its exact storage references."""
    if received.files != expected.files:
        raise VerificationError(f"metric {metric_id!r} dependency references differ")


def verify_recomputed_metrics(
    attempt: RunAttempt,
    plan: VerifiedRunPlan,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    measurements: tuple[Measurement, ...],
    stored_inputs: Mapping[StageId, Mapping[InputName, VerifiedInput]],
    future_inputs: Mapping[StageId, Mapping[InputName, VerifiedInput]],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify persisted production and recomputation evidence for each metric."""
    del policy
    metric_specs = {metric.metric_id: metric for metric in plan.experiment.metrics}
    stage_refs = {stage.stage_id: stage for stage in attempt.resolved_stages}
    expected_keys = {
        (stage_id, metric_id)
        for stage_id, stage in plan.stages.items()
        if stage_id in stage_refs
        for metric_id in stage.metric_ids
        if metric_specs[metric_id].mode == "recompute"
    }
    if len(attempt.metric_verification_files) != len(expected_keys):
        raise VerificationError(
            "recomputed metrics require one immutable verification receipt each"
        )
    receipts: dict[tuple[StageId, str], MetricVerificationReceipt] = {}
    root_path = run_root(plan.run)
    for reference in attempt.metric_verification_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError(
                "metric verification files must use immutable artifact storage"
            )
        raw = read_resolved_file(reference, fetcher=fetcher)
        try:
            receipt = MetricVerificationReceipt.model_validate(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError("metric verification receipt is invalid") from exc
        expected_path = (
            f"{root_path}/attempts/{attempt.attempt_id}/metric_verification/"
            f"{receipt.stage_id}.{receipt.metric_id}.yaml"
        )
        if reference.stored_at.path != expected_path:
            raise VerificationError(
                "metric verification receipt is outside its canonical path"
            )
        key = (receipt.stage_id, receipt.metric_id)
        if key in receipts:
            raise VerificationError(
                "metric verification receipt identity is duplicated"
            )
        receipts[key] = receipt
    if set(receipts) != expected_keys:
        raise VerificationError("metric verification receipts select different metrics")

    for stage_id, stage in plan.stages.items():
        if stage_id not in stage_refs:
            continue
        for metric_id in stage.metric_ids:
            metric = metric_specs[metric_id]
            if metric.mode != "recompute":
                continue
            recorded = tuple(
                measurement
                for measurement in measurements
                if measurement.stage_id == stage_id
                and measurement.metric_id == metric_id
            )
            if len(recorded) != 1:
                raise VerificationError(
                    f"recomputed metric {metric_id!r} of stage {stage_id!r} "
                    "requires exactly one measurement"
                )
            receipt = receipts[(stage_id, metric_id)]
            if receipt.measurement != recorded[0]:
                raise VerificationError(
                    f"metric {metric_id!r} receipt embeds a different measurement"
                )
            if receipt.production.implementation != metric.implementation:
                raise VerificationError(
                    f"metric {metric_id!r} production implementation differs"
                )
            if receipt.production.params != metric.params:
                raise VerificationError(
                    f"metric {metric_id!r} production parameters differ"
                )
            if receipt.comparator != metric.comparator:
                raise VerificationError(
                    f"metric {metric_id!r} comparator differs from MetricSpec"
                )
            resolved_stage = resolved_stages[stage_id]
            stage_ref = stage_refs[stage_id]
            verified_artifacts = {
                name: verify_snapshot_artifact(
                    stage_ref,
                    resolved_artifact,
                    data_role=stage.artifacts[name].data_role,
                    fetcher=fetcher,
                )
                for name, resolved_artifact in resolved_stage.artifacts.items()
            }
            inputs = {
                **stored_inputs.get(stage_id, {}),
                **future_inputs.get(stage_id, {}),
            }
            metric_inputs: dict[str, VerifiedInput] = {}
            metric_artifacts: dict[str, VerifiedArtifact] = {}
            for dependency in metric.dependencies:
                if dependency.source == "input":
                    selected_input = inputs.get(dependency.name)
                    if selected_input is None:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} is absent"
                        )
                    if selected_input.data_role != dependency.required_data_role:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} data role differs"
                        )
                    metric_inputs[dependency.name] = selected_input
                else:
                    selected_artifact = verified_artifacts.get(dependency.name)
                    if selected_artifact is None:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} is absent"
                        )
                    if selected_artifact.data_role != dependency.required_data_role:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} data role differs"
                        )
                    metric_artifacts[dependency.name] = selected_artifact
            expected_dependencies = tuple(
                ResolvedMetricDependency(
                    dependency=dependency,
                    files=(
                        metric_inputs[dependency.name].references
                        if dependency.source == "input"
                        else metric_artifacts[dependency.name].references
                    ),
                )
                for dependency in metric.dependencies
            )
            if tuple(
                value.dependency for value in receipt.production.dependencies
            ) != tuple(value.dependency for value in expected_dependencies):
                raise VerificationError(
                    f"metric {metric_id!r} dependency declarations differ"
                )
            for received, expected in zip(
                receipt.production.dependencies,
                expected_dependencies,
                strict=True,
            ):
                verify_metric_dependency_references(received, expected, metric_id)
                for reference in received.files:
                    read_resolved_file(reference, fetcher=fetcher)
            for worker in (receipt.production, receipt.recomputation):
                _verify_metric_worker_runtime(plan.run, stage, worker)
            if not (
                resolved_stage.completed_at
                <= receipt.production.started_at
                < receipt.production.completed_at
                <= recorded[0].measured_at
                <= receipt.recomputation.started_at
                < receipt.recomputation.completed_at
                <= receipt.completed_at
                <= attempt.completed_at
            ):
                raise VerificationError(
                    f"metric {metric_id!r} execution timing is inconsistent"
                )
            if not compare_metric_values(
                recorded[0].value,
                receipt.recomputation.value,
                cast(FloatComparator, metric.comparator),
            ):
                raise VerificationError(
                    f"recomputed metric {metric_id!r} does not match its measurement"
                )
            if not receipt.passed:
                raise VerificationError(
                    f"metric {metric_id!r} verification receipt records failure"
                )
