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
result: /path/to/viper/experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

Each execution receives a new run ID and writes its own result directory.

## Read the complete program

These four blocks form [cpu_quickstart.py](../../examples/cpu_quickstart.py).
The stage fits a linear model and records mean squared error from predictions
and targets.

### 1. Define the metric and output loaders

```python
"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
from pathlib import Path

from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    """Load and validate the terminal training state."""
    return load_resume_state(path)


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    """Compute mean squared error over matching predictions and targets."""
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)
```

### 2. Train the model and write its outputs

```python
@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    loss = 0.0
    epoch = 0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["mean_squared_error"].record(
            predictions, targets, epoch=epoch, step=epoch
        )
        loss = measurement.value
        errors = tuple(
            prediction - target for prediction, target in zip(predictions, targets)
        )
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient

    model = context.outputs["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    save_resume_state(
        context.outputs["resume_state"],
        ResumeState(
            optimizer_state={"weight": weight, "loss": loss},
            main_process_rng=capture_main_process_rng(
                context.numpy_generators,
                capture_legacy_global=True,
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"epoch": epoch},
            ),
        ),
    )
```

### 3. Declare the experiment

```python
mse = measure(mean_squared_error, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={
        "dataset": input(
            "examples/data/tiny.csv",
            data_role="training",
        )
    },
    outputs=TrainOutputs(
        model=output(
            path="model.json",
            loader=load_json,
            data_role="training",
        ),
        resume_state=output(
            path="resume_state.pt",
            loader=load_state,
            data_role="training",
        ),
    ),
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

### 4. Identify the source and run the experiment

`read_source()` returns the checked-out commit and the `origin` repository URL.
Omitting `reproducibility` selects reproducible execution.

```python
def main() -> None:
    """Run the training experiment with the default reproducible policy."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
```

Run the [policy example](../../examples/execution_policies.py) to select a policy
for the same training computation:

```bash
python examples/execution_policies.py reproducible
python examples/execution_policies.py relaxed
python examples/execution_policies.py custom
```

Only custom mode constructs the complete numerical settings. Its example uses
two intra-operation CPU threads and permits nondeterministic algorithms.

## Inspect the result

Open the printed `resolved.yaml`. It identifies the terminal status, the successful
attempt, and the immutable references that connect the result to its plan and produced
evidence. The model itself is under:

```text
experiments/cpu_quickstart/runs/baseline/<run-id>/artifacts/train/model/model.json
```

Both the example file and the Python blocks printed on this page are executed by
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
