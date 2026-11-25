# Queued cloud offload audit — simplicity and lifecycle consistency

Read-only source review. No active source/tests, shared plans, contract, or
manifests were edited. No tests, application commands, type checks or gates ran.
This report records the queued files as read before the controller's current
contract/metadata synchronization; authors may supersede them with corrections.

## Material findings

1. **PB03 constructs a cloud client before trying an available original/cache.**
   `plans/cloud-offload/CFO-PB-03/replace/src/viper/_source.py:151`,
   `:175–180`, and `:195–196` call `_cloud_service` before the ordinary resolver.
   `src/viper/cloud.py:51` immediately constructs its provider;
   `src/viper/gcs.py:220` constructs `storage.Client()`. A previously downloaded
   artifact can therefore fail credential discovery before returning valid local
   bytes. The existing reader checked its persistent cache before constructing
   the cloud service. This is an ordinary offline/local-reuse regression, not a
   speculative failure. Pass a lazy provider lookup through the single resolver
   and instantiate it only on the metadata/download path that actually needs
   cloud access. Preserve pooling and task-cache configuration; do not add a
   second resolve attempt or swallow an original's integrity error. The resolver
   author has been notified. PB04's cumulative storage replacement must inherit
   the fix as well.

2. **The contract needs the accepted admission boundary stated explicitly.**
   `contracts/cloud-offload.toml:64` states one internal lifetime but does not yet
   distinguish admitted pending actions from separate later Python calls.
   `plans/cloud-offload/CFO-PB-06/README.md:26` likewise does not specify queued
   input protection at admission, returned batch-failure handling, or independent
   benchmark computation. The actual seams are:

   - `_batch.py:73–82`: all submitted plans are available before executor entry;
     reserve known input payloads there without fetching their bytes merely to
     reserve them. Forward the same owner explicitly through `executor.submit`
     at `:95–101`; ordinary ContextVars do not propagate themselves to threads.
   - `_batch.py:118`: execution failures become returned outcomes. Determine root
     success from these outcomes, not solely absence of an escaping exception.
   - `_attempt.py:695`: a completed snapshot can enter publication before later
     metrics at `:718`. Do not release its producer-owned bytes at this seam.
   - `_attempt.py:826–846` and `:995`: terminal verification/indexing and run-lock
     release remain within the owner; nested attempts do not close the root.
   - `_benchmark.py:132`, `:166`, and `:285`: candidate verification, independent
     confirmation and result publication share one benchmark owner. The producer
     run may have occurred before this owner existed.
   - `inputs.py:108–113`: FutureInputRef currently refers to a prior stage in the
     same run. Existing run_many is not a cross-run future-dependency scheduler.

   Smallest remedy: extend REQ06/VR06 and PB06 with an explicit admitted outer
   operation, holds for queued known inputs and newly sealed outputs, native
   child forwarding, and an observing producer/evaluation/benchmark sequence.
   Separate later calls require a declared common owner or an existing keep
   preference. Do not infer arbitrary Python main/interpreter lifetime. Preserve
   `_attempt.py:511–515` benchmark-confirmation reuse exclusion and the independent
   comparisons at `_benchmark.py:202–226`; cache reuse must not replace the
   independent scientific computation.

3. **Queue cleanup instead of turning root closure into a cloud wait.**
   `contracts/cloud-offload.toml:78` and
   `plans/cloud-offload/CFO-PB-07/README.md:19` describe correct eligibility
   conditions but do not yet require nonblocking cleanup admission. Add that
   successful root closure durably queues cleanup after closing collection and
   releasing its managed readers; the worker waits for actual all-target proof
   and rechecks current policy, readers, ownership and physical identity before
   removal. Job identity must not capture a mutable offload boolean or grant
   future deletion through a stale physical path. Reuse the publication worker's
   durable operation/progress mechanism; no separate cleanup broker is needed.
   Explicit APIs promising verified cloud references retain their waiting path.

4. **Progress metadata is stale relative to the user's applied edits.**
   `plans/cloud-offload/QUEUE.md:3–17` still says no blocks were applied, begins
   again at PB01 and says no code was installed. The aggregate manifest and
   PB01–PB03 proposals retain `authored_not_applied_gates_not_run`. Reconcile
   application state separately from unexecuted gates; do not turn user-applied
   code into a pass claim. Rebase successor whole-file payloads to actual guided
   bytes, including the accepted Generator annotations, before giving them to
   the user. Preserve the original PB01 requirement/verifier/contribution itself.

## Reviewed consistency

- The original REQ01/VR01/PB01 declaration at contract lines 5–30 remains intact.
- PB02 persists full immutable inventory independently of resident payloads;
  binding retirement does not unlink files. Legacy admission now sorts canonical
  member strings and uses the shared SnapshotInventory validator.
- PB03 orders registered original aliases before cache aliases and reports a
  selected original's integrity error. It still explicitly defers original-local
  cold backing lookup to PB06. The eager caller-side cloud construction above is
  the remaining original-first defect observed in this audit.
- PB04 has one exact artifact/member override, subscriber votes derived from
  membership and current defaults, additive tables under the same writer, and
  explicit keep through the resolver. Legacy eviction remains an explicitly
  deferred PB07 connector: its current `retention.py:220–223` still bypasses the
  new authority, so whole-lifecycle keep must not be claimed before routing it.
- PB05's exact guard precedes provider intent/publication; pending GCS/HF retry
  reconciles the same immutable request; committed proof reuse does not read
  evicted originals. It is correctly described as a synchronous worker primitive,
  not durable admission, workflow closure or eviction authorization.
- PB08/PB09 correctly leave end-to-end acceptance and separate Viper/JEP code
  reduction unproven. No replacement scheduler, persistent reader counter or
  second retention registry is needed to address these findings.

No runtime correctness or completed lifecycle acceptance is claimed.
