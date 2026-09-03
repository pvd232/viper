"""Shared protocol objects used by independent test modules."""

import hashlib

from viper import parameters
from viper._schema import DataRole
from viper.artifacts import ArtifactLoaderRef
from viper.http import (
    BuiltinHttpTransportSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
)
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    MetricImplementationRef,
    MetricKind,
    MetricSpec,
)
from viper.parameters import ParameterModelRef
from viper.randomness import (
    LegacyNumPyRNGState,
    MainProcessRNGState,
    NumPyRNGState,
    PCG64GeneratorState,
    PCG64InternalState,
    PythonRNGState,
)
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
)
from viper.runtime import (
    PythonEnvironmentSpec,
    ReproducibilitySpec,
    observe_python_environment,
)
from viper.stages import StageImplementationRef
from viper.verification.models import VerificationPolicy

DEFAULT_ARTIFACT_LOADER_SOURCE = b"def load(path):\n    return path.read_bytes()\n"


def python_environment() -> PythonEnvironmentSpec:
    """Capture the interpreter and installed distributions used by this test run."""
    return observe_python_environment()


def metric_source(metric_id: str, kind: MetricKind) -> bytes:
    """Build one decorated metric implementation matched by ``metric_spec``."""
    mode = "recompute" if kind == "evaluation" else "live"
    return (
        "from viper.metrics import metric\n\n"
        f'@metric(metric_id="{metric_id}", kind="{kind}", mode="{mode}")\n'
        "def compute(context):\n"
        "    return 0.91\n"
    ).encode()


def parameter_model_ref(kind: str) -> ParameterModelRef:
    """Build one exact synthetic parameter-model identity for model tests."""
    raw = parameter_model_source(kind)
    class_name = f"{kind.title()}Parameters"
    return ParameterModelRef(
        path=f"project/parameters/{kind}.py",
        symbol=class_name,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def parameter_model_source(kind: str) -> bytes:
    """Build the source bytes matched by ``parameter_model_ref``."""
    class_name = f"{kind.title()}Parameters"
    base_name = kind.title()
    return (
        "from viper import parameters\n\n"
        f"class {class_name}(parameters.{base_name}):\n"
        f'    """Validate the {kind} parameters used by this fixture."""\n'
    ).encode()


def stage_implementation_ref(
    path: str,
    raw: bytes = b"# stage implementation\n",
    *,
    symbol: str = "run",
) -> StageImplementationRef:
    """Build one exact synthetic stage-callable identity for model tests."""
    return StageImplementationRef(
        path=path,
        symbol=symbol,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def artifact_loader_ref(
    path: str,
    raw: bytes = DEFAULT_ARTIFACT_LOADER_SOURCE,
    *,
    symbol: str = "load",
) -> ArtifactLoaderRef:
    """Build one exact synthetic artifact-loader identity for tests."""
    return ArtifactLoaderRef(
        path=path,
        symbol=symbol,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def http_request(
    *,
    url: str = "https://example.com/fixture.bin",
    body: bytes = b"fixture HTTP body",
    version: str = "v1",
) -> HttpRequestSpec:
    """Build one frozen request whose expected identity matches ``body``."""
    return HttpRequestSpec.model_validate(
        {
            "url": url,
            "version": version,
            "expected_body_sha256": hashlib.sha256(body).hexdigest(),
            "expected_body_bytes": len(body),
        }
    )


def http_policy(
    *,
    hosts: frozenset[str] = frozenset({"example.com"}),
    ports: frozenset[int] = frozenset({443}),
) -> HttpRetrievalPolicy:
    """Build the bounded retrieval policy used by synthetic download stages."""
    return HttpRetrievalPolicy(
        allowed_schemes=frozenset({"http", "https"}),
        allowed_hosts=hosts,
        allowed_ports=ports,
        max_redirects=2,
        max_body_bytes=1024 * 1024,
        timeout_seconds=30,
    )


def builtin_http_transport() -> BuiltinHttpTransportSpec:
    """Select the HTTPX transport for one synthetic download stage."""
    return BuiltinHttpTransportSpec()


def reproducibility() -> ReproducibilitySpec:
    """Build the strict single-process CPU controls used by execution tests."""
    return ReproducibilitySpec.model_validate(
        {
            "determinism": {
                "deterministic_algorithms": True,
                "deterministic_warn_only": False,
                "cudnn_deterministic": True,
                "cudnn_benchmark": False,
                "cublas_workspace_config": ":4096:8",
            },
            "precision": {
                "float32_matmul_precision": "highest",
                "cudnn_allow_tf32": False,
                "autocast_enabled": False,
                "autocast_dtype": None,
            },
            "parallelism": {
                "process_count": 1,
                "torch_intraop_threads": 1,
                "torch_interop_threads": 1,
                "dataloader": {
                    "workers": 0,
                    "prefetch_factor": None,
                    "persistent_workers": False,
                    "in_order": True,
                },
            },
            "numpy_randomness": {
                "generators": {"training": "PCG64"},
                "capture_legacy_global": True,
            },
        }
    )


def verification_policy(*repositories: object) -> VerificationPolicy:
    """Trust project code from the named test repositories."""
    return VerificationPolicy(
        trusted_source_repositories=frozenset(str(value) for value in repositories)
    )


def metric_spec(
    metric_id: str,
    kind: MetricKind,
    required_data_role: DataRole = "evaluation",
) -> MetricSpec:
    """Build one metric bound to an exact user-repository implementation path."""
    source = metric_source(metric_id, kind)
    implementation = MetricImplementationRef(
        path=f"project/metrics/{kind}/{metric_id}.py",
        symbol="compute",
        sha256=hashlib.sha256(source).hexdigest(),
        bytes=len(source),
    )
    if kind == "evaluation":
        return MetricSpec(
            metric_id=metric_id,
            kind=kind,
            implementation=implementation,
            params=parameters.Metric(),
            mode="recompute",
            dependencies=(
                MetricDependency(
                    source="artifact",
                    name="predictions",
                    required_data_role=required_data_role,
                ),
            ),
            comparator=FloatComparator(),
        )
    return MetricSpec(
        metric_id=metric_id,
        kind=kind,
        implementation=implementation,
        params=parameters.Metric(),
        mode="live",
    )


def resume_state(
    *,
    workers: int = 0,
    prefetch_factor: int | None = None,
    persistent_workers: bool = False,
) -> ResumeState:
    """Build a valid serialized resume state for verifier tests."""
    return ResumeState(
        optimizer_state={"state": {}, "param_groups": []},
        main_process_rng=MainProcessRNGState(
            python=PythonRNGState(
                version=3,
                internal_state=(1,),
                gaussian_cache=None,
            ),
            numpy=NumPyRNGState(
                generators={
                    "training": PCG64GeneratorState(
                        state=PCG64InternalState(state=1, inc=1),
                        has_uint32=0,
                        uinteger=0,
                    )
                },
                legacy_global=LegacyNumPyRNGState(
                    keys=(0,) * 624,
                    position=0,
                    has_gaussian=0,
                    cached_gaussian=0.0,
                ),
            ),
            torch_cpu=b"torch-cpu",
            torch_cuda=(),
        ),
        dataloader=DataLoaderResumeState(
            configuration=DataLoaderConfiguration(
                workers=workers,
                prefetch_factor=prefetch_factor,
                persistent_workers=persistent_workers,
                in_order=True,
            ),
            state_dict={"num_yielded": 10},
        ),
    )
