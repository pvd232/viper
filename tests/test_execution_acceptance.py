"""Acceptance tests for runner-owned download artifact publication."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.test_storage import InMemoryViperCloudProvider, install_in_memory_cloud
from viper.execution._downloads import publish_download_body
from viper.execution._publication import publish_attempt_files
from viper.execution.errors import RunError
from viper.journal import DurableJournal
from viper.references import GcsFileRef
from viper.storage import ViperCloudDestination


def test_download_body_becomes_declared_artifact(tmp_path: Path) -> None:
    """Copy and hash the HTTP result at the declared artifact path."""
    body = b"tiny response body"
    scratch = tmp_path / ".viper/workspaces/run/attempts/1/http/body"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(body)
    destination = "experiments/example/artifacts/datasets/tiny/dataset.bin"

    reference = publish_download_body(
        repository_root=tmp_path,
        source=scratch,
        destination=destination,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        expected_bytes=len(body),
    )

    assert (tmp_path / destination).read_bytes() == body
    assert reference.path == destination
    assert reference.sha256 == hashlib.sha256(body).hexdigest()
    assert reference.bytes == len(body)


def test_download_publication_rejects_cloud_only_output_materialization(
    tmp_path: Path,
) -> None:
    """Materialize HTTP bodies at the declared artifact path only."""
    body = b"tiny response body"
    scratch = tmp_path / ".viper/workspaces/run/attempts/1/http/body"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(body)
    destination = "experiments/example/artifacts/datasets/tiny/dataset.bin"
    cloud_only_destination = (
        tmp_path / ".viper/workspaces/run/attempt-1/stages/download/outputs/tiny.bin"
    )

    reference = publish_download_body(
        repository_root=tmp_path,
        source=scratch,
        destination=destination,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        expected_bytes=len(body),
    )

    assert (tmp_path / destination).read_bytes() == body
    assert not cloud_only_destination.exists()
    assert reference.path == destination
    assert reference.sha256 == hashlib.sha256(body).hexdigest()
    assert reference.bytes == len(body)


def test_download_body_mutation_prevents_artifact_publication(tmp_path: Path) -> None:
    """Reject a same-size body mutation before the artifact becomes visible."""
    expected = b"prior"
    scratch = tmp_path / ".viper/workspaces/run/attempts/1/http/body"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"alter")
    destination = "experiments/example/artifacts/datasets/tiny/prior.bin"

    with pytest.raises(RunError, match="SHA-256 changed"):
        publish_download_body(
            repository_root=tmp_path,
            source=scratch,
            destination=destination,
            expected_sha256=hashlib.sha256(expected).hexdigest(),
            expected_bytes=len(expected),
        )

    assert not (tmp_path / destination).exists()


def test_attempt_publishes_evidence_to_selected_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish journal, metric, verification, and log bytes directly to cloud."""
    run_root = "experiments/example/runs/run"
    journal = DurableJournal(tmp_path / run_root / "attempts/1/journal.jsonl")
    journal.path.parent.mkdir(parents=True)
    journal.path.write_bytes(b'{"state":"terminal"}\n')
    measurement = tmp_path / run_root / "attempts/1/measurements/score.json"
    verification = tmp_path / run_root / "attempts/1/metric_verification/score.json"
    measurement.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    measurement.write_bytes(b'{"value":1}\n')
    verification.write_bytes(b'{"verified":true}\n')
    client = InMemoryViperCloudProvider(tmp_path)
    install_in_memory_cloud(monkeypatch, tmp_path, client)

    journal_ref, measurements, verifications, logs = publish_attempt_files(
        tmp_path,
        ViperCloudDestination(owner="machina", workspace="weekend_models"),
        run_root,
        1,
        journal,
        {f"{run_root}/attempts/1/logs/stage.log": b"complete\n"},
        [measurement],
        [verification],
    )

    stored = (
        journal_ref.stored_at,
        measurements[0].stored_at,
        verifications[0].stored_at,
        logs[0].stored_at,
    )
    assert all(isinstance(item, GcsFileRef) for item in stored)
    assert not (tmp_path / ".viper/store").exists()
