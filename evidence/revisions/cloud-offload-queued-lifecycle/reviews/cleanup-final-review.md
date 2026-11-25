# Cleanup/lifetime cross-review of staged proposal

Verdict: **APPROVE_SCOPED** for the staged contract, planned PB06/PB07 ownership
and cleanup requirements, and prepared PB03/PB04 source foundations. This is
source review of proposed work, not execution evidence or completion approval
for a native queue or automatic deletion.

Reviewed base: `/tmp/viper-offload-queued-revision-20261122/staged`.
No production edits, imports, tests, gate commands or application actions ran.

## Findings

- Contract REQ05/06 now protects admitted queued inputs and every later admitted
  consumer, including gaps between calls. It separates persistent artifact
  subscriptions from process-held readers and explicitly borrows one outer
  owner across nested actions and worker boundaries (`contracts/cloud-offload.toml`,
  lines 57 and 64).
- REQ07 supplies durable pending-source protection across process exit and
  retries; ordinary reader locks are not presented as sufficient recovery
  protection (`contracts/cloud-offload.toml`, line 71; PB06 README lines 30–36).
- REQ08 queues reconsideration rather than fixed deletion authority. Current
  policy and exact owned binding are rechecked under exclusion and one short
  registry transaction, while transfer/verification happens outside that
  transaction. Pending proof or readers cannot monopolize the worker ahead of
  ready uploads (`contracts/cloud-offload.toml`, line 78; PB07 README lines 22–26).
- REQ09 preserves cold-path and complete-keep waiting guarantees, separate
  publication status, unchanged scientific bytes and reuse of completed proof
  (`contracts/cloud-offload.toml`, line 85).
- The staged PB04 keep wrapper selects the active workspace registry, persists
  keep first and resolves all original members before successful return
  (`plans/cloud-offload/CFO-PB-04/replace/src/viper/retention.py`, lines 241–255).
  Original reference addresses are preserved; no old workspace is opened by
  the wrapper. The registry permission query remains the sole current vote
  calculation and explicitly rejects queueing its result as deletion permission
  (`.../_storage_registry.py`, lines 510–560).
- PB03 RunFetcher looks in the active registry before old-workspace fallback
  (`.../CFO-PB-03/replace/src/viper/_source.py`, lines 122–140). The ordinary
  resolver checks existing original/cache bytes before constructing cloud
  clients and has no eviction-on-read path (`.../storage.py`, lines 386–463).
- Prepared lock ownership is process-held and releases on workflow-owner exit;
  its docs require admission closure and joining all admitted consumers before
  close (`.../CFO-PB-03/add/src/viper/_storage_locks.py`, lines 64–110). No dormant
  workflow-owner parameters have been added to RunFetcher or storage.

## Scope and remaining integration stop conditions

No current source-level material blocker found for this proposal's stated
scope. PB06 and PB07 correctly remain planned and explicitly not execution-ready.

Before enabling deletion, the real outer owner must acquire protection before
both cold resolution and execution-local remembered-path use; child action
completion cannot close it. Pending publications must protect their needed
sources even when no reader/worker process exists. Cleanup must consume actual
successful closure and all-target final receipt proof, use fresh registry policy
and exact-file checks, and route legacy eviction and managed recursive removal
through the same decision. These are planned integration obligations, not
implemented behavior claimed by this approval.
