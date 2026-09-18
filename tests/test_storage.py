"""Tests for repository-local immutable output publication."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from viper import execution
from viper._schema import SHA256, RepoRelPath
from viper._verification.storage import read_resolved_file
from viper.artifacts import ResolvedBundleArtifact, ResolvedSingleFileArtifact
from viper.evidence import VerificationError, VerificationPolicy
from viper.execution._restore import (
    _IndexedFile,
    _plan_files,
    _PlannedFile,
    _restore_files,
)
from viper.execution._source import RunFetcher
from viper.execution.errors import RestoreError
from viper.ids import HumanId
from viper.references import (
    GitFileRef,
    HuggingFaceFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
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

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
CONSUMER_REPOSITORY = "https://example.com/consumer.git"


def _restore_file(path: str) -> ResolvedFileRef:
    """Create one immutable file reference for restore-planner tests."""
    payload = path.encode()
    return ResolvedFileRef(
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        stored_at=LocalFileRef(
            workspace=Path("/workspace"),
            store_id="0" * 32,
            commit="a" * 64,
            path=path,
        ),
    )


def test_resolve_run_reference_identifies_local_terminal_bytes(tmp_path: Path) -> None:
    """Expose a local terminal run as an immutable public run reference."""
    (tmp_path / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )
    terminal = tmp_path / "runs/example/resolved.yaml"
    terminal.parent.mkdir(parents=True)
    terminal.write_bytes(b"status: succeeded\n")

    reference = execution.resolve_run_reference(tmp_path, terminal)

    assert isinstance(reference, ResolvedRunRef)
    assert reference.sha256 == hashlib.sha256(terminal.read_bytes()).hexdigest()
    assert reference.bytes == terminal.stat().st_size
    assert reference.stored_at.path == "runs/example/resolved.yaml"


def test_run_fetcher_reuses_one_external_git_file_within_an_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetch each immutable external Git file once per RunFetcher."""
    reference = GitFileRef(
        repository=HttpUrl("https://example.com/producer.git"),
        commit="a" * 40,
        path="src/producer/loader.py",
    )
    fetched: list[GitFileRef] = []

    def fetch(location: GitFileRef, *, checkout: Path) -> bytes:
        fetched.append(location)
        return b"source"

    monkeypatch.setattr("viper.execution._source.fetch_git_file_bytes", fetch)
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.com/consumer.git",
    )

    assert fetcher(reference) == b"source"
    assert fetcher(reference) == b"source"
    assert fetched == [reference]


def test_run_fetcher_does_not_retain_an_external_git_file_over_its_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound retained external Git bytes without rejecting retrieval."""
    reference = GitFileRef(
        repository=HttpUrl("https://example.com/producer.git"),
        commit="a" * 40,
        path="artifacts/model.bin",
    )
    fetched: list[GitFileRef] = []

    def fetch(location: GitFileRef, *, checkout: Path) -> bytes:
        fetched.append(location)
        return b"checkpoint"

    monkeypatch.setattr("viper.execution._source.fetch_git_file_bytes", fetch)
    monkeypatch.setattr("viper.execution._source._MAX_EXTERNAL_GIT_CACHE_BYTES", 5)
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.com/consumer.git",
    )

    assert fetcher(reference) == b"checkpoint"
    assert fetcher(reference) == b"checkpoint"
    assert fetched == [reference, reference]


def test_run_fetcher_reuses_one_checkout_for_files_from_the_same_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetch one external commit when verification reads several of its files."""
    references = tuple(
        GitFileRef(
            repository=HttpUrl("https://example.com/producer.git"),
            commit="a" * 40,
            path=path,
        )
        for path in ("src/producer/loader.py", "src/producer/model.py")
    )
    checkouts: list[Path] = []

    def fetch(location: GitFileRef, *, checkout: Path) -> bytes:
        checkouts.append(checkout)
        return str(location.path).encode()

    monkeypatch.setattr("viper.execution._source.fetch_git_file_bytes", fetch)
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.com/consumer.git",
    )

    assert [fetcher(reference) for reference in references] == [
        str(reference.path).encode() for reference in references
    ]
    assert checkouts[0] == checkouts[1]
    second_fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.com/consumer.git",
    )

    assert second_fetcher(references[0]) == str(references[0].path).encode()
    assert checkouts[2] == checkouts[0]
    assert checkouts[0].is_relative_to(tmp_path / ".viper/cache/git-checkouts")


def test_run_fetcher_reuses_verified_bytes_across_executions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serve a second execution from the content-addressed workspace cache."""
    payload = b"resolved evidence"
    location = HuggingFaceFileRef(
        repository="example/evidence",
        commit="a" * 40,
        path="runs/example/resolved.yaml",
        repo_type="dataset",
    )
    reference = ResolvedFileRef(
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        stored_at=location,
    )
    fetches: list[HuggingFaceFileRef] = []

    def fetch(selected: HuggingFaceFileRef) -> bytes:
        fetches.append(selected)
        return payload

    monkeypatch.setattr("viper.execution._source.fetch_huggingface_file_bytes", fetch)
    store = LocalArtifactStore(tmp_path)

    assert (
        read_resolved_file(
            reference,
            fetcher=RunFetcher(tmp_path, store, CONSUMER_REPOSITORY),
        )
        == payload
    )
    assert (
        read_resolved_file(
            reference,
            fetcher=RunFetcher(tmp_path, store, CONSUMER_REPOSITORY),
        )
        == payload
    )
    assert fetches == [location]


def test_run_fetcher_repairs_corrupt_verified_cache_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refetch instead of serving cached bytes with the wrong identity."""
    payload = b"resolved evidence"
    location = HuggingFaceFileRef(
        repository="example/evidence",
        commit="a" * 40,
        path="runs/example/resolved.yaml",
        repo_type="dataset",
    )
    reference = ResolvedFileRef(
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        stored_at=location,
    )
    fetches: list[HuggingFaceFileRef] = []

    def fetch(selected: HuggingFaceFileRef) -> bytes:
        fetches.append(selected)
        return payload

    monkeypatch.setattr("viper.execution._source.fetch_huggingface_file_bytes", fetch)
    store = LocalArtifactStore(tmp_path)
    fetcher = RunFetcher(tmp_path, store, CONSUMER_REPOSITORY)
    fetcher.read_verified(reference)
    cache_path = (
        tmp_path
        / ".viper/cache/verified-objects"
        / reference.sha256[:2]
        / reference.sha256
    )
    cache_path.write_bytes(b"corrupt")

    assert (
        RunFetcher(tmp_path, store, CONSUMER_REPOSITORY).read_verified(reference)
        == payload
    )
    assert cache_path.read_bytes() == payload
    assert fetches == [location, location]


def test_run_fetcher_does_not_duplicate_local_store_objects(tmp_path: Path) -> None:
    """Read workspace-local immutable bytes from their owning store."""
    store = LocalArtifactStore(tmp_path)
    reference = store.resolved_files({"evidence.bin": b"evidence"})[0]
    resolved = ResolvedFileRef.model_validate(reference.model_dump(mode="python"))

    assert (
        RunFetcher(tmp_path, store, CONSUMER_REPOSITORY).read_verified(resolved)
        == b"evidence"
    )
    assert not (tmp_path / ".viper/cache/verified-objects").exists()


def test_local_stores_persist_distinct_workspace_identities(tmp_path: Path) -> None:
    """Keep one stable identity per local workspace store."""
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first = LocalArtifactStore(first_root)
    second = LocalArtifactStore(second_root)

    assert first.store_id == LocalArtifactStore(first_root).store_id
    assert first.store_id != second.store_id
    assert (first.store_root / ".identity").read_text(encoding="ascii").strip() == (
        first.store_id
    )


def test_local_store_rejects_a_reference_owned_by_another_workspace(
    tmp_path: Path,
) -> None:
    """Reject a local reference when a different store attempts retrieval."""
    producer_root = tmp_path / "producer"
    consumer_root = tmp_path / "consumer"
    producer_root.mkdir()
    consumer_root.mkdir()
    producer = LocalArtifactStore(producer_root)
    consumer = LocalArtifactStore(consumer_root)
    reference = producer.resolved_files({"artifact.bin": b"payload"})[0]

    with pytest.raises(LocalStoreError, match="different store"):
        consumer.fetch(reference.stored_at)


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
                workspace=store.repository_root,
                store_id=store.store_id,
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
        self.fetch_to_path_calls: list[ViperCloudFileRef] = []
        self.rejected_seals = rejected_seals
        self.seal_calls = 0

    def upload(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
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
        key = (owner, workspace, revision, path)
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
        assert (source.owner, source.workspace, source.revision) in self.sealed
        raw = self.uploads[
            (source.owner, source.workspace, source.revision, source.path)
        ]
        assert len(raw) == bytes
        assert hashlib.sha256(raw).hexdigest() == sha256
        self.uploads[(target.owner, target.workspace, target.revision, target.path)] = (
            raw
        )
        self.copy_calls.append((source, target))

    def seal(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        files: tuple[SnapshotFileRef, ...],
    ) -> None:
        """Expose all uploaded files after the configured failures."""
        self.seal_calls += 1
        if self.seal_calls <= self.rejected_seals:
            raise RuntimeError("seal unavailable")
        self.sealed[(owner, workspace, revision)] = files

    def fetch(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
    ) -> bytes:
        """Read a file only when its revision is sealed."""
        if (owner, workspace, revision) not in self.sealed:
            raise FileNotFoundError("revision is not sealed")
        return self.uploads[(owner, workspace, revision, path)]

    def fetch_to_path(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        destination: Path,
    ) -> Path:
        """Write one sealed in-memory file to the selected test path."""
        self.fetch_to_path_calls.append(
            ViperCloudFileRef(
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
            )
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            self.fetch(
                owner=owner,
                workspace=workspace,
                revision=revision,
                path=path,
            )
        )
        return destination

    def list_files(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
    ) -> tuple[SnapshotFileRef, ...]:
        """List the files exposed by a sealed revision."""
        return self.sealed[(owner, workspace, revision)]

    def verify_file(
        self,
        *,
        owner: HumanId,
        workspace: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        sha256: SHA256,
        bytes: int,
    ) -> None:
        """Verify one sealed in-memory file without writing another copy."""
        raw = self.fetch(
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=path,
        )
        if len(raw) != bytes or hashlib.sha256(raw).hexdigest() != sha256:
            raise StorageConfigurationError("cloud file identity changed")


def test_cloud_publication_is_atomic_and_retryable(tmp_path: Path) -> None:
    """Expose cloud files only after sealing one deterministic revision."""
    artifact = tmp_path / "artifacts" / "model.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"parameters")
    destination = ViperCloudDestination(owner="machina", workspace="weekend_models")
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
        workspace=snapshot.workspace,
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
            workspace=location.workspace,
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
        workspace="weekend_models",
        revision="0" * 64,
        path="runs/example/evidence.yaml",
    )
    client.upload(
        owner=location.owner,
        workspace=location.workspace,
        revision=location.revision,
        path=location.path,
        source=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
    client.seal(
        owner=location.owner,
        workspace=location.workspace,
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


def test_cloud_fetcher_streams_one_verified_path_per_execution(tmp_path: Path) -> None:
    """Reuse a streamed immutable object without fetching or hashing it again."""
    client = InMemoryViperCloudClient()
    raw = b"large artifact"
    location = ViperCloudFileRef(
        owner="machina",
        workspace="weekend_models",
        revision="1" * 64,
        path="runs/example/large.bin",
    )
    reference = ResolvedFileRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=location,
    )
    client.upload(
        owner=location.owner,
        workspace=location.workspace,
        revision=location.revision,
        path=location.path,
        source=raw,
        sha256=reference.sha256,
        bytes=reference.bytes,
    )
    client.seal(
        owner=location.owner,
        workspace=location.workspace,
        revision=location.revision,
        files=(
            SnapshotFileRef(
                path=location.path,
                sha256=reference.sha256,
                bytes=reference.bytes,
            ),
        ),
    )
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        CONSUMER_REPOSITORY,
        cloud_client=client,
    )

    first = fetcher.read_verified_path(reference)
    second = fetcher.read_verified_path(reference)

    assert first == second
    assert first.read_bytes() == raw
    assert client.fetch_to_path_calls == [location]


def test_execution_fetcher_trusts_sealed_local_payload_until_strict_verification(
    tmp_path: Path,
) -> None:
    """Trust a sealed local payload in execution and retain strict checks."""
    store = LocalArtifactStore(tmp_path)
    raw = b"large artifact"
    reference = store.resolved_files({"runs/example/large.bin": raw})[0]
    trusted = RunFetcher(
        tmp_path,
        store,
        CONSUMER_REPOSITORY,
        trust_immutable_payloads=True,
    )

    path = trusted.read_verified_path(reference)
    path.write_bytes(b"other artifact")

    assert trusted.read_verified_path(reference) == path
    with pytest.raises(VerificationError, match="SHA-256 mismatch"):
        RunFetcher(
            tmp_path,
            store,
            CONSUMER_REPOSITORY,
        ).read_verified_path(reference)


def test_cloud_verification_rejects_local_references() -> None:
    """Reject a cloud terminal graph that still reaches local evidence."""
    resolved_run = ResolvedRun.model_construct(
        spec=ResolvedRunSpecRef.model_construct(
            stored_at=ViperCloudFileRef(
                owner="machina",
                workspace="weekend_models",
                revision="0" * 64,
                path="runs/example/spec.yaml",
            )
        ),
        status="succeeded",
        attempts=(
            ResolvedAttemptRef.model_construct(
                stored_at=LocalFileRef(
                    workspace=Path("/workspace"),
                    store_id="0" * 32,
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
    marker.write_text("[workspace]\nschema_version = 2\n", encoding="utf-8")

    local = load_storage_settings(tmp_path)
    assert local == StorageSettings(destination=LocalStorageDestination())
    assert StorageSettings.model_validate_json(local.model_dump_json()) == local

    marker.write_text(
        "[workspace]\nschema_version = 2\n"
        '[storage]\ndestination = "viper://machina/weekend_models"\n',
        encoding="utf-8",
    )
    cloud = load_storage_settings(tmp_path)
    assert cloud.destination == ViperCloudDestination(
        owner="machina",
        workspace="weekend_models",
    )
    assert StorageSettings.model_validate_json(cloud.model_dump_json()) == cloud

    marker.write_text(
        "[workspace]\nschema_version = 2\n"
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
    marker.write_text("[workspace]\nschema_version = 2\n", encoding="utf-8")
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
        "[workspace]\nschema_version = 2\n",
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
            ViperCloudDestination(owner="machina", workspace="weekend_models"),
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
            stored_at=LocalFileRef(
                workspace=Path("/workspace"),
                store_id="0" * 32,
                commit="a" * 64,
                path="artifacts/first.bin",
            ),
        ),
        ResolvedFileRef(
            sha256=hashlib.sha256(second).hexdigest(),
            bytes=len(second),
            stored_at=LocalFileRef(
                workspace=Path("/workspace"),
                store_id="0" * 32,
                commit="a" * 64,
                path="artifacts/second.bin",
            ),
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


def test_multi_artifact_restore_uses_declared_paths(tmp_path: Path) -> None:
    """Place several selected artifacts beneath one output directory."""
    prediction = ArtifactRestoreSelector(
        stage_id="predict", artifact_name="raw_gene_predictions"
    )
    receipt = ArtifactRestoreSelector(
        stage_id="evaluate", artifact_name="parity_receipt"
    )

    planned = _plan_files(
        root=tmp_path,
        indexed={
            prediction: (
                _IndexedFile(
                    reference=_restore_file(
                        "runs/example/artifacts/predict/raw_gene_predictions/"
                        "stored-predictions.npz"
                    ),
                    declared_path="raw_gene_predictions.npz",
                ),
            ),
            receipt: (
                _IndexedFile(
                    reference=_restore_file(
                        "runs/example/artifacts/evaluate/parity_receipt/"
                        "stored-receipt.json"
                    ),
                    declared_path="hopfield_replay_receipt.json",
                ),
            ),
        },
        selectors=(prediction, receipt),
        output=Path("replay"),
    )

    assert tuple(item.destination for item in planned) == (
        tmp_path / "replay/raw_gene_predictions.npz",
        tmp_path / "replay/hopfield_replay_receipt.json",
    )


@pytest.mark.parametrize(
    "artifact",
    (
        {
            "kind": "file",
            "file": {
                "path": "stored/result.bin",
                "sha256": "a" * 64,
                "bytes": 1,
            },
        },
        {
            "kind": "bundle",
            "members": (
                {
                    "relative_path": "first.bin",
                    "file": {
                        "path": "stored/first.bin",
                        "sha256": "a" * 64,
                        "bytes": 1,
                    },
                },
                {
                    "relative_path": "second.bin",
                    "file": {
                        "path": "stored/second.bin",
                        "sha256": "b" * 64,
                        "bytes": 1,
                    },
                },
            ),
        },
    ),
)
def test_resolved_artifact_requires_its_declared_path(
    artifact: dict[str, object],
) -> None:
    """Reject a resolved artifact that omits the author's output path."""
    model = (
        ResolvedSingleFileArtifact
        if artifact["kind"] == "file"
        else ResolvedBundleArtifact
    )

    with pytest.raises(ValidationError, match="relative_path"):
        model.model_validate(artifact)


def test_multi_artifact_restore_rejects_overlapping_declared_paths(
    tmp_path: Path,
) -> None:
    """Reject selected artifacts that declare the same destination path."""
    first = ArtifactRestoreSelector(stage_id="first", artifact_name="result")
    second = ArtifactRestoreSelector(stage_id="second", artifact_name="result")

    with pytest.raises(RestoreError, match="restore destinations overlap"):
        _plan_files(
            root=tmp_path,
            indexed={
                first: (
                    _IndexedFile(
                        reference=_restore_file("runs/first/result.json"),
                        declared_path="result.json",
                    ),
                ),
                second: (
                    _IndexedFile(
                        reference=_restore_file("runs/second/result.json"),
                        declared_path="result.json",
                    ),
                ),
            },
            selectors=(first, second),
            output=Path("replay"),
        )


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
                workspace=store.repository_root,
                store_id=store.store_id,
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
    destination = ViperCloudDestination(owner="machina", workspace="weekend_models")
    client = InMemoryViperCloudClient()
    publisher = ViperCloudSnapshotPublisher(tmp_path, destination, client)
    source_snapshot = publisher.publish(
        resolved_stage_path="runs/source/stages/train/resolved.yaml",
        resolved_stage=b"stage_id: train\n",
        files={"runs/source/artifacts/model.bin": artifact},
    )
    source_files = client.list_files(
        owner=source_snapshot.owner,
        workspace=source_snapshot.workspace,
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
        client.uploads[(target.owner, target.workspace, target.revision, target.path)]
        is client.uploads[
            (source.owner, source.workspace, source.revision, source.path)
        ]
    )
    assert (
        client.fetch(
            owner=target_snapshot.owner,
            workspace=target_snapshot.workspace,
            revision=target_snapshot.revision,
            path=target.path,
        )
        == b"parameters"
    )
