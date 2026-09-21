from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from .._schema import RepoRelPath, repo_file_paths_overlap
from ..artifacts import ResolvedBundleArtifact, ResolvedSingleFileArtifact
from ..cloud import ViperCloud
from ..evidence import StorageFetcher
from ..references import (
    GcsFileRef,
    GcsStageResultSnapshotRef,
    HuggingFaceFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    resolve_snapshot_file_ref,
)
from ..repository import PathError, resolve_path
from ..restoration import (
    ArtifactRestoreSelector,
    RestoredArtifact,
    RestoredFile,
    RestoreResult,
    RestoreRunReference,
    validate_viper_cloud_run_uri,
)
from ..runs import ResolvedRun, RunAttempt
from ..serialization import parse_yaml_bytes
from ..stages import ResolvedSpec
from ..storage import LocalArtifactStore, load_storage_settings
from ._source import RunFetcher
from .errors import RestoreError


class _PlannedFile(BaseModel):
    """Hold one verified source reference and its final destination."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    selector: ArtifactRestoreSelector
    reference: ResolvedFileRef
    destination: Path


class _IndexedFile(BaseModel):
    """Join immutable stored bytes to their declared artifact path."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    reference: ResolvedFileRef
    declared_path: RepoRelPath


_RESOLVED_SPEC = TypeAdapter(ResolvedSpec)


def _verified_bytes(fetcher: StorageFetcher, reference: ResolvedFileRef) -> bytes:
    """Retrieve one file and require its recorded byte identity."""
    try:
        raw = fetcher(reference.stored_at)
    except Exception as error:
        raise RestoreError("restore source is unavailable") from error
    if (
        len(raw) != reference.bytes
        or hashlib.sha256(raw).hexdigest() != reference.sha256
    ):
        raise RestoreError("restore source differs from its recorded identity")
    return raw


def _local_run_reference(root: Path, path: Path) -> ResolvedRunRef:
    """Reconstruct the immutable terminal reference selected by a local path."""
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
        terminal = resolve_path(root, relative, operation="read")
    except (OSError, ValueError, PathError) as error:
        raise RestoreError("local terminal run path is invalid") from error
    raw = terminal.read_bytes()
    sidecar = terminal.with_name("resolved.ref.yaml")
    if sidecar.exists():
        try:
            reference = ResolvedRunRef.model_validate(
                parse_yaml_bytes(sidecar.read_bytes())
            )
        except (OSError, ValueError) as error:
            raise RestoreError(
                "stored run reference differs from terminal identity"
            ) from error
        if (
            not isinstance(reference.stored_at, (GcsFileRef, HuggingFaceFileRef))
            or reference.stored_at.path != relative
            or reference.bytes != len(raw)
            or reference.sha256 != hashlib.sha256(raw).hexdigest()
        ):
            raise RestoreError("stored run reference differs from terminal identity")
        return reference
    store = LocalArtifactStore(root)
    reference = store.resolved_files({relative: raw})[0]
    return ResolvedRunRef(
        sha256=reference.sha256,
        bytes=reference.bytes,
        stored_at=reference.stored_at,
    )


def _cloud_run_reference(root: Path, uri: str) -> ResolvedRunRef:
    """Resolve one cloud URI through its sealed manifest entry."""
    validate_viper_cloud_run_uri(uri)
    address = uri.removeprefix("viper://")
    owner, remainder = address.split("/", maxsplit=1)
    workspace_revision, path = remainder.split("/", maxsplit=1)
    workspace, revision = workspace_revision.split("@", maxsplit=1)
    settings = load_storage_settings(root)
    if settings.repository is None or settings.repository.provider != "gcs":
        raise RestoreError("Viper Cloud URI requires a configured GCS repository")
    snapshot = GcsStageResultSnapshotRef(
        bucket=settings.repository.bucket,
        prefix=settings.repository.prefix,
        owner=owner,
        workspace=workspace,
        revision=revision,
    )
    cloud = ViperCloud(root, settings.repository)
    files = tuple(file for file in cloud.list_files(snapshot) if file.path == path)
    if len(files) != 1:
        raise RestoreError("Viper Cloud URI does not identify one terminal run")
    file = files[0]
    return ResolvedRunRef(
        sha256=file.sha256,
        bytes=file.bytes,
        stored_at=GcsFileRef(
            bucket=settings.repository.bucket,
            prefix=settings.repository.prefix,
            owner=owner,
            workspace=workspace,
            revision=revision,
            path=file.path,
        ),
    )


def resolve_run_reference(
    root: Path,
    selected: RestoreRunReference,
) -> ResolvedRunRef:
    """Resolve a local path or cloud URI to an immutable terminal-run reference.

    The returned reference can connect artifacts from an existing run to a new
    run plan without calling a private restoration helper.
    """
    root = root.resolve(strict=True)
    if isinstance(selected, ResolvedRunRef):
        return selected
    if isinstance(selected, Path):
        return _local_run_reference(root, selected)
    return _cloud_run_reference(root, selected)


def _successful_attempt(
    run: ResolvedRun,
    fetcher: StorageFetcher,
) -> RunAttempt:
    """Load the successful attempt named by a terminal run."""
    if run.status != "succeeded" or run.successful_attempt_id is None:
        raise RestoreError("restore requires a succeeded run")
    for reference in run.attempts:
        raw = _verified_bytes(fetcher, reference)
        attempt = RunAttempt.model_validate(parse_yaml_bytes(raw))
        if attempt.attempt_id == run.successful_attempt_id:
            if attempt.status != "succeeded":
                raise RestoreError("selected restore attempt did not succeed")
            return attempt
    raise RestoreError("successful attempt is absent from the terminal run")


def _stage_artifacts(
    attempt: RunAttempt,
    fetcher: StorageFetcher,
) -> dict[ArtifactRestoreSelector, tuple[_IndexedFile, ...]]:
    """Load each resolved stage and index its immutable artifact files."""
    indexed: dict[ArtifactRestoreSelector, tuple[_IndexedFile, ...]] = {}
    for stage in attempt.resolved_stages:
        stage_reference = resolve_snapshot_file_ref(stage.snapshot, stage.resolved_spec)
        stage_raw = _verified_bytes(fetcher, stage_reference)
        resolved = _RESOLVED_SPEC.validate_python(parse_yaml_bytes(stage_raw))
        for name, artifact in resolved.artifacts.items():
            selector = ArtifactRestoreSelector(
                stage_id=stage.stage_id,
                artifact_name=name,
            )
            if isinstance(artifact, ResolvedSingleFileArtifact):
                files = ((artifact.relative_path, artifact.file),)
            else:
                assert isinstance(artifact, ResolvedBundleArtifact)
                files = tuple(
                    (
                        f"{artifact.relative_path}/{member.relative_path}",
                        member.file,
                    )
                    for member in artifact.members
                )
            indexed[selector] = tuple(
                _IndexedFile(
                    reference=resolve_snapshot_file_ref(stage.snapshot, file),
                    declared_path=declared_path,
                )
                for declared_path, file in files
            )
    return indexed


def _destination(
    *,
    root: Path,
    reference: ResolvedFileRef,
    declared_path: RepoRelPath,
    selector_count: int,
    bundle: bool,
    output: Path | None,
) -> Path:
    """Resolve one selected file to its final root-confined destination."""
    if output is None:
        candidate = root / reference.stored_at.path
    elif selector_count == 1 and not bundle:
        candidate = output if output.is_absolute() else root / output
    else:
        base = output if output.is_absolute() else root / output
        candidate = base / declared_path
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
        return resolve_path(root, relative, operation="write")
    except (OSError, ValueError, PathError) as error:
        raise RestoreError(
            "restore destination is outside the workspace root"
        ) from error


def _plan_files(
    *,
    root: Path,
    indexed: dict[ArtifactRestoreSelector, tuple[_IndexedFile, ...]],
    selectors: tuple[ArtifactRestoreSelector, ...],
    output: Path | None,
) -> tuple[_PlannedFile, ...]:
    """Resolve selections and reject conflicting destinations before retrieval."""
    selected = selectors or tuple(
        sorted(indexed, key=lambda item: (item.stage_id, item.artifact_name))
    )
    if len(set(selected)) != len(selected):
        raise RestoreError("artifact selectors must be unique")
    missing = tuple(selector for selector in selected if selector not in indexed)
    if missing:
        raise RestoreError("selected artifact is absent from the successful attempt")
    planned: list[_PlannedFile] = []
    for selector in selected:
        indexed_files = indexed[selector]
        bundle = len(indexed_files) > 1
        for indexed_file in indexed_files:
            planned.append(
                _PlannedFile(
                    selector=selector,
                    reference=indexed_file.reference,
                    destination=_destination(
                        root=root,
                        reference=indexed_file.reference,
                        declared_path=indexed_file.declared_path,
                        selector_count=len(selected),
                        bundle=bundle,
                        output=output,
                    ),
                )
            )
    relative_paths = tuple(
        item.destination.relative_to(root).as_posix() for item in planned
    )
    for index, path in enumerate(relative_paths):
        if any(
            repo_file_paths_overlap(path, prior) for prior in relative_paths[:index]
        ):
            raise RestoreError("restore destinations overlap")
    return tuple(planned)


def _restore_files(
    fetcher: StorageFetcher,
    planned: tuple[_PlannedFile, ...],
) -> dict[ArtifactRestoreSelector, list[RestoredFile]]:
    """Verify every source and destination before atomically replacing files."""
    prepared: list[tuple[_PlannedFile, bytes]] = []
    for item in planned:
        raw = _verified_bytes(fetcher, item.reference)
        if item.destination.exists():
            if not item.destination.is_file() or item.destination.read_bytes() != raw:
                raise RestoreError("restore destination contains different bytes")
        prepared.append((item, raw))

    restored: dict[ArtifactRestoreSelector, list[RestoredFile]] = {}
    temporary: list[Path] = []
    try:
        for item, raw in prepared:
            status: Literal["restored", "already_present"] = "already_present"
            if not item.destination.exists():
                item.destination.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(
                    dir=item.destination.parent,
                    prefix=f".{item.destination.name}.",
                )
                temporary_path = Path(name)
                temporary.append(temporary_path)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                if temporary_path.read_bytes() != raw:
                    raise RestoreError("temporary restore file changed before commit")
                os.replace(temporary_path, item.destination)
                temporary.remove(temporary_path)
                status = "restored"
            restored.setdefault(item.selector, []).append(
                RestoredFile(path=item.destination, status=status)
            )
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
    return restored


def restore(
    repository_root: Path,
    run_reference: RestoreRunReference,
    *,
    artifacts: tuple[ArtifactRestoreSelector, ...] = (),
    output: Path | None = None,
) -> RestoreResult:
    """Restore selected verified artifacts from one successful immutable run."""
    root = repository_root.resolve(strict=True)
    reference = resolve_run_reference(
        root,
        run_reference,
    )
    fetcher = RunFetcher(root, LocalArtifactStore(root), "")
    terminal_raw = _verified_bytes(fetcher, reference)
    run = ResolvedRun.model_validate(parse_yaml_bytes(terminal_raw))
    attempt = _successful_attempt(run, fetcher)
    indexed = _stage_artifacts(attempt, fetcher)
    planned = _plan_files(
        root=root,
        indexed=indexed,
        selectors=artifacts,
        output=output,
    )
    files = _restore_files(fetcher, planned)
    return RestoreResult(
        run=reference,
        artifacts=tuple(
            RestoredArtifact(selector=selector, files=tuple(files[selector]))
            for selector in (
                artifacts
                or tuple(
                    sorted(files, key=lambda item: (item.stage_id, item.artifact_name))
                )
            )
        ),
    )
