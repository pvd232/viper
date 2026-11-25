# Cloud Offload

## 1. Status

**Contract status:** user-approved queue/locality/lifetime revision; guided implementation in progress; no implementation gate or completion receipt asserted.

The canonical [package](cloud-offload.toml) retains all requirement and PairBlock IDs. The [workspace](../checklists/cloud-offload.toml) owns registration and placement. [Original expansion history](../evidence/revisions/cloud-offload-storage-policy/README.md) is retained; the [current revision](../evidence/revisions/cloud-offload-queued-lifecycle/README.md) preserves its exact before-image and production-computed impact plan. [The code queue](../plans/cloud-offload/QUEUE.md) distinguishes user-applied foundations, proposed successors and still-planned native integration.

| ID | Implementation obligation |
| --- | --- |
| <nobr><code>CFO-REQ-01</code></nobr> | Preserve original snapshot and file identities. |
| <nobr><code>CFO-REQ-02</code></nobr> | Persist complete inventory and current physical bindings. |
| <nobr><code>CFO-REQ-03</code></nobr> | Resolve resident originals first through one shared owner. |
| <nobr><code>CFO-REQ-04</code></nobr> | Apply one global default and exact-artifact overrides. |
| <nobr><code>CFO-REQ-05</code></nobr> | Coordinate subscriber permissions and admitted consumer protection. |
| <nobr><code>CFO-REQ-06</code></nobr> | Own the full explicitly admitted workflow across child actions. |
| <nobr><code>CFO-REQ-07</code></nobr> | Durably queue all native publication outside computation. |
| <nobr><code>CFO-REQ-08</code></nobr> | Queue cleanup and recheck permission in the worker. |
| <nobr><code>CFO-REQ-09</code></nobr> | Preserve recovery and truthful completion guarantees. |
| <nobr><code>CFO-REQ-10</code></nobr> | Consolidate Viper/JEP ownership and demonstrate code reduction. |

## 2. Claim

Viper preserves exact artifact identity while reusing verified local bytes, queueing cloud publication and cleanup outside computation, and deleting only after the complete admitted workflow and current safety conditions permit it.

`storage.offload` defaults to `false` and controls retention independently of cloud publication destinations. Exact artifact overrides remain `inherit`, `keep` and `offload`, including complete bundle membership. Offload permits later removal; it does not demand deletion on every child return. Explicit keep is durable before resolution and returns only after the whole artifact is verified locally. Global keep retains produced/accessed payloads without downloading history.

## Analysis basis

The user accepted [the source-backed lifecycle review](../evidence/revisions/cloud-offload-queued-lifecycle/impact.md). It corrects two ordinary problems: foreground storage work and avoidable offload/download between related calls. Five independent source reviews additionally found eager cloud-client creation before local lookup and a second persistent Hub payload cache on ordinary restores. The proposed shared resolver fixes both. Native queue/owner/deletion connectors remain planned.

## 3. Models

| Model or owner | Role and boundary |
| --- | --- |
| Existing SnapshotInventory, RevisionManifest and shared validator | Immutable original reference, complete membership and file byte identities; remain unchanged. |
| StorageRegistry | One authority for inventories, original/cache bindings, custody and preferences. Current workspace bindings are consulted before an old embedded workspace address. |
| Existing LocalSource and SnapshotSources | Observed physical copies. Binding retirement alone does not authorize deletion. |
| PayloadLocks and WorkflowReaders | Process-held protection for admitted consumers, including gaps between child calls. Reader protection is internal and does not add retention subscriptions. |
| Existing PublicationJournal and SnapshotCopy | Upload intent, recovery and verified exact-copy proof; remain worker primitives rather than a second location/retention registry. |
| Proposed native outer owner | Explicitly admitted actions share one lifetime from authoring through final verification. Known queued inputs are protected before execution; child calls borrow and cannot close it. This transient execution ownership does not alter immutable provenance fields. |
| Proposed durable publication operation | Refers to original inventory identities and pinned targets. The existing work mechanism handles transfer, proof, retry and deferred cleanup; pending work durably protects sources even when no worker currently holds an OS lock. |
| Proposed publication status and final portable receipt | Pending/complete/failed publication is separate from scientific success. Final proof is complete only after collection closes and all required objects/receipts verify at all admitted targets. |

The exact native operation/status symbols remain PB06 design targets, not fabricated public APIs. A callback's return cannot reveal future independent Python calls. The top-level driver must admit the complete sequence; there is no prediction, TTL or implicit interpreter-wide retention service.

## 4. Execution

1. Establish one owner before native draft compilation, pointer freezing or batch scheduling. Forward the borrowed owner through nested calls, executor tasks and managed workers. Account for returned batch failures as well as raised exceptions.
2. Finish saving each output and relinquish further writes. Reuse the identity owner to hash it, register complete inventory and owned original paths, and durably admit publication before reporting acceptance. Admission persistence failure is immediate; a later worker-launch failure leaves recoverable work.
3. Queue plan, pointer, stage, attempt, terminal and benchmark records through the same managed path. This happens with offload either enabled or disabled. Do not reject an enrolled original local producer merely because cloud is the intended destination; establish genuine dependency enrollment and recoverability instead of removing reachability checks indiscriminately.
4. Continue computation while an independently surviving worker transfers originals, verifies cloud bytes and persists proof. Requests carry identities and source bindings, not checkpoint bytes or precomputed deletion permission. The runner does not own a transfer executor that joins on exit.
5. Before physical access, acquire the workflow's content protection. Resolve a verified registered original first, then the shared store payload, then genuinely missing bytes from verified backing. A resident hit does not create a provider or require credentials. Managed Hub payload restores stream into Viper's temporary file and shared store without another persistent Hub payload copy.
6. Retain needed copies across admitted training, inference, evaluation, diagnostics and benchmark actions. Preserve independent benchmark computation, per-execution verification and bundle-relative materialization. An individual stage/read/run return does not close a borrowed owner.
7. Join every admitted consumer and writer, complete local scientific verification, persist the actual workflow outcome, close collection with final inventory, and durably request cleanup. Return without waiting for remote publication or cleanup. Failed science never becomes eligible merely because its body returned normally.
8. The worker completes required publication and all-target final receipts. At an eligible cleanup attempt it obtains reader exclusion and rechecks current subscribers, pending source requirements, recoverable backing, ownership and exact physical identity in one short registry transaction. No network I/O runs under that transaction.
9. Keep, busy readers or pending proof defer removal without blocking computation or ready uploads. Reuse committed proof on later cleanup without reopening upload or repeating full remote verification. Preserve inventory, preferences, bindings and recovery records after deletion.

Existing APIs promising verified cloud references still wait. Explicit keep and a cold filesystem-path request still wait for verified local availability. Native queued results expose pending publication separately and never manufacture completed cloud references. Asynchronous verification retains its transfer costs; it moves those costs off the computation path. Source bytes and their host must survive pending work until verified publication or a verified durable handoff.

## 5. Persisted evidence

| Record | Purpose |
| --- | --- |
| [contracts/cloud-offload.toml](cloud-offload.toml) | Canonical requirements, verifiers and PairBlock contributions. |
| [checklists/cloud-offload.toml](../checklists/cloud-offload.toml) | Registration, phases and existing Viper/JEP repository/executable bindings. |
| `.viper/store/registry.sqlite3` | Complete inventory and current binding/custody/preference authority, independent of resident payloads. |
| Existing publication journal | Per-target exact upload intent, reconciliation and verified copy proof. |
| Proposed native operation and final receipt | Durable admission, source obligations, collection closure, deferred failure/status and complete final coverage; no duplicate binding authority. |
| [Current revision history](../evidence/revisions/cloud-offload-queued-lifecycle/README.md) | Exact previous declaration, actual revision impact, review reports and metadata-only validation. |

## 6. Verification

These declarations name observing checks; they do not claim those checks ran. New native checks remain planned until their implementation is authored and the user executes the gate.

| Rule | Executable condition |
| --- | --- |
| <nobr><code>CFO-VR-01</code></nobr> | Matching declared inventories preserve the original snapshot reference, reproduce its commit, and establish a one-to-one correspondence of unique paths and file identities. |
| <nobr><code>CFO-VR-02</code></nobr> | After registration and payload removal, reloading the registry returns the exact original inventory and complete membership. |
| <nobr><code>CFO-VR-03</code></nobr> | Distinct immutable member addresses with equal verified content share one ordinary managed payload while preserving references and bundle-relative materialization. |
| <nobr><code>CFO-VR-04</code></nobr> | Both override directions and inherit follow current configuration independently of publication destination. Global keep does not enumerate or download historical artifacts. |
| <nobr><code>CFO-VR-05</code></nobr> | One keep subscriber prevents losing the last local copy shared by otherwise offloadable artifacts. Repeated reads add no persistent subscriptions. |
| <nobr><code>CFO-VR-06</code></nobr> | Training, inference, evaluation and diagnostics reuse original references and enrolled input/restored copies through the shared resolver. |
| <nobr><code>CFO-VR-07</code></nobr> | Captured original member paths upload through the existing provider and shared exact-inventory check; full cloud-byte verification precedes published acknowledgment. |
| <nobr><code>CFO-VR-08</code></nobr> | Outer workflow completion queues cleanup and returns while publication and deletion may remain pending. Background cleanup alone evaluates all-target final proof, current policy, admitted consumers, reader exclusion and exact owned binding. |
| <nobr><code>CFO-VR-09</code></nobr> | Restart reuses inventory, preferences and existing proof to restore unchanged original references into the current store. Deferred publication failure is observable independently of successful science. |
| <nobr><code>CFO-VR-10</code></nobr> | Native and migrated JEP lifecycle callers use the same owners; ordinary duplicate cache and source-journal paths are retired with their successors. |
| <nobr><code>CFO-VR-11</code></nobr> | Durable admission precedes return and fails immediately if not committed. With retention enabled or disabled, native plan/pointer/stage/attempt/terminal/benchmark paths queue publication and permit progress during later computation without foreground provider calls. |
| <nobr><code>CFO-VR-12</code></nobr> | Managed readers protect the shared payload before resolution and across overlapping workflow lifetimes. Repeated reads share workflow protection; process exit releases ordinary locks. |
| <nobr><code>CFO-VR-13</code></nobr> | JEP callers use the native Viper queue, resolver and retention interfaces while preserving existing private-cloud and workload-identity configuration. |
| <nobr><code>CFO-VR-14</code></nobr> | Fresh fetchers and current-workspace bindings resolve resident originals before provider construction, credentials or network access; unchanged references survive original workspace loss when registered locally. |
| <nobr><code>CFO-VR-15</code></nobr> | An admitted producer/evaluation/benchmark sequence retains needed originals across gaps between child calls and protects queued inputs before their consumers start. Benchmarks still compute independent confirmation. |

Use the existing `.venv` and Pyrefly as the sole type checker. The deferred application gate remains type checking, focused CPU/mock tests, semantic documentation/schema checks, then non-mutating Ruff format/lint checks. No GPU provisioning or live-cloud spending is required for the first acceptance checks.

## 7. Propagation

| Surface | Required change |
| --- | --- |
| `_cloud.py` | Preserve shared identity validation and serialized formats. |
| `_storage_registry.py`, `storage.py` | Preserve inventory and current-root bindings; centralize original-first/lazy-provider/shared-streamed resolution and current retention authority. Native managed publication must admit original Paths rather than copy them into a new payload cache. |
| `_source.py`, `_verified_cache.py` | Share ordinary storage while retaining provider pools, per-execution proof reuse and bounded transfer isolation. |
| `authoring.py::_freeze_input`, `freeze_run_plan` | Enclose authoring in native ownership; enroll reachable managed local producers and queue pointer/plan records without foreground cloud calls. Preserve explicit low-level cloud-return contracts. |
| `execution/__init__.py`, `_run.py`, `_batch.py`, `_benchmark.py`, `_attempt.py` | Share one admitted root lifetime, protect queued work, keep benchmark recomputation and failure aggregation, and cover all final records before closure. |
| `_stage.py::StageWorkerContext`, `_metric.py::MetricWorkerContext` | Forward transient owner information across process boundaries without altering hash-bound scientific records. |
| `_publication.py`, `execution/results.py`, API/CLI adapters | Durably admit native evidence records; expose publication pending/complete/failed distinctly from science. Existing synchronous promises continue waiting. |
| `retention.py`, `_storage_locks.py`, materialization/restoration | Queue cleanup and route legacy/recursive managed deletion through the single fresh worker-side decision. Preserve exports, keep completion and exact-copy protection. |
| Journal/providers | Reuse direct Path publication and committed exact-copy proof inside the worker. Preserve bounded transfer staging and explicit legacy promotion. |
| JEP callers | Integrate the shared outer driver and replace duplicated queue/cleanup only in JEP-owned PB09 after native acceptance. |

## 8. Acceptance case

### Success

An admitted driver produces held-out data, then trains/evaluates against it and performs independent benchmark confirmation. Earlier child returns do not evict the data or candidate files. Fresh fetchers use registered originals with provider construction disabled; only absent payloads restore. Each completed original enters durable publication while later compute continues. The root joins consumers, verifies science, closes collection and queues cleanup, returning while transfer/proof may remain pending. A later worker verifies every target and rechecks current policy/readers/exact files before removal. Restart restores unchanged original references into the current store. An explicit keep subscriber retains one usable local shared copy.

### Rejection

Fail durable admission: return an immediate admission error, never accepted-but-lost work. Fail remote verification after successful science: retain original files and durable failed publication status without changing successful scientific records. A newer keep, unstarted admitted consumer, active reader, incomplete target or replaced file prevents stale cleanup. A returned failed batch also blocks successful workflow cleanup. Existing verified-cloud-return APIs and explicit keep never return pending work as fulfilled.

## 9. Implementation order

1. Preserve PB01's identity contribution and observing declarations unchanged.
2. Reconcile user-applied PB02 registry/listing fixes and current Generator convention with prepared successors.
3. Complete PB03 original-first/lazy-provider/shared-streamed resolver and prepared reader protection; deletion stays disabled.
4. Apply PB04 overrides, subscriber aggregation and complete-bundle keep.
5. Apply PB05 exact-original worker publication and recovery.
6. Author PB06's complete native owner/admission/status implementation, including authoring and every final record, before declaring it execution-ready.
7. Author PB07 queued cleanup and the single live deletion decision using real closure/proof. Preserve synchronous return guarantees.
8. Consolidate Viper ownership and validate ordinary end-to-end lifecycle and measured source/test reduction.
9. Migrate the existing JEP top-level driver and retire its duplicated publication/cleanup machinery in PB09.

## 10. Master checklist

The [workspace](../checklists/cloud-offload.toml) still places each requirement exactly once. [The human checklist](../checklists/cloud-offload.md) and [queue](../plans/cloud-offload/QUEUE.md) report guided progress honestly. No approval, accepted implementation or completed publication is inferred from planning.

## 11. Contract-owned PairBlocks

[The queue](../plans/cloud-offload/QUEUE.md) retains PB01–PB09 IDs and dependencies. PB01 has the existing actual-baseline plan; only its package binding is refreshed. PB02–PB05 contain complete proposed files, reconciled with user-applied fixes. PB06–PB09 remain target/check declarations with no fabricated baseline or placeholder implementation.

## 12. ContractTarget

| Requirement | PairBlock | Implementation owner or target | Observing check | Evidence |
| --- | --- | --- | --- | --- |
| <nobr><code>CFO-REQ-01</code></nobr> | PB01 | SnapshotInventory and exact-copy validator | CFO-VR-01 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-02</code></nobr> | PB02 | StorageRegistry and snapshot registration/listing | CFO-VR-02 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-03</code></nobr> | PB03, PB06 | LocalArtifactStore resolver, RunFetcher and native admission | CFO-VR-03, CFO-VR-14 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-04</code></nobr> | PB04 | StorageSettings and retention preference setter | CFO-VR-04 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-05</code></nobr> | PB03, PB04, PB07 | WorkflowReaders, registry policy and final deletion | CFO-VR-05, CFO-VR-12 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-06</code></nobr> | PB06 | Outer owner, authoring, batch/benchmark and worker propagation | CFO-VR-06, CFO-VR-15 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-07</code></nobr> | PB05, PB06 | Exact direct-copy journal and independently drained admission | CFO-VR-07, CFO-VR-11 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-08</code></nobr> | PB07 | Queued cleanup and single live deletion decision | CFO-VR-08 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-09</code></nobr> | PB05, PB06, PB07 | Recovery, publication status and completion boundaries | CFO-VR-09 | Proposed implementation/checks; no completion receipt. |
| <nobr><code>CFO-REQ-10</code></nobr> | PB08, PB09 | Viper consolidation and JEP-owned migration | CFO-VR-10, CFO-VR-13 | Proposed implementation/checks; no completion receipt. |
