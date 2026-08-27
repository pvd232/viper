"""Define the public parameter categories that projects may specialize."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ._schema import SHA256, ProtocolModel, PythonRepoRelPath, PythonSymbol


class ParameterSet(BaseModel):
    """A versioned JSON parameter mapping that project classes may specialize."""

    model_config = ConfigDict(extra="allow", frozen=True)

    __pydantic_extra__: dict[str, JsonValue] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        init=False
    )
    schema_version: Literal[1] = 1


class Download(ParameterSet):
    """Parameters consumed by one project-defined download procedure."""


class Build(ParameterSet):
    """Parameters consumed by one project-defined prior builder."""


class Embed(ParameterSet):
    """Parameters consumed by one project-defined embedding stage."""


class Train(ParameterSet):
    """Parameters consumed by one project-defined training procedure."""


class Evaluate(ParameterSet):
    """Model-specific parameters outside the shared evaluation contract."""

    @model_validator(mode="after")
    def exclude_shared_fields(self) -> Self:
        """Keep metric IDs and split inputs on EvaluateSpec."""
        supplied = set(self.model_extra or {})
        if {"metric_ids", "split_inputs"} & supplied:
            raise ValueError(
                "metric_ids and split_inputs belong directly on EvaluateSpec"
            )
        return self


class Metric(ParameterSet):
    """Parameters consumed by one project-defined metric."""


class HttpTransport(ParameterSet):
    """Parameters consumed by one project-defined HTTP transport."""


class ParameterModelRef(ProtocolModel):
    """Identify one project-owned Pydantic parameter class by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


__all__ = [
    "Build",
    "Download",
    "Embed",
    "Evaluate",
    "HttpTransport",
    "Metric",
    "ParameterModelRef",
    "Train",
]
