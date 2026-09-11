# How VIPER works

VIPER saves an experiment's plan, runs its stages, and checks the results against
that plan. The [CPU quickstart](../../examples/cpu_quickstart.py) shows this with
a linear model trained on a small CSV dataset.

Run it from the workspace root:

```bash
python examples/cpu_quickstart.py
```

The model learns a weight close to 2. The program prints the weight, the run's
status, and the path to `resolved.yaml`, which records the result.
See the [tutorial](../tutorials/getting-started.md) for the complete program.

## Declare the training stage

`fit()` reads the dataset and trains the model. Its `@train(config=TrainConfig)`
decorator identifies it as a training function. `stage()` connects that function
to the dataset and declares where it will save the model and checkpoint.

VIPER passes a `Context` to `fit()`. The function reads the CSV from
`context.inputs["dataset"]` and writes the learned weight to
`context.outputs["model"]`. It saves the training state separately through
`context.outputs["resume_state"]`.

Each of the twenty training steps computes predictions and updates the weight.
The `mean_squared_error` function calculates the error from those predictions
and their targets. Calling `context.metrics["mean_squared_error"]` evaluates
that function and records its value for the current epoch.

The experiment declaration, `study`, places this stage in the `baseline`
variant and defines a replicate with seed 7. Variants select different stage
configurations; replicates repeat a variant with a selected seed.

## Select a run

`plan()` selects the `baseline` variant and the `seed_7` replicate from `study`.
It assigns a run ID and returns a `RunPlanDraft`.

The draft includes the source commit returned by `read_source()`. It also
records the Python environment and lockfile selected by the example. Omitting
`reproducibility` selects the reproducible policy; the concrete settings are
saved in the draft. Later changes to the original configuration objects leave
the draft unchanged.

## Save the plan and execute it

`execution.run(draft)` saves the plan before starting the stage. VIPER records
the source file and function name for each implementation, together with a hash
of the file's contents. These references let VIPER check that it uses the code
selected by the plan.

Before starting work, VIPER checks the plan and its source files and confirms
that the runtime meets the plan's requirements. It then starts a worker process
for `fit()`. The worker applies the execution settings and records the active
PyTorch controls immediately before calling the function.

A run can have several attempts. Each attempt records stage progress so that a
failure can be inspected or retried. Retrying keeps the same plan; changing the
experiment requires a new plan.

To execute a plan later, save it with `freeze_run_plan()`. The
[execution guide](../how-to/execution.md#save-a-plan-for-later) shows how to run
that saved plan later.

## Check the output

After `fit()` returns, VIPER checks its declared outputs and records each file's
path, size, and SHA-256 hash. A hash lets later verification detect changed
file contents. The saved measurements identify the stage, metric, and epoch
that produced each value.

Before returning a successful result, VIPER verifies the completed run against
its plan. Required stages must have completed, file contents must match their
recorded hashes, and recorded runtime controls must match the selected settings.
Measurements must belong to metrics declared by the stage.

The returned `RunResult` exposes `.status` and `.path`. Its `.record` contains
the saved run record, and `.reference` identifies the stored copy. The example
uses `.path` to locate `resolved.yaml` and read the model file beside it.

## Use the saved run

The saved records identify which source, data, and settings produced the model.
You can [restore its artifacts or compare it with another
run](../how-to/retry-restore-compare.md), or [index it for
search](../how-to/catalog-knowledge-mcp.md).

Verification checks the recorded execution. Comparing repeated output bytes is
a separate check, and assessing the experiment's scientific conclusions still
requires judgment about the data and method. See [What VIPER
guarantees](guarantees.md) for the scope of these checks.
