"""Declare the outputs a stage promises to write."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Generic, Literal, Self, TypeVar, cast

from pydantic import BaseModel, ConfigDict, model_validator

from ._schema import DataRole, ProtocolModel, RepoRelPath
from .artifacts import ArtifactLoaderRef

OutputT = TypeVar("OutputT")


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

    def keys(self) -> tuple[str, ...]:
        """Return declared and workspace-defined output names."""
        declared = tuple(type(self).model_fields)
        extra = tuple(self._extra_outputs())
        return declared + extra

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


__all__ = [
    "EvalOutputs",
    "OutputDraft",
    "OutputSpec",
    "StageOutputs",
    "TrainOutputs",
    "output",
]
