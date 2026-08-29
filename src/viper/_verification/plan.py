"""Verify a frozen run plan and every selected source-bound specification."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping

import yaml
from pydantic import TypeAdapter

from .._parameter.validation import (
    ParameterValidationError,
    verify_parameter_model_bytes,
)
from .._schema import PARAMETERS_INPUT, DataRole, RepoRelPath, repo_file_paths_overlap
from ..benchmark import BenchmarkSpec
from ..experiments import ExperimentSpec, VariantSpec
from ..ids import InputName, StageId
from ..inputs import FutureInputRef, StoredInputRef
from ..references import GitFileRef, ResolvedFileRef, ResolvedRunSpecRef
from ..runs import ResolvedRun, RunSpec
from ..serialization import parse_yaml_bytes
from ..stages import (
    BaseSpec,
    BuildSpec,
    DownloadSpec,
    EmbedSpec,
    EvaluateSpec,
    InternalSpec,
    ParameterizedSpec,
    Spec,
    StageDefinitionError,
    TrainSpec,
    verify_stage_implementation_bytes,
)
from .models import VerificationError, VerifiedRunPlan
from .paths import run_root, stage_spec_path
from .storage import (
    StorageFetcher,
    fetch_storage_bytes,
    read_resolved_file,
    verify_resolved_file_bytes,
)

SPEC_ADAPTER = TypeAdapter(Spec)


_DATA_ROLE_RANK: dict[DataRole, int] = {
    "training": 0,
    "validation": 1,
    "evaluation": 2,
    "benchmark": 3,
}


def _verify_stage_data_roles(
    stage_id: StageId,
    stage: BaseSpec,
    prior_stages: Mapping[StageId, BaseSpec],
) -> None:
    """Reject restricted inputs and artifact-role downgrades within a run plan."""
    if not isinstance(stage, InternalSpec):
        return

    input_roles = _stage_input_roles(stage_id, stage, prior_stages)

    if isinstance(stage, TrainSpec):
        restricted = {
            name: role
            for name, role in input_roles.items()
            if _DATA_ROLE_RANK[role] > _DATA_ROLE_RANK["validation"]
        }
        if restricted:
            names = ", ".join(sorted(restricted))
            raise VerificationError(
                f"training stage {stage_id!r} cannot consume evaluation or "
                f"benchmark inputs: {names}"
            )

    if isinstance(stage, EvaluateSpec):
        model_role = input_roles[PARAMETERS_INPUT]
        if _DATA_ROLE_RANK[model_role] > _DATA_ROLE_RANK["validation"]:
            raise VerificationError(
                f"evaluation stage {stage_id!r} parameters must have training "
                "or validation data_role"
            )

        dataset_input = stage.inputs["evaluation_dataset"]
        assert isinstance(dataset_input, StoredInputRef)
        evaluation_role = dataset_input.data_role
        incompatible = {
            name: role
            for name, role in input_roles.items()
            if _DATA_ROLE_RANK[role] > _DATA_ROLE_RANK[evaluation_role]
        }
        if incompatible:
            names = ", ".join(sorted(incompatible))
            raise VerificationError(
                f"evaluation stage {stage_id!r} consumes inputs more restricted "
                f"than its {evaluation_role!r} evaluation: {names}"
            )

    highest_input_rank = max(_DATA_ROLE_RANK[role] for role in input_roles.values())
    downgraded_outputs = {
        name
        for name, artifact in stage.artifacts.items()
        if _DATA_ROLE_RANK[artifact.data_role] < highest_input_rank
    }
    if downgraded_outputs:
        names = ", ".join(sorted(downgraded_outputs))
        raise VerificationError(
            f"stage {stage_id!r} artifacts cannot have a less restricted "
            f"data_role than their inputs: {names}"
        )


def _stage_input_roles(
    stage_id: StageId,
    stage: InternalSpec,
    prior_stages: Mapping[StageId, BaseSpec],
) -> dict[InputName, DataRole]:
    """Resolve each internal stage input to its declared data role."""
    input_roles: dict[InputName, DataRole] = {}
    for input_name, input_ref in stage.inputs.items():
        if isinstance(input_ref, StoredInputRef):
            input_roles[input_name] = input_ref.data_role
            continue

        producer = prior_stages.get(input_ref.producer_stage_id)
        if producer is None:
            raise VerificationError(
                f"future input {input_name!r} of stage {stage_id!r} must select "
                "an earlier stage"
            )
        declaration = producer.artifacts.get(input_ref.producer_artifact)
        if declaration is None:
            raise VerificationError(
                f"future input {input_name!r} of stage {stage_id!r} selects an "
                "undeclared producer artifact"
            )
        input_roles[input_name] = declaration.data_role
    return input_roles


def verify_run_spec(
    resolved_run: ResolvedRun,
    *,
    fetcher: StorageFetcher | None = None,
) -> RunSpec:
    """Retrieve and verify the RunSpec governing a resolved run."""
    raw = read_resolved_file(resolved_run.spec, fetcher=fetcher)

    try:
        file_run = RunSpec.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError("resolved run spec is not a valid RunSpec") from exc

    expected_path = f"{run_root(file_run)}/spec.yaml"
    if resolved_run.spec.stored_at.path != expected_path:
        raise VerificationError(
            "resolved run spec reference is outside the canonical run path"
        )
    if resolved_run.spec.stored_at.repository != file_run.source.repository:
        raise VerificationError(
            "resolved run spec and source snapshot must use one Git repository"
        )

    return file_run


def verify_experiment_and_variant(
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> tuple[ExperimentSpec, VariantSpec]:
    """Load and verify the experiment and variant selected by a run."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher

    experiment_location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"experiments/{run.experiment_id}/spec.yaml",
    )
    variant_location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"experiments/{run.experiment_id}/variants/{run.variant_id}.spec.yaml",
    )

    try:
        experiment = ExperimentSpec.model_validate(
            parse_yaml_bytes(retrieve(experiment_location))
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "experiment file is not a valid ExperimentSpec document"
        ) from exc

    try:
        variant = VariantSpec.model_validate(
            parse_yaml_bytes(retrieve(variant_location))
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "variant file is not a valid VariantSpec document"
        ) from exc

    for metric in experiment.metrics:
        implementation = metric.implementation
        metric_location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=implementation.path,
        )
        metric_raw = retrieve(metric_location)
        if len(metric_raw) != implementation.bytes:
            raise VerificationError("metric implementation byte count differs")
        if hashlib.sha256(metric_raw).hexdigest() != implementation.sha256:
            raise VerificationError("metric implementation SHA-256 differs")
        try:
            metric_tree = ast.parse(metric_raw, filename=implementation.path)
        except SyntaxError as exc:
            raise VerificationError(
                f"metric {metric.metric_id!r} implementation is not valid Python"
            ) from exc
        permitted_nodes: tuple[type[ast.AST], ...] = (
            (ast.FunctionDef, ast.AsyncFunctionDef)
            if metric.mode == "recompute"
            else (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        if not any(
            isinstance(node, permitted_nodes) and node.name == implementation.symbol
            for node in metric_tree.body
        ):
            raise VerificationError(
                f"metric {metric.metric_id!r} implementation must define "
                f"{implementation.symbol}"
            )

    if experiment.experiment_id != run.experiment_id:
        raise VerificationError("run and experiment IDs do not match")

    if variant.experiment_id != run.experiment_id:
        raise VerificationError("run and variant experiment IDs do not match")

    if variant.variant_id != run.variant_id:
        raise VerificationError("run and variant IDs do not match")

    if run.variant_id not in experiment.variant_ids:
        raise VerificationError("run variant is not declared by the experiment")

    factors = {factor.factor_id: factor for factor in experiment.factors}
    if set(variant.levels) != set(factors):
        raise VerificationError(
            "variant must assign exactly one level to every experiment factor"
        )

    for factor_id, level_id in variant.levels.items():
        if level_id not in factors[factor_id].levels:
            raise VerificationError(
                f"variant level {level_id!r} is not permitted for factor {factor_id!r}"
            )

    replicates = {
        replicate.replicate_id: replicate for replicate in experiment.replicates
    }
    if run.replicate_id not in replicates:
        raise VerificationError("run replicate is not declared by the experiment")

    if run.seed != replicates[run.replicate_id].seed:
        raise VerificationError("run seed does not match the experiment replicate")

    return experiment, variant


def verify_benchmark_spec(
    run: RunSpec,
    *,
    fetcher: StorageFetcher | None = None,
) -> BenchmarkSpec | None:
    """Load the benchmark selected by a run, when one is selected."""
    if run.benchmark_id is None:
        return None

    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    location = GitFileRef(
        repository=run.source.repository,
        commit=run.source.commit,
        path=f"benchmarks/{run.benchmark_id}.spec.yaml",
    )
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(retrieve(location)))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark file is not a valid BenchmarkSpec document"
        ) from exc

    if benchmark.benchmark_id != run.benchmark_id:
        raise VerificationError("run and benchmark IDs do not match")
    return benchmark


def verify_run_plan_relationships(
    run: RunSpec,
    experiment: ExperimentSpec,
    variant: VariantSpec,
    benchmark: BenchmarkSpec | None,
    stages: Mapping[StageId, BaseSpec],
) -> None:
    """Verify plan relationships spanning experiment, variant, and stages."""

    def require_source_snapshot(location: GitFileRef, label: str) -> None:
        if (
            location.repository != run.source.repository
            or location.commit != run.source.commit
        ):
            raise VerificationError(f"{label} must belong to the run source snapshot")

    require_source_snapshot(run.environment.lockfile, "shared lockfile")

    for stage_id, stage in stages.items():
        if stage.environment is not None:
            require_source_snapshot(
                stage.environment.lockfile,
                f"environment lockfile of stage {stage_id!r}",
            )

    prior_stages: dict[StageId, BaseSpec] = {}
    prior_stages_by_id: dict[StageId, dict[StageId, BaseSpec]] = {}
    for stage_reference in run.stages:
        stage = stages[stage_reference.stage_id]
        prior_stages_by_id[stage_reference.stage_id] = dict(prior_stages)
        _verify_stage_data_roles(stage_reference.stage_id, stage, prior_stages)
        prior_stages[stage_reference.stage_id] = stage

    parameterized_stages = {
        stage_id: stage
        for stage_id, stage in stages.items()
        if isinstance(
            stage,
            (DownloadSpec, BuildSpec, EmbedSpec, TrainSpec, EvaluateSpec),
        )
    }
    variant_params = {stage.stage_id: stage for stage in variant.stage_params}

    if set(variant_params) != set(parameterized_stages):
        raise VerificationError(
            "variant stage parameters must match all parameterized run stages"
        )

    for stage_id, stage in parameterized_stages.items():
        selected = variant_params[stage_id]
        if selected.kind != stage.kind or selected.params != stage.params:
            raise VerificationError(
                f"variant parameters do not match stage {stage_id!r}"
            )

    estimator_stage = stages.get(run.estimator.stage_id)
    if not isinstance(estimator_stage, TrainSpec):
        raise VerificationError("run estimator must select a training stage")

    experiment_metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for stage_id, stage in stages.items():
        undeclared_metrics = set(stage.metric_ids) - set(experiment_metrics)
        if undeclared_metrics:
            raise VerificationError(f"stage {stage_id!r} selects undeclared metrics")

        selected_kinds = {
            experiment_metrics[metric_id].kind for metric_id in stage.metric_ids
        }
        if isinstance(stage, EvaluateSpec):
            if selected_kinds - {"evaluation"}:
                raise VerificationError(
                    f"evaluation stage {stage_id!r} must select evaluation metrics"
                )
        elif isinstance(stage, TrainSpec):
            if selected_kinds - {"training", "diagnostic"}:
                raise VerificationError(
                    f"training stage {stage_id!r} selects an incompatible metric"
                )
        elif selected_kinds - {"diagnostic"}:
            raise VerificationError(
                f"stage {stage_id!r} must select diagnostic metrics"
            )

    evaluation_stages = [
        stage for stage in stages.values() if isinstance(stage, EvaluateSpec)
    ]
    expected_evaluation_role: DataRole = (
        "benchmark" if benchmark is not None else "evaluation"
    )
    for evaluation in evaluation_stages:
        dataset_input = evaluation.inputs["evaluation_dataset"]
        assert isinstance(dataset_input, StoredInputRef)
        if dataset_input.data_role != expected_evaluation_role:
            raise VerificationError(
                f"evaluation {evaluation.evaluation_id!r} must use "
                f"{expected_evaluation_role!r} data_role"
            )

    for stage_id, stage in stages.items():
        input_roles = (
            _stage_input_roles(stage_id, stage, prior_stages_by_id[stage_id])
            if isinstance(stage, InternalSpec)
            else {}
        )
        for metric_id in stage.metric_ids:
            metric = experiment_metrics[metric_id]
            for dependency in metric.dependencies:
                if dependency.source == "input":
                    role = input_roles.get(dependency.name)
                else:
                    artifact = stage.artifacts.get(dependency.name)
                    role = None if artifact is None else artifact.data_role
                if role is None:
                    raise VerificationError(
                        f"metric {metric_id!r} selects absent {dependency.source} "
                        f"dependency {dependency.name!r}"
                    )
                if role != dependency.required_data_role:
                    raise VerificationError(
                        f"metric {metric_id!r} dependency {dependency.name!r} "
                        "data role differs from its stage declaration"
                    )

    if benchmark is None:
        return

    if len(evaluation_stages) != 1:
        raise VerificationError("benchmark runs require exactly one evaluation stage")

    evaluation = evaluation_stages[0]
    model_input = evaluation.inputs[PARAMETERS_INPUT]
    if not isinstance(model_input, FutureInputRef):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )
    if (
        model_input.producer_stage_id != run.estimator.stage_id
        or model_input.producer_artifact != run.estimator.artifact_name
    ):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )

    if evaluation.evaluation_id != benchmark.evaluation_id:
        raise VerificationError(
            "evaluation stage ID does not match the benchmark evaluation ID"
        )

    dataset_input = evaluation.inputs["evaluation_dataset"]
    if not isinstance(dataset_input, StoredInputRef):
        raise VerificationError("benchmark evaluation dataset must be stored")
    if dataset_input.pointer != benchmark.evaluation_dataset:
        raise VerificationError(
            "evaluation dataset does not match the benchmark specification"
        )

    if set(evaluation.split_inputs) != set(benchmark.splits):
        raise VerificationError(
            "evaluation split names do not match the benchmark specification"
        )
    for split_name, pointer in benchmark.splits.items():
        split_input = evaluation.inputs[split_name]
        if not isinstance(split_input, StoredInputRef):
            raise VerificationError(f"benchmark split {split_name!r} must be stored")
        if split_input.pointer != pointer:
            raise VerificationError(
                f"evaluation split {split_name!r} does not match the benchmark"
            )

    benchmark_metric_ids = {criterion.metric_id for criterion in benchmark.metrics}
    if set(evaluation.metric_ids) != benchmark_metric_ids:
        raise VerificationError(
            "evaluation metrics do not match the benchmark specification"
        )
    for criterion in benchmark.metrics:
        metric = experiment_metrics[criterion.metric_id]
        if metric.kind != "evaluation" or metric.mode != "recompute":
            raise VerificationError(
                f"benchmark criterion {criterion.metric_id!r} must select a "
                "recomputed evaluation metric"
            )


def verify_parameter_model_references(
    run: RunSpec,
    stages: Mapping[StageId, BaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> None:
    """Verify each parameterized stage's class against frozen source bytes."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    for stage_id, stage in stages.items():
        if not isinstance(stage, ParameterizedSpec):
            continue
        reference = stage.parameter_model
        location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=reference.path,
        )
        try:
            raw = retrieve(location)
            verify_parameter_model_bytes(reference, raw)
            tree = ast.parse(raw, filename=reference.path)
        except (KeyError, OSError, SyntaxError, ParameterValidationError) as exc:
            raise VerificationError(
                f"parameter model of stage {stage_id!r} failed source verification"
            ) from exc
        if not any(
            isinstance(node, ast.ClassDef) and node.name == reference.symbol
            for node in tree.body
        ):
            raise VerificationError(
                f"parameter model of stage {stage_id!r} must define {reference.symbol}"
            )


def verify_stage_plan(
    run: RunSpec,
    run_spec_reference: ResolvedRunSpecRef,
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, BaseSpec]:
    """Load and verify stage specs from the run-plan snapshot."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    loaded_stages: dict[StageId, BaseSpec] = {}

    for stage in run.stages:
        if stage.spec != stage_spec_path(run, stage.stage_id):
            raise VerificationError(
                f"stage {stage.stage_id!r} spec is outside its canonical run path"
            )

        plan_location = run_spec_reference.stored_at
        location = GitFileRef(
            repository=plan_location.repository,
            commit=plan_location.commit,
            path=stage.spec,
        )

        stage_reference = ResolvedFileRef(
            sha256=stage.sha256,
            bytes=stage.bytes,
            stored_at=location,
        )
        raw = verify_resolved_file_bytes(stage_reference, retrieve(location))

        try:
            spec = SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage.stage_id!r} file is not a valid stage spec"
            ) from exc

        implementation = spec.implementation
        implementation_location = GitFileRef(
            repository=run.source.repository,
            commit=run.source.commit,
            path=implementation.path,
        )
        try:
            implementation_raw = retrieve(implementation_location)
            verify_stage_implementation_bytes(implementation, implementation_raw)
            implementation_tree = ast.parse(
                implementation_raw,
                filename=implementation.path,
            )
        except (KeyError, OSError, SyntaxError, StageDefinitionError) as exc:
            raise VerificationError(
                f"implementation of stage {stage.stage_id!r} failed source verification"
            ) from exc
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == implementation.symbol
            for node in implementation_tree.body
        ):
            raise VerificationError(
                f"implementation of stage {stage.stage_id!r} must define "
                f"top-level callable {implementation.symbol!r}"
            )

        artifact_root = f"{run_root(run)}/artifacts/"
        for artifact_name, artifact in spec.artifacts.items():
            if not str(artifact.path).startswith(artifact_root):
                raise VerificationError(
                    f"artifact {artifact_name!r} of stage {stage.stage_id!r} "
                    "is outside the canonical run artifact root"
                )

        if isinstance(spec, InternalSpec):
            for input_name, input_ref in spec.inputs.items():
                if isinstance(input_ref, StoredInputRef) and not str(
                    input_ref.path
                ).startswith("inputs/"):
                    raise VerificationError(
                        f"stored input {input_name!r} of stage "
                        f"{stage.stage_id!r} is outside inputs"
                    )

        if isinstance(spec, InternalSpec):
            stored_inputs = tuple(
                input_ref
                for input_ref in spec.inputs.values()
                if isinstance(input_ref, StoredInputRef)
            )
            future_materialization_paths: dict[RepoRelPath, InputName] = {}

            for input_name, input_ref in spec.inputs.items():
                if not isinstance(input_ref, FutureInputRef):
                    continue

                producer_stage_id = input_ref.producer_stage_id
                if producer_stage_id not in loaded_stages:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        "must name an earlier stage"
                    )

                producer_spec = loaded_stages[producer_stage_id]
                producer_artifact = producer_spec.artifacts.get(
                    input_ref.producer_artifact
                )
                if producer_artifact is None:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        f"selects undeclared artifact "
                        f"{input_ref.producer_artifact!r}"
                    )

                producer_path = producer_artifact.path

                for (
                    previous_path,
                    previous_name,
                ) in future_materialization_paths.items():
                    if repo_file_paths_overlap(producer_path, previous_path):
                        raise VerificationError(
                            f"future input paths for {previous_name!r} and "
                            f"{input_name!r} of stage {stage.stage_id!r} collide"
                        )
                future_materialization_paths[producer_path] = input_name

                if repo_file_paths_overlap(producer_path, spec.implementation.path):
                    raise VerificationError(
                        f"future input {input_name!r} path collides with the "
                        f"implementation of stage {stage.stage_id!r}"
                    )

                for artifact_name, artifact in spec.artifacts.items():
                    if repo_file_paths_overlap(producer_path, artifact.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with "
                            f"artifact {artifact_name!r} of stage "
                            f"{stage.stage_id!r}"
                        )

                for stored_input in stored_inputs:
                    if repo_file_paths_overlap(producer_path, stored_input.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with a "
                            f"stored input of stage {stage.stage_id!r}"
                        )

            _verify_stage_data_roles(stage.stage_id, spec, loaded_stages)

        loaded_stages[stage.stage_id] = spec

    return loaded_stages


def verify_run_plan(
    resolved_run: ResolvedRun,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifiedRunPlan:
    """Retrieve and verify every record constituting a frozen run plan."""
    run = verify_run_spec(resolved_run, fetcher=fetcher)
    experiment, variant = verify_experiment_and_variant(run, fetcher=fetcher)
    benchmark = verify_benchmark_spec(run, fetcher=fetcher)
    stages = verify_stage_plan(run, resolved_run.spec, fetcher=fetcher)
    verify_run_plan_relationships(
        run,
        experiment,
        variant,
        benchmark,
        stages,
    )
    verify_parameter_model_references(run, stages, fetcher=fetcher)
    return VerifiedRunPlan(
        run=run,
        experiment=experiment,
        variant=variant,
        benchmark=benchmark,
        stages=stages,
    )
