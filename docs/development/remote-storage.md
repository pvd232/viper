# Remote storage contract and execution checklist

VIPER can copy a completed local run to Hugging Face, release selected local
files, and restore the same run on another machine. This contract defines the
required schema, commands, execution order, and checks.

## 1. Status

**Contract status:** proposed schema revision; implementation pending.

VIPER already has the two file-reference types required by this feature:

- `LocalFileRef` identifies a file in the repository-local immutable store.
- `HuggingFaceFileRef` identifies a file at an exact Hugging Face commit.

`ResolvedFileRef` supplies the expected byte count and SHA-256 digest. The
verifier already checks retrieved bytes against those values. The runner
currently writes completed runs through `LocalArtifactStore`. Remote upload,
retry, offload, and restore remain pending.

This contract adds one persisted document, `RunSyncState`. Existing experiment
documents and artifact pointers retain their current schemas.

## 2. Required claim

When a project configures a Hugging Face destination, VIPER copies every local
file required to restore and verify a terminal run. VIPER records the exact
remote commit and keeps the local files until the user runs `viper offload`.

The guarantee ends at byte identity. VIPER controls the upload and records the
returned commit. On retrieval, VIPER checks every downloaded file against the
byte count and SHA-256 digest already stored in the run.

## 3. Current gap

The current implementation stops between local publication and remote
retrieval:

```text
LocalArtifactStore
-> writes immutable local files

HuggingFaceFileRef
-> identifies one file at an exact remote commit

fetch_huggingface_file_bytes()
-> downloads and verifies that remote file
```

The missing connector is a persisted value that joins one completed local run
to the Hugging Face commit containing its files. Retry, restore, and local
offload all require that exact remote revision.

`ArtifactPointer` has a separate job. It selects one artifact for later use.
The new sync document identifies the remote copy of one complete run.

## 4. Schema changes

### Existing schemas

This feature keeps these persisted types unchanged:

```text
ArtifactPointer
ResolvedRun
ResolvedFileRef
LocalFileRef
HuggingFaceFileRef
StorageRef
```

Each local file in the run remains identified by its existing reference. VIPER
uses the local path, byte count, and SHA-256 digest already stored there.

### New runtime configuration

`viper.toml` gains one optional setting:

```toml
[storage]
destination = "hf://peter/viper-runs"
```

The default value is `local`. The configuration selects where the current
machine copies completed runs. It stays outside the frozen experiment plan
because changing the storage destination leaves the experiment unchanged.
VIPER treats an `hf://` destination as a Hugging Face dataset repository.

### New persisted document

VIPER adds one schema named `RunSyncState`:

```python
class RunSyncState(ProtocolModel):
    schema_version: Literal[1] = 1
    run: ResolvedRunRef
    repository: NonEmptyStr
    commit: GitCommit | None = None
```

The document lives at:

```text
.viper/sync/<resolved_run_sha256>.yaml
```

One completed example is:

```yaml
schema_version: 1
run:
  kind: resolved_run
  sha256: 5ab1d8...
  bytes: 1842
  stored_at:
    kind: local
    store: .viper/store
    commit: 7f64c2...
    path: experiments/example/runs/baseline/run-001/resolved.yaml
repository: peter/viper-runs
commit: c31a76...
```

The type name describes the document's stable role: it stores the current
synchronization state for one terminal run. The type remains internal to the
storage subsystem and is absent from the package-root imports.

`RunSyncState` enforces these rules:

```text
run.stored_at is a LocalFileRef

commit is null
-> synchronization is pending

commit contains a full remote commit hash
-> synchronization is complete

filename
== .viper/sync/<run.sha256>.yaml
```

The run already contains each file's path, byte count, and digest. The sync
document stores only the missing run-to-remote-commit relationship.

Each field has one writer and one use:

| Field | Writer | Consumer |
| --- | --- | --- |
| `schema_version` | Sync-state serializer | Sync-state loader |
| `run` | Synchronization coordinator after local terminal publication | Closure traversal, identity checks, and offload |
| `repository` | Synchronization coordinator from `[storage].destination` | Upload, retrieval, and restore |
| `commit` | Synchronization coordinator after upload | Retrieval, restore, and the offload-completion check |

## 5. User interface

### Automatic synchronization

The normal run command stays the same:

```bash
viper run experiments/example/runs/baseline/run-001/spec.yaml \
  --repository-root .
```

After local verification succeeds, VIPER reads `[storage].destination`. A Hugging
Face destination starts synchronization. The command prints the exact remote
URI when the upload completes:

```text
hf://peter/viper-runs@<commit>/runs/<resolved-run-sha256>/resolved.yaml
```

An upload failure leaves the completed run and every local file in place. The
command reports `storage_sync_pending` and prints the local `resolved.yaml`
path.

### Retry synchronization

Retry one run:

```bash
viper sync experiments/example/runs/baseline/run-001/resolved.yaml \
  --repository-root .
```

Retry every pending run:

```bash
viper sync --all --repository-root .
```

`viper sync` reads the existing `RunSyncState`, rebuilds the same run closure,
and uploads to the same remote root.

### Offload local files

Preview one run:

```bash
viper offload experiments/example/runs/baseline/run-001/resolved.yaml \
  --dry-run \
  --repository-root .
```

Offload every run whose sync state is complete:

```bash
viper offload --all --repository-root .
```

Keep selected payload paths:

```bash
viper offload --all \
  --keep "artifacts/checkpoints/**" \
  --keep "artifacts/models/final/**" \
  --repository-root .
```

Each `--keep` pattern matches a path relative to the project root. VIPER
preserves terminal run documents, sync documents, attempt documents, journals,
and source files. Offload removes synchronized artifact files and their local
immutable-store copies.

### Restore a run

Restore from the URI printed by `viper run` or `viper sync`:

```bash
viper restore \
  "hf://peter/viper-runs@<commit>/runs/<digest>/resolved.yaml" \
  --repository-root .
```

`viper restore` downloads `resolved.yaml`, follows its references, recreates
the recorded repository-relative paths, and checks each restored file. It
publishes the terminal document through `LocalArtifactStore` and reconstructs
`RunSyncState` with the commit from the URI. The restored run is then ready for
`viper verify-run`.

Hugging Face accepts a full commit hash through the `revision` argument to
`hf_hub_download()`. See the official
[download guide](https://huggingface.co/docs/huggingface_hub/en/guides/download).

## 6. Run closure and remote layout

### Run closure

The run closure is the finite set of local files required to restore and
verify one terminal `ResolvedRun`. The synchronization coordinator constructs
the closure by following these existing references:

```text
terminal resolved.yaml
-> ResolvedRun.attempts
-> each RunAttempt
-> resolved stage documents
-> stage invocation receipts
-> journals, logs, measurements, and metric-verification files
-> each local stage snapshot
-> every file in each resolved artifact
```

The closure also contains each declared artifact path. VIPER takes those bytes
from the verified immutable stage snapshot. Git and existing Hugging Face
references remain at their current locations and stay outside the upload set.

Before synchronization, VIPER publishes terminal `resolved.yaml` through
`LocalArtifactStore.resolved_files()`. That operation produces the
`ResolvedRunRef` stored in `RunSyncState.run`.

### Remote layout

The remote root is derived from the terminal run digest:

```text
runs/<RunSyncState.run.sha256>/
```

VIPER writes one bootstrap copy of the terminal document at:

```text
runs/<digest>/resolved.yaml
```

Every file in the run closure keeps its project-relative path beneath:

```text
runs/<digest>/files/<project-relative-path>
```

For example:

```text
local
.viper/store/<local-commit>/experiments/example/artifacts/weights.bin

remote
runs/<digest>/files/.viper/store/<local-commit>/
experiments/example/artifacts/weights.bin
```

The displayed remote lines form one path. This deterministic mapping lets the
retrieval layer derive a remote filename from an existing `LocalFileRef` and a
`RunSyncState` containing a commit.

## 7. Execution

### Start synchronization

After VIPER writes and verifies terminal `resolved.yaml`, the synchronization
coordinator performs this sequence:

```text
publish resolved.yaml in LocalArtifactStore
-> construct ResolvedRunRef
-> write RunSyncState(commit=None)
-> traverse the run closure
-> verify each selected local file against its existing reference
-> stage the files under the deterministic remote layout
-> upload the staged directory
-> receive the final Hugging Face commit
-> write RunSyncState(commit=<returned commit>)
```

VIPER writes the pending document before the first network request. After the
upload returns, VIPER atomically replaces that document with the completed
value.

Hugging Face's `upload_folder()` preserves the staged folder structure and
returns commit information. Re-running an interrupted upload skips content
already committed by the service. See the official
[`upload_folder()` reference](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.upload_folder).

VIPER uses the account configured through `hf auth login` or `HF_TOKEN`.
Authentication values stay outside VIPER documents. See Hugging Face's
[authentication guide](https://huggingface.co/docs/huggingface_hub/en/quick-start#authentication).

### Retrieve an offloaded file

The retrieval coordinator receives `RunSyncState` for the run being verified
or materialized. When a `LocalFileRef` is unavailable and the state contains a
commit, the coordinator performs this lookup:

```text
RunSyncState.repository
+ RunSyncState.commit
+ runs/<run.sha256>/files/
+ LocalFileRef.store/<LocalFileRef.commit>/<LocalFileRef.path>
-> exact Hugging Face file
```

The coordinator downloads that file and applies the byte-count and SHA-256
checks from the existing `ResolvedFileRef` or `SnapshotFileRef`.

`LocalArtifactStore.fetch()` keeps its current local-only contract. The
run-aware retrieval coordinator owns the remote fallback because the
`LocalFileRef` alone lacks the terminal run digest and remote commit.

### Offload local files

`viper offload` first loads a `RunSyncState` containing a remote commit. It
reconstructs the run closure, applies each `--keep` pattern, and presents the
resulting paths during `--dry-run`.

The command removes selected working artifacts. It removes an immutable-store
revision only when every regular file in that revision belongs to the selected
closure and no `--keep` pattern preserves a member. This rule prevents a shared
local revision from becoming incomplete.

Offload keeps the terminal `resolved.yaml`, its immutable local-store revision,
and `RunSyncState` available. Those values provide the remote URI and the entry
point for later retrieval.

## 8. Persisted evidence

The feature adds one durable document:

| Document | Writer | Purpose |
| --- | --- | --- |
| `.viper/sync/<resolved_run_sha256>.yaml` | Synchronization coordinator | Connect one local terminal run to one exact remote commit; a null commit marks pending synchronization |

The remote repository contains the run closure at the commit recorded by a
`RunSyncState`. Restore receives the repository and commit through its URI,
starts from the remote `resolved.yaml`, and recreates the local sync document.

## 9. Verification rules

Each rule receives a stable error code.

### `storage.destination`

`load_storage_settings()` accepts `local` or `hf://<owner>/<repository>`. Empty
repository names, query strings, fragments, embedded credentials, and unknown
`[storage]` keys produce `storage_destination_invalid`.

### `storage.sync.identity`

The sync-state filename must equal:

```text
.viper/sync/<RunSyncState.run.sha256>.yaml
```

VIPER retrieves `RunSyncState.run`, checks its byte count and digest, and parses
the bytes as `ResolvedRun`. A mismatch produces `storage_sync_identity_mismatch`.

### `storage.sync.state`

`commit: null` marks pending synchronization. A full commit hash marks complete
synchronization. Any other value produces `storage_sync_state_invalid`.

### `storage.local.identity`

Before upload, VIPER checks every local file against the existing byte count
and SHA-256 digest in the run closure. A mismatch produces
`storage_local_identity_mismatch` and leaves the sync state pending.

### `storage.remote.identity`

After retrieval, VIPER compares the downloaded bytes with the existing file
reference:

```text
len(downloaded bytes) == reference.bytes

sha256(downloaded bytes) == reference.sha256
```

A mismatch produces `storage_remote_identity_mismatch`.

### `storage.offload.complete`

Offload requires `RunSyncState.commit` to contain a full commit hash. A null or
missing commit produces `storage_sync_incomplete` and preserves every local
file.

### `storage.offload.scope`

Offload removes only paths selected from the verified run closure. A complete
immutable-store revision may be removed after every regular file in that
revision passes the scope check. A partial revision remains intact.

### `storage.restore.path`

Restore resolves each destination beneath the selected repository root.
Absolute paths, parent traversal, symbolic links, and overlapping file and
directory targets produce `storage_restore_unsafe_path`.

## 10. Propagation

| Surface | Required change |
| --- | --- |
| Configuration | Load `[storage].destination` from repository-root `viper.toml`; default to `local` |
| Schema | Add the internal persisted `RunSyncState` schema and canonical sync-state path |
| Local publication | Publish terminal `resolved.yaml` through `LocalArtifactStore` and return a `ResolvedRunRef` |
| Closure traversal | Enumerate every local file reachable from the terminal run and its declared artifacts |
| Remote upload | Upload the staged closure and return the final Hugging Face commit |
| Runner | Start synchronization after terminal local verification |
| Retrieval | Add a run-aware coordinator that resolves missing `LocalFileRef` bytes through `RunSyncState` |
| Application API | Add typed `sync`, `offload`, and `restore` operations |
| CLI | Add `viper sync`, `viper offload`, and `viper restore` with JSON results and stable exit codes |
| Verification | Implement the seven named storage rules above |
| Documentation | Explain configuration, retry, offload, restore, and the new sync document |

## 11. Acceptance cases

Two focused integration cases close the contract.

### Complete remote lifecycle

A controlled fake Hub client returns commit `c31a76...` for `run-001`:

```text
run-001 completes and verifies locally
-> automatic synchronization writes pending RunSyncState
-> upload returns c31a76...
-> RunSyncState becomes complete
-> viper offload removes one synchronized artifact and its store copy
-> verification retrieves the missing bytes from c31a76...
-> the existing digest check accepts the bytes
```

The test asserts that the local and retrieved bytes are identical and that the
complete sync state contains the returned commit.

### Interrupted synchronization

The fake Hub client raises an upload error after VIPER writes pending state:

```text
resolved.yaml remains present
artifact and immutable-store files remain present
RunSyncState remains pending
viper offload returns storage_sync_incomplete
viper sync retries the same run closure
RunSyncState becomes complete after the retry
```

These cases cover the new connector. Existing verifier tests continue covering
digest mismatches for individual `HuggingFaceFileRef` values.

## 12. Master execution checklist

### Terminal outcome

The feature is complete when this path succeeds:

```text
[storage].destination = "hf://peter/viper-runs"
-> viper run
-> automatic synchronization
-> viper offload --all --keep <pattern>
-> verification retrieves an offloaded file
-> viper restore on a clean machine
-> viper verify-run accepts the restored run
```

### Phase 1. Configuration and schema

- [ ] Add `load_storage_settings()`.
- [ ] Add `RunSyncState` under the private storage implementation.
- [ ] Add canonical serialization and state-invariant tests.
- [ ] Publish terminal `resolved.yaml` through `LocalArtifactStore`.

**Focused gate:** storage-settings and sync-state unit tests.

**Commit boundary:** configuration and the one new persisted schema.

### Phase 2. Run closure and synchronization

- [ ] Implement deterministic run-closure traversal.
- [ ] Verify every selected local file before upload.
- [ ] Stage the closure under `runs/<digest>/files/`.
- [ ] Write pending state before the upload request.
- [ ] Upload through the Hugging Face client.
- [ ] Record the final remote commit.

**Focused gate:** complete remote lifecycle through the fake Hub client.

**Commit boundary:** explicit synchronization produces complete state.

### Phase 3. Automatic synchronization and retry

- [ ] Start synchronization after local terminal verification.
- [ ] Preserve the successful local run when upload fails.
- [ ] Report `storage_sync_pending` with the local run path.
- [ ] Add `sync` to the application API and CLI.
- [ ] Support one-run and `--all` retry scopes.

**Focused gate:** interrupted synchronization and successful retry.

**Commit boundary:** normal runs synchronize automatically and failed uploads
resume through `viper sync`.

### Phase 4. Offload and retrieval

- [ ] Add `offload` with one-run, `--all`, `--dry-run`, and repeatable `--keep`
      scopes.
- [ ] Require a recorded remote commit before deleting local payloads.
- [ ] Preserve partial immutable-store revisions.
- [ ] Add run-aware remote fallback to verification and input materialization.
- [ ] Check every downloaded file with its existing reference.

**Focused gate:** offload one payload and retrieve it during verification.

**Commit boundary:** synchronized payloads can leave local storage and return
with the same bytes.

### Phase 5. Restore and public surface

- [ ] Add `restore` for the immutable remote URI.
- [ ] Restore the terminal document before traversing the remaining closure.
- [ ] Reconstruct sync state with the commit from the immutable remote URI.
- [ ] Recreate safe repository-relative paths.
- [ ] Add `sync`, `offload`, and `restore` to capability and schema discovery.
- [ ] Add concise CLI help and machine-readable results.
- [ ] Update the README, API reference, and formal protocol.

**Focused gate:** restore into a clean directory and run `viper verify-run`.

**Commit boundary:** the installed interface exposes the complete workflow.

### Deferred work

| Item | Reason for deferral |
| --- | --- |
| Additional hosting providers | Hugging Face completes the approved first user path |
| Background upload daemon | `viper sync` supplies explicit recovery |
| Automatic deletion after synchronization | `viper offload` keeps deletion under user control |
| Provider availability monitoring | Retrieval checks the provider when VIPER needs the bytes |

## Implementation sources

- [Local store implementation](../../src/viper/storage.py)
- [Storage reference schemas](../../src/viper/references.py)
- [Run schema](../../src/viper/runs.py)
- [Run publication code](../../src/viper/execution/_publication.py)
- [Hugging Face retrieval](../../src/viper/_verification/storage.py)
