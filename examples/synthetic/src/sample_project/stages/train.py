"""Execute the example train stage."""

from sample_project.parameters import TrainParameters
from viper import train_stage


@train_stage(parameter_model=TrainParameters)
def train(context) -> None:
    """Write the trained-weights artifact from verified inputs."""
    source = next(iter(context.inputs.values()))
    payload = source.read_bytes()
    weights_path = context.artifacts["parameters"]
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_bytes(payload)
    context.artifacts["resume_state"].write_bytes(b"resume")
