"""Compare worker control readings with the saved run settings."""

from ..runtime import ReproducibilitySpec, RuntimeControlsReceipt


def verify_runtime_controls(
    observed: RuntimeControlsReceipt, reproducibility: ReproducibilitySpec, backend: str
) -> None:
    """Reject the first observed control that differs from the plan."""
    if observed.backend != backend:
        raise ValueError("startup.controls: backend differs from the plan")

    # Compare the worker readings with the saved run, including relaxed values.
    expected: dict[str, object] = {
        "deterministic_algorithms": (
            reproducibility.determinism.deterministic_algorithms
        ),
        "deterministic_warn_only": reproducibility.determinism.deterministic_warn_only,
        "float32_matmul_precision": reproducibility.precision.float32_matmul_precision,
        "torch_intraop_threads": reproducibility.parallelism.torch_intraop_threads,
        "torch_interop_threads": reproducibility.parallelism.torch_interop_threads,
        "autocast_enabled": reproducibility.precision.autocast_enabled,
        "autocast_dtype": (
            reproducibility.precision.autocast_dtype
            if reproducibility.precision.autocast_enabled
            else None
        ),
    }

    # cuDNN controls GPU operations. Include these expected values only for
    # CUDA verification; this dictionary update leaves PyTorch state unchanged.
    if backend == "cuda":
        expected.update(
            cudnn_deterministic=reproducibility.determinism.cudnn_deterministic,
            cudnn_benchmark=reproducibility.determinism.cudnn_benchmark,
            cudnn_allow_tf32=reproducibility.precision.cudnn_allow_tf32,
        )
    readings = observed.model_dump()
    for field, value in expected.items():
        if readings[field] != value:
            raise ValueError(f"startup.controls: {field} differs from the plan")
