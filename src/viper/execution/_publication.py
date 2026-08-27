"""Publish synchronized run heads and immutable attempt evidence."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ..journal import DurableJournal
from ..references import ResolvedFileRef
from ..runs import AttemptJournalRef, ResolvedAttemptRef, RunAttempt
from ..serialization import serialize_document
from ..stages import (
    ResolvedStageInvocationRef,
    StageInvocationReceipt,
)
from ..storage import LocalArtifactStore
from ._errors import RunError


def _write_synchronized(path: Path, raw: bytes) -> None:
    """Atomically write and synchronize one local control or terminal file."""
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise RunError(f"refusing to replace different bytes at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(raw)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()


def _replace_synchronized(path: Path, raw: bytes) -> None:
    """Atomically replace one mutable local head document and synchronize it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(raw)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _publish_attempt_files(
    store: LocalArtifactStore,
    root: Path,
    run_root: str,
    attempt_id: int,
    journal: DurableJournal,
    log_files: Mapping[str, bytes],
    measurement_paths: list[Path],
    metric_verification_paths: list[Path],
) -> tuple[
    AttemptJournalRef,
    tuple[ResolvedFileRef, ...],
    tuple[ResolvedFileRef, ...],
    tuple[ResolvedFileRef, ...],
]:
    """Publish one terminal journal and every available attempt-owned file."""
    files = dict(log_files)
    for path in (*measurement_paths, *metric_verification_paths):
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    journal_path = f"{run_root}/attempts/{attempt_id}/journal.jsonl"
    files[journal_path] = journal.path.read_bytes()
    references = store.resolved_files(files)
    journal_file = next(
        reference
        for reference in references
        if reference.stored_at.path == journal_path
    )
    return (
        AttemptJournalRef(
            sha256=journal_file.sha256,
            bytes=journal_file.bytes,
            stored_at=journal_file.stored_at,
        ),
        tuple(
            reference
            for reference in references
            if "/measurements/" in str(reference.stored_at.path)
        ),
        tuple(
            reference
            for reference in references
            if "/metric_verification/" in str(reference.stored_at.path)
        ),
        tuple(
            reference
            for reference in references
            if "/logs/" in str(reference.stored_at.path)
        ),
    )


def _write_attempt_document(
    root: Path,
    run_root: str,
    attempt: RunAttempt,
    store: LocalArtifactStore,
) -> ResolvedAttemptRef:
    """Publish one canonical attempt document and return its immutable reference."""
    path = root / run_root / "attempts" / str(attempt.attempt_id) / "resolved.yaml"
    raw = serialize_document(attempt)
    _write_synchronized(path, raw)
    reference = store.resolved_files({path.relative_to(root).as_posix(): raw})[0]
    return ResolvedAttemptRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )


def _publish_invocation_receipt(
    store: LocalArtifactStore,
    path: str,
    receipt: StageInvocationReceipt,
) -> ResolvedStageInvocationRef:
    """Publish one stage invocation receipt at its canonical attempt path."""
    raw = serialize_document(receipt)
    reference = store.resolved_files({path: raw})[0]
    return ResolvedStageInvocationRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )
