# Direct Viper Cloud publication

VIPER saves copies of the files and records needed to verify a run. The saved
bytes stay fixed. This contract calls that step publication.

Local publication writes the copies beneath `.viper/store`. Viper Cloud
publication uploads them from their working paths. In cloud mode,
`.viper/store` receives zero payload copies.

The user chooses each run-relative working path through `ArtifactDraft.path`.
Freezing prefixes the selected run root and writes the concrete
`ArtifactSpec.path`. Storage configuration only chooses where VIPER publishes
the immutable copy.

## 1. Status

**Contract status:** draft after system review; owner review pending.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| RSP-01 <!-- contract-requirement: RSP-01 phase=1 test=tests/test_storage.py --> | Add destination-neutral stage and standalone publication with local implementations. |
| RSP-02 <!-- contract-requirement: RSP-02 phase=1 test=tests/test_run_execution.py --> | Route current local publication through the new interfaces and bind one destination per run. |
| RSP-03 <!-- contract-requirement: RSP-03 phase=4 test=tests/test_metric_provenance.py --> | Derive metric dependency references from existing stage snapshots and publish zero duplicate payloads. |
| RSP-04 <!-- contract-requirement: RSP-04 phase=9 test=tests/test_storage.py --> | Add Viper Cloud references, the cloud client, atomic sealing, and retry behavior. |
| RSP-05 <!-- contract-requirement: RSP-05 phase=9 test=tests/test_execution_acceptance.py --> | Publish every stage snapshot and standalone evidence file directly to the selected destination. |
| RSP-06 <!-- contract-requirement: RSP-06 phase=9 test=tests/test_verification_acceptance.py --> | Retrieve cloud evidence, verify byte identity, reject local references in cloud graphs, and return terminal handles. |
| RSP-07 <!-- contract-requirement: RSP-07 phase=10 test=tests/test_storage.py --> | Restore all or selected artifacts through verified temporary files and atomic final writes. |
| RSP-08 <!-- contract-requirement: RSP-08 phase=10 test=tests/test_api.py --> | Expose one restore result through Python, typed API, and CLI surfaces. |
| RSP-09 <!-- contract-requirement: RSP-09 phase=11 test=tests/test_documentation.py --> | Remove retired sync and mirroring concepts and publish the final storage workflow. |

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
| [`external-input-roots.md`](external-input-roots.md) | Local files and HTTP responses use source-specific root records; later stages select artifacts through `FutureInputRef` or `StoredInputRef`. |
| [`automatic-input-resolution.md`](automatic-input-resolution.md) | Python authoring compiles local files, same-run handles, and prior-run selections into frozen input references. |
| [`frozen-plan-git-identity.md`](frozen-plan-git-identity.md) | Generated plan documents use a Git plan commit; project definitions use the earlier source commit. |
| This contract | Every immutable file and stage snapshot publishes directly to the configured local or Viper Cloud destination. |

## 2. Required claim

When a project selects Viper Cloud, VIPER uploads each completed stage directly
from the files the stage wrote or consumed under runner custody. A stage
snapshot contains the resolved stage YAML, stage artifacts, HTTP bodies, and
captured local inputs owned by that stage. `ResolvedStageRef.snapshot` stores
the cloud location. Each `SnapshotFileRef` stores a path, SHA-256 digest, and
byte count.

VIPER must be able to retrieve and check the same bytes later:

```text
declared working file
-> verified path, SHA-256 digest, and byte count
-> immutable publication at the configured destination
-> persisted reference to that destination
-> retrieval through the persisted reference
-> repeated SHA-256 and byte-count verification
```

Both storage modes preserve the same stage graph, parameters, artifact
declarations, and working paths. A plan containing a generated prior-run
pointer records that pointer's storage location during freezing, so freezing
and execution use the same bound destination.

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
project. Each frozen `ArtifactSpec.path` still controls the concrete working
output path.

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

VIPER reads cloud credentials from the active CLI session.

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
    bytes: int = Field(ge=0)
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
| Generated artifact pointer | `StoredInputRef.pointer: ResolvedArtifactPointerRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Attempt journal | `RunAttempt.journal: AttemptJournalRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Measurement | `RunAttempt.measurement_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Metric-verification receipt | `RunAttempt.metric_verification_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Stage log | `RunAttempt.log_files[]: ResolvedFileRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Attempt record | `ResolvedRun.attempts[]: ResolvedAttemptRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Benchmark result | `BenchmarkExecutionResult.result_ref: ResolvedBenchmarkResultRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |
| Terminal run document | `RunResult.resolved_run_ref: ResolvedRunRef` | `stored_at: LocalFileRef` | `stored_at: ViperCloudFileRef` |

Each row uses a `ResolvedFileRef` subtype or field. Its `sha256` and `bytes`
fields identify the expected content. Its `stored_at` field identifies the
local-store file or Viper Cloud file that holds those bytes.

Stage artifacts, HTTP response bodies, captured local inputs, and resolved stage
documents use `SnapshotFileRef` because they belong to a completed stage
snapshot. Frozen run and benchmark specifications use Git-backed references.
Neither group appears in this standalone-file table.

Recomputed metric dependencies reuse those stage snapshots. VIPER converts the
selected `SnapshotFileRef` and its enclosing snapshot into a `ResolvedFileRef`:

| Dependency file owner | Local destination | Viper Cloud destination |
| --- | --- | --- |
| Current-stage artifact or captured input | `LocalFileRef` with the current stage snapshot commit and selected path | `ViperCloudFileRef` with the current stage snapshot revision and selected path |
| Earlier same-run stage artifact | `LocalFileRef` with the producer snapshot commit and selected path | `ViperCloudFileRef` with the producer snapshot revision and selected path |
| Prior-run stored artifact | Existing producer `StorageRef` reached through `ArtifactPointer` | Existing producer `StorageRef` reached through `ArtifactPointer` |

The conversion has one operation:

```python
def resolve_snapshot_file_ref(
    snapshot: StageResultSnapshot,
    file: SnapshotFileRef,
) -> ResolvedFileRef:
    ...
```

It copies `SnapshotFileRef.sha256` and `SnapshotFileRef.bytes` into the returned
`ResolvedFileRef`. It combines the file path with the enclosing snapshot's
storage address. It publishes zero bytes. A metric receipt can retrieve its
dependency independently while the payload remains stored once.

#### Example: captured local input

VIPER copies `inputs/raw/dataset.csv` to an attempt-owned input path and gives
that path to the training stage. The completed resolved train record stores:

```python
ResolvedExternalInputRef(
    source=LocalSource(path="inputs/raw/dataset.csv"),
    file=SnapshotFileRef(
        path=(
            ".viper/workspaces/<run-id>/attempt-<attempt-id>/inputs/"
            "train/dataset/dataset.csv"
        ),
        sha256=dataset_sha256,
        bytes=dataset_bytes,
    ),
    data_role="training",
)
```

The local input uses the same snapshot-scoped retrieval rule as a model
artifact:

```text
ResolvedStageRef.snapshot
+ ResolvedExternalInputRef.file
-> retrieve the captured input from the completed stage snapshot

ResolvedStageRef.snapshot
+ ResolvedSingleFileArtifact.file
-> retrieve a produced artifact from the completed stage snapshot
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
    bytes: int = Field(ge=0)
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
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_run: ResolvedRun
    resolved_run_ref: ResolvedRunRef
    resolved_run_path: Path
    journal_path: Path
```

In cloud mode, `resolved_run_ref.stored_at` is a `ViperCloudFileRef`. The CLI
uses that reference to print a restore URI. The terminal run contains the
references needed to find the rest of the run.

### 5.5 Benchmark result handle

When a benchmark finishes, VIPER publishes its result document as a standalone
file. `ResolvedBenchmarkResultRef` points to that file:

```python
class ResolvedBenchmarkResultRef(ResolvedFileRef):
    kind: Literal["benchmark_result"] = "benchmark_result"
```

`BenchmarkExecutionResult` returns the reference with the parsed result and its
local control path:

```python
class BenchmarkExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: BenchmarkResult
    result_ref: ResolvedBenchmarkResultRef
    result_path: Path
```

An `ArtifactPointer` for a benchmarked estimator copies this exact reference
into `benchmark_result`. The pointer therefore reaches the same immutable
benchmark result that the benchmark command returned.

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

The storage layer depends on this provider-neutral cloud client boundary:

```python
class ViperCloudClient(Protocol):
    def upload(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        path: RepoRelPath,
        source: PublicationSource,
        sha256: SHA256,
        bytes: int,
    ) -> None: ...

    def seal(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        files: tuple[SnapshotFileRef, ...],
    ) -> None: ...

    def fetch(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
        path: RepoRelPath,
    ) -> bytes: ...

    def list_files(
        self,
        *,
        owner: HumanId,
        project: HumanId,
        revision: SHA256,
    ) -> tuple[RepoRelPath, ...]: ...
```

The client receives credentials when VIPER creates it from the active CLI
session. The repository can implement and test publication against an in-memory
client before the Viper Cloud service fixes its HTTP endpoint and token format.
The production adapter remains blocked on that external API.

### 6.2 Publisher functions

VIPER chooses a `SnapshotPublisher` from `StorageDestination`. The stage
executor calls its `publish()` method:

```python
class SnapshotPublisher(Protocol):
    def publish(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        files: Mapping[RepoRelPath, Path],
    ) -> StageResultSnapshot: ...

    def publish_reuse(
        self,
        *,
        resolved_stage_path: RepoRelPath,
        resolved_stage: bytes,
        source_snapshot: StageResultSnapshot,
        files: tuple[ReusedStageFile, ...],
    ) -> StageResultSnapshot: ...
```

Files outside stage snapshots use a separate function:

```python
def publish_resolved_files(
    root: Path,
    destination: StorageDestination,
    files: Mapping[RepoRelPath, PublicationSource],
) -> dict[RepoRelPath, ResolvedFileRef]: ...


def bind_run_destination(
    root: Path,
    run_id: RunId,
    destination: StorageDestination,
) -> StorageDestination: ...
```

The local publisher calls `LocalArtifactStore`. The cloud publisher uploads
each source and seals one revision. It returns `ViperCloudFileRef` for a
separate file or `ViperCloudStageResultSnapshotRef` for a stage snapshot.

`publish_reuse()` supports the opt-in contract in
[`stage-reuse.md`](stage-reuse.md). The local publisher links or copies
verified source-snapshot bytes into a new target revision. The cloud publisher
seals a new target manifest over existing payload objects. Both paths publish
the target `resolved.yaml` and return a new target snapshot identity.

The stage executor uses this exact call:

```python
snapshot = snapshot_publisher.publish(
    resolved_stage_path=resolved_path,
    resolved_stage=resolved_raw,
    files=snapshot_paths,
)
```

`resolved_stage_path` supplies the repository-relative path of the completed
stage document.
`resolved_stage` supplies the serialized `resolved.yaml` bytes.
`snapshot_paths` maps each snapshot member path to its existing working `Path`.
The map contains declared artifacts and captured local inputs. Before upload,
the publisher parses `resolved_stage`, matches every member to its
`SnapshotFileRef`, and checks the source file's SHA-256 digest and byte count.
It then computes one manifest, uploads each unique path once, and returns the
sealed snapshot reference.

Files outside a stage snapshot use `publish_resolved_files()`. The returned map
uses each publication path as its key. Each value supplies `sha256`, `bytes`,
and `stored_at`. The caller selects the result by path and constructs the exact
reference named in the standalone-file table in section 5.1.

`bind_run_destination()` atomically creates or loads the run-level destination
record. `viper.freeze()` calls it before publishing a generated artifact
pointer. Run execution calls it before stage work or any immutable publication.
Both callers receive the stored destination and reject a different configured
value with `storage_destination_changed`.

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
HTTP function writes response into attempt scratch space
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
generate ArtifactPointer for a prior-run selection
-> publish pointer document through publish_resolved_files()
-> StoredInputRef.pointer records the returned storage location

finish an attempt
-> publish journal, measurements, metric-verification receipts, and logs
   through one publish_resolved_files() call
-> publish the RunAttempt document through publish_resolved_files()
-> ResolvedRun.attempts records the returned ResolvedAttemptRef

finish a benchmark
-> publish the BenchmarkResult document through publish_resolved_files()
-> BenchmarkExecutionResult.result_ref records the returned storage location

complete terminal ResolvedRun
-> publish resolved.yaml through publish_resolved_files()
-> RunResult.resolved_run_ref records the returned storage location
```

Stage invocation receipts use the same function when each stage process ends.
`RunAttempt.invocations` records the returned `ResolvedStageInvocationRef`.

Captured local inputs follow the stage-snapshot path instead. The runner copies
the source to an attempt-owned input path, the stage reads that path, and the
snapshot publisher stores the verified file with the consuming stage.

Each resulting reference tells VIPER where to retrieve its file. Restore and
verification follow those references.

## 8. Atomicity, failure, and recovery

### 8.1 Deterministic revision

VIPER uses the revision algorithm already implemented by
`LocalArtifactStore._content_commit()`. It sorts files by repository-relative
path. For each file, it hashes this exact sequence:

```text
8-byte big-endian path length
UTF-8 path bytes
8-byte big-endian file length
32 raw SHA-256 digest bytes for the file
```

The revision is the SHA-256 digest of every framed entry concatenated in sorted
path order. Viper Cloud uses the same algorithm. Existing local revision IDs
therefore remain stable. Stage snapshots and standalone-file batches both use
this rule.

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

The publisher retries transfer and seal operations against the same
deterministic revision while the coordinator remains active. Each retry reads
the same verified working paths. If the coordinator exits, the ordinary run
retry may execute the stage again. Resumable execution across coordinator
processes belongs to a future contract.

Standalone publication follows the same seal rule. VIPER writes each generated
document to its canonical local control path before upload. Existing source
files remain at their working paths. VIPER creates the corresponding
`ResolvedFileRef` only after the cloud revision is sealed. A retry republishes
the same verified path. The existing document bytes remain fixed.

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

Before the first immutable publication, VIPER writes the parsed
`StorageDestination` to:

```text
.viper/workspaces/<run-id>/storage-destination.json
```

`bind_run_destination()` creates that run-level control file atomically. The
first immutable publisher owns the first call. A prior-run input may make
`viper.freeze()` the first caller because freezing publishes its generated
`ArtifactPointer`. A plan whose freeze step publishes zero immutable files
binds the destination when execution begins.

Every retry and later attempt loads the record before stage work and compares
it with the current configuration. A different value produces
`storage_destination_changed`. A frozen plan that embeds a generated pointer is
already bound to that pointer's destination. Plans whose freeze step generates
zero pointers retain destination choice until their first execution.

## 9. Local control and recovery evidence

VIPER keeps these working files on the machine running the attempt:

```text
.viper/workspaces/<run-id>/<attempt-id>/
.viper/workspaces/<run-id>/storage-destination.json
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

A local terminal path follows the same trust sequence. VIPER requires terminal
`resolved.yaml` to be published as a one-file local revision. Restore validates
the canonical repository-relative path, reads the working file, and computes
the local content revision from `{terminal_path: terminal_bytes}`. It constructs
this reference:

```text
ResolvedRunRef(
    sha256=sha256(terminal_bytes),
    bytes=len(terminal_bytes),
    stored_at=LocalFileRef(
        commit=<computed one-file revision>,
        path=terminal_path,
    ),
)
```

Restore then fetches that `LocalFileRef` from `.viper/store` and requires the
stored bytes to match. A changed working file computes a revision absent from
the local store and fails before parsing.

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

The Python and typed-operation interfaces use these exact models:

```python
ViperCloudRunUri = Annotated[
    str,
    AfterValidator(validate_viper_cloud_run_uri),
]


class ArtifactRestoreSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_id: StageId
    artifact_name: ArtifactName


class RestoredFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    status: Literal["restored", "already_present"]


class RestoredArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: ArtifactRestoreSelector
    files: tuple[RestoredFile, ...] = Field(min_length=1)


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    artifacts: tuple[RestoredArtifact, ...] = Field(min_length=1)


RestoreRunReference = Path | ViperCloudRunUri | ResolvedRunRef


class LocalRunPath(APIModel):
    kind: Literal["local_path"] = "local_path"
    path: Path


class ViperCloudRunReference(APIModel):
    kind: Literal["viper_cloud_uri"] = "viper_cloud_uri"
    uri: ViperCloudRunUri


RestoreRequestReference = Annotated[
    LocalRunPath | ViperCloudRunReference | ResolvedRunRef,
    Field(discriminator="kind"),
]
```

`validate_viper_cloud_run_uri()` accepts only the
`viper://<owner>/<project>@<revision>/<terminal-path>` form defined above. The
CLI parses each `<stage-id>.<artifact-name>` value into
`ArtifactRestoreSelector` before calling the restore engine. The direct Python
function accepts ordinary `Path` and URI values. The serialized typed request
uses `RestoreRequestReference` to give each JSON value exactly one local-path,
cloud-URI, or resolved-reference meaning.

The direct execution function is:

```python
def restore(
    repository_root: Path,
    run_reference: RestoreRunReference,
    *,
    artifacts: tuple[ArtifactRestoreSelector, ...] = (),
    output: Path | None = None,
) -> RestoreResult: ...
```

The typed operation uses the same values:

```python
OperationName = Literal[
    "validate_stage",
    "validate_resolved_stage",
    "validate_run_spec",
    "freeze_run",
    "preflight",
    "execute_stage",
    "run",
    "retry",
    "execute_benchmark",
    "restore",
    "plan_diff",
    "lineage",
    "status",
    "compare_runs",
    "verify_run",
    "verify_benchmark",
    "verify_pointer",
    "get_schema",
    "get_capabilities",
    "init_project",
]


class RestoreRequest(APIModel):
    run_reference: RestoreRequestReference
    repository_root: Path
    artifacts: tuple[ArtifactRestoreSelector, ...] = ()
    output: Path | None = None


class RestoreSuccess(SuccessModel):
    operation: Literal["restore"] = "restore"
    result: RestoreResult
```

`restore` joins `OperationName`, `REQUEST_REGISTRY`, `HANDLER_REGISTRY`, and the
CLI operation table. The typed handler converts `LocalRunPath` or
`ViperCloudRunReference` to the corresponding direct-function value. The
direct function, typed handler, and CLI then call one restore engine.

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
  --artifacts train.model \
  --output recovered/model.bin
```

The user can restore several artifacts beneath one directory:

```bash
viper restore <run-reference> \
  --artifacts \
    train.model \
    train.state \
    evaluate.preds \
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
| Stage reuse | Add `SnapshotPublisher.publish_reuse()` so a target stage receives a new snapshot while its callable remains uncalled. |
| Stage execution | Pass resolved-stage bytes and declared artifact paths to the snapshot publisher after artifact validation. |
| Download execution | Publish the shared retrieval/artifact path once in the configured stage snapshot. |
| Local roots | Copy each source to an attempt-owned input path, verify it after stage execution, and include its `SnapshotFileRef` in the consuming-stage snapshot. |
| Pointer generation | Publish generated `ArtifactPointer` documents through `publish_resolved_files()`. |
| Attempt evidence | Publish invocation receipts, journals, measurements, metric-verification receipts, logs, and attempt documents through `publish_resolved_files()`. |
| Benchmark result | Publish the completed result and return `BenchmarkExecutionResult.result_ref`. |
| Terminal run | Publish terminal `resolved.yaml` and return `RunResult.resolved_run_ref`. |
| Destination stability | Call `bind_run_destination()` before the first immutable publication during freezing or execution; reject every later configured change. |
| Metric dependencies | Derive `ResolvedMetricDependency.files` from each selected `SnapshotFileRef` and its enclosing stage snapshot; reuse that snapshot payload. |
| Retrieval | Route Viper Cloud file and snapshot variants through the cloud client. |
| Recovery | Retry transfer and seal against the same deterministic revision while the coordinator remains active; preserve working files for an ordinary run retry after process loss. |
| CLI | Print the terminal run reference; derive the local immutable reference from a canonical one-file terminal publication; add full and artifact-selected restore from that local path or an immutable Viper Cloud URI. |
| Python and typed API | Add `ArtifactRestoreSelector`, `RestoreResult`, `viper.execution.restore()`, the discriminated typed request references, `RestoreRequest`, and `RestoreSuccess`; route all three public surfaces through one restore engine. |
| Verification | Apply existing path, digest, and byte-count rules to both destination variants. |
| Tests | Cover publishers and restore in [`tests/test_storage.py`](../../tests/test_storage.py), execution in [`tests/test_run_execution.py`](../../tests/test_run_execution.py), public surfaces in [`tests/test_public_api.py`](../../tests/test_public_api.py) and [`tests/test_cli.py`](../../tests/test_cli.py), and tamper rejection in [`tests/test_verification_acceptance.py`](../../tests/test_verification_acceptance.py). |

### 12.2 Removed design

Delete these proposed concepts from the implementation plan and documentation:

| Removed concept | Replacement |
| --- | --- |
| `RunSyncState` | `ResolvedRunRef` locates the terminal run; every reachable reference locates its own evidence. |
| `.viper/sync/` | `ResolvedRunRef` serves as the terminal restore handle. |
| `viper sync` | The active publisher retries the deterministic revision; a later `viper retry` follows ordinary attempt execution. |
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
publisher retry reuses the working paths
publisher retry seals the same deterministic revision
the active attempt continues
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

### 13.5 Standalone cloud evidence

One cloud-backed run emits every run-owned standalone file listed in section
5.1. The test follows each owning field and requires its `stored_at` value to
be a `ViperCloudFileRef`. It retrieves every file, checks its SHA-256 digest and
byte count, and confirms that `.viper/store` contains none of those payload
copies. A companion stage-snapshot assertion retrieves one captured local input
through `ResolvedExternalInputRef.file`.

A benchmark companion covers the remaining row. It requires
`BenchmarkExecutionResult.result_ref` to retrieve the same bytes parsed as
`BenchmarkExecutionResult.result`.

### 13.6 Destination change

The first attempt writes the selected destination and publishes one immutable
file. A retry changes `viper.toml`. VIPER emits
`storage_destination_changed` before starting a stage or uploading a file.

The freeze companion selects one prior-run artifact. Freezing binds the run
destination before publishing the generated pointer. Changing the destination
before execution also produces `storage_destination_changed`.

### 13.7 Metric dependency reuse

A recomputed evaluation metric depends on a prediction artifact in the
evaluation-stage snapshot. The metric receipt contains a `ResolvedFileRef` with
the same snapshot revision, path, SHA-256 digest, and byte count. The fake
publisher observes zero uploads for dependency resolution.

### 13.8 Local terminal restore identity

A local run publishes terminal `resolved.yaml` as a one-file revision. Restore
derives its `LocalFileRef`, fetches the immutable file, and restores one model
artifact. Changing the working `resolved.yaml` makes the derived revision
unavailable and stops restore before parsing.

The typed-operation companion passes a list of two
`ArtifactRestoreSelector` values. `RestoreSuccess.result` lists both artifacts
and every output file. Repeating the operation marks each unchanged output as
`already_present`.

## 14. Implementation order

1. Add `SnapshotPublisher` and `publish_resolved_files()`. Use
   `LocalArtifactStore` for the first implementations.
2. Change local stage and standalone publication to use those interfaces.
3. Add destination parsing, `bind_run_destination()`, and exact configuration
   tests. Call the binding before every freeze-time or execution-time
   publication.
4. Add Viper Cloud file and snapshot references, the snapshot-class rename,
   serialization tests, and union round-trip tests.
5. Change cloud stage publication to pass paths and stream each payload.
   Add the direct-cloud and local-compatibility cases.
6. Route every file in the section 5.1 table through
   `publish_resolved_files()`. Return the terminal-run and benchmark-result
   references from their public result objects.
7. Derive metric dependency references from their enclosing snapshots. Add
   cloud retrieval and apply existing identity checks.
8. Add seal-failure recovery and deterministic retry.
9. Route cloud publication through the destination binding already used by
   freezing. Add destination-stability and cloud-graph-reachability checks.
10. Add terminal-run restore through `ResolvedRunRef`, the direct Python
    function, the typed operation, and the CLI.
11. Remove every sync-state, closure-upload, offload, and remote-fallback design
   reference from the repository.
12. Update the public README after the complete cloud acceptance path passes.

## 15. Invariants

The implementation is complete when all of these statements hold:

```text
one immutable publication has one configured destination

frozen artifact paths remain unchanged by storage placement

cloud-backed stage payloads bypass .viper/store

SnapshotFileRef identifies bytes inside one enclosing stage snapshot

ResolvedStageRef.snapshot identifies that snapshot's storage location

ResolvedFileRef.stored_at identifies independently published evidence

ResolvedRunRef identifies the terminal run and starts restore

ResolvedBenchmarkResultRef identifies the published benchmark result

every persisted reference contains enough information to route retrieval

a Viper Cloud terminal graph reaches zero machine-local immutable references

every retrieved file passes its persisted SHA-256 and byte-count checks

a stage becomes complete after its snapshot is sealed and ResolvedStageRef exists

a failed seal preserves the working files required for retry

the first immutable publication fixes the run's destination before stage work
```

## Implementation sources

- [Local store implementation](../../src/viper/storage.py)
- [Storage reference schemas](../../src/viper/references.py)
- [Stage artifact resolution](../../src/viper/execution/_stage.py)
- [Attempt publication](../../src/viper/execution/_attempt.py)
- [Run result model](../../src/viper/execution/results.py)
- [Storage retrieval and verification](../../src/viper/_verification/storage.py)
