"""CSV preparation and evaluation functions used by the extended examples."""

import json
from pathlib import Path

from pydantic import Field

from viper.config import BuildConfig, EvalConfig, MetricConfig
from viper.metrics import MetricContext, metric
from viper.stages import StageContext, build, eval


def load_text(path: Path) -> str:
    """Read a saved dataset, split, or predictions file."""
    return path.read_text(encoding="utf-8")


class RowLimit(BuildConfig):
    """Select how many training rows to retain after the CSV header."""

    rows: int = Field(ge=1, description="Number of data rows used for training.")


@build(config=RowLimit)
def limit_rows(context: StageContext[RowLimit]) -> None:
    """Write the header and the requested number of training rows."""
    header, *rows = load_text(context.inputs["dataset"]).splitlines()
    context.outputs["dataset"].write_text(
        "\n".join([header, *rows[: context.config.rows]]) + "\n", encoding="utf-8"
    )


@build(config=BuildConfig)
def prepare_test_data(context: StageContext[BuildConfig]) -> None:
    """Write held-out observations and the row indices used for evaluation."""
    context.outputs["test_data"].write_text(
        load_text(context.inputs["source"]), encoding="utf-8"
    )
    context.outputs["test_split"].write_text("[0, 2]\n", encoding="utf-8")


@eval(config=EvalConfig)
def predict(context: StageContext[EvalConfig]) -> None:
    """Save model predictions paired with targets from the selected test rows."""
    model = json.loads(load_text(context.inputs["model"]))
    rows = [
        tuple(float(value) for value in row.split(","))
        for row in load_text(context.inputs["test"]).splitlines()[1:]
    ]
    indices = json.loads(load_text(context.inputs["holdout"]))
    pairs = [[model["weight"] * rows[index][0], rows[index][1]] for index in indices]
    context.outputs["predictions"].write_text(json.dumps(pairs), encoding="utf-8")


@metric(metric_id="root_mean_squared_error", mode="stateless")
def root_mean_squared_error(context: MetricContext[MetricConfig]) -> float:
    """Read predict's saved [prediction, target] pairs and return their RMSE."""
    pairs = json.loads(load_text(context.artifacts["predictions"]))
    if not pairs:
        raise ValueError("root_mean_squared_error requires at least one prediction")
    squared_errors = [(prediction - target) ** 2 for prediction, target in pairs]
    return (sum(squared_errors) / len(pairs)) ** 0.5
