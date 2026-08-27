"""Connect a project's executable stage module to VIPER coordination."""

from __future__ import annotations

import argparse
import hashlib
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .application import RetryRequest, RetrySuccess, RunRequest, RunSuccess
from .application import retry as application_retry
from .application import run as application_run
from .protocol import ParameterizedSpec, RunSpec
from .serialization import load_stage_spec, parse_yaml_bytes
from .stages import stage_definition, verify_stage_implementation_bytes


class PythonRunError(RuntimeError):
    """Report a mismatch between a launched callable and its frozen stage."""


def _parser() -> argparse.ArgumentParser:
    """Build the argument parser used by a project stage entrypoint."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--run", required=True, dest="run_spec", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=float)
    return parser


def run(
    stage_callable: Callable[[Any], None],
    *,
    argv: Sequence[str] | None = None,
) -> RunSuccess:
    """Bind one launched callable to a frozen stage and execute its complete run."""
    arguments = _parser().parse_args(None if argv is None else list(argv))
    root = arguments.repository_root.resolve()
    run_spec_path = arguments.run_spec
    if not run_spec_path.is_absolute():
        run_spec_path = root / run_spec_path
    run_spec_path = run_spec_path.resolve()
    if not run_spec_path.is_relative_to(root):
        raise PythonRunError("run specification is outside the repository root")
    run_spec = RunSpec.model_validate(parse_yaml_bytes(run_spec_path.read_bytes()))
    selected = next(
        (stage for stage in run_spec.stages if stage.stage_id == arguments.stage),
        None,
    )
    if selected is None:
        raise PythonRunError("selected stage ID is absent from the run plan")
    stage_path = (root / selected.spec).resolve()
    stage_raw = stage_path.read_bytes()
    if len(stage_raw) != selected.bytes or hashlib.sha256(stage_raw).hexdigest() != (
        selected.sha256
    ):
        raise PythonRunError("selected stage specification differs from RunStageRef")
    stage = load_stage_spec(stage_path)
    if not isinstance(stage, ParameterizedSpec):
        raise PythonRunError("selected stage is not parameterized")

    source_file = getattr(stage_callable, "__viper_source_path__", None)
    if source_file is None:
        source_file = inspect.getsourcefile(stage_callable)
    if source_file is None:
        raise PythonRunError("launched stage callable has no source file")
    source_path = Path(source_file).resolve()
    if not source_path.is_relative_to(root):
        raise PythonRunError("launched stage callable is outside the repository root")
    relative_source = source_path.relative_to(root).as_posix()
    if relative_source != stage.implementation.path:
        raise PythonRunError("launched stage callable path differs from the plan")
    if stage_callable.__name__ != stage.implementation.symbol:
        raise PythonRunError("launched stage callable symbol differs from the plan")
    verify_stage_implementation_bytes(stage.implementation, source_path.read_bytes())
    definition = stage_definition(stage_callable)
    if definition.kind != stage.kind:
        raise PythonRunError("launched stage decorator kind differs from the plan")
    if definition.parameter_model.__name__ != stage.parameter_model.symbol:
        raise PythonRunError("launched parameter class differs from the plan")

    return application_run(
        RunRequest(
            run_spec=run_spec_path,
            repository_root=root,
            timeout_seconds=arguments.timeout_seconds,
        )
    )


def retry(
    run_spec: Path,
    *,
    repository_root: Path = Path.cwd(),
    timeout_seconds: float | None = None,
) -> RetrySuccess:
    """Append one attempt to a failed frozen run."""
    root = repository_root.resolve()
    selected = run_spec if run_spec.is_absolute() else root / run_spec
    selected = selected.resolve()
    if not selected.is_relative_to(root):
        raise PythonRunError("run specification is outside the repository root")
    return application_retry(
        RetryRequest(
            run_spec=selected,
            repository_root=root,
            timeout_seconds=timeout_seconds,
        )
    )
