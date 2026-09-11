# Execute a plan and read its result

Use `execution.run()` for one plan. Use `execution.run_many()` when you want
per-run outcomes for a batch.

## Run a Python draft

Continue inside `main()` in the [CPU tutorial](../tutorials/getting-started.md#4-identify-the-source-and-run-the-experiment),
after its `draft = plan(...)` declaration:

```python
from viper import execution

resolved_run = execution.run(draft)
print(resolved_run.status)
print(resolved_run.path)
```

VIPER first saves the plan, then checks it and runs its stages. The call
returns after the completed run passes verification. The
[CPU tutorial](../tutorials/getting-started.md) supplies the complete setup.

## Saved run files

`execution.run(draft)` saves the plan and runs it. Each run directory contains
`spec.yaml` for the plan and `resolved.yaml` for the result. Keep the plan path
when a run fails; [retry](retry-restore-compare.md#retry-a-failed-run) uses it to
start another attempt.

To execute an existing plan by path through Python, CLI, or MCP, commit the
plan and its companion specifications first. Execution reads those records
from that commit. A Python draft passed directly to `execution.run()` is
published by the call; retry follows its saved plan reference.

`timeout_seconds` limits each stage or metric worker invocation. A run with
several stages can take longer than that limit in total. HTTP requests also
have the timeout declared by their retrieval policy.

## Inspect the returned object

Runs and benchmarks expose the same result attributes:

| Attribute | Meaning |
| --- | --- |
| `status` | Outcome recorded by the completed operation. |
| `path` | Local path of the saved record. |
| `record` | The parsed `ResolvedRun` or `BenchmarkResult`. |
| `reference` | Immutable location, byte count, and digest of the saved record. |

A run also exposes `journal_path`, the attempt's state-change log. For example:

```python
print(resolved_run.record.successful_attempt_id)
print(resolved_run.reference.sha256)
print(resolved_run.journal_path)
```

The local `path` belongs to the Python result wrapper. The persisted record
contains portable references so another workspace can retrieve it. See
[`viper.execution.results`](../../src/viper/execution/results.py) for the return
models and [the protocol reference](../reference/protocol.md) for stored records.

## Handle a failed operation

A single-run call raises when execution or verification fails. Inspect the
attempt journal and use the [troubleshooting guide](troubleshooting.md) to locate
the cause. A transient host failure can be retried with the same plan. A source
or config change requires a new plan.

Applications that need stable error codes can use the
[typed API](../reference/api.md#typed-operations). Direct execution functions
raise exceptions. Direct typed operations raise `ViperError` on expected failures;
`api.dispatch()` converts those exceptions to a `ViperFailure` result.

## Handle partial batch failure

The [variants example](../../examples/variants.py) constructs `root` and
`drafts` for its four variant-replicate pairs. Replace its batch call and result loop with:

```python
batch = execution.run_many(root, drafts, max_concurrency=2, stop_on_failure=True)
for entry in batch.runs:
    if entry.status == "succeeded":
        assert entry.result is not None
        print(entry.run_id, entry.result.path)
    elif entry.status == "failed":
        assert entry.failure is not None
        print(entry.run_id, entry.failure.message)
    else:
        print(entry.run_id, entry.skip_reason)
```

Results retain input order. With `stop_on_failure=True`, VIPER stops scheduling
new runs after a failure; already-started runs finish. Drafts are saved and validated before scheduling begins. The
[variants guide](variants-and-replicates.md) shows how to construct the drafts.

## Read a benchmark outcome

The [evaluation example](../../examples/evaluation.py) creates a benchmark
named `holdout_v1` and includes it in the plan before execution. Executing that
plan writes the benchmark specification used here:

```python
benchmark_spec_path = root / "benchmarks/holdout_v1.spec.yaml"
confirmation = execution.benchmark(root, resolved_run.path, benchmark_spec_path)
print(confirmation.status)
print(confirmation.path)
```

`verified` means the comparison matched and the benchmark omitted thresholds.
`passed` means the comparisons and declared thresholds passed. `failed` means
an artifact or metric comparison or a threshold failed. An execution or
verification error raises an exception. See
[metrics and benchmarks](metrics-and-benchmarks.md) for the benchmark declaration.
