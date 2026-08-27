# Benchmark execution

## Status

Implemented.

## Required claim

VIPER can execute the confirmation required by a frozen `BenchmarkSpec`, build
the resulting `BenchmarkResult`, and verify it through the existing benchmark
rules.

## Implementation

[`verify_benchmark_result()`](../../src/viper/verification.py) verifies a supplied
confirmation attempt, estimator parity, prediction parity, metric criteria,
and benchmark status. [`execute_benchmark()`](../../src/viper/benchmark.py) verifies
the candidate, executes a new confirmation attempt, constructs every comparison
receipt, verifies the completed result, and writes `benchmark.result.yaml`.

## Application operation

```python
class ExecuteBenchmarkRequest(APIModel):
    resolved_run: Path
    benchmark_spec: Path
    repository_root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteBenchmarkSuccess(SuccessModel):
    operation: Literal["execute_benchmark"] = "execute_benchmark"
    result: BenchmarkResult
    result_path: Path
```

The selected `BenchmarkSpec` fixes the evaluation identity, input selection,
metric criteria, and required execution count:

```python
class MetricCriterion(ProtocolModel):
    metric_id: MetricId
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)


class BenchmarkSpec(ProtocolModel):
    schema_version: Literal[1] = 1
    benchmark_id: BenchmarkId
    evaluation_id: EvaluationId
    evaluation_dataset: ArtifactPointerRef
    splits: dict[InputName, ArtifactPointerRef] = Field(min_length=1)
    metrics: tuple[MetricCriterion, ...] = Field(min_length=1)
    execution_count: Literal[2] = 2
```

The count includes the selected candidate execution and one independent
confirmation.

## Execution

VIPER performs this sequence for the one required confirmation:

```text
verify the candidate run
-> execute the same frozen run plan as a new attempt
-> preserve distinct resolved stage snapshots
-> recompute the benchmark metrics
-> compare estimator and prediction artifacts
-> apply every benchmark criterion
-> construct BenchmarkResult
-> verify BenchmarkResult
```

The confirmation uses the same frozen plan. It receives a new attempt ID and
new execution evidence. Its `RunAttempt.purpose` is
`benchmark_confirmation`; the candidate run history continues to contain only
ordinary run and retry attempts.

## Persisted evidence

The benchmark result stores these comparison receipts:

```python
class ArtifactComparisonReceipt(ProtocolModel):
    artifact: StageArtifactRef
    candidate_stage: ResolvedStageRef
    confirmation_stage: ResolvedStageRef
    candidate_digest: SHA256
    confirmation_digest: SHA256
    passed: bool


class MetricCriterionReceipt(ProtocolModel):
    metric_id: MetricId
    candidate_verification: ResolvedFileRef
    confirmation_verification: ResolvedFileRef
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)
    passed: bool


class BenchmarkResult(ProtocolModel):
    schema_version: Literal[1] = 1
    benchmark: ResolvedBenchmarkSpecRef
    run: ResolvedRunRef
    confirmation: ResolvedAttemptRef
    artifacts: tuple[ArtifactComparisonReceipt, ...] = Field(min_length=2)
    metrics: tuple[MetricCriterionReceipt, ...] = Field(min_length=1)
    status: Literal["passed", "failed"]
    completed_at: AwareDatetime
```

Each artifact digest hashes the canonical `ResolvedArtifact` description from
the selected stage snapshot. The two required artifact receipts select
`parameters` and `predictions`. Each metric receipt references the immutable
`MetricVerificationReceipt` files produced for the candidate and confirmation
attempts.

`BenchmarkResult.artifacts` contains exactly those two receipts. Its metric IDs
equal the IDs in `BenchmarkSpec.metrics`. Every referenced
`MetricVerificationReceipt.passed` value is true before the threshold is
applied.

## Verification

`execute_benchmark()` returns after `verify_benchmark_result()` accepts the
newly constructed result. The verifier reconstructs every artifact digest,
loads every metric-verification receipt, applies every threshold, and derives
the expected final status. It also requires the confirmation attempt ID to
exceed every candidate run attempt ID and its purpose to equal
`benchmark_confirmation`.

| Check | Rule |
|---|---|
| `benchmark.plan` | The candidate and confirmation use the same frozen run plan, source, stage specifications, inputs, seed, controls, and effective environments. |
| `benchmark.confirmation` | The confirmation is a distinct successful attempt with purpose `benchmark_confirmation` and a greater attempt ID. |
| `benchmark.artifacts` | The `parameters` and `predictions` receipts identify complete candidate and confirmation artifacts with equal canonical content descriptions. |
| `benchmark.metrics` | Both executions contain passed metric-verification receipts, and both recomputed values satisfy each frozen criterion. |
| `benchmark.status` | The recorded status equals the result derived from artifact parity and metric criteria. |

## Implemented surfaces

| Surface | Implemented operation |
|---|---|
| Application | Typed execute-benchmark request, success, and failure results. |
| CLI | `viper execute-benchmark` with human and JSON output. |
| Runner | Confirmation execution through the durable attempt coordinator. |
| Metrics | Independent recomputation through each declared dependency contract. |
| Persistence | Immutable confirmation attempt plus artifact and metric receipts in `benchmark.result.yaml`. |
| Tests | Passing confirmation, failed threshold, altered receipt, reused evidence, and input-lineage rejection. |

## Acceptance case

The candidate run trains and evaluates one model. `execute_benchmark()` runs the
same frozen plan as attempt `2`, recomputes the declared evaluation metric, and
publishes a passing `BenchmarkResult` after artifact parity and metric criteria
pass.

Replacing one prediction file with different bytes of the same length causes
benchmark verification to fail on its SHA-256 identity.
