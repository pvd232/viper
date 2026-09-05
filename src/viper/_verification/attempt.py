"""Verify stage execution and durable evidence for one run attempt."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import cast

import yaml
from pydantic import TypeAdapter

from viper.workspace import captured_input_path

from .._parameter.validation import (
    ParameterValidationError,
    verify_parameter_model_bytes,
)
from .._schema import RepoRelPath, repo_file_paths_overlap
from ..experiments import ExperimentSpec
from ..http import (
    HttpRetrievalError,
    ProjectHttpImplementationSpec,
    validate_request_policy,
)
from ..ids import InputName, StageId
from ..inputs import ExternalInputRef, FutureInputRef, ResolvedExternalInputRef
from ..journal import parse_journal_bytes
from ..metrics import Measurement
from ..references import (
    GitFileRef,
    HuggingFaceFileRef,
    LocalFileRef,
    ResolvedStageInvocationRef,
    StageResultSnapshot,
)
from ..runs import RunAttempt, RunSpec
from ..runtime import (
    ComputeBackendContext,
    ComputeSpec,
    CPUBackendContext,
    CUDABackendContext,
    EnvSpec,
    ExecutionContext,
    GCEEnvSpec,
    GCEHostContext,
    LocalHostContext,
    ResolvedEnv,
    ResolvedGCEEnv,
    process_environment,
)
from ..serialization import document_digest, parse_yaml_bytes
from ..stages import (
    BaseSpec,
    EvalSpec,
    InternalSpec,
    ParameterizedSpec,
    ParameterizedStageSpec,
    ResolvedBaseSpec,
    ResolvedDownloadSpec,
    ResolvedInternalSpec,
    ResolvedParameterizedSpec,
    ResolvedSpec,
    StageContextBinding,
    StageInvocationReceipt,
)
from ..verification.models import VerificationError, VerificationPolicy
from .paths import (
    resolved_stage_spec_path,
    run_root,
    stage_invocation_path,
)
from .storage import (
    StorageFetcher,
    artifact_revision_identity,
    fetch_storage_bytes,
    load_verified_artifact,
    read_resolved_file,
    read_snapshot_file,
    verify_snapshot_artifact,
)

RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Construct one JSON object while rejecting duplicate field names."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _logical_input_paths(
    run: RunSpec,
    attempt_id: int,
    stage_id: StageId,
    stage: BaseSpec,
    stage_specs: Mapping[StageId, BaseSpec],
) -> dict[InputName, RepoRelPath]:
    """Reconstruct the repository-relative input paths delivered to one stage."""
    if not isinstance(stage, InternalSpec):
        return {}
    paths: dict[InputName, RepoRelPath] = {}
    for name, reference in stage.inputs.items():
        if isinstance(reference, FutureInputRef):
            producer = stage_specs[reference.producer_stage_id]
            paths[name] = producer.artifacts[reference.name].path
        elif isinstance(reference, ExternalInputRef):
            paths[name] = captured_input_path(
                run_id=run.run_id,
                attempt_id=attempt_id,
                stage_id=stage_id,
                input_name=name,
                source_path=reference.source.path,
            )
        else:
            paths[name] = reference.path

    return paths


def _verify_effective_env(
    stage_id: StageId,
    requested: EnvSpec,
    resolved: ResolvedEnv,
    context: ExecutionContext,
) -> None:
    """Join the frozen env to its resolved and observed evidence."""
    if resolved.kind != requested.kind:
        raise VerificationError(
            f"env.kind: stage {stage_id!r} realized another host kind"
        )
    if resolved.compute != requested.compute:
        raise VerificationError(
            f"env.compute: stage {stage_id!r} realized another compute request"
        )
    if resolved.lockfile.stored_at != requested.lockfile:
        raise VerificationError(
            f"env.lockfile: stage {stage_id!r} resolved another lockfile"
        )
    if resolved.python_env != requested.python_env:
        raise VerificationError(
            f"env.python: stage {stage_id!r} observed another Python env"
        )
    if context.host.provider != requested.kind:
        raise VerificationError(
            f"env.host: stage {stage_id!r} ran on another host kind"
        )
    if isinstance(requested, GCEEnvSpec):
        if not isinstance(resolved, ResolvedGCEEnv):
            raise VerificationError(f"gce.env: stage {stage_id!r} omitted its GCE env")
        if not isinstance(context.host, GCEHostContext):
            raise VerificationError(
                f"gce.host: stage {stage_id!r} omitted its GCE host evidence"
            )
        if (
            resolved.provisioning != requested.provisioning
            or context.host.provisioning != requested.provisioning
        ):
            raise VerificationError(
                f"gce.provisioning: stage {stage_id!r} used another provisioning source"
            )
        if (
            resolved.machine_type != requested.machine_type
            or context.host.machine_type != requested.machine_type
        ):
            raise VerificationError(
                f"gce.machine_type: stage {stage_id!r} used another machine type"
            )
    elif not isinstance(context.host, LocalHostContext):
        raise VerificationError(
            f"env.host: stage {stage_id!r} omitted its local host evidence"
        )
    _verify_startup_backend(stage_id, requested.compute, context.backend)


def _verify_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    resolved_stage: ResolvedParameterizedSpec,
    fetcher: StorageFetcher | None,
) -> StageInvocationReceipt:
    """Verify one invocation receipt against its plan, context, and startup facts."""
    if reference.stored_at.path != stage_invocation_path(
        run, attempt.attempt_id, stage_id
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is outside its canonical path"
        )
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(
            run,
            attempt.attempt_id,
            stage_id,
            stage,
            stage_specs,
        ),
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    expected_digest = document_digest(expected_binding)
    if receipt.context_digest != expected_digest:
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    if receipt.outcome != "succeeded":
        raise VerificationError(
            f"resolved stage {stage_id!r} requires a successful invocation"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= resolved_stage.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its stage"
        )

    startup = resolved_stage.startup
    if startup.reproducibility != run.reproducibility:
        raise VerificationError(
            f"stage {stage_id!r} startup controls differ from the run plan"
        )
    compute = (stage.env or run.env).compute
    recorded_cuda = startup.env.get("CUDA_VISIBLE_DEVICES")
    if compute.kind == "cuda":
        if recorded_cuda is None or not recorded_cuda.isdigit():
            raise VerificationError(
                f"stage {stage_id!r} startup omitted its selected CUDA device"
            )
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
            cuda_ordinal=int(recorded_cuda),
        )
    else:
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
        )
    if startup.env != expected_environment:
        raise VerificationError(f"stage {stage_id!r} startup env differs from the plan")
    _verify_startup_backend(
        stage_id,
        compute,
        resolved_stage.execution_context.backend,
    )

    generators = startup.generators
    if any(generator.seed != run.seed for generator in generators):
        raise VerificationError(
            f"stage {stage_id!r} generator receipt uses a different seed"
        )
    family_counts = Counter(generator.family for generator in generators)
    if family_counts["python"] != 1 or family_counts["torch_cpu"] != 1:
        raise VerificationError(
            f"stage {stage_id!r} startup requires one Python and one CPU Torch "
            "generator receipt"
        )
    configured_names = set(expected_binding.numpy_generator_names)
    received_names = {
        generator.name
        for generator in generators
        if generator.family == "numpy_generator"
    }
    if received_names != configured_names:
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts differ"
        )
    if family_counts["numpy_generator"] != len(configured_names):
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts are duplicated"
        )
    legacy_count = sum(generator.family == "numpy_legacy" for generator in generators)
    if legacy_count != int(run.reproducibility.numpy_randomness.capture_legacy_global):
        raise VerificationError(
            f"stage {stage_id!r} legacy NumPy generator receipt differs"
        )
    cuda_receipts = tuple(
        generator for generator in generators if generator.family == "torch_cuda"
    )
    if compute.kind == "cpu" and cuda_receipts:
        raise VerificationError(
            f"stage {stage_id!r} CPU startup includes a CUDA generator receipt"
        )
    if compute.kind == "cuda" and (
        len(cuda_receipts) != 1 or cuda_receipts[0].device_index != 0
    ):
        raise VerificationError(
            f"stage {stage_id!r} CUDA startup requires one visible-device receipt"
        )
    return receipt


def _verify_startup_backend(
    stage_id: StageId,
    compute: ComputeSpec,
    backend: ComputeBackendContext,
) -> None:
    """Apply the named startup.backend rule to observed stage evidence."""
    if compute.kind != backend.kind:
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another backend kind"
        )
    if compute.kind == "cpu":
        if not isinstance(backend, CPUBackendContext):
            raise VerificationError(
                f"startup.backend: stage {stage_id!r} omitted its CPU context"
            )
        return
    if not isinstance(backend, CUDABackendContext):
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} omitted its CUDA context"
        )
    if len(backend.gpu_devices) != compute.count:
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another CUDA device count"
        )
    if any(device.model != compute.model for device in backend.gpu_devices):
        raise VerificationError(
            f"startup.backend: stage {stage_id!r} observed another CUDA model"
        )


def _verify_unresolved_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: StorageFetcher | None,
) -> None:
    """Verify the terminal receipt for a started stage that did not resolve."""
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(
            run, attempt.attempt_id, stage_id, stage, stage_specs
        ),
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    if receipt.context_digest != document_digest(expected_binding):
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    allowed_outcomes = (
        {"succeeded", "failed"} if attempt.status == "failed" else {attempt.status}
    )
    if receipt.outcome not in allowed_outcomes:
        raise VerificationError(
            f"stage {stage_id!r} invocation outcome differs from its attempt"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= attempt.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its attempt"
        )


def _verify_download_retrievals(
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    resolved: ResolvedDownloadSpec,
    snapshot: StageResultSnapshot,
    *,
    fetcher: StorageFetcher | None,
) -> None:
    """Verify each HTTP request, response, implementation, and artifact body."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    for input_name, retrieval in resolved.retrievals.items():
        try:
            validate_request_policy(retrieval.request, resolved.spec.policy)
            terminal_request = retrieval.request.model_copy(
                update={"url": retrieval.response.response_url}
            )
            validate_request_policy(terminal_request, resolved.spec.policy)
        except HttpRetrievalError as exc:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} violates its frozen policy"
            ) from exc
        if retrieval.response.status not in resolved.spec.policy.accepted_statuses:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} has an unaccepted status"
            )
        expected_path = resolved.spec.artifacts[input_name].path
        if retrieval.body.path != expected_path:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body uses another path"
            )
        body_raw = read_snapshot_file(
            snapshot,
            retrieval.body,
            fetcher=fetcher,
        )
        artifact = resolved.artifacts[input_name]
        if artifact.kind != "file" or artifact.file != retrieval.body:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} differs from its artifact"
            )
        if (
            hashlib.sha256(body_raw).hexdigest()
            != retrieval.request.expected_body_sha256
            or len(body_raw) != retrieval.request.expected_body_bytes
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body differs from its request"
            )
        if not (
            attempt.started_at
            <= retrieval.started_at
            < retrieval.completed_at
            <= resolved.completed_at
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} timing falls outside its stage"
            )

        http = retrieval.http
        if isinstance(http.spec, ProjectHttpImplementationSpec):
            implementation = http.spec.implementation
            implementation_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=implementation.path,
                )
            )
            if (
                len(implementation_raw) != implementation.bytes
                or hashlib.sha256(implementation_raw).hexdigest()
                != implementation.sha256
            ):
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} implementation source differs"
                )
            parameter_reference = http.spec.parameter_model
            parameter_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=parameter_reference.path,
                )
            )
            try:
                verify_parameter_model_bytes(parameter_reference, parameter_raw)
            except ParameterValidationError as exc:
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} HTTP parameter model differs"
                ) from exc
            for executable in http.external_executables:
                try:
                    executable_raw = executable.path.read_bytes()
                except OSError as exc:
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable is unavailable"
                    ) from exc
                if (
                    len(executable_raw) != executable.spec.bytes
                    or hashlib.sha256(executable_raw).hexdigest()
                    != executable.spec.sha256
                ):
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable identity differs"
                    )


def verify_attempt_stages(
    attempt: RunAttempt,
    run: RunSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    require_complete: bool,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, ResolvedBaseSpec]:
    """Verify the ordered resolved-stage prefix retained by one attempt."""
    expected_stage_ids = tuple(stage.stage_id for stage in run.stages)
    resolved_stage_ids = tuple(stage.stage_id for stage in attempt.resolved_stages)
    if resolved_stage_ids != expected_stage_ids[: len(resolved_stage_ids)]:
        raise VerificationError(
            "attempt resolved stages must form an ordered run-stage prefix"
        )
    if require_complete and resolved_stage_ids != expected_stage_ids:
        raise VerificationError("successful attempt must contain every run stage")

    if set(stage_specs) != set(expected_stage_ids):
        raise VerificationError("loaded stage specs do not match the run stage plan")
    resolved_parameterized_ids = tuple(
        stage_id
        for stage_id in resolved_stage_ids
        if isinstance(stage_specs[stage_id], ParameterizedSpec)
    )
    planned_parameterized_ids = tuple(
        stage_id
        for stage_id in expected_stage_ids
        if isinstance(stage_specs[stage_id], ParameterizedSpec)
    )
    if len(attempt.invocations) < len(resolved_parameterized_ids):
        raise VerificationError(
            "attempt must retain an invocation receipt for every project stage"
        )
    if len(attempt.invocations) > len(planned_parameterized_ids):
        raise VerificationError("attempt contains more invocations than planned stages")
    if len(attempt.invocations) > len(resolved_parameterized_ids) + 1:
        raise VerificationError(
            "attempt contains invocations after its unresolved active stage"
        )
    for index, invocation in enumerate(attempt.invocations):
        expected_path = stage_invocation_path(
            run,
            attempt.attempt_id,
            planned_parameterized_ids[index],
        )
        if invocation.stored_at.path != expected_path:
            raise VerificationError(
                "attempt invocation receipts must follow planned stage order"
            )

    verified_stages: dict[StageId, ResolvedBaseSpec] = {}

    for stage_index, stage_reference in enumerate(attempt.resolved_stages):
        expected_resolved_path = resolved_stage_spec_path(
            run,
            stage_reference.stage_id,
        )
        if stage_reference.resolved_spec.path != expected_resolved_path:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} resolved spec is outside "
                "its canonical run path"
            )

        raw = read_snapshot_file(
            stage_reference.snapshot,
            stage_reference.resolved_spec,
            fetcher=fetcher,
        )
        try:
            resolved_spec = RESOLVED_SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} file is not a valid "
                "resolved stage spec"
            ) from exc

        stage_spec = stage_specs[stage_reference.stage_id]

        for artifact_name, artifact_spec in stage_spec.artifacts.items():
            if repo_file_paths_overlap(
                stage_reference.resolved_spec.path,
                artifact_spec.path,
            ):
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} resolved spec collides "
                    f"with artifact {artifact_name!r}"
                )

        if resolved_spec.spec != stage_spec:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} does not embed its stage spec"
            )

        if isinstance(stage_spec, ParameterizedSpec):
            if not isinstance(resolved_spec, ResolvedParameterizedSpec):
                raise VerificationError("project stage omitted invocation evidence")
            invocation_index = resolved_parameterized_ids.index(
                stage_reference.stage_id
            )
            invocation_reference = attempt.invocations[invocation_index]
            if resolved_spec.invocation != invocation_reference:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} invocation reference differs "
                    "from its attempt"
                )
            _verify_stage_invocation(
                invocation_reference,
                attempt=attempt,
                run=run,
                stage_id=stage_reference.stage_id,
                stage=cast(ParameterizedStageSpec, stage_spec),
                stage_specs=stage_specs,
                resolved_stage=resolved_spec,
                fetcher=fetcher,
            )

            source_location = resolved_spec.source.stored_at
            if (
                source_location.repository != run.source.repository
                or source_location.commit != run.source.commit
            ):
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} source does not match the "
                    "run source snapshot"
                )

        if not (
            attempt.started_at < resolved_spec.completed_at <= attempt.completed_at
        ):
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} completion time falls outside "
                "its containing attempt"
            )

        if isinstance(resolved_spec, ResolvedDownloadSpec):
            _verify_download_retrievals(
                attempt,
                run,
                stage_reference.stage_id,
                resolved_spec,
                stage_reference.snapshot,
                fetcher=fetcher,
            )

        if verified_stages:
            previous_completed_at = next(
                reversed(verified_stages.values())
            ).completed_at
            if resolved_spec.completed_at < previous_completed_at:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} completed before its "
                    "preceding stage"
                )

        if isinstance(resolved_spec, ResolvedParameterizedSpec):
            read_resolved_file(resolved_spec.source, fetcher=fetcher)
        read_resolved_file(resolved_spec.env.lockfile, fetcher=fetcher)

        requested_environment = stage_spec.env or run.env
        resolved_environment = resolved_spec.env
        _verify_effective_env(
            stage_reference.stage_id,
            requested_environment,
            resolved_environment,
            resolved_spec.execution_context,
        )

        if isinstance(resolved_spec, ResolvedParameterizedSpec):
            expected_command = (
                "python",
                "-m",
                "viper._workers.stages",
            )
            if resolved_spec.command != expected_command:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} command does not match "
                    "the run plan"
                )

        for artifact_name, artifact in resolved_spec.artifacts.items():
            declaration = stage_spec.artifacts[artifact_name]
            verified_artifact = verify_snapshot_artifact(
                stage_reference,
                artifact,
                data_role=declaration.data_role,
                fetcher=fetcher,
            )
            load_verified_artifact(
                run,
                declaration,
                artifact_name,
                verified_artifact,
                policy=policy,
                fetcher=fetcher,
            )

        verified_stages[stage_reference.stage_id] = resolved_spec

    if len(attempt.invocations) == len(resolved_parameterized_ids) + 1:
        stage_id = expected_stage_ids[len(attempt.resolved_stages)]
        stage_spec = stage_specs[stage_id]
        if not isinstance(stage_spec, ParameterizedSpec):
            raise VerificationError("unresolved stage invocation is not parameterized")
        _verify_unresolved_stage_invocation(
            attempt.invocations[-1],
            attempt=attempt,
            run=run,
            stage_id=stage_id,
            stage=cast(ParameterizedStageSpec, stage_spec),
            stage_specs=stage_specs,
            fetcher=fetcher,
        )

    return verified_stages


def verify_attempt_journal(
    attempt: RunAttempt,
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify one terminal attempt journal and its canonical identity."""
    expected_path = f"{run_root(run)}/attempts/{attempt.attempt_id}/journal.jsonl"
    if attempt.journal.stored_at.path != expected_path:
        raise VerificationError("attempt journal path is not canonical")
    try:
        entries = parse_journal_bytes(
            read_resolved_file(attempt.journal, fetcher=fetcher)
        )
    except ValueError as exc:
        raise VerificationError("attempt journal is invalid") from exc
    if not entries or entries[-1].state != "terminal":
        raise VerificationError("published attempt journal is not terminal")


def verify_attempt_files(
    attempt: RunAttempt,
    run: RunSpec,
    experiment: ExperimentSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[Measurement, ...]:
    """Verify an attempt's measurements and logs against their file identities."""
    attempt_file_snapshots = {
        identity
        for reference in (
            *attempt.measurement_files,
            *attempt.metric_verification_files,
            *attempt.log_files,
        )
        if (identity := artifact_revision_identity(reference.stored_at)) is not None
    }
    if len(attempt_file_snapshots) > 1:
        raise VerificationError(
            "attempt measurement and log files must use one immutable snapshot"
        )

    completed_stage_ids = {stage.stage_id for stage in attempt.resolved_stages}
    planned_stage_ids = tuple(stage.stage_id for stage in run.stages)
    permitted_log_stage_ids = set(completed_stage_ids)
    if attempt.status != "succeeded" and len(completed_stage_ids) < len(
        planned_stage_ids
    ):
        permitted_log_stage_ids.add(planned_stage_ids[len(completed_stage_ids)])
    permitted_metrics = {metric.metric_id for metric in experiment.metrics}
    measurements: list[Measurement] = []
    root = run_root(run)
    for reference in attempt.measurement_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError(
                "measurement files must use immutable artifact storage"
            )
        measurement_root = f"{root}/attempts/{attempt.attempt_id}/measurements"
        if not str(reference.stored_at.path).startswith(f"{measurement_root}/"):
            raise VerificationError(
                "measurement file is outside the canonical run path"
            )

        raw = read_resolved_file(reference, fetcher=fetcher)
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise VerificationError("measurement file is not valid UTF-8") from exc

        for line in lines:
            if not line.strip():
                continue
            try:
                measurement = Measurement.model_validate(
                    json.loads(line, object_pairs_hook=unique_json_object)
                )
            except ValueError as exc:
                raise VerificationError(
                    "measurement file contains an invalid Measurement row"
                ) from exc

            if measurement.run_id != run.run_id:
                raise VerificationError("measurement run ID does not match the run")
            if measurement.attempt_id != attempt.attempt_id:
                raise VerificationError(
                    "measurement attempt ID does not match its containing attempt"
                )
            if measurement.stage_id not in completed_stage_ids:
                raise VerificationError(
                    "measurement stage is absent from its containing attempt"
                )
            if measurement.metric_id not in permitted_metrics:
                raise VerificationError(
                    "measurement metric is absent from the experiment"
                )
            stage_spec = stage_specs.get(measurement.stage_id)
            if stage_spec is None:
                raise VerificationError(
                    "measurement stage has no loaded stage specification"
                )
            if measurement.metric_id not in stage_spec.metric_ids:
                raise VerificationError(
                    "measurement metric is absent from its stage spec"
                )
            expected_path = (
                f"{measurement_root}/{measurement.stage_id}."
                f"{measurement.metric_id}.jsonl"
            )
            if reference.stored_at.path != expected_path:
                raise VerificationError(
                    "measurement file path does not match its stage and metric"
                )
            if not (
                attempt.started_at <= measurement.measured_at <= attempt.completed_at
            ):
                raise VerificationError(
                    "measurement timestamp falls outside its containing attempt"
                )
            measurements.append(measurement)

    if attempt.status == "succeeded":
        for stage_id in completed_stage_ids:
            stage_spec = stage_specs[stage_id]
            if not isinstance(stage_spec, EvalSpec):
                continue
            for metric_id in stage_spec.metric_ids:
                matches = [
                    measurement
                    for measurement in measurements
                    if measurement.stage_id == stage_id
                    and measurement.metric_id == metric_id
                ]
                if len(matches) != 1:
                    raise VerificationError(
                        f"successful evaluation stage {stage_id!r} must record "
                        f"exactly one measurement for metric {metric_id!r}"
                    )

    for reference in attempt.log_files:
        if not isinstance(reference.stored_at, (HuggingFaceFileRef, LocalFileRef)):
            raise VerificationError("log files must use immutable artifact storage")
        log_pattern = re.compile(
            rf"^{re.escape(root)}/attempts/{attempt.attempt_id}/logs/"
            r"([a-z][a-z0-9_]*)\.(stdout|stderr)\.log$"
        )
        match = log_pattern.fullmatch(str(reference.stored_at.path))
        if match is None or match.group(1) not in permitted_log_stage_ids:
            raise VerificationError(
                "log file path does not match its attempt and stage"
            )
        read_resolved_file(reference, fetcher=fetcher)

    return tuple(measurements)


def verify_measurement_stage_times(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    measurements: tuple[Measurement, ...],
    experiment: ExperimentSpec,
) -> None:
    """Place live and recomputed measurements on the correct stage boundary."""
    metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for measurement in measurements:
        resolved_stage = resolved_stages.get(measurement.stage_id)
        if resolved_stage is None:
            raise VerificationError("measurement stage has no resolved stage result")
        metric = metrics[measurement.metric_id]
        if (
            metric.mode == "live"
            and measurement.measured_at > resolved_stage.completed_at
        ):
            raise VerificationError(
                "live measurement timestamp follows its named stage completion"
            )
        if (
            metric.mode == "recompute"
            and measurement.measured_at < resolved_stage.completed_at
        ):
            raise VerificationError(
                "recomputed measurement timestamp precedes stage completion"
            )


def verify_external_inputs(
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    resolved: ResolvedInternalSpec,
    snapshot: StageResultSnapshot,
    *,
    fetcher: StorageFetcher | None,
) -> None:
    """Verify each local input captured in one completed stage snapshot."""
    for input_name, resolved_input in resolved.inputs.items():
        if not isinstance(resolved_input, ResolvedExternalInputRef):
            continue
        planned_input = resolved.spec.inputs[input_name]
        if not isinstance(planned_input, ExternalInputRef):
            raise VerificationError(
                "input.local.identity: resolved input differs from its plan"
            )
        if (
            resolved_input.source != planned_input.source
            or resolved_input.data_role != planned_input.data_role
        ):
            raise VerificationError(
                "input.local.identity: resolved input provenance differs"
            )
        expected_path = captured_input_path(
            run_id=run.run_id,
            attempt_id=attempt.attempt_id,
            stage_id=stage_id,
            input_name=input_name,
            source_path=planned_input.source.path,
        )
        if resolved_input.file.path != expected_path:
            raise VerificationError("input.local.identity: path differs")
        try:
            read_snapshot_file(snapshot, resolved_input.file, fetcher=fetcher)
        except VerificationError as exc:
            raise VerificationError(
                f"input.local.identity: captured input {input_name!r} differs"
            ) from exc
