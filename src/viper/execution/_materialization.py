"""Materialize verified stage inputs inside one run workspace."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ..artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
)
from ..http import (
    HttpRequestSpec,
    HttpResult,
    HttpRetrievalError,
    HttpRetrievalPolicy,
    ResolvedHttpImplementation,
    ResolvedHttpRetrieval,
    invoke_http,
    resolve_http,
)
from ..ids import InputName, RunId, StageId
from ..inputs import (
    ExternalInputRef,
    ResolvedExternalInputRef,
    ResolvedFutureInputRef,
    ResolvedInputRef,
    ResolvedStoredInputRef,
)
from ..references import (
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
from ..serialization import parse_yaml_bytes
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
)
from ..storage import snapshot_file
from ..verification import verify_promoted_artifact
from ..verification.models import VerificationPolicy, VerifiedArtifact
from ..workspace import AttemptWorkspace, captured_input_path
from ._downloads import publish_download_body
from ._source import RunFetcher
from .errors import RunError


def _write_materialized_file(root: Path, relative_path: str, raw: bytes) -> None:
    """Write verified input bytes at one safe repository-relative path."""
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise RunError("materialized input escapes the repository root")
    if target.exists() and (not target.is_file() or target.read_bytes() != raw):
        raise RunError("materialized input path contains different bytes")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def _materialize_verified_artifact(
    root: Path,
    target_path: str,
    artifact: VerifiedArtifact,
) -> None:
    """Write every verified artifact file at its selected input path."""
    if artifact.artifact.kind == "file":
        _write_materialized_file(root, target_path, artifact.files[0].content)
        return
    for member, verified_file in zip(
        artifact.artifact.members,
        artifact.files,
        strict=True,
    ):
        _write_materialized_file(
            root,
            f"{target_path}/{member.relative_path}",
            verified_file.content,
        )


def _http_helper(
    root: Path,
    implementation: ResolvedHttpImplementation,
    request: HttpRequestSpec,
    retrieval_workspace: Path,
    policy: HttpRetrievalPolicy,
    destination: Path,
    input_name: str,
) -> HttpResult:
    """Run one download-stage HTTP request through the selected implementation."""
    try:
        result = invoke_http(
            root,
            implementation,
            request,
            policy,
            retrieval_workspace,
            destination,
        )
    except (HttpRetrievalError, OSError) as exc:
        raise RunError(f"HTTP input {input_name!r} failed retrieval") from exc

    return result


def resolve_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    run_id: RunId,
    attempt_id: int,
    stage_id: StageId,
    stage: InternalSpec,
    completed: Mapping[StageId, ResolvedStageRef],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
) -> tuple[
    dict[InputName, ResolvedInputRef],
    dict[str, Path],
    dict[InputName, SnapshotFileRef],
    dict[InputName, tuple[ResolvedFileRef, ...]],
]:
    """Materialize inputs and retain their existing immutable references."""
    resolved: dict[InputName, ResolvedInputRef] = {}
    paths: dict[str, Path] = {}
    captured: dict[InputName, SnapshotFileRef] = {}
    stored: dict[InputName, tuple[ResolvedFileRef, ...]] = {}
    for name, input_ref in stage.inputs.items():
        if input_ref.kind == "future":
            producer = completed.get(input_ref.producer_stage_id)
            if producer is None:
                raise RunError("future input producer has not completed")
            resolved[name] = ResolvedFutureInputRef(producer=producer)
            producer_spec = stage_specs[input_ref.producer_stage_id]
            artifact = producer_spec.artifacts[input_ref.name]
            paths[name] = root / artifact.path
        elif input_ref.kind == "external":
            resolved_input, captured_path = capture_external_input(
                root,
                workspace,
                run_id=run_id,
                attempt_id=attempt_id,
                stage_id=stage_id,
                input_name=name,
                input_ref=input_ref,
            )
            resolved[name] = resolved_input
            paths[name] = captured_path
            captured[name] = resolved_input.file
        elif input_ref.kind == "stored":
            pointer_raw = fetcher(input_ref.pointer)
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            verified = verify_promoted_artifact(
                pointer,
                policy=policy,
                expected_data_role=input_ref.data_role,
                fetcher=fetcher,
            )
            _materialize_verified_artifact(root, input_ref.path, verified)
            resolved[name] = ResolvedStoredInputRef(
                pointer=ResolvedArtifactPointerRef(
                    sha256=hashlib.sha256(pointer_raw).hexdigest(),
                    bytes=len(pointer_raw),
                    stored_at=input_ref.pointer,
                )
            )
            paths[name] = root / input_ref.path
            stored[name] = verified.references
    return resolved, paths, captured, stored


def verify_captured_inputs(
    root: Path,
    captured: Mapping[InputName, SnapshotFileRef],
) -> None:
    """Require every captured local input to retain its pre-execution identity."""
    for input_name, reference in captured.items():
        try:
            raw = (root / reference.path).read_bytes()
        except OSError as exc:
            raise RunError(
                f"input.local.identity: captured input {input_name!r} is unavailable"
            ) from exc
        if snapshot_file(reference.path, raw) != reference:
            raise RunError(
                f"input.local.identity: captured input {input_name!r} changed"
            )


def retrieve_download_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    stage_id: StageId,
    stage: DownloadSpec,
) -> tuple[
    dict[InputName, ResolvedHttpRetrieval],
    dict[str, ResolvedArtifact],
    dict[str, Path],
]:
    """Retrieve each HTTP input and publish it as its same-named artifact."""
    try:
        implementation = resolve_http(root, stage.http)
    except (HttpRetrievalError, OSError) as exc:
        raise RunError("selected HTTP implementation failed identity checks") from exc

    retrievals: dict[InputName, ResolvedHttpRetrieval] = {}
    artifacts: dict[str, ResolvedArtifact] = {}
    paths: dict[str, Path] = {}
    for input_name, request in stage.inputs.items():
        retrieval_workspace = workspace.resolve(
            f"stages/{stage_id}/retrievals/{input_name}"
        )
        retrieval_workspace.mkdir(parents=True, exist_ok=True)
        destination = retrieval_workspace / "body"
        started_at = datetime.now(UTC)
        result = _http_helper(
            root=root,
            implementation=implementation,
            request=request,
            retrieval_workspace=retrieval_workspace,
            policy=stage.policy,
            destination=destination,
            input_name=input_name,
        )
        completed_at = datetime.now(UTC)
        declaration = stage.artifacts[input_name]
        if not isinstance(declaration, SingleFileArtifactSpec):
            raise RunError("download artifact must be a single file")
        body = publish_download_body(
            repository_root=root,
            source=result.body,
            destination=declaration.path,
            expected_sha256=request.expected_body_sha256,
            expected_bytes=request.expected_body_bytes,
        )
        retrievals[input_name] = ResolvedHttpRetrieval(
            input_name=input_name,
            request=request,
            http=implementation,
            response=result.response,
            body=body,
            started_at=started_at,
            completed_at=completed_at,
        )
        artifacts[input_name] = ResolvedSingleFileArtifact(file=body)
        paths[input_name] = root / body.path
    return retrievals, artifacts, paths


def capture_external_input(
    root: Path,
    workspace: AttemptWorkspace,
    *,
    run_id: RunId,
    attempt_id: int,
    stage_id: StageId,
    input_name: InputName,
    input_ref: ExternalInputRef,
) -> tuple[ResolvedExternalInputRef, Path]:
    """Copy one validated local source into attempt-owned custody."""
    declared_source = root / input_ref.source.path
    if declared_source.is_symlink():
        raise RunError("input.local.capture: source must not be a symbolic link")
    try:
        source = declared_source.resolve(strict=True)
    except OSError as exc:
        raise RunError("input.local.capture: source is unavailable") from exc
    if not source.is_relative_to(root) or not source.is_file():
        raise RunError("input.local.capture: source must be a repository file")
    raw = source.read_bytes()
    relative_path = captured_input_path(
        run_id=run_id,
        attempt_id=attempt_id,
        stage_id=stage_id,
        input_name=input_name,
        source_path=input_ref.source.path,
    )
    target = root / relative_path
    if not target.resolve().is_relative_to(workspace.inputs.resolve()):
        raise RunError(
            "input.local.capture: captured path escapes the attempt workspace"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    reference = snapshot_file(relative_path, raw)
    return (
        ResolvedExternalInputRef(
            source=input_ref.source,
            file=reference,
            data_role=input_ref.data_role,
        ),
        target,
    )
