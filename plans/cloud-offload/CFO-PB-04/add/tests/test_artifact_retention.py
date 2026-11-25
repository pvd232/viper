"""Verify artifact overrides, shared subscribers and explicit keep completion."""

import hashlib
import sqlite3
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from viper._cloud import SnapshotInventory, SnapshotSources, manifest_revision
from viper._storage_registry import StorageRegistry, StorageRegistryError
from viper.artifacts import (
    ResolvedBundleArtifact,
    ResolvedBundleMember,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from viper.references import (
    FileIdentity,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
)
from viper.retention import set_artifact_retention
from viper.storage import (
    LocalArtifactStore,
    LocalStorageDestination,
    StorageSettings,
    ViperCloudDestination,
)


def _bundle(
    registry: StorageRegistry,
    *,
    config: bytes = b"configuration-one",
    source_workspace: Path | None = None,
) -> tuple[LocalStageResultSnapshotRef, StageArtifactRef, ResolvedBundleArtifact]:
    """Register a two-file artifact without creating any resident payload copy."""
    payloads = {
        "artifacts/model/config.json": config,
        "artifacts/model/weights.bin": b"unchanged-model-weights",
    }
    files = tuple(
        SnapshotFileRef(
            path=path,
            bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        for path, raw in sorted(payloads.items())
    )
    source = LocalStageResultSnapshotRef(
        workspace=source_workspace or registry.repository_root,
        store=registry.store,
        commit=manifest_revision(files),
    )
    registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=source, source_files=files)
        )
    )
    selection = StageArtifactRef(stage_id="train", artifact_name="model")
    artifact = ResolvedBundleArtifact(
        relative_path="artifacts/model",
        members=tuple(
            ResolvedBundleMember(
                relative_path=file.path.removeprefix("artifacts/model/"),
                file=file,
            )
            for file in files
        ),
    )
    registry.register_artifact(source, selection, artifact)
    return source, selection, artifact


def _permission(
    registry: StorageRegistry,
    identity: FileIdentity,
    *,
    default_offload: bool,
) -> bool:
    """Use the same transaction boundary required by final cleanup admission."""
    with registry._transaction(write=True) as connection:
        return registry.offload_permitted(
            connection, identity, default_offload=default_offload
        )


def _input_version(
    registry: StorageRegistry,
    raw: bytes = b"training-records-version-one",
) -> tuple[LocalStageResultSnapshotRef, ResolvedSingleFileArtifact]:
    """Represent an already sealed standalone input without inventing a producer."""
    member = SnapshotFileRef(
        path="inputs/training.csv",
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    source = LocalStageResultSnapshotRef(
        workspace=registry.repository_root,
        store=registry.store,
        commit=manifest_revision((member,)),
    )
    registry.register_snapshot(
        SnapshotSources(
            inventory=SnapshotInventory(source=source, source_files=(member,))
        )
    )
    artifact = ResolvedSingleFileArtifact(relative_path=member.path, file=member)
    registry.register_artifact(source, member.path, artifact)
    return source, artifact


def test_inherited_retention_uses_the_current_default(tmp_path: Path) -> None:
    """Changing the default changes permission without rewriting subscriptions."""
    registry = StorageRegistry(tmp_path)
    source, selection, artifact = _bundle(registry)
    identity = artifact.members[0].file

    assert not _permission(registry, identity, default_offload=False)
    assert _permission(registry, identity, default_offload=True)
    assert not _permission(registry, identity, default_offload=False)
    assert registry.retention(source, selection) == "inherit"


def test_explicit_overrides_work_in_both_directions(tmp_path: Path) -> None:
    """Explicit offload permits release under keep, while explicit keep vetoes it."""
    registry = StorageRegistry(tmp_path)
    source, selection, artifact = _bundle(registry)
    identity = artifact.members[0].file

    registry.set_retention(source, selection, "offload")
    assert _permission(registry, identity, default_offload=False)
    registry.set_retention(source, selection, "keep")
    assert not _permission(registry, identity, default_offload=True)
    registry.set_retention(source, selection, "inherit")
    assert _permission(registry, identity, default_offload=True)


def test_any_shared_artifact_keep_vetoes_offload(tmp_path: Path) -> None:
    """Two named artifacts sharing payloads contribute independent preferences."""
    registry = StorageRegistry(tmp_path)
    source, first, artifact = _bundle(registry)
    second = StageArtifactRef(stage_id="train", artifact_name="best_model")
    first_key = registry.register_artifact(source, first, artifact)
    second_key = registry.register_artifact(source, second, artifact)
    assert first_key != second_key

    registry.set_retention(source, first, "offload")
    assert not _permission(
        registry, artifact.members[0].file, default_offload=False
    )
    registry.set_retention(source, second, "offload")
    assert _permission(registry, artifact.members[0].file, default_offload=False)
    registry.set_retention(source, second, "keep")
    assert not _permission(registry, artifact.members[0].file, default_offload=True)


def test_distinct_versions_share_votes_without_merging_identity(tmp_path: Path) -> None:
    """A changed bundle is a distinct version even when checkpoint bytes match."""
    registry = StorageRegistry(tmp_path)
    first, selection, old = _bundle(registry)
    second, _, new = _bundle(registry, config=b"configuration-two")
    assert first != second
    assert old.members[1].file == new.members[1].file

    registry.set_retention(first, selection, "keep")
    registry.set_retention(second, selection, "offload")
    assert not _permission(registry, new.members[1].file, default_offload=True)
    assert _permission(registry, new.members[0].file, default_offload=False)


def test_repeated_registration_and_restart_preserve_preference(tmp_path: Path) -> None:
    """Later workflows reuse the same registration without adding or resetting votes."""
    registry = StorageRegistry(tmp_path)
    source, selection, artifact = _bundle(registry)
    key = registry.register_artifact(source, selection, artifact)
    registry.set_retention(source, selection, "keep")

    reopened = StorageRegistry(tmp_path)
    for _ in range(3):
        assert reopened.register_artifact(source, selection, artifact) == key
    assert reopened.retention(source, selection) == "keep"
    assert not _permission(reopened, artifact.members[0].file, default_offload=True)


def test_artifact_registration_rejects_changed_bundle_membership(tmp_path: Path) -> None:
    """A later registration cannot silently replace a bundle with one member."""
    registry = StorageRegistry(tmp_path)
    source, selection, artifact = _bundle(registry)
    subset = ResolvedSingleFileArtifact(
        relative_path="artifacts/model/weights.bin", file=artifact.members[1].file
    )

    with pytest.raises(StorageRegistryError, match="registered artifact changed"):
        registry.register_artifact(source, selection, subset)


def test_artifact_registration_rejects_unsealed_member(tmp_path: Path) -> None:
    """An artifact cannot subscribe to identities outside its sealed snapshot."""
    registry = StorageRegistry(tmp_path)
    source, _, artifact = _bundle(registry)
    changed = artifact.members[0].file.model_copy(
        update={"bytes": artifact.members[0].file.bytes + 1}
    )
    incorrect = ResolvedSingleFileArtifact(
        relative_path="artifacts/model/config.json", file=changed
    )

    with pytest.raises(StorageRegistryError, match="artifact differs"):
        registry.register_artifact(
            source,
            StageArtifactRef(stage_id="train", artifact_name="incorrect"),
            incorrect,
        )


def test_standalone_input_can_keep_without_a_producer_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registered dataset member receives keep through its existing source path."""
    registry = StorageRegistry(tmp_path)
    source, artifact = _input_version(registry)
    calls: list[ResolvedFileRef] = []

    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
        """Confirm that dataset keep is durable before materialization starts."""
        assert storage.registry.retention(source, artifact.file.path) == "keep"
        calls.append(reference)
        return tmp_path / reference.stored_at.path

    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
    set_artifact_retention(tmp_path, source, artifact.file.path, "keep")

    assert len(calls) == 1
    assert calls[0].sha256 == artifact.file.sha256
    assert not _permission(registry, artifact.file, default_offload=True)
    key = registry.register_artifact(source, artifact.file.path, artifact)
    reopened = StorageRegistry(tmp_path)
    assert reopened.register_artifact(source, artifact.file.path, artifact) == key
    assert reopened.retention(source, artifact.file.path) == "keep"


def test_changed_input_is_a_new_version_with_an_independent_override(
    tmp_path: Path,
) -> None:
    """New dataset bytes at the same logical path do not inherit an old override."""
    registry = StorageRegistry(tmp_path)
    old, old_artifact = _input_version(registry)
    registry.set_retention(old, old_artifact.file.path, "keep")
    new, new_artifact = _input_version(registry, b"training-records-version-two")

    assert old != new
    assert old_artifact.file.path == new_artifact.file.path
    assert registry.retention(new, new_artifact.file.path) == "inherit"
    assert not _permission(registry, old_artifact.file, default_offload=True)
    assert _permission(registry, new_artifact.file, default_offload=True)


def test_member_selector_rejects_a_whole_bundle(tmp_path: Path) -> None:
    """A member selector cannot silently stand in for a multi-file artifact."""
    registry = StorageRegistry(tmp_path)
    source, _, artifact = _bundle(registry)

    with pytest.raises(StorageRegistryError, match="artifact must contain only"):
        registry.register_artifact(source, artifact.members[0].file.path, artifact)


def test_keep_resolves_every_member_after_persisting_preference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit keep records its veto before invoking normal full-bundle resolution."""
    registry = StorageRegistry(tmp_path)
    source, selection, _ = _bundle(registry)
    expected = registry.artifact_files(source, selection)
    calls: list[ResolvedFileRef] = []

    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
        """Observe the retained preference while standing in for the normal resolver."""
        assert storage.registry.retention(source, selection) == "keep"
        calls.append(reference)
        return tmp_path / reference.stored_at.path

    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
    set_artifact_retention(tmp_path, source, selection, "keep")

    assert tuple(calls) == expected
    assert len(calls) == 2


def test_keep_uses_current_registry_with_missing_original_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An old workspace address cannot redirect keep out of the active registry."""
    registry = StorageRegistry(tmp_path)
    old_workspace = tmp_path / "removed-producing-workspace"
    source, selection, _ = _bundle(registry, source_workspace=old_workspace)
    expected = registry.artifact_files(source, selection)
    original = registry.snapshot(source)
    calls: list[ResolvedFileRef] = []

    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
        """Observe keep admission before ordinary current-host materialization."""
        assert storage.repository_root == tmp_path
        assert storage.registry.retention(source, selection) == "keep"
        assert isinstance(reference.stored_at, LocalFileRef)
        assert reference.stored_at.workspace == old_workspace
        calls.append(reference)
        return tmp_path / "current-cache" / reference.stored_at.path

    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
    set_artifact_retention(tmp_path, source, selection, "keep")

    assert tuple(calls) == expected
    assert registry.retention(source, selection) == "keep"
    assert registry.snapshot(source) == original
    assert not old_workspace.exists()


def test_failed_keep_preserves_the_preference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed second member does not erase a committed keep decision."""
    registry = StorageRegistry(tmp_path)
    source, selection, _ = _bundle(registry)
    calls: list[ResolvedFileRef] = []

    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
        """Fail a later member after confirming that keep already committed."""
        assert storage.registry.retention(source, selection) == "keep"
        calls.append(reference)
        if len(calls) == 2:
            raise OSError("cloud unavailable")
        return tmp_path / reference.stored_at.path

    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
    with pytest.raises(OSError, match="cloud unavailable"):
        set_artifact_retention(tmp_path, source, selection, "keep")

    assert len(calls) == 2
    assert StorageRegistry(tmp_path).retention(source, selection) == "keep"


@pytest.mark.parametrize("preference", ["inherit", "offload"])
def test_non_keep_changes_do_not_materialize_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preference: Literal["inherit", "offload"],
) -> None:
    """A policy update does not download a previously evicted artifact."""
    registry = StorageRegistry(tmp_path)
    source, selection, _ = _bundle(registry)

    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
        """Fail if a policy-only update accidentally requests payload bytes."""
        raise AssertionError("policy-only update invoked the resolver")

    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
    set_artifact_retention(tmp_path, source, selection, preference)
    assert registry.retention(source, selection) == preference


def test_retention_extends_an_existing_inventory_registry(tmp_path: Path) -> None:
    """PB04 adds only its tables when upgrading a registry already used by PB02."""
    registry = StorageRegistry(tmp_path)
    source, selection, artifact = _bundle(registry)
    original = registry.snapshot(source)
    with sqlite3.connect(registry.path) as connection:
        connection.execute("DROP TABLE artifact_members")
        connection.execute("DROP TABLE artifact_versions")

    reopened = StorageRegistry(tmp_path)
    assert reopened.snapshot(source) == original
    reopened.register_artifact(source, selection, artifact)
    assert reopened.retention(source, selection) == "inherit"


def test_retention_policy_is_independent_of_publication_destination() -> None:
    """Offload may be enabled while new publications still select local storage."""
    settings = StorageSettings(destination=LocalStorageDestination(), offload=True)
    assert settings.offload
    assert settings.repository is None


def test_cloud_publication_still_requires_a_repository() -> None:
    """Decoupling retention does not permit an incomplete cloud destination."""
    with pytest.raises(ValidationError, match="repository is required"):
        StorageSettings(
            destination=ViperCloudDestination(owner="peter", workspace="models")
        )
