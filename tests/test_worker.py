"""Tests for bounded attempt workspaces, journals, and local workers."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from viper.journal import DurableJournal, JournalEntry
from viper.worker import (
    ExecutionPolicy,
    WorkerError,
    WorkerRequest,
    execute_worker,
)
from viper.workspace import (
    AttemptWorkspace,
    RunWorkspaceLock,
    WorkspaceError,
    next_attempt_id,
)


def test_workspace_enforces_exclusive_run_ownership(tmp_path: Path) -> None:
    """Reject a second owner while one run-workspace lock is active."""
    workspace = AttemptWorkspace.create(tmp_path, "01JABCDEFGHJKMNPQRSTVWXYZ", 1)
    workspace.acquire()

    with pytest.raises(WorkspaceError, match="active owner"):
        workspace.acquire()

    workspace.release()
    workspace.acquire()
    workspace.release()


def test_workspace_rejects_path_escape(tmp_path: Path) -> None:
    """Keep resolved attempt paths beneath the attempt root."""
    workspace = AttemptWorkspace.create(tmp_path, "01JABCDEFGHJKMNPQRSTVWXYZ", 1)

    with pytest.raises(WorkspaceError, match="escapes"):
        workspace.resolve("../../outside")


def test_attempt_allocator_uses_durable_workspace_history(tmp_path: Path) -> None:
    """Allocate one greater than every persisted attempt workspace ID."""
    run_id = "01JABCDEFGHJKMNPQRSTVWXYZ"
    AttemptWorkspace.create(tmp_path, run_id, 1)
    AttemptWorkspace.create(tmp_path, run_id, 3)

    assert next_attempt_id(tmp_path, run_id) == 4


def test_run_lock_coordinates_distinct_workspace_objects(tmp_path: Path) -> None:
    """Reject a second coordinator until the operating system releases ownership."""
    run_id = "01JABCDEFGHJKMNPQRSTVWXYZ"
    first = RunWorkspaceLock.for_run(tmp_path, run_id)
    second = RunWorkspaceLock.for_run(tmp_path, run_id)
    first.acquire()

    with pytest.raises(WorkspaceError, match="active owner"):
        second.acquire()

    first.release()
    second.acquire()
    second.release()


def test_journal_persists_ordered_attempt_transitions(tmp_path: Path) -> None:
    """Recover the latest attempt state from synchronized JSON Lines entries."""
    journal = DurableJournal(tmp_path / "control" / "journal.jsonl")
    now = datetime.now(UTC)

    journal.append("allocated", "attempt allocated", recorded_at=now)
    journal.append("preflighting", "preflight started", recorded_at=now)

    assert [entry.sequence for entry in journal.read()] == [1, 2]
    assert journal.latest().state == "preflighting"  # type: ignore[union-attr]


def test_journal_rejects_invalid_attempt_transition(tmp_path: Path) -> None:
    """Reject a durable state change outside the coordinator state machine."""
    journal = DurableJournal(tmp_path / "control" / "journal.jsonl")
    now = datetime.now(UTC)
    journal.append("allocated", "attempt allocated", recorded_at=now)

    with pytest.raises(ValueError, match="allocated -> publishing_stage"):
        journal.append("publishing_stage", "invalid publication", recorded_at=now)


def test_journal_rejects_invalid_persisted_history(tmp_path: Path) -> None:
    """Reject a journal whose stored entries violate the state machine."""
    path = tmp_path / "control" / "journal.jsonl"
    path.parent.mkdir(parents=True)
    now = datetime.now(UTC)
    entries = (
        JournalEntry(
            sequence=1,
            state="allocated",
            recorded_at=now,
            event="attempt allocated",
        ),
        JournalEntry(
            sequence=2,
            state="closing_attempt",
            recorded_at=now,
            event="invalid close",
        ),
    )
    path.write_text(
        "".join(f"{entry.model_dump_json()}\n" for entry in entries),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allocated -> closing_attempt"):
        DurableJournal(path).read()


def test_trusted_local_worker_receives_context_path(tmp_path: Path) -> None:
    """Supply the versioned context path through the worker environment."""
    context = tmp_path / "control" / "context.json"
    context.parent.mkdir()
    context.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    request = WorkerRequest(
        workspace_root=tmp_path,
        working_directory=tmp_path,
        context_path=context,
        command=(
            sys.executable,
            "-c",
            "import os; print(os.environ['VIPER_CONTEXT_PATH'])",
        ),
    )

    result = execute_worker(request)

    assert result.stdout.decode().strip() == str(context)


def test_trusted_local_worker_enforces_timeout(tmp_path: Path) -> None:
    """Terminate a local worker after its declared process duration."""
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    request = WorkerRequest(
        workspace_root=tmp_path,
        working_directory=tmp_path,
        context_path=context,
        command=(sys.executable, "-c", "import time; time.sleep(1)"),
        policy=ExecutionPolicy(timeout_seconds=0.01),
    )

    with pytest.raises(WorkerError, match="timeout"):
        execute_worker(request)
