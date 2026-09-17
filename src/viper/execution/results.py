"""Define the public results returned by complete run execution."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .._schema import SHA256, RepoRelPath
from ..benchmark import BenchmarkResult
from ..ids import ReplicateId, RunId, StageId, VariantId
from ..references import ResolvedBenchmarkResultRef, ResolvedRunRef
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt


class RunResult(BaseModel):
    """Return one terminal run, its latest attempt, and local output path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedRun = Field(
        description="Verified terminal record saved by the run."
    )
    reference: ResolvedRunRef = Field(
        description="Immutable reference to the saved terminal record."
    )
    path: Path = Field(description="Local path of the terminal record.")
    journal_path: Path = Field(description="Local journal for the completed attempt.")
    latest_attempt: RunAttempt = Field(
        description="Latest attempt recorded by this terminal run."
    )

    @property
    def status(self) -> Literal["succeeded", "failed", "cancelled"]:
        """Return the terminal status recorded for this run."""
        return self.record.status

    @property
    def completed_stage_ids(self) -> tuple[StageId, ...]:
        """Return stages published before the latest attempt ended."""
        return tuple(stage.stage_id for stage in self.latest_attempt.resolved_stages)

    @property
    def failed_stage_id(self) -> StageId | None:
        """Return the stage active when the latest attempt failed, if any."""
        failure = self.latest_attempt.failure
        return None if failure is None else failure.stage_id


class RunBundleEntry(BaseModel):
    """Identify one payload retained in a portable run bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RepoRelPath
    bytes: int = Field(ge=0)
    sha256: SHA256
    source: dict[str, Any]


class RunBundleSnapshot(BaseModel):
    """Retain the complete ordered membership of one stage snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: SHA256
    members: tuple[RepoRelPath, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_members(self) -> "RunBundleSnapshot":
        """Require every snapshot member to occur exactly once."""
        if len(self.members) != len(set(self.members)):
            raise ValueError("bundle snapshot members must be unique")
        return self


class RunBundleManifest(BaseModel):
    """Describe every file required by one portable run bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    root_run: RepoRelPath
    entries: tuple[RunBundleEntry, ...] = Field(min_length=1)
    snapshots: tuple[RunBundleSnapshot, ...] = ()

    @model_validator(mode="after")
    def validate_manifest(self) -> "RunBundleManifest":
        """Require canonical unique entries and snapshot memberships."""
        paths = tuple(item.path for item in self.entries)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("bundle entries must have unique sorted paths")
        sources = tuple(item.source for item in self.entries)
        if sum(source.get("kind") == "root_run" for source in sources) != 1:
            raise ValueError("bundle manifest must contain one root run")
        if self.root_run != "root/resolved.yaml":
            raise ValueError("bundle root run path is not canonical")
        source_keys = tuple(
            json.dumps(source, sort_keys=True, separators=(",", ":"))
            for source in sources
        )
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("bundle entries must have unique sources")
        for entry in self.entries:
            if entry.source.get("kind") == "root_run":
                if entry.path != self.root_run:
                    raise ValueError("bundle root entry path differs")
                continue
            source_raw = (
                json.dumps(entry.source, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            digest = hashlib.sha256(source_raw).hexdigest()
            if entry.path != f"objects/{digest[:2]}/{digest}":
                raise ValueError("bundle object path is not canonical")
        snapshot_ids = tuple(item.source_sha256 for item in self.snapshots)
        if snapshot_ids != tuple(sorted(snapshot_ids)) or len(snapshot_ids) != len(
            set(snapshot_ids)
        ):
            raise ValueError("bundle snapshots must have unique sorted identities")
        known = set(paths)
        if any(
            member not in known for item in self.snapshots for member in item.members
        ):
            raise ValueError("bundle snapshot names an absent member")
        return self


class RunExportResult(BaseModel):
    """Return one written or verified portable run bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path
    manifest_path: Path
    manifest_sha256: SHA256
    file_count: int = Field(ge=1)
    total_bytes: int = Field(ge=0)


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
