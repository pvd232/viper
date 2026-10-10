# Stage Reuse Pointer First

## 1. Status

**Contract status:** Draft registered in the [Execution storage protocol](../checklists/execution-storage-protocol.md) checklist.

### Implemented increment and remaining draft

Successful execution now registers fully verified stages in the
existing catalog through `Catalog.register_run()`. A later stage with
`reuse="verified"` discovers an identical stage through automatic registration.
Python authoring and parsed workspace stage specifications select verified reuse
by default. An explicit `reuse="never"` forces computation in a new run, and
benchmark confirmation always executes independently. The
[execution test](../tests/test_run_execution.py) covers automatic discovery,
explicit refresh, `reuse="never"`, a changed seed, and a failed catalog write.
The [catalog tests](../tests/test_inspection.py) cover preservation, rollback,
conflicting writers, schema compatibility, and every reuse-key component.

This increment extends catalog-backed discovery. The producer-only search below
remains proposed: the producer of a stored input can omit the consumer stage;
adding the producer's output as a new input also changes the reuse key. Older or
imported runs and a deleted catalog still require refresh.
The typed draft's pointer-producer discovery and reference-only requirements
remain proposed, with PairBlock completion still pending. Ordinary stored inputs
continue to supply verified filesystem paths.

<!-- contract-protocol:generated:start -->
**Draft.**

**Checklist:** [Execution storage protocol](../checklists/execution-storage-protocol.md)

### PairBlocks

<a id="srpf-pb-01"></a>

#### <nobr><code>SRPF-PB-01</code></nobr>

**Status:** ready for implementation

**Requirement contribution:** Feed `StoredInputRef` producer run references into verified stage reuse selection and retain byte materialization for ordinary stage inputs.

<a id="srpf-pb-02"></a>

#### <nobr><code>SRPF-PB-02</code></nobr>

**Status:** planned

**Requirement contribution:** Add a declared pointer-first stored-input path for stages that consume immutable artifact references without payload restore.

**Dependencies:** <nobr><code>SRPF-PB-01</code></nobr>

<a id="srpf-pb-03"></a>

#### <nobr><code>SRPF-PB-03</code></nobr>

**Status:** planned

**Requirement contribution:** Update public documentation and examples for automatic pointer-backed reuse discovery, manual catalog search, and pointer-first stage input execution.

**Dependencies:** <nobr><code>SRPF-PB-01</code></nobr>, <nobr><code>SRPF-PB-02</code></nobr>

### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>SRPF-REQ-01</code></nobr> | A stage with `reuse="verified"` must be able to discover matching reusable stage results from the resolved producer runs named by its `StoredInputRef` pointers without requiring the operator to run `catalog_refresh` first. | planned | <nobr><code>SRPF-VR-01</code></nobr> | <nobr><code>SRPF-PB-01</code></nobr> |
| <nobr><code>SRPF-REQ-02</code></nobr> | Stored-input producer discovery must use the same `StageReuseKey` fields as catalog reuse: normalized stage spec, resolved input identities, seed, environment lockfile identity, reproducibility identity, and selected metric identities. | planned | <nobr><code>SRPF-VR-02</code></nobr> | <nobr><code>SRPF-PB-01</code></nobr> |
| <nobr><code>SRPF-REQ-03</code></nobr> | Stored inputs must expose pointer-backed producer evidence to reuse selection while preserving byte-verified materialization for stage callables that require filesystem paths. | planned | <nobr><code>SRPF-VR-03</code></nobr> | <nobr><code>SRPF-PB-01</code></nobr> |
| <nobr><code>SRPF-REQ-04</code></nobr> | Viper must provide a pointer-first stored-input execution path for stages that declare they can consume immutable artifact references, so large upstream artifacts are not restored to local bytes solely to pass through unchanged. | planned | <nobr><code>SRPF-VR-04</code></nobr> | <nobr><code>SRPF-PB-02</code></nobr> |
| <nobr><code>SRPF-REQ-05</code></nobr> | The public docs must distinguish automatic pointer-backed reuse discovery, manual `catalog_refresh` for search workflows, and pointer-first execution for declared reference-consuming stages. | planned | <nobr><code>SRPF-VR-05</code></nobr> | <nobr><code>SRPF-PB-03</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>SRPF-VR-01</code></nobr> | <nobr><code>SRPF-REQ-01</code></nobr> | A second run with `reuse="verified"` and `StoredInputRef` pointers reuses a matching producer stage when the local catalog database is absent. | [test_verified_reuse_discovers_stored_pointer_producer_without_catalog_refresh](../tests/test_run_execution.py) | [test_verified_reuse_rejects_pointer_producer_with_nonmatching_key](../tests/test_run_execution.py) |
| <nobr><code>SRPF-VR-02</code></nobr> | <nobr><code>SRPF-REQ-02</code></nobr> | Changing one `StageReuseKey` field on the candidate producer prevents automatic pointer-backed reuse and forces the consumer stage to execute. | [test_pointer_backed_reuse_uses_complete_stage_reuse_key](../tests/test_run_execution.py) | [test_pointer_backed_reuse_rejects_metric_identity_mismatch](../tests/test_run_execution.py) |
| <nobr><code>SRPF-VR-03</code></nobr> | <nobr><code>SRPF-REQ-03</code></nobr> | `StoredInputRef` materialization returns producer run refs for reuse selection and still writes verified bytes to `context.inputs` for ordinary filesystem-consuming stages. | [test_stored_input_producer_refs_feed_reuse_selection_and_materialize_bytes](../tests/test_run_execution.py) | [test_stored_input_rejects_unverified_pointer_before_reuse_selection](../tests/test_run_execution.py) |
| <nobr><code>SRPF-VR-04</code></nobr> | <nobr><code>SRPF-REQ-04</code></nobr> | A reference-consuming stage receives immutable artifact references for selected stored inputs and the fetcher does not restore those artifact payload bytes before invoking the stage. | [test_pointer_first_stored_input_passes_reference_without_payload_restore](../tests/test_run_execution.py) | [test_pointer_first_stored_input_rejects_stage_that_opens_missing_bytes](../tests/test_run_execution.py) |
| <nobr><code>SRPF-VR-05</code></nobr> | <nobr><code>SRPF-REQ-05</code></nobr> | The stages, inputs, catalog, and API docs name the three execution paths and no doc says `catalog_refresh` is required before pointer-backed producer reuse can be attempted. | [Reuse a verified stage result](../docs/how-to/stages.md#reuse-a-verified-stage-result) | [manual catalog refresh described as execution prerequisite](../docs/how-to/catalog-knowledge-mcp.md#build-the-local-catalog) |
<!-- contract-protocol:generated:end -->

## 2. Claim

Viper must reuse matching stage results reachable through `StoredInputRef` producer pointers without forcing the operator to rebuild the local catalog, and Viper must avoid restoring stored-input payload bytes when a stage declares that immutable artifact references are sufficient.

The execution path has two acceptance predicates:

```text
ReuseCandidate(run, stage) =
  StageReuseKey(current stage, current resolved inputs, seed, env, reproducibility, metrics)
  ==
  StageReuseKey(producer stage, producer resolved inputs, seed, env, reproducibility, metrics)

PointerFirst(input, stage) =
  stage declares reference consumption
  and input.kind == "stored"
  and input.pointer verifies to an ArtifactPointer
```

`ReuseCandidate` decides whether `reuse_stage()` may publish a reused stage result. `PointerFirst` decides whether `resolve_inputs()` may pass immutable artifact references instead of restoring the artifact bytes before the stage starts.

## Current gap

At the draft baseline, Viper required manual catalog indexing before a new run
could reuse a stage. The implemented increment above removes that operator step
for newly completed runs. [Stored-input materialization](../docs/how-to/inputs.md#use-artifacts-from-another-run)
continues to verify a pointer and retrieve the artifact before invoking the consumer.

The implementation follows that contract. `execute_attempt()` calls `reuse_stage()` with `catalog=Catalog(root)`, and `reuse_stage()` calls `catalog.reuse_candidate(key)` when no explicit retry candidate is supplied. `resolve_inputs()` verifies a stored pointer with `verify_pointer_producer()`, selects the artifact with `verify_artifact_in_run()`, and writes the verified artifact bytes through `_materialize_verified_artifact()` before the stage worker starts.

The missing connector is therefore exact and local: `resolve_inputs()` already reads and verifies the producer run behind each stored pointer, but `execute_attempt()` does not use that producer run as a stage-reuse candidate source. A second missing connector remains separate: every stored input materializes bytes because the stage contract has no declared way to consume immutable artifact references directly.

## 3. Models

| Model | Current role | Required role |
|---|---|---|
| `StoredInputRef` | Selects an artifact through an `ArtifactPointerRef` or `ResolvedArtifactPointerRef`. | Keeps selecting the artifact and supplies the verified producer run reference to reuse selection. |
| `ArtifactPointer` | Stores `run` and `artifact` so verification can select one prior-run artifact. | Remains the stored-input source record and seeds producer-run reuse discovery through `ArtifactPointer.run`. |
| `VerifiedProducerRun` | Verifies a pointer's producer structure without retaining input payload bytes. | Remains sufficient for artifact selection, but `SRPF-PB-01` must use full `verify_run_result()` when building `StageReuseKey` candidates because reuse identity needs verified input evidence. |
| `StageReuseKey` | Hashes normalized stage spec, input identities, seed, environment, reproducibility, and metric identities. | Remains the single equality used by manual catalog reuse and automatic pointer-backed reuse discovery. |
| `ResolvedStoredInputRef` | Records the exact pointer file resolved during execution. | Remains the resolved input record for byte-materialized stages and pointer-first stages. |

## 4. Execution

1. `resolve_inputs()` reads each stored pointer from `StoredInputRef.pointer`.
2. `verify_pointer_producer()` verifies the producer run structure named by `ArtifactPointer.run`.
3. `verify_artifact_in_run()` verifies the selected artifact and its declared data role.
4. `SRPF-PB-01` returns the producer `ResolvedRunRef` beside the materialized input path and the `ReuseInputIdentity`.
5. `execute_attempt()` builds the current stage's `StageReuseKey`.
6. `execute_attempt()` verifies each stored-input producer run through `verify_run_result()` and builds `catalog_reuse_candidates()` from that run.
7. `reuse_stage()` receives a matching `StageReuseCandidate` directly when one exists; otherwise it keeps querying `Catalog(root)` for manually indexed candidates.
8. `SRPF-PB-02` adds a declared stage-input mode that passes immutable artifact references to the stage worker without restoring artifact payload bytes.

## 5. Persisted evidence

| Record or file | Evidence stored |
|---|---|
| `ResolvedRunRef` in `ArtifactPointer.run` | Exact producer run selected by a stored pointer. |
| `ResolvedStoredInputRef.pointer` | Exact pointer file used by the consumer attempt. |
| `StageReuseReceipt` | Source run, source attempt, source stage, reused files, selected metrics, and the accepted `StageReuseKey`. |
| `ResolvedStageRef.snapshot` | New run snapshot containing either executed outputs or remapped reused outputs. |
| Attempt measurement and metric verification files | Metric evidence used by `StageReuseKey` and `StageReuseReceipt.metrics`. |

## 6. Verification

| Rule | Executable condition |
|---|---|
| <nobr><code>SRPF-VR-01</code></nobr> | A no-catalog second run reuses a matching stored-pointer producer stage. |
| <nobr><code>SRPF-VR-02</code></nobr> | A mismatch in any required `StageReuseKey` component prevents pointer-backed reuse. |
| <nobr><code>SRPF-VR-03</code></nobr> | Producer refs feed reuse selection while ordinary stored inputs still materialize verified bytes for `context.inputs`. |
| <nobr><code>SRPF-VR-04</code></nobr> | A reference-consuming stage receives artifact references and no payload restore occurs before invocation. |
| <nobr><code>SRPF-VR-05</code></nobr> | Public docs describe automatic pointer-backed reuse discovery, manual catalog search, and pointer-first stage input execution as distinct paths. |

## 7. Propagation

| Surface | Required change |
|---|---|
| [execution/_materialization.py](../src/viper/execution/_materialization.py) | Return stored-input producer run references with resolved inputs, materialized paths, captured inputs, stored references, and reuse input identities. |
| [execution/_attempt.py](../src/viper/execution/_attempt.py) | Build pointer-backed reuse candidates from stored-input producer refs and pass the exact candidate to `reuse_stage()`. |
| [execution/_reuse.py](../src/viper/execution/_reuse.py) | Preserve the candidate-first path and keep `Catalog(root)` as the fallback for manually indexed runs. |
| [reuse.py](../src/viper/reuse.py) | Keep `StageReuseKey` as the only reuse equality; do not add a weaker pointer-specific key. |
| [inputs.py](../src/viper/inputs.py) | Add any pointer-first declaration field needed by `SRPF-PB-02` without changing the meaning of existing `StoredInputRef` materialization values. |
| [docs/how-to/stages.md](../docs/how-to/stages.md) | Replace the catalog-refresh prerequisite with separate descriptions for automatic pointer-backed discovery and manual search indexing. |
| [docs/how-to/inputs.md](../docs/how-to/inputs.md) | Explain byte materialization and pointer-first reference consumption as distinct stored-input modes. |
| [docs/how-to/catalog-knowledge-mcp.md](../docs/how-to/catalog-knowledge-mcp.md) | Keep `catalog_refresh` documented as a search and explicit indexing operation, not the only route to verified reuse. |

## 8. Acceptance case

### Success

A first run produces a trained model and writes a retained `ArtifactPointer` for that model. A second run declares a stored input that uses the pointer and declares `reuse="verified"` on a matching train stage. `.viper/catalog.sqlite3` is absent. `execute_attempt()` verifies the pointer producer run, rebuilds the source stage candidate key, finds that the key equals the current stage key, and publishes a reused stage result without executing the worker.

### Rejection

A second run changes one selected metric, lockfile identity, input identity, seed, reproducibility field, or normalized stage spec. `execute_attempt()` rebuilds a different `StageReuseKey`. Pointer-backed candidate selection fails, `Catalog(root)` has no matching manually indexed candidate, and the stage executes normally.

## 9. Implementation order

1. `SRPF-PB-01` carries stored-input producer run refs from `resolve_inputs()` to `execute_attempt()` and adds no-catalog pointer-backed reuse tests.
2. `SRPF-PB-02` adds the declared pointer-first stored-input path and tests that large payload bytes are not restored for reference-consuming stages.
3. `SRPF-PB-03` updates public docs after the executable behavior and tests exist.

## 10. Contract-owned PairBlocks

| PairBlock | Context |
|---|---|
| <nobr><code>SRPF-PB-01</code></nobr> | `resolve_inputs()` already verifies stored-input producer runs, but `execute_attempt()` only reuses cataloged or retry-sourced candidates. This block connects verified stored-pointer producers to `reuse_stage()` through `StageReuseKey`. |
| <nobr><code>SRPF-PB-02</code></nobr> | Stored inputs always restore artifact bytes before invocation. This block adds a declared input mode for stages that consume immutable references directly. |
| <nobr><code>SRPF-PB-03</code></nobr> | The docs describe manual catalog refresh as the reuse prerequisite and stored inputs as byte retrieval. This block documents the implemented execution modes separately. |

## 11. ContractTarget

The source-backed plan for each PairBlock must name each changed Python module, each changed documentation file, and each changed test target. `patch` actions may update existing files only. `add` actions may introduce tests or docs only when no existing file owns the behavior. A PairBlock is complete only when its verifier tests, Pyright on changed Python files, and non-mutating Ruff checks pass.
