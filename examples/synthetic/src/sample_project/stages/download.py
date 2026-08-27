"""Execute the example download stage."""

from sample_project.parameters import DownloadParameters
from viper import download_stage


@download_stage(parameter_model=DownloadParameters)
def download(context) -> None:
    """Write the declared dataset artifact from verified inputs."""
    for name, retrieval in context.retrievals.items():
        destination = context.artifacts[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(retrieval.body.read_bytes())
