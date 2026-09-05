"""Execute frozen runs, retries, and benchmark confirmations."""

from __future__ import annotations

from pathlib import Path

from ..authoring import RunPlanDraft, freeze_run_plan
from ..storage import ViperCloudClient
from ._benchmark import benchmark as _benchmark
from ._run import retry as _retry
from ._run import run as _run
from .results import BenchmarkExecutionResult, RunResult


def run(
    repository_root: Path,
    plan: RunPlanDraft | Path,
    *,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Compile one authored plan, then execute its immutable files."""
    if isinstance(plan, Path):
        return _run(
            repository_root,
            plan,
            timeout_seconds=timeout_seconds,
            cloud_client=cloud_client,
        )
    frozen = freeze_run_plan(
        repository_root,
        plan,
        cloud_client=cloud_client,
    )
    run_path = repository_root.resolve() / frozen.reference.stored_at.path
    return _run(
        repository_root,
        run_path,
        plan=frozen.reference,
        timeout_seconds=timeout_seconds,
        cloud_client=cloud_client,
    )


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Append one attempt to a failed frozen run and verify its result."""
    return _retry(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        cloud_client=cloud_client,
    )


def benchmark(
    repository_root: Path,
    resolved_run_path: Path,
    benchmark_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> BenchmarkExecutionResult:
    """Execute and verify one independent benchmark confirmation."""
    return _benchmark(
        repository_root,
        resolved_run_path,
        benchmark_spec_path,
        timeout_seconds=timeout_seconds,
        cloud_client=cloud_client,
    )


__all__ = [
    "benchmark",
    "retry",
    "run",
]
