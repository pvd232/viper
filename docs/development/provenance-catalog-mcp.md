# Provenance catalog and MCP server

VIPER already verifies one resolved run at a time. This contract adds a
rebuildable catalog that can search across verified runs. It then exposes the
catalog and the existing VIPER operations through one local Model Context
Protocol server.

## 1. Status

**Contract status:** draft after system review; owner review pending.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| PCM-01 <!-- contract-requirement: PCM-01 phase=13 test=tests/test_inspection.py --> | Build and atomically refresh a local catalog from immutable VIPER evidence. |
| PCM-02 <!-- contract-requirement: PCM-02 phase=13 test=tests/test_verification_acceptance.py --> | Search runs, artifacts, measurements, benchmarks, lineage edges, and stage-reuse keys while keeping immutable records authoritative. |
| PCM-03 <!-- contract-requirement: PCM-03 phase=15 test=tests/test_api.py --> | Generate deterministic MCP tool schemas from VIPER's typed operation models and route calls through the same handlers. |
| PCM-04 <!-- contract-requirement: PCM-04 phase=15 test=tests/test_cli.py --> | Ship a local stdio MCP command with read-only default access and explicit execution access. |

**Current:** `verify_run_result()` returns one connected verified run.
`lineage()` builds one graph from that result. `compare_runs()` compares two
verified runs. Current inspection covers one or two selected runs.

**Target:** `viper.catalog()` opens `.viper/catalog.sqlite3`. `Catalog.refresh()`
rebuilds searchable rows from terminal run references. Search results always
retain the immutable reference that supplied each fact. Deleting the database
and refreshing it produces the same searchable facts.

The MCP server is an adapter. It validates tool arguments with the same
Pydantic request models used by `viper.api.dispatch()`. It returns the same
typed result as structured content. Existing VIPER components retain execution,
storage, and verification ownership.

## 2. Required claim

The catalog can answer these questions from verified evidence:

- Which runs used one input digest?
- Which artifacts came from one source commit?
- Which measurements belong to one metric, variant, dataset, or environment?
- Which benchmark results evaluated one model artifact?
- Which completed stage has one exact stage-reuse key?

Every answer includes a `ResolvedRunRef` or another immutable reference that
the caller can verify. The SQLite row itself proves nothing.

The MCP server exposes the same answers and operations to an MCP client. Every
tool call passes through VIPER request validation, path boundaries,
verification, and execution locks.

## 3. Current gap

The existing inspection path starts with a run already selected by the caller:

```text
ResolvedRun
-> verify_run_result()
-> VerifiedRunResult
-> lineage() or compare_runs()
```

The missing path starts with a question:

```text
metric_id="test_loss" and variant="l2"
-> catalog query
-> matching immutable run and measurement references
-> optional full verification of the selected result
```

An MCP server built directly over filesystem searches would create a second,
weaker model of VIPER. This contract adds the catalog first. MCP calls the
catalog and typed API after both interfaces exist.

## 4. Catalog models

Catalog models use `BaseModel` and carry derived query results. Protocol models
remain the evidence records.

```python
class CatalogRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    status: Literal["succeeded", "failed", "cancelled"]
    source_commit: GitCommit
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    benchmark_id: BenchmarkId | None
    verification: Literal["verified"] = "verified"
    completed_at: AwareDatetime


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: StageResultSnapshot
    file: SnapshotFileRef


class CatalogArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    run_id: RunId
    stage_id: StageId
    artifact_name: ArtifactName
    kind: Literal["file", "bundle"]
    data_role: DataRole
    files: tuple[CatalogFile, ...] = Field(min_length=1)


class CatalogMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    measurement: ResolvedFileRef
    run_id: RunId
    stage_id: StageId
    metric_id: MetricId
    value: float = Field(allow_inf_nan=False)
    epoch: int | None = Field(default=None, ge=0)
    step: int | None = Field(default=None, ge=0)
    origin: Literal["executed", "reused"]
    measured_at: AwareDatetime


class CatalogBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: ResolvedBenchmarkResultRef
    run: ResolvedRunRef
    benchmark_id: BenchmarkId
    status: Literal["verified", "passed", "failed"]
    metrics: tuple[BenchmarkMetricResult, ...] = Field(min_length=1)


class CatalogEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    source: str
    target: str
    relation: Literal["produces", "selects", "consumes", "reuses"]
```

`CatalogMeasurement.origin="reused"` means a `StageReuseReceipt` selected the
measurement from an earlier verified run. The measurement keeps its original
immutable reference and original run identity.

## 5. Query models

Each query has a stable sort and bounded page size:

```python
class RunQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    replicate_ids: tuple[ReplicateId, ...] = ()
    statuses: tuple[Literal["succeeded", "failed", "cancelled"], ...] = ()
    source_commit: GitCommit | None = None
    env_sha256: SHA256 | None = None
    reproducibility_sha256: SHA256 | None = None
    benchmark_id: BenchmarkId | None = None
    input_sha256: SHA256 | None = None
    artifact_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ArtifactQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    artifact_names: tuple[ArtifactName, ...] = ()
    data_roles: tuple[DataRole, ...] = ()
    sha256: SHA256 | None = None
    source_commit: GitCommit | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class MeasurementQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    input_sha256: SHA256 | None = None
    env_sha256: SHA256 | None = None
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    origins: tuple[Literal["executed", "reused"], ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class BenchmarkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    benchmark_ids: tuple[BenchmarkId, ...] = ()
    statuses: tuple[Literal["verified", "passed", "failed"], ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    source_commit: GitCommit | None = None
    env_sha256: SHA256 | None = None
    input_sha256: SHA256 | None = None
    artifact_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None
```

The result models are `RunPage`, `ArtifactPage`, `MeasurementPage`, and
`BenchmarkPage`. Each contains an `items` tuple and
`next_cursor: str | None`. Runs sort by
`completed_at`, then `run_id`. Artifacts sort by `run_id`, `stage_id`, and
`artifact_name`. Measurements sort by `run_id`, `stage_id`, `metric_id`, then
by non-null epoch, non-null step, `measured_at`, and the immutable measurement
reference. An aggregate measurement with `epoch=None` or `step=None` follows
measurements with a numeric value in that position. Benchmarks sort by
`benchmark_id`, `run_id`, and immutable result reference.

## 6. Catalog storage and refresh

VIPER stores the derived database at:

```text
.viper/catalog.sqlite3
```

The database has these version-1 tables:

| Table | One row represents |
| --- | --- |
| `sources` | One immutable terminal reference considered during refresh |
| `runs` | One verified terminal run |
| `stages` | One completed stage in one run |
| `inputs` | One resolved stage input |
| `artifacts` | One named stage artifact |
| `files` | One file identity inside an artifact or captured input |
| `measurements` | One measured metric value |
| `benchmarks` | One benchmark result |
| `edges` | One lineage relation |
| `stage_reuse_keys` | One verified stage candidate indexed by its reuse key |

`Catalog.refresh()` follows this procedure:

```text
discover canonical local terminal paths and supplied ResolvedRunRef values
-> discover the local knowledge head and supplied knowledge manifest heads
-> verify each run and walk each manifest chain
-> extract normalized rows
-> write a new database in .viper/
-> fsync the database
-> atomically replace catalog.sqlite3
```

An invalid run enters `sources` with its rejection. Trusted run, artifact,
measurement, benchmark, lineage, and reuse-key tables accept verified sources.

Catalog writes stay inside its SQLite database and derived vector-index
directory. A stale or corrupt catalog can be deleted and rebuilt from immutable
VIPER records and knowledge manifest heads.

## 7. Public catalog interface

```python
class Catalog:
    def refresh(
        self,
        *,
        runs: tuple[ResolvedRunRef, ...] = (),
        knowledge: tuple[ResolvedFileRef, ...] = (),
    ) -> CatalogRefreshResult: ...

    def runs(self, query: RunQuery = RunQuery()) -> RunPage: ...

    def artifacts(
        self,
        query: ArtifactQuery = ArtifactQuery(),
    ) -> ArtifactPage: ...

    def measurements(
        self,
        query: MeasurementQuery = MeasurementQuery(),
    ) -> MeasurementPage: ...

    def benchmarks(
        self,
        query: BenchmarkQuery = BenchmarkQuery(),
    ) -> BenchmarkPage: ...

    def lineage(self, run: ResolvedRunRef) -> RunLineage: ...

    @property
    def knowledge(self) -> KnowledgeCatalog: ...


def catalog(*, root: Path = Path.cwd()) -> Catalog: ...
```

The typed API adds `catalog_refresh`, `search_runs`, `search_artifacts`,
`search_measurements`, and `search_benchmarks`. Their request and success
models contain the same query and page models.

## 8. MCP server

MCP clients discover tools and call them with JSON arguments. The MCP
specification assigns JSON Schema to tool inputs and outputs. VIPER uses its
existing Pydantic operation models as that schema source.

The first server uses stdio:

```bash
viper mcp --root /absolute/project/path
```

The command starts with read access. Execution access is explicit:

```bash
viper mcp --root /absolute/project/path --access execute
```

The server uses the official Python SDK's stable version-2 line. The package
declares it as an optional dependency:

```toml
[project.optional-dependencies]
mcp = ["mcp>=2,<3"]
```

The [official MCP tool contract](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx)
requires valid input schemas and supports output schemas and structured
content. The [official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
generates those schemas from Python types. VIPER still compares every generated
schema with the owning request or success model in tests.

### Read-access tools

The read server exposes these typed operations in deterministic name order:

```text
compare_runs
get_capabilities
get_schema
lineage
plan_diff
search_artifacts
search_benchmarks
search_measurements
search_runs
status
verify_benchmark
verify_pointer
verify_run
```

### Execution-access tools

Execution access adds:

```text
catalog_refresh
execute_benchmark
preflight
restore
retry
run
run_many
```

Python draft objects remain inside the user's authoring process. The MCP server
therefore begins with frozen plan paths and immutable references. Python
authoring files execute in the user's authoring process.

Each tool follows one route:

```text
MCP arguments
-> owning API request model
-> viper.api.dispatch()
-> owning handler
-> owning success model or ViperFailure
-> MCP structuredContent and matching JSON text
```

The default server exposes the read tool set. `--access execute` adds the
execution tool set and grants the local MCP client the same authority as the
user running the CLI process. `catalog_refresh` belongs to execution access
because it replaces the local derived database. The server fixes one
repository root at startup and rejects paths outside it.

Streamable HTTP stays deferred until VIPER defines authentication,
authorization, rate limits, and deployment ownership. The MCP specification
defines stdio and HTTP transports; stdio preserves VIPER's current local trust
boundary.

## 9. Stage-reuse dependency

[`stage-reuse.md`](stage-reuse.md) uses the `stage_reuse_keys` table to find
candidate stages. The catalog stores the complete `StageReuseKey`, the
candidate `ResolvedRunRef`, successful attempt reference, stage reference,
metric evidence, and completion time.

The executor verifies the selected candidate again before reuse. A matching
catalog row supplies a candidate. Full source verification grants permission
to skip execution.

## 10. Acceptance cases

### Rebuild equality

The test indexes three fixture runs, records every query result, deletes the
database, rebuilds it, and receives equal ordered results.

### Tampered source

A catalog source points to a terminal run whose referenced stage bytes changed.
Refresh records the invalid source and excludes its derived rows.

### Cross-run query

Two variants use the same dataset digest and produce different test-loss
measurements. `RunQuery(input_sha256=...)` finds both runs.
`MeasurementQuery(metric_ids=("test_loss",))` returns both values with their
variant IDs and immutable run references.

`ArtifactQuery(source_commit=...)` finds artifacts produced from one source
commit. `MeasurementQuery(input_sha256=..., env_sha256=...)` finds metric
values observed with one input and environment.
`BenchmarkQuery(artifact_sha256=...)` finds every benchmark result that
evaluated one artifact.

### Null ordering

One fixture contains step measurements, an epoch summary, and a stage summary
for the same metric. Two catalog rebuilds return the numeric steps first, then
the epoch summary, then the stage summary. Pagination across those boundaries
returns each measurement once.

### Atomic replacement

A reader holds the old catalog open while refresh builds and replaces the new
database. Every query sees either the complete old database or the complete
new database. The replacement keeps partial state invisible to readers.

### MCP schema equality

The MCP client lists tools twice and receives the same order. Every tool input
schema equals the JSON Schema of its API request model. Every successful call's
structured content validates against its API success model.

### Access boundary

The read server omits `run`, `retry`, `run_many`, `execute_benchmark`, and
`restore`. The execution server exposes them. Both reject a repository path
outside the root fixed at startup.

## 11. Propagation

| Surface | Required change |
| --- | --- |
| `src/viper/catalog.py` | Add the derived models, SQLite schema, refresh, exact run, artifact, measurement, and benchmark queries, and stage-reuse lookup. |
| `src/viper/inspection.py` | Share normalized lineage extraction with catalog refresh. |
| `src/viper/api.py` | Add catalog refresh and run, artifact, measurement, and benchmark search request and success models. |
| `src/viper/_api/handlers.py` | Route catalog requests through `Catalog`. |
| `src/viper/mcp.py` | Generate tools from typed operation registries and dispatch each call. |
| `src/viper/cli.py` | Add `catalog refresh`, catalog search commands, and `mcp --access`. |
| `src/viper/__init__.py` | Export `catalog` and public query and result models. |
| `pyproject.toml` | Add the optional `mcp` dependency group. |
| `tests/test_inspection.py` | Cover rebuild equality, ordering, pagination, filters, and lineage extraction. |
| `tests/test_verification_acceptance.py` | Reject invalid sources and require source references on every result. |
| `tests/test_api.py` | Compare API and MCP schemas and structured results. |
| `tests/test_cli.py` | Cover catalog commands, stdio startup, and access modes. |
| Public documentation | Explain local MCP setup, tool authority, and exact catalog queries. |

## 12. Legacy cleanup

Cross-run filesystem scans inside inspection commands move behind `Catalog`.
Single-run `lineage()` and `compare_runs()` remain public and continue to
operate directly on verified runs.

The MCP implementation imports request models, result models, verifiers,
storage clients, and execution functions from their existing owners. A tool
wrapper converts only the MCP result envelope.

## 13. Implementation order

1. Add catalog models and version-1 SQLite schema.
2. Extract rows from one verified run.
3. Add atomic rebuild, concurrent-reader proof, pagination, null ordering, and exact queries.
4. Add the stage-reuse lookup consumed by the next contract.
5. Add catalog typed operations and CLI commands.
6. Add the optional MCP dependency and stdio server.
7. Generate tools from the typed operation registry.
8. Add access-mode, schema-equality, structured-result, and path-boundary tests.
