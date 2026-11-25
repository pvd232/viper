"""Prove which file bytes belong to a Git commit and path."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Self

from pydantic import Field, model_validator

from ._schema import ProtocolModel, RepoRelPath
from ._verified_cache import verify_resolved_file_bytes
from .evidence import VerificationError
from .references import GitFileRef, ResolvedGitFileRef
from .serialization import document_digest

GIT_PROOF_PREFIX = ".viper/git-proofs/"


def _object_id(kind: str, raw: bytes, algorithm: str) -> str:
    """Hash a Git object, including its type and byte-count header."""
    return hashlib.new(algorithm, f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def _tree_entry(raw: bytes, component: str, width: int) -> tuple[bytes, str]:
    """Find one name in a Git directory object and reject malformed entries."""
    expected = component.encode("utf-8")
    selected = None
    position = 0
    while position < len(raw):
        terminator = raw.index(b"\0", position)
        mode, name = raw[position:terminator].split(b" ", 1)
        end = terminator + 1 + width
        if end > len(raw):
            raise ValueError("truncated Git directory entry")
        if name == expected:
            if selected is not None:
                raise ValueError("duplicate Git path component")
            selected = mode, raw[terminator + 1 : end].hex()
        position = end
    if selected is None:
        raise ValueError("Git path component is absent")
    return selected


def _commit_tree(raw: bytes) -> str:
    """Read the root directory ID from a Git commit object."""
    first = raw.split(b"\n", 1)[0]
    if not first.startswith(b"tree "):
        raise ValueError("Git commit has no root directory")
    return first[5:].decode("ascii")


def _file_object_id(proof: GitFileProof) -> str:
    """Follow checked commit and directory objects to the requested file ID."""
    location = proof.reference.stored_at
    if len(location.commit) not in (40, 64):
        raise ValueError("unsupported Git object ID length")
    algorithm = "sha1" if len(location.commit) == 40 else "sha256"
    commit = bytes.fromhex(proof.commit_object)
    if _object_id("commit", commit, algorithm) != location.commit:
        raise ValueError("Git commit object differs from the reference")
    expected = _commit_tree(commit)
    components = location.path.split("/")
    if len(components) != len(proof.tree_objects):
        raise ValueError("Git directory proof does not cover the file path")
    for index, (component, encoded) in enumerate(
        zip(components, proof.tree_objects, strict=True)
    ):
        tree = bytes.fromhex(encoded)
        if _object_id("tree", tree, algorithm) != expected:
            raise ValueError("Git directory object differs from its recorded ID")
        mode, expected = _tree_entry(tree, component, len(location.commit) // 2)
        if index + 1 < len(components):
            if mode not in (b"40000", b"040000"):
                raise ValueError("Git path parent is not a directory")
        elif mode not in (b"100644", b"100755", b"120000"):
            raise ValueError("Git path is not a file")
    return expected


class GitFileProof(ProtocolModel):
    """Keep the Git commit and directory objects needed to check one file."""

    reference: ResolvedGitFileRef = Field(description="Original Git file identity.")
    commit_object: str = Field(description="Raw Git commit object, encoded as hex.")
    tree_objects: tuple[str, ...] = Field(
        min_length=1, description="Git directory objects in path order, encoded as hex."
    )

    @model_validator(mode="after")
    def _check_objects(self) -> Self:
        """Check the pinned commit and every directory before accepting metadata."""
        _file_object_id(self)
        return self


def capture_git_file_proof(
    reference: ResolvedGitFileRef,
    read_object: Callable[[str, str], bytes],
) -> GitFileProof:
    """Collect commit and directory objects; check the file bytes separately."""
    location = reference.stored_at
    commit = read_object("commit", location.commit)
    expected = _commit_tree(commit)
    trees = []
    for component in location.path.split("/"):
        tree = read_object("tree", expected)
        trees.append(tree.hex())
        _, expected = _tree_entry(tree, component, len(location.commit) // 2)
    return GitFileProof(
        reference=reference, commit_object=commit.hex(), tree_objects=tuple(trees)
    )


def verify_git_file_proof(proof: GitFileProof, raw: bytes) -> None:
    """Check size, SHA-256 and membership in the named Git commit and path."""
    verify_resolved_file_bytes(proof.reference, raw)
    try:
        expected = _file_object_id(proof)
    except (ValueError, UnicodeError) as error:
        raise VerificationError("Git source proof is invalid") from error
    algorithm = "sha1" if len(proof.reference.stored_at.commit) == 40 else "sha256"
    if _object_id("blob", raw, algorithm) != expected:
        raise VerificationError("Git file differs from the named commit and path")


def proof_member_path(reference: ResolvedGitFileRef | GitFileRef) -> RepoRelPath:
    """Name the proof metadata carried beside source files in an existing snapshot."""
    location = reference if isinstance(reference, GitFileRef) else reference.stored_at
    return f"{GIT_PROOF_PREFIX}{document_digest(location)}.json"
