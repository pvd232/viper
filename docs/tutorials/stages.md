# Build a stage pipeline

Prepare a CSV dataset, produce polynomial features, train a linear model,
and write a row-count report. Run this from the repository root after the
[installation steps](getting-started.md#install-the-repository).

The program imports the complete training function and its metric from the
[CPU quickstart](../../examples/cpu_quickstart.py). All three downstream stages
read the prepared dataset through its output handle. The feature file is an
additional result; the linear model uses the original scalar inputs.

`stage_id` names an invocation in the graph. The decorator selects its kind.
Output handles express data dependencies, and producers precede consumers in
the variant's stage tuple. The [stage guide](../how-to/stages.md) explains each
kind and every context attribute.

Save the complete program as [examples/stages.py](../../examples/stages.py):

```python
"""Prepare data, compute features, train a model, and write a diagnostic report."""

import json

from examples.cpu_quickstart import fit, load_json, load_state, mse
from examples.workflow_functions import load_text
from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import BuildConfig, DiagnosticConfig, EmbedConfig
from viper.metrics import min
from viper.outputs import StageOutputs, TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, build, diagnostic, embed


@build(config=BuildConfig)
def sort_rows(context: Context[BuildConfig]) -> None:
    """Sort the data rows while preserving the CSV header."""
    header, *rows = load_text(context.inputs["source"]).splitlines()
    destination = context.outputs["dataset"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join([header, *sorted(rows)]) + "\n", encoding="utf-8")


prepared = stage(
    sort_rows,
    stage_id="prepare",
    inputs={"source": input("examples/data/tiny.csv", data_role="training")},
    outputs=StageOutputs(
        dataset=output(path="sorted.csv", loader=load_text, data_role="training")
    ),
)


@embed(config=EmbedConfig)
def polynomial_features(context: Context[EmbedConfig]) -> None:
    """Write each input value and its square."""
    rows = load_text(context.inputs["dataset"]).splitlines()[1:]
    values = [float(row.split(",")[0]) for row in rows]
    features = [[value, value * value] for value in values]
    destination = context.outputs["features"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(features), encoding="utf-8")


embedded = stage(
    polynomial_features,
    stage_id="embed",
    inputs={"dataset": prepared.outputs["dataset"]},
    outputs=StageOutputs(
        features=output(path="features.json", loader=load_text, data_role="training")
    ),
)


@diagnostic(config=DiagnosticConfig)
def count_rows(context: Context[DiagnosticConfig]) -> None:
    """Write the number of prepared training rows."""
    rows = load_text(context.inputs["dataset"]).splitlines()[1:]
    destination = context.outputs["report"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"rows: {len(rows)}\n", encoding="utf-8")


report = stage(
    count_rows,
    stage_id="report",
    inputs={"dataset": prepared.outputs["dataset"]},
    outputs=StageOutputs(
        report=output(path="rows.txt", loader=load_text, data_role="training")
    ),
)
training = stage(
    fit,
    stage_id="train",
    inputs={"dataset": prepared.outputs["dataset"]},
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
    experiment_id="stage_pipeline",
    variants=(
        variant(
            "baseline",
            stages=(prepared, embedded, training, report),
            estimator=training.outputs["model"],
        ),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Execute all four stages and print the saved result path."""
    source = read_source()
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
    result = execution.run(draft)
    print(f"result: {result.status} {result.path}")


if __name__ == "__main__":
    main()
```

Run it with:

```bash
python -m examples.stages
```
