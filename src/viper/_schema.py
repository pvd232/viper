"""Define shared protocol scalars, validators, and the frozen model base."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .ids import HumanId, InputName


def validate_repo_rel_path(value: str) -> str:
    """Validate a normalized, POSIX, repository-relative path."""
    if not value:
        raise ValueError("expected nonempty repository-relative path")
    if "\\" in value:
        raise ValueError("expected POSIX repository-relative path")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("repository-relative path contains a control character")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("expected repository-relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("repository-relative path contains an invalid component")
    return value


def validate_python_file_path(value: str) -> str:
    """Require a path that identifies a Python source file."""
    if not value.endswith(".py"):
        raise ValueError("expected repository-relative Python file path")
    return value


def repo_file_paths_overlap(left: str, right: str) -> bool:
    """Return whether either file path equals or sits below the other."""
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


RepoRelPath = Annotated[str, AfterValidator(validate_repo_rel_path)]
PythonRepoRelPath = Annotated[
    str,
    AfterValidator(validate_repo_rel_path),
    AfterValidator(validate_python_file_path),
]
PythonSymbol = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]
NormalizedDistributionName = Annotated[
    str,
    Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
GitCommit = Annotated[
    str,
    Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
ArtifactName = HumanId
BenchmarkId = HumanId
EvaluationId = HumanId
SelectionName = HumanId
RNGSeed = Annotated[int, Field(ge=0, le=2**32 - 1)]
DataRole = Literal["training", "validation", "evaluation", "benchmark"]

PARAMETERS: ArtifactName = "parameters"
RESUME_STATE: ArtifactName = "resume_state"
PARAMETERS_INPUT: InputName = "parameters"
RESUME_STATE_INPUT: InputName = "resume_state"
EVALUATION_DATASET_INPUT: InputName = "evaluation_dataset"
PREDICTIONS: ArtifactName = "predictions"


class ProtocolModel(BaseModel):
    """Closed, frozen protocol object."""

    model_config = ConfigDict(extra="forbid", frozen=True)


PythonSourceRelPath = Annotated[
    str,
    AfterValidator(validate_repo_rel_path),
    AfterValidator(validate_python_file_path),
]
