"""Persist ordered run-attempt transitions in an append-only journal."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AttemptState = Literal[
    "allocated",
    "preflighting",
    "running_stage",
    "publishing_stage",
    "closing_attempt",
    "publishing_attempt_files",
    "publishing_terminal_run",
    "terminal",
]

ATTEMPT_STATE_TRANSITIONS: dict[AttemptState, tuple[AttemptState, ...]] = {
    "allocated": ("preflighting", "terminal"),
    "preflighting": ("running_stage", "terminal"),
    "running_stage": ("publishing_stage", "terminal"),
    "publishing_stage": ("running_stage", "closing_attempt", "terminal"),
    "closing_attempt": ("publishing_attempt_files", "terminal"),
    "publishing_attempt_files": ("publishing_terminal_run", "terminal"),
    "publishing_terminal_run": ("terminal",),
    "terminal": (),
}


class JournalEntry(BaseModel):
    """Record one durable attempt transition or external-effect result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    state: AttemptState
    recorded_at: datetime
    event: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class DurableJournal:
    """Append synchronized entries and reconstruct one attempt's latest state."""

    def __init__(self, path: Path) -> None:
        """Bind the journal to one canonical control-file path."""
        self.path = path

    def read(self) -> tuple[JournalEntry, ...]:
        """Load and validate every complete journal entry in order."""
        if not self.path.exists():
            return ()
        return parse_journal_bytes(self.path.read_bytes())

    def append(
        self,
        state: AttemptState,
        event: str,
        *,
        recorded_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Append and synchronize one validated journal entry."""
        entries = self.read()
        if not entries and state != "allocated":
            raise ValueError("the first journal state must be allocated")
        if entries and state not in ATTEMPT_STATE_TRANSITIONS[entries[-1].state]:
            raise ValueError(
                f"invalid attempt transition: {entries[-1].state} -> {state}"
            )
        entry = JournalEntry(
            sequence=len(entries) + 1,
            state=state,
            recorded_at=recorded_at,
            event=event,
            details={} if details is None else details,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(entry.model_dump_json().encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def latest(self) -> JournalEntry | None:
        """Return the latest durable entry for recovery decisions."""
        entries = self.read()
        return entries[-1] if entries else None


def parse_journal_bytes(raw: bytes) -> tuple[JournalEntry, ...]:
    """Parse and validate one immutable attempt journal."""
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("journal is not valid UTF-8") from exc
    entries = tuple(JournalEntry.model_validate_json(line) for line in lines if line)
    if entries:
        expected = tuple(range(1, len(entries) + 1))
        if tuple(entry.sequence for entry in entries) != expected:
            raise ValueError("journal sequence is discontinuous")
        if entries[0].state != "allocated":
            raise ValueError("the first journal state must be allocated")
        for previous, current in zip(entries, entries[1:], strict=False):
            if current.state not in ATTEMPT_STATE_TRANSITIONS[previous.state]:
                raise ValueError(
                    f"invalid journal transition: {previous.state} -> {current.state}"
                )
    return entries


__all__ = [
    "ATTEMPT_STATE_TRANSITIONS",
    "AttemptState",
    "DurableJournal",
    "JournalEntry",
    "parse_journal_bytes",
]
