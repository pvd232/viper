"""Expose VIPER operations through one typed Python API."""

from __future__ import annotations

import hashlib
import inspect
import json
from argparse import ArgumentParser
from base64 import b64encode
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from ._contract_traceability import RepoSymbolRef
from ._system_impact.workflow import (
    WorkingTreeImpactError,
    analyze_working_tree_impact,
    analyze_working_tree_rename,
    plan_working_tree_rename,
)
from .artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
)
from .authoring import freeze_run_plan, load_run_plan_draft
from .benchmark import BenchmarkResult
from .execution._benchmark import benchmark as execute_benchmark_run
from .execution._restore import restore as restore_run_artifacts
from .execution._run import run as execute_run
from .execution._stage import StageExecutionError, execute_stage_process
from .execution.errors import BenchmarkExecutionError, RestoreError, RunError
from .ids import RunId, StageId
from .inspection import (
    InspectionError,
    LineageEdge,
    LineageNode,
    PlanChange,
    RunChange,
)
from .inspection import attempt_status as inspect_attempt_status
from .inspection import compare_runs as compare_verified_runs
from .inspection import lineage as build_lineage
from .inspection import plan_diff as compare_frozen_plans
from .journal import AttemptState
from .preflight import PreflightCheck, preflight_plan
from .project import InitError, RootError, init, resolve_root
from .references import ResolvedRunRef
from .restoration import (
    ArtifactRestoreSelector,
    RestoreResult,
    ViperCloudRunUri,
)
from .runs import (
    ResolvedRun,
    RunSpec,
)
from .serialization import load_resolved_stage, load_stage_spec, parse_yaml_bytes
from .stages import (
    ParameterizedSpec,
    Spec,
    stage_definition,
    verify_stage_implementation_bytes,
)
from .storage import LocalArtifactStore
from .system_impact.explain import (
    DependencyEvidence,
    ImpactPathSearch,
    explain_plan_check,
)
from .system_impact.models import CommitId, PlanCheck, SourceGraph
from .system_impact.rename import (
    DependentRename,
    ReferenceKind,
    ReferenceSite,
    RenameAnalysisError,
    RenameCheck,
    RenameObligationSet,
    rename_worklist_sites,
    render_rename_worklist,
)
from .verification import (
    verify_benchmark_result,
    verify_promoted_artifact,
    verify_run_result,
)
from .verification.models import (
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
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
    "restore",
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
    "explain_impact",
    "analyze_impact",
    "plan_rename",
    "get_rename_worklist",
    "check_rename",
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
    """Select one run-plan draft and its project root."""

    draft: Path
    root: Path


class FreezeRunSuccess(SuccessModel):
    """Report the canonical documents written for one frozen plan."""

    operation: Literal["freeze_run"] = "freeze_run"  # pyright: ignore[reportIncompatibleVariableOverride]
    run_id: RunId
    files: tuple[Path, ...]


class PreflightRequest(APIModel):
    """Select one local frozen plan for complete pre-execution inspection."""

    run_spec: Path
    root: Path


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
    root: Path
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
    root: Path
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
    root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteBenchmarkSuccess(SuccessModel):
    """Return one independently executed and verified benchmark result."""

    operation: Literal["execute_benchmark"] = "execute_benchmark"  # pyright: ignore[reportIncompatibleVariableOverride]
    result: BenchmarkResult
    result_path: Path


class PlanDiffRequest(APIModel):
    """Select two complete frozen plans for deterministic comparison."""

    left_run_spec: Path
    right_run_spec: Path
    left_root: Path
    right_root: Path


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

    root: Path
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
    left_root: Path
    right_root: Path
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


class ExplainImpactRequest(APIModel):
    """Select one plan check and its two source graphs for explanation."""

    check: Path = Field(description="Path to the persisted PlanCheck document.")
    baseline_graph: Path = Field(
        description="Path to the baseline SourceGraph named by the PlanCheck."
    )
    realized_graph: Path = Field(
        description="Path to the realized SourceGraph named by the PlanCheck."
    )
    targets: tuple[str, ...] = Field(
        default=(),
        description="Optional PATH:SYMBOL targets selected from PlanCheck.one_hop.",
    )


class ExplainImpactSuccess(SuccessModel):
    """Return verified direct dependency evidence for agents and tools."""

    operation: Literal["explain_impact"] = "explain_impact"  # pyright: ignore[reportIncompatibleVariableOverride]
    evidence: tuple[DependencyEvidence, ...] = Field(
        description=(
            "Verified one-hop dependency occurrences joined to source locations."
        )
    )


class AnalyzeImpactRequest(APIModel):
    """Select one Git baseline and current Python working tree for analysis."""

    root: Path = Field(
        default_factory=Path.cwd,
        description="Git repository whose current Python working tree is analyzed.",
    )
    base: str = Field(
        default="HEAD",
        min_length=1,
        description="Git revision expression resolved as the comparison baseline.",
    )
    targets: tuple[str, ...] = Field(
        min_length=1,
        description="PATH:SYMBOL declarations whose direct dependents are selected.",
    )
    artifact_root: Path | None = Field(
        default=None,
        description="Optional directory for graphs, decoded rows, and joined evidence.",
    )
    cache_root: Path | None = Field(
        default=None,
        description="Optional persistent directory for staged CodeQL cache entries.",
    )
    codeql_executable: Path | None = Field(
        default=None,
        description="Optional CodeQL executable; otherwise resolved from PATH.",
    )
    query_pack: Path | None = Field(
        default=None,
        description="Optional Python impact query pack directory.",
    )
    path_depth: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum reverse-dependency edges in one ranked path.",
    )
    path_limit: int = Field(
        default=12,
        ge=1,
        le=50,
        description="Maximum ranked candidate paths returned to the caller.",
    )
    path_expansion_budget: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum partial paths evaluated by the advisory search.",
    )

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, targets: tuple[str, ...]) -> tuple[str, ...]:
        """Reject repeated declarations before starting source analysis."""
        if len(targets) != len(set(targets)):
            raise ValueError("targets must contain unique source declarations")
        return targets


class AnalyzeImpactSuccess(SuccessModel):
    """Return direct dependencies compiled from the baseline and working tree."""

    operation: Literal["analyze_impact"] = "analyze_impact"  # pyright: ignore[reportIncompatibleVariableOverride]
    repository_root: Path = Field(
        description="Resolved Git top-level directory that supplied the working tree."
    )
    base_revision: CommitId = Field(
        description="Complete commit identifier resolved from the requested baseline."
    )
    artifact_root: Path = Field(
        description="Directory containing the persisted analysis evidence."
    )
    baseline_graph: Path = Field(
        description="Path to the receipt-bound graph for the baseline commit."
    )
    realized_graph: Path = Field(
        description="Path to the receipt-bound graph for the captured working tree."
    )
    evidence: tuple[DependencyEvidence, ...] = Field(
        description="Joined direct dependency occurrences around the selected targets."
    )
    path_search: ImpactPathSearch = Field(
        description="Bounded ranked baseline dependency paths from the targets."
    )


class RenameCheckRequest(APIModel):
    """Select one old-to-new symbol transition for exact working-tree analysis."""

    root: Path = Field(
        default_factory=Path.cwd,
        description="Git repository whose current Python working tree is checked.",
    )
    base: str = Field(
        default="HEAD",
        min_length=1,
        description="Git revision expression resolved as the rename baseline.",
    )
    old_target: RepoSymbolRef = Field(description="Baseline declaration being renamed.")
    new_target: RepoSymbolRef = Field(description="Required replacement declaration.")
    edge_kinds: tuple[ReferenceKind, ...] = Field(
        default=("imports", "calls", "reads", "writes"),
        min_length=1,
        description="Dependency operations governed by the rename.",
    )
    dependent_renames: tuple[DependentRename, ...] = Field(
        default=(),
        description="Explicit old-to-new identities for renamed dependents.",
    )
    artifact_root: Path | None = Field(
        default=None,
        description="Optional directory for graphs and rename evidence.",
    )
    cache_root: Path | None = Field(
        default=None,
        description="Optional persistent directory for staged CodeQL cache entries.",
    )
    codeql_executable: Path | None = Field(
        default=None,
        description="Optional CodeQL executable; otherwise resolved from PATH.",
    )
    query_pack: Path | None = Field(
        default=None,
        description="Optional Python impact query pack directory.",
    )


class RenamePlanRequest(RenameCheckRequest):
    """Select one rename whose baseline references form the agent worklist."""


class RenameCheckSuccess(SuccessModel):
    """Return an exact rename verdict and its persisted evidence paths."""

    operation: Literal["check_rename"] = "check_rename"  # pyright: ignore[reportIncompatibleVariableOverride]
    repository_root: Path = Field(
        description="Git top level that supplied both source snapshots."
    )
    base_revision: CommitId = Field(
        description="Exact baseline commit checked by CodeQL."
    )
    artifact_root: Path = Field(
        description="Directory containing the persisted rename evidence."
    )
    baseline_graph: Path = Field(
        description="Receipt-bound graph for the baseline commit."
    )
    realized_graph: Path = Field(
        description="Receipt-bound graph for the captured working tree."
    )
    obligations_path: Path = Field(description="Compiled baseline rename obligations.")
    check_path: Path = Field(description="Machine-readable exact rename decision.")
    report: str = Field(description="Compact agent-facing rename decision.")
    check: RenameCheck = Field(
        description="Validated rename transitions and derived verdict."
    )


class RenamePlanSuccess(SuccessModel):
    """Return the frozen baseline worklist before candidate editing."""

    operation: Literal["plan_rename"] = "plan_rename"  # pyright: ignore[reportIncompatibleVariableOverride]
    repository_root: Path = Field(
        description="Git top level that supplied the baseline."
    )
    base_revision: CommitId = Field(description="Exact baseline commit analyzed.")
    artifact_root: Path = Field(description="Directory containing plan evidence.")
    baseline_graph: Path = Field(description="Receipt-bound baseline graph.")
    obligations_path: Path = Field(description="Machine-readable frozen worklist.")
    worklist_path: Path = Field(description="Fast stdlib-only lookup index.")
    report: str = Field(description="Compact source-located worklist.")
    obligations: RenameObligationSet = Field(
        description="Validated baseline rename obligations."
    )


class RenameWorklistRequest(APIModel):
    """Select one page from an already compiled rename obligation set."""

    obligations_path: Path = Field(description="Frozen obligation-set JSON path.")
    offset: int = Field(default=0, ge=0, description="Zero-based first site index.")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum sites returned.")


class RenameWorklistSuccess(SuccessModel):
    """Return a read-only page from the persisted rename index."""

    operation: Literal["get_rename_worklist"] = "get_rename_worklist"  # pyright: ignore[reportIncompatibleVariableOverride]
    obligations_path: Path = Field(description="Loaded obligation-set path.")
    obligations_sha256: str = Field(description="Digest of the exact loaded bytes.")
    total: int = Field(ge=1, description="All indexed reference sites.")
    offset: int = Field(ge=0, description="Requested zero-based first index.")
    sites: tuple[ReferenceSite, ...] = Field(description="Selected source sites.")
    report: str = Field(description="Compact agent-facing source worklist.")


class LocalRunPath(APIModel):
    """Select a terminal run document beneath the project root."""

    kind: Literal["local_path"] = "local_path"
    path: Path


class ViperCloudRunReference(APIModel):
    """Select a terminal run from one sealed Viper Cloud revision."""

    kind: Literal["viper_cloud_uri"] = "viper_cloud_uri"
    uri: ViperCloudRunUri


RestoreRequestReference = Annotated[
    LocalRunPath | ViperCloudRunReference | ResolvedRunRef,
    Field(discriminator="kind"),
]


class RestoreRequest(APIModel):
    """Select a successful run and the artifacts to restore from it."""

    run_reference: RestoreRequestReference
    repository_root: Path
    artifacts: tuple[ArtifactRestoreSelector, ...] = ()
    output: Path | None = None


class RestoreSuccess(SuccessModel):
    """Return the files restored from one immutable run."""

    operation: Literal["restore"] = "restore"  # pyright: ignore[reportIncompatibleVariableOverride]
    result: RestoreResult


SCHEMA_REGISTRY: dict[str, Any] = {
    "ArtifactPointer": ArtifactPointer,
    "BenchmarkResult": BenchmarkResult,
    "CapabilitiesRequest": CapabilitiesRequest,
    "CapabilitiesSuccess": CapabilitiesSuccess,
    "ExecuteStageRequest": ExecuteStageRequest,
    "ExecuteStageSuccess": ExecuteStageSuccess,
    "ExecuteBenchmarkRequest": ExecuteBenchmarkRequest,
    "ExecuteBenchmarkSuccess": ExecuteBenchmarkSuccess,
    "RestoreRequest": RestoreRequest,
    "RestoreSuccess": RestoreSuccess,
    "ExplainImpactRequest": ExplainImpactRequest,
    "ExplainImpactSuccess": ExplainImpactSuccess,
    "AnalyzeImpactRequest": AnalyzeImpactRequest,
    "AnalyzeImpactSuccess": AnalyzeImpactSuccess,
    "RenameCheckRequest": RenameCheckRequest,
    "RenameCheckSuccess": RenameCheckSuccess,
    "RenamePlanRequest": RenamePlanRequest,
    "RenamePlanSuccess": RenamePlanSuccess,
    "RenameWorklistRequest": RenameWorklistRequest,
    "RenameWorklistSuccess": RenameWorklistSuccess,
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
    "restore",
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
    "explain_impact",
    "analyze_impact",
    "plan_rename",
    "get_rename_worklist",
    "check_rename",
)


def _load_model(path: Path, model_type: type[BaseModel]) -> BaseModel:
    """Load one local YAML document through its concrete Pydantic model."""
    return model_type.model_validate(parse_yaml_bytes(path.read_bytes()))


def _document_error(
    operation: OperationName,
    path: Path,
    exc: Exception,
) -> ViperError:
    """Translate a local document failure into the stable API model."""
    if isinstance(exc, FileNotFoundError):
        code: ErrorCode = "not_found"
        message = "document path does not exist"
    elif isinstance(exc, OSError):
        code = "io_failed"
        message = "document could not be read"
    else:
        code = "invalid_document"
        message = "document failed schema validation"
    return ViperError(
        ViperFailure(
            operation=operation,
            origin="application",
            code=code,
            message=message,
            details={"path": path.as_posix()},
        )
    )


def _root(root: Path, operation: OperationName) -> Path:
    """Resolve one operation root or raise its stable API failure."""
    try:
        return resolve_root(root)
    except RootError as error:
        raise ViperError(
            ViperFailure(
                operation=operation,
                origin="application",
                code="invalid_document",
                message="project root is invalid",
                details={
                    "root": root.as_posix(),
                },
            )
        ) from error


def _local_fetcher(
    project_root: Path,
    fetcher: StorageFetcher | None,
) -> StorageFetcher:
    """Use an injected fetcher or bind the selected project's local store."""
    if fetcher is not None:
        return fetcher
    return LocalArtifactStore(project_root).fetch


def validate_stage(request: ValidateStageRequest) -> ValidateStageSuccess:
    """Validate one authored stage document."""
    try:
        stage = load_stage_spec(request.path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_stage", request.path, exc) from exc
    return ValidateStageSuccess(path=request.path, stage_kind=stage.kind)


def validate_resolved_stage(
    request: ValidateResolvedStageRequest,
) -> ValidateResolvedStageSuccess:
    """Validate one resolved stage document."""
    try:
        stage = load_resolved_stage(request.path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_resolved_stage", request.path, exc) from exc
    return ValidateResolvedStageSuccess(path=request.path, stage_kind=stage.kind)


def validate_run_spec(request: ValidateRunSpecRequest) -> ValidateRunSpecSuccess:
    """Validate one RunSpec document and return its ordered stage identities."""
    try:
        run = _load_model(request.path, RunSpec)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_run_spec", request.path, exc) from exc
    assert isinstance(run, RunSpec)
    return ValidateRunSpecSuccess(
        path=request.path,
        run_id=run.run_id,
        stage_ids=tuple(stage.stage_id for stage in run.stages),
    )


def freeze_run(request: FreezeRunRequest) -> FreezeRunSuccess:
    """Freeze one draft into canonical stage and run documents."""
    project_root = _root(request.root, "freeze_run")
    try:
        draft = load_run_plan_draft(request.draft)
        frozen = freeze_run_plan(project_root, draft)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("freeze_run", request.draft, exc) from exc
    return FreezeRunSuccess(run_id=frozen.run.run_id, files=frozen.files)


def preflight(request: PreflightRequest) -> PreflightSuccess:
    """Inspect one complete local plan before allocating a run attempt."""
    project_root = _root(request.root, "preflight")
    report = preflight_plan(project_root, request.run_spec)
    return PreflightSuccess(
        run_id=report.run_id,
        ready=report.ready,
        checks=report.checks,
    )


def execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess:
    """Execute one selected stage and identify its declared outputs."""
    project_root = _root(request.root, "execute_stage")
    try:
        run = _load_model(request.run_spec, RunSpec)
        assert isinstance(run, RunSpec)
        reference = next(
            (stage for stage in run.stages if stage.stage_id == request.stage_id),
            None,
        )
        if reference is None:
            raise ValueError("selected stage is absent from the run plan")
        stage = load_stage_spec(project_root / reference.spec)
        if not isinstance(stage, ParameterizedSpec):
            raise ValueError("runner-owned download stages require execute_attempt")
        result = execute_stage_process(
            project_root,
            run,
            reference,
            stage,
            timeout_seconds=request.timeout_seconds,
        )
    except StageExecutionError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_stage",
                origin="application",
                code="execution_failed",
                message="stage process failed",
                details={"stage_id": request.stage_id},
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("execute_stage", request.run_spec, exc) from exc
    return ExecuteStageSuccess(
        stage_id=request.stage_id,
        command=result.command,
        artifacts=result.artifacts,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_request(request: RunRequest) -> RunSuccess:
    """Execute, publish, and verify one complete run on the active host."""
    project_root = _root(request.root, "run")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="execution_failed",
                message="run failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="verification_failed",
                message="run verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("run", request.run_spec, exc) from exc
    run = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RunSuccess(
        run_id=run.run_id,
        attempt_id=attempt_id,
        resolved_attempt=(
            result.resolved_run_path.parent
            / "attempts"
            / str(attempt_id)
            / "resolved.yaml"
        ),
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def retry_request(request: RetryRequest) -> RetrySuccess:
    """Append one attempt to a failed frozen run and verify its terminal result."""
    project_root = _root(request.root, "retry")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
            retry=True,
        )
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="execution_failed",
                message="retry failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="verification_failed",
                message="retry verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("retry", request.run_spec, exc) from exc
    run_spec = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RetrySuccess(
        run_id=run_spec.run_id,
        attempt_id=attempt_id,
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def execute_benchmark(
    request: ExecuteBenchmarkRequest,
) -> ExecuteBenchmarkSuccess:
    """Execute and verify one independent benchmark confirmation."""
    project_root = _root(request.root, "execute_benchmark")
    try:
        execution = execute_benchmark_run(
            project_root,
            request.resolved_run,
            request.benchmark_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except BenchmarkExecutionError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark execution failed",
            )
        ) from exc
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="execution_failed",
                message="benchmark confirmation failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("execute_benchmark", request.resolved_run, exc) from exc
    return ExecuteBenchmarkSuccess(
        result=execution.result,
        result_path=execution.result_path,
    )


def plan_diff(request: PlanDiffRequest) -> PlanDiffSuccess:
    """Compare two frozen plans, including their referenced stage specs."""
    left_root = _root(request.left_root, "plan_diff")
    right_root = _root(request.right_root, "plan_diff")
    try:
        result = compare_frozen_plans(
            left_root,
            request.left_run_spec,
            right_root,
            request.right_run_spec,
        )
    except (InspectionError, OSError, ValueError, yaml.YAMLError) as exc:
        raise ViperError(
            ViperFailure(
                operation="plan_diff",
                origin="application",
                code="invalid_document",
                message="frozen plans could not be compared",
                details={
                    "left_run_spec": request.left_run_spec.as_posix(),
                    "right_run_spec": request.right_run_spec.as_posix(),
                },
            )
        ) from exc
    return PlanDiffSuccess(
        left_run_id=result.left_run_id,
        right_run_id=result.right_run_id,
        identical=result.identical,
        changes=result.changes,
    )


def status(request: StatusRequest) -> StatusSuccess:
    """Return the latest durable state recorded by one attempt journal."""
    try:
        result = inspect_attempt_status(request.path)
    except (OSError, ValueError) as exc:
        raise _document_error("status", request.path, exc) from exc
    return StatusSuccess(
        path=result.journal,
        entry_count=result.entry_count,
        state=result.state,
        event=result.event,
        recorded_at=result.recorded_at,
        details=result.details,
        next_states=result.next_states,
        terminal=result.terminal,
    )


def _policy(repositories: frozenset[str]) -> VerificationPolicy:
    """Construct the verifier policy carried by one API request."""
    return VerificationPolicy(trusted_source_repositories=repositories)


def verify_run(
    request: VerifyRunRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyRunSuccess:
    """Verify one terminal run and summarize the connected evidence."""
    project_root = _root(request.root, "verify_run")
    fetcher = _local_fetcher(project_root, fetcher)
    try:
        resolved = _load_model(request.path, ResolvedRun)
        assert isinstance(resolved, ResolvedRun)
        verified = verify_run_result(
            resolved,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_run",
                origin="application",
                code="verification_failed",
                message="run verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_run", request.path, exc) from exc
    return VerifyRunSuccess(
        run_id=verified.plan.run.run_id,
        run_status=resolved.status,
        successful_attempt_id=resolved.successful_attempt_id,
        stage_ids=tuple(verified.resolved_stages),
        measurement_count=len(verified.measurements),
    )


def lineage(
    request: LineageRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> LineageSuccess:
    """Verify one terminal run and return its upstream lineage graph."""
    project_root = _root(request.root, "lineage")
    fetcher = _local_fetcher(project_root, fetcher)
    try:
        resolved = _load_model(request.path, ResolvedRun)
        assert isinstance(resolved, ResolvedRun)
        verified = verify_run_result(
            resolved,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="lineage",
                origin="application",
                code="verification_failed",
                message="run verification failed before lineage construction",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("lineage", request.path, exc) from exc
    result = build_lineage(verified)
    return LineageSuccess(
        run_id=result.run_id,
        nodes=result.nodes,
        edges=result.edges,
    )


def compare_runs(
    request: CompareRunsRequest,
    *,
    left_fetcher: StorageFetcher | None = None,
    right_fetcher: StorageFetcher | None = None,
) -> CompareRunsSuccess:
    """Verify two terminal runs and compare all of their connected evidence."""
    left_root = _root(request.left_root, "compare_runs")
    right_root = _root(request.right_root, "compare_runs")
    left_fetcher = _local_fetcher(
        left_root,
        left_fetcher,
    )
    right_fetcher = _local_fetcher(
        right_root,
        right_fetcher,
    )
    try:
        left_resolved = _load_model(request.left_path, ResolvedRun)
        right_resolved = _load_model(request.right_path, ResolvedRun)
        assert isinstance(left_resolved, ResolvedRun)
        assert isinstance(right_resolved, ResolvedRun)
        policy = _policy(request.trusted_source_repositories)
        left = verify_run_result(
            left_resolved,
            policy=policy,
            fetcher=left_fetcher,
        )
        right = verify_run_result(
            right_resolved,
            policy=policy,
            fetcher=right_fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="compare_runs",
                origin="application",
                code="verification_failed",
                message="run verification failed before comparison",
                details={
                    "left_path": request.left_path.as_posix(),
                    "right_path": request.right_path.as_posix(),
                },
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ViperError(
            ViperFailure(
                operation="compare_runs",
                origin="application",
                code="invalid_document",
                message="terminal runs could not be loaded",
                details={
                    "left_path": request.left_path.as_posix(),
                    "right_path": request.right_path.as_posix(),
                },
            )
        ) from exc
    result = compare_verified_runs(left, right)
    return CompareRunsSuccess(
        left_run_id=result.left_run_id,
        right_run_id=result.right_run_id,
        identical=result.identical,
        changes=result.changes,
    )


def verify_benchmark(
    request: VerifyBenchmarkRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyBenchmarkSuccess:
    """Verify one benchmark result and summarize its confirmation."""
    project_root = _root(request.root, "verify_benchmark")
    fetcher = _local_fetcher(project_root, fetcher)
    try:
        result = _load_model(request.path, BenchmarkResult)
        assert isinstance(result, BenchmarkResult)
        verified = verify_benchmark_result(
            result,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_benchmark", request.path, exc) from exc
    benchmark = verified.run.plan.benchmark
    assert benchmark is not None
    return VerifyBenchmarkSuccess(
        benchmark_id=benchmark.benchmark_id,
        run_id=verified.run.plan.run.run_id,
        benchmark_status=result.status,
        confirmation_attempt_id=verified.confirmation.attempt_id,
    )


def verify_pointer(
    request: VerifyPointerRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyPointerSuccess:
    """Verify one promoted artifact and report its physical file count."""
    project_root = _root(request.root, "verify_pointer")
    fetcher = _local_fetcher(project_root, fetcher)
    try:
        pointer = _load_model(request.path, ArtifactPointer)
        assert isinstance(pointer, ArtifactPointer)
        artifact = verify_promoted_artifact(
            pointer,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_pointer",
                origin="application",
                code="verification_failed",
                message="artifact verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_pointer", request.path, exc) from exc
    return VerifyPointerSuccess(file_count=len(artifact.files))


def get_schema(request: SchemaRequest) -> SchemaSuccess:
    """Return JSON Schema for one explicitly registered public type."""
    model = SCHEMA_REGISTRY.get(request.name)
    if model is None:
        raise ViperError(
            ViperFailure(
                operation="get_schema",
                origin="application",
                code="invalid_request",
                message="schema name is not registered",
                details={"name": request.name},
            )
        )
    return SchemaSuccess(
        name=request.name,
        json_schema=TypeAdapter(model).json_schema(),
    )


def get_capabilities(request: CapabilitiesRequest) -> CapabilitiesSuccess:
    """Return installed operations and available execution backends."""
    del request
    return CapabilitiesSuccess(
        protocol_version=1,
        operations=OPERATIONS,
        schemas=tuple(sorted(SCHEMA_REGISTRY)),
        execution_backends=("trusted_local",),
    )


def init_project(request: InitProjectRequest) -> InitProjectSuccess:
    """Generate one runnable five-stage starter project."""
    try:
        files = init(request.path, request.package)
    except InitError as exc:
        occupied = request.path.exists() and (
            not request.path.is_dir() or any(request.path.iterdir())
        )
        code: ErrorCode = "write_conflict" if occupied else "io_failed"
        raise ViperError(
            ViperFailure(
                operation="init_project",
                origin="application",
                code=code,
                message=str(exc),
                details={"path": request.path.as_posix()},
            )
        ) from exc
    return InitProjectSuccess(
        project_root=request.path.resolve(),
        files=files,
    )


def explain_impact(request: ExplainImpactRequest) -> ExplainImpactSuccess:
    """Load and explain one receipt-bound PlanCheck one-hop result."""
    documents = (
        (request.check, PlanCheck),
        (request.baseline_graph, SourceGraph),
        (request.realized_graph, SourceGraph),
    )
    loaded: list[BaseModel] = []
    for path, model_type in documents:
        try:
            loaded.append(_load_model(path, model_type))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise _document_error("explain_impact", path, exc) from exc
    check, baseline, realized = loaded
    assert isinstance(check, PlanCheck)
    assert isinstance(baseline, SourceGraph)
    assert isinstance(realized, SourceGraph)
    try:
        evidence = explain_plan_check(
            check=check,
            baseline=baseline,
            realized=realized,
            targets=request.targets,
        )
    except ValueError as exc:
        raise ViperError(
            ViperFailure(
                operation="explain_impact",
                origin="application",
                code="verification_failed",
                message=str(exc),
                details={
                    "check": request.check.as_posix(),
                    "baseline_graph": request.baseline_graph.as_posix(),
                    "realized_graph": request.realized_graph.as_posix(),
                },
            )
        ) from exc
    return ExplainImpactSuccess(evidence=evidence)


def analyze_impact(request: AnalyzeImpactRequest) -> AnalyzeImpactSuccess:
    """Compile and explain impact from one Git baseline to the working tree."""
    try:
        result = analyze_working_tree_impact(
            request.root,
            base=request.base,
            targets=request.targets,
            artifact_root=request.artifact_root,
            cache_root=request.cache_root,
            codeql_executable=request.codeql_executable,
            query_pack=request.query_pack,
            path_depth=request.path_depth,
            path_limit=request.path_limit,
            path_expansion_budget=request.path_expansion_budget,
        )
    except WorkingTreeImpactError as exc:
        raise ViperError(
            ViperFailure(
                operation="analyze_impact",
                origin="application",
                code="execution_failed",
                message=str(exc),
                details={
                    "root": request.root.as_posix(),
                    "base": request.base,
                    "targets": list(request.targets),
                },
            )
        ) from exc
    return AnalyzeImpactSuccess(
        repository_root=result.repository_root,
        base_revision=result.base_revision,
        artifact_root=result.artifact_root,
        baseline_graph=result.baseline_graph,
        realized_graph=result.realized_graph,
        evidence=result.evidence,
        path_search=result.path_search,
    )


def get_rename_worklist(
    request: RenameWorklistRequest,
) -> RenameWorklistSuccess:
    """Read one page from a persisted baseline index without running CodeQL."""
    path = request.obligations_path.resolve()
    try:
        content = path.read_bytes()
        obligations = RenameObligationSet.model_validate_json(content)
        sites = rename_worklist_sites(
            obligations,
            offset=request.offset,
            limit=request.limit,
        )
        report = render_rename_worklist(
            obligations,
            offset=request.offset,
            limit=request.limit,
        )
    except (OSError, ValueError, RenameAnalysisError) as exc:
        raise ViperError(
            ViperFailure(
                operation="get_rename_worklist",
                origin="application",
                code="invalid_document",
                message=str(exc),
            )
        ) from exc
    total = sum(
        len(obligation.baseline_sites) for obligation in obligations.obligations
    )
    return RenameWorklistSuccess(
        obligations_path=path,
        obligations_sha256=hashlib.sha256(content).hexdigest(),
        total=total,
        offset=request.offset,
        sites=sites,
        report=report,
    )


def plan_rename(request: RenamePlanRequest) -> RenamePlanSuccess:
    """Compile one exact baseline rename worklist."""
    try:
        result = plan_working_tree_rename(
            request.root,
            base=request.base,
            old_target=request.old_target,
            new_target=request.new_target,
            edge_kinds=request.edge_kinds,
            dependent_renames=request.dependent_renames,
            artifact_root=request.artifact_root,
            cache_root=request.cache_root,
            codeql_executable=request.codeql_executable,
            query_pack=request.query_pack,
        )
    except WorkingTreeImpactError as exc:
        raise ViperError(
            ViperFailure(
                operation="plan_rename",
                origin="application",
                code="execution_failed",
                message=str(exc),
            )
        ) from exc
    return RenamePlanSuccess(
        repository_root=result.repository_root,
        base_revision=result.base_revision,
        artifact_root=result.artifact_root,
        baseline_graph=result.baseline_graph,
        obligations_path=result.obligations_path,
        worklist_path=result.worklist_path,
        report=result.report,
        obligations=result.obligations,
    )


def check_rename(request: RenameCheckRequest) -> RenameCheckSuccess:
    """Compile and verify one exact rename against the current working tree."""
    try:
        result = analyze_working_tree_rename(
            request.root,
            base=request.base,
            old_target=request.old_target,
            new_target=request.new_target,
            edge_kinds=request.edge_kinds,
            dependent_renames=request.dependent_renames,
            artifact_root=request.artifact_root,
            cache_root=request.cache_root,
            codeql_executable=request.codeql_executable,
            query_pack=request.query_pack,
        )
    except WorkingTreeImpactError as exc:
        raise ViperError(
            ViperFailure(
                operation="check_rename",
                origin="application",
                code="verification_failed",
                message=str(exc),
                details={
                    "root": request.root.as_posix(),
                    "base": request.base,
                    "old_target": str(request.old_target),
                    "new_target": str(request.new_target),
                },
            )
        ) from exc
    return RenameCheckSuccess(
        repository_root=result.repository_root,
        base_revision=result.base_revision,
        artifact_root=result.artifact_root,
        baseline_graph=result.baseline_graph,
        realized_graph=result.realized_graph,
        obligations_path=result.obligations_path,
        check_path=result.check_path,
        report=result.report,
        check=result.check,
    )


RequestType = type[APIModel]
Handler = Callable[[Any], SuccessModel]


def restore_artifacts(request: RestoreRequest) -> RestoreSuccess:
    """Restore selected artifacts through the shared execution engine."""
    project_root = _root(request.repository_root, "restore")
    selected = request.run_reference
    if isinstance(selected, LocalRunPath):
        run_reference = selected.path
    elif isinstance(selected, ViperCloudRunReference):
        run_reference = selected.uri
    else:
        run_reference = selected
    try:
        result = restore_run_artifacts(
            project_root,
            run_reference,
            artifacts=request.artifacts,
            output=request.output,
        )
    except RestoreError as exc:
        raise ViperError(
            ViperFailure(
                operation="restore",
                origin="application",
                code="verification_failed",
                message="artifact restore failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        path = selected.path if isinstance(selected, LocalRunPath) else project_root
        raise _document_error("restore", path, exc) from exc
    return RestoreSuccess(result=result)


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
    "restore": RestoreRequest,
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
    "explain_impact": ExplainImpactRequest,
    "analyze_impact": AnalyzeImpactRequest,
    "plan_rename": RenamePlanRequest,
    "get_rename_worklist": RenameWorklistRequest,
    "check_rename": RenameCheckRequest,
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
    "restore": restore_artifacts,
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
    "explain_impact": explain_impact,
    "analyze_impact": analyze_impact,
    "plan_rename": plan_rename,
    "get_rename_worklist": get_rename_worklist,
    "check_rename": check_rename,
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


def _stage_parser() -> ArgumentParser:
    """Build the argument parser used by a project stage entrypoint."""
    parser = ArgumentParser(add_help=True)
    parser.add_argument("--run", required=True, dest="run_spec", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=float)
    return parser


def run(
    stage_callable: Callable[[Any], None],
    *,
    argv: Sequence[str] | None = None,
) -> RunSuccess:
    """Bind one launched callable to a frozen stage and execute its complete run."""
    arguments = _stage_parser().parse_args(None if argv is None else list(argv))
    project_root = resolve_root(arguments.root)
    run_spec_path = arguments.run_spec

    if not run_spec_path.is_absolute():
        run_spec_path = project_root / run_spec_path

    run_spec_path = run_spec_path.resolve()
    if not run_spec_path.is_relative_to(project_root):
        raise PythonRunError("run specification is outside the project root")

    run_spec = RunSpec.model_validate(parse_yaml_bytes(run_spec_path.read_bytes()))
    selected = next(
        (stage for stage in run_spec.stages if stage.stage_id == arguments.stage),
        None,
    )

    if selected is None:
        raise PythonRunError("selected stage ID is absent from the run plan")

    stage_path = (project_root / selected.spec).resolve()
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
    if not source_path.is_relative_to(project_root):
        raise PythonRunError("launched stage callable is outside the project root")

    relative_source = source_path.relative_to(project_root).as_posix()
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
            root=project_root,
            timeout_seconds=arguments.timeout_seconds,
        )
    )


def retry(
    run_spec: Path,
    *,
    root: Path,
    timeout_seconds: float | None = None,
) -> RetrySuccess:
    """Append one attempt to a failed frozen run."""
    project_root = resolve_root(root)
    selected = run_spec if run_spec.is_absolute() else project_root / run_spec
    selected = selected.resolve()
    if not selected.is_relative_to(project_root):
        raise PythonRunError("run specification is outside the project root")
    return retry_request(
        RetryRequest(
            run_spec=selected,
            root=project_root,
            timeout_seconds=timeout_seconds,
        )
    )


__all__ = [
    "APIModel",
    "AnalyzeImpactRequest",
    "AnalyzeImpactSuccess",
    "RenameCheckRequest",
    "RenameCheckSuccess",
    "RenamePlanRequest",
    "RenamePlanSuccess",
    "RenameWorklistRequest",
    "RenameWorklistSuccess",
    "CapabilitiesRequest",
    "CapabilitiesSuccess",
    "CompareRunsRequest",
    "CompareRunsSuccess",
    "DependentRename",
    "ExecuteStageRequest",
    "ExecuteStageSuccess",
    "ExecuteBenchmarkRequest",
    "ExecuteBenchmarkSuccess",
    "ExplainImpactRequest",
    "ExplainImpactSuccess",
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
    "RestoreRequest",
    "RestoreRequestReference",
    "RestoreSuccess",
    "LocalRunPath",
    "ViperCloudRunReference",
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
    "analyze_impact",
    "check_rename",
    "compare_runs",
    "dispatch",
    "execute_stage",
    "execute_benchmark",
    "explain_impact",
    "restore_artifacts",
    "freeze_run",
    "get_capabilities",
    "get_rename_worklist",
    "init_project",
    "get_schema",
    "lineage",
    "plan_diff",
    "plan_rename",
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
