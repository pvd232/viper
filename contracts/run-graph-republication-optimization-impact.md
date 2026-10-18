# Publication Work Reuse

## Decision and fixed scenario

Extend the existing journal, provider, space checker, and RICO checks. Preserve
all public APIs and persisted formats. The comparison uses the completed MIL /
Hopfield publication at VIPER `462b202` and RICO `cd81561d`: 783 snapshot mappings,
2,605 file addresses, 1,305 required payloads, and four recovered models.

The [completion record](../evidence/run-graph-republication-completion-20261018.json)
binds the inspected commits, passing CI, acceptance artifact, and scan observations.
An identical scientific result, full address mapping, and saved recovery output
is required before and after each optimization.

## Invariants and minimum design

| Decision | Existing owner and selected change | New or retired surface |
|---|---|---|
| Prepared identities | `PublicationJournal.publish` calls existing `provider.publish_revision` with its computed files and revision. | Retire its second VIPER hash pass and redundant returned-identity comparison; retain public `publish` for ordinary callers. |
| HF manifest | `PublicationJournal._verify` and `GraphComparison.verify` reuse their full `RevisionManifest` equality check. | Replace the following generic inventory branch with `elif`; other providers retain inventory checks. |
| Space accounting | Extend `TransferSpace.check` / `directory_bytes` to compute both totals together. | Retire the second traversal; preserve a separate inode set and confinement root for each total. |
| RICO reads | `model_checks`, `register`, and `recovery_reports` share bytes already read within one invocation. | Retire repeated request parsing and per-seed pointer hashing. |
| Verified downloads | PB-12 retains comparison downloads for semantic verification and reclaims only when a reservation needs room. | Reuses existing cleanup; no cache format or durable index. |

Reuse wins for identities, manifests, and RICO records. Extend the existing
space counter to report staging and cache totals together.
A new publication framework, trusted-hash public API, or persistent verification
index adds an authority whose invariant already has an owner. Keeping the duplicate
work remains the fallback if a candidate changes rejection behavior or fails to
show the expected operation-count reduction.

Every block preserves first-use size/SHA checks, source confinement, journal
intent before upload, exact-commit recovery, destination byte readback, full
source identities, independent graph comparison, capacity limits, and cold
acceptance with source storage blocked. File mutation between preparation and
upload must fail destination readback before the binding becomes complete.

## Baseline analysis for PB-09–11

Before PB-09, the first avoidable work was the provider recomputing the identities just
computed by the journal. That review also found the following manifest,
filesystem, and RICO repetitions. The diagrams govern the same input and result.

### Current DAG

```mermaid
flowchart TD
    A["Staged sources"]:::current -->|"source_file"| B["Journal: files + expected manifest"]:::implementation
    B -->|"cloud.publish: source_file again"| C["Provider hashes inputs again"]:::gap
    C -->|"publish_revision"| D["Pinned destination commit"]:::implementation
    D -->|"read_manifest then list_files"| E["Same HF manifest read twice"]:::gap
    E -->|"payload readback"| F["Verified journal binding"]:::implementation
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Proposed change DAG

```mermaid
flowchart TD
    A["Staged sources"]:::current -->|"source_file once"| B["Journal: files + expected manifest"]:::implementation
    B -->|"Proposed: reuse files and revision"| C["Existing publish_revision"]:::proposed
    C -->|"commit"| D["Pinned destination commit"]:::implementation
    D -->|"Proposed: one full manifest equality check"| E["Existing destination byte readback"]:::proposed
    E -->|"save after readback"| F["Same verified journal binding"]:::implementation
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Integrated DAG

```mermaid
flowchart TD
    A["Same staged inputs"]:::current -->|"one identity computation; save intent"| B["Journal + existing provider"]:::proposed
    B -->|"one manifest check; unchanged byte readback"| C["Same verified journal binding"]:::implementation
    C -->|"full addresses and frozen inventory"| D["Independent GraphComparison"]:::implementation
    D -->|"check staging and cache budgets"| E["Proposed: one traversal, two totals"]:::proposed
    E -->|"same accepted graph"| F["Fresh-process model recovery"]:::implementation
    F -->|"saved predictions and reports"| G["Proposed: RICO reuses request reads"]:::proposed
    G -->|"same registration checks"| H["Same additional-publication result"]:::implementation
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

## Propagation and removal map

Paths below belong to VIPER unless prefixed with `rico:`. New tests are
**PlannedAddition**; implementation will create these observers.

| Surface | Disposition and owner |
|---|---|
| [Journal](../src/viper/execution/_promotion_journal.py), [comparison](../src/viper/execution/_promotion_compare.py) | Change in RGP-PB-09 / RGP-REQ-11. Remove duplicate hash/manifest work. |
| [Provider](../src/viper/_cloud.py), [HF provider](../src/viper/huggingface.py), [cloud service](../src/viper/cloud.py) | Retain APIs and byte validation; reuse `publish_revision`. |
| [Transfer](../src/viper/execution/_promotion_transfer.py) | Change in RGP-PB-10 / RGP-REQ-12. Replace two traversals with one. |
| [Worker](../src/viper/execution/_promotion_worker.py), [reader](../src/viper/_source.py), [verified cache](../src/viper/_verified_cache.py) | PB-12 changes comparison-to-verifier retention; source readback and fresh-process checks stay independent. |
| `rico:tools/graph_publication/checks.py` | Change in RGP-PB-11 / RGP-REQ-13. Reuse loaded request bytes and pointer digests. |
| `rico:tools/graph_publication/recover.py` | Retain scientific inference, request binding, and report-repair behavior. |
| [Cloud tests](../tests/test_cloud_service.py) | PlannedAddition: `test_republication_reuses_prepared_identities`, `test_transfer_space_scans_both_budgets_once`. |
| [Execution tests](../tests/test_run_execution.py) | PlannedAddition: `test_republication_reads_manifest_once`. Reuse the connected graph builder and existing adversarial cases. |
| `rico:tests/test_graph_publication.py` | PlannedAddition: `test_registration_reuses_request_and_pointer_reads`; extend the existing registration fixture. |

Public types, serialized fields, journal records, manifest bytes, prediction
artifacts, and original model pointers retain their existing owners and values.

## Savings and measurement obligations

| Change | Static work reduction | Conditional time estimate | Estimated production-line delta |
|---|---|---|---|
| Prepared identities | 48,900,835,694 fewer bytes hashed by VIPER over a full new publication | 49 seconds at an assumed 1 GB/s | Approximately zero |
| Manifest reuse | 1,566 fewer manifest loads across publication and comparison | Unmeasured; cached reads may be entirely local | Zero |
| Combined scans | 5,210 fewer cache traversals for the 2,605-address comparison | About 18 minutes if the recorded 0.21-second scan cost persists | +10 to +25 |
| RICO reuse | One request read per request and one pointer digest per distinct pointer per invocation | Negligible compared with migration | -10 to +10 |
| Cache retention (original estimate) | Up to one 48.9 GB destination pass when retained files fit | 8.2 minutes at an assumed 100 MB/s, plus request overhead | +40 to +100, provisional |

These projections require candidate measurements; their savings overlap. Retain operation
counts, elapsed time, input identity, production additions/deletions, and memory /
disk peaks for the tested candidate. Run fixed-input baseline and candidate
measurements in alternating order. Compare the same filesystem tree; concurrent
file changes invalidated equivalence claims in the older scan observations.
Fixed local fixtures validate these patches while preserving production transfers and saved model predictions.

## Implemented follow-ups: PB-12–14

The extension keeps the same graph and evidence inputs. It changes only these
operations within one invocation:

| Block | Removed work and replacement | Observed result |
|---|---|---|
| PB-12 | Replace eager destination deletion after every comparison with existing cleanup on budget pressure; reserve missing files before semantic verification. | Two-file fixture: 4 destination downloads become 2 with room, or 3 after eviction. +32/-9 production lines. |
| PB-13 | Replace whole-file allocation with `hashlib.file_digest` and size from the same open descriptor. | 64 MiB fixture: 67,113,490 peak Python bytes become 267,745; identical hash/size. Median 37.90 ms becomes 33.82 ms over 10 alternating pairs. +4/-2 production lines. |
| PB-14 | Reuse the candidate and confirmation-stage checks; move metric criteria/status into the existing private verification module. | Candidate full checks 2 → 1; confirmation-stage checks 2 → 1; independent confirmation executions remain 1. +163/-175 production lines. |

The combined production change is **+13 lines**. No new serialized record,
persistent cache, global verification cache, or public verification bypass is
introduced. The benchmark helper is outside the public export list; only the
executor supplies previously checked evidence, under the same policy and fetcher.
It binds confirmation stages to the exact attempt read back. Public verification
always checks its own candidate and confirmation. The executor still verifies
published candidate bytes before accepting the assembled result.

Cache retention excludes journal-to-comparison sharing: independent comparison
still reads both endpoints. Source cleanup, budget/confinement rejection, final
cleanup, and fresh-reader corruption checks remain. Streaming hashing preserves
ordered file identities and the worker's independent pre-execution check.
Benchmark lineage, new-attempt/snapshot checks, metric receipts, thresholds,
artifact parity, and status validation remain.

See retained [PB-12](../evidence/rgp-pb12-validation.json),
[PB-13](../evidence/rgp-pb13-validation.json), and
[PB-14](../evidence/rgp-pb14-validation.json) results. Network and full benchmark
wall-time savings are unmeasured. Original GCS publications, model pointers,
and completed scientific measurements are unchanged.
