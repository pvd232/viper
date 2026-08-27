"""Break the temporary protocol-to-HTTP import cycle during decomposition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

import numpy as np

from . import parameters
from ._schema import ArtifactName
from .ids import HumanId, InputName, MetricId, RunId, StageId

if TYPE_CHECKING:
    from .metrics import MetricHandle

ParamsT = TypeVar("ParamsT", bound=parameters.ParameterSet)


@dataclass(frozen=True)
class StageContext(Generic[ParamsT]):
    """Carry one validated project-stage invocation inside the controlled child."""

    run_id: RunId
    attempt_id: int
    stage_id: StageId
    params: ParamsT
    inputs: Mapping[InputName, Path]
    artifacts: Mapping[ArtifactName, Path]
    metrics: Mapping[MetricId, MetricHandle]
    numpy_generators: Mapping[HumanId, np.random.Generator]
