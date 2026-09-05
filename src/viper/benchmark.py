"""Define benchmark specifications, criteria, comparisons, and results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ._schema import SHA256, BenchmarkId, DataRole, ProtocolModel, RepoRelPath
from .artifacts import StageArtifactRef
from .ids import EvalId, InputName, MetricId
from .metrics import MetricCriterionDraft, MetricDraft, metric_definition
from .references import (
    ResolvedArtifactPointerRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
)
from .runs import ResolvedAttemptRef


class MetricCriterion(ProtocolModel):
    """Define one threshold that a benchmark metric must satisfy."""

    metric_id: MetricId
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)


class RunArtifactDraft(BaseModel):
    """Select one artifact from a completed run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    artifact: StageArtifactRef
    path: RepoRelPath
    data_role: DataRole


class BenchmarkDraft(BaseModel):
    """Fix the inputs and metrics used by one benchmark."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    benchmark_id: BenchmarkId
    eval_id: EvalId
    test: RunArtifactDraft
    splits: dict[InputName, RunArtifactDraft] = Field(min_length=1)
    metrics: tuple[MetricDraft[Any], ...] = Field(min_length=1)
    criteria: tuple[MetricCriterionDraft, ...] = ()
    execution_count: Literal[2] = 2

    @model_validator(mode="after")
    def validate_metrics(self) -> BenchmarkDraft:
        """Require unique metrics and criteria selected from those metrics."""
        metric_ids = tuple(
            metric_definition(metric.implementation).metric_id
            for metric in self.metrics
        )
        criterion_ids = tuple(
            metric_definition(criterion.metric.implementation).metric_id
            for criterion in self.criteria
        )
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("benchmark metric IDs must be unique")
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("benchmark criterion metric IDs must be unique")
        if not set(criterion_ids) <= set(metric_ids):
            raise ValueError("benchmark criteria must select benchmark metrics")
        return self


class BenchmarkSpec(ProtocolModel):
    """Define the fixed inputs and metrics for one benchmark."""

    schema_version: Literal[1] = 1
    benchmark_id: BenchmarkId
    eval_id: EvalId
    test: ResolvedArtifactPointerRef
    splits: dict[InputName, ResolvedArtifactPointerRef] = Field(min_length=1)
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)
    criteria: tuple[MetricCriterion, ...] = ()
    execution_count: Literal[2] = 2

    @model_validator(mode="after")
    def validate_unique_metrics(self) -> BenchmarkSpec:
        """Require unique metrics and optional criteria for selected metrics."""
        metric_ids = self.metric_ids
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("benchmark metric IDs must be unique")
        criterion_ids = tuple(criterion.metric_id for criterion in self.criteria)
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("benchmark criterion metric IDs must be unique")
        if not set(criterion_ids) <= set(metric_ids):
            raise ValueError("benchmark criteria must select benchmark metrics")
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


class MetricCriterionResult(ProtocolModel):
    """Record one threshold result for both benchmark executions."""

    criterion: MetricCriterion
    candidate_passed: bool
    confirmation_passed: bool
    passed: bool

    @model_validator(mode="after")
    def validate_passed(self) -> MetricCriterionResult:
        """Require the combined result to equal both execution results."""
        if self.passed != (self.candidate_passed and self.confirmation_passed):
            raise ValueError("criterion result differs from its execution results")
        return self


class BenchmarkMetricResult(ProtocolModel):
    """Record one metric across candidate and confirmation executions."""

    metric_id: MetricId
    candidate_verification: ResolvedFileRef
    confirmation_verification: ResolvedFileRef
    candidate_value: float = Field(allow_inf_nan=False)
    confirmation_value: float = Field(allow_inf_nan=False)
    matched: bool
    criterion: MetricCriterionResult | None = None


class BenchmarkResult(ProtocolModel):
    """Record the independent confirmation and outcome of a benchmark."""

    schema_version: Literal[1] = 1
    benchmark: ResolvedBenchmarkSpecRef
    run: ResolvedRunRef
    confirmation: ResolvedAttemptRef
    artifacts: tuple[ArtifactComparisonReceipt, ...] = Field(min_length=2)
    metrics: tuple[BenchmarkMetricResult, ...] = Field(min_length=1)
    status: Literal["verified", "passed", "failed"]
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_receipt_sets(self) -> BenchmarkResult:
        """Require unique artifact selectors and metric results."""
        artifacts = tuple(
            (receipt.artifact.stage_id, receipt.artifact.artifact_name)
            for receipt in self.artifacts
        )
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("benchmark artifact comparisons must be unique")
        metrics = tuple(receipt.metric_id for receipt in self.metrics)
        if len(set(metrics)) != len(metrics):
            raise ValueError("benchmark metric results must be unique")
        return self


def at_least(metric: MetricDraft[Any], threshold: float) -> MetricCriterionDraft:
    """Require a benchmark metric value at or above one threshold."""
    return MetricCriterionDraft(metric=metric, comparison="ge", threshold=threshold)


def at_most(metric: MetricDraft[Any], threshold: float) -> MetricCriterionDraft:
    """Require a benchmark metric value at or below one threshold."""
    return MetricCriterionDraft(metric=metric, comparison="le", threshold=threshold)


def benchmark(
    *,
    benchmark_id: BenchmarkId,
    eval_id: EvalId,
    test: RunArtifactDraft,
    splits: dict[InputName, RunArtifactDraft],
    metrics: tuple[MetricDraft[Any], ...],
    criteria: tuple[MetricCriterionDraft, ...] = (),
) -> BenchmarkDraft:
    """Declare one benchmark over fixed prior-run inputs."""
    return BenchmarkDraft(
        benchmark_id=benchmark_id,
        eval_id=eval_id,
        test=test,
        splits=splits,
        metrics=metrics,
        criteria=criteria,
    )
