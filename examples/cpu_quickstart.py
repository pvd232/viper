"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter

from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.references import GitFileRef, GitSource
from viper.repository import resolve_root
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, ReproducibilitySpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    """Load and validate the terminal training state."""
    return load_resume_state(path)


@metric(metric_id="training_loss", mode="stateless")
def training_loss(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    """Compute mean squared error over matching predictions and targets."""
    if not targets:
        raise ValueError("training_loss requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)


@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    loss = 0.0
    epoch = 0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["training_loss"].record(
            predictions, targets, epoch=epoch, step=epoch
        )
        loss = measurement.value
        errors = tuple(
            prediction - target for prediction, target in zip(predictions, targets)
        )
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient

    model = context.outputs["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    save_resume_state(
        context.outputs["resume_state"],
        ResumeState(
            optimizer_state={"weight": weight, "loss": loss},
            main_process_rng=capture_main_process_rng(
                context.numpy_generators,
                capture_legacy_global=True,
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"epoch": epoch},
            ),
        ),
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
    repository = TypeAdapter(HttpUrl).validate_python(
        _git(root, "remote", "get-url", "origin")
    )
    source = GitSource(repository=repository, commit=commit)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=repository,
            commit=commit,
            path="pyproject.toml",
        ),
        python_env=observe_python_env(),
    )

    loss = measure(training_loss, config=MetricConfig())
    training = stage(
        fit,
        config=TrainConfig(),
        inputs={
            "dataset": input(
                "examples/data/tiny.csv",
                data_role="training",
            )
        },
        outputs=TrainOutputs(
            model=output(
                path="model.json",
                loader=load_json,
                data_role="training",
            ),
            resume_state=output(
                path="resume_state.pt",
                loader=load_state,
                data_role="training",
            ),
        ),
        metrics=(loss,),
        objective=min(loss),
    )
    study = experiment(
        experiment_id="cpu_quickstart",
        variants={
            "baseline": variant(
                levels={},
                stages={"train": training},
                estimator=training.outputs["model"],
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

    resolved_run = execution.run(root, draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path.relative_to(root)}")


if __name__ == "__main__":
    main()
