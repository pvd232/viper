"""Expose VIPER operations through one typed Python API."""

# Public request and result types must exist before private handlers import them.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from base64 import b64encode
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from .artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
)
from .benchmark import BenchmarkResult
from .ids import RunId, StageId
from .inspection import (
    LineageEdge,
    LineageNode,
    PlanChange,
    RunChange,
)
from .journal import AttemptState
from .preflight import PreflightCheck
from .runs import (
    ResolvedRun,
    RunSpec,
)
from .serialization import load_stage_spec, parse_yaml_bytes
from .stages import (
    ParameterizedSpec,
    Spec,
    stage_definition,
    verify_stage_implementation_bytes,
)

OperationName = Literal[
    "validate_stage",
    "validate_resolved_stage",
    "validate_run_spec",
    "freeze_run",
    "preflight",
    "execute_stage",
    "run",
    "retry",
    "execute_benchmark",
    "plan_diff",
    "lineage",
    "status",
    "compare_runs",
    "verify_run",
    "verify_benchmark",
    "verify_pointer",
    "get_schema",
    "get_capabilities",
    "init_project",
]
FailureOrigin = Literal["request", "application", "cli", "internal"]
ErrorCode = Literal[
    "invalid_request",
    "invalid_document",
    "not_found",
    "retrieval_failed",
    "write_conflict",
    "io_failed",
    "execution_failed",
    "verification_failed",
    "publication_failed",
    "cancelled",
    "internal_error",
]

_REDACTED = "<redacted>"
_SENSITIVE_FIELD_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


def _redact_public_value(value: Any, *, field_name: str = "") -> Any:
    """Remove credential-bearing values from public failure details."""
    normalized_name = field_name.casefold()
    if any(part in normalized_name for part in _SENSITIVE_FIELD_PARTS):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): _redact_public_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_public_value(item) for item in value]
    return value


class APIModel(BaseModel):
    """Base model for stable API requests and results."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        ser_json_bytes="base64",
    )


class ViperFailure(APIModel):
    """Describe one expected failure at the API boundary."""

    status: Literal["error"] = "error"
    operation: OperationName | None
    origin: FailureOrigin
    code: ErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("details", mode="before")
    @classmethod
    def redact_details(cls, value: Any) -> Any:
        """Redact secret-bearing fields before a failure can be serialized."""
        return _redact_public_value(value)


class ViperError(RuntimeError):
    """Carry one typed expected API failure to a Python caller."""

    def __init__(self, failure: ViperFailure) -> None:
        """Initialize the exception from one stable failure model."""
        super().__init__(failure.message)
        self.failure = failure


class SuccessModel(APIModel):
    """Base model for successful API results."""

    status: Literal["ok"] = "ok"
    operation: OperationName
    warnings: tuple[str, ...] = ()


class PathRequest(APIModel):
    """Select one local protocol document."""

    path: Path


class ValidateStageRequest(PathRequest):
    """Select one authored stage specification."""


class ValidateStageSuccess(SuccessModel):
    """Report the kind of one valid authored stage specification."""

    operation: Literal["validate_stage"] = "validate_stage"  # pyright: ignore[reportIncompatibleVariableOverride]
    path: Path
    stage_kind: str


class ValidateResolvedStageRequest(PathRequest):
    """Select one resolved stage specification."""


class ValidateResolvedStageSuccess(SuccessModel):
    """Report the kind of one valid resolved stage specification."""

    operation: Literal["validate_resolved_stage"] = "validate_resolved_stage"  # pyright: ignore[reportIncompatibleVariableOverride]
    path: Path
    stage_kind: str


class ValidateRunSpecRequest(PathRequest):
    """Select one frozen RunSpec document."""


class ValidateRunSpecSuccess(SuccessModel):
    """Report the identity and stage order of one valid RunSpec."""

    operation: Literal["validate_run_spec"] = "validate_run_spec"  # pyright: ignore[reportIncompatibleVariableOverride]
    path: Path
    run_id: RunId
    stage_ids: tuple[StageId, ...]


class FreezeRunRequest(APIModel):
    """Select one run-plan draft and its repository root."""

    draft: Path
    repository_root: Path


class FreezeRunSuccess(SuccessModel):
    """Report the canonical documents written for one frozen plan."""

    operation: Literal["freeze_run"] = "freeze_run"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    files: tuple[Path, ...]


class PreflightRequest(APIModel):
    """Select one local frozen plan for complete pre-execution inspection."""

    run_spec: Path
    repository_root: Path


class PreflightSuccess(SuccessModel):
    """Return every applicable check and the resulting readiness decision."""

    operation: Literal["preflight"] = "preflight"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId | None
    ready: bool
    checks: tuple[PreflightCheck, ...]


class ExecuteStageRequest(APIModel):
    """Select one stage from a frozen local run plan."""

    run_spec: Path
    stage_id: StageId
    repository_root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteStageSuccess(SuccessModel):
    """Return the observed result of one completed stage process."""

    operation: Literal["execute_stage"] = "execute_stage"  # pyright: ignore[reportIncompatibleVariableOverride]
    stage_id: StageId
    command: tuple[str, ...]
    artifacts: dict[str, ResolvedArtifact]
    stdout: bytes
    stderr: bytes


class RunRequest(APIModel):
    """Select one frozen plan for complete execution on the active host."""

    run_spec: Path
    repository_root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class RunSuccess(SuccessModel):
    """Report the terminal document written by one verified run."""

    operation: Literal["run"] = "run"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    attempt_id: int = Field(ge=1)
    resolved_attempt: Path
    resolved_run: Path
    journal: Path


class RetryRequest(RunRequest):
    """Select a failed frozen run for one new attempt."""


class RetrySuccess(SuccessModel):
    """Report the terminal document written by one successful retry."""

    operation: Literal["retry"] = "retry"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    attempt_id: int = Field(ge=2)
    resolved_run: Path
    journal: Path


class ExecuteBenchmarkRequest(APIModel):
    """Select one candidate run and its frozen benchmark specification."""

    resolved_run: Path
    benchmark_spec: Path
    repository_root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteBenchmarkSuccess(SuccessModel):
    """Return one independently executed and verified benchmark result."""

    operation: Literal["execute_benchmark"] = "execute_benchmark"  # pyright: ignore[reportIncompatibleVariableOverride]
    result: BenchmarkResult
    result_path: Path


class PlanDiffRequest(APIModel):
    """Select two complete frozen plans for deterministic comparison."""

    left_run_spec: Path
    left_repository_root: Path
    right_run_spec: Path
    right_repository_root: Path


class PlanDiffSuccess(SuccessModel):
    """Return every leaf value that differs between two frozen plans."""

    operation: Literal["plan_diff"] = "plan_diff"  # pyright: ignore[reportIncompatibleVariableOverride]
    left_run_id: RunId
    right_run_id: RunId
    identical: bool
    changes: tuple[PlanChange, ...]


class StatusRequest(PathRequest):
    """Select one durable local attempt journal."""


class StatusSuccess(SuccessModel):
    """Return the latest durable attempt state and its valid successors."""

    operation: Literal["status"] = "status"  # pyright: ignore[reportIncompatibleVariableOverride]
    path: Path
    entry_count: int
    state: AttemptState | None
    event: str | None
    recorded_at: datetime | None
    details: dict[str, Any]
    next_states: tuple[AttemptState, ...]
    terminal: bool


class VerificationRequest(PathRequest):
    """Select a document and source repositories trusted to supply code."""

    trusted_source_repositories: frozenset[str] = Field(min_length=1)


class VerifyRunRequest(VerificationRequest):
    """Select one terminal run for complete verification."""


class VerifyRunSuccess(SuccessModel):
    """Summarize one verified terminal run."""

    operation: Literal["verify_run"] = "verify_run"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    run_status: str
    successful_attempt_id: int | None
    stage_ids: tuple[StageId, ...]
    measurement_count: int


class LineageRequest(VerificationRequest):
    """Select one terminal run whose verified upstream lineage is requested."""


class LineageSuccess(SuccessModel):
    """Return the verified upstream graph of one successful run."""

    operation: Literal["lineage"] = "lineage"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]


class CompareRunsRequest(APIModel):
    """Select two terminal runs and the repositories trusted to supply code."""

    left_path: Path
    right_path: Path
    trusted_source_repositories: frozenset[str] = Field(min_length=1)


class CompareRunsSuccess(SuccessModel):
    """Return every connected-evidence difference between two verified runs."""

    operation: Literal["compare_runs"] = "compare_runs"  # pyright: ignore[reportIncompatibleVariableOverride]
    left_run_id: RunId
    right_run_id: RunId
    identical: bool
    changes: tuple[RunChange, ...]


class VerifyBenchmarkRequest(VerificationRequest):
    """Select one benchmark result for verification."""


class VerifyBenchmarkSuccess(SuccessModel):
    """Summarize one verified benchmark result."""

    operation: Literal["verify_benchmark"] = "verify_benchmark"  # pyright: ignore[reportIncompatibleVariableOverride]
    benchmark_id: str
    run_id: RunId
    benchmark_status: str
    confirmation_attempt_id: int


class VerifyPointerRequest(VerificationRequest):
    """Select one promoted artifact pointer for verification."""


class VerifyPointerSuccess(SuccessModel):
    """Summarize one verified promoted artifact."""

    operation: Literal["verify_pointer"] = "verify_pointer"  # pyright: ignore[reportIncompatibleVariableOverride]
    file_count: int


class SchemaRequest(APIModel):
    """Select one public schema by its registered name."""

    name: str = Field(min_length=1)


class SchemaSuccess(SuccessModel):
    """Return one registered JSON Schema."""

    operation: Literal["get_schema"] = "get_schema"  # pyright: ignore[reportIncompatibleVariableOverride]
    name: str
    json_schema: dict[str, Any]


class CapabilitiesRequest(APIModel):
    """Request the installed operation and backend inventory."""


class CapabilitiesSuccess(SuccessModel):
    """Return installed API operations and execution backends."""

    operation: Literal["get_capabilities"] = "get_capabilities"  # pyright: ignore[reportIncompatibleVariableOverride]
    protocol_version: int
    operations: tuple[OperationName, ...]
    schemas: tuple[str, ...]
    execution_backends: tuple[str, ...]


class InitProjectRequest(APIModel):
    """Select an absent or empty project root and its import package name."""

    path: Path
    package: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class InitProjectSuccess(SuccessModel):
    """Report the root and files written for one starter project."""

    operation: Literal["init_project"] = "init_project"  # pyright: ignore[reportIncompatibleVariableOverride]
    project_root: Path
    files: tuple[Path, ...]


SCHEMA_REGISTRY: dict[str, Any] = {
    "ArtifactPointer": ArtifactPointer,
    "BenchmarkResult": BenchmarkResult,
    "CapabilitiesRequest": CapabilitiesRequest,
    "CapabilitiesSuccess": CapabilitiesSuccess,
    "ExecuteStageRequest": ExecuteStageRequest,
    "ExecuteStageSuccess": ExecuteStageSuccess,
    "ExecuteBenchmarkRequest": ExecuteBenchmarkRequest,
    "ExecuteBenchmarkSuccess": ExecuteBenchmarkSuccess,
    "FreezeRunRequest": FreezeRunRequest,
    "FreezeRunSuccess": FreezeRunSuccess,
    "InitProjectRequest": InitProjectRequest,
    "InitProjectSuccess": InitProjectSuccess,
    "LineageRequest": LineageRequest,
    "LineageSuccess": LineageSuccess,
    "CompareRunsRequest": CompareRunsRequest,
    "CompareRunsSuccess": CompareRunsSuccess,
    "PlanDiffRequest": PlanDiffRequest,
    "PlanDiffSuccess": PlanDiffSuccess,
    "StatusRequest": StatusRequest,
    "StatusSuccess": StatusSuccess,
    "PreflightRequest": PreflightRequest,
    "PreflightSuccess": PreflightSuccess,
    "ResolvedRun": ResolvedRun,
    "RunRequest": RunRequest,
    "RunSuccess": RunSuccess,
    "RetryRequest": RetryRequest,
    "RetrySuccess": RetrySuccess,
    "RunSpec": RunSpec,
    "SchemaRequest": SchemaRequest,
    "SchemaSuccess": SchemaSuccess,
    "Spec": Spec,
    "ValidateResolvedStageRequest": ValidateResolvedStageRequest,
    "ValidateResolvedStageSuccess": ValidateResolvedStageSuccess,
    "ValidateRunSpecRequest": ValidateRunSpecRequest,
    "ValidateRunSpecSuccess": ValidateRunSpecSuccess,
    "ValidateStageRequest": ValidateStageRequest,
    "ValidateStageSuccess": ValidateStageSuccess,
    "VerifyBenchmarkRequest": VerifyBenchmarkRequest,
    "VerifyBenchmarkSuccess": VerifyBenchmarkSuccess,
    "VerifyPointerRequest": VerifyPointerRequest,
    "VerifyPointerSuccess": VerifyPointerSuccess,
    "VerifyRunRequest": VerifyRunRequest,
    "VerifyRunSuccess": VerifyRunSuccess,
    "ViperFailure": ViperFailure,
}

OPERATIONS: tuple[OperationName, ...] = (
    "validate_stage",
    "validate_resolved_stage",
    "validate_run_spec",
    "freeze_run",
    "preflight",
    "execute_stage",
    "run",
    "retry",
    "execute_benchmark",
    "plan_diff",
    "lineage",
    "status",
    "compare_runs",
    "verify_run",
    "verify_benchmark",
    "verify_pointer",
    "get_schema",
    "get_capabilities",
    "init_project",
)


from ._api.handlers import (
    compare_runs,
    execute_benchmark,
    execute_stage,
    freeze_run,
    get_capabilities,
    get_schema,
    init_project,
    lineage,
    plan_diff,
    preflight,
    retry_request,
    run_request,
    status,
    validate_resolved_stage,
    validate_run_spec,
    validate_stage,
    verify_benchmark,
    verify_pointer,
    verify_run,
)

RequestType = type[APIModel]
Handler = Callable[[Any], SuccessModel]

REQUEST_REGISTRY: dict[OperationName, RequestType] = {
    "validate_stage": ValidateStageRequest,
    "validate_resolved_stage": ValidateResolvedStageRequest,
    "validate_run_spec": ValidateRunSpecRequest,
    "freeze_run": FreezeRunRequest,
    "preflight": PreflightRequest,
    "execute_stage": ExecuteStageRequest,
    "run": RunRequest,
    "retry": RetryRequest,
    "execute_benchmark": ExecuteBenchmarkRequest,
    "plan_diff": PlanDiffRequest,
    "lineage": LineageRequest,
    "status": StatusRequest,
    "compare_runs": CompareRunsRequest,
    "verify_run": VerifyRunRequest,
    "verify_benchmark": VerifyBenchmarkRequest,
    "verify_pointer": VerifyPointerRequest,
    "get_schema": SchemaRequest,
    "get_capabilities": CapabilitiesRequest,
    "init_project": InitProjectRequest,
}

HANDLER_REGISTRY: dict[OperationName, Handler] = {
    "validate_stage": validate_stage,
    "validate_resolved_stage": validate_resolved_stage,
    "validate_run_spec": validate_run_spec,
    "freeze_run": freeze_run,
    "preflight": preflight,
    "execute_stage": execute_stage,
    "run": run_request,
    "retry": retry_request,
    "execute_benchmark": execute_benchmark,
    "plan_diff": plan_diff,
    "lineage": lineage,
    "status": status,
    "compare_runs": compare_runs,
    "verify_run": verify_run,
    "verify_benchmark": verify_benchmark,
    "verify_pointer": verify_pointer,
    "get_schema": get_schema,
    "get_capabilities": get_capabilities,
    "init_project": init_project,
}


def dispatch(
    operation: OperationName,
    payload: Mapping[str, Any],
) -> SuccessModel | ViperFailure:
    """Validate one raw request and return a typed success or failure."""
    request_type = REQUEST_REGISTRY[operation]
    try:
        request = request_type.model_validate(payload)
    except ValidationError as exc:
        return ViperFailure(
            operation=operation,
            origin="request",
            code="invalid_request",
            message="request failed schema validation",
            details={
                "errors": exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            },
        )
    try:
        return HANDLER_REGISTRY[operation](request)
    except ViperError as exc:
        return exc.failure
    except Exception:
        return ViperFailure(
            operation=operation,
            origin="internal",
            code="internal_error",
            message="unexpected application failure",
        )


def result_json_bytes(result: APIModel) -> bytes:
    """Encode one API result as deterministic UTF-8 JSON."""

    def normalize(value: Any) -> Any:
        """Convert public values into one canonical JSON-compatible form."""
        if isinstance(value, BaseModel):
            return normalize(value.model_dump(mode="python"))
        if isinstance(value, Path):
            return value.as_posix()
        if isinstance(value, AnyUrl):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("public datetimes must include a timezone")
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if isinstance(value, bytes):
            return b64encode(value).decode("ascii")
        if isinstance(value, Enum):
            return normalize(value.value)
        if isinstance(value, Mapping):
            return {
                str(key): normalize(value[key])
                for key in sorted(value, key=lambda item: str(item))
            }
        if isinstance(value, (set, frozenset)):
            normalized = [normalize(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    value = normalize(result)
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{rendered}\n".encode()


class PythonRunError(RuntimeError):
    """Report a mismatch between a launched callable and its frozen stage."""


def _stage_parser() -> argparse.ArgumentParser:
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
    arguments = _stage_parser().parse_args(None if argv is None else list(argv))
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

    return run_request(
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
    return retry_request(
        RetryRequest(
            run_spec=selected,
            repository_root=root,
            timeout_seconds=timeout_seconds,
        )
    )


__all__ = [
    "APIModel",
    "CapabilitiesRequest",
    "CapabilitiesSuccess",
    "CompareRunsRequest",
    "CompareRunsSuccess",
    "ExecuteStageRequest",
    "ExecuteStageSuccess",
    "ExecuteBenchmarkRequest",
    "ExecuteBenchmarkSuccess",
    "ErrorCode",
    "FailureOrigin",
    "FreezeRunRequest",
    "FreezeRunSuccess",
    "InitProjectRequest",
    "InitProjectSuccess",
    "LineageRequest",
    "LineageSuccess",
    "OperationName",
    "PythonRunError",
    "PlanDiffRequest",
    "PlanDiffSuccess",
    "PreflightRequest",
    "PreflightSuccess",
    "RunRequest",
    "RunSuccess",
    "RetryRequest",
    "RetrySuccess",
    "SchemaRequest",
    "SchemaSuccess",
    "StatusRequest",
    "StatusSuccess",
    "SuccessModel",
    "ValidateResolvedStageRequest",
    "ValidateResolvedStageSuccess",
    "ValidateRunSpecRequest",
    "ValidateRunSpecSuccess",
    "ValidateStageRequest",
    "ValidateStageSuccess",
    "VerifyBenchmarkRequest",
    "VerifyBenchmarkSuccess",
    "VerifyPointerRequest",
    "VerifyPointerSuccess",
    "VerifyRunRequest",
    "VerifyRunSuccess",
    "ViperError",
    "ViperFailure",
    "compare_runs",
    "dispatch",
    "execute_stage",
    "execute_benchmark",
    "freeze_run",
    "get_capabilities",
    "init_project",
    "get_schema",
    "lineage",
    "plan_diff",
    "preflight",
    "result_json_bytes",
    "retry",
    "run",
    "status",
    "validate_resolved_stage",
    "validate_run_spec",
    "validate_stage",
    "verify_benchmark",
    "verify_pointer",
    "verify_run",
]
