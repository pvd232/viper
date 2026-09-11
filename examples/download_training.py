"""Download a pinned CSV and train a linear model from its verified bytes."""

from examples.cpu_quickstart import fit, load_json, load_state, mse
from examples.workflow_functions import load_text
from viper import execution
from viper.authoring import download, experiment, plan, replicate, stage, variant
from viper.http import HttpRequestSpec, HttpRetrievalPolicy
from viper.metrics import min
from viper.outputs import StageOutputs, TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source
from viper.runtime import LocalEnvSpec, observe_python_env

fetch_data = download(
    stage_id="download",
    inputs={
        "dataset": HttpRequestSpec(
            url=(
                "https://raw.githubusercontent.com/pvd232/viper/"
                "327d1f89ad38d855e500f5386bdd2894d049a899/examples/data/tiny.csv"
            ),
            version="327d1f89ad38d855e500f5386bdd2894d049a899",
            expected_body_sha256="5962ba6c35b56dabeb8121dd6656aba7b1e60afe0d2ddec498feb191057d15fe",
            expected_body_bytes=16,
        )
    },
    outputs=StageOutputs(
        dataset=output(
            path="train.csv",
            loader=load_text,
            data_role="training",
        )
    ),
    policy=HttpRetrievalPolicy(
        allowed_schemes=frozenset({"https"}),
        allowed_hosts=frozenset({"raw.githubusercontent.com"}),
        allowed_ports=frozenset({443}),
        max_redirects=0,
        max_body_bytes=20_000,
        timeout_seconds=30.0,
    ),
)

training = stage(
    fit,
    stage_id="train",
    inputs={"dataset": fetch_data.outputs["dataset"]},
    outputs=TrainOutputs(
        model=output(path="model.json", loader=load_json, data_role="training"),
        resume_state=output(
            path="resume_state.pt", loader=load_state, data_role="training"
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
)
study = experiment(
    experiment_id="download_training",
    variants=(
        variant(
            "baseline",
            stages=(fetch_data, training),
            estimator=training.outputs["model"],
        ),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Retrieve the declared dataset before starting training."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    result = execution.run(
        plan(
            experiment=study,
            source=source,
            env=environment,
        )
    )
    print(f"result: {result.status} {result.path}")


if __name__ == "__main__":
    main()
