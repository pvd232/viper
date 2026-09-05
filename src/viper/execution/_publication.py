"""Publish synchronized run heads and immutable attempt evidence."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ..journal import DurableJournal
from ..references import ResolvedFileRef, ResolvedStageInvocationRef
from ..runs import AttemptJournalRef, ResolvedAttemptRef, RunAttempt
from ..serialization import serialize_document
from ..stages import StageInvocationReceipt
from ..storage import StorageDestination, ViperCloudClient, publish_resolved_files
from .errors import RunError


def write_synchronized(path: Path, raw: bytes) -> None:
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


def replace_synchronized(path: Path, raw: bytes) -> None:
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


def publish_attempt_files(
    root: Path,
    destination: StorageDestination,
    run_root: str,
    attempt_id: int,
    journal: DurableJournal,
    log_files: Mapping[str, bytes],
    measurement_paths: list[Path],
    metric_verification_paths: list[Path],
    cloud_client: ViperCloudClient | None = None,
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
    references = publish_resolved_files(
        root,
        destination,
        files,
        cloud_client=cloud_client,
    )
    journal_file = references[journal_path]
    return (
        AttemptJournalRef(
            sha256=journal_file.sha256,
            bytes=journal_file.bytes,
            stored_at=journal_file.stored_at,
        ),
        tuple(
            reference
            for path, reference in references.items()
            if "/measurements/" in path
        ),
        tuple(
            reference
            for path, reference in references.items()
            if "/metric_verification/" in path
        ),
        tuple(reference for path, reference in references.items() if "/logs/" in path),
    )


def write_attempt_document(
    root: Path,
    run_root: str,
    attempt: RunAttempt,
    destination: StorageDestination,
    cloud_client: ViperCloudClient | None = None,
) -> ResolvedAttemptRef:
    """Publish one canonical attempt document and return its immutable reference."""
    path = root / run_root / "attempts" / str(attempt.attempt_id) / "resolved.yaml"
    raw = serialize_document(attempt)
    write_synchronized(path, raw)
    relative_path = path.relative_to(root).as_posix()
    reference = publish_resolved_files(
        root,
        destination,
        {relative_path: raw},
        cloud_client=cloud_client,
    )[relative_path]
    return ResolvedAttemptRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )


def publish_invocation_receipt(
    root: Path,
    destination: StorageDestination,
    path: str,
    receipt: StageInvocationReceipt,
    cloud_client: ViperCloudClient | None = None,
) -> ResolvedStageInvocationRef:
    """Publish one stage invocation receipt at its canonical attempt path."""
    raw = serialize_document(receipt)
    reference = publish_resolved_files(
        root,
        destination,
        {path: raw},
        cloud_client=cloud_client,
    )[path]
    return ResolvedStageInvocationRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )
