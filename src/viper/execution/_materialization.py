"""Materialize verified stage inputs inside one run workspace."""

from __future__ import annotations

import hashlib
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
from ..ids import InputName, StageId
from ..inputs import (
    ResolvedExternalInputRef,
    ResolvedFutureInputRef,
    ResolvedInputRef,
    ResolvedStoredInputRef,
)
from ..references import ResolvedArtifactPointerRef, ResolvedStageRef
from ..serialization import parse_yaml_bytes
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
)
from ..storage import LocalArtifactStore
from ..verification import verify_promoted_artifact
from ..verification.models import VerificationPolicy, VerifiedArtifact
from ..workspace import AttemptWorkspace
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
    stage_id: StageId,
    stage: InternalSpec,
    completed: Mapping[StageId, ResolvedStageRef],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
    store: LocalArtifactStore,
) -> tuple[dict[InputName, ResolvedInputRef], dict[str, Path]]:
    """Materialize stage inputs and bind each one to its verified producer."""
    resolved: dict[InputName, ResolvedInputRef] = {}
    paths: dict[str, Path] = {}
    for name, input_ref in stage.inputs.items():
        if input_ref.kind == "future":
            producer = completed.get(input_ref.producer_stage_id)
            if producer is None:
                raise RunError("future input producer has not completed")
            resolved[name] = ResolvedFutureInputRef(producer=producer)
            producer_spec = stage_specs[input_ref.producer_stage_id]
            artifact = producer_spec.artifacts[input_ref.producer_artifact]
            paths[name] = root / artifact.path

        elif input_ref.kind == "external":
            if input_ref.source.kind == "local":
                source_path = root / input_ref.source.path
                if not source_path.is_file():
                    raise RunError("external local input source is not a file")
                raw = source_path.read_bytes()
                file_ref = store.resolved_files({input_ref.source.path: raw})[0]
                _write_materialized_file(root, input_ref.path, raw)
                resolved[name] = ResolvedExternalInputRef(
                    source=input_ref.source,
                    file=file_ref,
                    data_role=input_ref.data_role,
                )
                paths[name] = root / input_ref.path
            elif input_ref.source.kind == "http":
                retrieval_workspace = workspace.resolve(
                    f"stages/{stage_id}/external/{name}"
                )
                retrieval_workspace.mkdir(parents=True, exist_ok=True)
                result = _http_helper(
                    root=root,
                    implementation=resolve_http(root, input_ref.source.http),
                    request=input_ref.source.request,
                    retrieval_workspace=retrieval_workspace,
                    destination=retrieval_workspace / "body",
                    policy=input_ref.source.policy,
                    input_name=name,
                )
                raw = result.body.read_bytes()
                file_ref = store.resolved_files({input_ref.path: raw})[0]
                _write_materialized_file(root, input_ref.path, raw)
                resolved[name] = ResolvedExternalInputRef(
                    source=input_ref.source,
                    file=file_ref,
                    data_role=input_ref.data_role,
                )
                paths[name] = root / input_ref.path

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
    return resolved, paths


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
