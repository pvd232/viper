# Cloud Offload

**Owner decision, 2026-11-25:** The user accepted the measured code-size increase and authorized the PyPI release. The net-reduction objective is waived as a release gate; the measured counts and historical verifier findings remain intact. [Approval record](../evidence/revisions/cloud-offload-size-override-20261125.json).

## Claim

Viper preserves exact artifact identity while reusing verified local bytes, queueing cloud publication and cleanup outside computation, and deleting only after the complete admitted workflow and current safety conditions permit it.

The [canonical package](cloud-offload.toml) owns the unchanged requirements and acceptance conditions. The [workspace](../checklists/cloud-offload.toml) owns repository bindings and requirement placement. The [binding amendment](../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) preserves the previous declaration and records the correction from planned test names to actual observing tests.

## Current status

Native publication, resolution, recovery and cleanup are implemented. The final fast gate passes at `df10a3e`: Ruff checks and formatting, Pyrefly with zero errors, and 805 tests plus 11 subtests, with 4 skips. All 227 selected integration cases pass across retained bounded runs, including all 27 README cases; [the coverage record](../evidence/cloud-offload-integration-20261125/coverage.json) maps each selected case to retained evidence. All seven hosted Viper CI jobs passed at runtime commit `df10a3e`, including integration and Python 3.11–3.13 compatibility. No formal acceptance or completion receipt is asserted.

The user applied PB01–PB05 foundations at checkpoints `7e7d981` and `1345473`, then authorized autonomous completion. Current implementation files in Git are authoritative. Obsolete PB02–PB07 source, test and diff mirrors have been retired; [their exact inventory](../evidence/revisions/cloud-offload-observer-bindings-20261125/retired-mirrors.json) preserves the boundary and raw hashes.

**The original CFO-REQ-10 net-reduction condition is unmet; the owner has accepted this size tradeoff.** Maintained Viper source and tests have grown enough that the current combined Viper/JEP candidate does not meet the required net reduction. The claim is unchanged. Removing obsolete planning mirrors does not count as maintained source/test reduction. The [source-hashed count report](../evidence/cloud-offload-implementation-20261125/review-10/README.md) records +4,986 runtime lines and +5,777 test lines combined, or +10,763 maintained lines, against the original baselines. It counts the frozen Viper source at `df10a3e`; the earlier +9,937 snapshot is historical.

Native integration is committed at `1b8ed60`, its recovery repair at `c869ea6`, cleanup at `95a2420`, consolidation at `59c381d`, Git source verification at `c83af457`, and its final inventory repair at `df10a3e`. JEP migration is committed at `e2285b8`; `d44073e` pins the final Viper commit. [Viper PR 24](https://github.com/pvd232/viper/pull/24) and [JEP PR 26](https://github.com/pvd232/JEP/pull/26) are drafts. The original baselines remain Viper `f659faf` and JEP `c2f9716`.

## Storage policy and identity

`storage.offload` defaults to `false`. Cloud settings select publication targets independently. Each exact registered artifact version, including its whole bundle, has one override: `inherit`, `keep` or `offload`. Inherit follows the current global setting. Explicit keep is saved before resolution and returns only after every member is verified locally. A global keep default retains produced or accessed files without downloading historical artifacts.

Original reference fields, file hashes, snapshot membership and scientific run records stay unchanged. The local registry stores the complete inventory and current file locations separately from resident bytes. A reference's `workspace` is its saved original address. The resolver consults the current workspace registry before trying that address, so a registered copy can remain usable after relocation. Retiring a location means Viper stops using that record. It grants no permission to delete an external file.

A cached file with the expected SHA-256 and size does not by itself prove that the file belongs to a named Git commit and path. The private `GitFileProof` keeps the original `ResolvedGitFileRef`, the raw commit object, and each directory object along that path. Viper checks their Git object hashes through to the file object, then checks the payload size and SHA-256. Both 40-character SHA-1 and 64-character SHA-256 Git object IDs are supported. A stale plan cannot authorize different cached code by changing only its declared payload hash.

The proof is additional verification metadata. It does not change public reference fields, scientific records, complete snapshot membership, or the publication receipt format. Existing published snapshots continue to use their original inventories.

## Implementation owners

| Owner | Responsibility |
| --- | --- |
| [`SnapshotInventory` and shared validators](../src/viper/_cloud.py) | Check the complete original file list and exact copied identities. |
| [`StorageRegistry`](../src/viper/_storage_registry.py) | Store inventories, current locations, artifact preferences, shared subscribers and source obligations; index immutable, hash-checked cloud and Git proofs. |
| [`LocalArtifactStore`](../src/viper/storage.py) | Find a verified original, reuse the shared content cache, or restore genuinely missing bytes. |
| [`RunFetcher`](../src/viper/_source.py) | Reuse checks during one execution while sharing ordinary storage across executions; require Git commit/path membership for cached source code. |
| [`GitFileProof`](../src/viper/_git_proof.py) | Verify the pinned Git commit, directories and file bytes, independently of the original repository. |
| [`verify_resolved_file_bytes`](../src/viper/_verified_cache.py) | Check the declared byte count and SHA-256 through one shared byte validator. Domain validators retain their own record checks. |
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

## Source restoration

Before closing the admitted workflow, Viper groups used Git source files with their proofs and queues them as ordinary auxiliary local snapshots through the existing publisher. Explicit run enrollment uses the same transport. The proof's logical member path is `.viper/git-proofs/<address>.json`; it is a member of that auxiliary snapshot, not a new reference kind or a second publication queue.

Receipt import verifies the ordinary copy, checks each proof against its source bytes, and saves the Git-address proof in the same registry. Reimporting a known copy can restore its missing proof index without downloading payloads again. Later source access can restore missing bytes from verified cloud backing and recheck membership without the original Git repository. A cloud copy with matching bytes but no Git membership proof cannot establish a Git address. Corrupt bytes from an available original Git source fail rather than being hidden by a cloud fallback.

## Persisted records

| Record | Writer and purpose |
| --- | --- |
| `.viper/store/registry.sqlite3` | Registry-owned inventories, current locations, preferences, subscribers and source protection. Existing `verified_files` rows also index hash-checked Git proofs with `git:` keys; these are excluded from cloud-file backing lookup. |
| `.viper/store/proofs/git/<address>.json` | Immutable Git membership metadata indexed by the registry. A proof is not a cloud backing or retention preference. |
| `.viper/publications/<id>/operation.json` | Workflow admission, closure, scientific outcome and final publication coverage. |
| `.viper/publications/<id>/jobs/<snapshot-key>.json` | Durable per-snapshot upload status and retry state. Current location and retention authority remain in the registry. |
| Per-target publication journal | Expected bytes, interrupted transfer recovery and verified destination copies. |
| `.viper/publications/<id>/receipt.json` | Closed portable publication evidence; existing references remain unchanged. |

## Observing examples

The repository-derived success case `test_snapshot_copies_complete_while_the_workflow_remains_open` queues `weights.bin`, drains its snapshot while collection remains open, rejects a final-completion wait during that open scope, then checks final publication after closure. Its provider is controlled in-memory. It establishes queue ordering and proof checks, not a live cloud deployment.

The rejection case `test_captured_sources_are_checked_before_intent_or_provider_io` changes bytes or removes/adds a declared member. It requires `RunPromotionError` matching `inventory`, an empty saved-copy map, no intent file and no provider upload, seal or download calls. `test_remote_hash_mismatch_leaves_captured_intent_unpublished` separately checks that corrupted remote bytes preserve an unpublished intent and the original local source.

The source-recovery case `test_workflow_publishes_git_proof_and_restores_after_source_eviction` uses the normal workflow queue, waits through worker drains, evicts source payloads, deletes the original repository, imports a receipt into a fresh workspace, and reads the same Git reference while all Git access is forbidden. It also checks that repeated import needs no extra downloads. The controlled provider is in-memory. `test_git_proof_verifies_offline_after_json_roundtrip` additionally checks both supported Git object formats. Rejection cases cover changed commit or directory objects, another path, unrelated bytes with a matching declared SHA, a stale compiled plan, and missing Git membership proof.

## Verification and remaining acceptance

The [canonical verifier bindings](cloud-offload.toml) name actual tests. The [static binding audit](../evidence/revisions/cloud-offload-observer-bindings-20261125/binding-audit.json) resolves each declared name against an active test definition. This audit parses TOML and Python definitions. It is not an application test gate or a production protocol-loader result.

The current production `ContractPackage` parser is unavailable in this checkout/environment. No parser clone, install, guessed canonical package digest or formal lifecycle record is created. Raw file hashes and exact before-images are retained. Historical plan bindings remain historical until a real protocol operation replaces them.

The retained [final fast-gate log](../evidence/cloud-offload-implementation-20261125/validation/make-check.log) records Ruff success, 173 formatted files, zero Pyrefly errors, and 805 passing tests plus 11 subtests in 499.66 seconds, with 4 skips and 239 deselections. [The repaired fresh-workspace run](../evidence/cloud-offload-integration-20261125/git-fresh-producer.log) passes in 125.68 seconds. JEP `d44073e` has [47 passing CPU tests plus 4 subtests](../evidence/cloud-offload-implementation-20261125/validation/jep-tests.log) in 2.80 seconds and [zero Pyrefly errors](../evidence/cloud-offload-implementation-20261125/validation/jep-pyrefly.log). Ten independent initial reviews and subsequent source-repair rechecks are recorded separately; all 227 selected integration cases pass across retained bounded runs; all seven hosted Viper CI jobs passed at runtime commit `df10a3e`. The measured increase remains recorded. The owner exception accepts this size tradeoff without claiming a passing net-reduction check.

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
| CFO-REQ-10 | PB08, PB09 | Shared storage ownership; measured size increase accepted by the owner. |
