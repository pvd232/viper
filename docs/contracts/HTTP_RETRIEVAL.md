# HTTP retrieval

## Status

The frozen request, selectable transport, retrieval receipt, stage delivery,
and verification path are implemented. The built-in HTTPX transport and
project-decorated transports run through one response-contract conformance
suite.

## Required claim

For each download input, VIPER verifies that the exact selected transport
received the frozen HTTP request and produced the file delivered to the exact
download-stage callable.

The completed path binds five identities:

```text
frozen HTTP request
        |
        v
exact transport implementation and parameters
        |
        v
retrieved file identity
        |
        v
exact download-stage callable
        |
        v
published artifacts
```

VIPER owns the request policy, credential resolution, destination path, file
hashing, receipt construction, and verification. The selected transport owns
the network transfer. Project tests establish the scientific correctness of
extraction and parsing code.

## Original gap

`RemoteFileRef` stored a URL and a project-supplied version.
`DownloadSpec` passed that declaration to a project script, which could ignore
the declared URL. `ResolvedDownloadSpec` stored the authored input and one
timestamp. The verifier established artifact identity after execution while
leaving retrieval unobserved.

The earlier draft also assigned transfer execution directly to one VIPER HTTP
client. The single-client boundary left the transport implementation implicit
and coupled the protocol to one client. It also treated one logical retrieval as
one HTTP exchange. A segmented downloader can issue several range requests to
produce one file, so the logical retrieval is the stable protocol unit.

## Contract models

### Parameterized download stage

Every stage inherits the same project-parameter contract:

```python
class ParameterizedSpec(BaseSpec):
    parameter_model: ParameterModelRef
```

`viper.parameters.Download` holds extraction, archive, and parsing values.
The transport has its own parameter model because transfer settings belong to
the transport implementation.

### Frozen request and policy

```python
class HttpOrigin(ProtocolModel):
    scheme: Literal["http", "https"]
    host: NonEmptyStr
    port: Annotated[int, Field(ge=1, le=65535)]


class EnvironmentSecretRef(ProtocolModel):
    kind: Literal["environment"] = "environment"
    variable: NonEmptyStr
    header: HttpHeaderName
    prefix: str = ""
    authorized_origins: frozenset[HttpOrigin] = Field(min_length=1)


class HttpRequestSpec(ProtocolModel):
    kind: Literal["http"] = "http"
    method: Literal["GET"] = "GET"
    url: HttpUrl
    headers: dict[HttpHeaderName, NonEmptyStr] = Field(default_factory=dict)
    version: NonEmptyStr
    expected_body_sha256: SHA256
    expected_body_bytes: int = Field(gt=0)
    credentials: EnvironmentSecretRef | None = None


class HttpRetrievalPolicy(ProtocolModel):
    allowed_schemes: frozenset[Literal["http", "https"]] = Field(min_length=1)
    allowed_hosts: frozenset[NonEmptyStr] = Field(min_length=1)
    allowed_ports: frozenset[
        Annotated[int, Field(ge=1, le=65535)]
    ] = Field(min_length=1)
    accepted_statuses: frozenset[
        Annotated[int, Field(ge=100, le=599)]
    ] = frozenset({200})
    max_redirects: int = Field(ge=0)
    max_body_bytes: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
```

`viper.authoring.expand_http_url()` accepts a URL template, path values, and
query values. It percent-encodes each path value, orders the complete query
mapping, rejects user information and fragments, and returns the URL stored in
the frozen request. URI normalization follows
[RFC 3986, Section 6](https://www.rfc-editor.org/rfc/rfc3986.html#section-6).

`headers` contains public fields that select or describe the requested
representation. VIPER rejects literal authorization credentials, cookies, and
proxy credentials. `EnvironmentSecretRef.variable` names an environment
variable available to the controlled child. `header` selects the request field
that receives the secret, and `prefix` supplies public text such as `Bearer `.
The secret value stays outside the frozen plan and resolved result.

`allowed_hosts` contains normalized, lower-case host names and uses exact
matching. `HttpRetrievalPolicy` governs each frozen request and redirect target.
`max_body_bytes` and `timeout_seconds` apply to each logical retrieval.

`expected_body_sha256` and `expected_body_bytes` fix the response body selected
by the experimental run plan. A discovery or scraping process may observe new
content and publish it as an artifact. A later experimental run selects that
artifact or freezes its observed body identity in `HttpRequestSpec`.

`EnvironmentSecretRef.authorized_origins` states exactly where the credential
may be sent. The request origin must appear in that set. A cross-origin redirect
receives the credential only when its destination origin also appears in that
set.

Origin comparison lowercases the scheme and host, removes a trailing DNS dot,
and assigns port `80` to an HTTP URL or `443` to an HTTPS URL whose text omits
the port. Each `HttpOrigin` stores that effective port.

HTTP defines a request through its method, target, and fields, and a response
through its status, fields, and content. The request model follows those
message components from
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-3.4).

### Transport selection

VIPER supplies one built-in HTTPX transport. A project may select an exact
decorated transport callable for a different transfer engine.

```python
class HttpTransportImplementationRef(ProtocolModel):
    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class ExternalExecutableSpec(ProtocolModel):
    executable_id: HumanId
    command: NonEmptyStr
    sha256: SHA256
    bytes: int = Field(gt=0)


class BuiltinHttpTransportSpec(ProtocolModel):
    kind: Literal["builtin"] = "builtin"
    transport_id: Literal["httpx"] = "httpx"


class ProjectHttpTransportSpec(ProtocolModel):
    kind: Literal["project"] = "project"
    transport_id: HumanId
    implementation: HttpTransportImplementationRef
    parameter_model: ParameterModelRef
    params: viper.parameters.HttpTransport
    executables: tuple[ExternalExecutableSpec, ...] = ()


HttpTransportSpec = Annotated[
    BuiltinHttpTransportSpec | ProjectHttpTransportSpec,
    Field(discriminator="kind"),
]
```

For the built-in transport, `ProcessStartupReceipt` and the effective Python
environment identify the installed VIPER and HTTPX versions. For a project
transport, `RunSpec.source`, `HttpTransportImplementationRef`, and
`ParameterModelRef` identify the exact callable and validator bytes.
`ExternalExecutableSpec` identifies each transfer binary before invocation.
Preflight resolves `command`, verifies its SHA-256 and byte count, and supplies
the verified path to the transport context. Exact file identity supplies the
enforced executable claim. Human-readable version output remains diagnostic
text because external tools expose client-specific version commands.

Requests exposes transport adapters for client-specific behavior. HTTPX
exposes custom transports that send one request and return one response. The
VIPER interface applies the same separation at the provenance boundary:
[Requests transport adapters](https://requests.readthedocs.io/en/stable/user/advanced/#transport-adapters)
and
[HTTPX custom transports](https://www.python-httpx.org/advanced/transports/).

The download stage selects one transport:

```python
class DownloadSpec(ParameterizedSpec):
    kind: Literal["download"] = "download"
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    transport: HttpTransportSpec
    policy: HttpRetrievalPolicy
    params: viper.parameters.Download
```

One transport governs every retrieval initiated by that stage. A plan that
requires different transports uses separate download stages, preserving one
transport identity per stage result.

### Project transport interface

A project transport is an ordinary decorated top-level callable:

```python
class Aria2Parameters(viper.parameters.HttpTransport):
    connections: int = Field(gt=0)
    split: int = Field(gt=0)
    continue_partial: bool = True


@viper.http_transport(
    transport_id="aria2c",
    parameter_model=Aria2Parameters,
)
def aria2c_transport(
    context: HttpTransportContext[Aria2Parameters],
) -> HttpTransportResult:
    ...
```

The decorator supplies authoring metadata. Freezing resolves the callable and
parameter class into `ProjectHttpTransportSpec`.

The runner constructs one context for each logical retrieval:

```python
TransportParamsT = TypeVar(
    "TransportParamsT",
    bound=viper.parameters.HttpTransport,
)


@dataclass(frozen=True)
class RuntimeHttpCredential:
    header: HttpHeaderName
    prefix: str
    value: str


@dataclass(frozen=True)
class HttpTransportContext(Generic[TransportParamsT]):
    request: HttpRequestSpec
    credential: RuntimeHttpCredential | None
    workspace: Path
    destination: Path
    policy: HttpRetrievalPolicy
    params: TransportParamsT
    executables: Mapping[HumanId, Path]


class ObservedHttpResponse(ProtocolModel):
    response_url: HttpUrl
    status: int = Field(ge=100, le=599)
    response_headers: dict[HttpHeaderName, str]


@dataclass(frozen=True)
class HttpTransportResult:
    body: Path
    response: ObservedHttpResponse
```

`HttpRequestSpec.headers` contains the public headers.
`RuntimeHttpCredential.value` contains the resolved secret. The
transport combines them only when it sends the request. VIPER redacts the
secret from persisted output. The runner assigns a dedicated retrieval
`workspace` inside the attempt workspace. `destination` is the exact body path
within that directory. A transport such as `aria2c` may place temporary
transfer files beside the destination. The transport returns only after the
completed body exists at `destination`.

Every successful transport returns the terminal HTTP response. This evidence
lets VIPER apply `accepted_statuses` to the execution that produced the body.

VIPER persists only `content-type`, `content-encoding`, `content-length`,
`etag`, `last-modified`, `digest`, and `content-digest` from the terminal
response. The runner rejects a returned response whose status falls outside
`HttpRetrievalPolicy.accepted_statuses`.

Preflight resolves every frozen `ExternalExecutableSpec`, verifies its SHA-256
and byte count, and passes its executable path through
`HttpTransportContext.executables`. The transport selects binaries from that
mapping.

Aria2 supports segmented HTTP transfers, multiple connections, partial-transfer
continuation, and explicit checksum validation:
[aria2 documentation](https://aria2.github.io/manual/en/html/aria2c.html).

### Resolved retrieval

```python
class ResolvedExternalExecutable(ProtocolModel):
    spec: ExternalExecutableSpec
    path: Path


class ResolvedHttpTransport(ProtocolModel):
    spec: HttpTransportSpec
    external_executables: tuple[ResolvedExternalExecutable, ...] = ()


class ResolvedHttpRetrieval(ProtocolModel):
    input_name: InputName
    request: HttpRequestSpec
    transport: ResolvedHttpTransport
    response: ObservedHttpResponse
    body: ResolvedFileRef
    started_at: AwareDatetime
    completed_at: AwareDatetime


class ResolvedDownloadSpec(ResolvedBaseSpec):
    kind: Literal["download"] = "download"
    spec: DownloadSpec
    retrievals: dict[InputName, ResolvedHttpRetrieval]
```

`retrievals` has the same keys as `DownloadSpec.inputs`. Redirects and
segmented range requests remain internal operations of one transport
invocation.

`body` identifies the completed file through its storage location, SHA-256,
and byte count. `response` preserves the terminal HTTP status, effective URL,
and allowlisted representation headers when the transport exposes them.

The initial retrieval for each input satisfies:

```text
ResolvedHttpRetrieval.input_name
-> DownloadSpec.inputs[input_name]

ResolvedHttpRetrieval.request
== DownloadSpec.inputs[input_name]

ResolvedHttpRetrieval.transport.spec
== DownloadSpec.transport
```

## Execution

### Transport invocation

The runner performs this sequence for every logical retrieval:

```text
validate request against HttpRetrievalPolicy
        |
        v
resolve runtime credentials
        |
        v
load the selected built-in or project transport
        |
        v
construct HttpTransportContext
        |
        v
invoke the exact transport callable
        |
        v
verify the returned path, response, and content identity
        |
        v
hash and store the completed body
        |
        v
write ResolvedHttpRetrieval
```

The runner owns the timestamps surrounding transport invocation. It requires
`HttpTransportResult.body` to equal the assigned destination, rejects symlinks
and path escape, checks the terminal response, enforces the body-size and
elapsed-time limits, verifies the expected SHA-256 and byte count, and stores
the completed file before returning a handle to project code. A successful
transport invocation returns `HttpTransportResult`; a failed invocation raises
the typed transport error defined by `viper.http`.

### Download-stage interface

The client-neutral stage interface is:

```python
@dataclass(frozen=True)
class HttpRetrievalHandle:
    response: ObservedHttpResponse
    body: Path


@dataclass(frozen=True)
class DownloadContext(StageContext[viper.parameters.Download]):
    retrievals: Mapping[InputName, HttpRetrievalHandle]
```

Each `body` path contains the bytes identified by the corresponding
`ResolvedHttpRetrieval.body`.

### Discovery boundary

Dynamic pagination and scraping discover content before an experimental run is
frozen. The discovery process publishes the observed files with their source
receipts. A later run selects those immutable files or freezes one request per
input with the expected body identity.

## Persisted evidence

The resolved download stage contains one retrieval for every declared input.
Each retrieval binds the frozen request, selected transport, verified external
executable identity, terminal response, final body identity, and runner-owned
timestamps.

Each retrieved body uses this canonical snapshot path:

```text
experiments/<experiment_id>/runs/<variant_id>/<run_id>/
└── stages/<stage_id>/retrievals/<input_name>/body
```

The stage invocation receipt stores one `HttpRetrievalContextBinding` per
input. Each binding contains the terminal response and a body-file reference
with its path, SHA-256, and byte count. The receipt digest therefore binds the
exact `DownloadContext` handles to the download-stage callable. The stage
snapshot stores the resolved download specification and retrieved bodies
together with the declared artifacts.

## Verification

The verifier performs these named checks:

| Check | Rule |
|---|---|
| `http.input` | Retrieval keys equal the keys in `DownloadSpec.inputs`. |
| `http.request` | Each retrieval request equals `DownloadSpec.inputs[input_name]`. |
| `http.policy` | Each frozen request and redirect target satisfies `DownloadSpec.policy`. |
| `http.credentials` | The runner sends the resolved secret only to its authorized origins and redacts its value from persisted evidence. |
| `http.transport.identity` | The built-in transport matches the effective installed environment, or the project transport callable and parameter model match their frozen identities. |
| `http.transport.parameters` | Project transport parameters validate through the selected parameter class and equal the frozen mapping. |
| `http.transport.executable` | Every frozen executable requirement matches the path verified before transport invocation. |
| `http.response` | The terminal response uses an accepted status and contains only the permitted persisted fields. |
| `http.content` | Retrieved bytes match the expected request identity and the resolved body identity. |
| `http.delivery` | Each context handle matches one resolved retrieval and its body path contains the verified bytes. |
| `parameter_model.identity` | Download parameter-model bytes match the frozen source identity. |
| `parameter_model.validation` | Frozen download parameters validate through the selected class. |
| `stage.source` | The executed download callable matches the frozen source identity. |
| `artifact.files` | Published artifact bytes match the resolved artifact identities. |

These checks establish that the identified transport callable received the
frozen request, produced the identified file, and supplied that file to the
identified download-stage callable.

VIPER 0.1 trusts the selected project transport and download-stage source.
Future network confinement will restrict undeclared outbound paths and support
a complete network-input claim.

## Propagation

| Surface | Required change |
|---|---|
| Protocol | Add the request, policy, transport, retrieval, and external-executable models. |
| Authoring | Expand URL templates, freeze the final request, expected body identity, selected transport, executable requirements, and authorized credential origins. |
| Variant binding | Include download-stage and project-transport parameter mappings. |
| Preflight | Validate request policy, callable identities, parameter identities, secret availability, and external executable identities. |
| Runner | Invoke the selected transport, constrain its destination, verify its response and body, and persist each retrieval before stage invocation. |
| Stage interface | Expose one verified retrieval handle per declared input through `DownloadContext`. |
| Resolved result | Publish the input-keyed retrievals, transport evidence, external-tool identities, responses, and body identities. |
| Verifier | Apply the named HTTP, transport, delivery, source, and artifact checks. |
| Public API | Export `http_transport`, transport contexts, transport results, and transport parameter bases. |
| Tests | Apply the transport conformance suite to the built-in transport and one decorated project transport. |

## Acceptance case

The built-in acceptance case freezes one HTTPX retrieval from a local test
server. The server returns one redirect followed by status `200`, content type
`application/gzip`, and fixed bytes. The runner records one retrieval, verifies
the expected body identity, constructs `DownloadContext`, and invokes the exact
download callable. The test checks the frozen request, built-in transport
identity, terminal response, body digest, byte count, stage invocation receipt,
extracted artifact identity, and terminal run verification.

The project-transport acceptance case decorates a transport with typed
parameters, freezes its implementation identity, and retrieves the same bytes
from a range-capable local server. The test checks transport-parameter delivery,
external-executable identity when one is used, and the same final body digest.

The conformance suite also covers a disallowed host, unauthorized credential
origin, missing secret, unaccepted status, timeout, oversized body, returned
path escape, missing external executable, modified transport source, and
same-length body tampering. Each case fails through its named preflight,
runtime, or verifier rule.

## Implementation order

1. Add frozen request, retrieval-policy, transport, and resolved-retrieval
   models.
2. Add the transport decorator, project-transport parameter validation, and
   source-identity checks.
3. Implement the built-in HTTPX transport and runner-owned body storage.
4. Add `DownloadContext` with one verified handle per declared input.
5. Add preflight executable verification for adapters such as `aria2c`.
6. Add verifier rules and the transport conformance suite.
