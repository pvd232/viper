"""Observe exact-text parsing, publication safety, and learned-vector identities."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import viper.journals as journals
from viper.evidence import VerifiedRunResult
from viper.journals import (
    JournalEncodingResult,
    JournalPublicationResult,
    JournalSettings,
    parse_journal,
)
from viper.knowledge import (
    JournalAssertion,
    JournalEncoderFile,
    JournalEncoderSpec,
    JournalEncoding,
    JournalEvidence,
    JournalSource,
    knowledge,
)
from viper.references import ResolvedRunRef
from viper.serialization import document_digest
from viper.storage import (
    LocalArtifactStore,
    LocalStorageDestination,
    publish_resolved_files,
)


def test_parser_preserves_unicode_crlf_fields_and_claim_kinds() -> None:
    """Keep exact spans while exposing methods, falsification, and corrections."""
    raw = (
        "# Scientific journal\r\n\r\n## Question and hypothesis\r\n"
        "Question: Does α improve retrieval?\r\nHypothesis: α improves it.\r\n"
        "Falsification: No matched-seed improvement.\r\n\r\n"
        "## Comparison and methods\r\nBaseline: old\r\nCandidate: new\r\n"
        "Held constant: seed and split\r\n\r\n"
        "## Observations\r\nID: obs-1\r\nMetric: mse\r\nStage: train\r\n"
        "Epoch: 20\r\nRecorded result is finite.\r\n\r\n"
        "## Interpretation and decision\r\nSupports: obs-1\r\n"
        "Supersedes: decision-0\r\nLimitations: toy data\r\n"
        "Next action: held-out evaluation\r\nReview: accepted\r\n\r\n"
        "## Notes\r\nUnclassified original prose.\r\n"
    ).encode()
    passages = parse_journal(raw)
    assert [passage.kind for passage in passages] == [
        "hypothesis",
        "note",
        "observation",
        "decision",
        "note",
    ]
    assert passages[0].fields["falsification"] == "No matched-seed improvement."
    assert passages[1].fields["held_constant"] == "seed and split"
    assert passages[3].fields["supersedes"] == "decision-0"
    for passage in passages:
        assert raw[passage.byte_start : passage.byte_end] == passage.text.encode(
            "utf-8"
        )


def test_parser_does_not_classify_headings_inside_code_fences() -> None:
    """Preserve code examples as notes instead of extracting fictional claims."""
    raw = b"## Notes\n```markdown\n## Hypothesis\nnot a real claim\n```\n"
    passages = parse_journal(raw)
    assert len(passages) == 1
    assert passages[0].kind == "note"
    assert passages[0].text == raw[len(b"## Notes\n") :].decode()


def test_shorter_fences_and_code_fields_do_not_change_scientific_structure() -> None:
    """Keep inner three-backtick examples inside an outer four-backtick fence."""
    raw = (
        b"## Notes\n````markdown\n```\n## Hypothesis\n"
        b"Hypothesis: example only\nMetric: not-real\n```\n````\n"
    )
    passages = parse_journal(raw)
    assert len(passages) == 1
    assert passages[0].kind == "note"
    assert passages[0].fields == {}


def test_parser_rejects_duplicate_fields_and_non_utf8() -> None:
    """Reject ambiguous scientific fields and invalid source encoding."""
    with pytest.raises(ValueError, match="duplicate journal field"):
        parse_journal(b"## Observations\nMetric: a\nMetric: b\n")
    with pytest.raises(UnicodeDecodeError):
        parse_journal(b"\xff")


def test_journal_publication_is_default_on_with_strict_optout() -> None:
    """Keep publication on by default and reject unknown opt-out settings."""
    assert JournalSettings().enabled
    assert not JournalSettings(enabled=False).enabled
    with pytest.raises(ValueError):
        JournalSettings.model_validate({"enable": False})


@pytest.mark.parametrize("timeout_seconds", (None, 12.0))
def test_encoder_budget_covers_slow_startup_and_preserves_explicit_limits(
    monkeypatch: pytest.MonkeyPatch, timeout_seconds: float | None
) -> None:
    """Allow a simulated 180-second worker only with the new default budget."""
    text = "Exact journal text.\r\n"
    encoder = JournalEncoderSpec(
        files=(JournalEncoderFile(path="model.safetensors", sha256="0" * 64, bytes=1),),
        transformers_version="test",
        torch_version="test",
        python_version="test",
        platform="test",
        tokenizers_version="test",
        safetensors_version="test",
    )
    expected = JournalEncodingResult(
        encoder=encoder,
        values=((1.0,) + (0.0,) * 1023,),
        encodings=(
            JournalEncoding(
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                encoder_sha256=document_digest(encoder),
                token_count=5,
            ),
        ),
    )

    def worker(command: tuple[str, ...], **options: object) -> SimpleNamespace:
        """Represent a 180-second worker by checking its deadline."""
        budget = cast(float, options["timeout"])
        assert budget == (600 if timeout_seconds is None else timeout_seconds)
        if budget < 180:
            raise journals.subprocess.TimeoutExpired(command, budget)
        return SimpleNamespace(returncode=0, stdout=expected.model_dump_json())

    monkeypatch.setattr(journals.subprocess, "run", worker)
    assert JournalSettings().timeout_seconds == 600
    if timeout_seconds is None:
        assert journals.encode_journal((text,)) == expected
    else:
        with pytest.raises(journals.subprocess.TimeoutExpired):
            journals.encode_journal((text,), timeout_seconds=timeout_seconds)


def test_optout_does_not_read_journal_or_invoke_encoder(tmp_path: Path) -> None:
    """Disable the entire capture path before resolving experiment files."""
    (tmp_path / "viper.toml").write_text("[journals]\nenabled = false\n")
    result = journals.publish_completed_journal(
        tmp_path, cast(ResolvedRunRef, None), cast(VerifiedRunResult, None)
    )
    assert result == JournalPublicationResult(skipped=True)
    assert not (tmp_path / ".viper").exists()


def test_absent_journal_does_not_invoke_encoder(tmp_path: Path) -> None:
    """Avoid model downloads and knowledge state for experiments without notes."""
    (tmp_path / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    verified = cast(
        VerifiedRunResult,
        SimpleNamespace(
            plan=SimpleNamespace(run=SimpleNamespace(experiment_id="no-notes"))
        ),
    )
    result = journals.publish_completed_journal(
        tmp_path, cast(ResolvedRunRef, None), verified
    )
    assert result.skipped
    assert not (tmp_path / ".viper").exists()


def test_capture_failure_warns_without_changing_saved_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Leave closure intact when downloading or encoding the journal fails."""

    def failed(*_args: object) -> None:
        """Represent an unavailable learned encoder."""
        raise RuntimeError("encoder unavailable")

    monkeypatch.setattr(journals, "publish_completed_journal", failed)
    verified = cast(
        VerifiedRunResult,
        SimpleNamespace(plan=SimpleNamespace(run=SimpleNamespace(run_id="saved-run"))),
    )
    journals.capture_completed_journal(Path.cwd(), cast(ResolvedRunRef, None), verified)
    assert "saved-run is saved; journal publication failed" in caplog.text
    assert "without repeating model inference" in caplog.text


def test_publication_rejects_assertion_not_matching_retained_span(
    tmp_path: Path,
) -> None:
    """Reject a forged offset even when the assertion's own digest is correct."""
    raw = b"First passage.\nSecond passage.\n"
    source = publish_resolved_files(
        tmp_path, LocalStorageDestination(), {"knowledge/journal.md": raw}
    )["knowledge/journal.md"]
    run_ref = LocalArtifactStore(tmp_path).resolved_files({"run.yaml": b"run"})[0]
    assertion = JournalAssertion(
        assertion_id="bad-span",
        kind="note",
        text="Second passage.\n",
        evidence=(JournalEvidence(kind="run", reference=run_ref),),
        status="proposed",
        authored_by="test",
        created_at=datetime.now(UTC),
        source=JournalSource(
            document=source,
            byte_start=0,
            byte_end=len(b"Second passage.\n"),
            text_sha256=hashlib.sha256(b"Second passage.\n").hexdigest(),
            section="Notes",
        ),
    )
    with pytest.raises(ValueError, match="source passage differs"):
        knowledge(
            root=tmp_path, destination=LocalStorageDestination()
        ).publish_assertion(assertion)
