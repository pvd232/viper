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
from viper.knowledge import (
    AssignmentQuery,
    DeclaredPrimitiveAssignment,
    DiagnosticComponent,
    DiagnosticSignature,
    DiagnosticVectorView,
    KnowledgeVector,
    OntologySpec,
    PrimitiveQuery,
    PrimitiveRef,
    PrimitiveSpec,
    RetrievalJudgment,
    RetrievalJudgmentQuery,
    RunKnowledgeTarget,
    SimilarityQuery,
    diagnostic_component_sha256,
    knowledge,
)
from viper.references import (
    GitFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
from viper.reuse import (
    ReusedStageFile,
    StageReuseCandidate,
    StageReuseKey,
    StageReuseReceipt,
    stage_reuse_key_sha256,
)
from viper.runs import (
    ResolvedAttemptRef,
    ResolvedRun,
    RunSpec,
)
from viper.serialization import (
    document_digest,
    load_stage_spec,
    parse_yaml_bytes,
    serialize_document,
)
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


def _reuse_receipt() -> StageReuseReceipt:
    """Build one valid reuse receipt for inspection tests."""
    resolved_file = SnapshotFileRef(
        path=f"{RUN_ROOT}/artifacts/datasets/toy/dataset.bin",
        sha256="c" * 64,
        bytes=1,
    )
    return StageReuseReceipt(
        stage_id="download",
        key=StageReuseKey(
            stage_id="download",
            stage_sha256="d" * 64,
            inputs=(),
            seed=42,
            env_sha256="e" * 64,
            reproducibility_sha256="f" * 64,
            metric_sha256s=(),
        ),
        source_run=ResolvedRunRef(
            sha256="1" * 64,
            bytes=1,
            stored_at=LocalFileRef(
                commit="2" * 64,
                path=f"{RUN_ROOT}/resolved.yaml",
            ),
        ),
        source_attempt=ResolvedAttemptRef(
            sha256="3" * 64,
            bytes=1,
            stored_at=LocalFileRef(
                commit="4" * 64,
                path=f"{RUN_ROOT}/attempts/1/resolved.yaml",
            ),
        ),
        source_stage=ResolvedStageRef(
            stage_id="download",
            snapshot=LocalStageResultSnapshotRef(commit="5" * 64),
            resolved_spec=SnapshotFileRef(
                path=f"{RUN_ROOT}/stages/download/resolved.yaml",
                sha256="6" * 64,
                bytes=1,
            ),
        ),
        files=(
            ReusedStageFile(
                artifact_name="dataset",
                source=resolved_file,
                target=resolved_file,
            ),
        ),
        metrics=(),
        completed_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def test_reuse_identity_appears_in_inspection_surfaces(tmp_path: Path) -> None:
    """Expose one verified reuse receipt in lineage and run comparison."""
    run_path = _write_plan(tmp_path, seed=42)
    verified = _verified_result(tmp_path, run_path)
    receipt = _reuse_receipt()
    reuse = {receipt.stage_id: receipt}

    result = lineage(verified, reuse=reuse)
    key_sha256 = document_digest(receipt.key)
    stage = next(node for node in result.nodes if node.node_id == "stage:download")
    source = next(node for node in result.nodes if node.kind == "source_run")
    assert stage.reuse_key_sha256 == key_sha256
    assert source.node_id == f"source-run:{receipt.source_run.sha256}"
    assert any(edge.relation == "reuses" for edge in result.edges)

    comparison = compare_runs(verified, verified, right_reuse=reuse)
    assert comparison.identical is False
    assert all(
        change.path == "stage_reuse" or change.path.startswith("stage_reuse.download")
        for change in comparison.changes
    )


def test_catalog_returns_an_exact_stage_reuse_candidate(tmp_path: Path) -> None:
    """Index one successful stage by its complete canonical reuse key."""
    root = tmp_path / "project"
    run_path = _write_plan(root, seed=42)
    source = _catalog_source(_verified_result(root, run_path))
    key = StageReuseKey(
        stage_id="download",
        stage_sha256="a" * 64,
        inputs=(),
        seed=source.verified.plan.run.seed,
        env_sha256="b" * 64,
        reproducibility_sha256="c" * 64,
        metric_sha256s=(),
    )
    candidate = StageReuseCandidate(
        key=key,
        source_run=source.reference,
        source_attempt=ResolvedAttemptRef(
            sha256="d" * 64,
            bytes=1,
            stored_at=LocalFileRef(commit="e" * 64, path="attempt.yaml"),
        ),
        attempt_id=1,
        source_stage=ResolvedStageRef(
            stage_id="download",
            snapshot=LocalStageResultSnapshotRef(commit="f" * 64),
            resolved_spec=SnapshotFileRef(
                path="resolved.yaml",
                sha256="0" * 64,
                bytes=1,
            ),
        ),
        completed_at=source.verified.result.completed_at,
    )
    catalog = Catalog(root)

    catalog.refresh(runs=(source,))
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "INSERT INTO stage_reuse_keys VALUES (?, ?, ?, ?, ?, ?)",
            (
                stage_reuse_key_sha256(key),
                "source",
                candidate.completed_at.isoformat(),
                RUN_ID,
                1,
                candidate.model_dump_json(),
            ),
        )

    assert catalog.reuse_candidate(key) == candidate
    assert catalog.reuse_candidate(key.model_copy(update={"seed": 43})) is None


def test_knowledge_retrieval_keeps_exact_indexes_authoritative(
    tmp_path: Path,
) -> None:
    """Filter exact records before ranking vectors inside one declared view."""
    (tmp_path / "viper.toml").write_text("[project]\nschema_version = 1\n")
    store = knowledge(root=tmp_path)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=created,
    )
    store.publish_ontology(ontology)
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="b" * 64, path="runs/final.yaml"),
    )
    assignment = DeclaredPrimitiveAssignment(
        target=RunKnowledgeTarget(run=run),
        primitive=PrimitiveRef(
            ontology_id=ontology.ontology_id,
            ontology_version=ontology.version,
            primitive_id=ontology.primitives[0].primitive_id,
        ),
        assigned_by="researcher",
        assigned_at=created,
    )
    store.publish_assignment(assignment)
    first_components = (
        DiagnosticComponent(
            metric_id="loss",
            measurement=ResolvedFileRef(
                sha256="c" * 64,
                bytes=10,
                stored_at=LocalFileRef(
                    commit="d" * 64,
                    path="measurements/first.json",
                ),
            ),
            value=1.0,
        ),
    )
    second_components = (
        DiagnosticComponent(
            metric_id="loss",
            measurement=ResolvedFileRef(
                sha256="e" * 64,
                bytes=10,
                stored_at=LocalFileRef(
                    commit="f" * 64,
                    path="measurements/second.json",
                ),
            ),
            value=2.0,
        ),
    )
    first_signature = store.publish_signature(
        DiagnosticSignature(
            run=run,
            stage_id="train",
            components=first_components,
            component_sha256=diagnostic_component_sha256(first_components),
            created_at=created,
        )
    )
    second_signature = store.publish_signature(
        DiagnosticSignature(
            run=run,
            stage_id="eval",
            components=second_components,
            component_sha256=diagnostic_component_sha256(second_components),
            created_at=created,
        )
    )
    view = DiagnosticVectorView(
        view_id="diagnostic-v1",
        version="1",
        metric_ids=("loss",),
        dimensions=1,
    )
    first = store.publish_vector(
        KnowledgeVector(
            view=view,
            source=first_signature.record,
            values=(1.0,),
            created_at=created,
        )
    )
    second = store.publish_vector(
        KnowledgeVector(
            view=view,
            source=second_signature.record,
            values=(-1.0,),
            created_at=created,
        )
    )
    store.publish_retrieval_judgment(
        RetrievalJudgment(
            query_vector=first.record,
            candidate_vector=second.record,
            aspects=("diagnostic",),
            relevance=2,
            reviewed_by="reviewer",
            reviewed_at=created,
        )
    )

    catalog = Catalog(tmp_path)
    catalog.refresh()
    records = catalog.knowledge
    primitive_page = records.primitives(
        PrimitiveQuery(primitive_ids=("gated-recurrence",))
    )
    assert tuple(item.label for item in primitive_page.items) == (
        "Gated recurrence",
    )
    assert records.assignments(
        AssignmentQuery(origins=("declared",))
    ).items[0].record.value == assignment

    similar = records.similar(
        SimilarityQuery(
            view_id=view.view_id,
            view_version=view.version,
            values=(1.0,),
        )
    )
    assert similar.items[0].vector == first.record
    assert similar.items[0].distance == 0.0
    judgments = records.retrieval_judgments(
        RetrievalJudgmentQuery(
            view_ids=(view.view_id,),
            minimum_relevance=2,
        )
    )
    assert len(judgments.items) == 1
    assert records.similar(
        SimilarityQuery(
            view_id="another-view",
            view_version="1",
            values=(1.0,),
        )
    ).items == ()
