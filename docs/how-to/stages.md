# Compose stages

A stage is a function with declared inputs and outputs. Connect stages by
passing an earlier stage's output to a later stage's input.

The [complete pipeline](../tutorials/stages.md) connects preparation, feature
computation, training, and diagnostics. The snippets below explain those stage
functions; the tutorial includes all imports, declarations, and the entry point.

## Use the stage context

When VIPER executes a stage, it constructs a `Context` and passes it as the
function's first argument. You declare the inputs, outputs, metrics, and config
with `stage()`; VIPER supplies their runtime values through that argument.
For example, `sort_rows(context: Context[BuildConfig])` below receives a
validated `BuildConfig` as `context.config`.

| Attribute | Value supplied to the stage |
| --- | --- |
| `config` | Validated settings from `stage(config=...)`, using the config class named in the decorator. |
| `inputs` | Mapping from the names in `stage(inputs=...)` to local `Path` objects for those files. Read input files through these paths. |
| `outputs` | Mapping from the names in the stage's output declaration to destination `Path` objects. VIPER creates the parent directories; your function writes the files. |
| `metrics` | Mapping from each attached stage-recorded metric's `metric_id` to a `MetricHandle`. Call its `record()` method to compute and save a measurement. Metrics configured for recomputation run separately. |
| `numpy_generators` | Mapping from generator names in the run's reproducibility settings to initialized NumPy generators. Use these generators for random sampling and checkpoint their state when saving training progress. |
| `run_id` | Identifier of the run being executed. |
| `attempt_id` | Attempt number within that run; retries receive a new attempt number. |
| `stage_id` | Name assigned to this stage in the variant's `stages` tuple. |

The dictionary keys come from your declarations. In the build example below,
an input named `source` supplies `context.inputs["source"]`, and
`StageOutputs(dataset=...)` supplies `context.outputs["dataset"]`.
A lookup using an undeclared name raises `KeyError`.

Metric functions receive a separate `MetricContext`, described in
[metrics and benchmarks](metrics-and-benchmarks.md#use-the-metric-context).

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
from examples.workflow_functions import load_text

from viper.authoring import input, stage
from viper.config import BuildConfig
from viper.outputs import StageOutputs, output
from viper.stages import Context, build


@build(config=BuildConfig)
def sort_rows(context: Context[BuildConfig]) -> None:
    header, *rows = load_text(context.inputs["source"]).splitlines()
    destination = context.outputs["dataset"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join([header, *sorted(rows)]) + "\n", encoding="utf-8")


prepared = stage(
    sort_rows,
    stage_id="prepare",

    inputs=(input("source", path="examples/data/tiny.csv", data_role="training"),),
    outputs=StageOutputs(
        dataset=output(path="sorted.csv", loader=load_text, data_role="training")
    ),
)
```

The local input is captured for the run. The output loader describes how to
read the resulting artifact; the stage itself writes the file.

## Connect an embedding stage

This example imports the CSV preparation stage as `prepared` from the
[pipeline example](../../examples/stages.py). It turns each selected value into
two features: the value and its square.

```python
import json

from examples.stages import prepared
from examples.workflow_functions import load_text
from viper.authoring import stage
from viper.config import EmbedConfig
from viper.outputs import StageOutputs, output
from viper.stages import Context, embed


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
    stage_id="embed",
    inputs=(prepared.outputs["dataset"],),
    outputs=StageOutputs(
        features=output(path="features.json", loader=load_text, data_role="training")
    ),
)
```

Include `prepared` before `embedded` in the variant's `stages` tuple. During
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

The [pipeline's training declaration](../../examples/stages.py) imports the
quickstart's training function and connects it to the sorted CSV output.

## Evaluate against saved test data

An evaluation stage consumes a `model`, a `test` dataset, and at least one named
split. The test and splits must be artifacts from a completed run with data
role `eval` or `benchmark`. The model can come from an earlier stage in the
current run or a completed run.

Run the complete [evaluation example](../../examples/evaluation.py) from the
repository root:

```bash
python -m examples.evaluation
```

It first trains a baseline and publishes test data and split indices in a separate run, then trains
and evaluates the model, and finally executes the benchmark confirmation.
The printed `data`, `result`, and `benchmark` paths identify each saved result.

`evaluation_stage(test_data, test_split)` below accepts two artifacts from a
completed run: a CSV with an `x,y` header and a JSON list of row indices such
as `[0, 2]`. It imports `training` from the CPU quickstart. The complete
[evaluation example](../../examples/evaluation.py) creates the test artifacts
and calls this function.

The returned stage connects the model to its metric:

| Declaration | Connection |
| --- | --- |
| `training.outputs["model"]` in `inputs` | Supplies the training stage's model to `predict`. |
| `predictions` in `EvalOutputs` | Names the file where `predict` writes `[prediction, target]` pairs. |
| `metrics=(rmse,)` | Attaches RMSE to this evaluation stage. |
| `name="predictions"` in `MetricDependency` | Selects this stage's output for the metric's `context.artifacts`. |

The variant contains both stages. Each has a `stage_id`; output names such as
`model` and `predictions` belong to their stage. The run identifies the execution
that produced the files.

```python
import json

from examples.cpu_quickstart import training
from examples.workflow_functions import load_text
from viper.authoring import StageDraft, input, stage
from viper.benchmark import RunArtifactDraft
from viper.config import EvalConfig, MetricConfig
from viper.metrics import (
    FloatComparator, MetricContext, MetricDependency, measure, metric, min,
)
from viper.outputs import EvalOutputs, output
from viper.stages import Context, eval


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
    """Read predict's saved [prediction, target] pairs and return their RMSE."""
    pairs = json.loads(load_text(context.artifacts["predictions"]))
    if not pairs:
        raise ValueError("root_mean_squared_error requires at least one prediction")
    squared_errors = [(prediction - target) ** 2 for prediction, target in pairs]
    return (sum(squared_errors) / len(pairs)) ** 0.5


rmse = measure(
    root_mean_squared_error,
    dependencies=(
        MetricDependency(
            source="artifact", name="predictions", data_role="benchmark"
        ),
    ),
    comparator=FloatComparator(mode="absolute", tolerance=1e-12),
)

def evaluation_stage(
    test_data: RunArtifactDraft, test_split: RunArtifactDraft
) -> StageDraft:
    """Evaluate the trained model against saved test rows and split indices."""
    return stage(
        predict,
        stage_id="eval",

        eval_id="holdout",
        inputs=(
            training.outputs["model"],
            input("test", source=test_data),
            input("holdout", source=test_split),
        ),
        split_inputs=("holdout",),
        outputs=EvalOutputs(
            predictions=output(
                path="predictions.json",
                loader=load_text,
                data_role="benchmark",
            )
        ),
        metrics=(rmse,),
        objective=min(rmse),
    )
```

Call `evaluation_stage(test_data, test_split)` and place its result after
`training` in the variant's stages, as the complete example does. VIPER computes `rmse`
after `predict` has written the predictions file. The metric reads that saved
file again during verification.
The split's data role must match the test dataset's role. Use a predictions
role compatible with those inputs; benchmark data remains `benchmark`.

Include the [benchmark declaration](metrics-and-benchmarks.md#add-benchmark-criteria)
in the plan, as the complete example does. For an evaluation-only run, use
stored inputs with the `eval` role and set both the prediction role and the
metric dependency's required role to `eval`.

## Add a diagnostic report

A diagnostic stage observes inputs and produces a report. Omit its objective.
Its outputs are terminal: downstream stages and the variant's estimator
must select outputs from other stage kinds.

```python
from examples.stages import prepared
from examples.workflow_functions import load_text
from viper.authoring import stage
from viper.config import DiagnosticConfig
from viper.outputs import StageOutputs, output
from viper.stages import Context, diagnostic


@diagnostic(config=DiagnosticConfig)
def count_rows(context: Context[DiagnosticConfig]) -> None:
    rows = load_text(context.inputs["dataset"]).splitlines()[1:]
    destination = context.outputs["report"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"rows: {len(rows)}\n", encoding="utf-8")


report = stage(
    count_rows,
    stage_id="report",

    inputs=(prepared.outputs["dataset"],),
    outputs=StageOutputs(
        report=output(path="rows.txt", loader=load_text, data_role="training")
    ),
)
```

## Reuse a verified stage result

The [complete recovery example](../../examples/recovery.py) demonstrates a
successful retry followed by reuse in a new run.

Set `reuse="verified"` in a workspace stage's `stage()` call to allow reuse.
The default is `reuse="never"`. Index the completed source run through
[the Python catalog refresh](catalog-knowledge-mcp.md#build-the-local-catalog) before
executing another plan that might reuse its stages.

VIPER looks for a candidate with matching stage, config, inputs, runtime,
randomness, and metric identities. A matching candidate is verified and its
artifacts are copied into the new run's snapshot; otherwise the stage executes.
The new run records whether each stage executed or reused earlier work. A
benchmark confirmation executes the candidate stages independently.
