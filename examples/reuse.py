"""Compare default verified reuse with forced computation using real training."""

import hashlib

from examples.cpu_quickstart import fit, load_json, load_state, mse, study
from viper import api, execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.metrics import min
from viper.outputs import TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.restoration import ArtifactRestoreSelector
from viper.runtime import LocalEnvSpec, observe_python_env

forced_training = stage(
    fit,
    stage_id="train",
    inputs=(input("dataset", path="examples/data/tiny.csv", data_role="training"),),
    outputs=TrainOutputs(
        model=output(path="model.json", loader=load_json, data_role="training"),
        resume_state=output(
            path="resume_state.pt", loader=load_state, data_role="training"
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
    reuse="never",
)
forced_study = experiment(
    experiment_id="forced_training",
    variants=(
        variant(
            "baseline",
            stages=(forced_training,),
            estimator=forced_training.outputs["model"],
        ),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Run twice with the default, then force computation and compare model bytes."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    trusted = frozenset({str(source.repository)})
    digests = []
    for label, selected in (
        ("first", study),
        ("default", study),
        ("forced", forced_study),
    ):
        result = execution.run(
            plan(experiment=selected, source=source, env=environment)
        )
        checked = api.verify_run(
            api.VerifyRunRequest(
                root=root, path=result.path, trusted_source_repositories=trusted
            )
        )
        graph = api.lineage(
            api.LineageRequest(
                root=root, path=result.path, trusted_source_repositories=trusted
            )
        )
        reused = sum(node.reuse_key_sha256 is not None for node in graph.nodes)
        restored = execution.restore(
            root,
            result.reference,
            artifacts=(
                ArtifactRestoreSelector(stage_id="train", artifact_name="model"),
            ),
            output=root / "restored" / f"{checked.run_id}.json",
        )
        model = restored.artifacts[0].files[0].path
        digests.append(hashlib.sha256(model.read_bytes()).hexdigest())
        print(f"{label}: {result.status}; reused stages: {reused}")
        print(
            f"verified measurements: {checked.measurement_count}; result: {result.path}"
        )
    assert len(set(digests)) == 1
    print("All three model files have identical bytes.")


if __name__ == "__main__":
    main()
