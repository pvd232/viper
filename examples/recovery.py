"""Retry a controlled failure, then reuse its verified training result."""

from examples.cpu_quickstart import fit, load_json, load_state, mse
from viper import api, execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import TrainConfig
from viper.execution.errors import RunError
from viper.metrics import min
from viper.outputs import TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, train


@train(config=TrainConfig)
def fit_after_failure(context: Context[TrainConfig]) -> None:
    """Simulate a transient first-attempt failure, then perform real training."""
    if context.attempt_id == 1:
        raise RuntimeError("Demonstration: first attempt is intentionally unavailable")
    fit(context)


training = stage(
    fit_after_failure,
    stage_id="train",
    inputs={"dataset": input("examples/data/tiny.csv", data_role="training")},
    outputs=TrainOutputs(
        model=output(path="model.json", loader=load_json, data_role="training"),
        resume_state=output(
            path="resume_state.pt", loader=load_state, data_role="training"
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
    reuse="verified",
)
study = experiment(
    experiment_id="recovery",
    variants=(
        variant("baseline", stages=(training,), estimator=training.outputs["model"]),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Recover the first run and index it before executing the second plan."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        source=source,
        env=environment,
    )
    try:
        execution.run(draft)
    except RunError:
        # Retry the saved plan after the simulated first-attempt failure.
        plan_path = (
            root / f"experiments/recovery/runs/baseline/{draft.run_id}/spec.yaml"
        )
        recovered = execution.retry(root, plan_path)
    else:
        raise RuntimeError("The demonstration expected its first attempt to fail")
    print(f"successful attempt: {recovered.record.successful_attempt_id}")
    api.catalog_refresh(
        api.CatalogRefreshRequest(
            root=root,
            run_paths=(recovered.path,),
            trusted_source_repositories=frozenset({str(source.repository)}),
        )
    )
    second = execution.run(
        plan(
            experiment=study,
            source=source,
            env=environment,
        )
    )
    print(f"reused run: {second.status}")
    print(f"result: {second.path}")


if __name__ == "__main__":
    main()
