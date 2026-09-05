# VIPER Python API

VIPER exposes two Python surfaces:

- project authors use domain modules to declare and execute experiments;
- tools and agents use typed request and result models from `viper.api`.

Import each public object from the module that defines it.

## Author and execute an experiment

The primary workflow is:

```python
from viper import execution
from viper.authoring import plan

draft = plan(
    experiment=study,
    variant="baseline",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
result = execution.run(repository_root, draft)
```

`viper.authoring.plan()` returns an immutable `RunPlanDraft`.
`viper.execution.run()` compiles a draft into canonical protocol files, executes
the selected stages, verifies the terminal evidence, and returns `RunResult`.

The execution namespace also provides:

```python
retry_result = execution.retry(repository_root, run_spec_path)
benchmark_result = execution.benchmark(
    repository_root,
    resolved_run_path,
    benchmark_spec_path,
)
batch_result = execution.run_many(
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
| `stage()` | `StageDraft` | Connect a decorated function to parameters, inputs, artifacts, metrics, and an objective. |
| `factor()` | `FactorDraft` | Declare the permitted levels of one experimental factor. |
| `variant()` | `VariantDraft` | Declare one reusable stage graph and estimator artifact. |
| `replicate()` | `ReplicateDraft` | Declare one reproducible seed. |
| `experiment()` | `ExperimentDraft` | Group factors, variants, and replicates. |
| `plan()` | `RunPlanDraft` | Select one variant-replicate pair and its source and runtime identity. |
| `expand()` | `ExperimentPlan` | Generate ordered plans for selected variant-replicate pairs. |

## Stage decorators and context

`build`, `embed`, `train`, and `eval` bind a top-level project function to one
stage kind and parameter class:

```python
from viper import params
from viper.stages import Context, train


class TrainingParams(params.Train):
    epochs: int = 20


@train(params=TrainingParams)
def fit(context: Context[TrainingParams]) -> None:
    dataset = context.inputs["dataset"]
    model = context.artifacts["model"]
```

`Context` provides validated parameters, materialized input paths, writable
artifact paths, metric handles, run identity, and named NumPy generators.

## Metrics and benchmarks

`metric()` declares a `stateful` or `stateless` metric. `measure()` configures
its parameter values and optional recomputation dependencies. `min()` and
`max()` select an objective direction. `benchmark()`, `at_least()`, and
`at_most()` declare independent benchmark confirmation and criteria.

See [Define metrics and benchmarks](../how-to/metrics-and-benchmarks.md).

## Inputs, artifacts, and HTTP

`viper.artifacts.artifact()` declares an output path, loader, role, and file or
bundle kind. `viper.authoring.input()` selects local bytes.
`viper.authoring.download()` combines `HttpRequestSpec`,
`HttpRetrievalPolicy`, artifacts, and an optional project HTTP implementation.

See [Load local and HTTP inputs](../how-to/inputs.md).

## Catalog and knowledge

`viper.catalog.catalog()` opens the derived local catalog. Its `runs()`,
`artifacts()`, `measurements()`, and `benchmarks()` methods accept typed query
models. `viper.knowledge.knowledge()` opens the immutable knowledge publisher;
`catalog().knowledge()` opens exact and similarity queries over indexed
knowledge records.

## Public modules

| Module | Owns |
| --- | --- |
| `viper.api` | Typed operations, dispatch, discovery, and JSON encoding |
| `viper.authoring` | Experiment, variant, stage, input, and immutable plan construction |
| `viper.params` | Built-in extensible parameter categories |
| `viper.stages` | Stage specifications, decorators, contexts, and invocation evidence |
| `viper.experiments` | Frozen experiments, variants, factors, levels, and replicates |
| `viper.runs` | Run plans, attempts, and terminal run records |
| `viper.artifacts` | Artifact declarations, resolved artifacts, loaders, and pointers |
| `viper.references` | Hash-bound references to separately stored values |
| `viper.metrics` | Metric decorators, specifications, measurements, and receipts |
| `viper.benchmark` | Benchmark specifications, criteria, comparisons, and results |
| `viper.http` | Requests, policies, implementations, retrievals, and HTTP context |
| `viper.runtime` | Environments, startup controls, and observed runtime context |
| `viper.randomness` | Python, NumPy, and PyTorch generator-state records |
| `viper.resume` | Optimizer, DataLoader, and combined resume-state records |
| `viper.execution` | Run, retry, batch, benchmark, and restore operations |
| `viper.restoration` | Artifact restore selectors and results |
| `viper.catalog` | Verified-run indexing and exact evidence queries |
| `viper.knowledge` | Typed scientific knowledge publication and models |
| `viper.inspection` | Plan diff, run comparison, status, and lineage models |
| `viper.verification` | Run, artifact, pointer, and benchmark verification |
| `viper.serialization` | Canonical YAML and JSON encoding and parsing |
| `viper.storage` | Immutable publication and retrieval |
| `viper.system_impact` | Contract plan checks and accepted source-impact evidence |
| `viper.system_impact.explain` | Joined one-hop dependency evidence for tools and agents |

## Typed operations

`viper.api` defines each operation name, request model, success model, failure
model, schema registry, handler registry, and JSON encoder. The CLI maps onto
the same operations.

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
| `init_project` | `InitProjectRequest` | `InitProjectSuccess` | `init` |
| `explain_impact` | `ExplainImpactRequest` | `ExplainImpactSuccess` | `impact-explain` |
| `analyze_impact` | `AnalyzeImpactRequest` | `AnalyzeImpactSuccess` | `impact-analyze` |
| `catalog_refresh` | `CatalogRefreshRequest` | `CatalogRefreshSuccess` | `catalog-refresh` |
| `search_runs` | `SearchRunsRequest` | `SearchRunsSuccess` | `search-runs` |
| `search_artifacts` | `SearchArtifactsRequest` | `SearchArtifactsSuccess` | `search-artifacts` |
| `search_measurements` | `SearchMeasurementsRequest` | `SearchMeasurementsSuccess` | `search-measurements` |
| `search_benchmarks` | `SearchBenchmarksRequest` | `SearchBenchmarksSuccess` | `search-benchmarks` |
| `knowledge_refresh` | `KnowledgeRefreshRequest` | `KnowledgeRefreshSuccess` | `knowledge-refresh` |
| `search_primitives` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-primitives` |
| `search_assignments` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-assignments` |
| `search_modulations` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-modulations` |
| `search_effects` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-effects` |
| `search_impacts` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-impacts` |
| `search_diagnostics` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-diagnostics` |
| `search_assertions` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-assertions` |
| `search_retrieval_judgments` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-retrieval-judgments` |
| `search_similar` | `KnowledgeSearchRequest` | `KnowledgeSearchSuccess` | `search-similar` |
| `publish_ontology` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-ontology` |
| `publish_assignment` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-assignment` |
| `publish_modulation` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-modulation` |
| `publish_effect` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-effect` |
| `publish_impact_policy` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-impact-policy` |
| `publish_impact` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-impact` |
| `publish_diagnostic` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-diagnostic` |
| `publish_assertion` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-assertion` |
| `publish_vector` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-vector` |
| `publish_retrieval_judgment` | `PublishKnowledgeRequest` | `PublishKnowledgeSuccess` | `publish-retrieval-judgment` |

Python callers may invoke an operation directly or send untyped input through
`dispatch()`:

```python
from viper.api import ValidateStageRequest, dispatch, validate_stage

result = validate_stage(ValidateStageRequest(path="stage/spec.yaml"))
encoded = dispatch("capabilities", {})
```

`dispatch()` validates the input through `REQUEST_REGISTRY`, invokes the
registered handler, and returns one typed success or `ViperFailure`.

## Failures and discovery

Every success contains `status="ok"`, its operation name, and warnings.
Expected operation failures use `ViperFailure` with an origin, stable code,
public message, redacted details, and warnings.

Use the CLI to inspect the exact installed surface:

```bash
viper --json capabilities
viper --json schema RunSpec
```

See the [CLI reference](cli.md) for command groups and the
[formal protocol](protocol.md) for serialized records.
