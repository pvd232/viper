"""Compare worker control readings with the saved run settings."""

from ..runtime import ReproducibilitySpec, RuntimeControlsReceipt


def verify_runtime_controls(
    observed: RuntimeControlsReceipt, settings: ReproducibilitySpec, backend: str
) -> None:
    """Reject the first observed control that differs from the plan."""
    if observed.backend != backend:
        raise ValueError("startup.controls: backend differs from the plan")

    # Compare the worker readings with the saved run, including relaxed values.
    expected: dict[str, object] = {
        "deterministic_algorithms": settings.determinism.deterministic_algorithms,
        "deterministic_warn_only": settings.determinism.deterministic_warn_only,
        "float32_matmul_precision": settings.precision.float32_matmul_precision,
        "torch_intraop_threads": settings.parallelism.torch_intraop_threads,
        "torch_interop_threads": settings.parallelism.torch_interop_threads,
        "autocast_enabled": settings.precision.autocast_enabled,
        "autocast_dtype": (
            settings.precision.autocast_dtype
            if settings.precision.autocast_enabled
            else None
        ),
    }

    # cuDNN controls GPU operations. Include these expected values only for
    # CUDA verification; this dictionary update leaves PyTorch state unchanged.
    if backend == "cuda":
        expected.update(
            cudnn_deterministic=settings.determinism.cudnn_deterministic,
            cudnn_benchmark=settings.determinism.cudnn_benchmark,
            cudnn_allow_tf32=settings.precision.cudnn_allow_tf32,
        )
    readings = observed.model_dump()
    for field, value in expected.items():
        if readings[field] != value:
            raise ValueError(f"startup.controls: {field} differs from the plan")
