"""Author canonical experiment, variant, benchmark, stage, and run-plan files."""

from __future__ import annotations

import hashlib
import inspect
import os
import re
import string
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter

from . import params
from ._schema import ArtifactName, BenchmarkId, DataRole, RepoRelPath, RNGSeed
from .artifacts import (
    ArtifactDraft,
    ArtifactLoaderRef,
    ArtifactSpec,
    BundleArtifactDraft,
    BundleArtifactSpec,
    SingleFileArtifactDraft,
    SingleFileArtifactSpec,
    StageArtifactRef,
)
from .benchmark import BenchmarkSpec
from .experiments import (
    ExperimentSpec,
    VariantSpec,
)
from .http import (
    BuiltinHttpImplementationSpec,
    HttpDefinition,
    HttpDraft,
    HttpImplementationRef,
    HttpImplementationSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
    ProjectHttpImplementationSpec,
)
from .ids import EvalId, ExperimentId, InputName, ReplicateId, RunId, StageId, VariantId
from .inputs import ExternalInputRef, FutureInputRef, InputRef, LocalSource
from .metrics import (
    MetricDraft,
    MetricObjectiveDraft,
    MetricObjectiveSpec,
    metric_definition,
)
from .params import ParameterModelRef
from .project import resolve_path, resolve_root
from .references import GitSource, ResolvedRunRef
from .runs import (
    RunSpec,
    RunStageRef,
)
from .runtime import EnvSpec, ReproducibilitySpec
from .serialization import parse_yaml_bytes, serialize_document
from .stages import (
    BuildSpec,
    Context,
    DownloadSpec,
    EmbedSpec,
    EvalSpec,
    Spec,
    StageImplementationRef,
    TrainSpec,
    stage_definition,
)

HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
UrlValue = str | int | float | bool


def _freeze_artifact(
    root: Path,
    run_root: str,
    draft: ArtifactDraft,
) -> ArtifactSpec:
    """Freeze one artifact loader and prefix its run-relative path."""
    source = inspect.getsourcefile(draft.loader)
    if source is None:
        raise ValueError("artifact loader has no Python source")
    path = Path(source).resolve()
    if not path.is_relative_to(root):
        raise ValueError("artifact loader is outside the project root")
    raw = path.read_bytes()
    loader = ArtifactLoaderRef(
        path=path.relative_to(root).as_posix(),
        symbol=draft.loader.__name__,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
    fields = {
        "path": f"{run_root}/{draft.path}",
        "loader": loader,
        "data_role": draft.data_role,
    }
    if isinstance(draft, BundleArtifactDraft):
        return BundleArtifactSpec(**fields)
    return SingleFileArtifactSpec(**fields)


def _freeze_http(root: Path, draft: HttpDraft) -> HttpImplementationSpec:
    """Freeze one built-in selection or decorated project HTTP callable."""
    if isinstance(draft, BuiltinHttpImplementationSpec):
        return draft
    definition = getattr(draft.implementation, "__viper_http__", None)
    if not isinstance(definition, HttpDefinition):
        raise ValueError("HTTP callable lacks a VIPER decorator")
    source = inspect.getsourcefile(draft.implementation)
    parameter_source = inspect.getsourcefile(definition.parameter_model)
    if source is None or parameter_source is None:
        raise ValueError("HTTP callable or parameter model has no Python source")
    implementation_path = Path(source).resolve()
    parameter_path = Path(parameter_source).resolve()
    if not implementation_path.is_relative_to(root):
        raise ValueError("HTTP callable is outside the project root")
    if not parameter_path.is_relative_to(root):
        raise ValueError("HTTP parameter model is outside the project root")
    implementation_raw = implementation_path.read_bytes()
    parameter_raw = parameter_path.read_bytes()
    return ProjectHttpImplementationSpec(
        id=definition.id,
        implementation=HttpImplementationRef(
            path=implementation_path.relative_to(root).as_posix(),
            symbol=draft.implementation.__name__,
            sha256=hashlib.sha256(implementation_raw).hexdigest(),
            bytes=len(implementation_raw),
        ),
        parameter_model=ParameterModelRef(
            owner="project",
            path=parameter_path.relative_to(root).as_posix(),
            symbol=definition.parameter_model.__name__,
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        ),
        params=draft.params,
        executables=definition.executables,
    )


@dataclass(frozen=True)
class StageDraftArtifactRef:
    """Select one artifact produced by an in-memory stage draft."""

    producer: StageDraft
    artifact_name: ArtifactName


class ExternalInputDraft(BaseModel):
    """Select one repository file as a future stage input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RepoRelPath
    data_role: DataRole


class RunArtifactDraft(BaseModel):
    """Select one artifact from a completed run for later pointer freezing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    artifact: StageArtifactRef
    path: RepoRelPath
    data_role: DataRole


StageInputDraft = ExternalInputDraft | RunArtifactDraft | StageDraftArtifactRef


class BaseSpecDraft(BaseModel):
    """Hold fields shared by every Python-authored stage."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    kind: str
    artifacts: dict[ArtifactName, ArtifactDraft] = Field(min_length=1)
    env: EnvSpec | None = None


class ParameterizedSpecDraft(BaseSpecDraft):
    """Hold one decorated project stage and its parameter values."""

    implementation: Callable[[Context[Any]], None]
    params: params.ParameterSet
    metrics: tuple[MetricDraft[Any], ...] = ()


class DownloadSpecDraft(BaseSpecDraft):
    """Hold runner-owned HTTP requests and their output artifacts."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpDraft = Field(default_factory=BuiltinHttpImplementationSpec)
    policy: HttpRetrievalPolicy


class InternalSpecDraft(ParameterizedSpecDraft):
    """Hold a project stage that consumes authored inputs."""

    inputs: dict[InputName, StageInputDraft] = Field(min_length=1)


class BuildSpecDraft(InternalSpecDraft):
    """Hold one project-defined prior builder."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: params.Build  # pyright: ignore[reportIncompatibleVariableOverride]


class EmbedSpecDraft(InternalSpecDraft):
    """Hold one configured embedding stage."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: params.Embed  # pyright: ignore[reportIncompatibleVariableOverride]
    objective: MetricObjectiveDraft | None = None


class TrainSpecDraft(InternalSpecDraft):
    """Hold one configured training stage and required objective."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: params.Train  # pyright: ignore[reportIncompatibleVariableOverride]
    objective: MetricObjectiveDraft


class EvalSpecDraft(InternalSpecDraft):
    """Hold one configured evaluation stage and required objective."""

    kind: Literal["eval"] = "eval"  # pyright: ignore[reportIncompatibleVariableOverride]
    eval_id: EvalId
    params: params.Eval  # pyright: ignore[reportIncompatibleVariableOverride]
    objective: MetricObjectiveDraft
    split_inputs: tuple[InputName, ...] = Field(min_length=1)


StageSpecDraft = Annotated[
    DownloadSpecDraft
    | BuildSpecDraft
    | EmbedSpecDraft
    | TrainSpecDraft
    | EvalSpecDraft,
    Field(discriminator="kind"),
]


class StageDraft(BaseModel):
    """Hold one validated Python stage declaration before freezing."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    spec: StageSpecDraft

    @property
    def artifacts(self) -> dict[ArtifactName, StageDraftArtifactRef]:
        """Return opaque handles for every artifact produced by this stage."""
        return {
            name: StageDraftArtifactRef(producer=self, artifact_name=name)
            for name in self.spec.artifacts
        }


class RunPlanDraft(BaseModel):
    """Collect run-level and Python stage selections before freezing."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None
    seed: RNGSeed
    source: GitSource
    env: EnvSpec
    reproducibility: ReproducibilitySpec
    stages: dict[StageId, StageDraft] = Field(min_length=1)
    estimator: StageDraftArtifactRef


class FrozenPlanFiles(BaseModel):
    """Return the validated run plan and every file written for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunSpec
    files: tuple[Path, ...]


def expand_http_url(
    template: str,
    *,
    path_values: Mapping[str, UrlValue] | None = None,
    query_values: Mapping[str, UrlValue] | None = None,
) -> HttpUrl:
    """Expand path fields and freeze one normalized, ordered HTTP URL."""
    components = urlsplit(template)
    if components.scheme not in {"http", "https"} or components.hostname is None:
        raise ValueError("HTTP URL template requires an HTTP origin")
    if components.username is not None or components.password is not None:
        raise ValueError("HTTP URL template must not contain user information")
    if components.fragment:
        raise ValueError("HTTP URL template must not contain a fragment")
    if any(
        "{" in value or "}" in value for value in (components.netloc, components.query)
    ):
        raise ValueError("HTTP URL fields are permitted only in the path")

    supplied_paths = {} if path_values is None else dict(path_values)
    expected_paths: set[str] = set()
    rendered_path: list[str] = []
    formatter = string.Formatter()
    for literal, field_name, format_spec, conversion in formatter.parse(
        components.path
    ):
        rendered_path.append(literal)
        if field_name is None:
            continue
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name) is None
            or format_spec
            or conversion is not None
        ):
            raise ValueError("HTTP path fields must be simple identifiers")
        if field_name not in supplied_paths:
            raise ValueError(f"HTTP path field {field_name!r} has no value")
        expected_paths.add(field_name)
        rendered_path.append(quote(str(supplied_paths[field_name]), safe=""))
    if set(supplied_paths) != expected_paths:
        raise ValueError("HTTP path values contain an unused field")

    query = list(parse_qsl(components.query, keep_blank_values=True))
    for name, value in sorted(({} if query_values is None else query_values).items()):
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        query.append((name, rendered))
    query.sort()
    expanded = urlunsplit(
        (
            components.scheme.lower(),
            components.netloc.lower(),
            "".join(rendered_path),
            urlencode(query),
            "",
        )
    )
    return HTTP_URL_ADAPTER.validate_python(expanded)


def _target_path(repository_root: Path, relative_path: str) -> Path:
    """Resolve one protocol path while keeping it beneath the repository root."""
    root = repository_root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("protocol output path escapes the repository root")
    return target


def _write_exact_file(path: Path, raw: bytes) -> None:
    """Write exact bytes atomically and preserve an identical existing file."""
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"refusing to replace a different file: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_experiment_spec(
    repository_root: Path,
    experiment: ExperimentSpec,
) -> Path:
    """Write one experiment definition at its canonical identity path."""
    target = _target_path(
        repository_root,
        f"experiments/{experiment.experiment_id}/spec.yaml",
    )
    _write_exact_file(target, serialize_document(experiment))
    return target


def write_variant_spec(repository_root: Path, variant: VariantSpec) -> Path:
    """Write one variant definition at its canonical experiment path."""
    target = _target_path(
        repository_root,
        (
            f"experiments/{variant.experiment_id}/variants/"
            f"{variant.variant_id}.spec.yaml"
        ),
    )
    _write_exact_file(target, serialize_document(variant))
    return target


def write_benchmark_spec(repository_root: Path, benchmark: BenchmarkSpec) -> Path:
    """Write one benchmark definition at its canonical identity path."""
    target = _target_path(
        repository_root,
        f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    _write_exact_file(target, serialize_document(benchmark))
    return target


def load_run_plan_draft(path: Path) -> RunPlanDraft:
    """Load one duplicate-key-safe run-plan draft."""
    return RunPlanDraft.model_validate(parse_yaml_bytes(path.read_bytes()))


def _freeze_input(
    root: Path,
    stages: Mapping[StageId, StageDraft],
    draft: StageInputDraft,
) -> InputRef:
    """Compile one local or same-run draft into a frozen input reference."""
    if isinstance(draft, ExternalInputDraft):
        path = resolve_path(root, draft.path, operation="read")
        return ExternalInputRef(
            source=LocalSource(path=path.relative_to(root).as_posix()),
            data_role=draft.data_role,
        )
    if isinstance(draft, StageDraftArtifactRef):
        owners = [name for name, stage in stages.items() if stage is draft.producer]
        if len(owners) != 1:
            raise ValueError("stage artifact must have one producer in this plan")
        return FutureInputRef(
            producer_stage_id=owners[0],
            name=draft.artifact_name,
        )
    raise ValueError("prior-run inputs are compiled in Master Phase 7")


def _freeze_stage(
    root: Path,
    run_root: str,
    stages: Mapping[StageId, StageDraft],
    draft: StageSpecDraft,
) -> Spec:
    """Freeze one Python stage draft into its protocol declaration."""
    artifacts: dict[ArtifactName, ArtifactSpec] = {
        name: _freeze_artifact(root, run_root, artifact)
        for name, artifact in draft.artifacts.items()
    }
    if isinstance(draft, DownloadSpecDraft):
        return DownloadSpec(
            artifacts=artifacts,
            env=draft.env,
            inputs=draft.inputs,
            http=_freeze_http(root, draft.http),
            policy=draft.policy,
        )
    definition = stage_definition(draft.implementation)
    source = inspect.getsourcefile(draft.implementation)
    parameter_source = inspect.getsourcefile(definition.parameter_model)
    if source is None or parameter_source is None:
        raise ValueError("stage callable or parameter model has no Python source")
    source_path = Path(source).resolve()
    parameter_path = Path(parameter_source).resolve()
    source_raw = source_path.read_bytes()
    parameter_raw = parameter_path.read_bytes()
    common = {
        "artifacts": artifacts,
        "env": draft.env,
        "implementation": StageImplementationRef(
            path=source_path.relative_to(root).as_posix(),
            symbol=draft.implementation.__name__,
            sha256=hashlib.sha256(source_raw).hexdigest(),
            bytes=len(source_raw),
        ),
        "parameter_model": ParameterModelRef(
            owner="project",
            path=parameter_path.relative_to(root).as_posix(),
            symbol=definition.parameter_model.__name__,
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        ),
        "params": draft.params,
        "inputs": {
            name: _freeze_input(root, stages, value)
            for name, value in draft.inputs.items()
        },
        "metric_ids": tuple(
            metric_definition(metric.implementation).metric_id
            for metric in draft.metrics
        ),
    }
    if isinstance(draft, BuildSpecDraft):
        return BuildSpec(**common)
    objective = (
        None
        if draft.objective is None
        else MetricObjectiveSpec(
            metric_id=metric_definition(
                draft.objective.metric.implementation
            ).metric_id,
            direction=draft.objective.direction,
        )
    )
    if isinstance(draft, EmbedSpecDraft):
        return EmbedSpec(**common, objective=objective)
    if objective is None:
        raise ValueError("train and eval stages require an objective")
    if isinstance(draft, TrainSpecDraft):
        return TrainSpec(**common, objective=objective)
    return EvalSpec(
        **common,
        objective=objective,
        eval_id=draft.eval_id,
        split_inputs=draft.split_inputs,
    )


def input(path: RepoRelPath, *, data_role: DataRole) -> ExternalInputDraft:
    """Select one repository file as a stage input."""
    return ExternalInputDraft(path=path, data_role=data_role)


def run_artifact(
    run: ResolvedRunRef,
    artifact: StageArtifactRef,
    *,
    path: RepoRelPath,
    data_role: DataRole,
) -> RunArtifactDraft:
    """Select one completed-run artifact for pointer compilation in Phase 7."""
    return RunArtifactDraft(run=run, artifact=artifact, path=path, data_role=data_role)


def download(
    *,
    inputs: dict[InputName, HttpRequestSpec],
    artifacts: Mapping[ArtifactName, SingleFileArtifactDraft],
    policy: HttpRetrievalPolicy,
    http: HttpDraft | None = None,
    env: EnvSpec | None = None,
) -> StageDraft:
    """Declare one runner-owned HTTP download stage."""
    selected_http = BuiltinHttpImplementationSpec() if http is None else http
    return StageDraft(
        spec=DownloadSpecDraft(
            inputs=inputs,
            artifacts=dict(artifacts),
            policy=policy,
            http=selected_http,
            env=env,
        )
    )


def stage(
    implementation: Callable[[Context[Any]], None],
    *,
    params: params.ParameterSet,
    inputs: dict[InputName, StageInputDraft],
    artifacts: dict[ArtifactName, ArtifactDraft],
    metrics: tuple[MetricDraft[Any], ...] = (),
    objective: MetricObjectiveDraft | None = None,
    env: EnvSpec | None = None,
    eval_id: EvalId | None = None,
    split_inputs: tuple[InputName, ...] = (),
) -> StageDraft:
    """Build the draft class selected by one decorated project callable."""
    definition = stage_definition(implementation)
    values = {
        "implementation": implementation,
        "params": params,
        "inputs": inputs,
        "artifacts": artifacts,
        "metrics": metrics,
        "env": env,
    }
    if definition.kind == "build":
        spec: StageSpecDraft = BuildSpecDraft(**values)
    elif definition.kind == "embed":
        spec = EmbedSpecDraft(**values, objective=objective)
    elif definition.kind == "train":
        if objective is None:
            raise ValueError("training stages require an objective")
        spec = TrainSpecDraft(**values, objective=objective)
    elif definition.kind == "eval":
        if objective is None or eval_id is None:
            raise ValueError("evaluation stages require an ID and objective")
        spec = EvalSpecDraft(
            **values, objective=objective, eval_id=eval_id, split_inputs=split_inputs
        )
    else:
        raise ValueError(f"unsupported stage kind: {definition.kind}")
    return StageDraft(spec=spec)


def freeze_run_plan(root: Path, draft: RunPlanDraft) -> FrozenPlanFiles:
    """Freeze Python stage drafts and write one exact run plan."""
    project_root = resolve_root(root)
    run_root = (
        f"experiments/{draft.experiment_id}/runs/{draft.variant_id}/{draft.run_id}"
    )
    files: list[tuple[Path, bytes]] = []
    stage_refs: list[RunStageRef] = []
    for stage_id, stage in draft.stages.items():
        spec = _freeze_stage(project_root, run_root, draft.stages, stage.spec)
        raw = serialize_document(spec)
        relative = f"{run_root}/stages/{stage_id}/spec.yaml"
        files.append((_target_path(project_root, relative), raw))
        stage_refs.append(
            RunStageRef(
                stage_id=stage_id,
                spec=relative,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )
    estimator_stage = next(
        (
            name
            for name, stage in draft.stages.items()
            if stage is draft.estimator.producer
        ),
        None,
    )
    if estimator_stage is None:
        raise ValueError("estimator producer is absent from the plan")
    run = RunSpec(
        run_id=draft.run_id,
        experiment_id=draft.experiment_id,
        variant_id=draft.variant_id,
        replicate_id=draft.replicate_id,
        benchmark_id=draft.benchmark_id,
        seed=draft.seed,
        source=draft.source,
        env=draft.env,
        reproducibility=draft.reproducibility,
        stages=tuple(stage_refs),
        estimator=StageArtifactRef(
            stage_id=estimator_stage,
            artifact_name=draft.estimator.artifact_name,
        ),
    )
    files.append(
        (_target_path(project_root, f"{run_root}/spec.yaml"), serialize_document(run))
    )
    for path, raw in files:
        _write_exact_file(path, raw)
    return FrozenPlanFiles(run=run, files=tuple(path for path, _ in files))
