"""Execute, publish, and verify one frozen run plan on a trusted local host."""

from __future__ import annotations

from pathlib import Path

from ..references import ResolvedRunSpecRef
from ..storage import ViperCloudClient
from ._attempt import execute_attempt
from .results import ConfirmationRunResult, RunResult


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
    retry: bool = False,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Execute one frozen plan and verify its terminal resolved run."""
    result = execute_attempt(
        repository_root,
        run_spec_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
        retry=retry,
        purpose="run",
        cloud_client=cloud_client,
    )
    assert isinstance(result, RunResult)
    return result


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Append one attempt to a failed frozen run and verify its result."""
    return run(
        repository_root,
        run_spec_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
        retry=True,
        cloud_client=cloud_client,
    )


def execute_benchmark_confirmation(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> ConfirmationRunResult:
    """Execute one independent confirmation of a successful frozen run."""
    result = execute_attempt(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        purpose="benchmark_confirmation",
        cloud_client=cloud_client,
    )
    assert isinstance(result, ConfirmationRunResult)
    return result
