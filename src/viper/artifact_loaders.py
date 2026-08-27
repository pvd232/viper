"""Validate verified artifact representations through project-owned loaders."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from .protocol import (
    RESUME_STATE,
    ArtifactLoaderRef,
    ArtifactName,
    ResumeState,
    RunSpec,
)
from .worker import ExecutionPolicy, WorkerRequest, execute_worker


class ArtifactLoaderError(RuntimeError):
    """Report failed loader identity, invocation, or semantic validation."""


class ArtifactLoaderWorkerContext(BaseModel):
    """Supply one verified artifact representation to its selected loader."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_root: Path
    loader: ArtifactLoaderRef
    loader_path: Path
    artifact_name: ArtifactName
    artifact_path: Path
    run: RunSpec
    result_path: Path

    @model_validator(mode="after")
    def validate_paths(self) -> ArtifactLoaderWorkerContext:
        """Keep every worker path beneath its disposable workspace."""
        root = self.workspace_root.resolve()
        for path in (self.loader_path, self.artifact_path, self.result_path):
            if not path.resolve().is_relative_to(root):
                raise ValueError("artifact loader path escapes its workspace")
        return self


class ArtifactValidationResult(BaseModel):
    """Name the strongest guarantee established for one loaded artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    guarantee: Literal["artifact.loadability", "artifact.semantic.resume_state"]


class ArtifactLoaderWorkerResult(BaseModel):
    """Return either one artifact guarantee or one worker failure message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation: ArtifactValidationResult | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ArtifactLoaderWorkerResult:
        """Require exactly one successful validation or failure message."""
        if (self.validation is None) == (self.error is None):
            raise ValueError("artifact loader result requires one outcome")
        return self


def verify_artifact_loader_bytes(reference: ArtifactLoaderRef, raw: bytes) -> None:
    """Compare loader bytes with their frozen byte count and SHA-256."""
    if len(raw) != reference.bytes:
        raise ArtifactLoaderError("artifact.loader: loader byte count differs")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ArtifactLoaderError("artifact.loader: loader SHA-256 differs")


def _load_artifact_value(context: ArtifactLoaderWorkerContext) -> object:
    """Load one exact top-level callable and invoke it on the artifact path."""
    raw = context.loader_path.read_bytes()
    verify_artifact_loader_bytes(context.loader, raw)
    module_name = f"_viper_artifact_loader_{context.loader.sha256}"
    module_spec = importlib.util.spec_from_file_location(
        module_name,
        context.loader_path,
    )
    if module_spec is None or module_spec.loader is None:
        raise ArtifactLoaderError("artifact.loader: loader module could not be loaded")
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except Exception as exc:
        raise ArtifactLoaderError("artifact.loader: loader import failed") from exc
    load = getattr(module, context.loader.symbol, None)
    if not callable(load):
        raise ArtifactLoaderError(
            f"artifact.loader: symbol {context.loader.symbol!r} is not callable"
        )
    try:
        return load(context.artifact_path)
    except Exception as exc:
        raise ArtifactLoaderError(
            "artifact.loadability: loader invocation failed"
        ) from exc


def _validate_resume_state(value: object, run: RunSpec) -> None:
    """Validate one loaded resume state against its run-wide controls."""
    try:
        resume_state = ResumeState.model_validate(value)
    except ValueError as exc:
        raise ArtifactLoaderError(
            "artifact.semantic.resume_state: loaded value is invalid"
        ) from exc

    expected_configuration = run.reproducibility.parallelism.dataloader
    if resume_state.dataloader.configuration != expected_configuration:
        raise ArtifactLoaderError(
            "artifact.semantic.resume_state: DataLoader configuration differs"
        )

    expected_numpy = run.reproducibility.numpy_randomness
    saved_numpy = resume_state.main_process_rng.numpy
    if set(saved_numpy.generators) != set(expected_numpy.generators):
        raise ArtifactLoaderError(
            "artifact.semantic.resume_state: NumPy generator names differ"
        )
    if (saved_numpy.legacy_global is not None) != expected_numpy.capture_legacy_global:
        raise ArtifactLoaderError(
            "artifact.semantic.resume_state: legacy NumPy state differs"
        )


def validate_artifact_context(
    context: ArtifactLoaderWorkerContext,
) -> ArtifactValidationResult:
    """Invoke one loader and apply the reserved validator when applicable."""
    value = _load_artifact_value(context)
    if context.artifact_name == RESUME_STATE:
        _validate_resume_state(value, context.run)
        return ArtifactValidationResult(guarantee="artifact.semantic.resume_state")
    return ArtifactValidationResult(guarantee="artifact.loadability")


def execute_artifact_loader(
    workspace_root: Path,
    context: ArtifactLoaderWorkerContext,
    *,
    timeout_seconds: float | None = None,
) -> ArtifactValidationResult:
    """Invoke one artifact loader in a dedicated trusted-local worker."""
    root = workspace_root.resolve()
    package_root = str(Path(__file__).resolve().parents[1])
    existing_python_path = os.environ.get("PYTHONPATH")
    python_path = (
        package_root
        if existing_python_path is None
        else f"{package_root}{os.pathsep}{existing_python_path}"
    )
    context.result_path.unlink(missing_ok=True)
    context.result_path.parent.mkdir(parents=True, exist_ok=True)
    context_path = context.result_path.with_name("context.json")
    context_path.write_text(context.model_dump_json(), encoding="utf-8")
    try:
        execute_worker(
            WorkerRequest(
                workspace_root=root,
                working_directory=root,
                context_path=context_path,
                command=(sys.executable, "-m", "viper.artifact_worker"),
                environment={"PYTHONPATH": python_path},
                policy=ExecutionPolicy(timeout_seconds=timeout_seconds),
            )
        )
    except Exception as exc:
        raise ArtifactLoaderError("artifact loader worker failed") from exc
    if not context.result_path.is_file():
        raise ArtifactLoaderError("artifact loader worker wrote no result")
    try:
        result = ArtifactLoaderWorkerResult.model_validate_json(
            context.result_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactLoaderError(
            "artifact loader worker wrote an invalid result"
        ) from exc
    if result.error is not None:
        raise ArtifactLoaderError(result.error)
    return cast(ArtifactValidationResult, result.validation)


def materialized_loader_context(
    root: Path,
    loader: ArtifactLoaderRef,
    artifact_name: ArtifactName,
    artifact_path: Path,
    run: RunSpec,
) -> ArtifactLoaderWorkerContext:
    """Construct the bounded worker context used by verifier materialization."""
    return ArtifactLoaderWorkerContext(
        workspace_root=root,
        loader=loader,
        loader_path=root / loader.path,
        artifact_name=artifact_name,
        artifact_path=artifact_path,
        run=run,
        result_path=root / ".viper" / "artifact-loader-result.json",
    )
