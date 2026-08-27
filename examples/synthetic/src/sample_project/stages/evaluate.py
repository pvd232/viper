"""Execute the example evaluate stage."""

from sample_project.parameters import EvaluateParameters
from viper import evaluate_stage


@evaluate_stage(parameter_model=EvaluateParameters)
def evaluate(context) -> None:
    """Write the declared predictions artifact from verified inputs."""
    payload = context.inputs["parameters"].read_bytes()
    destination = context.artifacts["predictions"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
