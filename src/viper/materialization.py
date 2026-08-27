"""Resolve verified same-run artifacts into stage input paths."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .ids import InputName, StageId
from .stages import (
    BaseSpec,
    FutureInputRef,
    InternalSpec,
)


class MaterializationError(RuntimeError):
    """Report an absent or unsafe stage input artifact."""


def future_input_paths(
    repository_root: Path,
    stage: InternalSpec,
    prior_stages: Mapping[StageId, BaseSpec],
) -> dict[InputName, Path]:
    """Map each same-run input to its canonical producer artifact path."""
    root = repository_root.resolve()
    paths: dict[InputName, Path] = {}
    for input_name, input_ref in stage.inputs.items():
        if not isinstance(input_ref, FutureInputRef):
            continue
        producer = prior_stages.get(input_ref.producer_stage_id)
        if producer is None:
            raise MaterializationError("future input producer has not completed")
        artifact = producer.artifacts.get(input_ref.producer_artifact)
        if artifact is None:
            raise MaterializationError("future input artifact is absent from producer")
        path = (root / artifact.path).resolve()
        if not path.is_relative_to(root):
            raise MaterializationError("future input path escapes the repository root")
        exists = path.is_file() if artifact.kind == "file" else path.is_dir()
        if not exists:
            raise MaterializationError("future input artifact has not materialized")
        paths[input_name] = path
    return paths
