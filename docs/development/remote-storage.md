# Direct Viper Cloud publication

VIPER saves copies of the files and records needed to verify a run. The saved
bytes stay fixed. This contract calls that step publication.

Local publication writes the copies beneath `.viper/store`. Viper Cloud
publication uploads them from their working paths. In cloud mode,
`.viper/store` receives zero payload copies.

The user still chooses each working path through `ArtifactSpec.path`. Storage
configuration only chooses where VIPER publishes the immutable copy.

## 1. Status

**Contract status:** proposed direct-publication contract; implementation
pending.

The current implementation writes every immutable copy through
`LocalArtifactStore`. It uses two references:

- `SnapshotFileRef` records a file's path, SHA-256 digest, and byte count.
- `ResolvedStageRef.snapshot` tells VIPER where the enclosing stage snapshot
  lives.

The cloud design keeps that split. It adds references that point to Viper
Cloud. Each saved record tells VIPER where to retrieve its files.

The four storage-related contracts divide ownership as follows:

| Contract | Owned decision |
| --- | --- |
| [`download-retrieval-artifacts.md`](download-retrieval-artifacts.md) | One successful HTTP body becomes the same-named single-file artifact through one shared `SnapshotFileRef`. |
| [`external-input-roots.md`](external-input-roots.md) | Local files and HTTP response bodies can both enter VIPER as external-input roots. `ResolvedExternalInputRef` records the local-file route. `ResolvedHttpRetrieval` records the HTTP route. Later stages select their artifacts through `FutureInputRef` or `StoredInputRef`. |
| [`automatic-input-resolution.md`](automatic-input-resolution.md) | Python authoring compiles local files, same-run handles, and prior-run selections into frozen input references. |
| This contract | Every immutable file and stage snapshot publishes directly to the configured local or Viper Cloud destination. |

## 2. Required claim

When a project selects Viper Cloud, VIPER uploads each completed stage directly
from the files the stage wrote. A stage snapshot contains the resolved stage
YAML and the stage's artifact files. `ResolvedStageRef.snapshot` stores the
cloud location. Each `SnapshotFileRef` stores a path, SHA-256 digest, and byte
count.

VIPER must be able to retrieve and check the same bytes later:

```text
declared working file
-> verified path, SHA-256 digest, and byte count
-> immutable publication at the configured destination
-> persisted reference to that destination
-> retrieval through the persisted reference
-> repeated SHA-256 and byte-count verification
```

Both storage modes execute the same frozen run plan. The stages, parameters,
inputs, artifact declarations, and working paths stay the same.

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

`LocalArtifactStore.snapshot()` accepts paths mapped to bytes. It writes those
bytes locally and returns `LocalStageResultSnapshotRef`. Cloud publication
needs a second publisher. The cloud publisher accepts existing file paths,
uploads their bytes, seals the snapshot, and returns
`ViperCloudStageResultSnapshotRef`.

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

Cloud publication leaves the declared working file in place. VIPER can use
that file again if the upload fails. `.viper/store` receives zero payload
copies.

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

This value uploads immutable copies into the `machina/weekend_models` cloud
project. Each `ArtifactSpec.path` still controls the working output path.

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

VIPER reads cloud credentials from the active CLI session. VIPER stores those
credentials outside `viper.toml`, frozen plans, resolved records, logs, and
cloud URIs.

## 5. Storage reference models

### 5.1 File stored outside a stage snapshot

`ViperCloudFileRef` points to one cloud file:

```python
class ViperCloudFileRef(ProtocolModel):
    kind: Literal["viper_cloud"] = "viper_cloud"
    owner: HumanId
    project: HumanId
    revision: SHA256
    path: RepoRelPath
```

`ResolvedFileRef` adds the expected digest and size:

```python
class ResolvedFileRef(ProtocolModel):
    sha256: SHA256
    bytes: int
    stored_at: StorageRef
```

`ResolvedFileRef` stores the check values beside the cloud location:

```text
ResolvedFileRef.sha256
ResolvedFileRef.bytes
ResolvedFileRef.stored_at = ViperCloudFileRef(...)
```

VIPER bundles each completed stage record and its artifacts into a stage
snapshot. VIPER publishes files that require independent retrieval as
standalone files. The configured storage destination controls where each file
lives:

| Standalone file | Owning field or reference | Local destination | Viper Cloud destination |
| --- | --- | --- | --- |
| Stage invocation receipt | `RunAttempt.invocations[]: ResolvedStageInvocationRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Captured local input | `ResolvedExternalInputRef.file: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Generated artifact pointer | `StoredInputRef.pointer: ResolvedArtifactPointerRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Attempt journal | `RunAttempt.journal: AttemptJournalRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Measurement | `RunAttempt.measurement_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Metric-verification receipt | `RunAttempt.metric_verification_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Stage log | `RunAttempt.log_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Attempt record | `ResolvedRun.attempts[]: ResolvedAttemptRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Benchmark result | `ArtifactPointer.benchmark_result: ResolvedBenchmarkResultRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Terminal run document | `RunResult.resolved_run_ref: ResolvedRunRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |

Each row uses a `ResolvedFileRef` subtype or field. Its `sha256` and `bytes`
fields identify the expected content. Its `stored_at` field identifies the
local-store file or Viper Cloud file that holds those bytes.

Stage artifacts, HTTP response bodies, and resolved stage documents use
`SnapshotFileRef` because they belong to a completed stage snapshot. Frozen run
and benchmark specifications use Git-backed references. Neither group appears
in this standalone-file table.

#### Example: captured local input

This illustrative target-contract example captures
`inputs/raw/dataset.csv` before a training stage reads it:

```python
resolved_input = ResolvedExternalInputRef(
    source=LocalSource(
        path="inputs/raw/dataset.csv",
    ),
    file=ResolvedFileRef(
        sha256=dataset_sha256,
        bytes=dataset_bytes,
        stored_at=ViperCloudFileRef(
            kind="viper_cloud",
            owner="machina",
            project="weekend_models",
            revision=sealed_revision,
            path="inputs/raw/dataset.csv",
        ),
    ),
    data_role="training",
)
```

VIPER follows the inner reference to retrieve the file. VIPER then checks the
retrieved bytes against the outer reference:

```text
resolved_input.file.stored_at
-> retrieve inputs/raw/dataset.csv from the named cloud revision

resolved_input.file.sha256 + resolved_input.file.bytes
-> verify the retrieved content
```

A model artifact produced by the training stage uses the snapshot-scoped
route instead:

```text
ResolvedStageRef.snapshot
+ SnapshotFileRef(path=".../parameters.bin")
-> retrieve parameters.bin from the completed stage snapshot
```

### 5.2 Cloud stage snapshot

`ViperCloudStageResultSnapshotRef` points to one sealed stage snapshot:

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

`StageResultSnapshotRef` is currently misnamed. It contains Hugging Face fields
and uses `kind="huggingface"`. Rename the Python class to
`HuggingFaceStageResultSnapshotRef`. Keep the YAML fields and `kind` value the
same.

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

`SnapshotFileRef` has the same fields for every storage provider:

```python
class SnapshotFileRef(ProtocolModel):
    path: RepoRelPath
    sha256: SHA256
    bytes: int
```

`SnapshotFileRef.path` names a file inside
`ResolvedStageRef.snapshot`. VIPER needs both values to retrieve the file:

```text
ResolvedStageRef.snapshot
+ SnapshotFileRef.path
-> immutable file bytes
```

The digest and byte count verify those bytes after retrieval.

### 5.4 Terminal run handle

When a run finishes, VIPER publishes its terminal `resolved.yaml` as a separate
file. `ResolvedRunRef` points to that file:

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
uses that reference to print a restore URI. The terminal run contains the
references needed to find the rest of the run.

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

### 6.2 Publisher functions

VIPER chooses a `SnapshotPublisher` from `StorageDestination`. The stage
executor calls its `publish()` method:

```python
class SnapshotPublisher(Protocol):
    def publish(
        self,
        *,
        resolved_stage: bytes,
        artifacts: Mapping[RepoRelPath, Path],
    ) -> StageResultSnapshot: ...
```

Files outside stage snapshots use a separate function:

```python
def publish_resolved_files(
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> tuple[ResolvedFileRef, ...]: ...
```

The local publisher calls `LocalArtifactStore`. The cloud publisher uploads
each source and seals one revision. It returns `ViperCloudFileRef` for a
separate file or `ViperCloudStageResultSnapshotRef` for a stage snapshot.

The stage executor uses this exact call:

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

Files outside a stage snapshot use `publish_resolved_files()`. That function
returns `sha256`, `bytes`, and `stored_at`. The caller places those values in
`ResolvedStageInvocationRef`, `ResolvedExternalInputRef.file`,
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

The worker finishes at step 2. The stage finishes at step 11, after VIPER has
published the snapshot and created `ResolvedStageRef`.

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

`ResolvedHttpRetrieval` records where the response entered VIPER.
`ResolvedSingleFileArtifact` records the same bytes as a stage output. Cloud
publication only changes where VIPER stores their shared snapshot.

### 7.3 Files outside stage snapshots

VIPER publishes these files when it creates them:

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

Each resulting reference tells VIPER where to retrieve its file. Restore and
verification follow those references.

## 8. Atomicity, failure, and recovery

### 8.1 Deterministic revision

VIPER sorts the snapshot paths. For each path, the manifest stores the SHA-256
digest and byte count. VIPER hashes that manifest. The manifest digest becomes
the revision and retry key.

Publishing the same manifest again targets the same revision. A retry can skip
objects the service already accepted.

### 8.2 Atomic seal

The cloud service hides uploaded files until it accepts the complete manifest.
The seal operation makes the revision available for retrieval. VIPER creates
`ViperCloudStageResultSnapshotRef` after the seal succeeds.

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

VIPER keeps these working files on the machine running the attempt:

```text
.viper/workspaces/<run-id>/<attempt-id>/
.viper/journals/<run-id>/<attempt-id>.jsonl
canonical terminal resolved.yaml at the run path
user-declared artifact paths
```

VIPER uses these files to run, diagnose, and retry the attempt. Persisted
references point to the immutable copies.

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

### 10.2 Files outside stage snapshots

`RunFetcher` reads `ResolvedFileRef.stored_at` and chooses the named storage
backend. A `ViperCloudFileRef` supplies the owner, project, revision, and path.
`RunFetcher` checks the retrieved bytes against `ResolvedFileRef.sha256` and
`ResolvedFileRef.bytes`.

### 10.3 Cloud graph reachability

A Viper Cloud run must work on another machine. Before VIPER publishes the
terminal `ResolvedRun`, it follows every attempt, stage, file, input, and
artifact reference.

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

This rule also covers an artifact from an earlier local run. The user must
publish or migrate the producer first. The user runs that migration as a
separate step before freezing the consumer.

### 10.4 Restore

The run command returns and prints the terminal `ResolvedRunRef`. The
`viper restore` command accepts a local terminal-run path or this cloud form:

```text
viper://machina/weekend_models@<revision>/<path-to-resolved.yaml>
```

The cloud revision identifies a sealed manifest. The manifest entry supplies
the terminal file's path, SHA-256 digest, and byte count. VIPER constructs the
`ResolvedRunRef` from that entry and requires the retrieved terminal file to
match it before following the run.

Restore accepts terminal runs with `status="succeeded"`. Omitting
`--artifacts` selects every artifact from the successful attempt. Supplying
`--artifacts` selects one or more values in this form:

```text
<stage-id>.<artifact-name>
```

The period is unambiguous because `StageId` and `ArtifactName` exclude periods.
A bundle selector restores every member of that bundle.

The output rules are:

| Selection | `--output` meaning |
| --- | --- |
| All artifacts | Directory beneath which VIPER recreates declared repository-relative paths |
| One single-file artifact | Exact output file |
| One bundle artifact | Directory containing the restored bundle |
| Several artifacts | Directory beneath which VIPER recreates declared repository-relative paths |

Omitting `--output` restores each selected artifact to its declared path beneath
`--repository-root`. VIPER requires every selected destination path to be
unique and nonoverlapping. A conflicting selection fails before retrieval.

Restore performs this sequence:

```text
parse terminal-run path or immutable URI
-> retrieve terminal resolved.yaml
-> check ResolvedRunRef digest and byte count
-> parse ResolvedRun
-> follow attempt, stage, snapshot, input, and artifact references
-> resolve the successful attempt and selected artifacts
-> validate every destination path and existing file
-> retrieve selected files into temporary paths
-> verify every SHA-256 digest and byte count
-> move each verified file into place
```

An absent destination receives the restored file. A destination containing the
expected bytes remains in place and is reported as already restored. A
destination containing different bytes fails the operation before VIPER writes
any file. Each final move is atomic.

Restore parses records, follows references, retrieves bytes, and checks file
identity. Stage callables, artifact loaders, and metric implementations remain
unexecuted.

Restore starts from `ResolvedRunRef`; the terminal run and all reachable
references carry their own storage locations.

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

The command above restores every artifact to its declared path. The user can
restore one artifact to a chosen file:

```bash
viper restore <run-reference> \
  --artifacts train.parameters \
  --output recovered/parameters.bin
```

The user can restore several artifacts beneath one directory:

```bash
viper restore <run-reference> \
  --artifacts \
    train.parameters \
    train.resume_state \
    evaluate.predictions \
  --output recovered/
```

## 12. Propagation and legacy cleanup

### 12.1 Required changes

| Surface | Required change |
| --- | --- |
| Configuration | Parse one `[storage].destination` value into `LocalStorageDestination` or `ViperCloudDestination`. |
| File references | Add `ViperCloudFileRef` to `StorageRef`. |
| Snapshot references | Add `ViperCloudStageResultSnapshotRef`; rename the Python Hugging Face snapshot class while preserving its serialized form. |
| Publication | Replace hard-coded local publication calls with `SnapshotPublisher.publish()` and `publish_resolved_files()`. |
| Stage execution | Pass resolved-stage bytes and declared artifact paths to the snapshot publisher after artifact validation. |
| Download execution | Publish the shared retrieval/artifact path once in the configured stage snapshot. |
| Local roots | Publish captured bytes through `publish_resolved_files()`. |
| Pointer generation | Publish generated `ArtifactPointer` documents through `publish_resolved_files()`. |
| Terminal run | Publish terminal `resolved.yaml` and return `RunResult.resolved_run_ref`. |
| Retrieval | Route Viper Cloud file and snapshot variants through the cloud client. |
| Recovery | Resume an unsealed stage publication from verified working paths before rerunning the stage. |
| CLI | Print the terminal run reference; add full and artifact-selected restore from a local terminal-run path or immutable Viper Cloud URI. |
| Verification | Apply existing path, digest, and byte-count rules to both destination variants. |

### 12.2 Removed design

Delete these proposed concepts from the implementation plan and documentation:

| Removed concept | Replacement |
| --- | --- |
| `RunSyncState` | `ResolvedRunRef` locates the terminal run; every reachable reference locates its own evidence. |
| `.viper/sync/` | `ResolvedRunRef` serves as the terminal restore handle. |
| `viper sync` | Failed stage publication resumes during run retry. |
| `viper offload` | Cloud mode bypasses local immutable payload publication from the start. |
| Terminal-run closure upload | VIPER publishes each stage snapshot and separate file when it creates them. |
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
3. Add `SnapshotPublisher` and `publish_resolved_files()`. Use
   `LocalArtifactStore` for the local implementations.
4. Change stage publication to pass artifact paths and stream each payload.
   Add the direct-cloud and local-compatibility cases.
5. Route local roots, generated pointers, invocations, attempts, logs, metrics,
   and terminal runs through `publish_resolved_files()`.
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
