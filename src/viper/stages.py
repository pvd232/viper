"""Define the project-facing stage callable and its live invocation context."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Generic, TypeVar, cast

import numpy as np

from . import parameters
from .ids import HumanId, InputName, MetricId, RunId, StageId
from .metrics import MetricHandle
from .protocol import (
    ArtifactName,
    ParameterizedSpec,
    StageImplementationRef,
)

ParamsT = TypeVar("ParamsT", bound=parameters.ParameterSet)
DecoratedStage = TypeVar("DecoratedStage", bound=Callable[..., None])


@dataclass(frozen=True)
class StageContext(Generic[ParamsT]):
    """Carry one validated project-stage invocation inside the controlled child."""

    run_id: RunId
    attempt_id: int
    stage_id: StageId
    params: ParamsT
    inputs: Mapping[InputName, Path]
    artifacts: Mapping[ArtifactName, Path]
    metrics: Mapping[MetricId, MetricHandle]
    numpy_generators: Mapping[HumanId, np.random.Generator]


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
            raise TypeError("a stage callable must accept one StageContext argument")
        setattr(function, "__viper_stage__", definition)
        return function

    return decorate


def download_stage(
    *, parameter_model: type[parameters.Download]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one download-stage callable."""
    return _stage_decorator("download", parameter_model)


def build_stage(
    *, parameter_model: type[parameters.Build]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one build-stage callable."""
    return _stage_decorator("build", parameter_model)


def embed_stage(
    *, parameter_model: type[parameters.Embed]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one embedding-stage callable."""
    return _stage_decorator("embed", parameter_model)


def train_stage(
    *, parameter_model: type[parameters.Train]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one training-stage callable."""
    return _stage_decorator("train", parameter_model)


def evaluate_stage(
    *, parameter_model: type[parameters.Evaluate]
) -> Callable[[DecoratedStage], DecoratedStage]:
    """Declare one evaluation-stage callable."""
    return _stage_decorator("evaluate", parameter_model)


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
) -> Callable[[StageContext[Any]], None]:
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
    return cast(Callable[[StageContext[Any]], None], value)


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
