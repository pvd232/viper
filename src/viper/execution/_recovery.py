"""Close abandoned attempt workspaces with durable failure evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..journal import DurableJournal
from ..runs import AttemptFailure, RunAttempt, RunSpec
from ..serialization import parse_yaml_bytes
from ..storage import LocalArtifactStore
from ._publication import publish_attempt_files, write_attempt_document


def reconcile_abandoned_attempts(
    root: Path,
    workspace_root: Path,
    run: RunSpec,
    run_root: str,
    store: LocalArtifactStore,
    known_attempts: tuple[RunAttempt, ...],
) -> tuple[RunAttempt, ...]:
    """Close every durable workspace omitted from the current run head."""
    recovered = {attempt.attempt_id: attempt for attempt in known_attempts}
    local_run_root = workspace_root.resolve() / str(run.run_id)
    if not local_run_root.is_dir():
        return known_attempts
    for workspace_path in sorted(local_run_root.glob("attempt-*")):
        suffix = workspace_path.name.removeprefix("attempt-")
        if not suffix.isdecimal():
            continue
        attempt_id = int(suffix)
        if attempt_id in recovered:
            continue
        attempt_document = (
            root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
        )
        if attempt_document.is_file():
            recovered[attempt_id] = RunAttempt.model_validate(
                parse_yaml_bytes(attempt_document.read_bytes())
            )
            continue
        journal = DurableJournal(workspace_path / "control" / "journal.jsonl")
        entries = journal.read()
        if not entries:
            continue
        if entries[-1].state != "terminal":
            lost_at = datetime.now(UTC)
            journal.append(
                "terminal",
                "attempt failed after coordinator loss",
                recorded_at=lost_at,
                details={"exception": "coordinator_lost"},
            )
        else:
            lost_at = entries[-1].recorded_at
        journal_reference, measurements, metric_receipts, logs = publish_attempt_files(
            store,
            root,
            run_root,
            attempt_id,
            journal,
            {},
            [],
            [],
        )
        recovered_attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose="run",
            status="failed",
            started_at=entries[0].recorded_at,
            completed_at=datetime.now(UTC),
            resolved_stages=(),
            invocations=(),
            journal=journal_reference,
            measurement_files=measurements,
            metric_verification_files=metric_receipts,
            log_files=logs,
            failure=AttemptFailure(
                code="coordinator_lost",
                stage_id=None,
                message="coordinator exited before terminal attempt publication",
                occurred_at=lost_at,
            ),
        )
        write_attempt_document(root, run_root, recovered_attempt, store)
        recovered[attempt_id] = recovered_attempt
    return tuple(recovered[key] for key in sorted(recovered))
