"""Tests for repository-local immutable output publication."""

from pathlib import Path

from viper.local_store import LocalArtifactStore
from viper.references import LocalFileRef


def test_local_store_publishes_and_retrieves_one_content_revision(
    tmp_path: Path,
) -> None:
    """Verify stable revision identity and exact retrieval for related files."""
    store = LocalArtifactStore(tmp_path)
    files = {
        "experiments/example/artifacts/parameters.bin": b"parameters",
        "experiments/example/logs/1.train.stdout.log": b"complete\n",
    }

    first_commit = store.publish(files)
    second_commit = store.publish(files)

    assert first_commit == second_commit
    assert (
        store.fetch(
            LocalFileRef(
                commit=first_commit,
                path="experiments/example/artifacts/parameters.bin",
            )
        )
        == b"parameters"
    )


def test_local_store_resolved_files_share_one_revision(tmp_path: Path) -> None:
    """Verify a related publication yields exact references in one revision."""
    store = LocalArtifactStore(tmp_path)
    references = store.resolved_files(
        {
            "experiments/example/logs/1.train.stdout.log": b"out",
            "experiments/example/logs/1.train.stderr.log": b"err",
        }
    )

    commits = {reference.stored_at.commit for reference in references}
    assert len(commits) == 1
    assert all(store.fetch(reference.stored_at) for reference in references)
