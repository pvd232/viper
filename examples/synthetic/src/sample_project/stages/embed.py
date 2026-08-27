"""Execute the example embed stage."""

from sample_project.parameters import EmbedParameters
from viper import embed_stage


@embed_stage(parameter_model=EmbedParameters)
def embed(context) -> None:
    """Write the declared embedding artifact from verified inputs."""
    source = next(iter(context.inputs.values()))
    payload = source.read_bytes()
    destination = context.artifacts["embedding"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
