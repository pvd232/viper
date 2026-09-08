# Define metrics and benchmarks

Metrics record scalar evidence. Objectives say which direction is better. Benchmarks
independently evaluate artifacts from a completed run.

## Record a stateless metric

Use a stateless metric to calculate one measurement from the current inputs.
This function computes mean squared error from predictions and targets:

```python
from viper.config import MetricConfig
from viper.metrics import MetricContext, measure, metric, min, max


@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    if not targets:
        raise ValueError("training_loss requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)


loss = measure(training_loss, config=MetricConfig())
```

Attach `loss` to the stage, then pass the metric's inputs from the stage function:

```python
measurement = context.metrics["training_loss"].record(
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

Use `min(loss)` or `max(score)` to select the direction of the stage objective.

## Accumulate a stateful metric

Use a stateful metric when the metric itself must retain observations between updates.
Subclass `StatefulMetric`, implement `update()` and `compute()`, and declare
`mode="stateful"`. The metric instance owns its state during the stage. File
dependencies and comparators apply only to stateless metrics.

```python
from viper.metrics import StatefulMetric


@metric(metric_id="mean_loss", mode="stateful")
class MeanLoss(StatefulMetric[MetricConfig]):
    def __init__(self, context: MetricContext[MetricConfig]) -> None:
        self.total = 0.0
        self.count = 0

    def update(self, value: float) -> None:
        self.total += value
        self.count += 1

    def compute(self) -> float:
        if self.count == 0:
            raise ValueError("mean_loss requires at least one observation")
        return self.total / self.count


mean_loss = measure(MeanLoss, config=MetricConfig())
```

Attach `mean_loss` to the stage. Call `context.metrics["mean_loss"].update(value)` for
each observation, then call `context.metrics["mean_loss"].record(step=step)` to save the
current mean. Accumulated state persists after recording.

## Recompute a stateless metric

A stateless metric can also be recomputed from declared artifacts. Configure it with
`dependencies` and a `comparator` in `measure()`. VIPER then loads the named files and
compares the recomputed value with the recorded value. The two arguments are paired:
supplying only dependencies or only a comparator is invalid. During recomputation, the
function reads paths from `MetricContext.inputs` or `MetricContext.artifacts`. It must
be callable with that context alone. Live positional arguments are available only while
the stage is running.

```python
from viper.metrics import FloatComparator, MetricDependency


@metric(metric_id="prediction_bytes", mode="stateless")
def prediction_bytes(context: MetricContext[MetricConfig]) -> float:
    return float(context.artifacts["predictions"].stat().st_size)


size = measure(
    prediction_bytes,
    dependencies=(
        MetricDependency(
            source="artifact",
            name="predictions",
            required_data_role="eval",
        ),
    ),
    comparator=FloatComparator(mode="exact"),
)
```

This metric checks a file property to illustrate recomputation. A scientific metric
would read the predictions and compute the quantity under study. The required data role
must match the selected artifact. Use `mode="absolute"` or `mode="relative"` with a
positive `tolerance` for approximate comparison.

## Add benchmark criteria

[`benchmark()`](../../src/viper/benchmark.py) declares a benchmark;
`execution.benchmark()` runs it. Start with `test_artifact` and `split_artifact`
selected through `run_artifact()` from a completed run, and a configured recomputed
metric named `accuracy`. `at_least()` and `at_most()` turn configured metrics into
explicit pass criteria:

```python
from viper.benchmark import at_least, benchmark

confirmation = benchmark(
    benchmark_id="holdout_v1",
    eval_id="holdout",
    test=test_artifact,
    splits={"holdout": split_artifact},
    metrics=(accuracy,),
    criteria=(at_least(accuracy, 0.90),),
)
```

The experiment must contain one evaluation stage with the same test input and split
selections. Add an evaluation stage when extending the CPU training-only quickstart.
Pass `benchmark=confirmation` to `plan()` to include the declaration in the frozen plan.
Execute it against the completed run and the resulting benchmark specification path:

```python
from viper import execution

confirmation = execution.benchmark(root, resolved_run.path, benchmark_spec_path)
print(confirmation.status)
print(confirmation.path)
```

The benchmark result records the independently resolved inputs, metric values, criteria,
and terminal status.
