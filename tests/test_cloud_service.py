"""Acceptance tests for provider-neutral ViperCloud dispatch."""

from __future__ import annotations

import hashlib
import inspect
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests.test_storage import InMemoryViperCloudProvider
from viper import execution
from viper._cloud import (
    GcsRepository,
    HuggingFaceRepository,
    ViperCloudDestination,
)
from viper.authoring import freeze_run_plan
from viper.cloud import ViperCloud
from viper.huggingface import HuggingFaceProvider
from viper.references import (
    GcsFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedFileRef,
)


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

    gcs_path = gcs_cloud.fetch_to_path(gcs_reference, Path("inputs/gcs.bin"))
    hf_path = hf_cloud.fetch_to_path(hf_reference, Path("inputs/hf.bin"))
    assert gcs_path.read_bytes() == raw
    assert hf_path.read_bytes() == raw
    assert not (fresh / ".viper/store").exists()
