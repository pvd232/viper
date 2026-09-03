"""Tests for repository-local immutable output publication."""

from pathlib import Path

import pytest

from viper.references import LocalFileRef, LocalStageResultSnapshotRef
from viper.storage import (
    LocalArtifactStore,
    LocalSnapshotPublisher,
    LocalStorageDestination,
    LocalStoreError,
    StorageConfigurationError,
    StorageSettings,
    ViperCloudDestination,
    bind_run_destination,
    create_snapshot_publisher,
    load_storage_settings,
    publish_resolved_files,
)

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_storage_publishes_and_retrieves_one_content_revision(
    tmp_path: Path,
) -> None:
    """Verify stable revision identity and exact retrieval for related files."""
    store = LocalArtifactStore(tmp_path)
    files = {
        "experiments/example/artifacts/parameters.bin": b"parameters",
        "experiments/example/logs/1.train.stdout.log": b"complete\n",
    }

    first_commit = store.publish(files)
    second_commit = store.publish(files)

    assert first_commit == second_commit
    assert (
        store.fetch(
            LocalFileRef(
                commit=first_commit,
                path="experiments/example/artifacts/parameters.bin",
            )
        )
        == b"parameters"
    )


def test_storage_resolved_files_share_one_revision(tmp_path: Path) -> None:
    """Verify a related publication yields exact references in one revision."""
    store = LocalArtifactStore(tmp_path)
    references = store.resolved_files(
        {
            "experiments/example/logs/1.train.stdout.log": b"out",
            "experiments/example/logs/1.train.stderr.log": b"err",
        }
    )

    commits = {reference.stored_at.commit for reference in references}
    assert len(commits) == 1
    assert all(store.fetch(reference.stored_at) for reference in references)


def test_store_uses_selected_project_root(tmp_path: Path) -> None:
    """Keep immutable bytes beneath the selected root after a working edit."""
    root = tmp_path / "project"
    root.mkdir()
    source = root / "artifacts" / "model.bin"
    source.parent.mkdir()
    source.write_bytes(b"original")
    store = LocalArtifactStore(root)
    reference = store.resolved_files({"artifacts/model.bin": source.read_bytes()})[0]
    source.write_bytes(b"changed")
    assert store.store_root == root / ".viper" / "store"
    assert store.fetch(reference.stored_at) == b"original"
    with pytest.raises(LocalStoreError):
        LocalArtifactStore(root, "../escape")


def test_storage_settings_parse_local_and_cloud_destinations(tmp_path: Path) -> None:
    """Parse the two destination forms and preserve their closed model shape."""
    marker = tmp_path / "viper.toml"
    marker.write_text("[project]\nschema_version = 1\n", encoding="utf-8")

    local = load_storage_settings(tmp_path)
    assert local == StorageSettings(destination=LocalStorageDestination())
    assert StorageSettings.model_validate_json(local.model_dump_json()) == local

    marker.write_text(
        "[project]\nschema_version = 1\n"
        '[storage]\ndestination = "viper://machina/weekend_models"\n',
        encoding="utf-8",
    )
    cloud = load_storage_settings(tmp_path)
    assert cloud.destination == ViperCloudDestination(
        owner="machina",
        project="weekend_models",
    )
    assert StorageSettings.model_validate_json(cloud.model_dump_json()) == cloud

    marker.write_text(
        "[project]\nschema_version = 1\n"
        '[storage]\ndestination = "https://example.com/project"\n',
        encoding="utf-8",
    )
    with pytest.raises(StorageConfigurationError, match="destination is invalid"):
        load_storage_settings(tmp_path)


def test_local_publishers_share_destination_neutral_interface(
    tmp_path: Path,
) -> None:
    """Publish stage and standalone bytes through the local destination boundary."""
    marker = tmp_path / "viper.toml"
    marker.write_text("[project]\nschema_version = 1\n", encoding="utf-8")
    artifact = tmp_path / "artifacts" / "model.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"parameters")
    destination = LocalStorageDestination()

    publisher = create_snapshot_publisher(tmp_path, destination)
    assert isinstance(publisher, LocalSnapshotPublisher)
    snapshot = publisher.publish(
        resolved_stage_path="runs/example/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\n",
        files={"artifacts/model.bin": artifact},
    )
    assert isinstance(snapshot, LocalStageResultSnapshotRef)
    store = LocalArtifactStore(tmp_path)
    assert set(store.list_snapshot_files(snapshot)) == {
        "artifacts/model.bin",
        "runs/example/stages/train/resolved.yaml",
    }

    references = publish_resolved_files(
        tmp_path,
        destination,
        {
            "runs/example/journal.jsonl": b'{"state":"terminal"}\n',
            "artifacts/model.bin": artifact,
        },
    )
    assert set(references) == {
        "artifacts/model.bin",
        "runs/example/journal.jsonl",
    }
    assert store.fetch(references["artifacts/model.bin"].stored_at) == b"parameters"


def test_bind_run_destination_is_idempotent_and_rejects_change(
    tmp_path: Path,
) -> None:
    """Persist the first run destination and reject a later different value."""
    (tmp_path / "viper.toml").write_text(
        "[project]\nschema_version = 1\n",
        encoding="utf-8",
    )
    local = LocalStorageDestination()

    assert bind_run_destination(tmp_path, RUN_ID, local) == local
    assert bind_run_destination(tmp_path, RUN_ID, local) == local
    destination_path = (
        tmp_path / ".viper" / "workspaces" / RUN_ID / "storage-destination.json"
    )
    assert destination_path.read_bytes() == b'{"kind":"local"}\n'

    with pytest.raises(StorageConfigurationError, match="storage_destination_changed"):
        bind_run_destination(
            tmp_path,
            RUN_ID,
            ViperCloudDestination(owner="machina", project="weekend_models"),
        )
