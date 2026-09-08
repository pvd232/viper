# VIPER protocol reference

VIPER stores the request for a run separately from the evidence produced while
executing it. This page is a map of those records. Use the installed schemas
for their exact fields.

## Record map

| Record | Purpose |
| --- | --- |
| `ExperimentSpec` | Defines factors, variants, replicates, and metrics. |
| `VariantSpec` | Selects the stage graph and config for each stage. |
| `RunSpec` | Selects one variant and replicate, the source revision, runtime, reproducibility settings, estimator, optional benchmark, and ordered stages. |
| `Spec` | Declares one stage's function, config, inputs, outputs, metrics, objective, runtime override, and reuse policy. |
| `ResolvedSpec` | Records the artifacts and runtime evidence produced by one stage attempt. |
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

Workspace functions therefore write through `context.outputs`. Verification,
restore, and catalog queries consume artifact records.

## Input references

| Type | Selects |
| --- | --- |
| `ExternalInputRef` | A repository file captured for the current run. |
| `FutureInputRef` | An output from an earlier stage in the same run. |
| `StoredInputRef` | An artifact from a verified earlier run. |

Download stages use `HttpRequestSpec` instead. The request stores the expected
response size and SHA-256 digest; the resolved retrieval records the observed
response.

## File references

Every file reference records a location, byte count, and SHA-256 digest. VIPER
checks the count and digest when it retrieves the file. References to immutable
storage also identify the repository revision that owns the path.

## Attempt and terminal states

`retry()` creates another numbered attempt against the same `RunSpec`. Earlier
attempts and the run plan remain unchanged.

An attempt ends as `succeeded`, `failed`, `preempted`, or `cancelled`. A
`ResolvedRun` ends as `succeeded`, `failed`, or `cancelled`. A successful
`ResolvedRun` identifies exactly one successful attempt.

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

See [How VIPER works](../explanation/how-viper-works.md) for the execution
walkthrough and [What VIPER guarantees](../explanation/guarantees.md) for the
verification boundary.
