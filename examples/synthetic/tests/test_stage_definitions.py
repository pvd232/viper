"""Verify generated stages expose their VIPER definitions."""

from sample_project.stages.build import build
from sample_project.stages.download import download
from sample_project.stages.embed import embed
from sample_project.stages.evaluate import evaluate
from sample_project.stages.train import train

from viper.stages import stage_definition


def test_stage_kinds() -> None:
    """Match each callable with the stage kind fixed by its decorator."""
    stages = (download, build, embed, train, evaluate)

    assert tuple(stage_definition(stage).kind for stage in stages) == (
        "download",
        "build",
        "embed",
        "train",
        "evaluate",
    )
