"""Execute the example build stage."""

from sample_project.parameters import BuildParameters
from viper import build_stage


@build_stage(parameter_model=BuildParameters)
def build(context) -> None:
    """Write the declared prior artifact from verified inputs."""
    source = next(iter(context.inputs.values()))
    payload = source.read_bytes()
    destination = context.artifacts["prior"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
