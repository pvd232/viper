"""Tests for canonical protocol-document serialization and compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from viper.serialization import (
    load_stage_spec,
    serialize_document,
    serialize_record,
)


def test_deprecated_serializer_preserves_canonical_bytes() -> None:
    """Emit one warning and return the canonical document bytes."""
    document = load_stage_spec(Path("examples/provenance/stages/download/spec.yaml"))

    with pytest.warns(DeprecationWarning, match="serialize_document"):
        legacy = serialize_record(document)

    assert legacy == serialize_document(document)
