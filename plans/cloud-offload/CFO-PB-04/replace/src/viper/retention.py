"""Set artifact retention preferences and remove verified cloud-backed local files."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, ValidationError

from ._cloud import ViperCloudError
from ._schema import ProtocolModel, RepoRelPath
from .artifacts import StageArtifactRef
from .cloud import ViperCloud
from .execution.results import RunResult
from .ids import RunId
from .references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
)
from .repository import PathError, resolve_path
from .runs import ResolvedRun, RunAttempt
from .serialization import parse_yaml_bytes
from .storage import LocalArtifactStore
from .workspace import RunWorkspaceLock, WorkspaceError


class RunFileEvictionError(RuntimeError):
    """Report a check that prevents deleting local run files."""


class RunFileEviction(ProtocolModel):
    """Record which files were removed and how much local space was freed."""

    artifacts: tuple[SnapshotFileRef, ...] = Field(
        description="Cloud-verified artifact files removed from the local workspace."
    )
    bytes_released: int = Field(
        ge=0,
        description="Total artifact and attempt-workspace bytes removed locally.",
    )
    attempt_workspace_bytes_released: int = Field(
        ge=0,
        description="Transient selected-attempt bytes removed from .viper/workspaces.",
    )


def _read_cloud_record(
    root: Path,
    reference: ResolvedFileRef,
) -> bytes:
    """Read a cloud record and check its byte count and SHA-256."""
    location = reference.stored_at
    if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
        raise RunFileEvictionError("run record is not durably stored in Viper Cloud")
    raw = ViperCloud.for_reference(root, location).fetch(location)
    if (
        len(raw) != reference.bytes
        or hashlib.sha256(raw).hexdigest() != reference.sha256
    ):
        raise RunFileEvictionError("cloud record identity changed")
    return raw


def _artifact_path(path: RepoRelPath) -> bool:
    """Recognize the standard path of a file produced by a stage."""
    parts = path.split("/")
    return len(parts) >= 9 and parts[0] == "experiments" and parts[5] == "artifacts"


def _run_id_from_terminal_path(path: RepoRelPath) -> RunId:
    """Read the run ID from its final record path."""
    parts = path.split("/")
    if (
        len(parts) != 6
        or parts[0] != "experiments"
        or parts[2] != "runs"
        or parts[5] != "resolved.yaml"
    ):
        raise RunFileEvictionError("terminal run path is not canonical")
    try:
        return TypeAdapter(RunId).validate_python(parts[4])
    except ValidationError as error:
        raise RunFileEvictionError("terminal run path has an invalid run ID") from error


def _directory_bytes(path: Path) -> int:
    """Count file bytes under the directory."""
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def evict_cloud_backed_run_files(
    repository_root: Path,
    run: RunResult | ResolvedRunRef,
) -> RunFileEviction:
    """Remove local output files after checking their cloud copies.

    Keep inputs and run evidence, including stage records and measurements.
    Also remove the selected attempt workspace. Check every existing output
    locally and in its fixed cloud revision before deleting anything. Files
    already absent are ignored.
    """
    root = repository_root.resolve(strict=True)
    reference = run.reference if isinstance(run, RunResult) else run
    location = reference.stored_at
    if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
        raise RunFileEvictionError("terminal run is not stored in Viper Cloud")

    try:
        terminal = resolve_path(
            root,
            location.path,
            operation="read",
        ).read_bytes()
    except (OSError, PathError) as error:
        raise RunFileEvictionError(
            "local terminal record is missing or unsafe"
        ) from error
    if (
        len(terminal) != reference.bytes
        or hashlib.sha256(terminal).hexdigest() != reference.sha256
        or _read_cloud_record(root, reference) != terminal
    ):
        raise RunFileEvictionError("terminal record identity changed")
    record = ResolvedRun.model_validate(parse_yaml_bytes(terminal))
    if isinstance(run, RunResult) and run.record != record:
        raise RunFileEvictionError("RunResult differs from its terminal record")
    if record.status != "succeeded" or record.successful_attempt_id is None:
        raise RunFileEvictionError("only a successful terminal run may be evicted")

    selected_attempt: RunAttempt | None = None
    for attempt_reference in record.attempts:
        raw = _read_cloud_record(root, attempt_reference)
        attempt = RunAttempt.model_validate(parse_yaml_bytes(raw))
        if attempt.attempt_id == record.successful_attempt_id:
            selected_attempt = attempt
            break
    if (
        selected_attempt is None
        or selected_attempt.status != "succeeded"
        or selected_attempt.purpose != "run"
    ):
        raise RunFileEvictionError("successful attempt record is missing")

    candidates: dict[
        RepoRelPath, tuple[SnapshotFileRef, CloudStageResultSnapshotRef]
    ] = {}
    for stage in selected_attempt.resolved_stages:
        snapshot = stage.snapshot
        if not isinstance(
            snapshot,
            (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef),
        ):
            raise RunFileEvictionError("successful attempt contains a local-only stage")
        cloud = ViperCloud.for_snapshot(root, snapshot)
        for file in cloud.list_files(snapshot):
            if not _artifact_path(file.path):
                continue
            previous = candidates.setdefault(file.path, (file, snapshot))
            if previous[0] != file:
                raise RunFileEvictionError(
                    "artifact path has conflicting cloud identities"
                )

    verified: list[SnapshotFileRef] = []
    for file, snapshot in candidates.values():
        try:
            local = resolve_path(root, file.path, operation="write")
        except (OSError, PathError) as error:
            raise RunFileEvictionError("local artifact path is unsafe") from error
        if not local.exists():
            continue
        if not local.is_file():
            raise RunFileEvictionError("local artifact is not a regular file")
        with local.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if local.stat().st_size != file.bytes or digest != file.sha256:
            raise RunFileEvictionError("local artifact identity changed")
        try:
            reference = ResolvedFileRef(
                sha256=file.sha256,
                bytes=file.bytes,
                stored_at=ViperCloud.for_snapshot(root, snapshot).file_ref(
                    snapshot, file.path
                ),
            )
            cloud_location = reference.stored_at
            assert isinstance(cloud_location, (GcsFileRef, HuggingFaceFileRef))
            ViperCloud.for_reference(root, cloud_location).verify_file(reference)
        except ViperCloudError as error:
            raise RunFileEvictionError("cloud artifact identity changed") from error
        verified.append(file)

    run_id = _run_id_from_terminal_path(location.path)
    attempt_workspace = (
        root
        / ".viper"
        / "workspaces"
        / run_id
        / f"attempt-{selected_attempt.attempt_id}"
    )
    attempt_workspace_bytes = (
        _directory_bytes(attempt_workspace) if attempt_workspace.is_dir() else 0
    )
    run_lock = RunWorkspaceLock.for_run(root / ".viper/workspaces", run_id)
    try:
        run_lock.acquire()
    except WorkspaceError as error:
        raise RunFileEvictionError("run workspace still has an active owner") from error
    try:
        for file in verified:
            (root / file.path).unlink()
        if attempt_workspace.is_dir():
            shutil.rmtree(attempt_workspace)
    finally:
        run_lock.release()
    return RunFileEviction(
        artifacts=tuple(sorted(verified, key=lambda item: item.path)),
        bytes_released=sum(file.bytes for file in verified) + attempt_workspace_bytes,
        attempt_workspace_bytes_released=attempt_workspace_bytes,
    )


def set_artifact_retention(
    repository_root: Path,
    source: StageResultSnapshotRef,
    selection: StageArtifactRef | RepoRelPath,
    preference: Literal["inherit", "keep", "offload"],
    *,
    store: RepoRelPath = ".viper/store",
) -> None:
    """Save an artifact preference and finish any requested keep operation.

    Select a registered producer artifact or captured input file. Use the
    current workspace registry even if the original workspace is gone.
    Keep is saved before downloading every missing artifact file. A failed
    download leaves keep saved and raises the error. Inherit and offload
    change the preference without downloading or deleting files.
    """
    storage = LocalArtifactStore(repository_root, store)
    storage.registry.set_retention(source, selection, preference)
    if preference == "keep":
        for reference in storage.registry.artifact_files(source, selection):
            storage.resolve(reference)


__all__ = [
    "set_artifact_retention",
    "RunFileEvictionError",
    "RunFileEviction",
    "evict_cloud_backed_run_files",
]
