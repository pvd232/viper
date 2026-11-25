"""Publish synchronized run heads and immutable attempt evidence."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..journal import DurableJournal
from ..references import (
    GcsFileRef,
    HuggingFaceFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageInvocationRef,
)
from ..runs import AttemptJournalRef, ResolvedAttemptRef, RunAttempt
from ..serialization import (
    replace_synchronized,
    serialize_document,
    write_synchronized,
)
from ..stages import StageInvocationReceipt
from ..storage import StorageDestination, publish_resolved_files
from .errors import RunError


def persist_terminal_reference(
    path: Path,
    reference: ResolvedRunRef,
    *,
    replace_existing: bool = False,
) -> Path | None:
    """Save one cloud terminal pointer beside its local terminal document."""
    if not isinstance(reference.stored_at, (GcsFileRef, HuggingFaceFileRef)):
        return None
    sidecar = path.with_name("resolved.ref.yaml")
    raw = serialize_document(reference)
    if sidecar.exists() and sidecar.read_bytes() != raw:
        if not replace_existing:
            raise RunError("terminal cloud reference differs")
        replace_synchronized(sidecar, raw)
        return sidecar
    write_synchronized(sidecar, raw)
    return sidecar


def publish_attempt_files(
    root: Path,
    destination: StorageDestination,
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
    references = publish_resolved_files(
        root,
        destination,
        files,
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
    *,
    replace_existing: bool = False,
) -> ResolvedAttemptRef:
    """Publish one attempt document and return its immutable reference."""
    path = root / run_root / "attempts" / str(attempt.attempt_id) / "resolved.yaml"
    raw = serialize_document(attempt)
    writer = replace_synchronized if replace_existing else write_synchronized
    writer(path, raw)
    relative_path = path.relative_to(root).as_posix()
    reference = publish_resolved_files(
        root,
        destination,
        {relative_path: raw},
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
) -> ResolvedStageInvocationRef:
    """Publish one stage invocation receipt at its canonical attempt path."""
    raw = serialize_document(receipt)
    reference = publish_resolved_files(
        root,
        destination,
        {path: raw},
    )[path]
    return ResolvedStageInvocationRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )
