"""Validated identifier types shared by VIPER provenance records."""

from typing import Annotated

from pydantic import Field

RunId = Annotated[
    str,
    Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$"),
]

HumanId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]*$"),
]

ExperimentId = HumanId
VariantId = HumanId
FactorId = HumanId
LevelId = HumanId
ReplicateId = HumanId
StageId = HumanId
InputName = HumanId
MetricId = HumanId
EvalId = HumanId
