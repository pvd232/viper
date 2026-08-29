# VIPER API

VIPER exposes a Python interface for project code and a typed operation API for
tools and agents. The `viper` command validates CLI arguments, maps them onto an
operation, and renders the same result models.

## Project interface

Import these names from the package root:

```python
import viper

viper.download_stage
viper.build_stage
viper.embed_stage
viper.train_stage
viper.evaluate_stage
viper.http_transport
viper.run
viper.retry
viper.StageContext
viper.DownloadContext
```

Stage decorators bind one top-level callable to a stage kind and a project
parameter class:

```python
import viper
from my_project.training import train_model


class TrainParameters(viper.parameters.Train):
    epochs: int
    learning_rate: float


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset_path = context.inputs["dataset"]
    weights_path = context.artifacts["parameters"]
    train_model(
        dataset_path=dataset_path,
        weights_path=weights_path,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

`StageContext` provides the active run, attempt, and stage IDs; the validated
parameter value; materialized input paths; writable artifact paths; live metric
handles; and named NumPy generators. `DownloadContext` adds verified HTTP
retrieval handles.

`train_model` is the project's training implementation. VIPER supplies its
validated parameter values and allocated paths. The `parameters` artifact key
is VIPER's required slot for trained model state; `weights_path` is the local
name used by the project.

## Parameter categories

Stage and HTTP transport implementations subclass the category selected by
their parameter-model reference. Metrics receive a versioned open JSON mapping:

| Category | Selected by |
| --- | --- |
| `Download` | `DownloadSpec.parameter_model` |
| `Build` | `BuildSpec.parameter_model` |
| `Embed` | `EmbedSpec.parameter_model` |
| `Train` | `TrainSpec.parameter_model` |
| `Evaluate` | `EvaluateSpec.parameter_model` |
| `Metric` | `MetricSpec.params` |
| `HttpTransport` | `ProjectHttpTransportSpec.parameter_model` |

`ParameterModelRef` fixes the class through its repository-relative source
path, top-level symbol, SHA-256 digest, and byte count. `MetricSpec.params`
rehydrates as `viper.parameters.Metric`; the frozen metric implementation
defines the meaning of its project fields and receives the same mapping during
production and recomputation.

## Python execution

`viper.run(stage_callable)` connects a project entrypoint to one stage selected
by the command arguments:

```python
if __name__ == "__main__":
    viper.run(train)
```

```bash
python train.py --run path/to/spec.yaml --stage train --repository-root .
```

Before the complete plan starts, `run()` checks that the launched callable
matches the selected `StageImplementationRef`, decorator kind, and parameter
class. The function returns `RunSuccess` after the terminal run passes
verification.

`viper.retry(run_spec, repository_root=...)` allocates the next attempt for the
same frozen plan and returns `RetrySuccess`.

Administrative Python callers can execute complete plans directly through the
execution namespace:

```python
from viper import execution
from viper.execution import (
    BenchmarkExecutionError,
    BenchmarkExecutionResult,
    RunError,
    RunResult,
)

run_result = execution.run(repository_root, run_spec_path)
retry_result = execution.retry(repository_root, run_spec_path)
benchmark_result = execution.benchmark(
    repository_root,
    resolved_run_path,
    benchmark_spec_path,
)
```

`run()` and `retry()` return `RunResult`. `benchmark()` returns
`BenchmarkExecutionResult`. Callers can catch `RunError` and
`BenchmarkExecutionError` through the same namespace.

## Typed operations

`viper.api` defines every operation name, request model, success model, failure
model, schema registry, handler registry, and JSON encoder.

| Operation | Request | Success | CLI |
| --- | --- | --- | --- |
| `validate_stage` | `ValidateStageRequest` | `ValidateStageSuccess` | `validate-stage` |
| `validate_resolved_stage` | `ValidateResolvedStageRequest` | `ValidateResolvedStageSuccess` | `validate-resolved-stage` |
| `validate_run_spec` | `ValidateRunSpecRequest` | `ValidateRunSpecSuccess` | `validate-run` |
| `freeze_run` | `FreezeRunRequest` | `FreezeRunSuccess` | `freeze-run` |
| `preflight` | `PreflightRequest` | `PreflightSuccess` | `preflight` |
| `execute_stage` | `ExecuteStageRequest` | `ExecuteStageSuccess` | `execute-stage` |
| `run` | `RunRequest` | `RunSuccess` | `run` |
| `retry` | `RetryRequest` | `RetrySuccess` | `retry` |
| `execute_benchmark` | `ExecuteBenchmarkRequest` | `ExecuteBenchmarkSuccess` | `execute-benchmark` |
| `plan_diff` | `PlanDiffRequest` | `PlanDiffSuccess` | `plan-diff` |
| `lineage` | `LineageRequest` | `LineageSuccess` | `lineage` |
| `status` | `StatusRequest` | `StatusSuccess` | `status` |
| `compare_runs` | `CompareRunsRequest` | `CompareRunsSuccess` | `compare-runs` |
| `verify_run` | `VerifyRunRequest` | `VerifyRunSuccess` | `verify-run` |
| `verify_benchmark` | `VerifyBenchmarkRequest` | `VerifyBenchmarkSuccess` | `verify-benchmark` |
| `verify_pointer` | `VerifyPointerRequest` | `VerifyPointerSuccess` | `verify-pointer` |
| `get_schema` | `SchemaRequest` | `SchemaSuccess` | `schema` |
| `get_capabilities` | `CapabilitiesRequest` | `CapabilitiesSuccess` | `capabilities` |
| `init_project` | `InitProjectRequest` | `InitProjectSuccess` | `init` |

Python callers can invoke a concrete operation directly:

```python
from pathlib import Path

from viper.api import ValidateStageRequest, validate_stage

result = validate_stage(ValidateStageRequest(path=Path("stage/spec.yaml")))
```

Tools that start from untyped input call `dispatch()`:

```python
from viper.api import dispatch

result = dispatch(
    "run",
    {
        "run_spec": "path/to/spec.yaml",
        "repository_root": ".",
    },
)
```

`dispatch()` validates the mapping through the request class in
`REQUEST_REGISTRY`. It then calls the function in `HANDLER_REGISTRY` and returns
one `SuccessModel` or `ViperFailure`.

## Request fields

Validation and status requests select one local `path`. Run operations use
these fields:

| Request | Required fields | Optional fields |
| --- | --- | --- |
| `FreezeRunRequest` | `draft`, `repository_root` | — |
| `PreflightRequest` | `run_spec`, `repository_root` | — |
| `ExecuteStageRequest` | `run_spec`, `stage_id`, `repository_root` | `timeout_seconds` |
| `RunRequest` | `run_spec`, `repository_root` | `timeout_seconds` |
| `RetryRequest` | `run_spec`, `repository_root` | `timeout_seconds` |
| `ExecuteBenchmarkRequest` | `resolved_run`, `benchmark_spec`, `repository_root` | `timeout_seconds` |
| `VerifyRunRequest` | `path`, `trusted_source_repositories` | — |
| `VerifyBenchmarkRequest` | `path`, `trusted_source_repositories` | — |
| `VerifyPointerRequest` | `path`, `trusted_source_repositories` | — |

Every success contains `status="ok"`, its operation name, and `warnings`.
Execution successes add the canonical output paths and identities produced by
the selected operation.

## Failures

Direct operation functions raise `ViperError` for an expected operation
failure. `ViperError.failure` contains one `ViperFailure`:

| Field | Meaning |
| --- | --- |
| `operation` | Selected operation, when parsing reached one |
| `origin` | `request`, `application`, `cli`, or `internal` |
| `code` | Stable machine-readable error category |
| `message` | Public explanation |
| `details` | Structured public values with credential fields redacted |
| `warnings` | Additional public warnings |

`ErrorCode` admits these values: `invalid_request`, `invalid_document`,
`not_found`, `retrieval_failed`, `write_conflict`, `io_failed`,
`execution_failed`, `verification_failed`, `publication_failed`, `cancelled`,
and `internal_error`.

## JSON CLI

Place `--json` before the command:

```bash
viper --json capabilities
viper --json preflight path/to/spec.yaml
viper --json run path/to/spec.yaml
viper --json verify-run path/to/resolved.yaml --trust-source <repository>
```

JSON mode writes one UTF-8 document followed by one newline. A successful
operation returns exit status `0`. A `ViperFailure` returns `1`. A completed
preflight with `ready=false` also returns `1`.

`result_json_bytes()` encodes paths, URLs, datetimes, bytes, enums, mappings,
sets, sequences, request models, and result models into deterministic JSON.

## Discovery

`get_schema(SchemaRequest(name=...))` returns the JSON Schema for one name in
`SCHEMA_REGISTRY`.

`get_capabilities(CapabilitiesRequest())` returns the protocol version,
operation names, registered schemas, and installed execution backends. The CLI
equivalents are:

```bash
viper --json schema RunSpec
viper --json capabilities
```

## Module ownership

Public types and functions have one owner:

| Module | Owns |
| --- | --- |
| `viper.api` | Typed operations, dispatch, discovery, and JSON encoding |
| `viper.parameters` | Project parameter categories and references |
| `viper.stages` | Stage specifications, decorators, contexts, and invocation evidence |
| `viper.experiments` | Experiments, variants, factors, levels, and replicates |
| `viper.runs` | Run plans, attempts, and terminal run results |
| `viper.artifacts` | Artifact declarations, resolved artifacts, loaders, and pointers |
| `viper.references` | Hash-bound references to separately stored values |
| `viper.metrics` | Metric decorators, specifications, measurements, and receipts |
| `viper.benchmark` | Benchmark specifications, comparisons, and results |
| `viper.http` | Requests, transports, retrievals, and HTTP execution context |
| `viper.runtime` | Environments, startup controls, and observed execution context |
| `viper.randomness` | Python, NumPy, and PyTorch generator-state contracts |
| `viper.resume` | Optimizer, DataLoader, and combined resume-state contracts |
| `viper.execution` | Run, retry, and benchmark operations |
| `viper.verification` | Run, artifact, pointer, and benchmark verification |
| `viper.serialization` | Canonical YAML and JSON encoding and parsing |
| `viper.storage` | Immutable publication and retrieval through the local store |

The package root contains `viper.parameters`, the project-facing decorators,
the runtime contexts, `run()`, and `retry()`. Import administrative documents
and operations from the owner modules listed above.
