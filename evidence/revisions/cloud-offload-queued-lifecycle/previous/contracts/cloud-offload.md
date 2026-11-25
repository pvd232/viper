# Cloud Offload

## 1. Status

**Contract status:** expanded declaration; guided implementation in progress; no cloud-offload implementation gate or completion receipt is asserted.

The canonical [package](cloud-offload.toml) preserves CFO-REQ-01, CFO-VR-01 and CFO-PB-01 unchanged. The [transition record](../evidence/revisions/cloud-offload-storage-policy/README.md) retains the original declaration, the production-computed revision plan and metadata validation. Existing source edits remain unverified work. The [checklist](../checklists/cloud-offload.md) and [pair-coding queue](../plans/cloud-offload/QUEUE.md) distinguish authored code from planned integration.

| ID | Implementation obligation |
| --- | --- |
| <nobr><code>CFO-REQ-01</code></nobr> | Preserve exact original snapshot references and member identities. |
| <nobr><code>CFO-REQ-02</code></nobr> | Persist complete immutable inventory and one mutable location registry. |
| <nobr><code>CFO-REQ-03</code></nobr> | Resolve ordinary files through one shared verified storage owner. |
| <nobr><code>CFO-REQ-04</code></nobr> | Apply one global retention default and one override per exact artifact version. |
| <nobr><code>CFO-REQ-05</code></nobr> | Derive shared subscriber permissions and coordinate live readers. |
| <nobr><code>CFO-REQ-06</code></nobr> | Enroll managed inputs, outputs and restorations under one native workflow lifetime. |
| <nobr><code>CFO-REQ-07</code></nobr> | Queue exact direct-source publication durably outside computation. |
| <nobr><code>CFO-REQ-08</code></nobr> | Authorize every managed deletion through one current eligibility decision. |
| <nobr><code>CFO-REQ-09</code></nobr> | Preserve recovery, original-reference restoration and truthful API completion. |
| <nobr><code>CFO-REQ-10</code></nobr> | Remove displaced ownership and demonstrate maintained-code reduction. |

## 2. Claim

Viper preserves exact artifact identity while managing verified local availability, background cloud publication and conditional local release through one storage mechanism.

An immutable snapshot address and its original file inventory identify bytes. Physical locations, local retention and active readers are mutable state. Changing a preference or moving a local payload cannot rewrite the snapshot, run record, queued publication identity or completed receipt.

The public default remains storage.offload = false. Overrides are inherit, keep and offload. Inherit reads the current project default. Explicit keep is persisted before restoration and completes only after every bundle member is verified locally; failure preserves the preference. Global keep retains produced or accessed bytes without restoring the historical catalog. Offload permits removal but does not force it or create an upload destination.

## Analysis basis

This revision adopts the user's retention augmentation and the nine accepted refinements following ten independent design reviews. It replaces the pending per-operation capture registry with one store registry, and drops generic durable holds for unsupported raw-path handoffs.

Current defining owners inspected: LocalArtifactStore in storage.py, RunFetcher in _source.py, VerifiedObjectCache in _verified_cache.py, capture_external_input in execution/_materialization.py, PublicationJournal in execution/_promotion_journal.py, and evict_cloud_backed_run_files in retention.py. The current Viper has publication journals and blocking promotion; the durable background-admission pattern exists in JEP background_storage.py at 23ccbf24, with immutable-generation verification in full_data_prompt_uploads.py at 925d26ea. Native durable admission remains an implementation obligation.

## 3. Models

| Model or owner | Role and disposition |
| --- | --- |
| Existing SnapshotInventory and shared inventory validator | Retain exact original source and canonical full membership. |
| Existing RevisionManifest and SnapshotCopy | Retain immutable cloud inventory and authoritative verified copy proof. |
| Existing LocalSource and SnapshotSources | Reuse for mutable locations. A retired binding is invalid for resolution; retirement alone never authorizes byte deletion. |
| Proposed StorageRegistry | Own inventories, derived member index, current/historical local bindings and retention rows beneath the owning store. No duplicate upload state machine. |
| Proposed private artifact-version key | Existing immutable snapshot plus an existing named artifact selection, or one exact member path for a sealed standalone input. Complete bundle membership is reused. |
| Proposed PayloadLocks and WorkflowReaders | Hold shared content protection for tracked workflow lifetimes; ordinary process exit releases protection. No persistent reader counts. |
| Proposed native publication collection | Refer to registry snapshot identities and pinned destinations. Collection closes before final inventory/proof completion; source locations and retention remain registry-owned. |

A source path is an observed materialization, not artifact identity. Repeated reads do not register new persistent subscribers. A changed external input seals a new version; an absent managed input resolves the registered prior version. User-owned exports require deliberate enrollment before automatic removal.

## 4. Execution

1. Finish saving each native output and relinquish further writes.
2. Hash through existing identity owners and register complete immutable inventory plus explicitly owned original paths. Do not copy originals merely to populate the cache.
3. Register the exact artifact version and existing member relationships once.
4. Persist publication admission before returning; workers resolve current source locations and use the existing exact-copy journal/provider path independently of later computation.
5. Resolve subsequent reads through verified originals, shared payloads under .viper/store or verified backing. Preserve directory views needed by bundle loaders.
6. Retain shared reader protection until the native workflow has joined training, inference, evaluation, diagnostics and nested work.
7. Close collection with final roots and inventory. Verify all required objects and final receipts at every admitted destination.
8. Recheck current subscriber permissions, reader protection, backing, ownership and the exact physical materialization before deletion. Keep one usable copy if any subscriber requires it.
9. Keep inventory, preferences, bindings and recovery records after eviction; restore through the same resolver later.

Network transfers never hold the global registry metadata transaction. A queue returning does not authorize destroying its pending sources or source host.

## 5. Persisted evidence

| Record | Purpose |
| --- | --- |
| contracts/cloud-offload.toml | Canonical guarantees, observing checks and PairBlock dependencies. |
| checklists/cloud-offload.toml | Requirement placement, repository ownership and executable bindings. |
| .viper/store/registry.sqlite3, proposed | Store-owned inventory links, derived indexes, exact local bindings and retention rows. |
| Existing per-target publication journal | Upload intent, reconciliation and committed byte-verification proof. |
| Proposed native collection and portable final receipt | Frozen operation membership, admitted destinations and complete proof coverage; no competing retention/location state. |
| evidence/revisions/cloud-offload-storage-policy/previous/contracts/cloud-offload.toml | Exact pre-expansion authored declaration. |
| evidence/revisions/cloud-offload-storage-policy/plan.json | Real production DeclarationRevisionPlan; planning evidence, not a revision-application receipt. |
| plans/cloud-offload/CFO-PB-*/ | Complete authored action payloads where available; future baselines are frozen only when known. |

## 6. Verification

The package names exact success and rejection targets. All implementation checks remain planned until the user runs them against a frozen candidate.

| Rule | Executable condition |
| --- | --- |
| <nobr><code>CFO-VR-01</code></nobr> | Exact source/destination inventory, original seal and unchanged reference. |
| <nobr><code>CFO-VR-02</code></nobr> | Durable inventory, conflicting-binding rejection and corruption distinction. |
| <nobr><code>CFO-VR-03</code></nobr> | Shared verified resolution, complete listing and failed-download rejection. |
| <nobr><code>CFO-VR-04</code></nobr> | Current default, both overrides and failed keep preserving intent. |
| <nobr><code>CFO-VR-05</code></nobr> | Derived unanimous permissions and keep defeating stale cleanup. |
| <nobr><code>CFO-VR-06</code></nobr> | Managed dataset reuse, changed-source versioning and export ownership. |
| <nobr><code>CFO-VR-07</code></nobr> | Direct original upload and full cloud verification before acknowledgment. |
| <nobr><code>CFO-VR-08</code></nobr> | Whole-workflow, all-target, reader and exact-file cleanup gates. |
| <nobr><code>CFO-VR-09</code></nobr> | Restart restoration, existing proof reuse and synchronous return guarantees. |
| <nobr><code>CFO-VR-10</code></nobr> | One Viper owner per responsibility and no legacy cleanup bypass. |
| <nobr><code>CFO-VR-11</code></nobr> | Durable nonblocking admission and publication-only recovery. |
| <nobr><code>CFO-VR-12</code></nobr> | Overlapping readers, process exit and closed-workflow rejection. |
| <nobr><code>CFO-VR-13</code></nobr> | JEP adapter migration without repeated computation or duplicate orchestration. |

Use the existing .venv and Pyrefly as the sole type checker. Freeze type checking before focused tests, then documentation/schema checks, then Ruff format --check and Ruff check last. Native execution changes require the applicable integration gate. No GPU provisioning or live-cloud spend is required for the first CPU/mock checks.

## 7. Propagation

| Surface | Required change |
| --- | --- |
| _cloud.py | Retain the shared validator and formats; separate binding invalidation from deletion permission. |
| New _storage_registry.py | Extend the store owner with the single authoritative inventory/location/retention registry. |
| storage.py | Register complete inventories; unify reads and listing; decouple retention from publication destination. |
| _source.py and _verified_cache.py | Delegate ordinary persistent payload ownership; reuse verification and atomic installation; preserve bounded task caches. |
| Existing retention.py | Add the narrow preference setter; later route legacy eviction through the single deletion decision. |
| Native run/batch/benchmark, stage and metric workers | Share and explicitly forward workflow ownership; register all final records and join consumers before closure. |
| capture_external_input and restoration | Enroll managed copies before removal; preserve mutable source semantics and user-owned exports. |
| Publication journal and providers | Retain legacy explicit promotion; add exact-original publication and restart behavior. |
| JEP publication callers | Migrate in the JEP-owned <nobr><code>CFO-PB-09</code></nobr>, after native acceptance, before deleting duplicated queue/cleanup code. |
| Tests, configuration/API docs and line report | Observe ordinary lifecycle and document the actual new settings and completion boundaries. |

## 8. Acceptance case

### Success

Train a two-file checkpoint bundle, publish directly from its completed originals while inference and diagnostics continue, and retain the same immutable references. Register a dataset keep preference and an offload preference on another artifact sharing bytes: the shared local payload remains. After current permissions allow offload, a successful joined workflow and all-target final proof authorize release. Restart with empty local payloads, resolve the original reference and verify restored size, SHA-256, full listing and bundle filenames.

### Rejection

Change one original member after sealing or fail remote byte verification. Publication cannot acknowledge that snapshot; the source remains recoverable. A later keep, a remaining reader, an incomplete target or replacement file also prevents an older cleanup from removing its candidate.

## 9. Implementation order

1. Adopt the existing identity work and observing tests without changing PB01's contribution.
2. Connect durable inventory/registry to the existing publisher and listing.
3. Consolidate ordinary verified resolution and prepare workflow reader protection.
4. Add exact artifact retention and derived shared permissions.
5. Add exact direct publication and provider recovery.
6. Connect durable admission, current backing lookup, stable input enrollment and native workflow closure.
7. Connect one exact deletion decision and restart/API guarantees.
8. Remove displaced Viper ownership and validate the complete lifecycle.
9. Migrate JEP callers in their repository and finish the measured reduction report.

## 10. Master checklist

The [workspace](../checklists/cloud-offload.toml) places every requirement exactly once. The [human checklist](../checklists/cloud-offload.md) points to the code tranches. No bootstrap or completion is inferred from earlier conversation or uncommitted edits.

## 11. Contract-owned PairBlocks

See the [complete queue](../plans/cloud-offload/QUEUE.md). CFO-PB-01 has a current baseline-bound plan. CFO-PB-02 through CFO-PB-05 have complete proposed file actions, pending their actual predecessor baselines and gates. CFO-PB-06 through CFO-PB-09 retain targets, contributions and observing checks without placeholder implementation bodies.

## 12. ContractTarget

| Requirement | PairBlock | Implementation owner or target | Observing check | Evidence |
| --- | --- | --- | --- | --- |
| <nobr><code>CFO-REQ-01</code></nobr> | <nobr><code>CFO-PB-01</code></nobr> | SnapshotInventory and exact-copy adapter | <nobr><code>CFO-VR-01</code></nobr> | Authored tests; no gate receipt. |
| <nobr><code>CFO-REQ-02</code></nobr> | <nobr><code>CFO-PB-02</code></nobr> | StorageRegistry and LocalArtifactStore | <nobr><code>CFO-VR-02</code></nobr> | Complete proposed files. |
| <nobr><code>CFO-REQ-03</code></nobr> | <nobr><code>CFO-PB-03</code></nobr>, <nobr><code>CFO-PB-06</code></nobr>, <nobr><code>CFO-PB-08</code></nobr> | Shared resolver and verified-backing connector | <nobr><code>CFO-VR-03</code></nobr> | Resolver foundation authored; backing connector planned. |
| <nobr><code>CFO-REQ-04</code></nobr> | <nobr><code>CFO-PB-04</code></nobr> | Store-owned preferences and existing retention module | <nobr><code>CFO-VR-04</code></nobr> | Complete proposed files. |
| <nobr><code>CFO-REQ-05</code></nobr> | <nobr><code>CFO-PB-03</code></nobr>, <nobr><code>CFO-PB-04</code></nobr>, <nobr><code>CFO-PB-07</code></nobr> | Readers, membership votes and final decision | <nobr><code>CFO-VR-05</code></nobr>, <nobr><code>CFO-VR-12</code></nobr> | Mechanisms authored; integrated decision planned. |
| <nobr><code>CFO-REQ-06</code></nobr> | <nobr><code>CFO-PB-06</code></nobr>, <nobr><code>CFO-PB-08</code></nobr> | Native input and materialization owners | <nobr><code>CFO-VR-06</code></nobr> | Planned. |
| <nobr><code>CFO-REQ-07</code></nobr> | <nobr><code>CFO-PB-05</code></nobr>, <nobr><code>CFO-PB-06</code></nobr> | PublicationJournal, providers and native durable admission | <nobr><code>CFO-VR-07</code></nobr>, <nobr><code>CFO-VR-11</code></nobr> | Direct foundation authored; admission planned. |
| <nobr><code>CFO-REQ-08</code></nobr> | <nobr><code>CFO-PB-07</code></nobr> | Unified managed deletion owner | <nobr><code>CFO-VR-08</code></nobr> | Planned. |
| <nobr><code>CFO-REQ-09</code></nobr> | <nobr><code>CFO-PB-05</code></nobr> through <nobr><code>CFO-PB-08</code></nobr> | Publication recovery, resolver, closure and API owners | <nobr><code>CFO-VR-09</code></nobr> | Partial direct foundation authored. |
| <nobr><code>CFO-REQ-10</code></nobr> | <nobr><code>CFO-PB-08</code></nobr>, <nobr><code>CFO-PB-09</code></nobr> | Viper consolidation and JEP adapter | <nobr><code>CFO-VR-10</code></nobr>, <nobr><code>CFO-VR-13</code></nobr> | Removal map planned; reduction not yet measured. |

