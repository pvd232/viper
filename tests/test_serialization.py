"""Tests for canonical protocol-document serialization and compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from viper.serialization import (
    load_stage_spec,
    serialize_document,
    serialize_record,
)

EXAMPLE_STAGE = Path(__file__).parent / "data/download_stage.yaml"


def test_deprecated_serializer_preserves_canonical_bytes() -> None:
    """Emit one warning and return the canonical document bytes."""
    document = load_stage_spec(EXAMPLE_STAGE)

    with pytest.warns(DeprecationWarning, match="serialize_document"):
        legacy = serialize_record(document)

    assert legacy == serialize_document(document)
