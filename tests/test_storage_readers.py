"""Exercise native reader lifetimes and process-exit cleanup protection."""

from __future__ import annotations

import multiprocessing
import os
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest

from viper._storage_locks import PayloadLocks, WorkflowReaders
from viper.references import FileIdentity


def _identity() -> FileIdentity:
    """Return one valid content identity used only to name a lock."""
    return FileIdentity(sha256="1" * 64, bytes=8)


def _reader_process(root: str, ready: Event, finish: Event) -> None:
    """Exit abruptly while holding a reader so the OS must release it."""
    with PayloadLocks(Path(root)).reader(_identity()):
        ready.set()
        if not finish.wait(10):
            os._exit(2)
        os._exit(0)


def test_reader_defers_cleanup_until_workflow_completion(tmp_path: Path) -> None:
    """A later admitted consumer keeps its payload resident between stage calls."""
    locks = PayloadLocks(tmp_path)
    with WorkflowReaders(locks) as readers:
        readers.hold(_identity())
        with locks.exclusive(_identity()) as acquired:
            assert not acquired
        readers.hold(_identity())
        with locks.exclusive(_identity()) as acquired:
            assert not acquired
    with locks.exclusive(_identity()) as acquired:
        assert acquired


def test_overlapping_workflows_keep_independent_reader_holds(tmp_path: Path) -> None:
    """One completed workflow cannot release another workflow's reader."""
    locks = PayloadLocks(tmp_path)
    first = WorkflowReaders(locks)
    second = WorkflowReaders(locks)
    try:
        first.hold(_identity())
        second.hold(_identity())
        first.close()
        with locks.exclusive(_identity()) as acquired:
            assert not acquired
    finally:
        first.close()
        second.close()
    with locks.exclusive(_identity()) as acquired:
        assert acquired


def test_exception_releases_reader_without_authorizing_deletion(tmp_path: Path) -> None:
    """Reader lifetime ends on failure; publication and retention gates still apply."""
    locks = PayloadLocks(tmp_path)
    with pytest.raises(RuntimeError, match="experiment failed"):
        with WorkflowReaders(locks) as readers:
            readers.hold(_identity())
            raise RuntimeError("experiment failed")
    with locks.exclusive(_identity()) as acquired:
        assert acquired


def test_process_exit_releases_reader_without_a_registry_counter(
    tmp_path: Path,
) -> None:
    """An interrupted worker leaves no permanent reader subscription or count."""
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    finish = context.Event()
    process = context.Process(
        target=_reader_process,
        args=(str(tmp_path), ready, finish),
    )
    process.start()
    locks = PayloadLocks(tmp_path)
    try:
        assert ready.wait(10)
        with locks.exclusive(_identity()) as acquired:
            assert not acquired
        finish.set()
        process.join(10)
        assert process.exitcode == 0
        with locks.exclusive(_identity()) as acquired:
            assert acquired
    finally:
        finish.set()
        if process.is_alive():
            process.kill()
        process.join(10)


def test_closed_workflow_rejects_new_readers(tmp_path: Path) -> None:
    """A completed scope cannot silently acquire untracked new readers."""
    readers = WorkflowReaders(PayloadLocks(tmp_path))
    readers.close()
    with pytest.raises(RuntimeError, match="already closed"):
        readers.hold(_identity())
