"""Define one recomputed evaluation metric."""

from viper.metrics import metric


@metric(metric_id="prediction_bytes", kind="evaluation", mode="recompute")
def prediction_bytes(context) -> float:
    """Return the byte count of the verified prediction artifact."""
    return float(len(context.artifacts["predictions"].read_bytes()))
