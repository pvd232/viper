"""Tests for process-start controls and initialized generator evidence."""

import hashlib
import json

import pytest

from viper._verification.attempt import _verify_startup_backend
from viper.resume import DataLoaderConfiguration
from viper.runtime import (
    CPUBackendContext,
    CPUComputeSpec,
    CUDABackendContext,
    CUDAComputeSpec,
    CUDADeviceContext,
    NumPyRandomnessSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    TorchDeterminismSpec,
    TorchPrecisionSpec,
    apply_reproducibility,
    process_environment,
)
from viper.verification import VerificationError


def _controls() -> ReproducibilitySpec:
    """Build the run controls used by startup tests."""
    return ReproducibilitySpec(
        determinism=TorchDeterminismSpec(
            deterministic_algorithms=True,
            deterministic_warn_only=False,
            cudnn_deterministic=True,
            cudnn_benchmark=False,
            cublas_workspace_config=":4096:8",
        ),
        precision=TorchPrecisionSpec(
            float32_matmul_precision="highest",
            cudnn_allow_tf32=False,
            autocast_enabled=False,
            autocast_dtype=None,
        ),
        parallelism=ParallelismSpec(
            process_count=1,
            torch_intraop_threads=1,
            torch_interop_threads=1,
            dataloader=DataLoaderConfiguration(workers=0),
        ),
        numpy_randomness=NumPyRandomnessSpec(
            generators={"augmentation": "PCG64"},
            capture_legacy_global=True,
        ),
    )


def test_process_environment_hides_cuda_from_a_cpu_stage() -> None:
    """Derive the complete allowlisted startup mapping for CPU execution."""
    values = process_environment(7, _controls(), CPUComputeSpec())

    assert values == {
        "PYTHONHASHSEED": "7",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "CUDA_VISIBLE_DEVICES": "",
    }


def test_process_environment_rejects_multi_gpu_startup() -> None:
    """Route a multi-device request to the deferred distributed contract."""
    with pytest.raises(ValueError, match="startup.distributed"):
        process_environment(
            7,
            _controls(),
            CUDAComputeSpec(model="NVIDIA L4", count=2),
            cuda_ordinal=0,
        )


def test_named_numpy_receipt_identifies_the_delivered_generator() -> None:
    """Hash the same initialized generator object delivered to StageContext."""
    initialized = apply_reproducibility(7, _controls())
    generator = initialized.numpy_generators["augmentation"]
    receipt = next(
        value
        for value in initialized.receipt.generators
        if value.family == "numpy_generator"
    )
    initial_raw = json.dumps(
        generator.bit_generator.state,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert receipt.name == "augmentation"
    assert receipt.state_sha256 == hashlib.sha256(initial_raw).hexdigest()
    generator.random()
    advanced_raw = json.dumps(
        generator.bit_generator.state,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(advanced_raw).hexdigest() != receipt.state_sha256


def _cuda_backend(*models: str) -> CUDABackendContext:
    """Build observed CUDA evidence for named backend-rule tests."""
    return CUDABackendContext(
        gpu_devices=tuple(
            CUDADeviceContext(
                ordinal=ordinal,
                model=model,
                compute_capability_major=8,
                compute_capability_minor=9,
                memory_bytes=24_000_000_000,
            )
            for ordinal, model in enumerate(models)
        ),
        nvidia_driver_version="560.35",
        pytorch_cuda_version="12.6",
        cudnn_version="9.5",
    )


def test_startup_backend_accepts_matching_cpu_and_cuda_evidence() -> None:
    """Accept the backend kind, device count, and model fixed by each request."""
    _verify_startup_backend("train", CPUComputeSpec(), CPUBackendContext())
    _verify_startup_backend(
        "train",
        CUDAComputeSpec(model="NVIDIA L4", count=1),
        _cuda_backend("NVIDIA L4"),
    )


@pytest.mark.parametrize(
    ("compute", "backend", "message"),
    (
        (
            CPUComputeSpec(),
            _cuda_backend("NVIDIA L4"),
            "another backend kind",
        ),
        (
            CUDAComputeSpec(model="NVIDIA L4", count=1),
            _cuda_backend("NVIDIA L4", "NVIDIA L4"),
            "another CUDA device count",
        ),
        (
            CUDAComputeSpec(model="NVIDIA L4", count=1),
            _cuda_backend("NVIDIA H100"),
            "another CUDA model",
        ),
    ),
    ids=("kind", "count", "model"),
)
def test_startup_backend_rejects_changed_observed_evidence(
    compute: CPUComputeSpec | CUDAComputeSpec,
    backend: CPUBackendContext | CUDABackendContext,
    message: str,
) -> None:
    """Reject each observed backend fact that differs from the frozen request."""
    with pytest.raises(VerificationError, match=message):
        _verify_startup_backend("train", compute, backend)
