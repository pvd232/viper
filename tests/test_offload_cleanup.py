"""Exercise deferred cleanup against real storage, publication proofs and locks."""

from __future__ import annotations

import hashlib
import os
from io import BufferedReader
from pathlib import Path
from threading import Event, Thread
from typing import Any, Literal

import pytest

import viper.execution._offload_worker as worker
from tests.test_storage import InMemoryViperCloudProvider
from viper._cloud import (
    GcsRepository,
    PublicationSource,
    SnapshotCopy,
    SnapshotInventory,
    canonical_json_bytes,
)
from viper._git_proof import capture_git_file_proof
from viper._offload import (
    Operation,
    PublicationJob,
    build_receipt,
    load_job,
    load_operation,
    save_job,
    save_operation,
    session_scope,
)
from viper._source import run_git
from viper._storage_locks import PayloadLocks, WorkflowReaders
from viper.artifacts import ResolvedSingleFileArtifact, StageArtifactRef
from viper.cloud import PublicationReceipt, PublicationTarget, ViperCloud
from viper.execution._promotion_journal import (
    PublicationJournal,
    publish_captured_snapshot,
)
from viper.references import (
    GcsStageResultSnapshotRef,
    GitSource,
    ResolvedGitFileRef,
    SnapshotFileRef,
    resolve_snapshot_file_ref,
)
from viper.retention import RunFileEvictionError, cleanup_operation
from viper.serialization import document_digest, write_synchronized
from viper.storage import LocalArtifactStore, ViperCloudDestination

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class _CleanupCase:
    """Prepare a real registered output and completed copies in two fake clouds."""

    def __init__(
        self,
        root: Path,
        *,
        science_succeeded: bool = True,
        reuse_previous: bool = False,
    ) -> None:
        """Build the persisted state presented to the cleanup worker."""
        self.root = root.resolve(strict=True)
        root = self.root
        (root / "viper.toml").write_text("[storage]\noffload = true\n")
        self.storage = LocalArtifactStore(root)
        self.raw = b"model weights"
        self.source = self.storage.snapshot({"weights.bin": self.raw})
        self.inventory = SnapshotInventory(
            source=self.source,
            source_files=self.storage.snapshot_files(self.source),
        )
        self.member = self.inventory.source_files[0]
        self.reference = resolve_snapshot_file_ref(self.source, self.member)
        self.cache_path = self.storage.resolve(self.reference)
        self.path = (
            root
            / ".viper/workspaces"
            / RUN_ID
            / "attempt-1/stages/train/model/weights.bin"
        )
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(self.raw)
        self.storage.registry.record_materialization(
            self.source, self.member, self.path, custody="output"
        )
        self.selection = StageArtifactRef(stage_id="train", artifact_name="model")
        self.storage.registry.register_artifact(
            self.source,
            self.selection,
            ResolvedSingleFileArtifact(relative_path="weights.bin", file=self.member),
        )
        self.providers: dict[str, InMemoryViperCloudProvider] = {}
        self.targets = tuple(
            PublicationTarget(
                repository=GcsRepository(bucket=f"cloud-{index}"),
                destination=ViperCloudDestination(owner="owner", workspace="models"),
                google_project_id="approved-project",
                gcp_service_account="uploader@approved-project.iam.gserviceaccount.com",
            )
            for index in range(2)
        )
        data_targets = self.targets
        if reuse_previous:
            data_targets = (
                PublicationTarget(
                    repository=GcsRepository(bucket="prior-cloud"),
                    destination=self.targets[0].destination,
                ),
            )
        self.copies = tuple(
            self._publish(self.inventory, {"weights.bin": self.path}, target)
            for target in data_targets
        )
        identifier = "a" * 32
        self.receipt_path = root / ".viper/publications" / identifier / "receipt.json"
        self.receipt_path.parent.mkdir(parents=True)
        self.receipt_path.write_bytes(
            canonical_json_bytes(
                PublicationReceipt(
                    operation_id=identifier,
                    targets=self.targets,
                    science_succeeded=science_succeeded,
                    used=(self.reference,),
                    copies=self.copies,
                )
            )
        )
        relative = self.receipt_path.relative_to(root).as_posix()
        receipt_source = self.storage.snapshot(
            {relative: self.receipt_path.read_bytes()}
        )
        receipt_inventory = SnapshotInventory(
            source=receipt_source,
            source_files=self.storage.snapshot_files(receipt_source),
        )
        finals = tuple(
            self._publish(receipt_inventory, {relative: self.receipt_path}, target)
            for target in self.targets
        )
        registered = self.storage.registry.snapshot(self.source)
        assert registered is not None
        self.operation = Operation.model_validate(
            {
                "operation_id": identifier,
                "repository_root": root,
                "store": self.storage.store,
                "targets": self.targets,
                "closed": True,
                "science_succeeded": science_succeeded,
                "used": (self.reference,),
                "locations": tuple(
                    {"reference": self.reference, "location": location}
                    for location in registered.locations["weights.bin"]
                ),
                "jobs": () if reuse_previous else (document_digest(self.source),),
                "publication_complete": True,
                "final_receipts": finals,
            }
        )

        self.operation_path = self.receipt_path.with_name("operation.json")
        for key in self.operation.jobs:
            path = self.operation_path.parent / "jobs" / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            save_job(
                path,
                PublicationJob(
                    inventory=self.inventory, status="complete", copies=self.copies
                ),
            )
        save_operation(self.operation_path, self.operation)

    def _publish(
        self,
        inventory: SnapshotInventory,
        sources: dict[str, PublicationSource],
        target: PublicationTarget,
    ) -> SnapshotCopy:
        """Create proof through the real journal and an existing fake provider."""
        repository = target.repository
        assert isinstance(repository, GcsRepository)
        if repository.bucket not in self.providers:
            self.providers[repository.bucket] = InMemoryViperCloudProvider(self.root)
        provider = self.providers[repository.bucket]
        provider.bucket = repository.bucket
        provider.prefix = repository.prefix
        cloud = ViperCloud(self.root, repository, provider=provider)
        directory = (
            self.root
            / ".viper/test-publications"
            / repository.bucket
            / document_digest(inventory.source)
        )
        with PublicationJournal(
            directory / "progress.json",
            document_digest(inventory),
            cloud,
            target.destination,
        ) as journal:
            copy = publish_captured_snapshot(journal, inventory, sources)
        proof = directory / "copy.json"
        proof.write_bytes(canonical_json_bytes(copy))
        self.storage.registry.register_backing(
            copy, proof.relative_to(self.root).as_posix()
        )
        return copy

    def cleanup(
        self,
        operation: Operation | None = None,
        copies: tuple[SnapshotCopy, ...] | None = None,
    ) -> bool:
        """Invoke the worker entry point with the saved proof and locations."""
        current = operation or self.operation
        save_operation(self.operation_path, current)
        return bool(
            cleanup_operation(
                self.root,
                current.model_dump(mode="json"),
                self.copies if copies is None else copies,
            )
        )


@pytest.fixture
def cleanup_case(tmp_path: Path) -> _CleanupCase:
    """Provide a completed operation whose local output has not been released."""
    return _CleanupCase(tmp_path)


def test_cleanup_releases_original_and_cache_without_reopening_cloud(
    cleanup_case: _CleanupCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completed proof permits release while references and inventory survive."""
    case = cleanup_case
    before = case.reference.model_dump(mode="json")
    receipt = case.receipt_path.read_bytes()

    def reject_cloud(*_args: object, **_kwargs: object) -> None:
        """Reject any new cloud-client creation during cleanup."""
        pytest.fail("cleanup reopened the cloud after verified publication")

    monkeypatch.setattr(ViperCloud, "_create_provider", reject_cloud)

    assert case.cleanup()
    assert not case.path.exists()
    assert not case.cache_path.exists()
    assert case.reference.model_dump(mode="json") == before
    assert case.receipt_path.read_bytes() == receipt
    assert LocalArtifactStore(case.root).snapshot_files(case.source) == (case.member,)


@pytest.mark.parametrize("field", ("closed", "publication_complete"))
def test_an_open_or_unpublished_operation_preserves_local_files(
    cleanup_case: _CleanupCase, field: str
) -> None:
    """Uploaded files alone cannot finish a still-open or unpublished workflow."""
    case = cleanup_case
    pending = case.operation.model_copy(update={field: False})

    assert not case.cleanup(pending)
    assert case.path.read_bytes() == case.raw
    assert case.cache_path.read_bytes() == case.raw
    assert case.cleanup()


def test_failed_whole_workflow_preserves_even_verified_outputs(
    tmp_path: Path,
) -> None:
    """A successful upload does not turn failed science into cleanup permission."""
    case = _CleanupCase(tmp_path, science_succeeded=False)

    assert not case.cleanup()
    assert case.path.read_bytes() == case.raw
    assert case.cache_path.read_bytes() == case.raw


def test_every_target_needs_final_and_data_proof(
    cleanup_case: _CleanupCase,
) -> None:
    """One successful destination cannot authorize releasing two-target work."""
    case = cleanup_case
    incomplete = case.operation.model_copy(
        update={"final_receipts": case.operation.final_receipts[:-1]}
    )

    assert not case.cleanup(incomplete)
    with pytest.raises(RunFileEvictionError):
        case.cleanup(copies=case.copies[:-1])
    assert case.path.read_bytes() == case.raw
    assert case.cache_path.read_bytes() == case.raw
    assert case.cleanup()


def test_changed_final_receipt_cannot_authorize_deletion(
    cleanup_case: _CleanupCase,
) -> None:
    """Equivalent JSON with changed bytes still fails the immutable receipt."""
    case = cleanup_case
    case.receipt_path.write_bytes(case.receipt_path.read_bytes() + b"\n")

    with pytest.raises(RunFileEvictionError):
        case.cleanup()
    assert case.path.read_bytes() == case.raw
    assert case.cache_path.read_bytes() == case.raw


def test_new_keep_defeats_a_previously_queued_cleanup(
    cleanup_case: _CleanupCase,
) -> None:
    """Cleanup reads the newer artifact preference instead of saved permission."""
    case = cleanup_case
    registry = case.storage.registry
    registry.set_retention(case.source, case.selection, "keep")

    assert not case.cleanup()
    assert case.path.read_bytes() == case.raw
    assert case.cache_path.read_bytes() == case.raw
    registry.set_retention(case.source, case.selection, "offload")
    assert case.cleanup()


def test_inherit_reads_current_global_setting(
    cleanup_case: _CleanupCase,
) -> None:
    """Changing the global default after queueing takes effect at deletion."""
    case = cleanup_case
    settings = case.root / "viper.toml"
    settings.write_text("[storage]\noffload = false\n")

    assert not case.cleanup()
    assert case.path.exists()
    settings.write_text("[storage]\noffload = true\n")
    assert case.cleanup()


def test_an_overlapping_reader_outlives_the_first_workflow(
    cleanup_case: _CleanupCase,
) -> None:
    """Closing one reader cannot release a file another workflow still uses."""
    case = cleanup_case
    locks = PayloadLocks(case.root)
    first, second = WorkflowReaders(locks), WorkflowReaders(locks)
    try:
        first.hold(case.reference)
        second.hold(case.reference)
        first.close()
        assert not case.cleanup()
        assert case.path.read_bytes() == case.raw
    finally:
        first.close()
        second.close()

    assert case.cleanup()
    assert not case.path.exists()


def test_a_keep_subscriber_in_another_snapshot_protects_shared_bytes(
    cleanup_case: _CleanupCase,
) -> None:
    """Retention votes follow shared contents across distinct artifact versions."""
    case = cleanup_case
    other = case.storage.snapshot({"another/model.bin": case.raw})
    member = case.storage.snapshot_files(other)[0]
    selector = StageArtifactRef(stage_id="train", artifact_name="other")
    case.storage.registry.register_artifact(
        other,
        selector,
        ResolvedSingleFileArtifact(relative_path="another/model.bin", file=member),
    )
    case.storage.registry.set_retention(case.source, case.selection, "offload")
    case.storage.registry.set_retention(other, selector, "keep")

    assert not case.cleanup()
    assert case.path.read_bytes() == case.raw
    case.storage.registry.set_retention(other, selector, "offload")
    assert case.cleanup()


@pytest.mark.parametrize("status", ("pending", "failed"))
def test_another_operations_unfinished_upload_pins_the_source(
    cleanup_case: _CleanupCase, status: Literal["pending", "failed"]
) -> None:
    """A durable pending or failed publication protects bytes between workers."""
    case = cleanup_case
    key = document_digest(case.source)
    other_id = "b" * 32
    path = case.root / ".viper/publications" / other_id / "jobs" / f"{key}.json"
    path.parent.mkdir(parents=True)
    job = PublicationJob(
        inventory=case.inventory,
        status=status,
        error="storage unavailable" if status == "failed" else None,
    )
    save_job(path, job)
    pin = f"{other_id}/{key}"
    case.storage.registry.pin_source(case.source, pin)

    assert not case.cleanup()
    assert case.path.read_bytes() == case.raw
    save_job(path, job.model_copy(update={"status": "complete", "copies": case.copies}))
    case.storage.registry.unpin_source(pin)
    assert case.cleanup()


def test_a_replacement_with_identical_bytes_survives_stale_cleanup(
    cleanup_case: _CleanupCase,
) -> None:
    """Matching hashes cannot authorize deleting a different physical file."""
    case = cleanup_case
    replacement = case.path.with_name("replacement.bin")
    replacement.write_bytes(case.raw)
    inode = replacement.stat().st_ino
    replacement.replace(case.path)

    case.cleanup()

    assert case.path.read_bytes() == case.raw
    assert case.path.stat().st_ino == inode


def test_cleanup_keeps_an_unregistered_sibling_in_the_attempt_workspace(
    cleanup_case: _CleanupCase,
) -> None:
    """Removing managed outputs never recursively removes unrelated files."""
    case = cleanup_case
    unrelated = case.path.parent / "user-notes.txt"
    unrelated.write_text("keep these notes")

    assert case.cleanup()
    assert not case.path.exists()
    assert unrelated.read_text() == "keep these notes"


def test_cleanup_preserves_a_registered_external_copy(
    cleanup_case: _CleanupCase,
) -> None:
    """Cloud backing and offload permission do not transfer file ownership."""
    case = cleanup_case
    external = case.root / "user-dataset.csv"
    external.write_bytes(case.raw)
    location = case.storage.registry.record_materialization(
        case.source, case.member, external, custody="external"
    )
    value = case.operation.model_dump(mode="json")
    value["locations"].append(
        {
            "reference": case.reference.model_dump(mode="json"),
            "location": location.model_dump(mode="json"),
        }
    )

    assert case.cleanup(Operation.model_validate(value))
    assert external.read_bytes() == case.raw
    assert not case.path.exists()


def test_prior_cloud_proof_releases_a_read_copy_without_new_data_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only workflow can reuse backing outside its current destinations."""
    case = _CleanupCase(tmp_path, reuse_previous=True)
    transfers = {
        bucket: (len(provider.upload_calls), len(provider.fetch_to_path_calls))
        for bucket, provider in case.providers.items()
    }

    def reject_cloud(*_args: object, **_kwargs: object) -> None:
        """Reject transfer or full verification through a new cloud client."""
        pytest.fail("cleanup reopened previously verified cloud backing")

    monkeypatch.setattr(ViperCloud, "_create_provider", reject_cloud)

    assert case.cleanup()
    assert not case.path.exists()
    assert not case.cache_path.exists()
    assert {
        bucket: (len(provider.upload_calls), len(provider.fetch_to_path_calls))
        for bucket, provider in case.providers.items()
    } == transfers


@pytest.mark.parametrize("reference_kind", ("cloud", "git"))
def test_verified_cloud_read_offloads_with_portable_file_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference_kind: Literal["cloud", "git"],
) -> None:
    """One verified download needs no fabricated proof for unread snapshot files."""
    root = tmp_path.resolve(strict=True)
    (root / "viper.toml").write_text("[storage]\noffload = true\n")
    provider = InMemoryViperCloudProvider(root)
    cloud = ViperCloud(root, GcsRepository(bucket=provider.bucket), provider=provider)
    references = cloud.resolved_files(
        ViperCloudDestination(owner="owner", workspace="existing"),
        {"cloud/weights.bin": b"weights", "cloud/unread.bin": b"unread"},
    )
    remote = references["cloud/weights.bin"]
    storage = LocalArtifactStore(root)
    path = storage.resolve(remote, cloud=cloud)
    cloud_source = GcsStageResultSnapshotRef.model_validate(
        remote.stored_at.model_dump(exclude={"path"})
    )
    source: GcsStageResultSnapshotRef | GitSource = cloud_source
    reference = remote
    git_reference: ResolvedGitFileRef | None = None
    assert storage.registry.backings(cloud_source) == ()
    assert remote in storage.registry.file_backings(reference)
    if reference_kind == "git":
        (root / "data").mkdir()
        (root / "data/weights.bin").write_bytes(b"weights")
        for args in (
            ("init", "--quiet"),
            ("config", "user.name", "Viper cleanup test"),
            ("config", "user.email", "viper@example.test"),
            ("add", "data/weights.bin"),
            ("commit", "--quiet", "-m", "source fixture"),
        ):
            run_git(root, *args)
        source = GitSource(
            repository="https://example.com/source.git",
            commit=run_git(root, "rev-parse", "HEAD").decode().strip(),
        )
        member = SnapshotFileRef(
            path="data/weights.bin", sha256=remote.sha256, bytes=remote.bytes
        )
        reference = resolve_snapshot_file_ref(source, member)
        git_reference = ResolvedGitFileRef.model_validate(reference.model_dump())
        proof = capture_git_file_proof(
            git_reference, lambda kind, oid: run_git(root, "cat-file", kind, oid)
        )
        storage.registry.register_git_file(proof, b"weights")
    record = storage.registry.snapshot(cloud_source)
    assert record is not None
    operation = Operation.model_validate(
        {
            "operation_id": "c" * 32,
            "repository_root": root,
            "store": storage.store,
            "targets": (),
            "closed": True,
            "science_succeeded": True,
            "publication_complete": True,
            "used": (reference,),
            "locations": tuple(
                {"reference": reference, "location": location}
                for location in record.locations[remote.stored_at.path]
            ),
        }
    )
    transfers = len(provider.upload_calls), len(provider.fetch_to_path_calls)

    def reject_cloud(*_args: object, **_kwargs: object) -> None:
        """Reject a second transfer or whole-snapshot verification."""
        pytest.fail("verified read reopened the cloud during receipt or cleanup")

    monkeypatch.setattr(ViperCloud, "_create_provider", reject_cloud)
    receipt = build_receipt(operation, ())
    assert receipt.copies == ()
    assert remote in receipt.file_copies

    assert cleanup_operation(root, operation.model_dump(mode="json"), ())
    assert not path.exists()
    assert (len(provider.upload_calls), len(provider.fetch_to_path_calls)) == transfers
    if git_reference is not None:
        assert storage.registry.git_file_proof(git_reference.stored_at) is not None
        assert (root / "data/weights.bin").read_bytes() == b"weights"


def test_checkpoint_hashing_does_not_block_a_new_reader(
    cleanup_case: _CleanupCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readers can start while background cleanup checks a large file."""
    case = cleanup_case
    started, resume, reader_ready, reader_done = (Event() for _ in range(4))
    real_digest = hashlib.file_digest
    results: list[bool] = []
    errors: list[BaseException] = []

    def paused_digest(stream: BufferedReader, algorithm: str) -> Any:
        """Pause the real digest operation to make the overlap deterministic."""
        started.set()
        assert resume.wait(5)
        return real_digest(stream, algorithm)

    def clean() -> None:
        """Run the actual cleanup entry point in its background thread."""
        try:
            results.append(case.cleanup())
        except BaseException as error:
            errors.append(error)

    def read() -> None:
        """Read the original while holding the real shared content lock."""
        try:
            with WorkflowReaders(PayloadLocks(case.root)) as readers:
                readers.hold(case.reference)
                assert case.path.read_bytes() == case.raw
                reader_ready.set()
                assert reader_done.wait(5)
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr("viper.retention.hashlib.file_digest", paused_digest)
    worker = Thread(target=clean)
    reader = Thread(target=read)
    worker.start()
    try:
        assert started.wait(5)
        reader.start()
        assert reader_ready.wait(2), "reader waited for the checkpoint hash"
        resume.set()
        worker.join(5)
        assert not worker.is_alive()
        assert results == [False]
        assert case.path.read_bytes() == case.raw
    finally:
        resume.set()
        reader_done.set()
        worker.join(5)
        if reader.ident is not None:
            reader.join(5)
    assert not errors
    assert case.cleanup()


def test_cleanup_removes_both_selected_hardlinks_after_ctime_changes(
    tmp_path: Path,
) -> None:
    """Unlink every authorized alias without treating link metadata as replacement."""
    case = _CleanupCase(tmp_path)
    record = case.storage.registry.snapshot(case.source)
    assert record is not None
    previous = next(
        location
        for location in record.locations[case.member.path]
        if location.custody == "output"
    )
    case.storage.registry.retire_materialization(previous)
    case.path.unlink()
    os.link(case.cache_path, case.path)
    case.storage.registry.record_materialization(
        case.source, case.member, case.cache_path, custody="cache"
    )
    case.storage.registry.record_materialization(
        case.source, case.member, case.path, custody="output"
    )
    current = case.storage.registry.snapshot(case.source)
    assert current is not None
    operation = case.operation.model_copy(update={"locations": tuple()})
    document = operation.model_dump(mode="json")
    document["locations"] = [
        {
            "reference": case.reference.model_dump(mode="json"),
            "location": location.model_dump(mode="json"),
        }
        for location in current.locations[case.member.path]
    ]
    operation = Operation.model_validate(document)
    save_operation(case.operation_path, operation)
    assert case.path.stat().st_ino == case.cache_path.stat().st_ino
    assert cleanup_operation(tmp_path, operation.model_dump(mode="json"), case.copies)
    assert not case.path.exists()
    assert not case.cache_path.exists()


def test_worker_runs_cleanup_after_verified_publication(cleanup_case, monkeypatch):
    """Release in the worker using existing proof without new cloud operations."""
    case = cleanup_case
    monkeypatch.setattr(
        ViperCloud,
        "_create_provider",
        lambda *args: pytest.fail("cleanup reopened cloud"),
    )
    assert case.path.exists() and case.cache_path.exists()
    worker.drain_once(case.root)
    assert load_operation(case.operation_path).cleanup_complete
    assert not case.path.exists() and not case.cache_path.exists()


def test_ready_uploads_precede_deferred_cleanup(cleanup_case, monkeypatch):
    """Let a ready publication run before inspecting older eligible payloads."""
    case = cleanup_case
    events = []
    original_publish = worker._publish_job
    original_cleanup = worker.cleanup_operation

    def publish(*args):
        events.append("upload")
        return original_publish(*args)

    def cleanup(*args):
        events.append("cleanup")
        return original_cleanup(*args)

    def cloud(cls, root, target):
        return ViperCloud(
            root, target.repository, provider=case.providers[target.repository.bucket]
        )

    monkeypatch.setattr(worker, "_publish_job", publish)
    monkeypatch.setattr(worker, "cleanup_operation", cleanup)
    monkeypatch.setattr(ViperCloud, "for_target", classmethod(cloud))
    with session_scope(case.root, targets=case.targets) as session:
        source = case.storage.snapshot({"later.bin": b"later payload"})
        job_path = (
            session.operation_path.parent / "jobs" / (document_digest(source) + ".json")
        )
        worker.drain_once(case.root)
        assert load_job(job_path).status == "complete"
        assert events.index("upload") < events.index("cleanup")
        assert not case.path.exists()


def test_worker_retries_after_last_reader_without_registry_changes(cleanup_case):
    """A released reader hold makes deferred cleanup eligible in the same worker."""
    case = cleanup_case
    readers = WorkflowReaders(PayloadLocks(case.root))
    readers.hold(case.reference)
    seen = set()
    try:
        assert worker.drain_once(case.root, cleanup_seen=seen) is not None
        assert case.path.exists() and case.cache_path.exists()
        registry_time = case.storage.registry.path.stat().st_mtime_ns
    finally:
        readers.close()
    assert case.storage.registry.path.stat().st_mtime_ns == registry_time
    assert worker.drain_once(case.root, cleanup_seen=seen) is None
    assert load_operation(case.operation_path).cleanup_complete
    assert not case.path.exists() and not case.cache_path.exists()


def test_worker_memoizes_mixed_keep_and_rechecks_changed_preference(cleanup_case):
    """A kept file defers cleanup without polling and remains offloadable later."""
    case = cleanup_case
    save_operation(
        case.operation_path,
        case.operation.model_copy(update={"cleanup_complete": True}),
    )
    source = case.storage.snapshot({"keep.bin": b"training data"})
    inventory = SnapshotInventory(
        source=source, source_files=case.storage.snapshot_files(source)
    )
    member = inventory.source_files[0]
    reference = resolve_snapshot_file_ref(source, member)
    path = case.storage.resolve(reference)
    case._publish(inventory, {member.path: path}, case.targets[0])
    case.storage.registry.register_artifact(
        source,
        member.path,
        ResolvedSingleFileArtifact(relative_path=member.path, file=member),
    )
    case.storage.registry.set_retention(source, member.path, "keep")
    registered = case.storage.registry.snapshot(source)
    assert registered is not None
    locations = [*case.operation.locations]
    locations.extend(
        {"reference": reference, "location": location}
        for location in registered.locations[member.path]
    )
    operation = Operation(
        operation_id="b" * 32,
        repository_root=case.root,
        store=case.storage.store,
        targets=(),
        closed=True,
        science_succeeded=True,
        used=(case.reference, reference),
        locations=tuple(locations),
        publication_complete=True,
    )
    operation_path = (
        case.root / ".viper/publications" / operation.operation_id / "operation.json"
    )
    write_synchronized(
        operation_path.with_name("receipt.json"),
        canonical_json_bytes(build_receipt(operation, ())),
    )
    save_operation(operation_path, operation)
    seen = set()
    assert worker.drain_once(case.root, cleanup_seen=seen) is None
    assert not case.path.exists() and not case.cache_path.exists()
    assert path.exists()
    assert not load_operation(operation_path).cleanup_complete
    registry_time = case.storage.registry.path.stat().st_mtime_ns
    assert worker.drain_once(case.root, cleanup_seen=seen) is None
    assert registry_time == case.storage.registry.path.stat().st_mtime_ns
    case.storage.registry.set_retention(source, member.path, "offload")
    assert worker.drain_once(case.root, cleanup_seen=seen) is None
    assert not path.exists()
    assert load_operation(operation_path).cleanup_complete
