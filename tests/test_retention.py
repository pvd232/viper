"""Acceptance tests for cloud-backed local artifact eviction."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.test_storage import InMemoryViperCloudProvider, install_in_memory_cloud
from viper.execution.results import RunResult
from viper.references import (
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
from viper.retention import RunFileEvictionError, evict_cloud_backed_run_files
from viper.runs import AttemptJournalRef, ResolvedAttemptRef, ResolvedRun, RunAttempt
from viper.serialization import serialize_document
from viper.storage import (
    ViperCloudDestination,
    ViperCloudSnapshotPublisher,
    publish_resolved_files,
)


def _cloud_file(
    root: Path,
    client: InMemoryViperCloudProvider,
    path: str,
    raw: bytes,
):
    """Publish one small protocol record and return its resolved reference."""
    return publish_resolved_files(
        root,
        ViperCloudDestination(owner="machina", workspace="retention"),
        {path: raw},
    )[path]


def _successful_result(
    root: Path,
    client: InMemoryViperCloudProvider,
) -> tuple[RunResult, tuple[Path, Path]]:
    """Create one cloud-backed terminal result with a local artifact copy."""
    artifact_path = (
        "experiments/example/runs/selected/01ARZ3NDEKTSV4RRFFQ69G5FAV/"
        "artifacts/embed/encoder/model.bin"
    )
    artifact = root / artifact_path
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"parameters")
    history = artifact.parent.parent / "training_history/history.json"
    history.parent.mkdir(parents=True)
    history.write_bytes(b'{"loss":[1.0]}\n')
    attempt_workspace = (
        root / ".viper/workspaces/01ARZ3NDEKTSV4RRFFQ69G5FAV/attempt-1/inputs/embed"
    )
    attempt_workspace.mkdir(parents=True)
    (attempt_workspace / "prior.bin").write_bytes(b"copied input")
    resolved_path = (
        "experiments/example/runs/selected/01ARZ3NDEKTSV4RRFFQ69G5FAV/"
        "stages/embed/resolved.yaml"
    )
    snapshot = ViperCloudSnapshotPublisher(
        root,
        ViperCloudDestination(owner="machina", workspace="retention"),
    ).publish(
        resolved_stage_path=resolved_path,
        resolved_stage=b"schema_version: 2\n",
        files={artifact_path: artifact, history.relative_to(root).as_posix(): history},
    )
    journal_path = (
        "experiments/example/runs/selected/01ARZ3NDEKTSV4RRFFQ69G5FAV/"
        "attempts/1/journal.jsonl"
    )
    journal_file = _cloud_file(
        root,
        client,
        journal_path,
        b'{"state":"terminal"}\n',
    )
    started = datetime(2026, 9, 15, tzinfo=UTC)
    attempt = RunAttempt(
        attempt_id=1,
        purpose="run",
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=1),
        resolved_stages=(
            ResolvedStageRef(
                stage_id="embed",
                snapshot=snapshot,
                resolved_spec=SnapshotFileRef(
                    path=resolved_path,
                    sha256=hashlib.sha256(b"schema_version: 2\n").hexdigest(),
                    bytes=len(b"schema_version: 2\n"),
                ),
            ),
        ),
        invocations=(),
        journal=AttemptJournalRef(
            sha256=journal_file.sha256,
            bytes=journal_file.bytes,
            stored_at=journal_file.stored_at,
        ),
        measurement_files=(),
        log_files=(),
        failure=None,
    )
    attempt_path = (
        "experiments/example/runs/selected/01ARZ3NDEKTSV4RRFFQ69G5FAV/"
        "attempts/1/resolved.yaml"
    )
    attempt_file = _cloud_file(
        root,
        client,
        attempt_path,
        serialize_document(attempt),
    )
    attempt_ref = ResolvedAttemptRef(
        sha256=attempt_file.sha256,
        bytes=attempt_file.bytes,
        stored_at=attempt_file.stored_at,
    )
    run = ResolvedRun(
        spec=ResolvedRunSpecRef(
            sha256=journal_file.sha256,
            bytes=journal_file.bytes,
            stored_at=journal_file.stored_at,
        ),
        status="succeeded",
        attempts=(attempt_ref,),
        successful_attempt_id=1,
        completed_at=started + timedelta(seconds=2),
    )
    terminal_raw = serialize_document(run)
    terminal_path = (
        root
        / "experiments/example/runs/selected/01ARZ3NDEKTSV4RRFFQ69G5FAV/resolved.yaml"
    )
    terminal_path.parent.mkdir(parents=True, exist_ok=True)
    terminal_path.write_bytes(terminal_raw)
    terminal_file = _cloud_file(
        root,
        client,
        terminal_path.relative_to(root).as_posix(),
        terminal_raw,
    )
    return (
        RunResult(
            record=run,
            reference=ResolvedRunRef(
                sha256=terminal_file.sha256,
                bytes=terminal_file.bytes,
                stored_at=terminal_file.stored_at,
            ),
            path=terminal_path,
            journal_path=root / journal_path,
            latest_attempt=attempt,
        ),
        (artifact, history),
    )


def test_evicts_only_verified_cloud_backed_run_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release artifact bytes while retaining the local terminal record."""
    client = InMemoryViperCloudProvider(tmp_path)
    install_in_memory_cloud(monkeypatch, tmp_path, client)
    result, artifacts = _successful_result(tmp_path, client)

    eviction = evict_cloud_backed_run_files(
        tmp_path,
        result,
    )

    assert all(not artifact.exists() for artifact in artifacts)
    assert result.path.is_file()
    assert not (
        tmp_path / ".viper/workspaces/01ARZ3NDEKTSV4RRFFQ69G5FAV/attempt-1"
    ).exists()
    assert eviction.attempt_workspace_bytes_released == len(b"copied input")
    assert eviction.bytes_released == (
        len(b"parameters") + len(b'{"loss":[1.0]}\n') + len(b"copied input")
    )
    assert tuple(file.path for file in eviction.artifacts) == (
        artifacts[0].relative_to(tmp_path).as_posix(),
        artifacts[1].relative_to(tmp_path).as_posix(),
    )
    repeated = evict_cloud_backed_run_files(
        tmp_path,
        result.reference,
    )
    assert repeated.bytes_released == 0
    assert repeated.attempt_workspace_bytes_released == 0
    assert repeated.artifacts == ()


def test_rejects_changed_local_artifact_before_removing_any_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep every local artifact when one candidate no longer matches its seal."""
    client = InMemoryViperCloudProvider(tmp_path)
    install_in_memory_cloud(monkeypatch, tmp_path, client)
    result, artifacts = _successful_result(tmp_path, client)
    artifacts[1].write_bytes(b"substitute")

    with pytest.raises(RunFileEvictionError, match="local artifact identity changed"):
        evict_cloud_backed_run_files(
            tmp_path,
            result,
        )

    assert artifacts[0].read_bytes() == b"parameters"
    assert artifacts[1].read_bytes() == b"substitute"
    assert (
        tmp_path / ".viper/workspaces/01ARZ3NDEKTSV4RRFFQ69G5FAV/attempt-1"
    ).is_dir()
