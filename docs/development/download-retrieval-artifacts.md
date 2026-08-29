# Download retrieval artifact identity

`DownloadSpec` should publish every successful HTTP response as the
single-file artifact with the same name. `ResolvedHttpRetrieval` records the
HTTP exchange. `ResolvedSingleFileArtifact` exposes the retrieved body to
ordinary artifact consumers. Both records identify one file in the completed
download-stage snapshot.

## 1. Status

**Contract status:** proposed schema and execution revision; implementation
pending.

**Current:** `DownloadSpec.inputs` names HTTP requests, and
`BaseSpec.artifacts` names files written by the download callable. The names
and paths vary independently. [`DownloadSpec`](../../src/viper/stages.py) and
[`BaseSpec`](../../src/viper/stages.py) define those maps.

**Proposed:** each `DownloadSpec.inputs[name]` produces
`DownloadSpec.artifacts[name]`. The executor writes the verified response at
that declared artifact path. The successful `ResolvedHttpRetrieval` and
`ResolvedSingleFileArtifact` use one `SnapshotFileRef` for that path.

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
request, writes the verified body, passes its path to the controlled download
callable, records the final stage snapshot, and verifies the shared file
identity. Dataset meaning, license status, and scientific suitability remain
outside this contract.

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
    transport=...,
    policy=...,
    params=...,
)
```

The `DownloadSpec` validator owns the shared-name and single-file checks. A
download specification with a request key missing from `artifacts`, an artifact
key missing from `inputs`, or a bundle artifact fails validation.

### 4.2 Resolved records

**Proposed:** change `ResolvedHttpRetrieval.body` from `ResolvedFileRef` to
`SnapshotFileRef`. The file reference gives the retrieval receipt its path,
SHA-256 digest, and byte count inside the completed `ResolvedStageRef.snapshot`.

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
request, resolved transport, observed response, and timestamps. The inherited
`artifacts` map gives the same body the standard artifact interface used by
later stages and artifact pointers.

## 5. Execution

The executor owns the retrieval body from the transport result through the
completed stage snapshot.

```text
DownloadSpec.inputs["prior"]
    -> HTTP transport retrieves b"prior"
    -> executor checks the frozen request policy
    -> executor writes b"prior" at spec.artifacts["prior"].path
    -> executor creates SnapshotFileRef(path, sha256, bytes)
    -> ResolvedHttpRetrieval.body receives that reference
    -> DownloadContext.retrievals["prior"].body receives that path
    -> context.artifacts["prior"] receives that same path
    -> execute_stage_process() hashes the declared artifact
    -> ResolvedDownloadSpec validates reference equality
    -> stage snapshot stores the path once
```

`retrieve_download_inputs()` changes its output path from
`retrieval_body_path(...)` to `stage.artifacts[input_name].path`. The function
creates `SnapshotFileRef` directly from the declared artifact path and verified
response bytes. It stops calling `LocalArtifactStore.resolved_files()` for the
retrieval body.

The download callable continues to receive `DownloadContext.retrievals` and
`context.artifacts`. Existing copy-style callables read and rewrite the same
bytes at the same path. The final `ResolvedDownloadSpec` validator rejects a
callable that changes the response body after the executor writes it.

`_attempt.py` currently adds retrieval files and artifact files to one
`snapshot_files` dictionary before calling `LocalArtifactStore.snapshot()`.
Under this contract, both paths use the same dictionary key. The snapshot holds
one durable copy of the response body.

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
    transport: <resolved transport>
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

`_verify_download_retrievals()` continues to verify the selected transport,
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

### 7.3 Delivery rule

The stage-invocation verifier reconstructs `StageContextBinding`. For a
download stage, `StageContextBinding.retrievals[name].body` and
`StageContextBinding.artifacts[name]` use the same repository-relative path.
The verifier then checks the invocation receipt against that binding.
[`_verify_stage_invocation`](../../src/viper/_verification/attempt.py) owns the
binding comparison.

## 8. Propagation and change impact

| Surface | Current | Proposed | Effect |
| --- | --- | --- | --- |
| Frozen stage schema | Request and artifact keys vary independently | Keys match one-for-one and every download artifact is a single file | One HTTP body receives one artifact name |
| Retrieval receipt | `body: ResolvedFileRef` points to a local-store retrieval path | `body: SnapshotFileRef` points to the declared artifact path | Receipt and artifact reference one snapshot file |
| Retrieval runtime | `retrieve_download_inputs()` publishes a retrieval-body revision and materializes its canonical path | Executor materializes the verified response at `spec.artifacts[name].path` | One durable payload path |
| Worker binding | Retrieval body path and artifact path can differ | Both bindings use the declared artifact path | Download callable sees one file through both handles |
| Stage snapshot | Retrieval and artifact loops use different keys | Both loops use the same key | `snapshot_files` stores one body entry |
| Verification | HTTP body and artifact verification run independently | `download.receipt_artifact_identity` joins the two records | Verifier proves one HTTP body became the named artifact |
| User stage file | Default download function copies a retrieval body to an artifact path | Existing function reads and writes one shared path | Existing code remains executable; generated scaffold can remove the redundant copy |
| Fixtures and examples | Request names and artifact names may differ | Each download fixture uses the same name in both maps | Tests state the new public rule |
| Documentation | External roots describes the HTTP receipt and later artifact | External roots links to this contract | One owner for the schema and execution detail |

## 9. Acceptance case

### Success: one `prior` response becomes one `prior` artifact

The acceptance fixture declares:

```text
inputs["prior"]
-> frozen request expecting b"prior"

artifacts["prior"]
-> declared single-file dataset path
```

The controlled transport returns `b"prior"`. The executor writes the bytes at
the declared artifact path. The resolved download stage contains one retrieval
and one single-file artifact named `prior`. The stage snapshot contains the
artifact path once. `verify_run_result()` succeeds.

The test asserts:

```text
resolved.retrievals["prior"].body == resolved.artifacts["prior"].file
snapshot contains the declared artifact path once
stage invocation binds retrievals["prior"].body.path == artifacts["prior"].path
```

### Rejection: artifact file changes after retrieval

The fixture uses the same frozen request and response body. The download
callable overwrites `context.artifacts["prior"]` with different bytes. The
executor produces a different artifact digest. The
`download.receipt_artifact_identity` validator rejects the resolved download
stage because the retrieval-body and artifact-file references differ.

## 10. Implementation order

1. Add the shared-key and single-file `DownloadSpec` validator in
   [`src/viper/stages.py`](../../src/viper/stages.py). Add schema tests for a
   missing key, an extra key, and a bundle artifact.
2. Change `ResolvedHttpRetrieval.body` to `SnapshotFileRef`. Add the
   `ResolvedDownloadSpec` receipt-artifact identity validator and model tests.
3. Change `retrieve_download_inputs()` to materialize at the declared artifact
   path and return `SnapshotFileRef` values. Update worker-context binding and
   stage-snapshot collection in
   [`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py),
   [`src/viper/execution/_stage.py`](../../src/viper/execution/_stage.py), and
   [`src/viper/execution/_attempt.py`](../../src/viper/execution/_attempt.py).
4. Update `_verify_stage_invocation()` and `_verify_download_retrievals()` in
   [`src/viper/_verification/attempt.py`](../../src/viper/_verification/attempt.py)
   to read and compare the shared snapshot reference.
5. Replace the existing download fixtures whose request and artifact names
   differ. Add the success and rejection cases in `tests/test_run_execution.py`,
   `tests/test_execution_acceptance.py`, and
   `tests/test_verification_acceptance.py`.
6. Update generated download-stage scaffolding in
   [`src/viper/project_init.py`](../../src/viper/project_init.py) and the
   protocol reference. Link
   [`external-input-roots.md`](external-input-roots.md) to this contract.

## 11. Invariants

| Classification | Rule | Evidence |
| --- | --- | --- |
| Preserved | HTTP receipt verification checks the frozen request, transport, response policy, body digest, body byte count, and timing. | `ResolvedHttpRetrieval` and `_verify_download_retrievals()` tests |
| Preserved | A later stage selects a download artifact through `FutureInputRef` or `StoredInputRef`. | Same-run and prior-run input verification tests |
| Changed | Download stages accept matching request and artifact keys with one single-file artifact per request. | `DownloadSpec` validator tests |
| Changed | Retrieval bodies move from standalone `ResolvedFileRef` values to `SnapshotFileRef` values. | Resolved-document parser and verifier tests |
| Introduced | Retrieval receipt and resolved artifact share one exact `SnapshotFileRef`. | `download.receipt_artifact_identity` acceptance and rejection tests |
| Strengthened | The attempt verifier proves that the controlled download callable received the same path that appears in the retrieval receipt and artifact record. | Stage-invocation binding assertion |
