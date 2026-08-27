"""Execute and publish one independent benchmark confirmation."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .local_store import LocalArtifactStore
from .protocol import (
    PREDICTIONS,
    ArtifactComparisonReceipt,
    BenchmarkResult,
    BenchmarkSpec,
    EvaluateSpec,
    GitFileRef,
    MetricCriterionReceipt,
    MetricVerificationReceipt,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedRun,
    ResolvedRunRef,
    RunAttempt,
    StageArtifactRef,
)
from .runner import RunFetcher, execute_benchmark_confirmation
from .serialization import document_digest, parse_yaml_bytes, serialize_document
from .verifier import (
    VerificationPolicy,
    verify_attempt_stages,
    verify_benchmark_result,
    verify_run_result,
)


class BenchmarkExecutionError(RuntimeError):
    """Report a benchmark request, execution, or publication failure."""


class BenchmarkExecutionResult(BaseModel):
    """Return one verified benchmark result and its canonical local path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: BenchmarkResult
    result_path: Path


def _write_new(path: Path, raw: bytes) -> None:
    """Atomically create one benchmark result without replacing prior evidence."""
    if path.exists():
        raise BenchmarkExecutionError("benchmark result already exists")
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
        if path.exists():
            raise BenchmarkExecutionError("benchmark result already exists")
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _metric_receipts(
    attempt: RunAttempt,
    store: LocalArtifactStore,
    evaluation_stage_id: str,
) -> dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]]:
    """Load the recomputation receipt for each evaluation metric."""
    receipts: dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]] = {}
    for reference in attempt.metric_verification_files:
        receipt = MetricVerificationReceipt.model_validate(
            parse_yaml_bytes(store.fetch(reference.stored_at))
        )
        if receipt.stage_id == evaluation_stage_id:
            receipts[receipt.metric_id] = (reference, receipt)
    return receipts


def execute_benchmark(
    repository_root: Path,
    resolved_run_path: Path,
    benchmark_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> BenchmarkExecutionResult:
    """Execute, assemble, verify, and publish one benchmark confirmation."""
    root = repository_root.resolve()
    candidate_path = resolved_run_path.resolve()
    candidate_raw = candidate_path.read_bytes()
    candidate = ResolvedRun.model_validate(parse_yaml_bytes(candidate_raw))
    run_spec_path = candidate_path.with_name("spec.yaml")
    store = LocalArtifactStore(root)

    run = candidate.spec
    fetcher = RunFetcher(root, store, str(run.stored_at.repository))
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({str(run.stored_at.repository)})
    )
    verified_candidate = verify_run_result(
        candidate,
        policy=policy,
        fetcher=fetcher,
    )
    plan = verified_candidate.plan
    if plan.benchmark is None or plan.run.benchmark_id is None:
        raise BenchmarkExecutionError("candidate run has no benchmark specification")

    expected_benchmark_path = (
        root / f"benchmarks/{plan.benchmark.benchmark_id}.spec.yaml"
    )
    selected_benchmark_path = benchmark_spec_path.resolve()
    if selected_benchmark_path != expected_benchmark_path.resolve():
        raise BenchmarkExecutionError("benchmark path differs from the frozen plan")
    benchmark_raw = selected_benchmark_path.read_bytes()
    benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(benchmark_raw))
    if benchmark != plan.benchmark:
        raise BenchmarkExecutionError("benchmark document differs from the frozen plan")
    benchmark_location = GitFileRef(
        repository=plan.run.source.repository,
        commit=plan.run.source.commit,
        path=f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if fetcher(benchmark_location) != benchmark_raw:
        raise BenchmarkExecutionError("benchmark bytes differ from the frozen source")

    result_path = candidate_path.with_name("benchmark.result.yaml")
    if result_path.exists():
        raise BenchmarkExecutionError("benchmark result already exists")
    confirmation_result = execute_benchmark_confirmation(
        root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
    )
    confirmation = confirmation_result.attempt
    confirmation_stages = verify_attempt_stages(
        confirmation,
        plan.run,
        plan.stages,
        require_complete=True,
        policy=policy,
        fetcher=fetcher,
    )
    selected_attempt = next(
        attempt
        for attempt in verified_candidate.attempts
        if attempt.attempt_id == candidate.successful_attempt_id
    )
    selected_stage_refs = {
        stage.stage_id: stage for stage in selected_attempt.resolved_stages
    }
    confirmation_stage_refs = {
        stage.stage_id: stage for stage in confirmation.resolved_stages
    }

    evaluation_stage_ids = tuple(
        stage_id
        for stage_id, stage in plan.stages.items()
        if isinstance(stage, EvaluateSpec)
    )
    if len(evaluation_stage_ids) != 1:
        raise BenchmarkExecutionError("benchmark requires one evaluation stage")
    evaluation_stage_id = evaluation_stage_ids[0]
    artifact_selectors = (
        plan.run.estimator,
        StageArtifactRef(
            stage_id=evaluation_stage_id,
            artifact_name=PREDICTIONS,
        ),
    )
    artifact_receipts: list[ArtifactComparisonReceipt] = []
    for selector in artifact_selectors:
        candidate_artifact = verified_candidate.resolved_stages[
            selector.stage_id
        ].artifacts[selector.artifact_name]
        confirmation_artifact = confirmation_stages[selector.stage_id].artifacts[
            selector.artifact_name
        ]
        candidate_digest = document_digest(candidate_artifact)
        confirmation_digest = document_digest(confirmation_artifact)
        artifact_receipts.append(
            ArtifactComparisonReceipt(
                artifact=selector,
                candidate_stage=selected_stage_refs[selector.stage_id],
                confirmation_stage=confirmation_stage_refs[selector.stage_id],
                candidate_digest=candidate_digest,
                confirmation_digest=confirmation_digest,
                passed=candidate_digest == confirmation_digest,
            )
        )

    candidate_metrics = _metric_receipts(selected_attempt, store, evaluation_stage_id)
    confirmation_metrics = _metric_receipts(
        confirmation,
        store,
        evaluation_stage_id,
    )
    metric_receipts: list[MetricCriterionReceipt] = []
    for criterion in benchmark.metrics:
        try:
            candidate_ref, candidate_receipt = candidate_metrics[criterion.metric_id]
            confirmation_ref, confirmation_receipt = confirmation_metrics[
                criterion.metric_id
            ]
        except KeyError as exc:
            raise BenchmarkExecutionError(
                f"benchmark metric {criterion.metric_id!r} lacks verification evidence"
            ) from exc
        values = (
            candidate_receipt.recomputation.value,
            confirmation_receipt.recomputation.value,
        )
        passed = (
            all(value >= criterion.threshold for value in values)
            if criterion.comparison == "ge"
            else all(value <= criterion.threshold for value in values)
        )
        metric_receipts.append(
            MetricCriterionReceipt(
                metric_id=criterion.metric_id,
                candidate_verification=candidate_ref,
                confirmation_verification=confirmation_ref,
                comparison=criterion.comparison,
                threshold=criterion.threshold,
                passed=passed,
            )
        )

    candidate_reference = store.resolved_files(
        {candidate_path.relative_to(root).as_posix(): candidate_raw}
    )[0]
    result = BenchmarkResult(
        benchmark=ResolvedBenchmarkSpecRef(
            sha256=hashlib.sha256(benchmark_raw).hexdigest(),
            bytes=len(benchmark_raw),
            stored_at=benchmark_location,
        ),
        run=ResolvedRunRef(
            sha256=candidate_reference.sha256,
            bytes=candidate_reference.bytes,
            stored_at=candidate_reference.stored_at,
        ),
        confirmation=confirmation_result.attempt_reference,
        artifacts=tuple(artifact_receipts),
        metrics=tuple(metric_receipts),
        status=(
            "passed"
            if all(receipt.passed for receipt in artifact_receipts)
            and all(receipt.passed for receipt in metric_receipts)
            else "failed"
        ),
        completed_at=datetime.now(UTC),
    )
    verify_benchmark_result(result, policy=policy, fetcher=fetcher)
    _write_new(result_path, serialize_document(result))
    return BenchmarkExecutionResult(result=result, result_path=result_path)
