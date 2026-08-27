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
from .experiments import BuildVariantStageParams as BuildVariantStageParams
from .experiments import DownloadVariantStageParams as DownloadVariantStageParams
from .experiments import EmbedVariantStageParams as EmbedVariantStageParams
from .experiments import EvaluateVariantStageParams as EvaluateVariantStageParams
from .experiments import ExperimentSpec as ExperimentSpec
from .experiments import FactorSpec as FactorSpec
from .experiments import ReplicateSpec as ReplicateSpec
from .experiments import TrainVariantStageParams as TrainVariantStageParams
from .experiments import VariantSpec as VariantSpec
from .experiments import VariantStageParams as VariantStageParams
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
from .runs import AttemptFailure as AttemptFailure
from .runs import AttemptFailureCode as AttemptFailureCode
from .runs import AttemptJournalRef as AttemptJournalRef
from .runs import AttemptPurpose as AttemptPurpose
from .runs import AttemptStatus as AttemptStatus
from .runs import ResolvedAttemptRef as ResolvedAttemptRef
from .runs import ResolvedRun as ResolvedRun
from .runs import RunAttempt as RunAttempt
from .runs import RunSpec as RunSpec
from .runs import RunStageRef as RunStageRef
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


# ---------------------------------------------------------------------------
# Run primitives
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Resolved input refs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Resolved execution records
# ---------------------------------------------------------------------------
