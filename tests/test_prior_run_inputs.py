"""Verify prior-run artifact pointers created during plan compilation."""

import hashlib

import pytest

from tests.test_storage import InMemoryViperCloudClient
from viper.artifacts import ArtifactPointer, StageArtifactRef
from viper.authoring import RunArtifactDraft, _freeze_input
from viper.inputs import StoredInputRef
from viper.references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedRunRef,
    ViperCloudFileRef,
)
from viper.serialization import parse_yaml_bytes
from viper.storage import LocalArtifactStore, ViperCloudDestination


def test_prior_run_input_publishes_verified_pointer(tmp_path) -> None:
    """Publish one exact pointer for a selected prior-run artifact."""
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=LocalFileRef(
            commit="b" * 64,
            path="experiments/source/runs/base/run/resolved.yaml",
        ),
    )
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )

    frozen = _freeze_input(tmp_path, {}, draft)

    assert isinstance(frozen, StoredInputRef)
    assert isinstance(frozen.pointer, ResolvedArtifactPointerRef)
    raw = LocalArtifactStore(tmp_path).fetch(frozen.pointer.stored_at)
    assert len(raw) == frozen.pointer.bytes
    assert hashlib.sha256(raw).hexdigest() == frozen.pointer.sha256
    assert ArtifactPointer.model_validate(parse_yaml_bytes(raw)) == ArtifactPointer(
        run=run,
        artifact=draft.artifact,
    )
    assert frozen.pointer.stored_at.path == (
        f"inputs/datasets/toy/dataset_{run.sha256}.pointer.yaml"
    )


def test_prior_run_pointer_uses_the_selected_cloud_destination(tmp_path) -> None:
    """Publish a generated pointer directly to the bound cloud project."""
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=ViperCloudFileRef(
            owner="machina",
            project="source_models",
            revision="b" * 64,
            path="experiments/source/runs/base/run/resolved.yaml",
        ),
    )
    draft = RunArtifactDraft(
        run=run,
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )
    destination = ViperCloudDestination(owner="machina", project="weekend_models")
    client = InMemoryViperCloudClient()

    frozen = _freeze_input(
        tmp_path,
        {},
        draft,
        destination=destination,
        cloud_client=client,
    )

    assert isinstance(frozen, StoredInputRef)
    pointer = frozen.pointer
    assert isinstance(pointer, ResolvedArtifactPointerRef)
    assert isinstance(pointer.stored_at, ViperCloudFileRef)
    assert pointer.stored_at.owner == destination.owner
    assert pointer.stored_at.project == destination.project


def test_cloud_pointer_rejects_a_local_producer(tmp_path) -> None:
    """Stop before publishing a pointer that cannot work off-machine."""
    draft = RunArtifactDraft(
        run=ResolvedRunRef(
            sha256="a" * 64,
            bytes=10,
            stored_at=LocalFileRef(
                commit="b" * 64,
                path="experiments/source/runs/base/run/resolved.yaml",
            ),
        ),
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
        path="inputs/datasets/toy/current.bin",
        data_role="training",
    )

    with pytest.raises(ValueError, match="storage_graph_unreachable"):
        _freeze_input(
            tmp_path,
            {},
            draft,
            destination=ViperCloudDestination(
                owner="machina",
                project="weekend_models",
            ),
            cloud_client=InMemoryViperCloudClient(),
        )
