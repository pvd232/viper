"""Define experiments, variants, factors, and replicate selections."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import parameters
from ._schema import ProtocolModel, RNGSeed
from .ids import ExperimentId, FactorId, LevelId, ReplicateId, StageId, VariantId
from .metrics import MetricSpec


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
