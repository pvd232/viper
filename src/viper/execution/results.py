"""Define the public results returned by complete run execution."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..benchmark import BenchmarkResult
from ..references import ResolvedBenchmarkResultRef, ResolvedRunRef
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt
from typing import Literal

from pydantic import Field, model_validator

from ..ids import ReplicateId, RunId, VariantId



class RunResult(BaseModel):
    """Return one verified terminal run and its local output path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_run: ResolvedRun
    resolved_run_ref: ResolvedRunRef
    resolved_run_path: Path
    journal_path: Path


class ConfirmationRunResult(BaseModel):
    """Return one independently executed benchmark-confirmation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: RunAttempt
    attempt_reference: ResolvedAttemptRef
    attempt_path: Path
    journal_path: Path


class BenchmarkExecutionResult(BaseModel):
    """Return one verified benchmark result and its canonical local path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: BenchmarkResult
    result_ref: ResolvedBenchmarkResultRef
    result_path: Path


ExperimentRunFailureCode = Literal[
    "invalid_document",
    "execution_failed",
    "verification_failed",
]

ExperimentRunStatus = Literal["succeeded", "failed", "skipped"]

class ExperimentRunFailure(BaseModel):
    """Describe why one run in a batch failed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ExperimentRunFailureCode
    message: str = Field(min_length=1)

class ExperimentRunResult(BaseModel):
    """Retain one batch entry in its original input position."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_id: VariantId
    replicate_id: ReplicateId
    run_id: RunId
    run_spec_path: Path
    status: ExperimentRunStatus
    result: RunResult | None = None
    failure: ExperimentRunFailure | None = None
    skip_reason: str | None = Field(default=None, min_length=1)

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

    runs: tuple[ExperimentRunResult, ...] = Field(min_length=1)

__all__ = [
    "BenchmarkExecutionResult",
    "ExperimentExecutionResult",
    "ExperimentRunFailure",
    "ExperimentRunResult",
    "RunResult",
]
