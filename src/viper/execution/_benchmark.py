"""Execute and publish one independent benchmark confirmation."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .. import keys
from .._source import RunFetcher
from .._verification.attempt import verify_attempt_stages
from .._verification.metrics import (
    benchmark_metric_results,
    benchmark_status,
    eval_metric_receipts,
)
from .._verification.storage import fetch_storage_bytes, read_resolved_file
from ..artifacts import StageArtifactRef
from ..benchmark import (
    ArtifactComparisonReceipt,
    BenchmarkResult,
    BenchmarkSpec,
)
from ..evidence import VerificationPolicy
from ..references import (
    GitFileRef,
    LocalFileRef,
    ResolvedBenchmarkResultRef,
    ResolvedBenchmarkSpecRef,
    ResolvedRunRef,
    storage_file,
)
from ..runs import ResolvedRun, RunSpec
from ..serialization import document_digest, parse_yaml_bytes, serialize_document
from ..stages import EvalSpec
from ..storage import (
    LocalArtifactStore,
    bind_run_destination,
    load_storage_settings,
    local_artifact_store,
    publish_resolved_files,
)
from ..verification import verify_benchmark_evidence, verify_run_result
from ._run import execute_benchmark_confirmation
from .errors import BenchmarkExecutionError
from .results import BenchmarkExecutionResult


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


def _benchmark_mirror_path(
    root: Path,
    benchmark: BenchmarkSpec,
    candidate_path: Path,
) -> Path:
    """Return the benchmark-indexed mirror path for one candidate run."""
    run_directory = candidate_path.parent.relative_to(root)
    parts = run_directory.parts
    if len(parts) != 5 or parts[0] != "experiments" or parts[2] != "runs":
        raise BenchmarkExecutionError("candidate run path is outside experiments")
    _, experiment_id, _, variant_id, run_id = parts
    return (
        root
        / "benchmarks"
        / benchmark.benchmark_id
        / "runs"
        / experiment_id
        / variant_id
        / run_id
        / "benchmark.result.yaml"
    )


def benchmark(
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
    if isinstance(run.stored_at, GitFileRef):
        source_repository = str(run.stored_at.repository)
        run_raw = RunFetcher(root, store, source_repository)(run.stored_at)
    elif isinstance(run.stored_at, LocalFileRef):
        run_raw = local_artifact_store(run.stored_at).fetch(run.stored_at)
        source_repository = str(
            RunSpec.model_validate(parse_yaml_bytes(run_raw)).source.repository
        )
    else:
        run_raw = fetch_storage_bytes(run.stored_at)
        source_repository = str(
            RunSpec.model_validate(parse_yaml_bytes(run_raw)).source.repository
        )
    fetcher = RunFetcher(
        root,
        store,
        source_repository,
    )
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({source_repository})
    )
    verified_candidate = verify_run_result(
        candidate,
        policy=policy,
        fetcher=fetcher,
    )
    plan = verified_candidate.plan
    destination = bind_run_destination(
        root,
        plan.run.run_id,
        load_storage_settings(root).destination,
    )
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
    benchmark_location = storage_file(
        candidate.spec.stored_at,
        f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if fetcher(benchmark_location) != benchmark_raw:
        raise BenchmarkExecutionError("benchmark bytes differ from the frozen plan")

    result_path = candidate_path.with_name("benchmark.result.yaml")
    if result_path.exists():
        raise BenchmarkExecutionError("benchmark result already exists")
    confirmation_result = execute_benchmark_confirmation(
        root,
        run_spec_path,
        # Confirm the same stored plan even when its files were never Git-committed.
        plan=candidate.spec,
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

    eval_stage_ids = tuple(
        stage_id
        for stage_id, stage in plan.stages.items()
        if isinstance(stage, EvalSpec)
    )
    if len(eval_stage_ids) != 1:
        raise BenchmarkExecutionError("benchmark requires one eval stage")
    eval_stage_id = eval_stage_ids[0]
    artifact_selectors = (
        plan.run.estimator,
        StageArtifactRef(
            stage_id=eval_stage_id,
            artifact_name=keys.Eval.PREDICTIONS,
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

    candidate_metrics = eval_metric_receipts(
        selected_attempt,
        eval_stage_id,
        reused=verified_candidate.reuse.get(eval_stage_id),
        fetcher=fetcher,
    )
    confirmation_metrics = eval_metric_receipts(
        confirmation,
        eval_stage_id,
        reused=None,
        fetcher=fetcher,
    )
    metric_receipts = benchmark_metric_results(
        benchmark,
        candidate_metrics,
        confirmation_metrics,
    )

    candidate_relative_path = candidate_path.relative_to(root).as_posix()
    candidate_reference = publish_resolved_files(
        root,
        destination,
        {candidate_relative_path: candidate_raw},
    )[candidate_relative_path]
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
        metrics=metric_receipts,
        status=benchmark_status(benchmark, tuple(artifact_receipts), metric_receipts),
        completed_at=datetime.now(UTC),
    )
    if read_resolved_file(result.run, fetcher=fetcher) != candidate_raw:
        raise BenchmarkExecutionError("published candidate bytes differ")
    verify_benchmark_evidence(
        result,
        verified_candidate,
        policy=policy,
        fetcher=fetcher,
        verified_confirmation=(confirmation, confirmation_stages),
    )
    result_raw = serialize_document(result)
    _write_new(result_path, result_raw)
    mirror_path = _benchmark_mirror_path(root, benchmark, candidate_path)
    _write_new(mirror_path, result_raw)
    result_relative_path = result_path.relative_to(root).as_posix()
    result_reference = publish_resolved_files(
        root,
        destination,
        {result_relative_path: result_raw},
    )[result_relative_path]
    return BenchmarkExecutionResult(
        record=result,
        reference=ResolvedBenchmarkResultRef(
            sha256=result_reference.sha256,
            bytes=result_reference.bytes,
            stored_at=result_reference.stored_at,
        ),
        path=result_path,
    )
