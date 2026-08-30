# Download retrieval artifact identity

`DownloadSpec` should publish every successful HTTP response as the
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

**Contract status:** draft after system review; owner review pending.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| DRA-01 <!-- contract-requirement: DRA-01 phase=2 test=tests/test_protocol.py --> | Replace the frozen and resolved download models with the runner-owned hierarchy and shared-file schema. |
| DRA-02 <!-- contract-requirement: DRA-02 phase=2 test=tests/test_run_execution.py --> | Execute successful downloads in the attempt process and remove the project download worker. |
| DRA-03 <!-- contract-requirement: DRA-03 phase=2 test=tests/test_execution_acceptance.py --> | Copy and hash the HTTP result body into the declared artifact path before snapshot publication. |
| DRA-04 <!-- contract-requirement: DRA-04 phase=2 test=tests/test_verification_acceptance.py --> | Verify runner custody and exact receipt-artifact file equality. |
| DRA-05 <!-- contract-requirement: DRA-05 phase=2 test=tests/test_generated_project_acceptance.py --> | Remove the retired callable-copy path from fixtures, generated scaffolding, and execution tests. |
| DRA-06 <!-- contract-requirement: DRA-06 phase=11 test=tests/test_documentation.py --> | Remove the retired callable-copy path from protocol and public documentation. |

**Current:** `DownloadSpec.inputs` names HTTP requests, and
`BaseSpec.artifacts` names files written by the download callable. The names
and paths vary independently. [`DownloadSpec`](../../src/viper/stages.py) and
[`BaseSpec`](../../src/viper/stages.py) define those maps.

**Proposed:** each `DownloadSpec.inputs[name]` produces
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

## 3. Current gap

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

### Current path

**Current:** `retrieve_download_inputs()` retrieves the body into an attempt
workspace, publishes it through `LocalArtifactStore.resolved_files()`, and
writes it at `retrieval_body_path(run, stage_id, input_name)`. The function
stores that `ResolvedFileRef` in `ResolvedHttpRetrieval.body` and passes the
retrieval path to the download worker. See
[`retrieve_download_inputs`](../../src/viper/execution/_materialization.py)
and [`retrieval_body_path`](../../src/viper/paths.py).

**Current:** the download callable receives the body through
`DownloadContext.retrievals[name].body` and receives writable declared output
paths through `context.artifacts`. The project initializer writes a default
callable that reads each retrieval body and writes the same bytes to the
artifact path. [`DownloadContext`](../../src/viper/stages.py) and
[`project_init.py`](../../src/viper/project_init.py) establish that behavior.

**Current:** after the callable exits, `execute_stage_process()` hashes each
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

The current persisted records therefore describe two paths:

```text
ResolvedHttpRetrieval.body
-> ResolvedFileRef at stages/<stage-id>/retrievals/<input-name>/body

ResolvedSingleFileArtifact.file
-> SnapshotFileRef at the declared artifact path
```

The current validators establish separate checks for the request-body digest,
request-body byte count, and declared artifact path. The proposed validator
adds the retrieval-artifact equality rule for the name, path, SHA-256 digest,
and byte count. [`ResolvedHttpRetrieval`](../../src/viper/http.py),
[`ResolvedBaseSpec`](../../src/viper/stages.py), and
[`ResolvedDownloadSpec`](../../src/viper/stages.py) define those checks.

The missing connector is an equality rule joining one request, one retrieval
receipt, and one declared single-file artifact.

## 4. Contract models

### 4.1 Frozen `DownloadSpec`

**Proposed:** a `DownloadSpec` accepts one `HttpRequestSpec` and one declared
single-file artifact for each shared name.

The target frozen hierarchy places project callable identity on
`ParameterizedSpec` and leaves `DownloadSpec` under the common stage fields:

```python
class BaseSpec(ProtocolModel):
    kind: str
    schema_version: Literal[1] = 1
    environment: EnvironmentSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()
    artifacts: dict[ArtifactName, ArtifactSpec] = Field(min_length=1)


class ParameterizedSpec(BaseSpec):
    implementation: StageImplementationRef
    parameter_model: ParameterModelRef


class DownloadSpec(BaseSpec):
    kind: Literal["download"] = "download"
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    http: HttpImplementationSpec
    policy: HttpRetrievalPolicy
```

`DownloadSpec` therefore carries the request map, HTTP implementation, policy,
environment override, metric IDs, and artifact declarations. Build, embed,
train, and evaluate inherit `ParameterizedSpec` and retain project
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

**Proposed:** change `ResolvedHttpRetrieval.body` from `ResolvedFileRef` to
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

`ResolvedDownloadSpec` contains runner evidence and HTTP receipts. Project
source and stage-invocation fields belong to the four project-callable stages.

```python
class ResolvedDownloadSpec(ResolvedBaseSpec):
    kind: Literal["download"] = "download"
    spec: DownloadSpec
    retrievals: dict[InputName, ResolvedHttpRetrieval]
```

The coordinated authoring contract moves `source`, `startup`, `invocation`,
and `command` from `ResolvedBaseSpec` to `ResolvedParameterizedSpec`. The
download record retains `environment`, `execution_context`, `artifacts`, and
`completed_at`. Each `ResolvedHttpRetrieval` supplies request, HTTP implementation,
response, body, and timing evidence. See
[`automatic-input-resolution.md`](automatic-input-resolution.md#target-frozen-download-and-resolved-stage-models).

### 4.4 Complete public authoring example

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

import viper
from viper import HttpRequestSpec, HttpRetrievalPolicy


DATASET_PATH = "artifacts/datasets/training_set/dataset.csv"


def load_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


download = viper.download(
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
        "dataset": viper.file_artifact(
            path=DATASET_PATH,
            loader=load_dataset,
            data_role="training",
        ),
    },
)

download_spec = download.spec
assert isinstance(download_spec, viper.DownloadSpecDraft)
assert set(download_spec.inputs) == {"dataset"}
assert set(download_spec.artifacts) == {"dataset"}
assert download_spec.artifacts["dataset"].path == DATASET_PATH
```

At freeze time, `DownloadSpecDraft` becomes the frozen `DownloadSpec` shown in
section 4.1. Freezing prefixes the selected run root and writes the concrete
repository-relative path to `DownloadSpec.artifacts["dataset"].path`. At
execution time, VIPER invokes the selected HTTP implementation and publishes the verified
body at that concrete path. Project code delegates publication to the runner.

The complete custom-HTTP and model-run program lives in
[`automatic-input-resolution.md`](automatic-input-resolution.md#complete-proposed-authoring-example).

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

`_attempt.py` currently adds retrieval files and artifact files to one
`snapshot_files` dictionary before calling `LocalArtifactStore.snapshot()`.
Under this contract, both views use the same dictionary key. The
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
with the proposed shape.

## 7. Verification

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

**Proposed rule: `download.receipt_artifact_identity`.**

The `ResolvedDownloadSpec` validator checks the shared keys, single-file
artifact shape, and exact `SnapshotFileRef` equality. The attempt verifier
repeats the comparison after it loads `resolved.yaml` from the stage snapshot.

```text
retrievals[name].body.path   == artifacts[name].file.path
retrievals[name].body.sha256 == artifacts[name].file.sha256
retrievals[name].body.bytes  == artifacts[name].file.bytes
```

### 7.3 Runner custody rule

**Proposed rule: `download.runner_custody`.**

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

| Surface | Current | Proposed | Effect |
| --- | --- | --- | --- |
| Frozen stage schema | Request and artifact keys vary independently | Keys match one-for-one and every download artifact is a single file | One HTTP body receives one artifact name |
| Retrieval receipt | `body: ResolvedFileRef` points to a local-store retrieval path | `body: SnapshotFileRef` points to the declared artifact path | Receipt and artifact reference one snapshot file |
| Retrieval runtime | `retrieve_download_inputs()` publishes a retrieval-body revision and materializes its canonical path | `publish_download_body()` copies and hashes the HTTP result body into `spec.artifacts[name].path` | The digest covers the bytes actually written at the artifact path |
| Stage snapshot | Retrieval and artifact loops use different keys | Both loops use the same key | `snapshot_files` stores one body entry |
| Verification | HTTP body and artifact verification run independently | `download.receipt_artifact_identity` joins the two records | Verifier proves one HTTP body became the named artifact |
| Stage execution | Download launches a project worker after retrieval | The attempt process retrieves, verifies, publishes, and resolves the artifact | Download becomes a runner-owned stage |
| Resolved stage | `ResolvedDownloadSpec` carries project source, startup, invocation, and command fields through `ResolvedBaseSpec` | Those fields move to `ResolvedParameterizedSpec`; download retains runner environment, execution context, retrievals, artifacts, and completion | Resolved evidence matches the runtime owner |
| Fixtures and examples | Request names and artifact names may differ | Each download fixture uses the same name in both maps | Tests state the new public rule |
| Documentation | External roots describes the HTTP receipt and later artifact | External roots links to this contract | One owner for the schema and execution detail |
| Storage publication | Local publication writes the completed stage snapshot through `LocalArtifactStore` | The destination-aware publisher writes the shared snapshot file once to local storage or Viper Cloud | Receipt and artifact remain joined at either destination |

### 8.1 Legacy cleanup

This contract retires the repository-level retrieval-body path. The HTTP
function still receives an attempt-workspace directory and writes its completed response
there before the executor publishes the verified body at the declared artifact
path.

| Current occurrence | Disposition | Required replacement |
| --- | --- | --- |
| `viper.paths.retrieval_body_path()`, its imports, and the otherwise empty `viper.paths` module | Delete | Use `stage.artifacts[input_name].path` for the published body. Update the current-gap link when the module is removed. |
| The `run` and `store` parameters and `LocalArtifactStore.resolved_files()` call in `retrieve_download_inputs()` | Delete | Publish the body once through the completed stage snapshot. Keep the attempt-workspace transfer file as execution scratch. |
| `HttpRetrievalContextBinding`, `StageContextBinding.retrievals`, `HttpRetrievalHandle`, and `DownloadContext` | Delete | The attempt process consumes `HttpResult` directly and writes `ResolvedHttpRetrieval`. |
| Download path reconstruction in `viper._workers.stages` and `viper._verification.attempt` | Delete | Download skips the project-stage worker and stage-invocation verifier. Remove the resulting unused retrieval parameters and branches. |
| The generated download callable in `viper.project_init` | Delete | Generate `viper.download()` authoring code with publication owned by the executor. |
| Copy loops and mismatched request/artifact names in `test_execution_acceptance.py`, `test_run_execution.py`, and `test_execution_signals.py` | Replace | Use one shared name and let the executor publish the response body. |
| The `test_verification_acceptance.py` fixture that models one `archive` request and three unrelated artifacts | Replace | Declare three same-named requests and single-file artifacts because this fixture exercises artifact verification. |
| Mismatched `remote` and `dataset` names in `test_preflight.py` | Replace | Give the request and artifact one shared name. |
| Hard-coded `stages/<stage-id>/retrievals/<input-name>/body` assertions | Delete | Assert the declared artifact path and its single snapshot member. |
| `ResolvedHttpRetrieval` model tests that construct `ResolvedFileRef` bodies | Replace | Construct `SnapshotFileRef` bodies at the declared artifact path and assert receipt-artifact equality. Keep HTTP scratch-file tests unchanged. |
| Generated-project acceptance coverage | Replace | Assert that generated authoring uses `viper.download()` and execution publishes each response artifact. |
| `docs/reference/protocol.md` models and execution prose | Replace | Document runner-owned download, the shared successful `SnapshotFileRef`, and the executor-owned artifact write. |
| `HttpContext.workspace`, its bounded `destination`, and HTTP body tests | Retain | The attempt workspace remains the safety boundary for an in-progress request. |
| `LocalArtifactStore.resolved_files()` and its non-download callers | Replace at the orchestration boundary | Route independent files through `publish_resolved_files()`; the local implementation continues to delegate to `LocalArtifactStore`. |
| `DownloadSpec.implementation`, `download_stage`, `parameters.Download`, and download `StageInvocationReceipt` fixtures | Delete | `viper.download()` creates a runner-owned `DownloadSpec`; `ResolvedHttpRetrieval` supplies request execution evidence. |
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
7. Replace generated download-stage scaffolding with `viper.download()`
   authoring in [`src/viper/project_init.py`](../../src/viper/project_init.py)
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
| Changed | Download execution belongs to the attempt process; project-stage invocation receipts cover build, embed, train, and evaluate. | Resolved-stage schema and attempt-execution tests |
| Introduced | Retrieval receipt and resolved artifact share one exact `SnapshotFileRef`. | `download.receipt_artifact_identity` acceptance and rejection tests |
| Strengthened | The attempt verifier proves that the runner published the verified response at the path shared by the retrieval receipt and artifact record. | Runner-custody and receipt-artifact identity assertions |
