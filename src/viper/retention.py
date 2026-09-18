"""Release local run artifacts only after verifying their cloud copies."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from pydantic import Field, TypeAdapter, ValidationError

from ._cloud import ViperCloudError
from ._schema import ProtocolModel, RepoRelPath
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
)
from .repository import PathError, resolve_path
from .runs import ResolvedRun, RunAttempt
from .serialization import parse_yaml_bytes
from .workspace import RunWorkspaceLock, WorkspaceError


class RunFileEvictionError(RuntimeError):
    """Report evidence that prevents safe removal of local run artifacts."""


class RunFileEviction(ProtocolModel):
    """Record local run bytes released after cloud verification."""

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
    """Read one small cloud record and verify its retained byte identity."""
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
    """Recognize the canonical path of a stage-produced artifact file."""
    parts = path.split("/")
    return len(parts) >= 9 and parts[0] == "experiments" and parts[5] == "artifacts"


def _run_id_from_terminal_path(path: RepoRelPath) -> RunId:
    """Read the run ID from one canonical terminal-record path."""
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
    """Count regular-file bytes beneath one local directory."""
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def evict_cloud_backed_run_files(
    repository_root: Path,
    run: RunResult | ResolvedRunRef,
) -> RunFileEviction:
    """Remove one successful run's local artifacts after cloud-byte verification.

    Keep canonical inputs, the local terminal record, attempt record, journal,
    logs, measurements, and resolved stage documents. Remove the selected
    attempt's transient materializations. Verify every existing artifact locally
    and in its sealed cloud revision before deleting any file. Repeated calls are
    safe: files already absent from the local workspace are ignored.
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


__all__ = [
    "RunFileEvictionError",
    "RunFileEviction",
    "evict_cloud_backed_run_files",
]
