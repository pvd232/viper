# Metric provenance

## Status

Metric decorators, exact implementation references, dependency binding,
restricted metric contexts, controlled metric workers, measurement writing,
floating-point comparators, and immutable verification receipts are
implemented. Each successful recomputed metric publishes the production and
verification worker receipts with its measurement. Controlled stage children
receive runner-owned handles for selected live metrics and write their values
through the active measurement sink.

## Required claim

VIPER verifies that one metric value came from the frozen metric
implementation, its declared dependencies, its frozen parameters, and its
effective execution environment.

## Implemented path

`MetricSpec` identifies exact implementation bytes and declares each permitted
dependency. The runner and verifier construct
[`MetricContext`](../../src/viper/metrics.py) from that dependency set and reject a
data-role mismatch before invocation.

The runner launches separate production and verification workers under the
run's startup controls. Each worker records its startup and observed execution
context. The attempt publishes one `MetricVerificationReceipt` that binds both
workers to the recorded measurement and dependency files. The verifier checks
that complete stored evidence directly.

Live training and diagnostic metrics use the same frozen implementation
identity. The stage worker loads each selected live implementation, binds it to
the active attempt, and injects its handle into `StageContext.metrics`.

Each worker receipt records the run ID and attempt ID that own the measurement.
The verifier requires both worker receipts to select those same identities.

## Contract models

`kind` states the metric's scientific role. `mode` selects one complete
execution and verification path.

```python
MetricKind = Literal["training", "evaluation", "diagnostic"]
MetricMode = Literal["recompute", "live"]


class MetricImplementationRef(ProtocolModel):
    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class MetricDependency(ProtocolModel):
    source: Literal["input", "artifact"]
    name: InputName | ArtifactName
    required_data_role: DataRole


class MetricSpec(ProtocolModel):
    schema_version: Literal[1] = 1
    metric_id: MetricId
    kind: MetricKind
    implementation: MetricImplementationRef
    params: viper.parameters.Metric
    mode: MetricMode
    dependencies: tuple[MetricDependency, ...] = ()
    comparator: FloatComparator | None = None
```

The model validator enforces two complete configurations:

| Mode | Required fields | Execution rule | Verification rule |
|---|---|---|---|
| `recompute` | One or more dependencies and one comparator | A metric worker computes the value from persisted dependencies after the stage completes. | A second metric worker recomputes the value from the same immutable dependencies. |
| `live` | Empty dependencies; comparator absent | The running stage supplies live values through `MetricHandle`. | The stage invocation and measurement sink establish controlled execution. |

An evaluation metric uses `mode="recompute"`. A live metric has kind
`training` or `diagnostic`. Dependency pairs of `source` and `name` are unique.

`required_data_role` states the role accepted by the metric. Preflight and the
verifier compare it with the role declared by the selected stage input or
artifact.

For one execution, each authored dependency resolves to exact files:

```python
class ResolvedMetricDependency(ProtocolModel):
    dependency: MetricDependency
    files: tuple[ResolvedFileRef, ...] = Field(min_length=1)
```

A single-file value produces one file reference. A bundle produces one entry
for every regular member beneath its declared root.

## Project interface

A recomputed metric is an ordinary decorated function:

```python
@viper.metric(
    metric_id="accuracy",
    kind="evaluation",
    mode="recompute",
)
def accuracy(context: MetricContext) -> float:
    ...
```

`MetricContext` is a runtime dataclass containing the selected dependency paths
and frozen parameters:

```python
@dataclass(frozen=True)
class MetricContext:
    inputs: Mapping[InputName, Path]
    artifacts: Mapping[ArtifactName, Path]
    params: viper.parameters.Metric
```

A live metric can use a function or a stateful class:

```python
@viper.metric(
    metric_id="training_loss",
    kind="training",
    mode="live",
)
def training_loss(value: float) -> float:
    return value
```

```python
@viper.metric(
    metric_id="epoch_accuracy",
    kind="training",
    mode="live",
)
class EpochAccuracy(StatefulMetric):
    def update(self, predictions, targets) -> None:
        ...

    def compute(self) -> float:
        ...
```

The stage receives one runner-owned handle for each selected live metric:

```python
class MetricHandle(Protocol):
    def update(self, *args: object, **kwargs: object) -> None:
        ...

    def record(
        self,
        *args: object,
        epoch: int | None = None,
        step: int | None = None,
        **kwargs: object,
    ) -> Measurement:
        ...
```

For a function metric, `record()` invokes the frozen function and writes its
scalar result. For a stateful metric, `update()` advances the class instance and
`record()` calls `compute()` before writing the result. The handle supplies the
active run, attempt, stage, and metric identities to `MeasurementSink`.

## Execution

For `mode="recompute"`, the runner performs the first metric execution after
the producing stage completes:

```text
resolve the declared dependencies
-> verify their identities and data roles
-> start the dedicated metric worker
-> apply the effective startup and runtime controls
-> load the frozen metric callable
-> construct MetricContext from the declared dependencies only
-> invoke the callable
-> write the Measurement and production execution receipt
```

Verification repeats that sequence in a second metric worker. The verifier
compares the second value with the recorded measurement through the frozen
`FloatComparator`.

The coordinator supplies the active `run_id`, `attempt_id`, `stage_id`, and
`metric_id` to each worker. The worker constructs `MetricExecutionReceipt`
from those coordinator-owned values. The worker owns the receipt identities.
Metric code returns the scalar value.

For `mode="live"`, the controlled stage child loads the selected function or
stateful class before invoking the stage callable. `StageContext.metrics`
contains the bound `MetricHandle`. Every recorded value enters
`MeasurementSink` with the active run, attempt, stage, and metric IDs.

## Persisted evidence

Each dedicated worker writes its complete execution evidence:

```python
class MetricExecutionReceipt(ProtocolModel):
    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    metric_id: MetricId
    stage_id: StageId
    purpose: Literal["measurement", "verification"]
    implementation: MetricImplementationRef
    params: viper.parameters.Metric
    dependencies: tuple[ResolvedMetricDependency, ...] = Field(min_length=1)
    startup: ProcessStartupReceipt
    execution_context: ExecutionContext
    python_environment: PythonEnvironmentSpec
    value: float = Field(allow_inf_nan=False)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded"] = "succeeded"


class MetricVerificationReceipt(ProtocolModel):
    schema_version: Literal[1] = 1
    metric_id: MetricId
    stage_id: StageId
    measurement: Measurement
    production: MetricExecutionReceipt
    recomputation: MetricExecutionReceipt
    comparator: FloatComparator
    passed: bool
    completed_at: AwareDatetime
```

The production receipt's value equals `measurement.value`. Both execution
receipts identify `measurement.run_id`, `measurement.attempt_id`,
`measurement.stage_id`, and `measurement.metric_id`. They also identify the
same metric implementation, parameters, and resolved dependencies. Their
`purpose` values distinguish the original measurement from independent
verification.

The ownership equalities are:

```text
production.run_id
== recomputation.run_id
== measurement.run_id

production.attempt_id
== recomputation.attempt_id
== measurement.attempt_id

production.stage_id
== recomputation.stage_id
== measurement.stage_id

production.metric_id
== recomputation.metric_id
== measurement.metric_id
```

The attempt publishes the verification receipt as an immutable file. The
attempt-file reference supplies its SHA-256 and byte count, so the receipt
stores the complete dependency and runtime evidence directly.

A live metric uses the frozen `MetricSpec`, its `Measurement` rows, the stage
invocation receipt, and the attempt-file snapshot. A future tensor-capture
contract can add independent recomputation for selected live metrics.

## Verification

| Check | Rule |
|---|---|
| `metric.implementation` | Both worker receipts identify the implementation frozen by `MetricSpec` and `RunSpec.source`. |
| `metric.dependencies` | Every resolved dependency matches one declared dependency, stage value, data role, and complete verified file set. |
| `metric.parameters` | Both worker receipts contain the parameters frozen by `MetricSpec`. |
| `metric.measurement` | The embedded measurement equals one row in the attempt's measurement file. Both worker receipts contain its run, attempt, stage, and metric identities. |
| `metric.production` | The production worker's value equals the recorded measurement. |
| `metric.environment` | Each worker's startup and execution evidence satisfies the effective environment and run-wide reproducibility controls. |
| `metric.recompute` | The recomputation value satisfies the frozen comparator against the recorded measurement. |
| `metric.live_execution` | A live measurement was written through the handle bound to the active stage invocation. |

## Propagation

| Surface | Required change |
|---|---|
| Protocol | Add `MetricImplementationRef`, `MetricDependency`, `ResolvedMetricDependency`, `MetricMode`, `MetricExecutionReceipt`, and `MetricVerificationReceipt`. |
| Authoring | Resolve decorator metadata, dependency selections, parameters, mode, comparator, and implementation bytes. |
| Preflight | Validate each dependency and required data role against every selecting stage. |
| Runtime | Execute recomputed metrics in dedicated workers and inject live metric handles into `StageContext`. |
| Persistence | Store measurements, complete worker receipts, and immutable metric-verification receipts. |
| Verification | Apply implementation, dependency, parameter, runtime, measurement, and comparator checks. |
| Tests | Exercise one recomputed evaluation metric and one live training metric, plus dependency, execution, and tampering failures. |

## Acceptance case

An evaluation metric declares the `predictions` artifact and `targets` input.
VIPER supplies those two paths to the production metric worker. Verification
launches a second worker with the same immutable files and accepts equal values.

The dependency rejection case adds an undeclared `holdout_labels` path to the
worker context. `metric.dependencies` fails before metric invocation. The
ownership rejection case assigns the recomputation receipt to another attempt.
`metric.measurement` fails. The runtime rejection case changes the
recomputation worker's recorded CUDA or Python environment.
`metric.environment` fails.

## Implementation order

1. Add implementation, dependency, mode, and run-owned receipt models.
2. Freeze decorator metadata into `MetricSpec`.
3. Restrict each `MetricContext` to the declared dependencies.
4. Reuse the controlled worker launcher for production and recomputation.
5. Inject `MetricHandle` values for live metrics.
6. Add persisted evidence, verifier rules, and acceptance coverage.
