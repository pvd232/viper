"""Author canonical experiment, variant, benchmark, stage, and run-plan files."""

from __future__ import annotations

import hashlib
import inspect
import os
import re
import secrets
import string
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Never
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

from . import params
from ._schema import ArtifactName, DataRole, RepoRelPath, RNGSeed
from .artifacts import (
    ArtifactDraft,
    ArtifactLoaderRef,
    ArtifactPointer,
    ArtifactSpec,
    BundleArtifactDraft,
    BundleArtifactSpec,
    SingleFileArtifactDraft,
    SingleFileArtifactSpec,
    StageArtifactRef,
)
from .benchmark import BenchmarkSpec
from .experiments import (
    BuildVariantStageParams,
    EmbedVariantStageParams,
    EvalVariantStageParams,
    ExperimentSpec,
    FactorSpec,
    ReplicateSpec,
    TrainVariantStageParams,
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
from .ids import (
    EvalId,
    ExperimentId,
    FactorId,
    InputName,
    LevelId,
    ReplicateId,
    RunId,
    StageId,
    VariantId,
)
from .inputs import (
    ExternalInputRef,
    FutureInputRef,
    InputRef,
    LocalSource,
    StoredInputRef,
)
from .metrics import (
    MetricDraft,
    MetricImplementationRef,
    MetricObjectiveDraft,
    MetricObjectiveSpec,
    MetricSpec,
    metric_definition,
)
from .params import ParameterModelRef
from .project import resolve_path, resolve_root
from .references import (
    GitSource,
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
)
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
from .storage import LocalArtifactStore

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


class FactorDraft(BaseModel):
    """Hold the levels available for one experimental factor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    levels: tuple[LevelId, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_levels(self) -> FactorDraft:
        """Reject duplicate levels within one factor."""
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("factor levels must be unique")
        return self


class VariantDraft(BaseModel):
    """Hold one variant's factor levels, stages, and estimator."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    levels: dict[FactorId, LevelId]
    stages: dict[StageId, StageDraft] = Field(min_length=1)
    estimator: StageDraftArtifactRef

    @model_validator(mode="after")
    def validate_estimator(self) -> VariantDraft:
        """Require the estimator to come from this variant's stage graph."""
        if not any(stage is self.estimator.producer for stage in self.stages.values()):
            raise ValueError("estimator producer is absent from the variant")
        return self


class ReplicateDraft(BaseModel):
    """Hold the seed assigned to one experiment replicate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: RNGSeed


class ExperimentDraft(BaseModel):
    """Hold the reusable variants and replicates in one experiment."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    experiment_id: ExperimentId
    factors: dict[FactorId, FactorDraft] = Field(default_factory=dict)
    variants: dict[VariantId, VariantDraft] = Field(min_length=1)
    replicates: dict[ReplicateId, ReplicateDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_variants(self) -> ExperimentDraft:
        """Require every variant level to belong to its declared factor."""
        for variant in self.variants.values():
            if set(variant.levels) != set(self.factors):
                raise ValueError("variant factors differ from the experiment")
            for factor_id, level_id in variant.levels.items():
                if level_id not in self.factors[factor_id].levels:
                    raise ValueError("variant level is absent from its factor")
        return self


class RunPlanDraft(BaseModel):
    """Select one immutable experiment variant and replicate for execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment: ExperimentDraft
    variant: VariantId
    replicate: ReplicateId
    source: GitSource
    env: EnvSpec
    reproducibility: ReproducibilitySpec


class _FrozenDict(dict[Any, Any]):
    """Keep mapping behavior while rejecting every mutation."""

    def _reject(self, *args: object, **kwargs: object) -> Never:
        raise TypeError("frozen plan values cannot be changed")

    __delitem__ = _reject
    __ior__ = _reject
    __setitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject  # pyright: ignore[reportAssignmentType]
    update = _reject  # pyright: ignore[reportAssignmentType]


class _FrozenList(list[Any]):
    """Keep sequence behavior while rejecting every mutation."""

    def _reject(self, *args: object, **kwargs: object) -> Never:
        raise TypeError("frozen plan values cannot be changed")

    __delitem__ = _reject
    __iadd__ = _reject
    __imul__ = _reject
    __setitem__ = _reject
    append = _reject
    clear = _reject
    extend = _reject
    insert = _reject
    pop = _reject
    remove = _reject
    reverse = _reject
    sort = _reject  # pyright: ignore[reportAssignmentType]


_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_run_id() -> RunId:
    """Generate one sortable 128-bit run identity."""
    value = (time.time_ns() // 1_000_000 << 80) | int.from_bytes(
        secrets.token_bytes(10), "big"
    )
    encoded = "".join(
        _ULID_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5)
    )
    return TypeAdapter(RunId).validate_python(encoded)


def _deep_freeze(
    value: Any,
    memo: dict[int, Any] | None = None,
    active: set[int] | None = None,
) -> Any:
    """Replace nested mutable values while preserving shared references."""
    frozen = {} if memo is None else memo
    visiting = set() if active is None else active
    identity = id(value)
    if identity in frozen:
        return frozen[identity]
    if identity in visiting:
        raise TypeError("recursive plan values are not supported")
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        return value

    visiting.add(identity)
    try:
        if isinstance(value, StageDraftArtifactRef):
            result = StageDraftArtifactRef(
                producer=_deep_freeze(value.producer, frozen, visiting),
                artifact_name=value.artifact_name,
            )
        elif isinstance(value, BaseModel):
            updates = {
                name: _deep_freeze(field, frozen, visiting)
                for name, field in value.__dict__.items()
            }
            result = value.model_copy(update=updates)
        elif isinstance(value, dict):
            result = _FrozenDict(
                (
                    _deep_freeze(key, frozen, visiting),
                    _deep_freeze(item, frozen, visiting),
                )
                for key, item in value.items()
            )
        elif isinstance(value, list):
            result = _FrozenList(_deep_freeze(item, frozen, visiting) for item in value)
        elif isinstance(value, tuple):
            result = tuple(_deep_freeze(item, frozen, visiting) for item in value)
        elif isinstance(value, (set, frozenset)):
            result = frozenset(_deep_freeze(item, frozen, visiting) for item in value)
        else:
            result = value
    finally:
        visiting.remove(identity)
    frozen[identity] = result
    return result


def factor(*, levels: tuple[LevelId, ...]) -> FactorDraft:
    """Declare one experimental factor."""
    return FactorDraft(levels=levels)


def variant(
    *,
    levels: dict[FactorId, LevelId],
    stages: dict[StageId, StageDraft],
    estimator: StageDraftArtifactRef,
) -> VariantDraft:
    """Declare one reusable variant graph."""
    return VariantDraft(levels=levels, stages=stages, estimator=estimator)


def replicate(*, seed: RNGSeed) -> ReplicateDraft:
    """Declare one reproducible experiment replicate."""
    return ReplicateDraft(seed=seed)


def experiment(
    *,
    experiment_id: ExperimentId,
    variants: dict[VariantId, VariantDraft],
    replicates: dict[ReplicateId, ReplicateDraft],
    factors: dict[FactorId, FactorDraft] | None = None,
) -> ExperimentDraft:
    """Declare one experiment over reusable variants and replicates."""
    return ExperimentDraft(
        experiment_id=experiment_id,
        factors={} if factors is None else factors,
        variants=variants,
        replicates=replicates,
    )


def plan(
    *,
    experiment: ExperimentDraft,
    variant: VariantId,
    replicate: ReplicateId,
    source: GitSource,
    env: EnvSpec,
    reproducibility: ReproducibilitySpec,
) -> RunPlanDraft:
    """Create one identified plan detached from mutable caller values."""
    if variant not in experiment.variants:
        raise ValueError("variant is absent from the experiment")
    if replicate not in experiment.replicates:
        raise ValueError("replicate is absent from the experiment")
    draft = RunPlanDraft(
        run_id=_new_run_id(),
        experiment=experiment,
        variant=variant,
        replicate=replicate,
        source=source,
        env=env,
        reproducibility=reproducibility,
    )
    return _deep_freeze(draft)


class FrozenPlanFiles(BaseModel):
    """Return the validated run plan and every file written for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunSpec
    reference: ResolvedRunSpecRef
    files: tuple[Path, ...]


class _CompiledPlan(BaseModel):
    """Hold one complete protocol graph before it is published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunSpec
    run_path: RepoRelPath
    files: dict[RepoRelPath, bytes]


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
    """Compile one input draft into its frozen reference."""
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
    pointer = ArtifactPointer(run=draft.run, artifact=draft.artifact)
    raw = serialize_document(pointer)
    parts = draft.path.split("/")
    if len(parts) < 4 or parts[0] != "inputs":
        raise ValueError("prior-run input path must include category and entity")
    selection = f"{draft.artifact.artifact_name}_{draft.run.sha256}"
    pointer_path = "/".join((*parts[:3], f"{selection}.pointer.yaml"))
    published = LocalArtifactStore(root).resolved_files({pointer_path: raw})[0]
    reference = ResolvedArtifactPointerRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=published.stored_at,
    )
    return StoredInputRef(
        pointer=reference,
        path=draft.path,
        data_role=draft.data_role,
    )


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
    if definition.parameter_model.__module__ == params.__name__:
        parameter = params.model_ref(definition.parameter_model)
    else:
        if not parameter_path.is_relative_to(root):
            raise ValueError("stage parameter model is outside the project root")
        parameter = ParameterModelRef(
            owner="project",
            path=parameter_path.relative_to(root).as_posix(),
            symbol=definition.parameter_model.__name__,
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        )
    common = {
        "artifacts": artifacts,
        "env": draft.env,
        "implementation": StageImplementationRef(
            path=source_path.relative_to(root).as_posix(),
            symbol=draft.implementation.__name__,
            sha256=hashlib.sha256(source_raw).hexdigest(),
            bytes=len(source_raw),
        ),
        "parameter_model": parameter,
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


def _compile_metric(root: Path, draft: MetricDraft[Any]) -> MetricSpec:
    """Compile one configured metric from its exact Python definitions."""
    definition = metric_definition(draft.implementation)
    implementation_source = inspect.getsourcefile(draft.implementation)
    parameter_model = type(draft.params)
    parameter_source = inspect.getsourcefile(parameter_model)
    if implementation_source is None or parameter_source is None:
        raise ValueError("metric callable or parameter model has no Python source")

    implementation_path = Path(implementation_source).resolve()
    implementation_raw = implementation_path.read_bytes()
    if not implementation_path.is_relative_to(root):
        raise ValueError("metric callable is outside the project root")
    if parameter_model.__module__ == params.__name__:
        parameter = params.model_ref(parameter_model)
    else:
        parameter_path = Path(parameter_source).resolve()
        parameter_raw = parameter_path.read_bytes()
        if not parameter_path.is_relative_to(root):
            raise ValueError("metric parameter model is outside the project root")
        parameter = ParameterModelRef(
            owner="project",
            path=parameter_path.relative_to(root).as_posix(),
            symbol=parameter_model.__name__,
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        )
    return MetricSpec(
        metric_id=definition.metric_id,
        implementation=MetricImplementationRef(
            path=implementation_path.relative_to(root).as_posix(),
            symbol=draft.implementation.__name__,
            sha256=hashlib.sha256(implementation_raw).hexdigest(),
            bytes=len(implementation_raw),
        ),
        parameter_model=parameter,
        params=draft.params,
        mode=definition.mode,
        dependencies=draft.dependencies,
        comparator=draft.comparator,
    )


def _compile_metrics(root: Path, draft: ExperimentDraft) -> tuple[MetricSpec, ...]:
    """Derive one consistent metric registry from every variant stage."""
    metrics: dict[str, MetricSpec] = {}
    for variant_draft in draft.variants.values():
        for stage_draft in variant_draft.stages.values():
            spec = stage_draft.spec
            if not isinstance(spec, ParameterizedSpecDraft):
                continue
            configured = list(spec.metrics)
            objective = getattr(spec, "objective", None)
            if objective is not None:
                configured.append(objective.metric)
            for metric_draft in configured:
                metric = _compile_metric(root, metric_draft)
                existing = metrics.get(metric.metric_id)
                if existing is not None and existing != metric:
                    raise ValueError("one metric ID has conflicting configurations")
                metrics[metric.metric_id] = metric
    return tuple(metrics[metric_id] for metric_id in sorted(metrics))


def _compile_variant(
    experiment_id: ExperimentId,
    variant_id: VariantId,
    draft: VariantDraft,
) -> VariantSpec:
    """Compile the typed parameter selection for one variant."""
    stage_params = []
    for stage_id, stage_draft in draft.stages.items():
        spec = stage_draft.spec
        if isinstance(spec, BuildSpecDraft):
            stage_params.append(
                BuildVariantStageParams(stage_id=stage_id, params=spec.params)
            )
        elif isinstance(spec, EmbedSpecDraft):
            stage_params.append(
                EmbedVariantStageParams(stage_id=stage_id, params=spec.params)
            )
        elif isinstance(spec, TrainSpecDraft):
            stage_params.append(
                TrainVariantStageParams(stage_id=stage_id, params=spec.params)
            )
        elif isinstance(spec, EvalSpecDraft):
            stage_params.append(
                EvalVariantStageParams(stage_id=stage_id, params=spec.params)
            )
    if not stage_params:
        raise ValueError("variant requires one project stage")
    return VariantSpec(
        experiment_id=experiment_id,
        variant_id=variant_id,
        levels=draft.levels,
        stage_params=tuple(stage_params),
    )


def _compile_plan(root: Path, draft: RunPlanDraft) -> _CompiledPlan:
    """Compile one immutable draft into a complete in-memory protocol graph."""
    project_root = resolve_root(root)
    experiment_draft = draft.experiment
    variant_draft = experiment_draft.variants[draft.variant]
    replicate_draft = experiment_draft.replicates[draft.replicate]
    metrics = _compile_metrics(project_root, experiment_draft)
    experiment_spec = ExperimentSpec(
        experiment_id=experiment_draft.experiment_id,
        factors=tuple(
            FactorSpec(factor_id=factor_id, levels=factor.levels)
            for factor_id, factor in sorted(experiment_draft.factors.items())
        ),
        variant_ids=tuple(sorted(experiment_draft.variants)),
        replicates=tuple(
            ReplicateSpec(replicate_id=replicate_id, seed=replicate.seed)
            for replicate_id, replicate in sorted(experiment_draft.replicates.items())
        ),
        metrics=metrics,
    )
    variants = tuple(
        _compile_variant(experiment_draft.experiment_id, variant_id, value)
        for variant_id, value in sorted(experiment_draft.variants.items())
    )
    run_root = (
        f"experiments/{experiment_draft.experiment_id}/runs/"
        f"{draft.variant}/{draft.run_id}"
    )
    files: dict[RepoRelPath, bytes] = {
        f"experiments/{experiment_draft.experiment_id}/spec.yaml": serialize_document(
            experiment_spec
        )
    }
    for variant_spec in variants:
        path = (
            f"experiments/{experiment_draft.experiment_id}/variants/"
            f"{variant_spec.variant_id}.spec.yaml"
        )
        files[path] = serialize_document(variant_spec)

    stage_refs: list[RunStageRef] = []
    for stage_id, stage_draft in variant_draft.stages.items():
        stage_spec = _freeze_stage(
            project_root,
            run_root,
            variant_draft.stages,
            stage_draft.spec,
        )
        raw = serialize_document(stage_spec)
        path = f"{run_root}/stages/{stage_id}/spec.yaml"
        files[path] = raw
        stage_refs.append(
            RunStageRef(
                stage_id=stage_id,
                spec=path,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )
    estimator_stage = next(
        (
            stage_id
            for stage_id, stage_draft in variant_draft.stages.items()
            if stage_draft is variant_draft.estimator.producer
        ),
        None,
    )
    if estimator_stage is None:
        raise ValueError("estimator producer is absent from the plan")
    run = RunSpec(
        run_id=draft.run_id,
        experiment_id=experiment_draft.experiment_id,
        variant_id=draft.variant,
        replicate_id=draft.replicate,
        benchmark_id=None,
        seed=replicate_draft.seed,
        source=draft.source,
        env=draft.env,
        reproducibility=draft.reproducibility,
        stages=tuple(stage_refs),
        estimator=StageArtifactRef(
            stage_id=estimator_stage,
            artifact_name=variant_draft.estimator.artifact_name,
        ),
    )
    run_path = f"{run_root}/spec.yaml"
    files[run_path] = serialize_document(run)
    return _CompiledPlan(run=run, run_path=run_path, files=files)


def freeze_run_plan(root: Path, draft: RunPlanDraft) -> FrozenPlanFiles:
    """Publish one compiled plan and materialize its working files."""
    project_root = resolve_root(root)
    compiled = _compile_plan(project_root, draft)
    commit = LocalArtifactStore(project_root).publish(compiled.files)
    paths = tuple(_target_path(project_root, path) for path in compiled.files)
    for path, raw in zip(paths, compiled.files.values(), strict=True):
        _write_exact_file(path, raw)
    run_raw = compiled.files[compiled.run_path]
    reference = ResolvedRunSpecRef(
        sha256=hashlib.sha256(run_raw).hexdigest(),
        bytes=len(run_raw),
        stored_at=LocalFileRef(commit=commit, path=compiled.run_path),
    )
    return FrozenPlanFiles(run=compiled.run, reference=reference, files=paths)
