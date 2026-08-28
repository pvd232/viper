# Remote storage contract and execution checklist

This document defines how VIPER copies a completed run to Hugging Face,
recovers that run on another machine, and removes selected local copies.
It is the execution authority for this feature.

## 1. Status

**Contract status:** approved user workflow; implementation pending.

The formal protocol already defines `HuggingFaceFileRef` and permits
`ResolvedFileRef.stored_at` to select a file at an exact Hugging Face commit.
The verifier can retrieve and hash that file. The runner currently publishes
every completed stage and attempt through `LocalArtifactStore`.

This contract adds remote synchronization around the completed local run. It
leaves experiment execution and the existing artifact-pointer contract
unchanged.

## 2. Required claim

When a project selects a Hugging Face destination, VIPER copies every file
needed to restore and verify a terminal run, records the exact remote commit,
and preserves each local file until the user explicitly offloads it.

The claim covers delivery and retrieval. VIPER controls the upload, records the
returned Hugging Face commit, downloads requested files from that commit, and
checks their byte counts and SHA-256 digests. Provider durability lies outside
this claim.

## 3. Current gap

The current implementation contains three pieces of the required path:

```text
LocalArtifactStore
-> publishes immutable local revisions

HuggingFaceFileRef
-> identifies one file at an exact remote commit

fetch_huggingface_file_bytes()
-> downloads that file for verification
```

The runner always constructs `LocalArtifactStore`. The connector ends there:
the runner lacks an operation that copies the resulting revisions to Hugging
Face, records the copy, retries an interrupted upload, or removes a
synchronized local revision.

`ArtifactPointer` continues to select one named artifact from one run.
`RunPublicationReceipt` will connect the run's local files to their remote
copies. These objects serve different purposes:

```text
ArtifactPointer
-> selects the artifact a later stage wants to use

RunPublicationReceipt
-> states where VIPER copied the files supporting that run
```

## 4. User interface

### Select remote storage

The project selects one destination in `viper.toml`:

```toml
[storage]
destination = "hf://peter/viper-runs"
```

VIPER treats the repository as a Hugging Face dataset repository. VIPER uses
the account configured by `hf auth login` or the `HF_TOKEN` environment
variable. Tokens stay outside VIPER documents.

The setting controls storage on the machine executing the run. The frozen plan
continues describing the experiment; `viper.toml` describes where this machine
saves the result afterward.

The default destination is local storage.

### Run normally

The existing commands retain their current arguments:

```bash
viper run experiments/example/runs/baseline/run-001/spec.yaml \
  --repository-root .
```

VIPER closes and verifies the run locally. VIPER then synchronizes the terminal
run when `storage.destination` selects Hugging Face.

A successful synchronization writes `publication.yaml` beside
`resolved.yaml`. The receipt records the exact remote location. `resolved.yaml`
continues describing the scientific run and its provenance relationships.

### Retry synchronization

An interrupted upload leaves the verified local run intact. VIPER records the
pending synchronization and returns a distinct `storage_sync_pending` error.
The message includes the path to `resolved.yaml`.

Retry one run:

```bash
viper sync experiments/example/runs/baseline/run-001/resolved.yaml \
  --repository-root .
```

Retry every pending run in the project:

```bash
viper sync --all --repository-root .
```

Re-running `viper sync` uses the same remote root and reuses the existing local
file identities.

### Offload local files

Offload one synchronized run:

```bash
viper offload experiments/example/runs/baseline/run-001/resolved.yaml \
  --repository-root .
```

Offload every synchronized run:

```bash
viper offload --all --repository-root .
```

Preview the affected files:

```bash
viper offload --all --dry-run --repository-root .
```

Preserve selected working files with repeatable `--keep` patterns:

```bash
viper offload --all \
  --keep "artifacts/checkpoints/**" \
  --keep "runs/current/**" \
  --repository-root .
```

Each pattern matches a path relative to the project root. VIPER removes only
files named by a completed `RunPublicationReceipt`. VIPER preserves
`spec.yaml`, `resolved.yaml`, `publication.yaml`, attempt journals, and source
files.

### Restore a remote run

`viper sync` prints the immutable receipt URI after publication:

```text
hf://peter/viper-runs@<commit>/runs/run-001/<resolved-run-sha256>/publication.yaml
```

Restore the run on another machine:

```bash
viper restore \
  "hf://peter/viper-runs@<commit>/runs/run-001/<digest>/publication.yaml" \
  --repository-root .
```

`restore` downloads the receipt, recreates the recorded project-relative
paths, checks every file, and leaves the run ready for `viper verify-run`.

## 5. Contract models

`StorageSettings` represents the local `viper.toml` setting. It is runtime
configuration, so it remains outside the formal provenance protocol.

```python
@dataclass(frozen=True)
class StorageSettings:
    destination: str = "local"
```

`PublishedFile` records one local path and its exact remote copy:

```python
class PublishedFile(ProtocolModel):
    path: RepoRelPath
    role: Literal["artifact", "immutable_store", "control"]
    sha256: SHA256
    bytes: int = Field(ge=0)
    stored_at: HuggingFaceFileRef
```

The three `role` values form the offload policy:

- `artifact` identifies a stage output at its declared project path.
- `immutable_store` identifies a file beneath `.viper/store/<commit>/`.
- `control` identifies a plan, terminal document, attempt document, journal,
  measurement, log, or publication manifest.

`RunPublicationReceipt` records one completed synchronization:

```python
class RunPublicationReceipt(ProtocolModel):
    schema_version: Literal[1] = 1
    run_id: RunId
    resolved_run_path: RepoRelPath
    resolved_run_sha256: SHA256
    repository: NonEmptyStr
    repo_type: Literal["dataset"] = "dataset"
    files: tuple[PublishedFile, ...] = Field(min_length=1)
    published_at: AwareDatetime
```

The receipt is valid when:

```text
PublishedFile.path values are unique and ordered

sha256(local bytes at PublishedFile.path)
== PublishedFile.sha256

len(local bytes at PublishedFile.path)
== PublishedFile.bytes

PublishedFile.stored_at.repository
== RunPublicationReceipt.repository

PublishedFile.stored_at.repo_type
== RunPublicationReceipt.repo_type
```

Every `PublishedFile.stored_at` contains the full Hugging Face commit returned
after the upload containing that file.

## 6. Execution

### Build the publication

After VIPER writes terminal `resolved.yaml`, the synchronization coordinator
performs this sequence:

```text
resolved.yaml
-> traverse each referenced local immutable revision
-> add the run's control files and declared artifact paths
-> hash every selected local file
-> write one pending publication manifest
-> upload the selected files beneath a content-derived remote root
-> receive the immutable Hugging Face commit
-> construct RunPublicationReceipt
-> write publication.yaml locally
-> upload publication.yaml
-> mark the pending publication complete
```

The remote root is:

```text
runs/<run_id>/<resolved_run_sha256>/
```

The root prevents two different terminal results with the same `run_id` from
sharing a path.

The uploader sends repository-relative paths beneath that root. A local file at

```text
.viper/store/<local_commit>/experiments/example/artifacts/weights.bin
```

is stored remotely at

```text
runs/run-001/<resolved_run_sha256>/files/
.viper/store/<local_commit>/experiments/example/artifacts/weights.bin
```

The displayed lines join into one stored path.

Hugging Face's `upload_folder()` operation handles folder uploads and supports
retry by re-running the upload. VIPER records the final commit returned by that
operation. See [Hugging Face's upload guide](https://huggingface.co/docs/huggingface_hub/en/guides/upload).

### Record pending work

Before the first network request, VIPER writes:

```text
.viper/publications/pending/<run_id>-<resolved_run_sha256>.yaml
```

The pending document contains the destination, remote root, local file paths,
byte counts, and digests. `viper sync` reads this document and repeats the same
upload. Successful synchronization moves the document to:

```text
.viper/publications/complete/<run_id>-<resolved_run_sha256>.yaml
```

The completed document is the local `RunPublicationReceipt` index entry used by
offload and restore.

### Read an offloaded file

`LocalArtifactStore.fetch()` retains its current fast path. When the local file
is absent, the store looks for a completed publication containing the exact
repository-relative store path. VIPER downloads `PublishedFile.stored_at` and
checks `PublishedFile.sha256` and `PublishedFile.bytes` before returning the
bytes.

The fallback preserves the existing `LocalFileRef` and `resolved.yaml`. The
local reference identifies the same content-addressed path;
`RunPublicationReceipt` supplies the alternate place from which VIPER can
recover its bytes.

Hugging Face supports downloading one file at an exact commit through
`hf_hub_download(..., revision=<commit>)`. See [Hugging Face's download guide](https://huggingface.co/docs/huggingface_hub/en/guides/download).

## 7. Persisted evidence

The feature writes two durable documents:

| Document | Writer | Purpose |
| --- | --- | --- |
| Pending publication | Synchronization coordinator | Preserve the exact upload after a network or process failure |
| `RunPublicationReceipt` | Synchronization coordinator | Connect every eligible local file to its exact Hugging Face copy |

The remote repository stores the uploaded files and `publication.yaml` at
exact commits. The local run remains complete when synchronization fails.

## 8. Verification rules

Each rule receives a stable error code.

### `storage.destination`

`load_storage_settings()` accepts `local` or `hf://<owner>/<repository>`.
VIPER rejects an empty repository name, URL query, fragment, embedded
credentials, or additional `[storage]` keys.

### `storage.publication.complete`

`viper offload` requires a completed `RunPublicationReceipt` for every selected
run. A pending or missing receipt produces `storage_publication_incomplete` and
preserves every local file.

### `storage.publication.identity`

For every `PublishedFile`, the synchronizer requires the recorded byte count
and digest to equal the local bytes selected for upload.

### `storage.remote.identity`

After a remote file is downloaded, VIPER requires:

```text
len(downloaded bytes) == PublishedFile.bytes

sha256(downloaded bytes) == PublishedFile.sha256
```

A mismatch produces `storage_remote_identity_mismatch`.

### `storage.offload.scope`

`viper offload` selects files from completed receipts. The command removes
files whose role is `artifact` or `immutable_store`. It preserves every
`control` file and every path matched by `--keep`.

The command removes a local immutable revision directory only when the receipt
covers every regular file in that revision. A partial match leaves the complete
revision in place.

### `storage.restore.path`

`viper restore` resolves every destination beneath the selected repository
root. Parent traversal, absolute paths, symbolic links, and overlapping file
and directory targets produce `storage_restore_unsafe_path`.

## 9. Propagation

| Surface | Required change |
| --- | --- |
| Configuration | Load `[storage].destination` from repository-root `viper.toml`; default to `local` |
| Types | Add `PublishedFile` and `RunPublicationReceipt` to `viper.storage` |
| Runner | Start automatic synchronization after terminal local publication and verification |
| Persistence | Write pending and completed publication documents beneath `.viper/publications/` |
| Retrieval | Let `LocalArtifactStore.fetch()` recover a missing local file through a completed receipt |
| Application API | Add typed `sync`, `offload`, and `restore` requests, successes, and failures |
| CLI | Add `viper sync`, `viper offload`, and `viper restore` with JSON results and stable exit behavior |
| Verification | Apply the identity, scope, and path rules defined above |
| Protocol | Document `RunPublicationReceipt`; keep `ArtifactPointer`, `LocalFileRef`, and `ResolvedRun` unchanged |
| Documentation | Explain configuration, automatic synchronization, retry, offload, and restore in the README and API reference |

## 10. Acceptance cases

### Complete remote lifecycle

One focused integration case performs this sequence with a controlled fake Hub
client:

```text
run-001 completes and verifies locally
-> automatic synchronization uploads its required files
-> publication.yaml records exact remote commits
-> viper offload removes synchronized artifact and store files
-> verification fetches the missing bytes through publication.yaml
-> viper restore reconstructs the same paths in a clean directory
-> verify-run accepts the restored run
```

The test asserts byte-for-byte equality between the original files and the
restored files.

### Interrupted publication

The fake Hub client raises an upload error after VIPER writes the pending
publication. The test requires:

```text
resolved.yaml remains present
local artifact and store files remain present
viper offload rejects the run with storage_publication_incomplete
viper sync retries the pending publication
publication.yaml records the successful retry
```

These two cases establish the complete connector and its safety boundary.
Existing verifier tests continue covering digest mismatch for individual
`HuggingFaceFileRef` values.

## 11. Master execution checklist

### Terminal outcome

The feature is complete when this user path succeeds:

```text
[storage].destination = "hf://peter/viper-runs"
-> viper run
-> automatic remote publication
-> viper offload --all --keep <pattern>
-> verification retrieves an offloaded file
-> viper restore on a clean machine
-> verify-run accepts the restored run
```

### Checklist semantics

A checkbox closes after the named code exists and the phase's focused gate
passes. Complete phases in order. Each commit boundary must leave the repository
internally consistent.

### Coverage

| Work unit | Current state | Owning phase | Completion evidence |
| --- | --- | --- | --- |
| Existing local publication | Implemented | Baseline | `tests/test_storage.py` |
| Existing remote retrieval | Implemented | Baseline | Hugging Face verifier tests |
| Storage configuration | Pending | Phase 1 | Storage-settings tests |
| Publication models | Pending | Phase 1 | Model and serialization tests |
| Remote upload and receipt | Pending | Phase 2 | Synchronization integration test |
| Automatic synchronization | Pending | Phase 3 | Run integration test |
| Manual retry | Pending | Phase 3 | Interrupted-publication test |
| Safe offload | Pending | Phase 4 | Offload scope assertions |
| Remote fallback and restore | Pending | Phase 4 | Clean-directory restoration assertions |
| Public API and documentation | Pending | Phase 5 | CLI/API tests and documentation checks |

### Verified baseline

- [x] `LocalArtifactStore.publish()` derives one content identity and writes an
      immutable revision beneath `.viper/store/`.
- [x] `ResolvedFileRef` records a byte count, SHA-256 digest, and one
      `StorageRef`.
- [x] `fetch_huggingface_file_bytes()` downloads a file at the commit stored in
      `HuggingFaceFileRef`.
- [x] `ArtifactPointer` selects one artifact from one resolved run.
- [ ] The current environment lacks the project `.venv`; implementation gates
      require the setup procedure in `CONTRIBUTING.md` before execution.

### Phase 1. Configuration and documents

**Depends on:** verified baseline.

- [ ] Add `StorageSettings` and `load_storage_settings()` to
      `viper.storage`.
- [ ] Reject malformed destinations and unknown `[storage]` keys.
- [ ] Add `PublishedFile` and `RunPublicationReceipt` with the invariants in
      this contract.
- [ ] Add canonical YAML serialization coverage for the receipt.

**Acceptance gate**

```bash
python -m pytest tests/test_storage.py -q
```

**Commit boundary:** storage configuration and receipt models.

### Phase 2. Remote publication

**Depends on:** Phase 1.

- [ ] Add one internal Hugging Face publisher that accepts the selected local
      paths and returns exact `HuggingFaceFileRef` values.
- [ ] Write the pending publication before the first upload request.
- [ ] Write `publication.yaml` and the completed publication index after the
      Hub returns the commit.
- [ ] Keep authentication in the standard Hugging Face credential store or
      `HF_TOKEN`.

**Acceptance gate**

```bash
python -m pytest tests/test_storage_sync.py -q -k publication
```

**Commit boundary:** explicit synchronization produces one complete receipt.

### Phase 3. Automatic synchronization and retry

**Depends on:** Phase 2.

- [ ] Invoke synchronization after the runner writes the terminal local run.
- [ ] Return `storage_sync_pending` with the completed run path when upload
      fails.
- [ ] Add `sync` to the application API and CLI.
- [ ] Let `viper sync <resolved.yaml>` retry one pending publication.
- [ ] Let `viper sync --all` retry every pending publication.

**Acceptance gate**

```bash
python -m pytest tests/test_storage_sync.py -q
```

**Commit boundary:** normal runs synchronize automatically and interrupted
uploads resume while retaining completed stages.

### Phase 4. Offload, fallback, and restore

**Depends on:** Phase 3.

- [ ] Add `offload` to the application API and CLI with path or `--all` scope.
- [ ] Add repeatable `--keep` patterns and `--dry-run` output.
- [ ] Require a completed receipt before removing any selected file.
- [ ] Preserve every control file and partially covered immutable revision.
- [ ] Add remote fallback to `LocalArtifactStore.fetch()`.
- [ ] Add `restore` to retrieve and validate one immutable publication URI.

**Acceptance gate**

```bash
python -m pytest tests/test_storage_offload.py -q
```

**Commit boundary:** synchronized runs can release local space and recover the
same verified bytes.

### Phase 5. Public surface

**Depends on:** Phase 4.

- [ ] Add `sync`, `offload`, and `restore` to capability discovery and JSON
      Schema discovery.
- [ ] Add concise CLI help and machine-readable results for each operation.
- [ ] Update `docs/reference/protocol.md` with `RunPublicationReceipt`.
- [ ] Update `docs/reference/api.md`, the README, and the getting-started guide
      with the commands defined here.
- [ ] Update the `viper.storage` module description to cover local and remote
      publication.

**Acceptance gate**

```bash
python -m pytest tests/test_cli.py tests/test_application.py \
  tests/test_documentation.py -q
```

**Commit boundary:** the installed interface and public documentation expose
the completed storage workflow.

### Integration gate

```bash
python -m pytest tests/test_storage.py tests/test_storage_sync.py \
  tests/test_storage_offload.py tests/test_run_execution.py \
  tests/test_cli.py tests/test_application.py -q
```

The integration gate covers the modules changed by this contract. The package
release gate remains separate until this feature enters a release.

### Owner action

Peter supplies a Hugging Face dataset repository with write access and
authenticates the test account before any optional live-Hub smoke test. The
controlled fake client closes the implementation contract using local test
credentials.

### Deferred work

| Item | Concrete value | Scope basis |
| --- | --- | --- |
| Additional hosting providers | Use the same publication contract with another service | Hugging Face closes the approved user path |
| Background upload daemon | Continue uploads after the initiating process exits | `viper sync` provides deterministic recovery |
| Automatic deletion after synchronization | Free space as part of `viper sync` | Explicit `viper offload` preserves user control |
| Provider durability monitoring | Alert when a remote repository becomes unavailable | Retrieval verifies files when VIPER uses them |

## Implementation sources

- [Local store implementation](../../src/viper/storage.py)
- [Storage reference models](../../src/viper/references.py)
- [Run execution coordinator](../../src/viper/execution/_attempt.py)
- [Hugging Face retrieval](../../src/viper/_verification/storage.py)
- [Artifact pointer contract](../../src/viper/artifacts.py)
- Hugging Face, [Upload files to the Hub](https://huggingface.co/docs/huggingface_hub/en/guides/upload)
- Hugging Face, [Download files from the Hub](https://huggingface.co/docs/huggingface_hub/en/guides/download)
