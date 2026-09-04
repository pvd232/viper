"""Define the project-facing stage callable and its live invocation context."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, Generic, Literal, TypeVar, cast

import numpy as np
from pydantic import AwareDatetime, Field, model_validator

from . import parameters
from ._schema import (
    EVALUATION_DATASET_INPUT,
    PARAMETERS,
    PARAMETERS_INPUT,
    PREDICTIONS,
    RESUME_STATE,
    RESUME_STATE_INPUT,
    SHA256,
    ArtifactName,
    EvaluationId,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
    RepoRelPath,
    repo_file_paths_overlap,
)
from .artifacts import (
    ArtifactSpec,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
)
from .http import (
    BuiltinHttpImplementationSpec,
    HttpImplementationSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
    ResolvedHttpRetrieval,
)
from .ids import HumanId, InputName, MetricId, RunId, StageId
from .inputs import InputRef, ResolvedInputRef
from .metrics import MetricHandle
from .parameters import ParameterModelRef
from .references import (
    ResolvedGitFileRef,
    ResolvedStageInvocationRef,
)
from .runtime import (
    EnvironmentSpec,
    ExecutionContext,
    GCEEnvironmentSpec,
    GCEHostContext,
    ProcessStartupReceipt,
    ResolvedEnvironment,
    ResolvedGCEEnvironment,
)

ParamsT = TypeVar("ParamsT", bound=parameters.ParameterSet)


@dataclass(frozen=True)
class Context(Generic[ParamsT]):
    """Carry one validated project-stage invocation inside the controlled child."""

    run_id: RunId
    attempt_id: int
    stage_id: StageId
    params: ParamsT
    inputs: Mapping[InputName, Path]
    artifacts: Mapping[ArtifactName, Path]
    metrics: Mapping[MetricId, MetricHandle]
    numpy_generators: Mapping[HumanId, np.random.Generator]


class StageImplementationRef(ProtocolModel):
    """Identify one project-owned top-level stage callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class StageContextBinding(ProtocolModel):
    """Persist the stable values used to construct one live stage context."""

    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    parameter_model: ParameterModelRef
    parameter_digest: SHA256
    inputs: dict[InputName, RepoRelPath]
    artifacts: dict[ArtifactName, RepoRelPath]
    metric_ids: tuple[MetricId, ...]
    numpy_generator_names: tuple[HumanId, ...]


class StageInvocationReceipt(ProtocolModel):
    """Record the callable, logical context, timing, and outcome of one invocation."""

    implementation: StageImplementationRef
    context: StageContextBinding
    context_digest: SHA256
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded", "failed", "cancelled", "preempted"]

    @model_validator(mode="after")
    def validate_timing(self) -> StageInvocationReceipt:
        """Require completion to follow invocation start."""
        if self.completed_at <= self.started_at:
            raise ValueError("invocation completion must be after invocation start")
        return self


class BaseSpec(ProtocolModel):
    """Execution request recorded before a stage runs."""

    kind: str
    schema_version: Literal[1] = 1

    environment: EnvironmentSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()

    artifacts: dict[ArtifactName, ArtifactSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_paths(self) -> BaseSpec:
        """Enforce entrypoint, artifact, and metric declarations."""
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("stage metric IDs must be unique")

        artifact_categories = {
            "download": "datasets",
            "build": "priors",
            "embed": "models",
            "train": "models",
            "evaluate": "evaluations",
        }
        artifact_category = artifact_categories.get(self.kind)
        if artifact_category is None:
            raise ValueError("stage kind has no artifact category contract")

        checkpoint_artifacts = {PARAMETERS, RESUME_STATE}
        if self.kind != "train" and checkpoint_artifacts & set(self.artifacts):
            raise ValueError(
                "parameters and resume_state are reserved for training stages"
            )
        if self.kind != "evaluate" and PREDICTIONS in self.artifacts:
            raise ValueError("predictions is reserved for evaluation stages")

        artifact_roots: dict[RepoRelPath, ArtifactName] = {}

        for name, artifact in self.artifacts.items():
            parts = artifact.path.split("/")
            if (
                len(parts) < 8
                or parts[0] != "experiments"
                or parts[2] != "runs"
                or parts[5] != "artifacts"
                or parts[6] != artifact_category
                or re.fullmatch(r"[a-z][a-z0-9_]*", parts[7]) is None
                or (artifact.kind == "file" and len(parts) < 9)
            ):
                raise ValueError(
                    f"artifact {name!r} path must use a run artifact category "
                    "and entity ID"
                )

            for previous_path, previous_name in artifact_roots.items():
                if repo_file_paths_overlap(artifact.path, previous_path):
                    raise ValueError(
                        f"artifact roots for {previous_name!r} and {name!r} "
                        f"overlap: {previous_path} and {artifact.path}"
                    )

            artifact_roots[artifact.path] = name

        return self


class ParameterizedSpec(BaseSpec):
    """Request an operation governed by one project-defined parameter model."""

    implementation: StageImplementationRef
    parameter_model: ParameterModelRef

    @model_validator(mode="after")
    def validate_implementation_path(self) -> ParameterizedSpec:
        """Keep the project callable outside every declared artifact root."""
        for name, artifact in self.artifacts.items():
            if repo_file_paths_overlap(artifact.path, self.implementation.path):
                raise ValueError(
                    f"artifact {name!r} path collides with the stage implementation"
                )
        return self


class DownloadSpec(BaseSpec):
    """Request runner-owned HTTP retrievals into same-named file artifacts."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpImplementationSpec = Field(default_factory=BuiltinHttpImplementationSpec)
    policy: HttpRetrievalPolicy

    @model_validator(mode="after")
    def validate_download_artifacts(self) -> DownloadSpec:
        """Require one same-named single-file artifact for each HTTP request."""
        if set(self.inputs) != set(self.artifacts):
            raise ValueError("download input and artifact names must match")
        if any(
            not isinstance(artifact, SingleFileArtifactSpec)
            for artifact in self.artifacts.values()
        ):
            raise ValueError("download artifacts must be single files")
        return self


class InternalSpec(ParameterizedSpec):
    """Request a stage that consumes stored or prior-stage artifacts."""

    inputs: dict[InputName, InputRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_local_path_collisions(self) -> InternalSpec:
        """Keep stored inputs, scripts, and artifact paths disjoint."""
        stored_inputs = {
            name: ref for name, ref in self.inputs.items() if ref.kind == "stored"
        }

        materialization_paths: dict[RepoRelPath, InputName] = {}

        for name, ref in stored_inputs.items():
            for previous_path, previous_name in materialization_paths.items():
                if repo_file_paths_overlap(ref.path, previous_path):
                    raise ValueError(
                        f"input materialization paths for {previous_name!r} and "
                        f"{name!r} collide: {previous_path} and {ref.path}"
                    )

            materialization_paths[ref.path] = name

            if repo_file_paths_overlap(ref.path, self.implementation.path):
                raise ValueError(
                    f"input {name!r} path collides with the stage implementation"
                )

            for artifact_name, artifact in self.artifacts.items():
                if repo_file_paths_overlap(artifact.path, ref.path):
                    raise ValueError(
                        f"artifact {artifact_name!r} path collides with input {name!r}"
                    )

        return self


class BuildSpec(InternalSpec):
    """Request construction of a project-defined prior artifact."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Build


class EmbedSpec(InternalSpec):
    """Request construction of a project-defined embedding artifact."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Embed


class TrainSpec(InternalSpec):
    """Request training and one terminal replay checkpoint."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Train

    @model_validator(mode="after")
    def validate_terminal_checkpoint(self) -> TrainSpec:
        """Enforce the canonical terminal checkpoint and resume inputs."""
        required_artifacts = {PARAMETERS, RESUME_STATE}
        missing_artifacts = required_artifacts - set(self.artifacts)
        if missing_artifacts:
            missing = ", ".join(sorted(missing_artifacts))
            raise ValueError(
                f"training stages must declare terminal checkpoint artifacts: {missing}"
            )

        model_input = self.inputs.get(PARAMETERS_INPUT)
        state_input = self.inputs.get(RESUME_STATE_INPUT)

        if (model_input is None) != (state_input is None):
            raise ValueError("checkpoint inputs must be declared together")

        if model_input is None or state_input is None:
            return self

        if model_input.kind != state_input.kind:
            raise ValueError("checkpoint inputs must use the same input kind")

        if model_input.kind == "stored" and state_input.kind == "stored":
            if any(
                input_ref.pointer.path.split("/")[1] != "models"
                for input_ref in (model_input, state_input)
            ):
                raise ValueError("stored checkpoint inputs must use inputs/models")

        if model_input.kind == "future" and state_input.kind == "future":
            if model_input.producer_stage_id != state_input.producer_stage_id:
                raise ValueError(
                    "checkpoint inputs must select one checkpoint-producing stage"
                )
            if model_input.name != PARAMETERS:
                raise ValueError("parameters input must select parameters")
            if state_input.name != RESUME_STATE:
                raise ValueError("resume_state input must select resume_state")

        return self


class EvaluateSpec(InternalSpec):
    """Request prediction and metrics for one fixed model, dataset, and split."""

    kind: Literal["evaluate"] = "evaluate"  # pyright: ignore[reportIncompatibleVariableOverride]
    evaluation_id: EvaluationId
    metric_ids: tuple[MetricId, ...] = Field(  # pyright: ignore[reportGeneralTypeIssues]
        min_length=1
    )
    split_inputs: tuple[InputName, ...] = Field(min_length=1)
    params: parameters.Evaluate

    @model_validator(mode="after")
    def validate_evaluation_contract(self) -> EvaluateSpec:
        """Require fixed evaluation inputs and one canonical prediction artifact."""
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("evaluation metric IDs must be unique")
        if len(set(self.split_inputs)) != len(self.split_inputs):
            raise ValueError("evaluation split input names must be unique")

        model_input = self.inputs.get(PARAMETERS_INPUT)
        if model_input is None:
            raise ValueError("evaluation requires a parameters input")

        dataset_input = self.inputs.get(EVALUATION_DATASET_INPUT)
        if dataset_input is None:
            raise ValueError("evaluation requires an evaluation_dataset input")
        if dataset_input.kind != "stored":
            raise ValueError("evaluation_dataset must be a stored input")
        if dataset_input.pointer.path.split("/")[1] != "datasets":
            raise ValueError("evaluation_dataset must use inputs/datasets")
        if dataset_input.data_role not in {"evaluation", "benchmark"}:
            raise ValueError(
                "evaluation_dataset data_role must be evaluation or benchmark"
            )

        reserved_inputs = {PARAMETERS_INPUT, EVALUATION_DATASET_INPUT}
        if reserved_inputs & set(self.split_inputs):
            raise ValueError(
                "evaluation split inputs must differ from reserved input names"
            )

        missing_splits = set(self.split_inputs) - set(self.inputs)
        if missing_splits:
            missing = ", ".join(sorted(missing_splits))
            raise ValueError(f"evaluation split inputs are undeclared: {missing}")

        for split_name in self.split_inputs:
            split_input = self.inputs[split_name]
            if split_input.kind != "stored":
                raise ValueError(
                    f"evaluation split input {split_name!r} must be stored"
                )
            if split_input.pointer.path.split("/")[1] != "benchmarks":
                raise ValueError(
                    f"evaluation split input {split_name!r} must use inputs/benchmarks"
                )
            if split_input.data_role != dataset_input.data_role:
                raise ValueError(
                    f"evaluation split input {split_name!r} data_role must match "
                    "evaluation_dataset"
                )

        if model_input.kind == "future":
            if model_input.name != PARAMETERS:
                raise ValueError("same-run evaluation must consume parameters")
        elif model_input.kind == "external":
            if model_input.data_role not in {"training", "validation"}:
                raise ValueError(
                    "external evaluation parameters data_role must be training or "
                    "validation"
                )
        else:
            if model_input.pointer.path.split("/")[1] != "models":
                raise ValueError("stored evaluation model must use inputs/models")
            if model_input.data_role not in {"training", "validation"}:
                raise ValueError(
                    "stored evaluation parameters data_role must be training or "
                    "validation"
                )

        prediction = self.artifacts.get(PREDICTIONS)
        if prediction is None:
            raise ValueError("evaluation must declare a predictions artifact")

        if any(
            artifact.data_role != dataset_input.data_role
            for artifact in self.artifacts.values()
        ):
            raise ValueError(
                "evaluation artifact data_role must match evaluation_dataset"
            )

        if any(
            artifact.path.split("/")[7] != self.evaluation_id
            for artifact in self.artifacts.values()
        ):
            raise ValueError("evaluation artifact entity IDs must match evaluation_id")

        return self


ParameterizedStageSpec = BuildSpec | EmbedSpec | TrainSpec | EvaluateSpec


Spec = Annotated[
    DownloadSpec | ParameterizedStageSpec,
    Field(discriminator="kind"),
]


class ResolvedBaseSpec(ProtocolModel):
    """Record an execution and the exact output files it produced."""

    schema_version: Literal[1] = 1
    kind: str

    spec: BaseSpec
    environment: ResolvedEnvironment
    execution_context: ExecutionContext
    artifacts: dict[ArtifactName, ResolvedArtifact] = Field(min_length=1)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedBaseSpec:
        """Match realized source, artifacts, environment, and context to the request."""
        if set(self.artifacts) != set(self.spec.artifacts):
            raise ValueError(
                "resolved artifact names must match declared artifact names"
            )

        for name, resolved_artifact in self.artifacts.items():
            declared_artifact = self.spec.artifacts[name]

            if resolved_artifact.kind != declared_artifact.kind:
                raise ValueError(
                    f"resolved artifact {name!r} kind must match its declaration"
                )

            if declared_artifact.kind == "file" and resolved_artifact.kind == "file":
                if resolved_artifact.file.path != declared_artifact.path:
                    raise ValueError(
                        f"resolved artifact {name!r} path must match its declaration"
                    )
                continue

            if (
                declared_artifact.kind == "bundle"
                and resolved_artifact.kind == "bundle"
            ):
                for member in resolved_artifact.members:
                    expected_path = f"{declared_artifact.path}/{member.relative_path}"
                    if member.file.path != expected_path:
                        raise ValueError(
                            f"resolved artifact {name!r} member path must equal "
                            "its declared bundle root plus relative path"
                        )

        requested_environment = self.spec.environment
        if requested_environment is not None:
            if self.environment.kind != requested_environment.kind:
                raise ValueError("resolved environment kind must match its request")

            if isinstance(self.environment, ResolvedGCEEnvironment) and isinstance(
                requested_environment,
                GCEEnvironmentSpec,
            ):
                if self.environment.provisioning != requested_environment.provisioning:
                    raise ValueError(
                        "resolved GCE provisioning source must match the stage "
                        "environment override"
                    )
                if self.environment.machine_type != requested_environment.machine_type:
                    raise ValueError(
                        "resolved machine type must match the stage "
                        "environment override"
                    )

            if self.environment.compute != requested_environment.compute:
                raise ValueError(
                    "resolved compute must match the stage environment override"
                )

            if (
                self.environment.python_environment
                != requested_environment.python_environment
            ):
                raise ValueError(
                    "resolved Python environment must match the stage "
                    "environment override"
                )

            resolved_lockfile = self.environment.lockfile
            requested_lockfile = requested_environment.lockfile

            if (
                resolved_lockfile.stored_at.repository != requested_lockfile.repository
                or resolved_lockfile.stored_at.commit != requested_lockfile.commit
                or resolved_lockfile.stored_at.path != requested_lockfile.path
            ):
                raise ValueError(
                    "resolved lockfile must match the stage environment override"
                )

        host = self.execution_context.host
        if self.environment.kind != host.provider:
            raise ValueError("resolved environment kind must match the observed host")
        if isinstance(self.environment, ResolvedGCEEnvironment) and isinstance(
            host,
            GCEHostContext,
        ):
            if self.environment.provisioning != host.provisioning:
                raise ValueError(
                    "resolved GCE provisioning source must match the observed host"
                )
            if self.environment.machine_type != host.machine_type:
                raise ValueError(
                    "resolved machine type must match the observed host machine type"
                )

        compute = self.environment.compute
        backend = self.execution_context.backend

        if compute.kind != backend.kind:
            raise ValueError("resolved compute kind must match the observed backend")

        if compute.kind == "cuda" and backend.kind == "cuda":
            if len(backend.gpu_devices) != compute.count:
                raise ValueError(
                    "observed CUDA device count must match the resolved compute"
                )
            if any(device.model != compute.model for device in backend.gpu_devices):
                raise ValueError(
                    "observed CUDA device models must match the resolved compute"
                )

        return self


class ResolvedDownloadSpec(ResolvedBaseSpec):
    """Bind every frozen HTTP input to its completed retrieval evidence."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: DownloadSpec  # pyright: ignore[reportIncompatibleVariableOverride]

    retrievals: dict[InputName, ResolvedHttpRetrieval]

    @model_validator(mode="after")
    def validate_download_retrievals(self) -> ResolvedDownloadSpec:
        """Match each retrieval to its request, HTTP implementation, and timing."""
        if set(self.retrievals) != set(self.spec.inputs):
            raise ValueError("resolved retrieval names must match download inputs")
        if set(self.artifacts) != set(self.retrievals):
            raise ValueError("resolved download artifacts must match retrievals")
        for input_name, retrieval in self.retrievals.items():
            if retrieval.input_name != input_name:
                raise ValueError("resolved retrieval input name differs from its key")
            if retrieval.request != self.spec.inputs[input_name]:
                raise ValueError(
                    "resolved retrieval request differs from download input"
                )
            if retrieval.http.spec != self.spec.http:
                raise ValueError("resolved HTTP implementation differs from stage spec")
            artifact = self.artifacts[input_name]
            if not isinstance(artifact, ResolvedSingleFileArtifact):
                raise ValueError("resolved download artifacts must be single files")
            if retrieval.body != artifact.file:
                raise ValueError("retrieval body must equal its resolved artifact file")
            if retrieval.completed_at > self.completed_at:
                raise ValueError("download retrieval cannot follow stage completion")
        return self


class ResolvedParameterizedSpec(ResolvedBaseSpec):
    """Record evidence produced by one project-owned stage process."""

    spec: ParameterizedSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    source: ResolvedGitFileRef
    startup: ProcessStartupReceipt
    invocation: ResolvedStageInvocationRef
    command: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_project_invocation(self) -> ResolvedParameterizedSpec:
        """Match the resolved source to the selected project callable."""
        if self.source.stored_at.path != self.spec.implementation.path:
            raise ValueError(
                "resolved source entrypoint must match the stage implementation path"
            )
        return self


class ResolvedInternalSpec(ResolvedParameterizedSpec):
    """Record an operation that consumes previously produced artifacts."""

    spec: InternalSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, ResolvedInputRef]

    @model_validator(mode="after")
    def validate_internal_inputs(self) -> ResolvedInternalSpec:
        """Match each realized internal input to the frozen request."""
        if set(self.inputs) != set(self.spec.inputs):
            raise ValueError(
                "resolved input names must match the stage spec input names"
            )

        for name, resolved_input in self.inputs.items():
            spec_input = self.spec.inputs[name]

            if resolved_input.kind != spec_input.kind:
                raise ValueError(
                    f"resolved input {name!r} kind must match the stage spec input"
                )

            if (
                resolved_input.kind == "stored"
                and spec_input.kind == "stored"
                and resolved_input.pointer.stored_at != spec_input.pointer
            ):
                raise ValueError(
                    f"resolved input {name!r} pointer location must match "
                    "the stage spec pointer location"
                )

        return self


class ResolvedBuildSpec(ResolvedInternalSpec):
    """Record the realized execution of one build stage."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: BuildSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedEmbedSpec(ResolvedInternalSpec):
    """Record the realized execution of one embedding stage."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: EmbedSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedTrainSpec(ResolvedInternalSpec):
    """Record the realized execution of one training stage."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: TrainSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedEvaluateSpec(ResolvedInternalSpec):
    """Record the realized execution of one evaluation stage."""

    kind: Literal["evaluate"] = "evaluate"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: EvaluateSpec  # pyright: ignore[reportIncompatibleVariableOverride]


ResolvedSpec = Annotated[
    ResolvedDownloadSpec
    | ResolvedBuildSpec
    | ResolvedEmbedSpec
    | ResolvedTrainSpec
    | ResolvedEvaluateSpec,
    Field(discriminator="kind"),
]


ParamsT = TypeVar("ParamsT", bound=parameters.ParameterSet)
DecoratedStage = TypeVar("DecoratedStage", bound=Callable[..., None])


@dataclass(frozen=True)
class StageDefinition(Generic[ParamsT]):
    """Store the stage kind and parameter class attached by one decorator."""

    kind: str
    parameter_model: type[ParamsT]


class StageDefinitionError(RuntimeError):
    """Report an invalid decorated stage or frozen implementation identity."""


def _stage_decorator(
    kind: str,
    parameter_model: type[ParamsT],
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Create one stage decorator with fixed authoring metadata."""
    if not issubclass(parameter_model, parameters.ParameterSet):
        raise TypeError("stage parameter model must subclass ParameterSet")

    definition = StageDefinition(kind=kind, parameter_model=parameter_model)

    def decorate(function: DecoratedStage) -> DecoratedStage:
        """Validate the callable interface and attach its immutable definition."""
        parameters = tuple(inspect.signature(function).parameters.values())
        if len(parameters) != 1:
            raise TypeError("a stage callable must accept one Context argument")
        setattr(function, "__viper_stage__", definition)
        return function

    return decorate


def build(
    *, params: type[parameters.Build]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one build-stage callable."""
    return _stage_decorator("build", params)


def embed(
    *, params: type[parameters.Embed]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one embedding-stage callable."""
    return _stage_decorator("embed", params)


def train(
    *, params: type[parameters.Train]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one training-stage callable."""
    return _stage_decorator("train", params)


def eval(
    *, params: type[parameters.Evaluate]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one evaluation-stage callable."""
    return _stage_decorator("evaluate", params)


def verify_stage_implementation_bytes(
    reference: StageImplementationRef,
    raw: bytes,
) -> None:
    """Compare one implementation file with its frozen byte identity."""
    if len(raw) != reference.bytes:
        raise StageDefinitionError(
            "stage implementation byte count differs from its reference"
        )
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise StageDefinitionError(
            "stage implementation SHA-256 differs from its reference"
        )


def load_stage_callable(
    path: Path,
    reference: StageImplementationRef,
    *,
    import_root: Path | None = None,
) -> Callable[[Context[Any]], None]:
    """Load and validate the exact decorated top-level callable in one file."""
    verify_stage_implementation_bytes(reference, path.read_bytes())
    module_name = f"_viper_stage_{path.stem}_{abs(hash(path.resolve()))}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise StageDefinitionError("stage implementation module could not be loaded")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    resolved_import_root = None if import_root is None else import_root.resolve()
    import_roots: tuple[Path, ...] = ()
    if resolved_import_root is not None:
        source_root = resolved_import_root / "src"
        import_roots = (
            (source_root, resolved_import_root)
            if source_root.is_dir()
            else (resolved_import_root,)
        )
    inserted_paths = tuple(str(root) for root in import_roots)
    saved_modules: dict[str, ModuleType] = {}
    project_prefixes: set[str] = set()
    if import_roots:
        project_prefixes = {
            child.stem
            for root in import_roots
            for child in root.iterdir()
            if child.is_dir() or child.suffix == ".py"
        }
        for name in tuple(sys.modules):
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in project_prefixes
            ):
                saved_modules[name] = sys.modules.pop(name)
        for inserted_path in reversed(inserted_paths):
            sys.path.insert(0, inserted_path)
    try:
        module_spec.loader.exec_module(module)
        value = getattr(module, reference.symbol, None)
        if value is None or not callable(value):
            raise StageDefinitionError("stage implementation symbol is not callable")
        if getattr(value, "__module__", None) != module_name:
            raise StageDefinitionError("stage implementation symbol must be top-level")
        definition = getattr(value, "__viper_stage__", None)
        if not isinstance(definition, StageDefinition):
            raise StageDefinitionError("stage implementation lacks a VIPER decorator")
        parameter_source = inspect.getsourcefile(definition.parameter_model)
        setattr(value, "__viper_parameter_source__", parameter_source)
        setattr(value, "__viper_source_path__", str(path.resolve()))
    except Exception as exc:
        if isinstance(exc, StageDefinitionError):
            raise
        raise StageDefinitionError(
            "stage implementation module raised during import"
        ) from exc
    finally:
        sys.modules.pop(module_name, None)
        if import_roots:
            for inserted_path in inserted_paths:
                sys.path.remove(inserted_path)
            for name in tuple(sys.modules):
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in project_prefixes
                ):
                    sys.modules.pop(name, None)
            sys.modules.update(saved_modules)
    return cast(Callable[[Context[Any]], None], value)


def stage_definition(function: Callable[..., Any]) -> StageDefinition[Any]:
    """Return the decorator metadata attached to one stage callable."""
    definition = getattr(function, "__viper_stage__", None)
    if not isinstance(definition, StageDefinition):
        raise StageDefinitionError("callable lacks a VIPER stage decorator")
    return definition


def validate_stage_definition(
    repository_root: Path,
    stage: ParameterizedSpec,
) -> None:
    """Match one decorated callable with its frozen stage and parameter class."""
    root = repository_root.resolve()
    implementation_path = root / stage.implementation.path
    function = load_stage_callable(
        implementation_path,
        stage.implementation,
        import_root=root,
    )
    definition = stage_definition(function)
    if definition.kind != stage.kind:
        raise StageDefinitionError("stage decorator kind differs from the stage spec")
    if definition.parameter_model.__name__ != stage.parameter_model.symbol:
        raise StageDefinitionError(
            "stage decorator parameter class differs from ParameterModelRef"
        )
    source_file = getattr(function, "__viper_parameter_source__", None)
    if (
        source_file is None
        or Path(source_file).resolve() != (root / stage.parameter_model.path).resolve()
    ):
        raise StageDefinitionError(
            "stage decorator parameter class comes from a different source file"
        )
