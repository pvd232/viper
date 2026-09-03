"""Tests for process-start controls and initialized generator evidence."""

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import viper.runtime as runtime
from viper import _subprocess
from viper._verification.attempt import _verify_startup_backend
from viper.preflight import _git_bytes
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
from viper.verification.models import VerificationError


def _run_git(root: Path, *arguments: str) -> None:
    """Create the committed Git fixture through the spawn-safe facade."""
    _subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
    )


def test_run_uses_spawn_bridge_without_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the target with cwd, environment, and input while fork is disabled."""
    monkeypatch.setattr(_subprocess, "_use_spawn_bridge", lambda: True)

    def reject_fork(*args: object, **kwargs: object) -> None:
        raise AssertionError("spawn-safe execution called fork")

    monkeypatch.setattr(subprocess, "_fork_exec", reject_fork)
    environment = {**os.environ, "VIPER_SPAWN_VALUE": "observed"}
    completed = _subprocess.run(
        (
            sys.executable,
            "-c",
            "import os,sys; print(os.getcwd()); "
            "print(os.environ['VIPER_SPAWN_VALUE']); print(sys.stdin.read())",
        ),
        cwd=tmp_path,
        env=environment,
        input="payload",
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        str(tmp_path),
        "observed",
        "payload",
    ]


def test_popen_preserves_new_process_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply ``start_new_session`` inside the bridge before target execution."""
    monkeypatch.setattr(_subprocess, "_use_spawn_bridge", lambda: True)
    process = _subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import os; print(os.getsid(0) == os.getpid())",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr.decode(errors="replace")
    assert stdout == b"True\n"


def test_run_rejects_nonzero_target_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require successful target execution when ``check`` is enabled."""
    monkeypatch.setattr(_subprocess, "_use_spawn_bridge", lambda: True)

    with pytest.raises(subprocess.CalledProcessError) as failure:
        _subprocess.run(
            (sys.executable, "-c", "raise SystemExit(7)"),
            capture_output=True,
            check=True,
        )

    assert failure.value.returncode == 7


def test_preflight_git_read_executes_without_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read committed bytes through the migrated preflight process boundary."""
    _run_git(tmp_path, "init", "--quiet")
    _run_git(tmp_path, "config", "user.name", "VIPER test")
    _run_git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "value.txt").write_text("committed\n", encoding="utf-8")
    _run_git(tmp_path, "add", "value.txt")
    _run_git(tmp_path, "commit", "--quiet", "-m", "fixture")
    monkeypatch.setattr(_subprocess, "_use_spawn_bridge", lambda: True)

    def reject_fork(*args: object, **kwargs: object) -> None:
        raise AssertionError("preflight Git read called fork")

    monkeypatch.setattr(subprocess, "_fork_exec", reject_fork)

    assert _git_bytes(tmp_path, "HEAD", "value.txt") == b"committed\n"


def test_runtime_observation_does_not_invoke_platform_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid the hidden subprocess used by ``platform.processor()``."""

    def reject_processor_probe() -> str:
        raise AssertionError("runtime observation launched the processor probe")

    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime.platform, "processor", reject_processor_probe)

    observed = runtime.observe_local_execution(CPUComputeSpec())

    assert observed.cpu.model == observed.cpu.architecture


def test_repository_launch_sites_use_spawn_safe_subprocess() -> None:
    """Keep repository-owned subprocess calls behind the spawn-safe facade."""
    repository_root = Path(__file__).parents[1]
    search_roots = (repository_root / "src/viper", repository_root / "tests")
    direct_imports: list[str] = []
    for search_root in search_roots:
        for path in sorted(search_root.rglob("*.py")):
            relative_path = path.relative_to(repository_root).as_posix()
            if relative_path in {
                "src/viper/_subprocess.py",
                "tests/test_process_startup.py",
            }:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    alias.name == "subprocess" for alias in node.names
                ):
                    direct_imports.append(relative_path)
                if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                    direct_imports.append(relative_path)

    assert direct_imports == []


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
    """Hash the same initialized generator object delivered to Context."""
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
