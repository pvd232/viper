"""Publish held-out data, train a model, and confirm its evaluation benchmark."""

from examples.cpu_quickstart import training
from examples.workflow_functions import (
    load_text,
    predict,
    prepare_test_data,
    root_mean_squared_error,
)
from viper import execution
from viper.artifacts import StageArtifactRef
from viper.authoring import (
    experiment,
    input,
    plan,
    replicate,
    run_artifact,
    stage,
    variant,
)
from viper.benchmark import at_most, benchmark
from viper.config import BuildConfig, EvalConfig
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    measure,
    min,
)
from viper.outputs import EvalOutputs, StageOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env

data_stage = stage(
    prepare_test_data,
    config=BuildConfig(),
    inputs={"source": input("examples/data/held_out.csv", data_role="benchmark")},
    outputs=StageOutputs.model_validate(
        {
            "test_data": output(
                path="test.csv", loader=load_text, data_role="benchmark"
            ),
            "test_split": output(
                path="holdout.json", loader=load_text, data_role="benchmark"
            ),
        }
    ),
)
data_study = experiment(
    experiment_id="held_out_data",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training, "build": data_stage},
            estimator=training.outputs["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)


rmse = measure(
    root_mean_squared_error,
    dependencies=(
        MetricDependency(
            source="artifact", name="predictions", required_data_role="benchmark"
        ),
    ),
    comparator=FloatComparator(mode="absolute", tolerance=1e-12),
)


def main() -> None:
    """Run data preparation, evaluation, and an independent benchmark confirmation."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    data_run = execution.run(
        plan(
            experiment=data_study,
            variant="baseline",
            replicate="seed_7",
            source=source,
            env=environment,
        )
    )
    test_data = run_artifact(
        data_run.reference,
        StageArtifactRef(stage_id="build", artifact_name="test_data"),
        path="inputs/test.csv",
        data_role="benchmark",
    )
    test_split = run_artifact(
        data_run.reference,
        StageArtifactRef(stage_id="build", artifact_name="test_split"),
        path="inputs/holdout.json",
        data_role="benchmark",
    )
    evaluation = stage(
        predict,
        config=EvalConfig(),
        eval_id="holdout",
        inputs={
            "model": training.outputs["model"],
            "test": test_data,
            "holdout": test_split,
        },
        split_inputs=("holdout",),
        outputs=EvalOutputs(
            predictions=output(
                path="predictions.json", loader=load_text, data_role="benchmark"
            )
        ),
        metrics=(rmse,),
        objective=min(rmse),
    )
    study = experiment(
        experiment_id="held_out_evaluation",
        variants={
            "baseline": variant(
                levels={},
                stages={"train": training, "eval": evaluation},
                estimator=training.outputs["model"],
            )
        },
        replicates={"seed_7": replicate(seed=7)},
    )
    criteria = benchmark(
        benchmark_id="holdout_v1",
        eval_id="holdout",
        test=test_data,
        splits={"holdout": test_split},
        metrics=(rmse,),
        criteria=(at_most(rmse, 0.1),),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
        benchmark=criteria,
    )
    resolved_run = execution.run(draft)
    confirmation = execution.benchmark(
        root,
        resolved_run.path,
        root / "benchmarks/holdout_v1.spec.yaml",
    )
    print(f"data: {data_run.path}")
    print(f"result: {resolved_run.path}")
    print(f"benchmark: {confirmation.status} {confirmation.path}")


if __name__ == "__main__":
    main()
