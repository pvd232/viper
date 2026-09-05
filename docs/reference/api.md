# VIPER API

VIPER exposes a Python interface for project code and a typed operation API for
tools and agents. The `viper` command validates CLI arguments, maps them onto an
operation, and renders the same result models.

## Project interface

Import each name from the module that defines it:

```python
from viper.api import retry, run
from viper.http import http_transport
from viper.stages import (
    Context,
    build,
    download,
    embed,
    eval,
    train,
)
```

Stage decorators bind one top-level callable to a stage kind and a project
parameter class:

```python
from my_project.training import train_model
from viper import parameters
from viper.stages import Context, train


class TrainParameters(parameters.Train):
    epochs: int
    learning_rate: float


@train(params=TrainParameters)
def fit(context: Context[TrainParameters]) -> None:
    dataset_path = context.inputs["dataset"]
    weights_path = context.artifacts["parameters"]
    train_model(
        dataset_path=dataset_path,
        weights_path=weights_path,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

`Context` provides the active run, attempt, and stage IDs; the validated
parameter value; materialized input paths; writable artifact paths; live metric
handles; and named NumPy generators. External-input retrieval remains owned by
VIPER. Project stage callables receive materialized input paths.

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

`viper.api.run(stage_callable)` connects a project entrypoint to one stage selected
by the command arguments:

```python
from viper.api import run


if __name__ == "__main__":
    run(fit)
```

```bash
python train.py --run path/to/spec.yaml --stage train --root .
```

Before the complete plan starts, `run()` checks that the launched callable
matches the selected `StageImplementationRef`, decorator kind, and parameter
class. The function returns `RunSuccess` after the terminal run passes
verification.

`viper.api.retry(run_spec, root=...)` allocates the next attempt for the
same frozen plan and returns `RetrySuccess`.

Administrative Python callers can execute complete plans directly through the
execution namespace:

```python
from viper import execution
from viper import authoring
from viper.execution.errors import BenchmarkExecutionError, RunError
from viper.execution.results import BenchmarkExecutionResult, RunResult

draft = authoring.plan(
    experiment=experiment,
    variant="baseline",
    replicate="replicate-1",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
run_result = execution.run(repository_root, draft)
retry_result = execution.retry(repository_root, run_spec_path)
benchmark_result = execution.benchmark(
    repository_root,
    resolved_run_path,
    benchmark_spec_path,
)
restored = execution.restore(repository_root, run_reference)
```

`viper.authoring.plan()` returns the immutable draft consumed by
`viper.execution.run()`. `run()` and `retry()` return `RunResult`;
`viper.execution.benchmark()` returns `BenchmarkExecutionResult`; and
`viper.execution.restore()` returns `RestoreResult`. Callers can catch `RunError` and
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
| `restore` | `RestoreRequest` | `RestoreSuccess` | `restore` |
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
| `explain_impact` | `ExplainImpactRequest` | `ExplainImpactSuccess` | `impact-explain` |
| `analyze_impact` | `AnalyzeImpactRequest` | `AnalyzeImpactSuccess` | `impact-analyze` |
| `plan_rename` | `RenamePlanRequest` | `RenamePlanSuccess` | `impact-rename-plan` |
| `check_rename` | `RenameCheckRequest` | `RenameCheckSuccess` | `impact-rename-check` |

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
        "root": ".",
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
| `FreezeRunRequest` | `draft`, `root` | — |
| `PreflightRequest` | `run_spec`, `root` | — |
| `ExecuteStageRequest` | `run_spec`, `stage_id`, `root` | `timeout_seconds` |
| `RunRequest` | `run_spec`, `root` | `timeout_seconds` |
| `RetryRequest` | `run_spec`, `root` | `timeout_seconds` |
| `ExecuteBenchmarkRequest` | `resolved_run`, `benchmark_spec`, `root` | `timeout_seconds` |
| `PlanDiffRequest` | `left_run_spec`, `right_run_spec`, `left_root`, `right_root` | — |
| `CompareRunsRequest` | `left_path`, `right_path`, `left_root`, `right_root`, `trusted_source_repositories` | — |
| `VerifyRunRequest` | `path`, `root`, `trusted_source_repositories` | — |
| `LineageRequest` | `path`, `root`, `trusted_source_repositories` | — |
| `VerifyBenchmarkRequest` | `path`, `root`, `trusted_source_repositories` | — |
| `VerifyPointerRequest` | `path`, `root`, `trusted_source_repositories` | — |
| `ExplainImpactRequest` | `check`, `baseline_graph`, `realized_graph` | `targets` |

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
| `viper.system_impact.explain` | Joined one-hop dependency evidence for tools and agents |
| `viper.system_impact.rename` | Exact old-to-new dependency obligations and completion checks |
| `viper.verification` | Run, artifact, pointer, and benchmark verification |
| `viper.serialization` | Canonical YAML and JSON encoding and parsing |
| `viper.storage` | Immutable publication and retrieval through the local store |

The defining module owns every public object. Import each object from that
module; the package root remains docstring-only.

Agents can request compact, receipt-bound one-hop evidence through this
command:

```bash
viper --json impact explain \
  --check plan-check.json \
  --baseline-graph baseline-source-graph.json \
  --realized-graph realized-source-graph.json \
  --target src/package/api.py:parse
```

Agents missing those evidence files can compile the committed baseline and
current Python working tree before receiving the same joined answer:

```bash
viper --json impact analyze \
  --root . \
  --base HEAD \
  --target src/package/api.py:parse \
  --path-depth 3 \
  --path-limit 12 \
  --path-expansion-budget 500
```

`impact analyze` exports the baseline commit while preserving the working tree,
runs the checked-in Python CodeQL suite against both source snapshots, persists
both receipt-bound graphs under `.viper/system-impact/analysis`, and reports
every direct import, call, construction, inheritance, read, or write involving
the selected target. The result also contains `path_search`, an advisory ranked
traversal over the baseline graph. Each candidate includes the complete path
from the selected target, every edge kind, and the exact source location that
supports each step.

Agents can obtain the exact baseline worklist before editing:

```bash
viper impact rename-plan \
  --root . \
  --base HEAD \
  --old src/package/tools.py:run \
  --new src/package/tools.py:run_checked \
  --kind calls
```

The plan reports each required path, line, column, operation, and containing
declaration. After editing, agents can verify the same transformation:

```bash
viper impact rename-check \
  --root . \
  --base HEAD \
  --old src/package/tools.py:run \
  --new src/package/tools.py:run_checked \
  --kind calls
```

The command compiles every selected baseline reference into an obligation,
analyzes the current tree under the same CodeQL identity, and reports each
remaining old binding. A successful exit requires the old declaration and all
governed references to disappear, the replacement declaration to exist, and
every baseline occurrence to have one binding-equivalent replacement.

Path ranking weights calls and constructions above inheritance, writes, reads,
and imports. Each additional hop is discounted and penalized, and high-fanout
intermediate declarations receive another penalty. Declarations beneath `src/`
receive the largest role bonus; declarations beneath a repository-root `tests/`
directory receive a smaller bonus. `path_search.truncated` reports when the
result limit or expansion budget omitted candidates. Targets absent from the
baseline, including new working-tree declarations, appear in
`path_search.unranked_targets`.

Use `--artifact-root`, `--cache-root`,
`--codeql-executable`, or `--query-pack` to override the resolved defaults.
