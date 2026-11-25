"""Check Git file identity without the original repository or payload copies."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from viper import _subprocess as subprocess
from viper._cloud import GcsRepository, ViperCloudDestination
from viper._git_proof import (
    GitFileProof,
    capture_git_file_proof,
    proof_member_path,
    verify_git_file_proof,
)
from viper._offload import PublicationSession, current_session, load_job, load_operation
from viper.cloud import PublicationTarget, ViperCloud
from viper.evidence import VerificationError
from viper.references import GitFileRef, ResolvedGitFileRef
from viper.storage import LocalArtifactStore, workflow


@pytest.fixture(params=("sha1", "sha256"))
def git_file_proof(
    tmp_path: Path, request: pytest.FixtureRequest
) -> tuple[GitFileProof, bytes]:
    """Capture real Git objects for a nested source file in either object format."""

    def git(*args: str) -> bytes:
        """Run Git only inside this test's repository."""
        return subprocess.run(
            ("git", "-C", str(tmp_path), *args), capture_output=True, check=True
        ).stdout

    git("init", "--initial-branch=main", f"--object-format={request.param}")
    git("config", "user.name", "Viper source test")
    git("config", "user.email", "viper@example.test")
    (tmp_path / "src").mkdir()
    raw = b"value = 'current source'\n"
    (tmp_path / "src/code.py").write_bytes(raw)
    git("add", "src/code.py")
    git("commit", "-m", "source fixture")
    reference = ResolvedGitFileRef(
        stored_at=GitFileRef(
            repository="https://example.com/source.git",
            commit=git("rev-parse", "HEAD").decode().strip(),
            path="src/code.py",
        ),
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
    proof = capture_git_file_proof(
        reference, lambda kind, oid: git("cat-file", kind, oid)
    )
    return proof, raw


def test_git_proof_verifies_offline_after_json_roundtrip(git_file_proof) -> None:
    """Only commit/directory metadata and the ordinary payload are needed to verify."""
    proof, raw = git_file_proof
    restored = GitFileProof.model_validate_json(proof.model_dump_json())
    verify_git_file_proof(restored, raw)
    assert proof_member_path(proof.reference) == proof_member_path(
        proof.reference.stored_at
    )


def test_git_proof_rejects_unrelated_bytes_even_with_matching_declared_sha(
    git_file_proof,
) -> None:
    """Matching a cached payload's SHA cannot change a pinned Git file's identity."""
    proof, _ = git_file_proof
    unrelated = b"value = 'stale cached source'\n"
    claimed = proof.reference.model_copy(
        update={
            "sha256": hashlib.sha256(unrelated).hexdigest(),
            "bytes": len(unrelated),
        }
    )
    altered = proof.model_copy(update={"reference": claimed})
    assert proof_member_path(claimed) == proof_member_path(proof.reference)
    with pytest.raises(VerificationError, match="commit and path"):
        verify_git_file_proof(altered, unrelated)


@pytest.mark.parametrize("field", ("commit_object", "tree_objects"))
def test_git_proof_rejects_changed_metadata(git_file_proof, field: str) -> None:
    """Changing either the commit or a directory breaks its pinned object hash."""
    proof, raw = git_file_proof
    changed = (
        proof.commit_object + "00"
        if field == "commit_object"
        else (*proof.tree_objects[:-1], proof.tree_objects[-1] + "00")
    )
    with pytest.raises(ValidationError):
        GitFileProof.model_validate({**proof.model_dump(), field: changed})
    with pytest.raises(VerificationError, match="proof is invalid"):
        verify_git_file_proof(proof.model_copy(update={field: changed}), raw)


def test_git_proof_rejects_another_path(git_file_proof) -> None:
    """A valid proof for one path cannot authorize another path in that commit."""
    proof, raw = git_file_proof
    location = proof.reference.stored_at.model_copy(update={"path": "src/absent.py"})
    altered = proof.model_copy(
        update={"reference": proof.reference.model_copy(update={"stored_at": location})}
    )
    with pytest.raises(VerificationError, match="proof is invalid"):
        verify_git_file_proof(altered, raw)


def test_explicit_owner_close_admits_sources_and_restores_current_workflow(
    tmp_path: Path, git_file_proof, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing a borrowed owner later still queues sources under that owner."""
    proof, raw = git_file_proof
    (tmp_path / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    store = LocalArtifactStore(tmp_path)
    store.registry.register_git_file(proof, raw)
    store.cache_verified_bytes(proof.reference, raw)
    target = PublicationTarget(
        repository=GcsRepository(bucket="test-bucket"),
        destination=ViperCloudDestination(owner="owner", workspace="source"),
    )
    owner = PublicationSession(tmp_path, (target,))
    monkeypatch.setattr(
        ViperCloud,
        "for_target",
        lambda *args: pytest.fail("source admission opened a cloud client"),
    )
    try:
        with workflow(tmp_path, session=owner, targets=(target,)):
            owner.hold(proof.reference)
        assert not load_operation(owner.operation_path).closed
        with workflow(tmp_path, targets=()) as other:
            owner.close()
            assert current_session() is other
        operation = load_operation(owner.operation_path)
        assert operation.closed and len(operation.jobs) == 1
        job = load_job(
            owner.operation_path.parent / "jobs" / f"{operation.jobs[0]}.json"
        )
        assert {member.path for member in job.inventory.source_files} == {
            proof.reference.stored_at.path,
            proof_member_path(proof.reference),
        }
        assert current_session() is None
    finally:
        owner.close(False)
