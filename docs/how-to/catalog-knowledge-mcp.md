# Use the catalog, knowledge store, and MCP

Use the catalog to search completed runs and their measurements. Store your
interpretations of those results in the knowledge store. An agent can use the
same operations through MCP.

## Build the local catalog

After running the [CPU quickstart](../../examples/cpu_quickstart.py), replace
`YOUR_RUN_ID` with the printed run ID and the trust URL with your Git origin:

```bash
viper catalog-refresh experiments/cpu_quickstart/runs/baseline/YOUR_RUN_ID/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/workspace
```

The command verifies each supplied run before indexing it. Refresh rebuilds
`.viper/catalog.sqlite3`; supply the complete set of runs you want in the new index.
Check the accepted and rejected source counts in the result.

## Search measurements

```bash
viper --json search-measurements \
  --root . \
  --query '{"metric_ids":["mean_squared_error"],"limit":20}'
```

From the same workspace directory, Python opens that catalog:

```python
from viper.catalog import MeasurementQuery, catalog

page = catalog().measurements(
    MeasurementQuery(metric_ids=("mean_squared_error",), limit=20)
)
```

## Publish and search knowledge

`knowledge()` opens the repository's knowledge store. Its publication methods
save scientific annotations as typed records. Refresh the catalog with a knowledge head before searching
those records. A head is the manifest reference returned by publication; it links the
new record to preceding publications.

Knowledge records point to immutable run, stage, artifact, or measurement targets. They
store interpretations alongside the evidence they describe.

Knowledge publication, exact filtering, and vector similarity search are part of the
base VIPER installation. Similarity search filters records first, then calculates cosine
distance across the matching vectors with stable ordering.

To index local publications and search assertions:

```bash
viper knowledge refresh --root .
viper --json knowledge search search_assertions --root . --query '{"limit":20}'
```

`knowledge refresh` rebuilds the catalog using only knowledge sources. To keep run and
knowledge rows together, call `catalog().refresh()` with both `runs` and
`knowledge`. The method signature is in [`viper.catalog`](../../src/viper/catalog.py).

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

## Record an observation

A `JournalAssertion` attaches a claim to a saved result. In
the [CPU tutorial](../tutorials/getting-started.md#4-identify-the-source-and-run-the-experiment),
add the imports at module scope. Place the remaining code inside `main()`,
after `resolved_run = execution.run(draft)`:

```python
import json
from datetime import UTC, datetime

from viper.knowledge import JournalAssertion, JournalEvidence, knowledge

model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
weight = json.loads(model_path.read_text(encoding="utf-8"))["weight"]
observation = JournalAssertion(
    assertion_id="fitted_slope",
    kind="observation",
    text=f"Fitted slope: {weight:.6f} for the simulated y = 2x data.",
    evidence=(JournalEvidence(kind="run", reference=resolved_run.reference),),
    status="proposed",
    authored_by="experiment_author",
    created_at=datetime.now(UTC),
)
publication = knowledge().publish_assertion(observation)
print(publication.record.sha256)
```

Publication saves the record and returns its `record` and `manifest` references.
The manifest links it to earlier publications. To publish a reviewed assertion,
set `status="reviewed"` and supply both `reviewed_by` and `reviewed_at`.
Keep the author and reviewer identities accurate for your workflow.

Refresh with the returned manifest, then query the published assertions.
This refresh creates a knowledge-only catalog and replaces the previous index:

```python
from viper.knowledge import AssertionQuery

index = catalog()
index.refresh(knowledge=(publication.manifest,))
page = index.knowledge.assertions(
    AssertionQuery(statuses=("proposed",), limit=20)
)
for item in page.items:
    print(item)
```

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

## Read another page of results

Catalog and knowledge pages contain `items` and `next_cursor`. For exact queries,
pass the returned cursor with the same filters to fetch the next page:

```python
query = MeasurementQuery(metric_ids=("mean_squared_error",), limit=20)
index = catalog()
page = index.measurements(query)
while True:
    for measurement in page.items:
        print(measurement)
    if page.next_cursor is None:
        break
    query = query.model_copy(update={"cursor": page.next_cursor})
    page = index.measurements(query)
```
