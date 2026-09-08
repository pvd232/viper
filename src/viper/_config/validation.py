"""Verify project config classes and validate frozen config values."""

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

from .. import config
from ..config import ConfigTypeRef
from ..worker import ExecutionPolicy, WorkerRequest, execute_worker

ConfigT = TypeVar("ConfigT", bound=config.Config)


class ConfigValidationError(RuntimeError):
    """Report an invalid config identity, class, or value."""


class ConfigValidationContext(BaseModel):
    """Tell one worker which frozen stage and config class to validate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_spec_path: Path
    result_path: Path


def verify_config_type_bytes(
    reference: ConfigTypeRef,
    raw: bytes,
) -> None:
    """Compare retrieved config-type bytes with their frozen identity."""
    if len(raw) != reference.bytes:
        raise ConfigValidationError("config type byte count differs from its reference")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ConfigValidationError("config type SHA-256 differs from its reference")


def load_config_type(
    path: Path,
    symbol: str,
    expected_base: type[config.Config],
) -> type[config.Config]:
    """Load one top-level Pydantic class and enforce its stage-specific base."""
    module_name = f"_viper_config_type_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ConfigValidationError("config type module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ConfigValidationError("config type module raised during import") from exc
    value = getattr(module, symbol, None)
    if not isinstance(value, type) or not issubclass(value, expected_base):
        raise ConfigValidationError(
            f"config type must subclass {expected_base.__name__}"
        )
    return cast(type[config.Config], value)


def validate_config(
    path: Path,
    reference: ConfigTypeRef,
    config: config.Config,
    expected_base: type[config.Config],
) -> dict[str, JsonValue]:
    """Validate one frozen config mapping with its selected project class."""
    raw = path.read_bytes()
    verify_config_type_bytes(reference, raw)
    model = (
        load_config_type(path, reference.symbol, expected_base)
        if reference.owner == "project"
        else _installed_config_type(reference.symbol, expected_base)
    )
    frozen = cast(dict[str, JsonValue], config.model_dump(mode="json"))
    validated = model.model_validate(frozen, strict=True)
    effective = cast(dict[str, JsonValue], validated.model_dump(mode="json"))
    if effective != frozen:
        raise ConfigValidationError(
            "frozen config must contain every effective project-model value"
        )
    return effective


def instantiate_config(
    path: Path,
    reference: ConfigTypeRef,
    config: config.Config,
    expected_base: type[config.Config],
) -> config.Config:
    """Construct the exact project config class from one frozen mapping."""
    raw = path.read_bytes()
    verify_config_type_bytes(reference, raw)
    model = (
        load_config_type(path, reference.symbol, expected_base)
        if reference.owner == "project"
        else _installed_config_type(reference.symbol, expected_base)
    )
    frozen = cast(dict[str, JsonValue], config.model_dump(mode="json"))
    validated = model.model_validate(frozen, strict=True)
    effective = cast(dict[str, JsonValue], validated.model_dump(mode="json"))
    if effective != frozen:
        raise ConfigValidationError(
            "frozen config must contain every effective project-model value"
        )
    return validated


def validate_stage_config(
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
    state_root = root / ".viper" / "config-validation"
    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=state_root) as directory:
        workspace = Path(directory)
        context_path = workspace / "context.json"
        result_path = workspace / "result.json"
        context_path.write_text(
            ConfigValidationContext(
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
                        "viper._workers.config",
                    ),
                    environment={"PYTHONPATH": python_path},
                    policy=ExecutionPolicy(timeout_seconds=timeout_seconds),
                )
            )
        except Exception as exc:
            raise ConfigValidationError("config validation worker failed") from exc
        if not result_path.is_file():
            raise ConfigValidationError("config validation worker wrote no result")
        value = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ConfigValidationError("config validation worker returned no mapping")
        return cast(dict[str, JsonValue], value)


def config_type_path(
    project_root: Path,
    reference: ConfigTypeRef,
) -> Path:
    """Resolve a config-type path against its declared source owner."""
    base = (
        project_root.resolve()
        if reference.owner == "project"
        else Path(config.__file__).resolve().parent
    )
    path = (base / reference.path).resolve()
    if not path.is_relative_to(base):
        raise ConfigValidationError("config type escapes its source root")
    return path


def _installed_config_type(
    symbol: str,
    expected_base: type[config.Config],
) -> type[config.Config]:
    """Resolve a built-in config type from the installed VIPER package."""
    value = getattr(config, symbol, None)
    if not isinstance(value, type) or not issubclass(value, expected_base):
        raise ConfigValidationError(
            f"config type must subclass {expected_base.__name__}"
        )
    return cast(type[config.Config], value)
