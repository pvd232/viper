"""Define verified stage-reuse identities and evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self, cast

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from ._schema import (
    SHA256,
    ArtifactName,
    DataRole,
    ProtocolModel,
    RepoRelPath,
    RNGSeed,
)
from .ids import InputName, MetricId, StageId
from .metrics import MetricSpec
from .references import (
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunRef,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
from .runs import ResolvedAttemptRef
from .runtime import (
    EnvSpec,
    ExecutionContext,
    ProcessStartupReceipt,
    ReproducibilitySpec,
    ResolvedEnv,
)

if TYPE_CHECKING:
    from .stages import ParameterizedSpec
    from .verification.models import VerifiedInput, VerifiedRunResult

StageReuseMode = Literal["never", "verified"]


class ReuseFileIdentity(ProtocolModel):
    """Identify one input file independently of its run-specific path."""

    relative_path: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class ReuseInputIdentity(ProtocolModel):
    """Identify every file selected for one named stage input."""

    input_name: InputName
    data_role: DataRole
    files: tuple[ReuseFileIdentity, ...] = Field(min_length=1)


class StageReuseKey(ProtocolModel):
    """Describe every recorded value allowed to affect a reusable stage."""

    schema_version: Literal[1] = 1
    stage_id: StageId
    stage_sha256: SHA256
    inputs: tuple[ReuseInputIdentity, ...]
    seed: RNGSeed
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    metric_sha256s: tuple[SHA256, ...]


class ReusedStageFile(ProtocolModel):
    """Map one verified source file to its target snapshot path."""

    artifact_name: ArtifactName
    source: SnapshotFileRef
    target: SnapshotFileRef

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        """Keep source and target byte identities equal."""
        if self.source.sha256 != self.target.sha256:
            raise ValueError("reused file digests must match")
        if self.source.bytes != self.target.bytes:
            raise ValueError("reused file byte counts must match")
        return self


class ReusedMetricEvidence(ProtocolModel):
    """Link one reused metric to its original measurement evidence."""

    metric_id: MetricId
    measurement: ResolvedFileRef
    verification: ResolvedFileRef | None = None


class StageReuseReceipt(ProtocolModel):
    """Record the verified source and remapping for one reused stage."""

    schema_version: Literal[1] = 1
    stage_id: StageId
    key: StageReuseKey
    source_run: ResolvedRunRef
    source_attempt: ResolvedAttemptRef
    source_stage: ResolvedStageRef
    files: tuple[ReusedStageFile, ...] = Field(min_length=1)
    metrics: tuple[ReusedMetricEvidence, ...]
    completed_at: AwareDatetime


class ResolvedStageReuseRef(ResolvedFileRef):
    """Identify one immutable stage-reuse receipt."""

    kind: Literal["stage_reuse"] = "stage_reuse"


class ExecutedStageCompletion(ProtocolModel):
    """Record evidence created by an actual project stage process."""

    kind: Literal["executed"] = "executed"
    source: ResolvedGitFileRef
    env: ResolvedEnv
    execution_context: ExecutionContext
    startup: ProcessStartupReceipt
    invocation: ResolvedStageInvocationRef
    command: tuple[str, ...] = Field(min_length=1)


class ReusedStageCompletion(ProtocolModel):
    """Record that a project stage selected verified prior output."""

    kind: Literal["reused"] = "reused"
    receipt: ResolvedStageReuseRef


StageCompletion = Annotated[
    ExecutedStageCompletion | ReusedStageCompletion,
    Field(discriminator="kind"),
]


class StageReuseCandidate(ProtocolModel):
    """Retain one catalog candidate and every source reference needed to verify it."""

    key: StageReuseKey
    source_run: ResolvedRunRef
    source_attempt: ResolvedAttemptRef
    attempt_id: int = Field(ge=1)
    source_stage: ResolvedStageRef
    completed_at: AwareDatetime


def _canonical_sha256(value: BaseModel | dict[str, object]) -> SHA256:
    """Hash one model or mapping through canonical JSON bytes."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalized_stage(stage: ParameterizedSpec) -> dict[str, object]:
    """Remove run-specific paths and the permission flag from a stage spec."""
    payload = stage.model_dump(mode="json")
    payload.pop("reuse", None)
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, dict):
        raise ValueError("stage artifacts are invalid")
    for artifact in artifacts.values():
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise ValueError("stage artifact path is invalid")
        path = artifact["path"]
        marker = "/artifacts/"
        if marker not in path:
            raise ValueError("stage artifact path has no run-relative boundary")
        artifact["path"] = f"artifacts/{path.split(marker, 1)[1]}"
    return payload


def input_identity(
    input_name: InputName,
    data_role: DataRole,
    root: Path,
) -> ReuseInputIdentity:
    """Hash one materialized input file or directory in stable path order."""
    selected = root.resolve(strict=True)
    paths = (selected,) if selected.is_file() else tuple(sorted(selected.rglob("*")))
    files = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        relative = (
            path.name if selected.is_file() else path.relative_to(selected).as_posix()
        )
        files.append(
            ReuseFileIdentity(
                relative_path=relative,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )
    if not files:
        raise ValueError(f"stage input {input_name!r} has no regular files")
    return ReuseInputIdentity(
        input_name=input_name,
        data_role=data_role,
        files=tuple(files),
    )


def verified_input_identity(
    input_name: InputName,
    value: VerifiedInput,
) -> ReuseInputIdentity:
    """Build one reuse identity from input bytes already accepted by verification."""
    files = []
    for file in value.files:
        path = Path(file.reference.path)
        root = Path(value.path)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.name
        files.append(
            ReuseFileIdentity(
                relative_path=relative,
                sha256=file.reference.sha256,
                bytes=file.reference.bytes,
            )
        )
    return ReuseInputIdentity(
        input_name=input_name,
        data_role=value.data_role,
        files=tuple(sorted(files, key=lambda item: item.relative_path)),
    )


def build_stage_reuse_key(
    *,
    stage_id: StageId,
    stage: ParameterizedSpec,
    inputs: Sequence[ReuseInputIdentity],
    seed: RNGSeed,
    env: EnvSpec,
    reproducibility: ReproducibilitySpec,
    metrics: Mapping[MetricId, MetricSpec],
) -> StageReuseKey:
    """Build the canonical key for one frozen stage and its selected inputs."""
    selected_metrics = tuple(metrics[metric_id] for metric_id in stage.metric_ids)
    return StageReuseKey(
        stage_id=stage_id,
        stage_sha256=_canonical_sha256(_normalized_stage(stage)),
        inputs=tuple(sorted(inputs, key=lambda item: item.input_name)),
        seed=seed,
        env_sha256=_canonical_sha256(env),
        reproducibility_sha256=_canonical_sha256(reproducibility),
        metric_sha256s=tuple(_canonical_sha256(metric) for metric in selected_metrics),
    )


def stage_reuse_key_sha256(key: StageReuseKey) -> SHA256:
    """Return the catalog identity for one complete reuse key."""
    return _canonical_sha256(key)


def catalog_reuse_candidates(
    source_run: ResolvedRunRef,
    verified: VerifiedRunResult,
) -> tuple[StageReuseCandidate, ...]:
    """Build catalog candidates from one fully verified successful run."""
    successful_id = verified.result.successful_attempt_id
    if successful_id is None:
        return ()
    attempt_pairs = tuple(zip(verified.attempts, verified.result.attempts, strict=True))
    selected = next(
        (
            (attempt, reference)
            for attempt, reference in attempt_pairs
            if attempt.attempt_id == successful_id
        ),
        None,
    )
    if selected is None:
        raise ValueError("verified run has no successful attempt reference")
    attempt, attempt_reference = selected
    stage_references = {item.stage_id: item for item in attempt.resolved_stages}
    metrics = {item.metric_id: item for item in verified.plan.experiment.metrics}
    candidates = []
    for stage_id, resolved in verified.resolved_stages.items():
        completion = getattr(resolved, "completion", None)
        if not isinstance(completion, ExecutedStageCompletion):
            continue
        stage = cast("ParameterizedSpec", resolved.spec)
        source_stage = stage_references.get(stage_id)
        if source_stage is None:
            raise ValueError("verified stage has no successful attempt reference")
        inputs = tuple(
            verified_input_identity(name, value)
            for name, value in sorted(verified.inputs.get(stage_id, {}).items())
        )
        declared_inputs = getattr(stage, "inputs", {})
        if len(inputs) != len(declared_inputs):
            continue
        key = build_stage_reuse_key(
            stage_id=stage_id,
            stage=stage,
            inputs=inputs,
            seed=verified.plan.run.seed,
            env=stage.env or verified.plan.run.env,
            reproducibility=verified.plan.run.reproducibility,
            metrics=metrics,
        )
        candidates.append(
            StageReuseCandidate(
                key=key,
                source_run=source_run,
                source_attempt=attempt_reference,
                attempt_id=attempt.attempt_id,
                source_stage=source_stage,
                completed_at=resolved.completed_at,
            )
        )
    return tuple(candidates)


__all__ = [
    "ExecutedStageCompletion",
    "ResolvedStageReuseRef",
    "ReuseFileIdentity",
    "ReuseInputIdentity",
    "ReusedMetricEvidence",
    "ReusedStageCompletion",
    "ReusedStageFile",
    "StageCompletion",
    "StageReuseCandidate",
    "StageReuseKey",
    "StageReuseMode",
    "StageReuseReceipt",
    "build_stage_reuse_key",
    "catalog_reuse_candidates",
    "input_identity",
    "stage_reuse_key_sha256",
    "verified_input_identity",
]
