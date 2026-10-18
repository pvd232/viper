"""Tests for benchmark execution models and the typed API operation."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

import viper.verification as verification
from tests.git_repository import run_git
from tests.test_verification_acceptance import (
    POLICY,
    build_benchmark_fixture,
    fetch_attempt,
)
from viper._verification.metrics import benchmark_metric_results, benchmark_status
from viper.api import ExecuteBenchmarkRequest
from viper.api import execute_benchmark as execute_benchmark_application
from viper.benchmark import (
    ArtifactComparisonReceipt,
    BenchmarkResult,
    BenchmarkSpec,
    MetricCriterion,
)
from viper.evidence import VerificationError, VerificationPolicy
from viper.execution._benchmark import _benchmark_mirror_path, benchmark
from viper.execution.results import BenchmarkExecutionResult, ConfirmationRunResult
from viper.metrics import (
    FloatComparator,
    MetricExecutionReceipt,
    MetricVerificationReceipt,
)
from viper.references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedBenchmarkResultRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedRunRef,
)
from viper.runs import ResolvedAttemptRef
from viper.storage import LocalArtifactStore


def _file(path: str) -> ResolvedFileRef:
    """Build one local file reference for a focused benchmark test."""
    return ResolvedFileRef(
        sha256="a" * 64,
        bytes=1,
        stored_at=LocalFileRef(
            workspace=Path("/workspace"),
            commit="b" * 64,
            path=path,
        ),
    )


def _pointer(path: str) -> ResolvedArtifactPointerRef:
    """Build one resolved benchmark-input pointer."""
    output_name = Path(path).name.removesuffix(".pointer.yaml")
    return ResolvedArtifactPointerRef(
        sha256="a" * 64,
        bytes=1,
        stored_at=LocalFileRef(
            workspace=Path("/workspace"),
            commit="b" * 64,
            path=f".viper/pointers/{'a' * 64}/benchmark/{output_name}.pointer.yaml",
        ),
    )


def _metric(value: float) -> MetricVerificationReceipt:
    """Build the metric fields consumed by benchmark assembly."""
    return MetricVerificationReceipt.model_construct(
        recomputation=MetricExecutionReceipt.model_construct(value=value),
        comparator=FloatComparator(),
        passed=True,
    )


def test_benchmark_spec_counts_candidate_and_confirmation() -> None:
    """Expose the fixed two-execution contract through its public field."""
    benchmark = BenchmarkSpec(
        benchmark_id="holdout",
        eval_id="eval",
        test=_pointer("inputs/datasets/holdout/test.pointer.yaml"),
        splits={"split": _pointer("inputs/benchmarks/holdout/split.pointer.yaml")},
        metric_ids=("loss",),
    )

    assert benchmark.execution_count == 2


def test_benchmark_result_reference_accepts_local_immutable_storage() -> None:
    """Permit a local runner to bind its immutable benchmark result bytes."""
    reference = ResolvedBenchmarkResultRef(
        sha256="a" * 64,
        bytes=12,
        stored_at=LocalFileRef(
            workspace=Path("/workspace"),
            store=".viper/store",
            commit="b" * 64,
            path="experiments/e/runs/v/01ARZ3NDEKTSV4RRFFQ69G5FAV/benchmark.result.yaml",
        ),
    )

    assert reference.stored_at.kind == "local"


def test_benchmark_mirror_path_indexes_result_by_benchmark_and_run(
    tmp_path: Path,
) -> None:
    """Mirror benchmark results under the benchmark directory for local discovery."""
    benchmark = BenchmarkSpec(
        benchmark_id="sota",
        eval_id="evaluate",
        test=_pointer("inputs/datasets/holdout/test.pointer.yaml"),
        splits={"split": _pointer("inputs/benchmarks/holdout/split.pointer.yaml")},
        metric_ids=("accuracy",),
    )
    candidate_path = (
        tmp_path
        / "experiments/k562_cluster64_hopfield_v6/runs"
        / "cluster64_canonical_sota_v6_dual_space/01M2ZFP03ZKSRJ8T41NHHHGX04"
        / "resolved.yaml"
    )

    mirror_path = _benchmark_mirror_path(tmp_path, benchmark, candidate_path)

    assert mirror_path == (
        tmp_path
        / "benchmarks/sota/runs/k562_cluster64_hopfield_v6"
        / "cluster64_canonical_sota_v6_dual_space/01M2ZFP03ZKSRJ8T41NHHHGX04"
        / "benchmark.result.yaml"
    )


def test_benchmark_records_metrics_before_criteria() -> None:
    """Record every metric while attaching a criterion only where declared."""
    benchmark = BenchmarkSpec(
        benchmark_id="holdout",
        eval_id="eval",
        test=_pointer("inputs/datasets/holdout/test.pointer.yaml"),
        splits={"split": _pointer("inputs/benchmarks/holdout/split.pointer.yaml")},
        metric_ids=("loss", "accuracy"),
        criteria=(
            MetricCriterion(metric_id="accuracy", comparison="ge", threshold=0.9),
        ),
    )
    candidate = {
        "loss": (_file("candidate-loss.yaml"), _metric(0.2)),
        "accuracy": (_file("candidate-accuracy.yaml"), _metric(0.95)),
    }
    confirmation = {
        "loss": (_file("confirmation-loss.yaml"), _metric(0.2)),
        "accuracy": (_file("confirmation-accuracy.yaml"), _metric(0.95)),
    }

    metrics = benchmark_metric_results(benchmark, candidate, confirmation)

    assert tuple(metric.metric_id for metric in metrics) == benchmark.metric_ids
    assert metrics[0].criterion is None
    assert metrics[1].criterion is not None
    assert metrics[1].criterion.passed
    assert (
        benchmark_status(
            benchmark,
            (ArtifactComparisonReceipt.model_construct(passed=True),),
            metrics,
        )
        == "passed"
    )


def test_benchmark_status_covers_verified_and_failed_results() -> None:
    """Separate criterion-free verification from threshold or parity failure."""
    test = _pointer("inputs/datasets/holdout/test.pointer.yaml")
    splits = {"split": _pointer("inputs/benchmarks/holdout/split.pointer.yaml")}
    verified = BenchmarkSpec(
        benchmark_id="holdout",
        eval_id="eval",
        test=test,
        splits=splits,
        metric_ids=("accuracy",),
    )
    files = {
        "accuracy": (_file("accuracy.yaml"), _metric(0.95)),
    }
    metrics = benchmark_metric_results(verified, files, files)
    artifacts = (ArtifactComparisonReceipt.model_construct(passed=True),)

    assert benchmark_status(verified, artifacts, metrics) == "verified"

    threshold = verified.model_copy(
        update={
            "criteria": (
                MetricCriterion(
                    metric_id="accuracy",
                    comparison="ge",
                    threshold=0.99,
                ),
            )
        }
    )
    failed_threshold = benchmark_metric_results(threshold, files, files)
    assert benchmark_status(threshold, artifacts, failed_threshold) == "failed"

    mismatch = benchmark_metric_results(
        verified,
        files,
        {"accuracy": (_file("confirmation.yaml"), _metric(0.94))},
    )
    assert benchmark_status(verified, artifacts, mismatch) == "failed"


def test_api_returns_the_verified_benchmark_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the result and canonical path produced by the benchmark executor."""
    (tmp_path / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )
    run_git(tmp_path, "init")
    result = BenchmarkResult.model_construct(
        benchmark=ResolvedBenchmarkSpecRef.model_construct(),
        run=ResolvedRunRef.model_construct(),
        confirmation=ResolvedAttemptRef.model_construct(),
        artifacts=(),
        metrics=(),
        status="verified",
        completed_at=datetime.now(UTC),
    )
    result_path = tmp_path / "benchmark.result.yaml"
    execution_result = BenchmarkExecutionResult(
        record=result,
        reference=ResolvedBenchmarkResultRef.model_construct(),
        path=result_path,
    )
    assert execution_result.status == result.status
    assert execution_result.path == result_path
    monkeypatch.setattr(
        "viper.api.execute_benchmark_run",
        lambda *args, **kwargs: execution_result,
    )

    response = execute_benchmark_application(
        ExecuteBenchmarkRequest(
            resolved_run=tmp_path / "resolved.yaml",
            benchmark_spec=tmp_path / "benchmark.spec.yaml",
            root=tmp_path,
        )
    )

    assert response.result == result
    assert response.result_path == result_path


def test_benchmark_reuses_verified_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the candidate and confirmation stages once, then check assembly."""
    fixture, candidate, store = build_benchmark_fixture()
    confirmation = fetch_attempt(store, fixture.confirmation)
    candidate_path = tmp_path / str(fixture.run.stored_at.path)
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(store.fetch(fixture.run.stored_at))
    benchmark_path = tmp_path / str(fixture.benchmark.stored_at.path)
    benchmark_path.parent.mkdir(parents=True)
    benchmark_path.write_bytes(store.fetch(fixture.benchmark.stored_at))
    (tmp_path / "viper.toml").write_text("[workspace]\nschema_version = 2\n")

    def fetch(location):
        """Read newly published local records and immutable fixture records."""
        if isinstance(location, LocalFileRef):
            return LocalArtifactStore(tmp_path).fetch(location)
        return store.fetch(location)

    monkeypatch.setattr(
        fetch, "list_snapshot_files", store.list_snapshot_files, raising=False
    )
    monkeypatch.setitem(
        benchmark.__globals__, "RunFetcher", lambda *args, **kwargs: fetch
    )
    run_check = Mock(wraps=verification.verify_run_result)
    stage_check = Mock(wraps=verification.verify_attempt_stages)
    monkeypatch.setitem(benchmark.__globals__, "verify_run_result", run_check)
    monkeypatch.setattr(verification, "verify_run_result", run_check)
    monkeypatch.setitem(benchmark.__globals__, "verify_attempt_stages", stage_check)
    monkeypatch.setattr(verification, "verify_attempt_stages", stage_check)
    confirm = Mock(
        return_value=ConfirmationRunResult(
            attempt=confirmation,
            attempt_reference=fixture.confirmation,
            attempt_path=tmp_path / "attempt.yaml",
            journal_path=tmp_path / "journal.jsonl",
        )
    )
    monkeypatch.setitem(
        benchmark.__globals__, "execute_benchmark_confirmation", confirm
    )
    result = benchmark(tmp_path, candidate_path, benchmark_path)
    assert result.status == "passed"
    assert confirm.call_count == 1
    assert sum(call.args[0] == candidate for call in run_check.call_args_list) == 1
    assert sum(call.args[0] == confirmation for call in stage_check.call_args_list) == 1
    assert (
        verification.verify_benchmark_result(
            result.record, policy=POLICY, fetcher=fetch
        ).result
        == result.record
    )
    assert sum(call.args[0] == candidate for call in run_check.call_args_list) == 2
    assert sum(call.args[0] == confirmation for call in stage_check.call_args_list) == 2


def test_benchmark_public_verifier_remains_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check every public call and reject later corruption or a changed policy."""
    result, candidate, store = build_benchmark_fixture()
    run_check = Mock(wraps=verification.verify_run_result)
    stage_check = Mock(wraps=verification.verify_attempt_stages)
    monkeypatch.setattr(verification, "verify_run_result", run_check)
    monkeypatch.setattr(verification, "verify_attempt_stages", stage_check)
    for _ in range(2):
        verification.verify_benchmark_result(result, policy=POLICY, fetcher=store.fetch)
    confirmation = fetch_attempt(store, result.confirmation)
    assert sum(call.args[0] == candidate for call in run_check.call_args_list) == 2
    assert sum(call.args[0] == confirmation for call in stage_check.call_args_list) == 2
    with pytest.raises(VerificationError):
        verification.verify_benchmark_result(
            result,
            policy=VerificationPolicy(trusted_source_repositories=frozenset()),
            fetcher=store.fetch,
        )
    store.put(result.run.stored_at, b"corrupt")
    with pytest.raises(VerificationError, match="byte-count|SHA-256"):
        verification.verify_benchmark_result(result, policy=POLICY, fetcher=store.fetch)


def test_benchmark_rejects_changed_confirmation_after_stage_verification() -> None:
    """Bind reused stage checks to the exact confirmation attempt read back."""
    result, candidate, store = build_benchmark_fixture()
    checked_run = verification.verify_run_result(
        candidate, policy=POLICY, fetcher=store.fetch
    )
    confirmation = fetch_attempt(store, result.confirmation)
    stages = verification.verify_attempt_stages(
        confirmation,
        checked_run.plan.run,
        checked_run.plan.stages,
        require_complete=True,
        policy=POLICY,
        fetcher=store.fetch,
    )
    changed = confirmation.model_copy(
        update={"attempt_id": confirmation.attempt_id + 1}
    )
    with pytest.raises(VerificationError, match="verified confirmation differs"):
        verification.verify_benchmark_evidence(
            result,
            checked_run,
            policy=POLICY,
            fetcher=store.fetch,
            verified_confirmation=(changed, stages),
        )


@pytest.mark.parametrize("change", ("failed", "comparator", "missing"))
def test_benchmark_metric_results_require_consistent_evidence(change: str) -> None:
    """Reject failed, incompatible, or missing metric verification evidence."""
    spec = BenchmarkSpec(
        benchmark_id="holdout",
        eval_id="eval",
        test=_pointer("inputs/datasets/holdout/test.pointer.yaml"),
        splits={"split": _pointer("inputs/benchmarks/holdout/split.pointer.yaml")},
        metric_ids=("loss",),
    )
    candidate = {"loss": (_file("candidate.yaml"), _metric(0.2))}
    receipt = _metric(0.2)
    if change == "failed":
        receipt = receipt.model_copy(update={"passed": False})
    elif change == "comparator":
        receipt = receipt.model_copy(
            update={"comparator": FloatComparator(mode="absolute", tolerance=0.1)}
        )
    confirmation = (
        {} if change == "missing" else {"loss": (_file("confirmation.yaml"), receipt)}
    )
    with pytest.raises(VerificationError, match="benchmark.metrics"):
        benchmark_metric_results(spec, candidate, confirmation)


def test_benchmark_rejects_changed_metric_criterion() -> None:
    """Check threshold outcomes rather than trusting the assembled result."""
    result, _, store = build_benchmark_fixture()
    metric = result.metrics[0]
    assert metric.criterion is not None
    changed = metric.model_copy(
        update={"criterion": metric.criterion.model_copy(update={"passed": False})}
    )
    with pytest.raises(VerificationError, match="metric criterion result differs"):
        verification.verify_benchmark_result(
            result.model_copy(update={"metrics": (changed,)}),
            policy=POLICY,
            fetcher=store.fetch,
        )
