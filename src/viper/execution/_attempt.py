"""Coordinate one durable execution attempt from preflight through closure."""

from __future__ import annotations

import hashlib
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .._verification.storage import read_attempt_reference
from ..experiments import ExperimentSpec
from ..http import HttpRetrievalError, ResolvedHttpRetrieval
from ..ids import InputName, StageId
from ..inputs import ExternalInputRef, FutureInputRef, ResolvedInputRef, StoredInputRef
from ..journal import DurableJournal
from ..preflight import preflight_plan
from ..references import (
    GitFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    SnapshotFileRef,
    ViperCloudFileRef,
    storage_file,
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
    ParameterizedSpec,
    ResolvedBaseSpec,
    ResolvedInternalSpec,
)
from ..storage import (
    LocalArtifactStore,
    ViperCloudClient,
    bind_run_destination,
    create_snapshot_publisher,
    load_storage_settings,
    publish_resolved_files,
    snapshot_file,
)
from ..verification import verify_run_result
from ..verification.models import VerificationError, VerificationPolicy
from ..workspace import AttemptWorkspace, RunWorkspaceLock, next_attempt_id
from ._materialization import (
    resolve_inputs,
    retrieve_download_inputs,
    verify_captured_inputs,
)
from ._metric import MetricExecutionError, run_after_stage_metrics
from ._publication import (
    publish_attempt_files,
    publish_invocation_receipt,
    replace_synchronized,
    write_attempt_document,
    write_synchronized,
)
from ._recovery import reconcile_abandoned_attempts
from ._resolution import (
    resolve_download_stage,
    resolve_env,
    resolve_runner_env,
    resolve_stage,
)
from ._source import RunFetcher, resolve_git_file, run_git
from ._stage import (
    StageExecutionError,
    StageProcessInterrupted,
    execute_stage_process,
)
from .errors import RunError
from .results import ConfirmationRunResult, RunResult
from ..catalog import Catalog

from ..reuse import ReuseInputIdentity, build_stage_reuse_key, input_identity

from ._reuse import reuse_stage



def _reuse_input_identities(
    stage: InternalSpec,
    paths: dict[str, Path],
    loaded_stages: dict[StageId, BaseSpec],
) -> tuple[ReuseInputIdentity, ...]:
    """Hash materialized inputs with the roles declared by their producers."""
    identities = []
    for name, reference in stage.inputs.items():
        if isinstance(reference, (ExternalInputRef, StoredInputRef)):
            role = reference.data_role
        elif isinstance(reference, FutureInputRef):
            producer = loaded_stages[reference.producer_stage_id]
            role = producer.artifacts[reference.name].data_role
        else:
            raise RunError("stage input has no reuse role")
        identities.append(input_identity(name, role, paths[str(name)]))
    return tuple(sorted(identities, key=lambda item: item.input_name))

def execute_attempt(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
    retry: bool = False,
    purpose: AttemptPurpose = "run",
    cloud_client: ViperCloudClient | None = None,
) -> RunResult | ConfirmationRunResult:
    """Execute one ordinary or benchmark-confirmation attempt."""
    root = repository_root.resolve()
    run_path = run_spec_path.resolve()
    run_raw = run_path.read_bytes()
    run = RunSpec.model_validate(parse_yaml_bytes(run_raw))
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(
        root,
        store,
        str(run.source.repository),
        cloud_client=cloud_client,
    )
    origin = run_git(root, "remote", "get-url", "origin").decode().strip()
    if origin != str(run.source.repository):
        raise RunError("Git origin differs from RunSpec.source.repository")
    relative_run_path = run_path.relative_to(root).as_posix()
    if plan is None:
        plan_commit = run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
        if run_git(root, "show", f"{plan_commit}:{relative_run_path}") != run_raw:
            raise RunError("RunSpec bytes are absent from the current Git commit")
        plan_location = GitFileRef(
            repository=run.source.repository,
            commit=plan_commit,
            path=relative_run_path,
        )
    else:
        if plan.stored_at.path != relative_run_path:
            raise RunError("run path differs from the immutable plan reference")
        if fetcher(plan.stored_at) != run_raw:
            raise RunError("RunSpec bytes differ from the immutable plan")
        plan_location = plan.stored_at
    plan_revision = (
        plan_location.revision
        if isinstance(plan_location, ViperCloudFileRef)
        else plan_location.commit
    )

    destination = bind_run_destination(
        root,
        run.run_id,
        load_storage_settings(root).destination,
    )
    snapshot_publisher = create_snapshot_publisher(
        root,
        destination,
        cloud_client=cloud_client,
    )
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({str(run.source.repository)})
    )
    experiment = ExperimentSpec.model_validate(
        parse_yaml_bytes(
            fetcher(
                storage_file(
                    plan_location,
                    f"experiments/{run.experiment_id}/spec.yaml",
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
    previous_attempts = reconcile_abandoned_attempts(
        root,
        workspace_root,
        run,
        run_root,
        destination,
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
    completed_results: dict[StageId, ResolvedBaseSpec] = {}
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
        preflight = preflight_plan(root, run_path, plan=plan)
        preflight_path = workspace.control / "preflight.json"
        write_synchronized(
            preflight_path,
            f"{preflight.model_dump_json()}\n".encode(),
        )
        journal.append(
            "preflighting",
            "preflight completed and immutable plan located",
            recorded_at=datetime.now(UTC),
            details={
                "plan_commit": plan_revision,
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
            effective_environment = stage.env or run.env
            resolved_inputs: dict[InputName, ResolvedInputRef] | None = None
            resolved_retrievals: dict[InputName, ResolvedHttpRetrieval] | None = None
            captured_inputs: dict[InputName, SnapshotFileRef] = {}
            stored_input_references: dict[InputName, tuple[ResolvedFileRef, ...]] = {}
            input_paths: dict[str, Path] = {}
            process = None
            journal.append(
                "running_stage",
                "stage execution started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )

            if isinstance(stage, DownloadSpec):
                runner_environment, execution_context = resolve_runner_env(
                    fetcher,
                    effective_environment,
                )
                (
                    resolved_retrievals,
                    resolved_artifacts,
                    input_paths,
                ) = retrieve_download_inputs(
                    root,
                    workspace,
                    stage_reference.stage_id,
                    stage,
                )
                stage_completed = datetime.now(UTC)
                resolved = resolve_download_stage(
                    stage,
                    env=runner_environment,
                    execution_context=execution_context,
                    artifacts=resolved_artifacts,
                    retrievals=resolved_retrievals,
                    completed_at=stage_completed,
                )
            else:
                if not isinstance(stage, ParameterizedSpec):
                    raise RunError("project stage lacks its parameterized contract")
                source_location = GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=stage.implementation.path,
                )
                source = resolve_git_file(fetcher, source_location)
                if (root / stage.implementation.path).read_bytes() != fetcher(
                    source_location
                ):
                    raise RunError("stage source differs from the frozen source")
                if isinstance(stage, InternalSpec):
                    (
                        resolved_inputs,
                        input_paths,
                        captured_inputs,
                        stored_input_references,
                    ) = resolve_inputs(
                        root,
                        workspace,
                        run.run_id,
                        attempt_id,
                        stage_reference.stage_id,
                        stage,
                        completed,
                        loaded_stages,
                        fetcher,
                        policy,
                    )
                if (
                    isinstance(stage, InternalSpec)
                    and stage.reuse == "verified"
                    and purpose == "run"
                ):
                    metric_specs = {
                        metric.metric_id: metric for metric in experiment.metrics
                    }
                    key = build_stage_reuse_key(
                        stage_id=stage_reference.stage_id,
                        stage=stage,
                        inputs=_reuse_input_identities(
                            stage,
                            input_paths,
                            loaded_stages,
                        ),
                        seed=run.seed,
                        env=effective_environment,
                        reproducibility=run.reproducibility,
                        metrics=metric_specs,
                    )
                    resolved_path = (
                        f"experiments/{run.experiment_id}/runs/{run.variant_id}/"
                        f"{run.run_id}/stages/{stage_reference.stage_id}/resolved.yaml"
                    )
                    reused = reuse_stage(
                        root=root,
                        catalog=Catalog(root),
                        key=key,
                        stage=stage,
                        inputs=resolved_inputs or {},
                        captured_inputs=captured_inputs,
                        resolved_stage_path=resolved_path,
                        fetcher=fetcher,
                        policy=policy,
                        publisher=snapshot_publisher,
                        destination=destination,
                        cloud_client=cloud_client,
                        metrics=metric_specs,
                    )
                    if reused is not None:
                        journal.append(
                            "publishing_stage",
                            "verified stage reuse published",
                            recorded_at=datetime.now(UTC),
                            details={"stage_id": stage_reference.stage_id},
                        )
                        resolved_raw = serialize_document(reused.resolved)
                        resolved_stage_ref = ResolvedStageRef(
                            stage_id=stage_reference.stage_id,
                            snapshot=reused.snapshot,
                            resolved_spec=snapshot_file(resolved_path, resolved_raw),
                        )
                        resolved_stage_refs.append(resolved_stage_ref)
                        completed[stage_reference.stage_id] = resolved_stage_ref
                        completed_results[stage_reference.stage_id] = reused.resolved
                        active_stage_id = None
                        continue
                try:
                    process = execute_stage_process(
                        root,
                        run,
                        stage_reference,
                        stage,
                        attempt_id=attempt_id,
                        input_paths=input_paths,
                        timeout_seconds=timeout_seconds,
                    )
                except (StageExecutionError, StageProcessInterrupted) as exc:
                    run_log_root = f"{run_root}/attempts/{attempt_id}/logs"
                    log_files[
                        f"{run_log_root}/{stage_reference.stage_id}.stdout.log"
                    ] = exc.stdout
                    log_files[
                        f"{run_log_root}/{stage_reference.stage_id}.stderr.log"
                    ] = exc.stderr
                    if exc.invocation is not None:
                        invocation_path = (
                            f"{run_root}/attempts/{attempt_id}/invocations/"
                            f"{stage_reference.stage_id}.yaml"
                        )
                        invocation_refs.append(
                            publish_invocation_receipt(
                                root,
                                destination,
                                invocation_path,
                                exc.invocation,
                                cloud_client=cloud_client,
                            )
                        )
                    raise
                invocation_path = (
                    f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                    f"/attempts/{attempt_id}/invocations/{stage_reference.stage_id}.yaml"
                )
                invocation_ref = publish_invocation_receipt(
                    root,
                    destination,
                    invocation_path,
                    process.invocation,
                    cloud_client=cloud_client,
                )
                invocation_refs.append(invocation_ref)
                stage_completed = datetime.now(UTC)
                resolved = resolve_stage(
                    stage,
                    source=source,
                    env=resolve_env(
                        fetcher,
                        effective_environment,
                        process,
                    ),
                    process=process,
                    invocation=invocation_ref,
                    inputs=resolved_inputs,
                    completed_at=stage_completed,
                )
                resolved_artifacts = process.artifacts
                metric_specs = {
                    metric.metric_id: metric for metric in experiment.metrics
                }
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
            resolved_path = (
                f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                f"/stages/{stage_reference.stage_id}/resolved.yaml"
            )
            resolved_raw = serialize_document(resolved)
            verify_captured_inputs(root, captured_inputs)
            snapshot_paths: dict[str, Path] = {
                reference.path: root / reference.path
                for reference in captured_inputs.values()
            }
            if resolved_retrievals is not None:
                for retrieval in resolved_retrievals.values():
                    retrieval_path = retrieval.body.path
                    snapshot_paths[retrieval_path] = root / retrieval_path
            for artifact in resolved_artifacts.values():
                artifact_references: tuple[SnapshotFileRef, ...]
                if artifact.kind == "file":
                    artifact_references = (artifact.file,)
                else:
                    artifact_references = tuple(
                        member.file for member in artifact.members
                    )
                for reference in artifact_references:
                    snapshot_paths[reference.path] = root / reference.path
            journal.append(
                "publishing_stage",
                "stage snapshot publication started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )
            snapshot = snapshot_publisher.publish(
                resolved_stage_path=resolved_path,
                resolved_stage=resolved_raw,
                files=snapshot_paths,
            )
            resolved_stage_ref = ResolvedStageRef(
                stage_id=stage_reference.stage_id,
                snapshot=snapshot,
                resolved_spec=snapshot_file(resolved_path, resolved_raw),
            )
            resolved_stage_refs.append(resolved_stage_ref)
            completed[stage_reference.stage_id] = resolved_stage_ref
            completed_results[stage_reference.stage_id] = resolved
            if isinstance(stage, InternalSpec):
                resolved_internal = ResolvedInternalSpec.model_validate(resolved)
                run_after_stage_metrics(
                    root,
                    run,
                    stage_reference.stage_id,
                    stage,
                    resolved_internal,
                    resolved_stage_ref,
                    completed_results,
                    stored_input_references,
                    experiment,
                    input_paths,
                    measurement_paths,
                    metric_verification_paths,
                    timeout_seconds,
                    attempt_id,
                )
            if process is not None:
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
        ) = publish_attempt_files(
            root,
            destination,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
            cloud_client=cloud_client,
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
        attempt_reference = write_attempt_document(
            root,
            run_root,
            attempt,
            destination,
            cloud_client=cloud_client,
        )
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
            write_attempt_document(
                root,
                run_root,
                value,
                destination,
                cloud_client=cloud_client,
            )
            for value in previous_attempts
        ) + (attempt_reference,)
        resolved_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=plan_location,
            ),
            status="succeeded",
            attempts=attempt_references,
            successful_attempt_id=attempt_id,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(resolved_run)
        verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
        replace_synchronized(terminal_path, terminal_raw)
        write_synchronized(workspace.terminal, terminal_raw)
        terminal_reference = publish_resolved_files(
            root,
            destination,
            {terminal_path.relative_to(root).as_posix(): terminal_raw},
            cloud_client=cloud_client,
        )[terminal_path.relative_to(root).as_posix()]
        return RunResult(
            resolved_run=resolved_run,
            resolved_run_ref=ResolvedRunRef(
                sha256=terminal_reference.sha256,
                bytes=terminal_reference.bytes,
                stored_at=terminal_reference.stored_at,
            ),
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
        ) = publish_attempt_files(
            root,
            destination,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
            cloud_client=cloud_client,
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
        failed_attempt_reference = write_attempt_document(
            root,
            run_root,
            failed_attempt,
            destination,
            cloud_client=cloud_client,
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
            write_attempt_document(
                root,
                run_root,
                value,
                destination,
                cloud_client=cloud_client,
            )
            for value in previous_attempts
        ) + (failed_attempt_reference,)
        failed_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=plan_location,
            ),
            status="cancelled" if status == "cancelled" else "failed",
            attempts=attempt_references,
            successful_attempt_id=None,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(failed_run)
        replace_synchronized(terminal_path, terminal_raw)
        replace_synchronized(workspace.terminal, terminal_raw)
        raise RunError(
            f"attempt {attempt_id} failed; evidence written to {terminal_path}"
        ) from exc
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        run_lock.release()
