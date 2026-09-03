"""Construct one typed stage context and invoke its frozen callable once."""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from .._parameter.validation import instantiate_parameters
from ..execution._stage import StageWorkerContext, StageWorkerResult
from ..experiments import ExperimentSpec
from ..inputs import ExternalInputRef, FutureInputRef, StoredInputRef
from ..metrics import MeasurementSink, MetricHandle, bind_live_metric
from ..runs import RunSpec
from ..runtime import (
    apply_reproducibility,
    autocast_context,
    observe_execution,
    observe_python_environment,
)
from ..serialization import document_digest, load_stage_spec, parse_yaml_bytes
from ..stages import (
    BaseSpec,
    Context,
    InternalSpec,
    ParameterizedSpec,
    StageContextBinding,
    StageInvocationReceipt,
    load_stage_callable,
    stage_definition,
)


def _workspace_paths(
    root: Path,
    paths: dict[str, str],
) -> dict[str, Path]:
    """Resolve logical context paths beneath the selected repository root."""
    resolved: dict[str, Path] = {}
    for name, relative_path in paths.items():
        value = (root / relative_path).resolve()
        if not value.is_relative_to(root):
            raise ValueError("stage context path escapes the repository root")
        resolved[name] = value
    return resolved


def _write_result(path: Path, result: StageWorkerResult) -> None:
    """Write the complete child result as one UTF-8 JSON document."""
    path.write_text(result.model_dump_json(), encoding="utf-8")


def _planned_stage_context(
    root: Path,
    run: RunSpec,
    stage_id: str,
) -> tuple[ParameterizedSpec, dict[str, str]]:
    """Load the selected stage and derive its plan-owned logical input paths."""
    loaded: dict[str, BaseSpec] = {}
    selected: ParameterizedSpec | None = None
    expected_inputs: dict[str, str] = {}
    for reference in run.stages:
        path = root / reference.spec
        raw = path.read_bytes()
        if len(raw) != reference.bytes or hashlib.sha256(raw).hexdigest() != (
            reference.sha256
        ):
            raise ValueError("startup.plan: stage spec identity differs")
        candidate = load_stage_spec(path)
        if reference.stage_id == stage_id:
            if not isinstance(candidate, ParameterizedSpec):
                raise ValueError("startup.plan: selected stage is not parameterized")
            selected = candidate
            if isinstance(candidate, InternalSpec):
                for name, input_reference in candidate.inputs.items():
                    if isinstance(input_reference, StoredInputRef):
                        expected_inputs[name] = str(input_reference.path)
                    elif isinstance(input_reference, ExternalInputRef):
                        expected_inputs[name] = str(input_reference.path)
                    elif isinstance(input_reference, FutureInputRef):
                        producer = loaded[input_reference.producer_stage_id]
                        expected_inputs[name] = str(
                            producer.artifacts[input_reference.producer_artifact].path
                        )
            break
        loaded[reference.stage_id] = candidate
    if selected is None:
        raise ValueError("startup.plan: context stage ID is absent from RunSpec")
    return selected, expected_inputs


def _live_metric_handles(
    root: Path,
    run: RunSpec,
    stage: ParameterizedSpec,
    binding: StageContextBinding,
) -> dict[str, MetricHandle]:
    """Bind every selected live metric to the active attempt's measurement file."""
    if not stage.metric_ids:
        return {}

    experiment_path = root / f"experiments/{run.experiment_id}/spec.yaml"
    experiment = ExperimentSpec.model_validate(
        parse_yaml_bytes(experiment_path.read_bytes())
    )
    if experiment.experiment_id != run.experiment_id:
        raise ValueError("startup.plan: experiment ID differs from RunSpec")
    metrics = {metric.metric_id: metric for metric in experiment.metrics}
    handles: dict[str, MetricHandle] = {}
    for metric_id in stage.metric_ids:
        spec = metrics.get(metric_id)
        if spec is None:
            raise ValueError("startup.plan: stage selects an undeclared metric")
        if spec.mode != "live":
            continue
        path = (
            root
            / f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
            / f"attempts/{binding.attempt_id}/measurements"
            / f"{binding.stage_id}.{metric_id}.jsonl"
        )
        handles[metric_id] = bind_live_metric(
            root,
            spec,
            MeasurementSink(
                path,
                run_id=run.run_id,
                attempt_id=binding.attempt_id,
                stage_id=binding.stage_id,
                metric_id=metric_id,
            ),
        )
    return handles


def main(argv: list[str] | None = None) -> int:
    """Apply controls, construct the typed context, and invoke one callable."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        raise ValueError("stage worker accepts its context through VIPER_CONTEXT_PATH")
    context_path_value = os.environ.get("VIPER_CONTEXT_PATH")
    if context_path_value is None:
        raise ValueError("VIPER_CONTEXT_PATH is required")
    worker_context = StageWorkerContext.model_validate_json(
        Path(context_path_value).read_text(encoding="utf-8")
    )
    root = worker_context.repository_root.resolve()
    run = RunSpec.model_validate(
        parse_yaml_bytes(worker_context.run_spec_path.read_bytes())
    )
    stage = load_stage_spec(worker_context.stage_spec_path)
    binding = worker_context.binding
    started_at = datetime.now(UTC)
    initialization = None
    execution_context = None
    python_environment = None
    if not isinstance(stage, ParameterizedSpec):
        raise ValueError("stage worker requires a parameterized stage")
    try:
        planned_stage, expected_inputs = _planned_stage_context(
            root,
            run,
            binding.stage_id,
        )
        if stage != planned_stage:
            raise ValueError("startup.plan: selected stage differs from RunSpec")
        if (
            worker_context.stage_spec_path.resolve()
            != (
                root
                / next(
                    reference.spec
                    for reference in run.stages
                    if reference.stage_id == binding.stage_id
                )
            ).resolve()
        ):
            raise ValueError("startup.plan: selected stage path differs")
        if binding.run_id != run.run_id:
            raise ValueError("startup.plan: context run ID differs from RunSpec")
        if binding.parameter_model != stage.parameter_model:
            raise ValueError("startup.context: parameter model differs")
        if binding.parameter_digest != document_digest(stage.params):
            raise ValueError("startup.context: parameter digest differs")
        if binding.inputs != expected_inputs:
            raise ValueError("startup.context: input paths differ")
        expected_artifacts = {
            name: str(artifact.path) for name, artifact in stage.artifacts.items()
        }
        if binding.artifacts != expected_artifacts:
            raise ValueError("startup.context: artifact paths differ")
        if binding.metric_ids != stage.metric_ids:
            raise ValueError("startup.context: metric IDs differ")

        effective_environment = stage.environment or run.environment
        initialization = apply_reproducibility(run.seed, run.reproducibility)
        generator_names = tuple(sorted(initialization.numpy_generators))
        if generator_names != binding.numpy_generator_names:
            raise ValueError("startup.context: NumPy generator names differ")
        python_environment = observe_python_environment()
        if python_environment != effective_environment.python_environment:
            raise ValueError("startup.python: installed Python environment differs")
        execution_context = observe_execution(effective_environment)

        params = instantiate_parameters(
            root / stage.parameter_model.path,
            stage.parameter_model,
            stage.params,
            type(stage.params),
        )
        function = load_stage_callable(
            root / stage.implementation.path,
            stage.implementation,
            import_root=root,
        )
        definition = stage_definition(function)
        if definition.kind != stage.kind:
            raise ValueError("startup.callable: decorator kind differs")
        if definition.parameter_model.__name__ != stage.parameter_model.symbol:
            raise ValueError("startup.callable: decorator parameter class differs")
        parameter_source = getattr(function, "__viper_parameter_source__", None)
        if (
            parameter_source is None
            or Path(parameter_source).resolve()
            != (root / stage.parameter_model.path).resolve()
        ):
            raise ValueError("startup.callable: parameter model source differs")

        context = Context(
            run_id=binding.run_id,
            attempt_id=binding.attempt_id,
            stage_id=binding.stage_id,
            params=params,
            inputs=MappingProxyType(_workspace_paths(root, binding.inputs)),
            artifacts=MappingProxyType(_workspace_paths(root, binding.artifacts)),
            metrics=MappingProxyType(_live_metric_handles(root, run, stage, binding)),
            numpy_generators=MappingProxyType(initialization.numpy_generators),
        )
        with autocast_context(run.reproducibility):
            function(context)
    except Exception as exc:
        completed_at = datetime.now(UTC)
        invocation = StageInvocationReceipt(
            implementation=stage.implementation,
            context=binding,
            context_digest=document_digest(binding),
            started_at=started_at,
            completed_at=completed_at,
            outcome="failed",
        )
        _write_result(
            worker_context.result_path,
            StageWorkerResult(
                execution_context=execution_context,
                python_environment=python_environment,
                startup=None if initialization is None else initialization.receipt,
                invocation=invocation,
                error=f"{type(exc).__name__}: {exc}",
            ),
        )
        return 1

    completed_at = datetime.now(UTC)
    invocation = StageInvocationReceipt(
        implementation=stage.implementation,
        context=binding,
        context_digest=document_digest(binding),
        started_at=started_at,
        completed_at=completed_at,
        outcome="succeeded",
    )
    assert initialization is not None
    assert execution_context is not None
    assert python_environment is not None
    _write_result(
        worker_context.result_path,
        StageWorkerResult(
            execution_context=execution_context,
            python_environment=python_environment,
            startup=initialization.receipt,
            invocation=invocation,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
