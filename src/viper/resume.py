"""Capture and restore the state required to resume training exactly."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import torch
from pydantic import Field, model_validator
from torch.optim import Optimizer
from torchdata.stateful_dataloader import StatefulDataLoader

from ._schema import ProtocolModel
from .randomness import (
    MainProcessRNGState,
    capture_main_process_rng,
    restore_main_process_rng,
)


class DataLoaderConfiguration(ProtocolModel):
    """Fix worker and prefetch behavior for the training DataLoader."""

    workers: int = Field(ge=0)
    prefetch_factor: int | None = Field(default=None, ge=1)
    persistent_workers: bool = False
    in_order: Literal[True] = True

    @model_validator(mode="after")
    def validate_worker_configuration(self) -> DataLoaderConfiguration:
        """Enforce valid worker, prefetch, and persistence combinations."""
        if self.workers == 0:
            if self.prefetch_factor is not None:
                raise ValueError("prefetch_factor requires workers > 0")
            if self.persistent_workers:
                raise ValueError("persistent_workers requires workers > 0")
        elif self.prefetch_factor is None:
            raise ValueError("prefetch_factor is required when workers > 0")

        return self


class DataLoaderResumeState(ProtocolModel):
    """DataLoader configuration and state restored at a checkpoint."""

    configuration: DataLoaderConfiguration
    state_dict: dict[str, object] = Field(min_length=1)


class ResumeState(ProtocolModel):
    """State required to continue one training stage exactly."""

    schema_version: Literal[1] = 1
    optimizer_state: dict[str, object] = Field(min_length=1)
    main_process_rng: MainProcessRNGState
    dataloader: DataLoaderResumeState


def dataloader_configuration(
    dataloader: StatefulDataLoader,
) -> DataLoaderConfiguration:
    """Return the resume-relevant configuration of a DataLoader."""
    if not dataloader.in_order:
        raise ValueError("exact resume requires in_order=True")

    return DataLoaderConfiguration(
        workers=dataloader.num_workers,
        prefetch_factor=dataloader.prefetch_factor,
        persistent_workers=dataloader.persistent_workers,
        in_order=True,
    )


def capture_resume_state(
    optimizer: Optimizer,
    dataloader: StatefulDataLoader,
    numpy_generators: Mapping[str, np.random.Generator],
    *,
    capture_legacy_global: bool,
) -> ResumeState:
    """Capture optimizer, main-process RNG, and DataLoader state."""
    return ResumeState(
        optimizer_state=cast(dict[str, object], optimizer.state_dict()),
        main_process_rng=capture_main_process_rng(
            numpy_generators,
            capture_legacy_global=capture_legacy_global,
        ),
        dataloader=DataLoaderResumeState(
            configuration=dataloader_configuration(dataloader),
            state_dict=cast(dict[str, object], dataloader.state_dict()),
        ),
    )


def restore_resume_state(
    resume_state: ResumeState,
    optimizer: Optimizer,
    dataloader: StatefulDataLoader,
    numpy_generators: Mapping[str, np.random.Generator],
) -> None:
    """Restore a checkpoint after model parameters have been restored."""
    current_configuration = dataloader_configuration(dataloader)
    if resume_state.dataloader.configuration != current_configuration:
        raise ValueError(
            "saved DataLoader configuration does not match the current DataLoader"
        )

    optimizer.load_state_dict(cast(dict[str, Any], resume_state.optimizer_state))
    dataloader.load_state_dict(cast(dict[str, Any], resume_state.dataloader.state_dict))
    restore_main_process_rng(resume_state.main_process_rng, numpy_generators)


def save_resume_state(
    path: Path,
    resume_state: ResumeState,
) -> None:
    """Serialize a resume-state artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(resume_state.model_dump(mode="python"), path)


def load_resume_state(path: Path) -> ResumeState:
    """Load and validate a resume-state artifact without executing its contents."""
    loaded = torch.load(
        path,
        map_location="cpu",
        weights_only=True,
    )
    return ResumeState.model_validate(loaded)
