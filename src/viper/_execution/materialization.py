"""Materialize verified stage inputs inside one run workspace."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ..artifacts import ArtifactPointer
from ..http import (
    HttpRetrievalError,
    ResolvedHttpRetrieval,
    invoke_transport,
    resolve_transport,
)
from ..ids import InputName, StageId
from ..local_store import LocalArtifactStore
from ..paths import retrieval_body_path
from ..references import ResolvedArtifactPointerRef
from ..runs import RunSpec
from ..serialization import parse_yaml_bytes
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
    ResolvedFutureInputRef,
    ResolvedInternalInputRef,
    ResolvedStageRef,
    ResolvedStoredInputRef,
    StoredInputRef,
)
from ..verification import (
    VerificationPolicy,
    VerifiedArtifact,
    verify_promoted_artifact,
)
from ..workspace import AttemptWorkspace
from .errors import RunError
from .source import RunFetcher


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


def _resolve_inputs(
    root: Path,
    stage: InternalSpec,
    completed: Mapping[StageId, ResolvedStageRef],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
) -> tuple[dict[InputName, ResolvedInternalInputRef], dict[str, Path]]:
    """Materialize stage inputs and bind each one to its verified producer."""
    resolved: dict[InputName, ResolvedInternalInputRef] = {}
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
            continue

        assert isinstance(input_ref, StoredInputRef)
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


def _retrieve_download_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    run: RunSpec,
    stage_id: StageId,
    stage: DownloadSpec,
    store: LocalArtifactStore,
) -> tuple[dict[InputName, ResolvedHttpRetrieval], dict[str, Path]]:
    """Retrieve, verify, publish, and materialize every frozen HTTP input."""
    try:
        transport = resolve_transport(root, stage.transport)
    except (HttpRetrievalError, OSError) as exc:
        raise RunError("selected HTTP transport failed identity checks") from exc

    retrievals: dict[InputName, ResolvedHttpRetrieval] = {}
    paths: dict[str, Path] = {}
    for input_name, request in stage.inputs.items():
        retrieval_workspace = workspace.resolve(
            f"stages/{stage_id}/retrievals/{input_name}"
        )
        retrieval_workspace.mkdir(parents=True, exist_ok=True)
        destination = retrieval_workspace / "body"
        started_at = datetime.now(UTC)
        try:
            result = invoke_transport(
                root,
                transport,
                request,
                stage.policy,
                retrieval_workspace,
                destination,
            )
        except (HttpRetrievalError, OSError) as exc:
            raise RunError(f"HTTP input {input_name!r} failed retrieval") from exc
        completed_at = datetime.now(UTC)
        raw = result.body.read_bytes()
        canonical_path = retrieval_body_path(run, stage_id, input_name)
        body = store.resolved_files({canonical_path: raw})[0]
        _write_materialized_file(root, canonical_path, raw)
        retrievals[input_name] = ResolvedHttpRetrieval(
            input_name=input_name,
            request=request,
            transport=transport,
            response=result.response,
            body=body,
            started_at=started_at,
            completed_at=completed_at,
        )
        paths[input_name] = root / canonical_path
    return retrievals, paths
