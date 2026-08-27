"""Pydantic models for the active VIPER provenance protocol.

The model graph separates execution requests, resolved data artifacts,
the exact Git source tree, requested environments, observed execution
conditions, and immutable stage-result snapshots.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from . import parameters
from ._schema import (
    EVALUATION_DATASET_INPUT,
    PARAMETERS,
    PARAMETERS_INPUT,
    PREDICTIONS,
    RESUME_STATE,
    RESUME_STATE_INPUT,
    SHA256,
    ArtifactName,
    BenchmarkId,
    DataRole,
    EvaluationId,
    NonEmptyStr,
    NormalizedDistributionName,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
    RepoRelPath,
    RNGSeed,
    repo_file_paths_overlap,
)
from ._schema import SelectionName as SelectionName
from .ids import (
    ExperimentId,
    FactorId,
    HumanId,
    InputName,
    LevelId,
    MetricId,
    ReplicateId,
    RunId,
    StageId,
    VariantId,
)
from .parameters import ParameterModelRef as ParameterModelRef
from .references import (
    ArtifactPointerRef,
    GitFileRef,
    GitSource,
    LocalStageResultSnapshotRef,
    ResolvedArtifactPointerRef,
    ResolvedBenchmarkResultRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedGitFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StageResultSnapshotRef,
)
from .references import HuggingFaceFileRef as HuggingFaceFileRef
from .references import LocalFileRef as LocalFileRef
from .references import StorageModel as StorageModel
from .references import StorageRef as StorageRef

# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------


HttpHeaderName = Annotated[
    str,
    Field(pattern=r"^[!#$%&'*+.^_`|~0-9a-z-]+$", min_length=1),
]


class HttpOrigin(ProtocolModel):
    """Identify one normalized HTTP origin including its effective port."""

    scheme: Literal["http", "https"]
    host: NonEmptyStr
    port: int = Field(ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def validate_normalized_host(cls, value: str) -> str:
        """Require the lower-case host representation used for exact matching."""
        if value != value.lower().rstrip("."):
            raise ValueError("HTTP origin host must be normalized")
        return value


class EnvironmentSecretRef(ProtocolModel):
    """Select one runtime secret and the HTTP origins authorized to receive it."""

    kind: Literal["environment"] = "environment"
    variable: NonEmptyStr
    header: HttpHeaderName
    prefix: str = ""
    authorized_origins: frozenset[HttpOrigin] = Field(min_length=1)

    @field_validator("variable")
    @classmethod
    def validate_variable_name(cls, value: str) -> str:
        """Require a portable environment-variable name."""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("secret variable must be an environment-variable name")
        return value


class HttpRequestSpec(ProtocolModel):
    """Freeze one experimental HTTP request and its expected response body."""

    kind: Literal["http"] = "http"
    method: Literal["GET"] = "GET"
    url: HttpUrl
    headers: dict[HttpHeaderName, NonEmptyStr] = Field(default_factory=dict)
    version: NonEmptyStr
    expected_body_sha256: SHA256
    expected_body_bytes: int = Field(gt=0)
    credentials: EnvironmentSecretRef | None = None

    @model_validator(mode="after")
    def validate_public_headers_and_credential_origin(self) -> HttpRequestSpec:
        """Keep literal credentials out and authorize the initial request origin."""
        if self.url.username is not None or self.url.password is not None:
            raise ValueError("HTTP request URL must not contain user information")
        if self.url.fragment is not None:
            raise ValueError("HTTP request URL must not contain a fragment")
        sensitive = {"authorization", "cookie", "proxy-authorization"}
        if sensitive & set(self.headers):
            raise ValueError("HTTP request headers contain a literal credential")
        if self.credentials is not None:
            if self.credentials.header in self.headers:
                raise ValueError("credential header must not appear in public headers")
            if http_origin(self.url) not in self.credentials.authorized_origins:
                raise ValueError(
                    "request origin is not authorized to receive credential"
                )
        return self


class HttpRetrievalPolicy(ProtocolModel):
    """Bound the network and response behavior of one logical retrieval."""

    allowed_schemes: frozenset[Literal["http", "https"]] = Field(min_length=1)
    allowed_hosts: frozenset[NonEmptyStr] = Field(min_length=1)
    allowed_ports: frozenset[Annotated[int, Field(ge=1, le=65535)]] = Field(
        min_length=1
    )
    accepted_statuses: frozenset[Annotated[int, Field(ge=100, le=599)]] = frozenset(
        {200}
    )
    max_redirects: int = Field(ge=0)
    max_body_bytes: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("allowed_hosts")
    @classmethod
    def validate_normalized_hosts(cls, value: frozenset[str]) -> frozenset[str]:
        """Require exact lower-case host policy members."""
        if any(host != host.lower().rstrip(".") for host in value):
            raise ValueError("HTTP policy hosts must be normalized")
        return value


def http_origin(url: HttpUrl) -> HttpOrigin:
    """Return the normalized effective origin of one validated HTTP URL."""
    raw_scheme = url.scheme
    if raw_scheme not in {"http", "https"}:
        raise ValueError("HTTP request URL must use HTTP or HTTPS")
    scheme: Literal["http", "https"] = "http" if raw_scheme == "http" else "https"
    host = url.host
    if host is None:
        raise ValueError("HTTP request URL must contain a host")
    port = url.port or (80 if scheme == "http" else 443)
    return HttpOrigin(scheme=scheme, host=host.lower().rstrip("."), port=port)


# ---------------------------------------------------------------------------
# Verified files and code
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Artifact selectors
# ---------------------------------------------------------------------------


class StageArtifactRef(ProtocolModel):
    """Selects one named artifact produced by one stage."""

    stage_id: StageId
    artifact_name: ArtifactName


class ArtifactPointer(ProtocolModel):
    """Selects one artifact accepted as a reusable input."""

    schema_version: Literal[1] = 1
    run: ResolvedRunRef
    artifact: StageArtifactRef
    benchmark_result: ResolvedBenchmarkResultRef | None = None


# ---------------------------------------------------------------------------
# Requested and resolved GCE environment
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Determinism, precision, and parallelism
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Training resume state
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


MetricKind = Literal["training", "evaluation", "diagnostic"]
MetricMode = Literal["recompute", "live"]


class FloatComparator(ProtocolModel):
    """Define equality for one recomputed floating-point metric."""

    mode: Literal["exact", "absolute", "relative"] = "exact"
    tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_tolerance(self) -> FloatComparator:
        """Require a positive tolerance for approximate comparison modes."""
        if self.mode != "exact" and self.tolerance == 0:
            raise ValueError("approximate metric comparison requires tolerance")
        if self.mode == "exact" and self.tolerance != 0:
            raise ValueError("exact metric comparison requires zero tolerance")
        return self


class StageImplementationRef(ProtocolModel):
    """Identify one project-owned top-level stage callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class ArtifactLoaderRef(ProtocolModel):
    """Identify one project-owned artifact loader by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol = "load"
    sha256: SHA256
    bytes: int = Field(gt=0)


class HttpTransportImplementationRef(ProtocolModel):
    """Identify one project-owned HTTP transport callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class ExternalExecutableSpec(ProtocolModel):
    """Freeze the exact executable selected by one project transport."""

    executable_id: HumanId
    command: NonEmptyStr
    sha256: SHA256
    bytes: int = Field(gt=0)


class BuiltinHttpTransportSpec(ProtocolModel):
    """Select the built-in HTTPX transport."""

    kind: Literal["builtin"] = "builtin"
    transport_id: Literal["httpx"] = "httpx"


class ProjectHttpTransportSpec(ProtocolModel):
    """Select one frozen project-owned HTTP transport implementation."""

    kind: Literal["project"] = "project"
    transport_id: HumanId
    implementation: HttpTransportImplementationRef
    parameter_model: ParameterModelRef
    params: parameters.HttpTransport
    executables: tuple[ExternalExecutableSpec, ...] = ()

    @model_validator(mode="after")
    def validate_unique_executables(self) -> ProjectHttpTransportSpec:
        """Require one external executable requirement per identifier."""
        identifiers = tuple(value.executable_id for value in self.executables)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("external executable IDs must be unique")
        return self


HttpTransportSpec = Annotated[
    BuiltinHttpTransportSpec | ProjectHttpTransportSpec,
    Field(discriminator="kind"),
]


class ObservedHttpResponse(ProtocolModel):
    """Persist the terminal status, URL, and representation response fields."""

    response_url: HttpUrl
    status: int = Field(ge=100, le=599)
    response_headers: dict[HttpHeaderName, str]

    @model_validator(mode="after")
    def validate_persisted_headers(self) -> ObservedHttpResponse:
        """Restrict persisted headers to representation and content identity."""
        allowed = {
            "content-type",
            "content-encoding",
            "content-length",
            "etag",
            "last-modified",
            "digest",
            "content-digest",
        }
        if not set(self.response_headers) <= allowed:
            raise ValueError("response contains a non-persistable HTTP header")
        return self


class ResolvedExternalExecutable(ProtocolModel):
    """Bind one frozen executable requirement to its verified host path."""

    spec: ExternalExecutableSpec
    path: Path


class ResolvedHttpTransport(ProtocolModel):
    """Record the transport and executable identities used for retrieval."""

    spec: HttpTransportSpec
    external_executables: tuple[ResolvedExternalExecutable, ...] = ()

    @model_validator(mode="after")
    def validate_executable_resolution(self) -> ResolvedHttpTransport:
        """Resolve every project executable exactly once and none for HTTPX."""
        if isinstance(self.spec, BuiltinHttpTransportSpec):
            if self.external_executables:
                raise ValueError("built-in HTTP transport cannot resolve executables")
            return self
        expected = tuple(value.executable_id for value in self.spec.executables)
        received = tuple(
            value.spec.executable_id for value in self.external_executables
        )
        if received != expected:
            raise ValueError("resolved HTTP executables differ from transport spec")
        return self


class ResolvedHttpRetrieval(ProtocolModel):
    """Bind one logical request to its transport, response, and stored body."""

    input_name: InputName
    request: HttpRequestSpec
    transport: ResolvedHttpTransport
    response: ObservedHttpResponse
    body: ResolvedFileRef
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timing_and_content(self) -> ResolvedHttpRetrieval:
        """Require positive duration and the frozen expected body identity."""
        if self.completed_at <= self.started_at:
            raise ValueError("HTTP retrieval completion must follow its start")
        if self.body.sha256 != self.request.expected_body_sha256:
            raise ValueError("retrieved body SHA-256 differs from frozen request")
        if self.body.bytes != self.request.expected_body_bytes:
            raise ValueError("retrieved body byte count differs from frozen request")
        return self


class HttpRetrievalContextBinding(ProtocolModel):
    """Bind one download context handle to response and body-file identity."""

    response: ObservedHttpResponse
    body: SnapshotFileRef


class StageContextBinding(ProtocolModel):
    """Persist the stable values used to construct one live stage context."""

    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    parameter_model: ParameterModelRef
    parameter_digest: SHA256
    inputs: dict[InputName, RepoRelPath]
    retrievals: dict[InputName, HttpRetrievalContextBinding] = Field(
        default_factory=dict
    )
    artifacts: dict[ArtifactName, RepoRelPath]
    metric_ids: tuple[MetricId, ...]
    numpy_generator_names: tuple[HumanId, ...]


class StageInvocationReceipt(ProtocolModel):
    """Record the callable, logical context, timing, and outcome of one invocation."""

    implementation: StageImplementationRef
    context: StageContextBinding
    context_digest: SHA256
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded", "failed", "cancelled", "preempted"]

    @model_validator(mode="after")
    def validate_timing(self) -> StageInvocationReceipt:
        """Require completion to follow invocation start."""
        if self.completed_at <= self.started_at:
            raise ValueError("invocation completion must be after invocation start")
        return self


class ResolvedStageInvocationRef(ResolvedFileRef):
    """Identify one immutable stage-invocation receipt."""

    kind: Literal["stage_invocation"] = "stage_invocation"


class MetricImplementationRef(ProtocolModel):
    """Identify one project-owned metric callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class MetricDependency(ProtocolModel):
    """Select one stage value and the data role accepted by a metric."""

    source: Literal["input", "artifact"]
    name: HumanId
    required_data_role: DataRole


class MetricSpec(ProtocolModel):
    """Bind one metric identity to its role, parameters, and implementation."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    kind: MetricKind
    implementation: MetricImplementationRef
    params: parameters.Metric
    mode: MetricMode
    dependencies: tuple[MetricDependency, ...] = ()
    comparator: FloatComparator | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> MetricSpec:
        """Require one complete live or recomputed metric configuration."""
        identities = tuple(
            (dependency.source, dependency.name) for dependency in self.dependencies
        )
        if len(set(identities)) != len(identities):
            raise ValueError("metric dependencies must be unique")
        if self.mode == "recompute":
            if not self.dependencies:
                raise ValueError("recomputed metrics require dependencies")
            if self.comparator is None:
                raise ValueError("recomputed metrics require a comparator")
        elif self.dependencies or self.comparator is not None:
            raise ValueError("live metrics do not declare dependencies or a comparator")
        if self.kind == "evaluation" and self.mode != "recompute":
            raise ValueError("evaluation metrics require recomputation")
        return self


class ResolvedMetricDependency(ProtocolModel):
    """Bind one metric dependency to its exact persisted files."""

    dependency: MetricDependency
    files: tuple[ResolvedFileRef, ...] = Field(min_length=1)


class MetricExecutionReceipt(ProtocolModel):
    """Record one controlled metric worker execution and its scalar result."""

    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    metric_id: MetricId
    stage_id: StageId
    purpose: Literal["measurement", "verification"]
    implementation: MetricImplementationRef
    params: parameters.Metric
    dependencies: tuple[ResolvedMetricDependency, ...] = Field(min_length=1)
    startup: ProcessStartupReceipt
    execution_context: ExecutionContext
    python_environment: PythonEnvironmentSpec
    value: float = Field(allow_inf_nan=False)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded"] = "succeeded"


class Measurement(ProtocolModel):
    """One observed metric value produced during a run stage."""

    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    metric_id: MetricId

    value: float = Field(allow_inf_nan=False)
    measured_at: AwareDatetime

    epoch: int | None = Field(default=None, ge=0)
    step: int | None = Field(default=None, ge=0)


class MetricVerificationReceipt(ProtocolModel):
    """Bind one measurement to independent recomputation evidence."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    stage_id: StageId
    measurement: Measurement
    production: MetricExecutionReceipt
    recomputation: MetricExecutionReceipt
    comparator: FloatComparator
    passed: bool
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_execution_ownership(self) -> MetricVerificationReceipt:
        """Require both workers to select one measurement and frozen invocation."""
        if self.metric_id != self.measurement.metric_id:
            raise ValueError("verification metric ID differs from its measurement")
        if self.stage_id != self.measurement.stage_id:
            raise ValueError("verification stage ID differs from its measurement")
        expected_identity = (
            self.measurement.run_id,
            self.measurement.attempt_id,
            self.measurement.stage_id,
            self.measurement.metric_id,
        )
        for receipt in (self.production, self.recomputation):
            received_identity = (
                receipt.run_id,
                receipt.attempt_id,
                receipt.stage_id,
                receipt.metric_id,
            )
            if received_identity != expected_identity:
                raise ValueError("metric worker identity differs from its measurement")
        if self.production.purpose != "measurement":
            raise ValueError("production receipt must use measurement purpose")
        if self.recomputation.purpose != "verification":
            raise ValueError("recomputation receipt must use verification purpose")
        if (
            self.production.implementation != self.recomputation.implementation
            or self.production.params != self.recomputation.params
            or self.production.dependencies != self.recomputation.dependencies
        ):
            raise ValueError("metric worker invocation bindings differ")
        if self.production.value != self.measurement.value:
            raise ValueError("production value differs from its measurement")
        if self.completed_at < max(
            self.production.completed_at,
            self.recomputation.completed_at,
        ):
            raise ValueError("verification completion precedes a worker receipt")
        return self


class MetricCriterion(ProtocolModel):
    """Define one threshold that a benchmark metric must satisfy."""

    metric_id: MetricId
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)


class BenchmarkSpec(ProtocolModel):
    """Define the fixed evaluation and criteria for a strict benchmark."""

    schema_version: Literal[1] = 1
    benchmark_id: BenchmarkId
    evaluation_id: EvaluationId
    evaluation_dataset: ArtifactPointerRef
    splits: dict[InputName, ArtifactPointerRef] = Field(min_length=1)
    metrics: tuple[MetricCriterion, ...] = Field(min_length=1)
    execution_count: Literal[2] = 2

    @model_validator(mode="after")
    def validate_unique_metrics(self) -> BenchmarkSpec:
        """Require one criterion per benchmark metric."""
        metric_ids = tuple(criterion.metric_id for criterion in self.metrics)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("benchmark metric IDs must be unique")
        return self


# ---------------------------------------------------------------------------
# Experiment specs
# ---------------------------------------------------------------------------


class FactorSpec(ProtocolModel):
    """Declare one experimental factor and its permitted levels."""

    factor_id: FactorId
    levels: tuple[LevelId, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_unique_levels(self) -> FactorSpec:
        """Require unique levels within the factor."""
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("level IDs must be unique within a factor")
        return self


class ReplicateSpec(ProtocolModel):
    """Identify one experimental replicate and its global seed."""

    replicate_id: ReplicateId
    seed: RNGSeed


class ExperimentSpec(ProtocolModel):
    """Declare the factors, variants, replicates, and metrics in an experiment."""

    schema_version: Literal[1] = 1
    experiment_id: ExperimentId

    factors: tuple[FactorSpec, ...]
    variant_ids: tuple[VariantId, ...] = Field(min_length=1)
    replicates: tuple[ReplicateSpec, ...] = Field(min_length=1)
    metrics: tuple[MetricSpec, ...]

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ExperimentSpec:
        """Require unique factor, variant, replicate, seed, and metric identities."""
        factor_ids = tuple(factor.factor_id for factor in self.factors)
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("factor IDs must be unique")

        if len(set(self.variant_ids)) != len(self.variant_ids):
            raise ValueError("variant IDs must be unique")

        replicate_ids = tuple(replicate.replicate_id for replicate in self.replicates)
        if len(set(replicate_ids)) != len(replicate_ids):
            raise ValueError("replicate IDs must be unique")

        replicate_seeds = tuple(replicate.seed for replicate in self.replicates)
        if len(set(replicate_seeds)) != len(replicate_seeds):
            raise ValueError("replicate seeds must be unique")

        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("metric IDs must be unique")

        return self


# ---------------------------------------------------------------------------
# Run primitives
# ---------------------------------------------------------------------------

AttemptStatus = Literal[
    "succeeded",
    "failed",
    "preempted",
    "cancelled",
]

AttemptPurpose = Literal["run", "benchmark_confirmation"]
AttemptFailureCode = Literal[
    "preflight_failed",
    "execution_failed",
    "verification_failed",
    "publication_failed",
    "cancelled",
    "preempted",
    "coordinator_lost",
    "internal_error",
]


class AttemptFailure(ProtocolModel):
    """Identify the operation that terminated one unsuccessful attempt."""

    code: AttemptFailureCode
    stage_id: StageId | None
    message: NonEmptyStr
    occurred_at: AwareDatetime


class AttemptJournalRef(ResolvedFileRef):
    """Identify one immutable attempt journal."""

    kind: Literal["attempt_journal"] = "attempt_journal"


class ResolvedStageRef(ProtocolModel):
    """Binds one completed stage to its immutable stage-result snapshot."""

    stage_id: StageId
    snapshot: StageResultSnapshot
    resolved_spec: SnapshotFileRef


class RunAttempt(ProtocolModel):
    """Record the status and published files of one run attempt."""

    attempt_id: int = Field(ge=1)
    purpose: AttemptPurpose
    status: AttemptStatus

    started_at: AwareDatetime
    completed_at: AwareDatetime

    resolved_stages: tuple[ResolvedStageRef, ...]
    invocations: tuple[ResolvedStageInvocationRef, ...]
    journal: AttemptJournalRef
    measurement_files: tuple[ResolvedFileRef, ...]
    metric_verification_files: tuple[ResolvedFileRef, ...] = ()
    log_files: tuple[ResolvedFileRef, ...]

    failure: AttemptFailure | None

    @model_validator(mode="after")
    def validate_common_invariants(self) -> RunAttempt:
        """Enforce attempt outcome, timing, stage, and file invariants."""
        if self.status == "succeeded" and self.failure is not None:
            raise ValueError("successful attempts must not have failure evidence")

        if self.status == "succeeded" and not self.resolved_stages:
            raise ValueError("successful attempts must contain a completed stage")

        if self.status != "succeeded" and self.failure is None:
            raise ValueError(
                "failed, preempted, and cancelled attempts require failure evidence"
            )

        if self.failure is not None:
            if self.failure.occurred_at > self.completed_at:
                raise ValueError("attempt failure cannot follow attempt completion")
            if self.failure.occurred_at < self.started_at:
                raise ValueError("attempt failure cannot precede attempt start")
            expected_code = {
                "failed": {
                    "preflight_failed",
                    "execution_failed",
                    "verification_failed",
                    "publication_failed",
                    "coordinator_lost",
                    "internal_error",
                },
                "cancelled": {"cancelled"},
                "preempted": {"preempted"},
            }
            if (
                self.status != "succeeded"
                and self.failure.code not in expected_code[self.status]
            ):
                raise ValueError("attempt failure code differs from terminal status")

        if self.completed_at <= self.started_at:
            raise ValueError("attempt completion must be after attempt start")

        unique = set()
        snapshots: set[StageResultSnapshotRef | LocalStageResultSnapshotRef] = set()
        for stage in self.resolved_stages:
            if stage.stage_id in unique:
                raise ValueError("resolved stage IDs must be unique")
            unique.add(stage.stage_id)

            if stage.snapshot in snapshots:
                raise ValueError("resolved stages must use distinct snapshots")
            snapshots.add(stage.snapshot)

        measurement_locations = tuple(
            reference.stored_at for reference in self.measurement_files
        )
        if len(set(measurement_locations)) != len(measurement_locations):
            raise ValueError("measurement file storage locations must be unique")

        log_locations = tuple(reference.stored_at for reference in self.log_files)
        if len(set(log_locations)) != len(log_locations):
            raise ValueError("log file storage locations must be unique")

        if set(measurement_locations) & set(log_locations):
            raise ValueError("measurement and log storage locations must be disjoint")

        metric_locations = tuple(
            reference.stored_at for reference in self.metric_verification_files
        )
        if len(set(metric_locations)) != len(metric_locations):
            raise ValueError("metric verification file locations must be unique")
        if set(metric_locations) & (set(measurement_locations) | set(log_locations)):
            raise ValueError(
                "metric verification, measurement, and log locations must be disjoint"
            )

        journal_location = self.journal.stored_at
        if journal_location in (
            set(measurement_locations) | set(log_locations) | set(metric_locations)
        ):
            raise ValueError("attempt journal location must be distinct")

        invocation_locations = tuple(
            reference.stored_at for reference in self.invocations
        )
        if len(set(invocation_locations)) != len(invocation_locations):
            raise ValueError("invocation receipt storage locations must be unique")

        return self


class ResolvedAttemptRef(ResolvedFileRef):
    """Identify one canonical immutable RunAttempt document."""

    kind: Literal["resolved_attempt"] = "resolved_attempt"


class RunStageRef(ProtocolModel):
    """Identifies and verifies one stage spec in a run-plan snapshot."""

    stage_id: StageId
    spec: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class RunSpec(ProtocolModel):
    """Freeze one run plan and its ordered stage specifications."""

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None

    seed: RNGSeed
    source: GitSource
    environment: EnvironmentSpec
    reproducibility: ReproducibilitySpec

    stages: tuple[RunStageRef, ...] = Field(min_length=1)
    estimator: StageArtifactRef

    @model_validator(mode="after")
    def validate_common_invariants(self) -> RunSpec:
        """Enforce ordered-stage identity and estimator selection invariants."""
        stage_ids = tuple(stage.stage_id for stage in self.stages)
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("stage IDs must be unique")

        stage_spec_paths = tuple(stage.spec for stage in self.stages)
        if len(set(stage_spec_paths)) != len(stage_spec_paths):
            raise ValueError("stage spec paths must be unique")

        run_root = (
            f"experiments/{self.experiment_id}/runs/{self.variant_id}/{self.run_id}"
        )
        for stage in self.stages:
            expected_path = f"{run_root}/stages/{stage.stage_id}/spec.yaml"
            if stage.spec != expected_path:
                raise ValueError(
                    f"stage {stage.stage_id!r} spec must use its canonical run path"
                )

        if self.estimator.stage_id not in set(stage_ids):
            raise ValueError("estimator must select a declared run stage")

        if self.estimator.artifact_name != PARAMETERS:
            raise ValueError("estimator must select the parameters artifact")

        return self


class ResolvedRun(ProtocolModel):
    """Reference every attempt and record the terminal outcome of one run."""

    schema_version: Literal[1] = 1

    spec: ResolvedRunSpecRef

    status: Literal["succeeded", "failed", "cancelled"]

    attempts: tuple[ResolvedAttemptRef, ...] = Field(min_length=1)
    successful_attempt_id: int | None

    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedRun:
        """Require the success selector only for a successful terminal run."""
        if self.status == "succeeded":
            if self.successful_attempt_id is None:
                raise ValueError("a succeeded run requires successful_attempt_id")
        elif self.successful_attempt_id is not None:
            raise ValueError(
                "successful_attempt_id must be null without a successful run"
            )

        return self


class ArtifactComparisonReceipt(ProtocolModel):
    """Record one candidate-to-confirmation artifact comparison."""

    artifact: StageArtifactRef
    candidate_stage: ResolvedStageRef
    confirmation_stage: ResolvedStageRef
    candidate_digest: SHA256
    confirmation_digest: SHA256
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> ArtifactComparisonReceipt:
        """Derive the comparison outcome from the two canonical digests."""
        if self.passed != (self.candidate_digest == self.confirmation_digest):
            raise ValueError("artifact comparison outcome differs from its digests")
        return self


class MetricCriterionReceipt(ProtocolModel):
    """Record one benchmark threshold applied to two recomputed metric values."""

    metric_id: MetricId
    candidate_verification: ResolvedFileRef
    confirmation_verification: ResolvedFileRef
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)
    passed: bool


class BenchmarkResult(ProtocolModel):
    """Record the independent confirmation and outcome of a benchmark."""

    schema_version: Literal[1] = 1
    benchmark: ResolvedBenchmarkSpecRef
    run: ResolvedRunRef
    confirmation: ResolvedAttemptRef
    artifacts: tuple[ArtifactComparisonReceipt, ...] = Field(min_length=2)
    metrics: tuple[MetricCriterionReceipt, ...] = Field(min_length=1)
    status: Literal["passed", "failed"]
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_receipt_sets(self) -> BenchmarkResult:
        """Require unique artifact selectors and metric criteria."""
        artifacts = tuple(
            (receipt.artifact.stage_id, receipt.artifact.artifact_name)
            for receipt in self.artifacts
        )
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("benchmark artifact comparisons must be unique")
        metrics = tuple(receipt.metric_id for receipt in self.metrics)
        if len(set(metrics)) != len(metrics):
            raise ValueError("benchmark metric criteria must be unique")
        return self


# ---------------------------------------------------------------------------
# Observed execution context
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Stage input references
# ---------------------------------------------------------------------------


class StoredInputRef(ProtocolModel):
    """A promoted artifact selected before the run begins."""

    kind: Literal["stored"] = "stored"
    pointer: ArtifactPointerRef
    path: RepoRelPath
    data_role: DataRole

    @model_validator(mode="after")
    def validate_materialization_path(self) -> StoredInputRef:
        """Keep materialized input bytes within their promoted-input scope."""
        pointer_scope = self.pointer.path.split("/")[:3]
        materialization_parts = self.path.split("/")
        if (
            len(materialization_parts) < 3
            or materialization_parts[:3] != pointer_scope
            or repo_file_paths_overlap(self.path, self.pointer.path)
            or materialization_parts[-1].endswith(".pointer.yaml")
        ):
            raise ValueError(
                "stored input path must use the pointer's category and entity ID "
                "and must not use or overlap a pointer-file path"
            )
        return self


class FutureInputRef(ProtocolModel):
    """One named artifact produced by an earlier stage in the same run."""

    kind: Literal["future"] = "future"
    producer_stage_id: StageId
    producer_artifact: ArtifactName


InternalInputRef = Annotated[
    StoredInputRef | FutureInputRef,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Stage specifications
# ---------------------------------------------------------------------------


class SingleFileArtifactSpec(ProtocolModel):
    """Declares one named artifact written as one file."""

    kind: Literal["file"] = "file"
    path: RepoRelPath
    loader: ArtifactLoaderRef
    data_role: DataRole


class BundleArtifactSpec(ProtocolModel):
    """Declares one named artifact written beneath one directory root."""

    kind: Literal["bundle"] = "bundle"
    path: RepoRelPath
    loader: ArtifactLoaderRef
    data_role: DataRole


ArtifactSpec = Annotated[
    SingleFileArtifactSpec | BundleArtifactSpec,
    Field(discriminator="kind"),
]


class BaseSpec(ProtocolModel):
    """Execution request recorded before a stage runs."""

    kind: str
    schema_version: Literal[1] = 1

    implementation: StageImplementationRef

    environment: EnvironmentSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()

    artifacts: dict[ArtifactName, ArtifactSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_paths(self) -> BaseSpec:
        """Enforce entrypoint, artifact, and metric declarations."""
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("stage metric IDs must be unique")

        artifact_categories = {
            "download": "datasets",
            "build": "priors",
            "embed": "models",
            "train": "models",
            "evaluate": "evaluations",
        }
        artifact_category = artifact_categories.get(self.kind)
        if artifact_category is None:
            raise ValueError("stage kind has no artifact category contract")

        checkpoint_artifacts = {PARAMETERS, RESUME_STATE}
        if self.kind != "train" and checkpoint_artifacts & set(self.artifacts):
            raise ValueError(
                "parameters and resume_state are reserved for training stages"
            )
        if self.kind != "evaluate" and PREDICTIONS in self.artifacts:
            raise ValueError("predictions is reserved for evaluation stages")

        artifact_roots: dict[RepoRelPath, ArtifactName] = {}

        for name, artifact in self.artifacts.items():
            parts = artifact.path.split("/")
            if (
                len(parts) < 8
                or parts[0] != "experiments"
                or parts[2] != "runs"
                or parts[5] != "artifacts"
                or parts[6] != artifact_category
                or re.fullmatch(r"[a-z][a-z0-9_]*", parts[7]) is None
                or (artifact.kind == "file" and len(parts) < 9)
            ):
                raise ValueError(
                    f"artifact {name!r} path must use a run artifact category "
                    "and entity ID"
                )

            if repo_file_paths_overlap(artifact.path, self.implementation.path):
                raise ValueError(
                    f"artifact {name!r} path collides with the stage implementation"
                )

            for previous_path, previous_name in artifact_roots.items():
                if repo_file_paths_overlap(artifact.path, previous_path):
                    raise ValueError(
                        f"artifact roots for {previous_name!r} and {name!r} "
                        f"overlap: {previous_path} and {artifact.path}"
                    )

            artifact_roots[artifact.path] = name

        return self


class ParameterizedSpec(BaseSpec):
    """Request an operation governed by one project-defined parameter model."""

    parameter_model: ParameterModelRef


class DownloadSpec(ParameterizedSpec):
    """Request verified HTTP retrievals followed by one project operation."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    transport: HttpTransportSpec
    policy: HttpRetrievalPolicy
    params: parameters.Download


class InternalSpec(ParameterizedSpec):
    """Request a stage that consumes stored or prior-stage artifacts."""

    inputs: dict[InputName, InternalInputRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_local_path_collisions(self) -> InternalSpec:
        """Keep stored inputs, scripts, and artifact paths disjoint."""
        stored_inputs = {
            name: ref for name, ref in self.inputs.items() if ref.kind == "stored"
        }

        materialization_paths: dict[RepoRelPath, InputName] = {}

        for name, ref in stored_inputs.items():
            for previous_path, previous_name in materialization_paths.items():
                if repo_file_paths_overlap(ref.path, previous_path):
                    raise ValueError(
                        f"input materialization paths for {previous_name!r} and "
                        f"{name!r} collide: {previous_path} and {ref.path}"
                    )

            materialization_paths[ref.path] = name

            if repo_file_paths_overlap(ref.path, self.implementation.path):
                raise ValueError(
                    f"input {name!r} path collides with the stage implementation"
                )

            for artifact_name, artifact in self.artifacts.items():
                if repo_file_paths_overlap(artifact.path, ref.path):
                    raise ValueError(
                        f"artifact {artifact_name!r} path collides with input {name!r}"
                    )

        return self


class BuildSpec(InternalSpec):
    """Request construction of a project-defined prior artifact."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Build


class EmbedSpec(InternalSpec):
    """Request construction of a project-defined embedding artifact."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Embed


class TrainSpec(InternalSpec):
    """Request training and one terminal replay checkpoint."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    params: parameters.Train

    @model_validator(mode="after")
    def validate_terminal_checkpoint(self) -> TrainSpec:
        """Enforce the canonical terminal checkpoint and resume inputs."""
        required_artifacts = {PARAMETERS, RESUME_STATE}
        missing_artifacts = required_artifacts - set(self.artifacts)
        if missing_artifacts:
            missing = ", ".join(sorted(missing_artifacts))
            raise ValueError(
                f"training stages must declare terminal checkpoint artifacts: {missing}"
            )

        model_input = self.inputs.get(PARAMETERS_INPUT)
        state_input = self.inputs.get(RESUME_STATE_INPUT)

        if (model_input is None) != (state_input is None):
            raise ValueError("checkpoint inputs must be declared together")

        if model_input is None or state_input is None:
            return self

        if model_input.kind != state_input.kind:
            raise ValueError("checkpoint inputs must use the same input kind")

        if model_input.kind == "stored" and state_input.kind == "stored":
            if any(
                input_ref.pointer.path.split("/")[1] != "models"
                for input_ref in (model_input, state_input)
            ):
                raise ValueError("stored checkpoint inputs must use inputs/models")

        if model_input.kind == "future" and state_input.kind == "future":
            if model_input.producer_stage_id != state_input.producer_stage_id:
                raise ValueError(
                    "checkpoint inputs must select one checkpoint-producing stage"
                )
            if model_input.producer_artifact != PARAMETERS:
                raise ValueError("parameters input must select parameters")
            if state_input.producer_artifact != RESUME_STATE:
                raise ValueError("resume_state input must select resume_state")

        return self


class EvaluateSpec(InternalSpec):
    """Request prediction and metrics for one fixed model, dataset, and split."""

    kind: Literal["evaluate"] = "evaluate"  # pyright: ignore[reportIncompatibleVariableOverride]
    evaluation_id: EvaluationId
    metric_ids: tuple[MetricId, ...] = Field(  # pyright: ignore[reportGeneralTypeIssues]
        min_length=1
    )
    split_inputs: tuple[InputName, ...] = Field(min_length=1)
    params: parameters.Evaluate

    @model_validator(mode="after")
    def validate_evaluation_contract(self) -> EvaluateSpec:
        """Require fixed evaluation inputs and one canonical prediction artifact."""
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("evaluation metric IDs must be unique")
        if len(set(self.split_inputs)) != len(self.split_inputs):
            raise ValueError("evaluation split input names must be unique")

        model_input = self.inputs.get(PARAMETERS_INPUT)
        if model_input is None:
            raise ValueError("evaluation requires a parameters input")

        dataset_input = self.inputs.get(EVALUATION_DATASET_INPUT)
        if dataset_input is None:
            raise ValueError("evaluation requires an evaluation_dataset input")
        if dataset_input.kind != "stored":
            raise ValueError("evaluation_dataset must be a stored input")
        if dataset_input.pointer.path.split("/")[1] != "datasets":
            raise ValueError("evaluation_dataset must use inputs/datasets")
        if dataset_input.data_role not in {"evaluation", "benchmark"}:
            raise ValueError(
                "evaluation_dataset data_role must be evaluation or benchmark"
            )

        reserved_inputs = {PARAMETERS_INPUT, EVALUATION_DATASET_INPUT}
        if reserved_inputs & set(self.split_inputs):
            raise ValueError(
                "evaluation split inputs must differ from reserved input names"
            )

        missing_splits = set(self.split_inputs) - set(self.inputs)
        if missing_splits:
            missing = ", ".join(sorted(missing_splits))
            raise ValueError(f"evaluation split inputs are undeclared: {missing}")

        for split_name in self.split_inputs:
            split_input = self.inputs[split_name]
            if split_input.kind != "stored":
                raise ValueError(
                    f"evaluation split input {split_name!r} must be stored"
                )
            if split_input.pointer.path.split("/")[1] != "benchmarks":
                raise ValueError(
                    f"evaluation split input {split_name!r} must use inputs/benchmarks"
                )
            if split_input.data_role != dataset_input.data_role:
                raise ValueError(
                    f"evaluation split input {split_name!r} data_role must match "
                    "evaluation_dataset"
                )

        if model_input.kind == "future":
            if model_input.producer_artifact != PARAMETERS:
                raise ValueError("same-run evaluation must consume parameters")
        else:
            if model_input.pointer.path.split("/")[1] != "models":
                raise ValueError("stored evaluation model must use inputs/models")
            if model_input.data_role not in {"training", "validation"}:
                raise ValueError(
                    "stored evaluation parameters data_role must be training or "
                    "validation"
                )

        prediction = self.artifacts.get(PREDICTIONS)
        if prediction is None:
            raise ValueError("evaluation must declare a predictions artifact")

        if any(
            artifact.data_role != dataset_input.data_role
            for artifact in self.artifacts.values()
        ):
            raise ValueError(
                "evaluation artifact data_role must match evaluation_dataset"
            )

        if any(
            artifact.path.split("/")[7] != self.evaluation_id
            for artifact in self.artifacts.values()
        ):
            raise ValueError("evaluation artifact entity IDs must match evaluation_id")

        return self


class DownloadVariantStageParams(ProtocolModel):
    """Bind one download stage to its selected variant parameters."""

    kind: Literal["download"] = "download"
    stage_id: StageId
    params: parameters.Download


class BuildVariantStageParams(ProtocolModel):
    """Bind one build stage to its selected variant parameters."""

    kind: Literal["build"] = "build"
    stage_id: StageId
    params: parameters.Build


class EmbedVariantStageParams(ProtocolModel):
    """Bind one embedding stage to its selected variant parameters."""

    kind: Literal["embed"] = "embed"
    stage_id: StageId
    params: parameters.Embed


class TrainVariantStageParams(ProtocolModel):
    """Bind one training stage to its selected variant parameters."""

    kind: Literal["train"] = "train"
    stage_id: StageId
    params: parameters.Train


class EvaluateVariantStageParams(ProtocolModel):
    """Bind one evaluation stage to its selected variant parameters."""

    kind: Literal["evaluate"] = "evaluate"
    stage_id: StageId
    params: parameters.Evaluate


VariantStageParams = Annotated[
    DownloadVariantStageParams
    | BuildVariantStageParams
    | EmbedVariantStageParams
    | TrainVariantStageParams
    | EvaluateVariantStageParams,
    Field(discriminator="kind"),
]


class VariantSpec(ProtocolModel):
    """Assign factor levels and typed stage parameters to one variant."""

    schema_version: Literal[1] = 1
    experiment_id: ExperimentId
    variant_id: VariantId
    levels: dict[FactorId, LevelId]
    stage_params: tuple[VariantStageParams, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_stage_ids(self) -> VariantSpec:
        """Require one variant-parameter record per stage."""
        stage_ids = tuple(stage.stage_id for stage in self.stage_params)
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("variant stage IDs must be unique")
        return self


ParameterizedStageSpec = DownloadSpec | BuildSpec | EmbedSpec | TrainSpec | EvaluateSpec


Spec = Annotated[
    ParameterizedStageSpec,
    Field(discriminator="kind"),
]

# ---------------------------------------------------------------------------
# Resolved input refs
# ---------------------------------------------------------------------------


class ResolvedStoredInputRef(ProtocolModel):
    """Bind a stored stage input to its verified pointer file."""

    kind: Literal["stored"] = "stored"
    pointer: ResolvedArtifactPointerRef


class ResolvedFutureInputRef(ProtocolModel):
    """Bind a future input to its completed producer stage."""

    kind: Literal["future"] = "future"
    producer: ResolvedStageRef


ResolvedInternalInputRef = Annotated[
    ResolvedStoredInputRef | ResolvedFutureInputRef,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Resolved execution records
# ---------------------------------------------------------------------------


class ResolvedSingleFileArtifact(ProtocolModel):
    """Records the exact file representing one artifact."""

    kind: Literal["file"] = "file"
    file: SnapshotFileRef


class ResolvedBundleMember(ProtocolModel):
    """Records one exact file beneath a bundle artifact's directory root."""

    relative_path: RepoRelPath
    file: SnapshotFileRef


class ResolvedBundleArtifact(ProtocolModel):
    """Records every exact file representing one bundle artifact."""

    kind: Literal["bundle"] = "bundle"
    members: tuple[ResolvedBundleMember, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_member_paths(self) -> ResolvedBundleArtifact:
        """Require unique, ordered, and nonoverlapping bundle member paths."""
        relative_paths = tuple(member.relative_path for member in self.members)
        if len(set(relative_paths)) != len(relative_paths):
            raise ValueError("bundle member paths must be unique")
        if relative_paths != tuple(sorted(relative_paths)):
            raise ValueError("bundle members must use canonical path order")

        for index, relative_path in enumerate(relative_paths):
            for prior_path in relative_paths[:index]:
                if repo_file_paths_overlap(relative_path, prior_path):
                    raise ValueError("bundle member paths must not overlap")

        return self


ResolvedArtifact = Annotated[
    ResolvedSingleFileArtifact | ResolvedBundleArtifact,
    Field(discriminator="kind"),
]


class ResolvedBaseSpec(ProtocolModel):
    """Record an execution and the exact output files it produced."""

    schema_version: Literal[1] = 1
    kind: str

    spec: BaseSpec
    source: ResolvedGitFileRef

    environment: ResolvedEnvironment
    execution_context: ExecutionContext
    startup: ProcessStartupReceipt
    invocation: ResolvedStageInvocationRef

    command: tuple[str, ...] = Field(min_length=1)

    artifacts: dict[ArtifactName, ResolvedArtifact] = Field(min_length=1)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedBaseSpec:
        """Match realized source, artifacts, environment, and context to the request."""
        if not self.command[0]:
            raise ValueError("command executable must be nonempty")

        if self.source.stored_at.path != self.spec.implementation.path:
            raise ValueError(
                "resolved source entrypoint must match the stage implementation path"
            )

        if set(self.artifacts) != set(self.spec.artifacts):
            raise ValueError(
                "resolved artifact names must match declared artifact names"
            )

        for name, resolved_artifact in self.artifacts.items():
            declared_artifact = self.spec.artifacts[name]

            if resolved_artifact.kind != declared_artifact.kind:
                raise ValueError(
                    f"resolved artifact {name!r} kind must match its declaration"
                )

            if declared_artifact.kind == "file" and resolved_artifact.kind == "file":
                if resolved_artifact.file.path != declared_artifact.path:
                    raise ValueError(
                        f"resolved artifact {name!r} path must match its declaration"
                    )
                continue

            if (
                declared_artifact.kind == "bundle"
                and resolved_artifact.kind == "bundle"
            ):
                for member in resolved_artifact.members:
                    expected_path = f"{declared_artifact.path}/{member.relative_path}"
                    if member.file.path != expected_path:
                        raise ValueError(
                            f"resolved artifact {name!r} member path must equal "
                            "its declared bundle root plus relative path"
                        )

        requested_environment = self.spec.environment
        if requested_environment is not None:
            if self.environment.kind != requested_environment.kind:
                raise ValueError("resolved environment kind must match its request")

            if isinstance(self.environment, ResolvedGCEEnvironment) and isinstance(
                requested_environment,
                GCEEnvironmentSpec,
            ):
                if self.environment.provisioning != requested_environment.provisioning:
                    raise ValueError(
                        "resolved GCE provisioning source must match the stage "
                        "environment override"
                    )
                if self.environment.machine_type != requested_environment.machine_type:
                    raise ValueError(
                        "resolved machine type must match the stage "
                        "environment override"
                    )

            if self.environment.compute != requested_environment.compute:
                raise ValueError(
                    "resolved compute must match the stage environment override"
                )

            if (
                self.environment.python_environment
                != requested_environment.python_environment
            ):
                raise ValueError(
                    "resolved Python environment must match the stage "
                    "environment override"
                )

            resolved_lockfile = self.environment.lockfile
            requested_lockfile = requested_environment.lockfile

            if (
                resolved_lockfile.stored_at.repository != requested_lockfile.repository
                or resolved_lockfile.stored_at.commit != requested_lockfile.commit
                or resolved_lockfile.stored_at.path != requested_lockfile.path
            ):
                raise ValueError(
                    "resolved lockfile must match the stage environment override"
                )

        host = self.execution_context.host
        if self.environment.kind != host.provider:
            raise ValueError("resolved environment kind must match the observed host")
        if isinstance(self.environment, ResolvedGCEEnvironment) and isinstance(
            host,
            GCEHostContext,
        ):
            if self.environment.provisioning != host.provisioning:
                raise ValueError(
                    "resolved GCE provisioning source must match the observed host"
                )
            if self.environment.machine_type != host.machine_type:
                raise ValueError(
                    "resolved machine type must match the observed host machine type"
                )

        compute = self.environment.compute
        backend = self.execution_context.backend

        if compute.kind != backend.kind:
            raise ValueError("resolved compute kind must match the observed backend")

        if compute.kind == "cuda" and backend.kind == "cuda":
            if len(backend.gpu_devices) != compute.count:
                raise ValueError(
                    "observed CUDA device count must match the resolved compute"
                )
            if any(device.model != compute.model for device in backend.gpu_devices):
                raise ValueError(
                    "observed CUDA device models must match the resolved compute"
                )

        return self


class ResolvedDownloadSpec(ResolvedBaseSpec):
    """Bind every frozen HTTP input to its completed retrieval evidence."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: DownloadSpec  # pyright: ignore[reportIncompatibleVariableOverride]

    retrievals: dict[InputName, ResolvedHttpRetrieval]

    @model_validator(mode="after")
    def validate_download_retrievals(self) -> ResolvedDownloadSpec:
        """Match every retrieval to its input, request, transport, and timing."""
        if set(self.retrievals) != set(self.spec.inputs):
            raise ValueError("resolved retrieval names must match download inputs")
        for input_name, retrieval in self.retrievals.items():
            if retrieval.input_name != input_name:
                raise ValueError("resolved retrieval input name differs from its key")
            if retrieval.request != self.spec.inputs[input_name]:
                raise ValueError(
                    "resolved retrieval request differs from download input"
                )
            if retrieval.transport.spec != self.spec.transport:
                raise ValueError("resolved retrieval transport differs from stage spec")
            if retrieval.completed_at > self.completed_at:
                raise ValueError("download retrieval cannot follow stage completion")
        return self


class ResolvedInternalSpec(ResolvedBaseSpec):
    """Record an operation that consumes previously produced artifacts."""

    spec: InternalSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, ResolvedInternalInputRef]

    @model_validator(mode="after")
    def validate_internal_inputs(self) -> ResolvedInternalSpec:
        """Match each realized internal input to the frozen request."""
        if set(self.inputs) != set(self.spec.inputs):
            raise ValueError(
                "resolved input names must match the stage spec input names"
            )

        for name, resolved_input in self.inputs.items():
            spec_input = self.spec.inputs[name]

            if resolved_input.kind != spec_input.kind:
                raise ValueError(
                    f"resolved input {name!r} kind must match the stage spec input"
                )

            if (
                resolved_input.kind == "stored"
                and spec_input.kind == "stored"
                and resolved_input.pointer.stored_at != spec_input.pointer
            ):
                raise ValueError(
                    f"resolved input {name!r} pointer location must match "
                    "the stage spec pointer location"
                )

        return self


class ResolvedBuildSpec(ResolvedInternalSpec):
    """Record the realized execution of one build stage."""

    kind: Literal["build"] = "build"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: BuildSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedEmbedSpec(ResolvedInternalSpec):
    """Record the realized execution of one embedding stage."""

    kind: Literal["embed"] = "embed"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: EmbedSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedTrainSpec(ResolvedInternalSpec):
    """Record the realized execution of one training stage."""

    kind: Literal["train"] = "train"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: TrainSpec  # pyright: ignore[reportIncompatibleVariableOverride]


class ResolvedEvaluateSpec(ResolvedInternalSpec):
    """Record the realized execution of one evaluation stage."""

    kind: Literal["evaluate"] = "evaluate"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: EvaluateSpec  # pyright: ignore[reportIncompatibleVariableOverride]


ResolvedSpec = Annotated[
    ResolvedDownloadSpec
    | ResolvedBuildSpec
    | ResolvedEmbedSpec
    | ResolvedTrainSpec
    | ResolvedEvaluateSpec,
    Field(discriminator="kind"),
]
