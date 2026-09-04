"""Execute frozen runs, retries, and benchmark confirmations."""

from __future__ import annotations

import importlib
from pathlib import Path

from .results import BenchmarkExecutionResult, RunResult

# Parameter validation imports execution._process while viper is starting. Loading
# the run modules here would send that import back through parameter validation.


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Execute one frozen run plan and verify its terminal result."""
    return importlib.import_module("._run", __name__).run(
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
    return importlib.import_module("._run", __name__).retry(
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
    return importlib.import_module("._benchmark", __name__).benchmark(
        repository_root,
        resolved_run_path,
        benchmark_spec_path,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "benchmark",
    "retry",
    "run",
]
