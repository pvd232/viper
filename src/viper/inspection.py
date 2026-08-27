"""Inspect and compare frozen VIPER plans without executing them."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .ids import RunId
from .journal import ATTEMPT_STATE_TRANSITIONS, AttemptState, DurableJournal
from .protocol import FutureInputRef, InternalSpec, RunSpec, StoredInputRef
from .serialization import load_stage_spec, parse_yaml_bytes
from .verifier import VerifiedRunResult


class InspectionError(RuntimeError):
    """Report an unreadable or internally inconsistent frozen plan."""


class PlanChange(BaseModel):
    """Describe one added, removed, or changed value between two plans."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    kind: Literal["added", "removed", "changed"]
    left: Any = None
    right: Any = None


class PlanDiff(BaseModel):
    """Return the complete ordered difference between two frozen plans."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left_run_id: RunId
    right_run_id: RunId
    identical: bool
    changes: tuple[PlanChange, ...]


class RunChange(BaseModel):
    """Describe one changed value between two verified terminal runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    kind: Literal["added", "removed", "changed"]
    left: Any = None
    right: Any = None


class RunComparison(BaseModel):
    """Return the complete ordered difference between two verified runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left_run_id: RunId
    right_run_id: RunId
    identical: bool
    changes: tuple[RunChange, ...]


class AttemptJournalStatus(BaseModel):
    """Summarize the latest durable state of one local run attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    journal: Path
    entry_count: int
    state: AttemptState | None
    event: str | None
    recorded_at: datetime | None
    details: dict[str, Any]
    next_states: tuple[AttemptState, ...]
    terminal: bool


class LineageNode(BaseModel):
    """Identify one stage, input, artifact, or promoted selection in a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    kind: Literal["stage", "input", "artifact", "promoted_selection"]
    data_role: str | None = None
    path: str | None = None


class LineageEdge(BaseModel):
    """Describe one directed production, selection, or consumption relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    relation: Literal["produces", "selects", "consumes"]


class RunLineage(BaseModel):
    """Return the verified upstream lineage graph of one successful run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: RunId
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]


_MISSING = object()


def _load_plan(
    repository_root: Path, run_spec_path: Path
) -> tuple[RunSpec, dict[str, Any]]:
    """Load one RunSpec and the exact stage specifications it identifies."""
    run_raw = run_spec_path.read_bytes()
    run = RunSpec.model_validate(parse_yaml_bytes(run_raw))
    stages: dict[str, Any] = {}
    for reference in run.stages:
        stage_path = repository_root / reference.spec
        raw = stage_path.read_bytes()
        if len(raw) != reference.bytes:
            raise InspectionError(
                f"stage {reference.stage_id!r} byte count differs from RunSpec"
            )
        if hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise InspectionError(
                f"stage {reference.stage_id!r} digest differs from RunSpec"
            )
        stages[str(reference.stage_id)] = load_stage_spec(stage_path).model_dump(
            mode="json"
        )
    document = {
        "run": run.model_dump(mode="json"),
        "stage_specs": stages,
    }
    return run, document


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    """Map each JSON leaf to one stable dotted path."""
    if isinstance(value, dict):
        if not value:
            return {path: {}}
        flattened: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{path}.{key}" if path else str(key)
            flattened.update(_flatten(value[key], child))
        return flattened
    if isinstance(value, list):
        if not value:
            return {path: []}
        flattened = {}
        for index, item in enumerate(value):
            flattened.update(_flatten(item, f"{path}[{index}]"))
        return flattened
    return {path: value}


def plan_diff(
    left_repository_root: Path,
    left_run_spec: Path,
    right_repository_root: Path,
    right_run_spec: Path,
) -> PlanDiff:
    """Compare two complete frozen plans and return every changed JSON leaf."""
    left_run, left_document = _load_plan(left_repository_root, left_run_spec)
    right_run, right_document = _load_plan(right_repository_root, right_run_spec)
    left = _flatten(left_document)
    right = _flatten(right_document)
    changes: list[PlanChange] = []
    for path in sorted(left.keys() | right.keys()):
        left_value = left.get(path, _MISSING)
        right_value = right.get(path, _MISSING)
        if left_value is _MISSING:
            changes.append(PlanChange(path=path, kind="added", right=right_value))
        elif right_value is _MISSING:
            changes.append(PlanChange(path=path, kind="removed", left=left_value))
        elif left_value != right_value:
            changes.append(
                PlanChange(
                    path=path,
                    kind="changed",
                    left=left_value,
                    right=right_value,
                )
            )
    return PlanDiff(
        left_run_id=left_run.run_id,
        right_run_id=right_run.run_id,
        identical=not changes,
        changes=tuple(changes),
    )


def attempt_status(journal_path: Path) -> AttemptJournalStatus:
    """Read one attempt journal and report its latest durable transition."""
    if not journal_path.is_file():
        raise FileNotFoundError(journal_path)
    entries = DurableJournal(journal_path).read()
    if not entries:
        return AttemptJournalStatus(
            journal=journal_path,
            entry_count=0,
            state=None,
            event=None,
            recorded_at=None,
            details={},
            next_states=("allocated",),
            terminal=False,
        )
    latest = entries[-1]
    return AttemptJournalStatus(
        journal=journal_path,
        entry_count=len(entries),
        state=latest.state,
        event=latest.event,
        recorded_at=latest.recorded_at,
        details=latest.details,
        next_states=ATTEMPT_STATE_TRANSITIONS[latest.state],
        terminal=latest.state == "terminal",
    )


def _verified_run_document(verified: VerifiedRunResult) -> dict[str, Any]:
    """Convert one verified terminal run into a stable comparison document."""
    plan = verified.plan
    measurements = sorted(
        (measurement.model_dump(mode="json") for measurement in verified.measurements),
        key=lambda measurement: (
            measurement["attempt_id"],
            measurement["stage_id"],
            measurement["metric_id"],
            -1 if measurement["epoch"] is None else measurement["epoch"],
            -1 if measurement["step"] is None else measurement["step"],
            measurement["measured_at"],
        ),
    )
    return {
        "terminal_run": verified.result.model_dump(mode="json"),
        "run_spec": plan.run.model_dump(mode="json"),
        "experiment_spec": plan.experiment.model_dump(mode="json"),
        "variant_spec": plan.variant.model_dump(mode="json"),
        "benchmark_spec": (
            None if plan.benchmark is None else plan.benchmark.model_dump(mode="json")
        ),
        "stage_specs": {
            str(stage_id): plan.stages[stage_id].model_dump(mode="json")
            for stage_id in sorted(plan.stages, key=str)
        },
        "resolved_stages": {
            str(stage_id): verified.resolved_stages[stage_id].model_dump(mode="json")
            for stage_id in sorted(verified.resolved_stages, key=str)
        },
        "measurements": measurements,
    }


def compare_runs(
    left: VerifiedRunResult,
    right: VerifiedRunResult,
) -> RunComparison:
    """Compare every connected value in two verified terminal runs."""
    left_values = _flatten(_verified_run_document(left))
    right_values = _flatten(_verified_run_document(right))
    changes: list[RunChange] = []
    for path in sorted(left_values.keys() | right_values.keys()):
        left_value = left_values.get(path, _MISSING)
        right_value = right_values.get(path, _MISSING)
        if left_value is _MISSING:
            changes.append(RunChange(path=path, kind="added", right=right_value))
        elif right_value is _MISSING:
            changes.append(RunChange(path=path, kind="removed", left=left_value))
        elif left_value != right_value:
            changes.append(
                RunChange(
                    path=path,
                    kind="changed",
                    left=left_value,
                    right=right_value,
                )
            )
    return RunComparison(
        left_run_id=left.plan.run.run_id,
        right_run_id=right.plan.run.run_id,
        identical=not changes,
        changes=tuple(changes),
    )


def lineage(verified: VerifiedRunResult) -> RunLineage:
    """Build a stable lineage graph from one completely verified run result."""
    nodes: dict[str, LineageNode] = {}
    edges: list[LineageEdge] = []
    for stage_reference in verified.plan.run.stages:
        stage_id = str(stage_reference.stage_id)
        stage = verified.plan.stages[stage_reference.stage_id]
        stage_node = f"stage:{stage_id}"
        nodes[stage_node] = LineageNode(
            node_id=stage_node,
            kind="stage",
            path=stage_reference.spec,
        )

        if isinstance(stage, InternalSpec):
            for input_name, input_ref in sorted(stage.inputs.items()):
                input_node = f"input:{stage_id}:{input_name}"
                if isinstance(input_ref, FutureInputRef):
                    producer_stage = verified.plan.stages[input_ref.producer_stage_id]
                    producer_artifact = producer_stage.artifacts[
                        input_ref.producer_artifact
                    ]
                    data_role = producer_artifact.data_role
                    input_path = producer_artifact.path
                else:
                    data_role = input_ref.data_role
                    input_path = input_ref.path
                nodes[input_node] = LineageNode(
                    node_id=input_node,
                    kind="input",
                    data_role=data_role,
                    path=input_path,
                )
                edges.append(
                    LineageEdge(
                        source=input_node,
                        target=stage_node,
                        relation="consumes",
                    )
                )
                if isinstance(input_ref, FutureInputRef):
                    source = (
                        f"artifact:{input_ref.producer_stage_id}:"
                        f"{input_ref.producer_artifact}"
                    )
                else:
                    assert isinstance(input_ref, StoredInputRef)
                    source = f"promoted:{stage_id}:{input_name}"
                    nodes[source] = LineageNode(
                        node_id=source,
                        kind="promoted_selection",
                        data_role=input_ref.data_role,
                        path=input_ref.pointer.path,
                    )
                edges.append(
                    LineageEdge(
                        source=source,
                        target=input_node,
                        relation="selects",
                    )
                )

        for artifact_name, artifact in sorted(stage.artifacts.items()):
            artifact_node = f"artifact:{stage_id}:{artifact_name}"
            nodes[artifact_node] = LineageNode(
                node_id=artifact_node,
                kind="artifact",
                data_role=artifact.data_role,
                path=artifact.path,
            )
            edges.append(
                LineageEdge(
                    source=stage_node,
                    target=artifact_node,
                    relation="produces",
                )
            )

    return RunLineage(
        run_id=verified.plan.run.run_id,
        nodes=tuple(nodes[node_id] for node_id in sorted(nodes)),
        edges=tuple(sorted(edges, key=lambda edge: (edge.source, edge.target))),
    )


__all__ = [
    "AttemptJournalStatus",
    "InspectionError",
    "LineageEdge",
    "LineageNode",
    "PlanChange",
    "PlanDiff",
    "RunChange",
    "RunComparison",
    "RunLineage",
    "attempt_status",
    "compare_runs",
    "lineage",
    "plan_diff",
]
