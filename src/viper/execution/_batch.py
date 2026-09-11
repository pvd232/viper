"""Execute batches of authored or Git-committed plans in input order."""

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from ..authoring import RunPlanDraft, freeze_run_plan
from ..evidence import VerificationError
from ..runs import RunSpec
from ..serialization import parse_yaml_bytes
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
        raise ValueError("run specification is outside the workspace root")
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
    run_spec_paths: tuple[Path | RunPlanDraft, ...],
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

    # Preserve the immutable store reference when freezing a draft. A path-only
    # request instead identifies a plan committed to Git.
    inputs = []
    for item in run_spec_paths:
        if isinstance(item, RunPlanDraft):
            frozen = freeze_run_plan(root, item)
            inputs.append(
                (root / frozen.reference.stored_at.path, frozen.run, frozen.reference)
            )
        else:
            path, spec = _load_run_spec(root, item)
            inputs.append((path, spec, None))
    outcomes: list[ExperimentRunResult | None] = [None] * len(inputs)
    next_index = 0
    stop = False

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        pending: dict[Future[RunResult], int] = {}
        while pending or (next_index < len(inputs) and not stop):
            while (
                not stop and len(pending) < max_concurrency and next_index < len(inputs)
            ):
                path, _, plan = inputs[next_index]
                pending[
                    executor.submit(
                        execute_run,
                        root,
                        path,
                        plan=plan,
                        timeout_seconds=timeout_seconds,
                    )
                ] = next_index
                next_index += 1

            completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in sorted(completed, key=pending.__getitem__):
                index = pending.pop(future)
                path, spec, _ = inputs[index]
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
            path, spec, _ = inputs[index]
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
