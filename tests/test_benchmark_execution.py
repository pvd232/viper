"""Tests for benchmark execution models and the typed API operation."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.git_repository import run_git
from viper.api import ExecuteBenchmarkRequest
from viper.api import execute_benchmark as execute_benchmark_application
from viper.benchmark import (
    ArtifactComparisonReceipt,
    BenchmarkResult,
    BenchmarkSpec,
    MetricCriterion,
)
from viper.execution._benchmark import _benchmark_metric_results, _benchmark_status
from viper.execution.results import BenchmarkExecutionResult
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


def _file(path: str) -> ResolvedFileRef:
    """Build one local file reference for a focused benchmark test."""
    return ResolvedFileRef(
        sha256="a" * 64,
        bytes=1,
        stored_at=LocalFileRef(commit="b" * 64, path=path),
    )


def _pointer(path: str) -> ResolvedArtifactPointerRef:
    """Build one resolved benchmark-input pointer."""
    return ResolvedArtifactPointerRef(
        sha256="a" * 64,
        bytes=1,
        stored_at=LocalFileRef(commit="b" * 64, path=path),
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
            store=".viper/store",
            commit="b" * 64,
            path="experiments/e/runs/v/01ARZ3NDEKTSV4RRFFQ69G5FAV/benchmark.result.yaml",
        ),
    )

    assert reference.stored_at.kind == "local"


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

    metrics = _benchmark_metric_results(benchmark, candidate, confirmation)

    assert tuple(metric.metric_id for metric in metrics) == benchmark.metric_ids
    assert metrics[0].criterion is None
    assert metrics[1].criterion is not None
    assert metrics[1].criterion.passed
    assert (
        _benchmark_status(
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
    metrics = _benchmark_metric_results(verified, files, files)
    artifacts = (ArtifactComparisonReceipt.model_construct(passed=True),)

    assert _benchmark_status(verified, artifacts, metrics) == "verified"

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
    failed_threshold = _benchmark_metric_results(threshold, files, files)
    assert _benchmark_status(threshold, artifacts, failed_threshold) == "failed"

    mismatch = _benchmark_metric_results(
        verified,
        files,
        {"accuracy": (_file("confirmation.yaml"), _metric(0.94))},
    )
    assert _benchmark_status(verified, artifacts, mismatch) == "failed"


def test_api_returns_the_verified_benchmark_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the result and canonical path produced by the benchmark executor."""
    (tmp_path / "viper.toml").write_text(
        "[project]\nschema_version = 1\n",
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
    monkeypatch.setattr(
        "viper.api.execute_benchmark_run",
        lambda *args, **kwargs: BenchmarkExecutionResult(
            result=result,
            result_path=result_path,
        ),
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
