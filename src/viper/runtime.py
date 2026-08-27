"""Apply run-wide reproducibility controls and observe the active Python runtime."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pickle
import platform
import random
import re
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, cast

import numpy as np
import torch
from pydantic import Field, model_validator

from ._schema import (
    SHA256,
    NonEmptyStr,
    NormalizedDistributionName,
    ProtocolModel,
    RNGSeed,
)
from .ids import HumanId
from .references import GitFileRef, ResolvedGitFileRef


class GCEBootImageRef(ProtocolModel):
    """Select one immutable Google Compute Engine boot image."""

    kind: Literal["boot_image"] = "boot_image"
    project: NonEmptyStr
    name: NonEmptyStr
    id: NonEmptyStr


class GCEMachineImageRef(ProtocolModel):
    """Select one immutable Google Compute Engine machine image."""

    kind: Literal["machine_image"] = "machine_image"
    project: NonEmptyStr
    name: NonEmptyStr
    id: NonEmptyStr


GCEProvisioningRef = Annotated[
    GCEBootImageRef | GCEMachineImageRef,
    Field(discriminator="kind"),
]


class PythonDistributionSpec(ProtocolModel):
    """Fix one normalized installed Python distribution and version."""

    name: NormalizedDistributionName
    version: NonEmptyStr


class PythonEnvironmentSpec(ProtocolModel):
    """Fix the interpreter and installed distributions used by a stage."""

    python_version: NonEmptyStr
    distributions: tuple[PythonDistributionSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distribution_order(self) -> PythonEnvironmentSpec:
        """Require one canonically ordered entry for each distribution name."""
        names = tuple(distribution.name for distribution in self.distributions)
        if names != tuple(sorted(names)):
            raise ValueError("Python distributions must be sorted by name")
        if len(set(names)) != len(names):
            raise ValueError("Python distribution names must be unique")
        return self


class CPUComputeSpec(ProtocolModel):
    """Request CPU execution for a stage."""

    kind: Literal["cpu"] = "cpu"


class CUDAComputeSpec(ProtocolModel):
    """Request a specific CUDA device model and count."""

    kind: Literal["cuda"] = "cuda"
    model: NonEmptyStr
    count: int = Field(ge=1)


ComputeSpec = Annotated[
    CPUComputeSpec | CUDAComputeSpec,
    Field(discriminator="kind"),
]


class GCEEnvironmentSpec(ProtocolModel):
    """Declare the requested Google Compute Engine environment."""

    kind: Literal["gce"] = "gce"
    provisioning: GCEProvisioningRef
    machine_type: NonEmptyStr
    compute: ComputeSpec
    lockfile: GitFileRef
    python_environment: PythonEnvironmentSpec


class ResolvedGCEEnvironment(ProtocolModel):
    """Record the environment realized for one stage execution."""

    kind: Literal["gce"] = "gce"
    provisioning: GCEProvisioningRef
    machine_type: NonEmptyStr
    compute: ComputeSpec
    lockfile: ResolvedGitFileRef
    python_environment: PythonEnvironmentSpec


class LocalEnvironmentSpec(ProtocolModel):
    """Declare a local development environment fixed by one lockfile."""

    kind: Literal["local"] = "local"
    compute: ComputeSpec = Field(default_factory=CPUComputeSpec)
    lockfile: GitFileRef
    python_environment: PythonEnvironmentSpec


class ResolvedLocalEnvironment(ProtocolModel):
    """Record the local development environment used by one stage."""

    kind: Literal["local"] = "local"
    compute: ComputeSpec = Field(default_factory=CPUComputeSpec)
    lockfile: ResolvedGitFileRef
    python_environment: PythonEnvironmentSpec


EnvironmentSpec = Annotated[
    GCEEnvironmentSpec | LocalEnvironmentSpec,
    Field(discriminator="kind"),
]


ResolvedEnvironment = Annotated[
    ResolvedGCEEnvironment | ResolvedLocalEnvironment,
    Field(discriminator="kind"),
]


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


class NumPyRandomnessSpec(ProtocolModel):
    """Named NumPy generators and legacy-global capture applied run-wide."""

    generators: dict[HumanId, Literal["PCG64"]] = Field(default_factory=dict)
    capture_legacy_global: bool = False


class TorchDeterminismSpec(ProtocolModel):
    """PyTorch, cuDNN, and cuBLAS determinism controls."""

    deterministic_algorithms: bool
    deterministic_warn_only: bool
    cudnn_deterministic: bool
    cudnn_benchmark: bool
    cublas_workspace_config: Literal[":16:8", ":4096:8"] | None


class TorchPrecisionSpec(ProtocolModel):
    """PyTorch numerical-precision controls that can affect output values."""

    float32_matmul_precision: Literal["highest", "high", "medium"]
    cudnn_allow_tf32: bool

    autocast_enabled: bool
    autocast_dtype: Literal["float16", "bfloat16"] | None

    @model_validator(mode="after")
    def validate_autocast(self) -> TorchPrecisionSpec:
        """Require an autocast dtype exactly when autocast is enabled."""
        if self.autocast_enabled and self.autocast_dtype is None:
            raise ValueError("autocast_dtype is required when autocast_enabled is true")

        if not self.autocast_enabled and self.autocast_dtype is not None:
            raise ValueError(
                "autocast_dtype must be null when autocast_enabled is false"
            )

        return self


class ParallelismSpec(ProtocolModel):
    """Fix process, thread-pool, and DataLoader parallelism run-wide."""

    process_count: int = Field(ge=1)
    torch_intraop_threads: int = Field(ge=1)
    torch_interop_threads: int = Field(ge=1)

    dataloader: DataLoaderConfiguration


class ReproducibilitySpec(ProtocolModel):
    """Numerical controls applied to every stage in a run."""

    determinism: TorchDeterminismSpec
    precision: TorchPrecisionSpec
    parallelism: ParallelismSpec
    numpy_randomness: NumPyRandomnessSpec


GeneratorFamily = Literal[
    "python",
    "numpy_generator",
    "numpy_legacy",
    "torch_cpu",
    "torch_cuda",
]


class GeneratorInitializationReceipt(ProtocolModel):
    """Identify one generator state immediately after seeded initialization."""

    family: GeneratorFamily
    seed: RNGSeed
    name: HumanId | None = None
    device_index: int | None = Field(default=None, ge=0)
    state_sha256: SHA256

    @model_validator(mode="after")
    def validate_identity_fields(self) -> GeneratorInitializationReceipt:
        """Match optional identity fields to their generator family."""
        if (self.family == "numpy_generator") != (self.name is not None):
            raise ValueError("name is required exactly for a named NumPy generator")
        if (self.family == "torch_cuda") != (self.device_index is not None):
            raise ValueError("device_index is required exactly for a CUDA generator")
        return self


StartupVariable = Literal[
    "CUBLAS_WORKSPACE_CONFIG",
    "CUDA_VISIBLE_DEVICES",
    "MKL_NUM_THREADS",
    "OMP_NUM_THREADS",
    "PYTHONHASHSEED",
]


class ProcessStartupReceipt(ProtocolModel):
    """Record the startup environment, applied controls, and seeded generators."""

    environment: dict[StartupVariable, str]
    reproducibility: ReproducibilitySpec
    generators: tuple[GeneratorInitializationReceipt, ...]


class GCEHostContext(ProtocolModel):
    """Record the Google Compute Engine host observed at execution."""

    provider: Literal["gce"] = "gce"

    project_id: NonEmptyStr
    provisioning: GCEProvisioningRef
    machine_type: NonEmptyStr
    zone: NonEmptyStr

    guest_os_name: NonEmptyStr
    guest_os_version: NonEmptyStr
    kernel_release: NonEmptyStr


class LocalHostContext(ProtocolModel):
    """Record the operating system observed by a local development worker."""

    provider: Literal["local"] = "local"
    operating_system: NonEmptyStr
    release: NonEmptyStr
    architecture: NonEmptyStr


HostContext = Annotated[
    GCEHostContext | LocalHostContext,
    Field(discriminator="provider"),
]


class CPUContext(ProtocolModel):
    """Record the CPU available to the execution.

    Instruction-set features can change numerical-library implementation
    choices.
    """

    architecture: NonEmptyStr
    model: NonEmptyStr
    instruction_features: tuple[NonEmptyStr, ...] = Field(min_length=1)


class CPUBackendContext(ProtocolModel):
    """Records that PyTorch executed without a GPU backend."""

    kind: Literal["cpu"] = "cpu"
    device: Literal["cpu"] = "cpu"


class CUDADeviceContext(ProtocolModel):
    """Record one CUDA device observed at execution."""

    ordinal: int = Field(ge=0)
    model: NonEmptyStr

    compute_capability_major: int = Field(ge=0)
    compute_capability_minor: int = Field(ge=0)

    memory_bytes: int = Field(gt=0)


class CUDABackendContext(ProtocolModel):
    """The CUDA backend and devices observed during execution."""

    kind: Literal["cuda"] = "cuda"

    gpu_devices: tuple[CUDADeviceContext, ...] = Field(min_length=1)

    nvidia_driver_version: NonEmptyStr
    pytorch_cuda_version: NonEmptyStr
    cudnn_version: NonEmptyStr

    @model_validator(mode="after")
    def validate_unique_device_ordinals(self) -> CUDABackendContext:
        """Require one record per CUDA device ordinal."""
        ordinals = tuple(device.ordinal for device in self.gpu_devices)
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("CUDA device ordinals must be unique")
        return self


ComputeBackendContext = Annotated[
    CPUBackendContext | CUDABackendContext,
    Field(discriminator="kind"),
]


class NativeLibraryContext(ProtocolModel):
    """Record one native numerical library implementation and version."""

    implementation: NonEmptyStr
    version: NonEmptyStr


class NativeThreadPoolContext(NativeLibraryContext):
    """Record one native library and its active thread count."""

    threads: int = Field(ge=1)


class NumericalRuntimeContext(ProtocolModel):
    """Record language, framework, and numerical-library versions."""

    python_version: NonEmptyStr
    pytorch_version: NonEmptyStr
    numpy_version: NonEmptyStr

    blas: NativeLibraryContext
    lapack: NativeLibraryContext
    native_thread_pools: tuple[NativeThreadPoolContext, ...]


class RandomnessContext(ProtocolModel):
    """Record the global seed applied to each supported generator family."""

    python_seed: RNGSeed
    numpy_seed: RNGSeed
    torch_seed: RNGSeed
    dataloader_seed: RNGSeed

    @model_validator(mode="after")
    def validate_shared_seed(self) -> RandomnessContext:
        """Require every recorded generator family to use the global seed."""
        seeds = {
            self.python_seed,
            self.numpy_seed,
            self.torch_seed,
            self.dataloader_seed,
        }
        if len(seeds) != 1:
            raise ValueError("all recorded random-number generators must use one seed")
        return self


class ExecutionContext(ProtocolModel):
    """Facts observed from the host and running process.

    The GCE environment records the machine image and dependency lockfile
    supplied to the execution. This class records the host and runtime
    conditions under which it ran.
    """

    host: HostContext
    cpu: CPUContext
    backend: ComputeBackendContext
    numerical_runtime: NumericalRuntimeContext


_GCE_METADATA_ROOT = "http://metadata.google.internal/computeMetadata/v1"
MetadataGetter = Callable[[str], str]
ProvisioningIdGetter = Callable[[str, str, str], str]


@dataclass(frozen=True)
class RuntimeInitialization:
    """Return the live named generators and the startup evidence for one child."""

    numpy_generators: dict[str, np.random.Generator]
    receipt: ProcessStartupReceipt


def observe_python_environment() -> PythonEnvironmentSpec:
    """Record the interpreter and every installed Python distribution."""
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        try:
            raw_name = distribution.metadata["Name"]
        except KeyError:
            continue
        name = re.sub(r"[-_.]+", "-", raw_name).lower()
        version = distribution.version
        previous = versions.get(name)
        if previous is not None and previous != version:
            raise RuntimeError(f"installed distribution {name!r} has multiple versions")
        versions[name] = version
    if not versions:
        raise RuntimeError("the active Python environment has no distributions")
    return PythonEnvironmentSpec(
        python_version=platform.python_version(),
        distributions=tuple(
            PythonDistributionSpec(name=name, version=versions[name])
            for name in sorted(versions)
        ),
    )


def _gce_metadata(path: str) -> str:
    """Read one predefined value from the GCE metadata server."""
    request = urllib.request.Request(
        f"{_GCE_METADATA_ROOT}/{path}",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def _gce_provisioning_id(kind: str, project: str, name: str) -> str:
    """Return the server-defined ID for one GCE provisioning resource."""
    token = json.loads(_gce_metadata("instance/service-accounts/default/token"))
    access_token = cast(str, token["access_token"])
    project_value = urllib.parse.quote(project, safe="")
    resource_value = urllib.parse.quote(name, safe="")
    collection = "images" if kind == "boot_image" else "machineImages"
    request = urllib.request.Request(
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{project_value}/global/{collection}/{resource_value}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        resource = json.loads(response.read())
    return cast(str, resource["id"])


def _gce_resource_name(value: str, resource: str) -> str:
    """Extract one terminal resource name from a metadata resource path."""
    parts = value.strip("/").split("/")
    try:
        index = parts.index(resource)
        name = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"invalid GCE {resource} metadata path: {value}") from exc
    if not name:
        raise RuntimeError(f"empty GCE {resource} metadata name")
    return name


def observe_gce_provisioning(
    metadata_get: MetadataGetter = _gce_metadata,
    provisioning_id_get: ProvisioningIdGetter = _gce_provisioning_id,
) -> GCEProvisioningRef:
    """Resolve the active VM provisioning source and server-defined ID."""
    value = metadata_get("instance/image")
    if value:
        parts = value.strip("/").split("/")
        if (
            len(parts) != 5
            or parts[0] != "projects"
            or parts[2:4] != ["global", "images"]
        ):
            raise RuntimeError(f"invalid GCE image metadata path: {value}")
        project, name = parts[1], parts[4]
        return GCEBootImageRef(
            project=project,
            name=name,
            id=provisioning_id_get("boot_image", project, name),
        )

    kind = metadata_get("instance/attributes/viper-provisioning-kind")
    if kind != "machine_image":
        raise RuntimeError("GCE provisioning metadata is absent")
    project = metadata_get("instance/attributes/viper-provisioning-project")
    name = metadata_get("instance/attributes/viper-provisioning-name")
    declared_id = metadata_get("instance/attributes/viper-provisioning-id")
    observed_id = provisioning_id_get(kind, project, name)
    if declared_id != observed_id:
        raise RuntimeError("GCE machine-image metadata ID differs from the API")
    return GCEMachineImageRef(project=project, name=name, id=observed_id)


def process_environment(
    seed: RNGSeed,
    reproducibility: ReproducibilitySpec,
    compute: ComputeSpec,
    *,
    cuda_ordinal: int | None = None,
) -> dict[StartupVariable, str]:
    """Return environment variables that must exist when Python starts."""
    values: dict[StartupVariable, str] = {
        "PYTHONHASHSEED": str(seed),
        "OMP_NUM_THREADS": str(reproducibility.parallelism.torch_intraop_threads),
        "MKL_NUM_THREADS": str(reproducibility.parallelism.torch_intraop_threads),
    }
    workspace = reproducibility.determinism.cublas_workspace_config
    if workspace is not None:
        values["CUBLAS_WORKSPACE_CONFIG"] = workspace
    if isinstance(compute, CUDAComputeSpec):
        if compute.count != 1:
            raise ValueError("startup.distributed: CUDA count must equal one")
        if cuda_ordinal is None:
            raise ValueError("a CUDA stage requires one selected device ordinal")
        values["CUDA_VISIBLE_DEVICES"] = str(cuda_ordinal)
    else:
        values["CUDA_VISIBLE_DEVICES"] = ""
    return values


def _sha256(value: bytes) -> str:
    """Return the lowercase SHA-256 digest of one runtime-state encoding."""
    return hashlib.sha256(value).hexdigest()


def _numpy_state_bytes(generator: np.random.Generator) -> bytes:
    """Encode one NumPy bit-generator state in canonical JSON form."""
    return json.dumps(
        generator.bit_generator.state,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _startup_environment() -> dict[StartupVariable, str]:
    """Read the allowlisted startup variables from the active child process."""
    names: tuple[StartupVariable, ...] = (
        "CUBLAS_WORKSPACE_CONFIG",
        "CUDA_VISIBLE_DEVICES",
        "MKL_NUM_THREADS",
        "OMP_NUM_THREADS",
        "PYTHONHASHSEED",
    )
    return {
        name: os_value
        for name in names
        if (os_value := os.environ.get(name)) is not None
    }


def apply_reproducibility(
    seed: RNGSeed,
    reproducibility: ReproducibilitySpec,
) -> RuntimeInitialization:
    """Apply run controls and return the exact initialized generator objects."""
    random.seed(seed)
    receipts = [
        GeneratorInitializationReceipt(
            family="python",
            seed=seed,
            state_sha256=_sha256(pickle.dumps(random.getstate(), protocol=5)),
        )
    ]

    named_generators = {
        name: np.random.Generator(np.random.PCG64(seed))
        for name in sorted(reproducibility.numpy_randomness.generators)
    }
    receipts.extend(
        GeneratorInitializationReceipt(
            family="numpy_generator",
            name=name,
            seed=seed,
            state_sha256=_sha256(_numpy_state_bytes(generator)),
        )
        for name, generator in named_generators.items()
    )
    if reproducibility.numpy_randomness.capture_legacy_global:
        np.random.seed(seed)
        receipts.append(
            GeneratorInitializationReceipt(
                family="numpy_legacy",
                seed=seed,
                state_sha256=_sha256(pickle.dumps(np.random.get_state(), protocol=5)),
            )
        )

    torch.manual_seed(seed)
    receipts.append(
        GeneratorInitializationReceipt(
            family="torch_cpu",
            seed=seed,
            state_sha256=_sha256(torch.get_rng_state().numpy().tobytes()),
        )
    )
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        receipts.extend(
            GeneratorInitializationReceipt(
                family="torch_cuda",
                seed=seed,
                device_index=index,
                state_sha256=_sha256(state.cpu().numpy().tobytes()),
            )
            for index, state in enumerate(torch.cuda.get_rng_state_all())
        )

    determinism = reproducibility.determinism
    torch.use_deterministic_algorithms(
        determinism.deterministic_algorithms,
        warn_only=determinism.deterministic_warn_only,
    )
    torch.backends.cudnn.deterministic = determinism.cudnn_deterministic
    torch.backends.cudnn.benchmark = determinism.cudnn_benchmark

    precision = reproducibility.precision
    torch.set_float32_matmul_precision(precision.float32_matmul_precision)
    torch.backends.cudnn.allow_tf32 = precision.cudnn_allow_tf32

    parallelism = reproducibility.parallelism
    torch.set_num_threads(parallelism.torch_intraop_threads)
    torch.set_num_interop_threads(parallelism.torch_interop_threads)

    return RuntimeInitialization(
        numpy_generators=named_generators,
        receipt=ProcessStartupReceipt(
            environment=_startup_environment(),
            reproducibility=reproducibility,
            generators=tuple(receipts),
        ),
    )


def _numpy_build_dependency(name: str) -> NativeLibraryContext:
    """Read one BLAS or LAPACK identity from NumPy's build configuration."""
    configuration = np.show_config(mode="dicts")
    assert isinstance(configuration, Mapping)
    dependencies = configuration.get("Build Dependencies", {})
    dependency: Mapping[str, Any] = {}
    if isinstance(dependencies, Mapping):
        candidate = dependencies.get(name, {})
        if isinstance(candidate, Mapping):
            dependency = candidate
    return NativeLibraryContext(
        implementation=str(dependency.get("name", "unreported")),
        version=str(dependency.get("version", "unreported")),
    )


def _instruction_features() -> tuple[str, ...]:
    """Read the enabled SIMD extensions reported by NumPy."""
    configuration = np.show_config(mode="dicts")
    assert isinstance(configuration, Mapping)
    simd = configuration.get("SIMD Extensions", {})
    features: list[str] = []
    if isinstance(simd, Mapping):
        for group in ("baseline", "found"):
            values = simd.get(group, ())
            if isinstance(values, list):
                features.extend(str(value) for value in values)
    return tuple(dict.fromkeys(features)) or ("unreported",)


def _nvidia_driver_version() -> str:
    """Read the NVIDIA driver version visible to the active child."""
    try:
        output = subprocess.run(
            (
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("CUDA backend driver identity is unavailable") from exc
    version = output.splitlines()[0].strip() if output.splitlines() else ""
    if not version:
        raise RuntimeError("CUDA backend driver identity is empty")
    return version


def _cuda_backend() -> CUDABackendContext:
    """Observe the single CUDA device exposed to the active child."""
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("the CUDA child must expose exactly one device")
    properties = torch.cuda.get_device_properties(0)
    cudnn_version = torch.backends.cudnn.version()
    return CUDABackendContext(
        gpu_devices=(
            CUDADeviceContext(
                ordinal=0,
                model=properties.name,
                compute_capability_major=properties.major,
                compute_capability_minor=properties.minor,
                memory_bytes=properties.total_memory,
            ),
        ),
        nvidia_driver_version=_nvidia_driver_version(),
        pytorch_cuda_version=torch.version.cuda or "unreported",
        cudnn_version=str(cudnn_version or "unreported"),
    )


def select_cuda_device(model: str) -> int:
    """Return the first host CUDA ordinal whose model matches the request."""
    if not torch.cuda.is_available():
        raise RuntimeError("requested CUDA is unavailable")
    for ordinal in range(torch.cuda.device_count()):
        if torch.cuda.get_device_properties(ordinal).name == model:
            return ordinal
    raise RuntimeError(f"requested CUDA device model is unavailable: {model}")


def _observe_execution(host: HostContext, compute: ComputeSpec) -> ExecutionContext:
    """Capture CPU, backend, and numerical runtime facts for one observed host."""
    architecture = platform.machine() or "unreported"
    processor = platform.processor() or architecture
    return ExecutionContext(
        host=host,
        cpu=CPUContext(
            architecture=architecture,
            model=processor,
            instruction_features=_instruction_features(),
        ),
        backend=(
            _cuda_backend()
            if isinstance(compute, CUDAComputeSpec)
            else CPUBackendContext()
        ),
        numerical_runtime=NumericalRuntimeContext(
            python_version=platform.python_version(),
            pytorch_version=torch.__version__,
            numpy_version=np.__version__,
            blas=_numpy_build_dependency("blas"),
            lapack=_numpy_build_dependency("lapack"),
            native_thread_pools=(
                NativeThreadPoolContext(
                    implementation="pytorch_intraop",
                    version=torch.__version__,
                    threads=torch.get_num_threads(),
                ),
                NativeThreadPoolContext(
                    implementation="pytorch_interop",
                    version=torch.__version__,
                    threads=torch.get_num_interop_threads(),
                ),
            ),
        ),
    )


def observe_local_execution(compute: ComputeSpec) -> ExecutionContext:
    """Capture local host, CPU, backend, and numerical runtime facts."""
    architecture = platform.machine() or "unreported"
    return _observe_execution(
        LocalHostContext(
            operating_system=platform.system() or "unreported",
            release=platform.release() or "unreported",
            architecture=architecture,
        ),
        compute,
    )


def observe_gce_execution(
    compute: ComputeSpec,
    *,
    metadata_get: MetadataGetter = _gce_metadata,
    provisioning_id_get: ProvisioningIdGetter = _gce_provisioning_id,
) -> ExecutionContext:
    """Capture GCE host, CPU, backend, and numerical runtime facts."""
    try:
        os_release = platform.freedesktop_os_release()
    except OSError:
        os_release = {}
    return _observe_execution(
        GCEHostContext(
            project_id=metadata_get("project/project-id"),
            provisioning=observe_gce_provisioning(
                metadata_get,
                provisioning_id_get,
            ),
            machine_type=_gce_resource_name(
                metadata_get("instance/machine-type"), "machineTypes"
            ),
            zone=_gce_resource_name(metadata_get("instance/zone"), "zones"),
            guest_os_name=os_release.get("ID", platform.system() or "unreported"),
            guest_os_version=os_release.get(
                "VERSION_ID", platform.release() or "unreported"
            ),
            kernel_release=platform.release() or "unreported",
        ),
        compute,
    )


def observe_execution(environment: EnvironmentSpec) -> ExecutionContext:
    """Observe the host and backend selected by one effective environment."""
    if isinstance(environment, GCEEnvironmentSpec):
        return observe_gce_execution(environment.compute)
    return observe_local_execution(environment.compute)


def autocast_context(reproducibility: ReproducibilitySpec) -> Any:
    """Construct the run-wide autocast context for the active backend."""
    precision = reproducibility.precision
    if not precision.autocast_enabled:
        return torch.autocast(device_type="cpu", enabled=False)
    dtype = torch.float16 if precision.autocast_dtype == "float16" else torch.bfloat16
    device_type = "cuda" if torch.cuda.is_available() else "cpu"
    return torch.autocast(device_type=device_type, dtype=dtype, enabled=True)
