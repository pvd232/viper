"""Observe shared resolution, immutable listing, and bounded transfer staging."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import httpx
import pytest
from huggingface_hub import HfApi

from viper._cloud import (
    HuggingFaceRepository,
    LocalSource,
    RevisionManifest,
    SnapshotInventory,
    SnapshotSources,
    canonical_json_bytes,
)
from viper._source import RunFetcher
from viper._storage_registry import StorageRegistryError
from viper.cloud import ViperCloud
from viper.evidence import VerificationError
from viper.huggingface import HuggingFaceProvider
from viper.references import (
    GcsStageResultSnapshotRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from viper.storage import (
    LocalArtifactStore,
    LocalStoreError,
    content_revision,
    snapshot_file,
)


class MemoryCloud:
    """Represent verified cloud downloads without network access."""

    def __init__(self, files: dict[str, bytes]) -> None:
        """Bind one complete published inventory and count payload transfers."""
        self.files = files
        self.provider = object()
        self.members = tuple(
            snapshot_file(path, raw) for path, raw in sorted(files.items())
        )
        self.snapshot = GcsStageResultSnapshotRef(
            bucket="private-jep",
            owner="owner",
            workspace="experiments",
            revision=content_revision(self.members),
        )
        self.downloads = 0
        self.fail_download = False

    def list_files(self, snapshot: object) -> tuple[SnapshotFileRef, ...]:
        """Return the sealed full inventory used by the storage resolver."""
        assert snapshot == self.snapshot
        return self.members

    def fetch_to_path(self, reference: ResolvedFileRef, target: Path) -> Path:
        """Honor the provider contract by verifying before returning a path."""
        self.downloads += 1
        if self.fail_download:
            target.write_bytes(b"partial")
            raise VerificationError("cloud download was interrupted")
        raw = self.files[reference.stored_at.path]
        assert len(raw) == reference.bytes
        assert hashlib.sha256(raw).hexdigest() == reference.sha256
        target.write_bytes(raw)
        return target


def test_local_members_share_payload_without_changing_references(
    tmp_path: Path,
) -> None:
    """Different immutable member addresses share one verified physical payload."""
    store = LocalArtifactStore(tmp_path)
    first = store.resolved_files({"first/weights.bin": b"same weights"})[0]
    second = store.resolved_files({"second/weights.bin": b"same weights"})[0]

    assert first.stored_at != second.stored_at
    assert first.stored_at.path == "first/weights.bin"
    assert second.stored_at.path == "second/weights.bin"
    assert store.resolve(first) == store.resolve(second)
    assert store.resolve(first).read_bytes() == b"same weights"
    assert store.resolve(first).is_relative_to(tmp_path / ".viper/store/objects")


def test_registered_original_is_used_without_a_payload_copy(tmp_path: Path) -> None:
    """Explicitly registered sealed originals serve readers directly."""
    original = tmp_path / "outputs/checkpoint.pt"
    original.parent.mkdir()
    original.write_bytes(b"checkpoint")
    member = snapshot_file("weights.bin", b"checkpoint")
    source = LocalStageResultSnapshotRef(
        workspace=tmp_path, commit=content_revision((member,))
    )
    status = original.stat()
    store = LocalArtifactStore(tmp_path)
    store.registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=source, source_files=(member,)),
            locations={
                member.path: (
                    LocalSource(
                        path="outputs/checkpoint.pt",
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
    )

    assert store.resolve(resolve_snapshot_file_ref(source, member)) == original
    assert not (tmp_path / ".viper/store/objects").exists()


def test_listing_survives_partial_residency_and_restart(tmp_path: Path) -> None:
    """Payload loss cannot silently turn an immutable bundle into a shorter listing."""
    store = LocalArtifactStore(tmp_path)
    source = store.snapshot(
        {"bundle/config.json": b"{}", "bundle/weights.bin": b"weights"}
    )
    references = store.resolved_files(
        {"bundle/config.json": b"{}", "bundle/weights.bin": b"weights"}
    )
    store.resolve(references[0]).unlink()
    restarted = LocalArtifactStore(tmp_path)

    assert restarted.list_snapshot_files(source) == (
        "bundle/config.json",
        "bundle/weights.bin",
    )
    with pytest.raises(LocalStoreError, match="unavailable"):
        restarted.resolve(references[0])
    assert restarted.read(references[1]) == b"weights"


def test_complete_legacy_snapshot_is_adopted_before_partial_residency(
    tmp_path: Path,
) -> None:
    """Existing resident snapshots gain validated inventory without rewritten refs."""
    files = {"bundle/a.bin": b"first", "bundle/b.bin": b"second"}
    source = LocalStageResultSnapshotRef(
        workspace=tmp_path, commit=content_revision(files)
    )
    directory = tmp_path / ".viper/store" / source.commit
    for name, raw in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    store = LocalArtifactStore(tmp_path)

    assert store.list_snapshot_files(source) == tuple(files)
    (directory / "bundle/a.bin").unlink()
    assert LocalArtifactStore(tmp_path).list_snapshot_files(source) == tuple(files)


def test_corrupt_registered_original_is_reported(tmp_path: Path) -> None:
    """An original with changed bytes is not silently replaced by another copy."""
    original = tmp_path / "original.bin"
    original.write_bytes(b"right")
    member = snapshot_file("artifact.bin", b"right")
    source = LocalStageResultSnapshotRef(
        workspace=tmp_path, commit=content_revision((member,))
    )
    status = original.stat()
    store = LocalArtifactStore(tmp_path)
    store.registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=source, source_files=(member,)),
            locations={
                member.path: (
                    LocalSource(
                        path="original.bin",
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
    )
    original.write_bytes(b"wrong")

    with pytest.raises(VerificationError, match="SHA-256 mismatch"):
        store.resolve(resolve_snapshot_file_ref(source, member))


def test_run_fetcher_uses_shared_store_across_executions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordinary cloud readers share the store instead of creating a second cache."""
    cloud = MemoryCloud({"weights.bin": b"weights"})
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    monkeypatch.setattr(
        RunFetcher, "_cloud_service", lambda *_: cast(ViperCloud, cloud)
    )
    first = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
    path = first.path(reference)
    second = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")

    assert second.read(reference) == b"weights"
    assert second.path(reference) == path
    assert cloud.downloads == 1
    assert path.is_relative_to(tmp_path / ".viper/store/objects")
    assert not (tmp_path / ".viper/cache/verified-objects").exists()


def test_failed_download_never_installs_a_shared_payload(tmp_path: Path) -> None:
    """An interrupted restore preserves inventory while discarding partial bytes."""
    cloud = MemoryCloud({"weights.bin": b"weights"})
    cloud.fail_download = True
    store = LocalArtifactStore(tmp_path)
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])

    with pytest.raises(VerificationError, match="interrupted"):
        store.resolve(reference, cloud=cast(ViperCloud, cloud))
    assert not store.downloads.path(reference).exists()
    assert store.registry.snapshot(cloud.snapshot) is not None
    assert all(path.is_dir() for path in (tmp_path / ".viper/store/objects").rglob("*"))


def test_bounded_transfer_downloads_stay_in_their_task_cache(tmp_path: Path) -> None:
    """Independent transfer verification does not borrow a source's local bytes."""
    ordinary = LocalArtifactStore(tmp_path)
    original = ordinary.resolved_files({"weights.bin": b"weights"})[0]
    cloud = MemoryCloud({"weights.bin": b"weights"})
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    cache_root = tmp_path / "transfer/cache/verified-objects"
    bounded = LocalArtifactStore(tmp_path, cache_root=cache_root)

    path = bounded.resolve(reference, cloud=cast(ViperCloud, cloud))
    assert path.is_relative_to(cache_root)
    assert path != ordinary.resolve(original)
    assert cloud.downloads == 1
    assert bounded.registry.snapshot(cloud.snapshot) is None


def test_corrupt_shared_cache_is_repaired_on_the_next_execution(
    tmp_path: Path,
) -> None:
    """Verified cloud restoration may replace a corrupt cache generation."""
    cloud = MemoryCloud({"weights.bin": b"weights"})
    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
    first = LocalArtifactStore(tmp_path)
    path = first.resolve(reference, cloud=cast(ViperCloud, cloud))
    path.write_bytes(b"changed")

    restored = LocalArtifactStore(tmp_path).resolve(
        reference, cloud=cast(ViperCloud, cloud)
    )
    assert restored == path
    assert restored.read_bytes() == b"weights"
    assert cloud.downloads == 2


def test_republishing_exact_bytes_repairs_shared_cache_without_new_refs(
    tmp_path: Path,
) -> None:
    """Local publication can repair its verified cache without changing identity."""
    store = LocalArtifactStore(tmp_path)
    reference = store.resolved_files({"weights.bin": b"weights"})[0]
    store.resolve(reference).write_bytes(b"changed")

    assert store.resolved_files({"weights.bin": b"weights"})[0] == reference
    assert store.read(reference) == b"weights"


def _register_original(
    store: LocalArtifactStore,
    source: StageResultSnapshotRef,
    member: SnapshotFileRef,
    original: Path,
) -> ResolvedFileRef:
    """Register a verified original without requiring its producing host to exist."""
    status = original.stat()
    store.registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=source, source_files=(member,)),
            locations={
                member.path: (
                    LocalSource(
                        path=original.relative_to(store.repository_root).as_posix(),
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
    )
    return resolve_snapshot_file_ref(source, member)


def _no_cloud_client(*_args: object) -> ViperCloud:
    """Fail if resident artifact access attempts to create a cloud client."""
    raise AssertionError("resident artifact access must not create a cloud client")


def test_fresh_fetcher_reuses_registered_original_without_cloud_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate runs use the registered original before another cache or cloud."""
    store = LocalArtifactStore(tmp_path)
    cached = store.resolved_files({"already-cached.bin": b"weights"})[0]
    cached_path = store.resolve(cached)
    original = tmp_path / "outputs/checkpoint.pt"
    original.parent.mkdir()
    original.write_bytes(b"weights")
    published = MemoryCloud({"weights.bin": b"weights"})
    reference = _register_original(
        store, published.snapshot, published.members[0], original
    )
    monkeypatch.setattr(RunFetcher, "_cloud_service", _no_cloud_client)
    first = RunFetcher(tmp_path, store, "")
    second = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")

    assert cached_path != original
    assert first.path(reference) == original
    assert second.read(reference) == b"weights"
    assert second.path(reference) == original
    assert second.snapshot_files(published.snapshot) == published.members
    assert second.list_snapshot_files(published.snapshot) == ("weights.bin",)


def test_fetcher_uses_active_registry_for_foreign_local_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An immutable old-host reference resolves through the current host's binding."""
    departed = tmp_path / "departed-workspace"
    member = snapshot_file("weights.bin", b"weights")
    source = LocalStageResultSnapshotRef(
        workspace=departed, commit=content_revision((member,))
    )
    original = tmp_path / "checkpoint.pt"
    original.write_bytes(b"weights")
    store = LocalArtifactStore(tmp_path)
    reference = _register_original(store, source, member, original)
    monkeypatch.setattr("viper._source.local_artifact_store", _no_cloud_client)
    fetcher = RunFetcher(tmp_path, store, "")

    assert fetcher.path(reference) == original
    assert fetcher.read(reference) == b"weights"
    assert fetcher(reference.stored_at) == b"weights"
    assert fetcher.list_snapshot_files(source) == ("weights.bin",)
    assert isinstance(reference.stored_at, LocalFileRef)
    assert reference.stored_at.workspace == departed
    assert not departed.exists()


def test_fetcher_propagates_invalid_active_registry_before_legacy_fallback(
    tmp_path: Path,
) -> None:
    """A malformed current registry cannot be bypassed using a healthy old store."""
    producer_root = tmp_path / "producer"
    active_root = tmp_path / "active"
    producer_root.mkdir()
    active_root.mkdir()
    producer = LocalArtifactStore(producer_root)
    reference = producer.resolved_files({"weights.bin": b"weights"})[0]
    current = LocalArtifactStore(active_root)
    current.registry.path.parent.mkdir(parents=True)
    current.registry.path.write_bytes(b"malformed SQLite storage registry")
    fetcher = RunFetcher(active_root, current, "")

    with pytest.raises(StorageRegistryError, match="invalid"):
        fetcher.path(reference)
    assert producer.read(reference) == b"weights"


def _huggingface_cloud(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ViperCloud, ResolvedFileRef, httpx.Client, list[str]]:
    """Use the actual HF streaming provider with mocked metadata and HTTP bytes."""
    payload = b"weights"
    member = snapshot_file("weights.bin", payload)
    snapshot = HuggingFaceStageResultSnapshotRef(
        repository="owner/checkpoint", commit="a" * 40, repo_type="model"
    )
    metadata = root / "metadata/revision-manifest.json"
    metadata.parent.mkdir()
    metadata.write_bytes(
        canonical_json_bytes(
            RevisionManifest(
                owner="owner",
                workspace="experiments",
                revision=content_revision((member,)),
                files=(member,),
            )
        )
    )
    provider = HuggingFaceProvider(
        root, snapshot.repository, "model", api=HfApi(token=False)
    )

    def download_metadata(location: HuggingFaceFileRef) -> Path:
        """Allow ordinary manifest retrieval while rejecting a second payload cache."""
        assert location.path == ".viper/revision-manifest.json"
        return metadata

    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve the single immutable payload through the streaming HTTP path."""
        requests.append(request.url.path)
        return httpx.Response(200, content=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider, "_download", download_metadata)
    monkeypatch.setattr("viper.huggingface.get_session", lambda: client)
    cloud = ViperCloud(
        root,
        HuggingFaceRepository(repository=snapshot.repository, repo_type="model"),
        provider=provider,
    )
    monkeypatch.setattr(ViperCloud, "for_reference", lambda *_: cloud)
    return cloud, resolve_snapshot_file_ref(snapshot, member), client, requests


def test_managed_huggingface_restore_streams_into_shared_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary HF restore creates its verified payload only in shared storage."""
    _, reference, client, requests = _huggingface_cloud(tmp_path, monkeypatch)
    fetcher = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")

    with client:
        restored = fetcher.path(reference)
    assert restored.read_bytes() == b"weights"
    assert restored.is_relative_to(tmp_path / ".viper/store/objects")
    assert len(requests) == 1
    assert requests[0].endswith("/weights.bin")


def test_bounded_huggingface_restore_keeps_task_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transfer verification streams to its own cache despite shared local bytes."""
    ordinary = LocalArtifactStore(tmp_path)
    resident = ordinary.resolved_files({"local-weights.bin": b"weights"})[0]
    _, reference, client, requests = _huggingface_cloud(tmp_path, monkeypatch)
    task_cache = tmp_path / "transfer/cache"
    fetcher = RunFetcher(tmp_path, ordinary, "", cache_root=task_cache)

    with client:
        restored = fetcher.path(reference)
    assert restored.read_bytes() == b"weights"
    assert restored.is_relative_to(task_cache / "verified-objects")
    assert restored != ordinary.resolve(resident)
    assert len(requests) == 1
    assert requests[0].endswith("/weights.bin")


def test_registered_cache_hit_does_not_construct_cloud_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later run can reuse a verified shared cache without cloud credentials."""
    published = MemoryCloud({"weights.bin": b"weights"})
    reference = resolve_snapshot_file_ref(published.snapshot, published.members[0])
    store = LocalArtifactStore(tmp_path)
    resident = store.resolve(reference, cloud=cast(ViperCloud, published))
    monkeypatch.setattr(RunFetcher, "_cloud_service", _no_cloud_client)
    fresh = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")

    assert fresh.read(reference) == b"weights"
    assert fresh.path(reference) == resident
    assert published.downloads == 1


def test_new_snapshot_uses_registered_equal_content_original_without_downloading(
    tmp_path: Path,
) -> None:
    """First access to another snapshot reuses an original with the same bytes."""
    store = LocalArtifactStore(tmp_path)
    original = tmp_path / "checkpoint.pt"
    original.write_bytes(b"weights")
    old_member = snapshot_file("old/weights.bin", b"weights")
    old_source = LocalStageResultSnapshotRef(
        workspace=tmp_path, commit=content_revision((old_member,))
    )
    _register_original(store, old_source, old_member, original)
    published = MemoryCloud({"new/weights.bin": b"weights"})
    reference = resolve_snapshot_file_ref(published.snapshot, published.members[0])

    resolved = store.resolve(reference, cloud=cast(ViperCloud, published))

    assert resolved == original
    assert resolved.read_bytes() == b"weights"
    assert published.downloads == 0
    # Exact resident reads need no remote catalog request or partial registration.
    assert store.registry.snapshot(published.snapshot) is None
    assert (
        store.snapshot_files(published.snapshot, cloud=cast(ViperCloud, published))
        == published.members
    )
    assert store.registry.snapshot(published.snapshot) is not None
    assert not (tmp_path / ".viper/store/objects").exists()
