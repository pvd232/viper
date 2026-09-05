"""Define the public results returned by complete run execution."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..benchmark import BenchmarkResult
from ..references import ResolvedBenchmarkResultRef, ResolvedRunRef
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt


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


__all__ = ["BenchmarkExecutionResult", "RunResult"]
