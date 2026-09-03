# Download retrieval artifact identity

`DownloadSpec` publishes every successful HTTP response as the
single-file artifact with the same name. `ResolvedHttpRetrieval` records the
HTTP exchange. `ResolvedSingleFileArtifact` exposes the retrieved body to
ordinary artifact consumers. Both records identify one file in the completed
download-stage snapshot.

The same response bytes occupy three provenance roles:

```text
external-input-root record
-> ResolvedDownloadSpec.retrievals[name]: ResolvedHttpRetrieval

artifact view
-> ResolvedDownloadSpec.artifacts[name]: ResolvedSingleFileArtifact

same-run consumer selector
-> InternalSpec.inputs[name]: FutureInputRef
```

`ResolvedDownloadSpec.retrievals[name].body ==
ResolvedDownloadSpec.artifacts[name].file` joins the root record to the
artifact view. `FutureInputRef` names the download stage and artifact; the
selected artifact supplies the later stage's input bytes.

## 1. Status

**Contract status:** In progress; Phase 2 implemented; DRA-06 planned for Master Phase 11.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| DRA-01 <!-- contract-requirement: DRA-01 phase=2 test=tests/test_protocol.py --> | Replace the frozen and resolved download models with the runner-owned hierarchy and shared-file schema. |
| DRA-02 <!-- contract-requirement: DRA-02 phase=2 test=tests/test_run_execution.py --> | Execute successful downloads in the attempt process and remove the project download worker. |
| DRA-03 <!-- contract-requirement: DRA-03 phase=2 test=tests/test_execution_acceptance.py --> | Copy and hash the HTTP result body into the declared artifact path before snapshot publication. |
| DRA-04 <!-- contract-requirement: DRA-04 phase=2 test=tests/test_verification_acceptance.py --> | Verify runner custody and exact receipt-artifact file equality. |
| DRA-05 <!-- contract-requirement: DRA-05 phase=2 test=tests/test_generated_project_acceptance.py --> | Remove the retired callable-copy path from fixtures, generated scaffolding, and execution tests. |
| DRA-06 <!-- contract-requirement: DRA-06 phase=11 test=tests/test_documentation.py --> | Remove the retired callable-copy path from protocol and public documentation. |

**Implemented through DRA-05:** each `DownloadSpec.inputs[name]` produces
`DownloadSpec.artifacts[name]`. The executor writes the verified response at
that declared artifact path. The successful `ResolvedHttpRetrieval` and
`ResolvedSingleFileArtifact` use one `SnapshotFileRef` for that path.
`DownloadSpec` becomes runner-owned and drops the project callable, parameter
model, and stage parameters.

This contract owns the HTTP retrieval-to-artifact join. The external-root
contract owns the wider provenance graph; the automatic-input-resolution
contract owns later selection through `FutureInputRef`, `ArtifactPointer`, and
`StoredInputRef`.

## 2. Required claim

VIPER verifies that each successful request declared as
`DownloadSpec.inputs[name]` produced the single-file artifact declared as
`DownloadSpec.artifacts[name]`, and that the HTTP receipt and artifact record
identify the same snapshot file.

The claim covers delivery and execution custody. VIPER performs the HTTP
request, writes the verified body, records the final stage snapshot, and
verifies the shared file identity. Dataset meaning, license status, and
scientific suitability remain outside this contract.

## 3. Closed Phase 2 gap

### Fixed scenario

The fixed case uses one response body, `b"prior"`, for one frozen request and
one dataset artifact:

```text
HTTP request key:     "prior"
declared artifact:    "prior"
response body:        b"prior"
artifact path:        experiments/example/runs/baseline/<run-id>/artifacts/datasets/tiny/prior.bin
```

The design decision under review is the relationship between the retrieval
receipt body and the download-stage artifact file.

### Retired baseline path

The baseline `retrieve_download_inputs()` retrieved the body into an attempt
workspace, publishes it through `LocalArtifactStore.resolved_files()`, and
writes it at `retrieval_body_path(run, stage_id, input_name)`. The function
stores that `ResolvedFileRef` in `ResolvedHttpRetrieval.body` and passes the
retrieval path to the download worker. See
[`retrieve_download_inputs`](../../src/viper/execution/_materialization.py)
and the deleted `viper.paths.retrieval_body_path()` helper.

The baseline download callable received the body through
`DownloadContext.retrievals[name].body` and receives writable declared output
paths through `context.artifacts`. The project initializer writes a default
callable that reads each retrieval body and writes the same bytes to the
artifact path. [`DownloadContext`](../../src/viper/stages.py) and
[`project.py`](../../src/viper/project.py) establishes that behavior.

After the baseline callable exited, `execute_stage_process()` hashed each
file in `stage_spec.artifacts` and creates `ResolvedSingleFileArtifact` or
`ResolvedBundleArtifact`. [`execute_stage_process`](../../src/viper/execution/_stage.py)
owns that operation.

The active execution fixture demonstrates the unjoined relationship:

```python
inputs={"source": HttpRequestSpec(...)},
artifacts={"dataset": SingleFileArtifactSpec(...)},

source = context.retrievals["source"].body
target = context.artifacts["dataset"]
target.write_bytes(source.read_bytes())
```

[`tests/test_execution_acceptance.py`](../../tests/test_execution_acceptance.py)
contains that fixture.

The baseline persisted records therefore described two paths:

```text
ResolvedHttpRetrieval.body
-> ResolvedFileRef at stages/<stage-id>/retrievals/<input-name>/body

ResolvedSingleFileArtifact.file
-> SnapshotFileRef at the declared artifact path
```

The baseline validators established separate checks for the request-body digest,
request-body byte count, and declared artifact path. The implemented validator
adds the retrieval-artifact equality rule for the name, path, SHA-256 digest,
and byte count. [`ResolvedHttpRetrieval`](../../src/viper/http.py),
[`ResolvedBaseSpec`](../../src/viper/stages.py), and
[`ResolvedDownloadSpec`](../../src/viper/stages.py) define those checks.

Phase 2 closes that connector with an equality rule joining one request, one
retrieval receipt, and one declared single-file artifact.

### Current DAG at the Phase 2 review baseline

```mermaid
flowchart LR
    Request["HttpRequestSpec"] --> Receipt["ResolvedHttpRetrieval.body"]
    Receipt --> Copy["callable copies bytes"]
    Copy --> Artifact["ResolvedSingleFileArtifact.file"]
    Receipt --> Gap["identity checked separately"]
    Artifact --> Gap
    class Request,Receipt,Artifact current
    class Copy evidence
    class Gap gap
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef evidence fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Proposed-change DAG, implemented in Phase 2

```mermaid
flowchart LR
    Request["named request"] --> File["one published SnapshotFileRef"]
    File --> Receipt["ResolvedHttpRetrieval.body"]
    File --> Artifact["ResolvedSingleFileArtifact.file"]
    Receipt --> Rule["retrieval-artifact equality rule"]
    Artifact --> Rule
    class Request,File,Receipt,Artifact,Rule implemented
    classDef implemented fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Integrated DAG

```mermaid
flowchart LR
    Spec["DownloadSpec"] --> Fetch["runner fetches body"]
    Fetch --> Publish["publish_download_body"]
    Publish --> File["SnapshotFileRef"]
    File --> Receipt["ResolvedHttpRetrieval"]
    File --> Artifact["ResolvedSingleFileArtifact"]
    Receipt --> Verify["download verifier"]
    Artifact --> Verify
    class Spec contract
    class Fetch,Publish implementation
    class File,Receipt,Artifact,Verify output
    classDef contract fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef output fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

## 4. Contract models

### 4.1 Frozen `DownloadSpec`

`DownloadSpec` accepts one `HttpRequestSpec` and one declared
single-file artifact for each shared name.

The target frozen hierarchy places project callable identity on
`ParameterizedSpec` and leaves `DownloadSpec` under the common stage fields:

```python
class BaseSpec(ProtocolModel):
    kind: str
    schema_version: Literal[1] = 1
    env: EnvSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()
    artifacts: dict[ArtifactName, ArtifactSpec] = Field(min_length=1)


class ParameterizedSpec(BaseSpec):
    implementation: StageImplementationRef
    parameter_model: ParameterModelRef
    reuse: StageReuseMode = "never"


class DownloadSpec(BaseSpec):
    kind: Literal["download"] = "download"
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpImplementationSpec
    policy: HttpRetrievalPolicy
```

`DownloadSpec` therefore carries the request map, HTTP implementation, policy,
`env` override, metric IDs, and artifact declarations. Build, embed, train,
and eval stages inherit `ParameterizedSpec` and retain project
implementation and parameter-model identity.

```text
set(spec.inputs) == set(spec.artifacts)

for every name in spec.inputs:
    spec.artifacts[name] is SingleFileArtifactSpec
```

`InputName` and `ArtifactName` both use `HumanId`. The new equality rule gives
the common value one role in a download stage: it names the HTTP request, the
receipt, and the artifact.

```python
DownloadSpec(
    inputs={"prior": HttpRequestSpec(...)},
    artifacts={"prior": SingleFileArtifactSpec(...)},
    http=...,
    policy=...,
)
```

The `DownloadSpec` validator owns the shared-name and single-file checks. A
download specification with a request key missing from `artifacts`, an artifact
key missing from `inputs`, or a bundle artifact fails validation.

### 4.2 Resolved records

`ResolvedHttpRetrieval.body` is a
`SnapshotFileRef`. The file reference gives the retrieval receipt its path,
SHA-256 digest, and byte count inside the completed `ResolvedStageRef.snapshot`.

The complete target records are:

```python
class SnapshotFileRef(ProtocolModel):
    path: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class ResolvedHttpRetrieval(ProtocolModel):
    input_name: InputName
    request: HttpRequestSpec
    http: ResolvedHttpImplementation
    response: ObservedHttpResponse
    body: SnapshotFileRef
    started_at: AwareDatetime
    completed_at: AwareDatetime


class ResolvedSingleFileArtifact(ProtocolModel):
    kind: Literal["file"] = "file"
    file: SnapshotFileRef
```

`ResolvedDownloadSpec` retains two maps with different jobs:

```python
retrievals: dict[InputName, ResolvedHttpRetrieval]
artifacts: dict[ArtifactName, ResolvedArtifact]
```

The maps share keys. Each artifact value is `ResolvedSingleFileArtifact`. The
new `ResolvedDownloadSpec` validator requires:

```text
set(retrievals) == set(spec.inputs) == set(artifacts)

for every name:
    retrievals[name].body == artifacts[name].file
```

The two record classes remain separate. `ResolvedHttpRetrieval` stores the
request, resolved HTTP implementation, observed response, and timestamps. The inherited
`artifacts` map gives the same body the standard artifact interface used by
later stages and artifact pointers.

### 4.3 Runner-owned resolved record

`ResolvedDownloadSpec` contains runner evidence and HTTP receipts. The later
automatic-input-resolution phase places runner evidence in
`ResolvedExecutedSpec` and project-callable evidence in
`ExecutedStageCompletion`.

```python
class ResolvedDownloadSpec(ResolvedExecutedSpec):
    kind: Literal["download"] = "download"
    spec: DownloadSpec
    retrievals: dict[InputName, ResolvedHttpRetrieval]


class ResolvedParameterizedSpec(ResolvedBaseSpec):
    spec: ParameterizedSpec
    completion: StageCompletion
```

Phase 2 implements this ownership boundary with `ResolvedBaseSpec` and
`ResolvedParameterizedSpec`; the later phase introduces the completion unions
shown above. The download record retains `env`, execution context, retrievals,
artifacts, and completion. Each
`ResolvedHttpRetrieval` supplies request, HTTP implementation, response, body,
and timing evidence. See
[`automatic-input-resolution.md`](automatic-input-resolution.md#target-frozen-download-and-resolved-stage-models).

### 4.4 Planned public authoring example
<!-- contract-worked-example: start -->

This program declares one request and its same-named dataset artifact. Omitting
`http=` selects VIPER's built-in HTTPX implementation. The file served at the
URL contains these exact 22 bytes:

```csv
feature,label
1,0
2,1
```

```python
import csv
from pathlib import Path

from viper import authoring
from viper.artifacts import artifact
from viper.http import HttpRequestSpec, HttpRetrievalPolicy


DATASET_PATH = "artifacts/datasets/training_set/dataset.csv"


def load_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


download = authoring.download(
    inputs={
        "dataset": HttpRequestSpec(
            url="http://127.0.0.1:8000/dataset.csv",
            version="tiny-v1",
            expected_body_sha256=(
                "81801ff05409c3cddb57bffa4a856673"
                "06fa92cd48a8437a9aa937f750a7d7c6"
            ),
            expected_body_bytes=22,
        ),
    },
    policy=HttpRetrievalPolicy(
        allowed_schemes=frozenset({"http"}),
        allowed_hosts=frozenset({"127.0.0.1"}),
        allowed_ports=frozenset({8000}),
        accepted_statuses=frozenset({200}),
        max_redirects=0,
        max_body_bytes=1024,
        timeout_seconds=10.0,
    ),
    artifacts={
        "dataset": artifact(
            path=DATASET_PATH,
            loader=load_dataset,
            data_role="training",
        ),
    },
)

download_spec = download.spec
assert isinstance(download_spec, authoring.DownloadSpecDraft)
assert set(download_spec.inputs) == {"dataset"}
assert set(download_spec.artifacts) == {"dataset"}
assert download_spec.artifacts["dataset"].path == DATASET_PATH
```

Master Phase 6 adds `authoring.download()` and `DownloadSpecDraft`. At freeze
time, that draft becomes the frozen `DownloadSpec` shown in section 4.1.
Freezing prefixes the selected run root and writes the concrete
repository-relative path to `DownloadSpec.artifacts["dataset"].path`. At
execution time, VIPER invokes the selected HTTP implementation and publishes
the verified body at that concrete path.

The complete custom-HTTP and model-run program lives in
[`automatic-input-resolution.md`](automatic-input-resolution.md#complete-proposed-authoring-example).

<!-- contract-worked-example: end -->

## 5. Execution

The executor owns the retrieval body from `HttpResult` through the
completed stage snapshot.

```text
DownloadSpec.inputs["prior"]
    -> HTTP function retrieves b"prior"
    -> executor checks the frozen request policy
    -> executor writes b"prior" at spec.artifacts["prior"].path
    -> executor creates SnapshotFileRef(path, sha256, bytes)
    -> ResolvedHttpRetrieval.body receives that reference
    -> ResolvedSingleFileArtifact.file receives that same reference
    -> ResolvedDownloadSpec validates reference equality
    -> stage snapshot stores the path once
```

`retrieve_download_inputs()` changes its output path from
`retrieval_body_path(...)` to `stage.artifacts[input_name].path`. One helper
owns the copy from the HTTP scratch destination to that artifact path:

```python
def publish_download_body(
    *,
    repository_root: Path,
    source: Path,
    destination: RepoRelPath,
    expected_sha256: SHA256,
    expected_bytes: int,
) -> SnapshotFileRef: ...
```

The helper opens the HTTP result body as a regular, nonsymlink file beneath the
attempt workspace. It streams that file into a temporary sibling of the
declared artifact path while calculating the SHA-256 digest and byte count of
the bytes it writes. It compares those two values with the frozen request. It
flushes the accepted file and atomically replaces the declared artifact path.
It returns the `SnapshotFileRef` for that path. A failed comparison deletes the
temporary file and leaves the declared artifact path absent.

`retrieve_download_inputs()` stops calling
`LocalArtifactStore.resolved_files()` for the retrieval body. The later stage
snapshot publisher checks the artifact file against the returned
`SnapshotFileRef` before publication.

The executor performs the write that publishes the HTTP body as the declared
artifact. It then resolves the declared artifact directly and constructs the
two records from one `SnapshotFileRef`. Generated project code and execution
fixtures delete the download callable and its read-and-write loop.

`_attempt.py` adds retrieval files and artifact files to one `snapshot_files`
dictionary before publication. Both views use the same dictionary key. The
destination-aware snapshot publisher receives that path once and returns the
local or Viper Cloud snapshot reference.

## 6. Persisted evidence

The completed download-stage snapshot contains:

```text
stages/download/resolved.yaml
experiments/.../artifacts/datasets/tiny/prior.bin
```

`resolved.yaml` contains both views of `prior`:

```yaml
retrievals:
  prior:
    input_name: prior
    request: <frozen request>
    http: <resolved HTTP implementation>
    response: <observed response>
    body:
      path: experiments/.../artifacts/datasets/tiny/prior.bin
      sha256: <sha256 of b"prior">
      bytes: 5
    started_at: <timestamp>
    completed_at: <timestamp>
artifacts:
  prior:
    kind: file
    file:
      path: experiments/.../artifacts/datasets/tiny/prior.bin
      sha256: <sha256 of b"prior">
      bytes: 5
```

The duplicated YAML fields describe one file. The containing
`ResolvedDownloadSpec` validator establishes the equality relationship.

Implementation regenerates existing download fixtures and stored test records
with the implemented shape.

## 7. Verification

| Rule | Executable condition |
| --- | --- |
| `download.model.complete` <!-- verifier-rule: download.model.complete requirement=DRA-01 --> | Frozen and resolved download records use the runner-owned model hierarchy and shared-file schema. |
| `download.runner.custody` <!-- verifier-rule: download.runner.custody requirement=DRA-02 --> | A successful download runs inside the attempt process without invoking a project download worker. |
| `download.artifact.identity` <!-- verifier-rule: download.artifact.identity requirement=DRA-03 --> | The published artifact bytes, digest, and byte count equal the HTTP result body. |
| `download.verification.identity` <!-- verifier-rule: download.verification.identity requirement=DRA-04 --> | Verification proves runner custody and exact receipt-artifact file equality. |
| `download.legacy.removed` <!-- verifier-rule: download.legacy.removed requirement=DRA-05 --> | Fixtures, generated projects, and execution tests contain no callable-copy download path. |
| `download.docs.current` <!-- verifier-rule: download.docs.current requirement=DRA-06 --> | Protocol and public documentation contain no retired callable-copy download path. |

### 7.1 HTTP receipt rule

`ResolvedHttpRetrieval` continues to enforce:

```text
body.sha256 == request.expected_body_sha256
body.bytes  == request.expected_body_bytes
```

`_verify_download_retrievals()` continues to verify the selected HTTP implementation,
request policy, accepted response status, response body, and retrieval timing.
The function reads the body from the enclosing stage snapshot through
`SnapshotFileRef`. [`_verify_download_retrievals`](../../src/viper/_verification/attempt.py)
owns that verification.

### 7.2 Receipt-artifact identity rule

**Rule: `download.receipt_artifact_identity`.**

The `ResolvedDownloadSpec` validator checks the shared keys, single-file
artifact shape, and exact `SnapshotFileRef` equality. The attempt verifier
repeats the comparison after it loads `resolved.yaml` from the stage snapshot.

```text
retrievals[name].body.path   == artifacts[name].file.path
retrievals[name].body.sha256 == artifacts[name].file.sha256
retrievals[name].body.bytes  == artifacts[name].file.bytes
```

### 7.3 Runner custody rule

**Rule: `download.runner_custody`.**

`retrieve_download_inputs()` passes the attempt-workspace destination to the
selected HTTP function. `invoke_http()` requires
`HttpResult.body.resolve()` to equal that destination, verifies the
regular-file and symlink rules, checks the terminal response, and compares the
body byte count and SHA-256 digest with `HttpRequestSpec`.
`publish_download_body()` then hashes the bytes it writes to the declared
artifact path and repeats the frozen digest and byte-count checks. The shared
`SnapshotFileRef` comes from that copy operation. The snapshot publisher checks
the same identity once more before sealing the stage snapshot.

## 8. Propagation and change impact

| Surface | Baseline | Implemented | Effect |
| --- | --- | --- | --- |
| Frozen stage schema | Request and artifact keys vary independently | Keys match one-for-one and every download artifact is a single file | One HTTP body receives one artifact name |
| Retrieval receipt | `body: ResolvedFileRef` points to a local-store retrieval path | `body: SnapshotFileRef` points to the declared artifact path | Receipt and artifact reference one snapshot file |
| Retrieval runtime | `retrieve_download_inputs()` publishes a retrieval-body revision and materializes its canonical path | `publish_download_body()` copies and hashes the HTTP result body into `spec.artifacts[name].path` | The digest covers the bytes actually written at the artifact path |
| Stage snapshot | Retrieval and artifact loops use different keys | Both loops use the same key | `snapshot_files` stores one body entry |
| Verification | HTTP body and artifact verification run independently | `download.receipt_artifact_identity` joins the two records | Verifier proves one HTTP body became the named artifact |
| Stage execution | Download launches a project worker after retrieval | The attempt process retrieves, verifies, publishes, and resolves the artifact | Download becomes a runner-owned stage |
| Resolved stage | `ResolvedDownloadSpec` carries project source, startup, invocation, and command fields through `ResolvedBaseSpec` | Phase 2 moves those fields to `ResolvedParameterizedSpec`; the later completion-union phase moves them into `ExecutedStageCompletion`, while download retains runner `env`, execution context, retrievals, artifacts, and completion | Resolved evidence matches the runtime owner |
| Fixtures and examples | Request names and artifact names may differ | Each download fixture uses the same name in both maps | Tests state the new public rule |
| Documentation | External roots describes the HTTP receipt and later artifact | External roots links to this contract | One owner for the schema and execution detail |
| Storage publication | Local publication writes the completed stage snapshot through `LocalArtifactStore` | The destination-aware publisher writes the shared snapshot file once to local storage or Viper Cloud | Receipt and artifact remain joined at either destination |

### 8.1 Legacy cleanup

This contract retires the repository-level retrieval-body path. The HTTP
function still receives an attempt-workspace directory and writes its completed response
there before the executor publishes the verified body at the declared artifact
path.

| Retired occurrence | Disposition | Required replacement |
| --- | --- | --- |
| `viper.paths.retrieval_body_path()`, its imports, and the otherwise empty `viper.paths` module | Delete | Use `stage.artifacts[input_name].path` for the published body. Update the current-gap link when the module is removed. |
| The `run` and `store` parameters and `LocalArtifactStore.resolved_files()` call in `retrieve_download_inputs()` | Delete | Publish the body once through the completed stage snapshot. Keep the attempt-workspace transfer file as execution scratch. |
| `HttpRetrievalContextBinding`, `StageContextBinding.retrievals`, `HttpRetrievalHandle`, and `DownloadContext` | Delete | The attempt process consumes `HttpResult` directly and writes `ResolvedHttpRetrieval`. |
| Download path reconstruction in `viper._workers.stages` and `viper._verification.attempt` | Delete | Download skips the project-stage worker and stage-invocation verifier. Remove the resulting unused retrieval parameters and branches. |
| The generated download callable in `viper.project` | Delete | Omit project-owned download code; `DownloadSpec` declares runner-owned retrieval directly. |
| Copy loops and mismatched request/artifact names in `test_execution_acceptance.py`, `test_run_execution.py`, and `test_execution_signals.py` | Replace | Use one shared name and let the executor publish the response body. |
| The `test_verification_acceptance.py` fixture that models one `archive` request and three unrelated artifacts | Replace | Declare three same-named requests and single-file artifacts because this fixture exercises artifact verification. |
| Mismatched `remote` and `dataset` names in `test_preflight.py` | Replace | Give the request and artifact one shared name. |
| Hard-coded `stages/<stage-id>/retrievals/<input-name>/body` assertions | Delete | Assert the declared artifact path and its single snapshot member. |
| `ResolvedHttpRetrieval` model tests that construct `ResolvedFileRef` bodies | Replace | Construct `SnapshotFileRef` bodies at the declared artifact path and assert receipt-artifact equality. Keep HTTP scratch-file tests unchanged. |
| Generated-project acceptance coverage | Replace | Assert that the scaffold omits a download callable and execution publishes each response artifact. |
| `docs/reference/protocol.md` models and execution prose | Replace | Document runner-owned download, the shared successful `SnapshotFileRef`, and the executor-owned artifact write. |
| `HttpContext.workspace`, its bounded `destination`, and HTTP body tests | Retain | The attempt workspace remains the safety boundary for an in-progress request. |
| `LocalArtifactStore.resolved_files()` and its non-download callers | Replace at the orchestration boundary | Route independent files through `publish_resolved_files()`; the local implementation continues to delegate to `LocalArtifactStore`. |
| `DownloadSpec.implementation`, `download_stage`, `parameters.Download`, and download `StageInvocationReceipt` fixtures | Delete | `DownloadSpec` declares runner-owned retrieval; `ResolvedHttpRetrieval` supplies request execution evidence. |
| `BaseSpec.implementation` | Move | `ParameterizedSpec.implementation` owns project-callable stages. |
| `ResolvedBaseSpec.source`, `startup`, `invocation`, and `command` | Move | `ResolvedParameterizedSpec` owns project-callable execution evidence. |

## 9. Acceptance case

### Success: one `prior` response becomes one `prior` artifact

The acceptance fixture declares:

```text
inputs["prior"]
-> frozen request expecting b"prior"

artifacts["prior"]
-> declared single-file dataset path
```

The controlled HTTP function returns `b"prior"`. The executor writes the bytes at
the declared artifact path. The resolved download stage contains one retrieval
and one single-file artifact named `prior`. The stage snapshot contains the
artifact path once. `verify_run_result()` succeeds.

The test asserts:

```text
resolved.retrievals["prior"].body == resolved.artifacts["prior"].file
snapshot contains the declared artifact path once
retrieval body SHA-256 and byte count equal the frozen request
```

### Rejection: HTTP result body changes before artifact publication

The controlled HTTP function first returns the expected `b"prior"` body. Before
`publish_download_body()` copies it, the fixture replaces the scratch file
with `b"alter"`, which has the same byte count and a different digest.
`download.runner_custody` rejects the copy, leaves the declared artifact path
absent, and prevents stage-snapshot publication.

A separate model test changes
`resolved.artifacts["prior"].file.sha256` in a completed resolved-stage
document. `download.receipt_artifact_identity` rejects that unequal reference.

## 10. Implementation order

1. Add the shared-key and single-file `DownloadSpec` validator in
   [`src/viper/stages.py`](../../src/viper/stages.py). Add schema tests for a
   missing key, an extra key, and a bundle artifact.
2. Change `ResolvedHttpRetrieval.body` to `SnapshotFileRef`. Add the
   `ResolvedDownloadSpec` receipt-artifact identity validator and model tests.
3. Move `BaseSpec.implementation` to `ParameterizedSpec`. Remove
   `DownloadSpec.parameter_model` and `DownloadSpec.params`. Add
   `ResolvedParameterizedSpec`, then move `source`, `startup`, `invocation`,
   and `command` from `ResolvedBaseSpec` to that class.
4. Add `publish_download_body()` and make `retrieve_download_inputs()` use it
   for every verified response. Return the verified retrieval values and
   resolved artifacts needed by execution. Remove the helper's `store`
   parameter and duplicate
   `LocalArtifactStore.resolved_files()` call. Delete
   `retrieval_body_path()` and replace every caller with the same-named artifact
   path. Update stage-snapshot collection in
   [`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py),
   [`src/viper/execution/_stage.py`](../../src/viper/execution/_stage.py), and
   [`src/viper/execution/_attempt.py`](../../src/viper/execution/_attempt.py).
   Route `DownloadSpec` around `execute_stage_process()` and construct
   `ResolvedDownloadSpec` from runner-owned evidence.
5. Delete download retrieval bindings and live-handle reconstruction from
   [`src/viper/_workers/stages.py`](../../src/viper/_workers/stages.py). Update
   `_verify_stage_invocation()` and `_verify_download_retrievals()` in
   [`src/viper/_verification/attempt.py`](../../src/viper/_verification/attempt.py)
   so stage-invocation verification covers the four project-callable stages and
   download verification reads the shared snapshot reference.
6. Replace the existing download fixtures whose request and artifact names
   differ, and remove every retrieval-body-to-artifact copy loop. Remodel the
   verification-acceptance fixture as three same-named HTTP responses and
   artifacts. Add the success case, HTTP-body mutation case, and unequal
   resolved-reference case in
   `tests/test_run_execution.py`, `tests/test_execution_acceptance.py`,
   `tests/test_execution_signals.py`, `tests/test_preflight.py`,
   `tests/test_generated_project_acceptance.py`, and
   `tests/test_verification_acceptance.py`.
7. Remove generated download-stage scaffolding from
   [`src/viper/project.py`](../../src/viper/project.py)
   and the protocol reference. Link
   [`external-input-roots.md`](external-input-roots.md) to this contract and
   route the shared snapshot member through the destination-aware publisher
   defined by [`remote-storage.md`](remote-storage.md).

## 11. Invariants

| Classification | Rule | Evidence |
| --- | --- | --- |
| Preserved | HTTP receipt verification checks the frozen request, HTTP implementation, response policy, body digest, body byte count, and timing. | `ResolvedHttpRetrieval` and `_verify_download_retrievals()` tests |
| Preserved | A later stage selects a download artifact through `FutureInputRef` or `StoredInputRef`. | Same-run and prior-run input verification tests |
| Changed | Download stages accept matching request and artifact keys with one single-file artifact per request. | `DownloadSpec` validator tests |
| Changed | Retrieval bodies move from standalone `ResolvedFileRef` values to `SnapshotFileRef` values. | Resolved-document parser and verifier tests |
| Changed | Download execution belongs to the attempt process; project-stage invocation receipts cover build, embed, train, and eval stages. | Resolved-stage schema and attempt-execution tests |
| Introduced | Retrieval receipt and resolved artifact share one exact `SnapshotFileRef`. | `download.receipt_artifact_identity` acceptance and rejection tests |
| Strengthened | The attempt verifier proves that the runner published the verified response at the path shared by the retrieval receipt and artifact record. | Runner-custody and receipt-artifact identity assertions |

## 12. Contract-owned PairBlocks

These four blocks implement DRA-01 through DRA-05 from the accepted Phase 1
baseline `a6e0bdd318784d7e8fec86ff50a0d814540d73ee`. Their target declarations are the final reviewed
plan. One payload may serve several import or assignment names when those names
belong to the same Python statement.

<!-- pair-block-definition: P2-DRA-01 -->
```toml pair-block
id = "P2-DRA-01"
requirements = ["DRA-01"]
targets = [
    "src/viper/authoring.py:ProjectHttpImplementationSpec",
    "src/viper/authoring.py:ProjectHttpTransportSpec",
    "src/viper/authoring.py:freeze_run_plan",
    "src/viper/authoring.py:resolve_http",
    "src/viper/authoring.py:resolve_transport",
    "src/viper/authoring.py:validate_request_policy",
    "src/viper/experiments.py:DownloadVariantStageParams",
    "src/viper/experiments.py:VariantStageParams",
    "src/viper/http.py:BuiltinHttpImplementationSpec",
    "src/viper/http.py:BuiltinHttpTransportSpec",
    "src/viper/http.py:DecoratedHttp",
    "src/viper/http.py:DecoratedTransport",
    "src/viper/http.py:ExternalExecutableSpec",
    "src/viper/http.py:HttpCallable",
    "src/viper/http.py:HttpContext",
    "src/viper/http.py:HttpDefinition",
    "src/viper/http.py:HttpImplementationRef",
    "src/viper/http.py:HttpImplementationSpec",
    "src/viper/http.py:HttpParamsT",
    "src/viper/http.py:HttpResult",
    "src/viper/http.py:HttpRetrievalContextBinding",
    "src/viper/http.py:HttpRetrievalError",
    "src/viper/http.py:HttpRetrievalHandle",
    "src/viper/http.py:HttpTransportCallable",
    "src/viper/http.py:HttpTransportContext",
    "src/viper/http.py:HttpTransportDefinition",
    "src/viper/http.py:HttpTransportImplementationRef",
    "src/viper/http.py:HttpTransportResult",
    "src/viper/http.py:HttpTransportSpec",
    "src/viper/http.py:ProjectHttpImplementationSpec",
    "src/viper/http.py:ProjectHttpTransportSpec",
    "src/viper/http.py:ResolvedFileRef",
    "src/viper/http.py:ResolvedHttpImplementation",
    "src/viper/http.py:ResolvedHttpRetrieval",
    "src/viper/http.py:ResolvedHttpTransport",
    "src/viper/http.py:RuntimeHttpCredential",
    "src/viper/http.py:SnapshotFileRef",
    "src/viper/http.py:TransportParamsT",
    "src/viper/http.py:_httpx_request",
    "src/viper/http.py:_httpx_transport",
    "src/viper/http.py:_load_project_http",
    "src/viper/http.py:_load_project_transport",
    "src/viper/http.py:_verify_implementation_bytes",
    "src/viper/http.py:http",
    "src/viper/http.py:http_transport",
    "src/viper/http.py:invoke_http",
    "src/viper/http.py:invoke_transport",
    "src/viper/http.py:resolve_http",
    "src/viper/http.py:resolve_transport",
    "src/viper/inputs.py:HttpImplementationSpec",
    "src/viper/inputs.py:HttpRequestSpec",
    "src/viper/inputs.py:HttpRetrievalPolicy",
    "src/viper/inputs.py:HttpSource",
    "src/viper/inputs.py:HttpTransportSpec",
    "src/viper/parameters.py:Download",
    "src/viper/parameters.py:Http",
    "src/viper/parameters.py:HttpTransport",
    "src/viper/parameters.py:__all__",
    "src/viper/preflight.py:HttpRetrievalError",
    "src/viper/preflight.py:PreflightCheckCode",
    "src/viper/preflight.py:ProjectHttpImplementationSpec",
    "src/viper/preflight.py:ProjectHttpTransportSpec",
    "src/viper/preflight.py:preflight_plan",
    "src/viper/preflight.py:resolve_http",
    "src/viper/preflight.py:resolve_transport",
    "src/viper/preflight.py:validate_request_policy",
    "src/viper/stages.py:ArtifactSpec",
    "src/viper/stages.py:BaseSpec",
    "src/viper/stages.py:BuiltinHttpImplementationSpec",
    "src/viper/stages.py:DownloadContext",
    "src/viper/stages.py:DownloadSpec",
    "src/viper/stages.py:HttpImplementationSpec",
    "src/viper/stages.py:HttpRequestSpec",
    "src/viper/stages.py:HttpRetrievalContextBinding",
    "src/viper/stages.py:HttpRetrievalHandle",
    "src/viper/stages.py:HttpRetrievalPolicy",
    "src/viper/stages.py:HttpTransportSpec",
    "src/viper/stages.py:ParameterizedSpec",
    "src/viper/stages.py:ParameterizedStageSpec",
    "src/viper/stages.py:ResolvedArtifact",
    "src/viper/stages.py:ResolvedBaseSpec",
    "src/viper/stages.py:ResolvedDownloadSpec",
    "src/viper/stages.py:ResolvedHttpRetrieval",
    "src/viper/stages.py:ResolvedInternalSpec",
    "src/viper/stages.py:ResolvedParameterizedSpec",
    "src/viper/stages.py:ResolvedSingleFileArtifact",
    "src/viper/stages.py:SingleFileArtifactSpec",
    "src/viper/stages.py:Spec",
    "src/viper/stages.py:StageContextBinding",
    "src/viper/stages.py:download",
    "tests/test_http_retrieval.py:BuiltinHttpImplementationSpec",
    "tests/test_http_retrieval.py:BuiltinHttpTransportSpec",
    "tests/test_http_retrieval.py:EnvironmentSecretRef",
    "tests/test_http_retrieval.py:ExternalExecutableSpec",
    "tests/test_http_retrieval.py:HttpImplementationRef",
    "tests/test_http_retrieval.py:HttpRequestSpec",
    "tests/test_http_retrieval.py:HttpRetrievalError",
    "tests/test_http_retrieval.py:HttpRetrievalPolicy",
    "tests/test_http_retrieval.py:HttpTransportImplementationRef",
    "tests/test_http_retrieval.py:LocalFileRef",
    "tests/test_http_retrieval.py:ObservedHttpResponse",
    "tests/test_http_retrieval.py:ProjectHttpImplementationSpec",
    "tests/test_http_retrieval.py:ProjectHttpTransportSpec",
    "tests/test_http_retrieval.py:ResolvedFileRef",
    "tests/test_http_retrieval.py:ResolvedHttpImplementation",
    "tests/test_http_retrieval.py:ResolvedHttpRetrieval",
    "tests/test_http_retrieval.py:ResolvedHttpTransport",
    "tests/test_http_retrieval.py:SnapshotFileRef",
    "tests/test_http_retrieval.py:TransportFactory",
    "tests/test_http_retrieval.py:_invoke_conforming_http",
    "tests/test_http_retrieval.py:_invoke_conforming_transport",
    "tests/test_http_retrieval.py:_policy",
    "tests/test_http_retrieval.py:conforming_http",
    "tests/test_http_retrieval.py:conforming_transport",
    "tests/test_http_retrieval.py:invoke_http",
    "tests/test_http_retrieval.py:invoke_transport",
    "tests/test_http_retrieval.py:resolve_http",
    "tests/test_http_retrieval.py:resolve_transport",
    "tests/test_http_retrieval.py:test_http_conformance_accepts_exact_response_body",
    "tests/test_http_retrieval.py:test_http_conformance_rejects_destination_escape",
    "tests/test_http_retrieval.py:test_http_conformance_rejects_response_contract_violations",
    "tests/test_http_retrieval.py:test_http_rejects_policy_secret_and_same_length_body_failures",
    "tests/test_http_retrieval.py:test_http_rejects_unaccepted_status",
    "tests/test_http_retrieval.py:test_httpx_request_follows_policy_and_strips_cross_origin_secret",
    "tests/test_http_retrieval.py:test_httpx_transport_follows_policy_and_strips_cross_origin_secret",
    "tests/test_http_retrieval.py:test_project_http_receives_typed_parameters_and_exact_destination",
    "tests/test_http_retrieval.py:test_project_http_rejects_returned_path_escape",
    "tests/test_http_retrieval.py:test_project_transport_receives_typed_parameters_and_exact_destination",
    "tests/test_http_retrieval.py:test_project_transport_rejects_returned_path_escape",
    "tests/test_http_retrieval.py:test_resolved_retrieval_requires_the_expected_body_identity",
    "tests/test_http_retrieval.py:test_transport_conformance_accepts_exact_response_body",
    "tests/test_http_retrieval.py:test_transport_conformance_rejects_destination_escape",
    "tests/test_http_retrieval.py:test_transport_conformance_rejects_response_contract_violations",
    "tests/test_http_retrieval.py:test_transport_rejects_policy_secret_and_same_length_body_failures",
    "tests/test_http_retrieval.py:test_transport_rejects_unaccepted_status",
    "tests/test_preflight.py:artifact_loader_ref",
    "tests/test_preflight.py:builtin_http",
    "tests/test_preflight.py:builtin_http_transport",
    "tests/test_preflight.py:http_policy",
    "tests/test_preflight.py:http_request",
    "tests/test_preflight.py:parameter_model_ref",
    "tests/test_preflight.py:stage_implementation_ref",
    "tests/test_preflight.py:test_future_input_uses_canonical_producer_path",
    "tests/test_protocol.py:DownloadSpec",
    "tests/test_protocol.py:EvaluateSpec",
    "tests/test_protocol.py:ParameterizedSpec",
    "tests/test_protocol.py:TrainSpec",
    "tests/test_protocol.py:test_download_models_use_runner_owned_hierarchy",
    "tests/test_public_api.py:test_parameter_categories_form_the_public_extension_namespace",
    "tests/test_public_api.py:test_stage_interface_uses_parsimonious_names",
]
assets = [
    "docs/reference/protocol.md",
    "tests/data/download_stage.yaml",
]
tests = [
    "tests/test_protocol.py:test_download_models_use_runner_owned_hierarchy",
]
gate = "python -m pytest tests/test_protocol.py tests/test_http_retrieval.py tests/test_public_api.py tests/test_preflight.py -q"
depends_on = ["P1-RSP-04"]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/authoring.py:ProjectHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/authoring.py:resolve_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/experiments.py:DownloadVariantStageParams -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:BuiltinHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:DecoratedTransport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpRetrievalContextBinding -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpRetrievalHandle -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportCallable -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportContext -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportDefinition -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportImplementationRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportResult -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:HttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:ProjectHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:ResolvedFileRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:ResolvedHttpTransport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:TransportParamsT -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:_httpx_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:_load_project_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:http_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:invoke_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/http.py:resolve_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/inputs.py:HttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/parameters.py:Download -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/parameters.py:HttpTransport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/preflight.py:ProjectHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/preflight.py:resolve_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/stages.py:DownloadContext -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/stages.py:HttpRetrievalContextBinding -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/stages.py:HttpRetrievalHandle -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/stages.py:HttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=src/viper/stages.py:download -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:BuiltinHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:HttpTransportImplementationRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:LocalFileRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:ProjectHttpTransportSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:ResolvedFileRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:ResolvedHttpTransport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:_invoke_conforming_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:conforming_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:invoke_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:resolve_transport -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_httpx_transport_follows_policy_and_strips_cross_origin_secret -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_project_transport_receives_typed_parameters_and_exact_destination -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_project_transport_rejects_returned_path_escape -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_transport_conformance_accepts_exact_response_body -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_transport_conformance_rejects_destination_escape -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_transport_conformance_rejects_response_contract_violations -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_transport_rejects_policy_secret_and_same_length_body_failures -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_http_retrieval.py:test_transport_rejects_unaccepted_status -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=remove target=tests/test_preflight.py:builtin_http_transport -->
<!-- contract-remove -->

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/authoring.py:ProjectHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/authoring.py:resolve_http -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/authoring.py:validate_request_policy -->
```python contract-target
from .http import ProjectHttpImplementationSpec, resolve_http, validate_request_policy
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/authoring.py:freeze_run_plan -->
```python contract-target
def freeze_run_plan(
    repository_root: Path,
    draft: RunPlanDraft,
) -> FrozenPlanFiles:
    """Validate stage drafts, hash their bytes, and write one frozen run plan."""
    root = repository_root.resolve()
    run_root = (
        f"experiments/{draft.experiment_id}/runs/{draft.variant_id}/{draft.run_id}"
    )
    staged_files: list[tuple[Path, bytes]] = []
    references: list[RunStageRef] = []

    for stage in draft.stages:
        source = stage.spec_source
        if not source.is_absolute():
            source = root / source
        raw_source = source.read_bytes()
        spec = SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw_source))
        if isinstance(spec, ParameterizedSpec):
            reference = spec.parameter_model
            model_path = root / reference.path
            model_raw = model_path.read_bytes()
            verify_parameter_model_bytes(reference, model_raw)
            try:
                committed_model_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{reference.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise ParameterValidationError(
                    "parameter model is absent from the frozen source commit"
                ) from exc
            if model_raw != committed_model_raw:
                raise ParameterValidationError(
                    "parameter model differs from the frozen source commit"
                )
            validate_stage_parameters(root, source, spec)
            implementation = spec.implementation
            implementation_path = root / implementation.path
            implementation_raw = implementation_path.read_bytes()
            try:
                committed_implementation_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{implementation.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise StageDefinitionError(
                    "stage implementation is absent from the frozen source commit"
                ) from exc
            if implementation_raw != committed_implementation_raw:
                raise StageDefinitionError(
                    "stage implementation differs from the frozen source commit"
                )
            validate_stage_definition(root, spec)
        if isinstance(spec, DownloadSpec):
            for request in spec.inputs.values():
                validate_request_policy(request, spec.policy)
            resolve_http(root, spec.http)
            if isinstance(spec.http, ProjectHttpImplementationSpec):
                for reference in (
                    spec.http.implementation,
                    spec.http.parameter_model,
                ):
                    local_raw = (root / reference.path).read_bytes()
                    committed_raw = subprocess.run(
                        (
                            "git",
                            "-C",
                            str(root),
                            "show",
                            f"{draft.source.commit}:{reference.path}",
                        ),
                        check=True,
                        capture_output=True,
                    ).stdout
                    if local_raw != committed_raw:
                        raise ValueError(
                            "HTTP implementation source differs from the frozen commit"
                        )
        for artifact in spec.artifacts.values():
            loader = artifact.loader
            try:
                local_loader_raw = (root / loader.path).read_bytes()
                committed_loader_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{loader.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (OSError, subprocess.CalledProcessError) as exc:
                raise ValueError(
                    "artifact loader is absent from the frozen source commit"
                ) from exc
            if len(local_loader_raw) != loader.bytes:
                raise ValueError("artifact loader byte count differs")
            if hashlib.sha256(local_loader_raw).hexdigest() != loader.sha256:
                raise ValueError("artifact loader SHA-256 differs")
            if local_loader_raw != committed_loader_raw:
                raise ValueError(
                    "artifact loader differs from the frozen source commit"
                )
        raw = serialize_document(spec)
        relative_path = f"{run_root}/stages/{stage.stage_id}/spec.yaml"
        target = _target_path(root, relative_path)
        staged_files.append((target, raw))
        references.append(
            RunStageRef(
                stage_id=stage.stage_id,
                spec=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )

    run = RunSpec(
        run_id=draft.run_id,
        experiment_id=draft.experiment_id,
        variant_id=draft.variant_id,
        replicate_id=draft.replicate_id,
        benchmark_id=draft.benchmark_id,
        seed=draft.seed,
        source=draft.source,
        environment=draft.environment,
        reproducibility=draft.reproducibility,
        stages=tuple(references),
        estimator=draft.estimator,
    )
    run_target = _target_path(root, f"{run_root}/spec.yaml")
    files = (*staged_files, (run_target, serialize_document(run)))

    # Validate every destination before writing any member of the frozen group.
    for target, raw in files:
        if target.exists() and target.read_bytes() != raw:
            raise FileExistsError(f"refusing to replace a different file: {target}")
    for target, raw in files:
        _write_exact_file(target, raw)

    return FrozenPlanFiles(run=run, files=tuple(target for target, _ in files))
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/experiments.py:VariantStageParams -->
```python contract-target
VariantStageParams = Annotated[
    BuildVariantStageParams
    | EmbedVariantStageParams
    | TrainVariantStageParams
    | EvaluateVariantStageParams,
    Field(discriminator="kind"),
]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:SnapshotFileRef -->
```python contract-target
from .references import SnapshotFileRef
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpImplementationRef -->
```python contract-target
class HttpImplementationRef(ProtocolModel):
    """Identify one project-owned HTTP callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:ExternalExecutableSpec -->
```python contract-target
class ExternalExecutableSpec(ProtocolModel):
    """Freeze the exact executable selected by one project HTTP implementation."""

    executable_id: HumanId
    command: NonEmptyStr
    sha256: SHA256
    bytes: int = Field(gt=0)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:BuiltinHttpImplementationSpec -->
```python contract-target
class BuiltinHttpImplementationSpec(ProtocolModel):
    """Select the built-in HTTPX implementation."""

    kind: Literal["builtin"] = "builtin"
    id: Literal["httpx"] = "httpx"
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:ProjectHttpImplementationSpec -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpImplementationSpec -->
```python contract-target
HttpImplementationSpec = Annotated[
    BuiltinHttpImplementationSpec | ProjectHttpImplementationSpec,
    Field(discriminator="kind"),
]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:ResolvedHttpImplementation -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:ResolvedHttpRetrieval -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpParamsT -->
```python contract-target
HttpParamsT = TypeVar("HttpParamsT", bound=parameters.Http)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:DecoratedHttp -->
```python contract-target
DecoratedHttp = TypeVar("DecoratedHttp", bound=Callable[..., object])
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:HttpRetrievalError -->
```python contract-target
class HttpRetrievalError(RuntimeError):
    """Report one rejected request, HTTP implementation, response, or body."""
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:RuntimeHttpCredential -->
```python contract-target
@dataclass(frozen=True)
class RuntimeHttpCredential:
    """Carry one resolved secret only for the active HTTP invocation."""

    header: HttpHeaderName
    prefix: str
    value: str
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpContext -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpResult -->
```python contract-target
@dataclass(frozen=True)
class HttpResult:
    """Return one completed response body and its terminal HTTP response."""

    body: Path
    response: ObservedHttpResponse
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpDefinition -->
```python contract-target
@dataclass(frozen=True)
class HttpDefinition(Generic[HttpParamsT]):
    """Store authoring metadata attached to one project HTTP callable."""

    id: HumanId
    parameter_model: type[HttpParamsT]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:HttpCallable -->
```python contract-target
class HttpCallable(Protocol[HttpParamsT]):
    """Describe the callable interface shared by project HTTP implementations."""

    def __call__(
        self,
        context: HttpContext[HttpParamsT],
    ) -> HttpResult:
        """Transfer one request into the assigned destination."""
        ...
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:http -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/http.py:_verify_implementation_bytes -->
```python contract-target
def _verify_implementation_bytes(
    reference: HttpImplementationRef,
    raw: bytes,
) -> None:
    """Compare one project HTTP file with its frozen identity."""
    if len(raw) != reference.bytes:
        raise HttpRetrievalError("HTTP implementation byte count differs")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise HttpRetrievalError("HTTP implementation SHA-256 differs")
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:_load_project_http -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:resolve_http -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:_httpx_request -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/http.py:invoke_http -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/inputs.py:HttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/inputs.py:HttpRequestSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/inputs.py:HttpRetrievalPolicy -->
```python contract-target
from viper.http import HttpImplementationSpec, HttpRequestSpec, HttpRetrievalPolicy
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/inputs.py:HttpSource -->
```python contract-target
class HttpSource(ProtocolModel):
    """A network requested file ."""

    kind: Literal["http"] = "http"
    request: HttpRequestSpec
    policy: HttpRetrievalPolicy
    http: HttpImplementationSpec
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/parameters.py:Http -->
```python contract-target
class Http(ParameterSet):
    """Parameters consumed by one project-defined HTTP implementation."""
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/parameters.py:__all__ -->
```python contract-target
__all__ = [
    "Build",
    "Embed",
    "Evaluate",
    "Http",
    "Metric",
    "ParameterModelRef",
    "Train",
]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/preflight.py:HttpRetrievalError -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/preflight.py:ProjectHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/preflight.py:resolve_http -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/preflight.py:validate_request_policy -->
```python contract-target
from .http import (
    HttpRetrievalError,
    ProjectHttpImplementationSpec,
    resolve_http,
    validate_request_policy,
)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/preflight.py:PreflightCheckCode -->
```python contract-target
PreflightCheckCode = Literal[
    "artifact.loader",
    "environment.gce",
    "environment.python",
    "http.credentials",
    "http.request",
    "http.implementation",
    "input.future",
    "metric.implementation",
    "parameter_model.identity",
    "parameter_model.validation",
    "plan.document",
    "plan.git_identity",
    "plan.records",
    "plan.relationships",
    "source.repository",
    "stage.callable",
    "stage.document",
    "stage.identity",
    "stage.implementation",
    "startup.compute",
    "startup.distributed",
]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/preflight.py:preflight_plan -->
```python contract-target
def preflight_plan(repository_root: Path, run_spec_path: Path) -> PreflightReport:
    """Validate plan bytes, host requirements, and same-run dependencies."""
    root = repository_root.resolve()
    checks: list[PreflightCheck] = []
    try:
        run = RunSpec.model_validate(parse_yaml_bytes(run_spec_path.read_bytes()))
    except Exception:
        return PreflightReport(
            run_id=None,
            checks=(
                PreflightCheck(
                    code="plan.document",
                    status="failure",
                    target=run_spec_path.as_posix(),
                    message="run specification failed validation",
                ),
            ),
        )
    checks.append(_check("plan.document", run_spec_path.as_posix(), True, ""))

    def fetch(location: StorageModel) -> bytes:
        """Retrieve source-repository files locally and dispatch other backends."""
        if (
            isinstance(location, GitFileRef)
            and location.repository == run.source.repository
        ):
            return _git_bytes(root, location.commit, location.path)
        return fetch_storage_bytes(location)

    try:
        relative_run_path = run_spec_path.resolve().relative_to(root).as_posix()
        plan_raw = _git_bytes(root, "HEAD", relative_run_path)
        plan_is_frozen = plan_raw == run_spec_path.read_bytes()
    except (OSError, ValueError, subprocess.CalledProcessError):
        plan_is_frozen = False
    checks.append(
        _check(
            "plan.git_identity",
            run_spec_path.as_posix(),
            plan_is_frozen,
            "run specification bytes are absent from the current Git commit",
        )
    )

    try:
        origin = subprocess.run(
            ("git", "-C", str(root), "remote", "get-url", "origin"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        source_repository_matches = origin == str(run.source.repository)
    except (OSError, subprocess.CalledProcessError):
        source_repository_matches = False
    checks.append(
        _check(
            "source.repository",
            str(run.source.repository),
            source_repository_matches,
            "local Git origin differs from RunSpec.source.repository",
        )
    )

    active_python_environment = observe_python_environment()

    loaded: dict[StageId, BaseSpec] = {}
    prior: set[StageId] = set()
    for reference in run.stages:
        target = root / reference.spec
        raw = target.read_bytes() if target.is_file() else b""
        identity_matches = (
            target.is_file()
            and len(raw) == reference.bytes
            and hashlib.sha256(raw).hexdigest() == reference.sha256
        )
        checks.append(
            _check(
                "stage.identity",
                reference.stage_id,
                identity_matches,
                "stage specification bytes differ from RunStageRef",
            )
        )
        if not identity_matches:
            continue
        try:
            stage = load_stage_spec(target)
        except Exception:
            checks.append(
                PreflightCheck(
                    code="stage.document",
                    status="failure",
                    target=reference.stage_id,
                    message="stage specification failed validation",
                )
            )
            continue
        checks.append(_check("stage.document", reference.stage_id, True, ""))
        loaded[reference.stage_id] = stage

        if isinstance(stage, ParameterizedSpec):
            implementation_path = root / stage.implementation.path
            try:
                implementation_raw = implementation_path.read_bytes()
                verify_stage_implementation_bytes(
                    stage.implementation,
                    implementation_raw,
                )
                implementation_exists = (
                    implementation_path.is_file()
                    and implementation_raw
                    == _git_bytes(root, run.source.commit, stage.implementation.path)
                )
            except (OSError, subprocess.CalledProcessError, StageDefinitionError):
                implementation_exists = False
            checks.append(
                _check(
                    "stage.implementation",
                    reference.stage_id,
                    implementation_exists,
                    "stage implementation differs from the frozen source commit",
                )
            )
            callable_valid = False
            if implementation_exists:
                try:
                    validate_stage_definition(root, stage)
                    callable_valid = True
                except (OSError, StageDefinitionError):
                    pass
            checks.append(
                _check(
                    "stage.callable",
                    reference.stage_id,
                    callable_valid,
                    "stage callable decorator differs from the frozen stage contract",
                )
            )
        effective_environment = stage.environment or run.environment
        checks.append(
            _check(
                "environment.python",
                reference.stage_id,
                active_python_environment == effective_environment.python_environment,
                "installed Python environment differs from the frozen plan",
            )
        )
        if isinstance(effective_environment, GCEEnvironmentSpec):
            try:
                observed_gce = observe_gce_execution(effective_environment.compute)
                observed_host = observed_gce.host
                gce_matches = (
                    isinstance(observed_host, GCEHostContext)
                    and observed_host.provisioning == effective_environment.provisioning
                    and observed_host.machine_type == effective_environment.machine_type
                )
            except (OSError, RuntimeError):
                gce_matches = False
            checks.append(
                _check(
                    "environment.gce",
                    reference.stage_id,
                    gce_matches,
                    "active GCE host differs from the frozen environment",
                )
            )
        checks.append(
            _check(
                "startup.distributed",
                reference.stage_id,
                not (
                    effective_environment.compute.kind == "cuda"
                    and effective_environment.compute.count > 1
                ),
                "VIPER 0.1 supports one CUDA device per stage",
            )
        )
        compute_available = True
        if (
            effective_environment.compute.kind == "cuda"
            and effective_environment.compute.count == 1
        ):
            try:
                select_cuda_device(effective_environment.compute.model)
            except RuntimeError:
                compute_available = False
        checks.append(
            _check(
                "startup.compute",
                reference.stage_id,
                compute_available,
                "requested CUDA device model is unavailable on this host",
            )
        )
        loaders_exist = True
        for artifact in stage.artifacts.values():
            loader = artifact.loader
            loader_path = root / loader.path
            try:
                loader_raw = loader_path.read_bytes()
                if (
                    not loader_path.is_file()
                    or len(loader_raw) != loader.bytes
                    or hashlib.sha256(loader_raw).hexdigest() != loader.sha256
                    or loader_raw != _git_bytes(root, run.source.commit, loader.path)
                ):
                    loaders_exist = False
            except (OSError, subprocess.CalledProcessError):
                loaders_exist = False
        checks.append(
            _check(
                "artifact.loader",
                reference.stage_id,
                loaders_exist,
                "one or more artifact loaders are absent from the source tree",
            )
        )

        if isinstance(stage, ParameterizedSpec):
            parameter_identity_valid = False
            parameter_validation_valid = False
            parameter_reference = stage.parameter_model
            model_path = root / parameter_reference.path
            try:
                local_raw = model_path.read_bytes()
                verify_parameter_model_bytes(parameter_reference, local_raw)
                parameter_identity_valid = local_raw == _git_bytes(
                    root,
                    run.source.commit,
                    parameter_reference.path,
                )
            except (
                OSError,
                subprocess.CalledProcessError,
                ParameterValidationError,
            ):
                parameter_identity_valid = False
            if parameter_identity_valid:
                try:
                    validate_stage_parameters(root, target, stage)
                    parameter_validation_valid = True
                except (ParameterValidationError, OSError):
                    parameter_validation_valid = False
            checks.append(
                _check(
                    "parameter_model.identity",
                    reference.stage_id,
                    parameter_identity_valid,
                    "parameter model differs from its frozen source identity",
                )
            )
            checks.append(
                _check(
                    "parameter_model.validation",
                    reference.stage_id,
                    parameter_validation_valid,
                    "stage parameters failed their project parameter model",
                )
            )

        if isinstance(stage, DownloadSpec):
            request_policy_valid = True
            credentials_available = True
            for request in stage.inputs.values():
                try:
                    validate_request_policy(request, stage.policy)
                except HttpRetrievalError:
                    request_policy_valid = False
                if request.credentials is not None and not os.environ.get(
                    request.credentials.variable
                ):
                    credentials_available = False
            checks.append(
                _check(
                    "http.request",
                    reference.stage_id,
                    request_policy_valid,
                    "one or more frozen HTTP requests violate stage policy",
                )
            )
            checks.append(
                _check(
                    "http.credentials",
                    reference.stage_id,
                    credentials_available,
                    "one or more required HTTP credentials are unavailable",
                )
            )
            implementation_valid = True
            try:
                resolve_http(root, stage.http)
                if isinstance(stage.http, ProjectHttpImplementationSpec):
                    implementation_valid = (
                        root / stage.http.implementation.path
                    ).read_bytes() == _git_bytes(
                        root,
                        run.source.commit,
                        stage.http.implementation.path,
                    ) and (
                        root / stage.http.parameter_model.path
                    ).read_bytes() == _git_bytes(
                        root,
                        run.source.commit,
                        stage.http.parameter_model.path,
                    )
            except (
                HttpRetrievalError,
                OSError,
                subprocess.CalledProcessError,
            ):
                implementation_valid = False
            checks.append(
                _check(
                    "http.implementation",
                    reference.stage_id,
                    implementation_valid,
                    "selected HTTP implementation failed source or executable checks",
                )
            )

        valid_future_inputs = True
        if isinstance(stage, InternalSpec):
            for input_ref in stage.inputs.values():
                if not isinstance(input_ref, FutureInputRef):
                    continue
                producer = loaded.get(input_ref.producer_stage_id)
                if (
                    input_ref.producer_stage_id not in prior
                    or producer is None
                    or input_ref.producer_artifact not in producer.artifacts
                ):
                    valid_future_inputs = False
        checks.append(
            _check(
                "input.future",
                reference.stage_id,
                valid_future_inputs,
                "future input lacks an earlier declared producer artifact",
            )
        )
        prior.add(reference.stage_id)

    experiment = None
    variant = None
    benchmark = None
    try:
        experiment, variant = verify_experiment_and_variant(run, fetcher=fetch)
        benchmark = verify_benchmark_spec(run, fetcher=fetch)
        plan_records_valid = True
    except (VerificationError, OSError, subprocess.CalledProcessError):
        plan_records_valid = False
    checks.append(
        _check(
            "plan.records",
            str(run.run_id),
            plan_records_valid,
            "experiment, variant, or benchmark records failed verification",
        )
    )

    relationships_valid = False
    if (
        plan_records_valid
        and experiment is not None
        and variant is not None
        and len(loaded) == len(run.stages)
    ):
        try:
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                benchmark,
                loaded,
            )
            relationships_valid = True
        except VerificationError:
            pass
    checks.append(
        _check(
            "plan.relationships",
            str(run.run_id),
            relationships_valid,
            "run, experiment, variant, benchmark, and stage relationships conflict",
        )
    )

    implementations_valid = experiment is not None
    if experiment is not None:
        selected_metric_ids = {
            metric_id for stage in loaded.values() for metric_id in stage.metric_ids
        }
        metrics = {metric.metric_id: metric for metric in experiment.metrics}
        for metric_id in selected_metric_ids:
            metric = metrics.get(metric_id)
            if metric is None:
                implementations_valid = False
                continue
            implementation = metric.implementation
            implementation_path = root / implementation.path
            try:
                raw = implementation_path.read_bytes()
                if (
                    not implementation_path.is_file()
                    or len(raw) != implementation.bytes
                    or hashlib.sha256(raw).hexdigest() != implementation.sha256
                    or raw != _git_bytes(root, run.source.commit, implementation.path)
                ):
                    implementations_valid = False
                    continue
                validate_metric_definition(root, metric)
            except (OSError, subprocess.CalledProcessError, MetricError):
                implementations_valid = False
    checks.append(
        _check(
            "metric.implementation",
            str(run.run_id),
            implementations_valid,
            "one or more selected metric implementations differ from frozen source",
        )
    )

    return PreflightReport(run_id=run.run_id, checks=tuple(checks))
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ArtifactSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ResolvedArtifact -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/stages.py:ResolvedSingleFileArtifact -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/stages.py:SingleFileArtifactSpec -->
```python contract-target
from .artifacts import (
    ArtifactSpec,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/stages.py:BuiltinHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/stages.py:HttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:HttpRequestSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:HttpRetrievalPolicy -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ResolvedHttpRetrieval -->
```python contract-target
from .http import (
    BuiltinHttpImplementationSpec,
    HttpImplementationSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
    ResolvedHttpRetrieval,
)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:StageContextBinding -->
```python contract-target
class StageContextBinding(ProtocolModel):
    """Persist the stable values used to construct one live stage context."""

    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    parameter_model: ParameterModelRef
    parameter_digest: SHA256
    inputs: dict[InputName, RepoRelPath]
    artifacts: dict[ArtifactName, RepoRelPath]
    metric_ids: tuple[MetricId, ...]
    numpy_generator_names: tuple[HumanId, ...]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:BaseSpec -->
```python contract-target
class BaseSpec(ProtocolModel):
    """Execution request recorded before a stage runs."""

    kind: str
    schema_version: Literal[1] = 1

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

            for previous_path, previous_name in artifact_roots.items():
                if repo_file_paths_overlap(artifact.path, previous_path):
                    raise ValueError(
                        f"artifact roots for {previous_name!r} and {name!r} "
                        f"overlap: {previous_path} and {artifact.path}"
                    )

            artifact_roots[artifact.path] = name

        return self
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ParameterizedSpec -->
```python contract-target
class ParameterizedSpec(BaseSpec):
    """Request an operation governed by one project-defined parameter model."""

    implementation: StageImplementationRef
    parameter_model: ParameterModelRef

    @model_validator(mode="after")
    def validate_implementation_path(self) -> ParameterizedSpec:
        """Keep the project callable outside every declared artifact root."""
        for name, artifact in self.artifacts.items():
            if repo_file_paths_overlap(artifact.path, self.implementation.path):
                raise ValueError(
                    f"artifact {name!r} path collides with the stage implementation"
                )
        return self
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:DownloadSpec -->
```python contract-target
class DownloadSpec(BaseSpec):
    """Request runner-owned HTTP retrievals into same-named file artifacts."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpImplementationSpec = Field(default_factory=BuiltinHttpImplementationSpec)
    policy: HttpRetrievalPolicy

    @model_validator(mode="after")
    def validate_download_artifacts(self) -> DownloadSpec:
        """Require one same-named single-file artifact for each HTTP request."""
        if set(self.inputs) != set(self.artifacts):
            raise ValueError("download input and artifact names must match")
        if any(
            not isinstance(artifact, SingleFileArtifactSpec)
            for artifact in self.artifacts.values()
        ):
            raise ValueError("download artifacts must be single files")
        return self
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ParameterizedStageSpec -->
```python contract-target
ParameterizedStageSpec = BuildSpec | EmbedSpec | TrainSpec | EvaluateSpec
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:Spec -->
```python contract-target
Spec = Annotated[
    DownloadSpec | ParameterizedStageSpec,
    Field(discriminator="kind"),
]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ResolvedBaseSpec -->
```python contract-target
class ResolvedBaseSpec(ProtocolModel):
    """Record an execution and the exact output files it produced."""

    schema_version: Literal[1] = 1
    kind: str

    spec: BaseSpec
    environment: ResolvedEnvironment
    execution_context: ExecutionContext
    artifacts: dict[ArtifactName, ResolvedArtifact] = Field(min_length=1)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_common_invariants(self) -> ResolvedBaseSpec:
        """Match realized source, artifacts, environment, and context to the request."""
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ResolvedDownloadSpec -->
```python contract-target
class ResolvedDownloadSpec(ResolvedBaseSpec):
    """Bind every frozen HTTP input to its completed retrieval evidence."""

    kind: Literal["download"] = "download"  # pyright: ignore[reportIncompatibleVariableOverride]
    spec: DownloadSpec  # pyright: ignore[reportIncompatibleVariableOverride]

    retrievals: dict[InputName, ResolvedHttpRetrieval]

    @model_validator(mode="after")
    def validate_download_retrievals(self) -> ResolvedDownloadSpec:
        """Match each retrieval to its request, HTTP implementation, and timing."""
        if set(self.retrievals) != set(self.spec.inputs):
            raise ValueError("resolved retrieval names must match download inputs")
        if set(self.artifacts) != set(self.retrievals):
            raise ValueError("resolved download artifacts must match retrievals")
        for input_name, retrieval in self.retrievals.items():
            if retrieval.input_name != input_name:
                raise ValueError("resolved retrieval input name differs from its key")
            if retrieval.request != self.spec.inputs[input_name]:
                raise ValueError(
                    "resolved retrieval request differs from download input"
                )
            if retrieval.http.spec != self.spec.http:
                raise ValueError("resolved HTTP implementation differs from stage spec")
            artifact = self.artifacts[input_name]
            if not isinstance(artifact, ResolvedSingleFileArtifact):
                raise ValueError("resolved download artifacts must be single files")
            if retrieval.body != artifact.file:
                raise ValueError("retrieval body must equal its resolved artifact file")
            if retrieval.completed_at > self.completed_at:
                raise ValueError("download retrieval cannot follow stage completion")
        return self
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=src/viper/stages.py:ResolvedParameterizedSpec -->
```python contract-target
class ResolvedParameterizedSpec(ResolvedBaseSpec):
    """Record evidence produced by one project-owned stage process."""

    spec: ParameterizedSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    source: ResolvedGitFileRef
    startup: ProcessStartupReceipt
    invocation: ResolvedStageInvocationRef
    command: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_project_invocation(self) -> ResolvedParameterizedSpec:
        """Match the resolved source to the selected project callable."""
        if self.source.stored_at.path != self.spec.implementation.path:
            raise ValueError(
                "resolved source entrypoint must match the stage implementation path"
            )
        return self
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=src/viper/stages.py:ResolvedInternalSpec -->
```python contract-target
class ResolvedInternalSpec(ResolvedParameterizedSpec):
    """Record an operation that consumes previously produced artifacts."""

    spec: InternalSpec  # pyright: ignore[reportIncompatibleVariableOverride]
    inputs: dict[InputName, ResolvedInputRef]

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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:BuiltinHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:EnvironmentSecretRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:ExternalExecutableSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:HttpImplementationRef -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:HttpRequestSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:HttpRetrievalError -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:HttpRetrievalPolicy -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:ObservedHttpResponse -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:ProjectHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:ResolvedHttpImplementation -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:ResolvedHttpRetrieval -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:invoke_http -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:resolve_http -->
```python contract-target
from viper.http import (
    BuiltinHttpImplementationSpec,
    EnvironmentSecretRef,
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:SnapshotFileRef -->
```python contract-target
from viper.references import SnapshotFileRef
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:_policy -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:TransportFactory -->
```python contract-target
TransportFactory = Callable[[Path], ResolvedHttpImplementation]
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:conforming_http -->
```python contract-target
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
                    path="project/transport_params.py",
                    symbol="ConformingTransportParameters",
                    sha256=hashlib.sha256(parameter_raw).hexdigest(),
                    bytes=len(parameter_raw),
                ),
                params=parameters.Http(),
            ),
        )

    return create
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:_invoke_conforming_http -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_http_conformance_accepts_exact_response_body -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_http_conformance_rejects_response_contract_violations -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_http_conformance_rejects_destination_escape -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_http_retrieval.py:test_resolved_retrieval_requires_the_expected_body_identity -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_httpx_request_follows_policy_and_strips_cross_origin_secret -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_project_http_receives_typed_parameters_and_exact_destination -->
```python contract-target
def test_project_http_receives_typed_parameters_and_exact_destination(
    tmp_path: Path,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Load one decorated project HTTP callable and verify its completed body."""
    host, port, _ = local_http_server
    body = b"verified response"
    parameter_raw = (
        b"from pydantic import Field\n"
        b"from viper import parameters\n\n"
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
        b"parameter_model=ProjectTransportParameters)\n"
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_http_rejects_unaccepted_status -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_http_rejects_policy_secret_and_same_length_body_failures -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_http_retrieval.py:test_project_http_rejects_returned_path_escape -->
```python contract-target
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
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:artifact_loader_ref -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_preflight.py:builtin_http -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:http_policy -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:http_request -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:parameter_model_ref -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:stage_implementation_ref -->
```python contract-target
from tests.fixtures import (
    artifact_loader_ref,
    builtin_http,
    http_policy,
    http_request,
    parameter_model_ref,
    stage_implementation_ref,
)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_preflight.py:test_future_input_uses_canonical_producer_path -->
```python contract-target
def test_future_input_uses_canonical_producer_path(tmp_path: Path) -> None:
    """Resolve one consumer input to the materialized producer artifact."""
    producer = DownloadSpec(
        inputs={"dataset": http_request(url="https://example.com/data")},
        http=builtin_http(),
        policy=http_policy(),
        artifacts={
            "dataset": _artifact(
                "experiments/example/runs/baseline/01JABCDEFGHJKMNPQRSTVWXYZ0/"
                "artifacts/datasets/main/data.bin"
            )
        },
    )
    path = tmp_path / producer.artifacts["dataset"].path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"dataset")
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_protocol.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_protocol.py:EvaluateSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_protocol.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_protocol.py:TrainSpec -->
```python contract-target
from viper.stages import (
    DownloadSpec,
    EvaluateSpec,
    ParameterizedSpec,
    TrainSpec,
)
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=add target=tests/test_protocol.py:test_download_models_use_runner_owned_hierarchy -->
```python contract-target
def test_download_models_use_runner_owned_hierarchy() -> None:
    """Keep download requests outside the project-callable stage hierarchy."""
    stage = load_stage_spec(
        Path(__file__).parents[1] / "tests" / "data" / "download_stage.yaml"
    )

    assert isinstance(stage, DownloadSpec)
    assert not isinstance(stage, ParameterizedSpec)
    assert "implementation" not in type(stage).model_fields
    assert "parameter_model" not in type(stage).model_fields
    assert "params" not in type(stage).model_fields
    assert set(stage.inputs) == set(stage.artifacts)
    assert stage.http.kind == "builtin"
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_public_api.py:test_stage_interface_uses_parsimonious_names -->
```python contract-target
def test_stage_interface_uses_parsimonious_names() -> None:
    """Let the stage module supply the category once at each use site."""
    assert stages.Context.__module__ == "viper.stages"
    assert tuple(
        operation.__name__ for operation in (stages.build, stages.embed, stages.train)
    ) == ("build", "embed", "train")
    assert stages.eval.__name__ == "eval"
```

<!-- contract-target: requirements=DRA-01 block=P2-DRA-01 action=update target=tests/test_public_api.py:test_parameter_categories_form_the_public_extension_namespace -->
```python contract-target
def test_parameter_categories_form_the_public_extension_namespace() -> None:
    """Expose one parameter category for each supported extension role."""
    parameters = importlib.import_module("viper.parameters")
    assert tuple(parameters.__all__) == (
        "Build",
        "Embed",
        "Evaluate",
        "Http",
        "Metric",
        "ParameterModelRef",
        "Train",
    )
    assert issubclass(parameters.Train, parameters.ParameterSet)
```

<!-- pair-block-definition: P2-DRA-02 -->
```toml pair-block
id = "P2-DRA-02"
requirements = ["DRA-02", "DRA-03"]
targets = [
    "src/viper/api.py:execute_stage",
    "src/viper/execution/_attempt.py:BaseSpec",
    "src/viper/execution/_attempt.py:DownloadSpec",
    "src/viper/execution/_attempt.py:InternalSpec",
    "src/viper/execution/_attempt.py:ParameterizedSpec",
    "src/viper/execution/_attempt.py:execute_attempt",
    "src/viper/execution/_attempt.py:resolve_download_stage",
    "src/viper/execution/_attempt.py:resolve_environment",
    "src/viper/execution/_attempt.py:resolve_runner_environment",
    "src/viper/execution/_attempt.py:resolve_stage",
    "src/viper/execution/_downloads.py:Path",
    "src/viper/execution/_downloads.py:RepoRelPath",
    "src/viper/execution/_downloads.py:RunError",
    "src/viper/execution/_downloads.py:SHA256",
    "src/viper/execution/_downloads.py:SnapshotFileRef",
    "src/viper/execution/_downloads.py:annotations",
    "src/viper/execution/_downloads.py:hashlib",
    "src/viper/execution/_downloads.py:os",
    "src/viper/execution/_downloads.py:publish_download_body",
    "src/viper/execution/_downloads.py:tempfile",
    "src/viper/execution/_materialization.py:ArtifactPointer",
    "src/viper/execution/_materialization.py:HttpRequestSpec",
    "src/viper/execution/_materialization.py:HttpResult",
    "src/viper/execution/_materialization.py:HttpRetrievalError",
    "src/viper/execution/_materialization.py:HttpRetrievalPolicy",
    "src/viper/execution/_materialization.py:HttpTransportResult",
    "src/viper/execution/_materialization.py:ResolvedArtifact",
    "src/viper/execution/_materialization.py:ResolvedHttpImplementation",
    "src/viper/execution/_materialization.py:ResolvedHttpRetrieval",
    "src/viper/execution/_materialization.py:ResolvedHttpTransport",
    "src/viper/execution/_materialization.py:ResolvedSingleFileArtifact",
    "src/viper/execution/_materialization.py:RunSpec",
    "src/viper/execution/_materialization.py:SingleFileArtifactSpec",
    "src/viper/execution/_materialization.py:_http_helper",
    "src/viper/execution/_materialization.py:_http_transport_helper",
    "src/viper/execution/_materialization.py:invoke_http",
    "src/viper/execution/_materialization.py:invoke_transport",
    "src/viper/execution/_materialization.py:publish_download_body",
    "src/viper/execution/_materialization.py:resolve_http",
    "src/viper/execution/_materialization.py:resolve_inputs",
    "src/viper/execution/_materialization.py:resolve_transport",
    "src/viper/execution/_materialization.py:retrieval_body_path",
    "src/viper/execution/_materialization.py:retrieve_download_inputs",
    "src/viper/execution/_resolution.py:BaseSpec",
    "src/viper/execution/_resolution.py:DownloadSpec",
    "src/viper/execution/_resolution.py:EnvironmentSpec",
    "src/viper/execution/_resolution.py:ExecutionContext",
    "src/viper/execution/_resolution.py:GCEEnvironmentSpec",
    "src/viper/execution/_resolution.py:GCEHostContext",
    "src/viper/execution/_resolution.py:ParameterizedSpec",
    "src/viper/execution/_resolution.py:ResolvedArtifact",
    "src/viper/execution/_resolution.py:ResolvedBuildSpec",
    "src/viper/execution/_resolution.py:ResolvedDownloadSpec",
    "src/viper/execution/_resolution.py:ResolvedEmbedSpec",
    "src/viper/execution/_resolution.py:ResolvedEvaluateSpec",
    "src/viper/execution/_resolution.py:ResolvedGCEEnvironment",
    "src/viper/execution/_resolution.py:ResolvedLocalEnvironment",
    "src/viper/execution/_resolution.py:ResolvedSpec",
    "src/viper/execution/_resolution.py:ResolvedTrainSpec",
    "src/viper/execution/_resolution.py:observe_execution",
    "src/viper/execution/_resolution.py:observe_python_environment",
    "src/viper/execution/_resolution.py:resolve_download_stage",
    "src/viper/execution/_resolution.py:resolve_runner_environment",
    "src/viper/execution/_resolution.py:resolve_stage",
    "src/viper/execution/_stage.py:BaseSpec",
    "src/viper/execution/_stage.py:HttpRetrievalContextBinding",
    "src/viper/execution/_stage.py:ParameterizedSpec",
    "src/viper/execution/_stage.py:ParameterizedStageSpec",
    "src/viper/execution/_stage.py:ResolvedHttpRetrieval",
    "src/viper/execution/_stage.py:StageContextBinding",
    "src/viper/execution/_stage.py:StageInvocationReceipt",
    "src/viper/execution/_stage.py:execute_stage_process",
    "src/viper/paths.py:InputName",
    "src/viper/paths.py:RepoRelPath",
    "src/viper/paths.py:RunSpec",
    "src/viper/paths.py:StageId",
    "src/viper/paths.py:annotations",
    "src/viper/paths.py:cast",
    "src/viper/paths.py:retrieval_body_path",
    "tests/test_execution_acceptance.py:DownloadSpec",
    "tests/test_execution_acceptance.py:LocalArtifactStore",
    "tests/test_execution_acceptance.py:ObservedHttpResponse",
    "tests/test_execution_acceptance.py:ParameterModelRef",
    "tests/test_execution_acceptance.py:RUN_ID",
    "tests/test_execution_acceptance.py:RUN_ROOT",
    "tests/test_execution_acceptance.py:ResolvedHttpRetrieval",
    "tests/test_execution_acceptance.py:ResolvedHttpTransport",
    "tests/test_execution_acceptance.py:ResolvedSingleFileArtifact",
    "tests/test_execution_acceptance.py:RunError",
    "tests/test_execution_acceptance.py:RunSpec",
    "tests/test_execution_acceptance.py:RunStageRef",
    "tests/test_execution_acceptance.py:SingleFileArtifactSpec",
    "tests/test_execution_acceptance.py:StageExecutionAcceptanceTests",
    "tests/test_execution_acceptance.py:StageImplementationRef",
    "tests/test_execution_acceptance.py:TemporaryDirectory",
    "tests/test_execution_acceptance.py:UTC",
    "tests/test_execution_acceptance.py:annotations",
    "tests/test_execution_acceptance.py:artifact_loader_ref",
    "tests/test_execution_acceptance.py:builtin_http_transport",
    "tests/test_execution_acceptance.py:datetime",
    "tests/test_execution_acceptance.py:execute_stage_process",
    "tests/test_execution_acceptance.py:http_policy",
    "tests/test_execution_acceptance.py:http_request",
    "tests/test_execution_acceptance.py:parameters",
    "tests/test_execution_acceptance.py:publish_download_body",
    "tests/test_execution_acceptance.py:pytest",
    "tests/test_execution_acceptance.py:python_environment",
    "tests/test_execution_acceptance.py:retrieval_body_path",
    "tests/test_execution_acceptance.py:serialize_document",
    "tests/test_execution_acceptance.py:test_download_body_becomes_declared_artifact",
    "tests/test_execution_acceptance.py:test_download_body_mutation_prevents_artifact_publication",
    "tests/test_execution_acceptance.py:timedelta",
    "tests/test_execution_acceptance.py:unittest",
    "tests/test_execution_signals.py:DownloadSpec",
    "tests/test_execution_signals.py:DownloadVariantStageParams",
    "tests/test_execution_signals.py:ExperimentSpec",
    "tests/test_execution_signals.py:ReplicateSpec",
    "tests/test_execution_signals.py:ResolvedTrainSpec",
    "tests/test_execution_signals.py:StageImplementationRef",
    "tests/test_execution_signals.py:StageInvocationReceipt",
    "tests/test_execution_signals.py:TrainSpec",
    "tests/test_execution_signals.py:TrainVariantStageParams",
    "tests/test_execution_signals.py:VariantSpec",
    "tests/test_execution_signals.py:_freeze_signal_plan",
    "tests/test_execution_signals.py:_write_source_files",
    "tests/test_execution_signals.py:builtin_http",
    "tests/test_execution_signals.py:builtin_http_transport",
    "tests/test_execution_signals.py:http_policy",
    "tests/test_execution_signals.py:http_request",
    "tests/test_execution_signals.py:python_environment",
    "tests/test_execution_signals.py:reproducibility",
    "tests/test_execution_signals.py:resume_state",
    "tests/test_execution_signals.py:test_live_l4_stage_records_requested_backend",
    "tests/test_execution_signals.py:test_signal_closes_attempt_with_active_stage_evidence",
    "tests/test_run_execution.py:DownloadVariantStageParams",
    "tests/test_run_execution.py:ExperimentSpec",
    "tests/test_run_execution.py:ReplicateSpec",
    "tests/test_run_execution.py:TrainVariantStageParams",
    "tests/test_run_execution.py:VariantSpec",
    "tests/test_run_execution.py:builtin_http",
    "tests/test_run_execution.py:builtin_http_transport",
    "tests/test_run_execution.py:http_policy",
    "tests/test_run_execution.py:http_request",
    "tests/test_run_execution.py:python_environment",
    "tests/test_run_execution.py:reproducibility",
    "tests/test_run_execution.py:resume_state",
    "tests/test_run_execution.py:test_two_stage_local_run_writes_and_verifies_terminal_result",
]
assets = []
tests = [
    "tests/test_run_execution.py:test_two_stage_local_run_writes_and_verifies_terminal_result",
    "tests/test_execution_acceptance.py:test_download_execution_publishes_receipt_and_artifact_as_one_file",
]
gate = "python -m pytest tests/test_run_execution.py tests/test_execution_acceptance.py tests/test_execution_signals.py -q"
depends_on = ["P2-DRA-01"]
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:HttpTransportResult -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:ResolvedHttpTransport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:RunSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:_http_transport_helper -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:invoke_transport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:resolve_transport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_materialization.py:retrieval_body_path -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_resolution.py:BaseSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_stage.py:BaseSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_stage.py:HttpRetrievalContextBinding -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/execution/_stage.py:ResolvedHttpRetrieval -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:InputName -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:RepoRelPath -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:RunSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:StageId -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:annotations -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:cast -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=src/viper/paths.py:retrieval_body_path -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:LocalArtifactStore -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:ObservedHttpResponse -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:ParameterModelRef -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:RUN_ID -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:RUN_ROOT -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:ResolvedHttpRetrieval -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:ResolvedHttpTransport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:ResolvedSingleFileArtifact -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:RunSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:RunStageRef -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:SingleFileArtifactSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:StageExecutionAcceptanceTests -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:StageImplementationRef -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:TemporaryDirectory -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:UTC -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:artifact_loader_ref -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:builtin_http_transport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:datetime -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:execute_stage_process -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:http_policy -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:http_request -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:parameters -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:python_environment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:retrieval_body_path -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:serialize_document -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:timedelta -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_acceptance.py:unittest -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_signals.py:DownloadVariantStageParams -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_execution_signals.py:builtin_http_transport -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_run_execution.py:DownloadVariantStageParams -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=remove target=tests/test_run_execution.py:builtin_http_transport -->
<!-- contract-remove -->

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/api.py:execute_stage -->
```python contract-target
def execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess:
    """Execute one selected stage and identify its declared outputs."""
    project_root = _root(request.root, "execute_stage")
    try:
        run = _load_model(request.run_spec, RunSpec)
        assert isinstance(run, RunSpec)
        reference = next(
            (stage for stage in run.stages if stage.stage_id == request.stage_id),
            None,
        )
        if reference is None:
            raise ValueError("selected stage is absent from the run plan")
        stage = load_stage_spec(project_root / reference.spec)
        if not isinstance(stage, ParameterizedSpec):
            raise ValueError("runner-owned download stages require execute_attempt")
        result = execute_stage_process(
            project_root,
            run,
            reference,
            stage,
            timeout_seconds=request.timeout_seconds,
        )
    except StageExecutionError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_stage",
                origin="application",
                code="execution_failed",
                message="stage process failed",
                details={"stage_id": request.stage_id},
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("execute_stage", request.run_spec, exc) from exc
    return ExecuteStageSuccess(
        stage_id=request.stage_id,
        command=result.command,
        artifacts=result.artifacts,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:BaseSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:InternalSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_attempt.py:ParameterizedSpec -->
```python contract-target
from ..stages import (
    BaseSpec,
    DownloadSpec,
    InternalSpec,
    ParameterizedSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_attempt.py:resolve_download_stage -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:resolve_environment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_attempt.py:resolve_runner_environment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:resolve_stage -->
```python contract-target
from ._resolution import (
    resolve_download_stage,
    resolve_environment,
    resolve_runner_environment,
    resolve_stage,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_attempt.py:execute_attempt -->
```python contract-target
def execute_attempt(
    repository_root: Path,
    run_spec_path: Path,
    *,
    timeout_seconds: float | None = None,
    retry: bool = False,
    purpose: AttemptPurpose = "run",
) -> RunResult | ConfirmationRunResult:
    """Execute one ordinary or benchmark-confirmation attempt."""
    root = repository_root.resolve()
    run_path = run_spec_path.resolve()
    run_raw = run_path.read_bytes()
    run = RunSpec.model_validate(parse_yaml_bytes(run_raw))
    origin = run_git(root, "remote", "get-url", "origin").decode().strip()
    if origin != str(run.source.repository):
        raise RunError("Git origin differs from RunSpec.source.repository")
    plan_commit = run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
    relative_run_path = run_path.relative_to(root).as_posix()
    if run_git(root, "show", f"{plan_commit}:{relative_run_path}") != run_raw:
        raise RunError("RunSpec bytes are absent from the current Git commit")

    store = LocalArtifactStore(root)
    destination = bind_run_destination(
        root,
        run.run_id,
        load_storage_settings(root).destination,
    )
    snapshot_publisher = create_snapshot_publisher(root, destination)
    fetcher = RunFetcher(root, store, str(run.source.repository))
    policy = VerificationPolicy(
        trusted_source_repositories=frozenset({str(run.source.repository)})
    )
    experiment = ExperimentSpec.model_validate(
        parse_yaml_bytes(
            fetcher(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=f"experiments/{run.experiment_id}/spec.yaml",
                )
            )
        )
    )
    run_root = f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"

    workspace_root = root / ".viper" / "workspaces"
    run_lock = RunWorkspaceLock.for_run(workspace_root, run.run_id)
    run_lock.acquire()
    terminal_path = run_path.parent / "resolved.yaml"
    previous_run: ResolvedRun | None = None
    if terminal_path.is_file():
        previous_run = ResolvedRun.model_validate(
            parse_yaml_bytes(terminal_path.read_bytes())
        )
        if purpose == "run" and not retry:
            run_lock.release()
            raise RunError("run already has terminal attempt history; use retry")
        if purpose == "run" and previous_run.status == "succeeded":
            run_lock.release()
            raise RunError("a successful run cannot be retried")
    elif purpose == "benchmark_confirmation":
        run_lock.release()
        raise RunError("benchmark confirmation requires a terminal candidate run")
    if purpose == "benchmark_confirmation" and previous_run is not None:
        if previous_run.status != "succeeded":
            run_lock.release()
            raise RunError("benchmark confirmation requires a successful candidate run")
    known_attempts = (
        ()
        if previous_run is None
        else tuple(
            read_attempt_reference(reference, run, fetcher=fetcher)
            for reference in previous_run.attempts
        )
    )
    previous_attempts = reconcile_abandoned_attempts(
        root,
        workspace_root,
        run,
        run_root,
        destination,
        known_attempts,
    )
    attempt_id = max(
        next_attempt_id(workspace_root, run.run_id),
        max((attempt.attempt_id for attempt in previous_attempts), default=0) + 1,
    )
    workspace = AttemptWorkspace.create(workspace_root, run.run_id, attempt_id)
    journal = DurableJournal(workspace.control / "journal.jsonl")
    attempt_started = datetime.now(UTC)
    resolved_stage_refs: list[ResolvedStageRef] = []
    invocation_refs: list[ResolvedStageInvocationRef] = []
    completed: dict[StageId, ResolvedStageRef] = {}
    loaded_stages: dict[StageId, BaseSpec] = {}
    measurement_paths: list[Path] = []
    metric_verification_paths: list[Path] = []
    log_files: dict[str, bytes] = {}
    active_stage_id: StageId | None = None
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def cancel_attempt(signum: int, frame: object) -> None:
        """Convert an interrupt request into a durable cancellation outcome."""
        del signum, frame
        raise StageProcessInterrupted("cancelled")

    def preempt_attempt(signum: int, frame: object) -> None:
        """Convert host termination into a durable preemption outcome."""
        del signum, frame
        raise StageProcessInterrupted("preempted")

    signal.signal(signal.SIGINT, cancel_attempt)
    signal.signal(signal.SIGTERM, preempt_attempt)
    try:
        journal.append("allocated", "attempt allocated", recorded_at=attempt_started)
        preflight = preflight_plan(root, run_path)
        preflight_path = workspace.control / "preflight.json"
        write_synchronized(
            preflight_path,
            f"{preflight.model_dump_json()}\n".encode(),
        )
        journal.append(
            "preflighting",
            "preflight completed and frozen plan located in Git",
            recorded_at=datetime.now(UTC),
            details={
                "plan_commit": plan_commit,
                "report": preflight_path.relative_to(workspace.root).as_posix(),
            },
        )
        if not preflight.ready:
            failed_codes = ", ".join(
                check.code for check in preflight.checks if check.status == "failure"
            )
            raise RunError(f"plan preflight failed: {failed_codes}")
        for stage_reference in run.stages:
            active_stage_id = stage_reference.stage_id
            stage = load_stage_spec(root / stage_reference.spec)
            loaded_stages[stage_reference.stage_id] = stage
            effective_environment = stage.environment or run.environment
            resolved_inputs: dict[InputName, ResolvedInputRef] | None = None
            resolved_retrievals: dict[InputName, ResolvedHttpRetrieval] | None = None
            input_paths: dict[str, Path] = {}
            process = None
            journal.append(
                "running_stage",
                "stage execution started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )

            if isinstance(stage, DownloadSpec):
                runner_environment, execution_context = resolve_runner_environment(
                    fetcher,
                    effective_environment,
                )
                (
                    resolved_retrievals,
                    resolved_artifacts,
                    input_paths,
                ) = retrieve_download_inputs(
                    root,
                    workspace,
                    stage_reference.stage_id,
                    stage,
                )
                stage_completed = datetime.now(UTC)
                resolved = resolve_download_stage(
                    stage,
                    environment=runner_environment,
                    execution_context=execution_context,
                    artifacts=resolved_artifacts,
                    retrievals=resolved_retrievals,
                    completed_at=stage_completed,
                )
            else:
                if not isinstance(stage, ParameterizedSpec):
                    raise RunError("project stage lacks its parameterized contract")
                source_location = GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=stage.implementation.path,
                )
                source = resolve_git_file(fetcher, source_location)
                if (root / stage.implementation.path).read_bytes() != fetcher(
                    source_location
                ):
                    raise RunError("stage source differs from the frozen source")
                if isinstance(stage, InternalSpec):
                    resolved_inputs, input_paths = resolve_inputs(
                        root,
                        workspace,
                        stage_reference.stage_id,
                        stage,
                        completed,
                        loaded_stages,
                        fetcher,
                        policy,
                        store,
                    )
                try:
                    process = execute_stage_process(
                        root,
                        run,
                        stage_reference,
                        stage,
                        attempt_id=attempt_id,
                        input_paths=input_paths,
                        timeout_seconds=timeout_seconds,
                    )
                except (StageExecutionError, StageProcessInterrupted) as exc:
                    run_log_root = f"{run_root}/attempts/{attempt_id}/logs"
                    log_files[
                        f"{run_log_root}/{stage_reference.stage_id}.stdout.log"
                    ] = exc.stdout
                    log_files[
                        f"{run_log_root}/{stage_reference.stage_id}.stderr.log"
                    ] = exc.stderr
                    if exc.invocation is not None:
                        invocation_path = (
                            f"{run_root}/attempts/{attempt_id}/invocations/"
                            f"{stage_reference.stage_id}.yaml"
                        )
                        invocation_refs.append(
                            publish_invocation_receipt(
                                root,
                                destination,
                                invocation_path,
                                exc.invocation,
                            )
                        )
                    raise
                invocation_path = (
                    f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                    f"/attempts/{attempt_id}/invocations/{stage_reference.stage_id}.yaml"
                )
                invocation_ref = publish_invocation_receipt(
                    root,
                    destination,
                    invocation_path,
                    process.invocation,
                )
                invocation_refs.append(invocation_ref)
                stage_completed = datetime.now(UTC)
                resolved = resolve_stage(
                    stage,
                    source=source,
                    environment=resolve_environment(
                        fetcher,
                        effective_environment,
                        process,
                    ),
                    process=process,
                    invocation=invocation_ref,
                    inputs=resolved_inputs,
                    completed_at=stage_completed,
                )
                resolved_artifacts = process.artifacts
                metric_specs = {
                    metric.metric_id: metric for metric in experiment.metrics
                }
                for metric_id in stage.metric_ids:
                    if metric_specs[metric_id].mode != "live":
                        continue
                    live_path = (
                        root
                        / (
                            f"experiments/{run.experiment_id}/runs/"
                            f"{run.variant_id}/{run.run_id}"
                        )
                        / f"attempts/{attempt_id}/measurements"
                        / f"{stage_reference.stage_id}.{metric_id}.jsonl"
                    )
                    if live_path.is_file() and live_path not in measurement_paths:
                        measurement_paths.append(live_path)
            resolved_path = (
                f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
                f"/stages/{stage_reference.stage_id}/resolved.yaml"
            )
            resolved_raw = serialize_document(resolved)
            snapshot_paths: dict[str, Path] = {}
            if resolved_retrievals is not None:
                for retrieval in resolved_retrievals.values():
                    retrieval_path = retrieval.body.path
                    snapshot_paths[retrieval_path] = root / retrieval_path
            for artifact in resolved_artifacts.values():
                artifact_references: tuple[SnapshotFileRef, ...]
                if artifact.kind == "file":
                    artifact_references = (artifact.file,)
                else:
                    artifact_references = tuple(
                        member.file for member in artifact.members
                    )
                for reference in artifact_references:
                    snapshot_paths[reference.path] = root / reference.path
            journal.append(
                "publishing_stage",
                "stage snapshot publication started",
                recorded_at=datetime.now(UTC),
                details={"stage_id": stage_reference.stage_id},
            )
            snapshot = snapshot_publisher.publish(
                resolved_stage_path=resolved_path,
                resolved_stage=resolved_raw,
                files=snapshot_paths,
            )
            resolved_stage_ref = ResolvedStageRef(
                stage_id=stage_reference.stage_id,
                snapshot=snapshot,
                resolved_spec=snapshot_file(resolved_path, resolved_raw),
            )
            resolved_stage_refs.append(resolved_stage_ref)
            completed[stage_reference.stage_id] = resolved_stage_ref
            run_after_stage_metrics(
                root,
                run,
                stage_reference.stage_id,
                stage,
                experiment,
                input_paths,
                measurement_paths,
                metric_verification_paths,
                store,
                timeout_seconds,
                attempt_id,
            )
            if process is not None:
                log_files[
                    f"{run_root}/attempts/{attempt_id}/logs/"
                    f"{stage_reference.stage_id}.stdout.log"
                ] = process.stdout
                log_files[
                    f"{run_root}/attempts/{attempt_id}/logs/"
                    f"{stage_reference.stage_id}.stderr.log"
                ] = process.stderr
            active_stage_id = None

        journal.append(
            "closing_attempt",
            "all planned stages completed",
            recorded_at=datetime.now(UTC),
        )
        journal.append(
            "publishing_attempt_files",
            "attempt evidence publication started",
            recorded_at=datetime.now(UTC),
            details={},
        )
        journal.append(
            "terminal",
            "attempt succeeded",
            recorded_at=datetime.now(UTC),
        )
        (
            journal_reference,
            measurement_references,
            metric_verification_references,
            log_references,
        ) = publish_attempt_files(
            root,
            destination,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
        )
        attempt_completed = datetime.now(UTC)
        attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose=purpose,
            status="succeeded",
            started_at=attempt_started,
            completed_at=attempt_completed,
            resolved_stages=tuple(resolved_stage_refs),
            invocations=tuple(invocation_refs),
            journal=journal_reference,
            measurement_files=measurement_references,
            metric_verification_files=metric_verification_references,
            log_files=log_references,
            failure=None,
        )
        run_reference = GitFileRef(
            repository=run.source.repository,
            commit=plan_commit,
            path=relative_run_path,
        )
        attempt_reference = write_attempt_document(
            root,
            run_root,
            attempt,
            destination,
        )
        if purpose == "benchmark_confirmation":
            return ConfirmationRunResult(
                attempt=attempt,
                attempt_reference=attempt_reference,
                attempt_path=(
                    root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
                ),
                journal_path=journal.path,
            )
        attempt_references = tuple(
            write_attempt_document(root, run_root, value, destination)
            for value in previous_attempts
        ) + (attempt_reference,)
        resolved_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=run_reference,
            ),
            status="succeeded",
            attempts=attempt_references,
            successful_attempt_id=attempt_id,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(resolved_run)
        verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
        replace_synchronized(terminal_path, terminal_raw)
        write_synchronized(workspace.terminal, terminal_raw)
        return RunResult(
            resolved_run=resolved_run,
            resolved_run_path=terminal_path,
            journal_path=journal.path,
        )
    except (Exception, KeyboardInterrupt) as exc:
        failed_at = datetime.now(UTC)
        status: Literal["failed", "cancelled", "preempted"]
        if isinstance(exc, StageProcessInterrupted):
            status = exc.outcome
        elif isinstance(exc, KeyboardInterrupt):
            status = "cancelled"
        else:
            status = "failed"
        latest = journal.latest()
        if latest is not None and latest.state != "terminal":
            journal.append(
                "terminal",
                f"attempt {status}",
                recorded_at=failed_at,
                details={
                    "stage_id": active_stage_id,
                    "exception": type(exc).__name__,
                },
            )
        code = (
            "cancelled"
            if status == "cancelled"
            else "preempted"
            if status == "preempted"
            else "preflight_failed"
            if isinstance(exc, RunError)
            and str(exc).startswith("plan preflight failed")
            else "verification_failed"
            if isinstance(exc, VerificationError)
            else "execution_failed"
            if isinstance(
                exc,
                (StageExecutionError, MetricExecutionError, HttpRetrievalError),
            )
            else "internal_error"
        )
        (
            journal_reference,
            measurement_references,
            metric_verification_references,
            log_references,
        ) = publish_attempt_files(
            root,
            destination,
            run_root,
            attempt_id,
            journal,
            log_files,
            measurement_paths,
            metric_verification_paths,
        )
        completed_at = datetime.now(UTC)
        failed_attempt = RunAttempt(
            attempt_id=attempt_id,
            purpose=purpose,
            status=status,
            started_at=attempt_started,
            completed_at=completed_at,
            resolved_stages=tuple(resolved_stage_refs),
            invocations=tuple(invocation_refs),
            journal=journal_reference,
            measurement_files=measurement_references,
            metric_verification_files=metric_verification_references,
            log_files=log_references,
            failure=AttemptFailure(
                code=code,
                stage_id=active_stage_id,
                message=str(exc) or type(exc).__name__,
                occurred_at=failed_at,
            ),
        )
        run_reference = GitFileRef(
            repository=run.source.repository,
            commit=plan_commit,
            path=relative_run_path,
        )
        failed_attempt_reference = write_attempt_document(
            root,
            run_root,
            failed_attempt,
            destination,
        )
        if purpose == "benchmark_confirmation":
            failed_attempt_path = (
                root / run_root / "attempts" / str(attempt_id) / "resolved.yaml"
            )
            raise RunError(
                f"benchmark confirmation attempt {attempt_id} failed; evidence "
                f"written to {failed_attempt_path}"
            ) from exc
        attempt_references = tuple(
            write_attempt_document(root, run_root, value, destination)
            for value in previous_attempts
        ) + (failed_attempt_reference,)
        failed_run = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=hashlib.sha256(run_raw).hexdigest(),
                bytes=len(run_raw),
                stored_at=run_reference,
            ),
            status="cancelled" if status == "cancelled" else "failed",
            attempts=attempt_references,
            successful_attempt_id=None,
            completed_at=datetime.now(UTC),
        )
        terminal_raw = serialize_document(failed_run)
        replace_synchronized(terminal_path, terminal_raw)
        replace_synchronized(workspace.terminal, terminal_raw)
        raise RunError(
            f"attempt {attempt_id} failed; evidence written to {terminal_path}"
        ) from exc
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        run_lock.release()
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:annotations -->
```python contract-target
from __future__ import annotations
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:hashlib -->
```python contract-target
import hashlib
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:os -->
```python contract-target
import os
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:tempfile -->
```python contract-target
import tempfile
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:Path -->
```python contract-target
from pathlib import Path
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:RepoRelPath -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:SHA256 -->
```python contract-target
from .._schema import SHA256, RepoRelPath
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:SnapshotFileRef -->
```python contract-target
from ..references import SnapshotFileRef
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:RunError -->
```python contract-target
from .errors import RunError
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_downloads.py:publish_download_body -->
```python contract-target
def publish_download_body(
    *,
    repository_root: Path,
    source: Path,
    destination: RepoRelPath,
    expected_sha256: SHA256,
    expected_bytes: int,
) -> SnapshotFileRef:
    """Copy one verified HTTP body atomically into its declared artifact path."""
    root = repository_root.resolve(strict=True)
    source_path = source.resolve(strict=True)
    if source.is_symlink() or not source_path.is_file():
        raise RunError("HTTP result body must be a regular nonsymlink file")

    target = root / destination
    if not target.resolve(strict=False).is_relative_to(root):
        raise RunError("download artifact path escapes the repository root")
    if target.is_symlink():
        raise RunError("download artifact path must not be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with (
            source_path.open("rb") as source_file,
            os.fdopen(descriptor, "wb") as target_file,
        ):
            while chunk := source_file.read(1024 * 1024):
                target_file.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
            target_file.flush()
            os.fsync(target_file.fileno())

        observed_sha256 = digest.hexdigest()
        if byte_count != expected_bytes:
            raise RunError("download body byte count changed before publication")
        if observed_sha256 != expected_sha256:
            raise RunError("download body SHA-256 changed before publication")

        os.replace(temporary, target)
        return SnapshotFileRef(
            path=destination,
            sha256=observed_sha256,
            bytes=byte_count,
        )
    finally:
        temporary.unlink(missing_ok=True)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:ArtifactPointer -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:ResolvedArtifact -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:ResolvedSingleFileArtifact -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:SingleFileArtifactSpec -->
```python contract-target
from ..artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:HttpRequestSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:HttpResult -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:HttpRetrievalError -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:HttpRetrievalPolicy -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:ResolvedHttpImplementation -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:ResolvedHttpRetrieval -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:invoke_http -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:resolve_http -->
```python contract-target
from ..http import (
    HttpRequestSpec,
    HttpResult,
    HttpRetrievalError,
    HttpRetrievalPolicy,
    ResolvedHttpImplementation,
    ResolvedHttpRetrieval,
    invoke_http,
    resolve_http,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:publish_download_body -->
```python contract-target
from ._downloads import publish_download_body
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_materialization.py:_http_helper -->
```python contract-target
def _http_helper(
    root: Path,
    implementation: ResolvedHttpImplementation,
    request: HttpRequestSpec,
    retrieval_workspace: Path,
    policy: HttpRetrievalPolicy,
    destination: Path,
    input_name: str,
) -> HttpResult:
    try:
        result = invoke_http(
            root,
            implementation,
            request,
            policy,
            retrieval_workspace,
            destination,
        )
    except (HttpRetrievalError, OSError) as exc:
        raise RunError(f"HTTP input {input_name!r} failed retrieval") from exc

    return result
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:resolve_inputs -->
```python contract-target
def resolve_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    stage_id: StageId,
    stage: InternalSpec,
    completed: Mapping[StageId, ResolvedStageRef],
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: RunFetcher,
    policy: VerificationPolicy,
    store: LocalArtifactStore,
) -> tuple[dict[InputName, ResolvedInputRef], dict[str, Path]]:
    """Materialize stage inputs and bind each one to its verified producer."""
    resolved: dict[InputName, ResolvedInputRef] = {}
    paths: dict[str, Path] = {}
    for name, input_ref in stage.inputs.items():
        if input_ref.kind == "future":
            producer = completed.get(input_ref.producer_stage_id)
            if producer is None:
                raise RunError("future input producer has not completed")
            resolved[name] = ResolvedFutureInputRef(producer=producer)
            producer_spec = stage_specs[input_ref.producer_stage_id]
            artifact = producer_spec.artifacts[input_ref.producer_artifact]
            paths[name] = root / artifact.path

        elif input_ref.kind == "external":
            if input_ref.source.kind == "local":
                source_path = root / input_ref.source.path
                if not source_path.is_file():
                    raise RunError("external local input source is not a file")
                raw = source_path.read_bytes()
                file_ref = store.resolved_files({input_ref.source.path: raw})[0]
                _write_materialized_file(root, input_ref.path, raw)
                resolved[name] = ResolvedExternalInputRef(
                    source=input_ref.source,
                    file=file_ref,
                    data_role=input_ref.data_role,
                )
                paths[name] = root / input_ref.path
            elif input_ref.source.kind == "http":
                retrieval_workspace = workspace.resolve(
                    f"stages/{stage_id}/external/{name}"
                )
                retrieval_workspace.mkdir(parents=True, exist_ok=True)
                result = _http_helper(
                    root=root,
                    implementation=resolve_http(root, input_ref.source.http),
                    request=input_ref.source.request,
                    retrieval_workspace=retrieval_workspace,
                    destination=retrieval_workspace / "body",
                    policy=input_ref.source.policy,
                    input_name=name,
                )
                raw = result.body.read_bytes()
                file_ref = store.resolved_files({input_ref.path: raw})[0]
                _write_materialized_file(root, input_ref.path, raw)
                resolved[name] = ResolvedExternalInputRef(
                    source=input_ref.source,
                    file=file_ref,
                    data_role=input_ref.data_role,
                )
                paths[name] = root / input_ref.path

        elif input_ref.kind == "stored":
            pointer_raw = fetcher(input_ref.pointer)
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            verified = verify_promoted_artifact(
                pointer,
                policy=policy,
                expected_data_role=input_ref.data_role,
                fetcher=fetcher,
            )
            _materialize_verified_artifact(root, input_ref.path, verified)
            resolved[name] = ResolvedStoredInputRef(
                pointer=ResolvedArtifactPointerRef(
                    sha256=hashlib.sha256(pointer_raw).hexdigest(),
                    bytes=len(pointer_raw),
                    stored_at=input_ref.pointer,
                )
            )
            paths[name] = root / input_ref.path
    return resolved, paths
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_materialization.py:retrieve_download_inputs -->
```python contract-target
def retrieve_download_inputs(
    root: Path,
    workspace: AttemptWorkspace,
    stage_id: StageId,
    stage: DownloadSpec,
) -> tuple[
    dict[InputName, ResolvedHttpRetrieval],
    dict[str, ResolvedArtifact],
    dict[str, Path],
]:
    """Retrieve each HTTP input and publish it as its same-named artifact."""
    try:
        implementation = resolve_http(root, stage.http)
    except (HttpRetrievalError, OSError) as exc:
        raise RunError("selected HTTP implementation failed identity checks") from exc

    retrievals: dict[InputName, ResolvedHttpRetrieval] = {}
    artifacts: dict[str, ResolvedArtifact] = {}
    paths: dict[str, Path] = {}
    for input_name, request in stage.inputs.items():
        retrieval_workspace = workspace.resolve(
            f"stages/{stage_id}/retrievals/{input_name}"
        )
        retrieval_workspace.mkdir(parents=True, exist_ok=True)
        destination = retrieval_workspace / "body"
        started_at = datetime.now(UTC)
        result = _http_helper(
            root=root,
            implementation=implementation,
            request=request,
            retrieval_workspace=retrieval_workspace,
            policy=stage.policy,
            destination=destination,
            input_name=input_name,
        )
        completed_at = datetime.now(UTC)
        declaration = stage.artifacts[input_name]
        if not isinstance(declaration, SingleFileArtifactSpec):
            raise RunError("download artifact must be a single file")
        body = publish_download_body(
            repository_root=root,
            source=result.body,
            destination=declaration.path,
            expected_sha256=request.expected_body_sha256,
            expected_bytes=request.expected_body_bytes,
        )
        retrievals[input_name] = ResolvedHttpRetrieval(
            input_name=input_name,
            request=request,
            http=implementation,
            response=result.response,
            body=body,
            started_at=started_at,
            completed_at=completed_at,
        )
        artifacts[input_name] = ResolvedSingleFileArtifact(file=body)
        paths[input_name] = root / body.path
    return retrievals, artifacts, paths
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:ResolvedArtifact -->
```python contract-target
from ..artifacts import ResolvedArtifact
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:EnvironmentSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:ExecutionContext -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:GCEEnvironmentSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:GCEHostContext -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedGCEEnvironment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedLocalEnvironment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:observe_execution -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:observe_python_environment -->
```python contract-target
from ..runtime import (
    EnvironmentSpec,
    ExecutionContext,
    GCEEnvironmentSpec,
    GCEHostContext,
    ResolvedGCEEnvironment,
    ResolvedLocalEnvironment,
    observe_execution,
    observe_python_environment,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedBuildSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedDownloadSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedEmbedSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedEvaluateSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:ResolvedTrainSpec -->
```python contract-target
from ..stages import (
    DownloadSpec,
    ParameterizedSpec,
    ResolvedBuildSpec,
    ResolvedDownloadSpec,
    ResolvedEmbedSpec,
    ResolvedEvaluateSpec,
    ResolvedSpec,
    ResolvedTrainSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:resolve_runner_environment -->
```python contract-target
def resolve_runner_environment(
    fetcher: RunFetcher,
    environment: EnvironmentSpec,
) -> tuple[ResolvedLocalEnvironment | ResolvedGCEEnvironment, ExecutionContext]:
    """Resolve the environment observed by a runner-owned stage."""
    python_environment = observe_python_environment()
    if python_environment != environment.python_environment:
        raise RunError("runner Python environment differs from the stage request")
    execution_context = observe_execution(environment)
    if isinstance(environment, GCEEnvironmentSpec):
        host = execution_context.host
        if not isinstance(host, GCEHostContext):
            raise RunError("GCE download omitted its observed GCE host")
        resolved: ResolvedLocalEnvironment | ResolvedGCEEnvironment = (
            ResolvedGCEEnvironment(
                provisioning=host.provisioning,
                machine_type=host.machine_type,
                compute=environment.compute,
                lockfile=resolve_git_file(fetcher, environment.lockfile),
                python_environment=python_environment,
            )
        )
    else:
        resolved = ResolvedLocalEnvironment(
            compute=environment.compute,
            lockfile=resolve_git_file(fetcher, environment.lockfile),
            python_environment=python_environment,
        )
    return resolved, execution_context
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_resolution.py:resolve_stage -->
```python contract-target
def resolve_stage(
    stage: ParameterizedSpec,
    *,
    source: ResolvedGitFileRef,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    process: StageProcessResult,
    invocation: ResolvedStageInvocationRef,
    inputs: dict[InputName, ResolvedInputRef] | None,
    completed_at: datetime,
) -> ResolvedSpec:
    """Construct the resolved subtype for one completed project stage."""
    result = process
    common = {
        "spec": stage,
        "source": source,
        "environment": environment,
        "execution_context": result.execution_context,
        "startup": result.startup,
        "invocation": invocation,
        "command": result.command,
        "artifacts": result.artifacts,
        "completed_at": completed_at,
    }
    assert inputs is not None
    if stage.kind == "build":
        return ResolvedBuildSpec(**common, inputs=inputs)
    if stage.kind == "embed":
        return ResolvedEmbedSpec(**common, inputs=inputs)
    if stage.kind == "train":
        return ResolvedTrainSpec(**common, inputs=inputs)
    return ResolvedEvaluateSpec(**common, inputs=inputs)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=src/viper/execution/_resolution.py:resolve_download_stage -->
```python contract-target
def resolve_download_stage(
    stage: DownloadSpec,
    *,
    environment: ResolvedLocalEnvironment | ResolvedGCEEnvironment,
    execution_context: ExecutionContext,
    artifacts: dict[str, ResolvedArtifact],
    retrievals: dict[InputName, ResolvedHttpRetrieval],
    completed_at: datetime,
) -> ResolvedDownloadSpec:
    """Construct one runner-owned resolved download record."""
    return ResolvedDownloadSpec(
        spec=stage,
        environment=environment,
        execution_context=execution_context,
        artifacts=artifacts,
        retrievals=retrievals,
        completed_at=completed_at,
    )
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_stage.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_stage.py:ParameterizedStageSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_stage.py:StageContextBinding -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_stage.py:StageInvocationReceipt -->
```python contract-target
from ..stages import (
    ParameterizedSpec,
    ParameterizedStageSpec,
    StageContextBinding,
    StageInvocationReceipt,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=src/viper/execution/_stage.py:execute_stage_process -->
```python contract-target
def execute_stage_process(
    repository_root: Path,
    run: RunSpec,
    stage_reference: RunStageRef,
    stage_spec: ParameterizedSpec,
    *,
    attempt_id: int = 1,
    input_paths: dict[str, Path] | None = None,
    timeout_seconds: float | None = None,
) -> StageProcessResult:
    """Invoke one frozen callable and hash every declared output file."""
    root = repository_root.resolve()
    spec_path = _workspace_path(root, stage_reference.spec)
    spec_raw = spec_path.read_bytes()
    if hashlib.sha256(spec_raw).hexdigest() != stage_reference.sha256:
        raise StageExecutionError("stage spec SHA-256 does not match RunStageRef")
    if len(spec_raw) != stage_reference.bytes:
        raise StageExecutionError("stage spec byte count does not match RunStageRef")

    implementation_path = _workspace_path(root, stage_spec.implementation.path)
    if not implementation_path.is_file():
        raise StageExecutionError(
            f"stage implementation is missing: {stage_spec.implementation.path}"
        )
    implementation_raw = implementation_path.read_bytes()
    if len(implementation_raw) != stage_spec.implementation.bytes:
        raise StageExecutionError("stage implementation byte count differs")
    if hashlib.sha256(implementation_raw).hexdigest() != (
        stage_spec.implementation.sha256
    ):
        raise StageExecutionError("stage implementation SHA-256 differs")

    parameterized_stage = cast(ParameterizedStageSpec, stage_spec)
    try:
        validate_stage_parameters(
            root,
            spec_path,
            parameterized_stage,
            timeout_seconds=timeout_seconds,
        )
    except ParameterValidationError as exc:
        raise StageExecutionError("stage parameter validation failed") from exc

    run_spec_path = (
        f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}/spec.yaml"
    )
    supplied_inputs = {} if input_paths is None else input_paths
    logical_inputs: dict[str, str] = {}
    for name, path in supplied_inputs.items():
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(root):
            raise StageExecutionError("stage input path escapes the repository root")
        logical_inputs[name] = resolved_path.relative_to(root).as_posix()
    binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt_id,
        stage_id=stage_reference.stage_id,
        parameter_model=parameterized_stage.parameter_model,
        parameter_digest=document_digest(parameterized_stage.params),
        inputs=logical_inputs,
        artifacts={
            name: artifact.path for name, artifact in stage_spec.artifacts.items()
        },
        metric_ids=stage_spec.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    command = ("python", "-m", "viper._workers.stages")
    environment = os.environ.copy()
    effective_environment = stage_spec.environment or run.environment
    compute = effective_environment.compute
    cuda_ordinal = select_cuda_device(compute.model) if compute.kind == "cuda" else None
    startup_environment = process_environment(
        run.seed,
        run.reproducibility,
        compute,
        cuda_ordinal=cuda_ordinal,
    )
    environment.update({str(key): value for key, value in startup_environment.items()})
    package_root = str(Path(__file__).resolve().parents[2])
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        package_root
        if existing_python_path is None
        else f"{package_root}{os.pathsep}{existing_python_path}"
    )
    runtime_root = root / ".viper" / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    context_path = runtime_root / (
        f"{run.run_id}.{attempt_id}.{stage_reference.stage_id}.context.json"
    )
    result_path = runtime_root / (
        f"{run.run_id}.{attempt_id}.{stage_reference.stage_id}.result.json"
    )
    result_path.unlink(missing_ok=True)
    context_path.write_text(
        StageWorkerContext(
            repository_root=root,
            run_spec_path=root / run_spec_path,
            stage_spec_path=spec_path,
            binding=binding,
            result_path=result_path,
        ).model_dump_json(),
        encoding="utf-8",
    )
    environment["VIPER_CONTEXT_PATH"] = str(context_path)
    started_at = datetime.now(UTC)
    process = subprocess.Popen(
        (sys.executable, *command[1:]),
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except StageProcessInterrupted as exc:
        stdout, stderr = _stop_process_group(process)
        completed_at = datetime.now(UTC)
        exc.invocation = StageInvocationReceipt(
            implementation=stage_spec.implementation,
            context=binding,
            context_digest=document_digest(binding),
            started_at=started_at,
            completed_at=completed_at,
            outcome=exc.outcome,
        )
        exc.stdout = stdout
        exc.stderr = stderr
        raise
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _stop_process_group(process)
        completed_at = datetime.now(UTC)
        raise StageExecutionError(
            "stage command exceeded its timeout",
            invocation=StageInvocationReceipt(
                implementation=stage_spec.implementation,
                context=binding,
                context_digest=document_digest(binding),
                started_at=started_at,
                completed_at=completed_at,
                outcome="failed",
            ),
            stdout=stdout,
            stderr=stderr,
        ) from exc
    completed_at = datetime.now(UTC)
    if not result_path.is_file():
        raise StageExecutionError(
            f"stage command exited with status {process.returncode} without "
            "writing invocation evidence",
            invocation=StageInvocationReceipt(
                implementation=stage_spec.implementation,
                context=binding,
                context_digest=document_digest(binding),
                started_at=started_at,
                completed_at=completed_at,
                outcome="failed",
            ),
            stdout=stdout,
            stderr=stderr,
        )
    try:
        worker_result = StageWorkerResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise StageExecutionError("stage worker wrote an invalid result") from exc
    if process.returncode != 0 or worker_result.error is not None:
        message = worker_result.error or stderr.decode(errors="replace").strip()
        raise StageExecutionError(
            f"stage command exited with status {process.returncode}: {message}",
            invocation=worker_result.invocation,
            stdout=stdout,
            stderr=stderr,
        )
    if (
        worker_result.execution_context is None
        or worker_result.python_environment is None
        or worker_result.startup is None
    ):
        raise StageExecutionError("successful stage omitted runtime evidence")

    artifacts = {
        name: _resolve_artifact(root, declaration)
        for name, declaration in stage_spec.artifacts.items()
    }
    return StageProcessResult(
        command=command,
        started_at=started_at,
        completed_at=completed_at,
        artifacts=artifacts,
        execution_context=worker_result.execution_context,
        python_environment=worker_result.python_environment,
        startup=worker_result.startup,
        invocation=worker_result.invocation,
        stdout=stdout,
        stderr=stderr,
    )
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:annotations -->
```python contract-target
from __future__ import annotations
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:pytest -->
```python contract-target
import pytest
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:publish_download_body -->
```python contract-target
from viper.execution._downloads import publish_download_body
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:RunError -->
```python contract-target
from viper.execution.errors import RunError
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:test_download_body_becomes_declared_artifact -->
```python contract-target
def test_download_body_becomes_declared_artifact(tmp_path: Path) -> None:
    """Copy and hash the HTTP result at the declared artifact path."""
    body = b"tiny response body"
    scratch = tmp_path / ".viper/workspaces/run/attempts/1/http/body"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(body)
    destination = "experiments/example/artifacts/datasets/tiny/dataset.bin"

    reference = publish_download_body(
        repository_root=tmp_path,
        source=scratch,
        destination=destination,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        expected_bytes=len(body),
    )

    assert (tmp_path / destination).read_bytes() == body
    assert reference.path == destination
    assert reference.sha256 == hashlib.sha256(body).hexdigest()
    assert reference.bytes == len(body)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_acceptance.py:test_download_body_mutation_prevents_artifact_publication -->
```python contract-target
def test_download_body_mutation_prevents_artifact_publication(tmp_path: Path) -> None:
    """Reject a same-size body mutation before the artifact becomes visible."""
    expected = b"prior"
    scratch = tmp_path / ".viper/workspaces/run/attempts/1/http/body"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"alter")
    destination = "experiments/example/artifacts/datasets/tiny/prior.bin"

    with pytest.raises(RunError, match="SHA-256 changed"):
        publish_download_body(
            repository_root=tmp_path,
            source=scratch,
            destination=destination,
            expected_sha256=hashlib.sha256(expected).hexdigest(),
            expected_bytes=len(expected),
        )

    assert not (tmp_path / destination).exists()
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_signals.py:builtin_http -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:http_policy -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:http_request -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:python_environment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:reproducibility -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:resume_state -->
```python contract-target
from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
    resume_state,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:ExperimentSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:ReplicateSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:TrainVariantStageParams -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:VariantSpec -->
```python contract-target
from viper.experiments import (
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_execution_signals.py:ResolvedTrainSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:StageImplementationRef -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:StageInvocationReceipt -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:TrainSpec -->
```python contract-target
from viper.stages import (
    DownloadSpec,
    ResolvedTrainSpec,
    StageImplementationRef,
    StageInvocationReceipt,
    TrainSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:_write_source_files -->
```python contract-target
def _write_source_files(root: Path, *, blocking: bool = True) -> dict[str, bytes]:
    """Write the two stage callables and their supporting project code."""
    train_operation = (
        b"    output_root = context.artifacts['parameters'].parent\n"
        b"    output_root.mkdir(parents=True, exist_ok=True)\n"
        b"    child = subprocess.Popen(\n"
        b"        [sys.executable, '-c', 'import time; time.sleep(300)']\n"
        b"    )\n"
        b"    (output_root / 'worker-pids.txt').write_text(\n"
        b"        f'{os.getpid()}\\n{child.pid}\\n', encoding='utf-8'\n"
        b"    )\n"
        b"    print('blocking train started', flush=True)\n"
        b"    while True:\n"
        b"        time.sleep(1)\n"
        if blocking
        else (
            b"    import torch\n"
            b"    assert context.inputs['prior'].read_bytes() == b'prior'\n"
            b"    device = 'cuda' if torch.cuda.is_available() else 'cpu'\n"
            b"    values = torch.tensor([2.0, 3.0], device=device)\n"
            b"    result = values.square().sum().item()\n"
            b"    context.artifacts['parameters'].parent.mkdir(\n"
            b"        parents=True, exist_ok=True\n"
            b"    )\n"
            b"    context.artifacts['parameters'].write_bytes(\n"
            b"        f'{device}:{result}'.encode()\n"
            b"    )\n"
            b"    context.artifacts['resume_state'].write_bytes(b'resume')\n"
        )
    )
    source_files = {
        "viper.toml": b"[project]\nschema_version = 1\n",
        "environment.yml": b"name: viper-signal-test\n",
        "project/loaders/bytes_file.py": (
            b"def load(path):\n    return path.read_bytes()\n"
        ),
        "project/loaders/resume_state.py": (
            "def load(path):\n"
            f"    return {resume_state().model_dump(mode='python')!r}\n"
        ).encode(),
        "project/parameters/train.py": (
            b"from viper import parameters\n\n"
            b"class SignalTrainParameters(parameters.Train):\n"
            b'    """Validate this fixture\'s training parameters."""\n'
        ),
        "jobs/train.py": (
            b"import os\n"
            b"import subprocess\n"
            b"import sys\n"
            b"import time\n\n"
            b"from project.parameters.train import SignalTrainParameters\n"
            b"from viper.api import run\n"
            b"from viper.stages import train\n\n"
            b"@train(params=SignalTrainParameters)\n"
            b"def train(context):\n"
            + train_operation
            + b"\nif __name__ == '__main__':\n"
            b"    run(train)\n"
        ),
    }
    for relative_path, raw in source_files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return source_files
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:_freeze_signal_plan -->
```python contract-target
def _freeze_signal_plan(
    root: Path,
    source_files: dict[str, bytes],
    host: str,
    port: int,
    *,
    compute: CPUComputeSpec | CUDAComputeSpec | None = None,
) -> Path:
    """Freeze one download-then-blocking-train plan for a real coordinator."""
    experiment = ExperimentSpec(
        experiment_id="signals",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="r1", seed=7),),
        metrics=(),
    )
    variant = VariantSpec(
        experiment_id="signals",
        variant_id="baseline",
        levels={},
        stage_params=(
            TrainVariantStageParams(stage_id="train", params=parameters.Train()),
        ),
    )
    experiment_path = root / "experiments/signals/spec.yaml"
    variant_path = root / "experiments/signals/variants/baseline.spec.yaml"
    experiment_path.parent.mkdir(parents=True, exist_ok=True)
    variant_path.parent.mkdir(parents=True, exist_ok=True)
    experiment_path.write_bytes(serialize_document(experiment))
    variant_path.write_bytes(serialize_document(variant))
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "source")
    source_commit = _git(root, "rev-parse", "HEAD")

    source = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    environment = LocalEnvironmentSpec(
        compute=CPUComputeSpec() if compute is None else compute,
        lockfile=GitFileRef.model_validate(
            {
                "repository": REPOSITORY,
                "commit": source_commit,
                "path": "environment.yml",
            }
        ),
        python_environment=python_environment(),
    )
    bytes_loader = ArtifactLoaderRef(
        path="project/loaders/bytes_file.py",
        symbol="load",
        sha256=hashlib.sha256(
            source_files["project/loaders/bytes_file.py"]
        ).hexdigest(),
        bytes=len(source_files["project/loaders/bytes_file.py"]),
    )
    resume_loader = ArtifactLoaderRef(
        path="project/loaders/resume_state.py",
        symbol="load",
        sha256=hashlib.sha256(
            source_files["project/loaders/resume_state.py"]
        ).hexdigest(),
        bytes=len(source_files["project/loaders/resume_state.py"]),
    )
    download = DownloadSpec(
        inputs={
            "prior": http_request(
                url=f"http://{host}:{port}/prior",
                body=b"prior",
            )
        },
        http=builtin_http(),
        policy=http_policy(
            hosts=frozenset({host}),
            ports=frozenset({port}),
        ),
        artifacts={
            "prior": SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/datasets/tiny/prior.bin",
                loader=bytes_loader,
                data_role="training",
            )
        },
    )
    train = TrainSpec(
        implementation=StageImplementationRef(
            path="jobs/train.py",
            symbol="train",
            sha256=hashlib.sha256(source_files["jobs/train.py"]).hexdigest(),
            bytes=len(source_files["jobs/train.py"]),
        ),
        parameter_model=ParameterModelRef(
            path="project/parameters/train.py",
            symbol="SignalTrainParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/train.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/train.py"]),
        ),
        inputs={
            "prior": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="prior",
            )
        },
        params=parameters.Train(),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/parameters.bin",
                loader=bytes_loader,
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/resume_state.bin",
                loader=resume_loader,
                data_role="training",
            ),
        },
    )
    draft_root = root.parent / "drafts"
    draft_root.mkdir()
    download_draft = draft_root / "download.yaml"
    train_draft = draft_root / "train.yaml"
    download_draft.write_bytes(serialize_document(download))
    train_draft.write_bytes(serialize_document(train))
    frozen = freeze_run_plan(
        root,
        RunPlanDraft(
            run_id=RUN_ID,
            experiment_id="signals",
            variant_id="baseline",
            replicate_id="r1",
            seed=7,
            source=source,
            environment=environment,
            reproducibility=reproducibility(),
            stages=(
                StageDraft(stage_id="download", spec_source=download_draft),
                StageDraft(stage_id="train", spec_source=train_draft),
            ),
            estimator=StageArtifactRef(
                stage_id="train",
                artifact_name=PARAMETERS,
            ),
        ),
    )
    _git(root, "add", f"experiments/signals/runs/baseline/{RUN_ID}")
    _git(root, "commit", "--quiet", "-m", "plan")
    return frozen.files[-1]
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:test_live_l4_stage_records_requested_backend -->
```python contract-target
@pytest.mark.live_cuda
@pytest.mark.skipif(
    os.environ.get("VIPER_LIVE_CUDA") != "1",
    reason="set VIPER_LIVE_CUDA=1 to run live CUDA acceptance",
)
@pytest.mark.parametrize(
    ("compute", "expected_backend_type", "expected_artifact"),
    (
        (CPUComputeSpec(), CPUBackendContext, b"cpu:13.0"),
        (
            CUDAComputeSpec(model="NVIDIA L4", count=1),
            CUDABackendContext,
            b"cuda:13.0",
        ),
    ),
    ids=("cpu-on-l4-host", "cuda-on-l4"),
)
def test_live_l4_stage_records_requested_backend(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
    compute: CPUComputeSpec | CUDAComputeSpec,
    expected_backend_type: type[CPUBackendContext] | type[CUDABackendContext],
    expected_artifact: bytes,
) -> None:
    """Execute and verify separate CPU and CUDA plans on the L4 host."""
    assert torch.cuda.is_available()

    root = tmp_path / compute.kind
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)

    source_files = _write_source_files(root, blocking=False)
    run_path = _freeze_signal_plan(
        root,
        source_files,
        *signal_http_source,
        compute=compute,
    )

    result = execute_run(root, run_path)
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    verified = verify_run_result(
        result.resolved_run,
        policy=VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY})),
        fetcher=fetcher,
    )

    train_result = verified.resolved_stages["train"]
    assert isinstance(train_result, ResolvedTrainSpec)
    backend = train_result.execution_context.backend

    assert result.resolved_run.status == "succeeded"
    assert verified.attempts[-1].status == "succeeded"
    assert isinstance(backend, expected_backend_type)
    assert train_result.startup.environment["CUDA_VISIBLE_DEVICES"] == (
        "" if compute.kind == "cpu" else "0"
    )

    if isinstance(backend, CUDABackendContext):
        assert len(backend.gpu_devices) == 1
        assert backend.gpu_devices[0].model == "NVIDIA L4"

    parameters_path = root / RUN_ROOT / "artifacts/models/tiny/parameters.bin"
    assert parameters_path.read_bytes() == expected_artifact
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_execution_signals.py:test_signal_closes_attempt_with_active_stage_evidence -->
```python contract-target
@pytest.mark.parametrize(
    ("signal_number", "expected_status", "expected_code"),
    (
        (signal.SIGINT, "cancelled", "cancelled"),
        (signal.SIGTERM, "preempted", "preempted"),
    ),
    ids=("sigint-cancelled", "sigterm-preempted"),
)
def test_signal_closes_attempt_with_active_stage_evidence(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
    signal_number: signal.Signals,
    expected_status: str,
    expected_code: str,
) -> None:
    """Stop a real coordinator and preserve its completed prefix and active child."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)
    source_files = _write_source_files(root)
    run_path = _freeze_signal_plan(
        root,
        source_files,
        *signal_http_source,
    )
    pid_path = root / RUN_ROOT / "artifacts/models/tiny/worker-pids.txt"
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "viper.cli",
            "--json",
            "run",
            str(run_path),
            "--root",
            str(root),
        ),
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_for_file(pid_path)
        worker_pids = tuple(
            int(value) for value in pid_path.read_text(encoding="utf-8").splitlines()
        )
        os.kill(process.pid, signal_number)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    assert process.returncode == 1
    assert stderr == b""
    assert json.loads(stdout)["code"] == "execution_failed"
    for worker_pid in worker_pids:
        _wait_for_process_exit(worker_pid)

    run = ResolvedRun.model_validate(
        parse_yaml_bytes((root / RUN_ROOT / "resolved.yaml").read_bytes())
    )
    run_spec = RunSpec.model_validate(parse_yaml_bytes(run_path.read_bytes()))
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    attempt = read_attempt_reference(
        run.attempts[-1],
        run_spec,
        fetcher=fetcher,
    )
    assert attempt.status == expected_status
    assert attempt.failure is not None
    assert attempt.failure.code == expected_code
    assert tuple(stage.stage_id for stage in attempt.resolved_stages) == ("download",)
    assert len(attempt.invocations) == 1
    interrupted_receipt = StageInvocationReceipt.model_validate(
        parse_yaml_bytes(store.fetch(attempt.invocations[-1].stored_at))
    )
    assert interrupted_receipt.context.stage_id == "train"
    assert interrupted_receipt.outcome == expected_status
    log_paths = {reference.stored_at.path for reference in attempt.log_files}
    assert f"{RUN_ROOT}/attempts/1/logs/train.stdout.log" in log_paths
    assert f"{RUN_ROOT}/attempts/1/logs/train.stderr.log" in log_paths
    stdout_ref = next(
        reference
        for reference in attempt.log_files
        if reference.stored_at.path.endswith("train.stdout.log")
    )
    assert store.fetch(stdout_ref.stored_at) == b"blocking train started\n"
    journal_entry = DurableJournal(
        root / ".viper/workspaces" / RUN_ID / "attempt-1/control/journal.jsonl"
    ).latest()
    assert journal_entry is not None
    assert journal_entry.state == "terminal"
    verified = verify_run_result(
        run,
        policy=VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY})),
        fetcher=fetcher,
    )
    assert verified.attempts[-1] == attempt
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=add target=tests/test_run_execution.py:builtin_http -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:http_policy -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:http_request -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:python_environment -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:reproducibility -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:resume_state -->
```python contract-target
from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
    resume_state,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:ExperimentSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:ReplicateSpec -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:TrainVariantStageParams -->
<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:VariantSpec -->
```python contract-target
from viper.experiments import (
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
```

<!-- contract-target: requirements=DRA-02,DRA-03 block=P2-DRA-02 action=update target=tests/test_run_execution.py:test_two_stage_local_run_writes_and_verifies_terminal_result -->
```python contract-target
def test_two_stage_local_run_writes_and_verifies_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    http_source: tuple[str, int],
) -> None:
    """Execute source-frozen stages through immutable local publication."""
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.email", "viper@example.com")
    run_git(root, "config", "user.name", "VIPER Test")
    run_git(root, "remote", "add", "origin", REPOSITORY)

    train_params = parameters.Train.model_validate(
        {"epochs": 1, "batch_size": 1, "learning_rate": 0.1}
    )
    metric_source = (
        b"from viper.metrics import metric\n\n"
        b'@metric(metric_id="parameter_bytes", kind="diagnostic", '
        b'mode="recompute")\n'
        b"def compute(context):\n"
        b"    return float(len(context.artifacts['parameters'].read_bytes()))\n"
    )
    live_metric_source = (
        b"from viper.metrics import StatefulMetric, metric\n\n"
        b'@metric(metric_id="epoch_mean", kind="training", mode="live")\n'
        b"class EpochMean(StatefulMetric):\n"
        b"    def __init__(self):\n"
        b"        self.values = []\n"
        b"    def update(self, value):\n"
        b"        self.values.append(float(value))\n"
        b"    def compute(self):\n"
        b"        return sum(self.values) / len(self.values)\n"
    )
    parameter_bytes = MetricSpec(
        metric_id="parameter_bytes",
        kind="diagnostic",
        implementation=MetricImplementationRef(
            path="project/metrics/parameter_bytes.py",
            symbol="compute",
            sha256=hashlib.sha256(metric_source).hexdigest(),
            bytes=len(metric_source),
        ),
        params=parameters.Metric(),
        mode="recompute",
        dependencies=(
            MetricDependency(
                source="artifact",
                name=PARAMETERS,
                required_data_role="training",
            ),
        ),
        comparator=FloatComparator(),
    )
    epoch_mean = MetricSpec(
        metric_id="epoch_mean",
        kind="training",
        implementation=MetricImplementationRef(
            path="project/metrics/epoch_mean.py",
            symbol="EpochMean",
            sha256=hashlib.sha256(live_metric_source).hexdigest(),
            bytes=len(live_metric_source),
        ),
        params=parameters.Metric(),
        mode="live",
    )
    experiment = ExperimentSpec(
        experiment_id="example",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="r1", seed=7),),
        metrics=(parameter_bytes, epoch_mean),
    )
    variant = VariantSpec(
        experiment_id="example",
        variant_id="baseline",
        levels={},
        stage_params=(TrainVariantStageParams(stage_id="train", params=train_params),),
    )
    source_files = {
        "viper.toml": b"[project]\nschema_version = 1\n",
        "environment.yml": b"name: viper-test\n",
        "project/loaders/bytes_file.py": (
            b"def load(path):\n    return path.read_bytes()\n"
        ),
        "project/loaders/resume_state.py": (
            "def load(path):\n"
            f"    return {resume_state().model_dump(mode='python')!r}\n"
        ).encode(),
        "project/metrics/parameter_bytes.py": metric_source,
        "project/metrics/epoch_mean.py": live_metric_source,
        "project/parameters/train.py": (
            b"from pydantic import Field\n"
            b"from viper import parameters\n\n"
            b"class TinyTrainParameters(parameters.Train):\n"
            b"    epochs: int = Field(gt=0)\n"
            b"    batch_size: int = Field(gt=0)\n"
            b"    learning_rate: float = Field(gt=0)\n"
        ),
        "jobs/train.py": (
            b"from project.parameters.train import TinyTrainParameters\n"
            b"from viper.stages import train\n\n"
            b"@train(params=TinyTrainParameters)\n"
            b"def train(context):\n"
            b"    assert context.params.epochs == 1\n"
            b"    assert context.params.batch_size == 1\n"
            b"    assert context.params.learning_rate == 0.1\n"
            b"    assert context.inputs['prior'].read_bytes() == b'prior'\n"
            b"    context.artifacts['parameters'].parent.mkdir(\n"
            b"        parents=True, exist_ok=True\n"
            b"    )\n"
            b"    context.artifacts['parameters'].write_bytes(b'parameters')\n"
            b"    context.artifacts['resume_state'].write_bytes(b'resume')\n"
            b"    live_metric = context.metrics['epoch_mean']\n"
            b"    live_metric.update(1.0)\n"
            b"    live_metric.update(3.0)\n"
            b"    live_metric.record(epoch=0, step=1)\n"
        ),
        "experiments/example/spec.yaml": serialize_document(experiment),
        "experiments/example/variants/baseline.spec.yaml": serialize_document(variant),
    }
    for relative_path, raw in source_files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    run_git(root, "add", ".")
    run_git(root, "commit", "--quiet", "-m", "source")
    source_commit = run_git(root, "rev-parse", "HEAD")

    source = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    lockfile = GitFileRef.model_validate(
        {
            "repository": REPOSITORY,
            "commit": source_commit,
            "path": "environment.yml",
        }
    )
    if os.environ.get("VIPER_LIVE_GCE") == "1":
        environment = GCEEnvironmentSpec(
            provisioning=observe_gce_provisioning(),
            machine_type="g2-standard-12",
            compute=CUDAComputeSpec(model="NVIDIA L4", count=1),
            lockfile=lockfile,
            python_environment=python_environment(),
        )
    else:
        environment = LocalEnvironmentSpec(
            lockfile=lockfile,
            python_environment=python_environment(),
        )
    host, port = http_source
    download = DownloadSpec(
        inputs={
            "prior": http_request(
                url=f"http://{host}:{port}/redirect",
                body=b"prior",
            )
        },
        http=builtin_http(),
        policy=http_policy(
            hosts=frozenset({host}),
            ports=frozenset({port}),
        ),
        artifacts={
            "prior": SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/datasets/tiny/prior.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/bytes_file.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/bytes_file.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/bytes_file.py"]),
                ),
                data_role="training",
            )
        },
    )
    train = TrainSpec(
        implementation=StageImplementationRef(
            path="jobs/train.py",
            symbol="train",
            sha256=hashlib.sha256(source_files["jobs/train.py"]).hexdigest(),
            bytes=len(source_files["jobs/train.py"]),
        ),
        parameter_model=ParameterModelRef(
            path="project/parameters/train.py",
            symbol="TinyTrainParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/train.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/train.py"]),
        ),
        metric_ids=("parameter_bytes", "epoch_mean"),
        inputs={
            "prior": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="prior",
            )
        },
        params=train_params,
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/parameters.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/bytes_file.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/bytes_file.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/bytes_file.py"]),
                ),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/resume_state.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/resume_state.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/resume_state.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/resume_state.py"]),
                ),
                data_role="training",
            ),
        },
    )
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    download_draft = draft_root / "download.yaml"
    train_draft = draft_root / "train.yaml"
    download_draft.write_bytes(serialize_document(download))
    train_draft.write_bytes(serialize_document(train))
    frozen = freeze_run_plan(
        root,
        RunPlanDraft(
            run_id=RUN_ID,
            experiment_id="example",
            variant_id="baseline",
            replicate_id="r1",
            seed=7,
            source=source,
            environment=environment,
            reproducibility=reproducibility(),
            stages=(
                StageDraft(stage_id="download", spec_source=download_draft),
                StageDraft(stage_id="train", spec_source=train_draft),
            ),
            estimator=StageArtifactRef(
                stage_id="train",
                artifact_name=PARAMETERS,
            ),
        ),
    )
    run_git(root, "add", "experiments/example/runs")
    run_git(root, "commit", "--quiet", "-m", "plan")

    requests = []

    def fake_run_request(request):
        requests.append(request)
        return RunSuccess(
            run_id=RUN_ID,
            attempt_id=1,
            resolved_attempt=root / RUN_ROOT / "attempts/1/resolved.yaml",
            resolved_run=root / RUN_ROOT / "resolved.yaml",
            journal=root / ".viper" / "attempt.jsonl",
        )

    monkeypatch.setattr("viper.api.run_request", fake_run_request)
    train_callable = load_stage_callable(
        root / train.implementation.path,
        train.implementation,
        import_root=root,
    )
    run_stage(
        train_callable,
        argv=(
            "--run",
            str(frozen.files[-1]),
            "--stage",
            "train",
            "--root",
            str(root),
        ),
    )
    assert len(requests) == 1
    assert requests[0].run_spec == frozen.files[-1].resolve()

    orphan = AttemptWorkspace.create(
        root / ".viper" / "workspaces",
        RUN_ID,
        1,
    )
    orphan_journal = DurableJournal(orphan.control / "journal.jsonl")
    orphan_started = datetime.now(UTC)
    orphan_journal.append(
        "allocated",
        "attempt allocated",
        recorded_at=orphan_started,
    )
    orphan_journal.append(
        "preflighting",
        "coordinator exited during preflight",
        recorded_at=datetime.now(UTC),
    )

    def fail_first_train(*args, **kwargs):
        """Return real child evidence, then simulate one transient train failure ."""
        process = execute_stage_process(*args, **kwargs)
        stage_reference = args[2]

        if stage_reference.stage_id == "train":
            raise StageExecutionError(
                "transient train failure",
                invocation=process.invocation.model_copy(update={"outcome": "failed"}),
                stdout=process.stdout,
                stderr=b"transient train failure\n",
            )

        return process

    monkeypatch.setattr(
        "viper.execution._attempt.execute_stage_process",
        fail_first_train,
    )

    with pytest.raises(RunError, match="attempt 2 failed"):
        execute_run(root, frozen.files[-1])

    failed_run = ResolvedRun.model_validate(
        parse_yaml_bytes((root / RUN_ROOT / "resolved.yaml").read_bytes())
    )
    run_plan = RunSpec.model_validate(parse_yaml_bytes(frozen.files[-1].read_bytes()))
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    failed_attempts = tuple(
        read_attempt_reference(reference, run_plan, fetcher=fetcher)
        for reference in failed_run.attempts
    )
    assert failed_run.status == "failed"
    assert failed_attempts[0].failure is not None
    assert failed_attempts[0].failure.code == "coordinator_lost"
    failed_attempt = failed_attempts[1]
    assert failed_attempt.failure is not None
    assert failed_attempt.failure.code == "execution_failed"
    assert len(failed_attempt.resolved_stages) == 1
    assert len(failed_attempt.invocations) == 1
    assert (root / RUN_ROOT / "attempts/1/resolved.yaml").is_file()
    assert (root / RUN_ROOT / "attempts/2/resolved.yaml").is_file()

    monkeypatch.setattr(
        "viper.execution._attempt.execute_stage_process",
        execute_stage_process,
    )
    result = execute_retry(root, frozen.files[-1])

    assert result.resolved_run.status == "succeeded"
    destination_path = (
        root / ".viper" / "workspaces" / RUN_ID / "storage-destination.json"
    )
    assert destination_path.read_bytes() == b'{"kind":"local"}\n'
    assert result.resolved_run_path.is_file()
    attempts = tuple(
        read_attempt_reference(reference, run_plan, fetcher=fetcher)
        for reference in result.resolved_run.attempts
    )
    assert [attempt.attempt_id for attempt in attempts] == [1, 2, 3]
    assert (root / RUN_ROOT / "attempts/3/resolved.yaml").is_file()
    successful_attempt = attempts[2]
    assert len(successful_attempt.resolved_stages) == 2
    assert len(successful_attempt.measurement_files) == 2
    assert len(successful_attempt.metric_verification_files) == 1
    assert result.journal_path.is_file()
    assert (result.journal_path.parent / "preflight.json").is_file()
    metric_runtime = root / ".viper" / "runtime"
    production_result = MetricWorkerResult.model_validate_json(
        next(
            metric_runtime.glob("*.parameter_bytes.measurement.result.json")
        ).read_text(encoding="utf-8")
    )
    assert production_result.receipt is not None
    assert production_result.receipt.purpose == "measurement"
    assert tuple(
        entry.state for entry in DurableJournal(result.journal_path).read()
    ) == (
        "allocated",
        "preflighting",
        "running_stage",
        "publishing_stage",
        "running_stage",
        "publishing_stage",
        "closing_attempt",
        "publishing_attempt_files",
        "terminal",
    )

    live_reference = next(
        reference
        for reference in successful_attempt.measurement_files
        if str(reference.stored_at.path).endswith("train.epoch_mean.jsonl")
    )
    live_measurement = Measurement.model_validate_json(
        fetcher(live_reference.stored_at)
    )
    assert live_measurement.value == 2.0
    assert live_measurement.epoch == 0
    assert live_measurement.step == 1
    comparison = compare_runs_application(
        CompareRunsRequest(
            left_path=result.resolved_run_path,
            right_path=result.resolved_run_path,
            left_root=root,
            right_root=root,
            trusted_source_repositories=frozenset({REPOSITORY}),
        ),
        left_fetcher=fetcher,
        right_fetcher=fetcher,
    )
    assert comparison.identical is True
    assert comparison.changes == ()

    candidate_run_raw = result.resolved_run_path.read_bytes()
    confirmation = execute_benchmark_confirmation(root, frozen.files[-1])
    assert confirmation.attempt.attempt_id == 4
    assert confirmation.attempt.purpose == "benchmark_confirmation"
    assert confirmation.attempt.status == "succeeded"
    assert confirmation.attempt_path.is_file()
    assert result.resolved_run_path.read_bytes() == candidate_run_raw
    candidate_snapshots = {
        stage.snapshot.commit for stage in successful_attempt.resolved_stages
    }
    confirmation_snapshots = {
        stage.snapshot.commit for stage in confirmation.attempt.resolved_stages
    }
    assert candidate_snapshots.isdisjoint(confirmation_snapshots)

    first_snapshot = attempts[1].resolved_stages[0].snapshot
    assert first_snapshot.kind == "local"
    stored_artifact = (
        root
        / first_snapshot.store
        / first_snapshot.commit
        / f"{RUN_ROOT}/artifacts/datasets/tiny/prior.bin"
    )
    stored_artifact.write_bytes(b"tampered")
    with pytest.raises(VerificationError, match="byte-count mismatch"):
        verify_run_result(
            result.resolved_run,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({REPOSITORY})
            ),
            fetcher=RunFetcher(root, store, REPOSITORY),
        )
    stored_artifact.write_bytes(b"prior")
```

<!-- pair-block-definition: P2-DRA-03 -->
```toml pair-block
id = "P2-DRA-03"
requirements = ["DRA-04"]
targets = [
    "src/viper/_verification/attempt.py:BaseSpec",
    "src/viper/_verification/attempt.py:DownloadSpec",
    "src/viper/_verification/attempt.py:EvaluateSpec",
    "src/viper/_verification/attempt.py:GitFileRef",
    "src/viper/_verification/attempt.py:HttpRetrievalContextBinding",
    "src/viper/_verification/attempt.py:HttpRetrievalError",
    "src/viper/_verification/attempt.py:HuggingFaceFileRef",
    "src/viper/_verification/attempt.py:InternalSpec",
    "src/viper/_verification/attempt.py:LocalFileRef",
    "src/viper/_verification/attempt.py:LocalStageResultSnapshotRef",
    "src/viper/_verification/attempt.py:ParameterizedSpec",
    "src/viper/_verification/attempt.py:ParameterizedStageSpec",
    "src/viper/_verification/attempt.py:ProjectHttpImplementationSpec",
    "src/viper/_verification/attempt.py:ProjectHttpTransportSpec",
    "src/viper/_verification/attempt.py:ResolvedBaseSpec",
    "src/viper/_verification/attempt.py:ResolvedDownloadSpec",
    "src/viper/_verification/attempt.py:ResolvedParameterizedSpec",
    "src/viper/_verification/attempt.py:ResolvedSpec",
    "src/viper/_verification/attempt.py:ResolvedStageInvocationRef",
    "src/viper/_verification/attempt.py:SnapshotFileRef",
    "src/viper/_verification/attempt.py:StageContextBinding",
    "src/viper/_verification/attempt.py:StageInvocationReceipt",
    "src/viper/_verification/attempt.py:StageResultSnapshotRef",
    "src/viper/_verification/attempt.py:_logical_input_paths",
    "src/viper/_verification/attempt.py:_verify_download_retrievals",
    "src/viper/_verification/attempt.py:_verify_stage_invocation",
    "src/viper/_verification/attempt.py:_verify_unresolved_stage_invocation",
    "src/viper/_verification/attempt.py:retrieval_body_path",
    "src/viper/_verification/attempt.py:validate_request_policy",
    "src/viper/_verification/attempt.py:verify_attempt_stages",
    "src/viper/_verification/plan.py:BaseSpec",
    "src/viper/_verification/plan.py:BuildSpec",
    "src/viper/_verification/plan.py:DownloadSpec",
    "src/viper/_verification/plan.py:EmbedSpec",
    "src/viper/_verification/plan.py:EvaluateSpec",
    "src/viper/_verification/plan.py:InternalSpec",
    "src/viper/_verification/plan.py:ParameterizedSpec",
    "src/viper/_verification/plan.py:Spec",
    "src/viper/_verification/plan.py:StageDefinitionError",
    "src/viper/_verification/plan.py:TrainSpec",
    "src/viper/_verification/plan.py:verify_run_plan_relationships",
    "src/viper/_verification/plan.py:verify_stage_implementation_bytes",
    "src/viper/_verification/plan.py:verify_stage_plan",
    "tests/test_verification_acceptance.py:Any",
    "tests/test_verification_acceptance.py:ArtifactLoaderRef",
    "tests/test_verification_acceptance.py:ArtifactPointer",
    "tests/test_verification_acceptance.py:BuildVariantStageParams",
    "tests/test_verification_acceptance.py:BundleArtifactSpec",
    "tests/test_verification_acceptance.py:DOWNLOAD_SOURCE",
    "tests/test_verification_acceptance.py:DownloadVariantStageParams",
    "tests/test_verification_acceptance.py:EvaluateVariantStageParams",
    "tests/test_verification_acceptance.py:ExperimentSpec",
    "tests/test_verification_acceptance.py:HttpRetrievalContextBinding",
    "tests/test_verification_acceptance.py:ObservedHttpResponse",
    "tests/test_verification_acceptance.py:ReplicateSpec",
    "tests/test_verification_acceptance.py:ResolvedArtifact",
    "tests/test_verification_acceptance.py:ResolvedBundleArtifact",
    "tests/test_verification_acceptance.py:ResolvedBundleMember",
    "tests/test_verification_acceptance.py:ResolvedHttpImplementation",
    "tests/test_verification_acceptance.py:ResolvedHttpRetrieval",
    "tests/test_verification_acceptance.py:ResolvedHttpTransport",
    "tests/test_verification_acceptance.py:ResolvedSingleFileArtifact",
    "tests/test_verification_acceptance.py:SingleFileArtifactSpec",
    "tests/test_verification_acceptance.py:StageArtifactRef",
    "tests/test_verification_acceptance.py:TrainVariantStageParams",
    "tests/test_verification_acceptance.py:VariantSpec",
    "tests/test_verification_acceptance.py:builtin_http",
    "tests/test_verification_acceptance.py:builtin_http_transport",
    "tests/test_verification_acceptance.py:cast",
    "tests/test_verification_acceptance.py:http_policy",
    "tests/test_verification_acceptance.py:http_request",
    "tests/test_verification_acceptance.py:metric_source",
    "tests/test_verification_acceptance.py:metric_spec",
    "tests/test_verification_acceptance.py:parameter_model_ref",
    "tests/test_verification_acceptance.py:parameter_model_source",
    "tests/test_verification_acceptance.py:publish_invocation",
    "tests/test_verification_acceptance.py:publish_producer_run",
    "tests/test_verification_acceptance.py:python_environment",
    "tests/test_verification_acceptance.py:resume_state",
    "tests/test_verification_acceptance.py:retrieval_body_path",
    "tests/test_verification_acceptance.py:stage_implementation_ref",
    "tests/test_verification_acceptance.py:test_download_verification_binds_receipt_to_artifact",
    "tests/test_verification_acceptance.py:verification_policy",
]
assets = []
tests = [
    "tests/test_verification_acceptance.py:test_verifier_rejects_download_receipt_artifact_mismatch",
]
gate = "python -m pytest tests/test_verification_acceptance.py -q"
depends_on = ["P2-DRA-02"]
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/attempt.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/attempt.py:HttpRetrievalContextBinding -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/attempt.py:ProjectHttpTransportSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/attempt.py:SnapshotFileRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/attempt.py:retrieval_body_path -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=src/viper/_verification/plan.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:DOWNLOAD_SOURCE -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:DownloadVariantStageParams -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:HttpRetrievalContextBinding -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:ResolvedHttpTransport -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:builtin_http_transport -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=remove target=tests/test_verification_acceptance.py:retrieval_body_path -->
<!-- contract-remove -->

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:HttpRetrievalError -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=src/viper/_verification/attempt.py:ProjectHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:validate_request_policy -->
```python contract-target
from ..http import (
    HttpRetrievalError,
    ProjectHttpImplementationSpec,
    validate_request_policy,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:GitFileRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:HuggingFaceFileRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:LocalFileRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:LocalStageResultSnapshotRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ResolvedStageInvocationRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:StageResultSnapshotRef -->
```python contract-target
from ..references import (
    GitFileRef,
    HuggingFaceFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedStageInvocationRef,
    StageResultSnapshotRef,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:BaseSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:EvaluateSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:InternalSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ParameterizedStageSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ResolvedBaseSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ResolvedDownloadSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=src/viper/_verification/attempt.py:ResolvedParameterizedSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:ResolvedSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:StageContextBinding -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:StageInvocationReceipt -->
```python contract-target
from ..stages import (
    BaseSpec,
    EvaluateSpec,
    InternalSpec,
    ParameterizedSpec,
    ParameterizedStageSpec,
    ResolvedBaseSpec,
    ResolvedDownloadSpec,
    ResolvedParameterizedSpec,
    ResolvedSpec,
    StageContextBinding,
    StageInvocationReceipt,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:_logical_input_paths -->
```python contract-target
def _logical_input_paths(
    run: RunSpec,
    stage_id: StageId,
    stage: BaseSpec,
    stage_specs: Mapping[StageId, BaseSpec],
) -> dict[InputName, RepoRelPath]:
    """Reconstruct the repository-relative input paths delivered to one stage."""
    if not isinstance(stage, InternalSpec):
        return {}
    paths: dict[InputName, RepoRelPath] = {}
    for name, reference in stage.inputs.items():
        if isinstance(reference, FutureInputRef):
            producer = stage_specs[reference.producer_stage_id]
            paths[name] = producer.artifacts[reference.producer_artifact].path
        else:
            paths[name] = reference.path

    return paths
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:_verify_stage_invocation -->
```python contract-target
def _verify_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    resolved_stage: ResolvedParameterizedSpec,
    fetcher: StorageFetcher | None,
) -> StageInvocationReceipt:
    """Verify one invocation receipt against its plan, context, and startup facts."""
    if reference.stored_at.path != stage_invocation_path(
        run, attempt.attempt_id, stage_id
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is outside its canonical path"
        )
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(run, stage_id, stage, stage_specs),
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    expected_digest = document_digest(expected_binding)
    if receipt.context_digest != expected_digest:
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    if receipt.outcome != "succeeded":
        raise VerificationError(
            f"resolved stage {stage_id!r} requires a successful invocation"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= resolved_stage.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its stage"
        )

    startup = resolved_stage.startup
    if startup.reproducibility != run.reproducibility:
        raise VerificationError(
            f"stage {stage_id!r} startup controls differ from the run plan"
        )
    compute = (stage.environment or run.environment).compute
    recorded_cuda = startup.environment.get("CUDA_VISIBLE_DEVICES")
    if compute.kind == "cuda":
        if recorded_cuda is None or not recorded_cuda.isdigit():
            raise VerificationError(
                f"stage {stage_id!r} startup omitted its selected CUDA device"
            )
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
            cuda_ordinal=int(recorded_cuda),
        )
    else:
        expected_environment = process_environment(
            run.seed,
            run.reproducibility,
            compute,
        )
    if startup.environment != expected_environment:
        raise VerificationError(
            f"stage {stage_id!r} startup environment differs from the plan"
        )
    _verify_startup_backend(
        stage_id,
        compute,
        resolved_stage.execution_context.backend,
    )

    generators = startup.generators
    if any(generator.seed != run.seed for generator in generators):
        raise VerificationError(
            f"stage {stage_id!r} generator receipt uses a different seed"
        )
    family_counts = Counter(generator.family for generator in generators)
    if family_counts["python"] != 1 or family_counts["torch_cpu"] != 1:
        raise VerificationError(
            f"stage {stage_id!r} startup requires one Python and one CPU Torch "
            "generator receipt"
        )
    configured_names = set(expected_binding.numpy_generator_names)
    received_names = {
        generator.name
        for generator in generators
        if generator.family == "numpy_generator"
    }
    if received_names != configured_names:
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts differ"
        )
    if family_counts["numpy_generator"] != len(configured_names):
        raise VerificationError(
            f"stage {stage_id!r} named NumPy generator receipts are duplicated"
        )
    legacy_count = sum(generator.family == "numpy_legacy" for generator in generators)
    if legacy_count != int(run.reproducibility.numpy_randomness.capture_legacy_global):
        raise VerificationError(
            f"stage {stage_id!r} legacy NumPy generator receipt differs"
        )
    cuda_receipts = tuple(
        generator for generator in generators if generator.family == "torch_cuda"
    )
    if compute.kind == "cpu" and cuda_receipts:
        raise VerificationError(
            f"stage {stage_id!r} CPU startup includes a CUDA generator receipt"
        )
    if compute.kind == "cuda" and (
        len(cuda_receipts) != 1 or cuda_receipts[0].device_index != 0
    ):
        raise VerificationError(
            f"stage {stage_id!r} CUDA startup requires one visible-device receipt"
        )
    return receipt
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:_verify_unresolved_stage_invocation -->
```python contract-target
def _verify_unresolved_stage_invocation(
    reference: ResolvedStageInvocationRef,
    *,
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    stage: ParameterizedStageSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    fetcher: StorageFetcher | None,
) -> None:
    """Verify the terminal receipt for a started stage that did not resolve."""
    raw = read_resolved_file(reference, fetcher=fetcher)
    try:
        receipt = StageInvocationReceipt.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            f"stage {stage_id!r} invocation receipt is invalid"
        ) from exc
    expected_binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=_logical_input_paths(run, stage_id, stage, stage_specs),
        artifacts={name: value.path for name, value in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    if receipt.implementation != stage.implementation:
        raise VerificationError(
            f"stage {stage_id!r} invocation used a different implementation"
        )
    if receipt.context != expected_binding:
        raise VerificationError(
            f"stage {stage_id!r} invocation context differs from the plan"
        )
    if receipt.context_digest != document_digest(expected_binding):
        raise VerificationError(f"stage {stage_id!r} invocation context digest differs")
    allowed_outcomes = (
        {"succeeded", "failed"} if attempt.status == "failed" else {attempt.status}
    )
    if receipt.outcome not in allowed_outcomes:
        raise VerificationError(
            f"stage {stage_id!r} invocation outcome differs from its attempt"
        )
    if not (
        attempt.started_at
        <= receipt.started_at
        < receipt.completed_at
        <= attempt.completed_at
    ):
        raise VerificationError(
            f"stage {stage_id!r} invocation timing falls outside its attempt"
        )
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:_verify_download_retrievals -->
```python contract-target
def _verify_download_retrievals(
    attempt: RunAttempt,
    run: RunSpec,
    stage_id: StageId,
    resolved: ResolvedDownloadSpec,
    snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
    *,
    fetcher: StorageFetcher | None,
) -> None:
    """Verify each HTTP request, response, implementation, and artifact body."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    for input_name, retrieval in resolved.retrievals.items():
        try:
            validate_request_policy(retrieval.request, resolved.spec.policy)
            terminal_request = retrieval.request.model_copy(
                update={"url": retrieval.response.response_url}
            )
            validate_request_policy(terminal_request, resolved.spec.policy)
        except HttpRetrievalError as exc:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} violates its frozen policy"
            ) from exc
        if retrieval.response.status not in resolved.spec.policy.accepted_statuses:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} has an unaccepted status"
            )
        expected_path = resolved.spec.artifacts[input_name].path
        if retrieval.body.path != expected_path:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body uses another path"
            )
        body_raw = read_snapshot_file(
            snapshot,
            retrieval.body,
            fetcher=fetcher,
        )
        artifact = resolved.artifacts[input_name]
        if artifact.kind != "file" or artifact.file != retrieval.body:
            raise VerificationError(
                f"HTTP retrieval {input_name!r} differs from its artifact"
            )
        if (
            hashlib.sha256(body_raw).hexdigest()
            != retrieval.request.expected_body_sha256
            or len(body_raw) != retrieval.request.expected_body_bytes
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} body differs from its request"
            )
        if not (
            attempt.started_at
            <= retrieval.started_at
            < retrieval.completed_at
            <= resolved.completed_at
        ):
            raise VerificationError(
                f"HTTP retrieval {input_name!r} timing falls outside its stage"
            )

        http = retrieval.http
        if isinstance(http.spec, ProjectHttpImplementationSpec):
            implementation = http.spec.implementation
            implementation_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=implementation.path,
                )
            )
            if (
                len(implementation_raw) != implementation.bytes
                or hashlib.sha256(implementation_raw).hexdigest()
                != implementation.sha256
            ):
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} implementation source differs"
                )
            parameter_reference = http.spec.parameter_model
            parameter_raw = retrieve(
                GitFileRef(
                    repository=run.source.repository,
                    commit=run.source.commit,
                    path=parameter_reference.path,
                )
            )
            try:
                verify_parameter_model_bytes(parameter_reference, parameter_raw)
            except ParameterValidationError as exc:
                raise VerificationError(
                    f"HTTP retrieval {input_name!r} HTTP parameter model differs"
                ) from exc
            for executable in http.external_executables:
                try:
                    executable_raw = executable.path.read_bytes()
                except OSError as exc:
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable is unavailable"
                    ) from exc
                if (
                    len(executable_raw) != executable.spec.bytes
                    or hashlib.sha256(executable_raw).hexdigest()
                    != executable.spec.sha256
                ):
                    raise VerificationError(
                        f"HTTP retrieval {input_name!r} executable identity differs"
                    )
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/attempt.py:verify_attempt_stages -->
```python contract-target
def verify_attempt_stages(
    attempt: RunAttempt,
    run: RunSpec,
    stage_specs: Mapping[StageId, BaseSpec],
    *,
    require_complete: bool,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, ResolvedBaseSpec]:
    """Verify the ordered resolved-stage prefix retained by one attempt."""
    expected_stage_ids = tuple(stage.stage_id for stage in run.stages)
    resolved_stage_ids = tuple(stage.stage_id for stage in attempt.resolved_stages)
    if resolved_stage_ids != expected_stage_ids[: len(resolved_stage_ids)]:
        raise VerificationError(
            "attempt resolved stages must form an ordered run-stage prefix"
        )
    if require_complete and resolved_stage_ids != expected_stage_ids:
        raise VerificationError("successful attempt must contain every run stage")

    if set(stage_specs) != set(expected_stage_ids):
        raise VerificationError("loaded stage specs do not match the run stage plan")
    resolved_parameterized_ids = tuple(
        stage_id
        for stage_id in resolved_stage_ids
        if isinstance(stage_specs[stage_id], ParameterizedSpec)
    )
    planned_parameterized_ids = tuple(
        stage_id
        for stage_id in expected_stage_ids
        if isinstance(stage_specs[stage_id], ParameterizedSpec)
    )
    if len(attempt.invocations) < len(resolved_parameterized_ids):
        raise VerificationError(
            "attempt must retain an invocation receipt for every project stage"
        )
    if len(attempt.invocations) > len(planned_parameterized_ids):
        raise VerificationError("attempt contains more invocations than planned stages")
    if len(attempt.invocations) > len(resolved_parameterized_ids) + 1:
        raise VerificationError(
            "attempt contains invocations after its unresolved active stage"
        )
    for index, invocation in enumerate(attempt.invocations):
        expected_path = stage_invocation_path(
            run,
            attempt.attempt_id,
            planned_parameterized_ids[index],
        )
        if invocation.stored_at.path != expected_path:
            raise VerificationError(
                "attempt invocation receipts must follow planned stage order"
            )

    verified_stages: dict[StageId, ResolvedBaseSpec] = {}

    for stage_index, stage_reference in enumerate(attempt.resolved_stages):
        expected_resolved_path = resolved_stage_spec_path(
            run,
            stage_reference.stage_id,
        )
        if stage_reference.resolved_spec.path != expected_resolved_path:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} resolved spec is outside "
                "its canonical run path"
            )

        raw = read_snapshot_file(
            stage_reference.snapshot,
            stage_reference.resolved_spec,
            fetcher=fetcher,
        )
        try:
            resolved_spec = RESOLVED_SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} file is not a valid "
                "resolved stage spec"
            ) from exc

        stage_spec = stage_specs[stage_reference.stage_id]

        for artifact_name, artifact_spec in stage_spec.artifacts.items():
            if repo_file_paths_overlap(
                stage_reference.resolved_spec.path,
                artifact_spec.path,
            ):
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} resolved spec collides "
                    f"with artifact {artifact_name!r}"
                )

        if resolved_spec.spec != stage_spec:
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} does not embed its stage spec"
            )

        if isinstance(stage_spec, ParameterizedSpec):
            if not isinstance(resolved_spec, ResolvedParameterizedSpec):
                raise VerificationError("project stage omitted invocation evidence")
            invocation_index = resolved_parameterized_ids.index(
                stage_reference.stage_id
            )
            invocation_reference = attempt.invocations[invocation_index]
            if resolved_spec.invocation != invocation_reference:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} invocation reference differs "
                    "from its attempt"
                )
            _verify_stage_invocation(
                invocation_reference,
                attempt=attempt,
                run=run,
                stage_id=stage_reference.stage_id,
                stage=cast(ParameterizedStageSpec, stage_spec),
                stage_specs=stage_specs,
                resolved_stage=resolved_spec,
                fetcher=fetcher,
            )

            source_location = resolved_spec.source.stored_at
            if (
                source_location.repository != run.source.repository
                or source_location.commit != run.source.commit
            ):
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} source does not match the "
                    "run source snapshot"
                )

        if not (
            attempt.started_at < resolved_spec.completed_at <= attempt.completed_at
        ):
            raise VerificationError(
                f"stage {stage_reference.stage_id!r} completion time falls outside "
                "its containing attempt"
            )

        if isinstance(resolved_spec, ResolvedDownloadSpec):
            _verify_download_retrievals(
                attempt,
                run,
                stage_reference.stage_id,
                resolved_spec,
                stage_reference.snapshot,
                fetcher=fetcher,
            )

        if verified_stages:
            previous_completed_at = next(
                reversed(verified_stages.values())
            ).completed_at
            if resolved_spec.completed_at < previous_completed_at:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} completed before its "
                    "preceding stage"
                )

        if isinstance(resolved_spec, ResolvedParameterizedSpec):
            read_resolved_file(resolved_spec.source, fetcher=fetcher)
        read_resolved_file(resolved_spec.environment.lockfile, fetcher=fetcher)

        requested_environment = stage_spec.environment or run.environment
        resolved_environment = resolved_spec.environment
        _verify_effective_environment(
            stage_reference.stage_id,
            requested_environment,
            resolved_environment,
            resolved_spec.execution_context,
        )

        if isinstance(resolved_spec, ResolvedParameterizedSpec):
            expected_command = (
                "python",
                "-m",
                "viper._workers.stages",
            )
            if resolved_spec.command != expected_command:
                raise VerificationError(
                    f"stage {stage_reference.stage_id!r} command does not match "
                    "the run plan"
                )

        for artifact_name, artifact in resolved_spec.artifacts.items():
            declaration = stage_spec.artifacts[artifact_name]
            verified_artifact = verify_snapshot_artifact(
                stage_reference,
                artifact,
                data_role=declaration.data_role,
                fetcher=fetcher,
            )
            load_verified_artifact(
                run,
                declaration,
                artifact_name,
                verified_artifact,
                policy=policy,
                fetcher=fetcher,
            )

        verified_stages[stage_reference.stage_id] = resolved_spec

    if len(attempt.invocations) == len(resolved_parameterized_ids) + 1:
        stage_id = expected_stage_ids[len(attempt.resolved_stages)]
        stage_spec = stage_specs[stage_id]
        if not isinstance(stage_spec, ParameterizedSpec):
            raise VerificationError("unresolved stage invocation is not parameterized")
        _verify_unresolved_stage_invocation(
            attempt.invocations[-1],
            attempt=attempt,
            run=run,
            stage_id=stage_id,
            stage=cast(ParameterizedStageSpec, stage_spec),
            stage_specs=stage_specs,
            fetcher=fetcher,
        )

    return verified_stages
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:BaseSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:BuildSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:EmbedSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:EvaluateSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:InternalSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:Spec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:StageDefinitionError -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:TrainSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:verify_stage_implementation_bytes -->
```python contract-target
from ..stages import (
    BaseSpec,
    BuildSpec,
    EmbedSpec,
    EvaluateSpec,
    InternalSpec,
    ParameterizedSpec,
    Spec,
    StageDefinitionError,
    TrainSpec,
    verify_stage_implementation_bytes,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:verify_run_plan_relationships -->
```python contract-target
def verify_run_plan_relationships(
    run: RunSpec,
    experiment: ExperimentSpec,
    variant: VariantSpec,
    benchmark: BenchmarkSpec | None,
    stages: Mapping[StageId, BaseSpec],
) -> None:
    """Verify plan relationships spanning experiment, variant, and stages."""

    def require_source_snapshot(location: GitFileRef, label: str) -> None:
        if (
            location.repository != run.source.repository
            or location.commit != run.source.commit
        ):
            raise VerificationError(f"{label} must belong to the run source snapshot")

    require_source_snapshot(run.environment.lockfile, "shared lockfile")

    for stage_id, stage in stages.items():
        if stage.environment is not None:
            require_source_snapshot(
                stage.environment.lockfile,
                f"environment lockfile of stage {stage_id!r}",
            )

    prior_stages: dict[StageId, BaseSpec] = {}
    prior_stages_by_id: dict[StageId, dict[StageId, BaseSpec]] = {}
    for stage_reference in run.stages:
        stage = stages[stage_reference.stage_id]
        prior_stages_by_id[stage_reference.stage_id] = dict(prior_stages)
        _verify_stage_data_roles(stage_reference.stage_id, stage, prior_stages)
        prior_stages[stage_reference.stage_id] = stage

    parameterized_stages = {
        stage_id: stage
        for stage_id, stage in stages.items()
        if isinstance(
            stage,
            (BuildSpec, EmbedSpec, TrainSpec, EvaluateSpec),
        )
    }
    variant_params = {stage.stage_id: stage for stage in variant.stage_params}

    if set(variant_params) != set(parameterized_stages):
        raise VerificationError(
            "variant stage parameters must match all parameterized run stages"
        )

    for stage_id, stage in parameterized_stages.items():
        selected = variant_params[stage_id]
        if selected.kind != stage.kind or selected.params != stage.params:
            raise VerificationError(
                f"variant parameters do not match stage {stage_id!r}"
            )

    estimator_stage = stages.get(run.estimator.stage_id)
    if not isinstance(estimator_stage, TrainSpec):
        raise VerificationError("run estimator must select a training stage")

    experiment_metrics = {metric.metric_id: metric for metric in experiment.metrics}
    for stage_id, stage in stages.items():
        undeclared_metrics = set(stage.metric_ids) - set(experiment_metrics)
        if undeclared_metrics:
            raise VerificationError(f"stage {stage_id!r} selects undeclared metrics")

        selected_kinds = {
            experiment_metrics[metric_id].kind for metric_id in stage.metric_ids
        }
        if isinstance(stage, EvaluateSpec):
            if selected_kinds - {"evaluation"}:
                raise VerificationError(
                    f"evaluation stage {stage_id!r} must select evaluation metrics"
                )
        elif isinstance(stage, TrainSpec):
            if selected_kinds - {"training", "diagnostic"}:
                raise VerificationError(
                    f"training stage {stage_id!r} selects an incompatible metric"
                )
        elif selected_kinds - {"diagnostic"}:
            raise VerificationError(
                f"stage {stage_id!r} must select diagnostic metrics"
            )

    evaluation_stages = [
        stage for stage in stages.values() if isinstance(stage, EvaluateSpec)
    ]
    expected_evaluation_role: DataRole = (
        "benchmark" if benchmark is not None else "evaluation"
    )
    for evaluation in evaluation_stages:
        dataset_input = evaluation.inputs["evaluation_dataset"]
        assert isinstance(dataset_input, StoredInputRef)
        if dataset_input.data_role != expected_evaluation_role:
            raise VerificationError(
                f"evaluation {evaluation.evaluation_id!r} must use "
                f"{expected_evaluation_role!r} data_role"
            )

    for stage_id, stage in stages.items():
        input_roles = (
            _stage_input_roles(stage_id, stage, prior_stages_by_id[stage_id])
            if isinstance(stage, InternalSpec)
            else {}
        )
        for metric_id in stage.metric_ids:
            metric = experiment_metrics[metric_id]
            for dependency in metric.dependencies:
                if dependency.source == "input":
                    role = input_roles.get(dependency.name)
                else:
                    artifact = stage.artifacts.get(dependency.name)
                    role = None if artifact is None else artifact.data_role
                if role is None:
                    raise VerificationError(
                        f"metric {metric_id!r} selects absent {dependency.source} "
                        f"dependency {dependency.name!r}"
                    )
                if role != dependency.required_data_role:
                    raise VerificationError(
                        f"metric {metric_id!r} dependency {dependency.name!r} "
                        "data role differs from its stage declaration"
                    )

    if benchmark is None:
        return

    if len(evaluation_stages) != 1:
        raise VerificationError("benchmark runs require exactly one evaluation stage")

    evaluation = evaluation_stages[0]
    model_input = evaluation.inputs[PARAMETERS_INPUT]
    if not isinstance(model_input, FutureInputRef):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )
    if (
        model_input.producer_stage_id != run.estimator.stage_id
        or model_input.producer_artifact != run.estimator.artifact_name
    ):
        raise VerificationError(
            "benchmark evaluation model must select the run estimator"
        )

    if evaluation.evaluation_id != benchmark.evaluation_id:
        raise VerificationError(
            "evaluation stage ID does not match the benchmark evaluation ID"
        )

    dataset_input = evaluation.inputs["evaluation_dataset"]
    if not isinstance(dataset_input, StoredInputRef):
        raise VerificationError("benchmark evaluation dataset must be stored")
    if dataset_input.pointer != benchmark.evaluation_dataset:
        raise VerificationError(
            "evaluation dataset does not match the benchmark specification"
        )

    if set(evaluation.split_inputs) != set(benchmark.splits):
        raise VerificationError(
            "evaluation split names do not match the benchmark specification"
        )
    for split_name, pointer in benchmark.splits.items():
        split_input = evaluation.inputs[split_name]
        if not isinstance(split_input, StoredInputRef):
            raise VerificationError(f"benchmark split {split_name!r} must be stored")
        if split_input.pointer != pointer:
            raise VerificationError(
                f"evaluation split {split_name!r} does not match the benchmark"
            )

    benchmark_metric_ids = {criterion.metric_id for criterion in benchmark.metrics}
    if set(evaluation.metric_ids) != benchmark_metric_ids:
        raise VerificationError(
            "evaluation metrics do not match the benchmark specification"
        )
    for criterion in benchmark.metrics:
        metric = experiment_metrics[criterion.metric_id]
        if metric.kind != "evaluation" or metric.mode != "recompute":
            raise VerificationError(
                f"benchmark criterion {criterion.metric_id!r} must select a "
                "recomputed evaluation metric"
            )
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=src/viper/_verification/plan.py:verify_stage_plan -->
```python contract-target
def verify_stage_plan(
    run: RunSpec,
    run_spec_reference: ResolvedRunSpecRef,
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, BaseSpec]:
    """Load and verify stage specs from the run-plan snapshot."""
    retrieve = fetch_storage_bytes if fetcher is None else fetcher
    loaded_stages: dict[StageId, BaseSpec] = {}

    for stage in run.stages:
        if stage.spec != stage_spec_path(run, stage.stage_id):
            raise VerificationError(
                f"stage {stage.stage_id!r} spec is outside its canonical run path"
            )

        plan_location = run_spec_reference.stored_at
        location = GitFileRef(
            repository=plan_location.repository,
            commit=plan_location.commit,
            path=stage.spec,
        )

        stage_reference = ResolvedFileRef(
            sha256=stage.sha256,
            bytes=stage.bytes,
            stored_at=location,
        )
        raw = verify_resolved_file_bytes(stage_reference, retrieve(location))

        try:
            spec = SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw))
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                f"stage {stage.stage_id!r} file is not a valid stage spec"
            ) from exc

        if isinstance(spec, ParameterizedSpec):
            implementation = spec.implementation
            implementation_location = GitFileRef(
                repository=run.source.repository,
                commit=run.source.commit,
                path=implementation.path,
            )
            try:
                implementation_raw = retrieve(implementation_location)
                verify_stage_implementation_bytes(implementation, implementation_raw)
                implementation_tree = ast.parse(
                    implementation_raw,
                    filename=implementation.path,
                )
            except (KeyError, OSError, SyntaxError, StageDefinitionError) as exc:
                raise VerificationError(
                    f"implementation of stage {stage.stage_id!r} "
                    "failed source verification"
                ) from exc
            if not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == implementation.symbol
                for node in implementation_tree.body
            ):
                raise VerificationError(
                    f"implementation of stage {stage.stage_id!r} must define "
                    f"top-level callable {implementation.symbol!r}"
                )

        artifact_root = f"{run_root(run)}/artifacts/"
        for artifact_name, artifact in spec.artifacts.items():
            if not str(artifact.path).startswith(artifact_root):
                raise VerificationError(
                    f"artifact {artifact_name!r} of stage {stage.stage_id!r} "
                    "is outside the canonical run artifact root"
                )

        if isinstance(spec, InternalSpec):
            for input_name, input_ref in spec.inputs.items():
                if isinstance(input_ref, StoredInputRef) and not str(
                    input_ref.path
                ).startswith("inputs/"):
                    raise VerificationError(
                        f"stored input {input_name!r} of stage "
                        f"{stage.stage_id!r} is outside inputs"
                    )

        if isinstance(spec, InternalSpec):
            stored_inputs = tuple(
                input_ref
                for input_ref in spec.inputs.values()
                if isinstance(input_ref, StoredInputRef)
            )
            future_materialization_paths: dict[RepoRelPath, InputName] = {}

            for input_name, input_ref in spec.inputs.items():
                if not isinstance(input_ref, FutureInputRef):
                    continue

                producer_stage_id = input_ref.producer_stage_id
                if producer_stage_id not in loaded_stages:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        "must name an earlier stage"
                    )

                producer_spec = loaded_stages[producer_stage_id]
                producer_artifact = producer_spec.artifacts.get(
                    input_ref.producer_artifact
                )
                if producer_artifact is None:
                    raise VerificationError(
                        f"future input {input_name!r} of stage {stage.stage_id!r} "
                        f"selects undeclared artifact "
                        f"{input_ref.producer_artifact!r}"
                    )

                producer_path = producer_artifact.path

                for (
                    previous_path,
                    previous_name,
                ) in future_materialization_paths.items():
                    if repo_file_paths_overlap(producer_path, previous_path):
                        raise VerificationError(
                            f"future input paths for {previous_name!r} and "
                            f"{input_name!r} of stage {stage.stage_id!r} collide"
                        )
                future_materialization_paths[producer_path] = input_name

                if repo_file_paths_overlap(producer_path, spec.implementation.path):
                    raise VerificationError(
                        f"future input {input_name!r} path collides with the "
                        f"implementation of stage {stage.stage_id!r}"
                    )

                for artifact_name, artifact in spec.artifacts.items():
                    if repo_file_paths_overlap(producer_path, artifact.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with "
                            f"artifact {artifact_name!r} of stage "
                            f"{stage.stage_id!r}"
                        )

                for stored_input in stored_inputs:
                    if repo_file_paths_overlap(producer_path, stored_input.path):
                        raise VerificationError(
                            f"future input {input_name!r} path collides with a "
                            f"stored input of stage {stage.stage_id!r}"
                        )

            _verify_stage_data_roles(stage.stage_id, spec, loaded_stages)

        loaded_stages[stage.stage_id] = spec

    return loaded_stages
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:Any -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=tests/test_verification_acceptance.py:cast -->
```python contract-target
from typing import Any, cast
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=tests/test_verification_acceptance.py:builtin_http -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:http_policy -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:http_request -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:metric_source -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:metric_spec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:parameter_model_ref -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:parameter_model_source -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:python_environment -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:resume_state -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:stage_implementation_ref -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:verification_policy -->
```python contract-target
from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    metric_source,
    metric_spec,
    parameter_model_ref,
    parameter_model_source,
    python_environment,
    resume_state,
    stage_implementation_ref,
    verification_policy,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ArtifactLoaderRef -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ArtifactPointer -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:BundleArtifactSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=tests/test_verification_acceptance.py:ResolvedArtifact -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ResolvedBundleArtifact -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ResolvedBundleMember -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ResolvedSingleFileArtifact -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:SingleFileArtifactSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:StageArtifactRef -->
```python contract-target
from viper.artifacts import (
    ArtifactLoaderRef,
    ArtifactPointer,
    BundleArtifactSpec,
    ResolvedArtifact,
    ResolvedBundleArtifact,
    ResolvedBundleMember,
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
    StageArtifactRef,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:BuildVariantStageParams -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:EvaluateVariantStageParams -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ExperimentSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ReplicateSpec -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:TrainVariantStageParams -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:VariantSpec -->
```python contract-target
from viper.experiments import (
    BuildVariantStageParams,
    EvaluateVariantStageParams,
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ObservedHttpResponse -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=tests/test_verification_acceptance.py:ResolvedHttpImplementation -->
<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:ResolvedHttpRetrieval -->
```python contract-target
from viper.http import (
    ObservedHttpResponse,
    ResolvedHttpImplementation,
    ResolvedHttpRetrieval,
)
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:publish_invocation -->
```python contract-target
def publish_invocation(
    store: DocumentStore,
    *,
    run: RunSpec,
    stage_id: str,
    stage: ParameterizedStageSpec,
    input_paths: dict[str, str],
    started_at: datetime,
    completed_at: datetime,
    commit: str,
    attempt_id: int = 1,
) -> ResolvedStageInvocationRef:
    """Publish one successful stage-invocation receipt."""
    binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=input_paths,
        artifacts={name: artifact.path for name, artifact in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    receipt = StageInvocationReceipt(
        implementation=stage.implementation,
        context=binding,
        context_digest=document_digest(binding),
        started_at=started_at,
        completed_at=completed_at,
        outcome="succeeded",
    )
    raw = yaml_bytes(receipt)
    root = f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
    location = hf_file(
        commit,
        f"{root}/attempts/{attempt_id}/invocations/{stage_id}.yaml",
    )
    store.put(location, raw)
    return ResolvedStageInvocationRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=update target=tests/test_verification_acceptance.py:publish_producer_run -->
```python contract-target
def publish_producer_run(
    store: DocumentStore,
    *,
    evaluation_role: DataRole = "evaluation",
) -> tuple[ResolvedRunRef, dict[str, Any]]:
    """Publish a complete upstream run for stored-input verification."""
    run_root = "experiments/source_data/runs/baseline/01ARZ3NDEKTSV4RRFFQ69G5FAA"
    training_dataset_raw = b"fixed training dataset bytes"
    evaluation_dataset_raw = b"fixed evaluation dataset bytes"
    split_raw = b'{"test":[0,1]}\n'
    download = DownloadSpec(
        inputs={
            "dataset": http_request(
                url="https://example.com/toy-v1.tar.gz",
                body=training_dataset_raw,
            ),
            "evaluation_dataset": http_request(
                url="https://example.com/toy-evaluation-v1.bin",
                body=evaluation_dataset_raw,
            ),
            "split": http_request(
                url="https://example.com/toy-split-v1.json",
                body=split_raw,
            ),
        },
        http=builtin_http(),
        policy=http_policy(),
        artifacts={
            "dataset": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/dataset.bin",
                loader=loader_ref("bytes_file"),
                data_role="training",
            ),
            "evaluation_dataset": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/evaluation.bin",
                loader=loader_ref("bytes_file"),
                data_role=evaluation_role,
            ),
            "split": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/split.json",
                loader=loader_ref("bytes_file"),
                data_role=evaluation_role,
            ),
        },
    )
    train = TrainSpec(
        implementation=stage_implementation_ref(
            "training/fit.py",
            TRAIN_SOURCE,
            symbol="fit",
        ),
        parameter_model=parameter_model_ref("train"),
        inputs={
            "training_dataset": FutureInputRef(
                kind="future",
                producer_stage_id="download",
                producer_artifact="dataset",
            )
        },
        params=parameters.Train.model_validate(
            {"epochs": 1, "batch_size": 2, "learning_rate": 0.01}
        ),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/parameters.bin",
                loader=loader_ref("bytes_file"),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/resume_state.bin",
                loader=loader_ref("resume_state"),
                data_role="training",
            ),
        },
    )
    stage_specs: list[tuple[str, BaseSpec]] = [
        ("download", download),
        ("train", train),
    ]
    run = make_run(
        experiment_id="source_data",
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAA",
        source_commit=PRODUCER_SOURCE_COMMIT,
        plan_commit=PRODUCER_PLAN_COMMIT,
        stage_specs=stage_specs,
        estimator_stage_id="train",
    )
    experiment = ExperimentSpec(
        experiment_id="source_data",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
        metrics=(),
    )
    variant = VariantSpec(
        experiment_id="source_data",
        variant_id="baseline",
        levels={},
        stage_params=(
            TrainVariantStageParams(
                kind="train", stage_id="train", params=train.params
            ),
        ),
    )
    run_reference = add_plan_records(
        store,
        run=run,
        stage_specs=stage_specs,
        experiment=experiment,
        variant=variant,
        plan_commit=PRODUCER_PLAN_COMMIT,
    )

    add_loader(store, PRODUCER_SOURCE_COMMIT, "bytes_file")
    add_loader(store, PRODUCER_SOURCE_COMMIT, "resume_state")
    add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        parameter_model_ref("train").path,
        parameter_model_source("train"),
    )
    resolved_env = resolved_environment(store, PRODUCER_SOURCE_COMMIT)
    train_source = add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        str(train.implementation.path),
        TRAIN_SOURCE,
    )

    download_commit = "7" * 40
    resolved_download_artifacts = {
        "dataset": add_single_artifact(
            store,
            download_commit,
            str(download.artifacts["dataset"].path),
            training_dataset_raw,
        ),
        "evaluation_dataset": add_single_artifact(
            store,
            download_commit,
            str(download.artifacts["evaluation_dataset"].path),
            evaluation_dataset_raw,
        ),
        "split": add_single_artifact(
            store,
            download_commit,
            str(download.artifacts["split"].path),
            split_raw,
        ),
    }
    retrievals = {
        name: ResolvedHttpRetrieval(
            input_name=name,
            request=download.inputs[name],
            http=ResolvedHttpImplementation(spec=download.http),
            response=ObservedHttpResponse(
                response_url=download.inputs[name].url,
                status=200,
                response_headers={"content-length": str(artifact.file.bytes)},
            ),
            body=artifact.file,
            started_at=datetime(2026, 8, 20, 20, 2, tzinfo=UTC),
            completed_at=datetime(2026, 8, 20, 20, 5, tzinfo=UTC),
        )
        for name, artifact in resolved_download_artifacts.items()
    }
    resolved_download = ResolvedDownloadSpec(
        spec=download,
        environment=resolved_env,
        execution_context=execution_context(),
        retrievals=retrievals,
        artifacts=cast(dict[str, ResolvedArtifact], resolved_download_artifacts),
        completed_at=datetime(2026, 8, 20, 20, 10, tzinfo=UTC),
    )
    download_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="download",
        snapshot_commit=download_commit,
        resolved_spec=resolved_download,
    )

    train_commit = "8" * 40
    train_invocation = publish_invocation(
        store,
        run=run,
        stage_id="train",
        stage=train,
        input_paths={
            "training_dataset": str(download.artifacts["dataset"].path),
        },
        started_at=datetime(2026, 8, 20, 20, 11, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 29, tzinfo=UTC),
        commit=PRODUCER_RESULT_COMMIT,
    )
    resolved_train = ResolvedTrainSpec(
        spec=train,
        source=train_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=train_invocation,
        command=("python", "-m", "viper._workers.stages"),
        inputs={
            "training_dataset": ResolvedFutureInputRef(producer=download_stage),
        },
        artifacts={
            PARAMETERS: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[PARAMETERS].path),
                b"producer model",
            ),
            RESUME_STATE: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[RESUME_STATE].path),
                resume_state_bytes(),
            ),
        },
        completed_at=datetime(2026, 8, 20, 20, 30, tzinfo=UTC),
    )
    train_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="train",
        snapshot_commit=train_commit,
        resolved_spec=resolved_train,
    )
    attempt = RunAttempt(
        attempt_id=1,
        purpose="run",
        status="succeeded",
        started_at=datetime(2026, 8, 20, 20, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 35, tzinfo=UTC),
        resolved_stages=(download_stage, train_stage),
        invocations=(train_invocation,),
        journal=publish_attempt_journal(
            store,
            run_root_path=run_root,
            attempt_id=1,
            commit=PRODUCER_RESULT_COMMIT,
        ),
        measurement_files=(),
        log_files=(),
        failure=None,
    )
    resolved_run = ResolvedRun(
        spec=run_reference,
        status="succeeded",
        attempts=(
            publish_attempt(
                store,
                run_root_path=run_root,
                attempt=attempt,
                commit=PRODUCER_RESULT_COMMIT,
            ),
        ),
        successful_attempt_id=1,
        completed_at=datetime(2026, 8, 20, 20, 36, tzinfo=UTC),
    )
    resolved_run_raw = yaml_bytes(resolved_run)
    resolved_run_location = hf_file(
        PRODUCER_RESULT_COMMIT,
        f"{run_root}/resolved.yaml",
    )
    store.put(resolved_run_location, resolved_run_raw)
    reference = ResolvedRunRef(
        sha256=sha256(resolved_run_raw),
        bytes=len(resolved_run_raw),
        stored_at=resolved_run_location,
    )
    return reference, {
        "dataset": training_dataset_raw,
        "dataset_ref": download_stage,
        "run": resolved_run,
    }
```

<!-- contract-target: requirements=DRA-04 block=P2-DRA-03 action=add target=tests/test_verification_acceptance.py:test_download_verification_binds_receipt_to_artifact -->
```python contract-target
def test_download_verification_binds_receipt_to_artifact() -> None:
    """Verify one runner-owned response and artifact through the public boundary."""
    store = DocumentStore()
    _, records = publish_producer_run(store)

    verified = verify_run_result(
        records["run"],
        policy=POLICY,
        fetcher=store.fetch,
    )
    download = verified.resolved_stages["download"]

    assert isinstance(download, ResolvedDownloadSpec)
    artifact = download.artifacts["dataset"]
    assert isinstance(artifact, ResolvedSingleFileArtifact)
    assert download.retrievals["dataset"].body == artifact.file
```

<!-- pair-block-definition: P2-DRA-04 -->
```toml pair-block
id = "P2-DRA-04"
requirements = ["DRA-05"]
targets = [
    "src/viper/_workers/stages.py:Any",
    "src/viper/_workers/stages.py:BaseSpec",
    "src/viper/_workers/stages.py:Context",
    "src/viper/_workers/stages.py:DownloadContext",
    "src/viper/_workers/stages.py:DownloadSpec",
    "src/viper/_workers/stages.py:HttpRetrievalHandle",
    "src/viper/_workers/stages.py:InternalSpec",
    "src/viper/_workers/stages.py:ParameterizedSpec",
    "src/viper/_workers/stages.py:StageContextBinding",
    "src/viper/_workers/stages.py:StageInvocationReceipt",
    "src/viper/_workers/stages.py:_planned_stage_context",
    "src/viper/_workers/stages.py:load_stage_callable",
    "src/viper/_workers/stages.py:main",
    "src/viper/_workers/stages.py:retrieval_body_path",
    "src/viper/_workers/stages.py:stage_definition",
    "src/viper/project.py:_project_files",
    "tests/fixtures.py:BuiltinHttpImplementationSpec",
    "tests/fixtures.py:BuiltinHttpTransportSpec",
    "tests/fixtures.py:HttpRequestSpec",
    "tests/fixtures.py:HttpRetrievalPolicy",
    "tests/fixtures.py:builtin_http",
    "tests/fixtures.py:builtin_http_transport",
    "tests/test_documentation.py:PROTOCOL_ALIASES",
    "tests/test_documentation.py:_CONTRACT_TARGET_MARKER",
    "tests/test_documentation.py:_PAIR_BLOCK_MANIFEST_FENCE",
    "tests/test_documentation.py:test_module_ownership_pair_blocks_cover_every_moved_definition",
    "tests/test_documentation.py:test_public_examples_distinguish_weights_from_the_artifact_key",
    "tests/test_documentation.py:test_target_contracts_use_env_identifiers",
    "tests/test_generated_project_acceptance.py:BuildVariantStageParams",
    "tests/test_generated_project_acceptance.py:DownloadVariantStageParams",
    "tests/test_generated_project_acceptance.py:EmbedVariantStageParams",
    "tests/test_generated_project_acceptance.py:EvaluateVariantStageParams",
    "tests/test_generated_project_acceptance.py:ExperimentSpec",
    "tests/test_generated_project_acceptance.py:ReplicateSpec",
    "tests/test_generated_project_acceptance.py:TrainVariantStageParams",
    "tests/test_generated_project_acceptance.py:VariantSpec",
    "tests/test_generated_project_acceptance.py:builtin_http",
    "tests/test_generated_project_acceptance.py:builtin_http_transport",
    "tests/test_generated_project_acceptance.py:http_policy",
    "tests/test_generated_project_acceptance.py:http_request",
    "tests/test_generated_project_acceptance.py:python_environment",
    "tests/test_generated_project_acceptance.py:reproducibility",
    "tests/test_generated_project_acceptance.py:test_generated_project_executes_five_stage_benchmark",
    "tests/test_generated_project_acceptance.py:test_generated_project_uses_runner_owned_downloads",
]
assets = []
tests = [
    "tests/test_generated_project_acceptance.py:test_generated_project_executes_runner_owned_download",
]
gate = "python -m pytest tests/test_generated_project_acceptance.py -q"
depends_on = ["P2-DRA-03"]
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=src/viper/_workers/stages.py:Any -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=src/viper/_workers/stages.py:DownloadContext -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=src/viper/_workers/stages.py:DownloadSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=src/viper/_workers/stages.py:HttpRetrievalHandle -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=src/viper/_workers/stages.py:retrieval_body_path -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=tests/fixtures.py:BuiltinHttpTransportSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=tests/fixtures.py:builtin_http_transport -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=tests/test_generated_project_acceptance.py:DownloadVariantStageParams -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=tests/test_generated_project_acceptance.py:builtin_http_transport -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=remove target=tests/test_generated_project_acceptance.py:test_generated_project_executes_five_stage_benchmark -->
<!-- contract-remove -->

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=src/viper/_workers/stages.py:BaseSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:Context -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:InternalSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:ParameterizedSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:StageContextBinding -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:StageInvocationReceipt -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:load_stage_callable -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:stage_definition -->
```python contract-target
from ..stages import (
    BaseSpec,
    Context,
    InternalSpec,
    ParameterizedSpec,
    StageContextBinding,
    StageInvocationReceipt,
    load_stage_callable,
    stage_definition,
)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:_planned_stage_context -->
```python contract-target
def _planned_stage_context(
    root: Path,
    run: RunSpec,
    stage_id: str,
) -> tuple[ParameterizedSpec, dict[str, str]]:
    """Load the selected stage and derive its plan-owned logical input paths."""
    loaded: dict[str, BaseSpec] = {}
    selected: ParameterizedSpec | None = None
    expected_inputs: dict[str, str] = {}
    for reference in run.stages:
        path = root / reference.spec
        raw = path.read_bytes()
        if len(raw) != reference.bytes or hashlib.sha256(raw).hexdigest() != (
            reference.sha256
        ):
            raise ValueError("startup.plan: stage spec identity differs")
        candidate = load_stage_spec(path)
        if reference.stage_id == stage_id:
            if not isinstance(candidate, ParameterizedSpec):
                raise ValueError("startup.plan: selected stage is not parameterized")
            selected = candidate
            if isinstance(candidate, InternalSpec):
                for name, input_reference in candidate.inputs.items():
                    if isinstance(input_reference, StoredInputRef):
                        expected_inputs[name] = str(input_reference.path)
                    elif isinstance(input_reference, ExternalInputRef):
                        expected_inputs[name] = str(input_reference.path)
                    elif isinstance(input_reference, FutureInputRef):
                        producer = loaded[input_reference.producer_stage_id]
                        expected_inputs[name] = str(
                            producer.artifacts[input_reference.producer_artifact].path
                        )
            break
        loaded[reference.stage_id] = candidate
    if selected is None:
        raise ValueError("startup.plan: context stage ID is absent from RunSpec")
    return selected, expected_inputs
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/_workers/stages.py:main -->
```python contract-target
def main(argv: list[str] | None = None) -> int:
    """Apply controls, construct the typed context, and invoke one callable."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        raise ValueError("stage worker accepts its context through VIPER_CONTEXT_PATH")
    context_path_value = os.environ.get("VIPER_CONTEXT_PATH")
    if context_path_value is None:
        raise ValueError("VIPER_CONTEXT_PATH is required")
    worker_context = StageWorkerContext.model_validate_json(
        Path(context_path_value).read_text(encoding="utf-8")
    )
    root = worker_context.repository_root.resolve()
    run = RunSpec.model_validate(
        parse_yaml_bytes(worker_context.run_spec_path.read_bytes())
    )
    stage = load_stage_spec(worker_context.stage_spec_path)
    binding = worker_context.binding
    started_at = datetime.now(UTC)
    initialization = None
    execution_context = None
    python_environment = None
    if not isinstance(stage, ParameterizedSpec):
        raise ValueError("stage worker requires a parameterized stage")
    try:
        planned_stage, expected_inputs = _planned_stage_context(
            root,
            run,
            binding.stage_id,
        )
        if stage != planned_stage:
            raise ValueError("startup.plan: selected stage differs from RunSpec")
        if (
            worker_context.stage_spec_path.resolve()
            != (
                root
                / next(
                    reference.spec
                    for reference in run.stages
                    if reference.stage_id == binding.stage_id
                )
            ).resolve()
        ):
            raise ValueError("startup.plan: selected stage path differs")
        if binding.run_id != run.run_id:
            raise ValueError("startup.plan: context run ID differs from RunSpec")
        if binding.parameter_model != stage.parameter_model:
            raise ValueError("startup.context: parameter model differs")
        if binding.parameter_digest != document_digest(stage.params):
            raise ValueError("startup.context: parameter digest differs")
        if binding.inputs != expected_inputs:
            raise ValueError("startup.context: input paths differ")
        expected_artifacts = {
            name: str(artifact.path) for name, artifact in stage.artifacts.items()
        }
        if binding.artifacts != expected_artifacts:
            raise ValueError("startup.context: artifact paths differ")
        if binding.metric_ids != stage.metric_ids:
            raise ValueError("startup.context: metric IDs differ")

        effective_environment = stage.environment or run.environment
        initialization = apply_reproducibility(run.seed, run.reproducibility)
        generator_names = tuple(sorted(initialization.numpy_generators))
        if generator_names != binding.numpy_generator_names:
            raise ValueError("startup.context: NumPy generator names differ")
        python_environment = observe_python_environment()
        if python_environment != effective_environment.python_environment:
            raise ValueError("startup.python: installed Python environment differs")
        execution_context = observe_execution(effective_environment)

        params = instantiate_parameters(
            root / stage.parameter_model.path,
            stage.parameter_model,
            stage.params,
            type(stage.params),
        )
        function = load_stage_callable(
            root / stage.implementation.path,
            stage.implementation,
            import_root=root,
        )
        definition = stage_definition(function)
        if definition.kind != stage.kind:
            raise ValueError("startup.callable: decorator kind differs")
        if definition.parameter_model.__name__ != stage.parameter_model.symbol:
            raise ValueError("startup.callable: decorator parameter class differs")
        parameter_source = getattr(function, "__viper_parameter_source__", None)
        if (
            parameter_source is None
            or Path(parameter_source).resolve()
            != (root / stage.parameter_model.path).resolve()
        ):
            raise ValueError("startup.callable: parameter model source differs")

        context = Context(
            run_id=binding.run_id,
            attempt_id=binding.attempt_id,
            stage_id=binding.stage_id,
            params=params,
            inputs=MappingProxyType(_workspace_paths(root, binding.inputs)),
            artifacts=MappingProxyType(_workspace_paths(root, binding.artifacts)),
            metrics=MappingProxyType(_live_metric_handles(root, run, stage, binding)),
            numpy_generators=MappingProxyType(initialization.numpy_generators),
        )
        with autocast_context(run.reproducibility):
            function(context)
    except Exception as exc:
        completed_at = datetime.now(UTC)
        invocation = StageInvocationReceipt(
            implementation=stage.implementation,
            context=binding,
            context_digest=document_digest(binding),
            started_at=started_at,
            completed_at=completed_at,
            outcome="failed",
        )
        _write_result(
            worker_context.result_path,
            StageWorkerResult(
                execution_context=execution_context,
                python_environment=python_environment,
                startup=None if initialization is None else initialization.receipt,
                invocation=invocation,
                error=f"{type(exc).__name__}: {exc}",
            ),
        )
        return 1

    completed_at = datetime.now(UTC)
    invocation = StageInvocationReceipt(
        implementation=stage.implementation,
        context=binding,
        context_digest=document_digest(binding),
        started_at=started_at,
        completed_at=completed_at,
        outcome="succeeded",
    )
    assert initialization is not None
    assert execution_context is not None
    assert python_environment is not None
    _write_result(
        worker_context.result_path,
        StageWorkerResult(
            execution_context=execution_context,
            python_environment=python_environment,
            startup=initialization.receipt,
            invocation=invocation,
        ),
    )
    return 0
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=src/viper/project.py:_project_files -->
```python contract-target
def _project_files(package: str) -> dict[str, str]:
    """Return the complete starter-project file mapping."""
    stage_definitions = {
        "build": ("BuildParameters", "build", "prior"),
        "embed": ("EmbedParameters", "embed", "embedding"),
        "train": ("TrainParameters", "train", "parameters"),
        "evaluate": ("EvaluateParameters", "eval", "predictions"),
    }
    files: dict[str, str] = {
        **ROOT_FILES,
        ".gitignore": ".viper/\n__pycache__/\n*.egg-info/\n",
        "README.md": f"""# {package}

This project contains one decorated callable for each VIPER stage kind.

Run the focused project tests:

    python -m pytest -q

After replacing the stage templates, commit the project and write an experiment
draft under `experiments/`. The draft selects the stages and files for one run.
`viper freeze-run` turns that draft into the exact plan used for execution.

Benchmark specifications belong under `benchmarks/`.
""",
        "pyproject.toml": f'''[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "{package.replace("_", "-")}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["viper-provenance>=0.1.0a2"]

[project.optional-dependencies]
test = ["pytest>=9,<10"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
''',
        f"src/{package}/__init__.py": (
            f'"""Project-owned stages and provenance extensions for {package}."""\n'
        ),
        f"src/{package}/parameters.py": (
            '''"""Define project-owned stage parameter models."""

from pydantic import Field
from viper import parameters


class BuildParameters(parameters.Build):
    """Select the delimiter consumed by the prior builder."""

    delimiter: str = ","


class EmbedParameters(parameters.Embed):
    """Select the dimension of the example embedding."""

    dimensions: int = Field(default=2, gt=0)


class TrainParameters(parameters.Train):
    """Select the number of example training passes."""

    epochs: int = Field(default=1, gt=0)


class EvaluateParameters(parameters.Evaluate):
    """Select the label written beside the example predictions."""

    label: str = "baseline"
'''
        ),
        f"src/{package}/artifact_loaders/__init__.py": (
            '"""Project-owned artifact reconstruction functions."""\n'
        ),
        f"src/{package}/artifact_loaders/bytes_file.py": (
            '''"""Load one file artifact as exact bytes."""

from pathlib import Path


def load(path: Path) -> bytes:
    """Return the complete file contents."""
    return path.read_bytes()
'''
        ),
        f"src/{package}/artifact_loaders/resume_state.py": (
            '''"""Reconstruct the example terminal training state."""

from pathlib import Path

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


def load(path: Path) -> ResumeState:
    """Return the example resume state after confirming the file exists."""
    path.read_bytes()
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
            configuration=DataLoaderConfiguration(workers=0),
            state_dict={"num_yielded": 1},
        ),
    )
'''
        ),
        f"src/{package}/metrics/__init__.py": (
            '"""Project-owned metric implementations."""\n'
        ),
        f"src/{package}/metrics/evaluation.py": (
            '''"""Define one recomputed evaluation metric."""

from viper.metrics import metric


@metric(metric_id="prediction_bytes", kind="evaluation", mode="recompute")
def prediction_bytes(context) -> float:
    """Return the byte count of the verified prediction artifact."""
    return float(len(context.artifacts["predictions"].read_bytes()))
'''
        ),
        "experiments/README.md": """# Experiments

Freeze authored experiment, variant, stage, and run documents here. VIPER
binds every implementation through its repository-relative path and exact
source identity.
""",
        "benchmarks/README.md": """# Benchmarks

A benchmark governs one evaluation contract across candidate run plans and
requires an independently executed confirmation.
""",
        "train.py": f'''"""Run one frozen project plan."""

from {package}.stages.train import train
from viper.api import run


def main() -> None:
    """Execute the complete plan selected by the command-line arguments."""
    run(train)


if __name__ == "__main__":
    main()
''',
        "tests/test_stage_definitions.py": (
            f'''"""Verify generated stages expose their VIPER definitions."""

from {package}.stages.build import build
from {package}.stages.embed import embed
from {package}.stages.evaluate import evaluate
from {package}.stages.train import train

from viper.stages import stage_definition


def test_stage_kinds() -> None:
    """Match each callable with the stage kind fixed by its decorator."""
    stages = (build, embed, train, evaluate)

    assert tuple(stage_definition(stage).kind for stage in stages) == (
        "build",
        "embed",
        "train",
        "evaluate",
    )
'''
        ),
    }
    for stage, (parameter_class, decorator, artifact) in stage_definitions.items():
        if stage == "evaluate":
            input_read = "    payload = context.inputs['parameters'].read_bytes()\n"
        else:
            input_read = (
                "    source = next(iter(context.inputs.values()))\n"
                "    payload = source.read_bytes()\n"
            )
        extra_artifact = ""
        if stage == "train":
            extra_artifact = (
                "    context.artifacts['resume_state'].write_bytes(b'resume')\n"
            )
        destination_line = f'    destination = context.artifacts["{artifact}"]\n'
        stage_body = f"""{input_read}{destination_line}\
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
{extra_artifact}"""
        files[
            f"src/{package}/stages/{stage}.py"
        ] = f'''"""Execute the example {stage} stage."""

from {package}.parameters import {parameter_class}
from viper.stages import {decorator}


@{decorator}(params={parameter_class})
def {stage}(context) -> None:
    """Write the declared {artifact} artifact from verified inputs."""
{stage_body}'''
    files[f"src/{package}/stages/__init__.py"] = (
        '"""Project-owned decorated stage callables."""\n'
    )
    return files
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/fixtures.py:BuiltinHttpImplementationSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/fixtures.py:HttpRequestSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/fixtures.py:HttpRetrievalPolicy -->
```python contract-target
from viper.http import (
    BuiltinHttpImplementationSpec,
    HttpRequestSpec,
    HttpRetrievalPolicy,
)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/fixtures.py:builtin_http -->
```python contract-target
def builtin_http() -> BuiltinHttpImplementationSpec:
    """Select the HTTPX implementation for one synthetic download stage."""
    return BuiltinHttpImplementationSpec()
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/test_documentation.py:_PAIR_BLOCK_MANIFEST_FENCE -->
```python contract-target
_PAIR_BLOCK_MANIFEST_FENCE = re.compile(
    r"```toml pair-block\n.*?\n```",
    re.DOTALL,
)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/test_documentation.py:_CONTRACT_TARGET_MARKER -->
```python contract-target
_CONTRACT_TARGET_MARKER = re.compile(r"<!-- contract-target: [^\n]+ -->")
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_documentation.py:PROTOCOL_ALIASES -->
```python contract-target
PROTOCOL_ALIASES = {
    "ArtifactSpec",
    "AttemptFailureCode",
    "AttemptPurpose",
    "AttemptStatus",
    "ComputeBackendContext",
    "ComputeSpec",
    "DataRole",
    "EnvironmentSpec",
    "GeneratorFamily",
    "GCEProvisioningRef",
    "HostContext",
    "HttpImplementationSpec",
    "InputRef",
    "MetricKind",
    "MetricMode",
    "ParameterizedStageSpec",
    "ResolvedArtifact",
    "ResolvedEnvironment",
    "ResolvedInputRef",
    "ResolvedSpec",
    "Spec",
    "StageResultSnapshot",
    "StartupVariable",
    "StorageModel",
    "StorageRef",
    "VariantStageParams",
}
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_documentation.py:test_target_contracts_use_env_identifiers -->
```python contract-target
def test_target_contracts_use_env_identifiers() -> None:
    """Keep normative contract prose on `env` names before the rename executes."""
    contract_text = "\n".join(
        _CONTRACT_TARGET_MARKER.sub(
            "",
            _PAIR_BLOCK_MANIFEST_FENCE.sub(
                "",
                _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()),
            ),
        )
        for path in IMPLEMENTATION_CONTRACTS
    )
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    target_identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", contract_text))

    assert TARGET_ENV_IDENTIFIERS - target_identifiers == set()
    assert target_identifiers & RETIRED_TARGET_ENV_IDENTIFIERS == set()
    assert 'kind: Literal["env"] = "env"' in contract_text
    assert 'kind: Literal["environment"] = "environment"' not in contract_text
    assert all(name in checklist for name in TARGET_ENV_IDENTIFIERS)
    assert all(name in checklist for name in RETIRED_TARGET_ENV_IDENTIFIERS)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_documentation.py:test_module_ownership_pair_blocks_cover_every_moved_definition -->
```python contract-target
def test_module_ownership_pair_blocks_cover_every_moved_definition() -> None:
    """Keep each realized owner equal to its reviewed PairBlock."""
    reference = MODULE_OWNERSHIP.read_text(encoding="utf-8")

    def exports(tree: ast.Module) -> tuple[str, ...]:
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        )
        assert isinstance(assignment.value, (ast.List, ast.Tuple))
        return tuple(
            value.value
            for value in assignment.value.elts
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )

    def planned_tree(block_id: str) -> ast.Module:
        definition = next(
            match
            for match in _PAIR_BLOCK_DEFINITION.finditer(reference)
            if match.group("id") == block_id
        )
        edit = _TRACEABILITY_MODEL_FENCE.search(definition.group("body"))
        assert edit is not None
        return ast.parse(edit.group("body"))

    model_target = planned_tree("P0-MOD-01")
    model_source = ast.parse(
        (ROOT / "src/viper/verification/models.py").read_text(encoding="utf-8")
    )
    model_names = {
        "VerificationError",
        "VerificationPolicy",
        "VerifiedSnapshotFile",
        "VerifiedArtifact",
        "VerifiedInput",
        "VerifiedRunPlan",
        "VerifiedRunResult",
        "VerifiedBenchmarkResult",
    }
    target_models = {
        node.name: node
        for node in model_target.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    source_models = {
        node.name: node
        for node in model_source.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    assert source_models.keys() == target_models.keys()
    assert exports(model_source) == exports(model_target)

    verification_target = planned_tree("P0-MOD-02")
    verification_source = ast.parse(
        (ROOT / "src/viper/verification/__init__.py").read_text(encoding="utf-8")
    )
    target_operations = {
        node.name: node
        for node in verification_target.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    source_operations = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    assert source_operations.keys() == target_operations.keys()
    assert exports(verification_source) == exports(verification_target)

    api_target = planned_tree("P0-MOD-03")
    api_source = ast.parse((ROOT / "src/viper/api.py").read_text(encoding="utf-8"))
    target_handlers = {
        node.name: node for node in api_target.body if isinstance(node, ast.FunctionDef)
    }
    source_handlers = {
        node.name: node
        for node in api_source.body
        if isinstance(node, ast.FunctionDef) and node.name in target_handlers
    }
    assert source_handlers.keys() == target_handlers.keys()
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_documentation.py:test_public_examples_distinguish_weights_from_the_artifact_key -->
```python contract-target
def test_public_examples_distinguish_weights_from_the_artifact_key() -> None:
    """Keep tutorial vocabulary clear without changing the protocol artifact name."""
    public_text = "\n".join(
        _TRACEABILITY_MODEL_FENCE.sub("", path.read_text()) for path in PUBLIC_MARKDOWN
    )

    assert 'weights_path = context.artifacts["parameters"]' in public_text
    assert "parameters_path" not in public_text
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/test_generated_project_acceptance.py:builtin_http -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:http_policy -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:http_request -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:python_environment -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:reproducibility -->
```python contract-target
from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:BuildVariantStageParams -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:EmbedVariantStageParams -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:EvaluateVariantStageParams -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:ExperimentSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:ReplicateSpec -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:TrainVariantStageParams -->
<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=update target=tests/test_generated_project_acceptance.py:VariantSpec -->
```python contract-target
from viper.experiments import (
    BuildVariantStageParams,
    EmbedVariantStageParams,
    EvaluateVariantStageParams,
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
```

<!-- contract-target: requirements=DRA-05 block=P2-DRA-04 action=add target=tests/test_generated_project_acceptance.py:test_generated_project_uses_runner_owned_downloads -->
```python contract-target
def test_generated_project_uses_runner_owned_downloads(
    tmp_path: Path,
    http_source: tuple[str, int],
) -> None:
    """Run generated code through acquisition, training, and confirmation."""
    root = tmp_path / "generated"
    init(root, "sample_project")
    assert not (root / "src/sample_project/stages/download.py").exists()
    assert "DownloadParameters" not in (
        root / "src/sample_project/parameters.py"
    ).read_text(encoding="utf-8")
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.email", "viper@example.com")
    run_git(root, "config", "user.name", "VIPER Test")
    run_git(root, "remote", "add", "origin", REPOSITORY)
    host, port = http_source

    train_params = parameters.Train.model_validate({"epochs": 1})
    write_experiment_spec(
        root,
        ExperimentSpec(
            experiment_id="acquisition",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="r1", seed=11),),
            metrics=(),
        ),
    )
    write_variant_spec(
        root,
        VariantSpec(
            experiment_id="acquisition",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(stage_id="train", params=train_params),
            ),
        ),
    )
    run_git(root, "add", ".")
    run_git(root, "commit", "--quiet", "-m", "generated acquisition source")
    acquisition_source_commit = run_git(root, "rev-parse", "HEAD")
    acquisition_root = f"experiments/acquisition/runs/baseline/{ACQUISITION_RUN_ID}"
    acquisition_download = DownloadSpec(
        inputs={
            name: http_request(
                url=f"http://{host}:{port}/prior",
                body=b"prior",
                version=f"{name}-v1",
            )
            for name in ("seed_training", "evaluation_dataset", "test_split")
        },
        http=builtin_http(),
        policy=http_policy(hosts=frozenset({host}), ports=frozenset({port})),
        artifacts={
            "seed_training": _artifact(
                root,
                f"{acquisition_root}/artifacts/datasets/starter/seed.bin",
                "training",
            ),
            "evaluation_dataset": _artifact(
                root,
                f"{acquisition_root}/artifacts/datasets/starter/evaluation.bin",
                "benchmark",
            ),
            "test_split": _artifact(
                root,
                f"{acquisition_root}/artifacts/datasets/starter/test_split.bin",
                "benchmark",
            ),
        },
    )
    acquisition_train = TrainSpec(
        implementation=_stage_implementation(root, "train"),
        parameter_model=_parameter_model(root, "TrainParameters"),
        inputs={
            "dataset": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="seed_training",
            )
        },
        params=train_params,
        artifacts={
            PARAMETERS: _artifact(
                root,
                f"{acquisition_root}/artifacts/models/starter/parameters.bin",
                "training",
            ),
            RESUME_STATE: _artifact(
                root,
                f"{acquisition_root}/artifacts/models/starter/resume_state.bin",
                "training",
                loader_name="resume_state",
            ),
        },
    )
    acquisition_plan = _freeze(
        root,
        run_id=ACQUISITION_RUN_ID,
        experiment_id="acquisition",
        seed=11,
        source_commit=acquisition_source_commit,
        stages={"download": acquisition_download, "train": acquisition_train},
    )
    child_environment = _child_environment(root)
    acquisition_process = subprocess.run(
        (
            sys.executable,
            "-m",
            "viper.cli",
            "--json",
            "run",
            str(acquisition_plan),
            "--root",
            str(root),
        ),
        cwd=root,
        env=child_environment,
        check=False,
        capture_output=True,
    )
    assert acquisition_process.returncode == 0, acquisition_process.stderr.decode()
    acquisition_result_path = root / acquisition_root / "resolved.yaml"
    acquisition_result = ResolvedRun.model_validate(
        parse_yaml_bytes(acquisition_result_path.read_bytes())
    )
    assert acquisition_result.status == "succeeded"

    store = LocalArtifactStore(root)
    resolved_run_raw = acquisition_result_path.read_bytes()
    resolved_run_file = store.resolved_files(
        {acquisition_result_path.relative_to(root).as_posix(): resolved_run_raw}
    )[0]
    producer = ResolvedRunRef.model_validate(resolved_run_file.model_dump())
    evaluation_pointer_path = "inputs/datasets/starter/evaluation.pointer.yaml"
    split_pointer_path = "inputs/benchmarks/starter/test_split.pointer.yaml"
    pointer_documents = {
        evaluation_pointer_path: ArtifactPointer(
            run=producer,
            artifact=StageArtifactRef(
                stage_id="download",
                artifact_name="evaluation_dataset",
            ),
        ),
        split_pointer_path: ArtifactPointer(
            run=producer,
            artifact=StageArtifactRef(
                stage_id="download",
                artifact_name="test_split",
            ),
        ),
    }
    for path, pointer in pointer_documents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(serialize_document(pointer))
    run_git(root, "add", *pointer_documents)
    run_git(root, "commit", "--quiet", "-m", "promote benchmark inputs")
    pointer_commit = run_git(root, "rev-parse", "HEAD")
    evaluation_pointer = _pointer_ref(pointer_commit, evaluation_pointer_path)
    split_pointer = _pointer_ref(pointer_commit, split_pointer_path)

    metric_path = "src/sample_project/metrics/evaluation.py"
    metric_raw = (root / metric_path).read_bytes()
    metric = MetricSpec(
        metric_id="prediction_bytes",
        kind="evaluation",
        implementation=MetricImplementationRef(
            path=metric_path,
            symbol="prediction_bytes",
            sha256=hashlib.sha256(metric_raw).hexdigest(),
            bytes=len(metric_raw),
        ),
        params=parameters.Metric(),
        mode="recompute",
        dependencies=(
            MetricDependency(
                source="artifact",
                name=PREDICTIONS,
                required_data_role="benchmark",
            ),
        ),
        comparator=FloatComparator(),
    )
    build_params = parameters.Build.model_validate({"delimiter": ","})
    embed_params = parameters.Embed.model_validate({"dimensions": 2})
    evaluate_params = parameters.Evaluate.model_validate({"label": "baseline"})
    write_experiment_spec(
        root,
        ExperimentSpec(
            experiment_id="starter",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="r1", seed=17),),
            metrics=(metric,),
        ),
    )
    write_variant_spec(
        root,
        VariantSpec(
            experiment_id="starter",
            variant_id="baseline",
            levels={},
            stage_params=(
                BuildVariantStageParams(stage_id="build", params=build_params),
                EmbedVariantStageParams(stage_id="embed", params=embed_params),
                TrainVariantStageParams(stage_id="train", params=train_params),
                EvaluateVariantStageParams(
                    stage_id="evaluate",
                    params=evaluate_params,
                ),
            ),
        ),
    )
    benchmark_path = write_benchmark_spec(
        root,
        BenchmarkSpec(
            benchmark_id="starter",
            evaluation_id="starter_eval",
            evaluation_dataset=evaluation_pointer,
            splits={"test_split": split_pointer},
            metrics=(
                MetricCriterion(
                    metric_id="prediction_bytes",
                    comparison="ge",
                    threshold=1.0,
                ),
            ),
        ),
    )
    run_git(root, "add", "experiments/starter", "benchmarks/starter.spec.yaml")
    run_git(root, "commit", "--quiet", "-m", "define benchmark candidate")
    candidate_source_commit = run_git(root, "rev-parse", "HEAD")
    candidate_root = f"experiments/starter/runs/baseline/{CANDIDATE_RUN_ID}"
    candidate_download = DownloadSpec(
        inputs={
            "dataset": http_request(
                url=f"http://{host}:{port}/prior",
                body=b"prior",
                version="training-v1",
            )
        },
        http=builtin_http(),
        policy=http_policy(hosts=frozenset({host}), ports=frozenset({port})),
        artifacts={
            "dataset": _artifact(
                root,
                f"{candidate_root}/artifacts/datasets/starter/dataset.bin",
                "training",
            )
        },
    )
    candidate_build = BuildSpec(
        implementation=_stage_implementation(root, "build"),
        parameter_model=_parameter_model(root, "BuildParameters"),
        inputs={
            "dataset": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="dataset",
            )
        },
        params=build_params,
        artifacts={
            "prior": _artifact(
                root,
                f"{candidate_root}/artifacts/priors/starter/prior.bin",
                "training",
            )
        },
    )
    candidate_embed = EmbedSpec(
        implementation=_stage_implementation(root, "embed"),
        parameter_model=_parameter_model(root, "EmbedParameters"),
        inputs={
            "prior": FutureInputRef(
                producer_stage_id="build",
                producer_artifact="prior",
            )
        },
        params=embed_params,
        artifacts={
            "embedding": _artifact(
                root,
                f"{candidate_root}/artifacts/models/starter/embedding.bin",
                "training",
            )
        },
    )
    candidate_train = TrainSpec(
        implementation=_stage_implementation(root, "train"),
        parameter_model=_parameter_model(root, "TrainParameters"),
        inputs={
            "embedding": FutureInputRef(
                producer_stage_id="embed",
                producer_artifact="embedding",
            )
        },
        params=train_params,
        artifacts={
            PARAMETERS: _artifact(
                root,
                f"{candidate_root}/artifacts/models/starter/parameters.bin",
                "training",
            ),
            RESUME_STATE: _artifact(
                root,
                f"{candidate_root}/artifacts/models/starter/resume_state.bin",
                "training",
                loader_name="resume_state",
            ),
        },
    )
    candidate_evaluate = EvaluateSpec(
        implementation=_stage_implementation(root, "evaluate"),
        parameter_model=_parameter_model(root, "EvaluateParameters"),
        evaluation_id="starter_eval",
        metric_ids=("prediction_bytes",),
        split_inputs=("test_split",),
        inputs={
            PARAMETERS: FutureInputRef(
                producer_stage_id="train",
                producer_artifact=PARAMETERS,
            ),
            "evaluation_dataset": StoredInputRef(
                pointer=evaluation_pointer,
                path="inputs/datasets/starter/evaluation.bin",
                data_role="benchmark",
            ),
            "test_split": StoredInputRef(
                pointer=split_pointer,
                path="inputs/benchmarks/starter/test_split.bin",
                data_role="benchmark",
            ),
        },
        params=evaluate_params,
        artifacts={
            PREDICTIONS: _artifact(
                root,
                (
                    f"{candidate_root}/artifacts/evaluations/"
                    "starter_eval/predictions.bin"
                ),
                "benchmark",
            )
        },
    )
    candidate_plan = _freeze(
        root,
        run_id=CANDIDATE_RUN_ID,
        experiment_id="starter",
        seed=17,
        source_commit=candidate_source_commit,
        benchmark_id="starter",
        stages={
            "download": candidate_download,
            "build": candidate_build,
            "embed": candidate_embed,
            "train": candidate_train,
            "evaluate": candidate_evaluate,
        },
    )
    subprocess.run(
        (
            sys.executable,
            "train.py",
            "--run",
            str(candidate_plan),
            "--stage",
            "train",
            "--root",
            str(root),
        ),
        cwd=root,
        env=child_environment,
        check=True,
        capture_output=True,
    )
    candidate_result_path = root / candidate_root / "resolved.yaml"
    candidate_result = ResolvedRun.model_validate(
        parse_yaml_bytes(candidate_result_path.read_bytes())
    )
    subprocess.run(
        (
            sys.executable,
            "-m",
            "viper.cli",
            "--json",
            "execute-benchmark",
            str(candidate_result_path),
            str(benchmark_path),
            "--root",
            str(root),
        ),
        cwd=root,
        env=child_environment,
        check=True,
        capture_output=True,
    )
    benchmark_result = BenchmarkResult.model_validate(
        parse_yaml_bytes(
            (candidate_result_path.parent / "benchmark.result.yaml").read_bytes()
        )
    )

    assert candidate_result.status == "succeeded"
    assert benchmark_result.status == "passed"
    assert len(benchmark_result.artifacts) == 2
    assert len(benchmark_result.metrics) == 1
```

The final System Impact check freezes these manifests, target declarations,
the declared non-Python assets, and the candidate Python source together. The
accepted commit becomes the baseline for the next PairBlock or contract.
