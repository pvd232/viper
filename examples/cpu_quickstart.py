"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from viper import execution, params
from viper.artifacts import artifact
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.metrics import MetricContext, measure, metric, min
from viper.project import resolve_root
from viper.references import GitFileRef, GitSource
from viper.runtime import LocalEnvSpec, ReproducibilitySpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[params.Metric],
    loss: float,
) -> float:
    """Record the training loss computed for one epoch."""
    return loss


@train(params=params.Train)
def fit(context: Context[params.Train]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    weight = 0.0
    loss = 0.0
    for epoch in range(1, 21):
        errors = tuple(weight * x - y for x, y in rows)
        loss = sum(error**2 for error in errors) / len(rows)
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient
        context.metrics["training_loss"].record(loss, epoch=epoch, step=epoch)

    model = context.artifacts["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    context.artifacts["state"].write_text(
        json.dumps({"epoch": epoch, "loss": loss}) + "\n",
        encoding="utf-8",
    )


def _git(root: Path, *arguments: str) -> str:
    """Return one Git value required to identify the checked-out source."""
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _reproducibility() -> ReproducibilitySpec:
    """Use deterministic, single-process CPU settings for the example."""
    return ReproducibilitySpec.model_validate(
        {
            "determinism": {
                "deterministic_algorithms": True,
                "deterministic_warn_only": False,
                "cudnn_deterministic": True,
                "cudnn_benchmark": False,
                "cublas_workspace_config": ":4096:8",
            },
            "precision": {
                "float32_matmul_precision": "highest",
                "cudnn_allow_tf32": False,
                "autocast_enabled": False,
                "autocast_dtype": None,
            },
            "parallelism": {
                "process_count": 1,
                "torch_intraop_threads": 1,
                "torch_interop_threads": 1,
                "dataloader": {
                    "workers": 0,
                    "prefetch_factor": None,
                    "persistent_workers": False,
                    "in_order": True,
                },
            },
            "numpy_randomness": {
                "generators": {"training": "PCG64"},
                "capture_legacy_global": True,
            },
        }
    )


def main() -> None:
    """Author, execute, and report one locally verified run."""
    root = resolve_root(Path(__file__).parent)
    commit = _git(root, "rev-parse", "HEAD")
    repository = _git(root, "remote", "get-url", "origin")
    source = GitSource(repository=repository, commit=commit)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=repository,
            commit=commit,
            path="pyproject.toml",
        ),
        python_env=observe_python_env(),
    )

    loss = measure(training_loss, params=params.Metric())
    training = stage(
        fit,
        params=params.Train(),
        inputs={
            "dataset": input(
                "examples/data/tiny.csv",
                data_role="training",
            )
        },
        artifacts={
            "model": artifact(
                path="artifacts/models/tiny/model.json",
                loader=load_json,
                data_role="training",
            ),
            "state": artifact(
                path="artifacts/models/tiny/state.json",
                loader=load_json,
                data_role="training",
            ),
        },
        metrics=(loss,),
        objective=min(loss),
    )
    study = experiment(
        experiment_id="cpu_quickstart",
        variants={
            "baseline": variant(
                levels={},
                stages={"train": training},
                estimator=training.artifacts["model"],
            )
        },
        replicates={"seed_7": replicate(seed=7)},
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
        reproducibility=_reproducibility(),
    )

    result = execution.run(root, draft)
    model_path = result.resolved_run_path.parent / "artifacts/models/tiny/model.json"
    print(f"status: {result.resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {result.resolved_run_path.relative_to(root)}")


if __name__ == "__main__":
    main()
