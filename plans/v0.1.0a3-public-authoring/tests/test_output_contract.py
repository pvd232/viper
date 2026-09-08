"""Planned acceptance tests for the PAC-02 output lifecycle."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

PAIR_BLOCK_ID = "P1-PAC-02"
REQUIREMENT_ID = "PAC-02"
PLANNED_DESTINATION = "tests/test_output_contract.py"


def _load_bytes(path: Path) -> bytes:
    """Load one completed output for acceptance assertions."""
    return path.read_bytes()


def _draft(path: str) -> object:
    """Declare one output through the approved public constructor."""
    viper = importlib.import_module("viper")
    return viper.output(path=path, loader=_load_bytes, data_role="training")


def test_output_constructor_returns_an_output_draft() -> None:
    """Name pre-execution writes as outputs rather than artifacts."""
    outputs = importlib.import_module("viper.outputs")
    assert isinstance(_draft("parameters.json"), outputs.OutputDraft)


def test_flexible_stage_outputs_accept_workspace_names() -> None:
    """Allow flexible stages to choose semantic output field names."""
    outputs = importlib.import_module("viper.outputs")
    selected = outputs.StageOutputs(
        features=_draft("features.parquet"),
        index=_draft("search.index"),
    )
    assert selected.features.path == "features.parquet"
    assert selected.index.path == "search.index"


def test_output_names_must_be_identifiers() -> None:
    """Reject names that cannot become stable Python field access."""
    outputs = importlib.import_module("viper.outputs")
    with pytest.raises(ValidationError, match="output name"):
        outputs.StageOutputs.model_validate({"not-a-name": _draft("value.bin")})


@pytest.mark.parametrize("missing", ["parameters", "resume_state"])
def test_train_outputs_require_checkpoint_roles(missing: str) -> None:
    """Require both terminal training results by semantic role."""
    outputs = importlib.import_module("viper.outputs")
    values = {
        "parameters": _draft("parameters.json"),
        "resume_state": _draft("resume_state.pt"),
    }
    del values[missing]
    with pytest.raises(ValidationError, match=missing):
        outputs.TrainOutputs.model_validate(values)


def test_eval_outputs_require_predictions() -> None:
    """Require the canonical evaluation result."""
    outputs = importlib.import_module("viper.outputs")
    with pytest.raises(ValidationError, match="predictions"):
        outputs.EvalOutputs.model_validate({})


def test_typed_output_roles_support_attribute_access() -> None:
    """Expose required roles without a second enum or raw dictionary."""
    outputs = importlib.import_module("viper.outputs")
    selected = outputs.TrainOutputs(
        parameters=_draft("parameters.json"),
        resume_state=_draft("resume_state.pt"),
    )
    assert selected.parameters.path == "parameters.json"
    assert selected.resume_state.path == "resume_state.pt"


def test_stage_authoring_accepts_outputs_not_artifacts() -> None:
    """Use outputs for promises made before stage execution."""
    authoring = importlib.import_module("viper.authoring")
    parameters = inspect.signature(authoring.stage).parameters
    assert "outputs" in parameters
    assert "artifacts" not in parameters


def test_resolved_results_remain_artifacts() -> None:
    """Retain artifact terminology after VIPER observes completed bytes."""
    artifacts = importlib.import_module("viper.artifacts")
    assert hasattr(artifacts, "ResolvedArtifact")
    assert hasattr(artifacts, "ResolvedSingleFileArtifact")
