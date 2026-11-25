"""Check durable asynchronous publication using the real verification journal."""

from __future__ import annotations

import fcntl
import os
import sys
import textwrap
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from huggingface_hub.errors import HfHubHTTPError

from tests.fixtures import MemoryHub
from tests.test_storage import InMemoryViperCloudProvider
from viper import _offload
from viper import _subprocess as subprocess
from viper._cloud import (
    GcsRepository,
    HuggingFaceRepository,
    LocalSource,
    SnapshotInventory,
    SnapshotSources,
    ViperCloudDestination,
    ViperCloudError,
    manifest_revision,
    source_file,
)
from viper._offload import (
    PublicationError,
    PublicationSession,
    current_session,
    load_job,
    load_operation,
    operation_lock,
    read_publication_copies,
    read_publication_receipt,
    read_publication_status,
    retry_publication,
    save_job,
    save_operation,
    session_scope,
    start_publication_worker,
)
from viper._storage_locks import PayloadLocks
from viper._storage_registry import StorageRegistry
from viper.cloud import PublicationTarget, ViperCloud
from viper.execution import _offload_worker
from viper.execution._offload_worker import drain_once
from viper.execution._promotion_journal import (
    PublicationJournal,
    publish_captured_snapshot,
)
from viper.execution.errors import RunPromotionError
from viper.huggingface import HuggingFaceProvider
from viper.references import (
    LocalStageResultSnapshotRef,
    ResolvedRunRef,
    resolve_snapshot_file_ref,
)
from viper.serialization import document_digest
from viper.storage import LocalArtifactStore


@pytest.fixture
def target() -> PublicationTarget:
    """Select a fake repository without constructing cloud credentials."""
    return PublicationTarget(
        repository=GcsRepository(bucket="test-bucket"),
        destination=ViperCloudDestination(owner="machina", workspace="queue"),
    )


@pytest.fixture(autouse=True)
def no_detached_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests in process while exercising the actual durable drainer."""
    monkeypatch.setattr(_offload, "start_publication_worker", lambda *a, **k: None)


def _snapshot(root: Path, name: str, raw: bytes) -> SnapshotSources:
    """Register an original output without making a second payload copy."""
    original = root / name
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(raw)
    identity = source_file(root, name, original)
    source = LocalStageResultSnapshotRef(
        workspace=root, commit=manifest_revision((identity,))
    )
    status = original.stat()
    record = SnapshotSources(
        inventory=SnapshotInventory(source=source, source_files=(identity,)),
        locations={
            name: (
                LocalSource(
                    path=name,
                    observed_stat=(
                        status.st_dev,
                        status.st_ino,
                        status.st_mtime_ns,
                        status.st_ctime_ns,
                    ),
                    custody="output",
                ),
            )
        },
    )
    StorageRegistry(root).register_snapshot(record)
    return record


def _cloud(
    root: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> InMemoryViperCloudProvider:
    """Use existing cloud dispatch and exact verification with an in-memory host."""
    provider = InMemoryViperCloudProvider(root)
    cloud = ViperCloud(root, target.repository, provider=provider)
    monkeypatch.setattr(
        ViperCloud, "for_target", classmethod(lambda cls, root, target: cloud)
    )
    return provider


def test_admission_is_durable_without_foreground_cloud_work(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue exact originals and hold them before allowing computation to continue."""
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    member = record.inventory.source_files[0]
    reference = resolve_snapshot_file_ref(record.inventory.source, member)

    def reject_provider(*args: object, **kwargs: object) -> None:
        """Fail if admission tries to initialize any network service."""
        raise AssertionError("provider construction during admission")

    monkeypatch.setattr(ViperCloud, "for_target", reject_provider)
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
        session.admit(record.inventory, locations=record.locations)
        operation = load_operation(session.operation_path)
        assert not operation.closed
        assert len(operation.jobs) == 1
        assert (tmp_path / "weights.bin").read_bytes() == b"weights"
        assert not (tmp_path / ".viper/store/objects").exists()
        registry = StorageRegistry(tmp_path)
        with registry._transaction() as connection:
            assert registry.source_is_pending(reference, connection)
        with PayloadLocks(tmp_path).exclusive(reference) as acquired:
            assert not acquired
        assert read_publication_status(session.operation_path)["status"] == "pending"
    assert load_operation(session.operation_path).closed


def test_nested_scopes_retain_readers_until_the_outer_workflow_finishes(
    tmp_path: Path,
) -> None:
    """Keep a producer's bytes through later inference and diagnostic calls."""
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    reference = resolve_snapshot_file_ref(
        record.inventory.source, record.inventory.source_files[0]
    )
    with session_scope(tmp_path) as outer:
        with session_scope(tmp_path) as inner:
            assert inner is outer is current_session()
            inner.hold(reference)
        assert not load_operation(outer.operation_path).closed
        with PayloadLocks(tmp_path).exclusive(reference) as acquired:
            assert not acquired
    assert current_session() is None
    with PayloadLocks(tmp_path).exclusive(reference) as acquired:
        assert acquired


def test_snapshot_copies_complete_while_the_workflow_remains_open(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish data during the workflow and its final receipt after closure."""
    provider = _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
        assert drain_once(tmp_path) is not None
        copies = read_publication_copies(
            session.operation_path, record.inventory.source
        )
        assert len(copies) == 1
        assert copies[0].source == record.inventory.source
        assert copies[0].source_files == record.inventory.source_files
        assert read_publication_status(session.operation_path)["status"] == "pending"
        with pytest.raises(PublicationError, match="still open"):
            read_publication_status(session.operation_path, wait=True)
        with pytest.raises(PublicationError, match="not completed"):
            read_publication_receipt(session.operation_path)
    assert drain_once(tmp_path) is None
    assert read_publication_status(session.operation_path)["status"] == "complete"
    receipt = read_publication_receipt(session.operation_path)
    assert receipt["science_succeeded"] is True
    assert len(receipt["copies"]) == 1
    assert len(load_operation(session.operation_path).final_receipts) == 1
    assert len(provider.upload_calls) == 2
    assert len(provider.fetch_to_path_calls) == 2
    assert StorageRegistry(tmp_path).backings(record.inventory.source) == copies
    assert (tmp_path / "weights.bin").read_bytes() == b"weights"


def test_a_failed_snapshot_does_not_block_ready_uploads_and_can_be_retried(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep failed sources, finish unrelated work, and reuse verified work on retry."""
    provider = _cloud(tmp_path, target, monkeypatch)
    publish = provider.publish_revision

    def fail_bad(**kwargs: Any) -> Any:
        """Reject just one snapshot while accepting ready work behind it."""
        if "bad.bin" in kwargs["sources"]:
            raise OSError("temporarily unavailable")
        return publish(**kwargs)

    monkeypatch.setattr(provider, "publish_revision", fail_bad)
    bad = _snapshot(tmp_path, "bad.bin", b"retry me")
    good = _snapshot(tmp_path, "good.bin", b"publish now")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(bad.inventory, locations=bad.locations)
        session.admit(good.inventory, locations=good.locations)
    bad_key = document_digest(bad.inventory.source)
    for _ in range(3):
        with operation_lock(session.operation_path):
            job_path = session.operation_path.parent / "jobs" / f"{bad_key}.json"
            job = load_job(job_path)
            save_job(job_path, job.model_copy(update={"ready_at": 0.0}))
        drain_once(tmp_path)
    assert read_publication_status(session.operation_path)["status"] == "failed"
    assert (
        len(read_publication_copies(session.operation_path, good.inventory.source)) == 1
    )
    registry = StorageRegistry(tmp_path)
    with registry._transaction() as connection:
        assert registry.source_is_pending(bad.inventory.source_files[0], connection)
        assert not registry.source_is_pending(
            good.inventory.source_files[0], connection
        )
    assert (tmp_path / "bad.bin").read_bytes() == b"retry me"
    monkeypatch.setattr(provider, "publish_revision", publish)
    retry_publication(session.operation_path)
    drain_once(tmp_path)
    assert read_publication_status(session.operation_path)["status"] == "complete"
    assert sum(call[-1] == "good.bin" for call in provider.upload_calls) == 1


def test_orphaned_workflows_publish_without_authorizing_cleanup(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover admitted work after process death and retain scientific-failure state."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    session = PublicationSession(tmp_path, (target,))
    session.admit(record.inventory, locations=record.locations)
    for readers in session._readers.values():
        readers.close()
    os.close(session._owner)
    drain_once(tmp_path)
    operation = load_operation(session.operation_path)
    assert operation.closed
    assert operation.science_succeeded is False
    assert operation.publication_complete
    assert (tmp_path / "weights.bin").exists()


def test_runtime_subclass_refs_are_saved_as_base_file_refs(tmp_path: Path) -> None:
    """Keep run-kind tags out of a receipt field that accepts ordinary file refs."""
    record = _snapshot(tmp_path, "resolved.yaml", b"run")
    base = resolve_snapshot_file_ref(
        record.inventory.source, record.inventory.source_files[0]
    )
    run = ResolvedRunRef(**base.model_dump())
    with session_scope(tmp_path) as session:
        session.hold(run)
        session.note_result(False)
    operation = load_operation(session.operation_path)
    assert operation.science_succeeded is False
    assert "kind" not in operation.used[0].model_dump()
    assert operation.used[0] == base


def test_workflow_exception_survives_a_failed_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve the scientific exception when closing metadata also fails."""

    def fail_close(self: PublicationSession, succeeded: bool = True) -> None:
        """Simulate local metadata becoming unavailable on exit."""
        del succeeded
        os.close(self._owner)
        raise OSError("disk unavailable")

    monkeypatch.setattr(PublicationSession, "close", fail_close)
    with pytest.raises(RuntimeError, match="training failed"):
        with session_scope(tmp_path):
            raise RuntimeError("training failed")


def test_worker_starter_detaches_and_keeps_launch_failure_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Launch without waiting, and retain requests when process creation fails."""
    calls: list[dict[str, Any]] = []

    def launch(*arguments: object, **options: Any) -> None:
        """Record the production process launch without starting a provider."""
        assert arguments
        calls.append(options)
        raise OSError("process limit reached")

    monkeypatch.setattr(_offload.subprocess, "Popen", launch)
    start_publication_worker(tmp_path)
    assert calls[0]["start_new_session"] is True
    assert calls[0]["stdin"] == subprocess.DEVNULL
    assert calls[0]["stdout"] is calls[0]["stderr"]
    assert (
        "requests remain pending"
        in (tmp_path / ".viper/publications/worker.log").read_text()
    )


def test_detached_worker_finishes_after_the_producer_process_exits(
    tmp_path: Path,
) -> None:
    """Publish admitted originals in a real child after its original parent dies."""
    repository = Path(__file__).resolve().parents[1]
    worker = textwrap.dedent(
        """
        import sys
        import time
        from pathlib import Path
        from tests.test_storage import InMemoryViperCloudProvider
        from viper._cloud import GcsRepository
        from viper.cloud import ViperCloud
        from viper.execution._offload_worker import drain
        root = Path(sys.argv[1])
        time.sleep(0.3)
        provider = InMemoryViperCloudProvider(root)
        cloud = ViperCloud(root, GcsRepository(bucket="test-bucket"), provider=provider)
        ViperCloud.for_target = classmethod(lambda cls, root, target: cloud)
        drain(root)
        """
    )
    producer = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path
        from viper import _offload
        from viper import _subprocess as subprocess
        from viper._cloud import GcsRepository, ViperCloudDestination
        from viper._offload import PublicationSession, bind_session
        from viper.cloud import PublicationTarget
        from viper.storage import LocalArtifactStore
        root = Path(sys.argv[1])
        target = PublicationTarget(
            repository=GcsRepository(bucket="test-bucket"),
            destination=ViperCloudDestination(owner="machina", workspace="detached"),
        )
        _offload.start_publication_worker = lambda *args, **kwargs: None
        session = PublicationSession(root, (target,))
        original = root / "weights.bin"
        original.write_bytes(b"durable checkpoint")
        with bind_session(session):
            LocalArtifactStore(root)._publish(
                {"weights.bin": original}, path_custody="output"
            )
        with (root / "child.log").open("ab") as log:
            subprocess.Popen(
                [sys.executable, "-c", sys.argv[2], str(root)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        print(session.operation_path, flush=True)
        os._exit(0)
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(repository / "src"), str(repository))
    )
    result = subprocess.run(
        (sys.executable, "-c", producer, str(tmp_path), worker),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    path = Path(result.stdout.strip())
    deadline = time.monotonic() + 25
    while read_publication_status(path)["status"] == "pending":
        if time.monotonic() >= deadline:
            pytest.fail((tmp_path / "child.log").read_text())
        time.sleep(0.1)
    assert read_publication_status(path)["status"] == "complete"
    assert read_publication_receipt(path)["science_succeeded"] is False
    assert (tmp_path / "weights.bin").read_bytes() == b"durable checkpoint"


def test_local_only_work_does_not_start_an_upload_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the ordinary local default free of unnecessary background processes."""
    calls = []
    monkeypatch.setattr(
        _offload, "start_publication_worker", lambda *a, **k: calls.append(a)
    )
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    with session_scope(tmp_path) as session:
        session.admit(record.inventory, locations=record.locations)
    assert not calls
    assert read_publication_status(session.operation_path)["status"] == "complete"
    assert read_publication_receipt(session.operation_path)["targets"] == []


def test_reused_shared_bytes_are_portable_without_reuploading_them(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carry original membership and prior-host backing for a new logical alias."""
    provider = _cloud(tmp_path, target, monkeypatch)
    original = _snapshot(tmp_path, "original.bin", b"shared weights")
    with session_scope(tmp_path, targets=(target,)) as first:
        first.admit(original.inventory, locations=original.locations)
    drain_once(tmp_path)
    previous = read_publication_copies(first.operation_path, original.inventory.source)
    alias = _snapshot(tmp_path, "renamed.bin", b"shared weights")
    reference = resolve_snapshot_file_ref(
        alias.inventory.source, alias.inventory.source_files[0]
    )
    other_target = target.model_copy(
        update={
            "destination": ViperCloudDestination(owner="machina", workspace="later")
        }
    )
    with session_scope(tmp_path, targets=(other_target,)) as second:
        second.record_path(reference, tmp_path / "renamed.bin")
    drain_once(tmp_path)
    receipt = read_publication_receipt(second.operation_path)
    assert receipt["copies"] == [previous[0].model_dump(mode="json")]
    assert receipt["inventories"] == [alias.inventory.model_dump(mode="json")]
    assert not load_operation(second.operation_path).jobs
    assert len(provider.upload_calls) == 3  # Data once, then two final receipts.
    assert sum(call[-1] == "original.bin" for call in provider.upload_calls) == 1
    assert not any(call[-1] == "renamed.bin" for call in provider.upload_calls)


def test_receipt_reader_rejects_bytes_changed_after_cloud_verification(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate the local receipt against its final immutable cloud proofs."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
    drain_once(tmp_path)
    receipt_path = session.operation_path.with_name("receipt.json")
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(PublicationError, match="different receipt bytes"):
        read_publication_receipt(session.operation_path)


def test_reading_an_existing_cloud_file_carries_its_individual_backing(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a portable file proof without inventing or republishing its whole bundle."""
    provider = _cloud(tmp_path, target, monkeypatch)
    cloud = ViperCloud(tmp_path, target.repository, provider=provider)
    snapshot, files = cloud.publish(
        target.destination, {"weights.bin": b"weights", "unused.bin": b"other"}
    )
    reference = resolve_snapshot_file_ref(
        snapshot, next(file for file in files if file.path == "weights.bin")
    )
    with session_scope(tmp_path, targets=(target,)) as session:
        LocalArtifactStore(tmp_path).resolve(reference, cloud=cloud)
    assert not load_operation(session.operation_path).jobs
    assert not StorageRegistry(tmp_path).backings(snapshot)
    drain_once(tmp_path)
    receipt = read_publication_receipt(session.operation_path)
    assert receipt["copies"] == []
    assert receipt["file_copies"] == [reference.model_dump(mode="json")]
    assert len(provider.upload_calls) == 3  # Original bundle, then the final receipt.
    assert sum(call[-1] == "weights.bin" for call in provider.upload_calls) == 1
    assert len(provider.fetch_to_path_calls) == 2  # One read, one final proof.


def test_worker_restores_remote_snapshot_members_and_keeps_their_cleanup_selection(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish a cloud producer's full bundle even when only one member was read."""
    provider = _cloud(tmp_path, target, monkeypatch)
    cloud = ViperCloud(tmp_path, target.repository, provider=provider)
    snapshot, files = cloud.publish(
        target.destination, {"config.json": b"{}", "weights.bin": b"large weights"}
    )
    destination = target.model_copy(
        update={"destination": ViperCloudDestination(owner="machina", workspace="copy")}
    )
    storage = LocalArtifactStore(tmp_path)
    inventory = SnapshotInventory(source=snapshot, source_files=files)
    storage.registry.register_snapshot(SnapshotSources(inventory=inventory))
    config = resolve_snapshot_file_ref(
        snapshot, next(file for file in files if file.path == "config.json")
    )
    with session_scope(tmp_path, targets=(destination,)) as session:
        session.admit(inventory)
        storage.resolve(config, cloud=cloud)
        token = _offload._CURRENT.set(None)
        try:
            drain_once(tmp_path)
        finally:
            _offload._CURRENT.reset(token)
        persisted = load_operation(session.operation_path)
        assert len(persisted.locations) == 1  # Worker downloaded the unread weights.
    closed = load_operation(session.operation_path)
    assert len(closed.locations) == 2  # Closing merges worker and foreground copies.
    assert len(closed.used) == 2
    drain_once(tmp_path)
    assert read_publication_status(session.operation_path)["status"] == "complete"
    copies = read_publication_copies(session.operation_path, snapshot)
    assert copies[0].source_files == files
    assert (
        sum(
            ref.workspace == target.destination.workspace and ref.path == "weights.bin"
            for ref in provider.fetch_to_path_calls
        )
        == 1
    )


@pytest.fixture
def hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[HuggingFaceProvider, MemoryHub, PublicationTarget], None, None]:
    """Use the real Hub provider with an HTTP transport holding committed bytes."""
    api = MemoryHub(tmp_path / "hub-cache")
    provider = HuggingFaceProvider(
        tmp_path, "owner/copies", "dataset", api=cast(Any, api)
    )
    target = PublicationTarget(
        repository=HuggingFaceRepository(
            repository="owner/copies", repo_type="dataset"
        ),
        destination=ViperCloudDestination(owner="machina", workspace="queue"),
    )
    cloud = ViperCloud(tmp_path, target.repository, provider=provider)
    monkeypatch.setattr(provider, "_download", api.download)
    monkeypatch.setattr(
        ViperCloud, "for_target", classmethod(lambda cls, root, target: cloud)
    )
    with httpx.Client(transport=httpx.MockTransport(api.response)) as client:
        monkeypatch.setattr("viper.huggingface.get_session", lambda: client)
        yield provider, api, target


def test_hub_worker_verification_streams_payloads_without_a_hub_payload_cache(
    tmp_path: Path,
    hub: tuple[HuggingFaceProvider, MemoryHub, PublicationTarget],
) -> None:
    """Verify uploaded weights through bounded staging instead of a second cache."""
    _, api, target = hub
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
    drain_once(tmp_path)
    assert read_publication_status(session.operation_path)["status"] == "complete"
    assert not tuple(api.cache.rglob("weights.bin"))
    assert tuple(api.cache.rglob("revision-manifest.json"))


def test_hub_quota_delay_is_queued_while_another_snapshot_publishes(
    tmp_path: Path,
    hub: tuple[HuggingFaceProvider, MemoryHub, PublicationTarget],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an hour-long quota delay out of the shared worker's execution path."""
    _, api, target = hub
    commit = api.create_commit
    waits: list[float] = []
    response = httpx.Response(
        429,
        headers={"Retry-After": "3600"},
        request=httpx.Request("POST", "https://hub.test/commit"),
    )

    def limited(**kwargs: Any) -> Any:
        """Reject one snapshot while allowing other ready uploads."""
        if any(
            operation.path_in_repo == "bad.bin" for operation in kwargs["operations"]
        ):
            raise HfHubHTTPError("quota exceeded", response=response)
        return commit(**kwargs)

    monkeypatch.setattr(api, "create_commit", limited)
    monkeypatch.setattr("viper.huggingface.time.sleep", waits.append)
    bad = _snapshot(tmp_path, "bad.bin", b"retry later")
    good = _snapshot(tmp_path, "good.bin", b"upload now")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(bad.inventory, locations=bad.locations)
        session.admit(good.inventory, locations=good.locations)
    started = time.time()
    drain_once(tmp_path)
    key = document_digest(bad.inventory.source)
    job = load_job(session.operation_path.parent / "jobs" / f"{key}.json")
    assert not waits
    assert job.attempts == 1 and job.status == "pending"
    assert job.ready_at >= started + 3601
    assert (
        len(read_publication_copies(session.operation_path, good.inventory.source)) == 1
    )


def test_completed_observations_and_an_active_worker_do_not_spawn_waiters(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observe many generation acknowledgments without creating blocked processes."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    calls: list[object] = []
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
        monkeypatch.setattr(
            _offload, "start_publication_worker", lambda *a, **k: calls.append(a)
        )
        descriptor = os.open(
            session.operation_path.parents[1] / ".worker.lock",
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            with pytest.raises(TimeoutError):
                read_publication_copies(
                    session.operation_path,
                    record.inventory.source,
                    wait=True,
                    timeout_seconds=0,
                )
        finally:
            os.close(descriptor)
        assert not calls
        drain_once(tmp_path)
        for _ in range(5):
            assert (
                len(
                    read_publication_copies(
                        session.operation_path, record.inventory.source, wait=True
                    )
                )
                == 1
            )
        assert not calls


def test_third_final_receipt_attempt_stays_pending_until_the_transfer_finishes(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid declaring failure while the final permitted upload is succeeding."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
    with operation_lock(session.operation_path):
        operation = load_operation(session.operation_path)
        save_operation(
            session.operation_path,
            operation.model_copy(update={"final_attempts": 2}),
        )
    publish = _offload_worker._publish_snapshot
    observed: list[str] = []

    def inspect(*args: Any, **kwargs: Any) -> Any:
        """Observe status from inside the actual final receipt transfer."""
        inventory = args[2]
        if inventory.source_files[0].path.endswith("/receipt.json"):
            observed.append(read_publication_status(session.operation_path)["status"])
        return publish(*args, **kwargs)

    monkeypatch.setattr(_offload_worker, "_publish_snapshot", inspect)
    drain_once(tmp_path)
    assert observed == ["pending"]
    assert read_publication_status(session.operation_path)["status"] == "complete"


def test_completed_jobs_and_history_are_not_reparsed_or_unpinned_every_pass(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a long workflow's idle worker from repeatedly revisiting verified work."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    completed = {}
    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
        drain_once(tmp_path, completed=completed)
        reads: list[Path] = []
        unpins: list[str] = []
        load = _offload_worker.load_job
        monkeypatch.setattr(
            _offload_worker,
            "load_job",
            lambda path: (reads.append(path), load(path))[1],
        )
        monkeypatch.setattr(
            StorageRegistry, "unpin_source", lambda self, key: unpins.append(key)
        )
        drain_once(tmp_path, completed=completed)
        assert not reads and not unpins
    drain_once(tmp_path, completed=completed)
    reads.clear()
    drain_once(tmp_path, completed=completed)
    assert not reads and not unpins


@pytest.mark.parametrize("change", ("changed", "missing", "extra"))
def test_captured_sources_are_checked_before_intent_or_provider_io(
    tmp_path: Path,
    target: PublicationTarget,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """Reject changed payloads or membership before recording an upload intent."""
    provider = _cloud(tmp_path, target, monkeypatch)
    cloud = ViperCloud(tmp_path, target.repository, provider=provider)
    sources = {
        "config.json": tmp_path / "config.json",
        "weights.bin": tmp_path / "weights.bin",
    }
    sources["config.json"].write_bytes(b"{}")
    sources["weights.bin"].write_bytes(b"weights")
    members = tuple(
        source_file(tmp_path, name, path) for name, path in sorted(sources.items())
    )
    inventory = SnapshotInventory(
        source=LocalStageResultSnapshotRef(
            workspace=tmp_path, commit=manifest_revision(members)
        ),
        source_files=members,
    )
    if change == "changed":
        sources["weights.bin"].write_bytes(b"WEIGHTS")
    elif change == "missing":
        del sources["weights.bin"]
    else:
        extra = tmp_path / "extra.bin"
        extra.write_bytes(b"unexpected")
        sources["extra.bin"] = extra
    journal_path = tmp_path / "publication.json"
    with PublicationJournal(
        journal_path, "a" * 64, cloud, target.destination
    ) as journal:
        with pytest.raises(RunPromotionError, match="inventory"):
            publish_captured_snapshot(journal, inventory, dict(sources))
        assert journal.progress.copies == {}
        assert not journal_path.exists()
    assert not provider.upload_calls
    assert provider.seal_calls == 0
    assert not provider.fetch_to_path_calls


def test_remote_hash_mismatch_leaves_captured_intent_unpublished(
    tmp_path: Path,
    hub: tuple[HuggingFaceProvider, MemoryHub, PublicationTarget],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the source and pending intent when actual remote verification fails."""
    provider, api, target = hub
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    cloud = ViperCloud(tmp_path, target.repository, provider=provider)
    provider.stream_files = True
    publish = provider.publish_revision

    def corrupt_remote(**kwargs: Any) -> Any:
        """Change committed payload bytes while retaining their original manifest."""
        snapshot = publish(**kwargs)
        api.commits[snapshot.commit]["weights.bin"] = b"WEIGHTS"
        return snapshot

    monkeypatch.setattr(provider, "publish_revision", corrupt_remote)
    path = tmp_path / "publication.json"
    key = document_digest(record.inventory.source)
    with PublicationJournal(path, "b" * 64, cloud, target.destination) as journal:
        with pytest.raises(ViperCloudError, match="identity changed"):
            publish_captured_snapshot(
                journal, record.inventory, {"weights.bin": tmp_path / "weights.bin"}
            )
        assert journal.progress.copies[key].published is None
    assert api.head != "0" * 40
    with PublicationJournal(path, "b" * 64, cloud, target.destination) as saved:
        assert saved.progress.copies[key].published is None
        assert saved.progress.copies[key].source_files == record.inventory.source_files
    assert (tmp_path / "weights.bin").read_bytes() == b"weights"


def test_failed_durable_admission_does_not_accept_or_pin_the_snapshot(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return a persistence error before accepting work that could be lost."""
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    writer = _offload.write_synchronized
    launches: list[object] = []

    def fail_job_commit(path: Path, raw: bytes) -> None:
        """Fail only the job-file commit, leaving other durable writers unchanged."""
        if path.parent.name == "jobs":
            raise OSError("job storage unavailable")
        writer(path, raw)

    monkeypatch.setattr(_offload, "write_synchronized", fail_job_commit)
    monkeypatch.setattr(
        _offload, "start_publication_worker", lambda *a, **k: launches.append(a)
    )
    with session_scope(tmp_path, targets=(target,)) as session:
        with pytest.raises(OSError, match="job storage unavailable"):
            session.admit(record.inventory, locations=record.locations)
        operation = load_operation(session.operation_path)
        assert not operation.jobs
        assert not tuple((session.operation_path.parent / "jobs").glob("*.json"))
        assert not launches
        registry = StorageRegistry(tmp_path)
        with registry._transaction() as connection:
            assert not registry.source_is_pending(
                record.inventory.source_files[0], connection
            )
        assert registry.snapshot(record.inventory.source) is not None
        assert (tmp_path / "weights.bin").read_bytes() == b"weights"


def test_explicit_wait_restarts_a_drainer_that_dies_after_the_first_probe(
    tmp_path: Path, target: PublicationTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recheck worker liveness while waiting for a real saved job to complete."""
    _cloud(tmp_path, target, monkeypatch)
    record = _snapshot(tmp_path, "weights.bin", b"weights")
    clock = [0.0]
    descriptor: int | None = None
    starts: list[Path] = []

    def progress(seconds: float) -> None:
        """Advance time and release the original worker lock."""
        nonlocal descriptor
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
            clock[0] += 5.1
        else:
            clock[0] += seconds

    def restart(root: Path, **kwargs: Any) -> None:
        """Process the persisted job after the wait API detects the missing worker."""
        starts.append(root)
        drain_once(root)

    with session_scope(tmp_path, targets=(target,)) as session:
        session.admit(record.inventory, locations=record.locations)
        descriptor = os.open(
            session.operation_path.parents[1] / ".worker.lock",
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        monkeypatch.setattr(_offload.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(_offload.time, "sleep", progress)
        monkeypatch.setattr(_offload, "start_publication_worker", restart)
        try:
            copies = read_publication_copies(
                session.operation_path,
                record.inventory.source,
                wait=True,
                timeout_seconds=20,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
        assert len(copies) == 1 and copies[0].published is not None
        assert starts == [tmp_path]
        assert clock[0] >= 5
