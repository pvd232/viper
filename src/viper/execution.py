"""Execute, publish, and verify one frozen run plan on a trusted local host."""

from __future__ import annotations

import hashlib
import os
import signal
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ._execution.errors import RunError
from ._execution.source import RunFetcher, _git, _resolved_git_file
from .artifacts import ArtifactPointer
from .experiments import ExperimentSpec
from .http import (
    HttpRetrievalError,
    ResolvedHttpRetrieval,
    invoke_transport,
    resolve_transport,
)
from .ids import InputName, StageId
from .journal import DurableJournal
from .local_store import LocalArtifactStore, snapshot_file
from .metric_execution import MetricExecutionError, execute_metric_process
from .metrics import (
    FloatComparator,
    MeasurementSink,
    MetricSpec,
    MetricVerificationReceipt,
    ResolvedMetricDependency,
    compare_metric_values,
)
from .paths import retrieval_body_path
from .preflight import preflight_plan
from .references import (
    GitFileRef,
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunSpecRef,
    SnapshotFileRef,
)
from .runs import (
    AttemptFailure,
    AttemptJournalRef,
    AttemptPurpose,
    ResolvedAttemptRef,
    ResolvedRun,
    RunAttempt,
    RunSpec,
)
from .runtime import (
    EnvironmentSpec,
    GCEEnvironmentSpec,
    GCEHostContext,
    ResolvedGCEEnvironment,
    ResolvedLocalEnvironment,
)
from .serialization import load_stage_spec, parse_yaml_bytes, serialize_document
from .stage_execution import (
    StageExecutionError,
    StageProcessInterrupted,
    StageProcessResult,
    execute_stage_process,
)
from .stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
    ResolvedBuildSpec,
    ResolvedDownloadSpec,
    ResolvedEmbedSpec,
    ResolvedEvaluateSpec,
    ResolvedFutureInputRef,
    ResolvedInternalInputRef,
    ResolvedSpec,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    ResolvedStoredInputRef,
    ResolvedTrainSpec,
    StageInvocationReceipt,
    StoredInputRef,
)
from .verification import (
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    read_attempt_reference,
    verify_promoted_artifact,
    verify_run_result,
)
from .workspace import AttemptWorkspace, RunWorkspaceLock, next_attempt_id


class RunResult(BaseModel):
    """Return one verified terminal run and its local output path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_run: ResolvedRun
    resolved_run_path: Path
    journal_path: Path


class ConfirmationRunResult(BaseModel):
    """Return one independently executed benchmark-confirmation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: RunAttempt
    attempt_reference: ResolvedAttemptRef
    attempt_path: Path
    journal_path: Path


def _write_synchronized(path: Path, raw: bytes) -> None:
    """Atomically write and synchronize one local control or terminal file."""
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise RunError(f"refusing to replace different bytes at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(raw)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()


def _replace_synchronized(path: Path, raw: bytes) -> None:
    """Atomically replace one mutable local head document and synchronize it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(raw)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _publish_attempt_files(
    store: LocalArtifactStore,
    root: Path,
    run_root: str,
    attempt_id: int,
    journal: DurableJournal,
    log_files: Mapping[str, bytes],
    measurement_paths: list[Path],
    metric_verification_paths: list[Path],
) -> tuple[
    AttemptJournalRef,
    tuple[ResolvedFileRef, ...],
    tuple[ResolvedFileRef, ...],
    tuple[ResolvedFileRef, ...],
]:
    """Publish one terminal journal and every available attempt-owned file."""
    files = dict(log_files)
    for path in (*measurement_paths, *metric_verification_paths):
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    journal_path = f"{run_root}/attempts/{attempt_id}/journal.jsonl"
    files[journal_path] = journal.path.read_bytes()
    references = store.resolved_files(files)
    journal_file = next(
        reference
        for reference in references
        if reference.stored_at.path == journal_path
    )
    return (
        AttemptJournalRef(
            sha256=journal_file.sha256,
            bytes=journal_file.bytes,
            stored_at=journal_file.stored_at,
        ),
        tuple(
            reference
            for reference in references
            if "/measurements/" in str(reference.stored_at.path)
        ),
        tuple(
            reference
            for reference in references
            if "/metric_verification/" in str(reference.stored_at.path)
        ),
        tuple(
            reference
            for reference in references
            if "/logs/" in str(reference.stored_at.path)
        ),
    )


def _write_attempt_document(
    root: Path,
    run_root: str,
    attempt: RunAttempt,
    store: LocalArtifactStore,
) -> ResolvedAttemptRef:
    """Publish one canonical attempt document and return its immutable reference."""
    path = root / run_root / "attempts" / str(attempt.attempt_id) / "resolved.yaml"
    raw = serialize_document(attempt)
    _write_synchronized(path, raw)
    reference = store.resolved_files({path.relative_to(root).as_posix(): raw})[0]
    return ResolvedAttemptRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )


def _publish_invocation_receipt(
    store: LocalArtifactStore,
    path: str,
    receipt: StageInvocationReceipt,
) -> ResolvedStageInvocationRef:
    """Publish one stage invocation receipt at its canonical attempt path."""
    raw = serialize_document(receipt)
    reference = store.resolved_files({path: raw})[0]
    return ResolvedStageInvocationRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )


def _reconcile_abandoned_attempts(
    root: Path,
    workspace_root: Path,
    run: RunSpec,
    run_root: str,
    store: LocalArtifactStore,
    known_attempts: tuple[RunAttempt, ...],
) -> tuple[RunAttempt, ...]:
    """Close every durable workspace omitted from the current run head."""
    recovered = {attempt.attempt_id: attempt for attempt in known_attempts}
    local_run_root = workspace_root.resolve() / str(run.run_id)
    if not local_run_root.is_dir():
        return known_attempts
    for workspace_path in sorted(local_run_root.glob("attempt-*")):
        suffix = workspace_path.name.removeprefix("attempt-")
        if not suffix.isdecimal():
            continue
        attempt_id = int(suffix)
        if attempt_id in recovered:
            continue
        attempt_document = (
            root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
        )
        if attempt_document.is_file():
            recovered[attempt_id] = RunAttempt.model_validate(
                parse_yaml_bytes(attempt_document.read_bytes())
            )
            continue
        journal = DurableJournal(workspace_path / "control" / "journal.jsonl")
        entries = journal.read()
        if not entries:
            continue
        if entries[-1].state != "terminal":
            lost_at = datetime.now(UTC)
            journal.append(
                "terminal",
                "attempt failed after coordinator loss",
                recorded_at=lost_at,
                details={"exception": "coordinator_lost"},
            )
        else:
            lost_at = entries[-1].recorded_at
        journal_reference, measurements, metric_receipts, logs = _publish_attempt_files(
            store,
            root,
            run_root,
            attempt_id,
            journal,
            {},
            [],
            [],
        )
        recovered_attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose="run",
            status="failed",
            started_at=entries[0].recorded_at,
            completed_at=datetime.now(UTC),
            resolved_stages=(),
            invocations=(),
            journal=journal_reference,
            measurement_files=measurements,
            metric_verification_files=metric_receipts,
            log_files=logs,
            failure=AttemptFailure(
                code="coordinator_lost",
                stage_id=None,
                message="coordinator exited before terminal attempt publication",
                occurred_at=lost_at,
            ),
        )
        _write_attempt_document(root, run_root, recovered_attempt, store)
        recovered[attempt_id] = recovered_attempt
    return tuple(recovered[key] for key in sorted(recovered))


def _write_materialized_file(root: Path, relative_path: str, raw: bytes) -> None:
    """Write verified input bytes at one safe repository-relative path."""
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise RunError("materialized input escapes the repository root")
    if target.exists() and (not target.is_file() or target.read_bytes() != raw):
        raise RunError("materialized input path contains different bytes")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def _materialize_verified_artifact(
    root: Path,
    target_path: str,
    artifact: VerifiedArtifact,
) -> None:
    """Write every verified artifact file at its selected input path."""
    if artifact.artifact.kind == "file":
        _write_materialized_file(root, target_path, artifact.files[0].content)
        return
    for member, verified_file in zip(
        artifact.artifact.members,
        artifact.files,
        strict=True,
    ):
        _write_materialized_file(
            root,
            f"{target_path}/{member.relative_path}",
            verified_file.content,
        )


def _resolve_inputs(
    root: Path,
    stage: InternalSpec,
    completed: Mapping[StageId, ResolvedStageRef],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
) -> tuple[dict[InputName, ResolvedInternalInputRef], dict[str, Path]]:
    """Materialize stage inputs and bind each one to its verified producer."""
    resolved: dict[InputName, ResolvedInternalInputRef] = {}
    paths: dict[str, Path] = {}
    for name, input_ref in stage.inputs.items():
        if input_ref.kind == "future":
            producer = completed.get(input_ref.producer_stage_id)
            if producer is None:
                raise RunError("future input producer has not completed")
            resolved[name] = ResolvedFutureInputRef(producer=producer)
            producer_spec = stage_specs[input_ref.producer_stage_id]
            artifact = producer_spec.artifacts[input_ref.producer_artifact]
            paths[name] = root / artifact.path
            continue

        assert isinstance(input_ref, StoredInputRef)
        pointer_raw = fetcher(input_ref.pointer)
        pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
        verified = verify_promoted_artifact(
            pointer,
            policy=policy,
            expected_data_role=input_ref.data_role,
            fetcher=fetcher,
        )
        _materialize_verified_artifact(root, input_ref.path, verified)
        resolved[name] = ResolvedStoredInputRef(
            pointer=ResolvedArtifactPointerRef(
                sha256=hashlib.sha256(pointer_raw).hexdigest(),
                bytes=len(pointer_raw),
                stored_at=input_ref.pointer,
            )
        )
        paths[name] = root / input_ref.path
    return resolved, paths


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


def _retrieve_download_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    run: RunSpec,
    stage_id: StageId,
    stage: DownloadSpec,
    store: LocalArtifactStore,
) -> tuple[dict[InputName, ResolvedHttpRetrieval], dict[str, Path]]:
    """Retrieve, verify, publish, and materialize every frozen HTTP input."""
    try:
        transport = resolve_transport(root, stage.transport)
    except (HttpRetrievalError, OSError) as exc:
        raise RunError("selected HTTP transport failed identity checks") from exc

    retrievals: dict[InputName, ResolvedHttpRetrieval] = {}
    paths: dict[str, Path] = {}
    for input_name, request in stage.inputs.items():
        retrieval_workspace = workspace.resolve(
            f"stages/{stage_id}/retrievals/{input_name}"
        )
        retrieval_workspace.mkdir(parents=True, exist_ok=True)
        destination = retrieval_workspace / "body"
        started_at = datetime.now(UTC)
        try:
            result = invoke_transport(
                root,
                transport,
                request,
                stage.policy,
                retrieval_workspace,
                destination,
            )
        except (HttpRetrievalError, OSError) as exc:
            raise RunError(f"HTTP input {input_name!r} failed retrieval") from exc
        completed_at = datetime.now(UTC)
        raw = result.body.read_bytes()
        canonical_path = retrieval_body_path(run, stage_id, input_name)
        body = store.resolved_files({canonical_path: raw})[0]
        _write_materialized_file(root, canonical_path, raw)
        retrievals[input_name] = ResolvedHttpRetrieval(
            input_name=input_name,
            request=request,
            transport=transport,
            response=result.response,
            body=body,
            started_at=started_at,
            completed_at=completed_at,
        )
        paths[input_name] = root / canonical_path
    return retrievals, paths


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


def _resolved_environment(
    fetcher: RunFetcher,
    environment: EnvironmentSpec,
    process: StageProcessResult,
) -> ResolvedLocalEnvironment | ResolvedGCEEnvironment:
    """Resolve one requested environment from child-observed runtime evidence."""
    if isinstance(environment, GCEEnvironmentSpec):
        host = process.execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE execution omitted its observed GCE host")
        return ResolvedGCEEnvironment(
            provisioning=host.provisioning,
            machine_type=host.machine_type,
            compute=environment.compute,
            lockfile=_resolved_git_file(fetcher, environment.lockfile),
            python_environment=process.python_environment,
        )
    return ResolvedLocalEnvironment(
        compute=environment.compute,
        lockfile=_resolved_git_file(fetcher, environment.lockfile),
        python_environment=process.python_environment,
    )


def _resolved_stage(
    stage: BaseSpec,
    *,
    source: ResolvedGitFileRef,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    process: StageProcessResult,
    invocation: ResolvedStageInvocationRef,
    inputs: dict[InputName, ResolvedInternalInputRef] | None,
    retrievals: dict[InputName, ResolvedHttpRetrieval] | None,
    completed_at: datetime,
) -> ResolvedSpec:
    """Construct the concrete resolved-spec subtype for one completed stage."""
    result = process
    common = {
        "spec": stage,
        "source": source,
        "environment": environment,
        "execution_context": result.execution_context,
        "startup": result.startup,
        "invocation": invocation,
        "command": result.command,
        "artifacts": result.artifacts,
        "completed_at": completed_at,
    }
    if isinstance(stage, DownloadSpec):
        assert retrievals is not None
        return ResolvedDownloadSpec(**common, retrievals=retrievals)
    assert inputs is not None
    if stage.kind == "build":
        return ResolvedBuildSpec(**common, inputs=inputs)
    if stage.kind == "embed":
        return ResolvedEmbedSpec(**common, inputs=inputs)
    if stage.kind == "train":
        return ResolvedTrainSpec(**common, inputs=inputs)
    return ResolvedEvaluateSpec(**common, inputs=inputs)


def _execute_attempt(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    retry: bool = False,
    purpose: AttemptPurpose = "run",
) -> RunResult | ConfirmationRunResult:
    """Execute one ordinary or benchmark-confirmation attempt."""
    root = repository_root.resolve()
    run_path = run_spec_path.resolve()
    run_raw = run_path.read_bytes()
    run = RunSpec.model_validate(parse_yaml_bytes(run_raw))
    origin = _git(root, "remote", "get-url", "origin").decode().strip()
    if origin != str(run.source.repository):
        raise RunError("Git origin differs from RunSpec.source.repository")
    plan_commit = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    relative_run_path = run_path.relative_to(root).as_posix()
    if _git(root, "show", f"{plan_commit}:{relative_run_path}") != run_raw:
        raise RunError("RunSpec bytes are absent from the current Git commit")

    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, str(run.source.repository))
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({str(run.source.repository)})
    )
    experiment = ExperimentSpec.model_validate(
        parse_yaml_bytes(
            fetcher(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=f"experiments/{run.experiment_id}/spec.yaml",
                )
            )
        )
    )
    run_root = f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"

    workspace_root = root / ".viper" / "workspaces"
    run_lock = RunWorkspaceLock.for_run(workspace_root, run.run_id)
    run_lock.acquire()
    terminal_path = run_path.parent / "resolved.yaml"
    previous_run: ResolvedRun | None = None
    if terminal_path.is_file():
        previous_run = ResolvedRun.model_validate(
            parse_yaml_bytes(terminal_path.read_bytes())
        )
        if purpose == "run" and not retry:
            run_lock.release()
            raise RunError("run already has terminal attempt history; use retry")
        if purpose == "run" and previous_run.status == "succeeded":
            run_lock.release()
            raise RunError("a successful run cannot be retried")
    elif purpose == "benchmark_confirmation":
        run_lock.release()
        raise RunError("benchmark confirmation requires a terminal candidate run")
    if purpose == "benchmark_confirmation" and previous_run is not None:
        if previous_run.status != "succeeded":
            run_lock.release()
            raise RunError("benchmark confirmation requires a successful candidate run")
    known_attempts = (
        ()
        if previous_run is None
        else tuple(
            read_attempt_reference(reference, run, fetcher=fetcher)
            for reference in previous_run.attempts
        )
    )
    previous_attempts = _reconcile_abandoned_attempts(
        root,
        workspace_root,
        run,
        run_root,
        store,
        known_attempts,
    )
    attempt_id = max(
        next_attempt_id(workspace_root, run.run_id),
        max((attempt.attempt_id for attempt in previous_attempts), default=0) + 1,
    )
    workspace = AttemptWorkspace.create(workspace_root, run.run_id, attempt_id)
    journal = DurableJournal(workspace.control / "journal.jsonl")
    attempt_started = datetime.now(UTC)
    resolved_stage_refs: list[ResolvedStageRef] = []
    invocation_refs: list[ResolvedStageInvocationRef] = []
    completed: dict[StageId, ResolvedStageRef] = {}
    loaded_stages: dict[StageId, BaseSpec] = {}
    measurement_paths: list[Path] = []
    metric_verification_paths: list[Path] = []
    log_files: dict[str, bytes] = {}
    active_stage_id: StageId | None = None
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def cancel_attempt(signum: int, frame: object) -> None:
        """Convert an interrupt request into a durable cancellation outcome."""
        del signum, frame
        raise StageProcessInterrupted("cancelled")

    def preempt_attempt(signum: int, frame: object) -> None:
        """Convert host termination into a durable preemption outcome."""
        del signum, frame
        raise StageProcessInterrupted("preempted")

    signal.signal(signal.SIGINT, cancel_attempt)
    signal.signal(signal.SIGTERM, preempt_attempt)
    try:
        journal.append("allocated", "attempt allocated", recorded_at=attempt_started)
        preflight = preflight_plan(root, run_path)
        preflight_path = workspace.control / "preflight.json"
        _write_synchronized(
            preflight_path,
            f"{preflight.model_dump_json()}\n".encode(),
        )
        journal.append(
            "preflighting",
            "preflight completed and frozen plan located in Git",
            recorded_at=datetime.now(UTC),
            details={
                "plan_commit": plan_commit,
                "report": preflight_path.relative_to(workspace.root).as_posix(),
            },
        )
        if not preflight.ready:
            failed_codes = ", ".join(
                check.code for check in preflight.checks if check.status == "failure"
            )
            raise RunError(f"plan preflight failed: {failed_codes}")
        for stage_reference in run.stages:
            active_stage_id = stage_reference.stage_id
            stage = load_stage_spec(root / stage_reference.spec)
            loaded_stages[stage_reference.stage_id] = stage
            effective_environment = stage.environment or run.environment
            source_location = GitFileRef(
                repository=run.source.repository,
                commit=run.source.commit,
                path=stage.implementation.path,
            )
            source = _resolved_git_file(fetcher, source_location)
            if (root / stage.implementation.path).read_bytes() != fetcher(
                source_location
            ):
                raise RunError("stage source differs from the frozen source")

            resolved_inputs: dict[InputName, ResolvedInternalInputRef] | None = None
            resolved_retrievals: dict[InputName, ResolvedHttpRetrieval] | None = None
            input_paths: dict[str, Path] = {}
            if isinstance(stage, DownloadSpec):
                resolved_retrievals, input_paths = _retrieve_download_inputs(
                    root,
                    workspace,
                    run,
                    stage_reference.stage_id,
                    stage,
                    store,
                )
            elif isinstance(stage, InternalSpec):
                resolved_inputs, input_paths = _resolve_inputs(
                    root,
                    stage,
                    completed,
                    loaded_stages,
                    fetcher,
                    policy,
                )

            journal.append(
                "running_stage",
                "stage process started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )
            try:
                process = execute_stage_process(
                    root,
                    run,
                    stage_reference,
                    stage,
                    attempt_id=attempt_id,
                    input_paths=input_paths,
                    retrievals=resolved_retrievals,
                    timeout_seconds=timeout_seconds,
                )
            except (StageExecutionError, StageProcessInterrupted) as exc:
                run_log_root = f"{run_root}/attempts/{attempt_id}/logs"
                log_files[f"{run_log_root}/{stage_reference.stage_id}.stdout.log"] = (
                    exc.stdout
                )
                log_files[f"{run_log_root}/{stage_reference.stage_id}.stderr.log"] = (
                    exc.stderr
                )
                if exc.invocation is not None:
                    invocation_path = (
                        f"{run_root}/attempts/{attempt_id}/invocations/"
                        f"{stage_reference.stage_id}.yaml"
                    )
                    invocation_refs.append(
                        _publish_invocation_receipt(
                            store,
                            invocation_path,
                            exc.invocation,
                        )
                    )
                raise
            metric_specs = {metric.metric_id: metric for metric in experiment.metrics}
            for metric_id in stage.metric_ids:
                if metric_specs[metric_id].mode != "live":
                    continue
                live_path = (
                    root
                    / (
                        f"experiments/{run.experiment_id}/runs/"
                        f"{run.variant_id}/{run.run_id}"
                    )
                    / f"attempts/{attempt_id}/measurements"
                    / f"{stage_reference.stage_id}.{metric_id}.jsonl"
                )
                if live_path.is_file() and live_path not in measurement_paths:
                    measurement_paths.append(live_path)
            invocation_path = (
                f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                f"/attempts/{attempt_id}/invocations/{stage_reference.stage_id}.yaml"
            )
            invocation_ref = _publish_invocation_receipt(
                store,
                invocation_path,
                process.invocation,
            )
            invocation_refs.append(invocation_ref)
            stage_completed = datetime.now(UTC)
            resolved = _resolved_stage(
                stage,
                source=source,
                environment=_resolved_environment(
                    fetcher,
                    effective_environment,
                    process,
                ),
                process=process,
                invocation=invocation_ref,
                inputs=resolved_inputs,
                retrievals=resolved_retrievals,
                completed_at=stage_completed,
            )
            resolved_path = (
                f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                f"/stages/{stage_reference.stage_id}/resolved.yaml"
            )
            resolved_raw = serialize_document(resolved)
            snapshot_files: dict[str, bytes] = {resolved_path: resolved_raw}
            if resolved_retrievals is not None:
                for retrieval in resolved_retrievals.values():
                    retrieval_path = retrieval.body.stored_at.path
                    snapshot_files[retrieval_path] = (
                        root / retrieval_path
                    ).read_bytes()
            for artifact in process.artifacts.values():
                artifact_references: tuple[SnapshotFileRef, ...]
                if artifact.kind == "file":
                    artifact_references = (artifact.file,)
                else:
                    artifact_references = tuple(
                        member.file for member in artifact.members
                    )
                for reference in artifact_references:
                    snapshot_files[reference.path] = (
                        root / reference.path
                    ).read_bytes()
            journal.append(
                "publishing_stage",
                "stage snapshot publication started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )
            snapshot = store.snapshot(snapshot_files)
            resolved_stage_ref = ResolvedStageRef(
                stage_id=stage_reference.stage_id,
                snapshot=snapshot,
                resolved_spec=snapshot_file(resolved_path, resolved_raw),
            )
            resolved_stage_refs.append(resolved_stage_ref)
            completed[stage_reference.stage_id] = resolved_stage_ref
            _run_after_stage_metrics(
                root,
                run,
                stage_reference.stage_id,
                stage,
                experiment,
                input_paths,
                measurement_paths,
                metric_verification_paths,
                store,
                timeout_seconds,
                attempt_id,
            )
            log_files[
                f"{run_root}/attempts/{attempt_id}/logs/"
                f"{stage_reference.stage_id}.stdout.log"
            ] = process.stdout
            log_files[
                f"{run_root}/attempts/{attempt_id}/logs/"
                f"{stage_reference.stage_id}.stderr.log"
            ] = process.stderr
            active_stage_id = None

        journal.append(
            "closing_attempt",
            "all planned stages completed",
            recorded_at=datetime.now(UTC),
        )
        journal.append(
            "publishing_attempt_files",
            "attempt evidence publication started",
            recorded_at=datetime.now(UTC),
            details={},
        )
        journal.append(
            "terminal",
            "attempt succeeded",
            recorded_at=datetime.now(UTC),
        )
        (
            journal_reference,
            measurement_references,
            metric_verification_references,
            log_references,
        ) = _publish_attempt_files(
            store,
            root,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
        )
        attempt_completed = datetime.now(UTC)
        attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose=purpose,
            status="succeeded",
            started_at=attempt_started,
            completed_at=attempt_completed,
            resolved_stages=tuple(resolved_stage_refs),
            invocations=tuple(invocation_refs),
            journal=journal_reference,
            measurement_files=measurement_references,
            metric_verification_files=metric_verification_references,
            log_files=log_references,
            failure=None,
        )
        run_reference = GitFileRef(
            repository=run.source.repository,
            commit=plan_commit,
            path=relative_run_path,
        )
        attempt_reference = _write_attempt_document(root, run_root, attempt, store)
        if purpose == "benchmark_confirmation":
            return ConfirmationRunResult(
                attempt=attempt,
                attempt_reference=attempt_reference,
                attempt_path=(
                    root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
                ),
                journal_path=journal.path,
            )
        attempt_references = tuple(
            _write_attempt_document(root, run_root, value, store)
            for value in previous_attempts
        ) + (attempt_reference,)
        resolved_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=run_reference,
            ),
            status="succeeded",
            attempts=attempt_references,
            successful_attempt_id=attempt_id,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(resolved_run)
        verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
        _replace_synchronized(terminal_path, terminal_raw)
        _write_synchronized(workspace.terminal, terminal_raw)
        return RunResult(
            resolved_run=resolved_run,
            resolved_run_path=terminal_path,
            journal_path=journal.path,
        )
    except (Exception, KeyboardInterrupt) as exc:
        failed_at = datetime.now(UTC)
        status: Literal["failed", "cancelled", "preempted"]
        if isinstance(exc, StageProcessInterrupted):
            status = exc.outcome
        elif isinstance(exc, KeyboardInterrupt):
            status = "cancelled"
        else:
            status = "failed"
        latest = journal.latest()
        if latest is not None and latest.state != "terminal":
            journal.append(
                "terminal",
                f"attempt {status}",
                recorded_at=failed_at,
                details={
                    "stage_id": active_stage_id,
                    "exception": type(exc).__name__,
                },
            )
        code = (
            "cancelled"
            if status == "cancelled"
            else "preempted"
            if status == "preempted"
            else "preflight_failed"
            if isinstance(exc, RunError)
            and str(exc).startswith("plan preflight failed")
            else "verification_failed"
            if isinstance(exc, VerificationError)
            else "execution_failed"
            if isinstance(
                exc,
                (StageExecutionError, MetricExecutionError, HttpRetrievalError),
            )
            else "internal_error"
        )
        (
            journal_reference,
            measurement_references,
            metric_verification_references,
            log_references,
        ) = _publish_attempt_files(
            store,
            root,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
        )
        completed_at = datetime.now(UTC)
        failed_attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose=purpose,
            status=status,
            started_at=attempt_started,
            completed_at=completed_at,
            resolved_stages=tuple(resolved_stage_refs),
            invocations=tuple(invocation_refs),
            journal=journal_reference,
            measurement_files=measurement_references,
            metric_verification_files=metric_verification_references,
            log_files=log_references,
            failure=AttemptFailure(
                code=code,
                stage_id=active_stage_id,
                message=str(exc) or type(exc).__name__,
                occurred_at=failed_at,
            ),
        )
        run_reference = GitFileRef(
            repository=run.source.repository,
            commit=plan_commit,
            path=relative_run_path,
        )
        failed_attempt_reference = _write_attempt_document(
            root,
            run_root,
            failed_attempt,
            store,
        )
        if purpose == "benchmark_confirmation":
            failed_attempt_path = (
                root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
            )
            raise RunError(
                f"benchmark confirmation attempt {attempt_id} failed; evidence "
                f"written to {failed_attempt_path}"
            ) from exc
        attempt_references = tuple(
            _write_attempt_document(root, run_root, value, store)
            for value in previous_attempts
        ) + (failed_attempt_reference,)
        failed_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=run_reference,
            ),
            status="cancelled" if status == "cancelled" else "failed",
            attempts=attempt_references,
            successful_attempt_id=None,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(failed_run)
        _replace_synchronized(terminal_path, terminal_raw)
        _replace_synchronized(workspace.terminal, terminal_raw)
        raise RunError(
            f"attempt {attempt_id} failed; evidence written to {terminal_path}"
        ) from exc
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        run_lock.release()


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    retry: bool = False,
) -> RunResult:
    """Execute one frozen plan and verify its terminal resolved run."""
    result = _execute_attempt(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        retry=retry,
        purpose="run",
    )
    assert isinstance(result, RunResult)
    return result


def execute_benchmark_confirmation(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> ConfirmationRunResult:
    """Execute one independent confirmation of a successful frozen run."""
    result = _execute_attempt(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        purpose="benchmark_confirmation",
    )
    assert isinstance(result, ConfirmationRunResult)
    return result
