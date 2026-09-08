# Use the catalog, knowledge store, and MCP

The catalog is a derived SQLite index over verified evidence. The knowledge store
publishes typed scientific annotations. MCP exposes the same typed API to an agent over
local standard input and output.

## Build the local catalog

```bash
viper catalog-refresh experiments/example/runs/baseline/<run-id>/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/workspace
```

The command verifies each supplied terminal run before indexing it. Refresh rebuilds
`.viper/catalog.sqlite3`; supply the complete set of runs you want in the new index.
Check the accepted and rejected source counts in the result.

## Search measurements

```bash
viper --json search-measurements \
  --root . \
  --query '{"metric_ids":["mean_squared_error"],"limit":20}'
```

Equivalent Python code opens the same catalog:

```python
from viper.catalog import MeasurementQuery, catalog

page = catalog(root=root).measurements(
    MeasurementQuery(metric_ids=("mean_squared_error",), limit=20)
)
```

## Publish and search knowledge

`knowledge(root=root)` opens the repository's knowledge store. Its publication methods
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
knowledge rows together, call `catalog(root=root).refresh()` with both `runs` and
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

A `JournalAssertion` attaches a claim to immutable evidence. After a run:

```python
from datetime import UTC, datetime

from viper.knowledge import JournalAssertion, JournalEvidence, knowledge

observation = JournalAssertion(
    assertion_id="baseline_completed",
    kind="observation",
    text="The baseline run completed successfully.",
    evidence=(JournalEvidence(kind="run", reference=resolved_run.reference),),
    status="proposed",
    authored_by="experiment_author",
    created_at=datetime.now(UTC),
)
publication = knowledge(root=root).publish_assertion(observation)
print(publication.record.sha256)
```

Publication saves the record and returns its `record` and `manifest` references.
The manifest links it to earlier publications. To publish a reviewed assertion,
set `status="reviewed"` and supply both `reviewed_by` and `reviewed_at`.
Keep the author and reviewer identities accurate for your workflow.

After refreshing the catalog, query the published assertions:

```python
from viper.knowledge import AssertionQuery

page = catalog(root=root).knowledge.assertions(
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
index = catalog(root=root)
page = index.measurements(query)
while True:
    for measurement in page.items:
        print(measurement)
    if page.next_cursor is None:
        break
    query = query.model_copy(update={"cursor": page.next_cursor})
    page = index.measurements(query)
```
