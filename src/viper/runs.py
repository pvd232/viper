"""Define frozen run plans, durable attempts, and terminal run outcomes."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from . import keys
from ._schema import (
    SHA256,
    BenchmarkId,
    NonEmptyStr,
    ProtocolModel,
    RepoRelPath,
    RNGSeed,
)
from .artifacts import StageArtifactRef
from .ids import ExperimentId, ReplicateId, RunId, StageId, VariantId
from .references import (
    GitSource,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunSpecRef,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    StageResultSnapshotRef,
)
from .runtime import EnvSpec, ReproducibilitySpec

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

    schema_version: Literal[1] = 1
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
    env: EnvSpec
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

        if self.estimator.artifact_name != keys.Train.MODEL:
            raise ValueError("estimator must select the model artifact")

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
