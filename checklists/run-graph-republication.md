# Run Graph Republication Checklist

The [typed workspace](run-graph-republication.toml) registers the existing
[contract](../contracts/run-graph-republication.md). The migration baseline is
complete: 1,305 required payloads and four recovered models, with original GCS
objects and model pointers preserved. The [completion record](../evidence/run-graph-republication-completion-20261018.json)
binds acceptance and passing GitHub checks.

Review and integration remain pending. The contract's
[PR tracking table](../contracts/run-graph-republication.md#pr-review-and-integration)
records each observed head, checks, review decision, and merge state separately
from completed migration validation. Review and merge VIPER #5 through #13 in
order, retargeting each successor to `main`, then RICO #26. Continue with VIPER
#14 → #15 and RICO #27. PB-09–14 local validation is complete; review and merge
remain pending. The contract links their checks and measurements.

## Current outcome

Reduce repeated publication hashing, manifest reads, directory traversal, and
RICO request reads while preserving the completed migration's guarantees.
PB-09–14 are implemented and locally validated. PB-12–14 add bounded cache
retention, streaming metric hashing, and benchmark verification reuse. Continue
independent review after #15 with #16, #17, then PB-14, and integrate in that order. The [impact analysis](../contracts/run-graph-republication-optimization-impact.md)
records measured operation counts, memory use, exact owners, and remaining timing limits.

<details>
<summary>Historical compiler snapshot; current PR-backed completion is above</summary>

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

</details>

## Completion rules

Every new block names its scope, observing gate, and linked implementation PR.
Git retains the candidate; the PR diff presents it for review. Target-path formatting
precedes Pyrefly, affected tests, directory-discovered documentation checks, and
final non-mutating Ruff checks. Escalate only when the impact trace reaches a
wider consumer. Record actual operation counts and timings separately from the
estimates. Preserve saved inference outputs and completed migration evidence.
