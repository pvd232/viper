# Build your first VIPER experiment

This tutorial runs one small training experiment on your CPU. You will create a verified
run, inspect its output, and learn which parts of the workflow belong to your code and
which parts VIPER records.

## Install the repository

VIPER requires Python 3.11 or newer.

```bash
git clone https://github.com/pvd232/viper.git
cd viper
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[test]'
```

## Run the example

```bash
python examples/cpu_quickstart.py
```

The command fits a linear model, `y = weight * x`, to
[`examples/data/tiny.csv`](../../examples/data/tiny.csv) and prints:

```text
status: succeeded
model: {"weight": 1.999...}
result: experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

Each execution receives a new run ID and writes its own result directory.

## See the three pieces you authored

Open [`examples/cpu_quickstart.py`](../../examples/cpu_quickstart.py). The file contains
one metric, one stage, and one experiment.

### 1. The metric computes prediction error

```python
from viper.config import MetricConfig
from viper.metrics import MetricContext, metric


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)
```

The function computes mean squared error: square each prediction error and average
the results. The training loop passes its predictions and targets to
`context.metrics["mean_squared_error"].record(...)`. VIPER calls the function, saves the
returned value, and returns a measurement whose `.value` is the computed loss.

`stateless` means each call computes from its current inputs. A stateful metric
accumulates observations through `update()` and returns their combined result
from `compute()`.

### 2. The stage performs the scientific work

```python
from viper.config import TrainConfig
from viper.stages import Context, train


@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    rows = context.inputs["dataset"].read_text(encoding="utf-8")
    model = context.outputs["model"]
    # The complete example parses the rows, trains the model, records loss,
    # and writes the declared model and state artifacts.
```

Read the dataset through `context.inputs` and write the model through
`context.outputs`. Your function owns the computation. VIPER supplies those paths
and records the resulting files and measurements.

### 3. The experiment connects a stage to a variant and seed

```python
from viper.authoring import experiment, input, replicate, stage, variant
from viper.metrics import measure, min
from viper.outputs import TrainOutputs

mse = measure(mean_squared_error, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={"dataset": input("examples/data/tiny.csv", data_role="training")},
    outputs=TrainOutputs(...),
    metrics=(mse,),
    objective=min(mse),
)

study = experiment(
    experiment_id="cpu_quickstart",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training},
            estimator=training.outputs["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)
```

The ellipsis marks an abbreviated output declaration. The complete example declares both
output paths and selects the model as the variant's estimator.

## Follow the call that runs it

`plan()` creates an immutable Python draft tied to a Git commit, an observed
environment, and reproducibility settings. `execution.run()` compiles that draft into
protocol files, executes the stage, verifies the evidence, and returns the terminal
result.

```python
from viper import execution
from viper.authoring import plan

draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=_reproducibility(),
)

resolved_run = execution.run(root, draft)
print(resolved_run.status)
print(resolved_run.path)
```

`execution.run()` freezes the draft before starting the run. Use `freeze_run_plan()`
when you need to save the plan for later execution; the [batch
guide](../how-to/variants-and-replicates.md#expand-the-experiment) shows that workflow.

## Inspect the result

Open the printed `resolved.yaml`. It identifies the terminal status, the successful
attempt, and the immutable references that connect the result to its plan and produced
evidence. The model itself is under:

```text
experiments/cpu_quickstart/runs/baseline/<run-id>/artifacts/train/model/model.json
```

The example is guarded by
[`tests/test_readme_workflow.py`](../../tests/test_readme_workflow.py), which runs it in
a clean temporary Git repository and requires the output shown above.

## Make it yours

Change one thing at a time, then commit the changed source or data before running the
example again. VIPER checks the files against the selected commit.

1. Add a row to [`examples/data/tiny.csv`](../../examples/data/tiny.csv).
2. Change the learning rate or epoch count inside `fit()`.
3. Add another `variant()` with a different training stage or config.
4. Add another `replicate()` with a different seed.

Then continue with [metrics and benchmarks](../how-to/metrics-and-benchmarks.md) or
[variants and replicates](../how-to/variants-and-replicates.md).
