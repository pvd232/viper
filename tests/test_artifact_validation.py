"""Tests for artifact-loader identities and typed validation outcomes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.fixtures import (
    DEFAULT_ARTIFACT_LOADER_SOURCE,
    artifact_loader_ref,
)
from viper.artifact_loaders import (
    ArtifactLoaderError,
    ArtifactLoaderWorkerResult,
    ArtifactValidationResult,
    verify_artifact_loader_bytes,
)


def test_artifact_loader_reference_accepts_its_exact_source() -> None:
    """Accept source bytes matching the frozen loader identity."""
    reference = artifact_loader_ref("project/loaders/bytes_file.py")

    verify_artifact_loader_bytes(reference, DEFAULT_ARTIFACT_LOADER_SOURCE)


def test_artifact_loader_reference_rejects_same_length_tampering() -> None:
    """Reject changed loader bytes even when the byte count is unchanged."""
    reference = artifact_loader_ref("project/loaders/bytes_file.py")
    tampered = bytearray(DEFAULT_ARTIFACT_LOADER_SOURCE)
    tampered[-2] = ord(" ")

    with pytest.raises(ArtifactLoaderError, match="loader SHA-256 differs"):
        verify_artifact_loader_bytes(reference, bytes(tampered))


def test_artifact_worker_result_requires_one_outcome() -> None:
    """Reject worker results that contain neither success nor failure."""
    with pytest.raises(ValidationError, match="requires one outcome"):
        ArtifactLoaderWorkerResult()


def test_artifact_validation_names_the_established_guarantee() -> None:
    """Represent generic loadability and reserved semantic validation distinctly."""
    loadability = ArtifactValidationResult(guarantee="artifact.loadability")
    semantic = ArtifactValidationResult(guarantee="artifact.semantic.resume_state")

    assert loadability.guarantee == "artifact.loadability"
    assert semantic.guarantee == "artifact.semantic.resume_state"
