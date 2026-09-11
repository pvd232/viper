"""Declare the outputs a stage promises to write."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Generic, Literal, Self, TypeVar, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ._schema import DataRole, ProtocolModel, RepoRelPath
from .artifacts import ArtifactLoaderRef
from .ids import OutputName, StageId

OutputT = TypeVar("OutputT")
REPO_REL_PATH = TypeAdapter(RepoRelPath)


class OutputDraft(BaseModel):
    """Hold one callable-backed output before protocol freezing."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    kind: Literal["file", "bundle"] = "file"
    path: RepoRelPath
    loader: Callable[[Path], Any]
    data_role: DataRole


class OutputSpec(ProtocolModel):
    """Declare one output using an exact loader reference."""

    kind: Literal["file", "bundle"] = "file"
    path: RepoRelPath
    loader: ArtifactLoaderRef
    data_role: DataRole


class StageOutputs(BaseModel, Generic[OutputT]):
    """Map workspace-defined output names to values of one lifecycle type."""

    model_config = ConfigDict(extra="allow", frozen=True)

    def __init__(self, /, **data: OutputT) -> None:
        """Accept workspace-defined output names as keyword arguments."""
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def validate_output_values(cls, value: Any) -> Any:
        """Validate extra fields through the concrete generic output type."""
        if not isinstance(value, Mapping):
            return value
        arguments = cls.__pydantic_generic_metadata__.get("args", ())
        if not arguments or isinstance(arguments[0], TypeVar):
            return value
        adapter = TypeAdapter(arguments[0])
        return {name: adapter.validate_python(output) for name, output in value.items()}

    @model_validator(mode="after")
    def validate_output_names(self) -> Self:
        """Require at least one stable Python identifier."""
        names = self.keys()
        if not names:
            raise ValueError("at least one output is required")

        for name in names:
            if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
                raise ValueError(f"output name {name!r} must be a lowercase identifier")

        return self

    def _extra_outputs(self) -> dict[str, OutputT]:
        """Return Pydantic extras through the collection's generic value type."""
        return cast("dict[str, OutputT]", self.__pydantic_extra__ or {})

    def keys(self) -> tuple[OutputName, ...]:
        """Return declared and workspace-defined output names."""
        declared = tuple(type(self).model_fields)
        extra = tuple(self._extra_outputs())
        return cast("tuple[OutputName, ...]", declared + extra)

    def values(self) -> tuple[OutputT, ...]:
        """Return output values in field order."""
        return tuple(self[name] for name in self.keys())

    def items(self) -> tuple[tuple[str, OutputT], ...]:
        """Return output names paired with their values."""
        return tuple((name, self[name]) for name in self.keys())

    def __getitem__(self, name: str) -> OutputT:
        """Return one output by its stable name."""
        if name in type(self).model_fields:
            return getattr(self, name)
        return self._extra_outputs()[name]

    def __len__(self) -> int:
        """Return the number of declared outputs."""
        return len(self.keys())

    def __contains__(self, name: object) -> bool:
        """Report whether an output name is declared."""
        return name in self.keys()


class TrainOutputs(StageOutputs[OutputT], Generic[OutputT]):
    """Require the two values needed to restore training."""

    model: OutputT
    resume_state: OutputT


class EvalOutputs(StageOutputs[OutputT], Generic[OutputT]):
    """Require the canonical evaluation result."""

    predictions: OutputT


def output(
    *,
    path: RepoRelPath,
    loader: Callable[[Path], Any],
    data_role: DataRole,
    kind: Literal["file", "bundle"] = "file",
) -> OutputDraft:
    """Declare one file or directory a stage promises to write."""
    return OutputDraft(
        kind=kind,
        path=path,
        loader=loader,
        data_role=data_role,
    )


def run_output_path(
    *,
    stage_id: StageId,
    output_name: OutputName,
    relative_path: RepoRelPath,
) -> RepoRelPath:
    """Generate the run-relative path owned by one named stage output."""
    return REPO_REL_PATH.validate_python(
        f"artifacts/{stage_id}/{output_name}/{relative_path}"
    )


__all__ = [
    "EvalOutputs",
    "OutputDraft",
    "OutputSpec",
    "StageOutputs",
    "TrainOutputs",
    "output",
    "run_output_path",
]
