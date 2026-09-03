"""Acceptance tests for runner-owned download artifact publication."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from viper.execution._downloads import publish_download_body
from viper.execution.errors import RunError


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
