"""Invoke one frozen stage command and identify every produced artifact file."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ._parameter_validation import (
    ParameterValidationError,
    validate_stage_parameters,
)
from .protocol import (
    ArtifactName,
    BaseSpec,
    BundleArtifactSpec,
    ExecutionContext,
    HttpRetrievalContextBinding,
    ParameterizedSpec,
    ParameterizedStageSpec,
    ProcessStartupReceipt,
    PythonEnvironmentSpec,
    ResolvedArtifact,
    ResolvedBundleArtifact,
    ResolvedBundleMember,
    ResolvedHttpRetrieval,
    ResolvedSingleFileArtifact,
    RunSpec,
    RunStageRef,
    SingleFileArtifactSpec,
    SnapshotFileRef,
    StageContextBinding,
    StageInvocationReceipt,
)
from .runtime import process_environment, select_cuda_device
from .serialization import document_digest


class StageExecutionError(RuntimeError):
    """A frozen stage command failed or did not produce its declared files."""

    def __init__(
        self,
        message: str,
        *,
        invocation: StageInvocationReceipt | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        """Preserve failed-invocation evidence when the child produced it."""
        super().__init__(message)
        self.invocation = invocation
        self.stdout = stdout
        self.stderr = stderr


class StageProcessInterrupted(RuntimeError):
    """Carry one coordinator interruption and the stopped child's evidence."""

    def __init__(self, outcome: Literal["cancelled", "preempted"]) -> None:
        """Identify the requested terminal outcome before child cleanup."""
        super().__init__(f"stage process was {outcome}")
        self.outcome: Literal["cancelled", "preempted"] = outcome
        self.invocation: StageInvocationReceipt | None = None
        self.stdout = b""
        self.stderr = b""


class StageWorkerContext(BaseModel):
    """Supply one versioned logical invocation to the controlled child."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_root: Path
    run_spec_path: Path
    stage_spec_path: Path
    binding: StageContextBinding
    result_path: Path


class StageWorkerResult(BaseModel):
    """Return the evidence produced by one controlled stage child."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_context: ExecutionContext | None
    python_environment: PythonEnvironmentSpec | None
    startup: ProcessStartupReceipt | None
    invocation: StageInvocationReceipt
    error: str | None = None


@dataclass(frozen=True)
class StageProcessResult:
    """Record one local stage invocation and its exact output file identities."""

    command: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    artifacts: dict[ArtifactName, ResolvedArtifact]
    execution_context: ExecutionContext
    python_environment: PythonEnvironmentSpec
    startup: ProcessStartupReceipt
    invocation: StageInvocationReceipt
    stdout: bytes
    stderr: bytes


def _stop_process_group(
    process: subprocess.Popen[bytes],
) -> tuple[bytes, bytes]:
    """Terminate one stage process group and collect its remaining output."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


def _workspace_path(repository_root: Path, relative_path: str) -> Path:
    """Resolve a protocol path without permitting workspace escape."""
    root = repository_root.resolve()
    path = root / relative_path
    if not path.resolve().is_relative_to(root):
        raise StageExecutionError("stage path escapes the repository root")
    return path


def _snapshot_file(repository_root: Path, relative_path: str) -> SnapshotFileRef:
    """Hash one regular output file at its repository-relative path."""
    path = _workspace_path(repository_root, relative_path)
    if path.is_symlink() or not path.is_file():
        raise StageExecutionError(f"declared artifact file is missing: {relative_path}")
    raw = path.read_bytes()
    return SnapshotFileRef(
        path=relative_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def _resolve_artifact(
    repository_root: Path,
    declaration: SingleFileArtifactSpec | BundleArtifactSpec,
) -> ResolvedArtifact:
    """Convert one materialized artifact into exact file records."""
    if isinstance(declaration, SingleFileArtifactSpec):
        return ResolvedSingleFileArtifact(
            file=_snapshot_file(repository_root, declaration.path)
        )

    root = _workspace_path(repository_root, declaration.path)
    if root.is_symlink() or not root.is_dir():
        raise StageExecutionError(
            f"declared artifact bundle is missing: {declaration.path}"
        )

    members: list[ResolvedBundleMember] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise StageExecutionError("artifact bundles must not contain symlinks")
        if not path.is_file():
            continue
        relative_member = path.relative_to(root).as_posix()
        members.append(
            ResolvedBundleMember(
                relative_path=relative_member,
                file=_snapshot_file(
                    repository_root,
                    f"{declaration.path}/{relative_member}",
                ),
            )
        )

    try:
        return ResolvedBundleArtifact(members=tuple(members))
    except ValueError as exc:
        raise StageExecutionError(
            "artifact bundle does not satisfy its declared file contract"
        ) from exc


def execute_stage_process(
    repository_root: Path,
    run: RunSpec,
    stage_reference: RunStageRef,
    stage_spec: BaseSpec,
    *,
    attempt_id: int = 1,
    input_paths: dict[str, Path] | None = None,
    retrievals: dict[str, ResolvedHttpRetrieval] | None = None,
    timeout_seconds: float | None = None,
) -> StageProcessResult:
    """Invoke one frozen callable and hash every declared output file."""
    root = repository_root.resolve()
    spec_path = _workspace_path(root, stage_reference.spec)
    spec_raw = spec_path.read_bytes()
    if hashlib.sha256(spec_raw).hexdigest() != stage_reference.sha256:
        raise StageExecutionError("stage spec SHA-256 does not match RunStageRef")
    if len(spec_raw) != stage_reference.bytes:
        raise StageExecutionError("stage spec byte count does not match RunStageRef")

    implementation_path = _workspace_path(root, stage_spec.implementation.path)
    if not implementation_path.is_file():
        raise StageExecutionError(
            f"stage implementation is missing: {stage_spec.implementation.path}"
        )
    implementation_raw = implementation_path.read_bytes()
    if len(implementation_raw) != stage_spec.implementation.bytes:
        raise StageExecutionError("stage implementation byte count differs")
    if hashlib.sha256(implementation_raw).hexdigest() != (
        stage_spec.implementation.sha256
    ):
        raise StageExecutionError("stage implementation SHA-256 differs")

    if not isinstance(stage_spec, ParameterizedSpec):
        raise StageExecutionError("stage invocation requires a parameterized spec")
    parameterized_stage = cast(ParameterizedStageSpec, stage_spec)
    try:
        validate_stage_parameters(
            root,
            spec_path,
            parameterized_stage,
            timeout_seconds=timeout_seconds,
        )
    except ParameterValidationError as exc:
        raise StageExecutionError("stage parameter validation failed") from exc

    run_spec_path = (
        f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}/spec.yaml"
    )
    supplied_inputs = {} if input_paths is None else input_paths
    logical_inputs: dict[str, str] = {}
    for name, path in supplied_inputs.items():
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(root):
            raise StageExecutionError("stage input path escapes the repository root")
        logical_inputs[name] = resolved_path.relative_to(root).as_posix()
    binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt_id,
        stage_id=stage_reference.stage_id,
        parameter_model=parameterized_stage.parameter_model,
        parameter_digest=document_digest(parameterized_stage.params),
        inputs=logical_inputs,
        retrievals={
            name: HttpRetrievalContextBinding(
                response=retrieval.response,
                body=SnapshotFileRef(
                    path=logical_inputs[name],
                    sha256=retrieval.body.sha256,
                    bytes=retrieval.body.bytes,
                ),
            )
            for name, retrieval in ({} if retrievals is None else retrievals).items()
        },
        artifacts={
            name: artifact.path for name, artifact in stage_spec.artifacts.items()
        },
        metric_ids=stage_spec.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    command = ("python", "-m", "viper.stage_worker")
    environment = os.environ.copy()
    effective_environment = stage_spec.environment or run.environment
    compute = effective_environment.compute
    cuda_ordinal = select_cuda_device(compute.model) if compute.kind == "cuda" else None
    startup_environment = process_environment(
        run.seed,
        run.reproducibility,
        compute,
        cuda_ordinal=cuda_ordinal,
    )
    environment.update({str(key): value for key, value in startup_environment.items()})
    package_root = str(Path(__file__).resolve().parents[1])
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        package_root
        if existing_python_path is None
        else f"{package_root}{os.pathsep}{existing_python_path}"
    )
    runtime_root = root / ".viper" / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    context_path = runtime_root / (
        f"{run.run_id}.{attempt_id}.{stage_reference.stage_id}.context.json"
    )
    result_path = runtime_root / (
        f"{run.run_id}.{attempt_id}.{stage_reference.stage_id}.result.json"
    )
    result_path.unlink(missing_ok=True)
    context_path.write_text(
        StageWorkerContext(
            repository_root=root,
            run_spec_path=root / run_spec_path,
            stage_spec_path=spec_path,
            binding=binding,
            result_path=result_path,
        ).model_dump_json(),
        encoding="utf-8",
    )
    environment["VIPER_CONTEXT_PATH"] = str(context_path)
    started_at = datetime.now(UTC)
    process = subprocess.Popen(
        (sys.executable, *command[1:]),
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except StageProcessInterrupted as exc:
        stdout, stderr = _stop_process_group(process)
        completed_at = datetime.now(UTC)
        exc.invocation = StageInvocationReceipt(
            implementation=stage_spec.implementation,
            context=binding,
            context_digest=document_digest(binding),
            started_at=started_at,
            completed_at=completed_at,
            outcome=exc.outcome,
        )
        exc.stdout = stdout
        exc.stderr = stderr
        raise
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _stop_process_group(process)
        completed_at = datetime.now(UTC)
        raise StageExecutionError(
            "stage command exceeded its timeout",
            invocation=StageInvocationReceipt(
                implementation=stage_spec.implementation,
                context=binding,
                context_digest=document_digest(binding),
                started_at=started_at,
                completed_at=completed_at,
                outcome="failed",
            ),
            stdout=stdout,
            stderr=stderr,
        ) from exc
    completed_at = datetime.now(UTC)
    if not result_path.is_file():
        raise StageExecutionError(
            f"stage command exited with status {process.returncode} without "
            "writing invocation evidence",
            invocation=StageInvocationReceipt(
                implementation=stage_spec.implementation,
                context=binding,
                context_digest=document_digest(binding),
                started_at=started_at,
                completed_at=completed_at,
                outcome="failed",
            ),
            stdout=stdout,
            stderr=stderr,
        )
    try:
        worker_result = StageWorkerResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise StageExecutionError("stage worker wrote an invalid result") from exc
    if process.returncode != 0 or worker_result.error is not None:
        message = worker_result.error or stderr.decode(errors="replace").strip()
        raise StageExecutionError(
            f"stage command exited with status {process.returncode}: {message}",
            invocation=worker_result.invocation,
            stdout=stdout,
            stderr=stderr,
        )
    if (
        worker_result.execution_context is None
        or worker_result.python_environment is None
        or worker_result.startup is None
    ):
        raise StageExecutionError("successful stage omitted runtime evidence")

    artifacts = {
        name: _resolve_artifact(root, declaration)
        for name, declaration in stage_spec.artifacts.items()
    }
    return StageProcessResult(
        command=command,
        started_at=started_at,
        completed_at=completed_at,
        artifacts=artifacts,
        execution_context=worker_result.execution_context,
        python_environment=worker_result.python_environment,
        startup=worker_result.startup,
        invocation=worker_result.invocation,
        stdout=stdout,
        stderr=stderr,
    )
