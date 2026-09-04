"""Define benchmark specifications, criteria, comparisons, and results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from ._schema import SHA256, BenchmarkId, ProtocolModel
from .artifacts import StageArtifactRef
from .ids import EvalId, InputName, MetricId
from .metrics import MetricCriterionDraft, MetricDraft
from .references import (
    ArtifactPointerRef,
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


class BenchmarkSpec(ProtocolModel):
    """Define the fixed eval and criteria for a strict benchmark."""

    schema_version: Literal[1] = 1
    benchmark_id: BenchmarkId
    eval_id: EvalId
    eval_dataset: ArtifactPointerRef
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


def at_least(metric: MetricDraft[Any], threshold: float) -> MetricCriterionDraft:
    """Require a benchmark metric value at or above one threshold."""
    return MetricCriterionDraft(metric=metric, comparison="ge", threshold=threshold)


def at_most(metric: MetricDraft[Any], threshold: float) -> MetricCriterionDraft:
    """Require a benchmark metric value at or below one threshold."""
    return MetricCriterionDraft(metric=metric, comparison="le", threshold=threshold)
