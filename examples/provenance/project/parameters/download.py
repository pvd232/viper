"""Validate download parameters for the provenance example."""

import viper


class DownloadParameters(viper.parameters.Download):
    """Accept the download parameters frozen by the example stage."""
