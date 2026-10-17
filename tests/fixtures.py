"""Shared protocol objects used by independent test modules."""

import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from viper import config
from viper._schema import DataRole
from viper.artifacts import ArtifactLoaderRef
from viper.config import ConfigTypeRef
from viper.evidence import VerificationPolicy
from viper.http import (
    BuiltinHttpImplementationSpec,
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
    PythonEnvSpec as PythonEnvironmentSpec,
)
from viper.runtime import ReproducibilitySpec
from viper.runtime import (
    observe_python_env as observe_python_environment,
)
from viper.stages import StageImplementationRef

DEFAULT_ARTIFACT_LOADER_SOURCE = b"def load(path):\n    return path.read_bytes()\n"


def python_environment() -> PythonEnvironmentSpec:
    """Capture the interpreter and installed distributions used by this test run."""
    return observe_python_environment()


def metric_source(metric_id: str, kind: MetricKind) -> bytes:
    """Build one decorated metric implementation matched by ``metric_spec``."""
    return (
        "from viper.metrics import metric\n\n"
        f'@metric(metric_id="{metric_id}", mode="stateless")\n'
        "def compute(context):\n"
        "    return 0.91\n"
    ).encode()


def config_type_ref(kind: str) -> ConfigTypeRef:
    """Build one exact synthetic config-type identity for model tests."""
    raw = config_type_source(kind)
    class_name = f"{kind.title()}Config"
    return ConfigTypeRef(
        owner="workspace",
        path=f"project/config/{kind}.py",
        symbol=class_name,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def config_type_source(kind: str) -> bytes:
    """Build the source bytes matched by ``config_type_ref``."""
    class_name = f"{kind.title()}Config"
    base_name = {
        "build": "BuildConfig",
        "embed": "EmbedConfig",
        "train": "TrainConfig",
        "evaluate": "EvalConfig",
        "eval": "EvalConfig",
        "metric": "MetricConfig",
        "http": "HttpConfig",
        "diagnostic": "DiagnosticConfig",
    }[kind]
    return (
        "from viper import config\n\n"
        f"class {class_name}(config.{base_name}):\n"
        f'    """Validate the {kind} config used by this fixture."""\n'
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


def builtin_http() -> BuiltinHttpImplementationSpec:
    """Select the HTTPX implementation for one synthetic download stage."""
    return BuiltinHttpImplementationSpec()


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
    data_role: DataRole = "eval",
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
            config_type=config.type_ref(config.MetricConfig),
            metric_id=metric_id,
            implementation=implementation,
            config=config.MetricConfig(),
            mode="stateless",
            dependencies=(
                MetricDependency(
                    source="artifact",
                    name="predictions",
                    data_role=data_role,
                ),
            ),
            comparator=FloatComparator(),
        )
    return MetricSpec(
        config_type=config.type_ref(config.MetricConfig),
        metric_id=metric_id,
        implementation=implementation,
        config=config.MetricConfig(),
        mode="stateless",
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


class MemoryHub:
    """Keep complete Hugging Face commits for storage tests."""

    def __init__(self, cache: Path) -> None:
        """Start an empty repository and a separate download cache."""
        self.cache = cache
        self.token = None
        self.head = "0" * 40
        self.commits: dict[str, dict[str, bytes]] = {self.head: {}}
        self.messages: dict[str, str] = {}
        self.fail_after_commit = False

    def create_repo(self, **kwargs: Any) -> None:
        """Keep the already-created test repository."""

    def create_commit(self, *, operations: list[Any], **kwargs: Any) -> SimpleNamespace:
        """Apply all files together and optionally lose the response."""
        files = dict(self.commits[self.head])
        for operation in operations:
            source = operation.path_or_fileobj
            files[operation.path_in_repo] = (
                source.getvalue()
                if isinstance(source, BytesIO)
                else Path(source).read_bytes()
            )
        digest = hashlib.sha1()
        digest.update(self.head.encode())
        for name, raw in sorted(files.items()):
            digest.update(name.encode())
            digest.update(hashlib.sha256(raw).digest())
        self.head = digest.hexdigest()
        self.commits[self.head] = files
        self.messages[self.head] = kwargs.get("commit_message", "")
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise ConnectionError("commit response lost")
        return SimpleNamespace(oid=self.head)

    def repo_info(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return the current commit and repository privacy."""
        return SimpleNamespace(sha=self.head, private=True)

    def list_repo_commits(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        """Return newest commits first for interrupted-write recovery."""
        return [
            SimpleNamespace(commit_id=commit, title=self.messages.get(commit, ""))
            for commit in reversed(self.commits)
        ]

    def download(self, location: Any) -> Path:
        """Write the exact committed file into the test download cache."""
        raw = self.commits[location.commit][location.path]
        path = self.cache / location.commit / location.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def response(self, request: httpx.Request) -> httpx.Response:
        """Serve an exact commit through an in-memory HTTP connection."""
        _, selected = request.url.path.split("/resolve/", 1)
        commit, path = selected.split("/", 1)
        return httpx.Response(200, content=self.commits[commit][path])
