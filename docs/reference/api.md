# VIPER Python API

VIPER provides two ways to use Python:

- workspace authors use domain modules to declare and execute experiments;
- tools and agents use typed request and result models from `viper.api`.

Import each public object from the module that defines it.

## Author and execute an experiment

The primary workflow is:

```python
from viper import execution
from viper.authoring import plan
from viper.repository import read_source

source = read_source()

draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
resolved_run = execution.run(draft)
print(resolved_run.status)
print(resolved_run.path)
```

`viper.authoring.plan()` returns an immutable `RunPlanDraft`. `viper.execution.run()`
compiles a draft into protocol files, executes the selected stages, verifies the
terminal evidence, and returns `RunResult`. Read `.status` and `.path` directly;
`.record` contains the stored terminal record and `.reference` identifies its
immutable bytes. See [execution results](../how-to/execution.md).

`read_source()` finds the workspace from the current directory and returns its
checked-out commit and the HTTP(S) URL of `origin`. Select another remote with
`read_source(remote="mirror")` or another workspace with `read_source(root)`.
`execution.run(draft)` uses the same discovery; supply `repository_root=root`
to execute elsewhere. Missing workspace, commit, or remote information raises
`RootError`. Invalid source URLs fail `GitSource` validation.

The [policy example](../../examples/execution_policies.py) runs the training
experiment with reproducible, relaxed, or custom settings. Saved plans retain the
selection and its complete settings. Verification compares the workers' recorded
controls with those settings. Comparing output bytes between runs is separate.

The execution namespace also provides:

```python
retry_result = execution.retry(repository_root, run_spec_path)
benchmark_result = execution.benchmark(
    repository_root,
    resolved_run.path,
    benchmark_spec_path,
)
batch = execution.run_many(
    repository_root,
    run_spec_paths,
    max_concurrency=2,
)
restored = execution.restore(repository_root, run_reference)
```

## Authoring constructors

| Constructor | Returns | Purpose |
| --- | --- | --- |
| `input()` | `ExternalInputDraft` | Select one repository file as a stage input. |
| `download()` | `StageDraft` | Declare a runner-owned HTTP retrieval stage. |
| `run_artifact()` | `RunArtifactDraft` | Select an artifact from a verified prior run. |
| `stage()` | `StageDraft` | Connect a decorated function to config, inputs, outputs, metrics, and an objective. |
| `factor()` | `FactorDraft` | Declare the permitted levels of one experimental factor. |
| `variant()` | `VariantDraft` | Declare one reusable stage graph and estimator artifact. |
| `replicate()` | `ReplicateDraft` | Declare one reproducible seed. |
| `experiment()` | `ExperimentDraft` | Group factors, variants, and replicates. |
| `plan()` | `RunPlanDraft` | Select one variant-replicate pair and its source and runtime identity. |
| `expand()` | `tuple[RunPlanDraft, ...]` | Generate plans for selected variant-replicate pairs using caller-supplied run IDs. |
| `freeze_run_plan()` | `FrozenPlanFiles` | Save a draft as immutable protocol files for later execution. |

These constructors are defined in [`viper.authoring`](../../src/viper/authoring.py).
`plan()` assigns a new run ID. `expand()` requires a `run_ids` mapping for the selected
pairs; see [batch execution](../how-to/variants-and-replicates.md).

`plan()` and `expand()` default to `reproducibility="reproducible"`. Pass
`reproducibility="relaxed"` to permit nondeterministic algorithms while preserving
precision, or pass a `ReproducibilitySpec` for custom settings. Either preset
accepts a separate `parallelism=ParallelismSpec(...)`; custom settings already
contain their parallelism. Both types are defined in
[`viper.runtime`](../../src/viper/runtime.py).

The returned draft stores the selected mode in `execution_policy` and concrete
settings in `reproducibility`. Expansion resolves defaults once for the batch.
Current saved version-2 run specifications retain the concrete settings; policy
mode/version persistence is pending in the
[execution-policy contract](../development/execution-policy-contract.md).

## Naming conventions

| Name | Meaning | Example |
| --- | --- | --- |
| `Config` | Values consumed by a stage, metric, or HTTP implementation. | `TrainConfig` |
| `Draft` | A Python declaration that may contain callables and references to other drafts. | `StageDraft` |
| `Spec` | A serializable declaration of requested work. | `TrainSpec` |
| `Resolved` | A record containing identities or observations obtained during execution or retrieval. | `ResolvedRun` |
| `Ref` | A reference to another object or file. | `GitFileRef` |
| `Context` | Values and paths supplied to a running function. | `MetricContext` |
| `Receipt` | A stored record of an operation. | `StageInvocationReceipt` |
| `Result` | Values returned by an operation. Execution wrappers also expose local paths. | `RunResult` |

`RunPlanDraft` is immutable despite its suffix: `plan()` copies and freezes its
contents. It remains a draft until it is compiled into stored protocol files. In
`viper.stages`, `Spec` and `ResolvedSpec` are unions of the stage-specific models. Use a
concrete model such as `TrainSpec` when constructing a record.

Experiment, variant, factor, level, replicate, stage, input, output, metric, and
evaluation IDs use lowercase letters, digits, and underscores, beginning with a letter.
For example, use `optimizer_study`. Hyphens are rejected. Run IDs use a separate
26-character format; `plan()` generates them.

## Stage decorators and context

[Compose stages](../how-to/stages.md) covers each stage kind and its required
inputs and outputs.

`build`, `embed`, `train`, `eval`, and `diagnostic` bind a top-level workspace function
to one stage kind and config class.

The complete [`@train(config=TrainConfig)` implementation](../tutorials/getting-started.md#2-train-the-model-and-write-its-outputs)
reads `context.inputs`, computes predictions and gradients, records mean squared
error, and writes both files through `context.outputs`.

`Context` provides validated config, materialized input paths, writable output paths,
metric handles, run identity, and named NumPy generators.

## Metrics and benchmarks

`metric()` declares a `stateful` or `stateless` metric. `measure()` supplies its config
values and optional recomputation dependencies. `min()` and `max()` select an objective
direction. `benchmark()`, `at_least()`, and `at_most()` declare independent benchmark
confirmation and criteria.

See [Define metrics and benchmarks](../how-to/metrics-and-benchmarks.md).

## Inputs, artifacts, and HTTP

`viper.outputs.output()` declares an output path, loader, role, and file or bundle kind.
`viper.authoring.input()` selects local bytes. `viper.authoring.download()` combines
`HttpRequestSpec`, `HttpRetrievalPolicy`, outputs, and an optional workspace HTTP
implementation.

See [Load local and HTTP inputs](../how-to/inputs.md).

## Catalog and knowledge

`viper.catalog.catalog()` opens the derived local catalog. Its `runs()`, `artifacts()`,
`measurements()`, and `benchmarks()` methods accept typed query models.
`viper.knowledge.knowledge()` opens the immutable knowledge publisher;
`catalog().knowledge` opens exact and similarity queries over indexed knowledge records.

## Public modules

| Module | Owns |
| --- | --- |
| `viper.api` | Typed operations, dispatch, discovery, and JSON encoding |
| `viper.authoring` | Experiment, variant, stage, input, and immutable plan construction |
| `viper.config` | Built-in extensible stage and metric config classes |
| `viper.outputs` | Typed output declarations and required output names |
| `viper.inputs` | Local, same-run, and stored input references |
| `viper.ids` | Validated run IDs and user-assigned names |
| `viper.repository` | Workspace initialization, source identification, and path resolution |
| `viper.stages` | Stage specifications, decorators, contexts, and invocation evidence |
| `viper.experiments` | Frozen experiments, variants, factors, levels, and replicates |
| `viper.runs` | Run plans, attempts, and terminal run records |
| `viper.artifacts` | Resolved artifacts, loaders, and pointers |
| `viper.references` | Hash-bound references to separately stored values |
| `viper.metrics` | Metric decorators, specifications, measurements, and receipts |
| `viper.benchmark` | Benchmark specifications, criteria, comparisons, and results |
| `viper.http` | Requests, policies, implementations, retrievals, and HTTP context |
| `viper.runtime` | Environments, startup controls, and observed runtime context |
| `viper.randomness` | Python, NumPy, and PyTorch generator-state records |
| `viper.resume` | Optimizer, DataLoader, and combined resume-state records |
| `viper.execution` | Run, retry, batch, benchmark, and restore operations |
| `viper.execution.results` | Returned records, paths, and per-run batch outcomes |
| `viper.execution.errors` | Run, benchmark, and restore exceptions |
| `viper.restoration` | Artifact restore selectors and results |
| `viper.catalog` | Verified-run indexing and exact evidence queries |
| `viper.knowledge` | Typed scientific knowledge publication and models |
| `viper.inspection` | Plan diff, run comparison, status, and lineage models |
| `viper.evidence` | Verified files, artifacts, runs, and source acceptance policy |
| `viper.verification` | Run, artifact, pointer, and benchmark verification |
| `viper.serialization` | Canonical YAML and JSON encoding and parsing |
| `viper.storage` | Immutable publication and retrieval |

## Typed operations

`viper.api` defines each operation name, request model, success model, failure model,
schema registry, handler registry, and JSON encoder. The CLI maps onto the same
operations.

| Operation | Request | Success | CLI |
| --- | --- | --- | --- |
| `validate_stage` | `ValidateStageRequest` | `ValidateStageSuccess` | `validate-stage` |
| `validate_resolved_stage` | `ValidateResolvedStageRequest` | `ValidateResolvedStageSuccess` | `validate-resolved-stage` |
| `validate_run_spec` | `ValidateRunSpecRequest` | `ValidateRunSpecSuccess` | `validate-run` |
| `freeze_run` | `FreezeRunRequest` | `FreezeRunSuccess` | `freeze-run` |
| `preflight` | `PreflightRequest` | `PreflightSuccess` | `preflight` |
| `execute_stage` | `ExecuteStageRequest` | `ExecuteStageSuccess` | `execute-stage` |
| `run` | `RunRequest` | `RunSuccess` | `run` |
| `run_many` | `RunManyRequest` | `RunManySuccess` | `run-many` |
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
| `init_workspace` | `InitWorkspaceRequest` | `InitWorkspaceSuccess` | `init` |
| `catalog_refresh` | `CatalogRefreshRequest` | `CatalogRefreshSuccess` | `catalog-refresh` |
| `search_runs` | `SearchRunsRequest` | `SearchRunsSuccess` | `search-runs` |
| `search_artifacts` | `SearchArtifactsRequest` | `SearchArtifactsSuccess` | `search-artifacts` |
| `search_measurements` | `SearchMeasurementsRequest` | `SearchMeasurementsSuccess` | `search-measurements` |
| `search_benchmarks` | `SearchBenchmarksRequest` | `SearchBenchmarksSuccess` | `search-benchmarks` |
| `knowledge_refresh` | `KnowledgeRefreshRequest` | `KnowledgeRefreshSuccess` | `knowledge refresh` |
| `search_primitives` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_primitives` |
| `search_assignments` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_assignments` |
| `search_modulations` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_modulations` |
| `search_effects` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_effects` |
| `search_impacts` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_impacts` |
| `search_diagnostics` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_diagnostics` |
| `search_assertions` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_assertions` |
| `search_retrieval_judgments` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_retrieval_judgments` |
| `search_similar` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `knowledge search search_similar` |
| `publish_ontology` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_ontology` |
| `publish_assignment` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_assignment` |
| `publish_modulation` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_modulation` |
| `publish_effect` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_effect` |
| `publish_impact_policy` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_impact_policy` |
| `publish_impact` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_impact` |
| `publish_diagnostic` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_diagnostic` |
| `publish_assertion` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_assertion` |
| `publish_vector` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_vector` |
| `publish_retrieval_judgment` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `knowledge publish publish_retrieval_judgment` |

Python callers may invoke an operation directly or send untyped input through
`dispatch()`:

```python
from viper.api import ValidateStageRequest, dispatch, validate_stage

result = validate_stage(ValidateStageRequest(path="stage/spec.yaml"))
discovery = dispatch("get_capabilities", {})
```

`dispatch()` validates the input through `REQUEST_REGISTRY`, invokes the registered
handler, and returns one typed success or `ViperFailure`.

## Failures and discovery

Every success contains `status="ok"`, its operation name, and warnings. Expected
operation failures use `ViperFailure` with an origin, stable code, public message,
redacted details, and warnings.

Use the CLI to list installed operations and inspect a schema:

```bash
viper --json capabilities
viper --json schema RunSpec
```

See the [CLI reference](cli.md) for command groups and the [formal
protocol](protocol.md) for serialized records.
