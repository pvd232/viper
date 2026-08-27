"""Capture and restore the state required to resume training exactly."""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import numpy as np
import torch
from pydantic import Field, model_validator
from torch.optim import Optimizer
from torchdata.stateful_dataloader import StatefulDataLoader

from ._schema import ProtocolModel
from .ids import HumanId


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


class PythonRNGState(ProtocolModel):
    """Serializable state returned by Python's global random generator."""

    version: int = Field(ge=0)
    internal_state: tuple[int, ...] = Field(min_length=1)
    gaussian_cache: float | None


UInt32 = Annotated[int, Field(ge=0, lt=2**32)]


UInt128 = Annotated[int, Field(ge=0, lt=2**128)]


class PCG64InternalState(ProtocolModel):
    """The 128-bit state and stream increment of one PCG64 generator."""

    state: UInt128
    inc: UInt128


class PCG64GeneratorState(ProtocolModel):
    """Complete state required to restore one NumPy PCG64 generator."""

    bit_generator: Literal["PCG64"] = "PCG64"
    state: PCG64InternalState
    has_uint32: Literal[0, 1]
    uinteger: UInt32


class LegacyNumPyRNGState(ProtocolModel):
    """Complete state required to restore NumPy's global MT19937 generator."""

    bit_generator: Literal["MT19937"] = "MT19937"
    keys: tuple[UInt32, ...] = Field(min_length=624, max_length=624)
    position: int = Field(ge=0, le=624)
    has_gaussian: Literal[0, 1]
    cached_gaussian: float = Field(allow_inf_nan=False)


class NumPyRNGState(ProtocolModel):
    """Named PCG64 states and the optional legacy global NumPy state."""

    generators: dict[HumanId, PCG64GeneratorState]
    legacy_global: LegacyNumPyRNGState | None


class MainProcessRNGState(ProtocolModel):
    """Generator states owned by the main training process."""

    python: PythonRNGState
    numpy: NumPyRNGState
    torch_cpu: bytes = Field(min_length=1)
    torch_cuda: tuple[bytes, ...]


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


def rng_tensor_to_bytes(state: torch.Tensor) -> bytes:
    """Convert one PyTorch generator state into its serialized byte sequence."""
    return bytes(state.cpu().tolist())


def rng_bytes_to_tensor(state: bytes) -> torch.Tensor:
    """Reconstruct one PyTorch generator state from its byte sequence."""
    return torch.tensor(tuple(state), dtype=torch.uint8)


def capture_pcg64_generator(
    generator: np.random.Generator,
) -> PCG64GeneratorState:
    """Capture one named PCG64 generator."""
    if not isinstance(generator.bit_generator, np.random.PCG64):
        raise ValueError("named NumPy generators must use PCG64")

    state = cast(dict[str, Any], generator.bit_generator.state)
    internal = cast(dict[str, int], state["state"])

    return PCG64GeneratorState(
        bit_generator="PCG64",
        state=PCG64InternalState(
            state=int(internal["state"]),
            inc=int(internal["inc"]),
        ),
        has_uint32=cast(Literal[0, 1], state["has_uint32"]),
        uinteger=int(state["uinteger"]),
    )


def restore_pcg64_generator(
    saved: PCG64GeneratorState,
    generator: np.random.Generator,
) -> None:
    """Restore one named PCG64 generator."""
    if not isinstance(generator.bit_generator, np.random.PCG64):
        raise ValueError("named NumPy generators must use PCG64")

    generator.bit_generator.state = {
        "bit_generator": saved.bit_generator,
        "state": {
            "state": saved.state.state,
            "inc": saved.state.inc,
        },
        "has_uint32": saved.has_uint32,
        "uinteger": saved.uinteger,
    }


def capture_legacy_numpy_state() -> LegacyNumPyRNGState:
    """Capture NumPy's legacy global MT19937 state."""
    (
        bit_generator,
        keys,
        position,
        has_gaussian,
        cached_gaussian,
    ) = np.random.get_state(legacy=True)

    if bit_generator != "MT19937":
        raise ValueError("legacy NumPy global state must use MT19937")

    return LegacyNumPyRNGState(
        bit_generator="MT19937",
        keys=tuple(int(value) for value in keys),
        position=int(position),
        has_gaussian=1 if int(has_gaussian) == 1 else 0,
        cached_gaussian=float(cached_gaussian),
    )


def restore_legacy_numpy_state(state: LegacyNumPyRNGState) -> None:
    """Restore NumPy's legacy global MT19937 state."""
    np.random.set_state(
        (
            state.bit_generator,
            np.asarray(state.keys, dtype=np.uint32),
            state.position,
            state.has_gaussian,
            state.cached_gaussian,
        )
    )


def capture_main_process_rng(
    numpy_generators: Mapping[str, np.random.Generator],
    *,
    capture_legacy_global: bool,
) -> MainProcessRNGState:
    """Capture the main process generator states."""
    python_version, python_internal, python_gaussian = random.getstate()

    return MainProcessRNGState(
        python=PythonRNGState(
            version=python_version,
            internal_state=tuple(int(value) for value in python_internal),
            gaussian_cache=python_gaussian,
        ),
        numpy=NumPyRNGState(
            generators={
                generator_id: capture_pcg64_generator(generator)
                for generator_id, generator in numpy_generators.items()
            },
            legacy_global=(
                capture_legacy_numpy_state() if capture_legacy_global else None
            ),
        ),
        torch_cpu=rng_tensor_to_bytes(torch.get_rng_state()),
        torch_cuda=tuple(
            rng_tensor_to_bytes(state) for state in torch.cuda.get_rng_state_all()
        ),
    )


def restore_main_process_rng(
    state: MainProcessRNGState,
    numpy_generators: Mapping[str, np.random.Generator],
) -> None:
    """Restore the main process generator states."""
    saved_names = set(state.numpy.generators)
    supplied_names = set(numpy_generators)

    if saved_names != supplied_names:
        raise ValueError(
            "saved NumPy generator names do not match the supplied generators"
        )

    random.setstate(
        (
            state.python.version,
            state.python.internal_state,
            state.python.gaussian_cache,
        )
    )

    for generator_id, saved_generator in state.numpy.generators.items():
        restore_pcg64_generator(
            saved_generator,
            numpy_generators[generator_id],
        )

    if state.numpy.legacy_global is not None:
        restore_legacy_numpy_state(state.numpy.legacy_global)

    torch.set_rng_state(rng_bytes_to_tensor(state.torch_cpu))

    if len(state.torch_cuda) != torch.cuda.device_count():
        raise ValueError(
            "saved CUDA generator count does not match the available CUDA devices"
        )

    if state.torch_cuda:
        torch.cuda.set_rng_state_all(
            tuple(rng_bytes_to_tensor(cuda_state) for cuda_state in state.torch_cuda)
        )


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
