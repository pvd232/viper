"""Exercise VIPER retention for closed files outside an ML run graph."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from viper.cloud import ViperCloud
from viper.file_retention import FileEvictionError, evict_cloud_backed_files
from viper.references import GcsFileRef, LocalFileRef, ResolvedFileRef


class MemoryCloud(ViperCloud):
    """Control remote bytes while exercising actual VIPER retention."""

    def __init__(self, files: dict[str, bytes]) -> None:
        """Bind the declared remote bytes and optional local-change callback."""
        self.files = files
        self.change: Path | None = None
        self.reads = 0

    def verify_file(self, reference: ResolvedFileRef) -> None:
        """Reject changed remote bytes and optionally mutate a local producer output."""
        self.reads += 1
        raw = self.files[reference.stored_at.path]
        if (
            len(raw) != reference.bytes
            or hashlib.sha256(raw).hexdigest() != reference.sha256
        ):
            raise ValueError("remote bytes changed")
        if self.change is not None:
            self.change.write_bytes(b"changed by producer")


def reference(path: str, raw: bytes) -> ResolvedFileRef:
    """Identify one raw artifact in an immutable synthetic GCS revision."""
    return ResolvedFileRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=GcsFileRef(
            bucket="artifacts",
            prefix="viper",
            owner="aether",
            workspace="browser",
            revision="1" * 64,
            path=path,
        ),
    )


def test_verified_files_are_removed_and_repeat_is_empty(tmp_path: Path) -> None:
    """Remove exact cloud-backed bytes once and preserve a neighboring report."""
    (tmp_path / "trace.zip").write_bytes(b"trace")
    (tmp_path / "report.json").write_bytes(b"report")
    ref = reference("trace.zip", b"trace")
    cloud = MemoryCloud({"trace.zip": b"trace"})
    result = evict_cloud_backed_files(tmp_path, (ref, ref), cloud=cloud)
    assert result.bytes_released == 5
    assert len(result.artifacts) == 1
    assert not (tmp_path / "trace.zip").exists()
    assert (tmp_path / "report.json").read_bytes() == b"report"
    assert evict_cloud_backed_files(tmp_path, (ref,), cloud=cloud).bytes_released == 0


def test_remote_failure_preserves_the_entire_selection(tmp_path: Path) -> None:
    """A later verification failure preserves the earlier verified local file."""
    for name in ("a.zip", "b.zip"):
        (tmp_path / name).write_bytes(b"trace")
    cloud = MemoryCloud({"a.zip": b"trace", "b.zip": b"corrupt"})
    refs = tuple(reference(name, b"trace") for name in ("a.zip", "b.zip"))
    with pytest.raises(FileEvictionError, match="cloud artifact"):
        evict_cloud_backed_files(tmp_path, refs, cloud=cloud)
    assert all((tmp_path / name).exists() for name in ("a.zip", "b.zip"))


def test_changed_local_bytes_are_kept(tmp_path: Path) -> None:
    """A prior local edit cannot be erased using an older remote reference."""
    (tmp_path / "trace.zip").write_bytes(b"new local evidence")
    with pytest.raises(FileEvictionError, match="local artifact identity"):
        evict_cloud_backed_files(
            tmp_path,
            (reference("trace.zip", b"trace"),),
            cloud=MemoryCloud({"trace.zip": b"trace"}),
        )
    assert (tmp_path / "trace.zip").read_bytes() == b"new local evidence"


def test_source_change_during_remote_read_is_kept(tmp_path: Path) -> None:
    """A producer edit during remote verification survives the final local check."""
    path = tmp_path / "trace.zip"
    path.write_bytes(b"trace")
    cloud = MemoryCloud({"trace.zip": b"trace"})
    cloud.change = path
    with pytest.raises(FileEvictionError, match="local artifact identity"):
        evict_cloud_backed_files(
            tmp_path, (reference("trace.zip", b"trace"),), cloud=cloud
        )
    assert path.read_bytes() == b"changed by producer"


def test_time_and_size_policy_retain_hot_and_small_files(tmp_path: Path) -> None:
    """VIPER applies the hot-copy window and the retained-report size threshold."""
    path = tmp_path / "trace.zip"
    path.write_bytes(b"trace")
    ref = reference("trace.zip", b"trace")
    cloud = MemoryCloud({"trace.zip": b"trace"})
    assert (
        evict_cloud_backed_files(
            tmp_path,
            (ref,),
            cloud=cloud,
            not_before=datetime.now(UTC) + timedelta(hours=1),
        ).bytes_released
        == 0
    )
    assert (
        evict_cloud_backed_files(
            tmp_path, (ref,), cloud=cloud, minimum_bytes=6
        ).bytes_released
        == 0
    )
    assert cloud.reads == 0
    assert path.exists()


def test_unsafe_local_path_is_refused(tmp_path: Path) -> None:
    """An artifact symlink cannot make retention delete an outside file."""
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_bytes(b"trace")
    try:
        (tmp_path / "trace.zip").symlink_to(outside)
        with pytest.raises(FileEvictionError):
            evict_cloud_backed_files(
                tmp_path,
                (reference("trace.zip", b"trace"),),
                cloud=MemoryCloud({"trace.zip": b"trace"}),
            )
        assert outside.read_bytes() == b"trace"
    finally:
        outside.unlink()


def test_local_only_and_conflicting_references_are_refused(tmp_path: Path) -> None:
    """A local reference or conflicting identity cannot authorize removal."""
    path = tmp_path / "trace.zip"
    path.write_bytes(b"trace")
    local = ResolvedFileRef(
        sha256=hashlib.sha256(b"trace").hexdigest(),
        bytes=5,
        stored_at=LocalFileRef(
            workspace=str(tmp_path.resolve()), commit="1" * 64, path="trace.zip"
        ),
    )
    cloud = MemoryCloud({"trace.zip": b"trace"})
    with pytest.raises(FileEvictionError, match="not stored"):
        evict_cloud_backed_files(tmp_path, (local,), cloud=cloud)
    with pytest.raises(FileEvictionError, match="conflicting"):
        evict_cloud_backed_files(
            tmp_path,
            (reference("trace.zip", b"trace"), reference("trace.zip", b"other")),
            cloud=cloud,
        )
    assert path.exists()


def test_naive_retention_time_is_refused(tmp_path: Path) -> None:
    """A timezone-free retention boundary cannot silently change eviction time."""
    with pytest.raises(ValueError, match="timezone"):
        evict_cloud_backed_files(tmp_path, (), not_before=datetime(2030, 1, 1))
