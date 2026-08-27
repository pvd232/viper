"""Execute frozen HTTP retrievals through verified transport implementations."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Generic, Protocol, TypeVar, cast
from urllib.parse import urljoin

import httpx
from pydantic import HttpUrl, TypeAdapter

from . import parameters
from ._parameter_validation import (
    instantiate_parameters,
    verify_parameter_model_bytes,
)
from .ids import HumanId, InputName
from .protocol import (
    BuiltinHttpTransportSpec,
    EnvironmentSecretRef,
    ExternalExecutableSpec,
    HttpHeaderName,
    HttpRequestSpec,
    HttpRetrievalPolicy,
    HttpTransportImplementationRef,
    HttpTransportSpec,
    ObservedHttpResponse,
    ProjectHttpTransportSpec,
    ResolvedExternalExecutable,
    ResolvedHttpTransport,
    http_origin,
)
from .stages import StageContext

TransportParamsT = TypeVar("TransportParamsT", bound=parameters.HttpTransport)
DecoratedTransport = TypeVar("DecoratedTransport", bound=Callable[..., object])
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
    """Report one rejected request, transport, response, or completed body."""


@dataclass(frozen=True)
class RuntimeHttpCredential:
    """Carry one resolved secret only for the active transport invocation."""

    header: HttpHeaderName
    prefix: str
    value: str


@dataclass(frozen=True)
class HttpTransportContext(Generic[TransportParamsT]):
    """Supply one transport with its frozen request and bounded destination."""

    request: HttpRequestSpec
    credential: RuntimeHttpCredential | None
    workspace: Path
    destination: Path
    policy: HttpRetrievalPolicy
    params: TransportParamsT
    executables: Mapping[HumanId, Path]


@dataclass(frozen=True)
class HttpTransportResult:
    """Return one completed response body and its terminal HTTP response."""

    body: Path
    response: ObservedHttpResponse


@dataclass(frozen=True)
class HttpRetrievalHandle:
    """Expose one verified response body to the download-stage callable."""

    response: ObservedHttpResponse
    body: Path


@dataclass(frozen=True)
class DownloadContext(StageContext[parameters.Download]):
    """Extend the stage context with verified HTTP retrieval handles."""

    retrievals: Mapping[InputName, HttpRetrievalHandle]


@dataclass(frozen=True)
class HttpTransportDefinition(Generic[TransportParamsT]):
    """Store authoring metadata attached to one project transport callable."""

    transport_id: HumanId
    parameter_model: type[TransportParamsT]


class HttpTransportCallable(Protocol[TransportParamsT]):
    """Describe the callable interface shared by project HTTP transports."""

    def __call__(
        self,
        context: HttpTransportContext[TransportParamsT],
    ) -> HttpTransportResult:
        """Transfer one request into the assigned destination."""
        ...


def http_transport(
    *,
    transport_id: HumanId,
    parameter_model: type[TransportParamsT],
) -> Callable[[DecoratedTransport], DecoratedTransport]:
    """Declare one project-owned HTTP transport callable."""
    if not issubclass(parameter_model, parameters.HttpTransport):
        raise TypeError(
            "HTTP transport parameter model must subclass "
            "viper.parameters.HttpTransport"
        )
    definition = HttpTransportDefinition(
        transport_id=transport_id,
        parameter_model=parameter_model,
    )

    def decorate(function: DecoratedTransport) -> DecoratedTransport:
        """Validate the transport signature and attach its authoring metadata."""
        parameters = tuple(inspect.signature(function).parameters.values())
        if len(parameters) != 1:
            raise TypeError("an HTTP transport must accept one HttpTransportContext")
        setattr(function, "__viper_http_transport__", definition)
        return function

    return decorate


def _verify_implementation_bytes(
    reference: HttpTransportImplementationRef,
    raw: bytes,
) -> None:
    """Compare one project transport file with its frozen identity."""
    if len(raw) != reference.bytes:
        raise HttpRetrievalError("HTTP transport byte count differs")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise HttpRetrievalError("HTTP transport SHA-256 differs")


def _load_project_transport(
    repository_root: Path,
    spec: ProjectHttpTransportSpec,
) -> HttpTransportCallable[Any]:
    """Load the exact decorated top-level callable selected by one stage."""
    root = repository_root.resolve()
    path = (root / spec.implementation.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HttpRetrievalError("HTTP transport implementation is unavailable")
    _verify_implementation_bytes(spec.implementation, path.read_bytes())
    module_name = f"_viper_http_transport_{path.stem}_{abs(hash(path))}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise HttpRetrievalError("HTTP transport module could not be loaded")
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
            raise HttpRetrievalError("HTTP transport symbol is not callable")
        if getattr(value, "__module__", None) != module_name:
            raise HttpRetrievalError("HTTP transport symbol must be top-level")
        definition = getattr(value, "__viper_http_transport__", None)
        if not isinstance(definition, HttpTransportDefinition):
            raise HttpRetrievalError("HTTP transport lacks a VIPER decorator")
        if definition.transport_id != spec.transport_id:
            raise HttpRetrievalError("HTTP transport decorator ID differs")
        if definition.parameter_model.__name__ != spec.parameter_model.symbol:
            raise HttpRetrievalError("HTTP transport parameter class differs")
        parameter_source = inspect.getsourcefile(definition.parameter_model)
        if (
            parameter_source is None
            or Path(parameter_source).resolve()
            != (root / spec.parameter_model.path).resolve()
        ):
            raise HttpRetrievalError("HTTP transport parameter source differs")
    except Exception as exc:
        if isinstance(exc, HttpRetrievalError):
            raise
        raise HttpRetrievalError("HTTP transport module raised during import") from exc
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
    return cast(HttpTransportCallable[Any], value)


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


def resolve_transport(
    repository_root: Path,
    spec: HttpTransportSpec,
) -> ResolvedHttpTransport:
    """Validate source and executable identities before one transport runs."""
    if isinstance(spec, BuiltinHttpTransportSpec):
        return ResolvedHttpTransport(spec=spec)
    root = repository_root.resolve()
    implementation_path = root / spec.implementation.path
    _verify_implementation_bytes(spec.implementation, implementation_path.read_bytes())
    parameter_path = root / spec.parameter_model.path
    verify_parameter_model_bytes(spec.parameter_model, parameter_path.read_bytes())
    _load_project_transport(root, spec)
    instantiate_parameters(
        parameter_path,
        spec.parameter_model,
        spec.params,
        parameters.HttpTransport,
    )
    executables = tuple(_resolve_executable(value) for value in spec.executables)
    return ResolvedHttpTransport(spec=spec, external_executables=executables)


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


def _httpx_transport(
    context: HttpTransportContext[parameters.HttpTransport],
) -> HttpTransportResult:
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
                    return HttpTransportResult(
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
        raise HttpRetrievalError("HTTP transport failed") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def invoke_transport(
    repository_root: Path,
    transport: ResolvedHttpTransport,
    request: HttpRequestSpec,
    policy: HttpRetrievalPolicy,
    workspace: Path,
    destination: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> HttpTransportResult:
    """Invoke the selected transport and enforce its returned body contract."""
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
    if isinstance(transport.spec, BuiltinHttpTransportSpec):
        params = parameters.HttpTransport()
        function: HttpTransportCallable[Any] = _httpx_transport
    else:
        project = transport.spec
        params = cast(
            parameters.HttpTransport,
            instantiate_parameters(
                root / project.parameter_model.path,
                project.parameter_model,
                project.params,
                parameters.HttpTransport,
            ),
        )
        function = _load_project_transport(root, project)
    context = HttpTransportContext(
        request=request,
        credential=credential,
        workspace=resolved_workspace,
        destination=resolved_destination,
        policy=policy,
        params=params,
        executables={
            value.spec.executable_id: value.path
            for value in transport.external_executables
        },
    )
    started = time.monotonic()
    result = function(context)
    if time.monotonic() - started > policy.timeout_seconds:
        raise HttpRetrievalError("HTTP retrieval exceeded its timeout")
    expected_destination = destination.resolve()
    if result.body.resolve() != expected_destination:
        raise HttpRetrievalError("HTTP transport returned another body path")
    if result.body.is_symlink() or not result.body.is_file():
        raise HttpRetrievalError("HTTP transport returned no regular body file")
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
