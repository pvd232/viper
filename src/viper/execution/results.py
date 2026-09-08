"""Define the public results returned by complete run execution."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..benchmark import BenchmarkResult
from ..ids import ReplicateId, RunId, VariantId
from ..references import ResolvedBenchmarkResultRef, ResolvedRunRef
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt


class RunResult(BaseModel):
    """Return one verified terminal run and its local output path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedRun = Field(
        description="Verified terminal record saved by the run."
    )
    reference: ResolvedRunRef = Field(
        description="Immutable reference to the saved terminal record."
    )
    path: Path = Field(description="Local path of the terminal record.")
    journal_path: Path = Field(description="Local journal for the completed attempt.")

    @property
    def status(self) -> Literal["succeeded", "failed", "cancelled"]:
        """Return the terminal status recorded for this run."""
        return self.record.status


class ConfirmationRunResult(BaseModel):
    """Return one independently executed benchmark-confirmation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: RunAttempt = Field(description="Completed benchmark confirmation attempt.")
    attempt_reference: ResolvedAttemptRef = Field(
        description="Immutable reference to the confirmation attempt."
    )
    attempt_path: Path = Field(description="Local path of the confirmation attempt.")
    journal_path: Path = Field(description="Journal of confirmation state changes.")


class BenchmarkExecutionResult(BaseModel):
    """Return one verified benchmark result and its canonical local path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: BenchmarkResult = Field(description="Verified benchmark comparison record.")
    reference: ResolvedBenchmarkResultRef = Field(
        description="Immutable reference to the benchmark record."
    )
    path: Path = Field(description="Local path of the benchmark record.")

    @property
    def status(self) -> Literal["verified", "passed", "failed"]:
        """Return the comparison and criteria outcome recorded by the benchmark."""
        return self.record.status


ExperimentRunFailureCode = Literal[
    "invalid_document",
    "execution_failed",
    "verification_failed",
]

ExperimentRunStatus = Literal["succeeded", "failed", "skipped"]


class ExperimentRunFailure(BaseModel):
    """Describe why one run in a batch failed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ExperimentRunFailureCode = Field(description="Category of the run failure.")
    message: str = Field(min_length=1, description="Explanation of the run failure.")


class ExperimentRunResult(BaseModel):
    """Retain one batch entry in its original input position."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_id: VariantId = Field(description="Variant selected by this batch entry.")
    replicate_id: ReplicateId = Field(description="Replicate selected by this entry.")
    run_id: RunId = Field(description="Identity assigned to the selected run.")
    run_spec_path: Path = Field(description="Frozen plan supplied for this entry.")
    status: ExperimentRunStatus = Field(description="Execution outcome of this entry.")
    result: RunResult | None = Field(
        default=None, description="Verified run returned when execution succeeded."
    )
    failure: ExperimentRunFailure | None = Field(
        default=None, description="Failure details when execution failed."
    )
    skip_reason: str | None = Field(
        default=None, min_length=1, description="Reason this entry was left unexecuted."
    )

    @model_validator(mode="after")
    def validate_status(self) -> "ExperimentRunResult":
        """Require exactly the fields selected by the result status."""
        states = {
            "succeeded": (
                self.result is not None,
                self.failure is None,
                self.skip_reason is None,
            ),
            "failed": (
                self.result is None,
                self.failure is not None,
                self.skip_reason is None,
            ),
            "skipped": (
                self.result is None,
                self.failure is None,
                self.skip_reason is not None,
            ),
        }
        if not all(states[self.status]):
            raise ValueError("batch result fields differ from status")
        return self


class ExperimentExecutionResult(BaseModel):
    """Return every batch result in input order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[ExperimentRunResult, ...] = Field(
        min_length=1, description="Per-run outcomes in the original input order."
    )


__all__ = [
    "BenchmarkExecutionResult",
    "ExperimentExecutionResult",
    "ExperimentRunFailure",
    "ExperimentRunResult",
    "RunResult",
]
