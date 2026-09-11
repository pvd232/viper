# How VIPER works

VIPER executes Python functions according to a saved experiment plan.
The code below comes from the complete [CPU quickstart](../../examples/cpu_quickstart.py).
For installation and the full program, see the [tutorial](../tutorials/getting-started.md).

## The argument supplied to your function

The quickstart's training function is `fit(context: StageContext[TrainConfig])`.
VIPER creates this `StageContext` for the running stage and passes it to `fit`.
Its `config` contains the stage's validated training settings. Its `inputs`
and `outputs` map the names you declare to local file paths. Its `metrics`
maps the IDs of attached stage-recorded metrics to objects that compute and
save measurements. The [stage context reference](../how-to/stages.md#use-the-stage-context)
describes every attribute.

The declarations below select a `dataset` input, `model` and `resume_state`
outputs, and the `mean_squared_error` metric. Those names become the keys
used inside `fit`: `context.inputs["dataset"]`, `context.outputs["model"]`,
`context.outputs["resume_state"]`, and `context.metrics["mean_squared_error"]`.

## Define a metric

A metric function computes a measured quantity. Every metric function must
accept a `MetricContext` first; VIPER supplies it with settings and file paths
for calculations that need them. The training code supplies this function's
predictions and targets through `.record()`. MSE needs only those numbers,
so `_context` marks the required context argument as unused:

```python
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

The two tuples must have the same length, and `targets` must contain at least
one value. `metric_id` is the name used to access the metric during execution.
`mode="stateless"` means each call computes its value from the supplied arguments.

Create a configured metric with `measure()`:

```python
mse = measure(mean_squared_error)
```

Attaching `mse` through `stage(metrics=(mse,))`, as shown below, makes a
`MetricHandle` available as `context.metrics["mean_squared_error"]` inside
`fit()`. The key comes from `metric_id` in the decorator. Its `record()` method
computes and saves the measurement:

```python
measurement = context.metrics["mean_squared_error"].record(
    predictions, targets, epoch=epoch, step=epoch
)
loss = measurement.value
```

`record()` supplies the metric context and calls `mean_squared_error` with
the predictions and targets. It
returns a `Measurement` containing the computed value and records its epoch
and step. See [metrics and benchmarks](../how-to/metrics-and-benchmarks.md) for
stateful metrics and recomputation from saved files.

## Declare a stage

`stage()` connects a function to its inputs and outputs:

```python
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
```

`fit` is the training function declared with `@train(config=TrainConfig)` in
the quickstart. VIPER reconstructs the validated training settings as
`context.config` when it calls that function.

- `inputs["dataset"]` selects the CSV file. The worker supplies its local path
  through `context.inputs["dataset"]`.
- `outputs` declares the model and checkpoint files. `fit()` must write both
  files through `context.outputs`; their loaders validate them after the call.
- `metrics` makes `mse` available through `context.metrics`.
- `objective=min(mse)` declares that smaller metric values are preferable.
  The gradient-descent update is implemented in `fit()`.

The return value, `training`, is a `StageDraft`. Constructing it declares the
work; `execution.run()` executes it. See [stage kinds](../how-to/stages.md) for
download, evaluation, and other stage declarations.

## Organize variants and replicates

An experiment groups stage configurations into variants. Replicates select
seeds for repeated execution of a variant:

```python
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

`baseline` contains one stage, named `train`. Its `estimator` selects the model
output for the run. The `seed_7` replicate sets the run's seed to 7.

Add variants to compare stage configurations. Add replicates to run a variant
with different seeds. [Variants and replicates](../how-to/variants-and-replicates.md)
shows how to expand those combinations into run plans.

## Select and execute a run

`plan()` selects one variant and replicate. The quickstart executes that plan
from its entry point:

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
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")
```

`read_source()` finds the workspace from the current directory and reads its
Git commit and `origin` URL. The environment declaration records the Python
packages and the selected lockfile. Commit source changes before creating a
new plan so the saved commit contains the code you intend to run.

`plan()` returns a `RunPlanDraft` with a new run ID. The default execution
policy is `reproducible`. Use `reproducibility="relaxed"` to permit
nondeterministic algorithms, or supply a `ReproducibilitySpec` for custom
settings. The [policy example](../../examples/execution_policies.py) runs each
selection with the same training experiment.

`execution.run(draft)` saves the plan, checks its source and runtime
requirements, and starts the stage worker. The worker records the active
runtime controls immediately before calling `fit()`.

The [execution guide](../how-to/execution.md) explains saved run files and
batch execution with `execution.run_many()`.

## Read the result

`execution.run()` returns a `RunResult` after verification succeeds:

- `.status` is the run's final status.
- `.path` is the local path to `resolved.yaml`.
- `.record` contains the saved run record.
- `.reference` identifies the stored copy used by restore and verification.

Verification checks the completed stages and their outputs against the saved
plan. It checks file hashes and compares the recorded runtime controls with
the selected settings. Comparing output bytes between two runs is a separate
check; see [What VIPER guarantees](guarantees.md).

## Handle a failure

Common failures include:

- `RootError` from `viper.repository`: the workspace, source commit, or
  selected Git remote is missing or invalid. Run from the workspace and check
  that its source is committed.
- `ValueError` from `plan()`: the variant or replicate name is absent from the
  experiment, or the supplied settings are invalid. Correct the declaration
  before executing it.
- `RunError` from `viper.execution.errors`: an attempt failed during execution
  or verification. Its message identifies the saved failure record; the
  original exception is available through `__cause__`.

The failed attempt retains its logs and journal. Use the saved failure record
to locate them; the [troubleshooting guide](../how-to/troubleshooting.md)
explains the common failure codes.

Use `execution.retry()` to retry a failed run with the same saved plan. Changes
to source code or configuration require a new plan. See [retry, restore, and
compare](../how-to/retry-restore-compare.md) for the commands.
