"""Construct canonical paths used by verification operations."""

from .._schema import RepoRelPath
from ..ids import StageId
from ..runs import RunSpec


def run_root(run: RunSpec) -> RepoRelPath:
    """Return the canonical repository root for one run's records and outputs."""
    return f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"


def stage_spec_path(run: RunSpec, stage_id: StageId) -> RepoRelPath:
    """Return the canonical stage-spec path for a run stage."""
    return f"{run_root(run)}/stages/{stage_id}/spec.yaml"


def stage_invocation_path(
    run: RunSpec,
    attempt_id: int,
    stage_id: StageId,
) -> RepoRelPath:
    """Return the canonical receipt path for one attempted stage invocation."""
    return f"{run_root(run)}/attempts/{attempt_id}/invocations/{stage_id}.yaml"


def resolved_stage_spec_path(run: RunSpec, stage_id: StageId) -> RepoRelPath:
    """Return the canonical resolved-stage path for a run stage."""
    return f"{run_root(run)}/stages/{stage_id}/resolved.yaml"
