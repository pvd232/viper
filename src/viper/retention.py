"""Release local run artifacts only after verifying their cloud copies."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from ._schema import ProtocolModel, RepoRelPath
from .execution.results import RunResult
from .references import (
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from .repository import PathError, resolve_path
from .runs import ResolvedRun, RunAttempt
from .serialization import parse_yaml_bytes
from .storage import StorageConfigurationError, ViperCloudClient


class ArtifactEvictionError(RuntimeError):
    """Report evidence that prevents safe removal of local run artifacts."""


class RunArtifactEviction(ProtocolModel):
    """Record the exact local artifacts released after cloud verification."""

    artifacts: tuple[SnapshotFileRef, ...] = Field(
        description="Cloud-verified artifact files removed from the local workspace."
    )
    bytes_released: int = Field(
        ge=0,
        description="Total bytes removed from the local workspace.",
    )


def _read_cloud_record(
    reference: ResolvedFileRef,
    cloud_client: ViperCloudClient,
) -> bytes:
    """Read one small cloud record and verify its retained byte identity."""
    location = reference.stored_at
    if not isinstance(location, ViperCloudFileRef):
        raise ArtifactEvictionError("run record is not durably stored in Viper Cloud")
    raw = cloud_client.fetch(
        owner=location.owner,
        workspace=location.workspace,
        revision=location.revision,
        path=location.path,
    )
    if (
        len(raw) != reference.bytes
        or hashlib.sha256(raw).hexdigest() != reference.sha256
    ):
        raise ArtifactEvictionError("cloud record identity changed")
    return raw


def _artifact_path(path: RepoRelPath) -> bool:
    """Recognize the canonical path of a stage-produced artifact file."""
    parts = path.split("/")
    return len(parts) >= 9 and parts[0] == "experiments" and parts[5] == "artifacts"


def evict_cloud_backed_run_artifacts(
    repository_root: Path,
    run: RunResult | ResolvedRunRef,
    *,
    cloud_client: ViperCloudClient,
) -> RunArtifactEviction:
    """Remove one successful run's local artifacts after cloud-byte verification.

    Keep the local terminal record, attempt record, journal, logs, measurements,
    resolved stage documents, and inputs. Verify every existing artifact locally
    and in its sealed cloud revision before deleting any file. Repeated calls are
    safe: artifacts already absent from the local workspace are ignored.
    """
    root = repository_root.resolve(strict=True)
    reference = run.reference if isinstance(run, RunResult) else run
    location = reference.stored_at
    if not isinstance(location, ViperCloudFileRef):
        raise ArtifactEvictionError("terminal run is not stored in Viper Cloud")

    try:
        terminal = resolve_path(
            root,
            location.path,
            operation="read",
        ).read_bytes()
    except (OSError, PathError) as error:
        raise ArtifactEvictionError(
            "local terminal record is missing or unsafe"
        ) from error
    if (
        len(terminal) != reference.bytes
        or hashlib.sha256(terminal).hexdigest() != reference.sha256
        or _read_cloud_record(reference, cloud_client) != terminal
    ):
        raise ArtifactEvictionError("terminal record identity changed")
    record = ResolvedRun.model_validate(parse_yaml_bytes(terminal))
    if isinstance(run, RunResult) and run.record != record:
        raise ArtifactEvictionError("RunResult differs from its terminal record")
    if record.status != "succeeded" or record.successful_attempt_id is None:
        raise ArtifactEvictionError("only a successful terminal run may be evicted")

    selected_attempt: RunAttempt | None = None
    for attempt_reference in record.attempts:
        raw = _read_cloud_record(attempt_reference, cloud_client)
        attempt = RunAttempt.model_validate(parse_yaml_bytes(raw))
        if attempt.attempt_id == record.successful_attempt_id:
            selected_attempt = attempt
            break
    if (
        selected_attempt is None
        or selected_attempt.status != "succeeded"
        or selected_attempt.purpose != "run"
    ):
        raise ArtifactEvictionError("successful attempt record is missing")

    candidates: dict[
        RepoRelPath, tuple[SnapshotFileRef, ViperCloudStageResultSnapshotRef]
    ] = {}
    for stage in selected_attempt.resolved_stages:
        snapshot = stage.snapshot
        if not isinstance(snapshot, ViperCloudStageResultSnapshotRef):
            raise ArtifactEvictionError(
                "successful attempt contains a local-only stage"
            )
        for file in cloud_client.list_files(
            owner=snapshot.owner,
            workspace=snapshot.workspace,
            revision=snapshot.revision,
        ):
            if not _artifact_path(file.path):
                continue
            previous = candidates.setdefault(file.path, (file, snapshot))
            if previous[0] != file:
                raise ArtifactEvictionError(
                    "artifact path has conflicting cloud identities"
                )

    verified: list[SnapshotFileRef] = []
    for file, snapshot in candidates.values():
        try:
            local = resolve_path(root, file.path, operation="write")
        except (OSError, PathError) as error:
            raise ArtifactEvictionError("local artifact path is unsafe") from error
        if not local.exists():
            continue
        if not local.is_file():
            raise ArtifactEvictionError("local artifact is not a regular file")
        with local.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if local.stat().st_size != file.bytes or digest != file.sha256:
            raise ArtifactEvictionError("local artifact identity changed")
        try:
            cloud_client.verify_file(
                owner=snapshot.owner,
                workspace=snapshot.workspace,
                revision=snapshot.revision,
                path=file.path,
                sha256=file.sha256,
                bytes=file.bytes,
            )
        except StorageConfigurationError as error:
            raise ArtifactEvictionError("cloud artifact identity changed") from error
        verified.append(file)

    for file in verified:
        (root / file.path).unlink()
    return RunArtifactEviction(
        artifacts=tuple(sorted(verified, key=lambda item: item.path)),
        bytes_released=sum(file.bytes for file in verified),
    )


__all__ = [
    "ArtifactEvictionError",
    "RunArtifactEviction",
    "evict_cloud_backed_run_artifacts",
]
