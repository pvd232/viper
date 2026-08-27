"""Pydantic models for the active VIPER provenance protocol.

The model graph separates execution requests, resolved data artifacts,
the exact Git source tree, requested environments, observed execution
conditions, and immutable stage-result snapshots.
"""

# Temporary re-exports keep intermediate extraction commits executable. This
# module is deleted after every protocol type has one final owner.
# ruff: noqa: F401

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    Field,
    model_validator,
)

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
    BenchmarkId,
    DataRole,
    EvaluationId,
    NonEmptyStr,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
    RepoRelPath,
    RNGSeed,
    repo_file_paths_overlap,
)
from ._schema import NormalizedDistributionName as NormalizedDistributionName
from ._schema import SelectionName as SelectionName
from .artifacts import ArtifactLoaderRef as ArtifactLoaderRef
from .artifacts import ArtifactPointer as ArtifactPointer
from .artifacts import (
    ArtifactSpec,
    ResolvedArtifact,
    StageArtifactRef,
)
from .artifacts import BundleArtifactSpec as BundleArtifactSpec
from .artifacts import ResolvedBundleArtifact as ResolvedBundleArtifact
from .artifacts import ResolvedBundleMember as ResolvedBundleMember
from .artifacts import ResolvedSingleFileArtifact as ResolvedSingleFileArtifact
from .artifacts import SingleFileArtifactSpec as SingleFileArtifactSpec
from .http import BuiltinHttpTransportSpec as BuiltinHttpTransportSpec
from .http import EnvironmentSecretRef as EnvironmentSecretRef
from .http import ExternalExecutableSpec as ExternalExecutableSpec
from .http import HttpHeaderName as HttpHeaderName
from .http import HttpOrigin as HttpOrigin
from .http import (
    HttpRequestSpec,
    HttpRetrievalContextBinding,
    HttpRetrievalPolicy,
    HttpTransportSpec,
    ResolvedHttpRetrieval,
)
from .http import HttpTransportImplementationRef as HttpTransportImplementationRef
from .http import ObservedHttpResponse as ObservedHttpResponse
from .http import ProjectHttpTransportSpec as ProjectHttpTransportSpec
from .http import ResolvedExternalExecutable as ResolvedExternalExecutable
from .http import ResolvedHttpTransport as ResolvedHttpTransport
from .http import http_origin as http_origin
from .ids import (
    ExperimentId,
    FactorId,
    HumanId,
    InputName,
    LevelId,
    MetricId,
    ReplicateId,
    RunId,
    StageId,
    VariantId,
)
from .metrics import FloatComparator as FloatComparator
from .metrics import Measurement as Measurement
from .metrics import MetricDependency as MetricDependency
from .metrics import MetricExecutionReceipt as MetricExecutionReceipt
from .metrics import MetricImplementationRef as MetricImplementationRef
from .metrics import MetricKind as MetricKind
from .metrics import MetricMode as MetricMode
from .metrics import (
    MetricSpec,
)
from .metrics import MetricVerificationReceipt as MetricVerificationReceipt
from .metrics import ResolvedMetricDependency as ResolvedMetricDependency
from .parameters import ParameterModelRef as ParameterModelRef
from .references import (
    ArtifactPointerRef,
    GitSource,
    LocalStageResultSnapshotRef,
    ResolvedArtifactPointerRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StageResultSnapshotRef,
)
from .references import GitFileRef as GitFileRef
from .references import HuggingFaceFileRef as HuggingFaceFileRef
from .references import LocalFileRef as LocalFileRef
from .references import ResolvedBenchmarkResultRef as ResolvedBenchmarkResultRef
from .references import StorageModel as StorageModel
from .references import StorageRef as StorageRef
from .resume import DataLoaderConfiguration as DataLoaderConfiguration
from .resume import DataLoaderResumeState as DataLoaderResumeState
from .resume import LegacyNumPyRNGState as LegacyNumPyRNGState
from .resume import MainProcessRNGState as MainProcessRNGState
from .resume import NumPyRNGState as NumPyRNGState
from .resume import PCG64GeneratorState as PCG64GeneratorState
from .resume import PCG64InternalState as PCG64InternalState
from .resume import PythonRNGState as PythonRNGState
from .resume import ResumeState as ResumeState
from .runtime import ComputeBackendContext as ComputeBackendContext
from .runtime import ComputeSpec as ComputeSpec
from .runtime import CPUBackendContext as CPUBackendContext
from .runtime import CPUComputeSpec as CPUComputeSpec
from .runtime import CPUContext as CPUContext
from .runtime import CUDABackendContext as CUDABackendContext
from .runtime import CUDAComputeSpec as CUDAComputeSpec
from .runtime import CUDADeviceContext as CUDADeviceContext
from .runtime import (
    EnvironmentSpec,
    ExecutionContext,
    GCEEnvironmentSpec,
    GCEHostContext,
    ProcessStartupReceipt,
    ReproducibilitySpec,
    ResolvedEnvironment,
    ResolvedGCEEnvironment,
)
from .runtime import GCEBootImageRef as GCEBootImageRef
from .runtime import GCEMachineImageRef as GCEMachineImageRef
from .runtime import GCEProvisioningRef as GCEProvisioningRef
from .runtime import GeneratorFamily as GeneratorFamily
from .runtime import GeneratorInitializationReceipt as GeneratorInitializationReceipt
from .runtime import HostContext as HostContext
from .runtime import LocalEnvironmentSpec as LocalEnvironmentSpec
from .runtime import LocalHostContext as LocalHostContext
from .runtime import NativeLibraryContext as NativeLibraryContext
from .runtime import NativeThreadPoolContext as NativeThreadPoolContext
from .runtime import NumericalRuntimeContext as NumericalRuntimeContext
from .runtime import NumPyRandomnessSpec as NumPyRandomnessSpec
from .runtime import ParallelismSpec as ParallelismSpec
from .runtime import PythonDistributionSpec as PythonDistributionSpec
from .runtime import PythonEnvironmentSpec as PythonEnvironmentSpec
from .runtime import RandomnessContext as RandomnessContext
from .runtime import ResolvedLocalEnvironment as ResolvedLocalEnvironment
from .runtime import StartupVariable as StartupVariable
from .runtime import TorchDeterminismSpec as TorchDeterminismSpec
from .runtime import TorchPrecisionSpec as TorchPrecisionSpec
from .stages import (
    BaseSpec,
    BuildSpec,
    DownloadSpec,
    EmbedSpec,
    EvaluateSpec,
    FutureInputRef,
    InternalInputRef,
    InternalSpec,
    ParameterizedSpec,
    ResolvedBaseSpec,
    ResolvedBuildSpec,
    ResolvedDownloadSpec,
    ResolvedEvaluateSpec,
    ResolvedFutureInputRef,
    ResolvedInternalInputRef,
    ResolvedInternalSpec,
    ResolvedSpec,
    ResolvedStageRef,
    ResolvedStoredInputRef,
    ResolvedTrainSpec,
    Spec,
    StoredInputRef,
    TrainSpec,
)
from .stages import ParameterizedStageSpec as ParameterizedStageSpec
from .stages import ResolvedEmbedSpec as ResolvedEmbedSpec
from .stages import ResolvedStageInvocationRef as ResolvedStageInvocationRef
from .stages import StageContextBinding as StageContextBinding
from .stages import StageImplementationRef as StageImplementationRef
from .stages import StageInvocationReceipt as StageInvocationReceipt

# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Verified files and code
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Artifact selectors
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Requested and resolved GCE environment
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Determinism, precision, and parallelism
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Training resume state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


class MetricCriterion(ProtocolModel):
    """Define one threshold that a benchmark metric must satisfy."""

    metric_id: MetricId
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)


class BenchmarkSpec(ProtocolModel):
    """Define the fixed evaluation and criteria for a strict benchmark."""

    schema_version: Literal[1] = 1
    benchmark_id: BenchmarkId
    evaluation_id: EvaluationId
    evaluation_dataset: ArtifactPointerRef
    splits: dict[InputName, ArtifactPointerRef] = Field(min_length=1)
    metrics: tuple[MetricCriterion, ...] = Field(min_length=1)
    execution_count: Literal[2] = 2

    @model_validator(mode="after")
    def validate_unique_metrics(self) -> BenchmarkSpec:
        """Require one criterion per benchmark metric."""
        metric_ids = tuple(criterion.metric_id for criterion in self.metrics)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("benchmark metric IDs must be unique")
        return self


# ---------------------------------------------------------------------------
# Experiment specs
# ---------------------------------------------------------------------------


class FactorSpec(ProtocolModel):
    """Declare one experimental factor and its permitted levels."""

    factor_id: FactorId
    levels: tuple[LevelId, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_unique_levels(self) -> FactorSpec:
        """Require unique levels within the factor."""
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("level IDs must be unique within a factor")
        return self


class ReplicateSpec(ProtocolModel):
    """Identify one experimental replicate and its global seed."""

    replicate_id: ReplicateId
    seed: RNGSeed


class ExperimentSpec(ProtocolModel):
    """Declare the factors, variants, replicates, and metrics in an experiment."""

    schema_version: Literal[1] = 1
    experiment_id: ExperimentId

    factors: tuple[FactorSpec, ...]
    variant_ids: tuple[VariantId, ...] = Field(min_length=1)
    replicates: tuple[ReplicateSpec, ...] = Field(min_length=1)
    metrics: tuple[MetricSpec, ...]

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ExperimentSpec:
        """Require unique factor, variant, replicate, seed, and metric identities."""
        factor_ids = tuple(factor.factor_id for factor in self.factors)
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("factor IDs must be unique")

        if len(set(self.variant_ids)) != len(self.variant_ids):
            raise ValueError("variant IDs must be unique")

        replicate_ids = tuple(replicate.replicate_id for replicate in self.replicates)
        if len(set(replicate_ids)) != len(replicate_ids):
            raise ValueError("replicate IDs must be unique")

        replicate_seeds = tuple(replicate.seed for replicate in self.replicates)
        if len(set(replicate_seeds)) != len(replicate_seeds):
            raise ValueError("replicate seeds must be unique")

        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("metric IDs must be unique")

        return self


# ---------------------------------------------------------------------------
# Run primitives
# ---------------------------------------------------------------------------

AttemptStatus = Literal[
    "succeeded",
    "failed",
    "preempted",
    "cancelled",
]

AttemptPurpose = Literal["run", "benchmark_confirmation"]
AttemptFailureCode = Literal[
    "preflight_failed",
    "execution_failed",
    "verification_failed",
    "publication_failed",
    "cancelled",
    "preempted",
    "coordinator_lost",
    "internal_error",
]


class AttemptFailure(ProtocolModel):
    """Identify the operation that terminated one unsuccessful attempt."""

    code: AttemptFailureCode
    stage_id: StageId | None
    message: NonEmptyStr
    occurred_at: AwareDatetime


class AttemptJournalRef(ResolvedFileRef):
    """Identify one immutable attempt journal."""

    kind: Literal["attempt_journal"] = "attempt_journal"


class RunAttempt(ProtocolModel):
    """Record the status and published files of one run attempt."""

    attempt_id: int = Field(ge=1)
    purpose: AttemptPurpose
    status: AttemptStatus

    started_at: AwareDatetime
    completed_at: AwareDatetime

    resolved_stages: tuple[ResolvedStageRef, ...]
    invocations: tuple[ResolvedStageInvocationRef, ...]
    journal: AttemptJournalRef
    measurement_files: tuple[ResolvedFileRef, ...]
    metric_verification_files: tuple[ResolvedFileRef, ...] = ()
    log_files: tuple[ResolvedFileRef, ...]

    failure: AttemptFailure | None

    @model_validator(mode="after")
    def validate_common_invariants(self) -> RunAttempt:
        """Enforce attempt outcome, timing, stage, and file invariants."""
        if self.status == "succeeded" and self.failure is not None:
            raise ValueError("successful attempts must not have failure evidence")

        if self.status == "succeeded" and not self.resolved_stages:
            raise ValueError("successful attempts must contain a completed stage")

        if self.status != "succeeded" and self.failure is None:
            raise ValueError(
                "failed, preempted, and cancelled attempts require failure evidence"
            )

        if self.failure is not None:
            if self.failure.occurred_at > self.completed_at:
                raise ValueError("attempt failure cannot follow attempt completion")
            if self.failure.occurred_at < self.started_at:
                raise ValueError("attempt failure cannot precede attempt start")
            expected_code = {
                "failed": {
                    "preflight_failed",
                    "execution_failed",
                    "verification_failed",
                    "publication_failed",
                    "coordinator_lost",
                    "internal_error",
                },
                "cancelled": {"cancelled"},
                "preempted": {"preempted"},
            }
            if (
                self.status != "succeeded"
                and self.failure.code not in expected_code[self.status]
            ):
                raise ValueError("attempt failure code differs from terminal status")

        if self.completed_at <= self.started_at:
            raise ValueError("attempt completion must be after attempt start")

        unique = set()
        snapshots: set[StageResultSnapshotRef | LocalStageResultSnapshotRef] = set()
        for stage in self.resolved_stages:
            if stage.stage_id in unique:
                raise ValueError("resolved stage IDs must be unique")
            unique.add(stage.stage_id)

            if stage.snapshot in snapshots:
                raise ValueError("resolved stages must use distinct snapshots")
            snapshots.add(stage.snapshot)

        measurement_locations = tuple(
            reference.stored_at for reference in self.measurement_files
        )
        if len(set(measurement_locations)) != len(measurement_locations):
            raise ValueError("measurement file storage locations must be unique")

        log_locations = tuple(reference.stored_at for reference in self.log_files)
        if len(set(log_locations)) != len(log_locations):
            raise ValueError("log file storage locations must be unique")

        if set(measurement_locations) & set(log_locations):
            raise ValueError("measurement and log storage locations must be disjoint")

        metric_locations = tuple(
            reference.stored_at for reference in self.metric_verification_files
        )
        if len(set(metric_locations)) != len(metric_locations):
            raise ValueError("metric verification file locations must be unique")
        if set(metric_locations) & (set(measurement_locations) | set(log_locations)):
            raise ValueError(
                "metric verification, measurement, and log locations must be disjoint"
            )

        journal_location = self.journal.stored_at
        if journal_location in (
            set(measurement_locations) | set(log_locations) | set(metric_locations)
        ):
            raise ValueError("attempt journal location must be distinct")

        invocation_locations = tuple(
            reference.stored_at for reference in self.invocations
        )
        if len(set(invocation_locations)) != len(invocation_locations):
            raise ValueError("invocation receipt storage locations must be unique")

        return self


class ResolvedAttemptRef(ResolvedFileRef):
    """Identify one canonical immutable RunAttempt document."""

    kind: Literal["resolved_attempt"] = "resolved_attempt"


class RunStageRef(ProtocolModel):
    """Identifies and verifies one stage spec in a run-plan snapshot."""

    stage_id: StageId
    spec: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class RunSpec(ProtocolModel):
    """Freeze one run plan and its ordered stage specifications."""

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None

    seed: RNGSeed
    source: GitSource
    environment: EnvironmentSpec
    reproducibility: ReproducibilitySpec

    stages: tuple[RunStageRef, ...] = Field(min_length=1)
    estimator: StageArtifactRef

    @model_validator(mode="after")
    def validate_common_invariants(self) -> RunSpec:
        """Enforce ordered-stage identity and estimator selection invariants."""
        stage_ids = tuple(stage.stage_id for stage in self.stages)
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("stage IDs must be unique")

        stage_spec_paths = tuple(stage.spec for stage in self.stages)
        if len(set(stage_spec_paths)) != len(stage_spec_paths):
            raise ValueError("stage spec paths must be unique")

        run_root = (
            f"experiments/{self.experiment_id}/runs/{self.variant_id}/{self.run_id}"
        )
        for stage in self.stages:
            expected_path = f"{run_root}/stages/{stage.stage_id}/spec.yaml"
            if stage.spec != expected_path:
                raise ValueError(
                    f"stage {stage.stage_id!r} spec must use its canonical run path"
                )

        if self.estimator.stage_id not in set(stage_ids):
            raise ValueError("estimator must select a declared run stage")

        if self.estimator.artifact_name != PARAMETERS:
            raise ValueError("estimator must select the parameters artifact")

        return self


class ResolvedRun(ProtocolModel):
    """Reference every attempt and record the terminal outcome of one run."""

    schema_version: Literal[1] = 1

    spec: ResolvedRunSpecRef

    status: Literal["succeeded", "failed", "cancelled"]

    attempts: tuple[ResolvedAttemptRef, ...] = Field(min_length=1)
    successful_attempt_id: int | None

    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedRun:
        """Require the success selector only for a successful terminal run."""
        if self.status == "succeeded":
            if self.successful_attempt_id is None:
                raise ValueError("a succeeded run requires successful_attempt_id")
        elif self.successful_attempt_id is not None:
            raise ValueError(
                "successful_attempt_id must be null without a successful run"
            )

        return self


class ArtifactComparisonReceipt(ProtocolModel):
    """Record one candidate-to-confirmation artifact comparison."""

    artifact: StageArtifactRef
    candidate_stage: ResolvedStageRef
    confirmation_stage: ResolvedStageRef
    candidate_digest: SHA256
    confirmation_digest: SHA256
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> ArtifactComparisonReceipt:
        """Derive the comparison outcome from the two canonical digests."""
        if self.passed != (self.candidate_digest == self.confirmation_digest):
            raise ValueError("artifact comparison outcome differs from its digests")
        return self


class MetricCriterionReceipt(ProtocolModel):
    """Record one benchmark threshold applied to two recomputed metric values."""

    metric_id: MetricId
    candidate_verification: ResolvedFileRef
    confirmation_verification: ResolvedFileRef
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)
    passed: bool


class BenchmarkResult(ProtocolModel):
    """Record the independent confirmation and outcome of a benchmark."""

    schema_version: Literal[1] = 1
    benchmark: ResolvedBenchmarkSpecRef
    run: ResolvedRunRef
    confirmation: ResolvedAttemptRef
    artifacts: tuple[ArtifactComparisonReceipt, ...] = Field(min_length=2)
    metrics: tuple[MetricCriterionReceipt, ...] = Field(min_length=1)
    status: Literal["passed", "failed"]
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_receipt_sets(self) -> BenchmarkResult:
        """Require unique artifact selectors and metric criteria."""
        artifacts = tuple(
            (receipt.artifact.stage_id, receipt.artifact.artifact_name)
            for receipt in self.artifacts
        )
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("benchmark artifact comparisons must be unique")
        metrics = tuple(receipt.metric_id for receipt in self.metrics)
        if len(set(metrics)) != len(metrics):
            raise ValueError("benchmark metric criteria must be unique")
        return self


# ---------------------------------------------------------------------------
# Observed execution context
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stage input references
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stage specifications
# ---------------------------------------------------------------------------


class DownloadVariantStageParams(ProtocolModel):
    """Bind one download stage to its selected variant parameters."""

    kind: Literal["download"] = "download"
    stage_id: StageId
    params: parameters.Download


class BuildVariantStageParams(ProtocolModel):
    """Bind one build stage to its selected variant parameters."""

    kind: Literal["build"] = "build"
    stage_id: StageId
    params: parameters.Build


class EmbedVariantStageParams(ProtocolModel):
    """Bind one embedding stage to its selected variant parameters."""

    kind: Literal["embed"] = "embed"
    stage_id: StageId
    params: parameters.Embed


class TrainVariantStageParams(ProtocolModel):
    """Bind one training stage to its selected variant parameters."""

    kind: Literal["train"] = "train"
    stage_id: StageId
    params: parameters.Train


class EvaluateVariantStageParams(ProtocolModel):
    """Bind one evaluation stage to its selected variant parameters."""

    kind: Literal["evaluate"] = "evaluate"
    stage_id: StageId
    params: parameters.Evaluate


VariantStageParams = Annotated[
    DownloadVariantStageParams
    | BuildVariantStageParams
    | EmbedVariantStageParams
    | TrainVariantStageParams
    | EvaluateVariantStageParams,
    Field(discriminator="kind"),
]


class VariantSpec(ProtocolModel):
    """Assign factor levels and typed stage parameters to one variant."""

    schema_version: Literal[1] = 1
    experiment_id: ExperimentId
    variant_id: VariantId
    levels: dict[FactorId, LevelId]
    stage_params: tuple[VariantStageParams, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_stage_ids(self) -> VariantSpec:
        """Require one variant-parameter record per stage."""
        stage_ids = tuple(stage.stage_id for stage in self.stage_params)
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("variant stage IDs must be unique")
        return self


# ---------------------------------------------------------------------------
# Resolved input refs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Resolved execution records
# ---------------------------------------------------------------------------
