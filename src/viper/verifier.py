"""Cross-file verification for VIPER provenance records."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from huggingface_hub import HfApi, RepoFile, hf_hub_download
from pydantic import TypeAdapter

from ._parameter_validation import (
    ParameterValidationError,
    verify_parameter_model_bytes,
)
from .artifact_loaders import (
    ArtifactLoaderError,
    ArtifactValidationResult,
    execute_artifact_loader,
    materialized_loader_context,
    verify_artifact_loader_bytes,
)
from .http import HttpRetrievalError, validate_request_policy
from .ids import InputName, StageId
from .journal import parse_journal_bytes
from .metrics import compare_metric_values
from .paths import retrieval_body_path
from .protocol import (
    PARAMETERS,
    PARAMETERS_INPUT,
    PREDICTIONS,
    RESUME_STATE,
    RESUME_STATE_INPUT,
    ArtifactName,
    ArtifactPointer,
    ArtifactSpec,
    BaseSpec,
    BenchmarkResult,
    BenchmarkSpec,
    BuildSpec,
    ComputeBackendContext,
    ComputeSpec,
    CPUBackendContext,
    CUDABackendContext,
    DataRole,
    DownloadSpec,
    EmbedSpec,
    EnvironmentSpec,
    EvaluateSpec,
    ExecutionContext,
    ExperimentSpec,
    FloatComparator,
    FutureInputRef,
    GCEEnvironmentSpec,
    GCEHostContext,
    GitFileRef,
    HttpRetrievalContextBinding,
    HuggingFaceFileRef,
    InternalSpec,
    LocalFileRef,
    LocalHostContext,
    LocalStageResultSnapshotRef,
    Measurement,
    MetricExecutionReceipt,
    MetricVerificationReceipt,
    ParameterizedSpec,
    ParameterizedStageSpec,
    ProjectHttpTransportSpec,
    RepoRelPath,
    ResolvedArtifact,
    ResolvedAttemptRef,
    ResolvedBaseSpec,
    ResolvedBundleArtifact,
    ResolvedDownloadSpec,
    ResolvedEnvironment,
    ResolvedFileRef,
    ResolvedFutureInputRef,
    ResolvedGCEEnvironment,
    ResolvedInternalSpec,
    ResolvedMetricDependency,
    ResolvedRun,
    ResolvedRunSpecRef,
    ResolvedSingleFileArtifact,
    ResolvedSpec,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    ResolvedStoredInputRef,
    RunAttempt,
    RunSpec,
    SnapshotFileRef,
    Spec,
    StageArtifactRef,
    StageContextBinding,
    StageInvocationReceipt,
    StageResultSnapshotRef,
    StorageModel,
    StoredInputRef,
    TrainSpec,
    VariantSpec,
    repo_file_paths_overlap,
)
from .runtime import process_environment
from .serialization import document_digest, parse_yaml_bytes
from .stages import StageDefinitionError, verify_stage_implementation_bytes

StorageFetcher = Callable[[StorageModel], bytes]
StageSnapshot = StageResultSnapshotRef | LocalStageResultSnapshotRef
SPEC_ADAPTER = TypeAdapter(Spec)
RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)
_DATA_ROLE_RANK: dict[DataRole, int] = {
    "training": 0,
    "validation": 1,
    "evaluation": 2,
    "benchmark": 3,
}
_ARTIFACT_VALIDATION_CACHE: dict[
    tuple[str, str, str, tuple[tuple[str, str, int], ...]],
    ArtifactValidationResult,
] = {}


def run_root(run: RunSpec) -> RepoRelPath:
    """Return the canonical repository root for one run's records and outputs."""
    return f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"


def stage_spec_path(run: RunSpec, stage_id: StageId) -> RepoRelPath:
    """Return the canonical stage-spec path for a run stage."""
    return f"{run_root(run)}/stages/{stage_id}/spec.yaml"


def stage_invocation_path(
    run: RunSpec,
    attempt_id: int,
    stage_id: StageId,
) -> RepoRelPath:
    """Return the canonical receipt path for one attempted stage invocation."""
    return f"{run_root(run)}/attempts/{attempt_id}/invocations/{stage_id}.yaml"


def _verify_stage_data_roles(
    stage_id: StageId,
    stage: BaseSpec,
    prior_stages: Mapping[StageId, BaseSpec],
) -> None:
    """Reject restricted inputs and artifact-role downgrades within a run plan."""
    if not isinstance(stage, InternalSpec):
        return

    input_roles = _stage_input_roles(stage_id, stage, prior_stages)

    if isinstance(stage, TrainSpec):
        restricted = {
            name: role
            for name, role in input_roles.items()
            if _DATA_ROLE_RANK[role] > _DATA_ROLE_RANK["validation"]
        }
        if restricted:
            names = ", ".join(sorted(restricted))
            raise VerificationError(
                f"training stage {stage_id!r} cannot consume evaluation or "
                f"benchmark inputs: {names}"
            )

    if isinstance(stage, EvaluateSpec):
        model_role = input_roles[PARAMETERS_INPUT]
        if _DATA_ROLE_RANK[model_role] > _DATA_ROLE_RANK["validation"]:
            raise VerificationError(
                f"evaluation stage {stage_id!r} parameters must have training "
                "or validation data_role"
            )

        dataset_input = stage.inputs["evaluation_dataset"]
        assert isinstance(dataset_input, StoredInputRef)
        evaluation_role = dataset_input.data_role
        incompatible = {
            name: role
            for name, role in input_roles.items()
            if _DATA_ROLE_RANK[role] > _DATA_ROLE_RANK[evaluation_role]
        }
        if incompatible:
            names = ", ".join(sorted(incompatible))
            raise VerificationError(
                f"evaluation stage {stage_id!r} consumes inputs more restricted "
                f"than its {evaluation_role!r} evaluation: {names}"
            )

    highest_input_rank = max(_DATA_ROLE_RANK[role] for role in input_roles.values())
    downgraded_outputs = {
        name
        for name, artifact in stage.artifacts.items()
        if _DATA_ROLE_RANK[artifact.data_role] < highest_input_rank
    }
    if downgraded_outputs:
        names = ", ".join(sorted(downgraded_outputs))
        raise VerificationError(
            f"stage {stage_id!r} artifacts cannot have a less restricted "
            f"data_role than their inputs: {names}"
        )


def _stage_input_roles(
    stage_id: StageId,
    stage: InternalSpec,
    prior_stages: Mapping[StageId, BaseSpec],
) -> dict[InputName, DataRole]:
    """Resolve each internal stage input to its declared data role."""
    input_roles: dict[InputName, DataRole] = {}
    for input_name, input_ref in stage.inputs.items():
        if isinstance(input_ref, StoredInputRef):
            input_roles[input_name] = input_ref.data_role
            continue

        producer = prior_stages.get(input_ref.producer_stage_id)
        if producer is None:
            raise VerificationError(
                f"future input {input_name!r} of stage {stage_id!r} must select "
                "an earlier stage"
            )
        declaration = producer.artifacts.get(input_ref.producer_artifact)
        if declaration is None:
            raise VerificationError(
                f"future input {input_name!r} of stage {stage_id!r} selects an "
                "undeclared producer artifact"
            )
        input_roles[input_name] = declaration.data_role
    return input_roles


def resolved_stage_spec_path(run: RunSpec, stage_id: StageId) -> RepoRelPath:
    """Return the canonical resolved-stage path for a run stage."""
    return f"{run_root(run)}/stages/{stage_id}/resolved.yaml"


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


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Construct one JSON object while rejecting duplicate field names."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


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


@dataclass(frozen=True)
class VerifiedBenchmarkResult:
    """A benchmark result and its verified run and confirmation execution."""

    result: BenchmarkResult
    run: VerifiedRunResult
    confirmation: RunAttempt
    confirmation_stages: dict[StageId, ResolvedBaseSpec]
    confirmation_measurements: tuple[Measurement, ...]


def fetch_git_file_bytes(
    location: GitFileRef,
    *,
    timeout_seconds: float = 60,
) -> bytes:
    """Read one file from the exact commit recorded by a Git reference."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    git_environment = os.environ.copy()
    git_environment["GIT_TERMINAL_PROMPT"] = "0"

    def run_git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ("git", *arguments),
                check=True,
                capture_output=True,
                env=git_environment,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise VerificationError("Git is required to retrieve Git files") from exc
        except subprocess.TimeoutExpired as exc:
            raise VerificationError("Git file retrieval timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise VerificationError(
                "Git could not retrieve the referenced file"
            ) from exc

    with tempfile.TemporaryDirectory(prefix="viper-provenance-git-") as checkout:
        init_arguments = ["init", "--quiet"]
        if len(location.commit) == 64:
            init_arguments.append("--object-format=sha256")
        init_arguments.append(checkout)
        run_git(*init_arguments)
        run_git("-C", checkout, "remote", "add", "origin", str(location.repository))
        run_git(
            "-C",
            checkout,
            "fetch",
            "--quiet",
            "--depth=1",
            "origin",
            location.commit,
        )

        fetched_commit = (
            run_git("-C", checkout, "rev-parse", "FETCH_HEAD^{commit}")
            .stdout.decode("ascii")
            .strip()
        )
        if fetched_commit != location.commit:
            raise VerificationError("Git returned a different commit than requested")

        return run_git(
            "-C",
            checkout,
            "show",
            f"FETCH_HEAD:{location.path}",
        ).stdout


def fetch_huggingface_file_bytes(location: HuggingFaceFileRef) -> bytes:
    """Read one file from the exact Hugging Face commit in the reference."""
    repo_type = None if location.repo_type == "model" else location.repo_type

    try:
        downloaded_path = hf_hub_download(
            repo_id=location.repository,
            filename=location.path,
            repo_type=repo_type,
            revision=location.commit,
        )
        return Path(downloaded_path).read_bytes()
    except (OSError, ValueError) as exc:
        raise VerificationError(
            "Hugging Face could not retrieve the referenced file"
        ) from exc


def fetch_local_file_bytes(location: LocalFileRef) -> bytes:
    """Read one file from a repository-local immutable store revision."""
    repository_root = Path.cwd().resolve()
    revision_root = (repository_root / location.store / location.commit).resolve()
    path = (revision_root / location.path).resolve()
    if not path.is_relative_to(revision_root) or not path.is_file():
        raise VerificationError("local immutable file could not be retrieved")
    return path.read_bytes()


def fetch_storage_bytes(location: StorageModel) -> bytes:
    """Dispatch an immutable storage reference to its retrieval backend."""
    if isinstance(location, GitFileRef):
        return fetch_git_file_bytes(location)
    if isinstance(location, HuggingFaceFileRef):
        return fetch_huggingface_file_bytes(location)
    if isinstance(location, LocalFileRef):
        return fetch_local_file_bytes(location)
    raise TypeError(f"unsupported storage reference: {type(location).__name__}")


def list_huggingface_snapshot_files(
    snapshot: StageResultSnapshotRef,
) -> tuple[RepoRelPath, ...]:
    """List every regular file in one immutable Hugging Face snapshot."""
    repo_type = None if snapshot.repo_type == "model" else snapshot.repo_type
    try:
        entries = HfApi().list_repo_tree(
            repo_id=snapshot.repository,
            recursive=True,
            revision=snapshot.commit,
            repo_type=repo_type,
        )
        return tuple(
            sorted(entry.path for entry in entries if isinstance(entry, RepoFile))
        )
    except (OSError, ValueError) as exc:
        raise VerificationError("artifact.bundle: snapshot listing failed") from exc


def list_local_snapshot_files(
    snapshot: LocalStageResultSnapshotRef,
) -> tuple[RepoRelPath, ...]:
    """List every regular file in one repository-local snapshot."""
    revision_root = (Path.cwd() / snapshot.store / snapshot.commit).resolve()
    if not revision_root.is_dir():
        raise VerificationError("artifact.bundle: local snapshot is missing")
    paths: list[RepoRelPath] = []
    for path in sorted(revision_root.rglob("*")):
        if path.is_symlink():
            raise VerificationError("artifact.bundle: snapshot contains a symlink")
        if path.is_file():
            paths.append(path.relative_to(revision_root).as_posix())
    return tuple(paths)


def list_snapshot_files(
    snapshot: StageSnapshot,
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[RepoRelPath, ...]:
    """List one snapshot through its custom or installed storage backend."""
    owner = None if fetcher is None else getattr(fetcher, "__self__", fetcher)
    custom = None if owner is None else getattr(owner, "list_snapshot_files", None)
    if callable(custom):
        try:
            custom_listing = cast(
                Callable[[StageSnapshot], tuple[RepoRelPath, ...]],
                custom,
            )
            return tuple(custom_listing(snapshot))
        except Exception as exc:
            raise VerificationError(
                "artifact.bundle: custom snapshot listing failed"
            ) from exc
    if isinstance(snapshot, StageResultSnapshotRef):
        return list_huggingface_snapshot_files(snapshot)
    return list_local_snapshot_files(snapshot)


def verify_resolved_file_bytes(
    reference: ResolvedFileRef,
    raw: bytes,
) -> bytes:
    """Verify retrieved bytes against a resolved file reference."""
    if not isinstance(raw, bytes):
        raise TypeError("retrieved file content must be bytes")

    if len(raw) != reference.bytes:
        raise VerificationError(
            f"byte-count mismatch: expected {reference.bytes}, received {len(raw)}"
        )

    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != reference.sha256:
        raise VerificationError(
            f"SHA-256 mismatch: expected {reference.sha256}, received {actual_sha256}"
        )

    return raw


def read_resolved_file(
    reference: ResolvedFileRef,
    *,
    fetcher: StorageFetcher | None = None,
) -> bytes:
    """Retrieve a resolved file and verify its byte count and SHA-256."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    raw = retrieve(reference.stored_at)
    return verify_resolved_file_bytes(reference, raw)


def read_attempt_reference(
    reference: ResolvedAttemptRef,
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> RunAttempt:
    """Retrieve one canonical attempt document and verify its path identity."""
    path = str(reference.stored_at.path)
    prefix = f"{run_root(run)}/attempts/"
    suffix = "/resolved.yaml"
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise VerificationError("attempt.identity: attempt path is not canonical")
    attempt_text = path[len(prefix) : -len(suffix)]
    if not attempt_text.isdecimal() or str(int(attempt_text)) != attempt_text:
        raise VerificationError("attempt.identity: attempt path has an invalid ID")
    try:
        attempt = RunAttempt.model_validate(
            parse_yaml_bytes(read_resolved_file(reference, fetcher=fetcher))
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "attempt.identity: attempt document is invalid"
        ) from exc
    if attempt.attempt_id != int(attempt_text):
        raise VerificationError(
            "attempt.identity: attempt document ID differs from its path"
        )
    return attempt


def verify_run_attempt_references(
    resolved_run: ResolvedRun,
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[RunAttempt, ...]:
    """Resolve attempt references and enforce terminal history invariants."""
    locations = tuple(reference.stored_at for reference in resolved_run.attempts)
    if len(set(locations)) != len(locations):
        raise VerificationError("attempt.identity: attempt references are duplicated")
    attempts = tuple(
        read_attempt_reference(reference, run, fetcher=fetcher)
        for reference in resolved_run.attempts
    )
    successful: list[RunAttempt] = []
    previous: RunAttempt | None = None
    for index, attempt in enumerate(attempts):
        if attempt.purpose != "run":
            raise VerificationError(
                "attempt.purpose: resolved run contains confirmation"
            )
        if previous is not None and attempt.attempt_id <= previous.attempt_id:
            raise VerificationError("attempt.order: attempt IDs do not increase")
        if previous is not None and attempt.started_at < previous.completed_at:
            raise VerificationError("attempt.order: attempt execution times overlap")
        if attempt.status == "succeeded":
            successful.append(attempt)
            if index != len(attempts) - 1:
                raise VerificationError("attempt.order: attempt follows a success")
        previous = attempt

    if any(resolved_run.completed_at < attempt.completed_at for attempt in attempts):
        raise VerificationError("attempt.terminal: run predates an attempt completion")
    if resolved_run.status == "succeeded":
        if len(successful) != 1:
            raise VerificationError("attempt.terminal: succeeded run lacks one success")
        if resolved_run.successful_attempt_id != successful[0].attempt_id:
            raise VerificationError(
                "attempt.terminal: successful attempt selector differs"
            )
    else:
        if successful:
            raise VerificationError(
                "attempt.terminal: terminal failure contains success"
            )
        if resolved_run.status == "cancelled" and attempts[-1].status != "cancelled":
            raise VerificationError(
                "attempt.terminal: cancelled run lacks a cancelled final attempt"
            )
        if resolved_run.status == "failed" and attempts[-1].status not in {
            "failed",
            "preempted",
        }:
            raise VerificationError(
                "attempt.terminal: failed run has another final attempt status"
            )
    return attempts


def read_snapshot_file(
    snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
    reference: SnapshotFileRef,
    *,
    fetcher: StorageFetcher | None = None,
) -> bytes:
    """Retrieve and verify one file from a stage-result snapshot."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    if isinstance(snapshot, StageResultSnapshotRef):
        location: StorageModel = HuggingFaceFileRef(
            repository=snapshot.repository,
            commit=snapshot.commit,
            path=reference.path,
            repo_type=snapshot.repo_type,
        )
    else:
        location = LocalFileRef(
            store=snapshot.store,
            commit=snapshot.commit,
            path=reference.path,
        )
    try:
        raw = retrieve(location)
    except Exception as exc:
        raise VerificationError(
            f"artifact.representation: snapshot file is unavailable: {reference.path}"
        ) from exc

    resolved_reference = ResolvedFileRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=location,
    )
    return verify_resolved_file_bytes(resolved_reference, raw)


def _snapshot_identity(
    snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
) -> tuple[str, ...]:
    """Return a backend-qualified identity for one immutable stage snapshot."""
    if isinstance(snapshot, StageResultSnapshotRef):
        return (
            snapshot.kind,
            snapshot.repository,
            snapshot.commit,
            snapshot.repo_type,
        )
    return (snapshot.kind, snapshot.store, snapshot.commit)


def _artifact_revision_identity(location: StorageModel) -> tuple[str, ...] | None:
    """Return the immutable output revision containing one stored file."""
    if isinstance(location, HuggingFaceFileRef):
        return (
            location.kind,
            location.repository,
            location.commit,
            location.repo_type,
        )
    if isinstance(location, LocalFileRef):
        return (location.kind, location.store, location.commit)
    return None


def verify_snapshot_artifact(
    stage: ResolvedStageRef,
    artifact: ResolvedArtifact,
    *,
    data_role: DataRole,
    fetcher: StorageFetcher | None = None,
) -> VerifiedArtifact:
    """Verify every file representing one artifact in a stage snapshot."""
    if isinstance(artifact, ResolvedSingleFileArtifact):
        references = (artifact.file,)
    elif isinstance(artifact, ResolvedBundleArtifact):
        roots: set[str] = set()
        for member in artifact.members:
            full_path = str(member.file.path)
            relative_path = str(member.relative_path)
            suffix = f"/{relative_path}"
            if not full_path.endswith(suffix):
                raise VerificationError(
                    "artifact.bundle: member path differs from its relative path"
                )
            roots.add(full_path[: -len(suffix)])
        if len(roots) != 1:
            raise VerificationError(
                "artifact.bundle: members do not share one bundle root"
            )
        bundle_root = next(iter(roots))
        declared_paths = tuple(member.file.path for member in artifact.members)
        published_paths = tuple(
            path
            for path in list_snapshot_files(stage.snapshot, fetcher=fetcher)
            if str(path).startswith(f"{bundle_root}/")
        )
        if published_paths != declared_paths:
            raise VerificationError(
                "artifact.bundle: published members differ from the resolved list"
            )
        references = tuple(member.file for member in artifact.members)
    else:
        raise TypeError(f"unsupported resolved artifact: {type(artifact).__name__}")

    files = tuple(
        VerifiedSnapshotFile(
            reference=reference,
            content=read_snapshot_file(
                stage.snapshot,
                reference,
                fetcher=fetcher,
            ),
        )
        for reference in references
    )
    resolved_references = tuple(
        ResolvedFileRef(
            sha256=reference.sha256,
            bytes=reference.bytes,
            stored_at=(
                LocalFileRef(
                    store=stage.snapshot.store,
                    commit=stage.snapshot.commit,
                    path=reference.path,
                )
                if isinstance(stage.snapshot, LocalStageResultSnapshotRef)
                else HuggingFaceFileRef(
                    repository=stage.snapshot.repository,
                    commit=stage.snapshot.commit,
                    path=reference.path,
                    repo_type=stage.snapshot.repo_type,
                )
            ),
        )
        for reference in references
    )
    return VerifiedArtifact(
        artifact=artifact,
        files=files,
        data_role=data_role,
        references=resolved_references,
    )


def load_verified_artifact(
    run: RunSpec,
    declaration: ArtifactSpec,
    artifact_name: ArtifactName,
    artifact: VerifiedArtifact,
    *,
    policy: VerificationPolicy,
    materialization_path: RepoRelPath | None = None,
    fetcher: StorageFetcher | None = None,
) -> ArtifactValidationResult:
    """Materialize verified files and establish the artifact guarantee level."""
    if not policy.permits_source(run.source.repository):
        raise VerificationError(
            "artifact-loader execution requires an explicitly trusted source repository"
        )

    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    loader_reference = declaration.loader
    loader_location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=loader_reference.path,
    )
    loader_raw = retrieve(loader_location)
    try:
        verify_artifact_loader_bytes(loader_reference, loader_raw)
    except ArtifactLoaderError as exc:
        raise VerificationError(str(exc)) from exc

    target_path = (
        declaration.path if materialization_path is None else materialization_path
    )
    cache_key = (
        document_digest(run),
        document_digest(loader_reference),
        f"{artifact_name}:{target_path}",
        tuple(
            (
                str(verified_file.reference.path),
                verified_file.reference.sha256,
                verified_file.reference.bytes,
            )
            for verified_file in artifact.files
        ),
    )
    cached = _ARTIFACT_VALIDATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with tempfile.TemporaryDirectory(prefix="viper-artifact-") as directory:
        root = Path(directory)
        if isinstance(artifact.artifact, ResolvedSingleFileArtifact):
            materialized_files = ((target_path, artifact.files[0]),)
        elif isinstance(artifact.artifact, ResolvedBundleArtifact):
            materialized_files = tuple(
                (f"{target_path}/{member.relative_path}", verified_file)
                for member, verified_file in zip(
                    artifact.artifact.members,
                    artifact.files,
                    strict=True,
                )
            )
        else:
            raise TypeError(
                f"unsupported resolved artifact: {type(artifact.artifact).__name__}"
            )

        for path, verified_file in materialized_files:
            materialized = root / path
            materialized.parent.mkdir(parents=True, exist_ok=True)
            materialized.write_bytes(verified_file.content)

        materialized_loader = root / loader_reference.path
        materialized_loader.parent.mkdir(parents=True, exist_ok=True)
        materialized_loader.write_bytes(loader_raw)
        artifact_path = root / target_path
        try:
            result = execute_artifact_loader(
                root,
                materialized_loader_context(
                    root,
                    loader_reference,
                    artifact_name,
                    artifact_path,
                    run,
                ),
            )
        except ArtifactLoaderError as exc:
            raise VerificationError(str(exc)) from exc
        _ARTIFACT_VALIDATION_CACHE[cache_key] = result
        return result


def verify_run_spec(
    resolved_run: ResolvedRun,
    *,
    fetcher: StorageFetcher | None = None,
) -> RunSpec:
    """Retrieve and verify the RunSpec governing a resolved run."""
    raw = read_resolved_file(resolved_run.spec, fetcher=fetcher)

    try:
        file_run = RunSpec.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError("resolved run spec is not a valid RunSpec") from exc

    expected_path = f"{run_root(file_run)}/spec.yaml"
    if resolved_run.spec.stored_at.path != expected_path:
        raise VerificationError(
            "resolved run spec reference is outside the canonical run path"
        )
    if resolved_run.spec.stored_at.repository != file_run.source.repository:
        raise VerificationError(
            "resolved run spec and source snapshot must use one Git repository"
        )

    return file_run


def verify_experiment_and_variant(
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[ExperimentSpec, VariantSpec]:
    """Load and verify the experiment and variant selected by a run."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher

    experiment_location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"experiments/{run.experiment_id}/spec.yaml",
    )
    variant_location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"experiments/{run.experiment_id}/variants/{run.variant_id}.spec.yaml",
    )

    try:
        experiment = ExperimentSpec.model_validate(
            parse_yaml_bytes(retrieve(experiment_location))
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "experiment file is not a valid ExperimentSpec document"
        ) from exc

    try:
        variant = VariantSpec.model_validate(
            parse_yaml_bytes(retrieve(variant_location))
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "variant file is not a valid VariantSpec document"
        ) from exc

    for metric in experiment.metrics:
        implementation = metric.implementation
        metric_location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=implementation.path,
        )
        metric_raw = retrieve(metric_location)
        if len(metric_raw) != implementation.bytes:
            raise VerificationError("metric implementation byte count differs")
        if hashlib.sha256(metric_raw).hexdigest() != implementation.sha256:
            raise VerificationError("metric implementation SHA-256 differs")
        try:
            metric_tree = ast.parse(metric_raw, filename=implementation.path)
        except SyntaxError as exc:
            raise VerificationError(
                f"metric {metric.metric_id!r} implementation is not valid Python"
            ) from exc
        permitted_nodes: tuple[type[ast.AST], ...] = (
            (ast.FunctionDef, ast.AsyncFunctionDef)
            if metric.mode == "recompute"
            else (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        if not any(
            isinstance(node, permitted_nodes) and node.name == implementation.symbol
            for node in metric_tree.body
        ):
            raise VerificationError(
                f"metric {metric.metric_id!r} implementation must define "
                f"{implementation.symbol}"
            )

    if experiment.experiment_id != run.experiment_id:
        raise VerificationError("run and experiment IDs do not match")

    if variant.experiment_id != run.experiment_id:
        raise VerificationError("run and variant experiment IDs do not match")

    if variant.variant_id != run.variant_id:
        raise VerificationError("run and variant IDs do not match")

    if run.variant_id not in experiment.variant_ids:
        raise VerificationError("run variant is not declared by the experiment")

    factors = {factor.factor_id: factor for factor in experiment.factors}
    if set(variant.levels) != set(factors):
        raise VerificationError(
            "variant must assign exactly one level to every experiment factor"
        )

    for factor_id, level_id in variant.levels.items():
        if level_id not in factors[factor_id].levels:
            raise VerificationError(
                f"variant level {level_id!r} is not permitted for factor {factor_id!r}"
            )

    replicates = {
        replicate.replicate_id: replicate for replicate in experiment.replicates
    }
    if run.replicate_id not in replicates:
        raise VerificationError("run replicate is not declared by the experiment")

    if run.seed != replicates[run.replicate_id].seed:
        raise VerificationError("run seed does not match the experiment replicate")

    return experiment, variant


def verify_benchmark_spec(
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> BenchmarkSpec | None:
    """Load the benchmark selected by a run, when one is selected."""
    if run.benchmark_id is None:
        return None

    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"benchmarks/{run.benchmark_id}.spec.yaml",
    )
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(retrieve(location)))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark file is not a valid BenchmarkSpec document"
        ) from exc

    if benchmark.benchmark_id != run.benchmark_id:
        raise VerificationError("run and benchmark IDs do not match")
    return benchmark


def verify_run_plan_relationships(
    run: RunSpec,
    experiment: ExperimentSpec,
    variant: VariantSpec,
    benchmark: BenchmarkSpec | None,
    stages: Mapping[StageId, BaseSpec],
) -> None:
    """Verify plan relationships spanning experiment, variant, and stages."""

    def require_source_snapshot(location: GitFileRef, label: str) -> None:
        if (
            location.repository != run.source.repository
            or location.commit != run.source.commit
        ):
            raise VerificationError(f"{label} must belong to the run source snapshot")

    require_source_snapshot(run.environment.lockfile, "shared lockfile")

    for stage_id, stage in stages.items():
        if stage.environment is not None:
            require_source_snapshot(
                stage.environment.lockfile,
                f"environment lockfile of stage {stage_id!r}",
            )

    prior_stages: dict[StageId, BaseSpec] = {}
    prior_stages_by_id: dict[StageId, dict[StageId, BaseSpec]] = {}
    for stage_reference in run.stages:
        stage = stages[stage_reference.stage_id]
        prior_stages_by_id[stage_reference.stage_id] = dict(prior_stages)
        _verify_stage_data_roles(stage_reference.stage_id, stage, prior_stages)
        prior_stages[stage_reference.stage_id] = stage

    parameterized_stages = {
        stage_id: stage
        for stage_id, stage in stages.items()
        if isinstance(
            stage,
            (DownloadSpec, BuildSpec, EmbedSpec, TrainSpec, EvaluateSpec),
        )
    }
    variant_params = {stage.stage_id: stage for stage in variant.stage_params}

    if set(variant_params) != set(parameterized_stages):
        raise VerificationError(
            "variant stage parameters must match all parameterized run stages"
        )

    for stage_id, stage in parameterized_stages.items():
        selected = variant_params[stage_id]
        if selected.kind != stage.kind or selected.params != stage.params:
            raise VerificationError(
                f"variant parameters do not match stage {stage_id!r}"
            )

    estimator_stage = stages.get(run.estimator.stage_id)
    if not isinstance(estimator_stage, TrainSpec):
        raise VerificationError("run estimator must select a training stage")

    experiment_metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for stage_id, stage in stages.items():
        undeclared_metrics = set(stage.metric_ids) - set(experiment_metrics)
        if undeclared_metrics:
            raise VerificationError(f"stage {stage_id!r} selects undeclared metrics")

        selected_kinds = {
            experiment_metrics[metric_id].kind for metric_id in stage.metric_ids
        }
        if isinstance(stage, EvaluateSpec):
            if selected_kinds - {"evaluation"}:
                raise VerificationError(
                    f"evaluation stage {stage_id!r} must select evaluation metrics"
                )
        elif isinstance(stage, TrainSpec):
            if selected_kinds - {"training", "diagnostic"}:
                raise VerificationError(
                    f"training stage {stage_id!r} selects an incompatible metric"
                )
        elif selected_kinds - {"diagnostic"}:
            raise VerificationError(
                f"stage {stage_id!r} must select diagnostic metrics"
            )

    evaluation_stages = [
        stage for stage in stages.values() if isinstance(stage, EvaluateSpec)
    ]
    expected_evaluation_role: DataRole = (
        "benchmark" if benchmark is not None else "evaluation"
    )
    for evaluation in evaluation_stages:
        dataset_input = evaluation.inputs["evaluation_dataset"]
        assert isinstance(dataset_input, StoredInputRef)
        if dataset_input.data_role != expected_evaluation_role:
            raise VerificationError(
                f"evaluation {evaluation.evaluation_id!r} must use "
                f"{expected_evaluation_role!r} data_role"
            )

    for stage_id, stage in stages.items():
        input_roles = (
            _stage_input_roles(stage_id, stage, prior_stages_by_id[stage_id])
            if isinstance(stage, InternalSpec)
            else {}
        )
        for metric_id in stage.metric_ids:
            metric = experiment_metrics[metric_id]
            for dependency in metric.dependencies:
                if dependency.source == "input":
                    role = input_roles.get(dependency.name)
                else:
                    artifact = stage.artifacts.get(dependency.name)
                    role = None if artifact is None else artifact.data_role
                if role is None:
                    raise VerificationError(
                        f"metric {metric_id!r} selects absent {dependency.source} "
                        f"dependency {dependency.name!r}"
                    )
                if role != dependency.required_data_role:
                    raise VerificationError(
                        f"metric {metric_id!r} dependency {dependency.name!r} "
                        "data role differs from its stage declaration"
                    )

    if benchmark is None:
        return

    if len(evaluation_stages) != 1:
        raise VerificationError("benchmark runs require exactly one evaluation stage")

    evaluation = evaluation_stages[0]
    model_input = evaluation.inputs[PARAMETERS_INPUT]
    if not isinstance(model_input, FutureInputRef):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )
    if (
        model_input.producer_stage_id != run.estimator.stage_id
        or model_input.producer_artifact != run.estimator.artifact_name
    ):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )

    if evaluation.evaluation_id != benchmark.evaluation_id:
        raise VerificationError(
            "evaluation stage ID does not match the benchmark evaluation ID"
        )

    dataset_input = evaluation.inputs["evaluation_dataset"]
    if not isinstance(dataset_input, StoredInputRef):
        raise VerificationError("benchmark evaluation dataset must be stored")
    if dataset_input.pointer != benchmark.evaluation_dataset:
        raise VerificationError(
            "evaluation dataset does not match the benchmark specification"
        )

    if set(evaluation.split_inputs) != set(benchmark.splits):
        raise VerificationError(
            "evaluation split names do not match the benchmark specification"
        )
    for split_name, pointer in benchmark.splits.items():
        split_input = evaluation.inputs[split_name]
        if not isinstance(split_input, StoredInputRef):
            raise VerificationError(f"benchmark split {split_name!r} must be stored")
        if split_input.pointer != pointer:
            raise VerificationError(
                f"evaluation split {split_name!r} does not match the benchmark"
            )

    benchmark_metric_ids = {criterion.metric_id for criterion in benchmark.metrics}
    if set(evaluation.metric_ids) != benchmark_metric_ids:
        raise VerificationError(
            "evaluation metrics do not match the benchmark specification"
        )
    for criterion in benchmark.metrics:
        metric = experiment_metrics[criterion.metric_id]
        if metric.kind != "evaluation" or metric.mode != "recompute":
            raise VerificationError(
                f"benchmark criterion {criterion.metric_id!r} must select a "
                "recomputed evaluation metric"
            )


def verify_parameter_model_references(
    run: RunSpec,
    stages: Mapping[StageId, BaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify each parameterized stage's class against frozen source bytes."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    for stage_id, stage in stages.items():
        if not isinstance(stage, ParameterizedSpec):
            continue
        reference = stage.parameter_model
        location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=reference.path,
        )
        try:
            raw = retrieve(location)
            verify_parameter_model_bytes(reference, raw)
            tree = ast.parse(raw, filename=reference.path)
        except (KeyError, OSError, SyntaxError, ParameterValidationError) as exc:
            raise VerificationError(
                f"parameter model of stage {stage_id!r} failed source verification"
            ) from exc
        if not any(
            isinstance(node, ast.ClassDef) and node.name == reference.symbol
            for node in tree.body
        ):
            raise VerificationError(
                f"parameter model of stage {stage_id!r} must define {reference.symbol}"
            )


def verify_stage_plan(
    run: RunSpec,
    run_spec_reference: ResolvedRunSpecRef,
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, BaseSpec]:
    """Load and verify stage specs from the run-plan snapshot."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    loaded_stages: dict[StageId, BaseSpec] = {}

    for stage in run.stages:
        if stage.spec != stage_spec_path(run, stage.stage_id):
            raise VerificationError(
                f"stage {stage.stage_id!r} spec is outside its canonical run path"
            )

        plan_location = run_spec_reference.stored_at
        location = GitFileRef(
            repository=plan_location.repository,
            commit=plan_location.commit,
            path=stage.spec,
        )

        stage_reference = ResolvedFileRef(
            sha256=stage.sha256,
            bytes=stage.bytes,
            stored_at=location,
        )
        raw = verify_resolved_file_bytes(stage_reference, retrieve(location))

        try:
            spec = SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage.stage_id!r} file is not a valid stage spec"
            ) from exc

        implementation = spec.implementation
        implementation_location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=implementation.path,
        )
        try:
            implementation_raw = retrieve(implementation_location)
            verify_stage_implementation_bytes(implementation, implementation_raw)
            implementation_tree = ast.parse(
                implementation_raw,
                filename=implementation.path,
            )
        except (KeyError, OSError, SyntaxError, StageDefinitionError) as exc:
            raise VerificationError(
                f"implementation of stage {stage.stage_id!r} failed source verification"
            ) from exc
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == implementation.symbol
            for node in implementation_tree.body
        ):
            raise VerificationError(
                f"implementation of stage {stage.stage_id!r} must define "
                f"top-level callable {implementation.symbol!r}"
            )

        artifact_root = f"{run_root(run)}/artifacts/"
        for artifact_name, artifact in spec.artifacts.items():
            if not str(artifact.path).startswith(artifact_root):
                raise VerificationError(
                    f"artifact {artifact_name!r} of stage {stage.stage_id!r} "
                    "is outside the canonical run artifact root"
                )

        if isinstance(spec, InternalSpec):
            for input_name, input_ref in spec.inputs.items():
                if isinstance(input_ref, StoredInputRef) and not str(
                    input_ref.path
                ).startswith("inputs/"):
                    raise VerificationError(
                        f"stored input {input_name!r} of stage "
                        f"{stage.stage_id!r} is outside inputs"
                    )

        if isinstance(spec, InternalSpec):
            stored_inputs = tuple(
                input_ref
                for input_ref in spec.inputs.values()
                if isinstance(input_ref, StoredInputRef)
            )
            future_materialization_paths: dict[RepoRelPath, InputName] = {}

            for input_name, input_ref in spec.inputs.items():
                if not isinstance(input_ref, FutureInputRef):
                    continue

                producer_stage_id = input_ref.producer_stage_id
                if producer_stage_id not in loaded_stages:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        "must name an earlier stage"
                    )

                producer_spec = loaded_stages[producer_stage_id]
                producer_artifact = producer_spec.artifacts.get(
                    input_ref.producer_artifact
                )
                if producer_artifact is None:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        f"selects undeclared artifact "
                        f"{input_ref.producer_artifact!r}"
                    )

                producer_path = producer_artifact.path

                for (
                    previous_path,
                    previous_name,
                ) in future_materialization_paths.items():
                    if repo_file_paths_overlap(producer_path, previous_path):
                        raise VerificationError(
                            f"future input paths for {previous_name!r} and "
                            f"{input_name!r} of stage {stage.stage_id!r} collide"
                        )
                future_materialization_paths[producer_path] = input_name

                if repo_file_paths_overlap(producer_path, spec.implementation.path):
                    raise VerificationError(
                        f"future input {input_name!r} path collides with the "
                        f"implementation of stage {stage.stage_id!r}"
                    )

                for artifact_name, artifact in spec.artifacts.items():
                    if repo_file_paths_overlap(producer_path, artifact.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with "
                            f"artifact {artifact_name!r} of stage "
                            f"{stage.stage_id!r}"
                        )

                for stored_input in stored_inputs:
                    if repo_file_paths_overlap(producer_path, stored_input.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with a "
                            f"stored input of stage {stage.stage_id!r}"
                        )

            _verify_stage_data_roles(stage.stage_id, spec, loaded_stages)

        loaded_stages[stage.stage_id] = spec

    return loaded_stages


def verify_run_plan(
    resolved_run: ResolvedRun,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifiedRunPlan:
    """Retrieve and verify every record constituting a frozen run plan."""
    run = verify_run_spec(resolved_run, fetcher=fetcher)
    experiment, variant = verify_experiment_and_variant(run, fetcher=fetcher)
    benchmark = verify_benchmark_spec(run, fetcher=fetcher)
    stages = verify_stage_plan(run, resolved_run.spec, fetcher=fetcher)
    verify_run_plan_relationships(
        run,
        experiment,
        variant,
        benchmark,
        stages,
    )
    verify_parameter_model_references(run, stages, fetcher=fetcher)
    return VerifiedRunPlan(
        run=run,
        experiment=experiment,
        variant=variant,
        benchmark=benchmark,
        stages=stages,
    )


def _logical_input_paths(
    run: RunSpec,
    stage_id: StageId,
    stage: BaseSpec,
    stage_specs: Mapping[StageId, BaseSpec],
) -> dict[InputName, RepoRelPath]:
    """Reconstruct the repository-relative input paths delivered to one stage."""
    if isinstance(stage, DownloadSpec):
        return {name: retrieval_body_path(run, stage_id, name) for name in stage.inputs}
    if not isinstance(stage, InternalSpec):
        return {}
    paths: dict[InputName, RepoRelPath] = {}
    for name, reference in stage.inputs.items():
        if isinstance(reference, StoredInputRef):
            paths[name] = reference.path
            continue
        producer = stage_specs[reference.producer_stage_id]
        paths[name] = producer.artifacts[reference.producer_artifact].path
    return paths


def _verify_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    resolved_stage: ResolvedBaseSpec,
    fetcher: StorageFetcher | None,
) -> StageInvocationReceipt:
    """Verify one invocation receipt against its plan, context, and startup facts."""
    if reference.stored_at.path != stage_invocation_path(
        run, attempt.attempt_id, stage_id
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is outside its canonical path"
        )
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    retrieval_bindings: dict[InputName, HttpRetrievalContextBinding] = {}
    if isinstance(resolved_stage, ResolvedDownloadSpec):
        retrieval_bindings = {
            name: HttpRetrievalContextBinding(
                response=retrieval.response,
                body=SnapshotFileRef(
                    path=retrieval.body.stored_at.path,
                    sha256=retrieval.body.sha256,
                    bytes=retrieval.body.bytes,
                ),
            )
            for name, retrieval in resolved_stage.retrievals.items()
        }
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(run, stage_id, stage, stage_specs),
        retrievals=retrieval_bindings,
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    expected_digest = document_digest(expected_binding)
    if receipt.context_digest != expected_digest:
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    if receipt.outcome != "succeeded":
        raise VerificationError(
            f"resolved stage {stage_id!r} requires a successful invocation"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= resolved_stage.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its stage"
        )

    startup = resolved_stage.startup
    if startup.reproducibility != run.reproducibility:
        raise VerificationError(
            f"stage {stage_id!r} startup controls differ from the run plan"
        )
    compute = (stage.environment or run.environment).compute
    recorded_cuda = startup.environment.get("CUDA_VISIBLE_DEVICES")
    if compute.kind == "cuda":
        if recorded_cuda is None or not recorded_cuda.isdigit():
            raise VerificationError(
                f"stage {stage_id!r} startup omitted its selected CUDA device"
            )
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
            cuda_ordinal=int(recorded_cuda),
        )
    else:
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
        )
    if startup.environment != expected_environment:
        raise VerificationError(
            f"stage {stage_id!r} startup environment differs from the plan"
        )
    _verify_startup_backend(
        stage_id,
        compute,
        resolved_stage.execution_context.backend,
    )

    generators = startup.generators
    if any(generator.seed != run.seed for generator in generators):
        raise VerificationError(
            f"stage {stage_id!r} generator receipt uses a different seed"
        )
    family_counts = Counter(generator.family for generator in generators)
    if family_counts["python"] != 1 or family_counts["torch_cpu"] != 1:
        raise VerificationError(
            f"stage {stage_id!r} startup requires one Python and one CPU Torch "
            "generator receipt"
        )
    configured_names = set(expected_binding.numpy_generator_names)
    received_names = {
        generator.name
        for generator in generators
        if generator.family == "numpy_generator"
    }
    if received_names != configured_names:
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts differ"
        )
    if family_counts["numpy_generator"] != len(configured_names):
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts are duplicated"
        )
    legacy_count = sum(generator.family == "numpy_legacy" for generator in generators)
    if legacy_count != int(run.reproducibility.numpy_randomness.capture_legacy_global):
        raise VerificationError(
            f"stage {stage_id!r} legacy NumPy generator receipt differs"
        )
    cuda_receipts = tuple(
        generator for generator in generators if generator.family == "torch_cuda"
    )
    if compute.kind == "cpu" and cuda_receipts:
        raise VerificationError(
            f"stage {stage_id!r} CPU startup includes a CUDA generator receipt"
        )
    if compute.kind == "cuda" and (
        len(cuda_receipts) != 1 or cuda_receipts[0].device_index != 0
    ):
        raise VerificationError(
            f"stage {stage_id!r} CUDA startup requires one visible-device receipt"
        )
    return receipt


def _verify_startup_backend(
    stage_id: StageId,
    compute: ComputeSpec,
    backend: ComputeBackendContext,
) -> None:
    """Apply the named startup.backend rule to observed stage evidence."""
    if compute.kind != backend.kind:
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another backend kind"
        )
    if compute.kind == "cpu":
        if not isinstance(backend, CPUBackendContext):
            raise VerificationError(
                f"startup.backend: stage {stage_id!r} omitted its CPU context"
            )
        return
    if not isinstance(backend, CUDABackendContext):
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} omitted its CUDA context"
        )
    if len(backend.gpu_devices) != compute.count:
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another CUDA device count"
        )
    if any(device.model != compute.model for device in backend.gpu_devices):
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another CUDA model"
        )


def _verify_effective_environment(
    stage_id: StageId,
    requested: EnvironmentSpec,
    resolved: ResolvedEnvironment,
    context: ExecutionContext,
) -> None:
    """Join the frozen environment to its resolved and observed evidence."""
    if resolved.kind != requested.kind:
        raise VerificationError(
            f"environment.kind: stage {stage_id!r} realized another host kind"
        )
    if resolved.compute != requested.compute:
        raise VerificationError(
            f"environment.compute: stage {stage_id!r} realized another compute request"
        )
    if resolved.lockfile.stored_at != requested.lockfile:
        raise VerificationError(
            f"environment.lockfile: stage {stage_id!r} resolved another lockfile"
        )
    if resolved.python_environment != requested.python_environment:
        raise VerificationError(
            f"environment.python: stage {stage_id!r} observed another Python "
            "environment"
        )
    if context.host.provider != requested.kind:
        raise VerificationError(
            f"environment.host: stage {stage_id!r} ran on another host kind"
        )
    if isinstance(requested, GCEEnvironmentSpec):
        if not isinstance(resolved, ResolvedGCEEnvironment):
            raise VerificationError(
                f"gce.environment: stage {stage_id!r} omitted its GCE environment"
            )
        if not isinstance(context.host, GCEHostContext):
            raise VerificationError(
                f"gce.host: stage {stage_id!r} omitted its GCE host evidence"
            )
        if (
            resolved.provisioning != requested.provisioning
            or context.host.provisioning != requested.provisioning
        ):
            raise VerificationError(
                f"gce.provisioning: stage {stage_id!r} used another provisioning source"
            )
        if (
            resolved.machine_type != requested.machine_type
            or context.host.machine_type != requested.machine_type
        ):
            raise VerificationError(
                f"gce.machine_type: stage {stage_id!r} used another machine type"
            )
    elif not isinstance(context.host, LocalHostContext):
        raise VerificationError(
            f"environment.host: stage {stage_id!r} omitted its local host evidence"
        )
    _verify_startup_backend(stage_id, requested.compute, context.backend)


def _verify_unresolved_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: StorageFetcher | None,
) -> None:
    """Verify the terminal receipt for a started stage that did not resolve."""
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(run, stage_id, stage, stage_specs),
        retrievals=receipt.context.retrievals,
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    if receipt.context_digest != document_digest(expected_binding):
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    allowed_outcomes = (
        {"succeeded", "failed"} if attempt.status == "failed" else {attempt.status}
    )
    if receipt.outcome not in allowed_outcomes:
        raise VerificationError(
            f"stage {stage_id!r} invocation outcome differs from its attempt"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= attempt.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its attempt"
        )


def _verify_download_retrievals(
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    resolved: ResolvedDownloadSpec,
    snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
    *,
    fetcher: StorageFetcher | None,
) -> None:
    """Verify each HTTP request, response, body, transport, and delivery path."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    for input_name, retrieval in resolved.retrievals.items():
        try:
            validate_request_policy(retrieval.request, resolved.spec.policy)
            terminal_request = retrieval.request.model_copy(
                update={"url": retrieval.response.response_url}
            )
            validate_request_policy(terminal_request, resolved.spec.policy)
        except HttpRetrievalError as exc:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} violates its frozen policy"
            ) from exc
        if retrieval.response.status not in resolved.spec.policy.accepted_statuses:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} has an unaccepted status"
            )
        expected_path = retrieval_body_path(run, stage_id, input_name)
        if retrieval.body.stored_at.path != expected_path:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body uses another path"
            )
        body_raw = read_resolved_file(retrieval.body, fetcher=fetcher)
        read_snapshot_file(
            snapshot,
            SnapshotFileRef(
                path=expected_path,
                sha256=retrieval.body.sha256,
                bytes=retrieval.body.bytes,
            ),
            fetcher=fetcher,
        )
        if (
            hashlib.sha256(body_raw).hexdigest()
            != retrieval.request.expected_body_sha256
            or len(body_raw) != retrieval.request.expected_body_bytes
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body differs from its request"
            )
        if not (
            attempt.started_at
            <= retrieval.started_at
            < retrieval.completed_at
            <= resolved.completed_at
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} timing falls outside its stage"
            )

        transport = retrieval.transport
        if isinstance(transport.spec, ProjectHttpTransportSpec):
            implementation = transport.spec.implementation
            implementation_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=implementation.path,
                )
            )
            if (
                len(implementation_raw) != implementation.bytes
                or hashlib.sha256(implementation_raw).hexdigest()
                != implementation.sha256
            ):
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} transport source differs"
                )
            parameter_reference = transport.spec.parameter_model
            parameter_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=parameter_reference.path,
                )
            )
            try:
                verify_parameter_model_bytes(parameter_reference, parameter_raw)
            except ParameterValidationError as exc:
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} transport parameter model differs"
                ) from exc
            for executable in transport.external_executables:
                try:
                    executable_raw = executable.path.read_bytes()
                except OSError as exc:
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable is unavailable"
                    ) from exc
                if (
                    len(executable_raw) != executable.spec.bytes
                    or hashlib.sha256(executable_raw).hexdigest()
                    != executable.spec.sha256
                ):
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable identity differs"
                    )


def verify_attempt_stages(
    attempt: RunAttempt,
    run: RunSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    require_complete: bool,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, ResolvedBaseSpec]:
    """Verify the ordered resolved-stage prefix retained by one attempt."""
    expected_stage_ids = tuple(stage.stage_id for stage in run.stages)
    resolved_stage_ids = tuple(stage.stage_id for stage in attempt.resolved_stages)
    if resolved_stage_ids != expected_stage_ids[: len(resolved_stage_ids)]:
        raise VerificationError(
            "attempt resolved stages must form an ordered run-stage prefix"
        )
    if require_complete and resolved_stage_ids != expected_stage_ids:
        raise VerificationError("successful attempt must contain every run stage")

    if set(stage_specs) != set(expected_stage_ids):
        raise VerificationError("loaded stage specs do not match the run stage plan")
    if len(attempt.invocations) < len(attempt.resolved_stages):
        raise VerificationError(
            "attempt must retain an invocation receipt for every resolved stage"
        )
    if len(attempt.invocations) > len(expected_stage_ids):
        raise VerificationError("attempt contains more invocations than planned stages")
    if len(attempt.invocations) > len(attempt.resolved_stages) + 1:
        raise VerificationError(
            "attempt contains invocations after its unresolved active stage"
        )
    for index, invocation in enumerate(attempt.invocations):
        expected_path = stage_invocation_path(
            run,
            attempt.attempt_id,
            expected_stage_ids[index],
        )
        if invocation.stored_at.path != expected_path:
            raise VerificationError(
                "attempt invocation receipts must follow planned stage order"
            )

    verified_stages: dict[StageId, ResolvedBaseSpec] = {}

    for stage_index, stage_reference in enumerate(attempt.resolved_stages):
        expected_resolved_path = resolved_stage_spec_path(
            run,
            stage_reference.stage_id,
        )
        if stage_reference.resolved_spec.path != expected_resolved_path:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} resolved spec is outside "
                "its canonical run path"
            )

        raw = read_snapshot_file(
            stage_reference.snapshot,
            stage_reference.resolved_spec,
            fetcher=fetcher,
        )
        try:
            resolved_spec = RESOLVED_SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} file is not a valid "
                "resolved stage spec"
            ) from exc

        stage_spec = stage_specs[stage_reference.stage_id]

        for artifact_name, artifact_spec in stage_spec.artifacts.items():
            if repo_file_paths_overlap(
                stage_reference.resolved_spec.path,
                artifact_spec.path,
            ):
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} resolved spec collides "
                    f"with artifact {artifact_name!r}"
                )

        if resolved_spec.spec != stage_spec:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} does not embed its stage spec"
            )

        invocation_reference = attempt.invocations[stage_index]
        if resolved_spec.invocation != invocation_reference:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} invocation reference differs "
                "from its attempt"
            )
        if not isinstance(stage_spec, ParameterizedSpec):
            raise VerificationError("resolved stage is not parameterized")
        _verify_stage_invocation(
            invocation_reference,
            attempt=attempt,
            run=run,
            stage_id=stage_reference.stage_id,
            stage=cast(ParameterizedStageSpec, stage_spec),
            stage_specs=stage_specs,
            resolved_stage=resolved_spec,
            fetcher=fetcher,
        )

        source_location = resolved_spec.source.stored_at
        if (
            source_location.repository != run.source.repository
            or source_location.commit != run.source.commit
        ):
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} source does not match the "
                "run source snapshot"
            )

        if not (
            attempt.started_at < resolved_spec.completed_at <= attempt.completed_at
        ):
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} completion time falls outside "
                "its containing attempt"
            )

        if isinstance(resolved_spec, ResolvedDownloadSpec):
            _verify_download_retrievals(
                attempt,
                run,
                stage_reference.stage_id,
                resolved_spec,
                stage_reference.snapshot,
                fetcher=fetcher,
            )

        if verified_stages:
            previous_completed_at = next(
                reversed(verified_stages.values())
            ).completed_at
            if resolved_spec.completed_at < previous_completed_at:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} completed before its "
                    "preceding stage"
                )

        read_resolved_file(resolved_spec.source, fetcher=fetcher)
        read_resolved_file(resolved_spec.environment.lockfile, fetcher=fetcher)

        requested_environment = stage_spec.environment or run.environment
        resolved_environment = resolved_spec.environment
        _verify_effective_environment(
            stage_reference.stage_id,
            requested_environment,
            resolved_environment,
            resolved_spec.execution_context,
        )

        expected_command = (
            "python",
            "-m",
            "viper.stage_worker",
        )
        if resolved_spec.command != expected_command:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} command does not match "
                "the run plan"
            )

        for artifact_name, artifact in resolved_spec.artifacts.items():
            declaration = stage_spec.artifacts[artifact_name]
            verified_artifact = verify_snapshot_artifact(
                stage_reference,
                artifact,
                data_role=declaration.data_role,
                fetcher=fetcher,
            )
            load_verified_artifact(
                run,
                declaration,
                artifact_name,
                verified_artifact,
                policy=policy,
                fetcher=fetcher,
            )

        verified_stages[stage_reference.stage_id] = resolved_spec

    if len(attempt.invocations) == len(attempt.resolved_stages) + 1:
        stage_id = expected_stage_ids[len(attempt.resolved_stages)]
        stage_spec = stage_specs[stage_id]
        if not isinstance(stage_spec, ParameterizedSpec):
            raise VerificationError("unresolved stage invocation is not parameterized")
        _verify_unresolved_stage_invocation(
            attempt.invocations[-1],
            attempt=attempt,
            run=run,
            stage_id=stage_id,
            stage=cast(ParameterizedStageSpec, stage_spec),
            stage_specs=stage_specs,
            fetcher=fetcher,
        )

    return verified_stages


def verify_resolved_stages(
    resolved_run: ResolvedRun,
    run: RunSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, ResolvedBaseSpec]:
    """Verify the complete stage sequence retained by a successful run."""
    if resolved_run.status != "succeeded":
        raise VerificationError("resolved-stage verification requires a succeeded run")

    attempts = verify_run_attempt_references(
        resolved_run,
        run,
        fetcher=fetcher,
    )
    successful_attempt = next(
        (
            attempt
            for attempt in attempts
            if attempt.attempt_id == resolved_run.successful_attempt_id
        ),
        None,
    )
    if successful_attempt is None or successful_attempt.status != "succeeded":
        raise VerificationError("successful attempt could not be identified")

    return verify_attempt_stages(
        successful_attempt,
        run,
        stage_specs,
        require_complete=True,
        policy=policy,
        fetcher=fetcher,
    )


def verify_attempt_journal(
    attempt: RunAttempt,
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify one terminal attempt journal and its canonical identity."""
    expected_path = f"{run_root(run)}/attempts/{attempt.attempt_id}/journal.jsonl"
    if attempt.journal.stored_at.path != expected_path:
        raise VerificationError("attempt journal path is not canonical")
    try:
        entries = parse_journal_bytes(
            read_resolved_file(attempt.journal, fetcher=fetcher)
        )
    except ValueError as exc:
        raise VerificationError("attempt journal is invalid") from exc
    if not entries or entries[-1].state != "terminal":
        raise VerificationError("published attempt journal is not terminal")


def verify_attempt_files(
    attempt: RunAttempt,
    run: RunSpec,
    experiment: ExperimentSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[Measurement, ...]:
    """Verify an attempt's measurements and logs against their file identities."""
    attempt_file_snapshots = {
        identity
        for reference in (
            *attempt.measurement_files,
            *attempt.metric_verification_files,
            *attempt.log_files,
        )
        if (identity := _artifact_revision_identity(reference.stored_at)) is not None
    }
    if len(attempt_file_snapshots) > 1:
        raise VerificationError(
            "attempt measurement and log files must use one immutable snapshot"
        )

    completed_stage_ids = {stage.stage_id for stage in attempt.resolved_stages}
    planned_stage_ids = tuple(stage.stage_id for stage in run.stages)
    permitted_log_stage_ids = set(completed_stage_ids)
    if attempt.status != "succeeded" and len(completed_stage_ids) < len(
        planned_stage_ids
    ):
        permitted_log_stage_ids.add(planned_stage_ids[len(completed_stage_ids)])
    permitted_metrics = {metric.metric_id for metric in experiment.metrics}
    measurements: list[Measurement] = []
    root = run_root(run)
    for reference in attempt.measurement_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError(
                "measurement files must use immutable artifact storage"
            )
        measurement_root = f"{root}/attempts/{attempt.attempt_id}/measurements"
        if not str(reference.stored_at.path).startswith(f"{measurement_root}/"):
            raise VerificationError(
                "measurement file is outside the canonical run path"
            )

        raw = read_resolved_file(reference, fetcher=fetcher)
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise VerificationError("measurement file is not valid UTF-8") from exc

        for line in lines:
            if not line.strip():
                continue
            try:
                measurement = Measurement.model_validate(
                    json.loads(line, object_pairs_hook=unique_json_object)
                )
            except ValueError as exc:
                raise VerificationError(
                    "measurement file contains an invalid Measurement row"
                ) from exc

            if measurement.run_id != run.run_id:
                raise VerificationError("measurement run ID does not match the run")
            if measurement.attempt_id != attempt.attempt_id:
                raise VerificationError(
                    "measurement attempt ID does not match its containing attempt"
                )
            if measurement.stage_id not in completed_stage_ids:
                raise VerificationError(
                    "measurement stage is absent from its containing attempt"
                )
            if measurement.metric_id not in permitted_metrics:
                raise VerificationError(
                    "measurement metric is absent from the experiment"
                )
            stage_spec = stage_specs.get(measurement.stage_id)
            if stage_spec is None:
                raise VerificationError(
                    "measurement stage has no loaded stage specification"
                )
            if measurement.metric_id not in stage_spec.metric_ids:
                raise VerificationError(
                    "measurement metric is absent from its stage spec"
                )
            expected_path = (
                f"{measurement_root}/{measurement.stage_id}."
                f"{measurement.metric_id}.jsonl"
            )
            if reference.stored_at.path != expected_path:
                raise VerificationError(
                    "measurement file path does not match its stage and metric"
                )
            if not (
                attempt.started_at <= measurement.measured_at <= attempt.completed_at
            ):
                raise VerificationError(
                    "measurement timestamp falls outside its containing attempt"
                )
            measurements.append(measurement)

    if attempt.status == "succeeded":
        for stage_id in completed_stage_ids:
            stage_spec = stage_specs[stage_id]
            if not isinstance(stage_spec, EvaluateSpec):
                continue
            for metric_id in stage_spec.metric_ids:
                matches = [
                    measurement
                    for measurement in measurements
                    if measurement.stage_id == stage_id
                    and measurement.metric_id == metric_id
                ]
                if len(matches) != 1:
                    raise VerificationError(
                        f"successful evaluation stage {stage_id!r} must record "
                        f"exactly one measurement for metric {metric_id!r}"
                    )

    for reference in attempt.log_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError("log files must use immutable artifact storage")
        log_pattern = re.compile(
            rf"^{re.escape(root)}/attempts/{attempt.attempt_id}/logs/"
            r"([a-z][a-z0-9_]*)\.(stdout|stderr)\.log$"
        )
        match = log_pattern.fullmatch(str(reference.stored_at.path))
        if match is None or match.group(1) not in permitted_log_stage_ids:
            raise VerificationError(
                "log file path does not match its attempt and stage"
            )
        read_resolved_file(reference, fetcher=fetcher)

    return tuple(measurements)


def verify_measurement_stage_times(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    measurements: tuple[Measurement, ...],
    experiment: ExperimentSpec,
) -> None:
    """Place live and recomputed measurements on the correct stage boundary."""
    metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for measurement in measurements:
        resolved_stage = resolved_stages.get(measurement.stage_id)
        if resolved_stage is None:
            raise VerificationError("measurement stage has no resolved stage result")
        metric = metrics[measurement.metric_id]
        if (
            metric.mode == "live"
            and measurement.measured_at > resolved_stage.completed_at
        ):
            raise VerificationError(
                "live measurement timestamp follows its named stage completion"
            )
        if (
            metric.mode == "recompute"
            and measurement.measured_at < resolved_stage.completed_at
        ):
            raise VerificationError(
                "recomputed measurement timestamp precedes stage completion"
            )


def _verify_metric_worker_runtime(
    run: RunSpec,
    stage: BaseSpec,
    receipt: MetricExecutionReceipt,
) -> None:
    """Match one metric worker's startup and runtime facts to the run plan."""
    startup = receipt.startup
    if startup.reproducibility != run.reproducibility:
        raise VerificationError("metric worker reproducibility controls differ")
    compute = (stage.environment or run.environment).compute
    recorded_cuda = startup.environment.get("CUDA_VISIBLE_DEVICES")
    if compute.kind == "cuda":
        if recorded_cuda is None or not recorded_cuda.isdigit():
            raise VerificationError("metric worker omitted its selected CUDA device")
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
            cuda_ordinal=int(recorded_cuda),
        )
    else:
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
        )
    if startup.environment != expected_environment:
        raise VerificationError("metric worker startup environment differs")
    if any(generator.seed != run.seed for generator in startup.generators):
        raise VerificationError("metric worker generator seed differs")
    family_counts = Counter(generator.family for generator in startup.generators)
    if family_counts["python"] != 1 or family_counts["torch_cpu"] != 1:
        raise VerificationError("metric worker generator receipts are incomplete")
    expected_numpy_names = set(run.reproducibility.numpy_randomness.generators)
    received_numpy_names = {
        generator.name
        for generator in startup.generators
        if generator.family == "numpy_generator"
    }
    if received_numpy_names != expected_numpy_names:
        raise VerificationError("metric worker NumPy generators differ")
    context = receipt.execution_context
    effective_environment = stage.environment or run.environment
    if receipt.python_environment != effective_environment.python_environment:
        raise VerificationError("metric worker Python environment differs")
    if context.host.provider != effective_environment.kind:
        raise VerificationError("metric worker host provider differs")
    if isinstance(effective_environment, GCEEnvironmentSpec):
        if not isinstance(context.host, GCEHostContext):
            raise VerificationError("metric worker omitted its GCE host context")
        if context.host.machine_type != effective_environment.machine_type:
            raise VerificationError("metric worker machine type differs")
    if context.backend.kind != compute.kind:
        raise VerificationError("metric worker compute backend differs")
    if compute.kind == "cuda":
        if not isinstance(context.backend, CUDABackendContext):
            raise VerificationError("metric worker omitted its CUDA context")
        if len(context.backend.gpu_devices) != compute.count:
            raise VerificationError("metric worker CUDA device count differs")
        if any(device.model != compute.model for device in context.backend.gpu_devices):
            raise VerificationError("metric worker CUDA model differs")


def verify_recomputed_metrics(
    attempt: RunAttempt,
    plan: VerifiedRunPlan,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    measurements: tuple[Measurement, ...],
    stored_inputs: Mapping[StageId, Mapping[InputName, VerifiedInput]],
    future_inputs: Mapping[StageId, Mapping[InputName, VerifiedInput]],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify persisted production and recomputation evidence for each metric."""
    del policy
    metric_specs = {metric.metric_id: metric for metric in plan.experiment.metrics}
    stage_refs = {stage.stage_id: stage for stage in attempt.resolved_stages}
    expected_keys = {
        (stage_id, metric_id)
        for stage_id, stage in plan.stages.items()
        if stage_id in stage_refs
        for metric_id in stage.metric_ids
        if metric_specs[metric_id].mode == "recompute"
    }
    if len(attempt.metric_verification_files) != len(expected_keys):
        raise VerificationError(
            "recomputed metrics require one immutable verification receipt each"
        )
    receipts: dict[tuple[StageId, str], MetricVerificationReceipt] = {}
    root_path = run_root(plan.run)
    for reference in attempt.metric_verification_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError(
                "metric verification files must use immutable artifact storage"
            )
        raw = read_resolved_file(reference, fetcher=fetcher)
        try:
            receipt = MetricVerificationReceipt.model_validate(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError("metric verification receipt is invalid") from exc
        expected_path = (
            f"{root_path}/attempts/{attempt.attempt_id}/metric_verification/"
            f"{receipt.stage_id}.{receipt.metric_id}.yaml"
        )
        if reference.stored_at.path != expected_path:
            raise VerificationError(
                "metric verification receipt is outside its canonical path"
            )
        key = (receipt.stage_id, receipt.metric_id)
        if key in receipts:
            raise VerificationError(
                "metric verification receipt identity is duplicated"
            )
        receipts[key] = receipt
    if set(receipts) != expected_keys:
        raise VerificationError("metric verification receipts select different metrics")

    for stage_id, stage in plan.stages.items():
        if stage_id not in stage_refs:
            continue
        for metric_id in stage.metric_ids:
            metric = metric_specs[metric_id]
            if metric.mode != "recompute":
                continue
            recorded = tuple(
                measurement
                for measurement in measurements
                if measurement.stage_id == stage_id
                and measurement.metric_id == metric_id
            )
            if len(recorded) != 1:
                raise VerificationError(
                    f"recomputed metric {metric_id!r} of stage {stage_id!r} "
                    "requires exactly one measurement"
                )
            receipt = receipts[(stage_id, metric_id)]
            if receipt.measurement != recorded[0]:
                raise VerificationError(
                    f"metric {metric_id!r} receipt embeds a different measurement"
                )
            if receipt.production.implementation != metric.implementation:
                raise VerificationError(
                    f"metric {metric_id!r} production implementation differs"
                )
            if receipt.production.params != metric.params:
                raise VerificationError(
                    f"metric {metric_id!r} production parameters differ"
                )
            if receipt.comparator != metric.comparator:
                raise VerificationError(
                    f"metric {metric_id!r} comparator differs from MetricSpec"
                )
            resolved_stage = resolved_stages[stage_id]
            stage_ref = stage_refs[stage_id]
            verified_artifacts = {
                name: verify_snapshot_artifact(
                    stage_ref,
                    resolved_artifact,
                    data_role=stage.artifacts[name].data_role,
                    fetcher=fetcher,
                )
                for name, resolved_artifact in resolved_stage.artifacts.items()
            }
            inputs = {
                **stored_inputs.get(stage_id, {}),
                **future_inputs.get(stage_id, {}),
            }
            metric_inputs: dict[str, VerifiedInput] = {}
            metric_artifacts: dict[str, VerifiedArtifact] = {}
            for dependency in metric.dependencies:
                if dependency.source == "input":
                    selected_input = inputs.get(dependency.name)
                    if selected_input is None:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} is absent"
                        )
                    if selected_input.data_role != dependency.required_data_role:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} data role differs"
                        )
                    metric_inputs[dependency.name] = selected_input
                else:
                    selected_artifact = verified_artifacts.get(dependency.name)
                    if selected_artifact is None:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} is absent"
                        )
                    if selected_artifact.data_role != dependency.required_data_role:
                        raise VerificationError(
                            f"metric dependency {dependency.name!r} data role differs"
                        )
                    metric_artifacts[dependency.name] = selected_artifact
            expected_dependencies = tuple(
                ResolvedMetricDependency(
                    dependency=dependency,
                    files=(
                        metric_inputs[dependency.name].references
                        if dependency.source == "input"
                        else metric_artifacts[dependency.name].references
                    ),
                )
                for dependency in metric.dependencies
            )
            if tuple(
                value.dependency for value in receipt.production.dependencies
            ) != tuple(value.dependency for value in expected_dependencies):
                raise VerificationError(
                    f"metric {metric_id!r} dependency declarations differ"
                )
            for received, expected in zip(
                receipt.production.dependencies,
                expected_dependencies,
                strict=True,
            ):
                received_identities = tuple(
                    (reference.sha256, reference.bytes) for reference in received.files
                )
                expected_identities = tuple(
                    (reference.sha256, reference.bytes) for reference in expected.files
                )
                if received_identities != expected_identities:
                    raise VerificationError(
                        f"metric {metric_id!r} dependency file identities differ"
                    )
                for reference in received.files:
                    read_resolved_file(reference, fetcher=fetcher)
            for worker in (receipt.production, receipt.recomputation):
                _verify_metric_worker_runtime(plan.run, stage, worker)
            if not (
                resolved_stage.completed_at
                <= receipt.production.started_at
                < receipt.production.completed_at
                <= recorded[0].measured_at
                <= receipt.recomputation.started_at
                < receipt.recomputation.completed_at
                <= receipt.completed_at
                <= attempt.completed_at
            ):
                raise VerificationError(
                    f"metric {metric_id!r} execution timing is inconsistent"
                )
            if not compare_metric_values(
                recorded[0].value,
                receipt.recomputation.value,
                cast(FloatComparator, metric.comparator),
            ):
                raise VerificationError(
                    f"recomputed metric {metric_id!r} does not match its measurement"
                )
            if not receipt.passed:
                raise VerificationError(
                    f"metric {metric_id!r} verification receipt records failure"
                )


def verify_run_result(
    resolved_run: ResolvedRun,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedRunResult:
    """Verify a terminal run from its RunSpec through every completed attempt."""
    plan = verify_run_plan(resolved_run, fetcher=fetcher)
    attempts = verify_run_attempt_references(
        resolved_run,
        plan.run,
        fetcher=fetcher,
    )
    all_measurements: list[Measurement] = []
    successful_stages: dict[StageId, ResolvedBaseSpec] = {}
    stage_result_snapshots: set[tuple[str, ...]] = set()
    attempt_file_snapshots: set[tuple[str, ...]] = set()

    for attempt in attempts:
        current_stage_result_snapshots = {
            _snapshot_identity(stage.snapshot) for stage in attempt.resolved_stages
        }
        if stage_result_snapshots & current_stage_result_snapshots:
            raise VerificationError(
                "run attempts must use distinct stage-result snapshots"
            )
        stage_result_snapshots.update(current_stage_result_snapshots)

        current_attempt_file_snapshots = {
            identity
            for reference in (
                attempt.journal,
                *attempt.measurement_files,
                *attempt.metric_verification_files,
                *attempt.log_files,
            )
            if (identity := _artifact_revision_identity(reference.stored_at))
            is not None
        }
        if attempt_file_snapshots & current_attempt_file_snapshots:
            raise VerificationError(
                "run attempts must use distinct measurement and log snapshots"
            )
        attempt_file_snapshots.update(current_attempt_file_snapshots)

    if stage_result_snapshots & attempt_file_snapshots:
        raise VerificationError(
            "stage-result and attempt-file snapshots must be distinct"
        )

    for attempt in attempts:
        complete = attempt.status == "succeeded"
        verify_attempt_journal(attempt, plan.run, fetcher=fetcher)
        verified_stages = verify_attempt_stages(
            attempt,
            plan.run,
            plan.stages,
            require_complete=complete,
            policy=policy,
            fetcher=fetcher,
        )
        stored_inputs = verify_stored_inputs(
            verified_stages,
            policy=policy,
            fetcher=fetcher,
        )
        future_inputs = verify_attempt_future_inputs(
            attempt,
            plan.run,
            verified_stages,
            fetcher=fetcher,
        )
        attempt_measurements = verify_attempt_files(
            attempt,
            plan.run,
            plan.experiment,
            plan.stages,
            fetcher=fetcher,
        )
        verify_measurement_stage_times(
            verified_stages,
            attempt_measurements,
            plan.experiment,
        )
        verify_recomputed_metrics(
            attempt,
            plan,
            verified_stages,
            attempt_measurements,
            stored_inputs,
            future_inputs,
            policy=policy,
            fetcher=fetcher,
        )
        all_measurements.extend(attempt_measurements)
        if attempt.attempt_id == resolved_run.successful_attempt_id:
            successful_stages = verified_stages

    if resolved_run.status == "succeeded":
        estimator_stage = successful_stages.get(plan.run.estimator.stage_id)
        if estimator_stage is None:
            raise VerificationError("successful run has no estimator-producing stage")
        if plan.run.estimator.artifact_name not in estimator_stage.artifacts:
            raise VerificationError("successful run has no selected estimator artifact")

    return VerifiedRunResult(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        resolved_stages=successful_stages,
        measurements=tuple(all_measurements),
    )


def verify_promoted_artifact(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    expected_data_role: DataRole | None = None,
    materialization_path: RepoRelPath | None = None,
    fetcher: StorageFetcher | None = None,
) -> VerifiedArtifact:
    """Follow a promoted artifact pointer through its completed producer run."""
    resolved_run_raw = read_resolved_file(pointer.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(resolved_run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "artifact pointer run is not a valid ResolvedRun document"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
    expected_run_path = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if pointer.run.stored_at.path != expected_run_path:
        raise VerificationError(
            "artifact pointer run reference is outside the canonical run path"
        )

    if (
        verified_run.plan.run.benchmark_id is not None
        and pointer.artifact == verified_run.plan.run.estimator
        and pointer.benchmark_result is None
    ):
        raise VerificationError(
            "promotion of a benchmarked estimator requires a benchmark result"
        )

    producer_spec = verified_run.resolved_stages.get(pointer.artifact.stage_id)
    if producer_spec is None:
        raise VerificationError("artifact pointer selects an absent producer stage")

    artifact = producer_spec.artifacts.get(pointer.artifact.artifact_name)
    if artifact is None:
        raise VerificationError("artifact pointer selects an undeclared artifact")
    declaration = producer_spec.spec.artifacts[pointer.artifact.artifact_name]

    if pointer.benchmark_result is not None:
        benchmark_result_raw = read_resolved_file(
            pointer.benchmark_result,
            fetcher=fetcher,
        )
        try:
            benchmark_result = BenchmarkResult.model_validate(
                parse_yaml_bytes(benchmark_result_raw)
            )
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                "artifact pointer benchmark result is invalid"
            ) from exc

        verify_benchmark_result(
            benchmark_result,
            policy=policy,
            fetcher=fetcher,
        )
        expected_result_path = (
            f"{run_root(verified_run.plan.run)}/benchmark.result.yaml"
        )
        if pointer.benchmark_result.stored_at.path != expected_result_path:
            raise VerificationError(
                "artifact pointer benchmark result is outside the canonical run path"
            )
        if benchmark_result.status != "passed":
            raise VerificationError(
                "artifact pointer benchmark result must have passed"
            )
        if benchmark_result.run != pointer.run:
            raise VerificationError(
                "artifact pointer and benchmark result select different runs"
            )
        if pointer.artifact != verified_run.plan.run.estimator:
            raise VerificationError("benchmark promotion must select the run estimator")

    successful_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    producer_stage = next(
        stage
        for stage in successful_attempt.resolved_stages
        if stage.stage_id == pointer.artifact.stage_id
    )
    verified_artifact = verify_snapshot_artifact(
        producer_stage,
        artifact,
        data_role=declaration.data_role,
        fetcher=fetcher,
    )
    if (
        expected_data_role is not None
        and verified_artifact.data_role != expected_data_role
    ):
        raise VerificationError(
            f"selected artifact data_role {verified_artifact.data_role!r} does not "
            f"match stored input data_role {expected_data_role!r}"
        )
    if materialization_path is not None:
        load_verified_artifact(
            verified_run.plan.run,
            declaration,
            pointer.artifact.artifact_name,
            verified_artifact,
            policy=policy,
            materialization_path=materialization_path,
            fetcher=fetcher,
        )
    return verified_artifact


def verify_stored_input_selections(
    stage_id: StageId,
    stage_spec: InternalSpec,
    pointers: Mapping[InputName, ArtifactPointer],
) -> None:
    """Verify relationships among stored pointers consumed by one stage."""
    if isinstance(stage_spec, TrainSpec):
        model_input = stage_spec.inputs.get(PARAMETERS_INPUT)
        state_input = stage_spec.inputs.get(RESUME_STATE_INPUT)
        if isinstance(model_input, StoredInputRef) and isinstance(
            state_input,
            StoredInputRef,
        ):
            model_pointer = pointers[PARAMETERS_INPUT]
            state_pointer = pointers[RESUME_STATE_INPUT]
            if model_pointer.run != state_pointer.run:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one resolved run"
                )
            if model_pointer.artifact.stage_id != state_pointer.artifact.stage_id:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one producer stage"
                )
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored checkpoint model input of stage {stage_id!r} must "
                    "select parameters"
                )
            if state_pointer.artifact.artifact_name != RESUME_STATE:
                raise VerificationError(
                    f"stored checkpoint state input of stage {stage_id!r} must "
                    "select resume_state"
                )

    if isinstance(stage_spec, EvaluateSpec):
        model_input = stage_spec.inputs[PARAMETERS_INPUT]
        if isinstance(model_input, StoredInputRef):
            model_pointer = pointers[PARAMETERS_INPUT]
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored evaluation model input of stage {stage_id!r} must "
                    "select parameters"
                )


def verify_stored_inputs(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify every promoted artifact consumed by the resolved stages."""
    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}

    for stage_id, resolved_stage in resolved_stages.items():
        if not isinstance(resolved_stage, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}
        parsed_pointers: dict[InputName, ArtifactPointer] = {}

        for input_name, spec_input in resolved_stage.spec.inputs.items():
            if not isinstance(spec_input, StoredInputRef):
                continue

            resolved_input = resolved_stage.inputs.get(input_name)
            if not isinstance(resolved_input, ResolvedStoredInputRef):
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} has no "
                    "resolved stored-input reference"
                )

            if resolved_input.pointer.stored_at != spec_input.pointer:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} resolved "
                    "a different pointer location than the stage spec"
                )

            pointer_raw = read_resolved_file(
                resolved_input.pointer,
                fetcher=fetcher,
            )
            try:
                pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} pointer "
                    "is not a valid ArtifactPointer document"
                ) from exc

            parsed_pointers[input_name] = pointer

            verified_artifact = verify_promoted_artifact(
                pointer,
                policy=policy,
                expected_data_role=spec_input.data_role,
                materialization_path=spec_input.path,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=spec_input.path,
                data_role=spec_input.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        verify_stored_input_selections(
            stage_id,
            resolved_stage.spec,
            parsed_pointers,
        )

        if stage_inputs:
            verified_inputs[stage_id] = stage_inputs

    return verified_inputs


def verify_future_inputs(
    resolved_run: ResolvedRun,
    run: RunSpec,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify future inputs selected by the successful run attempt."""
    if resolved_run.status != "succeeded":
        raise VerificationError("future-input verification requires a succeeded run")

    attempts = verify_run_attempt_references(
        resolved_run,
        run,
        fetcher=fetcher,
    )
    successful_attempt = next(
        (
            attempt
            for attempt in attempts
            if attempt.attempt_id == resolved_run.successful_attempt_id
        ),
        None,
    )
    if successful_attempt is None or successful_attempt.status != "succeeded":
        raise VerificationError("successful attempt could not be identified")

    return verify_attempt_future_inputs(
        successful_attempt,
        run,
        resolved_stages,
        fetcher=fetcher,
    )


def verify_attempt_future_inputs(
    attempt: RunAttempt,
    run: RunSpec,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify same-attempt inputs consumed by every completed stage."""
    stage_positions: dict[StageId, int] = {}
    for position, stage_reference in enumerate(run.stages):
        stage_positions[stage_reference.stage_id] = position

    completed_stages = {stage.stage_id: stage for stage in attempt.resolved_stages}

    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    for consumer_stage_id, resolved_consumer_spec in resolved_stages.items():
        # Not checking download specs because they don't have any inputs to verify
        if not isinstance(resolved_consumer_spec, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}

        for input_name, spec_input in resolved_consumer_spec.spec.inputs.items():
            if not isinstance(spec_input, FutureInputRef):
                continue

            resolved_input = resolved_consumer_spec.inputs[input_name]

            if not isinstance(resolved_input, ResolvedFutureInputRef):
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} has no resolved future-input "
                    "reference"
                )

            producer_stage_id = spec_input.producer_stage_id

            if consumer_stage_id not in stage_positions:
                raise VerificationError(
                    f"consumer stage {consumer_stage_id!r} is not in the run plan"
                )

            if producer_stage_id not in stage_positions:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} is not in the run plan"
                )

            if stage_positions[producer_stage_id] >= stage_positions[consumer_stage_id]:
                raise VerificationError(
                    f"future input {input_name!r} must name an earlier stage"
                )

            resolved_producer_spec = resolved_stages.get(producer_stage_id)

            if resolved_producer_spec is None:
                raise VerificationError(
                    f"resolved producer stage {producer_stage_id!r} is missing"
                )

            producer_stage_reference = completed_stages.get(producer_stage_id)
            if producer_stage_reference is None:
                raise VerificationError(
                    f"successful attempt has no resolved stage for "
                    f"{producer_stage_id!r}"
                )

            if resolved_input.producer != producer_stage_reference:
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} does not identify the completed "
                    "producer stage"
                )

            artifact_name = spec_input.producer_artifact
            artifact = resolved_producer_spec.artifacts.get(artifact_name)
            if artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} has no artifact "
                    f"named {artifact_name!r}"
                )

            declared_artifact = resolved_producer_spec.spec.artifacts.get(artifact_name)
            if declared_artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} did not declare "
                    f"artifact {artifact_name!r}"
                )

            verified_artifact = verify_snapshot_artifact(
                producer_stage_reference,
                artifact,
                data_role=declared_artifact.data_role,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=declared_artifact.path,
                data_role=declared_artifact.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        if stage_inputs:
            verified_inputs[consumer_stage_id] = stage_inputs

    return verified_inputs


def verify_benchmark_result(
    result: BenchmarkResult,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedBenchmarkResult:
    """Verify benchmark parity and metric criteria across two executions."""
    benchmark_raw = read_resolved_file(result.benchmark, fetcher=fetcher)
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(benchmark_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid BenchmarkSpec"
        ) from exc

    run_raw = read_resolved_file(result.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid ResolvedRun"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)

    if result.completed_at < resolved_run.completed_at:
        raise VerificationError(
            "benchmark result cannot precede the selected run completion"
        )

    expected_run_location = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if result.run.stored_at.path != expected_run_location:
        raise VerificationError(
            "benchmark result run reference is outside the canonical run path"
        )

    expected_benchmark_location = GitFileRef(
        repository=verified_run.plan.run.source.repository,
        commit=verified_run.plan.run.source.commit,
        path=f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if result.benchmark.stored_at != expected_benchmark_location:
        raise VerificationError(
            "benchmark result reference does not match the run source snapshot"
        )

    if verified_run.plan.benchmark != benchmark:
        raise VerificationError(
            "benchmark result and run plan select different benchmark specs"
        )

    confirmation = read_attempt_reference(
        result.confirmation,
        verified_run.plan.run,
        fetcher=fetcher,
    )
    if confirmation.status != "succeeded":
        raise VerificationError("benchmark confirmation attempt must succeed")
    if confirmation.purpose != "benchmark_confirmation":
        raise VerificationError("benchmark confirmation has the wrong purpose")
    if result.completed_at < confirmation.completed_at:
        raise VerificationError(
            "benchmark result cannot precede confirmation completion"
        )

    selected_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    original_attempt_ids = {attempt.attempt_id for attempt in verified_run.attempts}
    if confirmation.attempt_id in original_attempt_ids:
        raise VerificationError("benchmark confirmation must use a new attempt ID")
    if confirmation.attempt_id <= max(original_attempt_ids):
        raise VerificationError(
            "benchmark confirmation attempt ID must follow the candidate history"
        )

    original_snapshots = {
        _snapshot_identity(stage.snapshot)
        for attempt in verified_run.attempts
        for stage in attempt.resolved_stages
    }
    confirmation_snapshots = {
        _snapshot_identity(stage.snapshot) for stage in confirmation.resolved_stages
    }
    if original_snapshots & confirmation_snapshots:
        raise VerificationError(
            "benchmark confirmation must use new stage-result snapshots"
        )

    original_attempt_file_snapshots = {
        identity
        for attempt in verified_run.attempts
        for reference in (
            attempt.journal,
            *attempt.measurement_files,
            *attempt.metric_verification_files,
            *attempt.log_files,
        )
        if (identity := _artifact_revision_identity(reference.stored_at)) is not None
    }
    confirmation_attempt_file_snapshots = {
        identity
        for reference in (
            confirmation.journal,
            *confirmation.measurement_files,
            *confirmation.metric_verification_files,
            *confirmation.log_files,
        )
        if (identity := _artifact_revision_identity(reference.stored_at)) is not None
    }
    if original_attempt_file_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation must use a new measurement and log snapshot"
        )
    if confirmation_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation stage-result and attempt-file snapshots "
            "must be distinct"
        )

    confirmation_stages = verify_attempt_stages(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.stages,
        require_complete=True,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_stored_inputs = verify_stored_inputs(
        confirmation_stages,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_future_inputs = verify_attempt_future_inputs(
        confirmation,
        verified_run.plan.run,
        confirmation_stages,
        fetcher=fetcher,
    )
    confirmation_measurements = verify_attempt_files(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.experiment,
        verified_run.plan.stages,
        fetcher=fetcher,
    )
    verify_measurement_stage_times(
        confirmation_stages,
        confirmation_measurements,
        verified_run.plan.experiment,
    )
    verify_recomputed_metrics(
        confirmation,
        verified_run.plan,
        confirmation_stages,
        confirmation_measurements,
        confirmation_stored_inputs,
        confirmation_future_inputs,
        policy=policy,
        fetcher=fetcher,
    )

    estimator_ref = verified_run.plan.run.estimator
    selected_estimator = verified_run.resolved_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    confirmation_estimator = confirmation_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    estimator_parity = selected_estimator == confirmation_estimator

    evaluation_stage_ids = [
        stage_id
        for stage_id, stage in verified_run.plan.stages.items()
        if isinstance(stage, EvaluateSpec)
    ]
    if len(evaluation_stage_ids) != 1:
        raise VerificationError("benchmark verification requires one evaluation stage")
    evaluation_stage_id = evaluation_stage_ids[0]
    selected_predictions = verified_run.resolved_stages[evaluation_stage_id].artifacts[
        PREDICTIONS
    ]
    confirmation_predictions = confirmation_stages[evaluation_stage_id].artifacts[
        PREDICTIONS
    ]
    prediction_parity = selected_predictions == confirmation_predictions

    expected_artifacts = {
        (estimator_ref.stage_id, estimator_ref.artifact_name): (
            estimator_ref,
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            selected_estimator,
            confirmation_estimator,
        ),
        (evaluation_stage_id, PREDICTIONS): (
            StageArtifactRef(
                stage_id=evaluation_stage_id,
                artifact_name=PREDICTIONS,
            ),
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == evaluation_stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == evaluation_stage_id
            ),
            selected_predictions,
            confirmation_predictions,
        ),
    }
    received_artifacts = {
        (receipt.artifact.stage_id, receipt.artifact.artifact_name): receipt
        for receipt in result.artifacts
    }
    if set(received_artifacts) != set(expected_artifacts):
        raise VerificationError(
            "benchmark.artifacts: result must compare parameters and predictions"
        )
    for artifact_key, expected in expected_artifacts.items():
        (
            artifact_ref,
            candidate_stage,
            confirmation_stage,
            candidate,
            confirmed,
        ) = expected
        receipt = received_artifacts[artifact_key]
        expected_candidate_digest = document_digest(candidate)
        expected_confirmation_digest = document_digest(confirmed)
        if (
            receipt.candidate_stage != candidate_stage
            or receipt.confirmation_stage != confirmation_stage
            or receipt.candidate_digest != expected_candidate_digest
            or receipt.confirmation_digest != expected_confirmation_digest
            or receipt.passed
            != (expected_candidate_digest == expected_confirmation_digest)
        ):
            raise VerificationError(
                "benchmark.artifacts: artifact comparison receipt differs"
            )

    def metric_receipts(
        attempt: RunAttempt,
    ) -> dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]]:
        """Load the evaluation metric receipts owned by one attempt."""
        receipts: dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]] = {}
        for reference in attempt.metric_verification_files:
            raw = read_resolved_file(reference, fetcher=fetcher)
            try:
                receipt = MetricVerificationReceipt.model_validate(
                    parse_yaml_bytes(raw)
                )
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    "benchmark.metrics: metric verification receipt is invalid"
                ) from exc
            if receipt.stage_id != evaluation_stage_id:
                continue
            receipts[receipt.metric_id] = (reference, receipt)
        return receipts

    candidate_metric_receipts = metric_receipts(selected_attempt)
    confirmation_metric_receipts = metric_receipts(confirmation)
    criteria = {criterion.metric_id: criterion for criterion in benchmark.metrics}
    received_metrics = {receipt.metric_id: receipt for receipt in result.metrics}
    if set(received_metrics) != set(criteria):
        raise VerificationError(
            "benchmark.metrics: result metric IDs differ from the benchmark"
        )
    criteria_pass = True
    for metric_id, criterion in criteria.items():
        if (
            metric_id not in candidate_metric_receipts
            or metric_id not in confirmation_metric_receipts
        ):
            raise VerificationError(
                f"benchmark.metrics: metric {metric_id!r} lacks verification evidence"
            )
        candidate_ref, candidate_receipt = candidate_metric_receipts[metric_id]
        confirmation_ref, confirmation_receipt = confirmation_metric_receipts[metric_id]
        values = (
            candidate_receipt.recomputation.value,
            confirmation_receipt.recomputation.value,
        )
        criterion_passed = (
            all(value >= criterion.threshold for value in values)
            if criterion.comparison == "ge"
            else all(value <= criterion.threshold for value in values)
        )
        receipt = received_metrics[metric_id]
        if (
            not candidate_receipt.passed
            or not confirmation_receipt.passed
            or receipt.candidate_verification != candidate_ref
            or receipt.confirmation_verification != confirmation_ref
            or receipt.comparison != criterion.comparison
            or receipt.threshold != criterion.threshold
            or receipt.passed != criterion_passed
        ):
            raise VerificationError(
                "benchmark.metrics: metric criterion receipt differs"
            )
        criteria_pass &= criterion_passed

    passed = estimator_parity and prediction_parity and criteria_pass
    expected_status = "passed" if passed else "failed"
    if result.status != expected_status:
        raise VerificationError(
            "benchmark result status does not match parity and metric checks"
        )

    return VerifiedBenchmarkResult(
        result=result,
        run=verified_run,
        confirmation=confirmation,
        confirmation_stages=confirmation_stages,
        confirmation_measurements=confirmation_measurements,
    )
