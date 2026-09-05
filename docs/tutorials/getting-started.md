# Build your first VIPER experiment

This tutorial runs one small training experiment on your CPU. You will create a
verified run, inspect its output, and learn which parts of the workflow belong
to your code and which parts VIPER records.

## Install the repository

VIPER requires Python 3.11 or newer.

```bash
git clone https://github.com/pvd232/viper.git
cd viper
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[test]'
```

## Run the checked example

```bash
python examples/cpu_quickstart.py
```

The command fits a one-parameter model to
[`examples/data/tiny.csv`](../../examples/data/tiny.csv) and prints:

```text
status: succeeded
model: {"weight": 1.999...}
result: experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

The exact run ID changes on each execution. The successful status and the
verified result file do not.

## See the three pieces you authored

Open [`examples/cpu_quickstart.py`](../../examples/cpu_quickstart.py). The file
contains one metric, one stage, and one experiment.

### 1. The metric names a measurement

```python
@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[params.Metric],
    loss: float,
) -> float:
    return loss
```

The training loop already computes `loss`. This stateless metric validates and
returns each supplied value. A stateful metric instead owns accumulated state:
it subclasses `StatefulMetric`, receives observations through `update()`, and
returns the current value from `compute()`.

### 2. The stage performs the scientific work

```python
@train(params=params.Train)
def fit(context: Context[params.Train]) -> None:
    rows = context.inputs["dataset"].read_text(encoding="utf-8")
    model = context.artifacts["model"]
    # The complete example parses the rows, trains the model, records loss,
    # and writes the declared model and state artifacts.
```

`Context` supplies the stage's validated parameters, readable input paths,
writable artifact paths, metric handles, run identity, and random generators.
Your function owns the model computation. VIPER owns the paths and records the
files and measurements produced there.

### 3. The experiment connects a stage to a variant and seed

```python
loss = measure(training_loss, params=params.Metric())
training = stage(
    fit,
    params=params.Train(),
    inputs={"dataset": input("examples/data/tiny.csv", data_role="training")},
    artifacts={...},
    metrics=(loss,),
    objective=min(loss),
)

study = experiment(
    experiment_id="cpu_quickstart",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training},
            estimator=training.artifacts["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)
```

The ellipses shorten the excerpt; they are not copied into the runnable file.
The complete example declares both artifact paths and selects the model as the
variant's estimator.

## Follow the call that runs it

`plan()` creates an immutable Python draft tied to a Git commit, an observed
environment, and reproducibility settings. `execution.run()` compiles that
draft into protocol files, executes the stage, verifies the evidence, and
returns the terminal result.

```python
draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=_reproducibility(),
)

result = execution.run(root, draft)
```

There is no separate public freeze step in this workflow. Freezing is the first
operation performed by `execution.run()` when it receives a `RunPlanDraft`.

## Inspect the result

Open the printed `resolved.yaml`. It identifies the terminal status, the
successful attempt, and the immutable references that connect the result to its
plan and produced evidence. The model itself is under:

```text
experiments/cpu_quickstart/runs/baseline/<run-id>/artifacts/models/tiny/model.json
```

The example is guarded by
[`tests/test_readme_workflow.py`](../../tests/test_readme_workflow.py), which
runs it in a clean temporary Git repository and requires the output shown above.

## Make it yours

Change one thing at a time:

1. Add a row to `examples/data/tiny.csv` and rerun the example.
2. Change the learning rate or epoch count inside `fit()`.
3. Add another `variant()` with a different training stage or parameter set.
4. Add another `replicate()` with a different seed.

Then continue with [metrics and benchmarks](../how-to/metrics-and-benchmarks.md)
or [variants and replicates](../how-to/variants-and-replicates.md).
