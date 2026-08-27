# Get started with VIPER

This tutorial creates a project, inspects its stage interface, and runs the
validation commands used before execution.

## Install VIPER

Create a Python 3.11 or newer environment, then install the package:

```bash
python -m pip install viper-provenance
```

Confirm the installed command and machine-readable interface:

```bash
viper --help
viper --json capabilities
```

## Create a project

Generate the five-stage starter project:

```bash
viper init my-project --package my_project
cd my-project
python -m pip install -e '.[test]'
python -m pytest -q
```

The project contains download, build, embed, train, and evaluate callables. It
also contains project parameter classes, one evaluation metric, artifact
loaders, and authored protocol directories.

VIPER accepts any repository layout. Frozen specifications identify project
code through repository-relative paths and exact file identities.

## Define a stage

A project parameter class extends the matching category from
`viper.parameters`. The stage callable receives one typed context:

```python
import viper
from my_project.training import train_model


class TrainParameters(viper.parameters.Train):
    epochs: int
    learning_rate: float


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset_path = context.inputs["dataset"]
    weights_path = context.artifacts["parameters"]
    train_model(
        dataset_path=dataset_path,
        weights_path=weights_path,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

VIPER validates the frozen parameter mapping through `TrainParameters` before
calling `train`. The worker supplies the resulting object as `context.params`.
It also supplies the materialized input path and the allocated artifact path.
`train_model` belongs to the project and performs the scientific computation.
The `parameters` key names VIPER's required trained-model artifact.
`weights_path` names that artifact's destination inside the project.

## Start a run from Python

Use the decorated callable in the project's normal entrypoint:

```python
if __name__ == "__main__":
    viper.run(train)
```

The entrypoint receives the selected plan and stage through command arguments:

```bash
python train.py \
  --run experiments/example/runs/run-001/spec.yaml \
  --stage train \
  --repository-root .
```

`viper.run(train)` checks that `train` matches the implementation selected by
the frozen stage. It then executes and verifies the complete run.

## Freeze and inspect a plan

Commit the project source before freezing. The source commit becomes part of
the run identity.

```bash
viper freeze-run path/to/draft.yaml --repository-root .
viper validate-run experiments/example/runs/run-001/spec.yaml
viper preflight experiments/example/runs/run-001/spec.yaml --repository-root .
```

`freeze-run` writes canonical stage specifications and the `RunSpec` that
references them. `preflight` checks the selected source, implementations,
parameters, inputs, environment, and execution requirements on the current
host.

## Execute and verify

Run the complete plan through the installed command:

```bash
viper run experiments/example/runs/run-001/spec.yaml --repository-root .
```

Inspect the durable attempt and terminal result:

```bash
viper --json status .viper/workspaces/run-001/attempts/1/journal.jsonl
viper --json verify-run path/to/resolved.yaml --trust-source <repository-url>
viper --json lineage path/to/resolved.yaml --trust-source <repository-url>
```

The exact terminal path appears in the successful `run` result. JSON mode emits
one machine-readable document with stable operation and failure identifiers.

## Retry a failed plan

Retry appends another attempt to the same frozen plan:

```bash
viper retry experiments/example/runs/run-001/spec.yaml --repository-root .
```

VIPER preserves the earlier attempt document, failure evidence, journal, and
logs. The new attempt receives the next integer ID.

## Confirm a benchmark

An evaluation measures one candidate. A benchmark executes an independent
confirmation from the same frozen plan and checks the shared evaluation
criteria:

```bash
viper execute-benchmark \
  path/to/candidate/resolved.yaml \
  benchmarks/example/spec.yaml \
  --repository-root .
```

The benchmark verifies the confirmation attempt, compares the trained-model
artifact and predictions, and applies its metric thresholds.

## Run on a GPU VM

Provision and enter the VM through the infrastructure workflow you already
use. Install the same VIPER wheel inside that machine and run the same Python or
CLI entrypoint. The plan's `GCEEnvironmentSpec` fixes the requested environment.
Each stage records the observed host, CPU, selected CUDA device, driver,
PyTorch CUDA runtime, and cuDNN runtime.

Version `0.1` supports one host process and one selected CUDA device per stage.
The [execution-environment explanation](../explanation/how-viper-works.md#12-execution-environment-and-scope)
defines the requested and observed fields.

## Continue reading

- [How VIPER works](../explanation/how-viper-works.md)
- [Python and CLI API](../reference/api.md)
- [Formal protocol](../reference/protocol.md)
- [Versioning policy](../reference/versioning.md)
