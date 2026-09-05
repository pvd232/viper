"""Select and report files restored from a verified run."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from ._schema import ArtifactName, ProtocolModel
from .ids import StageId
from .references import ResolvedRunRef


def validate_viper_cloud_run_uri(value: str) -> str:
    """Require one sealed Viper Cloud terminal-run URI."""
    if (
        re.fullmatch(
            r"viper://[a-z][a-z0-9_]*/[a-z][a-z0-9_]*@[0-9a-f]{64}/[^?#]+",
            value,
        )
        is None
    ):
        raise ValueError("Viper Cloud run URI is invalid")
    return value


ViperCloudRunUri = Annotated[str, AfterValidator(validate_viper_cloud_run_uri)]


class ArtifactRestoreSelector(ProtocolModel):
    """Select one artifact from one completed stage."""

    stage_id: StageId = Field(description="Stage that produced the artifact.")
    artifact_name: ArtifactName = Field(
        description="Artifact name declared by the selected stage."
    )


class RestoredFile(ProtocolModel):
    """Record one restored or already-correct destination file."""

    path: Path = Field(description="Final path of the verified file.")
    status: Literal["restored", "already_present"] = Field(
        description="Whether VIPER wrote the file or found matching bytes."
    )


class RestoredArtifact(ProtocolModel):
    """Record every file restored for one selected artifact."""

    selector: ArtifactRestoreSelector = Field(
        description="Stage artifact selected by the caller."
    )
    files: tuple[RestoredFile, ...] = Field(
        min_length=1,
        description="Verified files belonging to the selected artifact.",
    )


class RestoreResult(ProtocolModel):
    """Return the immutable run reference and restored artifact files."""

    run: ResolvedRunRef = Field(
        description="Immutable terminal run followed during restore."
    )
    artifacts: tuple[RestoredArtifact, ...] = Field(
        min_length=1,
        description="Artifacts restored from the successful attempt.",
    )


RestoreRunReference = Path | ViperCloudRunUri | ResolvedRunRef

__all__ = [
    "ArtifactRestoreSelector",
    "RestoredArtifact",
    "RestoredFile",
    "RestoreResult",
    "RestoreRunReference",
    "ViperCloudRunUri",
    "validate_viper_cloud_run_uri",
]
