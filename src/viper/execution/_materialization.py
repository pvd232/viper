"""Materialize verified stage inputs inside one run workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from .._offload import current_session
from .._schema import RepoRelPath
from .._source import RunFetcher
from .._verification.storage import snapshot_artifact_files
from ..artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from ..evidence import (
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedProducerRun,
    VerifiedSnapshotFile,
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
    ResolvedBenchmarkResultRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from ..repository import read_source, resolve_root
from ..reuse import ReuseFileIdentity, ReuseInputIdentity, artifact_input_identity
from ..serialization import document_digest, parse_yaml_bytes
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
    ResolvedBaseSpec,
)
from ..storage import LocalArtifactStore, snapshot_file, workflow
from ..verification import (
    select_artifact_in_run,
    verify_artifact_in_run,
    verify_pointer_producer,
    verify_snapshot_artifact,
)
from ..workspace import (
    AttemptWorkspace,
    captured_input_path,
    captured_input_snapshot_path,
    stored_input_path,
)
from ._downloads import publish_download_body
from .errors import RunError


def _write_materialized_file(
    root: Path,
    relative_path: str,
    verified_file: VerifiedSnapshotFile,
) -> None:
    """Write one verified input without buffering a path-backed payload."""
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise RunError("materialized input escapes the repository root")
    if target.exists():
        if not target.is_file():
            raise RunError("materialized input path contains different bytes")
        with target.open("rb") as stream:
            target_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        if (
            target.stat().st_size != verified_file.reference.bytes
            or target_sha256 != verified_file.reference.sha256
        ):
            raise RunError("materialized input path contains different bytes")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if verified_file.content is not None:
        target.write_bytes(verified_file.content)
    else:
        assert verified_file.local_path is not None
        try:
            os.link(verified_file.local_path, target)
        except OSError:
            shutil.copyfile(verified_file.local_path, target)
        mode = verified_file.local_path.stat().st_mode
        os.chmod(target, mode & ~0o222)


def materialize_verified_artifact(
    root: Path,
    target_path: str,
    artifact: VerifiedArtifact,
) -> Path:
    """Use an existing local artifact or assemble its required bundle layout."""
    store = LocalArtifactStore(root)
    session = current_session()
    if artifact.references:
        local_files = []
        for file, reference in zip(artifact.files, artifact.references, strict=True):
            if file.local_path is None:
                local_files.append(file)
            else:
                local = store.adopt_verified_reference(reference, file.local_path)
                local_files.append(replace(file, local_path=local))
        artifact = replace(artifact, files=tuple(local_files))

    direct: Path | None = None
    if artifact.artifact.kind == "file":
        direct = artifact.files[0].local_path
    elif artifact.files and all(file.local_path is not None for file in artifact.files):
        first = artifact.files[0].local_path
        assert first is not None
        relative = Path(artifact.artifact.members[0].relative_path)
        candidate = first.parents[len(relative.parts) - 1]
        if all(
            file.local_path == candidate / member.relative_path
            for member, file in zip(
                artifact.artifact.members, artifact.files, strict=True
            )
        ):
            direct = candidate
    if direct is not None and direct.is_relative_to(root):
        if session is not None:
            for file, reference in zip(
                artifact.files, artifact.references, strict=True
            ):
                assert file.local_path is not None
                session.hold(reference, store=store.store)
                session.record_path(reference, file.local_path, store=store.store)
        return direct

    if artifact.artifact.kind == "file":
        _write_materialized_file(root, target_path, artifact.files[0])
        paths = (root / target_path,)
    else:
        paths = tuple(
            root / target_path / member.relative_path
            for member in artifact.artifact.members
        )
        for path, file in zip(paths, artifact.files, strict=True):
            _write_materialized_file(root, path.relative_to(root).as_posix(), file)
    if session is not None:
        for path, reference in zip(paths, artifact.references, strict=True):
            source = TypeAdapter(StageResultSnapshotRef).validate_python(
                reference.stored_at.model_dump(exclude={"path"})
            )
            store.registry.record_materialization(
                source,
                SnapshotFileRef(
                    path=reference.stored_at.path,
                    sha256=reference.sha256,
                    bytes=reference.bytes,
                ),
                path,
                custody="cache",
            )
            session.hold(reference, store=store.store)
            session.record_path(reference, path, store=store.store)
    return root / target_path


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
    completed_results: Mapping[StageId, ResolvedBaseSpec],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
) -> tuple[
    dict[InputName, ResolvedInputRef],
    dict[str, Path],
    dict[InputName, SnapshotFileRef],
    dict[InputName, tuple[ResolvedFileRef, ...]],
    tuple[ReuseInputIdentity, ...],
]:
    """Materialize inputs and retain their existing immutable references."""
    resolved: dict[InputName, ResolvedInputRef] = {}
    paths: dict[str, Path] = {}
    captured: dict[InputName, SnapshotFileRef] = {}
    stored: dict[InputName, tuple[ResolvedFileRef, ...]] = {}
    identities: list[ReuseInputIdentity] = []
    verified_runs: dict[ResolvedRunRef, VerifiedProducerRun] = {}
    for name, input_ref in stage.inputs.items():
        if input_ref.kind == "future":
            producer = completed.get(input_ref.producer_stage_id)
            if producer is None:
                raise RunError("future input producer has not completed")
            producer_result = completed_results.get(input_ref.producer_stage_id)
            if producer_result is None:
                raise RunError("future input producer result is unavailable")
            resolved[name] = ResolvedFutureInputRef(producer=producer)
            producer_spec = stage_specs[input_ref.producer_stage_id]
            output_spec = producer_spec.outputs[input_ref.name]
            artifact = producer_result.artifacts[input_ref.name]
            verified = verify_snapshot_artifact(
                producer,
                artifact,
                data_role=output_spec.data_role,
                fetcher=fetcher,
            )
            materialized_path = output_spec.path
            paths[name] = materialize_verified_artifact(
                root, materialized_path, verified
            )
            identities.append(
                artifact_input_identity(
                    name,
                    output_spec.data_role,
                    materialized_path,
                    verified.artifact,
                )
            )
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
            identities.append(
                ReuseInputIdentity(
                    input_name=name,
                    data_role=input_ref.data_role,
                    files=(
                        ReuseFileIdentity(
                            relative_path=captured_path.name,
                            sha256=resolved_input.file.sha256,
                            bytes=resolved_input.file.bytes,
                        ),
                    ),
                )
            )
        elif input_ref.kind == "stored":
            if isinstance(input_ref.pointer, ResolvedArtifactPointerRef):
                pointer_raw = fetcher.read(input_ref.pointer)
                resolved_pointer = input_ref.pointer
            else:
                pointer_raw = fetcher(input_ref.pointer)
                resolved_pointer = ResolvedArtifactPointerRef(
                    sha256=hashlib.sha256(pointer_raw).hexdigest(),
                    bytes=len(pointer_raw),
                    stored_at=input_ref.pointer,
                )
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            verified_run = verified_runs.get(pointer.run)
            if verified_run is None:
                verified_run = verify_pointer_producer(
                    pointer,
                    policy=policy,
                    fetcher=fetcher,
                )
                verified_runs[pointer.run] = verified_run
            verified = verify_artifact_in_run(
                pointer,
                verified_run=verified_run,
                policy=policy,
                expected_data_role=input_ref.data_role,
                materialization_path=None,
                fetcher=fetcher,
            )
            materialized_path = stored_input_path(
                run_id=run_id,
                attempt_id=attempt_id,
                stage_id=stage_id,
                input_name=name,
                declared_path=input_ref.path,
                materialization=input_ref.materialization,
            )
            paths[name] = materialize_verified_artifact(
                root, materialized_path, verified
            )
            resolved[name] = ResolvedStoredInputRef(pointer=resolved_pointer)
            stored[name] = verified.references
            identities.append(
                artifact_input_identity(
                    name,
                    input_ref.data_role,
                    materialized_path,
                    verified.artifact,
                )
            )
    return (
        resolved,
        paths,
        captured,
        stored,
        tuple(sorted(identities, key=lambda item: item.input_name)),
    )


def verify_captured_inputs(
    captured: Mapping[InputName, SnapshotFileRef],
    paths: Mapping[str, Path],
) -> None:
    """Require every captured local input to retain its pre-execution identity."""
    for input_name, reference in captured.items():
        try:
            raw = paths[input_name].read_bytes()
        except (KeyError, OSError) as exc:
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
        declaration = stage.outputs[input_name]
        if declaration.kind != "file":
            raise RunError("download artifact must be a single file")
        body = publish_download_body(
            repository_root=root,
            source=result.body,
            destination=declaration.path,
            expected_sha256=request.expected_body_sha256,
            expected_bytes=request.expected_body_bytes,
            physical_destination=result.body,
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
        artifacts[input_name] = ResolvedSingleFileArtifact(
            relative_path=declaration.relative_path,
            file=body,
        )
        paths[input_name] = result.body
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
    captured_path = captured_input_path(
        run_id=run_id,
        attempt_id=attempt_id,
        stage_id=stage_id,
        input_name=input_name,
        source_path=input_ref.source.path,
    )
    target = root / captured_path
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
    snapshot_path = captured_input_snapshot_path(
        stage_id=stage_id,
        input_name=input_name,
        source_path=input_ref.source.path,
    )
    reference = snapshot_file(snapshot_path, raw)
    return (
        ResolvedExternalInputRef(
            source=input_ref.source,
            file=reference,
            data_role=input_ref.data_role,
        ),
        target,
    )


def _artifact_producer(
    root: Path,
    reference: ResolvedRunRef,
    selection: StageArtifactRef,
    benchmark_result: ResolvedBenchmarkResultRef | None,
    trusted_source_repositories: frozenset[str],
) -> tuple[RunFetcher, VerificationPolicy, ArtifactPointer, VerifiedProducerRun]:
    """Verify the shared producer records and preserve the caller's source trust."""
    repository = str(read_source(root).repository)
    fetcher = RunFetcher(root, LocalArtifactStore(root), repository)
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({repository})
        | trusted_source_repositories
    )
    pointer = ArtifactPointer(
        run=reference, artifact=selection, benchmark_result=benchmark_result
    )
    producer = verify_pointer_producer(pointer, policy=policy, fetcher=fetcher)
    return fetcher, policy, pointer, producer


def artifact_reference(
    repository_root: Path | None,
    reference: ResolvedRunRef,
    selection: StageArtifactRef,
    *,
    member: RepoRelPath | None = None,
    benchmark_result: ResolvedBenchmarkResultRef | None = None,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> ResolvedFileRef:
    """Return an expected file reference from verified producer records.

    The resolver checks payload availability and bytes when the file is read.
    Bundle selections require an exact relative member path.
    """
    owner = current_session()
    root = (
        owner.root
        if repository_root is None and owner is not None
        else resolve_root()
        if repository_root is None
        else repository_root.resolve(strict=True)
    )
    with workflow(root):
        fetcher, policy, pointer, producer = _artifact_producer(
            root, reference, selection, benchmark_result, trusted_source_repositories
        )
        _, stage, _, _, artifact = select_artifact_in_run(
            pointer, verified_run=producer, policy=policy, fetcher=fetcher
        )
        files = snapshot_artifact_files(stage, artifact, fetcher=fetcher)
        inventory = fetcher.snapshot_files(stage.snapshot)
        if not set(files).issubset(inventory):
            raise VerificationError("artifact files differ from the snapshot inventory")
        if artifact.kind == "file":
            return resolve_snapshot_file_ref(stage.snapshot, artifact.file)
        if member is None:
            raise ValueError("select an exact artifact bundle member")
        for selected in artifact.members:
            if selected.relative_path == member:
                return resolve_snapshot_file_ref(stage.snapshot, selected.file)
        raise ValueError("artifact bundle does not contain the selected member")


def artifact_path(
    repository_root: Path | None,
    reference: ResolvedRunRef,
    selection: StageArtifactRef,
    *,
    member: RepoRelPath | None = None,
    benchmark_result: ResolvedBenchmarkResultRef | None = None,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> Path:
    """Return the verified local path of a selected artifact or bundle member.

    A single-file artifact always selects its declared file. For a bundle,
    member selects an exact relative path; omit it to obtain the whole bundle.
    """
    owner = current_session()
    if owner is None:
        raise ValueError("artifact_path requires an active storage.workflow")
    root = (
        owner.root if repository_root is None else repository_root.resolve(strict=True)
    )
    if owner.root != root:
        raise ValueError("artifact path belongs to another workflow root")
    fetcher, policy, pointer, producer = _artifact_producer(
        root, reference, selection, benchmark_result, trusted_source_repositories
    )
    store = fetcher.store
    verified = verify_artifact_in_run(
        pointer,
        verified_run=producer,
        policy=policy,
        expected_data_role=None,
        materialization_path=None,
        fetcher=fetcher,
    )
    if verified.artifact.kind == "bundle" and member is not None:
        for selected, file in zip(
            verified.artifact.members, verified.references, strict=True
        ):
            if selected.relative_path == member:
                return store.adopt_verified_reference(file, fetcher.path(file))
        raise ValueError("artifact bundle does not contain the selected member")
    target = f"{store.store}/bundles/{document_digest(pointer)}"
    return materialize_verified_artifact(root, target, verified)
