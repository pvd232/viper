"""Drain durable original-file uploads without blocking experiment execution."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import stat
import time
import traceback
from pathlib import Path

from huggingface_hub.errors import HfHubHTTPError

from .._cloud import (
    LocalSource,
    PublicationSource,
    SnapshotCopy,
    SnapshotInventory,
    SnapshotSources,
    canonical_json_bytes,
    manifest_revision,
)
from .._offload import (
    Operation,
    PublicationJob,
    build_receipt,
    copy_matches_target,
    load_job,
    load_operation,
    operation_lock,
    save_job,
    save_operation,
    source_pin,
)
from .._storage_locks import PayloadLocks, WorkflowReaders
from .._storage_registry import StorageRegistry
from ..cloud import PublicationReceipt, PublicationTarget, ViperCloud
from ..huggingface import HuggingFaceProvider
from ..references import (
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    resolve_snapshot_file_ref,
)
from ..repository import resolve_path
from ..serialization import document_digest, parse_yaml_bytes, write_synchronized
from ..storage import LocalArtifactStore
from ._promotion_journal import PublicationJournal, publish_captured_snapshot

_ATTEMPTS = 3


def _owner_alive(path: Path) -> bool:
    """Use the operating system's workflow lock rather than guessing from a PID."""
    descriptor = os.open(
        path.parent / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(descriptor)


def _recover(path: Path) -> Operation:
    """Close orphaned collection conservatively and recover interrupted admissions."""
    with operation_lock(path):
        operation = load_operation(path)
        registry = StorageRegistry(operation.repository_root, operation.store)
        alive = not operation.closed and _owner_alive(path)
        if alive:
            return operation
        keys = set(operation.jobs)
        for job_path in (path.parent / "jobs").glob("*.json"):
            if job_path.stem in keys:
                continue
            job = load_job(job_path)
            key = document_digest(job.inventory.source)
            if job_path.stem != key:
                raise ValueError("queued snapshot key differs from its inventory")
            if key not in keys:
                registry.pin_source(job.inventory.source, source_pin(operation, key))
                keys.add(key)
        updates: dict[str, object] = {}
        if keys != set(operation.jobs):
            updates["jobs"] = tuple(sorted(keys))
        if not operation.closed:
            updates.update(closed=True, science_succeeded=False)
        if updates:
            operation = operation.model_copy(update=updates)
            save_operation(path, operation)
        return operation


def _sources(
    path: Path, operation: Operation, inventory: SnapshotInventory
) -> dict[str, Path]:
    """Select unchanged registered originals or shared copies for this inventory."""
    registry = StorageRegistry(operation.repository_root, operation.store)
    record = registry.snapshot(inventory.source)
    if record is None or record.inventory != inventory:
        raise ValueError("queued snapshot inventory is unavailable")
    result: dict[str, Path] = {}
    restored: list[dict[str, object]] = []
    storage = LocalArtifactStore(
        operation.repository_root, operation.store, targets=operation.targets
    )
    for member in inventory.source_files:
        for location in record.locations.get(member.path, ()):
            if location.retired:
                continue
            try:
                candidate = resolve_path(
                    operation.repository_root, location.path, operation="read"
                )
                status = candidate.lstat()
            except (OSError, ValueError):
                continue
            observation = (
                status.st_dev,
                status.st_ino,
                status.st_mtime_ns,
                status.st_ctime_ns,
            )
            if (
                stat.S_ISREG(status.st_mode)
                and status.st_size == member.bytes
                and observation[:3] == location.observed_stat[:3]
            ):
                result[member.path] = candidate
                break
        else:
            reference = resolve_snapshot_file_ref(inventory.source, member)
            resolved = storage.resolve(reference)
            result[member.path] = resolved
            location = registry.binding(
                reference, resolved.relative_to(operation.repository_root).as_posix()
            )
            if location is not None:
                restored.append(
                    {
                        "reference": reference.model_dump(mode="json"),
                        "location": location.model_dump(mode="json"),
                    }
                )
    if restored and document_digest(inventory.source) in operation.jobs:
        with operation_lock(path):
            current = load_operation(path)
            selections = [*current.model_dump(mode="json")["locations"], *restored]
            references = {
                document_digest(reference): reference for reference in current.used
            }
            for item in restored:
                reference = ResolvedFileRef.model_validate(item["reference"])
                references[document_digest(reference)] = reference
            updated = {
                **current.model_dump(),
                "used": tuple(references[key] for key in sorted(references)),
                "locations": selections,
            }
            save_operation(path, Operation.model_validate(updated))
    return result


def _publish_snapshot(
    path: Path,
    operation: Operation,
    inventory: SnapshotInventory,
    target: PublicationTarget,
) -> SnapshotCopy:
    """Reuse exact journal progress and persist one immutable verified copy proof."""
    key = document_digest(inventory.source)
    target_key = document_digest(target)
    proof_path = path.parent / "proofs" / key / f"{target_key}.json"
    registry = StorageRegistry(operation.repository_root, operation.store)
    if proof_path.exists():
        copy = SnapshotCopy.model_validate_json(proof_path.read_bytes())
        if (
            copy.source != inventory.source
            or copy.source_files != inventory.source_files
            or not copy_matches_target(copy, target)
        ):
            raise ValueError("saved publication proof differs from its request")
        registry.register_backing(
            copy, proof_path.relative_to(operation.repository_root).as_posix()
        )
        return copy
    for copy in registry.backings(inventory.source):
        if copy.source_files == inventory.source_files and copy_matches_target(
            copy, target
        ):
            write_synchronized(proof_path, canonical_json_bytes(copy))
            registry.register_backing(
                copy, proof_path.relative_to(operation.repository_root).as_posix()
            )
            return copy
    cloud = ViperCloud.for_target(operation.repository_root, target)
    if isinstance(cloud.provider, HuggingFaceProvider):
        cloud.provider.stream_files = True
        cloud.provider.wait_for_rate_limit = False
    request_hash = hashlib.sha256(
        f"{operation.operation_id}/{target_key}".encode()
    ).hexdigest()
    with WorkflowReaders(
        PayloadLocks(operation.repository_root, operation.store)
    ) as readers:
        for member in inventory.source_files:
            readers.hold(member)
        sources: dict[str, PublicationSource] = dict(
            _sources(path, operation, inventory)
        )
        with PublicationJournal(
            path.parent / "journals" / f"{target_key}.json",
            request_hash,
            cloud,
            target.destination,
        ) as journal:
            copy = publish_captured_snapshot(journal, inventory, sources)
    write_synchronized(proof_path, canonical_json_bytes(copy))
    registry.register_backing(
        copy, proof_path.relative_to(operation.repository_root).as_posix()
    )
    return copy


def _retry_delay(error: BaseException, attempts: int) -> float:
    """Leave quota delays in this job's metadata so other uploads can proceed."""
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, HfHubHTTPError) and cause.response.status_code == 429:
            value = cause.response.headers.get("Retry-After", "").strip()
            return float(int(value) + 1 if value.isdigit() else 3601)
        cause = cause.__cause__
    return float(min(2**attempts, 8))


def _publish_job(path: Path, operation: Operation, key: str) -> None:
    """Attempt one ready job; failure schedules only this snapshot for retry."""
    job_path = path.parent / "jobs" / f"{key}.json"
    with operation_lock(path):
        job = load_job(job_path)
        if job.status != "pending" or job.ready_at > time.time():
            return
        job = job.model_copy(update={"attempts": job.attempts + 1})
        save_job(job_path, job)
    try:
        copies = tuple(
            _publish_snapshot(path, operation, job.inventory, target)
            for target in operation.targets
        )
    except Exception as error:
        traceback.print_exc()
        with operation_lock(path):
            save_job(
                job_path,
                job.model_copy(
                    update={
                        "status": "failed" if job.attempts >= _ATTEMPTS else "pending",
                        "error": f"{type(error).__name__}: {error}",
                        "ready_at": time.time() + _retry_delay(error, job.attempts),
                    }
                ),
            )
        return
    with operation_lock(path):
        save_job(
            job_path,
            job.model_copy(
                update={"status": "complete", "copies": copies, "error": None}
            ),
        )
    StorageRegistry(operation.repository_root, operation.store).unpin_source(
        source_pin(operation, key)
    )


def _receipt_inventory(
    path: Path, operation: Operation, copies: tuple[SnapshotCopy, ...]
) -> SnapshotInventory:
    """Save the closed operation's portable receipt as one immutable snapshot."""
    receipt_path = path.with_name("receipt.json")
    if receipt_path.exists():
        raw = receipt_path.read_bytes()
        receipt = PublicationReceipt.model_validate(parse_yaml_bytes(raw))
        if (
            receipt.operation_id != operation.operation_id
            or receipt.targets != operation.targets
            or receipt.science_succeeded != operation.science_succeeded
            or receipt.used != operation.used
            or not {document_digest(copy) for copy in copies}.issubset(
                document_digest(copy) for copy in receipt.copies
            )
        ):
            raise ValueError("saved receipt differs from the closed publication")
    else:
        raw = canonical_json_bytes(build_receipt(operation, copies))
        write_synchronized(receipt_path, raw)
    relative = receipt_path.relative_to(operation.repository_root).as_posix()
    member = SnapshotFileRef(
        path=relative, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
    )
    inventory = SnapshotInventory(
        source=LocalStageResultSnapshotRef(
            workspace=operation.repository_root,
            store=operation.store,
            commit=manifest_revision((member,)),
        ),
        source_files=(member,),
    )
    status = receipt_path.stat()
    StorageRegistry(operation.repository_root, operation.store).register_snapshot(
        SnapshotSources(
            inventory=inventory,
            locations={
                relative: (
                    LocalSource(
                        path=relative,
                        observed_stat=(
                            status.st_dev,
                            status.st_ino,
                            status.st_mtime_ns,
                            status.st_ctime_ns,
                        ),
                        custody="external",
                    ),
                )
            },
        )
    )
    return inventory


def _finalize(
    path: Path, operation: Operation, copies: tuple[SnapshotCopy, ...]
) -> Operation:
    """Publish final receipts only after collection and every data job finish."""
    if (
        operation.publication_complete
        or operation.final_attempts >= _ATTEMPTS
        or operation.final_ready_at > time.time()
    ):
        return operation
    operation = load_operation(path)
    try:
        inventory = _receipt_inventory(path, operation, copies)
        final = tuple(
            _publish_snapshot(path, operation, inventory, target)
            for target in operation.targets
        )
        updates = {
            "publication_complete": True,
            "final_receipts": final,
            "error": None,
        }
    except Exception as error:
        traceback.print_exc()
        failures = operation.final_attempts + 1
        updates = {
            "error": f"{type(error).__name__}: {error}",
            "final_attempts": failures,
            "final_ready_at": time.time() + _retry_delay(error, failures),
        }
    with operation_lock(path):
        operation = load_operation(path).model_copy(update=updates)
        save_operation(path, operation)
    return operation


def drain_once(
    root: Path,
    *,
    completed: dict[tuple[str, str], PublicationJob] | None = None,
) -> float | None:
    """Process ready uploads across all workflows before sleeping for retries."""
    if completed is None:
        completed = {}
    next_wake: float | None = None
    for path in sorted((root / ".viper/publications").glob("*/operation.json")):
        try:
            operation = load_operation(path)
            if operation.publication_complete:
                continue
            operation = _recover(path)
            registry = StorageRegistry(root, operation.store)
            jobs = []
            for key in operation.jobs:
                memo_key = (operation.operation_id, key)
                job_path = path.parent / "jobs" / f"{key}.json"
                if memo_key in completed:
                    job = completed[memo_key]
                else:
                    job = load_job(job_path)
                    if job.status == "complete":
                        registry.unpin_source(source_pin(operation, key))
                        completed[memo_key] = job
                    elif job.status == "pending" and job.ready_at <= time.time():
                        _publish_job(path, operation, key)
                        job = load_job(job_path)
                        if job.status == "complete":
                            completed[memo_key] = job
                jobs.append(job)
            if operation.closed and all(job.status == "complete" for job in jobs):
                copies = tuple(copy for job in jobs for copy in job.copies)
                operation = _finalize(path, operation, copies)
            deadlines = [job.ready_at for job in jobs if job.status == "pending"]
            if not operation.closed:
                deadlines.append(time.time() + 1)
            elif (
                not operation.publication_complete
                and operation.final_attempts < _ATTEMPTS
                and all(job.status == "complete" for job in jobs)
            ):
                deadlines.append(operation.final_ready_at)
            if deadlines:
                due = max(time.time() + 0.1, min(deadlines))
                next_wake = due if next_wake is None else min(due, next_wake)
        except Exception:
            traceback.print_exc()
    return next_wake


def drain(root: Path) -> None:
    """Give one supervised drainer ownership; queued contenders close exit races."""
    directory = root / ".viper/publications"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        directory / ".worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        completed: dict[tuple[str, str], PublicationJob] = {}
        while (next_wake := drain_once(root, completed=completed)) is not None:
            time.sleep(min(max(next_wake - time.time(), 0.1), 1.0))
    finally:
        os.close(descriptor)


def main() -> None:
    """Run a detached worker for one workspace's existing queue."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--store", default=".viper/store")
    arguments = parser.parse_args()
    drain(arguments.root.resolve(strict=True))


if __name__ == "__main__":
    main()
