# External input roots contract and execution checklist

VIPER should accept ordinary user inputs while recording where each input
entered the provenance graph. This contract defines the root record for values
that originate outside an earlier VIPER run and connects that record to the
existing download, artifact, input-materialization, and verification paths.

## 1. Status

**Contract status:** proposed schema and execution change; implementation
pending.

**Current:** `DownloadSpec` declares HTTP requests through `HttpRequestSpec`.
The download worker retrieves each response, stores the response body through
`LocalArtifactStore`, and constructs `ResolvedHttpRetrieval`.
See [`src/viper/stages.py`](../../src/viper/stages.py) and
[`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py).

**Current:** A stage artifact becomes a `ResolvedArtifact` after the stage
process finishes. VIPER reads each declared artifact file or bundle member,
computes its byte count and SHA-256 digest, and places the result in the
resolved stage record.
See [`src/viper/execution/_stage.py`](../../src/viper/execution/_stage.py).

**Current:** Internal stages accept `FutureInputRef` for an earlier stage in
the active run and `StoredInputRef` for a promoted artifact from a completed
run. The current input union contains `StoredInputRef` and `FutureInputRef`; an
external-root branch belongs to the proposed contract.
See [`src/viper/stages.py`](../../src/viper/stages.py).

**Proposed:** VIPER treats every value entering through a VIPER-owned input
boundary as a provenance root when the value enters before any VIPER producer.
The root records the source description and the exact bytes observed by the
runner. A later stage can consume the root directly or produce a declared
artifact that later runs select through `ArtifactPointer`.

## 2. Required claim

When a user declares a local file or HTTP response as a stage input, VIPER
records the source, captures the observed bytes, assigns the input a root
identity, and verifies that the consuming stage receives those captured bytes.

The guarantee covers delivery and byte identity. The root records the origin
of the bytes; the consuming stage remains responsible for the scientific
meaning of those bytes.

## 3. Current gap

The fixed scenario is:

```text
user supplies an external dataset
-> VIPER gives the dataset to a training stage
-> the training stage produces model parameters
-> a later run reuses the model artifact
```

The current HTTP path is:

```text
HttpRequestSpec
-> invoke_transport()
-> HTTP response body at a retrieval workspace path
-> LocalArtifactStore.resolved_files()
-> ResolvedHttpRetrieval.body
-> DownloadSpec artifact declaration, when the stage declares the body
-> ResolvedArtifact
```

**Inspected:** `HttpRequestSpec` freezes the method, URL, expected body digest,
expected body byte count, headers, and credential reference.
[`src/viper/http.py`](../../src/viper/http.py)

**Inspected:** `ResolvedHttpRetrieval` binds the request, resolved transport,
observed response, and `ResolvedFileRef` for the stored body. Its validator
compares the body digest and byte count with the frozen request.
[`src/viper/http.py`](../../src/viper/http.py)

**Inspected:** `_retrieve_download_inputs()` creates `ResolvedHttpRetrieval`
after reading the transport body and publishing it through
`LocalArtifactStore.resolved_files()`.
[`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py)

**Inspected:** `_resolve_artifact()` creates `ResolvedSingleFileArtifact` or
`ResolvedBundleArtifact` for every artifact declared by any stage.
[`src/viper/execution/_stage.py`](../../src/viper/execution/_stage.py)

**Inspected:** `ResolvedHttpRetrieval` and `ResolvedArtifact` record related
facts with separate roles. The retrieval record describes an HTTP operation;
the artifact record describes a reusable stage output.

The missing connector is a protocol record that marks an external value as the
starting node of the provenance graph and lets the verifier distinguish an
observed root from an output produced by a VIPER stage.

## 4. Contract models

### External input source

**Proposed:** Define one source union for values entering through a VIPER-owned
boundary:

```python
class LocalExternalSource(ProtocolModel):
    kind: Literal["local"] = "local"
    path: RepoRelPath


class HttpExternalSource(ProtocolModel):
    kind: Literal["http"] = "http"
    request: HttpRequestSpec


ExternalInputSource = Annotated[
    LocalExternalSource | HttpExternalSource,
    Field(discriminator="kind"),
]
```

`LocalExternalSource` identifies the file selected by the user. The runner
reads that file at the declared input boundary. `HttpExternalSource` reuses
`HttpRequestSpec`; the HTTP retrieval subsystem owns request execution and
response verification.

### External input root

**Proposed:** Define the persisted root record:

```python
class ResolvedExternalInputRef(ProtocolModel):
    schema_version: Literal[1] = 1
    input_name: InputName
    source: ExternalInputSource
    files: tuple[ResolvedFileRef, ...] = Field(min_length=1)
    data_role: DataRole
```

`ResolvedExternalInputRef` belongs to the resolved consuming stage or its attempt
record. The runtime constructs it after it has captured and hashed the bytes.
The verifier consumes `files` to check delivery. The source-specific evidence
remains attached to `source`: HTTP roots retain `ResolvedHttpRetrieval`, and
local roots retain the captured `ResolvedFileRef`.

The final placement of the source-specific reference requires one schema
choice. The smallest compatible option stores an HTTP retrieval reference
beside `ResolvedExternalInputRef` in the resolved download record and stores a local
file reference directly in `ResolvedExternalInputRef.files`.

### Resolved stage connection

**Proposed:** Add external-root evidence to the resolved stage type that owns
the input operation:

```python
class ResolvedInternalSpec(ResolvedBaseSpec):
    inputs: dict[InputName, ResolvedInputRef]
    external_inputs: dict[InputName, ResolvedExternalInputRef] = Field(
        default_factory=dict
    )
```

The exact owner may instead be a run-level input record if one external input
can feed several stages. The implementation must choose one owner and preserve
the equality:

```text
set(external_inputs)
⊆
set(spec.inputs)
```

Each external input name identifies one consuming stage input. The input path
supplied to the stage remains the ordinary `Path` stored in the stage context
binding.

## 5. Execution

### Local file root

The runner performs this sequence when a stage declares a local external file:

```text
LocalExternalSource.path
-> resolve path beneath the repository or approved input root
-> read the exact file bytes
-> compute byte count and SHA-256
-> publish the captured bytes through LocalArtifactStore
-> construct ResolvedExternalInputRef
-> materialize the captured bytes at the stage input path
-> pass the path through StageContext.inputs[input_name]
```

The runner owns the read and capture operation. The stage callable receives the
captured file path and performs the project computation.

### HTTP root

The HTTP path reuses the current download machinery:

```text
HttpExternalSource.request
-> invoke_transport()
-> observe terminal response
-> verify expected body digest and byte count
-> publish body through LocalArtifactStore
-> construct ResolvedHttpRetrieval
-> construct ResolvedExternalInputRef from the stored body reference
-> pass the body path through StageContext.inputs[input_name]
```

`HttpRequestSpec` remains the frozen request contract. `ResolvedHttpRetrieval`
remains the HTTP execution receipt. `ResolvedExternalInputRef` supplies the common
provenance-graph role.

### Produced artifact connection

When the consuming stage declares the captured input as an output-derived
artifact, `_resolve_artifact()` continues to hash the declared output path and
construct `ResolvedArtifact`. A later run can select that artifact through
`ArtifactPointer`:

```text
external input root
-> consuming stage
-> declared output artifact
-> ResolvedArtifact
-> ArtifactPointer in a later run
```

An external root identifies where the input came from. An `ArtifactPointer`
identifies which completed VIPER run and declared artifact a later stage should
reuse.

## 6. Persisted evidence

The contract adds one root record and preserves the existing HTTP and artifact
records:

| Evidence | Writer | Consumer |
| --- | --- | --- |
| `HttpRequestSpec` | Run-plan authoring | HTTP transport and retrieval validator |
| `ResolvedHttpRetrieval` | Download executor | Download-stage verifier and resolved stage record |
| Local `ResolvedFileRef` | External-input capture operation | Root verifier and materializer |
| `ResolvedExternalInputRef` | Input capture owner | Input verifier and lineage inspection |
| `ResolvedArtifact` | Stage executor after declared output exists | Artifact verifier and later `ArtifactPointer` |

The root record must identify the exact captured bytes. A local source path
alone identifies a location; `files` identifies the observed contents.

The root record should live beneath the consuming run's canonical record path,
for example:

```text
experiments/<experiment>/runs/<variant>/<run>/stages/<stage>/external-inputs/<name>.yaml
```

The final path is an implementation choice. The path must remain beneath the
run record and appear in the resolved stage's persisted references.

## 7. Verification rules

### `external_input.source`

The authoring layer accepts only a supported source variant. A local source
must resolve to a regular file inside an approved root. An HTTP source must
pass the existing request and network policy checks.

### `external_input.capture`

The runtime writes the observed source bytes through `LocalArtifactStore` and
records the resulting `ResolvedFileRef`. The root record references that exact
file identity.

### `external_input.delivery`

Before the stage callable runs, the materializer reads the captured bytes and
writes them at the declared input path. The verifier compares the materialized
bytes with the root's `ResolvedFileRef` values.

### `external_input.http`

For an HTTP root, `ResolvedHttpRetrieval.body.sha256` equals
`HttpRequestSpec.expected_body_sha256`, and `ResolvedHttpRetrieval.body.bytes`
equals `HttpRequestSpec.expected_body_bytes`. The existing
`ResolvedHttpRetrieval` validator owns these comparisons.

### `external_input.lineage`

An external root enters before any VIPER producer. A later artifact produced
from that input records the consuming stage and can enter the normal artifact
and pointer chain.

### `external_input.path`

The materialization path stays beneath the repository root and remains distinct
from the persisted root record. The existing workspace path checks apply.

## 8. Default and harness modes

### Default mode

**Proposed:** The default mode accepts external roots through VIPER-owned input
boundaries. The user keeps the existing decorator, typed-parameter, and
`context.inputs` workflow. VIPER records the root internally.

```text
user declares or supplies an external input
-> VIPER captures and records the root
-> decorated stage receives a Path
```

### Harness mode

**Deferred:** Harness mode requires explicit promotion of selected outputs into
the project-root `inputs/` directory. Harness mode changes promotion authority
and pointer visibility. It preserves the external-root record and byte checks.

The harness contract requires separate decisions about naming, overwrite
rules, review ownership, and the relationship between generated pointers and
explicitly published pointers.

## 9. Propagation

| Surface | Required statement |
| --- | --- |
| Type | Add `ExternalInputSource` and `ResolvedExternalInputRef` with one source-specific branch for local files and one for HTTP requests |
| Authoring | Accept an external input declaration through the existing decorated-stage and typed-parameter workflow |
| Freeze | Bind the declaration to the consuming stage and write the selected source identity into the frozen plan |
| Runtime | Read or retrieve the source, hash the observed bytes, and construct `ResolvedExternalInputRef` |
| Persistence | Store the root record and its exact file references beneath the consuming run record |
| HTTP retrieval | Reuse `HttpRequestSpec` and `ResolvedHttpRetrieval` for request and response evidence |
| Artifact capture | Continue constructing `ResolvedArtifact` for every declared stage output |
| Materialization | Supply the captured bytes through the existing `StageContext.inputs` path |
| Verification | Compare root file identities with materialized bytes and validate HTTP request/body identity |
| Lineage | Treat the root as the graph origin and connect later outputs through the consuming stage |
| Tests | Add local-root, HTTP-root, tampered-byte, and produced-artifact acceptance cases |
| Documentation | Explain external roots in ordinary language and keep pointer internals out of the default user workflow |

## 10. Acceptance cases

### Local external dataset

The fixture supplies `data/input.h5ad` as the dataset for a decorated training
stage.

```text
freeze input declaration
-> execute capture
-> publish local bytes and create ResolvedExternalInputRef
-> materialize data/input.h5ad for train(context)
-> train writes declared model artifact
-> resolved stage contains root evidence and ResolvedArtifact
```

The test asserts that the root digest equals the captured file digest and that
the training callable receives bytes with the same digest.

### HTTP external dataset

The fixture supplies an `HttpRequestSpec` with an expected body digest and a
fake transport response.

```text
execute HttpRequestSpec
-> construct ResolvedHttpRetrieval
-> construct ResolvedExternalInputRef from retrieval.body
-> materialize the response body for train(context)
-> verify the body against the frozen request identity
```

The test asserts that the root references the retrieval body and that the
existing HTTP digest and byte-count checks remain active.

### Tampered captured bytes

Change the captured local file after the root identity is recorded and before
the training stage consumes it. The verifier must reject the input under
`external_input.delivery` because the materialized bytes differ from the root
file reference.

### Later artifact reuse

After the training stage completes, construct the existing
`ArtifactPointer` for its declared model artifact. A later run consumes the
model through the existing stored-input path.

The test asserts this chain:

```text
ResolvedExternalInputRef
-> resolved training stage
-> ResolvedArtifact
-> ArtifactPointer
-> later StoredInputRef
```

## 11. Implementation order

### Phase 1. Define the root evidence

- [ ] Add `ExternalInputSource` variants.
- [ ] Add `ResolvedExternalInputRef` and its canonical persisted path.
- [ ] Decide whether source-specific references live inside the root record or
      beside the resolved stage record.
- [ ] Add model and serialization tests.

**Commit boundary:** root records parse, serialize, and preserve exact file
identity.

### Phase 2. Capture local external inputs

- [ ] Add the local input authoring declaration.
- [ ] Resolve and validate the local source path.
- [ ] Publish captured bytes through `LocalArtifactStore`.
- [ ] Materialize the captured bytes for the consuming stage.
- [ ] Add the local-root acceptance and tampering rejection cases.

**Commit boundary:** a decorated training stage consumes a local external file
with persisted root evidence.

### Phase 3. Connect HTTP retrievals

- [ ] Reuse `HttpRequestSpec` as the HTTP source declaration.
- [ ] Attach `ResolvedHttpRetrieval` to the external-root evidence.
- [ ] Preserve the existing response digest and byte-count checks.
- [ ] Add the HTTP-root acceptance case.

**Commit boundary:** HTTP and local inputs share the root contract while HTTP
retains its request-specific evidence.

### Phase 4. Connect later artifact reuse

- [ ] Preserve `ResolvedArtifact` construction for declared outputs.
- [ ] Ensure lineage inspection traverses root evidence through the consuming
      stage.
- [ ] Generate or expose the later `ArtifactPointer` through the automatic
      input-resolution contract.
- [ ] Add the root-to-artifact-to-pointer acceptance case.

**Commit boundary:** external data enters the graph at a verified root and
later outputs use the existing artifact-reuse contract.

### Deferred harness mode

- [ ] Define explicit promotion syntax.
- [ ] Assign project-root `inputs/` ownership.
- [ ] Define pointer naming and overwrite rules.
- [ ] Define review and publication behavior.

## 12. Verdict

**Proposed decision:** treat every value entering through a VIPER-owned input
boundary as a provenance root and accept that root in default mode.

The root classification comes from the capture operation. A local path or HTTP
request becomes a root when VIPER reads the bytes, records their identity, and
hands the captured result to a stage. A file opened directly inside user code
remains outside the captured input contract.

The proposed contract preserves the current `DownloadSpec` and
`ResolvedHttpRetrieval` roles, adds the missing common root record, and lets
later stage outputs enter the existing `ResolvedArtifact` and
`ArtifactPointer` chain.

## Implementation sources

- [HTTP request and retrieval models](../../src/viper/http.py)
- [Stage input and artifact models](../../src/viper/stages.py)
- [Input materialization](../../src/viper/execution/_materialization.py)
- [Artifact resolution](../../src/viper/execution/_stage.py)
- [Artifact and pointer models](../../src/viper/artifacts.py)
- [Artifact verification](../../src/viper/verification.py)
- [Automatic input resolution contract](automatic-input-resolution.md)
