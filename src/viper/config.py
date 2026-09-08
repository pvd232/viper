"""Define built-in and workspace-owned stage config types."""

import hashlib
import inspect
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)

from ._schema import SHA256, ProtocolModel, PythonSourceRelPath, PythonSymbol

JSON_VALUE = TypeAdapter(JsonValue)


class Config(BaseModel):
    """A versioned JSON config mapping that workspace classes may specialize."""

    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: Literal[2] = 2

    @model_validator(mode="after")
    def validate_extra_values(self) -> Self:
        """Keep workspace-defined config fields JSON serializable."""
        if self.model_extra is not None:
            for name, value in self.model_extra.items():
                self.model_extra[name] = JSON_VALUE.validate_python(value)
        return self


class BuildConfig(Config):
    """Config consumed by one workspace-defined build stage."""


class EmbedConfig(Config):
    """Config consumed by one workspace-defined embedding stage."""


class TrainConfig(Config):
    """Config consumed by one workspace-defined training procedure."""


class EvalConfig(Config):
    """Model-specific config outside the shared eval contract."""

    @model_validator(mode="after")
    def exclude_shared_fields(self) -> Self:
        """Keep metric IDs and split inputs on EvalSpec."""
        supplied = set(self.model_extra or {})
        if {"metric_ids", "split_inputs"} & supplied:
            raise ValueError("metric_ids and split_inputs belong directly on EvalSpec")
        return self


class MetricConfig(Config):
    """Config consumed by one workspace-defined metric."""


class HttpConfig(Config):
    """Config consumed by one workspace-defined HTTP implementation."""


class DiagnosticConfig(Config):
    """Config consumed by one workspace-defined diagnostic stage."""


ConfigOwner = Literal["workspace", "viper"]


class ConfigTypeRef(ProtocolModel):
    """Identify one config class by owner, source bytes, and symbol."""

    owner: ConfigOwner
    path: PythonSourceRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


def type_ref(config_type: type[Config]) -> ConfigTypeRef:
    """Identify one built-in config class by its installed source bytes."""
    path = Path(inspect.getfile(config_type)).resolve()
    raw = path.read_bytes()
    return ConfigTypeRef(
        owner="viper",
        path=path.name,
        symbol=config_type.__name__,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


__all__ = [
    "BuildConfig",
    "ConfigOwner",
    "ConfigTypeRef",
    "Config",
    "DiagnosticConfig",
    "EmbedConfig",
    "EvalConfig",
    "HttpConfig",
    "MetricConfig",
    "TrainConfig",
    "type_ref",
]
