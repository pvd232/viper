"""Verify project parameter classes and validate frozen parameter values."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from .. import params
from ..params import ParameterModelRef
from ..worker import ExecutionPolicy, WorkerRequest, execute_worker

ParameterSetT = TypeVar("ParameterSetT", bound=params.ParameterSet)


class ParameterValidationError(RuntimeError):
    """Report an invalid parameter identity, class, or value."""


class ParameterValidationContext(BaseModel):
    """Tell one worker which frozen stage and parameter class to validate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_spec_path: Path
    result_path: Path


def verify_parameter_model_bytes(
    reference: ParameterModelRef,
    raw: bytes,
) -> None:
    """Compare retrieved parameter-model bytes with their frozen identity."""
    if len(raw) != reference.bytes:
        raise ParameterValidationError(
            "parameter model byte count differs from its reference"
        )
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ParameterValidationError(
            "parameter model SHA-256 differs from its reference"
        )


def load_parameter_model(
    path: Path,
    symbol: str,
    expected_base: type[params.ParameterSet],
) -> type[params.ParameterSet]:
    """Load one top-level Pydantic class and enforce its stage-specific base."""
    module_name = f"_viper_parameter_model_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ParameterValidationError("parameter model module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ParameterValidationError(
            "parameter model module raised during import"
        ) from exc
    value = getattr(module, symbol, None)
    if not isinstance(value, type) or not issubclass(value, expected_base):
        raise ParameterValidationError(
            f"parameter model must subclass {expected_base.__name__}"
        )
    return cast(type[params.ParameterSet], value)


def validate_parameters(
    path: Path,
    reference: ParameterModelRef,
    params: params.ParameterSet,
    expected_base: type[params.ParameterSet],
) -> dict[str, JsonValue]:
    """Validate one frozen parameter mapping with its selected project class."""
    raw = path.read_bytes()
    verify_parameter_model_bytes(reference, raw)
    model = (
        load_parameter_model(path, reference.symbol, expected_base)
        if reference.owner == "project"
        else _installed_parameter_model(reference.symbol, expected_base)
    )
    frozen = cast(dict[str, JsonValue], params.model_dump(mode="json"))
    validated = model.model_validate(frozen, strict=True)
    effective = cast(dict[str, JsonValue], validated.model_dump(mode="json"))
    if effective != frozen:
        raise ParameterValidationError(
            "frozen parameters must contain every effective project-model value"
        )
    return effective


def instantiate_parameters(
    path: Path,
    reference: ParameterModelRef,
    params: params.ParameterSet,
    expected_base: type[params.ParameterSet],
) -> params.ParameterSet:
    """Construct the exact project parameter class from one frozen mapping."""
    raw = path.read_bytes()
    verify_parameter_model_bytes(reference, raw)
    model = (
        load_parameter_model(path, reference.symbol, expected_base)
        if reference.owner == "project"
        else _installed_parameter_model(reference.symbol, expected_base)
    )
    frozen = cast(dict[str, JsonValue], params.model_dump(mode="json"))
    validated = model.model_validate(frozen, strict=True)
    effective = cast(dict[str, JsonValue], validated.model_dump(mode="json"))
    if effective != frozen:
        raise ParameterValidationError(
            "frozen parameters must contain every effective project-model value"
        )
    return validated


def validate_stage_parameters(
    repository_root: Path,
    stage_spec_path: Path,
    stage: object,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, JsonValue]:
    """Validate one stage in a separate trusted-local worker process."""
    root = repository_root.resolve()
    package_root = str(Path(__file__).resolve().parents[2])
    existing_python_path = os.environ.get("PYTHONPATH")
    python_path = (
        package_root
        if existing_python_path is None
        else f"{package_root}{os.pathsep}{existing_python_path}"
    )
    state_root = root / ".viper" / "parameter-validation"
    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=state_root) as directory:
        workspace = Path(directory)
        context_path = workspace / "context.json"
        result_path = workspace / "result.json"
        context_path.write_text(
            ParameterValidationContext(
                stage_spec_path=stage_spec_path.resolve(),
                result_path=result_path,
            ).model_dump_json(),
            encoding="utf-8",
        )
        try:
            execute_worker(
                WorkerRequest(
                    workspace_root=root,
                    working_directory=root,
                    context_path=context_path,
                    command=(
                        sys.executable,
                        "-m",
                        "viper._workers.parameters",
                    ),
                    environment={"PYTHONPATH": python_path},
                    policy=ExecutionPolicy(timeout_seconds=timeout_seconds),
                )
            )
        except Exception as exc:
            raise ParameterValidationError(
                "parameter validation worker failed"
            ) from exc
        if not result_path.is_file():
            raise ParameterValidationError(
                "parameter validation worker wrote no result"
            )
        value = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ParameterValidationError(
                "parameter validation worker returned no mapping"
            )
        return cast(dict[str, JsonValue], value)


def parameter_model_path(
    project_root: Path,
    reference: ParameterModelRef,
) -> Path:
    """Resolve a parameter-model path against its declared source owner."""
    base = (
        project_root.resolve()
        if reference.owner == "project"
        else Path(params.__file__).resolve().parent
    )
    path = (base / reference.path).resolve()
    if not path.is_relative_to(base):
        raise ParameterValidationError("parameter model escapes its source root")
    return path


def _installed_parameter_model(
    symbol: str,
    expected_base: type[params.ParameterSet],
) -> type[params.ParameterSet]:
    """Resolve a built-in parameter model from the installed VIPER package."""
    value = getattr(params, symbol, None)
    if not isinstance(value, type) or not issubclass(value, expected_base):
        raise ParameterValidationError(
            f"parameter model must subclass {expected_base.__name__}"
        )
    return cast(type[params.ParameterSet], value)
