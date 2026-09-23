"""Verify the production GCS adapter without contacting Google Cloud."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from google.api_core.exceptions import PreconditionFailed

from viper._cloud import ViperCloudError, manifest_revision
from viper.gcs import (
    GCS_OPERATION_TIMEOUT_SECONDS,
    GcsProgressEvent,
    GcsProvider,
    probe_gcs_storage,
)
from viper.references import GcsFileRef, GcsStageResultSnapshotRef, SnapshotFileRef
from viper.storage import ViperCloudDestination


class _Blob:
    """Model the GCS blob operations used by the production adapter."""

    def __init__(self, bucket: _Bucket, name: str) -> None:
        """Bind one object name to the shared fake bucket."""
        self.bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None

    def upload_from_string(
        self,
        raw: bytes,
        *,
        content_type: str,
        if_generation_match: int,
        checksum: str,
        timeout: float,
    ) -> None:
        """Create an object only when its key is absent."""
        assert content_type == "application/octet-stream"
        assert if_generation_match == 0
        assert checksum == "auto"
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        if self.name in self.bucket.objects:
            raise PreconditionFailed("object exists")
        self.bucket.next_generation += 1
        self.generation = self.bucket.next_generation
        self.bucket.objects[self.name] = (
            raw,
            dict(self.metadata or {}),
            self.generation,
        )

    def upload_from_filename(
        self,
        filename: str,
        *,
        content_type: str,
        if_generation_match: int,
        checksum: str,
        timeout: float,
    ) -> None:
        """Model the streaming upload path used for file-backed sources."""
        with Path(filename).open("rb") as stream:
            raw = stream.read()
        self.upload_from_string(
            raw,
            content_type=content_type,
            if_generation_match=if_generation_match,
            checksum=checksum,
            timeout=timeout,
        )

    def download_as_bytes(self, *, checksum: str, timeout: float) -> bytes:
        """Return the current object bytes."""
        assert checksum == "auto"
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        self.bucket.download_calls.append(self.name)
        return self.bucket.objects[self.name][0]

    def download_to_filename(
        self,
        filename: str,
        *,
        checksum: str,
        timeout: float,
    ) -> None:
        """Model a streamed object download to one local file."""
        assert checksum == "auto"
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        with Path(filename).open("wb") as stream:
            stream.write(self.bucket.objects[self.name][0])

    def download_to_file(
        self,
        stream: Any,
        *,
        if_generation_match: int,
        checksum: str,
        timeout: float,
    ) -> None:
        """Stream the selected immutable generation to a file-like consumer."""
        assert checksum == "auto"
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        raw, _, generation = self.bucket.objects[self.name]
        assert generation == if_generation_match
        stream.write(raw)

    def reload(self, *, timeout: float) -> None:
        """Load the current object's metadata and generation."""
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        raw, metadata, generation = self.bucket.objects[self.name]
        assert raw is not None
        self.metadata = dict(metadata)
        self.generation = generation


class _Bucket:
    """Hold immutable objects and model one server-side copy."""

    def __init__(self) -> None:
        """Start with no cloud objects."""
        self.objects: dict[str, tuple[bytes, dict[str, str], int]] = {}
        self.next_generation = 0
        self.copy_calls: list[tuple[str, str]] = []
        self.download_calls: list[str] = []

    def blob(self, name: str) -> _Blob:
        """Return a handle for one object name."""
        return _Blob(self, name)

    def copy_blob(
        self,
        source: _Blob,
        destination_bucket: _Bucket,
        *,
        new_name: str,
        if_generation_match: int,
        if_source_generation_match: int | None,
        timeout: float,
    ) -> _Blob:
        """Copy the selected source generation into one absent destination."""
        assert destination_bucket is self
        assert if_generation_match == 0
        assert timeout == GCS_OPERATION_TIMEOUT_SECONDS
        if new_name in self.objects:
            raise PreconditionFailed("object exists")
        raw, metadata, generation = self.objects[source.name]
        assert generation == if_source_generation_match
        self.next_generation += 1
        self.objects[new_name] = (raw, dict(metadata), self.next_generation)
        self.copy_calls.append((source.name, new_name))
        return self.blob(new_name)


class _Client:
    """Return one fake bucket through the Google client boundary."""

    def __init__(self) -> None:
        """Create the shared bucket."""
        self.selected_bucket: str | None = None
        self.value = _Bucket()

    def bucket(self, name: str) -> _Bucket:
        """Record and return the selected bucket."""
        self.selected_bucket = name
        return self.value


def _client(root: Path) -> tuple[GcsProvider, _Client]:
    """Create the production adapter over an inspectable fake GCS client."""
    fake = _Client()
    client = GcsProvider(
        root,
        "mantra-fixture",
        prefix="viper",
        client=cast(Any, fake),
    )
    return client, fake


def _client_with_progress(
    root: Path,
) -> tuple[GcsProvider, _Client, list[GcsProgressEvent]]:
    """Create the GCS adapter and capture its structured progress events."""
    fake = _Client()
    events: list[GcsProgressEvent] = []
    client = GcsProvider(
        root,
        "mantra-fixture",
        prefix="viper",
        client=cast(Any, fake),
        progress=events.append,
    )
    return client, fake, events


def test_publishes_and_restores_durable_snapshot(tmp_path: Path) -> None:
    """Seal a probe, restore identical bytes, and retain its durable reference."""
    client, fake = _client(tmp_path)
    destination = ViperCloudDestination(owner="machina", workspace="mantra")
    receipt_path = tmp_path / ".viper" / "probes" / "gcs.json"

    receipt = probe_gcs_storage(
        tmp_path,
        destination,
        client,
        receipt_path,
    )

    assert fake.selected_bucket == "mantra-fixture"
    assert receipt.passed is True
    assert receipt.sha256 == receipt.restored_sha256
    assert json.loads(receipt_path.read_text()) == receipt.model_dump(mode="json")
    revision = receipt.artifact_uri.split("@", 1)[1].split("/", 1)[0]
    file_key = f"viper/machina/mantra/{revision}/.viper/probes/gcs-storage.bin"
    assert file_key in fake.value.objects
    assert f"viper/machina/mantra/{revision}.manifest.json" in fake.value.objects
    assert fake.value.objects[file_key][0] == b"VIPER GCS storage probe\n"
    location = GcsFileRef(
        bucket="mantra-fixture",
        prefix="viper",
        owner="machina",
        workspace="mantra",
        revision=revision,
        path=".viper/probes/gcs-storage.bin",
    )
    client.verify_file(
        location,
        SnapshotFileRef(
            path=location.path,
            sha256=receipt.sha256,
            bytes=len(b"VIPER GCS storage probe\n"),
        ),
    )

    repeated = probe_gcs_storage(
        tmp_path,
        destination,
        client,
        receipt_path,
    )
    assert repeated == receipt


def test_streams_file_backed_publication(tmp_path: Path) -> None:
    """Upload a root-confined path without calling its ``read_bytes`` method."""
    client, fake = _client(tmp_path)
    source = tmp_path / "large.bin"
    source.write_bytes(b"bounded blocks")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with patch.object(
        Path,
        "read_bytes",
        side_effect=AssertionError("loaded whole file"),
    ):
        client.upload(
            owner="machina",
            workspace="mantra",
            revision="b" * 64,
            path="data/large.bin",
            source=source,
            sha256=digest,
            bytes=source.stat().st_size,
        )

    key = f"viper/machina/mantra/{'b' * 64}/data/large.bin"
    assert fake.value.objects[key][0] == b"bounded blocks"


def test_idempotent_upload_checks_metadata_without_downloading(
    tmp_path: Path,
) -> None:
    """Accept an existing upload from metadata without reading payload bytes."""
    client, fake = _client(tmp_path)
    raw = b"bounded blocks"
    digest = hashlib.sha256(raw).hexdigest()
    key = f"viper/machina/mantra/{'b' * 64}/data/large.bin"

    client.upload(
        owner="machina",
        workspace="mantra",
        revision="b" * 64,
        path="data/large.bin",
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )
    client.upload(
        owner="machina",
        workspace="mantra",
        revision="b" * 64,
        path="data/large.bin",
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )

    assert key not in fake.value.download_calls


def test_idempotent_upload_emits_reuse_progress(tmp_path: Path) -> None:
    """Report metadata-backed upload reuse with the exact object path."""
    client, fake, events = _client_with_progress(tmp_path)
    raw = b"bounded blocks"
    digest = hashlib.sha256(raw).hexdigest()
    path = "data/large.bin"
    revision = "b" * 64
    key = f"viper/machina/mantra/{revision}/{path}"

    client.upload(
        owner="machina",
        workspace="mantra",
        revision=revision,
        path=path,
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )
    client.upload(
        owner="machina",
        workspace="mantra",
        revision=revision,
        path=path,
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )

    assert key not in fake.value.download_calls
    assert events[-1] == GcsProgressEvent(
        phase="upload_reuse",
        bucket="mantra-fixture",
        key=key,
        owner="machina",
        workspace="mantra",
        revision=revision,
        path=path,
        bytes=len(raw),
    )


def test_streams_sealed_file_restore(tmp_path: Path) -> None:
    """Restore a sealed object without returning its complete byte payload."""
    client, _ = _client(tmp_path)
    destination = ViperCloudDestination(owner="machina", workspace="mantra")
    source = tmp_path / "large.bin"
    source.write_bytes(b"bounded blocks")
    snapshot, files = client.publish(destination, {"data/large.bin": source})
    reference = client.file_ref(snapshot, "data/large.bin")
    identity = files[0]

    restored = client.fetch_to_path(
        reference,
        identity,
        destination=tmp_path / "restored/large.bin",
    )

    assert restored.read_bytes() == b"bounded blocks"


def test_reuses_loaded_manifest_for_repeated_snapshot_reads(tmp_path: Path) -> None:
    """Use cached manifests while restoring several files from one snapshot."""
    client, fake, events = _client_with_progress(tmp_path)
    destination = ViperCloudDestination(owner="machina", workspace="mantra")
    snapshot, identities = client.publish(
        destination,
        {
            "runs/source/a.bin": b"alpha",
            "runs/source/b.bin": b"beta",
        },
    )
    assert isinstance(snapshot, GcsStageResultSnapshotRef)

    first = client.file_ref(snapshot, "runs/source/a.bin")
    second = client.file_ref(snapshot, "runs/source/b.bin")
    assert client.fetch(first) == b"alpha"
    client.verify_file(second, identities[1])
    assert client.list_files(snapshot) == identities

    manifest_key = f"viper/machina/mantra/{snapshot.revision}.manifest.json"
    assert fake.value.download_calls.count(manifest_key) == 0
    manifest_events = [event.phase for event in events if event.key == manifest_key]
    assert manifest_events.count("seal_done") == 1
    assert manifest_events.count("manifest_cache_hit") == 3
    fetch_events = [
        event
        for event in events
        if event.path == "runs/source/a.bin"
        and event.phase in {"fetch_start", "fetch_done"}
    ]
    assert [event.phase for event in fetch_events] == ["fetch_start", "fetch_done"]
    assert {event.bytes for event in fetch_events} == {len(b"alpha")}


def test_stream_restore_emits_source_and_destination_progress(
    tmp_path: Path,
) -> None:
    """Report streamed restore start and completion for one exact GCS object."""
    client, _, events = _client_with_progress(tmp_path)
    destination = ViperCloudDestination(owner="machina", workspace="mantra")
    snapshot, files = client.publish(destination, {"data/large.bin": b"bounded"})
    assert isinstance(snapshot, GcsStageResultSnapshotRef)
    reference = client.file_ref(snapshot, "data/large.bin")
    identity = files[0]

    restored = client.fetch_to_path(
        reference,
        identity,
        destination=tmp_path / "restored/large.bin",
    )

    assert restored.read_bytes() == b"bounded"
    key = f"viper/machina/mantra/{snapshot.revision}/data/large.bin"
    stream_events = [
        event
        for event in events
        if event.key == key and event.phase.startswith("stream")
    ]
    assert [event.phase for event in stream_events] == [
        "stream_fetch_start",
        "stream_fetch_done",
    ]
    assert {event.path for event in stream_events} == {"data/large.bin"}
    assert {event.bytes for event in stream_events} == {len(b"bounded")}


def test_rejects_changed_or_missing_cloud_object(tmp_path: Path) -> None:
    """Reject payload substitution and any file omitted by the sealed manifest."""
    client, fake = _client(tmp_path)
    destination = ViperCloudDestination(owner="machina", workspace="mantra")
    receipt = probe_gcs_storage(
        tmp_path,
        destination,
        client,
        tmp_path / "probe.json",
    )
    revision = receipt.artifact_uri.split("@", 1)[1].split("/", 1)[0]
    path = ".viper/probes/gcs-storage.bin"
    location = GcsFileRef(
        bucket="mantra-fixture",
        prefix="viper",
        owner="machina",
        workspace="mantra",
        revision=revision,
        path=path,
    )
    key = f"viper/machina/mantra/{revision}/{path}"
    _, metadata, generation = fake.value.objects[key]
    fake.value.objects[key] = (b"changed", metadata, generation + 1)

    with pytest.raises(ViperCloudError, match="identity changed"):
        client.fetch(location)
    with pytest.raises(ViperCloudError, match="identity changed"):
        client.verify_file(
            location,
            SnapshotFileRef(
                path=path,
                sha256=receipt.sha256,
                bytes=len(b"VIPER GCS storage probe\n"),
            ),
        )
    with pytest.raises(ViperCloudError, match="no requested file"):
        client.fetch(
            GcsFileRef(
                bucket="mantra-fixture",
                prefix="viper",
                owner="machina",
                workspace="mantra",
                revision=revision,
                path="missing.bin",
            )
        )


def test_server_side_copy_preserves_identity_and_requires_a_sealed_source(
    tmp_path: Path,
) -> None:
    """Copy a sealed file without downloading it and expose it only after sealing."""
    client, fake, events = _client_with_progress(tmp_path)
    raw = b"parameters"
    digest = hashlib.sha256(raw).hexdigest()
    source = GcsFileRef(
        bucket="mantra-fixture",
        prefix="viper",
        owner="machina",
        workspace="mantra",
        revision="a" * 64,
        path="runs/source/model.bin",
    )
    client.upload(
        owner=source.owner,
        workspace=source.workspace,
        revision=source.revision,
        path=source.path,
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )
    with pytest.raises(ViperCloudError, match="not sealed"):
        client.copy(
            source=source,
            target=GcsFileRef(
                bucket="mantra-fixture",
                prefix="viper",
                owner="machina",
                workspace="mantra",
                revision="b" * 64,
                path="runs/target/model.bin",
            ),
            sha256=digest,
            bytes=len(raw),
        )

    source_file = SnapshotFileRef(
        path=source.path,
        sha256=digest,
        bytes=len(raw),
    )
    actual_revision = manifest_revision((source_file,))
    client.upload(
        owner=source.owner,
        workspace=source.workspace,
        revision=actual_revision,
        path=source.path,
        source=raw,
        sha256=digest,
        bytes=len(raw),
    )
    client.seal(
        owner=source.owner,
        workspace=source.workspace,
        revision=actual_revision,
        files=(source_file,),
    )
    target_path = "runs/target/model.bin"
    target_file = SnapshotFileRef(path=target_path, sha256=digest, bytes=len(raw))
    target_revision_value = manifest_revision((target_file,))
    client.copy(
        source=source.model_copy(update={"revision": actual_revision}),
        target=GcsFileRef(
            bucket="mantra-fixture",
            prefix="viper",
            owner="machina",
            workspace="mantra",
            revision=target_revision_value,
            path=target_path,
        ),
        sha256=digest,
        bytes=len(raw),
    )
    fake.value.download_calls.clear()
    client.copy(
        source=source.model_copy(update={"revision": actual_revision}),
        target=GcsFileRef(
            bucket="mantra-fixture",
            prefix="viper",
            owner="machina",
            workspace="mantra",
            revision=target_revision_value,
            path=target_path,
        ),
        sha256=digest,
        bytes=len(raw),
    )
    client.seal(
        owner="machina",
        workspace="mantra",
        revision=target_revision_value,
        files=(target_file,),
    )

    assert fake.value.copy_calls
    target_key = f"viper/machina/mantra/{target_revision_value}/{target_path}"
    assert target_key not in fake.value.download_calls
    copy_events = [
        event
        for event in events
        if event.key == target_key and event.phase.startswith("copy")
    ]
    assert [event.phase for event in copy_events] == [
        "copy_start",
        "copy_done",
        "copy_start",
        "copy_reuse",
    ]
    assert {event.path for event in copy_events} == {target_path}
    assert {event.bytes for event in copy_events} == {len(raw)}
    assert (
        client.fetch(
            GcsFileRef(
                bucket="mantra-fixture",
                prefix="viper",
                owner="machina",
                workspace="mantra",
                revision=target_revision_value,
                path=target_path,
            )
        )
        == raw
    )
