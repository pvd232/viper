"""Live hardware acceptance for the process-startup contract."""

from __future__ import annotations

import os

import pytest
import torch

from tests.fixtures import reproducibility
from viper.protocol import (
    CPUBackendContext,
    CPUComputeSpec,
    CUDABackendContext,
    CUDAComputeSpec,
)
from viper.runtime import (
    observe_local_execution,
    process_environment,
    select_cuda_device,
)

LIVE_CUDA_ENABLED = os.environ.get("VIPER_LIVE_CUDA") == "1"

pytestmark = [
    pytest.mark.live_cuda,
    pytest.mark.skipif(
        not LIVE_CUDA_ENABLED,
        reason="set VIPER_LIVE_CUDA=1 to run live CUDA acceptance",
    ),
]


def test_live_host_exposes_one_nvidia_l4() -> None:
    """Require the single-L4 host selected by the live acceptance profile."""
    assert torch.cuda.is_available()
    assert torch.cuda.device_count() == 1
    assert torch.cuda.get_device_properties(0).name == "NVIDIA L4"


def test_cpu_request_records_cpu_backend_on_l4_host() -> None:
    """Keep a CPU-requested stage on CPU when the host also provides CUDA."""
    assert torch.cuda.is_available()

    execution_context = observe_local_execution(CPUComputeSpec())

    assert isinstance(execution_context.backend, CPUBackendContext)


def test_cuda_request_records_l4_backend_and_executes_cuda() -> None:
    """Record the selected L4 and complete one calculation through CUDA."""
    execution_context = observe_local_execution(
        CUDAComputeSpec(model="NVIDIA L4", count=1)
    )

    backend = execution_context.backend
    assert isinstance(backend, CUDABackendContext)
    assert len(backend.gpu_devices) == 1
    assert backend.gpu_devices[0].ordinal == 0
    assert backend.gpu_devices[0].model == "NVIDIA L4"

    values = torch.tensor([2.0, 3.0], device="cuda")
    result = values.square().sum().item()

    assert result == 13.0


def test_cuda_request_selects_l4_for_child_process() -> None:
    """Expose the selected host L4 to the controlled child process."""
    compute = CUDAComputeSpec(model="NVIDIA L4", count=1)
    host_ordinal = select_cuda_device(compute.model)

    startup_environment = process_environment(
        7,
        reproducibility(),
        compute,
        cuda_ordinal=host_ordinal,
    )

    assert host_ordinal == 0
    assert startup_environment["CUDA_VISIBLE_DEVICES"] == "0"
