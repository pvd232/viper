# VIPER

Run reproducible ML experiments and keep machine-readable evidence of what
actually happened.

VIPER turns a Python experiment into an immutable run plan, executes each stage,
records its source, inputs, environment, artifacts, and measurements, then
verifies the terminal result. People, scripts, and agents can inspect the same
evidence.

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
environment, and run the checked example:

```bash
git clone https://github.com/pvd232/viper.git
cd viper
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python examples/cpu_quickstart.py
```

The example prints a successful terminal status and the verified result it
wrote:

```text
status: succeeded
model: {"weight": 1.999...}
result: experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

This is an executed example. The
[acceptance test](tests/test_readme_workflow.py) runs the same file in a clean
Git repository and requires the successful result above.

## Follow the execution

The complete [CPU quickstart](examples/cpu_quickstart.py) is one ordinary Python
file. It defines a metric and a training stage:

### Define a stage

```python
import json
from pathlib import Path

from viper import params
from viper.metrics import MetricContext, metric
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    return json.loads(path.read_text(encoding="utf-8"))


@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[params.Metric],
    loss: float,
) -> float:
    return loss


@train(params=params.Train)
def fit(context: Context[params.Train]) -> None:
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"].read_text(encoding="utf-8").splitlines()[1:]
    ]
    weight = 0.0
    for epoch in range(1, 21):
        errors = tuple(weight * x - y for x, y in rows)
        loss = sum(error**2 for error in errors) / len(rows)
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient
        context.metrics["training_loss"].record(loss, epoch=epoch, step=epoch)

    model = context.artifacts["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    context.artifacts["state"].write_text(
        json.dumps({"epoch": epoch, "loss": loss}) + "\n",
        encoding="utf-8",
    )
```

`mode="stateless"` means `training_loss()` computes each value directly from
the arguments passed to `record()`. A stateful metric is a `StatefulMetric`
class that accumulates observations with `update()` and returns its current
value from `compute()`.

`Context` gives the stage its validated parameters, materialized input paths,
writable artifact paths, metric handles, run identity, and named random
generators. The stage owns the scientific computation. VIPER owns the run
directory and records the produced files. `params.Train` and `params.Metric`
are VIPER's built-in parameter records; this small example uses their default
settings.

### Connect the experiment

The same file connects the stage to one experiment variant and replicate:

```python
from viper import params
from viper.artifacts import artifact
from viper.authoring import experiment, input, replicate, stage, variant
from viper.metrics import measure, min


loss = measure(training_loss, params=params.Metric())
training = stage(
    fit,
    params=params.Train(),
    inputs={
        "dataset": input("examples/data/tiny.csv", data_role="training")
    },
    artifacts={
        "model": artifact(
            path="artifacts/models/tiny/model.json",
            loader=load_json,
            data_role="training",
        ),
        "state": artifact(
            path="artifacts/models/tiny/state.json",
            loader=load_json,
            data_role="training",
        ),
    },
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

Finally, `plan()` identifies the selected source commit and runtime.
`execution.run()` compiles that draft, runs the stage, and returns the verified
terminal record:

```python
draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)

result = execution.run(root, draft)
print(result.resolved_run.status)
print(result.resolved_run_path)
```

The quickstart keeps the Git and reproducibility setup in small helper
functions so the experiment remains readable. Open the
[complete source](examples/cpu_quickstart.py) to see those exact values.

## What the run preserves

The terminal result connects one execution to the evidence needed to inspect
it later:

```text
source commit
  + stage and metric implementations
  + parameter values and input identities
  + requested and observed runtime
  + artifact and measurement bytes
  + stage and attempt receipts
  = verified terminal run
```

Every referenced file carries its path, byte count, and SHA-256 digest. VIPER
checks that the plan, stages, inputs, artifacts, measurements, and terminal
result belong to the same run.

## Start your own project

Generate a project with decorated build, embed, train, and evaluation stages,
project-owned parameters, artifact loaders, and focused tests:

```bash
viper init my-project --package my_project
cd my-project
python -m pip install -e '.[test]'
python -m pytest -q
```

Commit the project before authoring a plan. The commit identifies the exact
source used by the run.

## Continue a workflow

Each workflow starts from a verified run or an immutable plan:

| Goal | Public interface | Guide |
| --- | --- | --- |
| Author and execute a plan | `viper.authoring.plan()` and `viper.execution.run()` | [Get started](docs/tutorials/getting-started.md) |
| Retry a failed run | `viper.execution.retry()` or `viper retry` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Confirm a benchmark | `viper.execution.benchmark()` | [How VIPER works](docs/explanation/how-viper-works.md) |
| Restore verified artifacts | `viper.execution.restore()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Inspect lineage or compare runs | `viper lineage` and `viper compare-runs` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Search completed measurements | `viper catalog-refresh` and `viper search-measurements` | [Catalog, knowledge, and MCP](docs/how-to/catalog-knowledge-mcp.md) |
| Give an agent typed access | `viper mcp --root .` | [How VIPER works](docs/explanation/how-viper-works.md) |

Place `--json` before a CLI command when another program needs one typed result
document:

```bash
viper --json verify-run path/to/resolved.yaml \
  --trust-source https://github.com/example/my-project
```

## Documentation

Use the [documentation home](docs/README.md) to choose a tutorial, a task-focused
guide, an explanation, or reference material.

- New to VIPER: [build and run the CPU quickstart](docs/tutorials/getting-started.md).
- Solving a specific task: open the [how-to guides](docs/README.md#how-to-guides).
- Understanding the evidence model: read [how VIPER works](docs/explanation/how-viper-works.md).
- Looking up an interface: open the [reference index](docs/reference/README.md).
- Changing VIPER itself: read [Contributing](CONTRIBUTING.md).

## License

VIPER is licensed under the [Apache License 2.0](LICENSE).
