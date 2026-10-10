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

VIPER calls the training function with a `StageContext`. It supplies the declared
input and output paths through `context.inputs` and `context.outputs`.
Attaching a metric to the stage makes it available by its `metric_id` through
`context.metrics`; calling `.record()` computes and saves a measurement.
See [the context attributes](docs/how-to/stages.md#use-the-stage-context).

Every metric function must accept a `MetricContext` as its first argument.
VIPER supplies it with the metric's settings and file paths. The training
function supplies predictions and targets through `.record()`. This MSE
calculation needs only those numbers, so `_context` marks the required context
argument as unused. Metrics that read saved predictions use the context to
locate those files. The [metric guide](docs/how-to/metrics-and-benchmarks.md)
shows both approaches, with complete training and saved-prediction examples.

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
from viper.restoration import ArtifactRestoreSelector
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import StageContext, train


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
def fit(context: StageContext[TrainConfig]) -> None:
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
mse = measure(mean_squared_error)
training = stage(
    fit,
    stage_id="train",
    inputs=(input("dataset", path="examples/data/tiny.csv", data_role="training"),),
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
    variants=(
        variant(
            "baseline",
            stages=(training,),
            estimator=training.outputs["model"],
        ),
    ),
    replicates=(replicate(seed=7),),
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
        source=source,
        env=environment,
    )
    resolved_run = execution.run(draft)
    restored = execution.restore(
        Path.cwd(),
        resolved_run.reference,
        artifacts=(ArtifactRestoreSelector(stage_id="train", artifact_name="model"),),
        output=Path.cwd() / "restored" / f"{draft.run_id}.json",
    )
    model_path = restored.artifacts[0].files[0].path
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

Generate a separate workspace with example stages and tests. From the installed
checkout above, keep the new project outside VIPER's Git repository:

```bash
cd ..
viper init my-workspace --package my_workspace
cd my-workspace
python -m venv .venv
source .venv/bin/activate
python -m pip install viper-provenance
python -m pip install -e '.[test]'
python -m pytest -q
git init
git remote add origin https://github.com/YOUR_ACCOUNT/my-workspace.git
git add .
git commit -m "Initialize VIPER workspace"
```

Replace the remote URL with your workspace's HTTP(S) repository URL. Install
`viper-provenance[mcp]` for MCP. The Google Cloud Storage client is a base
dependency; the `[gcs]` extra remains accepted. The new workspace keeps its own
environment and source history.

Replace the generated stage templates with your model's implementation and commit
the changes before authoring a plan. The generated checkpoint loader reconstructs
saved state; it does not invent optimizer or RNG values. The commit identifies the
exact source used by the run.

## Continue a workflow

Continue from a saved plan or run result:

| Goal | Public interface | Guide |
| --- | --- | --- |
| Author and execute a plan | `viper.authoring.plan()` and `viper.execution.run()` | [Get started](docs/tutorials/getting-started.md) |
| Connect stage inputs and outputs | `viper.authoring.stage()` | [Compose stages](docs/how-to/stages.md) |
| Execute a batch and handle failures | `viper.execution.run_many()` | [Execution outcomes](docs/how-to/execution.md) |
| Retry a failed run | `viper.execution.retry()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Confirm a benchmark | `viper.execution.benchmark()` | [Metrics and benchmarks](docs/how-to/metrics-and-benchmarks.md) |
| Restore verified artifacts | `viper.execution.restore()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Reference a completed local run | `viper.execution.resolve_run_reference()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Inspect lineage or compare runs | `viper.api.lineage()` and `viper.api.compare_runs()` | [Retry, restore, and compare](docs/how-to/retry-restore-compare.md) |
| Search completed measurements | `viper.api.catalog_refresh()` and `catalog().measurements()` | [Catalog, knowledge, and MCP](docs/how-to/catalog-knowledge-mcp.md) |
| Reuse verified stages or force computation | `stage(reuse="never")` overrides default verified reuse | [Reuse example](examples/reuse.py) |
| Publish and search measured knowledge | `knowledge()` and `catalog().knowledge` | [Measured vector search](docs/tutorials/knowledge-search.md) |
| Capture structured journals and learned vectors | Default-on `JOURNAL.md` capture; `api.publish_run_journal()` for later edits | [Complete journal workflow](docs/how-to/journals.md) |
| Export a portable evidence graph | `execution.export_run()` and `execution.verify_run_bundle()` | [Export example](examples/export_run.py) |
| Publish, promote, restore, and retain cloud runs | `execution.promote_run_to_cloud()` and `retention.evict_cloud_backed_run_files()` | [Cloud storage](docs/how-to/cloud-storage.md) |
| Give an agent typed access | `viper mcp --root .` | [Agent interface](docs/reference/agents.md) |

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
- Connecting an agent: read the [agent interface](docs/reference/agents.md) or [navigation index](llms.txt).
- Changing VIPER itself: read [Contributing](CONTRIBUTING.md).

## License

VIPER is licensed under the [Apache License 2.0](LICENSE).
