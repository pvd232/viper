"""Execute, publish, and verify one frozen run plan on a trusted local host."""

from __future__ import annotations

from pathlib import Path

from ._attempt import _execute_attempt
from ._errors import RunError as RunError
from ._results import ConfirmationRunResult as ConfirmationRunResult
from ._results import RunResult as RunResult
from ._source import RunFetcher as RunFetcher


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    retry: bool = False,
) -> RunResult:
    """Execute one frozen plan and verify its terminal resolved run."""
    result = _execute_attempt(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        retry=retry,
        purpose="run",
    )
    assert isinstance(result, RunResult)
    return result


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Append one attempt to a failed frozen run and verify its result."""
    return run(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        retry=True,
    )


def execute_benchmark_confirmation(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> ConfirmationRunResult:
    """Execute one independent confirmation of a successful frozen run."""
    result = _execute_attempt(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        purpose="benchmark_confirmation",
    )
    assert isinstance(result, ConfirmationRunResult)
    return result
