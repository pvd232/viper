"""Define project-owned stage parameter models."""

from pydantic import Field

import viper


class DownloadParameters(viper.parameters.Download):
    """Select the expected media type for the retrieved dataset."""

    media_type: str = "text/plain"


class BuildParameters(viper.parameters.Build):
    """Select the delimiter consumed by the prior builder."""

    delimiter: str = ","


class EmbedParameters(viper.parameters.Embed):
    """Select the dimension of the example embedding."""

    dimensions: int = Field(default=2, gt=0)


class TrainParameters(viper.parameters.Train):
    """Select the number of example training passes."""

    epochs: int = Field(default=1, gt=0)


class EvaluateParameters(viper.parameters.Evaluate):
    """Select the label written beside the example predictions."""

    label: str = "baseline"
