"""Tests for frozen HTTP requests, implementations, and retrieval evidence."""

import hashlib
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from viper import params as parameters
from viper.http import (
    BuiltinHttpImplementationSpec,
    ExternalExecutableSpec,
    HttpImplementationRef,
    HttpRequestSpec,
    HttpRetrievalError,
    HttpRetrievalPolicy,
    ObservedHttpResponse,
    ProjectHttpImplementationSpec,
    ResolvedHttpImplementation,
    ResolvedHttpRetrieval,
    invoke_http,
    resolve_http,
)
from viper.http import EnvSecretRef as EnvironmentSecretRef
from viper.params import ParameterModelRef
from viper.references import SnapshotFileRef


def _policy(*, host: str, port: int) -> HttpRetrievalPolicy:
    """Build one local-server policy for HTTP tests."""
    return HttpRetrievalPolicy(
        allowed_schemes=frozenset({"http"}),
        allowed_hosts=frozenset({host}),
        allowed_ports=frozenset({port}),
        max_redirects=2,
        max_body_bytes=1024,
        timeout_seconds=5,
    )


def _request(**updates: object) -> HttpRequestSpec:
    """Build one immutable request with fixed response-body identity."""
    values = {
        "url": "https://data.example.test/archive.bin",
        "version": "2026-08-23",
        "expected_body_sha256": "a" * 64,
        "expected_body_bytes": 128,
    }
    values.update(updates)
    return HttpRequestSpec.model_validate(values)


@pytest.fixture
def local_http_server() -> Iterator[tuple[str, int, list[tuple[str, str | None]]]]:
    """Serve deterministic bodies while recording credential delivery."""
    received: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        """Serve the redirect, body, and failure responses used by the suite."""

        def do_GET(self) -> None:
            """Record the authorization field and return the selected response."""
            received.append((self.path, self.headers.get("Authorization")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://localhost:"
                    f"{cast(ThreadingHTTPServer, self.server).server_port}/body",
                )
                self.end_headers()
                return
            if self.path == "/body":
                body = b"verified response"
                self.send_response(206 if self.headers.get("Range") else 200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/slow":
                time.sleep(0.1)
                self.send_response(200)
                self.send_header("Content-Length", "1")
                self.end_headers()
                try:
                    self.wfile.write(b"x")
                except BrokenPipeError:
                    pass
                return
            if self.path == "/large":
                body = b"x" * 32
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            """Keep expected local-server requests out of the test output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", server.server_port, received
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


TransportFactory = Callable[[Path], ResolvedHttpImplementation]


@pytest.fixture(params=("builtin", "project"))
def conforming_http(request: pytest.FixtureRequest) -> TransportFactory:
    """Return each HTTP implementation subject to the shared contract."""
    if request.param == "builtin":
        return lambda root: resolve_http(root, BuiltinHttpImplementationSpec())

    parameter_raw = (
        b"from viper import parameters\n\n"
        b"class ConformingTransportParameters(parameters.Http):\n"
        b'    """Validate the conformance transport parameters."""\n'
    )
    implementation_raw = (
        b"import httpx\n"
        b"from project.transport_params import ConformingTransportParameters\n"
        b"from viper.http import (\n"
        b"    HttpRetrievalError,\n"
        b"    HttpResult,\n"
        b"    ObservedHttpResponse,\n"
        b"    http,\n"
        b")\n\n"
        b"@http(id='conforming', "
        b"parameter_model=ConformingTransportParameters)\n"
        b"def transfer(context):\n"
        b"    try:\n"
        b"        response = httpx.get(\n"
        b"            str(context.request.url),\n"
        b"            follow_redirects=True,\n"
        b"            timeout=context.policy.timeout_seconds,\n"
        b"            trust_env=False,\n"
        b"        )\n"
        b"    except httpx.TimeoutException as exc:\n"
        b"        raise HttpRetrievalError(\n"
        b"            'HTTP retrieval exceeded its timeout'\n"
        b"        ) from exc\n"
        b"    context.destination.parent.mkdir(parents=True, exist_ok=True)\n"
        b"    context.destination.write_bytes(response.content)\n"
        b"    headers = {}\n"
        b"    if 'content-length' in response.headers:\n"
        b"        headers['content-length'] = response.headers['content-length']\n"
        b"    return HttpResult(\n"
        b"        body=context.destination,\n"
        b"        response=ObservedHttpResponse(\n"
        b"            response_url=str(response.url),\n"
        b"            status=response.status_code,\n"
        b"            response_headers=headers,\n"
        b"        ),\n"
        b"    )\n"
    )

    def create(root: Path) -> ResolvedHttpImplementation:
        """Write and resolve one exact project-owned HTTP implementation."""
        parameter_path = root / "project/transport_params.py"
        implementation_path = root / "project/conforming_transport.py"
        parameter_path.parent.mkdir(parents=True, exist_ok=True)
        parameter_path.write_bytes(parameter_raw)
        implementation_path.write_bytes(implementation_raw)
        return resolve_http(
            root,
            ProjectHttpImplementationSpec(
                id="conforming",
                implementation=HttpImplementationRef(
                    path="project/conforming_transport.py",
                    symbol="transfer",
                    sha256=hashlib.sha256(implementation_raw).hexdigest(),
                    bytes=len(implementation_raw),
                ),
                parameter_model=ParameterModelRef(
                    owner="project",
                    path="project/transport_params.py",
                    symbol="ConformingTransportParameters",
                    sha256=hashlib.sha256(parameter_raw).hexdigest(),
                    bytes=len(parameter_raw),
                ),
                params=parameters.Http(),
            ),
        )

    return create


def _invoke_conforming_http(
    root: Path,
    factory: TransportFactory,
    request: HttpRequestSpec,
    policy: HttpRetrievalPolicy,
    *,
    destination: Path | None = None,
) -> bytes:
    """Invoke either HTTP implementation through the same contract boundary."""
    workspace = root / "retrieval"
    selected_destination = workspace / "body" if destination is None else destination
    result = invoke_http(
        root,
        factory(root),
        request,
        policy,
        workspace,
        selected_destination,
    )
    return result.body.read_bytes()


def test_http_conformance_accepts_exact_response_body(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
    conforming_http: TransportFactory,
) -> None:
    """Accept one exact body through built-in and project HTTP implementations."""
    host, port, _ = local_http_server
    body = b"verified response"

    received = _invoke_conforming_http(
        tmp_path,
        conforming_http,
        _request(
            url=f"http://{host}:{port}/body",
            expected_body_sha256=hashlib.sha256(body).hexdigest(),
            expected_body_bytes=len(body),
        ),
        _policy(host=host, port=port),
    )

    assert received == body


@pytest.mark.parametrize(
    ("path", "request_updates", "policy_updates", "message"),
    (
        ("missing", {}, {}, "status"),
        (
            "body",
            {"expected_body_bytes": len(b"verified response") - 1},
            {},
            "byte count",
        ),
        (
            "body",
            {"expected_body_sha256": "b" * 64},
            {},
            "SHA-256",
        ),
        (
            "large",
            {"expected_body_bytes": 16},
            {"max_body_bytes": 16},
            "exceeds",
        ),
        (
            "redirect",
            {
                "expected_body_sha256": hashlib.sha256(
                    b"verified response"
                ).hexdigest(),
                "expected_body_bytes": len(b"verified response"),
            },
            {},
            "host",
        ),
        (
            "slow",
            {
                "expected_body_sha256": hashlib.sha256(b"x").hexdigest(),
                "expected_body_bytes": 1,
            },
            {"timeout_seconds": 0.01},
            "timeout",
        ),
    ),
    ids=("status", "bytes", "sha256", "size", "origin", "timeout"),
)
def test_http_conformance_rejects_response_contract_violations(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
    conforming_http: TransportFactory,
    path: str,
    request_updates: dict[str, object],
    policy_updates: dict[str, object],
    message: str,
) -> None:
    """Apply every response-boundary rejection to both HTTP implementations."""
    host, port, _ = local_http_server
    values: dict[str, object] = {
        "url": f"http://{host}:{port}/{path}",
        "expected_body_sha256": hashlib.sha256(b"verified response").hexdigest(),
        "expected_body_bytes": len(b"verified response"),
    }
    values.update(request_updates)
    policy = _policy(host=host, port=port).model_copy(update=policy_updates)

    with pytest.raises(HttpRetrievalError, match=message):
        _invoke_conforming_http(
            tmp_path,
            conforming_http,
            _request(**values),
            policy,
        )


def test_http_conformance_rejects_destination_escape(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
    conforming_http: TransportFactory,
) -> None:
    """Keep both HTTP implementations inside the retrieval workspace."""
    host, port, _ = local_http_server
    body = b"verified response"

    with pytest.raises(HttpRetrievalError, match="destination escapes"):
        _invoke_conforming_http(
            tmp_path,
            conforming_http,
            _request(
                url=f"http://{host}:{port}/body",
                expected_body_sha256=hashlib.sha256(body).hexdigest(),
                expected_body_bytes=len(body),
            ),
            _policy(host=host, port=port),
            destination=tmp_path / "escaped-body",
        )


def test_request_rejects_literal_and_unauthorized_credentials() -> None:
    """Keep secret values out and require origin-scoped secret delivery."""
    with pytest.raises(ValidationError, match="literal credential"):
        _request(headers={"authorization": "Bearer secret"})

    secret = EnvironmentSecretRef.model_validate(
        {
            "variable": "DATA_TOKEN",
            "header": "authorization",
            "prefix": "Bearer ",
            "authorized_origins": [
                {"scheme": "https", "host": "other.example.test", "port": 443}
            ],
        }
    )
    with pytest.raises(ValidationError, match="not authorized"):
        _request(credentials=secret)


def test_policy_requires_normalized_exact_hosts() -> None:
    """Represent the request allowlist with exact normalized host values."""
    with pytest.raises(ValidationError, match="normalized"):
        HttpRetrievalPolicy(
            allowed_schemes=frozenset({"https"}),
            allowed_hosts=frozenset({"DATA.EXAMPLE.TEST"}),
            allowed_ports=frozenset({443}),
            max_redirects=2,
            max_body_bytes=1024,
            timeout_seconds=30,
        )


def test_resolved_retrieval_requires_the_expected_body_identity() -> None:
    """Reject a same-length response body with another SHA-256 identity."""
    request = _request()
    body = SnapshotFileRef(
        path="artifacts/datasets/archive/body.bin",
        sha256="b" * 64,
        bytes=128,
    )
    with pytest.raises(ValidationError, match="SHA-256"):
        ResolvedHttpRetrieval(
            input_name="archive",
            request=request,
            http=ResolvedHttpImplementation(spec=BuiltinHttpImplementationSpec()),
            response=ObservedHttpResponse(
                response_url=request.url,
                status=200,
                response_headers={"content-length": "128"},
            ),
            body=body,
            started_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 23, 12, 1, tzinfo=UTC),
        )


def test_httpx_request_follows_policy_and_strips_cross_origin_secret(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Enforce redirects and withhold a secret from an unauthorized origin."""
    host, port, received = local_http_server
    body = b"verified response"
    request = _request(
        url=f"http://{host}:{port}/redirect",
        expected_body_sha256=hashlib.sha256(body).hexdigest(),
        expected_body_bytes=len(body),
        credentials=EnvironmentSecretRef.model_validate(
            {
                "variable": "TEST_HTTP_TOKEN",
                "header": "authorization",
                "prefix": "Bearer ",
                "authorized_origins": [{"scheme": "http", "host": host, "port": port}],
            }
        ),
    )
    policy = HttpRetrievalPolicy(
        allowed_schemes=frozenset({"http"}),
        allowed_hosts=frozenset({host, "localhost"}),
        allowed_ports=frozenset({port}),
        max_redirects=2,
        max_body_bytes=1024,
        timeout_seconds=5,
    )
    transport = resolve_http(tmp_path, BuiltinHttpImplementationSpec())
    workspace = tmp_path / "retrieval"

    result = invoke_http(
        tmp_path,
        transport,
        request,
        policy,
        workspace,
        workspace / "body",
        environment={"TEST_HTTP_TOKEN": "secret-value"},
    )

    assert result.body.read_bytes() == body
    assert result.response.status == 200
    assert received == [
        ("/redirect", "Bearer secret-value"),
        ("/body", None),
    ]


def test_project_http_receives_typed_parameters_and_exact_destination(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Load one decorated project HTTP callable and verify its completed body."""
    host, port, _ = local_http_server
    body = b"verified response"
    parameter_raw = (
        b"from pydantic import Field\n"
        b"from viper import params as parameters\n\n"
        b"class ProjectTransportParameters(parameters.Http):\n"
        b"    chunk_size: int = Field(gt=0)\n"
    )
    implementation_raw = (
        b"import httpx\n"
        b"from project.transport_params import ProjectTransportParameters\n"
        b"from viper.http import (\n"
        b"    HttpResult,\n"
        b"    ObservedHttpResponse,\n"
        b"    http,\n"
        b")\n\n"
        b"@http(id='project_http', "
        b"params=ProjectTransportParameters)\n"
        b"def transfer(context):\n"
        b"    assert context.params.chunk_size == 4\n"
        b"    response = httpx.get(str(context.request.url), "
        b"headers={'Range': 'bytes=0-'}, "
        b"follow_redirects=False, trust_env=False)\n"
        b"    context.destination.write_bytes(response.content)\n"
        b"    return HttpResult(\n"
        b"        body=context.destination,\n"
        b"        response=ObservedHttpResponse(\n"
        b"            response_url=str(response.url),\n"
        b"            status=response.status_code,\n"
        b"            response_headers={\n"
        b"                'content-length': response.headers['content-length']\n"
        b"            },\n"
        b"        ),\n"
        b"    )\n"
    )
    parameter_path = tmp_path / "project/transport_params.py"
    implementation_path = tmp_path / "project/transport.py"
    parameter_path.parent.mkdir(parents=True)
    parameter_path.write_bytes(parameter_raw)
    implementation_path.write_bytes(implementation_raw)
    spec = ProjectHttpImplementationSpec(
        id="project_http",
        implementation=HttpImplementationRef(
            path="project/transport.py",
            symbol="transfer",
            sha256=hashlib.sha256(implementation_raw).hexdigest(),
            bytes=len(implementation_raw),
        ),
        parameter_model=ParameterModelRef(
            owner="project",
            path="project/transport_params.py",
            symbol="ProjectTransportParameters",
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        ),
        params=parameters.Http.model_validate({"chunk_size": 4}),
    )
    request = _request(
        url=f"http://{host}:{port}/body",
        expected_body_sha256=hashlib.sha256(body).hexdigest(),
        expected_body_bytes=len(body),
    )
    transport = resolve_http(tmp_path, spec)
    workspace = tmp_path / "retrieval"
    workspace.mkdir()
    policy = _policy(host=host, port=port).model_copy(
        update={"accepted_statuses": frozenset({206})}
    )

    result = invoke_http(
        tmp_path,
        transport,
        request,
        policy,
        workspace,
        workspace / "body",
    )

    assert result.body == workspace / "body"
    assert result.body.read_bytes() == body
    assert result.response.status == 206

    missing_executable = spec.model_copy(
        update={
            "executables": (
                ExternalExecutableSpec(
                    executable_id="missing",
                    command="viper-definitely-absent-executable",
                    sha256="a" * 64,
                    bytes=1,
                ),
            )
        }
    )
    with pytest.raises(HttpRetrievalError, match="unavailable"):
        resolve_http(tmp_path, missing_executable)

    implementation_path.write_bytes(implementation_raw + b"# modified\n")
    with pytest.raises(HttpRetrievalError, match="byte count"):
        resolve_http(tmp_path, spec)


def test_http_rejects_unaccepted_status(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Reject a terminal response outside the frozen accepted-status set."""
    host, port, _ = local_http_server
    request = _request(
        url=f"http://{host}:{port}/missing",
        expected_body_sha256="b" * 64,
        expected_body_bytes=1,
    )
    workspace = tmp_path / "retrieval"

    with pytest.raises(HttpRetrievalError, match="status"):
        invoke_http(
            tmp_path,
            resolve_http(tmp_path, BuiltinHttpImplementationSpec()),
            request,
            _policy(host=host, port=port),
            workspace,
            workspace / "body",
        )


def test_http_rejects_policy_secret_and_same_length_body_failures(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Reject a disallowed host, missing secret, and changed body identity."""
    host, port, _ = local_http_server
    body = b"verified response"
    request = _request(
        url=f"http://{host}:{port}/body",
        expected_body_sha256=hashlib.sha256(body).hexdigest(),
        expected_body_bytes=len(body),
    )
    transport = resolve_http(tmp_path, BuiltinHttpImplementationSpec())
    workspace = tmp_path / "retrieval"
    disallowed = _policy(host="example.test", port=port)
    with pytest.raises(HttpRetrievalError, match="host"):
        invoke_http(
            tmp_path,
            transport,
            request,
            disallowed,
            workspace,
            workspace / "body",
        )

    oversized = request.model_copy(update={"expected_body_bytes": 2048})
    with pytest.raises(HttpRetrievalError, match="exceeds"):
        invoke_http(
            tmp_path,
            transport,
            oversized,
            _policy(host=host, port=port),
            workspace,
            workspace / "body",
        )

    secret_request = request.model_copy(
        update={
            "credentials": EnvironmentSecretRef.model_validate(
                {
                    "variable": "MISSING_HTTP_TOKEN",
                    "header": "authorization",
                    "authorized_origins": [
                        {"scheme": "http", "host": host, "port": port}
                    ],
                }
            )
        }
    )
    with pytest.raises(HttpRetrievalError, match="credential"):
        invoke_http(
            tmp_path,
            transport,
            secret_request,
            _policy(host=host, port=port),
            workspace,
            workspace / "body",
            environment={},
        )

    changed_identity = request.model_copy(update={"expected_body_sha256": "b" * 64})
    with pytest.raises(HttpRetrievalError, match="SHA-256"):
        invoke_http(
            tmp_path,
            transport,
            changed_identity,
            _policy(host=host, port=port),
            workspace,
            workspace / "body",
        )

    timeout_request = _request(
        url=f"http://{host}:{port}/slow",
        expected_body_sha256=hashlib.sha256(b"x").hexdigest(),
        expected_body_bytes=1,
    )
    timeout_policy = _policy(host=host, port=port).model_copy(
        update={"timeout_seconds": 0.01}
    )
    with pytest.raises(HttpRetrievalError, match="timeout"):
        invoke_http(
            tmp_path,
            transport,
            timeout_request,
            timeout_policy,
            workspace,
            workspace / "body",
        )


def test_project_http_rejects_returned_path_escape(tmp_path: Path) -> None:
    """Reject a project HTTP callable that returns a file outside its workspace."""
    parameter_raw = (
        b"from viper import parameters\n\n"
        b"class EscapeParameters(parameters.Http):\n"
        b'    """Validate the empty escape-test parameter mapping."""\n'
    )
    implementation_raw = (
        b"from project.params import EscapeParameters\n"
        b"from viper.http import (\n"
        b"    HttpResult,\n"
        b"    ObservedHttpResponse,\n"
        b"    http,\n"
        b")\n\n"
        b"@http(id='escape', parameter_model=EscapeParameters)\n"
        b"def transfer(context):\n"
        b"    escaped = context.workspace.parent / 'escaped'\n"
        b"    escaped.write_bytes(b'x')\n"
        b"    return HttpResult(\n"
        b"        body=escaped,\n"
        b"        response=ObservedHttpResponse(\n"
        b"            response_url=context.request.url,\n"
        b"            status=200,\n"
        b"            response_headers={},\n"
        b"        ),\n"
        b"    )\n"
    )
    parameter_path = tmp_path / "project/params.py"
    implementation_path = tmp_path / "project/escape.py"
    parameter_path.parent.mkdir(parents=True)
    parameter_path.write_bytes(parameter_raw)
    implementation_path.write_bytes(implementation_raw)
    spec = ProjectHttpImplementationSpec(
        id="escape",
        implementation=HttpImplementationRef(
            path="project/escape.py",
            symbol="transfer",
            sha256=hashlib.sha256(implementation_raw).hexdigest(),
            bytes=len(implementation_raw),
        ),
        parameter_model=ParameterModelRef(
            owner="project",
            path="project/params.py",
            symbol="EscapeParameters",
            sha256=hashlib.sha256(parameter_raw).hexdigest(),
            bytes=len(parameter_raw),
        ),
        params=parameters.Http(),
    )
    workspace = tmp_path / "retrieval"
    workspace.mkdir()

    with pytest.raises(HttpRetrievalError, match="another body path"):
        invoke_http(
            tmp_path,
            resolve_http(tmp_path, spec),
            _request(
                url="https://example.com/body",
                expected_body_sha256=hashlib.sha256(b"x").hexdigest(),
                expected_body_bytes=1,
            ),
            HttpRetrievalPolicy(
                allowed_schemes=frozenset({"https"}),
                allowed_hosts=frozenset({"example.com"}),
                allowed_ports=frozenset({443}),
                max_redirects=0,
                max_body_bytes=1,
                timeout_seconds=5,
            ),
            workspace,
            workspace / "body",
        )
