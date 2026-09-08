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

The example prints a successful terminal status and the verified result it wrote:

```text
status: succeeded
model: {"weight": 1.999...}
result: experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

The [acceptance test](tests/test_readme_workflow.py) runs this file in a clean Git
repository and checks its status and output.

## Follow the execution

The complete [CPU quickstart](examples/cpu_quickstart.py) is one ordinary Python file.
It defines a metric and a training stage:

### Define a stage

```python
import json
from pathlib import Path

from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, metric
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    return load_resume_state(path)


@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    if not targets:
        raise ValueError("training_loss requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)


@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"].read_text(encoding="utf-8").splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["training_loss"].record(
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

`training_loss()` computes mean squared error from the predictions and targets
passed to `record()`. The call saves that value and returns a measurement; `.value`
gives the training loop the computed loss. `mode="stateless"` means each call
computes a fresh value. A stateful metric is a `StatefulMetric` class that
accumulates observations with `update()` and returns its current value from `compute()`.

The stage reads its config and input paths from `Context`, then writes to the supplied
output paths. Metric handles record measurements during the computation. VIPER manages
the run directory and records the produced files.
`TrainConfig` and `MetricConfig` are VIPER's built-in config records; this small example
uses their default settings. Training stages require both `model` and `resume_state`
outputs; the checkpoint stores the optimizer, random-generator, and data-loader state
needed for resumption.

### Connect the experiment

The same file connects the stage to one experiment variant and replicate:

```python
from viper.config import MetricConfig, TrainConfig
from viper.outputs import TrainOutputs, output
from viper.authoring import experiment, input, replicate, stage, variant
from viper.metrics import measure, min


loss = measure(training_loss, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={
        "dataset": input("examples/data/tiny.csv", data_role="training")
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
    metrics=(loss,),
    objective=min(loss),
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

Finally, `plan()` identifies the selected source commit and runtime. `execution.run()`
compiles that draft, runs the stage, and returns the verified terminal record:

```python
from viper import execution
from viper.authoring import plan

draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)

resolved_run = execution.run(root, draft)
print(resolved_run.status)
print(resolved_run.path)
```

The quickstart keeps the Git and reproducibility setup in small helper functions so the
experiment remains readable. Open the [complete source](examples/cpu_quickstart.py) to
see those exact values.

## What the run preserves

The terminal result connects one execution to the evidence needed to inspect it later:

```text
source commit
  + stage and metric implementations
  + config values and input identities
  + requested and observed runtime
  + artifact and measurement bytes
  + stage and attempt receipts
  = verified terminal run
```

Resolved file references carry a path, byte count, and SHA-256 digest. VIPER checks that
the plan, stages, inputs, artifacts, measurements, and terminal result belong to the
same run.

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
