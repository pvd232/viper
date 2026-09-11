"""Run, verify, compare, restore, and query experiments through Python APIs."""

import json
from datetime import UTC, datetime

from examples.cpu_quickstart import study
from viper import api, execution
from viper.authoring import plan
from viper.catalog import ArtifactQuery, MeasurementQuery, RunQuery, catalog
from viper.inspection import attempt_status
from viper.knowledge import AssertionQuery, JournalAssertion, JournalEvidence, knowledge
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.restoration import ArtifactRestoreSelector
from viper.runtime import LocalEnvSpec, observe_python_env


def main() -> None:
    """Inspect two completed runs and publish the fitted slope as an observation."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    runs = tuple(
        execution.run(
            plan(
                experiment=study,
                source=source,
                env=environment,
            )
        )
        for _ in range(2)
    )
    left, right = runs
    trusted = frozenset({str(source.repository)})
    checked = api.verify_run(
        api.VerifyRunRequest(
            root=root, path=left.path, trusted_source_repositories=trusted
        )
    )
    print(f"verified measurements: {checked.measurement_count}")
    print(f"attempt state: {attempt_status(left.journal_path).state}")
    comparison = api.compare_runs(
        api.CompareRunsRequest(
            left_root=root,
            right_root=root,
            left_path=left.path,
            right_path=right.path,
            trusted_source_repositories=trusted,
        )
    )
    print(f"record differences: {len(comparison.changes)}")
    graph = api.lineage(
        api.LineageRequest(
            root=root, path=left.path, trusted_source_repositories=trusted
        )
    )
    print(f"lineage edges: {len(graph.edges)}")

    restored = execution.restore(
        root,
        left.reference,
        artifacts=(ArtifactRestoreSelector(stage_id="train", artifact_name="model"),),
        output=root / "restored" / f"{checked.run_id}.json",
    )
    model_path = restored.artifacts[0].files[0].path
    weight = json.loads(model_path.read_text(encoding="utf-8"))["weight"]
    print(f"restored weight: {weight:.6f}")

    refresh = api.catalog_refresh(
        api.CatalogRefreshRequest(
            root=root,
            run_paths=tuple(result.path for result in runs),
            trusted_source_repositories=trusted,
        )
    )
    index = catalog(root=root)
    print(f"indexed runs: {refresh.result.accepted}")
    print(
        f"successful runs: {len(index.runs(RunQuery(statuses=('succeeded',))).items)}"
    )
    models = index.artifacts(ArtifactQuery(artifact_names=("model",)))
    print(f"model artifacts: {len(models.items)}")
    query = MeasurementQuery(metric_ids=("mean_squared_error",), limit=7)
    count = 0
    while True:
        page = index.measurements(query)
        count += len(page.items)
        if page.next_cursor is None:
            break
        query = query.model_copy(update={"cursor": page.next_cursor})
    print(f"indexed measurements: {count}")

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
    # This rebuild replaces the run index with the selected knowledge records.
    index.refresh(knowledge=(publication.manifest,))
    observations = index.knowledge.assertions(AssertionQuery(statuses=("proposed",)))
    print(f"observations: {len(observations.items)}")


if __name__ == "__main__":
    main()
