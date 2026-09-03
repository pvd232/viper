"""Execute frozen HTTP retrievals through verified HTTP implementations."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, Generic, Literal, Protocol, TypeVar, cast
from urllib.parse import urljoin

import httpx
from pydantic import (
    AwareDatetime,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from . import parameters
from ._schema import (
    SHA256,
    NonEmptyStr,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
)
from .ids import HumanId, InputName
from .parameters import ParameterModelRef
from .references import SnapshotFileRef

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


class HttpImplementationRef(ProtocolModel):
    """Identify one project-owned HTTP callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class ExternalExecutableSpec(ProtocolModel):
    """Freeze the exact executable selected by one project HTTP implementation."""

    executable_id: HumanId
    command: NonEmptyStr
    sha256: SHA256
    bytes: int = Field(gt=0)


class BuiltinHttpImplementationSpec(ProtocolModel):
    """Select the built-in HTTPX implementation."""

    kind: Literal["builtin"] = "builtin"
    id: Literal["httpx"] = "httpx"


class ProjectHttpImplementationSpec(ProtocolModel):
    """Select one frozen project-owned HTTP implementation."""

    kind: Literal["project"] = "project"
    id: HumanId
    implementation: HttpImplementationRef
    parameter_model: ParameterModelRef
    params: parameters.Http
    executables: tuple[ExternalExecutableSpec, ...] = ()

    @model_validator(mode="after")
    def validate_unique_executables(self) -> ProjectHttpImplementationSpec:
        """Require one external executable requirement per identifier."""
        identifiers = tuple(value.executable_id for value in self.executables)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("external executable IDs must be unique")
        return self


HttpImplementationSpec = Annotated[
    BuiltinHttpImplementationSpec | ProjectHttpImplementationSpec,
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


class ResolvedHttpImplementation(ProtocolModel):
    """Record the HTTP and executable identities used for retrieval."""

    spec: HttpImplementationSpec
    external_executables: tuple[ResolvedExternalExecutable, ...] = ()

    @model_validator(mode="after")
    def validate_executable_resolution(self) -> ResolvedHttpImplementation:
        """Resolve every project executable exactly once and none for HTTPX."""
        if isinstance(self.spec, BuiltinHttpImplementationSpec):
            if self.external_executables:
                raise ValueError("built-in HTTP implementation cannot use executables")
            return self
        expected = tuple(value.executable_id for value in self.spec.executables)
        received = tuple(
            value.spec.executable_id for value in self.external_executables
        )
        if received != expected:
            raise ValueError("resolved HTTP executables differ from the specification")
        return self


class ResolvedHttpRetrieval(ProtocolModel):
    """Bind one request to its HTTP implementation, response, and snapshot body."""

    input_name: InputName
    request: HttpRequestSpec
    http: ResolvedHttpImplementation
    response: ObservedHttpResponse
    body: SnapshotFileRef
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


HttpParamsT = TypeVar("HttpParamsT", bound=parameters.Http)
DecoratedHttp = TypeVar("DecoratedHttp", bound=Callable[..., object])
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_PERSISTED_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-encoding",
        "content-length",
        "etag",
        "last-modified",
        "digest",
        "content-digest",
    }
)


class HttpRetrievalError(RuntimeError):
    """Report one rejected request, HTTP implementation, response, or body."""


@dataclass(frozen=True)
class RuntimeHttpCredential:
    """Carry one resolved secret only for the active HTTP invocation."""

    header: HttpHeaderName
    prefix: str
    value: str


@dataclass(frozen=True)
class HttpContext(Generic[HttpParamsT]):
    """Supply one HTTP implementation with its request and destination."""

    request: HttpRequestSpec
    credential: RuntimeHttpCredential | None
    workspace: Path
    destination: Path
    policy: HttpRetrievalPolicy
    params: HttpParamsT
    executables: Mapping[HumanId, Path]


@dataclass(frozen=True)
class HttpResult:
    """Return one completed response body and its terminal HTTP response."""

    body: Path
    response: ObservedHttpResponse


@dataclass(frozen=True)
class HttpDefinition(Generic[HttpParamsT]):
    """Store authoring metadata attached to one project HTTP callable."""

    id: HumanId
    parameter_model: type[HttpParamsT]


class HttpCallable(Protocol[HttpParamsT]):
    """Describe the callable interface shared by project HTTP implementations."""

    def __call__(
        self,
        context: HttpContext[HttpParamsT],
    ) -> HttpResult:
        """Transfer one request into the assigned destination."""
        ...


def http(
    *,
    id: HumanId,
    parameter_model: type[HttpParamsT],
) -> Callable[[DecoratedHttp], DecoratedHttp]:
    """Declare one project-owned HTTP callable."""
    if not issubclass(parameter_model, parameters.Http):
        raise TypeError("HTTP parameter model must subclass viper.parameters.Http")
    definition = HttpDefinition(
        id=id,
        parameter_model=parameter_model,
    )

    def decorate(function: DecoratedHttp) -> DecoratedHttp:
        """Validate the callable signature and attach its authoring metadata."""
        parameters = tuple(inspect.signature(function).parameters.values())
        if len(parameters) != 1:
            raise TypeError("an HTTP callable must accept one HttpContext")
        setattr(function, "__viper_http__", definition)
        return function

    return decorate


def _verify_implementation_bytes(
    reference: HttpImplementationRef,
    raw: bytes,
) -> None:
    """Compare one project HTTP file with its frozen identity."""
    if len(raw) != reference.bytes:
        raise HttpRetrievalError("HTTP implementation byte count differs")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise HttpRetrievalError("HTTP implementation SHA-256 differs")


def _load_project_http(
    repository_root: Path,
    spec: ProjectHttpImplementationSpec,
) -> HttpCallable[Any]:
    """Load the exact decorated top-level callable selected by one stage."""
    root = repository_root.resolve()
    path = (root / spec.implementation.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HttpRetrievalError("HTTP implementation is unavailable")
    _verify_implementation_bytes(spec.implementation, path.read_bytes())
    module_name = f"_viper_http_{path.stem}_{abs(hash(path))}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise HttpRetrievalError("HTTP module could not be loaded")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    inserted_path = str(root)
    saved_modules: dict[str, ModuleType] = {}
    project_prefixes = {
        child.stem
        for child in root.iterdir()
        if child.is_dir() or child.suffix == ".py"
    }
    for name in tuple(sys.modules):
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in project_prefixes
        ):
            saved_modules[name] = sys.modules.pop(name)
    sys.path.insert(0, inserted_path)
    try:
        module_spec.loader.exec_module(module)
        value = getattr(module, spec.implementation.symbol, None)
        if value is None or not callable(value):
            raise HttpRetrievalError("HTTP symbol is not callable")
        if getattr(value, "__module__", None) != module_name:
            raise HttpRetrievalError("HTTP symbol must be top-level")
        definition = getattr(value, "__viper_http__", None)
        if not isinstance(definition, HttpDefinition):
            raise HttpRetrievalError("HTTP callable lacks a VIPER decorator")
        if definition.id != spec.id:
            raise HttpRetrievalError("HTTP decorator ID differs")
        if definition.parameter_model.__name__ != spec.parameter_model.symbol:
            raise HttpRetrievalError("HTTP parameter class differs")
        parameter_source = inspect.getsourcefile(definition.parameter_model)
        if (
            parameter_source is None
            or Path(parameter_source).resolve()
            != (root / spec.parameter_model.path).resolve()
        ):
            raise HttpRetrievalError("HTTP parameter source differs")
    except Exception as exc:
        if isinstance(exc, HttpRetrievalError):
            raise
        raise HttpRetrievalError("HTTP module raised during import") from exc
    finally:
        sys.modules.pop(module_name, None)
        sys.path.remove(inserted_path)
        for name in tuple(sys.modules):
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in project_prefixes
            ):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
    return cast(HttpCallable[Any], value)


def validate_request_policy(
    request: HttpRequestSpec,
    policy: HttpRetrievalPolicy,
) -> None:
    """Require one request origin and expected body to satisfy its stage policy."""
    origin = http_origin(request.url)
    if origin.scheme not in policy.allowed_schemes:
        raise HttpRetrievalError("HTTP request scheme is disallowed")
    if origin.host not in policy.allowed_hosts:
        raise HttpRetrievalError("HTTP request host is disallowed")
    if origin.port not in policy.allowed_ports:
        raise HttpRetrievalError("HTTP request port is disallowed")
    if request.expected_body_bytes > policy.max_body_bytes:
        raise HttpRetrievalError("expected HTTP body exceeds the policy limit")


def _resolve_credential(
    reference: EnvironmentSecretRef | None,
    environment: Mapping[str, str],
) -> RuntimeHttpCredential | None:
    """Resolve one required environment secret without persisting its value."""
    if reference is None:
        return None
    value = environment.get(reference.variable)
    if value is None or value == "":
        raise HttpRetrievalError("required HTTP credential is unavailable")
    return RuntimeHttpCredential(
        header=reference.header,
        prefix=reference.prefix,
        value=value,
    )


def _resolve_executable(spec: ExternalExecutableSpec) -> ResolvedExternalExecutable:
    """Locate and verify one frozen external transfer executable."""
    selected = shutil.which(spec.command)
    if selected is None:
        raise HttpRetrievalError(
            f"required HTTP executable {spec.executable_id!r} is unavailable"
        )
    path = Path(selected).resolve()
    if not path.is_file():
        raise HttpRetrievalError("resolved HTTP executable is not a regular file")
    raw = path.read_bytes()
    if len(raw) != spec.bytes or hashlib.sha256(raw).hexdigest() != spec.sha256:
        raise HttpRetrievalError("resolved HTTP executable identity differs")
    return ResolvedExternalExecutable(spec=spec, path=path)


def resolve_http(
    repository_root: Path,
    spec: HttpImplementationSpec,
) -> ResolvedHttpImplementation:
    """Validate source and executable identities before one HTTP call."""
    from ._parameter.validation import (  # Avoid an HTTP-validation cycle.
        instantiate_parameters,
        verify_parameter_model_bytes,
    )

    if isinstance(spec, BuiltinHttpImplementationSpec):
        return ResolvedHttpImplementation(spec=spec)
    root = repository_root.resolve()
    implementation_path = root / spec.implementation.path
    _verify_implementation_bytes(spec.implementation, implementation_path.read_bytes())
    parameter_path = root / spec.parameter_model.path
    verify_parameter_model_bytes(spec.parameter_model, parameter_path.read_bytes())
    _load_project_http(root, spec)
    instantiate_parameters(
        parameter_path,
        spec.parameter_model,
        spec.params,
        parameters.Http,
    )
    executables = tuple(_resolve_executable(value) for value in spec.executables)
    return ResolvedHttpImplementation(spec=spec, external_executables=executables)


def _credential_headers(
    request: HttpRequestSpec,
    credential: RuntimeHttpCredential | None,
    url: HttpUrl,
) -> dict[str, str]:
    """Combine public headers with a credential authorized for this origin."""
    headers = dict(request.headers)
    if credential is None or request.credentials is None:
        return headers
    if http_origin(url) in request.credentials.authorized_origins:
        headers[credential.header] = f"{credential.prefix}{credential.value}"
    return headers


def _persisted_headers(response: httpx.Response) -> dict[str, str]:
    """Select the terminal representation headers allowed in a receipt."""
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() in _PERSISTED_RESPONSE_HEADERS
    }


def _httpx_request(
    context: HttpContext[parameters.Http],
) -> HttpResult:
    """Retrieve one exact response body through a bounded HTTPX client."""
    started = time.monotonic()
    current_url = context.request.url
    redirects = 0
    context.workspace.mkdir(parents=True, exist_ok=True)
    destination = context.destination.resolve()
    if not destination.is_relative_to(context.workspace.resolve()):
        raise HttpRetrievalError("HTTP destination escapes its retrieval workspace")
    if destination.is_symlink():
        raise HttpRetrievalError("HTTP destination must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            while True:
                validate_request_policy(
                    context.request.model_copy(update={"url": current_url}),
                    context.policy,
                )
                remaining = context.policy.timeout_seconds - (
                    time.monotonic() - started
                )
                if remaining <= 0:
                    raise HttpRetrievalError("HTTP retrieval exceeded its timeout")
                headers = _credential_headers(
                    context.request,
                    context.credential,
                    current_url,
                )
                with client.stream(
                    context.request.method,
                    str(current_url),
                    headers=headers,
                    timeout=remaining,
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if location is None:
                            raise HttpRetrievalError("HTTP redirect omitted Location")
                        if redirects >= context.policy.max_redirects:
                            raise HttpRetrievalError("HTTP redirect limit exceeded")
                        current_url = _HTTP_URL_ADAPTER.validate_python(
                            urljoin(str(current_url), location)
                        )
                        redirects += 1
                        continue
                    if response.status_code not in context.policy.accepted_statuses:
                        raise HttpRetrievalError("HTTP terminal status is unaccepted")
                    descriptor, temporary_name = tempfile.mkstemp(
                        dir=destination.parent,
                        prefix=f".{destination.name}.",
                    )
                    temporary_path = Path(temporary_name)
                    size = 0
                    with os.fdopen(descriptor, "wb") as body:
                        for chunk in response.iter_raw():
                            size += len(chunk)
                            if size > context.policy.max_body_bytes:
                                raise HttpRetrievalError(
                                    "HTTP body exceeds the policy limit"
                                )
                            if (
                                time.monotonic() - started
                                > context.policy.timeout_seconds
                            ):
                                raise HttpRetrievalError(
                                    "HTTP retrieval exceeded its timeout"
                                )
                            body.write(chunk)
                        body.flush()
                        os.fsync(body.fileno())
                    os.replace(temporary_path, destination)
                    temporary_path = None
                    return HttpResult(
                        body=destination,
                        response=ObservedHttpResponse(
                            response_url=_HTTP_URL_ADAPTER.validate_python(
                                str(response.url)
                            ),
                            status=response.status_code,
                            response_headers=_persisted_headers(response),
                        ),
                    )
    except httpx.TimeoutException as exc:
        raise HttpRetrievalError("HTTP retrieval exceeded its timeout") from exc
    except httpx.HTTPError as exc:
        raise HttpRetrievalError("HTTP request failed") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def invoke_http(
    repository_root: Path,
    implementation: ResolvedHttpImplementation,
    request: HttpRequestSpec,
    policy: HttpRetrievalPolicy,
    workspace: Path,
    destination: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> HttpResult:
    """Invoke the selected HTTP implementation and verify its result."""
    from ._parameter.validation import (  # Avoid an HTTP-validation cycle.
        instantiate_parameters,
    )

    root = repository_root.resolve()
    validate_request_policy(request, policy)
    credential = _resolve_credential(
        request.credentials,
        os.environ if environment is None else environment,
    )
    resolved_workspace = workspace.resolve()
    resolved_destination = destination.resolve()
    if not resolved_destination.is_relative_to(resolved_workspace):
        raise HttpRetrievalError("HTTP destination escapes its retrieval workspace")
    if destination.is_symlink():
        raise HttpRetrievalError("HTTP destination must not be a symlink")
    if isinstance(implementation.spec, BuiltinHttpImplementationSpec):
        params = parameters.Http()
        function: HttpCallable[Any] = _httpx_request
    else:
        project = implementation.spec
        params = cast(
            parameters.Http,
            instantiate_parameters(
                root / project.parameter_model.path,
                project.parameter_model,
                project.params,
                parameters.Http,
            ),
        )
        function = _load_project_http(root, project)
    context = HttpContext(
        request=request,
        credential=credential,
        workspace=resolved_workspace,
        destination=resolved_destination,
        policy=policy,
        params=params,
        executables={
            value.spec.executable_id: value.path
            for value in implementation.external_executables
        },
    )
    started = time.monotonic()
    result = function(context)
    if time.monotonic() - started > policy.timeout_seconds:
        raise HttpRetrievalError("HTTP retrieval exceeded its timeout")
    expected_destination = destination.resolve()
    if result.body.resolve() != expected_destination:
        raise HttpRetrievalError("HTTP implementation returned another body path")
    if result.body.is_symlink() or not result.body.is_file():
        raise HttpRetrievalError("HTTP implementation returned no regular body file")
    if result.response.status not in policy.accepted_statuses:
        raise HttpRetrievalError("HTTP terminal status is unaccepted")
    terminal_request = request.model_copy(update={"url": result.response.response_url})
    validate_request_policy(terminal_request, policy)
    raw = result.body.read_bytes()
    if len(raw) > policy.max_body_bytes:
        raise HttpRetrievalError("HTTP body exceeds the policy limit")
    if len(raw) != request.expected_body_bytes:
        raise HttpRetrievalError("HTTP body byte count differs from frozen request")
    if hashlib.sha256(raw).hexdigest() != request.expected_body_sha256:
        raise HttpRetrievalError("HTTP body SHA-256 differs from frozen request")
    return result
