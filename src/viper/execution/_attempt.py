"""Coordinate one durable execution attempt from preflight through closure."""

from __future__ import annotations

import hashlib
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ..experiments import ExperimentSpec
from ..http import HttpRetrievalError, ResolvedHttpRetrieval
from ..ids import InputName, StageId
from ..journal import DurableJournal
from ..preflight import preflight_plan
from ..references import (
    GitFileRef,
    ResolvedRunSpecRef,
    SnapshotFileRef,
)
from ..runs import (
    AttemptFailure,
    AttemptPurpose,
    ResolvedRun,
    RunAttempt,
    RunSpec,
)
from ..serialization import load_stage_spec, parse_yaml_bytes, serialize_document
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
    ResolvedInternalInputRef,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
)
from ..storage import LocalArtifactStore, snapshot_file
from ..verification import (
    VerificationError,
    VerificationPolicy,
    read_attempt_reference,
    verify_run_result,
)
from ..workspace import AttemptWorkspace, RunWorkspaceLock, next_attempt_id
from ._errors import RunError
from ._materialization import _resolve_inputs, _retrieve_download_inputs
from ._metric import MetricExecutionError, _run_after_stage_metrics
from ._publication import (
    _publish_attempt_files,
    _publish_invocation_receipt,
    _replace_synchronized,
    _write_attempt_document,
    _write_synchronized,
)
from ._recovery import _reconcile_abandoned_attempts
from ._resolution import _resolved_environment, _resolved_stage
from ._results import ConfirmationRunResult, RunResult
from ._source import RunFetcher, _git, _resolved_git_file
from ._stage import (
    StageExecutionError,
    StageProcessInterrupted,
    execute_stage_process,
)


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
