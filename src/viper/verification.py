"""Verify connected VIPER provenance records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, TypeAdapter

from . import keys
from ._schema import DataRole, RepoRelPath
from ._verification.attempt import (
    verify_attempt_files,
    verify_attempt_journal,
    verify_attempt_stages,
    verify_download_retrieval,
    verify_external_inputs,
    verify_measurement_stage_times,
)
from ._verification.metrics import verify_recomputed_metrics
from ._verification.paths import resolved_stage_spec_path, run_root
from ._verification.plan import verify_run_plan, verify_run_spec
from ._verification.storage import (
    artifact_revision_identity,
    load_verified_artifact,
    read_attempt_reference,
    read_resolved_file,
    read_snapshot_file,
    snapshot_identity,
    verify_run_attempt_references,
    verify_snapshot_artifact,
)
from .artifacts import (
    ArtifactPointer,
    ResolvedBundleArtifact,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from .benchmark import BenchmarkResult, BenchmarkSpec
from .evidence import (
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedBenchmarkResult,
    VerifiedInput,
    VerifiedProducerRun,
    VerifiedRunPlan,
    VerifiedRunResult,
)
from .ids import InputName, MetricId, StageId
from .inputs import (
    DownloadSourceClosureReceipt,
    DownloadSourceEdge,
    DownloadSourceNode,
    ExternalInputRef,
    FutureInputRef,
    InputRef,
    ResolvedFutureInputRef,
    ResolvedInputRef,
    ResolvedStoredInputRef,
    StoredInputRef,
    VerifiedDownloadSource,
    pointer_location_matches,
)
from .metrics import (
    Measurement,
    MetricVerificationReceipt,
    compare_metric_values,
    is_recomputed_metric,
)
from .references import (
    GitFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
    SnapshotFileRef,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
    storage_file,
)
from .reuse import (
    ReusedStageCompletion,
    ReuseInputIdentity,
    StageReuseKey,
    StageReuseReceipt,
    build_stage_reuse_key,
    verified_input_identity,
)
from .runs import ResolvedAttemptRef, ResolvedRun, RunAttempt, RunSpec
from .serialization import document_digest, parse_yaml_bytes
from .stages import (
    BaseSpec,
    EvalSpec,
    InternalSpec,
    ResolvedBaseSpec,
    ResolvedDownloadSpec,
    ResolvedInternalSpec,
    ResolvedParameterizedSpec,
    ResolvedSpec,
    Spec,
    TrainSpec,
)

__all__ = [
    "verify_download_source_closure",
    "verify_attempt_future_inputs",
    "verify_benchmark_result",
    "verify_promoted_artifact",
    "verify_run_result",
    "verify_stage_reuse",
    "verify_stored_input_selections",
    "verify_stored_inputs",
]


def verify_download_source_closure(
    stage_id: StageId,
    stage: InternalSpec,
    *,
    run: RunSpec,
    attempt_id: int,
    resolved_inputs: Mapping[InputName, ResolvedInputRef],
    stage_specs: Mapping[StageId, BaseSpec],
    completed_stages: Mapping[StageId, ResolvedStageRef],
    completed_results: Mapping[StageId, ResolvedBaseSpec],
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> DownloadSourceClosureReceipt:
    """Prove that every transitive input ends at an immutable Download receipt."""
    if not stage.inputs:
        raise VerificationError(
            f"stage {stage_id!r} has no inputs to prove download-rooted"
        )
    if set(resolved_inputs) != set(stage.inputs):
        raise VerificationError("download source closure inputs differ from the stage")

    spec_adapter = TypeAdapter(Spec)
    resolved_spec_adapter = TypeAdapter(ResolvedSpec)
    selected_runs: dict[ResolvedRunRef, tuple[ResolvedRun, RunSpec]] = {}
    selected_attempts: dict[tuple[ResolvedRunRef, ResolvedAttemptRef], RunAttempt] = {}
    selected_contexts: dict[
        tuple[ResolvedRunRef, ResolvedAttemptRef, StageId],
        tuple[
            RunSpec,
            RunAttempt,
            dict[StageId, BaseSpec],
            dict[StageId, ResolvedStageRef],
            dict[StageId, ResolvedBaseSpec],
        ],
    ] = {}
    active: set[tuple[str, int, StageId, str, str]] = set()
    nodes: dict[str, DownloadSourceNode] = {}
    edges: dict[tuple[str, str, str], DownloadSourceEdge] = {}

    def stage_node(
        selected_run: RunSpec,
        selected_attempt: int,
        selected_stage: StageId,
        direction: str,
        name: str,
        receipt: ResolvedStageRef | None = None,
    ) -> str:
        receipt_id = "current" if receipt is None else receipt.resolved_spec.sha256
        node_id = (
            f"run:{selected_run.run_id}/attempt:{selected_attempt}/"
            f"stage:{selected_stage}/receipt:{receipt_id}/{direction}:{name}"
        )
        kind = "stage_input" if direction == "input" else "stage_output"
        nodes[node_id] = DownloadSourceNode(node_id=node_id, kind=kind)
        return node_id

    def reference_node(kind: Literal["pointer", "reuse"], sha256: str) -> str:
        node_id = f"{kind}:{sha256}"
        nodes[node_id] = DownloadSourceNode(node_id=node_id, kind=kind)
        return node_id

    def connect(
        source: str,
        target: str,
        relation: Literal["future", "stored", "selects", "produced_from", "reuse"],
    ) -> None:
        identity = (source, target, relation)
        edges[identity] = DownloadSourceEdge(
            source=source,
            target=target,
            relation=relation,
        )

    def selected_context(
        reference: ResolvedRunRef,
        selected_stage_id: StageId,
        *,
        attempt_reference: ResolvedAttemptRef | None = None,
    ) -> tuple[
        RunSpec,
        RunAttempt,
        dict[StageId, BaseSpec],
        dict[StageId, ResolvedStageRef],
        dict[StageId, ResolvedBaseSpec],
    ]:
        """Load only the receipts on one selected producer branch."""
        loaded_run = selected_runs.get(reference)
        if loaded_run is None:
            try:
                result = ResolvedRun.model_validate(
                    parse_yaml_bytes(read_resolved_file(reference, fetcher=fetcher))
                )
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    "download source run receipt is invalid"
                ) from exc
            selected_run = verify_run_spec(result, fetcher=fetcher)
            if reference.stored_at.path != f"{run_root(selected_run)}/resolved.yaml":
                raise VerificationError(
                    "download source run receipt is outside its canonical path"
                )
            if not policy.permits_source(selected_run.source.repository):
                raise VerificationError("download source run repository is not trusted")
            selected_runs[reference] = (result, selected_run)
        else:
            result, selected_run = loaded_run
        if attempt_reference is None:
            if result.status != "succeeded" or result.successful_attempt_id is None:
                raise VerificationError("download source run did not succeed")
            expected_path = (
                f"{run_root(selected_run)}/attempts/"
                f"{result.successful_attempt_id}/resolved.yaml"
            )
            matching = tuple(
                candidate
                for candidate in result.attempts
                if candidate.stored_at.path == expected_path
            )
            if len(matching) != 1:
                raise VerificationError(
                    "download source successful attempt receipt is unavailable"
                )
            attempt_reference = matching[0]
        elif attempt_reference not in result.attempts:
            raise VerificationError("download source reuse attempt is unavailable")
        assert attempt_reference is not None
        cache_key = (reference, attempt_reference, selected_stage_id)
        cached = selected_contexts.get(cache_key)
        if cached is not None:
            return cached
        attempt_key = (reference, attempt_reference)
        source_attempt = selected_attempts.get(attempt_key)
        if source_attempt is None:
            source_attempt = read_attempt_reference(
                attempt_reference,
                selected_run,
                fetcher=fetcher,
            )
            if (
                attempt_reference.stored_at.path.endswith(
                    f"/{result.successful_attempt_id}/resolved.yaml"
                )
                and source_attempt.status != "succeeded"
            ):
                raise VerificationError("download source successful attempt differs")
            planned_ids = tuple(item.stage_id for item in selected_run.stages)
            completed_ids = tuple(
                item.stage_id for item in source_attempt.resolved_stages
            )
            if completed_ids != planned_ids[: len(completed_ids)]:
                raise VerificationError(
                    "download source attempt stages do not form a plan prefix"
                )
            selected_attempts[attempt_key] = source_attempt
        selected_specs: dict[StageId, BaseSpec] = {}
        selected_refs: dict[StageId, ResolvedStageRef] = {}
        selected_results: dict[StageId, ResolvedBaseSpec] = {}

        def load_stage(branch_stage_id: StageId) -> None:
            if branch_stage_id in selected_results:
                return
            planned = next(
                (
                    item
                    for item in selected_run.stages
                    if item.stage_id == branch_stage_id
                ),
                None,
            )
            resolved = next(
                (
                    item
                    for item in source_attempt.resolved_stages
                    if item.stage_id == branch_stage_id
                ),
                None,
            )
            if planned is None or resolved is None:
                raise VerificationError("download source producer is unavailable")
            if resolved.resolved_spec.path != resolved_stage_spec_path(
                selected_run, branch_stage_id
            ):
                raise VerificationError(
                    "download source stage receipt is outside its canonical path"
                )
            planned_reference = ResolvedFileRef(
                sha256=planned.sha256,
                bytes=planned.bytes,
                stored_at=storage_file(result.spec.stored_at, planned.spec),
            )
            try:
                stage_spec = spec_adapter.validate_python(
                    parse_yaml_bytes(
                        read_resolved_file(planned_reference, fetcher=fetcher)
                    )
                )
                stage_result = resolved_spec_adapter.validate_python(
                    parse_yaml_bytes(
                        read_snapshot_file(
                            resolved.snapshot,
                            resolved.resolved_spec,
                            fetcher=fetcher,
                        )
                    )
                )
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    "download source stage receipt is invalid"
                ) from exc
            if stage_result.spec != stage_spec:
                raise VerificationError(
                    "download source resolved stage differs from its plan"
                )
            selected_specs[branch_stage_id] = stage_spec
            selected_refs[branch_stage_id] = resolved
            selected_results[branch_stage_id] = stage_result
            if isinstance(stage_result, ResolvedInternalSpec) and not isinstance(
                stage_result.completion, ReusedStageCompletion
            ):
                for input_ref in stage_spec.inputs.values():
                    if isinstance(input_ref, FutureInputRef):
                        load_stage(input_ref.producer_stage_id)

        load_stage(selected_stage_id)
        context = (
            selected_run,
            source_attempt,
            selected_specs,
            selected_refs,
            selected_results,
        )
        selected_contexts[cache_key] = context
        return context

    def walk_stage(
        selected_output: str,
        *,
        selected_run: RunSpec,
        selected_attempt: int,
        selected_specs: Mapping[StageId, BaseSpec],
        selected_refs: Mapping[StageId, ResolvedStageRef],
        selected_results: Mapping[StageId, ResolvedBaseSpec],
        producer_stage_id: StageId,
    ) -> tuple[VerifiedDownloadSource, ...]:
        reference = selected_refs.get(producer_stage_id)
        if reference is None:
            raise VerificationError("download source producer is unavailable")
        key = (
            str(selected_run.run_id),
            selected_attempt,
            producer_stage_id,
            selected_output,
            reference.resolved_spec.sha256,
        )
        if key in active:
            raise VerificationError("download source graph contains a cycle")
        active.add(key)
        try:
            result = selected_results.get(producer_stage_id)
            spec = selected_specs.get(producer_stage_id)
            if result is None or spec is None:
                raise VerificationError("download source producer is unavailable")
            if selected_output not in result.artifacts:
                raise VerificationError("download source output is unavailable")

            if isinstance(result, ResolvedDownloadSpec):
                if selected_output not in result.retrievals:
                    raise VerificationError(
                        "download source output has no HTTP retrieval evidence"
                    )
                retrieval = result.retrievals[selected_output]
                if (
                    selected_output not in result.spec.inputs
                    or retrieval.request != result.spec.inputs[selected_output]
                ):
                    raise VerificationError(
                        "download source retrieval differs from its request"
                    )
                artifact = result.artifacts[selected_output]
                if not isinstance(artifact, ResolvedSingleFileArtifact) or (
                    retrieval.body != artifact.file
                ):
                    raise VerificationError(
                        "download source body differs from its artifact receipt"
                    )
                return (
                    VerifiedDownloadSource(
                        run_id=selected_run.run_id,
                        attempt_id=selected_attempt,
                        stage_id=producer_stage_id,
                        stage_receipt=reference,
                        input_name=selected_output,
                        request=retrieval.request,
                        body=retrieval.body,
                    ),
                )

            if not isinstance(result, ResolvedInternalSpec) or not isinstance(
                spec, InternalSpec
            ):
                raise VerificationError("download source producer is not traversable")
            if isinstance(result.completion, ReusedStageCompletion):
                output_node = stage_node(
                    selected_run,
                    selected_attempt,
                    producer_stage_id,
                    "output",
                    selected_output,
                    reference,
                )
                reuse_node = reference_node("reuse", result.completion.receipt.sha256)
                connect(output_node, reuse_node, "reuse")
                raw = read_resolved_file(
                    result.completion.receipt,
                    fetcher=fetcher,
                )
                try:
                    receipt = StageReuseReceipt.model_validate(parse_yaml_bytes(raw))
                except (yaml.YAMLError, ValueError) as exc:
                    raise VerificationError(
                        "download source reuse receipt is invalid"
                    ) from exc
                (
                    source_run,
                    source_attempt,
                    source_specs,
                    source_refs,
                    source_results,
                ) = selected_context(
                    receipt.source_run,
                    producer_stage_id,
                    attempt_reference=receipt.source_attempt,
                )
                source_attempt_id = source_attempt.attempt_id
                source_reference = source_refs[producer_stage_id]
                source_result = source_results[producer_stage_id]
                if (
                    receipt.stage_id != producer_stage_id
                    or receipt.source_stage != source_reference
                ):
                    raise VerificationError(
                        "download source reuse receipt selects another stage"
                    )
                expected_files = _expected_reused_files(source_result, result)
                received_files = tuple(
                    (file.artifact_name, file.source, file.target)
                    for file in receipt.files
                )
                if received_files != expected_files:
                    raise VerificationError(
                        "download source reuse files differ from their source"
                    )
                source_output = stage_node(
                    source_run,
                    source_attempt_id,
                    producer_stage_id,
                    "output",
                    selected_output,
                    source_reference,
                )
                connect(reuse_node, source_output, "selects")
                return walk_stage(
                    selected_output,
                    selected_run=source_run,
                    selected_attempt=source_attempt_id,
                    selected_specs=source_specs,
                    selected_refs=source_refs,
                    selected_results=source_results,
                    producer_stage_id=producer_stage_id,
                )
            if not result.inputs:
                raise VerificationError(
                    "download source internal producer has no transitive inputs"
                )
            roots: list[VerifiedDownloadSource] = []
            for input_name, input_ref in spec.inputs.items():
                output_node = stage_node(
                    selected_run,
                    selected_attempt,
                    producer_stage_id,
                    "output",
                    selected_output,
                    reference,
                )
                input_node = stage_node(
                    selected_run,
                    selected_attempt,
                    producer_stage_id,
                    "input",
                    input_name,
                    reference,
                )
                connect(output_node, input_node, "produced_from")
                roots.extend(
                    walk_input(
                        input_name,
                        input_ref,
                        result.inputs[input_name],
                        selected_run=selected_run,
                        selected_attempt=selected_attempt,
                        selected_specs=selected_specs,
                        selected_refs=selected_refs,
                        selected_results=selected_results,
                        consumer_stage_id=producer_stage_id,
                    )
                )
            return tuple(roots)
        finally:
            active.remove(key)

    def walk_input(
        input_name: InputName,
        input_ref: InputRef,
        resolved_input: ResolvedInputRef,
        *,
        selected_run: RunSpec,
        selected_attempt: int,
        selected_specs: Mapping[StageId, BaseSpec],
        selected_refs: Mapping[StageId, ResolvedStageRef],
        selected_results: Mapping[StageId, ResolvedBaseSpec],
        consumer_stage_id: StageId,
    ) -> tuple[VerifiedDownloadSource, ...]:
        input_node = stage_node(
            selected_run,
            selected_attempt,
            consumer_stage_id,
            "input",
            input_name,
        )
        if isinstance(input_ref, ExternalInputRef):
            raise VerificationError(
                f"input {input_name!r} originates from an external local file"
            )
        if isinstance(input_ref, FutureInputRef):
            if not isinstance(resolved_input, ResolvedFutureInputRef):
                raise VerificationError("future input resolved as another input kind")
            producer_result = selected_results.get(input_ref.producer_stage_id)
            producer_ref = selected_refs.get(input_ref.producer_stage_id)
            if producer_result is None or producer_ref is None:
                raise VerificationError("future input producer is unavailable")
            producer_spec = selected_specs.get(input_ref.producer_stage_id)
            if producer_spec is None or input_ref.name not in producer_spec.outputs:
                raise VerificationError("future input output is unavailable")
            if resolved_input.producer != producer_ref:
                raise VerificationError(
                    "future input resolves a different producer stage"
                )
            output_node = stage_node(
                selected_run,
                selected_attempt,
                input_ref.producer_stage_id,
                "output",
                input_ref.name,
                producer_ref,
            )
            connect(input_node, output_node, "future")
            return walk_stage(
                str(input_ref.name),
                selected_run=selected_run,
                selected_attempt=selected_attempt,
                selected_specs=selected_specs,
                selected_refs=selected_refs,
                selected_results=selected_results,
                producer_stage_id=input_ref.producer_stage_id,
            )
        if not isinstance(input_ref, StoredInputRef) or not isinstance(
            resolved_input, ResolvedStoredInputRef
        ):
            raise VerificationError("stored input resolved as another input kind")
        pointer_raw = read_resolved_file(resolved_input.pointer, fetcher=fetcher)
        pointer_node = reference_node("pointer", resolved_input.pointer.sha256)
        connect(input_node, pointer_node, "stored")
        try:
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError("download source pointer is invalid") from exc
        if not pointer_location_matches(
            input_ref.pointer,
            resolved_input.pointer.stored_at,
        ):
            raise VerificationError(
                f"input {input_name!r} resolved a different pointer location"
            )
        (
            source_run,
            source_attempt,
            source_specs,
            source_refs,
            source_results,
        ) = selected_context(
            pointer.run,
            pointer.artifact.stage_id,
        )
        producer = source_results[pointer.artifact.stage_id]
        artifact_name = pointer.artifact.artifact_name
        if artifact_name not in producer.artifacts:
            raise VerificationError(
                "download source pointer selects an undeclared artifact"
            )
        declaration = source_specs[pointer.artifact.stage_id].outputs[artifact_name]
        if declaration.data_role != input_ref.data_role:
            raise VerificationError(
                "download source pointer selects an incompatible data role"
            )
        output_node = stage_node(
            source_run,
            source_attempt.attempt_id,
            pointer.artifact.stage_id,
            "output",
            pointer.artifact.artifact_name,
            source_refs[pointer.artifact.stage_id],
        )
        connect(pointer_node, output_node, "selects")
        return walk_stage(
            str(pointer.artifact.artifact_name),
            selected_run=source_run,
            selected_attempt=source_attempt.attempt_id,
            selected_specs=source_specs,
            selected_refs=source_refs,
            selected_results=source_results,
            producer_stage_id=pointer.artifact.stage_id,
        )

    roots_by_input: dict[InputName, tuple[VerifiedDownloadSource, ...]] = {}
    for input_name, input_ref in stage.inputs.items():
        roots = walk_input(
            input_name,
            input_ref,
            resolved_inputs[input_name],
            selected_run=run,
            selected_attempt=attempt_id,
            selected_specs=stage_specs,
            selected_refs=completed_stages,
            selected_results=completed_results,
            consumer_stage_id=stage_id,
        )
        unique = {
            (
                root.run_id,
                root.attempt_id,
                root.stage_id,
                root.input_name,
                root.stage_receipt.resolved_spec.sha256,
            ): root
            for root in roots
        }
        roots_by_input[input_name] = tuple(unique[key] for key in sorted(unique))
    return DownloadSourceClosureReceipt(
        roots=roots_by_input,
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        edges=tuple(edges[key] for key in sorted(edges)),
    )


def _stage_artifact_files(
    stage: ResolvedBaseSpec,
) -> dict[str, tuple[SnapshotFileRef, ...]]:
    """Index every resolved artifact file by artifact name."""
    files: dict[str, tuple[SnapshotFileRef, ...]] = {}
    for artifact_name, artifact in stage.artifacts.items():
        if isinstance(artifact, ResolvedSingleFileArtifact):
            files[artifact_name] = (artifact.file,)
        elif isinstance(artifact, ResolvedBundleArtifact):
            files[artifact_name] = tuple(member.file for member in artifact.members)
    return files


def _artifact_relative_path(path: str) -> str:
    """Return the stable portion of an artifact path after its run root."""
    marker = "/artifacts/"
    if marker not in path:
        raise VerificationError("reused artifact file has no artifact path boundary")
    return path.split(marker, 1)[1]


def _expected_reused_files(
    source: ResolvedBaseSpec,
    target: ResolvedBaseSpec,
) -> tuple[tuple[str, SnapshotFileRef, SnapshotFileRef], ...]:
    """Join source and target files by artifact name and relative path."""
    source_files = _stage_artifact_files(source)
    target_files = _stage_artifact_files(target)
    if set(source_files) != set(target_files):
        raise VerificationError("reused source and target artifacts differ")

    pairs: list[tuple[str, SnapshotFileRef, SnapshotFileRef]] = []
    for artifact_name in sorted(source_files):
        source_by_path = {
            _artifact_relative_path(str(file.path)): file
            for file in source_files[artifact_name]
        }
        target_by_path = {
            _artifact_relative_path(str(file.path)): file
            for file in target_files[artifact_name]
        }
        if set(source_by_path) != set(target_by_path):
            raise VerificationError("reused source and target file paths differ")
        pairs.extend(
            (artifact_name, source_by_path[path], target_by_path[path])
            for path in sorted(source_by_path)
        )
    return tuple(pairs)


def _metric_references(
    references: Sequence[ResolvedFileRef],
    *,
    stage_id: StageId,
    directory: str,
) -> dict[MetricId, ResolvedFileRef]:
    """Index one stage's measurement or verification references by metric ID."""
    selected: dict[MetricId, ResolvedFileRef] = {}
    prefix = f"/{directory}/{stage_id}."
    suffix = ".jsonl" if directory == "measurements" else ".yaml"
    for reference in references:
        path = str(reference.stored_at.path)
        if prefix not in path or not path.endswith(suffix):
            continue
        metric_id = path.split(prefix, 1)[1].removesuffix(suffix)
        if metric_id in selected:
            raise VerificationError("reused metric evidence is duplicated")
        selected[metric_id] = reference
    return selected


def _rebuilt_reuse_key(
    plan: VerifiedRunPlan,
    stage_id: StageId,
    inputs: Sequence[ReuseInputIdentity],
) -> StageReuseKey:
    """Rebuild one stage key from its verified plan values and input files."""
    stage = plan.stages.get(stage_id)
    if not isinstance(stage, InternalSpec):
        raise VerificationError("stage reuse requires an internal stage")
    metrics = {metric.metric_id: metric for metric in plan.experiment.metrics}
    try:
        return build_stage_reuse_key(
            stage_id=stage_id,
            stage=stage,
            inputs=inputs,
            seed=plan.run.seed,
            env=stage.env or plan.run.env,
            reproducibility=plan.run.reproducibility,
            metrics=metrics,
        )
    except (KeyError, ValueError) as exc:
        raise VerificationError("stage reuse key cannot be rebuilt") from exc


def verify_stage_reuse(
    receipt: StageReuseReceipt,
    *,
    source_reference: ResolvedRunRef,
    source: VerifiedRunResult,
    source_inputs: Sequence[ReuseInputIdentity],
    target_plan: VerifiedRunPlan,
    target_stage: ResolvedStageRef,
    target_result: ResolvedBaseSpec,
    target_inputs: Sequence[ReuseInputIdentity],
) -> StageReuseReceipt:
    """Verify one reuse receipt across its source, key, files, and metrics."""
    if receipt.stage_id != target_stage.stage_id:
        raise VerificationError("reuse receipt and target stage IDs differ")
    if receipt.source_run != source_reference:
        raise VerificationError("reuse receipt selects a different source run")
    expected_source_path = f"{run_root(source.plan.run)}/resolved.yaml"
    if source_reference.stored_at.path != expected_source_path:
        raise VerificationError("reuse receipt source run path differs")

    try:
        attempt_index = source.result.attempts.index(receipt.source_attempt)
    except ValueError as exc:
        raise VerificationError("reuse receipt source attempt is absent") from exc
    source_attempt = source.attempts[attempt_index]

    source_stage = next(
        (
            stage
            for stage in source_attempt.resolved_stages
            if stage.stage_id == receipt.stage_id
        ),
        None,
    )
    if source_stage is None or receipt.source_stage != source_stage:
        raise VerificationError("reuse receipt selects a different source stage")
    source_results = source.attempt_stages.get(source_attempt.attempt_id)
    if source_results is None and (
        source_attempt.attempt_id == source.result.successful_attempt_id
    ):
        source_results = source.resolved_stages
    source_result = (
        None if source_results is None else source_results.get(receipt.stage_id)
    )
    if source_result is None:
        raise VerificationError("reused source stage has no verified result")
    source_reuse = source.attempt_reuse.get(source_attempt.attempt_id, {}).get(
        receipt.stage_id
    )
    if (
        isinstance(getattr(source_result, "completion", None), ReusedStageCompletion)
        and source_reuse is None
    ):
        raise VerificationError("reused source stage has no verified reuse receipt")

    source_key = _rebuilt_reuse_key(source.plan, receipt.stage_id, source_inputs)
    target_key = _rebuilt_reuse_key(target_plan, receipt.stage_id, target_inputs)
    if target_result.spec != target_plan.stages.get(receipt.stage_id):
        raise VerificationError("reuse target result differs from its plan")
    if receipt.key != source_key or receipt.key != target_key:
        raise VerificationError("reuse receipt key differs from source or target")

    expected_files = _expected_reused_files(source_result, target_result)
    received_files = tuple(
        (file.artifact_name, file.source, file.target) for file in receipt.files
    )
    if received_files != expected_files:
        raise VerificationError("reuse receipt file remapping differs")

    expected_metric_ids = tuple(target_result.spec.metric_ids)
    received_metric_ids = tuple(metric.metric_id for metric in receipt.metrics)
    if received_metric_ids != expected_metric_ids:
        raise VerificationError("reuse receipt metric coverage differs")
    if source_reuse is not None:
        if receipt.metrics != source_reuse.metrics:
            raise VerificationError(
                "reuse receipt metric evidence differs from source reuse"
            )
        return receipt

    measurements = _metric_references(
        source_attempt.measurement_files,
        stage_id=receipt.stage_id,
        directory="measurements",
    )
    verifications = _metric_references(
        source_attempt.metric_verification_files,
        stage_id=receipt.stage_id,
        directory="metric_verification",
    )
    source_metrics = {
        metric.metric_id: metric for metric in source.plan.experiment.metrics
    }
    for evidence in receipt.metrics:
        if measurements.get(evidence.metric_id) != evidence.measurement:
            raise VerificationError("reuse receipt measurement differs")
        metric = source_metrics.get(evidence.metric_id)
        if metric is None:
            raise VerificationError("reuse receipt metric is absent from source plan")
        expected_verification = (
            verifications.get(evidence.metric_id)
            if is_recomputed_metric(metric)
            else None
        )
        if is_recomputed_metric(metric) and expected_verification is None:
            raise VerificationError("reused metric has no verification evidence")
        if evidence.verification != expected_verification:
            raise VerificationError("reuse receipt metric verification differs")
        if not any(
            measurement.attempt_id == source_attempt.attempt_id
            and measurement.stage_id == receipt.stage_id
            and measurement.metric_id == evidence.metric_id
            for measurement in source.measurements
        ):
            raise VerificationError("reuse receipt metric has no verified measurement")
    return receipt


def _merge_stage_inputs(
    *groups: Mapping[StageId, Mapping[InputName, VerifiedInput]],
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Combine independently verified input kinds without overwriting a name."""
    merged: dict[StageId, dict[InputName, VerifiedInput]] = {}
    for group in groups:
        for stage_id, inputs in group.items():
            stage_inputs = merged.setdefault(stage_id, {})
            duplicate = set(stage_inputs) & set(inputs)
            if duplicate:
                raise VerificationError("verified stage input appears more than once")
            stage_inputs.update(inputs)
    return merged


def _input_identities(
    inputs: Mapping[InputName, VerifiedInput],
) -> tuple[ReuseInputIdentity, ...]:
    """Convert verified input bytes into the stable identity used by reuse."""
    return tuple(
        verified_input_identity(input_name, value)
        for input_name, value in sorted(inputs.items())
    )


def _verify_reused_stages(
    *,
    result: ResolvedRun,
    plan: VerifiedRunPlan,
    attempts: tuple[RunAttempt, ...],
    stages: Mapping[int, Mapping[StageId, ResolvedBaseSpec]],
    inputs: Mapping[int, Mapping[StageId, Mapping[InputName, VerifiedInput]]],
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
    ancestors: frozenset[str],
) -> dict[int, dict[StageId, StageReuseReceipt]]:
    """Follow and verify every reuse receipt in every recorded attempt."""
    receipts_by_attempt: dict[int, dict[StageId, StageReuseReceipt]] = {}
    for attempt in attempts:
        attempt_stages = stages.get(attempt.attempt_id, {})
        attempt_inputs = inputs.get(attempt.attempt_id, {})
        receipts: dict[StageId, StageReuseReceipt] = {}
        for stage_reference in attempt.resolved_stages:
            target = attempt_stages[stage_reference.stage_id]
            if not isinstance(target, ResolvedParameterizedSpec) or not isinstance(
                target.completion, ReusedStageCompletion
            ):
                continue
            raw = read_resolved_file(target.completion.receipt, fetcher=fetcher)
            try:
                receipt = StageReuseReceipt.model_validate(parse_yaml_bytes(raw))
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError("stage reuse receipt is invalid") from exc
            source_id = receipt.source_run.sha256
            if source_id in ancestors:
                raise VerificationError("stage reuse sources form a cycle")
            source_raw = read_resolved_file(receipt.source_run, fetcher=fetcher)
            try:
                source_run = ResolvedRun.model_validate(parse_yaml_bytes(source_raw))
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError("stage reuse source run is invalid") from exc
            source = _verify_run_result(
                source_run,
                policy=policy,
                fetcher=fetcher,
                ancestors=ancestors | {source_id},
            )
            source_attempt_id = next(
                (
                    source_attempt.attempt_id
                    for source_attempt, reference in zip(
                        source.attempts,
                        source.result.attempts,
                        strict=True,
                    )
                    if reference == receipt.source_attempt
                ),
                None,
            )
            if source_attempt_id is None:
                raise VerificationError("reuse receipt source attempt is absent")
            verify_stage_reuse(
                receipt,
                source_reference=receipt.source_run,
                source=source,
                source_inputs=_input_identities(
                    source.attempt_inputs.get(source_attempt_id, {}).get(
                        stage_reference.stage_id, {}
                    )
                ),
                target_plan=plan,
                target_stage=stage_reference,
                target_result=target,
                target_inputs=_input_identities(
                    attempt_inputs.get(stage_reference.stage_id, {})
                ),
            )
            receipts[stage_reference.stage_id] = receipt
        receipts_by_attempt[attempt.attempt_id] = receipts
    return receipts_by_attempt


def verify_run_result(
    resolved_run: ResolvedRun,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedRunResult:
    """Verify a terminal run from its RunSpec through every completed attempt."""
    return _verify_run_result(
        resolved_run,
        policy=policy,
        fetcher=fetcher,
        ancestors=frozenset(),
    )


def verify_promoted_artifact(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    expected_data_role: DataRole | None = None,
    materialization_path: RepoRelPath | None = None,
    fetcher: StorageFetcher | None = None,
) -> VerifiedArtifact:
    """Follow a promoted artifact pointer through its completed producer run."""
    verified_run = verify_pointer_run(pointer, policy=policy, fetcher=fetcher)
    return verify_artifact_in_run(
        pointer,
        verified_run=verified_run,
        policy=policy,
        expected_data_role=expected_data_role,
        materialization_path=materialization_path,
        fetcher=fetcher,
    )


def verify_pointer_run(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
) -> VerifiedRunResult:
    """Load and verify the completed run selected by one artifact pointer."""
    resolved_run_raw = read_resolved_file(pointer.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(resolved_run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "artifact pointer run is not a valid ResolvedRun document"
        ) from exc

    return verify_run_result(resolved_run, policy=policy, fetcher=fetcher)


@runtime_checkable
class _VerifiedProducerCache(Protocol):
    """Reuse producer structure proven earlier in one execution process."""

    def read_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
    ) -> VerifiedProducerRun | None:
        """Return cached producer evidence when available."""
        ...

    def remember_verified_producer(
        self,
        reference: ResolvedRunRef,
        policy: VerificationPolicy,
        producer: VerifiedProducerRun,
    ) -> None:
        """Retain producer evidence without artifact payload bytes."""
        ...


def _verified_producer_cache(
    fetcher: StorageFetcher | None,
) -> _VerifiedProducerCache | None:
    """Return the cache owner behind a callable storage fetcher."""
    owner = None if fetcher is None else getattr(fetcher, "__self__", fetcher)
    return owner if isinstance(owner, _VerifiedProducerCache) else None


def verify_pointer_producer(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
) -> VerifiedProducerRun:
    """Verify one producer structure without restoring unrelated payloads."""
    cache = _verified_producer_cache(fetcher)
    if cache is not None:
        cached = cache.read_verified_producer(pointer.run, policy)
        if cached is not None:
            return cached

    producer = _verify_pointer_producer_structure(
        pointer,
        policy=policy,
        fetcher=fetcher,
    )
    if cache is not None:
        cache.remember_verified_producer(pointer.run, policy, producer)
    return producer


def _verify_pointer_producer_structure(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
) -> VerifiedProducerRun:
    """Verify the producer records needed to select one immutable artifact."""
    resolved_run_raw = read_resolved_file(pointer.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(resolved_run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "artifact pointer run is not a valid ResolvedRun document"
        ) from exc

    _verify_cloud_graph(resolved_run)
    plan = verify_run_plan(resolved_run, fetcher=fetcher)
    attempts = verify_run_attempt_references(
        resolved_run,
        plan.run,
        fetcher=fetcher,
    )
    successful_stages: dict[StageId, ResolvedBaseSpec] = {}
    for attempt in attempts:
        verify_attempt_journal(attempt, plan.run, fetcher=fetcher)
        stages = verify_attempt_stages(
            attempt,
            plan.run,
            plan.stages,
            require_complete=attempt.status == "succeeded",
            policy=policy,
            fetcher=fetcher,
            verify_payloads=False,
        )
        if attempt.attempt_id == resolved_run.successful_attempt_id:
            successful_stages = stages

    if resolved_run.status == "succeeded":
        estimator_stage = successful_stages.get(plan.run.estimator.stage_id)
        if estimator_stage is None:
            raise VerificationError("successful run has no estimator-producing stage")
        if plan.run.estimator.artifact_name not in estimator_stage.artifacts:
            raise VerificationError("successful run has no selected estimator artifact")

    return VerifiedProducerRun(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        resolved_stages=successful_stages,
    )


def _verify_benchmark_plan_pointers(
    plan: VerifiedRunPlan,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
) -> None:
    """Verify benchmark pointer payloads reachable before their eval executes."""
    if plan.benchmark is None or getattr(fetcher, "read_plan_source", None) is None:
        return
    verified_runs: dict[ResolvedRunRef, VerifiedProducerRun] = {}
    references = (plan.benchmark.test, *plan.benchmark.splits.values())
    for reference in references:
        pointer_raw = read_resolved_file(reference, fetcher=fetcher)
        try:
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                "benchmark input pointer is not a valid ArtifactPointer document"
            ) from exc
        if pointer.run not in verified_runs:
            verified_runs[pointer.run] = verify_pointer_producer(
                pointer,
                policy=policy,
                fetcher=fetcher,
            )
        verify_artifact_in_run(
            pointer,
            verified_run=verified_runs[pointer.run],
            policy=policy,
            expected_data_role=None,
            materialization_path=None,
            fetcher=fetcher,
        )


def verify_artifact_in_run(
    pointer: ArtifactPointer,
    *,
    verified_run: VerifiedRunResult | VerifiedProducerRun,
    policy: VerificationPolicy,
    expected_data_role: DataRole | None,
    materialization_path: RepoRelPath | None,
    fetcher: StorageFetcher | None,
) -> VerifiedArtifact:
    """Verify one pointer selection against its already verified producer run."""
    expected_run_path = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if pointer.run.stored_at.path != expected_run_path:
        raise VerificationError(
            "artifact pointer run reference is outside the canonical run path"
        )

    if (
        verified_run.plan.run.benchmark_id is not None
        and pointer.artifact == verified_run.plan.run.estimator
        and pointer.benchmark_result is None
    ):
        raise VerificationError(
            "promotion of a benchmarked estimator requires a benchmark result"
        )

    producer_spec = verified_run.resolved_stages.get(pointer.artifact.stage_id)
    if producer_spec is None:
        raise VerificationError("artifact pointer selects an absent producer stage")

    artifact = producer_spec.artifacts.get(pointer.artifact.artifact_name)
    if artifact is None:
        raise VerificationError("artifact pointer selects an undeclared artifact")
    declaration = producer_spec.spec.outputs[pointer.artifact.artifact_name]

    if pointer.benchmark_result is not None:
        benchmark_result_raw = read_resolved_file(
            pointer.benchmark_result,
            fetcher=fetcher,
        )
        try:
            benchmark_result = BenchmarkResult.model_validate(
                parse_yaml_bytes(benchmark_result_raw)
            )
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                "artifact pointer benchmark result is invalid"
            ) from exc

        verify_benchmark_result(
            benchmark_result,
            policy=policy,
            fetcher=fetcher,
        )
        expected_result_path = (
            f"{run_root(verified_run.plan.run)}/benchmark.result.yaml"
        )
        if pointer.benchmark_result.stored_at.path != expected_result_path:
            raise VerificationError(
                "artifact pointer benchmark result is outside the canonical run path"
            )
        if benchmark_result.status != "passed":
            raise VerificationError(
                "artifact pointer benchmark result must have passed"
            )
        if benchmark_result.run != pointer.run:
            raise VerificationError(
                "artifact pointer and benchmark result select different runs"
            )
        if pointer.artifact != verified_run.plan.run.estimator:
            raise VerificationError("benchmark promotion must select the run estimator")

    successful_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == verified_run.result.successful_attempt_id
    )
    producer_stage = next(
        stage
        for stage in successful_attempt.resolved_stages
        if stage.stage_id == pointer.artifact.stage_id
    )
    verified_artifact = verify_snapshot_artifact(
        producer_stage,
        artifact,
        data_role=declaration.data_role,
        fetcher=fetcher,
    )
    if isinstance(producer_spec, ResolvedDownloadSpec):
        verify_download_retrieval(
            successful_attempt,
            verified_run.plan.run,
            producer_spec,
            producer_stage.snapshot,
            pointer.artifact.artifact_name,
            body_raw=verified_artifact.files[0].content,
            fetcher=fetcher,
        )
    if (
        expected_data_role is not None
        and verified_artifact.data_role != expected_data_role
    ):
        raise VerificationError(
            f"selected artifact data_role {verified_artifact.data_role!r} does not "
            f"match stored input data_role {expected_data_role!r}"
        )
    if materialization_path is not None:
        load_verified_artifact(
            verified_run.plan.run,
            declaration,
            pointer.artifact.artifact_name,
            verified_artifact,
            policy=policy,
            materialization_path=materialization_path,
            fetcher=fetcher,
        )
    return verified_artifact


def verify_stored_input_selections(
    stage_id: StageId,
    stage_spec: InternalSpec,
    pointers: Mapping[InputName, ArtifactPointer],
) -> None:
    """Verify relationships among stored pointers consumed by one stage."""
    if isinstance(stage_spec, TrainSpec):
        model_input = stage_spec.inputs.get(keys.Train.MODEL)
        state_input = stage_spec.inputs.get(keys.Train.RESUME_STATE)
        if isinstance(model_input, StoredInputRef) and isinstance(
            state_input,
            StoredInputRef,
        ):
            model_pointer = pointers[keys.Train.MODEL]
            state_pointer = pointers[keys.Train.RESUME_STATE]
            if model_pointer.run != state_pointer.run:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one resolved run"
                )
            if model_pointer.artifact.stage_id != state_pointer.artifact.stage_id:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one producer stage"
                )
            if model_pointer.artifact.artifact_name != keys.Train.MODEL:
                raise VerificationError(
                    f"stored checkpoint model input of stage {stage_id!r} must "
                    "select model"
                )
            if state_pointer.artifact.artifact_name != keys.Train.RESUME_STATE:
                raise VerificationError(
                    f"stored checkpoint state input of stage {stage_id!r} must "
                    "select resume_state"
                )

    if isinstance(stage_spec, EvalSpec):
        model_input = stage_spec.inputs[keys.Eval.MODEL]
        if isinstance(model_input, StoredInputRef):
            model_pointer = pointers[keys.Eval.MODEL]
            if model_pointer.artifact.artifact_name != keys.Train.MODEL:
                raise VerificationError(
                    f"stored eval model input of stage {stage_id!r} must select model"
                )


def verify_stored_inputs(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify every promoted artifact consumed by the resolved stages."""
    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    verified_runs: dict[ResolvedRunRef, VerifiedProducerRun] = {}

    for stage_id, resolved_stage in resolved_stages.items():
        if not isinstance(resolved_stage, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}
        parsed_pointers: dict[InputName, ArtifactPointer] = {}

        for input_name, spec_input in resolved_stage.spec.inputs.items():
            if not isinstance(spec_input, StoredInputRef):
                continue

            resolved_input = resolved_stage.inputs.get(input_name)
            if not isinstance(resolved_input, ResolvedStoredInputRef):
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} has no "
                    "resolved stored-input reference"
                )

            if not pointer_location_matches(
                spec_input.pointer,
                resolved_input.pointer.stored_at,
            ):
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} resolved "
                    "a different pointer location than the stage spec"
                )

            pointer_raw = read_resolved_file(
                resolved_input.pointer,
                fetcher=fetcher,
            )
            try:
                pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} pointer "
                    "is not a valid ArtifactPointer document"
                ) from exc

            parsed_pointers[input_name] = pointer

            if pointer.run not in verified_runs:
                verified_runs[pointer.run] = verify_pointer_producer(
                    pointer,
                    policy=policy,
                    fetcher=fetcher,
                )
            verified_artifact = verify_artifact_in_run(
                pointer,
                verified_run=verified_runs[pointer.run],
                policy=policy,
                expected_data_role=spec_input.data_role,
                materialization_path=spec_input.path,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=spec_input.path,
                data_role=spec_input.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        verify_stored_input_selections(
            stage_id,
            resolved_stage.spec,
            parsed_pointers,
        )

        if stage_inputs:
            verified_inputs[stage_id] = stage_inputs

    return verified_inputs


def verify_attempt_future_inputs(
    attempt: RunAttempt,
    run: RunSpec,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify same-attempt inputs consumed by every completed stage."""
    stage_positions: dict[StageId, int] = {}
    for position, stage_reference in enumerate(run.stages):
        stage_positions[stage_reference.stage_id] = position

    completed_stages = {stage.stage_id: stage for stage in attempt.resolved_stages}

    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    for consumer_stage_id, resolved_consumer_spec in resolved_stages.items():
        # Not checking download specs because they don't have any inputs to verify
        if not isinstance(resolved_consumer_spec, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}

        for input_name, spec_input in resolved_consumer_spec.spec.inputs.items():
            if not isinstance(spec_input, FutureInputRef):
                continue

            resolved_input = resolved_consumer_spec.inputs[input_name]

            if not isinstance(resolved_input, ResolvedFutureInputRef):
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} has no resolved future-input "
                    "reference"
                )

            producer_stage_id = spec_input.producer_stage_id

            if consumer_stage_id not in stage_positions:
                raise VerificationError(
                    f"consumer stage {consumer_stage_id!r} is not in the run plan"
                )

            if producer_stage_id not in stage_positions:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} is not in the run plan"
                )

            if stage_positions[producer_stage_id] >= stage_positions[consumer_stage_id]:
                raise VerificationError(
                    f"future input {input_name!r} must name an earlier stage"
                )

            resolved_producer_spec = resolved_stages.get(producer_stage_id)

            if resolved_producer_spec is None:
                raise VerificationError(
                    f"resolved producer stage {producer_stage_id!r} is missing"
                )

            producer_stage_reference = completed_stages.get(producer_stage_id)
            if producer_stage_reference is None:
                raise VerificationError(
                    f"successful attempt has no resolved stage for "
                    f"{producer_stage_id!r}"
                )

            if resolved_input.producer != producer_stage_reference:
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} does not identify the completed "
                    "producer stage"
                )

            artifact_name = spec_input.name
            artifact = resolved_producer_spec.artifacts.get(artifact_name)
            if artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} has no artifact "
                    f"named {artifact_name!r}"
                )

            declared_artifact = (
                resolved_producer_spec.spec.outputs[artifact_name]
                if artifact_name in resolved_producer_spec.spec.outputs.keys()
                else None
            )
            if declared_artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} did not declare "
                    f"artifact {artifact_name!r}"
                )

            verified_artifact = verify_snapshot_artifact(
                producer_stage_reference,
                artifact,
                data_role=declared_artifact.data_role,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=declared_artifact.path,
                data_role=declared_artifact.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        if stage_inputs:
            verified_inputs[consumer_stage_id] = stage_inputs

    return verified_inputs


def verify_benchmark_result(
    result: BenchmarkResult,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedBenchmarkResult:
    """Verify benchmark parity and metric criteria across two executions."""
    benchmark_raw = read_resolved_file(result.benchmark, fetcher=fetcher)
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(benchmark_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid BenchmarkSpec"
        ) from exc

    run_raw = read_resolved_file(result.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid ResolvedRun"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)

    if result.completed_at < resolved_run.completed_at:
        raise VerificationError(
            "benchmark result cannot precede the selected run completion"
        )

    expected_run_location = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if result.run.stored_at.path != expected_run_location:
        raise VerificationError(
            "benchmark result run reference is outside the canonical run path"
        )

    expected_benchmark_location = storage_file(
        resolved_run.spec.stored_at,
        f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if result.benchmark.stored_at != expected_benchmark_location:
        raise VerificationError(
            "benchmark result reference does not match the immutable run plan"
        )

    if verified_run.plan.benchmark != benchmark:
        raise VerificationError(
            "benchmark result and run plan select different benchmark specs"
        )

    confirmation = read_attempt_reference(
        result.confirmation,
        verified_run.plan.run,
        fetcher=fetcher,
    )
    if confirmation.status != "succeeded":
        raise VerificationError("benchmark confirmation attempt must succeed")
    if confirmation.purpose != "benchmark_confirmation":
        raise VerificationError("benchmark confirmation has the wrong purpose")
    if result.completed_at < confirmation.completed_at:
        raise VerificationError(
            "benchmark result cannot precede confirmation completion"
        )

    selected_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    original_attempt_ids = {attempt.attempt_id for attempt in verified_run.attempts}
    if confirmation.attempt_id in original_attempt_ids:
        raise VerificationError("benchmark confirmation must use a new attempt ID")
    if confirmation.attempt_id <= max(original_attempt_ids):
        raise VerificationError(
            "benchmark confirmation attempt ID must follow the candidate history"
        )

    original_snapshots = {
        snapshot_identity(stage.snapshot)
        for attempt in verified_run.attempts
        for stage in attempt.resolved_stages
    }
    confirmation_snapshots = {
        snapshot_identity(stage.snapshot) for stage in confirmation.resolved_stages
    }
    if original_snapshots & confirmation_snapshots:
        raise VerificationError(
            "benchmark confirmation must use new stage-result snapshots"
        )

    original_attempt_file_snapshots = {
        identity
        for attempt in verified_run.attempts
        for reference in (
            attempt.journal,
            *attempt.measurement_files,
            *attempt.metric_verification_files,
            *attempt.log_files,
        )
        if (identity := artifact_revision_identity(reference.stored_at)) is not None
    }
    confirmation_attempt_file_snapshots = {
        identity
        for reference in (
            confirmation.journal,
            *confirmation.measurement_files,
            *confirmation.metric_verification_files,
            *confirmation.log_files,
        )
        if (identity := artifact_revision_identity(reference.stored_at)) is not None
    }
    if original_attempt_file_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation must use a new measurement and log snapshot"
        )
    if confirmation_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation stage-result and attempt-file snapshots "
            "must be distinct"
        )

    confirmation_stages = verify_attempt_stages(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.stages,
        require_complete=True,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_stored_inputs = verify_stored_inputs(
        confirmation_stages,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_future_inputs = verify_attempt_future_inputs(
        confirmation,
        verified_run.plan.run,
        confirmation_stages,
        fetcher=fetcher,
    )
    confirmation_measurements = verify_attempt_files(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.experiment,
        verified_run.plan.stages,
        fetcher=fetcher,
    )
    verify_measurement_stage_times(
        confirmation_stages,
        confirmation_measurements,
        verified_run.plan.experiment,
    )
    verify_recomputed_metrics(
        confirmation,
        verified_run.plan,
        confirmation_stages,
        confirmation_measurements,
        confirmation_stored_inputs,
        confirmation_future_inputs,
        policy=policy,
        fetcher=fetcher,
    )

    estimator_ref = verified_run.plan.run.estimator
    selected_estimator = verified_run.resolved_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    confirmation_estimator = confirmation_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    estimator_parity = selected_estimator == confirmation_estimator

    eval_stage_ids = [
        stage_id
        for stage_id, stage in verified_run.plan.stages.items()
        if isinstance(stage, EvalSpec)
    ]
    if len(eval_stage_ids) != 1:
        raise VerificationError("benchmark verification requires one eval stage")
    eval_stage_id = eval_stage_ids[0]
    selected_predictions = verified_run.resolved_stages[eval_stage_id].artifacts[
        keys.Eval.PREDICTIONS
    ]
    confirmation_predictions = confirmation_stages[eval_stage_id].artifacts[
        keys.Eval.PREDICTIONS
    ]
    prediction_parity = selected_predictions == confirmation_predictions

    expected_artifacts = {
        (estimator_ref.stage_id, estimator_ref.artifact_name): (
            estimator_ref,
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            selected_estimator,
            confirmation_estimator,
        ),
        (eval_stage_id, keys.Eval.PREDICTIONS): (
            StageArtifactRef(
                stage_id=eval_stage_id,
                artifact_name=keys.Eval.PREDICTIONS,
            ),
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == eval_stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == eval_stage_id
            ),
            selected_predictions,
            confirmation_predictions,
        ),
    }
    received_artifacts = {
        (receipt.artifact.stage_id, receipt.artifact.artifact_name): receipt
        for receipt in result.artifacts
    }
    if set(received_artifacts) != set(expected_artifacts):
        raise VerificationError(
            "benchmark.artifacts: result must compare model and predictions"
        )
    for artifact_key, expected in expected_artifacts.items():
        (
            artifact_ref,
            candidate_stage,
            confirmation_stage,
            candidate,
            confirmed,
        ) = expected
        receipt = received_artifacts[artifact_key]
        expected_candidate_digest = document_digest(candidate)
        expected_confirmation_digest = document_digest(confirmed)
        if (
            receipt.candidate_stage != candidate_stage
            or receipt.confirmation_stage != confirmation_stage
            or receipt.candidate_digest != expected_candidate_digest
            or receipt.confirmation_digest != expected_confirmation_digest
            or receipt.passed
            != (expected_candidate_digest == expected_confirmation_digest)
        ):
            raise VerificationError(
                "benchmark.artifacts: artifact comparison receipt differs"
            )

    def metric_receipts(
        attempt: RunAttempt,
    ) -> dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]]:
        """Load the eval metric receipts owned by one attempt."""
        receipts: dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]] = {}
        for reference in attempt.metric_verification_files:
            raw = read_resolved_file(reference, fetcher=fetcher)
            try:
                receipt = MetricVerificationReceipt.model_validate(
                    parse_yaml_bytes(raw)
                )
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    "benchmark.metrics: metric verification receipt is invalid"
                ) from exc
            if receipt.stage_id != eval_stage_id:
                continue
            receipts[receipt.metric_id] = (reference, receipt)
        return receipts

    candidate_metric_receipts = metric_receipts(selected_attempt)
    confirmation_metric_receipts = metric_receipts(confirmation)
    criteria = {criterion.metric_id: criterion for criterion in benchmark.criteria}
    received_metrics = {receipt.metric_id: receipt for receipt in result.metrics}
    if set(received_metrics) != set(benchmark.metric_ids):
        raise VerificationError(
            "benchmark.metrics: result metric IDs differ from the benchmark"
        )
    criteria_pass = True
    metrics_match = True
    for metric_id in benchmark.metric_ids:
        if (
            metric_id not in candidate_metric_receipts
            or metric_id not in confirmation_metric_receipts
        ):
            raise VerificationError(
                f"benchmark.metrics: metric {metric_id!r} lacks verification evidence"
            )
        candidate_ref, candidate_receipt = candidate_metric_receipts[metric_id]
        confirmation_ref, confirmation_receipt = confirmation_metric_receipts[metric_id]
        if candidate_receipt.comparator != confirmation_receipt.comparator:
            raise VerificationError(
                "benchmark.metrics: candidate and confirmation comparators differ"
            )
        candidate_value = candidate_receipt.recomputation.value
        confirmation_value = confirmation_receipt.recomputation.value
        matched = compare_metric_values(
            candidate_value,
            confirmation_value,
            candidate_receipt.comparator,
        )
        receipt = received_metrics[metric_id]
        if (
            not candidate_receipt.passed
            or not confirmation_receipt.passed
            or receipt.candidate_verification != candidate_ref
            or receipt.confirmation_verification != confirmation_ref
            or receipt.candidate_value != candidate_value
            or receipt.confirmation_value != confirmation_value
            or receipt.matched != matched
        ):
            raise VerificationError("benchmark.metrics: metric result differs")
        metrics_match &= matched

        criterion = criteria.get(metric_id)
        if criterion is None:
            if receipt.criterion is not None:
                raise VerificationError(
                    "benchmark.metrics: metric has an undeclared criterion result"
                )
            continue
        candidate_passed = (
            candidate_value >= criterion.threshold
            if criterion.comparison == "ge"
            else candidate_value <= criterion.threshold
        )
        confirmation_passed = (
            confirmation_value >= criterion.threshold
            if criterion.comparison == "ge"
            else confirmation_value <= criterion.threshold
        )
        criterion_passed = candidate_passed and confirmation_passed
        if (
            receipt.criterion is None
            or receipt.criterion.criterion != criterion
            or receipt.criterion.candidate_passed != candidate_passed
            or receipt.criterion.confirmation_passed != confirmation_passed
            or receipt.criterion.passed != criterion_passed
        ):
            raise VerificationError(
                "benchmark.metrics: metric criterion result differs"
            )
        criteria_pass &= criterion_passed

    passed = estimator_parity and prediction_parity and metrics_match and criteria_pass
    expected_status = (
        "failed" if not passed else "verified" if not benchmark.criteria else "passed"
    )
    if result.status != expected_status:
        raise VerificationError(
            "benchmark result status does not match parity and metric checks"
        )

    return VerifiedBenchmarkResult(
        result=result,
        run=verified_run,
        confirmation=confirmation,
        confirmation_stages=confirmation_stages,
        confirmation_measurements=confirmation_measurements,
    )


def _stored_locations(value: object) -> tuple[object, ...]:
    """Collect storage references from one nested protocol record."""
    if isinstance(
        value,
        (
            GitFileRef,
            LocalFileRef,
            LocalStageResultSnapshotRef,
            ViperCloudFileRef,
            ViperCloudStageResultSnapshotRef,
        ),
    ):
        return (value,)
    if isinstance(value, BaseModel):
        return tuple(
            location
            for field in value.__dict__.values()
            for location in _stored_locations(field)
        )
    if isinstance(value, Mapping):
        return tuple(
            location for item in value.values() for location in _stored_locations(item)
        )
    if isinstance(value, (tuple, list)):
        return tuple(location for item in value for location in _stored_locations(item))
    return ()


def _verify_cloud_graph(resolved_run: ResolvedRun) -> None:
    """Reject local immutable references in a cloud-backed terminal run."""
    locations = _stored_locations(resolved_run)
    cloud = any(
        isinstance(
            location,
            (ViperCloudFileRef, ViperCloudStageResultSnapshotRef),
        )
        for location in locations
    )
    local = any(
        isinstance(location, (LocalFileRef, LocalStageResultSnapshotRef))
        for location in locations
    )
    if cloud and local:
        raise VerificationError("storage_graph_unreachable")


def _verify_run_result(
    resolved_run: ResolvedRun,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
    ancestors: frozenset[str],
) -> VerifiedRunResult:
    """Verify one run while retaining the reuse chain already visited."""
    _verify_cloud_graph(resolved_run)
    plan = verify_run_plan(resolved_run, fetcher=fetcher)
    _verify_benchmark_plan_pointers(plan, policy=policy, fetcher=fetcher)
    attempts = verify_run_attempt_references(
        resolved_run,
        plan.run,
        fetcher=fetcher,
    )
    all_measurements: list[Measurement] = []
    measurement_references: list[ResolvedFileRef] = []
    successful_stages: dict[StageId, ResolvedBaseSpec] = {}
    successful_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    attempt_stages: dict[int, dict[StageId, ResolvedBaseSpec]] = {}
    all_attempt_inputs: dict[int, dict[StageId, dict[InputName, VerifiedInput]]] = {}
    stage_result_snapshots: set[tuple[str, ...]] = set()
    attempt_file_snapshots: set[tuple[str, ...]] = set()

    for attempt in attempts:
        current_stage_result_snapshots = {
            snapshot_identity(stage.snapshot) for stage in attempt.resolved_stages
        }
        if stage_result_snapshots & current_stage_result_snapshots:
            raise VerificationError(
                "run attempts must use distinct stage-result snapshots"
            )
        stage_result_snapshots.update(current_stage_result_snapshots)

        current_attempt_file_snapshots = {
            identity
            for reference in (
                attempt.journal,
                *attempt.measurement_files,
                *attempt.metric_verification_files,
                *attempt.log_files,
            )
            if (identity := artifact_revision_identity(reference.stored_at)) is not None
        }
        if attempt_file_snapshots & current_attempt_file_snapshots:
            raise VerificationError(
                "run attempts must use distinct measurement and log snapshots"
            )
        attempt_file_snapshots.update(current_attempt_file_snapshots)

    if stage_result_snapshots & attempt_file_snapshots:
        raise VerificationError(
            "stage-result and attempt-file snapshots must be distinct"
        )

    for attempt in attempts:
        complete = attempt.status == "succeeded"
        verify_attempt_journal(attempt, plan.run, fetcher=fetcher)
        verified_stages = verify_attempt_stages(
            attempt,
            plan.run,
            plan.stages,
            require_complete=complete,
            policy=policy,
            fetcher=fetcher,
        )
        stored_inputs = verify_stored_inputs(
            verified_stages,
            policy=policy,
            fetcher=fetcher,
        )
        future_inputs = verify_attempt_future_inputs(
            attempt,
            plan.run,
            verified_stages,
            fetcher=fetcher,
        )
        external_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
        stage_references = {item.stage_id: item for item in attempt.resolved_stages}
        for stage_id, resolved_stage in verified_stages.items():
            if not isinstance(resolved_stage, ResolvedInternalSpec):
                continue
            verified_external = verify_external_inputs(
                attempt,
                plan.run,
                stage_id,
                resolved_stage,
                stage_references[stage_id].snapshot,
                fetcher=fetcher,
            )
            if verified_external:
                external_inputs[stage_id] = verified_external
        current_inputs = _merge_stage_inputs(
            stored_inputs,
            future_inputs,
            external_inputs,
        )
        for stage_id, resolved_stage in verified_stages.items():
            if (
                not isinstance(resolved_stage, ResolvedInternalSpec)
                or resolved_stage.spec.input_roots != "download"
            ):
                continue
            rebuilt_closure = verify_download_source_closure(
                stage_id,
                resolved_stage.spec,
                run=plan.run,
                attempt_id=attempt.attempt_id,
                resolved_inputs=resolved_stage.inputs,
                stage_specs=plan.stages,
                completed_stages=stage_references,
                completed_results=verified_stages,
                policy=policy,
                fetcher=fetcher,
            )
            if rebuilt_closure != resolved_stage.download_source_closure:
                raise VerificationError(
                    f"stage {stage_id!r} download source closure receipt differs"
                )
        attempt_stages[attempt.attempt_id] = verified_stages
        all_attempt_inputs[attempt.attempt_id] = current_inputs
        attempt_measurements = verify_attempt_files(
            attempt,
            plan.run,
            plan.experiment,
            plan.stages,
            fetcher=fetcher,
            measurement_references=measurement_references,
        )
        verify_measurement_stage_times(
            verified_stages,
            attempt_measurements,
            plan.experiment,
        )
        verify_recomputed_metrics(
            attempt,
            plan,
            verified_stages,
            attempt_measurements,
            stored_inputs,
            future_inputs,
            policy=policy,
            fetcher=fetcher,
        )
        all_measurements.extend(attempt_measurements)
        if attempt.attempt_id == resolved_run.successful_attempt_id:
            successful_stages = verified_stages
            successful_inputs = current_inputs

    if resolved_run.status == "succeeded":
        estimator_stage = successful_stages.get(plan.run.estimator.stage_id)
        if estimator_stage is None:
            raise VerificationError("successful run has no estimator-producing stage")
        if plan.run.estimator.artifact_name not in estimator_stage.artifacts:
            raise VerificationError("successful run has no selected estimator artifact")

    attempt_reuse = _verify_reused_stages(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        stages=attempt_stages,
        inputs=all_attempt_inputs,
        policy=policy,
        fetcher=fetcher,
        ancestors=ancestors,
    )
    reuse = (
        attempt_reuse.get(resolved_run.successful_attempt_id, {})
        if resolved_run.successful_attempt_id is not None
        else {}
    )

    return VerifiedRunResult(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        resolved_stages=successful_stages,
        measurements=tuple(all_measurements),
        measurement_references=tuple(measurement_references),
        inputs=successful_inputs,
        reuse=reuse,
        attempt_stages=attempt_stages,
        attempt_inputs=all_attempt_inputs,
        attempt_reuse=attempt_reuse,
    )
