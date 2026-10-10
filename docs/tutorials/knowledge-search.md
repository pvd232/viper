# Publish and search measured knowledge

Run the complete [knowledge-search program](../../examples/knowledge_search.py)
from the repository root after the [installation steps](getting-started.md#install-the-repository):

```bash
python -m examples.knowledge_search
```

Keep [cpu_quickstart.py](../../examples/cpu_quickstart.py) and the example data
beside the program. It trains the model, records training MSE, and recomputes
`slope_error` from the saved model with an exact comparator. It then reads the
actual measurement values and references from the catalog; it does not substitute
made-up measurements or manually constructed run references.

## Bind the vector to measurements

The program selects the last measurement of each metric, creates sorted
`DiagnosticComponent` records, and publishes a `DiagnosticSignature`. Each
component retains the immutable measurement-file reference and its observed value.
`diagnostic_component_sha256()` hashes that ordered tuple.

The two coordinates have these meanings:

| Coordinate | Source |
| --- | --- |
| `mean_squared_error` | Last training measurement before the final gradient update. |
| `slope_error` | Absolute difference between the saved model's slope and the simulated true slope, 2. |

`DiagnosticVectorView` fixes the coordinate order, dimension, cosine distance,
and view version. `KnowledgeVector.source` names the published signature.
Changing coordinate order or preprocessing requires a different view version.
The vector does not contain an embedding of journal text.

## Publish an observation without claiming review

The program publishes `JournalAssertion(kind="observation", status="proposed")`
and cites the signature. Its text reports the value read from the saved result.
Publication preserves the author's statement; it does not review the conclusion.
Use your author identity rather than the example's `experiment_author`.

## Refresh without dropping runs

`index.refresh_knowledge()` reads the current manifest head while retaining runs,
measurements, and reuse candidates. Do not replace this call with `index.refresh()`:
the latter deliberately rebuilds the whole catalog from its supplied sources.

The program checks that its measured run remains indexed, then prints the
proposed assertions and similarity matches. In a fresh workspace each count is 1.
Earlier publications can increase those counts when you run it again.

## Query the same view

`SimilarityQuery` supplies `view_id`, `view_version`, and the two values in the
declared order. The program uses its observed vector as the query and should find
its published signature with distance near zero. Cosine calculation can round;
the vector's saved values are unchanged. This example establishes publication
and retrieval, not a useful scientific distance between training errors.

For a real retrieval task, choose coordinates and scaling deliberately, retain
their definition in the view version, and validate retrieval with reviewed
`RetrievalJudgment` records. Zero-norm vectors are rejected during similarity
search. Exact query filters run before ranking.

The [catalog guide](../how-to/catalog-knowledge-mcp.md) explains pagination,
record types, and the equivalent MCP tools. The [journal guide](../how-to/journals.md)
separates current manual publication from the approved parser and encoder work.

## Complete program

Save this as `examples/knowledge_search.py`. Its helpers and data are supplied
by the linked CPU quickstart. Run it from a committed VIPER workspace as shown
above.

```python
"""Publish measured diagnostics, query their vectors, and retain journal claims."""

import json
from datetime import UTC, datetime

from examples.cpu_quickstart import fit, load_json, load_state, mse
from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.catalog import MeasurementQuery, RunQuery, catalog
from viper.config import MetricConfig
from viper.knowledge import (
    AssertionQuery,
    DiagnosticComponent,
    DiagnosticSignature,
    DiagnosticVectorView,
    JournalAssertion,
    JournalEvidence,
    KnowledgeVector,
    SimilarityQuery,
    diagnostic_component_sha256,
    knowledge,
)
from viper.metrics import (
    FloatComparator,
    MetricContext,
    MetricDependency,
    measure,
    metric,
    min,
)
from viper.outputs import TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env


@metric(metric_id="slope_error", mode="stateless")
def slope_error(context: MetricContext[MetricConfig]) -> float:
    """Compare the saved model's slope with the simulated data's true slope."""
    model = json.loads(context.artifacts["model"].read_text(encoding="utf-8"))
    return abs(model["weight"] - 2.0)


slope = measure(
    slope_error,
    dependencies=(
        MetricDependency(source="artifact", name="model", data_role="training"),
    ),
    comparator=FloatComparator(mode="exact"),
)
training = stage(
    fit,
    stage_id="train",
    inputs=(input("dataset", path="examples/data/tiny.csv", data_role="training"),),
    outputs=TrainOutputs(
        model=output(path="model.json", loader=load_json, data_role="training"),
        resume_state=output(
            path="resume_state.pt", loader=load_state, data_role="training"
        ),
    ),
    metrics=(mse, slope),
    objective=min(mse),
)
study = experiment(
    experiment_id="knowledge_search",
    variants=(
        variant("baseline", stages=(training,), estimator=training.outputs["model"]),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Read actual measurements and preserve indexed runs while publishing knowledge."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(experiment=study, source=source, env=environment)
    result = execution.run(draft)
    index = catalog(root=root)
    rows = index.measurements(MeasurementQuery(run_ids=(draft.run_id,))).items
    components = []
    for metric_id in ("mean_squared_error", "slope_error"):
        selected = max(
            (row for row in rows if row.metric_id == metric_id),
            key=lambda row: (row.step or 0, row.measured_at),
        )
        components.append(
            DiagnosticComponent(
                metric_id=selected.metric_id,
                measurement=selected.measurement,
                value=selected.value,
            )
        )
    ordered = tuple(components)
    now = datetime.now(UTC)
    store = knowledge(root=root)
    signature = store.publish_signature(
        DiagnosticSignature(
            run=result.reference,
            stage_id="train",
            components=ordered,
            component_sha256=diagnostic_component_sha256(ordered),
            created_at=now,
        )
    )
    view = DiagnosticVectorView(
        view_id="training_errors",
        version="1",
        metric_ids=tuple(part.metric_id for part in ordered),
        dimensions=len(ordered),
    )
    values = tuple(part.value for part in ordered)
    store.publish_vector(
        KnowledgeVector(
            view=view, source=signature.record, values=values, created_at=now
        )
    )
    store.publish_assertion(
        JournalAssertion(
            assertion_id=f"slope_{draft.run_id}",
            kind="observation",
            text=f"The saved model has slope error {components[1].value!r} on y = 2x.",
            evidence=(JournalEvidence(kind="diagnostic", reference=signature.record),),
            status="proposed",
            authored_by="experiment_author",
            created_at=now,
        )
    )
    index.refresh_knowledge()
    observations = index.knowledge.assertions(AssertionQuery(statuses=("proposed",)))
    matches = index.knowledge.similar(
        SimilarityQuery(view_id=view.view_id, view_version=view.version, values=values)
    )
    print(f"observations: {len(observations.items)}")
    print(f"similarity matches: {len(matches.items)}")
    for match in matches.items:
        print(match.source.reference.sha256, match.distance)
    retained = index.runs(RunQuery(experiment_id="knowledge_search")).items
    assert any(row.run_id == draft.run_id for row in retained)
    print("The measured run remains indexed after knowledge refresh.")


if __name__ == "__main__":
    main()
```
