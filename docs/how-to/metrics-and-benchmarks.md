# Define metrics and benchmarks

Metrics record scalar evidence. Objectives say which direction is better.
Benchmarks independently evaluate artifacts from a completed run.

## Record a stateless metric

Use a stateless metric when the stage already computes the value:

```python
@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[params.Metric],
    loss: float,
) -> float:
    return loss


loss = measure(training_loss, params=params.Metric())
```

Attach `loss` to the stage, then record values from the stage function:

```python
context.metrics["training_loss"].record(loss_value, epoch=epoch, step=step)
```

Use `min(loss)` or `max(score)` to select the direction of the stage objective.

## Accumulate a stateful metric

Use a stateful metric when the metric itself must retain observations between
updates. Subclass `StatefulMetric`, implement `update()` and `compute()`, and
declare `mode="stateful"`. Stateful metrics do not declare file dependencies
or a comparator; their state is owned by the metric instance during the stage.

## Recompute a stateless metric

A stateless metric can also be recomputed from declared artifacts. Configure
it with `dependencies` and a `comparator` in `measure()`. VIPER then loads the
named files and compares the recomputed value with the recorded value. The two
arguments are paired: supplying only dependencies or only a comparator is
invalid.

## Add benchmark criteria

[`benchmark()`](../../src/viper/benchmark.py) evaluates fixed artifacts from a
verified run. `at_least()` and `at_most()` turn configured metrics into explicit
pass criteria:

```python
from viper.benchmark import at_least, benchmark

confirmation = benchmark(
    benchmark_id="holdout-v1",
    eval_id="holdout",
    test=test_artifact,
    splits={"test": split_artifact},
    metrics=(accuracy,),
    criteria=(at_least(accuracy, 0.90),),
)
```

Execute the benchmark against a resolved run and a frozen benchmark spec:

```python
result = execution.benchmark(root, resolved_run_path, benchmark_spec_path)
```

The benchmark result records the independently resolved inputs, metric values,
criteria, and terminal status.
