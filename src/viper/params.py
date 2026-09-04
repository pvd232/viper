import hashlib
import inspect
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ._schema import SHA256, ProtocolModel, PythonSourceRelPath, PythonSymbol


class ParameterSet(BaseModel):
    """A versioned JSON parameter mapping that project classes may specialize."""

    model_config = ConfigDict(extra="allow", frozen=True)

    __pydantic_extra__: dict[str, JsonValue] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        init=False
    )
    schema_version: Literal[1] = 1


class Build(ParameterSet):
    """Parameters consumed by one project-defined prior builder."""


class Embed(ParameterSet):
    """Parameters consumed by one project-defined embedding stage."""


class Train(ParameterSet):
    """Parameters consumed by one project-defined training procedure."""


class Eval(ParameterSet):
    """Model-specific parameters outside the shared eval contract."""

    @model_validator(mode="after")
    def exclude_shared_fields(self) -> Self:
        """Keep metric IDs and split inputs on EvalSpec."""
        supplied = set(self.model_extra or {})
        if {"metric_ids", "split_inputs"} & supplied:
            raise ValueError("metric_ids and split_inputs belong directly on EvalSpec")
        return self


class Metric(ParameterSet):
    """Parameters consumed by one project-defined metric."""


class Http(ParameterSet):
    """Parameters consumed by one project-defined HTTP implementation."""


ParameterModelOwner = Literal["project", "viper"]


class ParameterModelRef(ProtocolModel):
    """Identify one parameter class by owner, source bytes, and symbol."""

    owner: ParameterModelOwner
    path: PythonSourceRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


def model_ref(model: type[ParameterSet]) -> ParameterModelRef:
    """Identify one built-in parameter class by its installed source bytes."""
    path = Path(inspect.getfile(model)).resolve()
    raw = path.read_bytes()
    return ParameterModelRef(
        owner="viper",
        path=path.name,
        symbol=model.__name__,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


__all__ = [
    "Build",
    "Embed",
    "Eval",
    "Http",
    "Metric",
    "ParameterModelOwner",
    "ParameterModelRef",
    "ParameterSet",
    "Train",
    "model_ref",
]
