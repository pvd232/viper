"""Tests for benchmark execution models and the typed API operation."""

from pathlib import Path

import pytest

from tests.test_verification_acceptance import build_benchmark_fixture
from viper.api import ExecuteBenchmarkRequest
from viper.api import execute_benchmark as execute_benchmark_application
from viper.benchmark import BenchmarkSpec
from viper.execution import BenchmarkExecutionResult
from viper.references import (
    LocalFileRef,
    ResolvedBenchmarkResultRef,
)
from viper.serialization import parse_yaml_bytes


def test_benchmark_spec_counts_candidate_and_confirmation() -> None:
    """Expose the fixed two-execution contract through its public field."""
    result, _, store = build_benchmark_fixture()
    benchmark = BenchmarkSpec.model_validate(
        parse_yaml_bytes(store.fetch(result.benchmark.stored_at))
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


def test_api_returns_the_verified_benchmark_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the result and canonical path produced by the benchmark executor."""
    result, _, _ = build_benchmark_fixture()
    result_path = tmp_path / "benchmark.result.yaml"
    monkeypatch.setattr(
        "viper._api.handlers.execute_benchmark_run",
        lambda *args, **kwargs: BenchmarkExecutionResult(
            result=result,
            result_path=result_path,
        ),
    )

    response = execute_benchmark_application(
        ExecuteBenchmarkRequest(
            resolved_run=tmp_path / "resolved.yaml",
            benchmark_spec=tmp_path / "benchmark.spec.yaml",
            repository_root=tmp_path,
        )
    )

    assert response.result == result
    assert response.result_path == result_path
