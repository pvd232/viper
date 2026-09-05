"""Define the public records consumed and returned by verification operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .._schema import DataRole, RepoRelPath
from ..artifacts import ResolvedArtifact
from ..benchmark import BenchmarkResult, BenchmarkSpec
from ..experiments import ExperimentSpec, VariantSpec
from ..ids import InputName, StageId
from ..metrics import Measurement
from ..references import (
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
)
from ..runs import ResolvedRun, RunAttempt, RunSpec
from ..stages import BaseSpec, ResolvedBaseSpec
from ..reuse import StageReuseReceipt



class VerificationError(ValueError):
    """A referenced file could not be retrieved or failed verification."""


@dataclass(frozen=True)
class VerificationPolicy:
    """Define which source repositories may execute project-owned code."""

    trusted_source_repositories: frozenset[str]

    def permits_source(self, repository: object) -> bool:
        """Return whether project code from one repository may execute."""
        normalized = str(repository).rstrip("/")
        return normalized in {
            trusted.rstrip("/") for trusted in self.trusted_source_repositories
        }


@dataclass(frozen=True)
class VerifiedSnapshotFile:
    """One snapshot file whose bytes match its recorded identity."""

    reference: SnapshotFileRef
    content: bytes


@dataclass(frozen=True)
class VerifiedArtifact:
    """One resolved artifact and all of its verified files."""

    artifact: ResolvedArtifact
    files: tuple[VerifiedSnapshotFile, ...]
    data_role: DataRole
    references: tuple[ResolvedFileRef, ...] = ()


@dataclass(frozen=True)
class VerifiedInput:
    """A verified artifact and the local path where a stage consumes it."""

    path: RepoRelPath
    data_role: DataRole
    artifact: ResolvedArtifact
    files: tuple[VerifiedSnapshotFile, ...]
    references: tuple[ResolvedFileRef, ...] = ()


@dataclass(frozen=True)
class VerifiedRunPlan:
    """The connected records constituting one verified run plan."""

    run: RunSpec
    experiment: ExperimentSpec
    variant: VariantSpec
    benchmark: BenchmarkSpec | None
    stages: dict[StageId, BaseSpec]


@dataclass(frozen=True)
class VerifiedRunResult:
    """A verified terminal run and its connected records."""

    result: ResolvedRun
    plan: VerifiedRunPlan
    attempts: tuple[RunAttempt, ...]
    resolved_stages: dict[StageId, ResolvedBaseSpec]
    measurements: tuple[Measurement, ...]
    inputs: dict[StageId, dict[InputName, VerifiedInput]] = field(default_factory=dict)
    reuse: dict[StageId, StageReuseReceipt] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedBenchmarkResult:
    """A benchmark result and its verified run and confirmation execution."""

    result: BenchmarkResult
    run: VerifiedRunResult
    confirmation: RunAttempt
    confirmation_stages: dict[StageId, ResolvedBaseSpec]
    confirmation_measurements: tuple[Measurement, ...]


StorageFetcher = Callable[[StorageModel], bytes]
StageSnapshot = StageResultSnapshot


__all__ = [
    "StageSnapshot",
    "StorageFetcher",
    "VerificationError",
    "VerificationPolicy",
    "VerifiedArtifact",
    "VerifiedBenchmarkResult",
    "VerifiedInput",
    "VerifiedRunPlan",
    "VerifiedRunResult",
    "VerifiedSnapshotFile",
]
