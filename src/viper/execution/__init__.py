"""Execute frozen runs, retries, and benchmark confirmations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._benchmark import BenchmarkExecutionResult
    from ._results import RunResult


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Execute one frozen run plan and verify its terminal result."""
    from ._run import run as execute

    return execute(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
    )


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Append one attempt to a failed frozen run and verify its result."""
    from ._run import retry as execute

    return execute(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
    )


def benchmark(
    repository_root: Path,
    resolved_run_path: Path,
    benchmark_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> BenchmarkExecutionResult:
    """Execute and verify one independent benchmark confirmation."""
    from ._benchmark import benchmark as execute

    return execute(
        repository_root,
        resolved_run_path,
        benchmark_spec_path,
        timeout_seconds=timeout_seconds,
    )


__all__ = ["benchmark", "retry", "run"]
