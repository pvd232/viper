"""Tests for deterministic inspection of complete frozen run plans."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.fixtures import python_environment
from viper.catalog import Catalog, CatalogRunSource, RunQuery
from viper.experiments import (
    ExperimentSpec,
    VariantSpec,
)
from viper.inspection import (
    InspectionError,
    attempt_status,
    compare_runs,
    lineage,
    plan_diff,
)
from viper.journal import DurableJournal
from viper.references import (
    GitFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
)
from viper.runs import (
    ResolvedRun,
    RunSpec,
)
from viper.serialization import load_stage_spec, parse_yaml_bytes, serialize_document
from viper.stages import DownloadSpec
from viper.verification.models import VerifiedRunPlan, VerifiedRunResult

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/inspection/runs/baseline/{RUN_ID}"
COMMIT = "a" * 40
EXAMPLE_STAGE = Path(__file__).parent / "data/download_stage.yaml"


def _run(stage_raw: bytes, *, seed: int) -> RunSpec:
    """Build one valid plan bound to the supplied stage bytes."""
    return RunSpec.model_validate(
        {
            "run_id": RUN_ID,
            "experiment_id": "inspection",
            "variant_id": "baseline",
            "replicate_id": "replicate_01",
            "seed": seed,
            "source": {
                "kind": "git",
                "repository": "https://github.com/example/project",
                "commit": COMMIT,
            },
            "env": {
                "kind": "local",
                "compute": {"kind": "cpu"},
                "python_env": python_environment().model_dump(mode="json"),
                "lockfile": {
                    "kind": "git",
                    "repository": "https://github.com/example/project",
                    "commit": COMMIT,
                    "path": "environment.yml",
                },
            },
            "reproducibility": {
                "determinism": {
                    "deterministic_algorithms": True,
                    "deterministic_warn_only": False,
                    "cudnn_deterministic": True,
                    "cudnn_benchmark": False,
                    "cublas_workspace_config": ":4096:8",
                },
                "precision": {
                    "float32_matmul_precision": "highest",
                    "cudnn_allow_tf32": False,
                    "autocast_enabled": False,
                    "autocast_dtype": None,
                },
                "parallelism": {
                    "process_count": 1,
                    "torch_intraop_threads": 1,
                    "torch_interop_threads": 1,
                    "dataloader": {
                        "workers": 0,
                        "prefetch_factor": None,
                        "persistent_workers": False,
                        "in_order": True,
                    },
                },
                "numpy_randomness": {
                    "generators": {"training": "PCG64"},
                    "capture_legacy_global": True,
                },
            },
            "stages": [
                {
                    "stage_id": "download",
                    "spec": f"{RUN_ROOT}/stages/download/spec.yaml",
                    "sha256": hashlib.sha256(stage_raw).hexdigest(),
                    "bytes": len(stage_raw),
                }
            ],
            "estimator": {
                "stage_id": "download",
                "artifact_name": "model",
            },
        }
    )


def _write_plan(root: Path, *, seed: int) -> Path:
    """Write one complete frozen plan beneath a temporary repository root."""
    stage_data = parse_yaml_bytes(EXAMPLE_STAGE.read_bytes())
    stage_data.pop("environment")
    for artifact in stage_data["artifacts"].values():
        if artifact["data_role"] == "evaluation":
            artifact["data_role"] = "eval"
    stage_raw = serialize_document(DownloadSpec.model_validate(stage_data))
    stage_path = root / RUN_ROOT / "stages/download/spec.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_bytes(stage_raw)
    run_path = root / RUN_ROOT / "spec.yaml"
    run_path.write_bytes(serialize_document(_run(stage_raw, seed=seed)))
    return run_path


def _verified_result(root: Path, run_path: Path) -> VerifiedRunResult:
    """Build the connected verified value used by inspection unit tests."""
    run = RunSpec.model_validate(parse_yaml_bytes(run_path.read_bytes()))
    stage = load_stage_spec(root / RUN_ROOT / "stages/download/spec.yaml")
    resolved_run = ResolvedRun.model_construct(
        schema_version=1,
        spec=ResolvedRunSpecRef(
            sha256="b" * 64,
            bytes=1,
            stored_at=GitFileRef.model_validate(
                {
                    "repository": "https://github.com/example/project",
                    "commit": COMMIT,
                    "path": f"{RUN_ROOT}/spec.yaml",
                }
            ),
        ),
        status="succeeded",
        attempts=(),
        successful_attempt_id=1,
        completed_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    return VerifiedRunResult(
        result=resolved_run,
        plan=VerifiedRunPlan(
            run=run,
            experiment=ExperimentSpec.model_construct(
                experiment_id="inspection",
                factors=(),
                variant_ids=("baseline",),
                replicates=(),
                metrics=(),
            ),
            variant=VariantSpec.model_construct(
                experiment_id="inspection",
                variant_id="baseline",
                levels={},
                stage_params=(),
            ),
            benchmark=None,
            stages={run.stages[0].stage_id: stage},
        ),
        attempts=(),
        resolved_stages={},
        measurements=(),
    )


def test_plan_diff_compares_run_and_stage_values(tmp_path: Path) -> None:
    """Return one stable leaf change when the global seed differs."""
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left = _write_plan(left_root, seed=42)
    right = _write_plan(right_root, seed=43)

    result = plan_diff(left_root, left, right_root, right)

    assert result.identical is False
    assert tuple(change.path for change in result.changes) == ("run.seed",)
    assert result.changes[0].left == 42
    assert result.changes[0].right == 43


def test_plan_diff_rejects_stage_bytes_outside_run_spec(tmp_path: Path) -> None:
    """Reject a stage file whose bytes differ from its frozen reference."""
    run_path = _write_plan(tmp_path, seed=42)
    stage_path = tmp_path / RUN_ROOT / "stages/download/spec.yaml"
    stage_path.write_bytes(stage_path.read_bytes() + b"\n")

    try:
        plan_diff(tmp_path, run_path, tmp_path, run_path)
    except InspectionError as exc:
        assert "byte count" in str(exc)
    else:
        raise AssertionError("tampered stage spec was accepted")


def test_lineage_returns_stable_stage_and_artifact_edges(tmp_path: Path) -> None:
    """Represent each declared artifact as an output of its verified stage."""
    run_path = _write_plan(tmp_path, seed=42)
    verified = _verified_result(tmp_path, run_path)

    result = lineage(verified)

    assert result.run_id == RUN_ID
    assert tuple(node.node_id for node in result.nodes) == (
        "artifact:download:dataset",
        "artifact:download:split",
        "stage:download",
    )
    assert tuple((edge.source, edge.target) for edge in result.edges) == (
        ("stage:download", "artifact:download:dataset"),
        ("stage:download", "artifact:download:split"),
    )


def test_attempt_status_returns_latest_state_and_valid_successors(
    tmp_path: Path,
) -> None:
    """Report the durable state and transitions available from that state."""
    journal_path = tmp_path / "control" / "journal.jsonl"
    journal = DurableJournal(journal_path)
    now = datetime(2026, 8, 22, tzinfo=UTC)
    journal.append("allocated", "attempt allocated", recorded_at=now)
    journal.append("preflighting", "preflight passed", recorded_at=now)

    result = attempt_status(journal_path)

    assert result.entry_count == 2
    assert result.state == "preflighting"
    assert result.event == "preflight passed"
    assert result.next_states == ("running_stage", "terminal")
    assert result.terminal is False


def test_compare_runs_reports_verified_evidence_changes(tmp_path: Path) -> None:
    """Return the exact connected-evidence change between two verified runs."""
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left = _verified_result(left_root, _write_plan(left_root, seed=42))
    right = _verified_result(right_root, _write_plan(right_root, seed=43))

    result = compare_runs(left, right)

    assert result.identical is False
    assert tuple(change.path for change in result.changes) == ("run_spec.seed",)
    assert result.changes[0].left == 42
    assert result.changes[0].right == 43


def _catalog_source(verified: VerifiedRunResult) -> CatalogRunSource:
    """Bind the verified terminal document to its exact immutable reference."""
    raw = serialize_document(verified.result)
    reference = ResolvedRunRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=GitFileRef.model_validate(
            {
                "repository": "https://github.com/example/project",
                "commit": COMMIT,
                "path": f"{RUN_ROOT}/resolved.yaml",
            }
        ),
    )
    return CatalogRunSource(reference=reference, verified=verified)


def test_catalog_refresh_is_atomic_and_rebuildable(
    tmp_path: Path,
) -> None:
    """Replace the index atomically and retain each run's immutable source."""
    root = tmp_path / "project"
    run_path = _write_plan(root, seed=42)
    source = _catalog_source(_verified_result(root, run_path))
    index = Catalog(root)

    first = index.refresh(runs=(source,))
    page = index.runs()
    assert first.accepted == 1
    assert first.rejected == 0
    assert page.items[0].run == source.reference

    reader = sqlite3.connect(first.database)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
        second = index.refresh(runs=(source,))
        assert reader.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
    finally:
        reader.close()
    assert second.sha256 == first.sha256

    first.database.unlink()
    rebuilt = index.refresh(runs=(source,))
    assert rebuilt.sha256 == first.sha256
    assert index.runs() == page

    invalid = CatalogRunSource(
        reference=source.reference.model_copy(update={"sha256": "c" * 64}),
        verified=source.verified,
    )
    rejected = index.refresh(runs=(invalid,))
    assert rejected.accepted == 0
    assert rejected.rejected == 1
    assert index.runs().items == ()


def test_catalog_results_retain_immutable_sources(tmp_path: Path) -> None:
    """Page stable rows and reject a cursor reused with different filters."""
    root = tmp_path / "project"
    run_path = _write_plan(root, seed=42)
    first_verified = _verified_result(root, run_path)
    first = _catalog_source(first_verified)
    second_verified = replace(
        first_verified,
        result=first_verified.result.model_copy(
            update={
                "completed_at": first_verified.result.completed_at
                + timedelta(minutes=1)
            }
        ),
        plan=replace(
            first_verified.plan,
            run=first_verified.plan.run.model_copy(
                update={
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                    "variant_id": "candidate",
                }
            ),
        ),
    )
    second = _catalog_source(second_verified)
    index = Catalog(root)
    index.refresh(runs=(second, first))

    page = index.runs(RunQuery(limit=1))
    assert tuple(item.run_id for item in page.items) == (RUN_ID,)
    assert page.next_cursor is not None
    next_page = index.runs(RunQuery(limit=1, cursor=page.next_cursor))
    assert tuple(item.run_id for item in next_page.items) == (
        "01ARZ3NDEKTSV4RRFFQ69G5FAW",
    )
    assert tuple(
        item.variant_id
        for item in index.runs(RunQuery(variant_ids=("candidate",))).items
    ) == ("candidate",)

    try:
        index.runs(RunQuery(statuses=("succeeded",), cursor=page.next_cursor))
    except ValueError as error:
        assert "another query" in str(error)
    else:
        raise AssertionError("a cursor was accepted under different filters")
