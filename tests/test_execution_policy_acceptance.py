"""Exercise execution policies in fresh CPU and optional CUDA processes."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from viper import _subprocess as subprocess

_PROGRAM = """
import hashlib
import json
import os
import sys

import torch

from viper._verification.runtime import verify_runtime_controls
from viper.runtime import (
    CPUComputeSpec, CUDAComputeSpec, apply_reproducibility, autocast_context,
    observe_process_startup, process_environment, resolve_execution_policy,
)

backend, mode = sys.argv[1:]
selection = resolve_execution_policy("relaxed")[1] if mode == "custom" else mode
policy, settings = resolve_execution_policy(selection)
compute = CPUComputeSpec() if backend == "cpu" else CUDAComputeSpec(
    model="NVIDIA L4", count=1
)
for key, value in process_environment(
    7, settings, compute, cuda_ordinal=0 if backend == "cuda" else None
).items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
initialization = apply_reproducibility(7, settings)
with autocast_context(settings, backend=backend):
    startup = observe_process_startup(initialization, settings, backend)
    values = torch.randn((64, 64), device=backend)
    result = values @ values.T
    # put_ without accumulation has no supported deterministic implementation.
    rejected = False
    try:
        torch.zeros(2, device=backend).put_(
            torch.tensor([0, 1], device=backend),
            torch.tensor([1.0, 2.0], device=backend),
            accumulate=False,
        )
    except RuntimeError as error:
        if "deterministic" not in str(error):
            raise
        rejected = True
verify_runtime_controls(startup.observed_controls, settings, backend)
print(json.dumps({
    "policy": policy.model_dump(mode="json"),
    "startup": startup.model_dump(mode="json"),
    "sha256": hashlib.sha256(result.cpu().numpy().tobytes()).hexdigest(),
    "unsupported_operation_rejected": rejected,
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "cudnn": torch.backends.cudnn.version(),
    "device": torch.cuda.get_device_name(0) if backend == "cuda" else "cpu",
}))
"""


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
@pytest.mark.parametrize(
    "backend",
    [
        "cpu",
        pytest.param(
            "cuda",
            marks=[
                pytest.mark.live_cuda,
                pytest.mark.skipif(
                    os.environ.get("VIPER_LIVE_CUDA") != "1",
                    reason="set VIPER_LIVE_CUDA=1 on the single-L4 acceptance host",
                ),
            ],
        ),
    ],
)
def test_policy_execution_and_repetition(
    tmp_path: Path, backend: str, mode: str
) -> None:
    """Check active controls, operation eligibility, and repeated output bytes."""
    reports = []
    for _ in range(2):
        completed = subprocess.run(
            (sys.executable, "-c", _PROGRAM, backend, mode),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        report = json.loads(completed.stdout)
        assert report["policy"]["mode"] == mode
        assert report["unsupported_operation_rejected"] == (mode == "reproducible")
        controls = report["startup"]["observed_controls"]
        assert controls["backend"] == backend
        assert controls["deterministic_algorithms"] == (mode == "reproducible")
        if backend == "cuda":
            assert report["device"] == "NVIDIA L4"
            assert controls["cudnn_benchmark"] == (mode != "reproducible")
        reports.append(report)
    equal_bytes = reports[0]["sha256"] == reports[1]["sha256"]
    if mode == "reproducible":
        assert equal_bytes
    # Keep relaxed comparisons separate from acceptance of the saved controls.
    evidence_root = Path(os.environ.get("VIPER_POLICY_EVIDENCE_DIR", str(tmp_path)))
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / f"{backend}-{mode}.json").write_text(
        json.dumps({"runs": reports, "equal_bytes": equal_bytes}, indent=2),
        encoding="utf-8",
    )
