"""Retrieve bytes and verify immutable file and artifact identities."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import yaml
from huggingface_hub import HfApi, RepoFile, hf_hub_download

from .. import _subprocess as subprocess
from .._schema import ArtifactName, DataRole, RepoRelPath
from ..artifact_loaders import (
    ArtifactLoaderError,
    ArtifactValidationResult,
    execute_artifact_loader,
    materialized_loader_context,
    verify_artifact_loader_bytes,
)
from ..artifacts import (
    ArtifactSpec,
    ResolvedArtifact,
    ResolvedBundleArtifact,
    ResolvedSingleFileArtifact,
)
from ..references import (
    GitFileRef,
    HuggingFaceFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
)
from ..runs import ResolvedAttemptRef, ResolvedRun, RunAttempt, RunSpec
from ..serialization import document_digest, parse_yaml_bytes
from ..verification.models import (
    StageSnapshot,
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedSnapshotFile,
)
from .paths import run_root

_ARTIFACT_VALIDATION_CACHE: dict[
    tuple[str, str, str, tuple[tuple[str, str, int], ...]],
    ArtifactValidationResult,
] = {}


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


def snapshot_identity(
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


def artifact_revision_identity(location: StorageModel) -> tuple[str, ...] | None:
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
