"""Verify prior-run artifact pointers created during plan compilation."""

import hashlib
from pathlib import Path

import pytest

from tests.test_storage import InMemoryViperCloudClient
from viper._verification.storage import fetch_local_file_bytes
from viper.artifacts import ArtifactPointer, StageArtifactRef
from viper.authoring import RunArtifactDraft, _freeze_input
from viper.execution._source import RunFetcher
from viper.inputs import StoredInputRef
from viper.references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedRunRef,
    ViperCloudFileRef,
)
from viper.serialization import parse_yaml_bytes
from viper.storage import LocalArtifactStore, ViperCloudDestination


def _publish_run(root: Path, path: str, raw: bytes = b"resolved run") -> ResolvedRunRef:
    """Publish one terminal document and return its bound local reference."""
    reference = LocalArtifactStore(root).resolved_files({path: raw})[0]
    return ResolvedRunRef.model_validate(reference.model_dump(mode="python"))


def test_prior_run_input_publishes_verified_pointer(tmp_path) -> None:
    """Publish one exact pointer for a selected prior-run artifact."""
    run = _publish_run(
        tmp_path,
        "experiments/source/runs/base/run/resolved.yaml",
    )
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )

    frozen = _freeze_input(tmp_path, {}, draft)

    assert isinstance(frozen, StoredInputRef)
    assert isinstance(frozen.pointer, ResolvedArtifactPointerRef)
    raw = LocalArtifactStore(tmp_path).fetch(frozen.pointer.stored_at)
    assert len(raw) == frozen.pointer.bytes
    assert hashlib.sha256(raw).hexdigest() == frozen.pointer.sha256
    assert ArtifactPointer.model_validate(parse_yaml_bytes(raw)) == ArtifactPointer(
        run=run,
        artifact=draft.artifact,
    )
    assert frozen.pointer.stored_at.path == (
        f".viper/pointers/{run.sha256}/download/dataset.pointer.yaml"
    )


def test_prior_run_pointer_uses_the_selected_cloud_destination(tmp_path) -> None:
    """Publish a generated pointer directly to the bound cloud project."""
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=ViperCloudFileRef(
            owner="machina",
            workspace="source_models",
            revision="b" * 64,
            path="experiments/source/runs/base/run/resolved.yaml",
        ),
    )
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )
    destination = ViperCloudDestination(owner="machina", workspace="weekend_models")
    client = InMemoryViperCloudClient()

    frozen = _freeze_input(
        tmp_path,
        {},
        draft,
        destination=destination,
        cloud_client=client,
    )

    assert isinstance(frozen, StoredInputRef)
    pointer = frozen.pointer
    assert isinstance(pointer, ResolvedArtifactPointerRef)
    assert isinstance(pointer.stored_at, ViperCloudFileRef)
    assert pointer.stored_at.owner == destination.owner
    assert pointer.stored_at.workspace == destination.workspace


def test_cloud_pointer_rejects_a_local_producer(tmp_path) -> None:
    """Stop before publishing a pointer that cannot work off-machine."""
    draft = RunArtifactDraft(
        run=ResolvedRunRef(
            sha256="a" * 64,
            bytes=10,
            stored_at=LocalFileRef(
                workspace=tmp_path,
                store_id="0" * 32,
                commit="b" * 64,
                path="experiments/source/runs/base/run/resolved.yaml",
            ),
        ),
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )

    with pytest.raises(ValueError, match="storage_graph_unreachable"):
        _freeze_input(
            tmp_path,
            {},
            draft,
            destination=ViperCloudDestination(
                owner="machina",
                workspace="weekend_models",
            ),
            cloud_client=InMemoryViperCloudClient(),
        )


def test_local_pointer_accepts_a_run_from_another_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a cross-workspace pointer connected to its producer store."""
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    run = _publish_run(producer, "runs/source/resolved.yaml")
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="build", artifact_name="dataset"),
        path="inputs/dataset.bin",
        data_role="training",
    )

    stored = _freeze_input(consumer, {}, draft)

    assert isinstance(run.stored_at, LocalFileRef)
    assert isinstance(stored, StoredInputRef)
    assert isinstance(stored.pointer, ResolvedArtifactPointerRef)
    assert isinstance(stored.pointer.stored_at, LocalFileRef)
    assert (
        RunFetcher(
            consumer,
            LocalArtifactStore(consumer),
            "",
        )(run.stored_at)
        == b"resolved run"
    )
    assert stored.pointer.stored_at.workspace == consumer
    pointer_raw = LocalArtifactStore(consumer).fetch(stored.pointer.stored_at)
    assert ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw)).run == run
    monkeypatch.chdir(consumer)
    assert fetch_local_file_bytes(run.stored_at) == b"resolved run"


def test_local_pointer_rejects_an_unknown_producer_store(tmp_path) -> None:
    """Reject a producer reference whose durable store identity does not match."""
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    run = _publish_run(producer, "runs/source/resolved.yaml")
    assert isinstance(run.stored_at, LocalFileRef)
    producer_store_id = run.stored_at.store_id
    unknown_store_id = (
        "1" if producer_store_id[0] != "1" else "2"
    ) + producer_store_id[1:]
    run = run.model_copy(
        update={
            "stored_at": run.stored_at.model_copy(update={"store_id": unknown_store_id})
        }
    )
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="build", artifact_name="dataset"),
        path="inputs/dataset.bin",
        data_role="training",
    )

    with pytest.raises(ValueError, match="storage_graph_unreachable"):
        _freeze_input(consumer, {}, draft)

    assert not (consumer / ".viper/pointers").exists()
