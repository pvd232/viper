# VIPER

VIPER is a Python library for reproducible ML experiments.

Declare an experiment in Python, then run it from a saved plan. VIPER checks the
completed run against that plan and keeps the evidence so you can inspect or
repeat the experiment later.

```text
Python experiment
      |
      v
immutable plan
      |
      v
execute on CPU or GPU
      |
      v
verified run evidence
      |
      +-- restore artifacts
      +-- compare and search runs
      +-- query through the CLI or MCP
```

## Run the CPU quickstart

VIPER requires Python 3.11 or newer. Clone the repository, create an isolated
environment, and run the CPU example:

```bash
git clone https://github.com/pvd232/viper.git
cd viper
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python examples/cpu_quickstart.py
```

The example prints the run status, learned weight, and result path:

```text
status: succeeded
model: {"weight": 1.999...}
result: /path/to/viper/experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

## Follow the execution

The following blocks form the complete [CPU quickstart](examples/cpu_quickstart.py).
Save them together as `examples/cpu_quickstart.py`, commit the file, and run it.

### Define the metric and training stage

VIPER calls the training function with a `Context`. It supplies the declared
input and output paths through `context.inputs` and `context.outputs`.
Attaching a metric to the stage makes it available by its `metric_id` through
`context.metrics`; calling `.record()` computes and saves a measurement.
See [the context attributes](docs/how-to/stages.md#use-the-stage-context).

The metric function receives a separate `MetricContext` containing its own
config and file paths. Mean squared error uses the supplied predictions and
targets, so it leaves that argument unused as `_context`.

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

### Declare the experiment

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

### Run the experiment

`read_source()` identifies the checked-out commit and repository URL.
`plan()` uses the reproducible policy by default.

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

The complete [policy example](examples/execution_policies.py) runs the same
experiment with `reproducible`, `relaxed`, or `custom` settings. Relaxed permits
nondeterministic algorithms. Verification checks each run against its own plan;
comparing artifacts from two runs is a separate operation.

## What the run preserves

Each run saves its plan and the files produced by its stages. The records identify
which source commit and input data were used. They also record the runtime
settings requested by the plan and read from the workers.

VIPER checks saved files against their recorded hashes when verifying or
restoring a run. See [How VIPER works](docs/explanation/how-viper-works.md) for
how the plan, execution, and result fit together.

## Start your own workspace

Generate a workspace with example stages and tests:

```bash
viper init my-workspace --package my_workspace
cd my-workspace
python -m pip install -e '.[test]'
python -m pytest -q
```

Commit the workspace before authoring a plan. The commit identifies the exact source
used by the run.

## Continue a workflow

Continue from a saved plan or run result:

| Goal | Public interface | Guide |
| --- | --- | --- |
| Author and execute a plan | `viper.authoring.plan()` and `viper.execution.run()` | [Get started](docs/tutorials/getting-started.md) |
| Connect stage inputs and outputs | `viper.authoring.stage()` | [Compose stages](docs/how-to/stages.md) |
| Execute a batch and handle failures | `viper.execution.run_many()` | [Execution outcomes](docs/how-to/execution.md) |
| Retry a failed run | `viper.execution.retry()` or `viper retry` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Confirm a benchmark | `viper.execution.benchmark()` | [Metrics and benchmarks](docs/how-to/metrics-and-benchmarks.md) |
| Restore verified artifacts | `viper.execution.restore()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Inspect lineage or compare runs | `viper lineage` and `viper compare-runs` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Search completed measurements | `viper catalog-refresh` and `viper search-measurements` | [Catalog, knowledge, and MCP](docs/how-to/catalog-knowledge-mcp.md) |
| Give an agent typed access | `viper mcp --root .` | [How VIPER works](docs/explanation/how-viper-works.md) |

Place `--json` before a CLI command when another program needs one typed result
document:

```bash
viper --json verify-run path/to/resolved.yaml \
  --trust-source https://github.com/example/my-workspace
```

## Documentation

Use the [documentation home](docs/README.md) to choose a tutorial, a task-focused guide,
an explanation, or reference material.

- New to VIPER: [build and run the CPU quickstart](docs/tutorials/getting-started.md).
- Solving a specific task: open the [how-to guides](docs/README.md#how-to-guides).
- Understanding the evidence model: read [how VIPER works](docs/explanation/how-viper-works.md).
- Looking up an interface: open the [reference index](docs/reference/README.md).
- Changing VIPER itself: read [Contributing](CONTRIBUTING.md).

## License

VIPER is licensed under the [Apache License 2.0](LICENSE).
