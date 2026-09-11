# Define metrics and benchmarks

A metric defines the quantity being measured, such as mean squared error or
classification accuracy. An objective selects a metric and the direction to
optimize. A measurement records its value in a particular stage and run.
Benchmarks independently evaluate artifacts from a completed run.

The two stateless examples show different sources for the numbers:

| Use case | How the metric gets its inputs | Complete program |
| --- | --- | --- |
| Record MSE during training | The training function passes predictions and targets to `.record()`. | [CPU quickstart](../../examples/cpu_quickstart.py) |
| Recompute RMSE after evaluation | VIPER supplies the saved prediction file through `context.artifacts`. | [Evaluation and benchmark](../../examples/evaluation.py) |

## Use the metric context

VIPER passes a `MetricContext` as the first argument to a stateless metric
function, or to a stateful metric's constructor. `context.config` holds the
metric settings selected by `measure(config=...)`.

The context argument is required even when a calculation needs only the
numbers passed by its caller. VIPER uses the same calling convention for
metrics that need settings or saved files. For example, the
[recomputed RMSE metric below](#recompute-a-stateless-metric) reads
`context.artifacts["predictions"]` to locate its prediction file.

For a metric recorded during a stage, `context.inputs` contains the stage's
input paths and `context.artifacts` contains its output paths. For a recomputed
metric, these mappings contain the files selected by `MetricDependency`.
Their values are local `Path` objects, keyed by the declared names.

The stage itself receives a different object, [`Context`](stages.md#use-the-stage-context).
Its `metrics` mapping contains `MetricHandle` objects for the stage-recorded
metrics attached with `stage(metrics=...)`. The decorator's `metric_id`
supplies each key. Calling a handle's `record()` method computes the value
and saves a measurement associated with the current run, attempt, and stage.
For stateless metrics it calls the function with the metric context and your
arguments; for stateful metrics it calls the instance's `compute()` method.

## Record a stateless metric

Use a stateless metric to calculate one measurement from the current inputs.
This function computes mean squared error from predictions and targets.
VIPER supplies its first argument; the training function supplies `predictions`
and `targets` through `.record()`. `_context` marks the required context
argument as unused because this calculation needs only those numbers:

```python
from viper.config import MetricConfig
from viper.metrics import MetricContext, measure, metric, min, max


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)


mse = measure(mean_squared_error)
```

Set `metrics=(mse,)` in the stage declaration, as in the
[complete training example](../../examples/cpu_quickstart.py). Inside that
stage's function, `context` is the stage argument. Pass predictions and targets
to the attached metric's handle:

```python
measurement = context.metrics["mean_squared_error"].record(
    predictions=(1.0, 3.0),
    targets=(2.0, 5.0),
    epoch=1,
    step=1,
)
print(measurement.value)  # 2.5
```

`record()` calls the metric, saves its result, and returns the measurement.
The metric receives the prediction and target arguments; `epoch` and `step`
label the saved measurement. Here the squared errors are 1 and 4, so their
mean is 2.5. The function rejects empty inputs and unequal sequence lengths.

This records a calculation made during training. To check a value again from
saved files, configure [recomputation](#recompute-a-stateless-metric). Live
prediction and target arguments are absent from the saved measurement.

Use `min(mse)` or `max(score)` to select the direction of the stage objective.

Name the metric for its calculation. Mean squared error can serve as a training
loss or an evaluation score; the stage records where it was measured, and the
objective records how it is used. VIPER uses “metric” for scalar measures,
including scores that lack the mathematical properties of a distance metric.

## Recompute a stateless metric

The [evaluation stage](stages.md#evaluate-against-saved-test-data) includes
`training.outputs["model"]` in its inputs. Its `predict` function writes
`[prediction, target]` pairs to the stage's `predictions` output.

Attach the metric below to that stage. `MetricDependency` selects its
`predictions` output, and `context.artifacts["predictions"]` supplies the file's
path. For example, `[[2.0, 3.0], [6.0, 7.0]]` gives RMSE `1.0`.

```python
import json

from viper.config import MetricConfig
from viper.metrics import (
    FloatComparator, MetricContext, MetricDependency, measure, metric,
)


@metric(metric_id="root_mean_squared_error", mode="stateless")
def root_mean_squared_error(context: MetricContext[MetricConfig]) -> float:
    """Read predict's saved [prediction, target] pairs and return their RMSE."""
    pairs = json.loads(context.artifacts["predictions"].read_text(encoding="utf-8"))
    if not pairs:
        raise ValueError("root_mean_squared_error requires at least one prediction")
    squared_errors = [(prediction - target) ** 2 for prediction, target in pairs]
    return (sum(squared_errors) / len(pairs)) ** 0.5


rmse = measure(
    root_mean_squared_error,
    dependencies=(
        MetricDependency(
            source="artifact",
            name="predictions",
            data_role="eval",
        ),
    ),
    comparator=FloatComparator(mode="absolute", tolerance=1e-12),
)
```

Set `metrics=(rmse,)` on the evaluation stage. VIPER computes RMSE after
`predict` returns and repeats it from the saved file during verification.

Supply `dependencies` and `comparator` together; the function must accept its
context alone. The dependency's data role must match the output. This comparator
allows an absolute difference of `1e-12`; `exact` requires equality, and
`relative` applies a positive relative tolerance.

## Add benchmark criteria

[`benchmark()`](../../src/viper/benchmark.py) declares a benchmark;
`execution.benchmark()` runs it. Continue inside `main()` in the complete
[evaluation example](../../examples/evaluation.py), which defines
`test_data`, `test_split`, `evaluation`, and the recomputed `rmse` metric.
That example uses `data_role="benchmark"` for the test data, split, predictions,
and metric dependency.
Use `eval` for a standalone evaluation; use `benchmark` consistently
when the plan includes benchmark criteria.

`at_most(rmse, 0.1)` requires root mean squared error to be at most 0.1:

```python
from viper.benchmark import at_most, benchmark

criteria = benchmark(
    benchmark_id="holdout_v1",
    eval_id="holdout",
    test=test_data,
    splits={"holdout": test_split},
    metrics=(rmse,),
    criteria=(at_most(rmse, 0.1),),
)
```

The experiment must contain one evaluation stage with the same test input and split
selections. Add an evaluation stage when extending the CPU training-only quickstart.
Pass `benchmark=criteria` to `plan()` to include the declaration in the frozen plan.
`execution.run(draft)` saves the benchmark specification along with the plan.
In the complete example, `root = resolve_root()` selects the workspace directory
and `resolved_run = execution.run(draft)` completes training and evaluation.
Execute the confirmation against that result:

```python
from viper import execution

benchmark_spec_path = root / "benchmarks/holdout_v1.spec.yaml"
confirmation = execution.benchmark(root, resolved_run.path, benchmark_spec_path)
print(confirmation.status)
print(confirmation.path)
```

The benchmark result records the independently resolved inputs, metric values, criteria,
and final status.

## Accumulate a stateful metric

Use a stateful metric when the metric itself must retain observations between updates.
Subclass `StatefulMetric`, implement `update()` and `compute()`, and declare
`mode="stateful"`. The metric instance owns its state during the stage. File
dependencies and comparators apply only to stateless metrics.

```python
from viper.metrics import StatefulMetric


@metric(metric_id="mean_absolute_error", mode="stateful")
class MeanAbsoluteError(StatefulMetric[MetricConfig]):
    def __init__(self, context: MetricContext[MetricConfig]) -> None:
        self.total = 0.0
        self.count = 0

    def update(self, prediction: float, target: float) -> None:
        self.total += abs(prediction - target)
        self.count += 1

    def compute(self) -> float:
        if self.count == 0:
            raise ValueError("mean_absolute_error requires at least one observation")
        return self.total / self.count


mae = measure(MeanAbsoluteError)
```

Attach `mae` to the stage. Call
`context.metrics["mean_absolute_error"].update(prediction, target)` for each pair,
then call `context.metrics["mean_absolute_error"].record(step=step)` to save the
mean absolute error. Accumulated state persists after recording.

## Configure a distance metric

A metric can read its own settings from `context.config`. This example measures
the distance between two vectors. `order=1` sums absolute coordinate differences;
`order=2` computes Euclidean distance. The setting belongs to the metric,
independently of the training algorithm:

```python
from typing import Literal

from viper.config import MetricConfig
from viper.metrics import MetricContext, measure, metric


class DistanceConfig(MetricConfig):
    """Choose the norm used to compare vectors."""

    order: Literal[1, 2] = 2


@metric(metric_id="vector_distance", mode="stateless")
def vector_distance(
    context: MetricContext[DistanceConfig],
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    """Compute L1 or L2 distance between nonempty, equally sized vectors."""
    if not left:
        raise ValueError("vector_distance requires nonempty vectors")
    order = context.config.order
    total = sum(abs(a - b) ** order for a, b in zip(left, right, strict=True))
    return total ** (1 / order)


distance = measure(vector_distance, config=DistanceConfig(order=2))
```

Attach `distance` with `stage(metrics=(distance,))`. Inside that stage,
`context.metrics["vector_distance"].record((0.0, 0.0), (3.0, 4.0))` records `5.0`.
Changing the configured order to `1` records `7.0` for the same vectors.
