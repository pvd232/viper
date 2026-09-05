from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from .._schema import repo_file_paths_overlap
from ..artifacts import ResolvedBundleArtifact, ResolvedSingleFileArtifact
from ..project import PathError, resolve_path
from ..references import (
    LocalFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ViperCloudFileRef,
    resolve_snapshot_file_ref,
)
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
from ..storage import LocalArtifactStore, ViperCloudClient, content_revision
from ..verification.models import StorageFetcher
from ._source import RunFetcher
from .errors import RestoreError


class _PlannedFile(BaseModel):
    """Hold one verified source reference and its final destination."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    selector: ArtifactRestoreSelector
    reference: ResolvedFileRef
    destination: Path


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
    revision = content_revision({relative: raw})
    return ResolvedRunRef(
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        stored_at=LocalFileRef(commit=revision, path=relative),
    )


def _cloud_run_reference(
    uri: str,
    client: ViperCloudClient | None,
) -> ResolvedRunRef:
    """Resolve one cloud URI through its sealed manifest entry."""
    validate_viper_cloud_run_uri(uri)
    if client is None:
        raise RestoreError("Viper Cloud restore requires a client")
    address = uri.removeprefix("viper://")
    owner, remainder = address.split("/", maxsplit=1)
    project_revision, path = remainder.split("/", maxsplit=1)
    project, revision = project_revision.split("@", maxsplit=1)
    files = tuple(
        file
        for file in client.list_files(
            owner=owner,
            project=project,
            revision=revision,
        )
        if file.path == path
    )
    if len(files) != 1:
        raise RestoreError("Viper Cloud URI does not identify one terminal run")
    file = files[0]
    return ResolvedRunRef(
        sha256=file.sha256,
        bytes=file.bytes,
        stored_at=ViperCloudFileRef(
            owner=owner,
            project=project,
            revision=revision,
            path=file.path,
        ),
    )


def _run_reference(
    root: Path,
    selected: RestoreRunReference,
    client: ViperCloudClient | None,
) -> ResolvedRunRef:
    """Resolve one direct restore input to an immutable terminal reference."""
    if isinstance(selected, ResolvedRunRef):
        return selected
    if isinstance(selected, Path):
        return _local_run_reference(root, selected)
    return _cloud_run_reference(selected, client)


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
) -> dict[ArtifactRestoreSelector, tuple[ResolvedFileRef, ...]]:
    """Load each resolved stage and index its immutable artifact files."""
    indexed: dict[ArtifactRestoreSelector, tuple[ResolvedFileRef, ...]] = {}
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
                files = (artifact.file,)
            else:
                assert isinstance(artifact, ResolvedBundleArtifact)
                files = tuple(member.file for member in artifact.members)
            indexed[selector] = tuple(
                resolve_snapshot_file_ref(stage.snapshot, file) for file in files
            )
    return indexed


def _destination(
    *,
    root: Path,
    reference: ResolvedFileRef,
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
        candidate = base / reference.stored_at.path
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
        return resolve_path(root, relative, operation="write")
    except (OSError, ValueError, PathError) as error:
        raise RestoreError("restore destination is outside the project root") from error


def _plan_files(
    *,
    root: Path,
    indexed: dict[ArtifactRestoreSelector, tuple[ResolvedFileRef, ...]],
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
        references = indexed[selector]
        bundle = len(references) > 1
        for reference in references:
            planned.append(
                _PlannedFile(
                    selector=selector,
                    reference=reference,
                    destination=_destination(
                        root=root,
                        reference=reference,
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
    cloud_client: ViperCloudClient | None = None,
) -> RestoreResult:
    """Restore selected verified artifacts from one successful immutable run."""
    root = repository_root.resolve(strict=True)
    reference = _run_reference(root, run_reference, cloud_client)
    fetcher = RunFetcher(root, LocalArtifactStore(root), "", cloud_client)
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
