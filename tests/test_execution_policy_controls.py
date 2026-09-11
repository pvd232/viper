"""Check observed policy controls and reject altered worker readings."""

import os
import sys
from pathlib import Path

import pytest
import torch

from viper import _subprocess as subprocess
from viper._verification.runtime import verify_runtime_controls
from viper.runtime import (
    ProcessStartupReceipt,
    RuntimeControlsReceipt,
    observe_runtime_controls,
    resolve_execution_policy,
)


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
def test_policy_controls_from_fresh_worker(mode: str) -> None:
    """Apply one policy in a fresh process and verify its recorded readings."""
    program = """
import sys
from viper.runtime import (
    apply_reproducibility, autocast_context, observe_process_startup,
    resolve_execution_policy,
)
from viper._verification.runtime import verify_runtime_controls
mode = sys.argv[1]
selection = resolve_execution_policy("relaxed")[1] if mode == "custom" else mode
policy, settings = resolve_execution_policy(selection)
initialization = apply_reproducibility(7, settings)
with autocast_context(settings, backend="cpu"):
    startup = observe_process_startup(initialization, settings, "cpu")
verify_runtime_controls(startup.observed_controls, settings, "cpu")
print(startup.observed_controls.model_dump_json())
"""
    completed = subprocess.run(
        (sys.executable, "-c", program, mode),
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
            "CUDA_VISIBLE_DEVICES": "",
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = RuntimeControlsReceipt.model_validate_json(completed.stdout)
    assert observed.deterministic_algorithms == (mode == "reproducible")
    assert observed.autocast_enabled is False


def test_policy_controls_observe_autocast_scope() -> None:
    """Read the enabled dtype while the caller's autocast context is active."""
    with torch.autocast("cpu", dtype=torch.bfloat16):
        observed = observe_runtime_controls("cpu")
    assert observed.autocast_enabled is True
    assert observed.autocast_dtype == "bfloat16"
    with torch.autocast("cpu", enabled=False):
        disabled = observe_runtime_controls("cpu")
    assert disabled.autocast_enabled is False
    assert disabled.autocast_dtype is None


@pytest.mark.parametrize(
    "field",
    [
        "deterministic_algorithms",
        "deterministic_warn_only",
        "cudnn_deterministic",
        "cudnn_benchmark",
        "cudnn_allow_tf32",
        "float32_matmul_precision",
        "torch_intraop_threads",
        "torch_interop_threads",
        "autocast_enabled",
        "autocast_dtype",
        "backend",
    ],
)
def test_policy_controls_reject_altered_reading(field: str) -> None:
    """Reject each altered CUDA receipt field while preserving requested settings."""
    _, settings = resolve_execution_policy()
    values = {
        "backend": "cuda",
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "cudnn_allow_tf32": False,
        "float32_matmul_precision": "highest",
        "torch_intraop_threads": 1,
        "torch_interop_threads": 1,
        "autocast_enabled": False,
        "autocast_dtype": None,
    }
    verify_runtime_controls(
        RuntimeControlsReceipt.model_validate(values), settings, "cuda"
    )
    altered = {
        "backend": "cpu",
        "deterministic_algorithms": False,
        "deterministic_warn_only": True,
        "cudnn_deterministic": False,
        "cudnn_benchmark": True,
        "cudnn_allow_tf32": True,
        "float32_matmul_precision": "high",
        "torch_intraop_threads": 2,
        "torch_interop_threads": 2,
        "autocast_enabled": True,
        "autocast_dtype": "bfloat16",
    }
    values[field] = altered[field]
    with pytest.raises(ValueError, match=field):
        verify_runtime_controls(
            RuntimeControlsReceipt.model_validate(values), settings, "cuda"
        )


def test_policy_receipt_fields_describe_saved_values() -> None:
    """Preserve a generated-schema description for every receipt field."""
    for model in (RuntimeControlsReceipt, ProcessStartupReceipt):
        properties = model.model_json_schema()["properties"]
        for name, schema in properties.items():
            assert schema.get("description", "").strip(), (model.__name__, name)
