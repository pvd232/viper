"""Planned acceptance tests for PAC-03 output and pointer locations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from viper.execution._stage import StageExecutionError, _resolved_output_paths
from viper.outputs import OutputDraft, OutputSpec, StageOutputs, output, run_output_path
from viper.references import output_pointer_path

PAIR_BLOCK_ID = "P1-PAC-03"
REQUIREMENT_ID = "PAC-03"
PLANNED_DESTINATION = "tests/test_output_paths.py"


def _load_bytes(path: Path) -> bytes:
    """Load output bytes for a planned declaration."""
    return path.read_bytes()


def _output(path: str) -> OutputDraft:
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

    class BuildOutputs(StageOutputs[OutputDraft]):
        features: OutputDraft
        index: OutputDraft

    declared = BuildOutputs(
        features=_output("customers.parquet"),
        index=_output("customers.usearch"),
    )
    assert set(declared.keys()) == {"features", "index"}


def test_generated_run_paths_use_stage_and_output_identity() -> None:
    """Place bytes under the stage ID, output name, and relative path."""
    path = run_output_path(
        stage_id="train", output_name="model", relative_path="model.json"
    )
    assert path == "artifacts/train/model/model.json"


def test_generated_pointer_paths_use_run_stage_and_output_identity() -> None:
    """Keep storage categories out of promoted-output pointer paths."""
    path = output_pointer_path(
        run_digest="a" * 64,
        producer_stage_id="train",
        output_name="model",
    )
    assert path == (".viper/pointers/" + "a" * 64 + "/train/model.pointer.yaml")


def test_generated_paths_do_not_contain_retired_categories() -> None:
    """Exclude datasets, models, priors, and evals from generated identity."""
    path = run_output_path(
        stage_id="build", output_name="features", relative_path="values.bin"
    )
    assert not {"datasets", "models", "priors", "evals"} & set(path.split("/"))


def test_repeated_output_detaches_readonly_snapshot_inode(tmp_path: Path) -> None:
    """Allow a new attempt to write without mutating retained artifact bytes."""
    stored = tmp_path / "immutable.bin"
    stored.write_bytes(b"original measurement")
    stored.chmod(0o444)
    (tmp_path / "outputs").mkdir()
    output_path = tmp_path / "outputs/output.bin"
    os.link(stored, output_path)
    declaration = OutputSpec.model_validate(
        {
            "kind": "file",
            "path": "outputs/output.bin",
            "relative_path": "output.bin",
            "loader": {
                "path": "loader.py",
                "symbol": "load",
                "sha256": "b" * 64,
                "bytes": 1,
            },
            "data_role": "training",
        }
    )
    resolved = _resolved_output_paths(tmp_path, {"model": declaration})
    assert resolved["model"].read_bytes() == b"original measurement"
    output_path.write_bytes(b"new measurement")
    assert stored.read_bytes() == b"original measurement"
    assert stored.stat().st_mode & 0o222 == 0
    assert stored.stat().st_ino != output_path.stat().st_ino


@pytest.mark.parametrize("link", ("parent", "file"))
def test_output_preparation_rejects_symlinks_without_touching_store(
    tmp_path: Path, link: str
) -> None:
    """Reject aliases into retained storage before replacing any output inode."""
    retained = tmp_path / "retained"
    retained.mkdir()
    stored = retained / "output.bin"
    stored.write_bytes(b"immutable result")
    stored.chmod(0o444)
    inode = stored.stat().st_ino
    outputs = tmp_path / "outputs"
    if link == "parent":
        outputs.symlink_to(retained, target_is_directory=True)
    else:
        outputs.mkdir()
        (outputs / "output.bin").symlink_to(stored)
    declaration = OutputSpec.model_validate(
        {
            "path": "outputs/output.bin",
            "relative_path": "output.bin",
            "loader": {
                "path": "loader.py",
                "symbol": "load",
                "sha256": "b" * 64,
                "bytes": 1,
            },
            "data_role": "training",
        }
    )
    with pytest.raises(StageExecutionError, match="symlink"):
        _resolved_output_paths(tmp_path, {"model": declaration})
    assert stored.read_bytes() == b"immutable result"
    assert stored.stat().st_ino == inode
    assert stored.stat().st_mode & 0o222 == 0
