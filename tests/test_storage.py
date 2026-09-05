"""Tests for repository-local immutable output publication."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from viper._schema import SHA256, RepoRelPath
from viper.execution._restore import (
    _PlannedFile,
    _restore_files,
)
from viper.execution._source import RunFetcher
from viper.execution.errors import RestoreError
from viper.ids import HumanId
from viper.references import (
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunSpecRef,
    SnapshotFileRef,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from viper.restoration import ArtifactRestoreSelector
from viper.runs import ResolvedAttemptRef, ResolvedRun
from viper.storage import (
    LocalArtifactStore,
    LocalSnapshotPublisher,
    LocalStorageDestination,
    LocalStoreError,
    PublicationSource,
    StorageConfigurationError,
    StorageSettings,
    ViperCloudClient,
    ViperCloudDestination,
    ViperCloudSnapshotPublisher,
    bind_run_destination,
    create_snapshot_publisher,
    load_storage_settings,
    publish_resolved_files,
)
from viper.verification import verify_run_result
from viper.verification.models import VerificationError, VerificationPolicy

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


class InMemoryViperCloudClient(ViperCloudClient):
    """Hold unsealed uploads separately from retrievable revisions."""

    def __init__(self, *, rejected_seals: int = 0) -> None:
        """Configure how many seal calls fail before the revision appears."""
        self.uploads: dict[tuple[str, str, str, str], bytes] = {}
        self.sealed: dict[tuple[str, str, str], tuple[SnapshotFileRef, ...]] = {}
        self.upload_calls: list[tuple[str, str, str, str]] = []
        self.copy_calls: list[tuple[ViperCloudFileRef, ViperCloudFileRef]] = []
        self.rejected_seals = rejected_seals
        self.seal_calls = 0

    def upload(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        source: PublicationSource,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Save an upload without making it retrievable."""
        raw = source.read_bytes() if isinstance(source, Path) else source
        assert len(raw) == bytes
        assert hashlib.sha256(raw).hexdigest() == sha256
        key = (owner, project, revision, path)
        self.upload_calls.append(key)
        existing = self.uploads.setdefault(key, raw)
        assert existing == raw

    def copy(
        self,
        *,
        source: ViperCloudFileRef,
        target: ViperCloudFileRef,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Reuse one sealed payload under a target revision and path."""
        assert (source.owner, source.project, source.revision) in self.sealed
        raw = self.uploads[(source.owner, source.project, source.revision, source.path)]
        assert len(raw) == bytes
        assert hashlib.sha256(raw).hexdigest() == sha256
        self.uploads[(target.owner, target.project, target.revision, target.path)] = raw
        self.copy_calls.append((source, target))

    def seal(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        files: tuple[SnapshotFileRef, ...],
    ) -> None:
        """Expose all uploaded files after the configured failures."""
        self.seal_calls += 1
        if self.seal_calls <= self.rejected_seals:
            raise RuntimeError("seal unavailable")
        self.sealed[(owner, project, revision)] = files

    def fetch(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        path: RepoRelPath,
    ) -> bytes:
        """Read a file only when its revision is sealed."""
        if (owner, project, revision) not in self.sealed:
            raise FileNotFoundError("revision is not sealed")
        return self.uploads[(owner, project, revision, path)]

    def list_files(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
    ) -> tuple[SnapshotFileRef, ...]:
        """List the files exposed by a sealed revision."""
        return self.sealed[(owner, project, revision)]


def test_cloud_publication_is_atomic_and_retryable(tmp_path: Path) -> None:
    """Expose cloud files only after sealing one deterministic revision."""
    artifact = tmp_path / "artifacts" / "model.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"parameters")
    destination = ViperCloudDestination(owner="machina", project="weekend_models")
    client = InMemoryViperCloudClient(rejected_seals=1)

    publisher = create_snapshot_publisher(
        tmp_path,
        destination,
        cloud_client=client,
    )
    assert isinstance(publisher, ViperCloudSnapshotPublisher)
    snapshot = publisher.publish(
        resolved_stage_path="runs/example/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\n",
        files={"artifacts/model.bin": artifact},
    )

    assert isinstance(snapshot, ViperCloudStageResultSnapshotRef)
    assert client.seal_calls == 2
    listed = client.list_files(
        owner=snapshot.owner,
        project=snapshot.project,
        revision=snapshot.revision,
    )
    assert tuple(file.path for file in listed) == (
        "artifacts/model.bin",
        "runs/example/stages/train/resolved.yaml",
    )
    assert listed[0].sha256 == hashlib.sha256(b"parameters").hexdigest()
    assert listed[0].bytes == len(b"parameters")

    references = publish_resolved_files(
        tmp_path,
        destination,
        {"runs/example/journal.jsonl": b'{"state":"terminal"}\n'},
        cloud_client=client,
    )
    location = references["runs/example/journal.jsonl"].stored_at
    assert isinstance(location, ViperCloudFileRef)
    assert (
        client.fetch(
            owner=location.owner,
            project=location.project,
            revision=location.revision,
            path=location.path,
        )
        == b'{"state":"terminal"}\n'
    )


def test_cloud_fetcher_retrieves_the_selected_sealed_file(tmp_path: Path) -> None:
    """Retrieve a cloud file through the same fetcher used by verification."""
    client = InMemoryViperCloudClient()
    raw = b"evidence"
    location = ViperCloudFileRef(
        owner="machina",
        project="weekend_models",
        revision="0" * 64,
        path="runs/example/evidence.yaml",
    )
    client.upload(
        owner=location.owner,
        project=location.project,
        revision=location.revision,
        path=location.path,
        source=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
    client.seal(
        owner=location.owner,
        project=location.project,
        revision=location.revision,
        files=(),
    )
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.com/source.git",
        cloud_client=client,
    )

    assert fetcher(location) == raw


def test_cloud_verification_rejects_local_references() -> None:
    """Reject a cloud terminal graph that still reaches local evidence."""
    resolved_run = ResolvedRun.model_construct(
        spec=ResolvedRunSpecRef.model_construct(
            stored_at=ViperCloudFileRef(
                owner="machina",
                project="weekend_models",
                revision="0" * 64,
                path="runs/example/spec.yaml",
            )
        ),
        status="succeeded",
        attempts=(
            ResolvedAttemptRef.model_construct(
                stored_at=LocalFileRef(
                    commit="1" * 64,
                    path="runs/example/attempt.yaml",
                )
            ),
        ),
        successful_attempt_id=1,
        completed_at=datetime.now(UTC),
    )

    with pytest.raises(VerificationError, match="storage_graph_unreachable"):
        verify_run_result(
            resolved_run,
            policy=VerificationPolicy(trusted_source_repositories=frozenset()),
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

    locations = tuple(reference.stored_at for reference in references)
    local_locations = tuple(
        location for location in locations if isinstance(location, LocalFileRef)
    )
    assert len(local_locations) == len(locations)
    commits = {location.commit for location in local_locations}
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


def test_restore_verifies_before_atomic_write(tmp_path: Path) -> None:
    """Leave every destination untouched when one selected file conflicts."""
    selector = ArtifactRestoreSelector(stage_id="train", artifact_name="model")
    first = b"first"
    second = b"second"
    references = (
        ResolvedFileRef(
            sha256=hashlib.sha256(first).hexdigest(),
            bytes=len(first),
            stored_at=LocalFileRef(commit="a" * 64, path="artifacts/first.bin"),
        ),
        ResolvedFileRef(
            sha256=hashlib.sha256(second).hexdigest(),
            bytes=len(second),
            stored_at=LocalFileRef(commit="a" * 64, path="artifacts/second.bin"),
        ),
    )
    first_destination = tmp_path / "restored/first.bin"
    second_destination = tmp_path / "restored/second.bin"
    second_destination.parent.mkdir()
    second_destination.write_bytes(b"occupied")
    planned = tuple(
        _PlannedFile(
            selector=selector,
            reference=reference,
            destination=destination,
        )
        for reference, destination in zip(
            references,
            (first_destination, second_destination),
            strict=True,
        )
    )
    payloads = {
        "artifacts/first.bin": first,
        "artifacts/second.bin": second,
    }

    with pytest.raises(RestoreError, match="different bytes"):
        _restore_files(
            lambda location: payloads[location.path],
            planned,
        )

    assert not first_destination.exists()
    assert second_destination.read_bytes() == b"occupied"
def test_local_snapshot_reuse_remaps_source_files(tmp_path: Path) -> None:
    """Publish verified local bytes under the target run's artifact paths."""
    source_artifact = tmp_path / "source" / "model.bin"
    source_artifact.parent.mkdir()
    source_artifact.write_bytes(b"parameters")
    publisher = LocalSnapshotPublisher(tmp_path)
    source_snapshot = publisher.publish(
        resolved_stage_path="runs/source/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\n",
        files={"runs/source/artifacts/model.bin": source_artifact},
    )
    source_file = SnapshotFileRef(
        path="runs/source/artifacts/model.bin",
        sha256=hashlib.sha256(b"parameters").hexdigest(),
        bytes=len(b"parameters"),
    )

    target_snapshot = publisher.publish_reuse(
        resolved_stage_path="runs/target/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\ncompletion: reused\n",
        source_snapshot=source_snapshot,
        files={"runs/target/artifacts/model.bin": source_file},
        source_bytes={"runs/target/artifacts/model.bin": b"parameters"},
    )

    store = LocalArtifactStore(tmp_path)
    assert store.list_snapshot_files(target_snapshot) == (
        "runs/target/artifacts/model.bin",
        "runs/target/stages/train/resolved.yaml",
    )
    assert (
        store.fetch(
            LocalFileRef(
                commit=target_snapshot.commit,
                path="runs/target/artifacts/model.bin",
            )
        )
        == b"parameters"
    )

def test_cloud_snapshot_reuse_copies_existing_payload(tmp_path: Path) -> None:
    """Copy a sealed cloud payload and upload only the target stage document."""
    artifact = tmp_path / "source" / "model.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"parameters")
    destination = ViperCloudDestination(owner="machina", project="weekend_models")
    client = InMemoryViperCloudClient()
    publisher = ViperCloudSnapshotPublisher(tmp_path, destination, client)
    source_snapshot = publisher.publish(
        resolved_stage_path="runs/source/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\n",
        files={"runs/source/artifacts/model.bin": artifact},
    )
    source_files = client.list_files(
        owner=source_snapshot.owner,
        project=source_snapshot.project,
        revision=source_snapshot.revision,
    )
    source_file = next(
        file for file in source_files if file.path.endswith("artifacts/model.bin")
    )
    source_uploads = len(client.upload_calls)

    target_snapshot = publisher.publish_reuse(
        resolved_stage_path="runs/target/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\ncompletion: reused\n",
        source_snapshot=source_snapshot,
        files={"runs/target/artifacts/model.bin": source_file},
        source_bytes={"runs/target/artifacts/model.bin": b"parameters"},
    )

    assert len(client.upload_calls) == source_uploads + 1
    assert len(client.copy_calls) == 1
    source, target = client.copy_calls[0]
    assert source.path == "runs/source/artifacts/model.bin"
    assert target.path == "runs/target/artifacts/model.bin"
    assert (
        client.uploads[(target.owner, target.project, target.revision, target.path)]
        is client.uploads[(source.owner, source.project, source.revision, source.path)]
    )
    assert (
        client.fetch(
            owner=target_snapshot.owner,
            project=target_snapshot.project,
            revision=target_snapshot.revision,
            path=target.path,
        )
        == b"parameters"
    )
