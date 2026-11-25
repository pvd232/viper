# VIPER protocol reference

VIPER stores the request for a run separately from the evidence produced while executing
it. This page is a map of those records. Use the installed schemas for their exact
fields.

## Record map

| Record | Purpose |
| --- | --- |
| `ExperimentSpec` | Defines factors, variants, replicates, and metrics. |
| `VariantSpec` | Selects the stage graph and config for each stage. |
| `RunSpec` | Selects one variant and replicate, the source revision, runtime, reproducibility settings, estimator, optional benchmark, and ordered stages. |
| `Spec` | Declares one stage's function, config, inputs, outputs, metrics, objective, runtime override, reuse policy, file-access mode, and input-root policy. |
| `ResolvedSpec` | Records the artifacts, runtime evidence, and any required download-source closure produced by one stage attempt. |
| `StageInvocationReceipt` | Records the executed callable, bound context, timing, outcome, and any governed workspace file accesses. |
| `RunAttempt` | Records status, timing, completed stages, measurements, logs, and failure evidence for one attempt. |
| `ResolvedRun` | Records a run's terminal status and the attempt that supports it. |

The model definitions live in [`viper.experiments`](../../src/viper/experiments.py),
[`viper.runs`](../../src/viper/runs.py), and
[`viper.stages`](../../src/viper/stages.py).

## Terms that mark different lifecycle states

| Before execution | After execution |
| --- | --- |
| An **output** declares where a stage must write. | An **artifact** identifies the files written for that output. |
| A stage `Spec` declares the requested operation. | A `ResolvedSpec` records the completed operation. |
| A `RunSpec` fixes the requested run. | A `ResolvedRun` records its terminal result. |

Workspace functions therefore write through `context.outputs`. Verification, restore,
and catalog queries consume artifact records.

## Input references

| Type | Selects |
| --- | --- |
| `ExternalInputRef` | A repository file captured for the current run. |
| `FutureInputRef` | An output from an earlier stage in the same run. |
| `StoredInputRef` | An artifact from a verified earlier run. |

Download stages use `HttpRequestSpec` instead. The request stores the expected response
size and SHA-256 digest; the resolved retrieval records the observed response.

An internal stage may set `input_roots="download"`. Before VIPER reuses or starts that
stage, `verify_download_source_closure()` follows same-run `FutureInputRef` producers,
prior-run `StoredInputRef` producers, and exact stage-reuse sources. It rejects
`ExternalInputRef` leaves and accepts the stage only when every terminal leaf is a
`ResolvedDownloadSpec` receipt whose request, body reference, and artifact reference
agree. The walk reads only the selected receipt branch; it does not read artifact bodies,
other attempts, or unrelated stages. The retained `DownloadSourceClosureReceipt` records
every visited node and edge plus the Download roots for each direct consumer input.
Terminal run verification repeats the receipt walk and rejects a substituted receipt.

## File references

A source reference such as `GitFileRef` selects a repository, revision, and path. A
resolved file reference adds the byte count and SHA-256 digest, which VIPER checks when
retrieving the file. A local storage reference identifies its producer workspace,
store directory, content-derived revision, and path. This lets another local
workspace retrieve the referenced bytes without confusing the producer store with its
own. Git and Hugging Face references use repository commits. See
[`viper.references`](../../src/viper/references.py).

## Automatic reuse discovery

After verification and immutable terminal publication, successful run execution
registers its stages with `Catalog.register_run()`. The catalog
retains earlier runs and knowledge. Reused stages remain indexed as run evidence;
automatic registration retains an existing reuse target. A stage recovered from
a failed attempt can enter the catalog through the successful retry when the
catalog is missing that key.

Workspace stages default to `reuse="verified"`, which permits skipping computation
in a new run. An explicit `reuse="never"` forces computation in that run.
Lookup uses the complete `StageReuseKey`, and the existing verifier checks the
selected source again before publishing a reuse receipt. Stored inputs continue
to materialize verified filesystem paths. Benchmark confirmation still invokes
stages independently.

The catalog is a derived index. A registration failure emits a warning and
preserves the successful run. `catalog_refresh` can index that saved result or
rebuild the catalog. Registration and refresh exclude concurrent writers through
the same lock. The [reuse guide](../how-to/stages.md#reuse-a-verified-stage-result)
states the default, recomputation, and recovery behavior.

## Workspace and cloud paths

Scientific journals use `JournalSource` for immutable Markdown revisions and
byte spans, and `JournalEncoding`/`JournalEncoderSpec` for exact text and learned
encoder identities. `JournalAssertion.source` and `KnowledgeVector.encoding`
are optional for older manually authored records. Learned journal views include
the complete encoder/runtime digest in their version. See the
[journal guide](../how-to/journals.md) for the writer and reader operations.

`viper.repository.init_workspace()` creates the starter files returned by
[`workspace_files()`](../../src/viper/repository.py). A run then writes its records and
logical artifact addresses under the same workspace root:

```text
<workspace>/
├── src/<package>/                 # workspace-owned stage code
├── tests/                         # workspace-owned tests
├── benchmarks/                    # benchmark declarations
├── experiments/<experiment_id>/
│   └── runs/<variant_id>/<run_id>/
│       ├── resolved.yaml
│       ├── stages/<stage_id>/
│       ├── artifacts/<stage_id>/<output_name>/<relative_path>  # logical address
│       └── attempts/<attempt_id>/
└── .viper/
    ├── store/                     # immutable inventories and shared payloads
    ├── workspaces/<run_id>/attempt-<n>/stages/<stage>/<output>/  # physical outputs
    ├── pointers/                  # retained artifact pointers
    └── catalog.sqlite3
```

The artifact address in a snapshot reference is logical. Use Viper resolution for
an actual path; native original outputs live under the attempt-owned directory above,
and restored bytes normally live under `.viper/store/objects`. `api.execute_stage()`
returns its actual `output_paths` alongside logical artifact identities.

The GCS client stores one sealed content revision at:

```text
gs://<bucket>/<prefix>/<owner>/<workspace>/<content-revision>/<workspace-relative-path>
gs://<bucket>/<prefix>/<owner>/<workspace>/<content-revision>.manifest.json
```

Everything after `<content-revision>/` is the exact workspace-relative path. VIPER does
not rename an artifact to `datasets/`, `models/`, or another cloud-only category. The
manifest is the revision's seal: readers list and restore only paths named by that
manifest, then verify the restored byte count and SHA-256 digest.

### Disk retention boundary

Immutable references identify exact bytes and snapshot membership. The registry keeps
complete inventory, current local bindings and retention preferences separately.
A reference's embedded workspace is its original address; the current workspace's
registered bindings and verified cloud copies take precedence after relocation.
Serialized `<commit>/<path>` addressing does not require a physical payload at that
location. Original files and equal-content store payloads can satisfy the same identity.

Native cloud publication is durably queued before acceptance. Cloud completion is
separate from local scientific success; the original references and records do not
change when publication completes. Final portable receipts cover the closed collection
at every required destination. Existing explicit cloud-return APIs still verify before
returning. Older direct-cloud terminal references may retain `resolved.ref.yaml`.

With `storage.offload = true`, successful outer workflow completion requests cleanup.
The worker requires verified backing, complete required publication, unanimous current
retention permission, finished readers and the exact owned physical copy. It rechecks
permission under reader exclusion and a short registry transaction. There is no network
transfer or full file hash under that final transaction. Shared-reader protection covers
admitted later actions and queued inputs, including gaps between child calls.

Cleanup preserves inventory, preferences, references and recovery records. It removes
only selected owned payloads; unknown files and external outputs remain protected.
Explicit keep saves its preference before restoring complete bundle availability.
Download and upload failures retain the recoverable local sources. Later cleanup reuses
verified proof rather than uploading or verifying all remote bytes again.

The shared resolver prefers resident verified originals and payloads. Restores verify
size and SHA-256 in a temporary file before atomic installation. Full snapshot import
verifies and materializes its supplied copies into the current store. Individually
verified file proofs certify only those files, never an unexamined bundle.

The legacy `retention.evict_cloud_backed_run_files()` API applies the same deletion
decision to older cloud-terminal runs. Native stable-local references use their
finalized publication operation. Explicit promotion remains available for older local
runs and keeps its existing synchronous cloud-reference guarantees.

## Attempt and terminal states

`retry()` creates another numbered attempt against the same `RunSpec`. Earlier attempts
and the run plan remain unchanged.

An attempt ends as `succeeded`, `failed`, `preempted`, or `cancelled`. A `ResolvedRun`
ends as `succeeded`, `failed`, or `cancelled`. A successful `ResolvedRun` identifies
exactly one successful attempt.

## Inspect exact fields

Query the schemas installed with the current package:

```bash
viper --json schema RunSpec
viper --json schema ResolvedRun
viper --json schema Spec
```

List every available schema and operation:

```bash
viper --json capabilities
```

See [How VIPER works](../explanation/how-viper-works.md) for the execution walkthrough
and [What VIPER guarantees](../explanation/guarantees.md) for the verification boundary.
