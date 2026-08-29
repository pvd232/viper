"""Construct resolved environments and stage documents after execution."""

from __future__ import annotations

from datetime import datetime

from ..http import ResolvedHttpRetrieval
from ..ids import InputName
from ..inputs import ResolvedInputRef
from ..references import ResolvedGitFileRef, ResolvedStageInvocationRef
from ..runtime import (
    EnvironmentSpec,
    GCEEnvironmentSpec,
    GCEHostContext,
    ResolvedGCEEnvironment,
    ResolvedLocalEnvironment,
)
from ..stages import (
    BaseSpec,
    DownloadSpec,
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


def resolve_stage(
    stage: BaseSpec,
    *,
    source: ResolvedGitFileRef,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    process: StageProcessResult,
    invocation: ResolvedStageInvocationRef,
    inputs: dict[InputName, ResolvedInputRef] | None,
    retrievals: dict[InputName, ResolvedHttpRetrieval] | None,
    completed_at: datetime,
) -> ResolvedSpec:
    """Construct the concrete resolved-spec subtype for one completed stage."""
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
    if isinstance(stage, DownloadSpec):
        assert retrievals is not None
        return ResolvedDownloadSpec(**common, retrievals=retrievals)
    assert inputs is not None
    if stage.kind == "build":
        return ResolvedBuildSpec(**common, inputs=inputs)
    if stage.kind == "embed":
        return ResolvedEmbedSpec(**common, inputs=inputs)
    if stage.kind == "train":
        return ResolvedTrainSpec(**common, inputs=inputs)
    return ResolvedEvaluateSpec(**common, inputs=inputs)
