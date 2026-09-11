"""Execute frozen runs, retries, and benchmark confirmations."""

from __future__ import annotations

from pathlib import Path

from ..authoring import RunPlanDraft, freeze_run_plan
from ..repository import resolve_root
from ..storage import ViperCloudClient
from ._batch import run_many as _run_many
from ._benchmark import benchmark as _benchmark
from ._restore import restore
from ._run import retry as _retry
from ._run import run as _run
from .results import BenchmarkExecutionResult, ExperimentExecutionResult, RunResult


def run(
    plan: RunPlanDraft | Path,
    *,
    repository_root: Path | None = None,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Execute a Python draft or a saved run specification.

    Discover the workspace from the current directory unless a root is supplied.
    A draft is frozen before execution; a Path selects an existing RunSpec.
    Return a verified RunResult with direct status and path attributes.
    Execution and verification failures raise and leave attempt evidence for
    inspection. timeout_seconds bounds each stage or metric worker invocation.
    """
    repository_root = resolve_root(repository_root)
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
    """Append an attempt to the same frozen plan and verify its result.

    Earlier attempts remain available. Source or config changes require a new
    plan. The return value and worker timeout follow run().
    """
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
    """Execute an independent confirmation and compare it with a completed run.

    Return the saved comparison through record, reference, path, and status.
    A failed comparison returns status="failed"; an execution or verification
    error raises an exception. The benchmark specification must match the plan.
    """
    return _benchmark(
        repository_root,
        resolved_run_path,
        benchmark_spec_path,
        timeout_seconds=timeout_seconds,
        cloud_client=cloud_client,
    )


def run_many(
    repository_root: Path,
    run_spec_paths: tuple[Path | RunPlanDraft, ...],
    *,
    max_concurrency: int = 1,
    timeout_seconds: float | None = None,
    stop_on_failure: bool = False,
) -> ExperimentExecutionResult:
    """Execute drafts or Git-committed plans and return outcomes in input order.

    Drafts are frozen before scheduling and retain their immutable store
    references. Paths select plan files committed to the workspace repository.

    Load all plans before scheduling. max_concurrency limits active runs;
    stop_on_failure leaves unscheduled runs marked as skipped after a failure.
    Already-started runs finish. Expected execution failures are captured in
    each entry's failure field. Invalid plan files raise before execution.
    """
    return _run_many(
        repository_root,
        run_spec_paths,
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
        stop_on_failure=stop_on_failure,
    )


__all__ = [
    "benchmark",
    "retry",
    "restore",
    "run",
    "run_many",
]
