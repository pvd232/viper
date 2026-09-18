"""Execute, publish, and verify one frozen run plan on a trusted local host."""

from __future__ import annotations

from pathlib import Path

from ..references import ResolvedRunSpecRef
from ._attempt import execute_attempt
from .results import ConfirmationRunResult, RunResult


def run(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
    retry: bool = False,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> RunResult:
    """Execute one plan with the caller's explicit prior-run source trust."""
    result = execute_attempt(
        repository_root,
        run_spec_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
        retry=retry,
        purpose="run",
        trusted_source_repositories=trusted_source_repositories,
    )
    assert isinstance(result, RunResult)
    return result


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> RunResult:
    """Retry one plan with the caller's explicit prior-run source trust."""
    return run(
        repository_root,
        run_spec_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
        retry=True,
        trusted_source_repositories=trusted_source_repositories,
    )


def execute_benchmark_confirmation(
    repository_root: Path,
    run_spec_path: Path,
    *,
    plan: ResolvedRunSpecRef | None = None,
    timeout_seconds: float | None = None,
) -> ConfirmationRunResult:
    """Execute one independent confirmation of a successful frozen run."""
    result = execute_attempt(
        repository_root,
        run_spec_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
        purpose="benchmark_confirmation",
    )
    assert isinstance(result, ConfirmationRunResult)
    return result
