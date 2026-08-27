"""Construct canonical repository paths owned by the VIPER protocol."""

from __future__ import annotations

from typing import cast

from ._schema import RepoRelPath
from .ids import InputName, StageId
from .runs import RunSpec


def retrieval_body_path(
    run: RunSpec,
    stage_id: StageId,
    input_name: InputName,
) -> RepoRelPath:
    """Return the canonical stage-snapshot path of one retrieved HTTP body."""
    return cast(
        RepoRelPath,
        f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}/"
        f"stages/{stage_id}/retrievals/{input_name}/body",
    )
