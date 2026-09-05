"""Construct one restricted metric context and invoke its frozen callable."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ..execution._metric import MetricWorkerContext, MetricWorkerResult
from ..metrics import (
    MetricContext,
    MetricExecutionReceipt,
    load_metric,
    metric_definition,
    validate_metric_definition,
)
from ..runtime import (
    apply_reproducibility,
    autocast_context,
    observe_execution,
    observe_python_env,
)


def _write_result(path: Path, result: MetricWorkerResult) -> None:
    """Write the complete metric-worker result as one JSON document."""
    path.write_text(result.model_dump_json(), encoding="utf-8")


def _validated_paths(root: Path, paths: Mapping[str, Path]) -> dict[str, Path]:
    """Resolve metric dependency paths and reject workspace escape."""
    resolved: dict[str, Path] = {}
    for name, path in paths.items():
        value = path.resolve()
        if not value.is_relative_to(root):
            raise ValueError("metric dependency path escapes the repository root")
        if not value.exists():
            raise ValueError(f"metric dependency {name!r} is absent")
        resolved[name] = value
    return resolved


def _path_identities(path: Path) -> tuple[tuple[str, int], ...]:
    """Return ordered SHA-256 and byte-count pairs for one file or bundle."""
    if path.is_file():
        members = (path,)
    elif path.is_dir():
        members = tuple(
            member for member in sorted(path.rglob("*")) if member.is_file()
        )
    else:
        raise ValueError("metric dependency path is absent")
    if not members:
        raise ValueError("metric dependency contains no regular files")
    identities: list[tuple[str, int]] = []
    for member in members:
        if member.is_symlink():
            raise ValueError("metric dependency contains a symbolic link")
        raw = member.read_bytes()
        identities.append((hashlib.sha256(raw).hexdigest(), len(raw)))
    return tuple(identities)


def main(argv: list[str] | None = None) -> int:
    """Apply controls, invoke one metric, and emit its execution receipt."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        raise ValueError(
            "metric worker accepts context through VIPER_METRIC_CONTEXT_PATH"
        )
    context_value = os.environ.get("VIPER_METRIC_CONTEXT_PATH")
    if context_value is None:
        raise ValueError("VIPER_METRIC_CONTEXT_PATH is required")
    context = MetricWorkerContext.model_validate_json(
        Path(context_value).read_text(encoding="utf-8")
    )
    root = context.repository_root.resolve()
    started_at = datetime.now(UTC)
    try:
        if context.metric.metric_id not in context.stage.metric_ids:
            raise ValueError("metric is absent from the selected stage")
        if tuple(value.dependency for value in context.dependencies) != tuple(
            context.metric.dependencies
        ):
            raise ValueError("metric dependency bindings differ from MetricSpec")
        validate_metric_definition(root, context.metric)
        definition = metric_definition(
            load_metric(
                root / context.metric.implementation.path,
                context.metric.implementation.symbol,
            )
        )
        if definition.mode != "post_stage":
            raise ValueError("dedicated metric worker requires recompute mode")

        initialization = apply_reproducibility(
            context.run.seed,
            context.run.reproducibility,
        )
        effective_environment = context.stage.env or context.run.env
        python_env = observe_python_env()
        if python_env != effective_environment.python_env:
            raise ValueError("startup.python: installed Python env differs")
        execution_context = observe_execution(effective_environment)
        callable_metric = load_metric(
            root / context.metric.implementation.path,
            context.metric.implementation.symbol,
        )
        input_paths = _validated_paths(root, context.input_paths)
        artifact_paths = _validated_paths(root, context.artifact_paths)
        for binding in context.dependencies:
            path = (
                input_paths[binding.dependency.name]
                if binding.dependency.source == "input"
                else artifact_paths[binding.dependency.name]
            )
            recorded_identities = tuple(
                (file.sha256, file.bytes) for file in binding.files
            )
            if _path_identities(path) != recorded_identities:
                raise ValueError("metric dependency bytes differ from their receipt")
        with autocast_context(context.run.reproducibility):
            value = float(
                callable_metric(
                    MetricContext(
                        inputs=input_paths,
                        artifacts=artifact_paths,
                        params=context.metric.params,
                    )
                )
            )
        completed_at = datetime.now(UTC)
        receipt = MetricExecutionReceipt(
            run_id=context.run.run_id,
            attempt_id=context.attempt_id,
            metric_id=context.metric.metric_id,
            stage_id=context.stage_id,
            purpose=context.purpose,
            implementation=context.metric.implementation,
            parameter_model=context.metric.parameter_model,
            params=context.metric.params,
            dependencies=context.dependencies,
            startup=initialization.receipt,
            execution_context=execution_context,
            python_env=python_env,
            value=value,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:
        _write_result(
            context.result_path,
            MetricWorkerResult(error=f"{type(exc).__name__}: {exc}"),
        )
        return 1
    _write_result(context.result_path, MetricWorkerResult(receipt=receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
