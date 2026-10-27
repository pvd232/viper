"""Verify JAX checkpoint continuation through ordinary VIPER training stages."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Annotated, Literal

import jax
import jax.numpy as jnp
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from viper import execution
from viper.authoring import (
    StageDraft,
    experiment,
    input,
    plan,
    replicate,
    stage,
    variant,
)
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng, restore_main_process_rng
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import StageContext, train

UInt32 = Annotated[int, Field(ge=0, lt=2**32)]
PRNGImplementation = Literal["threefry2x32", "rbg", "unsafe_rbg"]


class Model(BaseModel):
    """Validate the scalar regression parameter saved for prediction."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    weight: float = Field(allow_inf_nan=False, description="Learned regression slope.")


class Checkpoint(BaseModel):
    """Preserve momentum, position and the next unused JAX random key."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = Field(
        default=1, description="Checkpoint format version."
    )
    velocity: float = Field(
        allow_inf_nan=False, description="SGD momentum accumulator."
    )
    step: int = Field(ge=0, description="Number of completed parameter updates.")
    key_data: tuple[UInt32, ...] = Field(
        min_length=1, description="Unsigned key words."
    )
    key_implementation: PRNGImplementation = Field(
        description="JAX PRNG implementation."
    )


class JaxTrainConfig(TrainConfig):
    """Validate the number of additional SGD updates in one training stage."""

    steps: int = Field(default=8, gt=0, description="Updates performed by this stage.")


@partial(
    jax.tree_util.register_dataclass,
    data_fields=("weight", "velocity", "key", "step"),
    meta_fields=(),
)
@dataclass(frozen=True)
class TrainingState:
    """Carry the parameter, optimizer accumulator, random key and update count."""

    weight: jax.Array
    velocity: jax.Array
    key: jax.Array
    step: jax.Array


def load_model(path: Path) -> Model:
    """Validate one prediction parameter from its JSON artifact."""
    return Model.model_validate_json(path.read_bytes())


def load_checkpoint(path: Path) -> ResumeState:
    """Validate checkpoint metadata and the PRNG implementation and key shape."""
    state = load_resume_state(path)
    saved = Checkpoint.model_validate(state.optimizer_state)
    if state.dataloader.state_dict.get("step") != saved.step:
        raise ValueError("saved sampler position differs from the optimizer step")
    jax.random.wrap_key_data(
        jnp.asarray(saved.key_data, dtype=jnp.uint32), impl=saved.key_implementation
    )
    return state


def restore_state(
    model_path: Path,
    checkpoint_path: Path,
    numpy_generators: Mapping[str, np.random.Generator] | None = None,
) -> TrainingState:
    """Rebuild explicit training state from the paired model and checkpoint."""
    model = load_model(model_path)
    checkpoint = load_checkpoint(checkpoint_path)
    saved = Checkpoint.model_validate(checkpoint.optimizer_state)
    restore_main_process_rng(checkpoint.main_process_rng, numpy_generators or {})
    return TrainingState(
        weight=jnp.asarray(model.weight, dtype=jnp.float32),
        velocity=jnp.asarray(saved.velocity, dtype=jnp.float32),
        key=jax.random.wrap_key_data(
            jnp.asarray(saved.key_data, dtype=jnp.uint32), impl=saved.key_implementation
        ),
        step=jnp.asarray(saved.step, dtype=jnp.int32),
    )


def save_state(
    state: TrainingState,
    model_path: Path,
    checkpoint_path: Path,
    numpy_generators: Mapping[str, np.random.Generator] | None = None,
) -> None:
    """Write prediction weights separately from the state needed to continue SGD."""
    model = Model(weight=float(state.weight))
    implementations: tuple[PRNGImplementation, ...] = (
        "threefry2x32",
        "rbg",
        "unsafe_rbg",
    )
    implementation = next(
        name
        for name in implementations
        if jax.random.key_impl(state.key)
        == jax.random.key_impl(jax.random.key(0, impl=name))
    )
    checkpoint = Checkpoint(
        velocity=float(state.velocity),
        step=int(state.step),
        key_data=tuple(int(word) for word in jax.random.key_data(state.key).tolist()),
        key_implementation=implementation,
    )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(model.model_dump_json() + "\n", encoding="utf-8")
    save_resume_state(
        checkpoint_path,
        ResumeState(
            optimizer_state=checkpoint.model_dump(),
            main_process_rng=capture_main_process_rng(
                numpy_generators or {}, capture_legacy_global=True
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"step": int(state.step)},
            ),
        ),
    )


def squared_error(weight: jax.Array, x: jax.Array, y: jax.Array) -> jax.Array:
    """Compute mean squared prediction error for the selected observations."""
    return jnp.mean(jnp.square(weight * x - y))


@jax.jit
def update(state: TrainingState, x: jax.Array, y: jax.Array) -> TrainingState:
    """Split the key, sample one row and apply one momentum SGD update."""
    next_key, sample_key = jax.random.split(state.key)
    row = jax.random.randint(sample_key, (), 0, x.shape[0])
    gradient = jax.grad(squared_error)(state.weight, x[row], y[row])
    velocity = 0.9 * state.velocity + gradient
    return TrainingState(
        weight=state.weight - 0.01 * velocity,
        velocity=velocity,
        key=next_key,
        step=state.step + 1,
    )


@metric(metric_id="jax_mse", mode="stateless")
def mean_squared_error(_context: MetricContext[MetricConfig], value: float) -> float:
    """Record the training stage's full-dataset squared error."""
    return value


@train(config=JaxTrainConfig)
def fit(context: StageContext[JaxTrainConfig]) -> None:
    """Perform JAX training with explicit keys inside VIPER's checkpoint schema."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"].read_text().splitlines()[1:]
    ]
    x = jnp.asarray([row[0] for row in rows], dtype=jnp.float32)
    y = jnp.asarray([row[1] for row in rows], dtype=jnp.float32)
    if "model" in context.inputs:
        state = restore_state(
            context.inputs["model"],
            context.inputs["resume_state"],
            context.numpy_generators,
        )
    else:
        # VIPER seeds Python from the replicate; JAX owns the explicit key thereafter.
        state = TrainingState(
            weight=jnp.asarray(0.0, dtype=jnp.float32),
            velocity=jnp.asarray(0.0, dtype=jnp.float32),
            key=jax.random.key(random.getrandbits(32), impl="threefry2x32"),
            step=jnp.asarray(0, dtype=jnp.int32),
        )
    for _ in range(context.config.steps):
        state = update(state, x, y)
    context.metrics["jax_mse"].record(
        float(squared_error(state.weight, x, y)), step=int(state.step)
    )
    save_state(
        state,
        context.outputs["model"],
        context.outputs["resume_state"],
        context.numpy_generators,
    )


mse = measure(mean_squared_error)


def training_stage(
    name: str, steps: int, previous: StageDraft | None = None
) -> StageDraft:
    """Declare a fresh stage or consume both checkpoint files from its producer."""
    dataset = input("dataset", path="examples/data/tiny.csv", data_role="training")
    inputs = (
        (dataset,)
        if previous is None
        else (dataset, previous.outputs["model"], previous.outputs["resume_state"])
    )
    return stage(
        fit,
        stage_id=name,
        config=JaxTrainConfig(steps=steps),
        inputs=tuple(inputs),
        outputs=TrainOutputs(
            model=output(path="model.json", loader=load_model, data_role="training"),
            resume_state=output(
                path="state.pt", loader=load_checkpoint, data_role="training"
            ),
        ),
        metrics=(mse,),
        objective=min(mse),
        reuse="never",
    )


whole = training_stage("whole", 8)
first = training_stage("first", 3)
resumed = training_stage("resumed", 5, first)
study = experiment(
    experiment_id="jax_training",
    variants=(
        variant(
            "checkpoint",
            stages=(whole, first, resumed),
            estimator=resumed.outputs["model"],
        ),
    ),
    replicates=(replicate(seed=7),),
)


def main() -> None:
    """Run fresh and resumed processes and compare every saved training value."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    result = execution.run(plan(experiment=study, source=source, env=environment))
    run_root = Path(result.path).parent
    artifacts = run_root / "artifacts"
    for name, loader, filename in (
        ("model", load_model, "model.json"),
        ("resume_state", load_checkpoint, "state.pt"),
    ):
        expected = loader(artifacts / "whole" / name / filename)
        actual = loader(artifacts / "resumed" / name / filename)
        if expected != actual:
            raise AssertionError(f"JAX continuation differs for {name}")
    print(f"status: {result.status}")
    print("JAX parameters, momentum, step and next key match after checkpoint resume.")


if __name__ == "__main__":
    main()
