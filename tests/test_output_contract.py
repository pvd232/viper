"""Planned acceptance tests for the PAC-02 output lifecycle."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError

import viper.artifacts as artifacts
from viper.authoring import StageDraftOutputRef, download, stage
from viper.http import HttpRequestSpec, HttpRetrievalPolicy
from viper.ids import OutputName
from viper.outputs import EvalOutputs, OutputDraft, StageOutputs, TrainOutputs, output
from viper.stages import BaseSpec, DownloadSpec, ResolvedDownloadSpec

PAIR_BLOCK_ID = "P1-PAC-02"
REQUIREMENT_ID = "PAC-02"
PLANNED_DESTINATION = "tests/test_output_contract.py"


def _load_bytes(path: Path) -> bytes:
    """Load one completed output for acceptance assertions."""
    return path.read_bytes()


def _draft(path: str) -> OutputDraft:
    """Declare one output through the approved public constructor."""
    return output(path=path, loader=_load_bytes, data_role="training")


def _request() -> HttpRequestSpec:
    """Declare one deterministic HTTP response for download validation."""
    return HttpRequestSpec.model_validate(
        {
            "url": "https://data.example.org/train.csv",
            "version": "2026-09-08",
            "expected_body_sha256": "0" * 64,
            "expected_body_bytes": 1,
        }
    )


def _policy() -> HttpRetrievalPolicy:
    """Allow only the deterministic test origin."""
    return HttpRetrievalPolicy(
        allowed_schemes=frozenset({"https"}),
        allowed_hosts=frozenset({"data.example.org"}),
        allowed_ports=frozenset({443}),
        max_redirects=0,
        max_body_bytes=1,
        timeout_seconds=1,
    )


def test_output_constructor_returns_an_output_draft() -> None:
    """Name pre-execution writes as outputs rather than artifacts."""
    assert isinstance(_draft("model.json"), OutputDraft)


def test_flexible_stage_outputs_accept_workspace_names() -> None:
    """Allow flexible stages to choose semantic output field names."""

    class BuildOutputs(StageOutputs[OutputDraft]):
        features: OutputDraft
        index: OutputDraft

    selected = BuildOutputs(
        features=_draft("features.parquet"),
        index=_draft("search.index"),
    )
    assert selected.features.path == "features.parquet"
    assert selected.index.path == "search.index"


def test_output_names_must_be_identifiers() -> None:
    """Reject names that cannot become stable Python field access."""
    with pytest.raises(ValidationError, match="output name"):
        StageOutputs.model_validate({"not-a-name": _draft("value.bin")})


def test_draft_output_references_use_output_name() -> None:
    """Keep pre-execution output identity distinct from recorded artifacts."""
    annotations = get_type_hints(StageDraftOutputRef, include_extras=True)
    assert annotations["output_name"] == OutputName
    assert "artifact_name" not in annotations


@pytest.mark.parametrize("missing", ["model", "resume_state"])
def test_train_outputs_require_checkpoint_roles(missing: str) -> None:
    """Require both terminal training results by semantic role."""
    values = {
        "model": _draft("model.json"),
        "resume_state": _draft("resume_state.pt"),
    }
    del values[missing]
    with pytest.raises(ValidationError, match=missing):
        TrainOutputs.model_validate(values)


def test_eval_outputs_require_predictions() -> None:
    """Require the canonical evaluation result."""
    with pytest.raises(ValidationError, match="predictions"):
        EvalOutputs.model_validate({})


def test_typed_output_roles_support_attribute_access() -> None:
    """Expose required roles without a second enum or raw dictionary."""
    selected = TrainOutputs(
        model=_draft("model.json"),
        resume_state=_draft("resume_state.pt"),
    )
    assert selected.model.path == "model.json"
    assert selected.resume_state.path == "resume_state.pt"


def test_stage_authoring_accepts_outputs_not_artifacts() -> None:
    """Use outputs for promises made before stage execution."""
    parameters = inspect.signature(stage).parameters
    assert "outputs" in parameters
    assert "artifacts" not in parameters


def test_download_authoring_accepts_outputs_not_artifacts() -> None:
    """Use outputs for files promised by an HTTP download stage."""
    parameters = inspect.signature(download).parameters
    assert "outputs" in parameters
    assert "artifacts" not in parameters


def test_download_spec_declares_outputs_before_execution() -> None:
    """Keep download promises separate from completed artifacts."""
    assert "outputs" in BaseSpec.model_fields
    assert "artifacts" not in BaseSpec.model_fields
    assert "outputs" in DownloadSpec.model_fields
    assert "artifacts" not in DownloadSpec.model_fields
    assert "artifacts" in ResolvedDownloadSpec.model_fields


def test_download_requires_matching_input_and_output_names() -> None:
    """Bind each HTTP request to the output that receives its body."""
    with pytest.raises(ValidationError, match="input and output names must match"):
        download(
            inputs={"dataset": _request()},
            outputs=StageOutputs.model_validate({"other": _draft("train.csv")}),
            policy=_policy(),
        )


def test_download_rejects_bundle_outputs() -> None:
    """Require every downloaded response body to resolve as one file."""
    bundle = output(
        path="downloaded",
        loader=_load_bytes,
        data_role="training",
        kind="bundle",
    )
    with pytest.raises(ValidationError, match="outputs must be single files"):
        download(
            inputs={"dataset": _request()},
            outputs=StageOutputs.model_validate({"dataset": bundle}),
            policy=_policy(),
        )


def test_resolved_results_remain_artifacts() -> None:
    """Retain artifact terminology after VIPER observes completed bytes."""
    assert hasattr(artifacts, "ResolvedArtifact")
    assert hasattr(artifacts, "ResolvedSingleFileArtifact")


def test_generic_output_extras_deserialize_to_the_declared_value_type() -> None:
    """Validate workspace-defined output fields during protocol loading."""
    declared = StageOutputs[OutputDraft].model_validate(
        {"report": {"path": "report.json", "loader": _load_bytes, "data_role": "eval"}}
    )
    assert isinstance(declared["report"], OutputDraft)
