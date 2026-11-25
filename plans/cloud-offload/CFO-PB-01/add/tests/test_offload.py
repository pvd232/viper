"""Verify exact original snapshot bindings without changing their identities."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from viper._cloud import (
    RevisionManifest,
    SnapshotCopy,
    SnapshotInventory,
    manifest_revision,
)
from viper.execution._promotion_journal import validate_exact_snapshot_copy
from viper.execution.errors import RunPromotionError
from viper.references import LocalStageResultSnapshotRef, SnapshotFileRef
from viper.storage import snapshot_file


def _members(files: dict[str, bytes]) -> tuple[SnapshotFileRef, ...]:
    """Use the existing file-identity owner to describe complete source bytes."""
    return tuple(snapshot_file(path, raw) for path, raw in sorted(files.items()))


def _copy(
    root: Path,
    original: tuple[SnapshotFileRef, ...],
    destination: tuple[SnapshotFileRef, ...],
    *,
    commit: str | None = None,
) -> SnapshotCopy:
    """Bind one immutable local snapshot to an independently declared copy."""
    return SnapshotCopy(
        source=LocalStageResultSnapshotRef(
            workspace=root,
            commit=commit or manifest_revision(original),
        ),
        source_files=original,
        expected=RevisionManifest(
            owner="machina",
            workspace="offload",
            revision=manifest_revision(destination),
            files=destination,
        ),
        dependencies_sha256=hashlib.sha256(b"[]").hexdigest(),
        previous_head=None,
    )


def test_offload_binding_preserves_original_snapshot_identity(tmp_path: Path) -> None:
    """Accept exact member copies without changing the original reference."""
    members = _members({"model/config.json": b"{}", "model/weights.bin": b"weights"})
    copy = _copy(tmp_path, members, members)
    source_before = copy.source.model_dump(mode="json")

    assert validate_exact_snapshot_copy(copy) is copy
    assert copy.source.model_dump(mode="json") == source_before
    assert copy.source_files == copy.expected.files
    assert SnapshotInventory(source=copy.source, source_files=members).source == copy.source


@pytest.mark.parametrize("change_source", [False, True])
def test_offload_binding_rejects_changed_payload(
    tmp_path: Path, change_source: bool
) -> None:
    """Reject destination changes and joint tampering under the original seal."""
    original = _members({"model/weights.bin": b"weights"})
    changed = _members({"model/weights.bin": b"changed"})
    source = changed if change_source else original
    copy = _copy(tmp_path, source, changed, commit=manifest_revision(original))

    with pytest.raises(RunPromotionError, match="inventory"):
        validate_exact_snapshot_copy(copy)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate"])
def test_offload_binding_rejects_changed_snapshot_membership(
    tmp_path: Path, change: str
) -> None:
    """Reject member-set changes, including duplicate original member paths."""
    original = _members({"model/config.json": b"{}", "model/weights.bin": b"weights"})
    if change == "duplicate":
        source = original + (original[-1],)
        destination = original
    elif change == "missing":
        source = original
        destination = original[:1]
    else:
        source = original
        destination = _members(
            {
                "model/config.json": b"{}",
                "model/extra.bin": b"extra",
                "model/weights.bin": b"weights",
            }
        )
    copy = _copy(tmp_path, source, destination, commit=manifest_revision(original))

    with pytest.raises(RunPromotionError, match="inventory"):
        validate_exact_snapshot_copy(copy)

