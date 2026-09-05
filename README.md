# VIPER

Run reproducible ML experiments with machine-readable evidence for people and
agents.

VIPER freezes an experiment before execution, records the files and
measurements produced by each stage, and verifies the completed run against
the frozen plan. The same verified records support artifact restoration,
cross-run search, scientific annotations, and a local MCP server.

```text
project code + experiment
            |
            v
       frozen plan
            |
            v
    execute and record
            |
            v
      verified result
       /     |      \
      v      v       v
 restore  catalog   MCP
```

## Install

VIPER requires Python 3.11 or newer.

```bash
python -m pip install viper-provenance
```

Create a project and install its test dependencies:

```bash
viper init my-project --package my_project
cd my-project
python -m pip install -e '.[test]'
python -m pytest -q
```

The generated project contains one decorated function for each stage kind,
project-owned parameter models, artifact loaders, a metric, and directories
for experiments and benchmarks.

## A complete workflow

Here is the shape of a small VIPER project: one training function, one metric,
and one experiment with two variants and two seeds. The scientific code stays
ordinary Python. VIPER supplies the paths, records what happened, and verifies
the result.

### Define a stage

Put the project-owned computation in a normal Python module:

```python
from pathlib import Path

from my_project.training import train_model
from viper import parameters
from viper.metrics import MetricContext, measure, metric, min
from viper.stages import Context, train


def load_bytes(path: Path) -> bytes:
    """Load one saved model or checkpoint."""

    return path.read_bytes()


class TrainParameters(parameters.Train):
    """Values that distinguish one training run from another."""

    epochs: int
    learning_rate: float


@metric(metric_id="training_loss", mode="live")
def training_loss(
    _context: MetricContext[parameters.Metric],
    losses: list[float],
) -> float:
    """Return the final loss recorded by the training loop."""

    return losses[-1]


@train(params=TrainParameters)
def fit(context: Context[TrainParameters]) -> None:
    """Train one model using inputs and outputs allocated by VIPER."""

    dataset: Path = context.inputs["dataset"]
    model: Path = context.artifacts["model"]
    state: Path = context.artifacts["state"]
    losses = train_model(
        dataset=dataset,
        model=model,
        state=state,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
    context.metrics["training_loss"].record(losses)
```

`Context` contains the validated parameters, materialized input paths, writable
artifact paths, metric handles, and named random generators for this attempt.
VIPER chooses the run directory and output identity for the function.

### Connect the experiment

The authoring module connects those pieces into an experiment. This example
compares two learning rates and repeats each choice under two seeds:

```python
from my_project.benchmarks import benchmark_definition
from my_project.settings import environment, reproducibility, source
from my_project.training import TrainParameters, fit, load_bytes, training_loss
from viper.artifacts import artifact
from viper.authoring import (
    experiment,
    factor,
    input,
    plan,
    replicate,
    stage,
    variant,
)
from viper.metrics import measure, min


loss = measure(training_loss)
dataset = input(path="inputs/dataset.csv", data_role="training")


def training(learning_rate: float):
    """Build one training stage for a selected learning rate."""

    return stage(
        fit,
        params=TrainParameters(epochs=20, learning_rate=learning_rate),
        inputs={"dataset": dataset},
        artifacts={
            "model": artifact(
                path="artifacts/model.bin",
                loader=load_bytes,
                data_role="model",
            ),
            "state": artifact(
                path="artifacts/state.bin",
                loader=load_bytes,
                data_role="checkpoint",
            ),
        },
        metrics=(loss,),
        objective=min(loss),
    )


baseline = training(1e-3)
fast = training(3e-3)
study = experiment(
    experiment_id="learning_rate_demo",
    factors={"learning_rate": factor(levels=("baseline", "fast"))},
    variants={
        "baseline": variant(
            levels={"learning_rate": "baseline"},
            stages={"train": baseline},
            estimator=baseline.artifacts["model"],
        ),
        "fast": variant(
            levels={"learning_rate": "fast"},
            stages={"train": fast},
            estimator=fast.artifacts["model"],
        ),
    },
    replicates={
        "seed_7": replicate(seed=7),
        "seed_11": replicate(seed=11),
    },
)

draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
    benchmark=benchmark_definition,
)
```

`source`, `environment`, and `reproducibility` are project settings that pin
the Git revision, Python environment, and numerical controls. The
[getting-started guide](docs/tutorials/getting-started.md) explains each one.

`viper.authoring.plan()` returns an immutable draft with a generated run ID.
`viper.execution.run()` is the public handoff: it compiles the draft into
canonical YAML before starting the first stage.

### Run it from Python

Commit the project code first so the plan can identify the exact source it
uses. Then pass the draft directly to `viper.execution.run()`:

```bash
git add .
git commit -m "Define learning-rate experiment"
```

```python
from pathlib import Path

from viper import execution


root = Path.cwd()
result = execution.run(root, draft)

print(result.resolved_run.status)
print(result.resolved_run_path)
```

One call now covers the normal user journey:

```text
Python experiment
  -> immutable plan files
  -> preflight
  -> stages in dependency order
  -> terminal verification
  -> resolved run
```

The generated plan remains reusable. Run it again from a shell when that is
more convenient:

```bash
viper run path/to/spec.yaml --root .
```

### Confirm, restore, and inspect

If the plan includes a benchmark, run its independent confirmation against the
verified result:

```python
benchmark_result = execution.benchmark(
    root,
    result.resolved_run_path,
    root / f"benchmarks/{benchmark_definition.benchmark_id}.spec.yaml",
)
print(benchmark_result.result.status)
```

Restore a verified artifact directly from the stored run evidence:

```python
from viper.restoration import ArtifactRestoreSelector


restored = execution.restore(
    root,
    result.resolved_run_ref,
    artifacts=(
        ArtifactRestoreSelector(stage_id="train", artifact_name="model"),
    ),
    output=root / "restored",
)
print(restored.artifacts[0].files[0].path)
```

The CLI exposes the same records to people, scripts, and agents:

```bash
viper --json verify-run path/to/resolved.yaml \
  --trust-source https://github.com/example/my-project
viper --json lineage path/to/resolved.yaml \
  --trust-source https://github.com/example/my-project
```

Place `--json` before the command whenever a program or agent needs one typed
result document.

### Search completed runs

The catalog is a disposable SQLite index over immutable run records. Refresh
it from one or more verified results:

```bash
viper catalog-refresh \
  path/to/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/my-project
```

Query the resulting measurements:

```bash
viper --json search-measurements \
  --root . \
  --query '{"metric_ids":["test_loss"]}'
```

VIPER writes the derived index to `.viper/catalog.sqlite3`. The immutable run
evidence remains intact when the index is deleted, and refresh rebuilds the
index from those verified records.

### Add scientific context or agent access

After verification, a project can publish versioned primitive definitions,
assignments, controlled comparisons, effects, impact assessments, diagnostic
signatures, and journal assertions. These records cite immutable run or
measurement references and preserve the original evidence.

Refresh the knowledge projection and search one primitive:

```bash
viper knowledge refresh --root .

viper --json knowledge search search_primitives \
  --root . \
  --query '{"primitive_ids":["gated-recurrence"]}'
```

Exact filters are authoritative. Vector similarity ranks records within one
declared vector view. Exact identities and reviewed equivalence determine
experimental identity and duplicate evidence.

Start the local MCP server when an agent needs the same typed operations:

```bash
viper mcp --root .
```

Read mode exposes validation, verification, catalog, lineage, comparison, and
knowledge-search operations. Execution and publication require explicit
access:

```bash
viper mcp --root . --access execute
```

The CLI and MCP server both dispatch through the same typed API registry, so
they validate the same request models and return the same result models.

## What VIPER preserves

For one completed run, VIPER connects:

```text
Git commit
  + frozen stage and parameter definitions
  + input file identities
  + observed execution environment
  + stage snapshots
  + artifacts and measurements
  = verifiable terminal run
```

Each referenced file carries its path, byte count, and SHA-256 digest. VIPER
checks that stages, artifacts, measurements, and benchmark results belong to
the same run. Verification reruns metrics marked for recomputation against
verified files. Model training executes once during the original run.

Evidence can remain in the project-local immutable store or be published to a
configured immutable Hugging Face repository. Catalogs and vector indexes are
derived views and can be rebuilt.

## Continue reading

- [Get started](docs/tutorials/getting-started.md)
- [Python and CLI API](docs/reference/api.md)
- [How VIPER works](docs/explanation/how-viper-works.md)
- [Formal protocol](docs/reference/protocol.md)
- [Versioning policy](docs/reference/versioning.md)
- [Contributing](CONTRIBUTING.md)

## License

VIPER is licensed under the [Apache License 2.0](LICENSE).
