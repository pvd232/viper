"""Check portable restoration, exact Git fallback and synchronous publication."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from viper import _offload, _source
from viper._cloud import (
    GcsRepository,
    PublicationSource,
    RevisionManifest,
    SnapshotCopy,
    SnapshotInventory,
    ViperCloudDestination,
    manifest_revision,
)
from viper._source import RunFetcher
from viper._storage_locks import PayloadLocks
from viper._storage_registry import StorageRegistryError
from viper.cloud import PublicationReceipt, PublicationTarget, ViperCloud
from viper.evidence import VerificationError
from viper.references import (
    CloudFileRef,
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    GitSource,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from viper.retention import set_artifact_retention
from viper.storage import (
    LocalArtifactStore,
    LocalSnapshotPublisher,
    LocalStorageDestination,
    StorageConfigurationError,
    import_publication_copies,
    import_publication_receipt,
    publish_resolved_files,
    snapshot_file,
    workflow,
)


class MemoryCloud:
    """Keep real file identities while replacing cloud I/O with local bytes."""

    def __init__(self, root: Path, files: dict[str, bytes]) -> None:
        """Bind one complete remote snapshot and count verified transfers."""
        self.root = root
        self.files = files
        self.members = tuple(
            snapshot_file(name, raw) for name, raw in sorted(files.items())
        )
        self.snapshot = GcsStageResultSnapshotRef(
            bucket="viper-recovery",
            owner="owner",
            workspace="models",
            revision=manifest_revision(self.members),
        )
        self.repository = GcsRepository(bucket=self.snapshot.bucket)
        self.provider = object()
        self.downloads = 0

    def list_files(self, snapshot: object) -> tuple[SnapshotFileRef, ...]:
        """Return the immutable remote inventory."""
        assert snapshot == self.snapshot
        return self.members

    def fetch_to_path(self, reference: ResolvedFileRef, destination: Path) -> Path:
        """Verify downloaded bytes before exposing the completed file."""
        self.downloads += 1
        raw = self.files[reference.stored_at.path]
        destination.write_bytes(raw)
        if (
            len(raw) != reference.bytes
            or hashlib.sha256(raw).hexdigest() != reference.sha256
        ):
            raise VerificationError("cloud SHA-256 or size mismatch")
        return destination

    def resolved_files(
        self,
        destination: ViperCloudDestination,
        sources: Mapping[str, PublicationSource],
    ) -> dict[str, ResolvedFileRef]:
        """Return the exact references only when publication has completed."""
        assert (destination.owner, destination.workspace) == ("owner", "models")
        assert set(sources) == set(self.files)
        return {
            member.path: resolve_snapshot_file_ref(self.snapshot, member)
            for member in self.members
        }


def _copy(root: Path, files: dict[str, bytes]) -> tuple[SnapshotCopy, MemoryCloud]:
    """Describe an original snapshot whose producing workspace is unavailable."""
    cloud = MemoryCloud(root, files)
    source = LocalStageResultSnapshotRef(
        workspace=root / "removed-producer", commit=manifest_revision(cloud.members)
    )
    expected = RevisionManifest(
        owner="owner", workspace="models", revision=source.commit, files=cloud.members
    )
    return SnapshotCopy(
        source=source,
        source_files=cloud.members,
        expected=expected,
        dependencies_sha256=hashlib.sha256(b"[]").hexdigest(),
        previous_head=None,
        published=cloud.snapshot,
    ), cloud


def _services(monkeypatch: pytest.MonkeyPatch, cloud: MemoryCloud) -> None:
    """Replace service construction without bypassing transfer identity checks."""

    def snapshot_service(
        cls: type[ViperCloud], root: Path, snapshot: CloudStageResultSnapshotRef
    ) -> ViperCloud:
        """Use the same immutable remote fixture for metadata and bytes."""
        assert snapshot == cloud.snapshot
        return cast(ViperCloud, cloud)

    def file_service(
        cls: type[ViperCloud], root: Path, reference: CloudFileRef
    ) -> ViperCloud:
        """Keep restored file requests on the expected repository."""
        assert ViperCloud._repository_for(reference) == cloud.repository
        return cast(ViperCloud, cloud)

    monkeypatch.setattr(ViperCloud, "for_snapshot", classmethod(snapshot_service))
    monkeypatch.setattr(ViperCloud, "for_reference", classmethod(file_service))


def _snapshot(reference: ResolvedFileRef) -> StageResultSnapshotRef:
    """Recover a local raw publication's containing snapshot."""
    return LocalStageResultSnapshotRef.model_validate(
        reference.stored_at.model_dump(exclude={"path"})
    )


def test_import_restores_unchanged_references_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh workspace restores complete copies without the producer directory."""
    copy, cloud = _copy(
        tmp_path, {"model/config.json": b"{}", "model/weights.pt": b"weights"}
    )
    _services(monkeypatch, cloud)
    reference = resolve_snapshot_file_ref(copy.source, copy.source_files[1])
    original = reference.model_dump(mode="json")

    import_publication_copies(tmp_path, (copy.model_dump(mode="json"),))
    store = LocalArtifactStore(tmp_path)
    assert cloud.downloads == 2
    assert store.list_snapshot_files(
        cast(LocalStageResultSnapshotRef, copy.source)
    ) == ("model/config.json", "model/weights.pt")
    assert store.resolve(reference).read_bytes() == b"weights"
    assert cloud.downloads == 2
    assert reference.model_dump(mode="json") == original
    assert not (tmp_path / "removed-producer").exists()

    import_publication_copies(tmp_path, (copy,))
    assert cloud.downloads == 2


def test_receipt_preserves_another_snapshot_inventory_for_shared_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy of shared bytes also restores differently named original members."""
    copy, cloud = _copy(tmp_path, {"backup/weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    member = snapshot_file("different/model.pt", b"weights")
    source = LocalStageResultSnapshotRef(
        workspace=tmp_path / "other-removed-producer",
        commit=manifest_revision((member,)),
    )
    reference = resolve_snapshot_file_ref(source, member)
    receipt = PublicationReceipt(
        operation_id="a" * 32,
        targets=(),
        science_succeeded=True,
        used=(reference,),
        copies=(copy,),
        inventories=(SnapshotInventory(source=source, source_files=(member,)),),
    )

    import_publication_receipt(tmp_path, receipt.model_dump(mode="json"))
    store = LocalArtifactStore(tmp_path)
    assert store.list_snapshot_files(source) == ("different/model.pt",)
    assert store.resolve(reference).read_bytes() == b"weights"
    assert reference.stored_at.path == "different/model.pt"
    assert cloud.downloads == 1


def test_receipt_imports_individual_file_proofs_without_claiming_full_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verified cloud file backs shared bytes without a fabricated snapshot proof."""
    _, cloud = _copy(tmp_path, {"remote/source.pt": b"weights"})
    _services(monkeypatch, cloud)
    remote = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    member = snapshot_file("local/model.pt", b"weights")
    source = LocalStageResultSnapshotRef(
        workspace=tmp_path / "gone", commit=manifest_revision((member,))
    )
    reference = resolve_snapshot_file_ref(source, member)
    receipt = PublicationReceipt(
        operation_id="b" * 32,
        targets=(),
        science_succeeded=True,
        used=(reference,),
        copies=(),
        file_copies=(remote,),
        inventories=(SnapshotInventory(source=source, source_files=(member,)),),
    )

    import_publication_receipt(tmp_path, receipt)
    store = LocalArtifactStore(tmp_path)
    assert store.resolve(reference).read_bytes() == b"weights"
    assert store.registry.backings(source) == ()
    assert store.registry.file_backings(reference) == (remote,)
    assert cloud.downloads == 1


def test_git_fallback_uses_shared_bytes_without_partial_git_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unavailable Git origin falls back by exact hash to an auxiliary copy."""
    copy, cloud = _copy(tmp_path, {"backup/module.py": b"x = 1\n"})
    _services(monkeypatch, cloud)
    import_publication_copies(tmp_path, (copy,))
    store = LocalArtifactStore(tmp_path)
    store.resolve(resolve_snapshot_file_ref(copy.source, copy.source_files[0])).unlink()
    location = GitFileRef(
        repository="https://example.com/source.git",
        commit="a" * 40,
        path="src/module.py",
    )
    reference = ResolvedFileRef(
        stored_at=location,
        sha256=copy.source_files[0].sha256,
        bytes=copy.source_files[0].bytes,
    )

    def missing_git(root: Path, *arguments: str) -> bytes:
        """Model an unavailable original commit."""
        raise VerificationError("Git source unavailable")

    monkeypatch.setattr(_source, "run_git", missing_git)
    fetcher = RunFetcher(tmp_path, store, str(location.repository))
    assert fetcher.read(reference) == b"x = 1\n"
    git_source = GitSource(repository=location.repository, commit=location.commit)
    assert store.registry.snapshot(git_source) is None
    assert reference.stored_at == location
    assert cloud.downloads == 2


def test_available_git_is_checked_before_cloud_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wrong bytes from an available Git source fail instead of hiding corruption."""
    raw = b"expected"
    location = GitFileRef(
        repository="https://example.com/source.git", commit="a" * 40, path="module.py"
    )
    reference = ResolvedFileRef(
        stored_at=location, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
    )
    store = LocalArtifactStore(tmp_path)
    fetcher = RunFetcher(tmp_path, store, str(location.repository))
    monkeypatch.setattr(_source, "run_git", lambda *args: b"different")

    def forbidden(*args: object, **kwargs: object) -> tuple[bytes, Path]:
        """Reject any fallback after successful but inconsistent Git retrieval."""
        raise AssertionError("corrupt Git bytes triggered cloud fallback")

    monkeypatch.setattr(store, "read_resolved", forbidden)
    with pytest.raises(VerificationError):
        fetcher.read(reference)


def test_explicit_attached_target_is_used_without_default_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Portable import preserves the explicitly requested attached identity."""
    copy, cloud = _copy(tmp_path, {"weights.pt": b"weights"})
    target = PublicationTarget(
        repository=cloud.repository,
        destination=ViperCloudDestination(owner="owner", workspace="models"),
        google_project_id="project-one",
        gcp_service_account="worker@example.iam.gserviceaccount.com",
    )
    observed = []

    def attached(
        cls: type[ViperCloud], root: Path, selected: PublicationTarget
    ) -> ViperCloud:
        """Observe the exact account and project supplied to the client factory."""
        observed.append(selected)
        return cast(ViperCloud, cloud)

    def forbidden(*args: object, **kwargs: object) -> ViperCloud:
        """Reject ambient credential fallback."""
        raise AssertionError("default cloud constructor was used")

    monkeypatch.setattr(ViperCloud, "for_target", classmethod(attached))
    monkeypatch.setattr(ViperCloud, "for_snapshot", classmethod(forbidden))
    import_publication_copies(tmp_path, (copy,), targets=(target,))
    assert observed == [target]
    assert cloud.downloads == 1


def test_unmatched_target_rejects_import_before_any_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit target cannot silently redirect to ambient credentials."""
    copy, cloud = _copy(tmp_path, {"weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    wrong = PublicationTarget(
        repository=GcsRepository(bucket="different-bucket"),
        destination=ViperCloudDestination(owner="owner", workspace="models"),
    )
    with pytest.raises(StorageConfigurationError, match="does not match"):
        import_publication_copies(tmp_path, (copy,), targets=(wrong,))
    assert cloud.downloads == 0
    assert not LocalArtifactStore(tmp_path).registry.path.exists()


def test_failed_remote_hash_check_does_not_register_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching manifest cannot make corrupt remote payloads into verified proof."""
    copy, cloud = _copy(tmp_path, {"weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    cloud.files["weights.pt"] = b"changed"
    with pytest.raises(VerificationError, match="SHA-256"):
        import_publication_copies(tmp_path, (copy,))
    store = LocalArtifactStore(tmp_path)
    reference = resolve_snapshot_file_ref(copy.source, copy.source_files[0])
    assert store.registry.backings(copy.source) == ()
    assert store.registry.file_backings(reference) == ()


def test_ordinary_cloud_read_records_only_its_verified_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A downloaded member gains an exact proof without verifying its siblings."""
    _, cloud = _copy(tmp_path, {"config.json": b"{}", "weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[1])
    store = LocalArtifactStore(tmp_path)
    assert store.read(reference) == b"weights"
    assert store.registry.file_backings(reference) == (reference,)
    assert store.registry.backings(cloud.snapshot) == ()
    assert store.resolve(reference).read_bytes() == b"weights"
    assert cloud.downloads == 1


def test_only_raw_publications_get_standalone_retention_entries(tmp_path: Path) -> None:
    """Raw files receive overrides without creating extra votes for stage members."""
    reference = publish_resolved_files(
        tmp_path, LocalStorageDestination(), {"ready.json": b"ready"}
    )["ready.json"]
    source = _snapshot(reference)
    registry = LocalArtifactStore(tmp_path).registry
    assert registry.retention(source, "ready.json") == "inherit"
    set_artifact_retention(tmp_path, source, "ready.json", "keep")
    assert registry.retention(source, "ready.json") == "keep"

    original = tmp_path / "weights.pt"
    original.write_bytes(b"weights")
    snapshot, _ = LocalSnapshotPublisher(tmp_path).publish(
        resolved_stage_path="stage.yaml",
        resolved_stage=b"stage",
        files={"model/weights.pt": original},
    )
    with pytest.raises(StorageRegistryError, match="not registered"):
        registry.retention(snapshot, "model/weights.pt")


def test_cloud_publication_outside_workflow_waits_for_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy cloud-returning calls do not return while publication is blocked."""
    _, cloud = _copy(tmp_path, {"ready.json": b"ready"})
    entered = Event()
    release = Event()
    complete = cloud.resolved_files

    def blocking(
        destination: ViperCloudDestination, sources: Mapping[str, PublicationSource]
    ) -> dict[str, ResolvedFileRef]:
        """Keep publication pending until the test releases its completion."""
        entered.set()
        assert release.wait(5)
        return complete(destination, sources)

    monkeypatch.setattr(cloud, "resolved_files", blocking)
    monkeypatch.setattr(
        "viper.storage.viper_cloud", lambda root: cast(ViperCloud, cloud)
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            publish_resolved_files,
            tmp_path,
            ViperCloudDestination(owner="owner", workspace="models"),
            {"ready.json": b"ready"},
        )
        assert entered.wait(5)
        assert not pending.done()
        release.set()
        references = pending.result(timeout=5)
    assert isinstance(references["ready.json"].stored_at, GcsFileRef)


def test_hardlink_adoption_keeps_foreign_file_observations_current(
    tmp_path: Path,
) -> None:
    """Link creation refreshes ctime without changing source bytes or ownership."""
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    original_store = LocalArtifactStore(producer)
    reference = original_store.resolved_files({"weights.pt": b"weights"})[0]
    original = original_store.resolve(reference)
    adopted = LocalArtifactStore(consumer).adopt_verified_reference(reference, original)
    assert adopted.read_bytes() == original.read_bytes() == b"weights"
    source = _snapshot(reference)
    record = original_store.registry.snapshot(source)
    assert record is not None
    assert (
        record.locations["weights.pt"][0].observed_stat[3]
        == original.stat().st_ctime_ns
    )

    os.link(original, producer / "second-name.pt")
    assert original_store.resolve(reference) == original
    refreshed = original_store.registry.snapshot(source)
    assert refreshed is not None
    assert (
        refreshed.locations["weights.pt"][0].observed_stat[3]
        == original.stat().st_ctime_ns
    )


def test_standalone_fetcher_holds_protection_across_memo_reads(tmp_path: Path) -> None:
    """A standalone verifier protects cached paths until its fetcher closes."""
    store = LocalArtifactStore(tmp_path)
    reference = store.resolved_files({"weights.pt": b"weights"})[0]
    fetcher = RunFetcher(tmp_path, store, "")
    assert fetcher.read(reference) == b"weights"
    with PayloadLocks(tmp_path).exclusive(reference) as acquired:
        assert not acquired
    assert fetcher.path(reference).read_bytes() == b"weights"
    with PayloadLocks(tmp_path).exclusive(reference) as acquired:
        assert not acquired
    fetcher.close()
    with PayloadLocks(tmp_path).exclusive(reference) as acquired:
        assert acquired


def test_standalone_fetcher_also_holds_the_foreign_store(tmp_path: Path) -> None:
    """Reading a foreign local reference protects both resolution namespaces."""
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    reference = LocalArtifactStore(producer).resolved_files({"weights.pt": b"weights"})[
        0
    ]
    with RunFetcher(consumer, LocalArtifactStore(consumer), "") as fetcher:
        assert fetcher.read(reference) == b"weights"
        with PayloadLocks(producer).exclusive(reference) as acquired:
            assert not acquired
        with PayloadLocks(consumer).exclusive(reference) as acquired:
            assert not acquired
    with PayloadLocks(producer).exclusive(reference) as acquired:
        assert acquired


def test_nested_workflow_inherits_explicit_attached_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native child calls retain the outer owner's complete target identity."""
    (tmp_path / "viper.toml").write_text(
        '[storage]\ndestination = "viper://owner/models"\n'
        '[viper_cloud]\nkind = "gcs"\nbucket = "viper-recovery"\n'
    )
    target = PublicationTarget(
        repository=GcsRepository(bucket="viper-recovery"),
        destination=ViperCloudDestination(owner="owner", workspace="models"),
        google_project_id="project-one",
        gcp_service_account="worker@example.iam.gserviceaccount.com",
    )
    monkeypatch.setattr(
        _offload, "start_publication_worker", lambda *args, **kwargs: None
    )
    with workflow(tmp_path, targets=(target,)) as outer:
        with workflow(tmp_path) as inner:
            assert inner is outer
            assert inner.targets == (target,)


def test_bare_local_fetcher_call_holds_reader_until_close(tmp_path: Path) -> None:
    """Legacy callable readers retain the same protection as resolved reads."""
    store = LocalArtifactStore(tmp_path)
    reference = store.resolved_files({"weights.pt": b"weights"})[0]
    with RunFetcher(tmp_path, store, "") as fetcher:
        assert fetcher(reference.stored_at) == b"weights"
        with PayloadLocks(tmp_path).exclusive(reference) as acquired:
            assert not acquired
    with PayloadLocks(tmp_path).exclusive(reference) as acquired:
        assert acquired


def test_import_holds_all_members_through_transfer_and_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queued cleanup cannot acquire a file between installation and registration."""
    copy, cloud = _copy(tmp_path, {"config.json": b"{}", "weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    references = tuple(
        resolve_snapshot_file_ref(copy.source, member) for member in copy.source_files
    )
    transfer = cloud.fetch_to_path

    def protected_transfer(reference: ResolvedFileRef, destination: Path) -> Path:
        """Attempt cleanup before the importer installs each verified member."""
        for selected in references:
            with PayloadLocks(tmp_path).exclusive(selected) as acquired:
                assert not acquired
        return transfer(reference, destination)

    monkeypatch.setattr(cloud, "fetch_to_path", protected_transfer)
    import_publication_copies(tmp_path, (copy,))
    for reference in references:
        with PayloadLocks(tmp_path).exclusive(reference) as acquired:
            assert acquired
    assert cloud.downloads == 2


def test_unseen_cloud_reference_reuses_registered_original_without_a_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expected size and hash can find local bytes before unseen cloud metadata."""
    original = tmp_path / "original.pt"
    original.write_bytes(b"weights")
    store = LocalArtifactStore(tmp_path)
    store._publish({"original/weights.pt": original}, path_custody="output")
    member = snapshot_file("unseen/remote.pt", b"weights")
    snapshot = GcsStageResultSnapshotRef(
        bucket="unavailable-cloud",
        owner="owner",
        workspace="models",
        revision=manifest_revision((member,)),
    )
    reference = resolve_snapshot_file_ref(snapshot, member)

    def forbidden(*args: object, **kwargs: object) -> ViperCloud:
        """Reject provider construction for already resident matching bytes."""
        raise AssertionError("cloud client created for a local file")

    monkeypatch.setattr(ViperCloud, "for_snapshot", classmethod(forbidden))
    monkeypatch.setattr(ViperCloud, "for_reference", classmethod(forbidden))
    with RunFetcher(tmp_path, store, "") as fetcher:
        assert fetcher.path(reference) == original
    assert store.registry.snapshot(snapshot) is None


def test_native_reuse_preserves_original_path_and_existing_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reused output paths avoid a second payload copy and retain output ownership."""
    (tmp_path / "viper.toml").write_text('[storage]\ndestination = "local"\n')
    original = tmp_path / "original.pt"
    original.write_bytes(b"weights")
    store = LocalArtifactStore(tmp_path)
    monkeypatch.setattr(
        _offload, "start_publication_worker", lambda *args, **kwargs: None
    )
    with workflow(tmp_path):
        commit, members = store._publish(
            {"producer/weights.pt": original}, path_custody="output"
        )
        source = LocalStageResultSnapshotRef(workspace=tmp_path, commit=commit)

        def forbidden(*args: object, **kwargs: object) -> bytes:
            """Reject the eager bytes conversion used by the legacy reuse branch."""
            raise AssertionError("native reuse loaded the payload into bytes")

        monkeypatch.setattr("viper.storage.read_publication_source", forbidden)
        snapshot = LocalSnapshotPublisher(tmp_path).publish_reuse(
            resolved_stage_path="reused-stage.yaml",
            resolved_stage=b"stage",
            source_snapshot=source,
            files={"consumer/weights.pt": members[0]},
            source_bytes={"consumer/weights.pt": original},
        )
        member = next(
            value
            for value in store.snapshot_files(snapshot)
            if value.path == "consumer/weights.pt"
        )
        reference = resolve_snapshot_file_ref(snapshot, member)
        assert store.resolve(reference) == original
        binding = store.registry.binding(reference, "original.pt")
        assert binding is not None and binding.custody == "output"
        assert not store.downloads.path(reference).exists()


def test_reused_file_proof_still_checks_explicit_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing proof cannot bypass the caller's requested cloud destination."""
    _, cloud = _copy(tmp_path, {"weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    receipt = PublicationReceipt(
        operation_id="c" * 32,
        targets=(),
        science_succeeded=True,
        used=(reference,),
        copies=(),
        file_copies=(reference,),
    )
    import_publication_receipt(tmp_path, receipt)
    wrong = PublicationTarget(
        repository=GcsRepository(bucket="other-bucket"),
        destination=ViperCloudDestination(owner="owner", workspace="models"),
    )
    with pytest.raises(StorageConfigurationError, match="does not match"):
        import_publication_receipt(tmp_path, receipt, targets=(wrong,))
    assert cloud.downloads == 1


@pytest.mark.parametrize("backing_kind", ["snapshot", "file"])
def test_cold_cloud_reference_uses_verified_alternate_before_original_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backing_kind: str
) -> None:
    """Restore an exact ref through verified bytes on another cloud host."""
    copy, cloud = _copy(tmp_path, {"alternate/weights.pt": b"weights"})
    _services(monkeypatch, cloud)
    alternate = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    if backing_kind == "snapshot":
        import_publication_copies(tmp_path, (copy,))
    else:
        LocalArtifactStore(tmp_path).read(alternate)
    store = LocalArtifactStore(tmp_path)
    store.resolve(alternate).unlink()
    member = snapshot_file("original/model.pt", b"weights")
    original_snapshot = GcsStageResultSnapshotRef(
        bucket="original-host-is-unavailable",
        owner="owner",
        workspace="models",
        revision=manifest_revision((member,)),
    )
    original = resolve_snapshot_file_ref(original_snapshot, member)
    saved = original.model_dump(mode="json")

    def unavailable_original() -> ViperCloud:
        """Fail if resolution asks for the unavailable original provider."""
        raise AssertionError("original host was consulted before verified alternate")

    assert (
        store.resolve(original, cloud=unavailable_original).read_bytes() == b"weights"
    )
    assert original.model_dump(mode="json") == saved
    assert store.registry.snapshot(original_snapshot) is None
    assert cloud.downloads == 2


def test_partial_foreign_adoption_preserves_access_to_remaining_original_members(
    tmp_path: Path,
) -> None:
    """Registering the whole inventory does not imply every payload was adopted."""
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    source_store = LocalArtifactStore(producer)
    references = source_store.resolved_files(
        {"config.json": b"{}", "weights.pt": b"weights"}
    )
    configuration, weights = references
    current = LocalArtifactStore(consumer)
    adopted = current.adopt_verified_reference(
        configuration, source_store.resolve(configuration)
    )
    assert adopted.is_relative_to(consumer)
    assert current.registry.snapshot(_snapshot(configuration)) is not None
    with RunFetcher(consumer, current, "") as fetcher:
        original = fetcher.path(weights)
        assert original.is_relative_to(producer)
        assert original.read_bytes() == b"weights"
        with PayloadLocks(producer).exclusive(weights) as acquired:
            assert not acquired
        with PayloadLocks(consumer).exclusive(weights) as acquired:
            assert not acquired
        assert fetcher.path(configuration) == adopted
    assert isinstance(weights.stored_at, LocalFileRef)
    assert isinstance(weights.stored_at, LocalFileRef)
    assert weights.stored_at.workspace == producer
