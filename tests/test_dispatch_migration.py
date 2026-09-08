"""Acceptance tests for PAC-06 dispatch and migration failures."""

from __future__ import annotations

import inspect

import pytest
from pydantic import TypeAdapter, ValidationError

import viper.authoring as authoring
import viper.execution._resolution as resolution
import viper.execution._reuse as reuse
import viper.serialization as serialization
import viper.stages as stages

PAIR_BLOCK_ID = "P2-PAC-06"
REQUIREMENT_ID = "PAC-06"
SUPPORTED_KINDS = {"download", "build", "embed", "train", "eval", "diagnostic"}


def test_frozen_stage_union_contains_every_supported_kind() -> None:
    """Keep every stage discriminator in the public frozen union."""
    schema = TypeAdapter(stages.Spec).json_schema()
    assert set(schema["discriminator"]["mapping"]) == SUPPORTED_KINDS


def test_resolved_stage_union_contains_every_supported_kind() -> None:
    """Keep every stage discriminator in the resolved union."""
    schema = TypeAdapter(stages.ResolvedSpec).json_schema()
    assert set(schema["discriminator"]["mapping"]) == SUPPORTED_KINDS


@pytest.mark.parametrize(
    "module,function_name",
    [
        (authoring, "stage"),
        (resolution, "resolve_stage"),
        (reuse, "_resolved_stage"),
    ],
)
def test_stage_dispatch_has_explicit_unsupported_kind_error(
    module: object,
    function_name: str,
) -> None:
    """Forbid an evaluation or other subtype as the default branch."""
    source = inspect.getsource(getattr(module, function_name))
    assert "unsupported stage kind" in source
    assert "return ResolvedEvalSpec" not in source.split("else:")[-1]


def test_unknown_stage_discriminator_is_rejected_by_name() -> None:
    """Report the received discriminator instead of guessing its subtype."""
    with pytest.raises(ValidationError, match="unknown"):
        TypeAdapter(stages.Spec).validate_python(
            {"kind": "unknown", "schema_version": 2}
        )


@pytest.mark.parametrize("retired", ["params", "parameter_model", "stage_params"])
def test_version_one_config_vocabulary_gets_migration_error(retired: str) -> None:
    """Reject affected version-1 documents with an actionable message."""
    with pytest.raises(
        serialization.MigrationRequiredError,
        match=rf"schema version 1.+{retired}.+config",
    ):
        serialization.load_stage_document(
            {"kind": "train", "schema_version": 1, retired: {}}
        )


def test_version_one_authoring_artifacts_get_migration_error() -> None:
    """Explain the output vocabulary when an old authoring document is loaded."""
    with pytest.raises(
        serialization.MigrationRequiredError,
        match=r"schema version 1.+artifacts.+outputs",
    ):
        serialization.load_stage_document(
            {"kind": "train", "schema_version": 1, "artifacts": {}}
        )
