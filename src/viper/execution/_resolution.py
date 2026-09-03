"""Construct resolved environments and stage documents after execution."""

from __future__ import annotations

from datetime import datetime

from ..artifacts import ResolvedArtifact
from ..http import ResolvedHttpRetrieval
from ..ids import InputName
from ..inputs import ResolvedInputRef
from ..references import ResolvedGitFileRef, ResolvedStageInvocationRef
from ..runtime import (
    EnvironmentSpec,
    ExecutionContext,
    GCEEnvironmentSpec,
    GCEHostContext,
    ResolvedGCEEnvironment,
    ResolvedLocalEnvironment,
    observe_execution,
    observe_python_environment,
)
from ..stages import (
    DownloadSpec,
    ParameterizedSpec,
    ResolvedBuildSpec,
    ResolvedDownloadSpec,
    ResolvedEmbedSpec,
    ResolvedEvaluateSpec,
    ResolvedSpec,
    ResolvedTrainSpec,
)
from ._source import RunFetcher, resolve_git_file
from ._stage import StageProcessResult
from .errors import RunError


def resolve_environment(
    fetcher: RunFetcher,
    environment: EnvironmentSpec,
    process: StageProcessResult,
) -> ResolvedLocalEnvironment | ResolvedGCEEnvironment:
    """Resolve one requested environment from child-observed runtime evidence."""
    if isinstance(environment, GCEEnvironmentSpec):
        host = process.execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE execution omitted its observed GCE host")
        return ResolvedGCEEnvironment(
            provisioning=host.provisioning,
            machine_type=host.machine_type,
            compute=environment.compute,
            lockfile=resolve_git_file(fetcher, environment.lockfile),
            python_environment=process.python_environment,
        )
    return ResolvedLocalEnvironment(
        compute=environment.compute,
        lockfile=resolve_git_file(fetcher, environment.lockfile),
        python_environment=process.python_environment,
    )


def resolve_runner_environment(
    fetcher: RunFetcher,
    environment: EnvironmentSpec,
) -> tuple[ResolvedLocalEnvironment | ResolvedGCEEnvironment, ExecutionContext]:
    """Resolve the environment observed by a runner-owned stage."""
    python_environment = observe_python_environment()
    if python_environment != environment.python_environment:
        raise RunError("runner Python environment differs from the stage request")
    execution_context = observe_execution(environment)
    if isinstance(environment, GCEEnvironmentSpec):
        host = execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE download omitted its observed GCE host")
        resolved: ResolvedLocalEnvironment | ResolvedGCEEnvironment = (
            ResolvedGCEEnvironment(
                provisioning=host.provisioning,
                machine_type=host.machine_type,
                compute=environment.compute,
                lockfile=resolve_git_file(fetcher, environment.lockfile),
                python_environment=python_environment,
            )
        )
    else:
        resolved = ResolvedLocalEnvironment(
            compute=environment.compute,
            lockfile=resolve_git_file(fetcher, environment.lockfile),
            python_environment=python_environment,
        )
    return resolved, execution_context


def resolve_stage(
    stage: ParameterizedSpec,
    *,
    source: ResolvedGitFileRef,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    process: StageProcessResult,
    invocation: ResolvedStageInvocationRef,
    inputs: dict[InputName, ResolvedInputRef] | None,
    completed_at: datetime,
) -> ResolvedSpec:
    """Construct the resolved subtype for one completed project stage."""
    result = process
    common = {
        "spec": stage,
        "source": source,
        "environment": environment,
        "execution_context": result.execution_context,
        "startup": result.startup,
        "invocation": invocation,
        "command": result.command,
        "artifacts": result.artifacts,
        "completed_at": completed_at,
    }
    assert inputs is not None
    if stage.kind == "build":
        return ResolvedBuildSpec(**common, inputs=inputs)
    if stage.kind == "embed":
        return ResolvedEmbedSpec(**common, inputs=inputs)
    if stage.kind == "train":
        return ResolvedTrainSpec(**common, inputs=inputs)
    return ResolvedEvaluateSpec(**common, inputs=inputs)


def resolve_download_stage(
    stage: DownloadSpec,
    *,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    execution_context: ExecutionContext,
    artifacts: dict[str, ResolvedArtifact],
    retrievals: dict[InputName, ResolvedHttpRetrieval],
    completed_at: datetime,
) -> ResolvedDownloadSpec:
    """Construct one runner-owned resolved download record."""
    return ResolvedDownloadSpec(
        spec=stage,
        environment=environment,
        execution_context=execution_context,
        artifacts=artifacts,
        retrievals=retrievals,
        completed_at=completed_at,
    )
