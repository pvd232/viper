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
| `Spec` | Declares one stage's function, config, inputs, outputs, metrics, objective, runtime override, reuse policy, and file-access mode. |
| `ResolvedSpec` | Records the artifacts and runtime evidence produced by one stage attempt. |
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

## File references

A source reference such as `GitFileRef` selects a repository, revision, and path. A
resolved file reference adds the byte count and SHA-256 digest, which VIPER checks when
retrieving the file. A local storage reference identifies its producer workspace,
durable store instance, content-derived revision, and path. This lets another local
workspace retrieve the referenced bytes without confusing the producer store with its
own. Git and Hugging Face references use repository commits. See
[`viper.references`](../../src/viper/references.py).

## Workspace and cloud paths

`viper.repository.init_workspace()` creates the starter files returned by
[`workspace_files()`](../../src/viper/repository.py). A run then writes its records and
artifacts under the same workspace root:

```text
<workspace>/
├── src/<package>/                 # workspace-owned stage code
├── tests/                         # workspace-owned tests
├── benchmarks/                    # benchmark declarations
├── experiments/<experiment_id>/
│   └── runs/<variant_id>/<run_id>/
│       ├── resolved.yaml
│       ├── stages/<stage_id>/
│       ├── artifacts/<stage_id>/<output_name>/<relative_path>
│       └── attempts/<attempt_id>/
└── .viper/
    ├── store/                     # immutable local objects
    ├── workspaces/                # materialized execution workspaces
    ├── pointers/                  # retained artifact pointers
    └── catalog.sqlite3
```

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

Cloud publication makes a stage output eligible for local eviction only after the
run succeeds and its parity decision is accepted. Call
`execution.evict_cloud_backed_run_artifacts()` with that `RunResult`, or its retained
`ResolvedRunRef` after a restart, and the same cloud client on any host running the
workspace. VIPER verifies the local terminal record, selected attempt, sealed
snapshot manifest, and the complete local and remote bytes before deleting any
artifact. It checks every candidate before the first deletion, so one mismatch leaves
the complete local set untouched.

The operation preserves inputs, the terminal record, attempt records, journals,
resolved stage documents, measurements, and logs. A second call releases zero bytes.
It refuses unsuccessful runs and attempts containing local-only stage snapshots. A
download cache may be removed without another cloud copy when its exact upstream
reference and expected digest are retained. Never manually evict a file selected only
by a `LocalFileRef` or a local stage snapshot.

`GcsViperCloudClient` streams path-backed uploads and `fetch_to_path()` restores large
objects through a temporary file followed by an atomic rename. The in-memory `fetch()`
method remains appropriate for small protocol documents.

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
