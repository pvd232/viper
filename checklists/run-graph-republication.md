# Run Graph Republication Checklist

The [typed workspace](run-graph-republication.toml) registers the existing
[contract](../contracts/run-graph-republication.md). The migration baseline is
complete: 1,305 required payloads and four recovered models, with original GCS
objects and model pointers preserved. The [completion record](../evidence/run-graph-republication-completion-20261018.json)
binds acceptance and passing GitHub checks.

## Current outcome

Reduce repeated publication hashing, manifest reads, directory traversal, and
RICO request reads while preserving the completed migration's guarantees.
Start with RGP-PB-09. The [impact analysis](../contracts/run-graph-republication-optimization-impact.md)
records projected savings, exact owners, and conditional cache retention.

<!-- contract-protocol:generated:start -->
**Resume here:** [Resume at RGP-PB-09](../contracts/run-graph-republication.md#rgp-pb-09)


### Phase 1: Read verified source documents

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-01</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-01) | <nobr><code>RGP-PB-01</code></nobr> | None |

### Phase 2: Select and discover the complete graph

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-02</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-02) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-01</code></nobr> |
| <nobr><code>RGP-REQ-03</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-03) | <nobr><code>RGP-PB-02</code></nobr> | <nobr><code>RGP-REQ-02</code></nobr> |

### Phase 3: Rewrite and publish cloud snapshots

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-04</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-04) | <nobr><code>RGP-PB-03</code></nobr> | <nobr><code>RGP-REQ-03</code></nobr> |

### Phase 4: Recover interrupted publication

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-05</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-05) | <nobr><code>RGP-PB-04</code></nobr> | <nobr><code>RGP-REQ-04</code></nobr> |

### Phase 5: Bound transfer resources

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-06</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-06) | <nobr><code>RGP-PB-05</code></nobr> | <nobr><code>RGP-REQ-05</code></nobr> |

### Phase 6: Compare graph meaning

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-07</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-07) | <nobr><code>RGP-PB-06</code></nobr> | <nobr><code>RGP-REQ-04</code></nobr>, <nobr><code>RGP-REQ-06</code></nobr> |

### Phase 7: Rehearse cold recovery

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-08</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-08) | <nobr><code>RGP-PB-07</code></nobr> | <nobr><code>RGP-REQ-07</code></nobr> |
| <nobr><code>RGP-REQ-09</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-09) | <nobr><code>RGP-PB-07</code></nobr> | <nobr><code>RGP-REQ-08</code></nobr> |

### Phase 8: Publish and recover the selected models

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-10</code></nobr> | complete | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-10) | <nobr><code>RGP-PB-08</code></nobr> | <nobr><code>RGP-REQ-09</code></nobr> |

### Phase 9: Remove repeated publication work

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-11</code></nobr> | in_progress | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-11) | <nobr><code>RGP-PB-09</code></nobr> | <nobr><code>RGP-REQ-05</code></nobr>, <nobr><code>RGP-REQ-07</code></nobr> |
| <nobr><code>RGP-REQ-12</code></nobr> | planned | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-12) | <nobr><code>RGP-PB-10</code></nobr> | <nobr><code>RGP-REQ-06</code></nobr>, <nobr><code>RGP-REQ-11</code></nobr> |
| <nobr><code>RGP-REQ-13</code></nobr> | in_progress | [run-graph-republication](../contracts/run-graph-republication.md#rgp-req-13) | <nobr><code>RGP-PB-11</code></nobr> | <nobr><code>RGP-REQ-10</code></nobr> |
<!-- contract-protocol:generated:end -->

## Completion rules

Every new block freezes one candidate and observing gate. Target-path formatting
precedes Pyrefly, affected tests, directory-discovered documentation checks, and
final non-mutating Ruff checks. Escalate only when the impact trace reaches a
wider consumer. Record actual operation counts and timings separately from the
estimates. Preserve saved inference outputs and completed migration evidence.
