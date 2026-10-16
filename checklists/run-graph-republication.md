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

## Finished

- [x] Use one `RunFetcher` with `read()` and `path()`. Remove the subclass and
  verification flag. Check pre-existing artifacts once per execution and reuse
  publication hashes. Committed in
  [`27fbcaf8`](https://github.com/pvd232/viper/commit/27fbcaf8446cbeb2e76d8fee5717c43ce38006f8).
- [x] Pass the same fetcher into promotion. Remove the duplicate document reader
  and preserve the original cause of read failures. Committed in
  [`b1d5d9da`](https://github.com/pvd232/viper/commit/b1d5d9dab58c37524552c4e798282460080e7650).

The [RGP-PB-01 record](../plans/run-graph-republication/RGP-PB-01/README.md)
links the checks for both changes. Ordinary local promotion remains supported.
Cloud graph republication remains planned.

## Next step

RGP-PB-02 will let the caller specify which storage to move. VIPER must then
follow every dependency from the selected run, including links from Hugging Face
back to GCS, and list the required files before copying anything. Source reads
must keep using the original storage settings after a new destination is chosen.

<!-- contract-protocol:generated:start -->
**Resume here:** [Resume at RGP-PB-02](../contracts/run-graph-republication.md#rgp-pb-02)


### Phase 1: Read verified source documents

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-01</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-01) | <nobr><code>RGP-PB-01</code></nobr> | None |

### Phase 2: Select and discover the complete graph

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-02</code></nobr> | in_progress | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-02) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-01</code></nobr> |
| <nobr><code>RGP-REQ-03</code></nobr> | in_progress | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-03) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-02</code></nobr> |

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

The first phase reuses storage tests for content checks. One promoter test covers
fetcher delegation and the cause of a failed read. Existing promotion tests cover
ordinary publication and staging from neighboring stores. Later phases must
cover their declared rejection cases before their gates can pass. Measurements
from real transfers remain part of the rehearsal and model migration.

## Owner inputs and external actions

| Input or action | First consumer | Evidence required |
|---|---|---|
| Original provider-neutral GCS binding | Source-selection implementation and rehearsal | Frozen bucket and prefix; source reads independent of destination configuration. |
| Exact selected run roots and independent inventory | Real-model pilot preflight | Immutable root references and every required role/file identity. |
| Destination repository, access, quotas, and resource limits | Rehearsal and pilot | Existing repository, checked publication access, measured capacity, and explicit budgets. |
| Model source commit, runtime, fixture inputs, expected outputs, comparator | Cold recovery | Frozen identities and a comparison rule selected before inference. |
| Application pointer paths and generation | Final cutover | Complete old/new mapping and all selected acceptance references. |
| Authorization for real publication and pointer cutover | Operational migration | The user authorizes the concrete selected roots, destination, and pointer transition. |

The first block is installed. Model transfer and pointer cutover belong to the
final operational run. Application bindings are required before that run's
plan becomes executable.

## Deferred work

Training, full benchmark reruns, changing scientific formats, general migration
frameworks, automatic deletion of original GCS objects, and removal of every
external source-code repository are outside this contract. `export_run()` keeps
its separate archival responsibility. Broader dead-code cleanup belongs to a
different review unless the current block removes the last caller.
