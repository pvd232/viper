"""Compare training on two or three rows across two replicate seeds."""

from examples.cpu_quickstart import fit, load_json, load_state, mse
from examples.workflow_functions import RowLimit, limit_rows, load_text
from viper import execution
from viper.authoring import (
    VariantDraft,
    expand,
    experiment,
    factor,
    input,
    replicate,
    stage,
    variant,
)
from viper.metrics import min
from viper.outputs import StageOutputs, TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env

training_rows = factor("training_rows", levels=("two", "three"))


def training_variant(name: str, rows: int, level: str) -> VariantDraft:
    """Connect row selection to the complete quickstart training function."""
    prepared = stage(
        limit_rows,
        stage_id="prepare",
        config=RowLimit(rows=rows),
        inputs=(input("dataset", path="examples/data/tiny.csv", data_role="training"),),
        outputs=StageOutputs(
            dataset=output(path="selected.csv", loader=load_text, data_role="training")
        ),
    )
    training = stage(
        fit,
        stage_id="train",
        inputs=(prepared.outputs["dataset"],),
        outputs=TrainOutputs(
            model=output(path="model.json", loader=load_json, data_role="training"),
            resume_state=output(
                path="resume_state.pt", loader=load_state, data_role="training"
            ),
        ),
        metrics=(mse,),
        objective=min(mse),
    )
    return variant(
        name,
        levels=(training_rows.level(level),),
        stages=(
            prepared,
            training,
        ),
        estimator=training.outputs["model"],
    )


study = experiment(
    experiment_id="training_rows",
    factors=(training_rows,),
    variants=(
        training_variant("two_rows", 2, "two"),
        training_variant("three_rows", 3, "three"),
    ),
    replicates=(replicate(seed=7), replicate(seed=19)),
)


def main() -> None:
    """Create one plan per pair and report each batch outcome."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    drafts = expand(study, source=source, env=environment)
    root = resolve_root()
    batch = execution.run_many(root, drafts, max_concurrency=2)
    for entry in batch.runs:
        if entry.result is not None:
            print(f"{entry.run_id}: {entry.result.status} {entry.result.path}")
        elif entry.failure is not None:
            print(f"{entry.run_id}: failed {entry.failure.message}")
        else:
            print(f"{entry.run_id}: skipped {entry.skip_reason}")


if __name__ == "__main__":
    main()
