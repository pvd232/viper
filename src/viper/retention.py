"""Keep artifact preferences and remove eligible managed local copies."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from pydantic import Field, TypeAdapter

from ._cloud import (
    LocalSource,
    RevisionManifest,
    SnapshotCopy,
    canonical_json_bytes,
    validate_snapshot_copy,
)
from ._offload import (
    PublicationError,
    read_publication_receipt,
    start_publication_worker,
)
from ._schema import ProtocolModel, RepoRelPath
from ._storage_locks import PayloadLocks
from ._storage_registry import RetentionPreference
from ._verified_cache import VerifiedObjectCache
from .artifacts import StageArtifactRef
from .cloud import ViperCloud
from .evidence import VerificationError
from .execution.results import RunResult
from .huggingface import HuggingFaceProvider
from .ids import RunId
from .references import (
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitSource,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from .repository import PathError, resolve_path
from .runs import ResolvedRun, RunAttempt
from .serialization import document_digest, parse_yaml_bytes, write_synchronized
from .storage import LocalArtifactStore, load_storage_settings
from .workspace import RunWorkspaceLock, WorkspaceError


class RunFileEvictionError(RuntimeError):
    """Report a failed check while removing managed local files."""


class RunFileEviction(ProtocolModel):
    """Record removed artifact copies and their byte counts."""

    artifacts: tuple[SnapshotFileRef, ...] = Field(
        description="Artifact identities whose managed local copies were removed."
    )
    bytes_released: int = Field(
        ge=0, description="Bytes removed from managed originals and shared storage."
    )
    attempt_workspace_bytes_released: int = Field(
        ge=0, description="Removed managed bytes inside the selected attempt workspace."
    )


def _file_reference(value: dict[str, Any]) -> ResolvedFileRef:
    """Read a file identity, accepting the kind field of a typed reference."""
    return ResolvedFileRef.model_validate(
        {key: item for key, item in value.items() if key != "kind"}
    )


def _snapshot(reference: ResolvedFileRef) -> StageResultSnapshotRef | GitSource:
    """Get the containing snapshot without the individual file path."""
    return TypeAdapter(StageResultSnapshotRef | GitSource).validate_python(
        reference.stored_at.model_dump(exclude={"path"})
    )


def _completed(
    root: Path, operation: dict[str, Any], copies: tuple[SnapshotCopy, ...]
) -> bool:
    """Require successful closure and reuse the shared final-receipt checks."""
    if not all(
        operation.get(name) is True
        for name in ("closed", "science_succeeded", "publication_complete")
    ):
        return False
    if not operation["targets"]:
        return True
    if len(operation["final_receipts"]) != len(operation["targets"]):
        return False
    try:
        path = resolve_path(
            root,
            f".viper/publications/{operation['operation_id']}/operation.json",
            operation="read",
        )
        receipt = read_publication_receipt(path)
    except (OSError, PathError):
        return False
    except PublicationError as error:
        raise RunFileEvictionError("final publication receipt is invalid") from error
    if any(
        receipt.get(name) != operation[name]
        for name in ("operation_id", "targets", "science_succeeded", "used")
    ):
        raise RunFileEvictionError("final receipt differs from the closed operation")
    recorded = tuple(SnapshotCopy.model_validate(value) for value in receipt["copies"])
    if sorted(document_digest(copy) for copy in recorded) != sorted(
        document_digest(copy) for copy in copies
    ):
        raise RunFileEvictionError(
            "final receipt contains different publication proofs"
        )
    return True


def _backed(
    storage: LocalArtifactStore,
    reference: ResolvedFileRef,
    copies: tuple[SnapshotCopy, ...],
) -> bool:
    """Find verified cloud bytes with the requested size and hash."""
    source = _snapshot(reference)
    if not isinstance(source, GitSource):
        record = storage.registry.snapshot(source)
        member = SnapshotFileRef(
            path=reference.stored_at.path,
            bytes=reference.bytes,
            sha256=reference.sha256,
        )
        if (record is None and source.kind == "local") or (
            record is not None and member not in record.inventory.source_files
        ):
            raise RunFileEvictionError("cleanup reference differs from its snapshot")
    available = (
        *copies,
        *storage.registry.backings(source, identity=reference),
    )
    for copy in available:
        if copy.published is not None and any(
            file.sha256 == reference.sha256 and file.bytes == reference.bytes
            for file in copy.expected.files
        ):
            validate_snapshot_copy(copy)
            return True
    return bool(storage.registry.file_backings(reference))


def _permitted(
    storage: LocalArtifactStore,
    cnx: sqlite3.Connection,
    reference: ResolvedFileRef,
    default_offload: bool | None,
) -> bool:
    """Check current preferences and pending source obligations."""
    current_default = (
        load_storage_settings(storage.repository_root).offload
        if default_offload is None
        else default_offload
    )
    return storage.registry.offload_permitted(
        cnx, reference, default_offload=current_default
    ) and not storage.registry.source_is_pending(reference, cnx)


def _observation(status: os.stat_result) -> tuple[int, int, int, int]:
    """Read the file details used to reject changed or replaced copies."""
    return status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns


def _remove_copy(
    storage: LocalArtifactStore,
    locks: PayloadLocks,
    reference: ResolvedFileRef,
    expected: LocalSource,
    *,
    default_offload: bool | None,
) -> bool | None:
    """Check bytes before taking brief exclusive access to remove this exact copy."""
    if expected.retired or expected.custody == "external":
        return False
    with locks.exclusive(reference) as acquired:
        if not acquired:
            return None
    try:
        path = resolve_path(storage.repository_root, expected.path, operation="read")
        with path.open("rb") as stream:
            status = os.fstat(stream.fileno())
            observed = _observation(status)
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_size != reference.bytes
                or observed[:3] != expected.observed_stat[:3]
            ):
                return False
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if _observation(os.fstat(stream.fileno())) != observed:
                return None
        if digest != reference.sha256:
            raise RunFileEvictionError("selected local file differs from its reference")
    except (FileNotFoundError, PathError):
        return False
    with locks.exclusive(reference) as acquired:
        if not acquired:
            return None
        with storage.registry._transaction(write=True) as cnx:
            row = cnx.execute(
                "SELECT * FROM local_bindings "
                "WHERE path = ? AND sha256 = ? AND bytes = ? AND retired = 0",
                (expected.path, reference.sha256, reference.bytes),
            ).fetchone()
            if row is None:
                return False
            current = storage.registry._location(row)
            if (
                current.path != expected.path
                or current.custody != expected.custody
                or current.observed_stat[:3] != expected.observed_stat[:3]
            ):
                return False
            if not _permitted(storage, cnx, reference, default_offload):
                return None
            try:
                status = path.lstat()
            except FileNotFoundError:
                return False
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_size != reference.bytes
                or _observation(status) != observed
            ):
                return None
            path.unlink()
            cnx.execute(
                "UPDATE local_bindings SET retired = 1 "
                "WHERE path = ? AND sha256 = ? AND bytes = ? AND retired = 0",
                (expected.path, reference.sha256, reference.bytes),
            )
    for directory in path.parents:
        if directory == storage.repository_root:
            break
        try:
            directory.rmdir()
        except OSError:
            break
    return True


def _cleanup(
    storage: LocalArtifactStore,
    operation: dict[str, Any],
    copies: tuple[SnapshotCopy, ...],
    *,
    default_offload: bool | None = None,
) -> tuple[bool | None, tuple[tuple[SnapshotFileRef, LocalSource], ...]]:
    """Apply the same current deletion checks to every selected physical copy."""
    used = tuple(_file_reference(value) for value in operation["used"])
    selected = tuple(
        (
            _file_reference(value["reference"]),
            LocalSource.model_validate(value["location"]),
        )
        for value in operation["locations"]
    )
    if selected:
        current_default = (
            load_storage_settings(storage.repository_root).offload
            if default_offload is None
            else default_offload
        )
        with storage.registry._transaction() as cnx:
            if not any(
                location.custody != "external"
                and not location.retired
                and _permitted(storage, cnx, reference, current_default)
                for reference, location in selected
            ):
                return False, ()
    if not _completed(storage.repository_root, operation, copies):
        return False, ()
    if any(reference not in used for reference, _ in selected):
        raise RunFileEvictionError("cleanup location belongs to an unused reference")
    locks = PayloadLocks(storage.repository_root, storage.store)
    removed = []
    seen = set()
    complete: bool | None = True
    for reference, location in selected:
        key = (reference.sha256, reference.bytes, location.path, location.observed_stat)
        if key in seen or location.retired or location.custody == "external":
            continue
        seen.add(key)
        with storage.registry._transaction() as cnx:
            permitted = _permitted(storage, cnx, reference, default_offload)
        if not permitted:
            if complete is not None:
                complete = False
            continue
        if not _backed(storage, reference, copies):
            if complete is not None:
                complete = False
            continue
        result = _remove_copy(
            storage, locks, reference, location, default_offload=default_offload
        )
        if result is None:
            complete = None
        elif result:
            removed.append(
                (
                    SnapshotFileRef(
                        path=reference.stored_at.path,
                        sha256=reference.sha256,
                        bytes=reference.bytes,
                    ),
                    location,
                )
            )
    return complete, tuple(removed)


def cleanup_operation(
    root: Path,
    operation: dict[str, Any],
    receipt_copies: tuple[SnapshotCopy, ...],
) -> bool | None:
    """Remove eligible copies, returning None when a transient hold requires retry."""
    return _cleanup(
        LocalArtifactStore(root, operation["store"]), operation, receipt_copies
    )[0]


def _ensure_backing(storage: LocalArtifactStore, reference: ResolvedFileRef) -> None:
    """Reuse saved proof or verify an existing cloud snapshot for manual cleanup."""
    if _backed(storage, reference, ()):
        return
    source = _snapshot(reference)
    if isinstance(source, GitSource) or source.kind == "local":
        raise RunFileEvictionError("selected run file has no verified cloud copy")
    cloud = ViperCloud.for_snapshot(storage.repository_root, source)
    files = storage.snapshot_files(source)
    if isinstance(source, GcsStageResultSnapshotRef):
        manifest = RevisionManifest(
            owner=source.owner,
            workspace=source.workspace,
            revision=source.revision,
            files=files,
        )
    elif isinstance(cloud.provider, HuggingFaceProvider):
        manifest = cloud.provider.read_manifest(source)
    else:
        raise RunFileEvictionError(
            "manual cleanup requires a self-describing cloud reference"
        )
    for member in files:
        cloud.verify_file(resolve_snapshot_file_ref(source, member))
    copy = SnapshotCopy(
        source=source,
        source_files=files,
        expected=manifest,
        dependencies_sha256=hashlib.sha256(b"[]").hexdigest(),
        previous_head=None,
        published=source,
    )
    validate_snapshot_copy(copy)
    proof = (
        storage.repository_root
        / ".viper/publications"
        / f"manual-{document_digest(source)}"
        / "proof.json"
    )
    write_synchronized(proof, canonical_json_bytes(copy))
    storage.registry.register_backing(
        copy, proof.relative_to(storage.repository_root).as_posix()
    )


def evict_cloud_backed_run_files(
    repository_root: Path,
    run: RunResult | ResolvedRunRef,
) -> RunFileEviction:
    """Remove a successful run's eligible managed copies after cloud verification.

    This explicit deletion request treats inherited preferences as offload.
    Explicit keep preferences, active readers and pending uploads still prevent
    deletion. Automatic cleanup instead follows the current storage.offload setting.
    Files outside Viper's ownership and nonempty directories remain untouched.
    """
    storage = LocalArtifactStore(repository_root)
    root = storage.repository_root
    reference = run.reference if isinstance(run, RunResult) else run
    if not isinstance(reference.stored_at, (GcsFileRef, HuggingFaceFileRef)):
        raise RunFileEvictionError("terminal run is not stored in Viper Cloud")
    terminal = storage.read(reference)
    _ensure_backing(storage, reference)
    record = ResolvedRun.model_validate(parse_yaml_bytes(terminal))
    if isinstance(run, RunResult) and run.record != record:
        raise RunFileEvictionError("RunResult differs from its terminal record")
    if record.status != "succeeded" or record.successful_attempt_id is None:
        raise RunFileEvictionError("only a successful terminal run may be evicted")
    parts = reference.stored_at.path.split("/")
    if (
        len(parts) != 6
        or parts[0] != "experiments"
        or parts[2] != "runs"
        or parts[5] != "resolved.yaml"
    ):
        raise RunFileEvictionError("terminal run path is not canonical")
    try:
        run_id = TypeAdapter(RunId).validate_python(parts[4])
    except ValueError as error:
        raise RunFileEvictionError("terminal run path has an invalid run ID") from error
    selected: RunAttempt | None = None
    for attempt_ref in record.attempts:
        if not isinstance(attempt_ref.stored_at, (GcsFileRef, HuggingFaceFileRef)):
            raise RunFileEvictionError("attempt record is not stored in Viper Cloud")
        attempt = RunAttempt.model_validate(parse_yaml_bytes(storage.read(attempt_ref)))
        if attempt.attempt_id == record.successful_attempt_id:
            _ensure_backing(storage, attempt_ref)
            selected = attempt
            break
    if selected is None or selected.status != "succeeded" or selected.purpose != "run":
        raise RunFileEvictionError("successful attempt record is missing")
    used = []
    locations = []
    artifact_prefix = "/".join(parts[:5]) + "/artifacts/"
    attempt_prefix = f".viper/workspaces/{run_id}/attempt-{selected.attempt_id}/"
    for stage in selected.resolved_stages:
        if not isinstance(
            stage.snapshot,
            (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef),
        ):
            raise RunFileEvictionError("successful attempt contains a local-only stage")
        for member in storage.snapshot_files(stage.snapshot):
            if not member.path.startswith(artifact_prefix):
                continue
            file = resolve_snapshot_file_ref(stage.snapshot, member)
            _ensure_backing(storage, file)
            registered = storage.registry.snapshot(stage.snapshot)
            assert registered is not None
            # The explicit API selects these produced paths for deletion.
            direct = resolve_path(root, member.path, operation="write")
            if direct.exists() and not any(
                local.path == member.path
                for local in registered.locations.get(member.path, ())
            ):
                try:
                    VerifiedObjectCache.verify_path(file, direct)
                except VerificationError as error:
                    raise RunFileEvictionError(
                        "local artifact identity changed"
                    ) from error
                storage.registry.record_materialization(
                    stage.snapshot, member, direct, custody="output"
                )
                registered = storage.registry.snapshot(stage.snapshot)
                assert registered is not None
            value = file.model_dump(mode="json")
            used.append(value)
            for local in registered.locations.get(member.path, ()):
                if (
                    local.custody == "cache"
                    or local.path == member.path
                    or (
                        local.custody == "output"
                        and local.path.startswith(
                            attempt_prefix + f"stages/{stage.stage_id}/"
                        )
                    )
                ):
                    locations.append(
                        {"reference": value, "location": local.model_dump(mode="json")}
                    )
    operation = {
        "closed": True,
        "science_succeeded": True,
        "publication_complete": True,
        "targets": [],
        "used": used,
        "locations": locations,
    }
    lock = RunWorkspaceLock.for_run(root / ".viper/workspaces", run_id)
    try:
        lock.acquire()
    except WorkspaceError as error:
        raise RunFileEvictionError("run workspace still has an active owner") from error
    try:
        _, removed = _cleanup(storage, operation, (), default_offload=True)
    finally:
        lock.release()
    artifacts = {member.path: member for member, _ in removed}
    return RunFileEviction(
        artifacts=tuple(artifacts[path] for path in sorted(artifacts)),
        bytes_released=sum(member.bytes for member, _ in removed),
        attempt_workspace_bytes_released=sum(
            member.bytes
            for member, local in removed
            if local.path.startswith(attempt_prefix)
        ),
    )


def set_artifact_retention(
    repository_root: Path,
    source: StageResultSnapshotRef,
    selection: StageArtifactRef | RepoRelPath,
    preference: RetentionPreference,
    *,
    store: RepoRelPath = ".viper/store",
) -> None:
    """Save an artifact preference and resolve all its files when keeping locally.

    Save keep before resolving files. A failed resolution leaves keep saved
    and raises the error. Inherit and offload wake the existing cleanup worker.
    """
    storage = LocalArtifactStore(repository_root, store)
    storage.registry.set_retention(source, selection, preference)
    if preference == "keep":
        for reference in storage.registry.artifact_files(source, selection):
            storage.resolve(reference)
    else:
        start_publication_worker(storage.repository_root, store=store)


__all__ = [
    "RunFileEvictionError",
    "RunFileEviction",
    "evict_cloud_backed_run_files",
    "set_artifact_retention",
]
