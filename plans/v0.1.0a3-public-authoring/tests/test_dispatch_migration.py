"""Planned acceptance tests for PAC-06 dispatch and migration failures."""

from __future__ import annotations

import importlib
import inspect

import pytest
from pydantic import TypeAdapter, ValidationError

PAIR_BLOCK_ID = "P2-PAC-06"
REQUIREMENT_ID = "PAC-06"
PLANNED_DESTINATION = "tests/test_dispatch_migration.py"

SUPPORTED_KINDS = {"download", "build", "embed", "train", "eval", "diagnostic"}


def test_frozen_stage_union_contains_every_supported_kind() -> None:
    """Keep every stage discriminator in the public frozen union."""
    stages = importlib.import_module("viper.stages")
    schema = TypeAdapter(stages.Spec).json_schema()
    assert set(schema["discriminator"]["mapping"]) == SUPPORTED_KINDS


def test_resolved_stage_union_contains_every_supported_kind() -> None:
    """Keep every stage discriminator in the resolved union."""
    stages = importlib.import_module("viper.stages")
    schema = TypeAdapter(stages.ResolvedSpec).json_schema()
    assert set(schema["discriminator"]["mapping"]) == SUPPORTED_KINDS


@pytest.mark.parametrize(
    "module_name,function_name",
    [
        ("viper.authoring", "stage"),
        ("viper.execution._resolution", "resolve_stage"),
        ("viper.execution._reuse", "_resolved_stage"),
    ],
)
def test_stage_dispatch_has_explicit_unsupported_kind_error(
    module_name: str,
    function_name: str,
) -> None:
    """Forbid an evaluation or other subtype as the default branch."""
    module = importlib.import_module(module_name)
    source = inspect.getsource(getattr(module, function_name))
    assert "unsupported stage kind" in source
    assert "return ResolvedEvalSpec" not in source.split("else:")[-1]


def test_unknown_stage_discriminator_is_rejected_by_name() -> None:
    """Report the received discriminator instead of guessing its subtype."""
    stages = importlib.import_module("viper.stages")
    with pytest.raises(ValidationError, match="unknown"):
        TypeAdapter(stages.Spec).validate_python(
            {"kind": "unknown", "schema_version": 2}
        )


@pytest.mark.parametrize("retired", ["params", "parameter_model", "stage_params"])
def test_version_one_config_vocabulary_gets_migration_error(retired: str) -> None:
    """Reject affected version-1 documents with an actionable message."""
    serialization = importlib.import_module("viper.serialization")
    with pytest.raises(
        serialization.MigrationRequiredError,
        match=rf"schema version 1.+{retired}.+config",
    ):
        serialization.load_stage_document(
            {"kind": "train", "schema_version": 1, retired: {}}
        )


def test_version_one_authoring_artifacts_get_migration_error() -> None:
    """Explain the output vocabulary when an old authoring document is loaded."""
    serialization = importlib.import_module("viper.serialization")
    with pytest.raises(
        serialization.MigrationRequiredError,
        match=r"schema version 1.+artifacts.+outputs",
    ):
        serialization.load_stage_document(
            {"kind": "train", "schema_version": 1, "artifacts": {}}
        )
