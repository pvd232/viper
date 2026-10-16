# Run Graph Republication Checklist

This checklist coordinates the [Run Graph Republication contract](../contracts/run-graph-republication.md).
The [typed workspace](run-graph-republication.toml) places each requirement once;
the [contract declaration](../contracts/run-graph-republication.toml) owns the
requirements, verifiers, PairBlocks, and their dependencies.

## Terminal outcome

Each selected MIL and Hopfield root has a native Hugging Face replacement with
unchanged scientific payloads, preserved graph relationships, and successful
cold recovery and bounded inference with Mantra unavailable. Canonical SOTA
pointers advance together after all selected roots pass. The original roots and
GCS objects remain available for rollback.

## Checklist semantics

Status comes only from compiled declarations and verified receipts. A passing
candidate gate permits review. Installed implementation, real-model acceptance,
and user approval each require their own evidence. Commit and review each bounded slice
before the next begins. Future plans are frozen against their actual baseline.

## Inspected baseline

At `77acb8382697af7fd5eb975e3afab6791505e626`, the promoter handles local graphs,
the verified reader supports provider-specific references, and the Hugging Face
provider writes a manifest and returns an exact commit. The current discovery
and promotion shortcuts leave cloud dependencies unchanged. These are source
observations; the new migration acceptance path is still planned.

<!-- contract-protocol:generated:start -->
**Resume here:** [Resume at RGP-PB-01](../contracts/run-graph-republication.md#rgp-pb-01)


### Phase 1: Read verified source documents

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-01</code></nobr> | in_progress | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-01) | <nobr><code>RGP-PB-01</code></nobr> | None |

### Phase 2: Select and discover the complete graph

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-02</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-02) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-01</code></nobr> |
| <nobr><code>RGP-REQ-03</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-03) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-02</code></nobr> |

### Phase 3: Rewrite and publish cloud snapshots

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-04</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-04) | <nobr><code>RGP-PB-03</code></nobr> | <nobr><code>RGP-REQ-03</code></nobr> |

### Phase 4: Recover interrupted publication

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-05</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-05) | <nobr><code>RGP-PB-04</code></nobr> | <nobr><code>RGP-REQ-04</code></nobr> |

### Phase 5: Bound transfer resources

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-06</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-06) | <nobr><code>RGP-PB-05</code></nobr> | <nobr><code>RGP-REQ-05</code></nobr> |

### Phase 6: Compare graph meaning

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-07</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-07) | <nobr><code>RGP-PB-06</code></nobr> | <nobr><code>RGP-REQ-04</code></nobr>, <nobr><code>RGP-REQ-06</code></nobr> |

### Phase 7: Rehearse cold recovery

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-08</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-08) | <nobr><code>RGP-PB-07</code></nobr> | <nobr><code>RGP-REQ-07</code></nobr> |
| <nobr><code>RGP-REQ-09</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-09) | <nobr><code>RGP-PB-07</code></nobr> | <nobr><code>RGP-REQ-08</code></nobr> |

### Phase 8: Migrate selected models and switch pointers

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-10</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-10) | <nobr><code>RGP-PB-08</code></nobr> | <nobr><code>RGP-REQ-09</code></nobr> |
<!-- contract-protocol:generated:end -->

## Completion evidence

Every phase closes through its declared verifier cases and the exact current
PairBlock gate. Python gates run Pyright, affected tests, documentation checks,
Ruff format checking, then Ruff lint checking. Apply import and formatting
repairs at the materialized target paths before that recorded sequence.
Discover Python files under the plan's source and test roots for documentation
coverage; inspect every new or changed schema field when a block introduces one.

The first phase checks the new reader on local, GCS, and Hugging Face references,
rejects missing and altered bytes, preserves exception causes, and runs existing
promotion regressions. Later phases must cover the named rejection cases in the
contract before their candidate gates can pass. Live rehearsal, resource peaks,
and real-model receipts remain separate from controlled provider tests.

## Owner inputs and external actions

| Input or action | First consumer | Evidence required |
|---|---|---|
| Original provider-neutral GCS binding | Source-selection implementation and rehearsal | Frozen bucket and prefix; source reads independent of destination configuration. |
| Exact selected run roots and independent inventory | Real-model pilot preflight | Immutable root references and every required role/file identity. |
| Destination repository, access, quotas, and resource limits | Rehearsal and pilot | Existing repository, checked publication access, measured capacity, and explicit budgets. |
| Model source commit, runtime, fixture inputs, expected outputs, comparator | Cold recovery | Frozen identities and a comparison rule selected before inference. |
| Application pointer paths and generation | Final cutover | Complete old/new mapping and all selected acceptance references. |
| Authorization for real publication and pointer cutover | Operational migration | The user authorizes the concrete selected roots, destination, and pointer transition. |

Preparing this contract and its first candidate produces planning and review
artifacts. Model transfer and pointer cutover belong to the final operational run. Application bindings are required before the final operational
plan becomes executable.

## Deferred work

Training, full benchmark reruns, changing scientific formats, general migration
frameworks, automatic deletion of original GCS objects, and removal of every
external source-code repository are outside this contract. `export_run()` keeps
its separate archival responsibility. Broader dead-code cleanup belongs to a
different review unless the current block removes the last caller.
