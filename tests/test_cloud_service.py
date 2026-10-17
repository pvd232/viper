"""Acceptance tests for provider-neutral ViperCloud dispatch."""

from __future__ import annotations

import hashlib
import inspect
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from tests.fixtures import MemoryHub
from tests.test_storage import InMemoryViperCloudProvider
from viper import execution
from viper._cloud import (
    GcsRepository,
    HuggingFaceRepository,
    ViperCloudDestination,
    ViperCloudError,
)
from viper._source import RunFetcher
from viper.authoring import freeze_run_plan
from viper.cloud import ViperCloud
from viper.execution._promotion_journal import PublicationJournal
from viper.execution._promotion_transfer import (
    TransferSpace,
    directory_bytes,
)
from viper.execution.errors import RunPromotionError
from viper.huggingface import HuggingFaceProvider
from viper.references import (
    GcsFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
)
from viper.storage import LocalArtifactStore, RunPromotionPolicy, TransferLimits


class _HuggingFaceApi:
    """Capture one atomic repository commit in memory."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.create_repo_calls = 0
        self.create_commit_calls = 0

    def create_repo(self, **kwargs: Any) -> None:
        self.create_repo_calls += 1

    def create_commit(self, *, operations: list[Any], **kwargs: Any) -> Any:
        self.create_commit_calls += 1
        for operation in operations:
            payload = operation.path_or_fileobj
            if isinstance(payload, BytesIO):
                self.files[operation.path_in_repo] = payload.getvalue()
            else:
                self.files[operation.path_in_repo] = Path(payload).read_bytes()
        return SimpleNamespace(oid="a" * 40)


def test_hugging_face_repository_publishes_one_self_describing_reference(
    tmp_path: Path,
) -> None:
    """Keep provider selection inside ViperCloud and return an HF file ref."""
    api = _HuggingFaceApi()
    provider = HuggingFaceProvider(
        tmp_path,
        "machina/viper-artifacts",
        "dataset",
        api=cast(Any, api),
    )
    cloud = ViperCloud(
        tmp_path,
        HuggingFaceRepository(
            repository="machina/viper-artifacts",
            repo_type="dataset",
        ),
        provider=provider,
    )

    references = cloud.resolved_files(
        ViperCloudDestination(owner="machina", workspace="models"),
        {"runs/example/resolved.yaml": b"status: succeeded\n"},
    )

    reference = references["runs/example/resolved.yaml"]
    assert isinstance(reference.stored_at, HuggingFaceFileRef)
    assert reference.stored_at.repository == "machina/viper-artifacts"
    assert reference.stored_at.commit == "a" * 40
    assert api.create_repo_calls == 1
    assert api.create_commit_calls == 1
    assert set(api.files) == {
        ".viper/revision-manifest.json",
        "runs/example/resolved.yaml",
    }


def test_hugging_face_snapshot_resolves_through_the_same_service(
    tmp_path: Path,
) -> None:
    """Create the configured provider from a self-describing HF snapshot ref."""
    snapshot = HuggingFaceStageResultSnapshotRef(
        repository="machina/viper-artifacts",
        commit="a" * 40,
        repo_type="dataset",
    )

    cloud = ViperCloud.for_snapshot(tmp_path, snapshot)

    assert isinstance(cloud.repository, HuggingFaceRepository)
    assert cloud.repository.repository == snapshot.repository
    assert cloud.repository.repo_type == snapshot.repo_type


def test_gcs_repository_receives_progress_sink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass GCS progress reporting through the provider-neutral cloud service."""
    captured: dict[str, Any] = {}

    class _Provider(InMemoryViperCloudProvider):
        def __init__(
            self,
            root: Path,
            bucket: str,
            *,
            prefix: str,
            progress: Any,
        ) -> None:
            captured["root"] = root
            captured["bucket"] = bucket
            captured["prefix"] = prefix
            captured["progress"] = progress
            super().__init__(root)

    monkeypatch.setattr("viper.cloud.GcsProvider", _Provider)
    events: list[Any] = []

    cloud = ViperCloud(
        tmp_path,
        GcsRepository(bucket="test-bucket", prefix="artifacts"),
        progress=events.append,
    )

    assert isinstance(cloud.provider, _Provider)
    assert captured == {
        "root": tmp_path.resolve(),
        "bucket": "test-bucket",
        "prefix": "artifacts",
        "progress": events.append,
    }


def test_public_execution_signatures_do_not_expose_provider_clients() -> None:
    """Keep provider construction inside VIPER's workspace boundary."""
    operations = (
        execution.run,
        execution.retry,
        execution.restore,
        execution.benchmark,
        execution.export_run,
        freeze_run_plan,
    )

    assert all(
        "cloud_client" not in inspect.signature(operation).parameters
        for operation in operations
    )


def test_fresh_workspace_materializes_each_provider_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Materialize GCS and Hugging Face refs without a producer workspace."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    raw = b"parameters"
    identity = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    destination = ViperCloudDestination(owner="machina", workspace="models")

    gcs_provider = InMemoryViperCloudProvider(fresh)
    gcs_snapshot, gcs_files = gcs_provider.publish(
        destination,
        {"artifacts/model.bin": raw},
    )
    gcs_location = gcs_provider.file_ref(gcs_snapshot, gcs_files[0].path)
    assert isinstance(gcs_location, GcsFileRef)
    gcs_reference = ResolvedFileRef(stored_at=gcs_location, **identity)
    gcs_cloud = ViperCloud(
        fresh,
        GcsRepository(bucket=gcs_provider.bucket, prefix=gcs_provider.prefix),
        provider=gcs_provider,
    )

    remote_file = tmp_path / "remote/model.bin"
    remote_file.parent.mkdir()
    remote_file.write_bytes(raw)
    hf_provider = HuggingFaceProvider(
        fresh,
        "machina/viper-artifacts",
        "dataset",
        api=cast(Any, _HuggingFaceApi()),
    )
    monkeypatch.setattr(hf_provider, "_download", lambda location: remote_file)
    hf_reference = ResolvedFileRef(
        stored_at=HuggingFaceFileRef(
            repository="machina/viper-artifacts",
            commit="a" * 40,
            path="artifacts/model.bin",
            repo_type="dataset",
        ),
        **identity,
    )
    hf_cloud = ViperCloud(
        fresh,
        HuggingFaceRepository(
            repository="machina/viper-artifacts",
            repo_type="dataset",
        ),
        provider=hf_provider,
    )

    gcs_path = gcs_cloud.fetch_to_path(gcs_reference, fresh / "inputs/gcs.bin")
    hf_path = hf_cloud.fetch_to_path(hf_reference, fresh / "inputs/hf.bin")
    assert gcs_path.read_bytes() == raw
    assert hf_path.read_bytes() == raw
    assert not (fresh / ".viper/store").exists()


@pytest.mark.parametrize("lost_response", (False, True))
def test_republication_recovers_commit_after_lost_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_response: bool
) -> None:
    """Reuse the same verified destination commit when publication resumes."""
    api = MemoryHub(tmp_path / "hub")
    provider = HuggingFaceProvider(
        tmp_path, "owner/copies", "dataset", api=cast(Any, api)
    )
    monkeypatch.setattr(provider, "_download", api.download)
    cloud = ViperCloud(
        tmp_path,
        HuggingFaceRepository(repository="owner/copies", repo_type="dataset"),
        provider=provider,
    )
    destination = ViperCloudDestination(owner="owner", workspace="models")
    source = LocalArtifactStore(tmp_path).snapshot({"weights.bin": b"weights"})
    files = (
        SnapshotFileRef(
            path="weights.bin",
            bytes=7,
            sha256=hashlib.sha256(b"weights").hexdigest(),
        ),
    )
    path = tmp_path / "progress.json"
    api.fail_after_commit = lost_response
    with PublicationJournal(path, "a" * 64, cloud, destination) as journal:
        if lost_response:
            with pytest.raises(RunPromotionError, match="outcome is unresolved"):
                journal.publish(source, files, {"weights.bin": b"weights"}, "b" * 64)
        else:
            journal.publish(source, files, {"weights.bin": b"weights"}, "b" * 64)
    committed, count = api.head, len(api.commits)
    with PublicationJournal(path, "a" * 64, cloud, destination) as journal:
        published, observed = journal.publish(
            source, files, {"weights.bin": b"weights"}, "b" * 64
        )
        assert isinstance(published, HuggingFaceStageResultSnapshotRef)
        assert published.commit == committed
        assert observed == files
        with pytest.raises(RunPromotionError, match="publication journal differs"):
            journal.publish(source, files, {"weights.bin": b"weights"}, "c" * 64)
        with pytest.raises(RunPromotionError, match="publication journal is locked"):
            with PublicationJournal(path, "a" * 64, cloud, destination):
                pytest.fail("a second writer acquired the lock")
    assert len(api.commits) == count
    with pytest.raises(RunPromotionError, match="publication journal differs"):
        with PublicationJournal(path, "d" * 64, cloud, destination):
            pytest.fail("a different request opened the saved progress")


def test_republication_keeps_an_uncertain_write_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check saved progress before making another upload attempt."""
    api = MemoryHub(tmp_path / "hub")
    provider = HuggingFaceProvider(
        tmp_path, "owner/copies", "dataset", api=cast(Any, api)
    )
    monkeypatch.setattr(provider, "_download", api.download)
    cloud = ViperCloud(
        tmp_path,
        HuggingFaceRepository(repository="owner/copies", repo_type="dataset"),
        provider=provider,
    )
    destination = ViperCloudDestination(owner="owner", workspace="models")
    source = LocalArtifactStore(tmp_path).snapshot({"file.bin": b"x"})
    files = (
        SnapshotFileRef(
            path="file.bin", bytes=1, sha256=hashlib.sha256(b"x").hexdigest()
        ),
    )
    attempts = []

    def interrupted(**kwargs: Any) -> None:
        """Simulate a connection failure with an unknown remote outcome."""
        attempts.append(kwargs)
        raise ConnectionError("upload response unavailable")

    monkeypatch.setattr(api, "create_commit", interrupted)
    for _ in range(2):
        with PublicationJournal(
            tmp_path / "progress.json", "a" * 64, cloud, destination
        ) as journal:
            with pytest.raises(RunPromotionError, match="outcome is unresolved"):
                journal.publish(source, files, {"file.bin": b"x"}, "b" * 64)
    assert len(attempts) == 1


@pytest.mark.parametrize("body", (b"weights", b"short", b"WEIGHTS", b"weights-extra"))
def test_streamed_hub_file_checks_size_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    """Check streamed files and discard temporary bytes after a failed check."""
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve the chosen body through the normal HTTP streaming interface."""
        requests.append(request.url.path)
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("viper.huggingface.get_session", lambda: client)
    provider = HuggingFaceProvider(tmp_path, "owner/copies", "dataset")
    provider.stream_files = True
    location = HuggingFaceFileRef(
        repository="owner/copies",
        repo_type="dataset",
        commit="a" * 40,
        path="weights.bin",
    )
    identity = SnapshotFileRef(
        path="weights.bin", bytes=7, sha256=hashlib.sha256(b"weights").hexdigest()
    )
    target = tmp_path / "restored.bin"
    with client:
        if body == b"weights":
            assert (
                provider.fetch_to_path(location, identity, target).read_bytes() == body
            )
        else:
            with pytest.raises(ViperCloudError):
                provider.fetch_to_path(location, identity, target)
            assert not target.exists()
            assert not list(tmp_path.glob(".restored.bin.*"))
    assert len(requests) == 1


def test_transfer_space_checks_capacity_and_preserves_source_files(
    tmp_path: Path,
) -> None:
    """Reject oversized work and remove only the copy's verified downloads."""
    limits = TransferLimits(staging_bytes=64, cache_bytes=32, connections=2)
    space = TransferSpace(tmp_path / "copy", limits)
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        "https://example.test/code",
        cache_root=space.cache,
    )
    with pytest.raises(RunPromotionError, match="staging budget is insufficient"):
        space.check(40, 40)
    with pytest.raises(RunPromotionError, match="cache budget is insufficient"):
        space.check(33)
    (local,) = LocalArtifactStore(tmp_path).resolved_files({"original.bin": b"weights"})
    original = fetcher.path(local)
    remote = ResolvedFileRef(
        stored_at=HuggingFaceFileRef(
            repository="owner/copies",
            repo_type="dataset",
            commit="a" * 40,
            path="weights.bin",
        ),
        bytes=7,
        sha256=local.sha256,
    )
    fetcher._verified_objects.write(remote, b"weights")
    cached = fetcher._verified_objects.path(remote)
    fetcher.remember_path(remote, cached)
    space.check()
    assert space.peak_bytes == space.peak_cache_bytes == 7
    space.release(fetcher)
    assert not cached.exists()
    assert original.read_bytes() == b"weights"
    assert fetcher.path(local) == original
    assert directory_bytes(space.root) == 0
    shared = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
    with pytest.raises(RunPromotionError, match="cleanup requires the copy's cache"):
        space.release(shared)


@pytest.mark.parametrize("reply", ("valid", "failed", "wrong_host", "wrong_roots"))
def test_additional_publication_uses_a_separate_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    """Pass the exact copy request to a child and validate the returned hosts."""
    original = ResolvedRunRef(
        stored_at=GcsFileRef(
            bucket="original",
            owner="owner",
            workspace="runs",
            revision="a" * 64,
            path="run.yaml",
        ),
        sha256="b" * 64,
        bytes=8,
    )
    copied = ResolvedRunRef(
        stored_at=HuggingFaceFileRef(
            repository="owner/additional",
            repo_type="dataset",
            commit="c" * 40,
            path="run.yaml",
        ),
        sha256="d" * 64,
        bytes=9,
    )
    host = HuggingFaceRepository(repository="owner/additional", repo_type="dataset")
    limits = TransferLimits(staging_bytes=2048, cache_bytes=1024, connections=2)
    calls = []

    def run(command, **kwargs):
        """Check process settings and return a controlled publication response."""
        request = json.loads(kwargs["input"])
        calls.append(request)
        assert command[-1] == "viper.execution._promotion_worker"
        assert kwargs["env"]["HF_HUB_DISABLE_XET"] == "1"
        assert request["limits"] == limits.model_dump()
        assert request["inventory"]["roots"] == [original.model_dump(mode="json")]
        assert request["policy"]["hosts"] == [host.model_dump(mode="json")]
        response = {
            "passed": True,
            "host": host.model_dump(mode="json"),
            "source_roots": [original.model_dump(mode="json")],
            "destination_roots": [copied.model_dump(mode="json")],
        }
        if reply == "wrong_host":
            response["host"] = {**response["host"], "repository": "owner/other"}
        if reply == "wrong_roots":
            response["source_roots"] = []
        return SimpleNamespace(
            returncode=1 if reply == "failed" else 0,
            stdout=json.dumps({"publications": [response]}),
            stderr=json.dumps({"error": "copy interrupted"}),
        )

    monkeypatch.setattr(execution.subprocess, "run", run)
    if reply == "valid":
        assert execution.promote_run_to_cloud(
            tmp_path,
            original,
            ViperCloudDestination(owner="owner", workspace="runs"),
            policy=RunPromotionPolicy(hosts=(host,)),
            limits=limits,
        ) == (copied,)
    else:
        message = (
            "copy interrupted" if reply == "failed" else "publication result is invalid"
        )
        with pytest.raises(RunPromotionError, match=message):
            execution.promote_run_to_cloud(
                tmp_path,
                original,
                ViperCloudDestination(owner="owner", workspace="runs"),
                policy=RunPromotionPolicy(hosts=(host,)),
                limits=limits,
            )
    assert len(calls) == 1
