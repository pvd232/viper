"""Queue immutable snapshots and keep their local files safe until work ends."""

from __future__ import annotations

import fcntl
import hashlib
import os
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter

import viper._subprocess as subprocess

from ._cloud import (
    LocalSource,
    SnapshotCopy,
    SnapshotInventory,
    canonical_json_bytes,
    validate_snapshot_copy,
)
from ._schema import SHA256, ProtocolModel, RepoRelPath
from ._storage_locks import PayloadLocks, WorkflowReaders
from ._storage_registry import StorageRegistry
from .cloud import PublicationReceipt, PublicationTarget, ViperCloud
from .references import (
    FileIdentity,
    GcsFileRef,
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from .repository import resolve_path
from .serialization import (
    document_digest,
    ensure_directory_synchronized,
    parse_yaml_bytes,
    replace_synchronized,
    write_synchronized,
)

_SOURCE = TypeAdapter(StageResultSnapshotRef | GitSource)
_CURRENT: ContextVar[PublicationSession | None] = ContextVar(
    "viper_publication_session", default=None
)


class PublicationError(RuntimeError):
    """Report pending, failed, or inconsistent background publication."""


class _Location(ProtocolModel):
    """Select one observed local copy for later policy checks."""

    reference: ResolvedFileRef
    location: LocalSource


class Operation(ProtocolModel):
    """Persist one workflow's collection boundary and publication outcome."""

    operation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    repository_root: Path
    store: RepoRelPath
    targets: tuple[PublicationTarget, ...]
    closed: bool = False
    science_succeeded: bool = True
    used: tuple[ResolvedFileRef, ...] = ()
    locations: tuple[_Location, ...] = ()
    jobs: tuple[SHA256, ...] = ()
    publication_complete: bool = False
    final_receipts: tuple[SnapshotCopy, ...] = ()
    final_attempts: int = 0
    final_ready_at: float = 0.0
    error: str | None = None
    cleanup_complete: bool = False


class PublicationJob(ProtocolModel):
    """Persist one original snapshot and its verified destination copies."""

    inventory: SnapshotInventory
    status: Literal["pending", "complete", "failed"] = "pending"
    attempts: int = 0
    ready_at: float = 0.0
    copies: tuple[SnapshotCopy, ...] = ()
    error: str | None = None


def current_session() -> PublicationSession | None:
    """Return the workflow owning this thread's Viper file access."""
    return _CURRENT.get()


@contextmanager
def bind_session(session: PublicationSession) -> Generator[None, None, None]:
    """Share an existing workflow explicitly with a managed child thread."""
    token = _CURRENT.set(session)
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextmanager
def operation_lock(path: Path) -> Generator[None, None, None]:
    """Serialize short metadata updates without holding a lock during transfers."""
    descriptor = os.open(
        path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def load_operation(path: Path) -> Operation:
    """Read a workflow record and reject a mismatched local address."""
    operation = Operation.model_validate(parse_yaml_bytes(path.read_bytes()))
    expected = (
        operation.repository_root
        / ".viper/publications"
        / operation.operation_id
        / "operation.json"
    )
    if path.absolute() != expected or path.is_symlink():
        raise PublicationError("publication record belongs to another workspace")
    return operation


def save_operation(path: Path, operation: Operation) -> None:
    """Replace the workflow record while its metadata lock is held."""
    replace_synchronized(path, canonical_json_bytes(operation))


def load_job(path: Path) -> PublicationJob:
    """Read the exact inventory and progress of one queued snapshot."""
    return PublicationJob.model_validate(parse_yaml_bytes(path.read_bytes()))


def save_job(path: Path, job: PublicationJob) -> None:
    """Atomically persist a snapshot's current publication progress."""
    replace_synchronized(path, canonical_json_bytes(job))


def source_pin(operation: Operation, key: str) -> str:
    """Name this operation's durable obligation to keep the upload source."""
    return f"{operation.operation_id}/{key}"


def start_publication_worker(root: Path) -> None:
    """Wake the detached drainer after durable work is saved.

    Launch failure leaves the saved request available to a later wake or restart.
    """
    directory = resolve_path(root, ".viper/publications", operation="write")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with (directory / "worker.log").open("ab") as log:
            environment = dict(os.environ)
            source_root = str(Path(__file__).resolve().parent.parent)
            environment["PYTHONPATH"] = os.pathsep.join(
                part
                for part in (source_root, environment.get("PYTHONPATH", ""))
                if part
            )
            subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "viper.execution._offload_worker",
                    str(root),
                ),
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
    except OSError as error:
        with (directory / "worker.log").open("a", encoding="utf-8") as log:
            log.write(f"worker launch failed; requests remain pending: {error}\n")


class PublicationSession:
    """Own one workflow's readers and durably admit completed originals."""

    def __init__(
        self,
        root: Path,
        targets: tuple[PublicationTarget, ...] = (),
        store: RepoRelPath = ".viper/store",
    ) -> None:
        """Create recovery metadata without constructing any cloud provider."""
        self.root = root.resolve(strict=True)
        self.store = store
        self.targets = targets
        self.operation_id = uuid4().hex
        self.operation_path = resolve_path(
            self.root,
            f".viper/publications/{self.operation_id}/operation.json",
            operation="write",
        )
        ensure_directory_synchronized(self.operation_path.parent)
        self._owner = os.open(
            self.operation_path.parent / "owner.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        fcntl.flock(self._owner, fcntl.LOCK_EX)
        self._mutex = RLock()
        self._closed = False
        self._successful = True
        self._started = False
        self.before_close: Callable[[], None] | None = None
        self._readers: dict[tuple[Path, str], WorkflowReaders] = {}
        self._used: dict[str, ResolvedFileRef] = {}
        self._locations: dict[str, _Location] = {}
        self.enrolled_runs: dict[
            ResolvedRunRef, tuple[StageResultSnapshotRef, ...]
        ] = {}
        try:
            write_synchronized(
                self.operation_path,
                canonical_json_bytes(
                    Operation(
                        operation_id=self.operation_id,
                        repository_root=self.root,
                        store=store,
                        targets=targets,
                    )
                ),
            )
        except BaseException:
            os.close(self._owner)
            raise

    def hold(
        self,
        reference: FileIdentity,
        repository_root: Path | None = None,
        store: RepoRelPath = ".viper/store",
    ) -> None:
        """Protect these bytes through the entire owning workflow."""
        root = (repository_root or self.root).resolve(strict=True)
        with self._mutex:
            if self._closed:
                raise PublicationError("workflow has already closed")
            namespace = (root, store)
            if namespace not in self._readers:
                self._readers[namespace] = WorkflowReaders(PayloadLocks(root, store))
            self._readers[namespace].hold(reference)
            if isinstance(reference, ResolvedFileRef):
                base = ResolvedFileRef(
                    sha256=reference.sha256,
                    bytes=reference.bytes,
                    stored_at=reference.stored_at,
                )
                self._used[document_digest(base)] = base

    def _remember(self, reference: ResolvedFileRef, location: LocalSource) -> None:
        """Remember only the observed copy used by this workflow."""
        self.hold(reference, store=self.store)
        base = ResolvedFileRef(
            sha256=reference.sha256,
            bytes=reference.bytes,
            stored_at=reference.stored_at,
        )
        selection = _Location(reference=base, location=location)
        self._locations[document_digest(selection)] = selection

    def admit(
        self,
        inventory: SnapshotInventory,
        *,
        locations: dict[str, tuple[LocalSource, ...]] | None = None,
    ) -> None:
        """Save a recoverable upload request before returning to computation."""
        registry = StorageRegistry(self.root, self.store)
        key = document_digest(inventory.source)
        with self._mutex:
            if self._closed:
                raise PublicationError("workflow has already closed")
            record = registry.snapshot(inventory.source)
            if record is None or record.inventory != inventory:
                raise PublicationError("snapshot must be registered before queueing")
            for member in inventory.source_files:
                reference = resolve_snapshot_file_ref(inventory.source, member)
                self.hold(reference, store=self.store)
                for location in (locations or {}).get(member.path, ()):
                    self._remember(reference, location)
            if not self.targets:
                return
            path = self.operation_path.parent / "jobs" / f"{key}.json"
            with operation_lock(self.operation_path):
                operation = load_operation(self.operation_path)
                if key not in operation.jobs:
                    write_synchronized(
                        path, canonical_json_bytes(PublicationJob(inventory=inventory))
                    )
                    registry.pin_source(inventory.source, source_pin(operation, key))
                    operation = operation.model_copy(
                        update={"jobs": (*operation.jobs, key)}
                    )
                    save_operation(self.operation_path, operation)
            if not self._started:
                self._started = True
                start_publication_worker(self.root)

    def record_path(
        self,
        reference: ResolvedFileRef,
        path: Path,
        repository_root: Path | None = None,
        store: RepoRelPath = ".viper/store",
    ) -> None:
        """Select the actual verified local copy, without claiming foreign files."""
        root = (repository_root or self.root).resolve(strict=True)
        self.hold(reference, repository_root=root, store=store)
        if root != self.root or store != self.store:
            return
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            return
        status = path.stat()
        observed = (
            status.st_dev,
            status.st_ino,
            status.st_mtime_ns,
            status.st_ctime_ns,
        )
        location = StorageRegistry(root, store).binding(reference, relative)
        with self._mutex:
            if (
                location is not None
                and location.observed_stat == observed
                and not location.retired
            ):
                self._remember(reference, location)

    def note_result(self, succeeded: bool) -> None:
        """Keep a returned scientific failure from becoming cleanup success."""
        with self._mutex:
            self._successful = self._successful and succeeded

    def used_files(self) -> tuple[ResolvedFileRef, ...]:
        """Include files found by background recovery as well as foreground reads."""
        with self._mutex:
            used = {
                document_digest(ref): ref
                for ref in load_operation(self.operation_path).used
            }
            used.update(self._used)
            return tuple(used[key] for key in sorted(used))

    def close(self, succeeded: bool = True) -> None:
        """Close collection and release readers without waiting for cloud work."""
        with self._mutex:
            if self._closed:
                return
            self._successful = self._successful and succeeded
            try:
                if self.before_close is not None:
                    with bind_session(self):
                        self.before_close()
                self._closed = True
                with operation_lock(self.operation_path):
                    operation = load_operation(self.operation_path)
                    used = {
                        document_digest(reference): reference
                        for reference in operation.used
                    }
                    used.update(self._used)
                    locations = {
                        document_digest(selection): selection
                        for selection in operation.locations
                    }
                    locations.update(self._locations)
                    operation = operation.model_copy(
                        update={
                            "closed": True,
                            "science_succeeded": self._successful,
                            "used": tuple(used[key] for key in sorted(used)),
                            "locations": tuple(
                                locations[key] for key in sorted(locations)
                            ),
                        }
                    )
                    if not self.targets:
                        write_synchronized(
                            self.operation_path.with_name("receipt.json"),
                            canonical_json_bytes(build_receipt(operation, ())),
                        )
                        operation = operation.model_copy(
                            update={"publication_complete": True}
                        )
                    save_operation(self.operation_path, operation)
            finally:
                self._closed = True
                for readers in self._readers.values():
                    readers.close()
                os.close(self._owner)
        if self.targets or self._has_backed_selections():
            start_publication_worker(self.root)

    def _has_backed_selections(self) -> bool:
        """Avoid starting a drainer when local-only work has nothing to offload."""
        registry = StorageRegistry(self.root, self.store)
        seen = set()
        for selected in self._locations.values():
            reference = selected.reference
            identity = (reference.sha256, reference.bytes)
            if identity in seen:
                continue
            seen.add(identity)
            source = _SOURCE.validate_python(
                reference.stored_at.model_dump(exclude={"path"})
            )
            if registry.backings(source, identity=reference) or registry.file_backings(
                reference
            ):
                return True
        return False


@contextmanager
def session_scope(
    root: Path,
    *,
    targets: tuple[PublicationTarget, ...] = (),
    session: PublicationSession | None = None,
    store: RepoRelPath = ".viper/store",
) -> Generator[PublicationSession, None, None]:
    """Borrow the outer workflow or establish one owner at the native boundary."""
    root = root.resolve(strict=True)
    owner = session or current_session()
    created = owner is None
    if owner is None:
        owner = PublicationSession(root, targets, store)
    elif owner.root != root:
        raise PublicationError("nested workflow belongs to another workspace")
    elif targets and owner.targets != targets:
        raise PublicationError("nested workflow changes publication destinations")
    succeeded = False
    with bind_session(owner):
        try:
            yield owner
            succeeded = True
        finally:
            if not succeeded:
                owner.note_result(False)
            if created:
                if succeeded:
                    owner.close(True)
                else:
                    try:
                        owner.close(False)
                    except Exception:
                        # Preserve the exception from the scientific workflow.
                        # Recovery treats the still-open record as unsuccessful.
                        pass


def _status(path: Path) -> dict[str, Any]:
    """Summarize data and final receipt publication without guessing completion."""
    operation = load_operation(path)
    if operation.publication_complete:
        return {
            "operation_path": path,
            "status": "complete",
            "completed": len(operation.jobs),
            "total": len(operation.jobs),
            "error": None,
        }
    jobs = tuple(
        load_job(path.parent / "jobs" / f"{key}.json") for key in operation.jobs
    )
    errors = [job.error for job in jobs if job.status == "failed"]
    if operation.final_attempts >= 3 and not operation.publication_complete:
        errors.append(operation.error)
    status = (
        "complete"
        if operation.publication_complete
        else "failed"
        if errors
        else "pending"
    )
    return {
        "operation_path": path,
        "status": status,
        "completed": sum(job.status == "complete" for job in jobs),
        "total": len(jobs),
        "error": next((error for error in errors if error), None),
    }


def _wake_if_idle(operation: Operation) -> None:
    """Observation wakes a stopped drainer without adding waiters behind a live one."""
    path = resolve_path(
        operation.repository_root,
        ".viper/publications/.worker.lock",
        operation="write",
    )
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    finally:
        os.close(descriptor)
    start_publication_worker(operation.repository_root)


def read_publication_status(
    path: Path,
    *,
    wait: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Return publication status; waiting is always an explicit caller choice."""
    path = path.absolute()
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    operation = load_operation(path)
    if wait and not operation.closed:
        raise PublicationError("workflow is still open; observe a snapshot instead")
    next_probe = 0.0
    while True:
        result = _status(path)
        if not wait or result["status"] != "pending":
            return result
        if time.monotonic() >= next_probe:
            _wake_if_idle(operation)
            next_probe = time.monotonic() + 5.0
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("publication is still pending")
        time.sleep(0.1)


def read_publication_copies(
    path: Path,
    source: StageResultSnapshotRef | GitSource,
    *,
    wait: bool = False,
    timeout_seconds: float | None = None,
) -> tuple[SnapshotCopy, ...]:
    """Observe verified copies of one snapshot, including during an open workflow."""
    path = path.absolute()
    key = document_digest(source)
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    operation = load_operation(path)
    if not operation.targets:
        return ()
    if key not in operation.jobs:
        raise PublicationError("snapshot is not enrolled in this workflow")
    next_probe = 0.0
    while True:
        job = load_job(path.parent / "jobs" / f"{key}.json")
        if job.status == "complete":
            return job.copies
        if job.status == "failed":
            raise PublicationError(job.error or "snapshot publication failed")
        if not wait:
            return ()
        if time.monotonic() >= next_probe:
            _wake_if_idle(operation)
            next_probe = time.monotonic() + 5.0
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("snapshot publication is still pending")
        time.sleep(0.1)


def copy_matches_target(copy: SnapshotCopy, target: PublicationTarget) -> bool:
    """Match the cloud address, independently of the credentials used to publish."""
    validate_snapshot_copy(copy)
    return (
        copy.published is not None
        and ViperCloud._repository_for(copy.published) == target.repository
        and copy.expected.owner == target.destination.owner
        and copy.expected.workspace == target.destination.workspace
    )


def build_receipt(
    operation: Operation, copies: tuple[SnapshotCopy, ...]
) -> PublicationReceipt:
    """Preserve used inventories and already verified backing without reuploading."""
    registry = StorageRegistry(operation.repository_root, operation.store)
    available = {document_digest(copy): copy for copy in copies}
    inventories = {
        document_digest(copy.source): SnapshotInventory(
            source=copy.source, source_files=copy.source_files
        )
        for copy in copies
    }
    members = {
        key: set(inventory.source_files) for key, inventory in inventories.items()
    }
    covered = {
        (file.sha256, file.bytes) for copy in copies for file in copy.source_files
    }
    file_copies: dict[str, ResolvedFileRef] = {}
    for reference in operation.used:
        source = _SOURCE.validate_python(
            reference.stored_at.model_dump(exclude={"path"})
        )
        key = document_digest(source)
        if key not in inventories:
            record = registry.snapshot(source)
            if record is not None:
                inventories[key] = record.inventory
                members[key] = set(record.inventory.source_files)
            elif not isinstance(
                reference.stored_at, (GitFileRef, GcsFileRef, HuggingFaceFileRef)
            ):
                raise PublicationError("used snapshot inventory is unavailable")
        member = SnapshotFileRef(
            path=reference.stored_at.path,
            sha256=reference.sha256,
            bytes=reference.bytes,
        )
        if key in members and member not in members[key]:
            raise PublicationError(
                "used reference differs from its immutable inventory"
            )
        identity = (reference.sha256, reference.bytes)
        if identity in covered:
            continue
        backing = registry.backings(source, identity=reference)
        if backing:
            copy = backing[0]
            available[document_digest(copy)] = copy
            covered.update((file.sha256, file.bytes) for file in copy.source_files)
        else:
            backing_files = registry.file_backings(reference)
            if backing_files:
                file_copy = backing_files[0]
                file_copies[document_digest(file_copy)] = file_copy
                covered.add(identity)
    represented = {document_digest(copy.source) for copy in available.values()}
    return PublicationReceipt(
        operation_id=operation.operation_id,
        targets=operation.targets,
        science_succeeded=operation.science_succeeded,
        used=operation.used,
        copies=tuple(available[key] for key in sorted(available)),
        inventories=tuple(
            inventories[key] for key in sorted(inventories) if key not in represented
        ),
        file_copies=tuple(file_copies[key] for key in sorted(file_copies)),
    )


def _validate_receipt_members(receipt: PublicationReceipt) -> None:
    """Check original inventory membership for every portable file reference."""
    inventories = {
        document_digest(inventory.source): set(inventory.source_files)
        for inventory in receipt.inventories
    }
    inventories.update(
        (document_digest(copy.source), set(copy.source_files))
        for copy in receipt.copies
    )
    for reference in receipt.used:
        source = _SOURCE.validate_python(
            reference.stored_at.model_dump(exclude={"path"})
        )
        inventory = inventories.get(document_digest(source))
        member = SnapshotFileRef(
            path=reference.stored_at.path,
            sha256=reference.sha256,
            bytes=reference.bytes,
        )
        if inventory is None:
            if isinstance(
                reference.stored_at, (GitFileRef, GcsFileRef, HuggingFaceFileRef)
            ):
                continue
            raise PublicationError("receipt is missing a used snapshot inventory")
        if member not in inventory:
            raise PublicationError("receipt is missing a used snapshot member")


def read_publication_receipt(path: Path) -> dict[str, Any]:
    """Validate the immutable local receipt and every final cloud proof."""
    path = path.absolute()
    operation = load_operation(path)
    if not operation.publication_complete:
        raise PublicationError("publication has not completed")
    raw = path.with_name("receipt.json").read_bytes()
    receipt = PublicationReceipt.model_validate(parse_yaml_bytes(raw))
    if (
        receipt.operation_id != operation.operation_id
        or receipt.targets != operation.targets
        or receipt.science_succeeded != operation.science_succeeded
        or receipt.used != operation.used
    ):
        raise PublicationError("receipt differs from the closed operation")
    _validate_receipt_members(receipt)
    recorded = {document_digest(copy) for copy in receipt.copies}
    for key in operation.jobs:
        job = load_job(path.parent / "jobs" / f"{key}.json")
        if (
            job.status != "complete"
            or len(job.copies) != len(operation.targets)
            or document_digest(job.inventory.source) != key
            or any(
                copy.source != job.inventory.source
                or copy.source_files != job.inventory.source_files
                for copy in job.copies
            )
        ):
            raise PublicationError("receipt publication is incomplete")
        remaining = list(operation.targets)
        for copy in job.copies:
            if document_digest(copy) not in recorded:
                raise PublicationError("receipt is missing a completed publication")
            for target in remaining:
                if copy_matches_target(copy, target):
                    remaining.remove(target)
                    break
            else:
                raise PublicationError("snapshot was published to a different target")
        if remaining:
            raise PublicationError("snapshot publication is missing a target")
    member = SnapshotFileRef(
        path=path.with_name("receipt.json")
        .relative_to(operation.repository_root)
        .as_posix(),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    remaining = list(operation.targets)
    for copy in operation.final_receipts:
        if copy.source_files != (member,) or copy.expected.files != (member,):
            raise PublicationError("final proof contains different receipt bytes")
        for target in remaining:
            if copy_matches_target(copy, target):
                remaining.remove(target)
                break
        else:
            raise PublicationError("final proof was published to another target")
    if remaining:
        raise PublicationError("final receipt publication is missing a target")
    return receipt.model_dump(mode="json")


def retry_publication(path: Path) -> None:
    """Retry failed publication without rerunning the scientific workflow."""
    with operation_lock(path):
        operation = load_operation(path)
        for key in operation.jobs:
            job_path = path.parent / "jobs" / f"{key}.json"
            job = load_job(job_path)
            if job.status == "failed":
                save_job(
                    job_path,
                    job.model_copy(
                        update={
                            "status": "pending",
                            "attempts": 0,
                            "ready_at": 0.0,
                            "error": None,
                        }
                    ),
                )
        save_operation(
            path,
            operation.model_copy(
                update={"final_attempts": 0, "final_ready_at": 0.0, "error": None}
            ),
        )
    start_publication_worker(operation.repository_root)
