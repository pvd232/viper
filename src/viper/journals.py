"""Parse scientific journals and publish exact-source learned search vectors."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import viper._subprocess as subprocess

from ._schema import NonEmptyStr, ProtocolModel
from ._source import RunFetcher
from .catalog import Catalog
from .evidence import VerificationPolicy, VerifiedRunResult
from .knowledge import (
    JournalAssertion,
    JournalEncoderSpec,
    JournalEncoding,
    JournalEvidence,
    JournalSource,
    JournalVectorView,
    KnowledgeVector,
    knowledge,
)
from .references import ResolvedFileRef, ResolvedRunRef
from .repository import read_source, resolve_path, resolve_root
from .runs import ResolvedRun
from .serialization import document_digest, parse_yaml_bytes
from .storage import LocalArtifactStore, LocalStorageDestination, publish_resolved_files
from .verification import verify_run_result

_LOGGER = logging.getLogger(__name__)
_HEADING = re.compile(rb" {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*(?:\r?\n)?$")
_FIELD = re.compile(r"^([A-Za-z][A-Za-z _-]*):[ \t]*(.*)$")
_FENCE = re.compile(rb" {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?$")
_KINDS = {
    "hypothesis": "hypothesis",
    "hypotheses": "hypothesis",
    "question and hypothesis": "hypothesis",
    "observation": "observation",
    "observations": "observation",
    "decision": "decision",
    "decisions": "decision",
    "interpretation and decision": "decision",
}


class JournalSettings(ProtocolModel):
    """Configure default-on local publication from an experiment's JOURNAL.md."""

    enabled: bool = Field(
        default=True, description="Publish journals after saved runs."
    )
    authored_by: NonEmptyStr = Field(
        default="workspace journal",
        description="Attribution without an Author field; not a reviewer identity.",
    )
    timeout_seconds: float = Field(
        default=120,
        gt=0,
        description="Encoder subprocess limit, including the first model download.",
    )


class JournalPassage(ProtocolModel):
    """Preserve a paragraph's exact bytes and author-labeled scientific fields."""

    text: NonEmptyStr = Field(
        description="Exact UTF-8 passage, preserving whitespace and line endings."
    )
    byte_start: int = Field(ge=0, description="Inclusive source byte offset.")
    byte_end: int = Field(gt=0, description="Exclusive source byte offset.")
    section: NonEmptyStr = Field(
        description="Nearest Markdown heading outside code fences."
    )
    kind: Literal["observation", "hypothesis", "decision", "note"] = Field(
        description="Author-declared claim category; other sections remain notes."
    )
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Author-written hypothesis, controls, and other scientific labels.",
    )


class JournalPublicationResult(BaseModel):
    """Return retained text and all immutable assertion and vector references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ResolvedFileRef | None = Field(
        default=None, description="Immutable original Markdown revision, when present."
    )
    assertions: tuple[ResolvedFileRef, ...] = Field(
        default=(),
        description="Published exact-source assertions, all initially proposed.",
    )
    vectors: tuple[ResolvedFileRef, ...] = Field(
        default=(),
        description="Vectors produced for the corresponding assertions in order.",
    )
    skipped: bool = Field(
        default=False,
        description="Publication was disabled or no journal file was present.",
    )


class JournalEncodingResult(ProtocolModel):
    """Return one pinned encoder and its exact-source invocation results."""

    encoder: JournalEncoderSpec = Field(
        description="Pinned model, preprocessing, file hashes, and library versions."
    )
    values: tuple[tuple[float, ...], ...] = Field(
        description="Normalized vectors in the exact input passage order."
    )
    encodings: tuple[JournalEncoding, ...] = Field(
        description="Input digests and token counts in the same passage order."
    )


def load_journal_settings(root: Path) -> JournalSettings:
    """Read the optional [journals] table without changing workspace settings."""
    marker = tomllib.loads((root / "viper.toml").read_text(encoding="utf-8"))
    return JournalSettings.model_validate(marker.get("journals", {}))


def _fence_state(
    line: bytes, current: tuple[bytes, int] | None
) -> tuple[bytes, int] | None:
    """Close fences only with the same marker and at least the opening length."""
    matched = _FENCE.fullmatch(line)
    if matched is None:
        return current
    marker, tail = matched.groups()
    if current is None:
        if marker[:1] == b"`" and b"`" in tail:
            return None
        return marker[:1], len(marker)
    if marker[:1] == current[0] and len(marker) >= current[1] and not tail.strip():
        return None
    return current


def parse_journal(raw: bytes) -> tuple[JournalPassage, ...]:
    """Split UTF-8 Markdown into exact paragraphs, ignoring headings inside fences.

    Headings select author-declared claim kinds. Other sections and unlabeled
    prose remain notes. Label:value lines expose structured author statements;
    parsing never reviews claims or infers scientific conclusions.
    """
    raw.decode("utf-8")
    passages: list[JournalPassage] = []
    section = "Notes"
    start: int | None = None
    offset = 0
    fence: tuple[bytes, int] | None = None

    def flush(end: int) -> None:
        """Retain one complete span without stripping or normalizing its text."""
        nonlocal start
        if start is None:
            return
        text = raw[start:end].decode("utf-8")
        fields: dict[str, str] = {}
        field_fence: tuple[bytes, int] | None = None
        for line in text.splitlines():
            previous_fence = field_fence
            field_fence = _fence_state(line.encode("utf-8"), field_fence)
            if previous_fence is not None or field_fence is not None:
                continue
            matched = _FIELD.fullmatch(line)
            if matched is not None:
                key = matched[1].lower().replace(" ", "_").replace("-", "_")
                if key in fields:
                    raise ValueError(f"duplicate journal field: {key}")
                fields[key] = matched[2]
        kind = _KINDS.get(section.casefold(), "note")
        if "hypothesis" in fields and kind == "note":
            kind = "hypothesis"
        passages.append(
            JournalPassage.model_validate(
                {
                    "text": text,
                    "byte_start": start,
                    "byte_end": end,
                    "section": section,
                    "kind": kind,
                    "fields": fields,
                }
            )
        )
        start = None

    for line in raw.splitlines(keepends=True):
        fence = _fence_state(line, fence)
        heading = _HEADING.fullmatch(line) if fence is None else None
        if heading is not None:
            flush(offset)
            section = heading[1].decode("utf-8")
        elif not line.strip() and fence is None:
            flush(offset)
        elif start is None:
            start = offset
        offset += len(line)
    flush(len(raw))
    return tuple(passages)


def encode_journal(
    texts: tuple[str, ...], *, timeout_seconds: float = 120
) -> JournalEncodingResult:
    """Encode exact passages in an isolated CPU worker with pinned Qwen weights.

    No query prompt, whitespace rewrite, or truncation is applied. The worker
    rejects overlong input, records loaded file hashes and numerical settings,
    and leaves the experiment process's RNG and thread settings unchanged.
    """
    completed = subprocess.run(
        (sys.executable, "-m", "viper._journal_encoder"),
        input=json.dumps({"texts": texts}),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode:
        raise RuntimeError(f"journal encoder failed: {completed.stderr[-4000:]}")
    result = JournalEncodingResult.model_validate_json(completed.stdout)
    if len(result.values) != len(texts) or len(result.encodings) != len(texts):
        raise ValueError("journal encoder result count differs from the source")
    for text, values, encoding in zip(
        texts, result.values, result.encodings, strict=True
    ):
        if encoding.text_sha256 != hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise ValueError("journal encoder text identity differs from the source")
        if len(values) != result.encoder.dimensions:
            raise ValueError("journal encoder vector width differs")
        if encoding.encoder_sha256 != document_digest(result.encoder):
            raise ValueError("journal encoder identity differs")
    return result


def publish_completed_journal(
    root: Path, run: ResolvedRunRef, verified: VerifiedRunResult
) -> JournalPublicationResult:
    """Publish current experiment notes after the run's immutable closure.

    Every passage cites the run as context. Metric/Stage/Epoch/Step labels may
    select saved measurements; an unmatched selector rejects publication.
    Notes remain proposed regardless of any author-written Review field.
    """
    settings = load_journal_settings(root)
    if not settings.enabled:
        return JournalPublicationResult(skipped=True)
    relative = f"experiments/{verified.plan.run.experiment_id}/JOURNAL.md"
    if not (root / relative).exists():
        return JournalPublicationResult(skipped=True)
    path = resolve_path(root, relative, operation="read")
    raw = path.read_bytes()
    passages = parse_journal(raw)
    destination = LocalStorageDestination()
    source_path = f"knowledge/journals/{hashlib.sha256(raw).hexdigest()}.md"
    source = publish_resolved_files(root, destination, {source_path: raw})[source_path]
    store = knowledge(root=root, destination=destination)
    # Bind timestamps to the saved run so retrying unchanged notes does not
    # create different assertion/vector bytes just because the clock advanced.
    created_at = verified.result.completed_at
    declarations: list[JournalAssertion] = []
    for passage in passages:
        evidence = [JournalEvidence(kind="run", reference=run)]
        if "metric" not in passage.fields and any(
            key in passage.fields for key in ("stage", "epoch", "step")
        ):
            raise ValueError("journal Stage/Epoch/Step selectors require Metric")
        if "metric" in passage.fields:
            selected = [
                (measurement, reference)
                for measurement, reference in zip(
                    verified.measurements, verified.measurement_references, strict=True
                )
                if measurement.metric_id == passage.fields["metric"]
                and (
                    "stage" not in passage.fields
                    or measurement.stage_id == passage.fields["stage"]
                )
                and (
                    "epoch" not in passage.fields
                    or str(measurement.epoch) == passage.fields["epoch"]
                )
                and (
                    "step" not in passage.fields
                    or str(measurement.step) == passage.fields["step"]
                )
            ]
            if not selected:
                raise ValueError("journal measurement selector has no saved match")
            references = {reference.sha256: reference for _, reference in selected}
            evidence.extend(
                JournalEvidence(kind="measurement", reference=references[key])
                for key in sorted(references)
            )
        assertion = JournalAssertion(
            assertion_id=f"journal-{source.sha256}-{passage.byte_start}-{run.sha256}",
            kind=passage.kind,
            text=passage.text,
            evidence=tuple(evidence),
            status="proposed",
            authored_by=passage.fields.get("author", settings.authored_by),
            created_at=created_at,
            source=JournalSource(
                document=source,
                byte_start=passage.byte_start,
                byte_end=passage.byte_end,
                text_sha256=hashlib.sha256(passage.text.encode("utf-8")).hexdigest(),
                section=passage.section,
                fields=passage.fields,
            ),
        )
        declarations.append(assertion)
    assertions = tuple(
        store.publish_assertion(assertion).record for assertion in declarations
    )
    # Make original prose searchable even if downloading or encoding fails.
    Catalog(root).refresh_knowledge()
    if not passages:
        return JournalPublicationResult(source=source)
    encoded = encode_journal(
        tuple(passage.text for passage in passages),
        timeout_seconds=settings.timeout_seconds,
    )
    view = JournalVectorView(
        view_id="journal-qwen3-0.6b",
        version=document_digest(encoded.encoder),
        embedder=encoded.encoder,
        dimensions=encoded.encoder.dimensions,
    )
    vectors = tuple(
        store.publish_vector(
            KnowledgeVector(
                view=view,
                source=assertion,
                values=values,
                encoding=encoding,
                created_at=created_at,
            )
        ).record
        for assertion, values, encoding in zip(
            assertions, encoded.values, encoded.encodings, strict=True
        )
    )
    Catalog(root).refresh_knowledge()
    return JournalPublicationResult(
        source=source, assertions=assertions, vectors=vectors
    )


def publish_run_journal(
    root: Path, resolved_run: Path, *, trusted_source_repositories: frozenset[str]
) -> JournalPublicationResult:
    """Verify a saved run and publish its current journal without rerunning stages."""
    root = resolve_root(root)
    selected = resolved_run if resolved_run.is_absolute() else root / resolved_run
    path = resolve_path(root, selected.relative_to(root).as_posix(), operation="read")
    raw = path.read_bytes()
    result = ResolvedRun.model_validate(parse_yaml_bytes(raw))
    if result.status != "succeeded":
        raise ValueError("journal publication requires a succeeded run")
    source = read_source(root)
    fetcher = RunFetcher(root, LocalArtifactStore(root), str(source.repository))
    verified = verify_run_result(
        result, policy=VerificationPolicy(trusted_source_repositories), fetcher=fetcher
    )
    reference = LocalArtifactStore(root).resolved_files(
        {path.relative_to(root).as_posix(): raw}
    )[0]
    run = ResolvedRunRef(
        sha256=reference.sha256, bytes=reference.bytes, stored_at=reference.stored_at
    )
    return publish_completed_journal(root, run, verified)


def capture_completed_journal(
    root: Path, run: ResolvedRunRef, verified: VerifiedRunResult
) -> None:
    """Warn on journal failure without changing a completed experiment's result."""
    try:
        publish_completed_journal(root, run, verified)
    except (Exception, KeyboardInterrupt) as error:
        _LOGGER.warning(
            "Completed run %s is saved; journal publication failed: %s. "
            "Retry publish_run_journal without repeating model inference.",
            verified.plan.run.run_id,
            error,
        )


__all__ = [
    "JournalSettings",
    "JournalPassage",
    "JournalPublicationResult",
    "JournalEncodingResult",
    "load_journal_settings",
    "parse_journal",
    "encode_journal",
    "publish_run_journal",
]
