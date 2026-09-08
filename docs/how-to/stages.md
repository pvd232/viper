# Compose stages

A stage is a function with declared inputs and outputs. Connect stages by
passing an earlier stage's output to a later stage's input.

## Choose a stage kind

| Work | Declaration | Config | Outputs | Objective |
| --- | --- | --- | --- | --- |
| Retrieve files over HTTP | `download()` | HTTP policy and optional `HttpConfig` | One output for each request name | Omit |
| Prepare data or other inputs | `@build` | `BuildConfig` | `StageOutputs` | Omit |
| Compute representations | `@embed` | `EmbedConfig` | `StageOutputs` | Optional |
| Fit a model | `@train` | `TrainConfig` | `TrainOutputs`: `model`, `resume_state` | Required |
| Evaluate a model | `@eval` | `EvalConfig` | `EvalOutputs`: `predictions` | Required |
| Produce a diagnostic report | `@diagnostic` | `DiagnosticConfig` | `StageOutputs` | Omit |

The decorators and stage models are defined in
[`viper.stages`](../../src/viper/stages.py). The constructors are in
[`viper.authoring`](../../src/viper/authoring.py). Download stages are executed
by VIPER; the other kinds invoke a workspace function.

The following examples belong in importable Python files in your workspace.
They demonstrate separate stage declarations. Commit the files before creating
a plan, and supply the source and runtime records shown in the
[CPU tutorial](../tutorials/getting-started.md).

## Build an input artifact

This build stage sorts the rows of a CSV file while preserving its header:

```python
from pathlib import Path

from viper.authoring import input, stage
from viper.config import BuildConfig
from viper.outputs import StageOutputs, output
from viper.stages import Context, build


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@build(config=BuildConfig)
def sort_rows(context: Context[BuildConfig]) -> None:
    header, *rows = load_text(context.inputs["source"]).splitlines()
    destination = context.outputs["dataset"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join([header, *sorted(rows)]) + "\n", encoding="utf-8")


prepared = stage(
    sort_rows,
    config=BuildConfig(),
    inputs={"source": input("examples/data/tiny.csv", data_role="training")},
    outputs=StageOutputs(
        dataset=output(path="sorted.csv", loader=load_text, data_role="training")
    ),
)
```

The local input is captured for the run. The output loader describes how to
read the resulting artifact; the stage itself writes the file.

## Connect an embedding stage

An embedding stage uses the same input and output interfaces and may have a metric objective.
This example creates two numeric features from the first CSV column. A model
embedding function can use the same input and output interfaces.

```python
import json

from viper.config import EmbedConfig
from viper.stages import embed


@embed(config=EmbedConfig)
def polynomial_features(context: Context[EmbedConfig]) -> None:
    rows = load_text(context.inputs["dataset"]).splitlines()[1:]
    values = [float(row.split(",")[0]) for row in rows]
    features = [[value, value * value] for value in values]
    destination = context.outputs["features"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(features), encoding="utf-8")


embedded = stage(
    polynomial_features,
    config=EmbedConfig(),
    inputs={"dataset": prepared.outputs["dataset"]},
    outputs=StageOutputs(
        features=output(path="features.json", loader=load_text, data_role="training")
    ),
)
```

Include `prepared` before `embedded` in the variant's `stages` mapping. During
execution, VIPER supplies the prepared artifact through
`context.inputs["dataset"]`. The input name belongs to the receiving function;
it can differ from the producing output's name.

## Train and save a checkpoint

The [CPU example](../../examples/cpu_quickstart.py) contains a complete training
function and its `TrainOutputs` declaration. A training stage must declare a
metric objective and write both the model and resume state.

The model output stores learned model values. `ResumeState` stores the optimizer,
random generators, and data-loader state. These are separate files because
using a trained model for prediction and resuming its training require different
state. See [resume training](retry-restore-compare.md#resume-training-from-a-checkpoint)
for the restoration order.

To consume the sorted CSV above, use
`inputs={"dataset": prepared.outputs["dataset"]}` in that training stage.
To consume the polynomial features instead, adapt the training function to read
JSON and select `embedded.outputs["features"]`.

## Evaluate against saved test data

An evaluation stage consumes a `model`, a `test` dataset, and at least one named
split. The test and splits must be artifacts from a completed run with data
role `eval` or `benchmark`. The model can come from an earlier stage in the
current run or a completed run.

Select the test and split using `run_artifact()` as shown in
[stored inputs](inputs.md#use-an-artifact-from-a-completed-run). The `test_data`
artifact must contain a CSV with an `x,y` header; `test_split` must contain a
JSON list of zero-based row indices, such as `[0, 2]`. Use the tutorial's
`training` stage, which writes a JSON model containing `weight`.

This evaluation selects those rows, predicts their targets, writes the paired
predictions and targets, and computes root mean squared error from that file:

```python
import json

from viper.config import EvalConfig, MetricConfig
from viper.metrics import (
    FloatComparator, MetricContext, MetricDependency, measure, metric, min,
)
from viper.outputs import EvalOutputs
from viper.stages import eval


@eval(config=EvalConfig)
def predict(context: Context[EvalConfig]) -> None:
    model = json.loads(load_text(context.inputs["model"]))
    rows = [
        tuple(float(value) for value in row.split(","))
        for row in load_text(context.inputs["test"]).splitlines()[1:]
    ]
    indices = json.loads(load_text(context.inputs["holdout"]))
    pairs = [
        [model["weight"] * rows[index][0], rows[index][1]]
        for index in indices
    ]
    destination = context.outputs["predictions"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(pairs), encoding="utf-8")


@metric(metric_id="root_mean_squared_error", mode="stateless")
def root_mean_squared_error(context: MetricContext[MetricConfig]) -> float:
    pairs = json.loads(load_text(context.artifacts["predictions"]))
    if not pairs:
        raise ValueError("root_mean_squared_error requires at least one prediction")
    squared_errors = [(prediction - target) ** 2 for prediction, target in pairs]
    return (sum(squared_errors) / len(pairs)) ** 0.5


rmse = measure(
    root_mean_squared_error,
    dependencies=(
        MetricDependency(
            source="artifact", name="predictions", required_data_role="eval"
        ),
    ),
    comparator=FloatComparator(mode="absolute", tolerance=1e-12),
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
            path="predictions.json",
            loader=load_text,
            data_role="eval",
        )
    ),
    metrics=(rmse,),
    objective=min(rmse),
)
```

Add `evaluation` after `training` in the variant's stages. VIPER computes `rmse`
after `predict` has written the predictions file. The metric reads that saved
file again during verification.
The split's data role must match the test dataset's role. Use a predictions
role compatible with those inputs; benchmark data remains `benchmark`.

The [metrics guide](metrics-and-benchmarks.md) explains recomputation and how to
attach benchmark criteria to this evaluation.

## Add a diagnostic report

A diagnostic stage observes inputs and produces a report. Omit its objective.
Its outputs are terminal: downstream stages and the variant's estimator
must select outputs from other stage kinds.

```python
from viper.config import DiagnosticConfig
from viper.stages import diagnostic


@diagnostic(config=DiagnosticConfig)
def count_rows(context: Context[DiagnosticConfig]) -> None:
    rows = load_text(context.inputs["dataset"]).splitlines()[1:]
    destination = context.outputs["report"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"rows: {len(rows)}\n", encoding="utf-8")


report = stage(
    count_rows,
    config=DiagnosticConfig(),
    inputs={"dataset": prepared.outputs["dataset"]},
    outputs=StageOutputs(
        report=output(path="rows.txt", loader=load_text, data_role="training")
    ),
)
```

## Reuse a verified stage result

Set `reuse="verified"` in a workspace stage's `stage()` call to allow reuse.
The default is `reuse="never"`. Index the completed source run through
[`catalog-refresh`](catalog-knowledge-mcp.md#build-the-local-catalog) before
executing another plan that might reuse its stages.

VIPER looks for a candidate with matching stage, config, inputs, runtime,
randomness, and metric identities. A matching candidate is verified and its
artifacts are copied into the new run's snapshot; otherwise the stage executes.
The new run records whether each stage executed or reused earlier work. A
benchmark confirmation executes the candidate stages independently.
The [reuse acceptance test](../../tests/test_run_execution.py) checks that a
verified reuse skips the stage worker while preserving the new run's evidence.
