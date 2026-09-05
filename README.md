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

**Repository-derived example.** The names below describe one small training
run. The commands and interfaces match the current public implementation;
replace the example model and paths with your project values.

### Define a stage

VIPER owns validation, paths, execution records, and verification. Your
project function owns the scientific computation.

```python
from pathlib import Path

from my_project.training import train_model
from viper import parameters
from viper.stages import Context, train


class TrainParameters(parameters.Train):
    """Configure one training run."""

    epochs: int
    learning_rate: float


@train(params=TrainParameters)
def fit(context: Context[TrainParameters]) -> None:
    """Train one model using paths allocated by VIPER."""

    dataset: Path = context.inputs["dataset"]
    weights: Path = context.artifacts["parameters"]
    train_model(
        dataset=dataset,
        weights=weights,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

The stage context carries validated parameters, materialized input paths,
writable artifact paths, metric handles, and named random generators. The
stage writes model state to `context.artifacts["parameters"]`; VIPER records
that file after the function returns.

### Author the experiment

Use the Python authoring interface to connect stage functions, inputs,
artifacts, metrics, variants, and replicates. `viper.authoring.plan()` returns
an immutable draft. `viper.execution.run()` compiles that draft into canonical
files before starting the first attempt.

For this example, the frozen plan appears at:

```text
experiments/example/runs/baseline/run-001/spec.yaml
```

Commit the project before execution. The plan records the Git commit that owns
the selected stage, parameter, metric, and loader definitions.

```bash
git add .
git commit -m "Define baseline experiment"
```

### Check and run the frozen plan

Preflight checks the selected source, inputs, environment, and implementation
references before training begins:

```bash
viper preflight \
  experiments/example/runs/baseline/run-001/spec.yaml \
  --root .
```

Run the complete plan:

```bash
viper run \
  experiments/example/runs/baseline/run-001/spec.yaml \
  --root .
```

`viper run` executes every stage in dependency order and verifies the terminal
result before reporting success. The result identifies the generated
`resolved.yaml`, which records the completed attempt and its stage snapshots.

### Verify and inspect the result

Verification can be repeated later or on another machine. Trust only the
repository allowed to supply the recorded project implementations:

```bash
viper verify-run \
  experiments/example/runs/baseline/run-001/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/my-project
```

Inspect the verified stage, artifact, and measurement relationships:

```bash
viper --json lineage \
  experiments/example/runs/baseline/run-001/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/my-project
```

Place `--json` before the command whenever a program or agent needs one typed
result document.

### Search completed runs

The catalog is a disposable SQLite index over immutable run records. Refresh
it from one or more verified results:

```bash
viper catalog-refresh \
  experiments/example/runs/baseline/run-001/resolved.yaml \
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

### Add scientific context

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

### Give an agent the same interface

Start the local MCP server in read mode:

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
