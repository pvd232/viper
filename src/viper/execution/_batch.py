from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from ..runs import RunSpec
from ..serialization import parse_yaml_bytes
from ..verification.models import VerificationError
from ._run import run as execute_run
from ._stage import StageExecutionError
from .errors import RunError
from .results import (
    ExperimentExecutionResult,
    ExperimentRunFailure,
    ExperimentRunFailureCode,
    ExperimentRunResult,
    RunResult,
)


def _load_run_spec(root: Path, path: Path) -> tuple[Path, RunSpec]:
    """Resolve and parse one batch input before starting any run."""
    selected = path if path.is_absolute() else root / path
    selected = selected.resolve()
    if not selected.is_relative_to(root):
        raise ValueError("run specification is outside the project root")
    return selected, RunSpec.model_validate(parse_yaml_bytes(selected.read_bytes()))


def _failed_run(path: Path, spec: RunSpec, error: Exception) -> ExperimentRunResult:
    """Convert one expected run failure into its batch entry."""
    code: ExperimentRunFailureCode
    if isinstance(error, VerificationError):
        code = "verification_failed"
    elif isinstance(error, (RunError, StageExecutionError)):
        code = "execution_failed"
    else:
        code = "invalid_document"
    return ExperimentRunResult(
        variant_id=spec.variant_id,
        replicate_id=spec.replicate_id,
        run_id=spec.run_id,
        run_spec_path=path,
        status="failed",
        failure=ExperimentRunFailure(
            code=code,
            message=str(error) or type(error).__name__,
        ),
    )


def run_many(
    repository_root: Path,
    run_spec_paths: tuple[Path, ...],
    *,
    max_concurrency: int = 1,
    timeout_seconds: float | None = None,
    stop_on_failure: bool = False,
) -> ExperimentExecutionResult:
    """Execute frozen plans with bounded concurrency and stable result order."""
    root = repository_root.resolve()
    if not run_spec_paths:
        raise ValueError("run_spec_paths must not be empty")
    if isinstance(max_concurrency, bool) or max_concurrency < 1:
        raise ValueError("max_concurrency must be at least one")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    inputs = tuple(_load_run_spec(root, path) for path in run_spec_paths)
    outcomes: list[ExperimentRunResult | None] = [None] * len(inputs)
    next_index = 0
    stop = False

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        pending: dict[Future[RunResult], int] = {}
        while pending or (next_index < len(inputs) and not stop):
            while len(pending) < max_concurrency and next_index < len(inputs):
                path, _ = inputs[next_index]
                pending[
                    executor.submit(
                        execute_run,
                        root,
                        path,
                        timeout_seconds=timeout_seconds,
                    )
                ] = next_index
                next_index += 1

            completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in sorted(completed, key=pending.__getitem__):
                index = pending.pop(future)
                path, spec = inputs[index]
                try:
                    result = future.result()
                except (
                    OSError,
                    ValueError,
                    RunError,
                    StageExecutionError,
                    VerificationError,
                ) as error:
                    outcomes[index] = _failed_run(path, spec, error)
                    stop = stop_on_failure
                else:
                    outcomes[index] = ExperimentRunResult(
                        variant_id=spec.variant_id,
                        replicate_id=spec.replicate_id,
                        run_id=spec.run_id,
                        run_spec_path=path,
                        status="succeeded",
                        result=result,
                    )

    if stop:
        for index in range(next_index, len(inputs)):
            path, spec = inputs[index]
            outcomes[index] = ExperimentRunResult(
                variant_id=spec.variant_id,
                replicate_id=spec.replicate_id,
                run_id=spec.run_id,
                run_spec_path=path,
                status="skipped",
                skip_reason="stopped after an earlier run failed",
            )
    if any(outcome is None for outcome in outcomes):
        raise RuntimeError("batch execution omitted an input")
    return ExperimentExecutionResult(
        runs=tuple(outcome for outcome in outcomes if outcome is not None)
    )
