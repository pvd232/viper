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

from . import config, keys
from ._schema import (
    SHA256,
    ArtifactName,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
    RepoRelPath,
    repo_file_paths_overlap,
)
from .artifacts import (
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
)
from .config import ConfigTypeRef
from .http import (
    BuiltinHttpImplementationSpec,
    HttpImplementationSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
    ResolvedHttpRetrieval,
)
from .ids import EvalId, HumanId, InputName, MetricId, OutputName, RunId, StageId
from .inputs import (
    InputRef,
    ResolvedInputRef,
    pointer_location_matches,
)
from .metrics import MetricHandle, MetricObjectiveSpec
from .outputs import OutputSpec, StageOutputs
from .reuse import StageCompletion, StageReuseMode
from .runtime import (
    EnvSpec,
    ExecutionContext,
    GCEEnvSpec,
    GCEHostContext,
    ResolvedEnv,
    ResolvedGCEEnv,
)

ConfigT = TypeVar("ConfigT", bound=config.Config)


@dataclass(frozen=True)
class Context(Generic[ConfigT]):
    """Carry one validated project-stage invocation inside the controlled child."""

    run_id: RunId
    attempt_id: int
    stage_id: StageId
    config: ConfigT
    inputs: Mapping[InputName, Path]
    outputs: Mapping[OutputName, Path]
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
    config_type: ConfigTypeRef
    config_digest: SHA256
    inputs: dict[InputName, RepoRelPath]
    outputs: dict[OutputName, RepoRelPath]
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

    env: EnvSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()

    outputs: StageOutputs[OutputSpec]

    @model_validator(mode="after")
    def validate_output_paths(self) -> BaseSpec:
        """Validate generated stage and output paths without categories."""
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("stage metric IDs must be unique")

        output_roots: dict[RepoRelPath, OutputName] = {}
        for name, output in self.outputs.items():
            parts = output.path.split("/")
            if (
                len(parts) < 9
                or parts[0] != "experiments"
                or parts[2] != "runs"
                or parts[5] != "artifacts"
                or re.fullmatch(r"[a-z][a-z0-9_]*", parts[6]) is None
                or parts[7] != name
                or (output.kind == "file" and len(parts) < 9)
            ):
                raise ValueError(
                    f"output {name!r} path must use its stage and output identity"
                )

            for previous_path, previous_name in output_roots.items():
                if repo_file_paths_overlap(output.path, previous_path):
                    raise ValueError(
                        f"output roots for {previous_name!r} and {name!r} "
                        f"overlap: {previous_path} and {output.path}"
                    )
            output_roots[output.path] = name

        return self


class ParameterizedSpec(BaseSpec):
    """Request an operation governed by one project-defined config type."""

    implementation: StageImplementationRef
    config_type: ConfigTypeRef
    reuse: StageReuseMode = "never"

    @model_validator(mode="after")
    def validate_implementation_path(self) -> ParameterizedSpec:
        """Keep the project callable outside every declared artifact root."""
        for name, artifact in self.outputs.items():
            if repo_file_paths_overlap(artifact.path, self.implementation.path):
                raise ValueError(
                    f"artifact {name!r} path collides with the stage implementation"
                )
        return self


class DownloadSpec(BaseSpec):
    """Request HTTP retrievals into same-named single-file outputs."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpImplementationSpec = Field(default_factory=BuiltinHttpImplementationSpec)
    policy: HttpRetrievalPolicy

    @model_validator(mode="after")
    def validate_download_outputs(self) -> DownloadSpec:
        """Require one same-named file output for every HTTP request."""
        if set(self.inputs) != set(self.outputs.keys()):
            raise ValueError("download input and output names must match")
        if any(output.kind != "file" for output in self.outputs.values()):
            raise ValueError("download outputs must be single files")
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

            for output_name, output in self.outputs.items():
                if repo_file_paths_overlap(output.path, ref.path):
                    raise ValueError(
                        f"output {output_name!r} path collides with input {name!r}"
                    )

        return self


class BuildSpec(InternalSpec):
    """Request construction of a project-defined prior artifact."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    config: config.BuildConfig


class EmbedSpec(InternalSpec):
    """Request construction of a project-defined embedding artifact."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    objective: MetricObjectiveSpec | None = None
    config: config.EmbedConfig

    @model_validator(mode="after")
    def validate_objective(self) -> EmbedSpec:
        """Require a selected embedding objective to occur in metric_ids."""
        if (
            self.objective is not None
            and self.objective.metric_id not in self.metric_ids
        ):
            raise ValueError("embedding objective must occur in stage metric IDs")
        return self


class TrainSpec(InternalSpec):
    """Request training with a measured minimization or maximization objective."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)  # pyright: ignore[reportGeneralTypeIssues]
    objective: MetricObjectiveSpec
    config: config.TrainConfig

    @model_validator(mode="after")
    def validate_training_contract(self) -> TrainSpec:
        """Require the objective and canonical terminal checkpoint contract."""
        if self.objective.metric_id not in self.metric_ids:
            raise ValueError("training objective must occur in stage metric IDs")
        required_outputs = {keys.Train.MODEL, keys.Train.RESUME_STATE}
        missing = required_outputs - set(self.outputs.keys())
        if missing:
            raise ValueError(
                "training stages must declare terminal checkpoint artifacts: "
                + ", ".join(sorted(missing))
            )
        model_input = self.inputs.get(keys.Train.MODEL)
        state_input = self.inputs.get(keys.Train.RESUME_STATE)
        if (model_input is None) != (state_input is None):
            raise ValueError("checkpoint inputs must be declared together")
        if model_input is None or state_input is None:
            return self
        if model_input.kind != state_input.kind:
            raise ValueError("checkpoint inputs must use the same input kind")
        if model_input.kind == "stored" and state_input.kind == "stored":
            if any(
                value.data_role not in {"training", "validation"}
                for value in (model_input, state_input)
            ):
                raise ValueError(
                    "stored checkpoint inputs require training or validation data"
                )
        if model_input.kind == "future" and state_input.kind == "future":
            if model_input.producer_stage_id != state_input.producer_stage_id:
                raise ValueError("checkpoint inputs must select one producer stage")
            if model_input.name != keys.Train.MODEL:
                raise ValueError("parameters input must select parameters")
            if state_input.name != keys.Train.RESUME_STATE:
                raise ValueError("resume_state input must select resume_state")
        return self


class EvalSpec(InternalSpec):
    """Request prediction and recomputed metrics for one fixed eval."""

    kind: Literal["eval"] = "eval"  # pyright: ignore[reportIncompatibleVariableOverride]
    eval_id: EvalId
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)  # pyright: ignore[reportGeneralTypeIssues]
    objective: MetricObjectiveSpec
    split_inputs: tuple[InputName, ...] = Field(min_length=1)
    config: config.EvalConfig

    @model_validator(mode="after")
    def validate_eval_contract(self) -> EvalSpec:
        """Require the objective, fixed inputs, splits, and prediction artifact."""
        if self.objective.metric_id not in self.metric_ids:
            raise ValueError("eval objective must occur in stage metric IDs")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("eval metric IDs must be unique")
        if len(set(self.split_inputs)) != len(self.split_inputs):
            raise ValueError("eval split input names must be unique")
        model_input = self.inputs.get(keys.Train.MODEL)
        if model_input is None:
            raise ValueError("eval requires a parameters input")
        dataset = self.inputs.get(keys.Eval.TEST)
        if dataset is None:
            raise ValueError("eval requires an eval_dataset input")
        if dataset.kind != "stored":
            raise ValueError("eval_dataset must be a stored input")
        if dataset.data_role not in {"eval", "benchmark"}:
            raise ValueError("eval_dataset has an invalid data role")
        reserved = {keys.Train.MODEL, keys.Eval.TEST}
        if reserved & set(self.split_inputs):
            raise ValueError("eval splits must differ from reserved inputs")
        if any(name not in self.inputs for name in self.split_inputs):
            raise ValueError("eval split input is absent")
        for split_name in self.split_inputs:
            split_input = self.inputs[split_name]
            if split_input.kind != "stored":
                raise ValueError(f"eval split input {split_name!r} must be stored")
            if split_input.data_role != dataset.data_role:
                raise ValueError(
                    f"eval split input {split_name!r} data_role must match test"
                )
        if model_input.kind == "future":
            if model_input.name != keys.Train.MODEL:
                raise ValueError("same-run eval must consume model")
        elif model_input.kind == "stored":
            if model_input.data_role not in {"training", "validation"}:
                raise ValueError(
                    "stored eval parameters data_role must be training or validation"
                )
        elif model_input.data_role not in {"training", "validation"}:
            raise ValueError(
                "external evaluation parameters data_role must be training "
                "or validation"
            )
        predictions = (
            self.outputs[keys.Eval.PREDICTIONS]
            if keys.Eval.PREDICTIONS in self.outputs.keys()
            else None
        )
        if predictions is None:
            raise ValueError("eval requires a predictions artifact")
        return self


ParameterizedStageSpec = BuildSpec | EmbedSpec | TrainSpec | EvalSpec


Spec = Annotated[
    DownloadSpec | ParameterizedStageSpec,
    Field(discriminator="kind"),
]


class ResolvedBaseSpec(ProtocolModel):
    """Record an execution and the exact output files it produced."""

    schema_version: Literal[1] = 1
    kind: str

    spec: BaseSpec
    artifacts: dict[ArtifactName, ResolvedArtifact] = Field(min_length=1)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedBaseSpec:
        """Match realized source, artifacts, env, and context to the request."""
        if set(self.artifacts) != set(self.spec.outputs.keys()):
            raise ValueError("resolved artifact names must match declared output names")

        for name, resolved_artifact in self.artifacts.items():
            declared_artifact = self.spec.outputs[name]

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

        return self


class ResolvedExecutedSpec(ResolvedBaseSpec):
    """Record environment evidence created by a runner-owned execution."""

    env: ResolvedEnv
    execution_context: ExecutionContext

    @model_validator(mode="after")
    def validate_execution_environment(self) -> ResolvedExecutedSpec:
        """Match the resolved environment to its request and observed host."""
        requested_environment = self.spec.env
        if requested_environment is not None:
            if self.env.kind != requested_environment.kind:
                raise ValueError("resolved env kind must match its request")

            if isinstance(self.env, ResolvedGCEEnv) and isinstance(
                requested_environment,
                GCEEnvSpec,
            ):
                if self.env.provisioning != requested_environment.provisioning:
                    raise ValueError(
                        "resolved GCE provisioning source must match the stage "
                        "env override"
                    )
                if self.env.machine_type != requested_environment.machine_type:
                    raise ValueError(
                        "resolved machine type must match the stage env override"
                    )

            if self.env.compute != requested_environment.compute:
                raise ValueError("resolved compute must match the stage env override")

            if self.env.python_env != requested_environment.python_env:
                raise ValueError(
                    "resolved Python env must match the stage env override"
                )

            resolved_lockfile = self.env.lockfile
            requested_lockfile = requested_environment.lockfile

            if (
                resolved_lockfile.stored_at.repository != requested_lockfile.repository
                or resolved_lockfile.stored_at.commit != requested_lockfile.commit
                or resolved_lockfile.stored_at.path != requested_lockfile.path
            ):
                raise ValueError("resolved lockfile must match the stage env override")

        host = self.execution_context.host
        if self.env.kind != host.provider:
            raise ValueError("resolved env kind must match the observed host")
        if isinstance(self.env, ResolvedGCEEnv) and isinstance(
            host,
            GCEHostContext,
        ):
            if self.env.provisioning != host.provisioning:
                raise ValueError(
                    "resolved GCE provisioning source must match the observed host"
                )
            if self.env.machine_type != host.machine_type:
                raise ValueError(
                    "resolved machine type must match the observed host machine type"
                )

        compute = self.env.compute
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


class ResolvedDownloadSpec(ResolvedExecutedSpec):
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
    """Record an executed or verified-reused project stage."""

    spec: ParameterizedSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    completion: StageCompletion

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_execution(cls, value: object) -> object:
        """Read existing stage documents into the explicit completion union."""
        if not isinstance(value, dict) or "completion" in value:
            return value
        legacy = {
            "source",
            "env",
            "execution_context",
            "startup",
            "invocation",
            "command",
        }
        if not legacy <= set(value):
            return value
        payload = dict(value)
        payload["completion"] = {
            "kind": "executed",
            **{name: payload.pop(name) for name in legacy},
        }
        return payload

    @model_validator(mode="after")
    def validate_project_invocation(self) -> ResolvedParameterizedSpec:
        """Match the resolved source to the selected project callable."""
        if self.completion.kind == "reused":
            return self
        if self.completion.source.stored_at.path != self.spec.implementation.path:
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
                and not pointer_location_matches(
                    spec_input.pointer,
                    resolved_input.pointer.stored_at,
                )
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


class ResolvedEvalSpec(ResolvedInternalSpec):
    """Record the realized execution of one eval stage."""

    kind: Literal["eval"] = "eval"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: EvalSpec  # pyright: ignore[reportIncompatibleVariableOverride]


ResolvedSpec = Annotated[
    ResolvedDownloadSpec
    | ResolvedBuildSpec
    | ResolvedEmbedSpec
    | ResolvedTrainSpec
    | ResolvedEvalSpec,
    Field(discriminator="kind"),
]


DecoratedStage = TypeVar("DecoratedStage", bound=Callable[..., None])


@dataclass(frozen=True)
class StageDefinition(Generic[ConfigT]):
    """Store the stage kind and config class attached by one decorator."""

    kind: str
    config_type: type[ConfigT]


class StageDefinitionError(RuntimeError):
    """Report an invalid decorated stage or frozen implementation identity."""


def _stage_decorator(
    kind: str,
    config_type: type[ConfigT],
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Create one stage decorator with fixed authoring metadata."""
    if not issubclass(config_type, config.Config):
        raise TypeError("stage config type must subclass Config")

    definition = StageDefinition(kind=kind, config_type=config_type)

    def decorate(function: DecoratedStage) -> DecoratedStage:
        """Validate the callable interface and attach its immutable definition."""
        parameters = tuple(inspect.signature(function).parameters.values())
        if len(parameters) != 1:
            raise TypeError("a stage callable must accept one Context argument")
        setattr(function, "__viper_stage__", definition)
        return function

    return decorate


def build(
    *, config: type[config.BuildConfig]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one build-stage callable."""
    return _stage_decorator("build", config)


def embed(
    *, config: type[config.EmbedConfig]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one embedding-stage callable."""
    return _stage_decorator("embed", config)


def train(
    *, config: type[config.TrainConfig]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one training-stage callable."""
    return _stage_decorator("train", config)


def eval(
    *, config: type[config.EvalConfig]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one eval-stage callable."""
    return _stage_decorator("eval", config)


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
        # An example can run from VIPER's own repository. Keep the framework
        # module loaded so decorators use the same StageDefinition class.
        project_prefixes.discard(__name__.partition(".")[0])
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
        config_source = inspect.getsourcefile(definition.config_type)
        setattr(value, "__viper_config_source__", config_source)
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
    """Match one decorated callable with its frozen stage and config class."""
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
    if definition.config_type.__name__ != stage.config_type.symbol:
        raise StageDefinitionError(
            "stage decorator config class differs from ConfigTypeRef"
        )
    source_file = getattr(function, "__viper_config_source__", None)
    if (
        source_file is None
        or Path(source_file).resolve()
        != (
            root / stage.config_type.path
            if stage.config_type.owner == "project"
            else Path(config.__file__).resolve().parent / stage.config_type.path
        ).resolve()
    ):
        raise StageDefinitionError(
            "stage decorator config class comes from a different source file"
        )
