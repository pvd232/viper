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
