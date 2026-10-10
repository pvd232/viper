"""Run a documented journal workflow and retrieve its learned vectors."""

from examples.cpu_quickstart import study
from viper import execution
from viper.authoring import experiment, plan
from viper.catalog import catalog
from viper.journals import encode_journal
from viper.knowledge import AssertionQuery, JournalAssertion, SimilarityQuery
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env


def main() -> None:
    """Create notes, execute the toy fit, and search with the same pinned encoder."""
    root = resolve_root()
    source = read_source(root)
    journal = root / "experiments/journal_demo/JOURNAL.md"
    if not journal.exists():
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_bytes((root / "examples/data/JOURNAL.md").read_bytes())
    selected = experiment(
        experiment_id="journal_demo",
        variants=study.variants,
        replicates=study.replicates,
    )
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    result = execution.run(plan(experiment=selected, source=source, env=environment))
    index = catalog(root=root)
    query = AssertionQuery(statuses=("proposed",))
    current: list[JournalAssertion] = []
    while True:
        page = index.knowledge.assertions(query)
        current.extend(
            item.record.value
            for item in page.items
            if isinstance(item.record.value, JournalAssertion)
            and any(
                evidence.kind == "run"
                and evidence.reference.sha256 == result.reference.sha256
                and evidence.reference.bytes == result.reference.bytes
                and evidence.reference.stored_at == result.reference.stored_at
                for evidence in item.record.value.evidence
            )
        )
        if page.next_cursor is None:
            break
        query = query.model_copy(update={"cursor": page.next_cursor})
    assert current, "Journal capture failed or [journals].enabled is false."
    encoded = encode_journal(("Which experiment reports a final training loss?",))
    matches = index.knowledge.similar(
        SimilarityQuery(
            view_id="journal-qwen3-0.6b",
            view_version=encoded.encodings[0].encoder_sha256,
            values=encoded.values[0],
            assertion_statuses=("proposed",),
            limit=5,
        )
    )
    assert matches.items, "No vectors in this exact encoder/runtime view."
    print("run:", result.path)
    print("captured passages:", len(current))
    print("encoder revision:", encoded.encoder.revision)
    for match in matches.items:
        assertion = match.source.record.value
        assert isinstance(assertion, JournalAssertion)
        print(assertion.kind, assertion.text, "distance:", match.distance)


if __name__ == "__main__":
    main()
