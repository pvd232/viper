# Cloud Offload

## Claim

Viper preserves exact artifact identity while reusing verified local bytes, queueing cloud publication and cleanup outside computation, and deleting only after the complete admitted workflow and current safety conditions permit it.

The [canonical package](cloud-offload.toml) owns the unchanged requirements and acceptance conditions. The [workspace](../checklists/cloud-offload.toml) owns repository bindings and requirement placement. The [binding amendment](../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) preserves the previous declaration and records the correction from planned test names to actual observing tests.

## Current status

Native publication, resolution, recovery and cleanup are implemented in the active candidate. Final broad validation and independent repair rechecks are still in progress. No formal acceptance or completion receipt is asserted.

The user applied PB01–PB05 foundations at checkpoints `7e7d981` and `1345473`, then authorized autonomous completion. Current implementation files in Git are authoritative. Obsolete PB02–PB07 source, test and diff mirrors have been retired; [their exact inventory](../evidence/revisions/cloud-offload-observer-bindings-20261125/retired-mirrors.json) preserves the boundary and raw hashes.

**CFO-REQ-10 remains OPEN and unaccepted.** Maintained Viper source and tests have grown enough that the current combined Viper/JEP candidate does not meet the required net reduction. The claim is unchanged. Removing obsolete planning mirrors does not count as maintained source/test reduction. The [final count snapshot](../evidence/cloud-offload-implementation-20261125/review-10/README.md) records +4,602 runtime lines and +5,335 test lines combined, or +9,937 maintained lines.

Native integration is committed at `1b8ed60`, its recovery repair at `c869ea6`, and cleanup at `95a2420`. Final broad and integration validation remain pending.

## Storage policy and identity

`storage.offload` defaults to `false`. Cloud settings select publication targets independently. Each exact registered artifact version, including its whole bundle, has one override: `inherit`, `keep` or `offload`. Inherit follows the current global setting. Explicit keep is saved before resolution and returns only after every member is verified locally. A global keep default retains produced or accessed files without downloading historical artifacts.

Original reference fields, file hashes, snapshot membership and scientific run records stay unchanged. The local registry stores the complete inventory and current file locations separately from resident bytes. A reference's `workspace` is its saved original address. The resolver consults the current workspace registry before trying that address, so a registered copy can remain usable after relocation. Retiring a location means Viper stops using that record. It grants no permission to delete an external file.

## Implementation owners

| Owner | Responsibility |
| --- | --- |
| [`SnapshotInventory` and shared validators](../src/viper/_cloud.py) | Check the complete original file list and exact copied identities. |
| [`StorageRegistry`](../src/viper/_storage_registry.py) | Store inventories, current locations, artifact preferences, shared subscribers and source obligations. |
| [`LocalArtifactStore`](../src/viper/storage.py) | Find a verified original, reuse the shared content cache, or restore genuinely missing bytes. |
| [`RunFetcher`](../src/viper/_source.py) | Reuse checks during one execution while sharing ordinary storage across executions. |
| [`PublicationSession`, `Operation` and `PublicationJob`](../src/viper/_offload.py) | Own the admitted workflow, persist upload admission, retain pending sources and record collection closure. |
| [`PayloadLocks` and `WorkflowReaders`](../src/viper/_storage_locks.py) | Protect files before access and through managed consumer lifetimes. |
| [`PublicationJournal`](../src/viper/execution/_promotion_journal.py) and providers | Upload original paths, verify cloud bytes and retain retry/proof records. |
| [`PublicationReceipt`](../src/viper/cloud.py) | Carry completed exact-copy proof and inventories for restoration on another host. |
| [`retention.py`](../src/viper/retention.py) and the [same publication worker](../src/viper/execution/_offload_worker.py) | Recheck current permission, proof, readers and the exact owned file before removal in the publication worker. |
| [`serialization.py`](../src/viper/serialization.py) | Write complete control files atomically and synchronize their file and directory entries. |

The ordinary cache lives under `.viper/store/objects`. Bounded transfer staging remains task-owned. Ordinary reads no longer need a separate persistent `.viper/cache/verified-objects` owner. Hash checks and cloud transfers stay outside short registry transactions.

## Execution and completion

A native entry point establishes the workflow before authoring or execution. Related independent calls can share the explicit `workflow(...)` scope in [storage.py](../src/viper/storage.py). Nested calls borrow that owner. Batch executor threads receive it explicitly. Queued known inputs remain protected before their consumers start. Separate future Python calls are not predicted.

The producer finishes writing before its output is hashed and admitted. Each stage attempt writes its own physical files, while logical output addresses stay unchanged. Child stage and metric processes acquire their own read locks. Parent and child paths therefore remain protected across computation and verification. Benchmark confirmation still executes independently.

Admission persists the original inventory and durable work before reporting acceptance. A failed admission surfaces immediately. A failed worker launch leaves recoverable work. Publication is queued with offload enabled or disabled. The detached worker performs transfer, remote verification, final receipts and retry. Pending source obligations persist while no worker is running and between attempts.

The resolver uses a valid local original first. A cold filesystem-path request waits for verified downloaded bytes. Existing APIs promising a completed cloud reference still wait. `RunResult.publication_path`, `publication_status(...)`, `publication_copies(...)`, `publication_receipt(...)` and `retry_publication(...)` expose publication separately from scientific results. A pending job is never presented as a verified cloud reference.

Successful outer closure records the real scientific outcome, closes collection and requests cleanup. Cleanup may remove an owned local copy only after all required data and final receipts verify at every admitted target, current subscribers permit offload, no readers or pending source obligations remain, and the observed physical file still matches. Failed science or unresolved publication retains its sources. Keep, busy readers and incomplete proof defer cleanup. Later cleanup reuses completed proof without uploading again. Legacy and recursive managed deletion must use this same decision.

## Persisted records

| Record | Writer and purpose |
| --- | --- |
| `.viper/store/registry.sqlite3` | Registry-owned inventories, current locations, preferences, subscribers and source protection. |
| `.viper/publications/<id>/operation.json` | Workflow admission, closure, scientific outcome and final publication coverage. |
| `.viper/publications/<id>/jobs/<snapshot-key>.json` | Durable per-snapshot upload status and retry state. Current location and retention authority remain in the registry. |
| Per-target publication journal | Expected bytes, interrupted transfer recovery and verified destination copies. |
| `.viper/publications/<id>/receipt.json` | Closed portable publication evidence; existing references remain unchanged. |

## Observing examples

The repository-derived success case `test_snapshot_copies_complete_while_the_workflow_remains_open` queues `weights.bin`, drains its snapshot while collection remains open, rejects a final-completion wait during that open scope, then checks final publication after closure. Its provider is controlled in-memory. It establishes queue ordering and proof checks, not a live cloud deployment.

The rejection case `test_captured_sources_are_checked_before_intent_or_provider_io` changes bytes or removes/adds a declared member. It requires `RunPromotionError` matching `inventory`, an empty saved-copy map, no intent file and no provider upload, seal or download calls. `test_remote_hash_mismatch_leaves_captured_intent_unpublished` separately checks that corrupted remote bytes preserve an unpublished intent and the original local source.

## Verification and remaining acceptance

The [canonical verifier bindings](cloud-offload.toml) name actual tests. The [static binding audit](../evidence/revisions/cloud-offload-observer-bindings-20261125/binding-audit.json) resolves each declared name against an active test definition. This audit parses TOML and Python definitions. It is not an application test gate or a production protocol-loader result.

The current production `ContractPackage` parser is unavailable in this checkout/environment. No parser clone, install, guessed canonical package digest or formal lifecycle record is created. Raw file hashes and exact before-images are retained. Historical plan bindings remain historical until a real protocol operation replaces them.

Use the project environment and Pyrefly for the application gate. Focused and broad command results, ten independent reviews and their repair rechecks must be retained against the final candidate. Requirement 10 cannot close until a real separate-and-combined maintained source/test report demonstrates the promised reduction while preserving guarantees and meaningful checks.

| Requirement | Owning blocks | Current implementation owner |
| --- | --- | --- |
| CFO-REQ-01 | PB01 | Original inventory and exact-copy validation. |
| CFO-REQ-02 | PB02 | Durable registry and complete listing. |
| CFO-REQ-03 | PB03, PB06 | Shared local-first resolver and native admission. |
| CFO-REQ-04 | PB04 | Artifact overrides and complete keep. |
| CFO-REQ-05 | PB03, PB04, PB07 | Readers, subscriber unanimity and final deletion checks. |
| CFO-REQ-06 | PB06 | Native outer owner, batch and child propagation. |
| CFO-REQ-07 | PB05, PB06 | Captured-original publication and durable background work. |
| CFO-REQ-08 | PB07 | Same-worker cleanup after successful closure. |
| CFO-REQ-09 | PB05, PB06, PB07 | Recovery, portable copies and honest completion. |
| CFO-REQ-10 | PB08, PB09 | Shared Viper/JEP ownership and unmet net reduction. |
