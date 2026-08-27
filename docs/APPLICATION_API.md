# `viper.application`

`viper.application` is VIPER's public operation layer. Python callers pass a
typed request model to a function. The `viper` command validates a mapping,
calls the same function, and renders its result.

Project stage modules use the root `viper.run(stage_callable)` adapter defined
by [Process startup](contracts/PROCESS_STARTUP.md). That adapter and the
installed command both delegate complete-run coordination to
`viper.application.run(request)`. The callable argument binds the launched
module to one frozen stage. The application operation executes the complete
ordered run plan.

The execution names in this document are the active 0.1 surface.

## Operations

| Python | CLI | Result |
| --- | --- | --- |
| `validate_stage(request)` | `viper validate-stage` | Validated stage kind |
| `validate_resolved_stage(request)` | `viper validate-resolved-stage` | Validated resolved-stage kind |
| `validate_run_spec(request)` | `viper validate-run` | Run ID and ordered stage IDs |
| `freeze_run(request)` | `viper freeze-run` | Canonical stage and run specification paths |
| `preflight(request)` | `viper preflight` | Every applicable check and one readiness value |
| `execute_stage(request)` | `viper execute-stage` | Command, artifacts, standard output, and standard error |
| `run(request)` | `viper run` | Verified terminal run, attempt document, and journal paths |
| `retry(request)` | `viper retry` | New terminal attempt for the same frozen run plan |
| `execute_benchmark(request)` | `viper execute-benchmark` | Verified independent benchmark confirmation |
| `plan_diff(request)` | `viper plan-diff` | Ordered leaf differences between two complete frozen plans |
| `lineage(request)` | `viper lineage` | Verified stages, inputs, artifacts, and their directed relationships |
| `status(request)` | `viper status` | Latest durable attempt state and permitted successor states |
| `compare_runs(request)` | `viper compare-runs` | Ordered differences between two verified terminal runs |
| `verify_run(request)` | `viper verify-run` | Verified run, attempt, stage, and measurement summary |
| `verify_benchmark(request)` | `viper verify-benchmark` | Verified benchmark and confirmation summary |
| `verify_pointer(request)` | `viper verify-pointer` | Verified artifact file count |
| `get_schema(request)` | `viper schema` | JSON Schema for one registered public type |
| `get_capabilities(request)` | `viper capabilities` | Operations, schemas, and execution backends in this installation |
| `init_project(request)` | `viper init` | Runnable project scaffold in an empty directory |

Every success contains `status="ok"` and the function's `operation` name.

## Validate documents

```python
validate_stage(request: ValidateStageRequest) -> ValidateStageSuccess
validate_resolved_stage(
    request: ValidateResolvedStageRequest,
) -> ValidateResolvedStageSuccess
validate_run_spec(request: ValidateRunSpecRequest) -> ValidateRunSpecSuccess
```

Each request supplies `path: Path`. The stage operations return `path` and
`stage_kind`. Run validation returns `path`, `run_id`, and the ordered
`stage_ids`.

Expected errors: `invalid_document`, `not_found`, `io_failed`.

## Freeze a run plan

```python
freeze_run(request: FreezeRunRequest) -> FreezeRunSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `draft` | `Path` | `RunPlanDraft` YAML document |
| `repository_root` | `Path` | Root for source paths and canonical run paths |

The operation validates each stage draft, writes its canonical `spec.yaml`,
records its SHA-256 and byte count in `RunSpec.stages`, and writes the run
`spec.yaml`. The result contains `run_id` and every written path.

Expected errors: `invalid_document`, `not_found`, `write_conflict`, `io_failed`.

## Preflight a plan

```python
preflight(request: PreflightRequest) -> PreflightSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `run_spec` | `Path` | Frozen run `spec.yaml` |
| `repository_root` | `Path` | Repository root on the active execution host |

The result contains `run_id`, `ready`, and every `PreflightCheck`. Each check
contains a stable `code`, `status`, `target`, and `message`. `ready` is true
when the report contains zero failures.

## Execute one stage

```python
execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `run_spec` | `Path` | Frozen run `spec.yaml` |
| `stage_id` | `StageId` | Stage selected from `RunSpec.stages` |
| `repository_root` | `Path` | Repository root on the active execution host |
| `timeout_seconds` | positive `float` or `None` | Process deadline |

VIPER verifies the stage-spec bytes, applies the run controls through
`viper._workers.stages`, invokes the frozen stage callable, and hashes every
declared artifact file. The result contains `stage_id`, `command`, `artifacts`,
`stdout`, and `stderr`.

Expected errors: `invalid_document`, `not_found`, `io_failed`,
`execution_failed`.

## Execute a complete run

```python
run(request: RunRequest) -> RunSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `run_spec` | `Path` | Frozen run `spec.yaml` present in the current Git commit |
| `repository_root` | `Path` | Git repository root on the active execution host |
| `timeout_seconds` | positive `float` or `None` | Per-stage process deadline |

The coordinator performs these operations in order:

```text
preflight plan
-> acquire run lock
-> materialize verified inputs
-> start one controlled child for each stage
-> pass the exact callable its typed StageContext and named NumPy generators
-> invoke and verify declared metrics
-> publish immutable local snapshots
-> publish the attempt document and evidence files
-> write terminal resolved.yaml
-> verify the complete terminal run
```

The result contains `run_id`, `attempt_id`, `resolved_attempt`, `resolved_run`,
and `journal`. Output snapshots live under `.viper/store/<content digest>/`.
Attempt control files live under
`.viper/workspaces/<run ID>/attempt-<attempt ID>/`.

The active host may satisfy `LocalEnvironmentSpec` or `GCEEnvironmentSpec`.
The [cloud-execution contract](contracts/CLOUD_EXECUTION.md) defines GCE runtime
observation. The [process-startup contract](contracts/PROCESS_STARTUP.md)
defines the child process used by both Python and CLI callers.

Expected errors: `execution_failed`, `verification_failed`, `invalid_document`,
`not_found`, `io_failed`.

## Retry a frozen run

```python
retry(request: RetryRequest) -> RetrySuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `run_spec` | `Path` | Frozen plan whose terminal result is failed or cancelled |
| `repository_root` | `Path` | Repository containing the same frozen run plan |
| `timeout_seconds` | positive `float` or `None` | Per-stage process deadline |

The coordinator loads the canonical terminal result beside `run_spec`, requires
`status="failed"` or `status="cancelled"`, allocates the next attempt ID, and
executes the same plan. The result contains the new attempt ID, canonical
attempt path, terminal run path, and journal path.

Expected errors: `execution_failed`, `verification_failed`, `invalid_document`,
`not_found`, `write_conflict`, `io_failed`.

## Execute a benchmark confirmation

```python
execute_benchmark(
    request: ExecuteBenchmarkRequest,
) -> ExecuteBenchmarkSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `resolved_run` | `Path` | Verified candidate run selected for qualification |
| `benchmark_spec` | `Path` | Frozen benchmark specification governing that run |
| `repository_root` | `Path` | Repository containing the frozen run plan |
| `timeout_seconds` | positive `float` or `None` | Per-stage process deadline |

The operation executes one independent confirmation, writes its immutable
attempt document, constructs the artifact and metric comparison receipts, and
publishes `BenchmarkResult` after verification succeeds. The result contains
the benchmark-result path and the confirmation-attempt reference.

Expected errors: `execution_failed`, `verification_failed`, `invalid_document`,
`not_found`, `write_conflict`, `io_failed`.

## Compare frozen plans

```python
plan_diff(request: PlanDiffRequest) -> PlanDiffSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `left_run_spec` | `Path` | First frozen run `spec.yaml` |
| `left_repository_root` | `Path` | Repository containing the first plan |
| `right_run_spec` | `Path` | Second frozen run `spec.yaml` |
| `right_repository_root` | `Path` | Repository containing the second plan |

VIPER verifies every referenced stage file against its `RunStageRef`, then
compares the run specs and stage-spec contents. Each `PlanChange` contains a
stable dotted `path`, a `kind` of `added`, `removed`, or `changed`, and the
applicable values from each plan.

Expected errors: `invalid_document`.

## Read attempt status

```python
status(request: StatusRequest) -> StatusSuccess
```

`StatusRequest.path` selects one durable attempt journal. The result returns
the entry count, latest state, event, timestamp, event details, terminal flag,
and the states accepted by the next journal append. VIPER validates transition
order when each entry is written.

Expected errors: `invalid_document`, `not_found`, `io_failed`.

## Inspect run lineage

```python
lineage(
    request: LineageRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> LineageSuccess
```

The request supplies a terminal run path and
`trusted_source_repositories`, the repositories from which VIPER may execute
frozen metric and loader code. VIPER verifies the complete run before
constructing the graph.

Each node identifies a stage, input, artifact, or promoted input selection.
Each directed edge has one relation:

- `produces`: stage to artifact;
- `selects`: artifact or promoted selection to stage input;
- `consumes`: stage input to consuming stage.

Expected errors: `invalid_document`, `verification_failed`.

## Compare verified runs

```python
compare_runs(
    request: CompareRunsRequest,
    *,
    left_fetcher: StorageFetcher | None = None,
    right_fetcher: StorageFetcher | None = None,
) -> CompareRunsSuccess
```

The request supplies two terminal run paths and
`trusted_source_repositories`, the repositories from which VIPER may execute
frozen metric and loader code. VIPER verifies each run before comparison. The
comparison covers:

- terminal run and attempt fields;
- run, experiment, variant, and benchmark specifications;
- ordered stage specifications;
- resolved stage results and artifact identities; and
- recorded measurements.

Each `RunChange` contains a stable dotted `path`, a `kind` of `added`,
`removed`, or `changed`, and the applicable value from each run.

Expected errors: `invalid_document`, `verification_failed`.

## Verify published evidence

```python
verify_run(
    request: VerifyRunRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyRunSuccess

verify_benchmark(
    request: VerifyBenchmarkRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyBenchmarkSuccess

verify_pointer(
    request: VerifyPointerRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyPointerSuccess
```

Each request supplies `path` and `trusted_source_repositories`. A supplied
`fetcher` retrieves exact bytes for Git, Hugging Face, or local storage
references. Verification checks the connected plan, stage results, inputs,
artifacts, measurements, logs, runtime controls, and terminal selection.
Metrics with `mode="recompute"` execute in a dedicated production worker and a
second verification worker. Both receive the frozen implementation, verified
dependencies, frozen parameters, and the owning run and attempt identities.
VIPER records each worker's startup and runtime evidence, then applies the
metric's declared comparator to the two values.

Expected errors: `invalid_document`, `not_found`, `io_failed`,
`verification_failed`.

## Discover schemas and capabilities

```python
get_schema(request: SchemaRequest) -> SchemaSuccess
get_capabilities(request: CapabilitiesRequest) -> CapabilitiesSuccess
```

`SchemaRequest.name` selects one key in `SCHEMA_REGISTRY`. `SchemaSuccess`
returns `name` and `json_schema`.

`CapabilitiesRequest` has zero fields. `CapabilitiesSuccess` returns the
protocol version, callable operations, registered schema names, and installed
execution backends.

## Create a project

```python
init_project(request: InitProjectRequest) -> InitProjectSuccess
```

| Request field | Type | Meaning |
| --- | --- | --- |
| `path` | `Path` | Absent or empty target directory |
| `package` | `PythonPackageName` | Import package created beneath `src/` |

`PythonPackageName` matches `^[a-z][a-z0-9_]*$`.

VIPER validates both fields before writing. The result contains the created
project root and every generated path. A populated target returns
`write_conflict` and preserves its contents.

Expected errors: `invalid_request`, `write_conflict`, `io_failed`.

## Failures

Expected application failures raise `ViperError`. Its `failure` field is a
`ViperFailure`:

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | `"error"` | Result status |
| `operation` | `OperationName` or `None` | Selected operation |
| `origin` | `request`, `application`, `cli`, or `internal` | Layer that produced the failure |
| `code` | `ErrorCode` | Stable machine-readable category |
| `message` | `str` | Public explanation |
| `details` | `dict[str, object]` | Structured public evidence |

`dispatch(operation, payload)` returns `ViperFailure` for invalid mappings and
expected operation failures. Direct function calls receive Pydantic validation
errors during request construction and `ViperError` during execution.

## JSON CLI

Place `--json` before the command:

```bash
viper --json capabilities
viper --json preflight experiments/example/runs/baseline/<run_id>/spec.yaml
viper --json run experiments/example/runs/baseline/<run_id>/spec.yaml
viper --json plan-diff <left-spec.yaml> <right-spec.yaml>
viper --json lineage <resolved.yaml> --trust-source <repository>
viper --json status <journal.jsonl>
viper --json compare-runs <left-resolved.yaml> <right-resolved.yaml> \
  --trust-source <repository>
```

JSON mode writes one UTF-8 document with one trailing newline. Completed
operations use exit status `0`. Application failures and a preflight result
with `ready=false` use exit status `1`.
