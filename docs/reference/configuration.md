# Configuration and schemas

Stage config describes your computation. Environment and reproducibility records
describe how VIPER should execute it. Storage settings choose where VIPER saves the
evidence.

## Workspace root

A workspace is your Git repository containing `viper.toml`. Commands that use a
workspace accept `--root`; Python execution functions accept a `Path`.
[`resolve_root()`](../../src/viper/repository.py) locates the marker and checks the Git
work-tree root.

## Stage and metric config

Subclass the config class for the operation you are defining. Declare fields with types
and defaults, then pass an instance to `stage()`.

This build stage keeps a configured number of CSV data rows and preserves the
header. VIPER supplies the running function's `Context`: `config` contains
`RowLimit`, `inputs` contains the declared input paths, and `outputs` contains
the destinations to write. Save the code in an importable workspace module:

```python
from pathlib import Path

from pydantic import Field

from viper.authoring import input, stage
from viper.config import BuildConfig
from viper.outputs import StageOutputs, output
from viper.stages import Context, build


class RowLimit(BuildConfig):
    rows: int = Field(default=2, ge=1)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@build(config=RowLimit)
def limit_rows(context: Context[RowLimit]) -> None:
    header, *rows = load_text(context.inputs["dataset"]).splitlines()
    destination = context.outputs["dataset"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "\n".join([header, *rows[:context.config.rows]]) + "\n",
        encoding="utf-8",
    )


limited = stage(
    limit_rows,
    config=RowLimit(rows=2),
    inputs={"dataset": input("examples/data/tiny.csv", data_role="training")},
    outputs=StageOutputs(
        dataset=output(path="limited.csv", loader=load_text, data_role="training")
    ),
)
```

With the tutorial's CSV input, this writes `x,y`, `1,2`, and `2,4` on separate
lines. `RowLimit(rows=1)` keeps only the first data row; zero and negative limits
are rejected when constructing the config. Add `limited` before training in the
variant's stages and select `limited.outputs["dataset"]` as the training input.
Commit the module before creating a plan.

[`viper.config`](../../src/viper/config.py) defines `BuildConfig`, `EmbedConfig`,
`TrainConfig`, `EvalConfig`, `DiagnosticConfig`, `MetricConfig`, and `HttpConfig`. Use
`MetricConfig` subclasses with `measure()` and `HttpConfig` subclasses with a custom
HTTP implementation. Evaluation metric IDs and split inputs belong to the stage
declaration, outside `EvalConfig`.

## Local environment

`LocalEnvSpec` selects CPU compute by default. Its `lockfile` identifies a committed
dependency file, and `python_env` records the installed Python and package versions.
Install the required packages before calling `observe_python_env()` to capture the
environment.

The [CPU example](../../examples/cpu_quickstart.py) uses its committed `pyproject.toml`
as the dependency-file reference. That file contains version ranges. For your own
experiments, select a committed lockfile with pinned versions so the declared
environment can be recreated.

`CUDAComputeSpec` selects a CUDA device model. The runtime models and observation
functions are defined in [`viper.runtime`](../../src/viper/runtime.py).

## Reproducibility

`plan()` and `expand()` accept `reproducibility` with three choices:

| Selection | Behavior |
| --- | --- |
| `"reproducible"` (default) | Requires deterministic algorithms and deterministic cuDNN execution; disables cuDNN benchmarking and TF32. |
| `"relaxed"` | Permits nondeterministic algorithms and cuDNN benchmarking while preserving the preset's precision settings. |
| A `ReproducibilitySpec` instance | Uses your explicit algorithm, precision, parallelism, and generator settings as the `custom` policy. |

Run the [complete policy example](../../examples/execution_policies.py) with
one selection:

```bash
python examples/execution_policies.py reproducible
python examples/execution_policies.py relaxed
python examples/execution_policies.py custom
```

The custom branch shows every required setting. For either preset, use the
separate `parallelism` argument to select thread and data-loader settings.
Custom specs include parallelism directly. Worker startup records the active
controls; verification compares them with the plan. See
[reproducibility guarantees](../explanation/guarantees.md#reproducibility) for
what that comparison establishes.

## Storage

The default setting in `viper.toml` is:

```toml
[storage]
destination = "local"
```

VIPER saves immutable files beneath `.viper/store`. The destination is recorded for each
run and remains fixed during retries. Restore uses the saved file references to retrieve
the original bytes. The supported destination types and configuration parser are in
[`viper.storage`](../../src/viper/storage.py).

## Inspect a schema

List the available schema names with `viper --json capabilities`, then request one
schema:

```bash
viper --json schema RunSpec
```

The [protocol reference](protocol.md) explains the relationships among records. The
installed schema gives each record's fields, types, defaults, and validation
constraints.

## Select a GPU

On a host with CUDA, select the device model in the environment declaration:

```python
import torch

from viper.references import GitFileRef
from viper.repository import read_source
from viper.runtime import CUDAComputeSpec, LocalEnvSpec, observe_python_env

source = read_source()
lockfile_reference = GitFileRef(
    repository=source.repository, commit=source.commit, path="pyproject.toml"
)
device_model = torch.cuda.get_device_name(0)
gpu_environment = LocalEnvSpec(
    lockfile=lockfile_reference,
    python_env=observe_python_env(),
    compute=CUDAComputeSpec(model=device_model, count=1),
)
```

`lockfile_reference` is the committed dependency file's `GitFileRef`;
`device_model` must match the model reported by CUDA on the execution host.
Pass `env=gpu_environment` to `plan()` to select it for the run, or to `stage()`
to override the run environment for one stage. The current preflight check
accepts one CUDA device and rejects other requested counts.

`GCEEnvSpec` identifies the Google Compute Engine host and its
provisioning image. It describes the host where execution occurs. Provision
and configure the machine before running VIPER there.

## Check the host before execution

After saving the plan, inspect its preflight result:

```bash
viper --json preflight path/to/spec.yaml --root .
```

Read `ready` and the individual `checks` in the response. A failed check names
its target and reason. Execution performs these checks as well; calling
preflight separately lets you inspect them before starting the work.
