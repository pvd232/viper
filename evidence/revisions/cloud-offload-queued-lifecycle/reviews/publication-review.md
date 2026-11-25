# PB05 source audit for queued publication and cleanup

PB05 needs no behavioral change for the accepted queue semantics. The complete
journal, Hugging Face provider and focused test module in this directory are
unchanged copies of the last PB05 proposal. They are not applied to the active
worktree. No Python, application, test, formatter or type-checker command ran.

The journal/helper is synchronous physical work executed by an independent
worker. Keeping that implementation synchronous does not make native workflow
admission wait. Queue admission and workflow ownership belong to PB06/PB07,
which remain planned until complete implementations and real interfaces exist.

## Guarantees retained by PB05

- Exact original membership and byte identities are checked before saving an
  upload intent, initializing a provider repository or starting publication.
- Original references, snapshot membership and serialized run bytes remain
  unchanged; the primitive does not discover or rewrite a run graph.
- Native GCS resumes the same immutable create-only publication. HF reconciles
  from its saved head before retrying a definitively absent commit; unresolved
  history stays unresolved.
- Full remote size/SHA-256 verification precedes saving `published`. Committed
  proof can be reused without opening evicted original sources or downloading
  payloads again; address/manifest checks on that path still perform network I/O
  and therefore belong in the worker.
- The initial HF head lookup initializes the repository idempotently first.
- Default legacy promotion behavior and explicit cloud-reference return waits
  remain intact. Provider/session isolation and stream-mode defaults are not
  changed.
- The primitive owns no retention settings, local source registry, admission
  queue, final workflow receipt or cleanup authorization. Mutable source paths
  are runtime inputs, not part of saved copy identity.

## Required native connection targets

These are source observations, not authored implementations:

```text
execution/__init__.py:187 run
  Draft freeze occurs at :212 before private _run.run; the outer owner must
  include authoring, or cloud plan publication remains on the caller path.

authoring.py:1706 freeze_run_plan
  Local immutable plan is saved at :1728, then cloud files are synchronously
  published at :1734. Managed admission must use the established original refs
  and preserve required compiled plan sources without waiting for cloud.

authoring.py:968 _freeze_input
  :995 rejects a local producer merely because the destination is cloud.
  :1019 publishes its pointer. A known managed producer requires real inventory,
  backing/dependency enrollment and source protection; do not simply remove the
  reachability check or rewrite the producer graph.

storage.py:499 ViperCloudSnapshotPublisher
storage.py:562 publish_resolved_files
  Managed native writes need durable registration/admission for both completed
  stage snapshots and standalone metadata. Low-level explicit cloud APIs retain
  synchronous return semantics.

execution/_attempt.py
  :394 retry's prior terminal reference
  :604/:616 invocation receipts, including failed stage receipts
  :695 stage snapshot before metrics at :718
  :766/:791 attempt files and attempt document
  :807 prior attempt documents
  :830 terminal run before RunResult at :847
  :896/:926/:942/:965 corresponding failed-attempt/final-run publication
  All applicable records must use the same managed admission path, not leave
  synchronous metadata uploads after moving only the checkpoint transfer.

execution/_publication.py:85 publish_attempt_files
execution/_publication.py:132 write_attempt_document
execution/_publication.py:158 publish_invocation_receipt
  Persist local control/evidence before asynchronous cloud work, keeping their
  original refs and byte identities.

execution/_run.py:12 run
execution/_batch.py:54 run_many
execution/_benchmark.py:95 benchmark
  One native owner covers authoring, nested execution and final records. Batch
  freezes drafts at :76 and submits compute at :95. Explicitly pass the borrowed
  operation through threads rather than assume ContextVars propagate. Join only
  managed computation/readers; do not join an upload/cleanup executor on return.

execution/_benchmark.py:249/:285
  Candidate and final result publication occur after confirmation, so the nested
  confirmation's return cannot close the outer collection.

execution/_stage.py:89/:464 StageWorkerContext
execution/_metric.py:56/:149 MetricWorkerContext
  Propagate transient operation ownership to managed workers without changing
  hash-bound provenance records merely to carry mutable execution state.

execution/results.py:17 RunResult and API/CLI result adapters
  Report publication pending/completed/failed separately from scientific status.
  Returning an original local ref with pending publication must not fabricate a
  verified provider-specific cloud ref.

retention.py, _storage_registry.py, _storage_locks.py, _materialization.py
  Use the same queue for deferred cleanup requests. Worker-side eligibility
  consumes actual successful closed workflow evidence, all required final
  publication proof, current policy, source protection and reader exclusion.
```

Current explicit promotion still waits through `subprocess.run` at
`execution/__init__.py:121`; this is an explicit cloud-return API. Its process
wrapper is not native durable admission and should not be relabeled as such.
The current native Viper checkout has no durable publication supervisor.
JEP's known independent drainer and atomic record pattern is a concrete reuse
candidate for PB06, not an already integrated native implementation.

`journals.publish_completed_journal()` currently explicitly chooses local
storage (`journals.py:271`). This audit does not incorrectly classify optional
note-encoding computation as an existing cloud upload or add it to PB05.

## Minimal acceptance additions for PB06/PB07

The following are proposed integration checks, not placeholder test bodies:

1. `test_native_authoring_and_final_records_admit_without_cloud_io`
   With cloud destinations configured, freeze a draft using a registered local
   producer, then run stage/metrics/confirmation/final publication. Block the
   remote provider and prove all these caller-side paths register durable work
   and use original references. Offload false still queues publication; it only
   changes retention. Reject unenrolled/unrecoverable producer dependencies.
2. `test_background_work_survives_runner_exit_without_join`
   A deliberately blocked upload does not delay native computation completion
   or runner exit. The independent worker later completes verification and final
   receipts and performs already admitted eligible cleanup without another
   native workflow being needed to drain it.
3. `test_pending_publication_protects_sources_between_worker_attempts`
   Failed/interrupted transfer and worker restart retain a durable source
   protection link even while no OS reader lock is held. A queued cleanup cannot
   remove those sources before the required proof or verified handoff exists.
4. `test_queued_cleanup_does_not_block_ready_uploads`
   Admit a cleanup whose publication/closure dependencies are pending, then a
   ready upload. The worker processes ready work; it does not block a single
   drainer waiting for a dependency queued behind that cleanup.
5. `test_background_cloud_failure_preserves_scientific_success`
   Let computation finish successfully, then fail publication in the worker.
   Preserve its successful immutable run record, retain sources and publish a
   durable failed/pending publication status with real diagnostics. Native
   compute exceptions are likewise not replaced by later upload exceptions.
6. `test_cleanup_uses_completed_proof_without_republishing`
   Change current retention after completed publication. The same queue evaluates
   cleanup from the existing final proof and current registry state, without a
   new upload, changed publication identity or modified final receipt. Keeping
   files is a normal retention outcome rather than publication failure.

Existing PB05 direct-helper tests already observe exact membership rejection,
remote byte verification before acknowledgment, GCS/HF restart behavior,
source-location changes under one intent, and proof reuse after eviction. Do
not duplicate those checks to imply the missing process/admission layer exists.
Explicit cloud-return calls must retain their wait; cold path retrieval still
must finish verified materialization before returning a usable path.

## State and ownership constraints

Queueable transfer, proof creation, final receipt and cleanup happen after local
admission. Closed collection and publication proof gate worker-side deletion;
they do not impose a runner wait. Source protection survives retry and worker
absence until its durable requirement is satisfied. The global registry owns
current paths, custody, preferences and readers; jobs refer to its identities.

Keep operation identity stable while capture grows. Pin publication targets for
that operation and freeze its complete logical inventory on closure. Current
retention and physical paths cannot alter that identity or prior receipts.
Release only short registry transactions before hashing/transfer/verification.
Do not add a second queue, registry, retry framework, location authority or
trusted-success boolean in PB05 to simulate the still-planned native layer.
