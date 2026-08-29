# Direct Viper Cloud publication

VIPER publishes immutable provenance evidence after it captures and verifies
each file. This contract adds an opt-in Viper Cloud destination. With that
destination selected, VIPER streams verified files from their declared working
paths into a cloud snapshot and skips the duplicate payload write beneath
`.viper/store`.

The user still controls every declared artifact path. A training stage can
write model weights wherever its frozen `ArtifactSpec.path` says. Storage
configuration chooses where VIPER publishes the immutable evidence for those
bytes.

## 1. Status

**Contract status:** proposed direct-publication contract; implementation
pending.

The current implementation publishes immutable files through
`LocalArtifactStore`. It already separates two identities:

- `SnapshotFileRef` identifies one file inside a completed stage snapshot.
- `ResolvedStageRef.snapshot` identifies the snapshot that contains that file.

The target retains those roles and adds Viper Cloud variants for the storage
locations. It removes the proposed run-level synchronization layer. Each
persisted reference identifies its own storage location.

The four storage-related contracts divide ownership as follows:

| Contract | Owned decision |
| --- | --- |
| [`download-retrieval-artifacts.md`](download-retrieval-artifacts.md) | One successful HTTP body becomes the same-named single-file artifact through one shared `SnapshotFileRef`. |
| [`external-input-roots.md`](external-input-roots.md) | Local files and HTTP responses use source-specific root records; later stages select artifacts through `FutureInputRef` or `StoredInputRef`. |
| [`automatic-input-resolution.md`](automatic-input-resolution.md) | Python authoring compiles local files, same-run handles, and prior-run selections into frozen input references. |
| This contract | Every immutable file and stage snapshot publishes directly to the configured local or Viper Cloud destination. |

## 2. Required claim

When a project selects Viper Cloud, VIPER publishes each completed stage
snapshot directly from the files the stage wrote. VIPER records the returned
cloud snapshot in `ResolvedStageRef.snapshot`. Every file reference retains its
repository-relative path, SHA-256 digest, and byte count.

The guarantee covers exact byte identity and durable retrieval:

```text
declared working file
-> verified path, SHA-256 digest, and byte count
-> immutable publication at the configured destination
-> persisted reference to that destination
-> retrieval through the persisted reference
-> repeated SHA-256 and byte-count verification
```

Storage placement leaves the frozen run plan unchanged. The same stage,
parameters, inputs, artifact declarations, and output paths execute in both
storage modes.

## 3. Current gap

### Fixed scenario

A training stage declares this artifact:

```text
experiments/tiny/runs/baseline/<run-id>/artifacts/model/parameters.bin
```

The stage writes 400 MiB of model weights at that path and exits successfully.

### Current local path

The attempt executor performs this sequence:

```text
stage writes parameters.bin
-> execute_stage_process() checks the declared output
-> _resolve_artifact() hashes the file
-> _execute_attempt() reads the entire file into memory
-> LocalArtifactStore.snapshot() writes a second copy beneath .viper/store
-> ResolvedStageRef.snapshot records LocalStageResultSnapshotRef
```

[`_resolve_artifact()`](../../src/viper/execution/_stage.py) creates the
`SnapshotFileRef`. [`_execute_attempt()`](../../src/viper/execution/_attempt.py)
collects the resolved stage document and artifact bytes.
[`LocalArtifactStore.snapshot()`](../../src/viper/storage.py) publishes the
immutable local snapshot.

### Missing connector

The current snapshot call accepts a mapping of paths to in-memory bytes and
always returns a local snapshot reference. Direct cloud publication needs one
destination-aware publisher that accepts file paths as sources, streams those
files, seals the snapshot, and returns the matching snapshot-reference
variant.

The target cloud path is:

```text
stage writes parameters.bin at its declared path
-> stage exits successfully
-> VIPER hashes and validates parameters.bin
-> Viper Cloud publisher streams parameters.bin from that path
-> Viper Cloud atomically seals the stage snapshot
-> ResolvedStageRef.snapshot records ViperCloudStageResultSnapshotRef
-> attempt execution continues
```

The cloud path bypasses the immutable payload write beneath `.viper/store`.
It preserves the declared working file for the user and for recovery from a
publication failure.

## 4. Storage configuration

### 4.1 Public configuration

One field selects the immutable publication destination:

```toml
[storage]
destination = "local"
```

`local` publishes immutable evidence beneath `.viper/store`.

```toml
[storage]
destination = "viper://machina/weekend_models"
```

The Viper Cloud URI contains:

```text
scheme:   viper
owner:    machina
project:  weekend_models
```

It means: publish immutable evidence directly into the
`machina/weekend_models` cloud namespace. The URI controls immutable storage;
each `ArtifactSpec.path` continues to control the user’s working output path.

An absent `[storage]` table has the same effect as `destination = "local"`.
The single destination field replaces separate placement, mirror, sync, and
offload modes.

### 4.2 Parsed configuration

The parser converts the public string into this internal union:

```python
class LocalStorageDestination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["local"] = "local"


class ViperCloudDestination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["viper_cloud"] = "viper_cloud"
    owner: HumanId
    project: HumanId


StorageDestination = Annotated[
    LocalStorageDestination | ViperCloudDestination,
    Field(discriminator="kind"),
]


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: StorageDestination = Field(
        default_factory=LocalStorageDestination
    )
```

Authentication comes from the active Viper CLI session. Credentials stay out
of `viper.toml`, frozen plans, resolved records, logs, and cloud URIs.

## 5. Storage reference models

### 5.1 Independent cloud file

`ViperCloudFileRef` locates one independently published immutable file:

```python
class ViperCloudFileRef(ProtocolModel):
    kind: Literal["viper_cloud"] = "viper_cloud"
    owner: HumanId
    project: HumanId
    revision: SHA256
    path: RepoRelPath
```

`ResolvedFileRef` retains the byte identity:

```python
class ResolvedFileRef(ProtocolModel):
    sha256: SHA256
    bytes: int
    stored_at: StorageRef
```

The cloud location joins with that identity as follows:

```text
ResolvedFileRef.sha256
ResolvedFileRef.bytes
ResolvedFileRef.stored_at = ViperCloudFileRef(...)
```

Invocation receipts, captured local roots, generated artifact-pointer
documents, logs, metrics, attempts, and the terminal resolved run use this
independent-file path when they live outside a stage snapshot.

### 5.2 Cloud stage snapshot

`ViperCloudStageResultSnapshotRef` locates one sealed stage snapshot:

```python
class ViperCloudStageResultSnapshotRef(ProtocolModel):
    kind: Literal["viper_cloud"] = "viper_cloud"
    owner: HumanId
    project: HumanId
    revision: SHA256
```

The stage snapshot union becomes:

```python
StageResultSnapshot = Annotated[
    LocalStageResultSnapshotRef
    | HuggingFaceStageResultSnapshotRef
    | ViperCloudStageResultSnapshotRef,
    Field(discriminator="kind"),
]
```

The active Python class named `StageResultSnapshotRef` contains Hugging Face
fields and `kind="huggingface"`. Rename that class to
`HuggingFaceStageResultSnapshotRef`. Preserve its serialized fields and
discriminator so existing records retain their meaning.

The general storage union becomes:

```python
StorageRef = Annotated[
    GitFileRef
    | HuggingFaceFileRef
    | LocalFileRef
    | ViperCloudFileRef,
    Field(discriminator="kind"),
]
```

### 5.3 Snapshot-scoped file identity

`SnapshotFileRef` remains independent of the storage provider:

```python
class SnapshotFileRef(ProtocolModel):
    path: RepoRelPath
    sha256: SHA256
    bytes: int
```

It identifies a file relative to the enclosing `ResolvedStageRef.snapshot`.
The pair forms the complete retrieval address:

```text
ResolvedStageRef.snapshot
+ SnapshotFileRef.path
-> immutable file bytes
```

The digest and byte count verify those bytes after retrieval.

### 5.4 Terminal run handle

The terminal `resolved.yaml` is an independently published file. Its existing
`ResolvedRunRef` becomes the restore handle:

```python
class ResolvedRunRef(ResolvedFileRef):
    kind: Literal["resolved_run"] = "resolved_run"
```

`RunResult` returns that handle with the local control paths:

```python
class RunResult(BaseModel):
    resolved_run: ResolvedRun
    resolved_run_ref: ResolvedRunRef
    resolved_run_path: Path
    journal_path: Path
```

In cloud mode, `resolved_run_ref.stored_at` is a `ViperCloudFileRef`. The CLI
can print an immutable restore URI from that reference. Every retrieval
relationship already exists in the terminal run graph, so the model ends at
`ResolvedRunRef`.

## 6. Publication interface

### 6.1 Sources

The publisher accepts generated bytes and existing files:

```python
PublicationSource = bytes | Path
```

- `bytes` serves small documents that VIPER has already serialized in memory.
- `Path` serves stage outputs and other existing files. A cloud publisher
  streams from that path and avoids a second full in-memory copy.

Every source is paired with its repository-relative destination path. Before
publication, VIPER checks that each `Path` remains beneath the repository
root, names a regular file, and matches its resolved digest and byte count.

### 6.2 Destination-aware operations

Two operations own immutable publication:

```python
def publish_stage_snapshot(
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> StageResultSnapshot: ...


def publish_resolved_files(
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> tuple[ResolvedFileRef, ...]: ...
```

The local implementation delegates to `LocalArtifactStore`. The cloud
implementation uploads each source, seals one immutable revision, and returns
`ViperCloudFileRef` or `ViperCloudStageResultSnapshotRef` values.

The stage executor uses this call:

```python
snapshot = snapshot_publisher.publish(
    resolved_stage=resolved_raw,
    artifacts=artifact_paths,
)
```

`resolved_stage` supplies the serialized `resolved.yaml` bytes.
`artifact_paths` maps each declared artifact path to the existing working
`Path`. The publisher computes one manifest, uploads each unique path once,
and returns the sealed snapshot reference.

Independent evidence uses `publish_resolved_files()`. The caller copies each
returned `sha256`, `bytes`, and `stored_at` value into the specific subtype it
owns, such as `ResolvedStageInvocationRef`, `ResolvedExternalInputRef.file`,
`ResolvedArtifactPointerRef`, or `ResolvedRunRef`.

## 7. Stage execution

### 7.1 Successful project stage

For the fixed model-weight scenario:

```text
1. The worker writes parameters.bin at ArtifactSpec.path.
2. The worker exits successfully.
3. VIPER confirms the declared file exists.
4. VIPER computes its SHA-256 digest and byte count.
5. VIPER builds ResolvedSingleFileArtifact with SnapshotFileRef.
6. VIPER serializes the completed resolved stage document.
7. The publisher streams parameters.bin from its working path.
8. The publisher uploads the resolved stage document.
9. The publisher atomically seals the snapshot manifest.
10. The publisher returns ViperCloudStageResultSnapshotRef.
11. VIPER constructs ResolvedStageRef(snapshot=<returned reference>).
12. The attempt records the completed stage and continues.
```

Stage completion occurs at step 11. A successful worker process alone proves
that the user code finished. The `ResolvedStageRef` proves that VIPER also
published the resulting evidence.

### 7.2 Download stage

The download contract gives the HTTP receipt and artifact one shared
`SnapshotFileRef`:

```text
HTTP transport writes response into attempt scratch space
-> runner verifies the body
-> runner moves or writes the body at the declared artifact path
-> ResolvedHttpRetrieval.body receives SnapshotFileRef
-> ResolvedSingleFileArtifact.file receives the same SnapshotFileRef
-> publisher streams that declared path once
-> publisher seals the download-stage snapshot
```

`ResolvedHttpRetrieval` remains the external-input-root record.
`ResolvedSingleFileArtifact` remains the artifact view. Cloud publication
changes the enclosing snapshot location and leaves those provenance roles
unchanged.

### 7.3 Independent evidence

Evidence created outside a completed stage snapshot publishes when VIPER
creates it:

```text
capture local external input
-> publish captured bytes through publish_resolved_files()
-> ResolvedExternalInputRef.file records the returned storage location

generate ArtifactPointer for a prior-run selection
-> publish pointer document through publish_resolved_files()
-> StoredInputRef.pointer records the returned storage location

complete terminal ResolvedRun
-> publish resolved.yaml through publish_resolved_files()
-> RunResult.resolved_run_ref records the returned storage location
```

All reachable immutable evidence therefore self-locates. Restore and
verification follow the references stored in the protocol graph.

## 8. Atomicity, failure, and recovery

### 8.1 Deterministic revision

The publisher derives the revision from the canonical snapshot manifest. The
manifest contains every repository-relative path, SHA-256 digest, and byte
count in sorted path order. The resulting digest serves as both immutable
revision and idempotency key.

Publishing the same manifest again targets the same revision. A retry can skip
objects the service already accepted.

### 8.2 Atomic seal

Uploads remain provisional until the service accepts the complete manifest.
Retrieval exposes a revision only after the seal operation succeeds. A
partially uploaded snapshot therefore remains unreachable through a
`ViperCloudStageResultSnapshotRef`.

### 8.3 Failed publication

When cloud publication fails after a worker succeeds:

```text
declared working artifacts remain in place
attempt workspace remains in place
journal records publishing_stage failure
ResolvedStageRef is absent
attempt stops before dependent stages execute
```

The next execution resumes publication from the same verified working paths.
It reruns the stage only when those files are absent or fail their recorded
identity checks.

The stable failure codes are:

| Code | Condition |
| --- | --- |
| `storage_authentication_failed` | The active Viper session lacks publication authority for the configured owner and project. |
| `storage_source_invalid` | A publication source escapes the repository, is missing, is a symbolic link, or names a non-regular file. |
| `storage_source_identity_mismatch` | A source differs from its expected SHA-256 digest or byte count. |
| `storage_upload_failed` | Object transfer fails before sealing. |
| `storage_seal_failed` | The service rejects or fails to seal the complete manifest. |
| `storage_remote_identity_mismatch` | Retrieved bytes differ from the persisted digest or byte count. |
| `storage_destination_changed` | A later attempt selects a different destination from the run’s first immutable publication. |
| `storage_graph_unreachable` | A Viper Cloud terminal graph reaches machine-local immutable evidence. |

### 8.4 Destination stability

The first immutable publication for a run fixes its storage destination. Every
retry and later attempt uses the same destination. Changing `viper.toml` during
that run produces `storage_destination_changed` before VIPER starts new stage
work.

## 9. Local control and recovery evidence

Cloud mode retains mutable execution control state on the machine running the
attempt:

```text
.viper/workspaces/<run-id>/<attempt-id>/
.viper/journals/<run-id>/<attempt-id>.jsonl
canonical terminal resolved.yaml at the run path
user-declared artifact paths
```

These files support process coordination, failure diagnosis, and publication
retry. They are distinct from the immutable evidence graph.

The local destination publishes immutable evidence beneath `.viper/store`.
The Viper Cloud destination publishes immutable evidence to the cloud and
places zero payload copies beneath `.viper/store`. User-declared output files
and attempt recovery files remain in place.

## 10. Retrieval, verification, and restore

### 10.1 Stage file retrieval

The verifier receives a `ResolvedStageRef` and one `SnapshotFileRef`:

```text
ResolvedStageRef.snapshot.kind == "local"
-> LocalArtifactStore retrieves snapshot revision + file path

ResolvedStageRef.snapshot.kind == "huggingface"
-> Hugging Face fetcher retrieves repository + commit + file path

ResolvedStageRef.snapshot.kind == "viper_cloud"
-> Viper Cloud client retrieves owner + project + revision + file path
```

After retrieval, the verifier checks:

```text
len(bytes) == SnapshotFileRef.bytes
sha256(bytes) == SnapshotFileRef.sha256
```

### 10.2 Independent file retrieval

`RunFetcher` routes each `ResolvedFileRef.stored_at` variant to its owning
backend. A `ViperCloudFileRef` contains every value needed for that route. The
fetcher applies the enclosing `ResolvedFileRef` digest and byte-count checks.

### 10.3 Cloud graph reachability

A Viper Cloud terminal run must remain retrievable from another machine. Before
publishing the terminal `ResolvedRun`, VIPER follows its attempt, stage,
independent-file, input, and artifact references.

The accepted storage locations are:

```text
ViperCloudFileRef
ViperCloudStageResultSnapshotRef
HuggingFaceFileRef
HuggingFaceStageResultSnapshotRef
GitFileRef
```

Reaching `LocalFileRef` or `LocalStageResultSnapshotRef` produces
`storage_graph_unreachable`. The run keeps its local recovery files and stops
before terminal cloud publication.

This rule applies when a cloud run selects an artifact from an earlier local
run. VIPER asks the user to publish or migrate that producer through a separate
workflow. Producer-run migration remains an explicit operation outside
consumer freezing.

### 10.4 Restore

The run command returns and prints the terminal `ResolvedRunRef`. Its cloud
form can be represented as:

```text
viper://machina/weekend_models@<revision>/<path-to-resolved.yaml>
```

Restore performs this sequence:

```text
parse immutable terminal-run URI
-> retrieve terminal resolved.yaml
-> check ResolvedRunRef digest and byte count
-> parse ResolvedRun
-> follow attempt, stage, snapshot, input, and artifact references
-> retrieve each selected file from the backend named by its reference
-> recreate requested repository-relative working paths
-> verify every retrieved file
```

Restore starts from `ResolvedRunRef`; the terminal run and all reachable
references carry their own locations.

## 11. Public workflow

### Local immutable publication

```toml
[storage]
destination = "local"
```

```bash
viper run experiments/tiny/runs/baseline/<run-id>/spec.yaml \
  --repository-root .
```

The command returns a `ResolvedRunRef` whose `stored_at` value is a
`LocalFileRef`.

### Direct Viper Cloud publication

```toml
[storage]
destination = "viper://machina/weekend_models"
```

```bash
viper run experiments/tiny/runs/baseline/<run-id>/spec.yaml \
  --repository-root .
```

The stage writes its normal local output files. VIPER streams each completed
snapshot directly to Viper Cloud. The command returns a `ResolvedRunRef` whose
`stored_at` value is a `ViperCloudFileRef`.

```bash
viper restore \
  "viper://machina/weekend_models@<revision>/<path-to-resolved.yaml>" \
  --repository-root restored-project
```

## 12. Propagation and legacy cleanup

### 12.1 Required changes

| Surface | Required change |
| --- | --- |
| Configuration | Parse one `[storage].destination` value into `LocalStorageDestination` or `ViperCloudDestination`. |
| File references | Add `ViperCloudFileRef` to `StorageRef`. |
| Snapshot references | Add `ViperCloudStageResultSnapshotRef`; rename the Python Hugging Face snapshot class while preserving its serialized form. |
| Publication | Replace hard-coded local publication calls with destination-aware `publish_stage_snapshot()` and `publish_resolved_files()`. |
| Stage execution | Pass resolved-stage bytes and declared artifact paths to the snapshot publisher after artifact validation. |
| Download execution | Publish the shared retrieval/artifact path once in the configured stage snapshot. |
| Local roots | Publish captured bytes through the configured independent-file publisher. |
| Pointer generation | Publish generated `ArtifactPointer` documents through the configured independent-file publisher. |
| Terminal run | Publish terminal `resolved.yaml` and return `RunResult.resolved_run_ref`. |
| Retrieval | Route Viper Cloud file and snapshot variants through the cloud client. |
| Recovery | Resume an unsealed stage publication from verified working paths before rerunning the stage. |
| CLI | Print the terminal run reference and add restore from an immutable Viper Cloud URI. |
| Verification | Apply existing path, digest, and byte-count rules to both destination variants. |

### 12.2 Removed design

Delete these proposed concepts from the implementation plan and documentation:

| Removed concept | Replacement |
| --- | --- |
| `RunSyncState` | `ResolvedRunRef` locates the terminal run; every reachable reference locates its own evidence. |
| `.viper/sync/` | `ResolvedRunRef` serves as the terminal restore handle. |
| `viper sync` | Failed stage publication resumes during run retry. |
| `viper offload` | Cloud mode bypasses local immutable payload publication from the start. |
| Terminal-run closure upload | Evidence publishes at the stage or independent-file boundary where VIPER captures it. |
| Remote fallback for missing `LocalFileRef` bytes | Cloud-published records contain `ViperCloudFileRef` directly. |
| Staged Hugging Face directory upload | The Viper Cloud publisher streams declared paths and seals a manifest. |
| Mirrored local-and-remote payload mode | One configured destination owns each new immutable publication. |

Existing `HuggingFaceFileRef` and Hugging Face stage-snapshot records remain
valid retrieval references. This contract removes the proposed post-run
Hugging Face mirroring workflow. It leaves migration or replication between
storage providers for a separate contract.

## 13. Acceptance cases

### 13.1 Direct cloud model-weight publication

The fixture configures Viper Cloud and runs one training stage:

```text
stage writes parameters.bin at the declared path
-> VIPER creates SnapshotFileRef(path, sha256, bytes)
-> fake cloud publisher receives that same filesystem Path
-> publisher streams the bytes once
-> publisher seals the manifest
-> ResolvedStageRef.snapshot is ViperCloudStageResultSnapshotRef
-> .viper/store contains no parameters.bin payload
-> verifier retrieves the file and accepts its digest and byte count
```

The test also asserts that the declared working `parameters.bin` remains
available after the run.

### 13.2 Local publication compatibility

The same frozen run executes with `destination = "local"`:

```text
stage writes parameters.bin
-> local publisher creates LocalStageResultSnapshotRef
-> .viper/store contains the immutable snapshot
-> verifier retrieves and accepts the same bytes
```

The stage specification and artifact path remain identical across both cases.

### 13.3 Failed seal and retry

The fake cloud service accepts artifact objects and rejects the first seal:

```text
working artifacts remain available
ResolvedStageRef remains absent
journal records storage_seal_failed
dependent stage does not start
retry reuses the working paths
retry seals the same deterministic revision
attempt continues
```

### 13.4 Self-contained prior-run selection

A cloud-backed producer run publishes its terminal document, generated pointer
document, stage snapshot, and selected artifact through cloud references. A
later run consumes that artifact through `StoredInputRef`.

```text
StoredInputRef.pointer.stored_at
-> ViperCloudFileRef for ArtifactPointer

ArtifactPointer.run.stored_at
-> ViperCloudFileRef for producer ResolvedRun

producer ResolvedStageRef.snapshot
-> ViperCloudStageResultSnapshotRef
```

Restore and verification succeed on a machine with an empty `.viper/store`.
Removing any referenced cloud object makes the corresponding retrieval fail.

The rejection companion selects a producer whose terminal graph contains a
`LocalFileRef` while the consumer uses Viper Cloud. Freezing produces
`storage_graph_unreachable` before it writes the consumer pointer.

## 14. Implementation order

1. Add destination parsing and exact configuration tests.
2. Add Viper Cloud file and snapshot references, the snapshot-class rename,
   serialization tests, and union round-trip tests.
3. Add the destination-aware publication interface. Adapt
   `LocalArtifactStore` behind the local implementation.
4. Change stage publication to pass artifact paths and stream each payload.
   Add the direct-cloud and local-compatibility cases.
5. Route independent file publication for local roots, generated pointers,
   invocation evidence, attempts, logs, metrics, and terminal runs.
6. Add cloud retrieval and apply existing identity checks.
7. Add seal-failure recovery and deterministic retry.
8. Add destination-stability and cloud-graph-reachability checks.
9. Add terminal-run restore through `ResolvedRunRef`.
10. Remove every sync-state, closure-upload, offload, and remote-fallback design
   reference from the repository.
11. Update the public README after the complete cloud acceptance path passes.

## 15. Invariants

The implementation is complete when all of these statements hold:

```text
one immutable publication has one configured destination

user-declared artifact paths remain unchanged by storage placement

cloud-backed stage payloads bypass .viper/store

SnapshotFileRef identifies bytes inside one enclosing stage snapshot

ResolvedStageRef.snapshot identifies that snapshot's storage location

ResolvedFileRef.stored_at identifies independently published evidence

ResolvedRunRef identifies the terminal run and starts restore

every persisted reference contains enough information to route retrieval

a Viper Cloud terminal graph reaches zero machine-local immutable references

every retrieved file passes its persisted SHA-256 and byte-count checks

a stage becomes complete after its snapshot is sealed and ResolvedStageRef exists

a failed seal preserves the working files required for retry
```

## Implementation sources

- [Local store implementation](../../src/viper/storage.py)
- [Storage reference schemas](../../src/viper/references.py)
- [Stage artifact resolution](../../src/viper/execution/_stage.py)
- [Attempt publication](../../src/viper/execution/_attempt.py)
- [Run result model](../../src/viper/execution/results.py)
- [Storage retrieval and verification](../../src/viper/_verification/storage.py)
