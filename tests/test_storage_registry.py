"""Observe inventory persistence and shared physical binding behavior."""

import hashlib
import sqlite3
from pathlib import Path
from typing import Literal

import pytest

from viper._cloud import (
    LocalSource,
    RevisionManifest,
    SnapshotCopy,
    SnapshotInventory,
    SnapshotSources,
    canonical_json_bytes,
    manifest_revision,
)
from viper._storage_registry import StorageRegistry, StorageRegistryError
from viper.references import (
    GcsStageResultSnapshotRef,
    LocalStageResultSnapshotRef,
    SnapshotFileRef,
)


def _inventory(root: Path, files: dict[str, bytes]) -> SnapshotInventory:
    """Build an original local inventory using the shared revision function."""
    members = tuple(
        SnapshotFileRef(
            path=path, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
        )
        for path, raw in sorted(files.items())
    )
    return SnapshotInventory(
        source=LocalStageResultSnapshotRef(
            workspace=root, commit=manifest_revision(members)
        ),
        source_files=members,
    )


def _location(
    root: Path,
    path: Path,
    *,
    custody: Literal["output", "cache", "external"] = "output",
) -> LocalSource:
    """Capture a real source observation after its producer has finished."""
    status = path.stat()
    return LocalSource(
        path=path.relative_to(root).as_posix(),
        observed_stat=(
            status.st_dev,
            status.st_ino,
            status.st_mtime_ns,
            status.st_ctime_ns,
        ),
        custody=custody,
    )


def test_unregistered_lookup_does_not_initialize_storage(tmp_path: Path) -> None:
    """Leave legacy lookup free of registry creation or payload writes."""
    registry = StorageRegistry(tmp_path)
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})

    assert registry.snapshot(inventory.source) is None
    assert not registry.path.exists()
    assert not registry.store_root.exists()


def test_inventory_survives_restart_and_payload_absence(tmp_path: Path) -> None:
    """Keep full declared membership after one member disappears locally."""
    weights = tmp_path / "model.pt"
    report = tmp_path / "report.json"
    weights.write_bytes(b"weights")
    report.write_bytes(b"{}")
    inventory = _inventory(tmp_path, {"weights.pt": b"weights", "report.json": b"{}"})
    record = SnapshotSources(
        inventory=inventory,
        locations={
            "weights.pt": (_location(tmp_path, weights),),
            "report.json": (_location(tmp_path, report),),
        },
    )
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(record)
    registry.register_snapshot(record)
    weights.unlink()

    reopened = StorageRegistry(tmp_path).snapshot(inventory.source)

    assert reopened is not None
    assert reopened.inventory == inventory
    assert tuple(file.path for file in reopened.inventory.source_files) == (
        "report.json",
        "weights.pt",
    )
    assert reopened.locations == record.locations
    assert report.read_bytes() == b"{}"


def test_equal_content_shares_original_without_another_payload(tmp_path: Path) -> None:
    """Let another snapshot use an already registered physical payload."""
    original = tmp_path / "checkpoint.pt"
    original.write_bytes(b"weights")
    first = _inventory(tmp_path, {"weights.pt": b"weights"})
    second = _inventory(tmp_path, {"reused.pt": b"weights"})
    location = _location(tmp_path, original)
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(
        SnapshotSources(inventory=first, locations={"weights.pt": (location,)})
    )
    registry.register_snapshot(SnapshotSources(inventory=second))

    shared = registry.snapshot(second.source)

    assert shared is not None
    assert first.source != second.source
    assert shared.inventory == second
    assert shared.locations["reused.pt"] == (location,)
    assert original.read_bytes() == b"weights"


def test_registered_inventory_cannot_change(tmp_path: Path) -> None:
    """Reject changed membership under one exact cloud snapshot address."""
    local = _inventory(tmp_path, {"weights.pt": b"weights"})
    source = GcsStageResultSnapshotRef(
        bucket="test-bucket", owner="machina", workspace="jep", revision="a" * 64
    )
    original = SnapshotInventory(source=source, source_files=local.source_files)
    changed = SnapshotInventory(
        source=source,
        source_files=(
            SnapshotFileRef(path="extra.bin", sha256="b" * 64, bytes=1),
            *local.source_files,
        ),
    )
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(SnapshotSources(inventory=original))

    with pytest.raises(StorageRegistryError, match="inventory changed"):
        registry.register_snapshot(SnapshotSources(inventory=changed))

    saved = registry.snapshot(source)
    assert saved is not None
    assert saved.inventory == original


def test_custody_conflict_rolls_back_new_snapshot(tmp_path: Path) -> None:
    """Do not acquire ownership of an existing external physical path."""
    original = tmp_path / "dataset.bin"
    original.write_bytes(b"data")
    first = _inventory(tmp_path, {"input.bin": b"data"})
    second = _inventory(tmp_path, {"claimed.bin": b"data"})
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(
        SnapshotSources(
            inventory=first,
            locations={
                "input.bin": (_location(tmp_path, original, custody="external"),)
            },
        )
    )

    with pytest.raises(StorageRegistryError, match="another binding"):
        registry.register_snapshot(
            SnapshotSources(
                inventory=second,
                locations={"claimed.bin": (_location(tmp_path, original),)},
            )
        )

    assert registry.snapshot(second.source) is None
    saved = registry.snapshot(first.source)
    assert saved is not None
    assert saved.locations["input.bin"][0].custody == "external"
    assert original.read_bytes() == b"data"


def test_source_replacement_before_registration_is_rejected(tmp_path: Path) -> None:
    """Reject a saved observation whose path now names a replacement file."""
    original = tmp_path / "checkpoint.pt"
    original.write_bytes(b"weights")
    stale = _location(tmp_path, original)
    replacement = tmp_path / "replacement.pt"
    replacement.write_bytes(b"weights")
    replacement.replace(original)
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
    registry = StorageRegistry(tmp_path)

    with pytest.raises(StorageRegistryError, match="source changed"):
        registry.register_snapshot(
            SnapshotSources(inventory=inventory, locations={"weights.pt": (stale,)})
        )

    assert registry.snapshot(inventory.source) is None


def test_dataset_reseal_retires_only_its_old_binding(tmp_path: Path) -> None:
    """Keep original inventory while a declared dataset path gains a new version."""
    dataset = tmp_path / "dataset.bin"
    dataset.write_bytes(b"old data")
    first = _inventory(tmp_path, {"input.bin": b"old data"})
    registry = StorageRegistry(tmp_path)
    old = _location(tmp_path, dataset, custody="external")
    registry.register_snapshot(
        SnapshotSources(inventory=first, locations={"input.bin": (old,)})
    )
    dataset.write_bytes(b"new data")
    second = _inventory(tmp_path, {"input.bin": b"new data"})
    current = _location(tmp_path, dataset, custody="external")

    registry.register_snapshot(
        SnapshotSources(inventory=second, locations={"input.bin": (current,)})
    )

    before = registry.snapshot(first.source)
    after = registry.snapshot(second.source)
    assert before is not None and after is not None
    assert before.inventory == first
    assert before.locations["input.bin"][0].retired
    assert after.locations["input.bin"] == (current,)
    assert dataset.read_bytes() == b"new data"


def test_invalidating_external_binding_does_not_delete_file(tmp_path: Path) -> None:
    """Permit stale input-binding invalidation without granting deletion custody."""
    dataset = tmp_path / "dataset.bin"
    dataset.write_bytes(b"data")
    inventory = _inventory(tmp_path, {"input.bin": b"data"})
    location = _location(tmp_path, dataset, custody="external")
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(
        SnapshotSources(inventory=inventory, locations={"input.bin": (location,)})
    )

    assert registry.retire_materialization(location)
    saved = registry.snapshot(inventory.source)
    assert saved is not None
    assert saved.locations["input.bin"][0].retired
    assert dataset.read_bytes() == b"data"


@pytest.mark.parametrize("batch", (False, True))
def test_verified_cache_repair_defeats_stale_retirement(
    tmp_path: Path, batch: bool
) -> None:
    """Install a verified replacement without letting an older job retire it."""
    cached = tmp_path / "cached.bin"
    cached.write_bytes(b"weights")
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
    old = _location(tmp_path, cached, custody="cache")
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(
        SnapshotSources(inventory=inventory, locations={"weights.pt": (old,)})
    )
    replacement = tmp_path / "verified.bin"
    replacement.write_bytes(b"weights")
    replacement.replace(cached)

    if batch:
        current = _location(tmp_path, cached, custody="cache")
        registry.register_snapshot(
            SnapshotSources(inventory=inventory, locations={"weights.pt": (current,)})
        )
    else:
        current = registry.record_materialization(
            inventory.source, inventory.source_files[0], cached
        )

    assert not registry.retire_materialization(old)
    saved = registry.snapshot(inventory.source)
    assert saved is not None
    assert saved.locations["weights.pt"] == (current,)
    assert not current.retired
    assert cached.read_bytes() == b"weights"


def test_retirement_preserves_inventory_and_does_not_unlink(tmp_path: Path) -> None:
    """Record release without giving the registry independent deletion authority."""
    output = tmp_path / "checkpoint.pt"
    output.write_bytes(b"weights")
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
    location = _location(tmp_path, output)
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(
        SnapshotSources(inventory=inventory, locations={"weights.pt": (location,)})
    )

    assert registry.retire_materialization(location)
    assert not registry.retire_materialization(location)
    saved = registry.snapshot(inventory.source)
    assert saved is not None
    assert saved.inventory == inventory
    assert saved.locations["weights.pt"][0].retired
    assert output.read_bytes() == b"weights"


def test_registered_index_corruption_does_not_become_unmanaged(tmp_path: Path) -> None:
    """Fail closed when saved membership no longer matches its inventory."""
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
    registry = StorageRegistry(tmp_path)
    registry.register_snapshot(SnapshotSources(inventory=inventory))
    with sqlite3.connect(registry.path) as connection:
        connection.execute("DELETE FROM snapshot_members")

    with pytest.raises(StorageRegistryError, match="membership index differs"):
        registry.snapshot(inventory.source)


def test_corrupt_registry_does_not_become_unmanaged(tmp_path: Path) -> None:
    """Distinguish absent metadata from an existing unreadable registry."""
    registry = StorageRegistry(tmp_path)
    registry.path.parent.mkdir(parents=True)
    registry.path.write_bytes(b"not a SQLite database")
    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})

    with pytest.raises(StorageRegistryError, match="registry is invalid"):
        registry.snapshot(inventory.source)


def test_pending_publication_protects_shared_bytes_after_restart(
    tmp_path: Path,
) -> None:
    """Keep an equal-content snapshot protected until its upload completes."""
    first = _inventory(tmp_path, {"first.pt": b"weights"})
    second = _inventory(tmp_path, {"second.pt": b"weights"})
    registry = StorageRegistry(tmp_path)
    for inventory in (first, second):
        registry.register_snapshot(SnapshotSources(inventory=inventory))
    registry.pin_source(first.source, "operation:first")
    reopened = StorageRegistry(tmp_path)
    with reopened._transaction() as cnx:
        assert reopened.source_is_pending(second.source_files[0], cnx)
    reopened.unpin_source("operation:first")
    with reopened._transaction() as cnx:
        assert not reopened.source_is_pending(first.source_files[0], cnx)


def test_verified_backing_survives_source_removal_and_checks_proof(
    tmp_path: Path,
) -> None:
    """Restore shared bytes from another snapshot while rejecting changed proof."""
    first = _inventory(tmp_path, {"first.pt": b"weights"})
    second = _inventory(tmp_path, {"second.pt": b"weights"})
    manifest = RevisionManifest(
        owner="machina",
        workspace="offload",
        revision=manifest_revision(first.source_files),
        files=first.source_files,
    )
    copy = SnapshotCopy(
        source=first.source,
        source_files=first.source_files,
        expected=manifest,
        dependencies_sha256=hashlib.sha256(b"[]").hexdigest(),
        previous_head=None,
        published=GcsStageResultSnapshotRef(
            bucket="verified-artifacts",
            owner="machina",
            workspace="offload",
            revision=manifest.revision,
        ),
    )
    proof = tmp_path / "proof.json"
    proof.write_bytes(canonical_json_bytes(copy))
    registry = StorageRegistry(tmp_path)
    registry.register_backing(copy, "proof.json")
    registry.register_snapshot(SnapshotSources(inventory=second))
    reopened = StorageRegistry(tmp_path)
    assert reopened.backings(second.source) == ()
    assert reopened.backings(second.source, second.source_files[0]) == (copy,)
    proof.write_bytes(proof.read_bytes() + b" ")
    with pytest.raises(StorageRegistryError, match="proof changed"):
        reopened.backings(second.source, second.source_files[0])
