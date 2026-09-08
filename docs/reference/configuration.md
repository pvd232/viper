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
and defaults, then pass an instance to `stage()`:

```python
from viper.config import TrainConfig
from viper.stages import Context, train


class TrainingConfig(TrainConfig):
    epochs: int = 20
    learning_rate: float = 0.05


@train(config=TrainingConfig)
def fit(context: Context[TrainingConfig]) -> None:
    epochs = context.config.epochs
    learning_rate = context.config.learning_rate
    # Use these values in the training loop, then write the declared outputs.
```

This excerpt shows config access; the [CPU example](../../examples/cpu_quickstart.py)
contains the training loop and output writing. In its `stage()` call, pass
`config=TrainingConfig(epochs=40)` to select a different value. Keep the class and
decorated function in importable workspace files and commit them before creating a plan.

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

`ReproducibilitySpec` groups deterministic algorithm settings, numerical precision,
process and thread counts, data-loader settings, and named NumPy generator families.
Pass it to `plan()` alongside the environment. The [CPU
example](../../examples/cpu_quickstart.py) contains a complete single-process
configuration.

See [What VIPER guarantees](../explanation/guarantees.md#reproducibility) for the limits
of these controls.

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
from viper.runtime import CUDAComputeSpec, LocalEnvSpec, observe_python_env

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
