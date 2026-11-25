"""Check native workflow ownership, queued authoring and physical artifact access."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

import viper.execution as execution
import viper.execution._batch as batch
import viper.execution._materialization as materialization
import viper.execution._metric as metric_execution
from tests.test_authoring import _compiled_plan
from tests.test_verification_acceptance import build_complete_fixture, fetch_attempt
from viper._cloud import (
    GcsRepository,
    SnapshotInventory,
    SnapshotSources,
    manifest_revision,
)
from viper._offload import current_session, load_operation
from viper._source import RunFetcher
from viper._storage_locks import PayloadLocks
from viper.artifacts import (
    ArtifactPointer,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from viper.authoring import freeze_run_plan
from viper.cloud import PublicationTarget, ViperCloud
from viper.evidence import (
    VerificationError,
    VerificationPolicy,
    VerifiedProducerRun,
    VerifiedRunPlan,
)
from viper.execution.errors import RunError
from viper.execution.results import RunResult
from viper.experiments import ExperimentSpec, VariantSpec
from viper.metrics import MetricVerificationReceipt
from viper.outputs import OutputSpec
from viper.references import (
    FileIdentity,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
    SnapshotFileRef,
    storage_file,
)
from viper.runs import ResolvedRun, RunAttempt, RunSpec
from viper.serialization import parse_yaml_bytes
from viper.stages import InternalSpec, ResolvedInternalSpec, TrainSpec
from viper.storage import (
    LocalArtifactStore,
    LocalSnapshotPublisher,
    ViperCloudDestination,
    publication_status,
    workflow,
)


@pytest.fixture(autouse=True)
def no_detached_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep all publication work inside the isolated test process."""
    monkeypatch.setattr(
        "viper._offload.start_publication_worker", lambda *args, **kwargs: None
    )


def _workspace(root: Path) -> None:
    """Create the local settings needed by a workflow."""
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")


def _result(root: Path, operation: Path) -> RunResult:
    """Supply a terminal result to tests of runner ownership."""
    return RunResult.model_construct(
        record=ResolvedRun.model_construct(status="succeeded"),
        reference=ResolvedRunRef.model_construct(),
        path=root / "resolved.yaml",
        journal_path=root / "journal.jsonl",
        latest_attempt=RunAttempt.model_construct(),
        publication_path=operation,
    )


def test_native_freeze_admits_plan_without_constructing_cloud_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue the original plan while its cloud destination is unavailable."""
    _, draft = _compiled_plan(tmp_path)
    forbidden = Mock(
        side_effect=AssertionError("foreground constructed a cloud client")
    )
    monkeypatch.setattr(ViperCloud, "for_target", forbidden)
    target = PublicationTarget(
        repository=GcsRepository(bucket="test-bucket"),
        destination=ViperCloudDestination(owner="owner", workspace="models"),
    )
    with workflow(tmp_path, targets=(target,)) as owner:
        frozen = freeze_run_plan(tmp_path, draft)
        assert isinstance(frozen.reference.stored_at, LocalFileRef)
        assert frozen.publication_path == owner.operation_path
        assert current_session() is owner
        assert not load_operation(owner.operation_path).closed
        assert publication_status(owner.operation_path).status == "pending"
    assert load_operation(owner.operation_path).closed
    assert publication_status(owner.operation_path).status == "pending"
    forbidden.assert_not_called()


def test_child_completion_does_not_close_parent_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the outer owner across several native calls."""
    _workspace(tmp_path)
    observed = []

    def run(root: Path, path: Path, **kwargs: Any) -> RunResult:
        owner = kwargs["_session"]
        assert current_session() is owner
        observed.append(owner.operation_path)
        return _result(root, owner.operation_path)

    monkeypatch.setattr(execution, "_run", run)
    monkeypatch.setattr(execution, "resolve_root", lambda root: root)
    with workflow(tmp_path) as owner:
        first = execution.run(Path("first.yaml"), repository_root=tmp_path)
        second = execution.run(Path("second.yaml"), repository_root=tmp_path)
        assert first.publication_path == second.publication_path == owner.operation_path
        assert not load_operation(owner.operation_path).closed
    assert observed == [owner.operation_path, owner.operation_path]
    assert load_operation(owner.operation_path).closed


def test_failed_batch_does_not_authorize_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record returned batch failures even though the batch itself returns normally."""
    _workspace(tmp_path)
    spec = RunSpec.model_construct(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", variant_id="baseline", replicate_id="r1"
    )
    monkeypatch.setattr(batch, "_load_run_spec", lambda root, path: (root / path, spec))
    monkeypatch.setattr(batch, "enroll_plan_inputs", lambda *args, **kwargs: None)

    def fail(*args: Any, **kwargs: Any) -> RunResult:
        raise RunError("scientific run failed")

    monkeypatch.setattr(batch, "execute_run", fail)
    with workflow(tmp_path) as owner:
        result = batch.run_many(tmp_path, (Path("failed.yaml"),), _session=owner)
        assert result.runs[0].status == "failed"
        assert result.publication_path == owner.operation_path
        assert not load_operation(owner.operation_path).closed
    assert not load_operation(owner.operation_path).science_succeeded


def test_queued_input_is_held_before_its_consumer_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protect all admitted inputs before submitting any worker thread."""
    _workspace(tmp_path)
    specs = tuple(
        RunSpec.model_construct(run_id=run_id, variant_id="baseline", replicate_id="r1")
        for run_id in ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FAW")
    )
    identities = tuple(
        FileIdentity(sha256=hashlib.sha256(bytes([index])).hexdigest(), bytes=1)
        for index in range(2)
    )
    admitted = []
    monkeypatch.setattr(
        batch, "_load_run_spec", lambda root, path: (root / path, specs[int(path.stem)])
    )

    with workflow(tmp_path) as owner:

        def admit(root: Path, spec: RunSpec) -> None:
            index = specs.index(spec)
            owner.hold(identities[index])
            admitted.append(spec.run_id)

        def consume(root: Path, path: Path, **kwargs: Any) -> RunResult:
            assert kwargs["_session"] is owner
            assert len(admitted) == 2
            with workflow(root, session=kwargs["_session"]):
                assert current_session() is owner
                for identity in identities:
                    with PayloadLocks(root).exclusive(identity) as acquired:
                        assert not acquired
            return _result(root, owner.operation_path)

        monkeypatch.setattr(batch, "enroll_plan_inputs", admit)
        monkeypatch.setattr(batch, "execute_run", consume)
        result = batch.run_many(
            tmp_path,
            (Path("0.yaml"), Path("1.yaml")),
            max_concurrency=2,
            _session=owner,
        )
        assert all(entry.status == "succeeded" for entry in result.runs)
        assert not load_operation(owner.operation_path).closed


def test_post_stage_metrics_receive_the_actual_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the original output in both independent metric worker invocations."""
    record, documents, _ = build_complete_fixture()
    attempt = fetch_attempt(documents, record.attempts[0])
    template = MetricVerificationReceipt.model_validate(
        parse_yaml_bytes(
            documents.fetch(attempt.metric_verification_files[0].stored_at)
        )
    )
    run = RunSpec.model_validate(
        parse_yaml_bytes(documents.fetch(record.spec.stored_at))
    )
    experiment = ExperimentSpec.model_validate(
        parse_yaml_bytes(
            documents.fetch(
                storage_file(
                    record.spec.stored_at, f"experiments/{run.experiment_id}/spec.yaml"
                )
            )
        )
    )
    selected = next(
        metric
        for metric in experiment.metrics
        if metric.metric_id == template.metric_id
    )
    stage = InternalSpec.model_construct(metric_ids=(selected.metric_id,), inputs={})
    resolved = ResolvedInternalSpec.model_construct()
    actual = tmp_path / ".viper/workspaces/output.bin"
    actual.parent.mkdir(parents=True)
    actual.write_bytes(b"original output")
    calls = []

    def execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        assert set(kwargs["artifact_paths"].values()) == {actual}
        assert actual.read_bytes() == b"original output"
        receipt = (
            template.production
            if kwargs["purpose"] == "measurement"
            else template.recomputation
        )
        return SimpleNamespace(receipt=receipt)

    monkeypatch.setattr(
        metric_execution,
        "_resolve_metric_dependencies",
        lambda *args: template.production.dependencies,
    )
    monkeypatch.setattr(metric_execution, "execute_metric_process", execute)
    names = {
        dependency.name: actual
        for dependency in selected.dependencies
        if dependency.source == "artifact"
    }
    inputs = {
        dependency.name: actual
        for dependency in selected.dependencies
        if dependency.source == "input"
    }
    measurement_paths = []
    verification_paths = []
    metric_execution.run_after_stage_metrics(
        tmp_path,
        run,
        template.stage_id,
        stage,
        resolved,
        attempt.resolved_stages[0],
        {},
        {},
        experiment,
        inputs,
        measurement_paths,
        verification_paths,
        None,
        attempt.attempt_id,
        artifact_paths=names,
    )
    assert [call["purpose"] for call in calls] == ["measurement", "verification"]
    assert len(measurement_paths) == len(verification_paths) == 1


def _reference_selection(
    root: Path, *, benchmarked: bool = False
) -> tuple[RunFetcher, ArtifactPointer, VerifiedProducerRun, SnapshotFileRef]:
    """Provide verified producer metadata whose selected payload is absent."""
    member = SnapshotFileRef(
        path="artifacts/model/weights.bin",
        sha256=hashlib.sha256(b"weights").hexdigest(),
        bytes=7,
    )
    resolved = SnapshotFileRef(
        path="stages/train/resolved.yaml", sha256="b" * 64, bytes=12
    )
    members = tuple(sorted((member, resolved), key=lambda file: file.path))
    snapshot = LocalStageResultSnapshotRef(
        workspace=root, commit=manifest_revision(members)
    )
    store = LocalArtifactStore(root)
    store.registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=snapshot, source_files=members)
        )
    )
    selected = StageArtifactRef(stage_id="train", artifact_name="model")
    run = RunSpec.model_construct(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        experiment_id="example",
        variant_id="baseline",
        benchmark_id="holdout" if benchmarked else None,
        estimator=selected,
    )
    spec = TrainSpec.model_construct(
        outputs={"model": OutputSpec.model_construct(data_role="training")}
    )
    artifact = ResolvedSingleFileArtifact(relative_path="weights.bin", file=member)
    stage = ResolvedStageRef(
        stage_id="train", snapshot=snapshot, resolved_spec=resolved
    )
    attempt = RunAttempt.model_construct(attempt_id=1, resolved_stages=(stage,))
    producer = VerifiedProducerRun(
        result=ResolvedRun.model_construct(successful_attempt_id=1),
        plan=VerifiedRunPlan(
            run=run,
            experiment=ExperimentSpec.model_construct(),
            variant=VariantSpec.model_construct(),
            benchmark=None,
            stages={"train": spec},
        ),
        attempts=(attempt,),
        resolved_stages={
            "train": ResolvedInternalSpec.model_construct(
                spec=spec, artifacts={"model": artifact}
            )
        },
    )
    run_reference = ResolvedRunRef(
        sha256="c" * 64,
        bytes=20,
        stored_at=LocalFileRef(
            workspace=root,
            commit="d" * 64,
            path=f"experiments/example/runs/baseline/{run.run_id}/resolved.yaml",
        ),
    )
    pointer = ArtifactPointer(run=run_reference, artifact=selected)
    return (
        RunFetcher(root, store, "https://example.com/project.git"),
        pointer,
        producer,
        member,
    )


def test_artifact_reference_returns_expected_identity_without_restoring_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Select the exact immutable member while its local payload remains absent."""
    _workspace(tmp_path)
    fetcher, pointer, producer, member = _reference_selection(tmp_path)
    policy = VerificationPolicy(trusted_source_repositories=frozenset())
    monkeypatch.setattr(
        materialization,
        "_artifact_producer",
        lambda *args: (fetcher, policy, pointer, producer),
    )
    forbidden = Mock(
        side_effect=AssertionError("reference selection materialized a payload")
    )
    monkeypatch.setattr(fetcher, "path", forbidden)
    reference = execution.artifact_reference(
        tmp_path, pointer.run, pointer.artifact, member="old-filename-hint.bin"
    )
    assert reference.sha256 == member.sha256
    assert reference.bytes == member.bytes
    assert reference.stored_at.path == member.path
    forbidden.assert_not_called()
    assert not (tmp_path / ".viper/store/objects").exists()


def test_reference_selection_keeps_the_benchmark_estimator_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require benchmark evidence before selecting a benchmarked estimator."""
    _workspace(tmp_path)
    fetcher, pointer, producer, _ = _reference_selection(tmp_path, benchmarked=True)
    monkeypatch.setattr(
        materialization,
        "_artifact_producer",
        lambda *args: (
            fetcher,
            VerificationPolicy(trusted_source_repositories=frozenset()),
            pointer,
            producer,
        ),
    )
    with pytest.raises(VerificationError, match="requires a benchmark result"):
        execution.artifact_reference(tmp_path, pointer.run, pointer.artifact)


def test_artifact_path_requires_a_tracked_workflow(tmp_path: Path) -> None:
    """Prevent an owning helper from evicting a path before its caller uses it."""
    _workspace(tmp_path)
    _, pointer, _, _ = _reference_selection(tmp_path)
    with pytest.raises(ValueError, match="active storage.workflow"):
        execution.artifact_path(tmp_path, pointer.run, pointer.artifact)


def test_native_reuse_keeps_the_existing_original_without_another_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse an owned checkpoint path while storing only the new stage record."""
    _workspace(tmp_path)
    original = tmp_path / "checkpoint.pt"
    raw = b"checkpoint" * 104_858
    original.write_bytes(raw)
    publisher = LocalSnapshotPublisher(tmp_path)
    with workflow(tmp_path):
        commit, members = publisher.store._publish(
            {"old/model.pt": original}, path_custody="output"
        )
        source = LocalStageResultSnapshotRef(workspace=tmp_path, commit=commit)
        write = type(publisher.store._objects).write

        def store_metadata(cache, reference: ResolvedFileRef, content: bytes) -> None:
            assert content != raw, "reuse wrote another checkpoint payload"
            write(cache, reference, content)

        monkeypatch.setattr(type(publisher.store._objects), "write", store_metadata)
        reused = publisher.publish_reuse(
            resolved_stage_path="new/resolved.yaml",
            resolved_stage=b"stage metadata",
            source_snapshot=source,
            files={"new/model.pt": members[0]},
            source_bytes={"new/model.pt": original},
        )
        record = publisher.store.registry.snapshot(reused)
        assert record is not None
        assert record.locations["new/model.pt"][0].path == "checkpoint.pt"
        assert (
            publisher.store.path(
                LocalFileRef(**reused.model_dump(exclude={"kind"}), path="new/model.pt")
            )
            == original
        )
        assert original.read_bytes() == raw
