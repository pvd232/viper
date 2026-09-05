"""Construct resolved environments and stage documents after execution."""

from __future__ import annotations

from datetime import datetime

from ..artifacts import ResolvedArtifact
from ..http import ResolvedHttpRetrieval
from ..ids import InputName
from ..inputs import ResolvedInputRef
from ..references import ResolvedGitFileRef, ResolvedStageInvocationRef
from ..runtime import (
    EnvSpec,
    ExecutionContext,
    GCEEnvSpec,
    GCEHostContext,
    ResolvedGCEEnv,
    ResolvedLocalEnv,
    observe_execution,
    observe_python_env,
)
from ..stages import (
    DownloadSpec,
    ParameterizedSpec,
    ResolvedBuildSpec,
    ResolvedDownloadSpec,
    ResolvedEmbedSpec,
    ResolvedEvalSpec,
    ResolvedSpec,
    ResolvedTrainSpec,
)
from ._source import RunFetcher, resolve_git_file
from ._stage import StageProcessResult
from .errors import RunError
from ..reuse import ExecutedStageCompletion



def resolve_env(
    fetcher: RunFetcher,
    env: EnvSpec,
    process: StageProcessResult,
) -> ResolvedLocalEnv | ResolvedGCEEnv:
    """Resolve one requested env from child-observed runtime evidence."""
    if isinstance(env, GCEEnvSpec):
        host = process.execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE execution omitted its observed GCE host")
        return ResolvedGCEEnv(
            provisioning=host.provisioning,
            machine_type=host.machine_type,
            compute=env.compute,
            lockfile=resolve_git_file(fetcher, env.lockfile),
            python_env=process.python_env,
        )
    return ResolvedLocalEnv(
        compute=env.compute,
        lockfile=resolve_git_file(fetcher, env.lockfile),
        python_env=process.python_env,
    )


def resolve_runner_env(
    fetcher: RunFetcher,
    env: EnvSpec,
) -> tuple[ResolvedLocalEnv | ResolvedGCEEnv, ExecutionContext]:
    """Resolve the env observed by a runner-owned stage."""
    python_env = observe_python_env()
    if python_env != env.python_env:
        raise RunError("runner Python env differs from the stage request")
    execution_context = observe_execution(env)
    if isinstance(env, GCEEnvSpec):
        host = execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE download omitted its observed GCE host")
        resolved: ResolvedLocalEnv | ResolvedGCEEnv = ResolvedGCEEnv(
            provisioning=host.provisioning,
            machine_type=host.machine_type,
            compute=env.compute,
            lockfile=resolve_git_file(fetcher, env.lockfile),
            python_env=python_env,
        )
    else:
        resolved = ResolvedLocalEnv(
            compute=env.compute,
            lockfile=resolve_git_file(fetcher, env.lockfile),
            python_env=python_env,
        )
    return resolved, execution_context


def resolve_stage(
    stage: ParameterizedSpec,
    *,
    source: ResolvedGitFileRef,
    env: ResolvedLocalEnv | ResolvedGCEEnv,
    process: StageProcessResult,
    invocation: ResolvedStageInvocationRef,
    inputs: dict[InputName, ResolvedInputRef] | None,
    completed_at: datetime,
) -> ResolvedSpec:
    """Construct the resolved subtype for one completed project stage."""
    result = process
    common = {
        "spec": stage,
        "completion": ExecutedStageCompletion(
            source=source,
            env=env,
            execution_context=result.execution_context,
            startup=result.startup,
            invocation=invocation,
            command=result.command,
        ),
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
    return ResolvedEvalSpec(**common, inputs=inputs)


def resolve_download_stage(
    stage: DownloadSpec,
    *,
    env: ResolvedLocalEnv | ResolvedGCEEnv,
    execution_context: ExecutionContext,
    artifacts: dict[str, ResolvedArtifact],
    retrievals: dict[InputName, ResolvedHttpRetrieval],
    completed_at: datetime,
) -> ResolvedDownloadSpec:
    """Construct one runner-owned resolved download record."""
    return ResolvedDownloadSpec(
        spec=stage,
        env=env,
        execution_context=execution_context,
        artifacts=artifacts,
        retrievals=retrievals,
        completed_at=completed_at,
    )
