# Search runs and publish observations

The [complete Python example](../tutorials/inspect-results.md) runs the CPU
experiment twice, verifies both runs, searches their measurements, and publishes
an observation. Run it from the repository root with:

```bash
python -m examples.inspect_results
```

The following sections explain its catalog and knowledge operations. Each
excerpt belongs inside that program's `main()`; keep its imports at module scope.

## Build the local catalog

`runs` contains the two results returned by `execution.run()`. `root` is the
workspace path, and `trusted` contains its source repository URL. Verify and
index the selected runs before querying them:

```python
from viper import api
from viper.catalog import catalog

refresh = api.catalog_refresh(
    api.CatalogRefreshRequest(
        root=root,
        run_paths=tuple(result.path for result in runs),
        trusted_source_repositories=trusted,
    )
)
index = catalog(root=root)
print(refresh.result.accepted)
```

Refresh replaces `.viper/catalog.sqlite3`. Supply all runs you want to search.
Verification checks each run before it enters the index; a rejected source
raises an error and leaves the existing index intact.

## Search and paginate

Query objects select records by their fields. Each response contains `items`
and `next_cursor`. Keep the filters unchanged when requesting the next page:

```python
from viper.catalog import MeasurementQuery

query = MeasurementQuery(metric_ids=("mean_squared_error",), limit=7)
while True:
    page = index.measurements(query)
    for measurement in page.items:
        print(measurement.value)
    if page.next_cursor is None:
        break
    query = query.model_copy(update={"cursor": page.next_cursor})
```

Use `index.runs(RunQuery(...))`, `index.artifacts(ArtifactQuery(...))`, and
`index.benchmarks(BenchmarkQuery(...))` for the other record types. The complete
example demonstrates run and artifact filters alongside measurement pagination.

## Publish an observation

`knowledge(root=root)` opens the knowledge store. In the complete example,
`left` is one completed run and `weight` is read from its restored model:

```python
from datetime import UTC, datetime
from viper.knowledge import AssertionQuery, JournalAssertion, JournalEvidence, knowledge

store = knowledge(root=root)
publication = store.publish_assertion(
    JournalAssertion(
        assertion_id="fitted_slope",
        kind="observation",
        text=f"Fitted slope: {weight:.6f} for the simulated y = 2x data.",
        evidence=(JournalEvidence(kind="run", reference=left.reference),),
        status="proposed",
        authored_by="experiment_author",
        created_at=datetime.now(UTC),
    )
)
index.refresh(knowledge=(publication.manifest,))
observations = index.knowledge.assertions(AssertionQuery(statuses=("proposed",)))
print(len(observations.items))
```

Publication returns immutable `record` and `manifest` references. The manifest
links this publication to its predecessors. The refresh above creates a
knowledge-only index and replaces the run index. To index both together, pass
verified `CatalogRunSource` objects through `refresh(runs=..., knowledge=...)`.

Use your author identity in `authored_by`. A reviewed assertion also requires
`reviewed_by` and `reviewed_at`. Publication records an interpretation; the
referenced run supplies the experimental evidence supporting it.

## Choose a knowledge record

Use the record that matches the claim you are storing. The models and their
validators are defined in [`viper.knowledge`](../../src/viper/knowledge.py).

| Claim or definition | Model | Publication method |
| --- | --- | --- |
| A vocabulary of terms and parent relationships | `OntologySpec` | `publish_ontology()` |
| A term assigned to an experimental object | `DeclaredPrimitiveAssignment`, `InferredPrimitiveAssignment`, or `ReviewedPrimitiveAssignment` | `publish_assignment()` |
| A controlled change between runs | `Modulation` | `publish_modulation()` |
| An estimated improvement across matched pairs | `EffectEstimate` | `publish_effect()` |
| Rules for interpreting practical importance | `ImpactPolicy` | `publish_impact_policy()` |
| An assessment under those rules | `ImpactAssessment` | `publish_impact()` |
| A structured diagnostic observation | `DiagnosticSignature` | `publish_signature()` |
| An observation, hypothesis, decision, or exclusion | `JournalAssertion` | `publish_assertion()` |
| A vector for finding related records | `KnowledgeVector` | `publish_vector()` |
| A review of a retrieval result | `RetrievalJudgment` | `publish_retrieval_judgment()` |

For similarity search, publish vectors under a `DiagnosticVectorView` or
`JournalVectorView`, then query that exact view and version with `SimilarityQuery`.
The query vector must have the view's dimensions. Exact filters are applied
before cosine-distance ranking; similarity expresses proximity in the selected
view. Assess scientific agreement separately.


## Give an agent access

Install the MCP extra from the repository root in the environment that will run the
server:

```bash
python -m pip install -e '.[mcp]'
```

```bash
viper mcp --root . --access read
```

Read access exposes searches, comparisons, status, and verification. `--access execute`
also permits running, retrying, benchmarking, restoring, refreshing catalogs, and
publishing knowledge. The allowed operations are listed in
[`viper.mcp`](../../src/viper/mcp.py).
