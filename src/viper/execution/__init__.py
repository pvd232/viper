"""Execute frozen runs, retries, and benchmark confirmations."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import overload

import viper._subprocess as subprocess

from .._schema import SHA256
from ..authoring import RunPlanDraft, freeze_run_plan
from ..references import ResolvedFileRef, ResolvedRunRef, ResolvedStageRef
from ..repository import resolve_root
from ..storage import RunPromotionPolicy, TransferLimits, ViperCloudDestination
from ._batch import run_many as _run_many
from ._benchmark import benchmark as _benchmark
from ._export import export_run as _export_run
from ._export import verify_run_bundle as _verify_run_bundle
from ._promotion import promote_run_to_cloud as _promote_run_to_cloud
from ._restore import resolve_run_reference, restore
from ._run import retry as _retry
from ._run import run as _run
from .errors import RunPromotionError
from .results import (
    BenchmarkExecutionResult,
    ExperimentExecutionResult,
    RunExportResult,
    RunResult,
)


@overload
def promote_run_to_cloud(
    repository_root: Path,
    source: Path | ResolvedRunRef,
    destination: ViperCloudDestination,
) -> ResolvedRunRef: ...


@overload
def promote_run_to_cloud(
    repository_root: Path,
    source: Path | ResolvedRunRef | tuple[ResolvedRunRef, ...],
    destination: ViperCloudDestination,
    *,
    policy: RunPromotionPolicy,
    limits: TransferLimits,
    required_files: Mapping[str, ResolvedFileRef] | None = None,
    supporting_roots: tuple[
        ResolvedRunRef | ResolvedStageRef | ResolvedFileRef, ...
    ] = (),
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> tuple[ResolvedRunRef, ...]: ...


def promote_run_to_cloud(
    repository_root: Path,
    source: Path | ResolvedRunRef | tuple[ResolvedRunRef, ...],
    destination: ViperCloudDestination,
    *,
    policy: RunPromotionPolicy | None = None,
    limits: TransferLimits | None = None,
    required_files: Mapping[str, ResolvedFileRef] | None = None,
    supporting_roots: tuple[
        ResolvedRunRef | ResolvedStageRef | ResolvedFileRef, ...
    ] = (),
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> ResolvedRunRef | tuple[ResolvedRunRef, ...]:
    """Publish saved runs and return their additional cloud references.

    The three-argument call publishes one local run through workspace settings.
    policy selects additional hosts; limits bounds the separate copy process.
    That form accepts several roots, checks required_files, and returns references
    in host order and then source-root order. Original publications and workspace
    settings remain unchanged. supporting_roots includes separately recorded source
    builds and files. Progress and checks are saved under .viper/promotion.
    """
    root = repository_root.resolve(strict=True)
    if policy is None:
        if (
            isinstance(source, tuple)
            or limits is not None
            or required_files is not None
            or supporting_roots
        ):
            raise ValueError(
                "multiple roots and copy limits require a promotion policy"
            )
        return _promote_run_to_cloud(root, source, destination)
    if limits is None:
        raise ValueError("additional graph publications require transfer limits")
    roots = (
        source if isinstance(source, tuple) else (resolve_run_reference(root, source),)
    )
    request = {
        "repository_root": str(root),
        "inventory": {
            "roots": [reference.model_dump(mode="json") for reference in roots],
            "supporting_roots": [
                reference.model_dump(mode="json") for reference in supporting_roots
            ],
            "required_files": {
                role: reference.model_dump(mode="json")
                for role, reference in (required_files or {}).items()
            },
        },
        "policy": policy.model_dump(mode="json"),
        "destination": destination.model_dump(mode="json"),
        "limits": limits.model_dump(mode="json"),
        "trusted_source_repositories": sorted(trusted_source_repositories),
    }
    package_root = str(Path(__file__).resolve().parents[2])
    environment = dict(os.environ, HF_HUB_DISABLE_XET="1", HF_HUB_DISABLE_TELEMETRY="1")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (package_root, environment.get("PYTHONPATH")))
    )
    completed = subprocess.run(
        (sys.executable, "-B", "-m", "viper.execution._promotion_worker"),
        cwd=root,
        env=environment,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        completed.check_returncode()
    except subprocess.CalledProcessError as error:
        raise RunPromotionError(
            f"additional publication worker failed: {completed.stderr.strip() or error}"
        ) from error
    try:
        response = json.loads(completed.stdout.splitlines()[-1])
        published = []
        if len(response["publications"]) != len(policy.hosts):
            raise ValueError("publication host count changed")
        for host, result in zip(policy.hosts, response["publications"], strict=True):
            if result["host"] != host.model_dump(mode="json"):
                raise ValueError("publication host changed")
            if result["source_roots"] != request["inventory"]["roots"]:
                raise ValueError("publication roots changed")
            if not result["passed"] or len(result["destination_roots"]) != len(roots):
                raise ValueError("publication is incomplete")
            published.extend(
                ResolvedRunRef.model_validate(item)
                for item in result["destination_roots"]
            )
        return tuple(published)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RunPromotionError("publication result is invalid") from error


def export_run(
    repository_root: Path,
    resolved_run_path: Path,
    output: Path,
    *,
    trusted_source_repositories: frozenset[str],
) -> RunExportResult:
    """Write a complete verified-run evidence graph to a portable directory."""
    return _export_run(
        repository_root,
        resolved_run_path,
        output,
        trusted_source_repositories=trusted_source_repositories,
    )


def verify_run_bundle(
    bundle_path: Path,
    *,
    trusted_source_repositories: frozenset[str],
    expected_manifest_sha256: SHA256 | None = None,
) -> RunExportResult:
    """Verify one exported run bundle without its source workspace or store."""
    return _verify_run_bundle(
        bundle_path,
        trusted_source_repositories=trusted_source_repositories,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def run(
    plan: RunPlanDraft | Path,
    *,
    repository_root: Path | None = None,
    timeout_seconds: float | None = None,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> RunResult:
    """Execute a Python draft or a saved run specification.

    Discover the workspace from the current directory unless a root is supplied.
    A draft is frozen before execution; a Path selects an existing RunSpec.
    Return a verified RunResult with direct status and path attributes.
    Execution and verification failures raise and leave attempt evidence for
    inspection. timeout_seconds bounds each stage or metric worker invocation.
    trusted_source_repositories approves additional repositories whose artifact
    loaders must run while verifying prior-run inputs.
    """
    repository_root = resolve_root(repository_root)
    if isinstance(plan, Path):
        return _run(
            repository_root,
            plan,
            timeout_seconds=timeout_seconds,
            trusted_source_repositories=trusted_source_repositories,
        )
    frozen = freeze_run_plan(
        repository_root,
        plan,
    )
    run_path = repository_root.resolve() / frozen.reference.stored_at.path
    return _run(
        repository_root,
        run_path,
        plan=frozen.reference,
        timeout_seconds=timeout_seconds,
        trusted_source_repositories=trusted_source_repositories,
    )


def retry(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> RunResult:
    """Append an attempt to the same frozen plan and verify its result.

    Earlier attempts remain available. Source or config changes require a new
    plan. The return value, worker timeout, and explicit source trust follow
    run().
    """
    return _retry(
        repository_root,
        run_spec_path,
        timeout_seconds=timeout_seconds,
        trusted_source_repositories=trusted_source_repositories,
    )


def benchmark(
    repository_root: Path,
    resolved_run_path: Path,
    benchmark_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
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
    "export_run",
    "promote_run_to_cloud",
    "resolve_run_reference",
    "retry",
    "restore",
    "run",
    "run_many",
    "verify_run_bundle",
]
