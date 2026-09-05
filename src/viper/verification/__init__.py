"""Verify connected VIPER provenance records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import yaml
from pydantic import BaseModel

from .._schema import (
    PARAMETERS,
    PARAMETERS_INPUT,
    PREDICTIONS,
    RESUME_STATE,
    RESUME_STATE_INPUT,
    DataRole,
    RepoRelPath,
)
from .._verification import attempt as _attempt
from .._verification import metrics as _metrics
from .._verification import paths as _paths
from .._verification import plan as _plan
from .._verification import storage as _storage
from ..artifacts import (
    ArtifactPointer,
    ResolvedBundleArtifact,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from ..benchmark import BenchmarkResult, BenchmarkSpec
from ..ids import InputName, MetricId, StageId
from ..inputs import (
    FutureInputRef,
    ResolvedFutureInputRef,
    ResolvedStoredInputRef,
    StoredInputRef,
)
from ..metrics import Measurement, MetricVerificationReceipt, compare_metric_values
from ..references import (
    GitFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedStageRef,
    SnapshotFileRef,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from ..runs import ResolvedRun, RunAttempt, RunSpec
from ..serialization import document_digest, parse_yaml_bytes
from ..stages import (
    EvalSpec,
    InternalSpec,
    ParameterizedSpec,
    ResolvedBaseSpec,
    ResolvedInternalSpec,
    ResolvedParameterizedSpec,
    TrainSpec,
)
from .models import (
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedBenchmarkResult,
    VerifiedInput,
    VerifiedRunPlan,
    VerifiedRunResult,
)
from ..reuse import (
    ReusedStageCompletion,
    ReuseInputIdentity,
    StageReuseKey,
    StageReuseReceipt,
    build_stage_reuse_key,
    verified_input_identity,
)


__all__ = [
    "verify_attempt_future_inputs",
    "verify_benchmark_result",
    "verify_promoted_artifact",
    "verify_run_result",
    "verify_stage_reuse",
    "verify_stored_input_selections",
    "verify_stored_inputs",
]


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
    if not isinstance(stage, ParameterizedSpec):
        raise VerificationError("stage reuse requires a parameterized stage")
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
    if source.result.status != "succeeded":
        raise VerificationError("reused source run did not succeed")
    expected_source_path = f"{_paths.run_root(source.plan.run)}/resolved.yaml"
    if source_reference.stored_at.path != expected_source_path:
        raise VerificationError("reuse receipt source run path differs")

    try:
        attempt_index = next(
            index
            for index, attempt in enumerate(source.attempts)
            if attempt.attempt_id == source.result.successful_attempt_id
        )
    except StopIteration as exc:
        raise VerificationError("reused source run has no successful attempt") from exc
    source_attempt = source.attempts[attempt_index]
    if receipt.source_attempt != source.result.attempts[attempt_index]:
        raise VerificationError("reuse receipt selects a different source attempt")

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
    source_result = source.resolved_stages.get(receipt.stage_id)
    if source_result is None:
        raise VerificationError("reused source stage has no verified result")
    if isinstance(getattr(source_result, "completion", None), ReusedStageCompletion):
        raise VerificationError("a reused stage cannot be another reuse source")

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
            if metric.mode == "recompute"
            else None
        )
        if metric.mode == "recompute" and expected_verification is None:
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
    stages: Mapping[StageId, ResolvedBaseSpec],
    inputs: Mapping[StageId, Mapping[InputName, VerifiedInput]],
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None,
    ancestors: frozenset[str],
) -> dict[StageId, StageReuseReceipt]:
    """Follow and verify each reuse receipt in the successful attempt."""
    if result.successful_attempt_id is None:
        return {}
    attempt = next(
        item for item in attempts if item.attempt_id == result.successful_attempt_id
    )
    receipts: dict[StageId, StageReuseReceipt] = {}
    for stage_reference in attempt.resolved_stages:
        target = stages[stage_reference.stage_id]
        if not isinstance(target, ResolvedParameterizedSpec) or not isinstance(
            target.completion, ReusedStageCompletion
        ):
            continue
        raw = _storage.read_resolved_file(target.completion.receipt, fetcher=fetcher)
        try:
            receipt = StageReuseReceipt.model_validate(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError("stage reuse receipt is invalid") from exc
        source_id = receipt.source_run.sha256
        if source_id in ancestors:
            raise VerificationError("stage reuse sources form a cycle")
        source_raw = _storage.read_resolved_file(receipt.source_run, fetcher=fetcher)
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
        verify_stage_reuse(
            receipt,
            source_reference=receipt.source_run,
            source=source,
            source_inputs=_input_identities(
                source.inputs.get(stage_reference.stage_id, {})
            ),
            target_plan=plan,
            target_stage=stage_reference,
            target_result=target,
            target_inputs=_input_identities(inputs.get(stage_reference.stage_id, {})),
        )
        receipts[stage_reference.stage_id] = receipt
    return receipts

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
    resolved_run_raw = _storage.read_resolved_file(pointer.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(resolved_run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "artifact pointer run is not a valid ResolvedRun document"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
    expected_run_path = f"{_paths.run_root(verified_run.plan.run)}/resolved.yaml"
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
    declaration = producer_spec.spec.artifacts[pointer.artifact.artifact_name]

    if pointer.benchmark_result is not None:
        benchmark_result_raw = _storage.read_resolved_file(
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
            f"{_paths.run_root(verified_run.plan.run)}/benchmark.result.yaml"
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
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    producer_stage = next(
        stage
        for stage in successful_attempt.resolved_stages
        if stage.stage_id == pointer.artifact.stage_id
    )
    verified_artifact = _storage.verify_snapshot_artifact(
        producer_stage,
        artifact,
        data_role=declaration.data_role,
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
        _storage.load_verified_artifact(
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
        model_input = stage_spec.inputs.get(PARAMETERS_INPUT)
        state_input = stage_spec.inputs.get(RESUME_STATE_INPUT)
        if isinstance(model_input, StoredInputRef) and isinstance(
            state_input,
            StoredInputRef,
        ):
            model_pointer = pointers[PARAMETERS_INPUT]
            state_pointer = pointers[RESUME_STATE_INPUT]
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
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored checkpoint model input of stage {stage_id!r} must "
                    "select parameters"
                )
            if state_pointer.artifact.artifact_name != RESUME_STATE:
                raise VerificationError(
                    f"stored checkpoint state input of stage {stage_id!r} must "
                    "select resume_state"
                )

    if isinstance(stage_spec, EvalSpec):
        model_input = stage_spec.inputs[PARAMETERS_INPUT]
        if isinstance(model_input, StoredInputRef):
            model_pointer = pointers[PARAMETERS_INPUT]
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored eval model input of stage {stage_id!r} must "
                    "select parameters"
                )


def verify_stored_inputs(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify every promoted artifact consumed by the resolved stages."""
    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}

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

            if resolved_input.pointer.stored_at != spec_input.pointer:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} resolved "
                    "a different pointer location than the stage spec"
                )

            pointer_raw = _storage.read_resolved_file(
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

            verified_artifact = verify_promoted_artifact(
                pointer,
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

            declared_artifact = resolved_producer_spec.spec.artifacts.get(artifact_name)
            if declared_artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} did not declare "
                    f"artifact {artifact_name!r}"
                )

            verified_artifact = _storage.verify_snapshot_artifact(
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
    benchmark_raw = _storage.read_resolved_file(result.benchmark, fetcher=fetcher)
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(benchmark_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid BenchmarkSpec"
        ) from exc

    run_raw = _storage.read_resolved_file(result.run, fetcher=fetcher)
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

    expected_run_location = f"{_paths.run_root(verified_run.plan.run)}/resolved.yaml"
    if result.run.stored_at.path != expected_run_location:
        raise VerificationError(
            "benchmark result run reference is outside the canonical run path"
        )

    expected_benchmark_location = GitFileRef(
        repository=verified_run.plan.run.source.repository,
        commit=verified_run.plan.run.source.commit,
        path=f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if result.benchmark.stored_at != expected_benchmark_location:
        raise VerificationError(
            "benchmark result reference does not match the run source snapshot"
        )

    if verified_run.plan.benchmark != benchmark:
        raise VerificationError(
            "benchmark result and run plan select different benchmark specs"
        )

    confirmation = _storage.read_attempt_reference(
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
        _storage.snapshot_identity(stage.snapshot)
        for attempt in verified_run.attempts
        for stage in attempt.resolved_stages
    }
    confirmation_snapshots = {
        _storage.snapshot_identity(stage.snapshot)
        for stage in confirmation.resolved_stages
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
        if (identity := _storage.artifact_revision_identity(reference.stored_at))
        is not None
    }
    confirmation_attempt_file_snapshots = {
        identity
        for reference in (
            confirmation.journal,
            *confirmation.measurement_files,
            *confirmation.metric_verification_files,
            *confirmation.log_files,
        )
        if (identity := _storage.artifact_revision_identity(reference.stored_at))
        is not None
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

    confirmation_stages = _attempt.verify_attempt_stages(
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
    confirmation_measurements = _attempt.verify_attempt_files(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.experiment,
        verified_run.plan.stages,
        fetcher=fetcher,
    )
    _attempt.verify_measurement_stage_times(
        confirmation_stages,
        confirmation_measurements,
        verified_run.plan.experiment,
    )
    _metrics.verify_recomputed_metrics(
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
        PREDICTIONS
    ]
    confirmation_predictions = confirmation_stages[eval_stage_id].artifacts[PREDICTIONS]
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
        (eval_stage_id, PREDICTIONS): (
            StageArtifactRef(
                stage_id=eval_stage_id,
                artifact_name=PREDICTIONS,
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
            "benchmark.artifacts: result must compare parameters and predictions"
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
            raw = _storage.read_resolved_file(reference, fetcher=fetcher)
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
    plan = _plan.verify_run_plan(resolved_run, fetcher=fetcher)
    attempts = _storage.verify_run_attempt_references(
        resolved_run,
        plan.run,
        fetcher=fetcher,
    )
    all_measurements: list[Measurement] = []
    successful_stages: dict[StageId, ResolvedBaseSpec] = {}
    successful_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    stage_result_snapshots: set[tuple[str, ...]] = set()
    attempt_file_snapshots: set[tuple[str, ...]] = set()

    for attempt in attempts:
        current_stage_result_snapshots = {
            _storage.snapshot_identity(stage.snapshot)
            for stage in attempt.resolved_stages
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
            if (identity := _storage.artifact_revision_identity(reference.stored_at))
            is not None
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
        _attempt.verify_attempt_journal(attempt, plan.run, fetcher=fetcher)
        verified_stages = _attempt.verify_attempt_stages(
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
            verified_external = _attempt.verify_external_inputs(
                attempt,
                plan.run,
                stage_id,
                resolved_stage,
                stage_references[stage_id].snapshot,
                fetcher=fetcher,
            )
            if verified_external:
                external_inputs[stage_id] = verified_external
        attempt_inputs = _merge_stage_inputs(
            stored_inputs,
            future_inputs,
            external_inputs,
        )
        attempt_measurements = _attempt.verify_attempt_files(
            attempt,
            plan.run,
            plan.experiment,
            plan.stages,
            fetcher=fetcher,
        )
        _attempt.verify_measurement_stage_times(
            verified_stages,
            attempt_measurements,
            plan.experiment,
        )
        _metrics.verify_recomputed_metrics(
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
            successful_inputs = attempt_inputs

    if resolved_run.status == "succeeded":
        estimator_stage = successful_stages.get(plan.run.estimator.stage_id)
        if estimator_stage is None:
            raise VerificationError("successful run has no estimator-producing stage")
        if plan.run.estimator.artifact_name not in estimator_stage.artifacts:
            raise VerificationError("successful run has no selected estimator artifact")

    reuse = _verify_reused_stages(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        stages=successful_stages,
        inputs=successful_inputs,
        policy=policy,
        fetcher=fetcher,
        ancestors=ancestors,
    )

    return VerifiedRunResult(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        resolved_stages=successful_stages,
        measurements=tuple(all_measurements),
        inputs=successful_inputs,
        reuse=reuse,
    )
