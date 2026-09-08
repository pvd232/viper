"""Planned acceptance tests for PAC-03 output and pointer locations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from viper.outputs import StageOutputs, output, run_output_path

from viper.references import output_pointer_path

PAIR_BLOCK_ID = "P1-PAC-03"
REQUIREMENT_ID = "PAC-03"
PLANNED_DESTINATION = "tests/test_output_paths.py"


def _load_bytes(path: Path) -> bytes:
    """Load output bytes for a planned declaration."""
    return path.read_bytes()


def _output(path: str) -> Any:
    """Build one future output declaration."""
    return output(path=path, loader=_load_bytes, data_role="training")


def test_output_paths_are_relative_to_the_named_output() -> None:
    """Keep stage and output identity out of the user-supplied path."""
    draft = _output("nested/value.bin")
    assert draft.path == "nested/value.bin"


@pytest.mark.parametrize("path", ["/value.bin", "../value.bin", "a/../../value.bin"])
def test_output_paths_reject_escape_from_generated_root(path: str) -> None:
    """Prevent an output from escaping its generated directory."""
    with pytest.raises(ValidationError):
        _output(path)


def test_two_build_outputs_do_not_require_categories() -> None:
    """Accept unrelated workspace outputs without build-to-priors coupling."""
    declared = StageOutputs(
        features=_output("customers.parquet"),
        index=_output("customers.usearch"),
    )
    assert set(declared) == {"features", "index"}


def test_generated_run_paths_use_stage_and_output_identity() -> None:
    """Place bytes under the stage ID, output name, and relative path."""
    path = run_output_path(
        stage_id="train", output_name="parameters", relative_path="model.json"
    )
    assert path == "artifacts/train/parameters/model.json"


def test_generated_pointer_paths_use_run_stage_and_output_identity() -> None:
    """Keep storage categories out of promoted-output pointer paths."""
    path = output_pointer_path(
        run_digest="a" * 64,
        producer_stage_id="train",
        output_name="parameters",
    )
    assert path == (
        ".viper/pointers/"
        + "a" * 64
        + "/train/parameters.pointer.yaml"
    )


def test_generated_paths_do_not_contain_retired_categories() -> None:
    """Exclude datasets, models, priors, and evals from generated identity."""
    path = run_output_path(
        stage_id="build", output_name="features", relative_path="values.bin"
    )
    assert not {"datasets", "models", "priors", "evals"} & set(path.split("/"))
