# Execute a plan and read its result

Use `execution.run()` for one plan. Use `execution.run_many()` when you want
per-run outcomes for a batch.

## Run a Python draft

After declaring the experiment and selecting a variant and replicate with
`plan()`, execute the returned draft:

```python
from viper import execution

resolved_run = execution.run(root, draft)
print(resolved_run.status)
print(resolved_run.path)
```

VIPER first saves the plan, then checks it and runs its stages. The call
returns after terminal verification succeeds. The
[CPU tutorial](../tutorials/getting-started.md) supplies the complete setup.

## Save a plan for later

```python
from viper.authoring import freeze_run_plan

frozen = freeze_run_plan(root, draft)
plan_path = root / frozen.reference.stored_at.path
resolved_run = execution.run(root, plan_path)
```

`frozen.files` lists the local files written during freezing. Its `reference`
identifies the immutable run specification. Passing `plan_path` executes those
saved declarations. Keep the matching workspace source and environment available.

The equivalent CLI call is:

```bash
viper run path/to/spec.yaml --root . --timeout-seconds 600
```

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

The typed API offers structured failures for applications that need stable
error codes:

```python
from viper.api import ViperFailure, dispatch

response = dispatch("run", {"root": str(root), "run_spec": str(plan_path)})
if isinstance(response, ViperFailure):
    print(response.code, response.message)
else:
    print(response)
```

`dispatch()` returns a success or failure model. Direct domain functions raise
exceptions; choose the interface that fits your caller.

## Handle partial batch failure

```python
batch = execution.run_many(root, plan_paths, max_concurrency=2, stop_on_failure=True)
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
new runs after a failure; already-started runs finish. Invalid plan files are
rejected when loading the batch, before execution begins. The
[variants guide](variants-and-replicates.md) shows how to construct `plan_paths`.

## Read a benchmark outcome

```python
confirmation = execution.benchmark(root, resolved_run.path, benchmark_spec_path)
print(confirmation.status)
print(confirmation.path)
```

`verified` means the comparison matched and the benchmark omitted thresholds.
`passed` means the comparisons and declared thresholds passed. `failed` means
an artifact or metric comparison or a threshold failed. An execution or
verification error raises an exception. See
[metrics and benchmarks](metrics-and-benchmarks.md) for the benchmark declaration.
